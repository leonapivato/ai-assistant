"""What the observer reads around a leaving episode, and how it renders it (ADR-0329 §8).

For a leaving episode the observer reads (§8:1): the episode's whole record; the
episodes still in the window that occurred after it; for each story the episode's
activation belongs to, its summary and its most recent episodes, up to a bound; and past
episodes, their candidates and memories related to the episode, found by relevance
search over the memory store, up to a bound. This module gathers them
(:class:`EpisodeReader`) and renders them for the scout (:meth:`Reading.payload`).

**Parts, not fields** (§8:6). An episode is rendered by the parts a support may point
at (ADR-0328 §4's part table, §9:6): the input or each message it took in, each round's
message, each evidence item of its digests, and, for a candidate recorded under an
approval, the user's yes to the wording it showed. Outside input and digested evidence
are rendered, each marked outside where it is; an episode's ``content``, its notes, its
understanding and every other field are not. Each part carries a label (``P1``, ``P2``,
...) the scout names it by, and code maps the label back to the part: no model writes
a part's address.

**Code-owned facts** (§9:5). Each part is read with what code sets on a support that
points at it: its origin, from the part and the episode's record (ADR-0328 §4:2-§4:4),
and its ``when`` (§4:12). A round's message takes its outside origin where the
activation's record says it had read outside content (§4:3), as authorizing decides it
(:func:`~ai_assistant.orchestration.authorizer.read_outside_content`), over the stored
record alone. Every span reaches the model as quoted source data, attributed from the
record — whose message, which round, which digest, outside or not — and never from the
text (§8:5, ADR-0098 §2).

**What is not read** (§8:4). No held result, no model's hidden thinking, no diagnostic
record: this module imports none of them, and an import-linter contract forbids the
observer's modules importing ``orchestration.held_results`` (§15:4). An episode without
a processing record carries no recorded trigger to set an origin from (ADR-0328 §4:2),
so it is read as no part, and a leaving one is skipped by the stage. An open episode is
read as an id with no record (ADR-0286 §6:4).
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ConfirmationPart,
    EpisodicMemory,
    EvidenceItemPart,
    FindingUnwritten,
    InputOrigin,
    InputPart,
    LabelKind,
    Memory,
    MemoryKind,
    MemoryStanding,
    Placement,
    PlacementReach,
    PlacementSetter,
    RecordedChannelTrigger,
    RecordedTextInput,
    RoundMessagePart,
    StoryMember,
    StoryMemberKind,
    SupportOrigin,
    ToolOutcome,
    origin_is_outside,
    part_episode,
)
from ai_assistant.orchestration.authorizer import (
    WorkingRecord,
    read_outside_content,
    values_digest,
)
from ai_assistant.orchestration.candidates import done_candidates
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.reliance import (
    MEMORIES_ARGUMENT,
    NOTE_RELIANCE_CAPABILITY,
    SHAPED_ARGUMENT,
)
from ai_assistant.orchestration.remembering import (
    FACT_ARGUMENT,
    REMEMBER_CAPABILITY,
    Candidate,
    candidate_of,
)
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.support_parts import part_content

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping, Sequence, Set
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PlanStore, StoryStore
    from ai_assistant.core.types import (
        ActivationEffect,
        EpisodeProcessingRecord,
        FrozenJson,
        StoryNote,
        SupportPart,
    )

__all__ = [
    "ORIGIN_WORDS",
    "STANDING_WORDS",
    "EpisodeReader",
    "Hint",
    "ReadEpisode",
    "ReadMemory",
    "ReadPart",
    "ReadStory",
    "Reading",
    "Rehydrated",
    "Reliance",
    "approval_instant",
    "episode_text",
    "input_origin",
]

#: Whose words a part is, as the record says (§8:5): the attribution a rendering
#: carries beside each span, never read from the span's own text.
ORIGIN_WORDS: Final[Mapping[SupportOrigin, str]] = {
    SupportOrigin.USER_MESSAGE: "the user",
    SupportOrigin.OUTSIDE_INPUT: "outside: an input from a source or a forward, not the user",
    SupportOrigin.CONFIRMATION: "the user's yes to the exact wording shown",
    SupportOrigin.EVIDENCE: "outside: what a digest of a source's result recorded",
    SupportOrigin.ASSISTANT_MESSAGE: "the assistant",
    SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE: "the assistant, after reading outside content",
    SupportOrigin.REMEMBERED: "the assistant's earlier note to remember",
    SupportOrigin.REMEMBERED_OVER_OUTSIDE: (
        "the assistant's earlier note to remember, after reading outside content"
    ),
    SupportOrigin.LEGACY: "a record kept before supports existed",
    SupportOrigin.LEGACY_OUTSIDE: "a record kept before supports existed, from outside",
    SupportOrigin.OBSERVER_INFERENCE: "an inference drawn looking back",
}

#: How a memory stands, in the words a surface uses (ADR-0328 §6:1, §15:4).
STANDING_WORDS: Final[Mapping[MemoryStanding, str]] = {
    MemoryStanding.CONFIRMED: "you confirmed this wording",
    MemoryStanding.SAID: "you said it",
    MemoryStanding.SOURCE: "from a source",
    MemoryStanding.INFERENCE: "inference",
}


@dataclass(frozen=True, slots=True)
class ReadPart:
    """One part of one episode, as the observer read it (ADR-0328 §4's part table).

    Attributes:
        handle: The label the steps name it by (``P1``, ``P2``, ...).
        part: The part, as a support points at it.
        episode: The episode it is a part of.
        occurred_at: When that episode occurred, which orders parts across episodes.
        text: Its content.
        origin: The origin code sets on a support pointing at it (ADR-0328 §4:2).
        when: The ``when`` code sets on such a support (§4:12), or ``None``.
        answers: The message it replies to, where it is a reply (§9:3).
        question: For an evidence item, the question its digest answered.
    """

    handle: str
    part: SupportPart
    episode: str
    occurred_at: datetime
    text: str
    origin: SupportOrigin
    when: datetime | None
    answers: str | None = None
    question: str | None = None

    def rendered(self, *, answers: bool = False) -> dict[str, FrozenJson]:
        """The part as the steps are shown it, attributed from the record (§8:5).

        Args:
            answers: Whether to carry the message it replies to (§9:3).

        Returns:
            One JSON object.
        """
        shown: dict[str, FrozenJson] = {
            "part": self.handle,
            "from": ORIGIN_WORDS[self.origin],
            "outside": origin_is_outside(self.origin),
            "at": None if self.when is None else self.when.isoformat(),
            "text": self.text,
        }
        if self.question is not None:
            shown["digest_question"] = self.question
        if answers and self.answers is not None:
            shown["answers"] = self.answers
        return shown


@dataclass(frozen=True, slots=True)
class ReadEpisode:
    """One episode the observer read, with its parts.

    Attributes:
        handle: The label it is shown under (``E1``, ``E2``, ...).
        record: The episode, as stored.
        parts: Its parts, in record order.
    """

    handle: str
    record: EpisodicMemory
    parts: tuple[ReadPart, ...]

    def rendered(self) -> dict[str, FrozenJson]:
        """The episode as the scout is shown it: when it happened, and its parts."""
        return {
            "exchange": self.handle,
            "occurred_at": self.record.occurred_at.isoformat(),
            "parts": [one.rendered() for one in self.parts],
        }


@dataclass(frozen=True, slots=True)
class ReadMemory:
    """One stored memory the observer read, and the label it is shown under (``M1``...)."""

    handle: str
    memory: Memory

    def rendered(self) -> dict[str, FrozenJson]:
        """The memory as the scout is shown it: its claim, standing and open questions."""
        return {
            "memory": self.handle,
            "claim": self.memory.content,
            "stands": STANDING_WORDS[self.memory.standing],
            "status": self.memory.status.value,
            "open_questions": [one.asks for one in self.memory.open_questions if not one.resolved],
        }


@dataclass(frozen=True, slots=True)
class Hint:
    """One candidate of the leaving episode: a hint, never a part (ADR-0329 §3:6, §9:1).

    Attributes:
        handle: The label it is shown under (``C1``, ``C2``, ...).
        effect: The id of the effect record that shows it done (§3:3).
        fact: Its fact.
        why: Why planning noted it, where it said.
        rests_on: The parts it names, by their labels, where the reading holds them.
        memory: The memory it bears on, by its label, where the reading holds it.
        note: How it bears on that memory.
        confirmation: For a candidate recorded under an approval, the user's yes to its
            wording (§5:5), which a finding about it rests on.
    """

    handle: str
    effect: str
    fact: str
    why: str | None = None
    rests_on: tuple[str, ...] = ()
    memory: str | None = None
    note: str | None = None
    confirmation: ReadPart | None = None

    def rendered(self) -> dict[str, FrozenJson]:
        """The candidate as the scout is shown it."""
        return {
            "candidate": self.handle,
            "fact": self.fact,
            "why": self.why,
            "rests_on": list(self.rests_on),
            "memory": self.memory,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Reliance:
    """One memory a reliance call in the leaving episode named (ADR-0329 §6:7, §14:1).

    Attributes:
        handle: The memory's label.
        memory: The memory, as read.
        shaped: What the reliance shaped, as planning said it.
        relied_at: When the round that noted it was recorded.
    """

    handle: str
    memory: Memory
    shaped: str
    relied_at: datetime


@dataclass(frozen=True, slots=True)
class ReadStory:
    """One story the leaving episode's activation belongs to (§8:1).

    Attributes:
        summary: Its summary's lines, none where none was written.
        outside: Its summary's mark (ADR-0303 §3:4).
        recent: Its most recent episodes not shown in an earlier section.
    """

    summary: tuple[str, ...]
    outside: bool
    recent: tuple[ReadEpisode, ...]


@dataclass(frozen=True, slots=True)
class Reading:
    """Everything the observer read for one leaving episode (§8:1).

    Attributes:
        leaving: The leaving episode.
        later: The episodes still in the window that occurred after it, oldest first.
        stories: The stories its activation belongs to.
        past: Related past episodes, each with its candidates' facts and the claims of
            the single observations recorded on it (§11:4).
        memories: Related stored memories, and the memories its hints and reliance
            calls name.
        hints: Its candidates.
        reliances: The memories its reliance calls named.
        supplied: The placement of every record read, for the meet a write takes
            (ADR-0329 §12:6).
    """

    leaving: ReadEpisode
    later: tuple[ReadEpisode, ...] = ()
    stories: tuple[ReadStory, ...] = ()
    past: tuple[tuple[ReadEpisode, tuple[str, ...]], ...] = ()
    memories: tuple[ReadMemory, ...] = ()
    hints: tuple[Hint, ...] = ()
    reliances: tuple[Reliance, ...] = ()
    supplied: tuple[Placement, ...] = ()
    _parts: dict[str, ReadPart] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index every part by its label, once."""
        episodes = [
            self.leaving,
            *self.later,
            *(one for story in self.stories for one in story.recent),
            *(one for one, _ in self.past),
        ]
        for one in episodes:
            for part in one.parts:
                self._parts[part.handle] = part
        for hint in self.hints:
            if hint.confirmation is not None:
                self._parts[hint.confirmation.handle] = hint.confirmation

    def part(self, handle: str) -> ReadPart | None:
        """The part a label names, or ``None``."""
        return self._parts.get(handle)

    def at(self, part: SupportPart) -> ReadPart | None:
        """The part read at ``part``'s address, or ``None`` where none was."""
        return next((one for one in self._parts.values() if one.part == part), None)

    @property
    def leaving_parts(self) -> frozenset[SupportPart]:
        """The leaving episode's parts, its confirmations included (§8:2)."""
        own = {one.part for one in self.leaving.parts}
        own.update(hint.confirmation.part for hint in self.hints if hint.confirmation)
        return frozenset(own)

    def memory(self, handle: str) -> Memory | None:
        """The memory a label names, or ``None``."""
        held = next((one.memory for one in self.memories if one.handle == handle), None)
        if held is not None:
            return held
        return next((one.memory for one in self.reliances if one.handle == handle), None)

    def reliance(self, memory_id: str) -> Reliance | None:
        """The reliance call naming the memory ``memory_id``, or ``None``."""
        return next((one for one in self.reliances if one.memory.id == memory_id), None)

    def payload(self) -> dict[str, FrozenJson]:
        """What the scout is shown: one JSON object of quoted source data (§8:5).

        Returns:
            The object.
        """
        leaving = self.leaving.rendered()
        leaving["candidates"] = [hint.rendered() for hint in self.hints]
        leaving["confirmations"] = [
            hint.confirmation.rendered() for hint in self.hints if hint.confirmation is not None
        ]
        leaving["reliance"] = [
            {"memory": one.handle, "claim": one.memory.content, "shaped": one.shaped}
            for one in self.reliances
        ]
        return {
            "leaving": leaving,
            "later": [one.rendered() for one in self.later],
            "stories": [
                {
                    "summary": list(story.summary),
                    "summary_outside": story.outside,
                    "recent": [one.rendered() for one in story.recent],
                }
                for story in self.stories
            ],
            "past": [{**one.rendered(), "candidates": list(facts)} for one, facts in self.past],
            "memories": [one.rendered() for one in self.memories],
        }


@dataclass(frozen=True, slots=True)
class Rehydrated:
    """Parts read again from the store by their addresses, and what that read supplied.

    Attributes:
        parts: Each part that still resolves in a stored episode, by its address.
        supplied: The placement of every episode the read was supplied (§12:6).
    """

    parts: dict[SupportPart, ReadPart]
    supplied: tuple[Placement, ...]


def episode_text(record: EpisodicMemory) -> str:
    """An episode's input as its record holds it: the text, or the messages joined.

    Args:
        record: The episode.

    Returns:
        The text, empty where it holds none.
    """
    processing = record.processing_record
    if processing is None:
        return ""
    trigger = processing.trigger
    if trigger.messages:
        return "\n".join(one.text for one in trigger.messages if one.text)
    payload = trigger.payload
    if isinstance(payload, RecordedTextInput):
        return payload.text
    return payload.transcript or ""


def input_origin(trigger: RecordedChannelTrigger, message: int | None) -> SupportOrigin:
    """The origin of a support pointing at an input, or one of its messages (ADR-0328 §4:4).

    The input takes ``outside_input`` where its origin is outside; a message carrying
    ``forwarded_from`` takes it too, and the input as a whole takes it where any of its
    messages does. Everything else the user wrote is ``user_message``.

    Args:
        trigger: The episode's recorded trigger.
        message: The message's position, or ``None`` for the input as a whole.

    Returns:
        The origin.
    """
    if trigger.origin is InputOrigin.OUTSIDE:
        return SupportOrigin.OUTSIDE_INPUT
    messages = trigger.messages if message is None else trigger.messages[message : message + 1]
    if any(one.forwarded_from is not None for one in messages):
        return SupportOrigin.OUTSIDE_INPUT
    return SupportOrigin.USER_MESSAGE


def approval_instant(record: EpisodicMemory) -> datetime:
    """When the yes an episode's input carries was given (ADR-0328 §4:12).

    The approval's ``given.at`` is when the input carrying the yes was given: the latest
    of the messages it took in, or the episode's capture instant where it took in none
    (``phase_path``'s ``given_at``). The approval itself is stored only on the decisions
    that name it (ADR-0321 §4:8), which the observer does not hold, so its instant is
    read from the input the yes came in.

    Args:
        record: The yes's episode.

    Returns:
        The instant.
    """
    processing = record.processing_record
    messages = () if processing is None else processing.trigger.messages
    return max((one.sent_at for one in messages), default=record.occurred_at)


#: The largest page of a channel's episodes read to find what an input answers.
_PAGE: Final = 100

#: How many episodes back on a channel the observer looks for what an input answers,
#: passing over those in which the assistant said nothing (§9:3).
_REPLY_HORIZON: Final = 50


class _Labels:
    """Hands out each kind's next label, once per thing."""

    def __init__(self) -> None:
        self._next: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        number = self._next.get(prefix, 0) + 1
        self._next[prefix] = number
        return f"{prefix}{number}"


@dataclass(frozen=True, slots=True)
class _Gathered:
    """The records one reading is built from, before any label is handed out."""

    later: tuple[EpisodicMemory, ...]
    stories: tuple[tuple[tuple[str, ...], bool, tuple[EpisodicMemory, ...]], ...]
    summaries: tuple[Placement, ...]
    past: tuple[EpisodicMemory, ...]
    memories: tuple[Memory, ...]
    effects: tuple[ActivationEffect, ...]


class EpisodeReader:
    """Reads what §8:1 names around one leaving episode, from the stores it holds."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        plans: PlanStore,
        stories: StoryStore,
        story_episodes: int,
        related: int,
    ) -> None:
        """Wire the reader to its stores and its two bounds.

        Args:
            memory: The memory store episodes and memories are read from.
            plans: The plan store effect records are read from.
            stories: The story store a story's summary and members are read from.
            story_episodes: The most recent episodes read per story (§8:1).
            related: The most past episodes, and the most memories, a relevance search
                reads (§8:1).

        Raises:
            ValueError: If a bound is negative.
        """
        if story_episodes < 0 or related < 0:
            msg = "the observer's reading bounds are not negative (ADR-0329 §8:1)"
            raise ValueError(msg)
        self._memory = memory
        self._plans = plans
        self._stories = stories
        self._story_episodes = story_episodes
        self._related = related

    async def read(self, leaving: EpisodicMemory, window: Sequence[EpisodicMemory]) -> Reading:
        """Read around ``leaving``, with what came after it in ``window`` (§8:1).

        Args:
            leaving: The leaving episode, frozen, with a processing record.
            window: The episodes the selector returns now.

        Returns:
            The reading.

        Raises:
            MemoryStoreError: If the memory store cannot be read.
            StoryStoreError: If the story store cannot be read.
            PlanningError: If the plan store cannot be read.
        """
        processing = leaving.processing_record
        if processing is None:  # pragma: no cover - the stage skips such an episode first
            msg = "the observer reads an episode with a processing record"
            raise ValueError(msg)
        gathered = await self._gather(leaving, processing, window)
        labels = _Labels()
        shown = _Shown(labels, await self._outsides(leaving, gathered))
        everything = (leaving, *gathered.later, *(r for s in gathered.stories for r in s[2]))
        answers: dict[str, str] = {}
        replied: list[Placement] = []
        for record in (*everything, *gathered.past):
            text, placement = await self._reply_to(record)
            if text is not None:
                answers[record.id] = text
            if placement is not None:
                replied.append(placement)
        read_leaving = shown.episode(leaving, answers)
        later = tuple(shown.episode(one, answers) for one in gathered.later)
        stories = tuple(
            ReadStory(
                summary=summary,
                outside=outside,
                recent=tuple(shown.episode(one, answers) for one in fresh),
            )
            for summary, outside, fresh in gathered.stories
        )
        past_effects = await self._effects(gathered.past)
        observed = await self._single_observations(gathered.past)
        past = tuple(
            (
                shown.episode(one, answers),
                tuple(dict.fromkeys((*_facts(one, past_effects), *observed.get(one.id, ())))),
            )
            for one in gathered.past
        )
        memories = [ReadMemory(handle=labels("M"), memory=one) for one in gathered.memories]
        reliances = await self._reliances(processing, memories, labels)
        asking_supply: list[Placement] = []
        hints = await self._hints(
            leaving, processing, gathered.effects, shown, memories, labels, asking_supply
        )
        stories_read = tuple(one for _, _, fresh in gathered.stories for one in fresh)
        supplied = [
            one.placement for one in (leaving, *gathered.later, *gathered.past, *stories_read)
        ]
        supplied.extend(gathered.summaries)
        supplied.extend(one.memory.placement for one in memories)
        supplied.extend(one.memory.placement for one in reliances)
        supplied.extend(asking_supply)
        supplied.extend(replied)
        return Reading(
            leaving=read_leaving,
            later=later,
            stories=stories,
            past=past,
            memories=tuple(memories),
            hints=hints,
            reliances=reliances,
            supplied=tuple(supplied),
        )

    async def parts_at(self, parts: Sequence[SupportPart]) -> Rehydrated:
        """Read ``parts`` again from the store, by their addresses (§9:5, §16:4).

        A finding recorded in an earlier attempt names parts by address, and the episodes
        they are parts of may have left this attempt's reading since, as the window
        moved: they are read again here, each with the facts code sets on a support
        pointing at it, so a retry commits what the finding rests on rather than losing
        it. A part that no longer resolves in a stored episode is left out.

        Args:
            parts: The parts' addresses.

        Returns:
            The parts that resolve, and the placements of the episodes read.

        Raises:
            MemoryStoreError: If the memory store cannot be read.
        """
        wanted = list(dict.fromkeys(parts))
        addresses: dict[str, None] = {}
        for part in wanted:
            if (episode := part_episode(part)) is not None:
                addresses[episode] = None
            if isinstance(part, ConfirmationPart):
                addresses[episode_address(part.asking_activation)] = None
        if not addresses:
            return Rehydrated(parts={}, supplied=())
        found = without_open_episodes(await self._memory.get_many(list(addresses)))
        episodes = {key: one for key, one in found.items() if isinstance(one, EpisodicMemory)}
        read: dict[SupportPart, ReadPart] = {}
        said = {part.episode for part in wanted if isinstance(part, RoundMessagePart)}
        outsides = await self._outsides_of([one for key, one in episodes.items() if key in said])
        supplied: list[Placement] = []
        for index, part in enumerate(wanted, start=1):
            record = episodes.get(part_episode(part) or "")
            text = part_content(part, episodes=episodes, effects={}, carried=None)
            if record is None or record.processing_record is None or not text:
                continue
            facts = _facts_at(part, record, outsides)
            if facts is None:
                continue
            answers, answered = await self._answered(part, record)
            if answered is not None:
                supplied.append(answered)
            read[part] = ReadPart(
                handle=f"P{index}",
                part=part,
                episode=record.id,
                occurred_at=record.occurred_at,
                text=text,
                origin=facts[0],
                when=facts[1],
                answers=answers,
            )
        supplied.extend(one.placement for one in episodes.values())
        return Rehydrated(parts=read, supplied=tuple(supplied))

    async def _answered(
        self, part: SupportPart, record: EpisodicMemory
    ) -> tuple[str | None, Placement | None]:
        """What a part read again replies to, and the placement of what was read for it (§9:3).

        A round's message answers its own episode's input; an input answers what the
        assistant last said on its channel before it (:meth:`_reply_to`).
        """
        if isinstance(part, RoundMessagePart):
            return episode_text(record) or None, None
        if not isinstance(part, InputPart):
            return None, None
        return await self._reply_to(record)

    async def _reply_to(self, record: EpisodicMemory) -> tuple[str | None, Placement | None]:
        """What the assistant last said on ``record``'s channel before it, and where (§9:3).

        The text, and the placement of the episode it came from, which joins the supply
        (§12:6). Read from the channel's own history, never from what a reading happens to hold:
        an episode the reading left out still stands between a question and its answer.
        An episode in which the assistant said nothing is passed over, up to
        :data:`_REPLY_HORIZON` episodes back.
        """
        processing = record.processing_record
        channel = None if processing is None else processing.trigger.channel
        if channel is None:
            return None, None
        key = (record.occurred_at, record.id)
        cursor: str | None = None
        seen = 0
        while seen < _REPLY_HORIZON:
            page = await self._memory.episodes(channel=channel, cursor=cursor, limit=_PAGE)
            earlier = [
                row.position.episode_id
                for row in page.items
                if (row.position.occurred_at, row.position.episode_id) < key
            ][: _REPLY_HORIZON - seen]
            seen += len(earlier)
            found = without_open_episodes(await self._memory.get_many(earlier)) if earlier else {}
            for episode_id in earlier:
                before = found.get(episode_id)
                rounds = (
                    before.processing_record.rounds
                    if isinstance(before, EpisodicMemory) and before.processing_record is not None
                    else ()
                )
                said = [one.text for one in rounds if one.text]
                if said and isinstance(before, EpisodicMemory):
                    return said[-1], before.placement
            if page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return None, None

    async def _gather(
        self,
        leaving: EpisodicMemory,
        processing: EpisodeProcessingRecord,
        window: Sequence[EpisodicMemory],
    ) -> _Gathered:
        """Every record the reading is built from (§8:1)."""
        key = (leaving.occurred_at, leaving.id)
        later = tuple(
            sorted(
                (
                    one
                    for one in window
                    if (one.occurred_at, one.id) > key and _readable(one) and one.id != leaving.id
                ),
                key=lambda one: (one.occurred_at, one.id),
            )
        )
        held = {leaving.id, *(one.id for one in later)}
        stories, summaries = await self._story_reads(processing.activation_id, held)
        held.update(one.id for _, _, fresh in stories for one in fresh)
        effects = await self._plans.activation_effects([processing.activation_id])
        query = " ".join(
            filter(
                None,
                (
                    episode_text(leaving),
                    *(one.fact for one in done_candidates(leaving.id, processing, effects)),
                ),
            )
        )
        past, memories = await self._related_reads(query, leaving, held)
        return _Gathered(
            later=later,
            stories=stories,
            summaries=summaries,
            past=past,
            memories=memories,
            effects=tuple(effects),
        )

    async def _story_reads(
        self, activation_id: str, held: set[str]
    ) -> tuple[
        tuple[tuple[tuple[str, ...], bool, tuple[EpisodicMemory, ...]], ...],
        tuple[Placement, ...],
    ]:
        """For each story the activation belongs to: its summary and recent episodes.

        Each summary read supplies a record placed for the owner alone, whoever wrote it
        (ADR-0304 §4:1), so what is written over it inherits that reach (§12:6).
        """
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
        headers = await self._stories.stories_of(member)
        read: list[tuple[tuple[str, ...], bool, tuple[EpisodicMemory, ...]]] = []
        summaries: list[Placement] = []
        for header in headers:
            state = await self._stories.current_summary(header.story_id)
            summary = None if state is None else state.summary
            if summary is not None:
                summaries.append(
                    Placement(
                        reach=PlacementReach.OWNER,
                        set_by=PlacementSetter.DERIVED,
                        set_at=summary.written_at,
                    )
                )
            lines = () if summary is None else tuple(line.text for line in summary.lines)
            outside = summary is not None and summary.outside
            recent = await self._recent(header.story_id, activation_id)
            addresses = [episode_address(one) for one in recent]
            found = without_open_episodes(await self._memory.get_many(addresses))
            fresh = tuple(
                record
                for address in addresses
                if isinstance(record := found.get(address), EpisodicMemory)
                and _readable(record)
                and record.id not in held
            )
            held.update(one.id for one in fresh)
            read.append((lines, outside, fresh))
        return tuple(read), tuple(summaries)

    async def _recent(self, story_id: str, activation_id: str) -> tuple[str, ...]:
        """A story's most recent activation members but ``activation_id``, newest last."""
        if self._story_episodes == 0:
            return ()
        members: list[str] = []
        cursor: int | None = None
        while True:
            page = await self._stories.view(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
            if page is None:
                break
            members.extend(
                entry.member.id
                for entry in page.entries
                if entry.member.kind is StoryMemberKind.ACTIVATION
                and entry.member.id != activation_id
            )
            if page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return tuple(members[-self._story_episodes :])

    async def _related_reads(
        self, query: str, leaving: EpisodicMemory, held: set[str]
    ) -> tuple[tuple[EpisodicMemory, ...], tuple[Memory, ...]]:
        """Past episodes and memories a relevance search finds related (§8:1)."""
        if not query.strip() or self._related == 0:
            return (), ()
        episodes = await self._memory.search(
            query, limit=self._related, kinds=(MemoryKind.EPISODIC,)
        )
        past = tuple(
            sorted(
                (
                    one
                    for one in episodes.records
                    if isinstance(one, EpisodicMemory)
                    and _readable(one)
                    and one.id not in held
                    and (one.occurred_at, one.id) < (leaving.occurred_at, leaving.id)
                ),
                key=lambda one: (one.occurred_at, one.id),
            )
        )
        memories = await self._memory.search(query, limit=self._related, kinds=(MemoryKind.MEMORY,))
        return past, tuple(one for one in memories.records if isinstance(one, Memory))

    async def _outsides(self, leaving: EpisodicMemory, gathered: _Gathered) -> dict[str, bool]:
        """Whether each read activation had read outside content (ADR-0328 §4:3)."""
        records = (leaving, *gathered.later, *gathered.past)
        records += tuple(one for _, _, fresh in gathered.stories for one in fresh)
        return await self._outsides_of(records)

    async def _outsides_of(self, records: Sequence[EpisodicMemory]) -> dict[str, bool]:
        """Whether each record's activation had read outside content, by the record's id.

        Read as authorizing reads it (ADR-0306 §4:5), over the stored record: no working
        set outlives its activation. What the working set held of the story notes
        planning was shown is read again from the story store, where each note's mark
        was set when it was written and never changes (ADR-0303 §3:1), so a note is read
        as outside content exactly where it is marked. A note the store no longer shows
        has a mark nothing can read, and fails closed, as authorizing's does.
        """
        held = [
            (record.id, processing)
            for record in records
            if (processing := record.processing_record) is not None
        ]
        wanted = {
            label.id
            for _, processing in held
            for label in processing.labels
            if label.kind is LabelKind.NOTE
        }
        notes = await _shown_notes(
            self._stories, wanted, [processing.activation_id for _, processing in held]
        )
        working = WorkingRecord(notes=notes)
        return {
            record_id: await read_outside_content(
                self._memory, processing.activation_id, working=working
            )
            for record_id, processing in held
        }

    async def _single_observations(
        self, episodes: Sequence[EpisodicMemory]
    ) -> dict[str, tuple[str, ...]]:
        """The single observations recorded on each episode, by its id (§11:4).

        A single observation is evidence only: it is kept as no memory, and waits as a
        candidate on its episode, where a later run's search finds it. So a past episode
        is shown with the claim of every finding its observation record holds whose
        outcome was a single observation, beside planning's candidates.

        Raises:
            PlanningError: If the plan store cannot be read.
        """
        if not episodes:
            return {}
        records = await self._plans.observations([one.id for one in episodes])
        return {
            record.episode: tuple(
                finding.claim
                for finding in record.findings
                if finding.outcome is not None
                and finding.outcome.unwritten is FindingUnwritten.SINGLE_OBSERVATION
            )
            for record in records
        }

    async def _effects(self, episodes: Sequence[EpisodicMemory]) -> tuple[ActivationEffect, ...]:
        activations = [
            one.processing_record.activation_id for one in episodes if one.processing_record
        ]
        if not activations:
            return ()
        return tuple(await self._plans.activation_effects(activations))

    async def _reliances(
        self,
        processing: EpisodeProcessingRecord,
        memories: list[ReadMemory],
        labels: _Labels,
    ) -> tuple[Reliance, ...]:
        """The memories the leaving episode's reliance calls named (§14:1)."""
        named = {one.label: one.id for one in processing.labels if one.kind is LabelKind.MEMORY}
        wanted: list[tuple[str, str, datetime]] = []
        for one in processing.rounds:
            for call in one.calls:
                if call.name != NOTE_RELIANCE_CAPABILITY:
                    continue
                shaped = call.arguments.get(SHAPED_ARGUMENT)
                relied = call.arguments.get(MEMORIES_ARGUMENT)
                if not isinstance(shaped, str) or not isinstance(relied, list | tuple):
                    continue
                wanted.extend(
                    (named[label], shaped, one.recorded_at)
                    for label in relied
                    if isinstance(label, str) and label in named
                )
        if not wanted:
            return ()
        found = await self._memory.get_many(list(dict.fromkeys(memory for memory, _, _ in wanted)))
        handles = {one.memory.id: one.handle for one in memories}
        reliances: dict[str, Reliance] = {}
        for memory_id, shaped, relied_at in wanted:
            record = found.get(memory_id)
            if not isinstance(record, Memory) or memory_id in reliances:
                continue
            handle = handles.get(memory_id) or labels("M")
            reliances[memory_id] = Reliance(
                handle=handle, memory=record, shaped=shaped, relied_at=relied_at
            )
        return tuple(reliances.values())

    async def _hints(  # noqa: PLR0913 — what the hints are mapped against, each read once already
        self,
        leaving: EpisodicMemory,
        processing: EpisodeProcessingRecord,
        effects: Sequence[ActivationEffect],
        shown: _Shown,
        memories: list[ReadMemory],
        labels: _Labels,
        asking_supply: list[Placement],
    ) -> tuple[Hint, ...]:
        """The leaving episode's candidates, as hints (§3:3, §9:1).

        ``asking_supply`` collects the placement of every asking episode read for a candidate
        recorded under an approval, whose wording the hint carries (§12:6).
        """
        hints: list[Hint] = []
        for done in done_candidates(leaving.id, processing, effects):
            try:
                candidate = candidate_of(done.values)
            except ValueError:
                hints.append(Hint(handle=labels("C"), effect=done.effect, fact=done.fact))
                continue
            memory = await self._memory_handle(candidate.memory, memories, labels)
            hints.append(
                Hint(
                    handle=labels("C"),
                    effect=done.effect,
                    fact=candidate.fact,
                    why=candidate.why,
                    rests_on=shown.resting_on(candidate, leaving),
                    memory=memory,
                    note=candidate.note,
                )
            )
        hints.extend(
            await self._approved(leaving, processing, effects, shown, labels, asking_supply)
        )
        return tuple(hints)

    async def _memory_handle(
        self, memory_id: str | None, memories: list[ReadMemory], labels: _Labels
    ) -> str | None:
        """The label of the memory a candidate names, reading it where it is not yet read."""
        if memory_id is None:
            return None
        held = next((one for one in memories if one.memory.id == memory_id), None)
        if held is not None:
            return held.handle
        record = await self._memory.get(memory_id)
        if not isinstance(record, Memory):
            return None
        read = ReadMemory(handle=labels("M"), memory=record)
        memories.append(read)
        return read.handle

    async def _approved(  # noqa: PLR0913 — what an approval is read against, each read already
        self,
        leaving: EpisodicMemory,
        processing: EpisodeProcessingRecord,
        effects: Sequence[ActivationEffect],
        shown: _Shown,
        labels: _Labels,
        asking_supply: list[Placement],
    ) -> list[Hint]:
        """The candidates recorded under an approval in the leaving episode (§3:3, §5:5).

        A ``remember`` run under an approval is proposed by its approved-action label, so
        its candidate is the asked call the effect record's question part names, as the
        asking round records it. The asking activation is the one the input's recorded
        answer pointers name whose round is that part's round.
        """
        approved = [
            one
            for one in effects
            if one.capability == REMEMBER_CAPABILITY
            and one.outcome is ToolOutcome.SUCCEEDED
            and one.part is not None
            and one.activation_id == processing.activation_id
        ]
        if not approved:
            return []
        askers = list(
            dict.fromkeys(
                answer.activation_id
                for understood in processing.understanding
                for answer in understood.answers
            )
        )
        found = without_open_episodes(
            await self._memory.get_many([episode_address(one) for one in askers])
        )
        asking_supply.extend(
            one.placement for one in found.values() if isinstance(one, EpisodicMemory)
        )
        hints: list[Hint] = []
        for effect in approved:
            part = effect.part
            if part is None:  # pragma: no cover - filtered above
                continue
            asked = _asked(found, askers, effect)
            if asked is None:
                continue
            asking, fact = asked
            confirmation = shown.confirmation(
                ConfirmationPart(episode=leaving.id, asking_activation=asking, question=part),
                episode=leaving,
                text=fact,
                when=approval_instant(leaving),
            )
            hints.append(
                Hint(
                    handle=labels("C"),
                    effect=effect.id,
                    fact=fact,
                    rests_on=(confirmation.handle,),
                    confirmation=confirmation,
                )
            )
        return hints


def _asked(
    found: Mapping[str, object], askers: Sequence[str], effect: ActivationEffect
) -> tuple[str, str] | None:
    """The asking activation and the fact its asked call showed, for one spent part.

    The asked call is the one the effect record's question part names, and its digest is
    the one the record claimed, as the panel's read checks it
    (:func:`~ai_assistant.orchestration.candidates.held_candidates`).
    """
    part = effect.part
    if part is None:
        return None
    for activation_id in askers:
        record = found.get(episode_address(activation_id))
        processing = record.processing_record if isinstance(record, EpisodicMemory) else None
        if processing is None:
            continue
        round_ = next((one for one in processing.rounds if one.id == part.round), None)
        if round_ is None or not 1 <= part.part <= len(round_.asked):
            continue
        asked = round_.asked[part.part - 1]
        fact = asked.values.get(FACT_ARGUMENT)
        if asked.tool.capability != REMEMBER_CAPABILITY or not isinstance(fact, str) or not fact:
            continue
        try:
            digest = values_digest(asked.request)
        except ValueError:
            continue
        if digest == effect.values_digest:
            return activation_id, fact
    return None


async def _shown_notes(
    stories: StoryStore, wanted: Set[str], activations: Sequence[str]
) -> tuple[StoryNote, ...]:
    """The story notes whose ids ``wanted`` names, as the story store holds them.

    A note label's id is its note's id (``PlanningLabel.id``). A note moves with a merge,
    a split or a move but is never removed and its mark never changes (ADR-0303 §3:1),
    so it is found wherever it is held now: first among the notes of the stories the
    ``activations`` belong to, where a note planning was shown is most often held, then,
    for any still not found, among every story's, newest first, stopping once all are.
    A label whose note is in none of them is left out, and fails closed where it is
    read (:func:`~ai_assistant.orchestration.authorizer.read_outside_content`).

    Raises:
        StoryStoreError: If the story store cannot be read.
    """
    wanted = {one for one in wanted if one.isdecimal()}
    found: dict[str, StoryNote] = {}
    if not wanted:
        return ()
    read: set[str] = set()
    async with aclosing(_stories_to_search(stories, activations)) as story_ids:
        async for story_id in story_ids:
            if story_id in read:
                continue
            read.add(story_id)
            found.update(
                (str(note.note_id), note)
                for note in await _story_notes(stories, story_id)
                if str(note.note_id) in wanted
            )
            if wanted <= found.keys():
                break
    return tuple(found.values())


async def _stories_to_search(
    stories: StoryStore, activations: Sequence[str]
) -> AsyncGenerator[str]:
    """The stories ``activations`` belong to, then every story, newest first, by id."""
    for activation_id in dict.fromkeys(activations):
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
        for header in await stories.stories_of(member):
            yield header.story_id
    cursor: int | None = None
    while True:
        page = await stories.stories(cursor=cursor, limit=MAX_STORY_PAGE)
        for header in page.stories:
            yield header.story_id
        if page.next_cursor is None or page.next_cursor == cursor:
            return
        cursor = page.next_cursor


async def _story_notes(stories: StoryStore, story_id: str) -> list[StoryNote]:
    """Every note a story holds now, every page read; none where it holds no such story."""
    held: list[StoryNote] = []
    cursor: int | None = None
    while True:
        page = await stories.notes(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if page is None:
            return held
        held.extend(page.notes)
        if page.next_cursor is None or page.next_cursor == cursor:
            return held
        cursor = page.next_cursor


def _facts_at(  # noqa: PLR0911 — one arm per part a finding may rest on (§9:6)
    part: SupportPart, record: EpisodicMemory, outsides: Mapping[str, bool]
) -> tuple[SupportOrigin, datetime | None] | None:
    """The origin and ``when`` code sets on a support pointing at ``part`` (§9:5).

    A round's message takes its outside origin from ``outsides``, and where that holds
    no answer for its episode, it is read as outside, failing closed.
    """
    processing = record.processing_record
    if processing is None:  # pragma: no cover - checked by the caller
        return None
    match part:
        case InputPart(message=None):
            return input_origin(processing.trigger, None), record.occurred_at
        case InputPart(message=int() as message) if message < len(processing.trigger.messages):
            sent = processing.trigger.messages[message].sent_at
            return input_origin(processing.trigger, message), sent
        case RoundMessagePart():
            round_ = next((one for one in processing.rounds if one.id == part.round), None)
            if round_ is None:
                return None
            origin = (
                SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE
                if outsides.get(record.id, True)
                else SupportOrigin.ASSISTANT_MESSAGE
            )
            return origin, round_.recorded_at
        case EvidenceItemPart() if part.digest < len(processing.digests):
            return SupportOrigin.EVIDENCE, processing.digests[part.digest].recorded_at
        case ConfirmationPart():
            return SupportOrigin.CONFIRMATION, approval_instant(record)
        case _:
            return None


def _readable(record: EpisodicMemory) -> bool:
    """Whether an episode is read as parts: frozen, with a processing record."""
    processing = record.processing_record
    return processing is not None and not processing.is_open


def _facts(record: EpisodicMemory, effects: Sequence[ActivationEffect]) -> tuple[str, ...]:
    processing = record.processing_record
    if processing is None:  # pragma: no cover - only readable episodes are read
        return ()
    return tuple(one.fact for one in done_candidates(record.id, processing, effects))


class _Shown:
    """Labels parts as they are read, and sets the code-owned facts on each."""

    def __init__(self, labels: _Labels, outsides: Mapping[str, bool]) -> None:
        self._labels = labels
        self._outsides = outsides
        self._issued: list[ReadPart] = []

    def _part(  # noqa: PLR0913 — one keyword per field of the part, as the record gives it
        self,
        part: SupportPart,
        *,
        episode: EpisodicMemory,
        text: str,
        origin: SupportOrigin,
        when: datetime | None,
        answers: str | None = None,
        question: str | None = None,
    ) -> ReadPart:
        read = ReadPart(
            handle=self._labels("P"),
            part=part,
            episode=episode.id,
            occurred_at=episode.occurred_at,
            text=text,
            origin=origin,
            when=when,
            answers=answers,
            question=question,
        )
        self._issued.append(read)
        return read

    def episode(self, record: EpisodicMemory, answers: Mapping[str, str]) -> ReadEpisode:
        """One episode and its parts, each labelled (§8:6)."""
        handle = self._labels("E")
        processing = record.processing_record
        parts: list[ReadPart] = []
        if processing is not None:
            parts.extend(self._inputs(record, processing, answers.get(record.id)))
            said = episode_text(record) or None
            over = self._outsides.get(record.id, True)
            origin = (
                SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE
                if over
                else SupportOrigin.ASSISTANT_MESSAGE
            )
            parts.extend(
                self._part(
                    RoundMessagePart(episode=record.id, round=one.id),
                    episode=record,
                    text=one.text,
                    origin=origin,
                    when=one.recorded_at,
                    answers=said,
                )
                for one in processing.rounds
                if one.text
            )
            for index, digest in enumerate(processing.digests):
                parts.extend(
                    self._part(
                        EvidenceItemPart(episode=record.id, digest=index, item=position),
                        episode=record,
                        text=item.text,
                        origin=SupportOrigin.EVIDENCE,
                        when=digest.recorded_at,
                        question=digest.question,
                    )
                    for position, item in enumerate(digest.evidence)
                )
        return ReadEpisode(handle=handle, record=record, parts=tuple(parts))

    def _inputs(
        self, record: EpisodicMemory, processing: EpisodeProcessingRecord, answers: str | None
    ) -> list[ReadPart]:
        """The input, or each message it took in (ADR-0328 §4:4, §4:12)."""
        trigger = processing.trigger
        if trigger.messages:
            return [
                self._part(
                    InputPart(episode=record.id, message=index),
                    episode=record,
                    text=one.text,
                    origin=input_origin(trigger, index),
                    when=one.sent_at,
                    answers=answers,
                )
                for index, one in enumerate(trigger.messages)
                if one.text
            ]
        text = episode_text(record)
        if not text:
            return []
        return [
            self._part(
                InputPart(episode=record.id),
                episode=record,
                text=text,
                origin=input_origin(trigger, None),
                when=record.occurred_at,
                answers=answers,
            )
        ]

    def confirmation(
        self, part: ConfirmationPart, *, episode: EpisodicMemory, text: str, when: datetime
    ) -> ReadPart:
        """A yes to a wording, in the yes's episode, labelled (ADR-0328 §4:5, §4:12)."""
        return self._part(
            part, episode=episode, text=text, origin=SupportOrigin.CONFIRMATION, when=when
        )

    def resting_on(self, candidate: Candidate, leaving: EpisodicMemory) -> tuple[str, ...]:
        """The labels of the parts a candidate names, among those this reading labelled.

        Its input is the leaving episode's input parts; an earlier exchange's user's or
        assistant's message is that episode's input or round message parts; a result is
        the evidence items of the digests of that result (§9:6). A part the reading did
        not read is not named.
        """
        wanted: set[tuple[str, str]] = set()
        if candidate.rests_on_input:
            wanted.add((leaving.id, "input"))
        wanted.update((one, "input") for one in candidate.user_messages)
        wanted.update((one, "round_message") for one in candidate.assistant_messages)
        digests = _result_digests(leaving, candidate.results)
        return tuple(
            part.handle
            for part in self._issued
            if (part.episode, part.part.part) in wanted
            or (
                isinstance(part.part, EvidenceItemPart)
                and part.episode == leaving.id
                and part.part.digest in digests
            )
        )


def _result_digests(record: EpisodicMemory, results: Sequence[str]) -> frozenset[int]:
    """The positions of an episode's digests of the results named, by their ids."""
    processing = record.processing_record
    if processing is None or not results:
        return frozenset()
    named = {one.label for one in processing.labels if one.kind is LabelKind.RESULT}
    ids = {one.label: one.id for one in processing.labels if one.kind is LabelKind.RESULT}
    wanted = {label for label in named if ids[label] in results}
    return frozenset(
        index
        for index, digest in enumerate(processing.digests)
        if digest.result is not None and digest.result in wanted
    )
