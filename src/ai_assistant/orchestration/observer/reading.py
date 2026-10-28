"""What the observer reads of a leaving episode, and how it renders it (ADR-0346 §2).

For a leaving episode the observer reads the episode's whole record and what that record
points at (§2:1): the memories and episodes its recall runs returned; the stories,
episodes, notes and memories its planning labels name; what its understanding's
referents name; and the asking activation of the question its input answers, which an
approval its rounds ran under names. It reads nothing else and runs no search (§2:4): no
later episode, no story read beyond what a label or a referent names, and no relevance
search. This module gathers it (:class:`EpisodeReader`) and renders it for the scout
(:meth:`Reading.payload`).

**As it stood then** (§2:2, ADR-0347 §4). What the record points at is shown as it stood
when the episode's activation started: a memory with the supports, operations, status
and open questions it had then, from its dated supports and operation log, and a story
with the summary of its latest version at or below the episode's ``stories_position``,
read through :meth:`~ai_assistant.core.protocols.StoryStore.summary_at`. Nothing that
happened after is shown. The activation's start is the instant, as the story store's
position is, since it is the one every read of the activation began from.

**No longer held** (§2:3, ADR-0347 §4:3). Where the store no longer holds a thing as it
stood then, the scout is shown only what the leaving episode itself recorded of it,
marked as no longer held: a memory or an episode by the recall item a recall run kept for
it, or by its identity alone where none did; and a story by its identity alone, where
the episode records no position, no version lies at or below it, or no text is held for
that version. Nothing later stands in for it.

**Parts, not fields** (ADR-0329 §8:6). An episode is rendered by the parts a support may
point at (ADR-0328 §4's part table): the input or each message it took in, each round's
message, each evidence item of its digests, and, for a candidate recorded under an
approval, the user's yes to the wording it showed. Each carries a label (``P1``, ``P2``,
...) the steps name it by, and code maps the label back to the part: no model writes a
part's address. The leaving episode's understanding, its latest version, is rendered
beside its parts (§2:5); every other field of an episode is not.

**Code-owned facts** (ADR-0329 §9:5). Each part is read with what code sets on a support
that points at it: its origin, from the part and the episode's record (ADR-0328
§4:2-§4:4), and its ``when`` (§4:12). A round's message takes its outside origin where the
activation's record says it had read outside content (§4:3), as authorizing decides it
(:func:`~ai_assistant.orchestration.authorizer.read_outside_content`). Every span reaches
the model as quoted source data, attributed from the record, never from the text
(ADR-0329 §8:5, ADR-0098 §2).

**What is not read** (ADR-0329 §8:4, as ADR-0346 §2:6 keeps it). No held result, no
model's hidden thinking, no diagnostic record: this module imports none of them, and an
import-linter contract forbids the observer's modules importing
``orchestration.held_results``. An episode without a processing record carries no
recorded trigger to set an origin from (ADR-0328 §4:2), so it is read as no part, and a
leaving one is skipped by the stage. An open episode is read as an id with no record
(ADR-0286 §6:4), shown by its identity alone.
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    OWNER_PERSON_ID,
    ConfirmationPart,
    EpisodicMemory,
    EvidenceItemPart,
    InputPart,
    LabelKind,
    Memory,
    MemoryKind,
    MemoryOperationKind,
    MemoryStanding,
    MemoryStatus,
    Placement,
    PlacementReach,
    PlacementSetter,
    RecordedTextInput,
    RoundMessagePart,
    StoryMember,
    StoryMemberKind,
    SupportOrigin,
    ToolOutcome,
    input_support_origin,
    origin_is_outside,
)
from ai_assistant.orchestration.authorizer import (
    WorkingRecord,
    read_outside_content,
    values_digest,
)
from ai_assistant.orchestration.candidates import done_candidates
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.remembering import (
    FACT_ARGUMENT,
    REMEMBER_CAPABILITY,
    Candidate,
    candidate_of,
)
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping, Sequence, Set
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PlanStore, StoryStore
    from ai_assistant.core.types import (
        ActivationEffect,
        ActivationUnderstanding,
        EpisodeProcessingRecord,
        FrozenJson,
        OpenQuestion,
        RecalledItem,
        StoryNote,
        SupportHolder,
        SupportPart,
        UnderstandingReferent,
    )

__all__ = [
    "ORIGIN_WORDS",
    "STANDING_WORDS",
    "USER_NAME",
    "EpisodeReader",
    "Hint",
    "ReadEpisode",
    "ReadMemory",
    "ReadPart",
    "ReadStory",
    "Reading",
    "approval_instant",
    "episode_text",
    "holder_words",
    "input_origin",
    "memory_then",
    "name_shown",
    "name_stored",
]

#: The placement a story's summary or a note supplies: the owner alone (ADR-0304 §4:1).
_OWNER_ONLY: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)

#: How the owner is named in what a model is shown and answers (ADR-0345 §9:4): the
#: record names them by :data:`OWNER_PERSON_ID`, which code puts in place of this.
USER_NAME: Final = "the user"

#: Whose words a part is, as the record says (ADR-0329 §8:5): the attribution a rendering
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
    # ADR-0338 §4:3-§4:4: the user pinned the memory on their own profile, which confirms
    # the wording it then had (#3335).
    SupportOrigin.PINNED: "the user's pin, confirming this wording",
}

#: How a memory stands, in the words a surface uses (ADR-0328 §6:1, §15:4).
STANDING_WORDS: Final[Mapping[MemoryStanding, str]] = {
    MemoryStanding.CONFIRMED: "you confirmed this wording",
    MemoryStanding.SAID: "you said it",
    MemoryStanding.SOURCE: "from a source",
    MemoryStanding.INFERENCE: "inference",
}


def name_shown(name: str) -> str:
    """A name as a model is shown it: the owner as :data:`USER_NAME` (ADR-0345 §9:4)."""
    return USER_NAME if name == OWNER_PERSON_ID else name


def name_stored(name: str) -> str:
    """A name a model gave, as the record keeps it: :data:`USER_NAME` as the owner's id."""
    stripped = name.strip()
    return OWNER_PERSON_ID if stripped.casefold() in {USER_NAME, "user"} else stripped


def holder_words(holder: SupportHolder) -> str:
    """A holder as a model is shown it, from the record (ADR-0345 §2:3, §12:1)."""
    match holder.kind.value:
        case "person":
            return USER_NAME if holder.identifier == OWNER_PERSON_ID else f"{holder.identifier}"
        case "outside_source":
            kind = "a source claimed by a forward" if holder.claimed else "a source"
            return f"{kind}: {holder.identifier}"
        case "assistant_statement":
            return "the assistant's statement"
        case _:
            return "unknown"


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
        answers: The message it replies to, where it is a reply (ADR-0346 §5:1).
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

    def rendered(
        self, *, answers: bool = False, exchange: str | None = None
    ) -> dict[str, FrozenJson]:
        """The part as the steps are shown it, attributed from the record (§8:5).

        Args:
            answers: Whether to carry the message it replies to (ADR-0346 §5:1).
            exchange: The label of the exchange it belongs to, where the step is shown
                parts apart from their exchanges (framing and placement); the part then
                names that exchange and when it occurred. The scout is shown each part
                inside its exchange instead, and passes none.

        Returns:
            One JSON object.
        """
        shown: dict[str, FrozenJson] = {"part": self.handle}
        if exchange is not None:
            shown["exchange"] = exchange
            shown["occurred_at"] = self.occurred_at.isoformat()
        shown |= {
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
    """One episode the observer read, with its parts, or by its identity alone.

    Attributes:
        handle: The label it is shown under (``E1``, ``E2``, ...).
        episode: Its id, exactly as held.
        record: The episode, as stored; ``None`` where it is no longer held (§2:3).
        parts: Its parts, in record order; none where it is not held.
        excerpt: Where it is not held, what a recall run kept of it, or ``None``.
    """

    handle: str
    episode: str
    record: EpisodicMemory | None
    parts: tuple[ReadPart, ...] = ()
    excerpt: str | None = None

    def rendered(self) -> dict[str, FrozenJson]:
        """The episode as the scout is shown it: when it happened, and its parts."""
        if self.record is None:
            return {"exchange": self.handle, "held": False, "recalled_as": self.excerpt}
        return {
            "exchange": self.handle,
            "occurred_at": self.record.occurred_at.isoformat(),
            "parts": [one.rendered() for one in self.parts],
        }


@dataclass(frozen=True, slots=True)
class ReadMemory:
    """One memory the record points at, as it stood then (§2:2), or not held (§2:3).

    Attributes:
        handle: Its label (``M1``, ``M2``, ...).
        memory_id: Its id, exactly as held.
        then: The memory as it stood when the activation started; ``None`` where the
            store no longer holds it as it stood then.
        excerpt: Where it is not held, what a recall run kept of it, or ``None``.
    """

    handle: str
    memory_id: str
    then: Memory | None
    excerpt: str | None = None

    def rendered(self) -> dict[str, FrozenJson]:
        """The memory as the scout is shown it: its claim, standing and open questions."""
        memory = self.then
        if memory is None:
            return {"memory": self.handle, "held": False, "recalled_as": self.excerpt}
        return {
            "memory": self.handle,
            "claim": memory.content,
            "stands": STANDING_WORDS[memory.standing],
            "status": memory.status.value,
            "held_by": [holder_words(one) for one in memory.holders],
            "open_questions": [one.asks for one in memory.open_questions if not one.resolved],
        }


@dataclass(frozen=True, slots=True)
class ReadStory:
    """One story the record points at, with the summary it had then (ADR-0347 §4).

    Attributes:
        handle: Its label (``S1``, ``S2``, ...).
        story_id: Its id, exactly as held.
        summary: The lines of the summary it had then; ``None`` where none is held (§4:3).
        outside: That summary's mark (ADR-0303 §3:4).
    """

    handle: str
    story_id: str
    summary: tuple[str, ...] | None
    outside: bool = False

    def rendered(self) -> dict[str, FrozenJson]:
        """The story as the scout is shown it."""
        if self.summary is None:
            return {"story": self.handle, "held": False}
        return {
            "story": self.handle,
            "summary": list(self.summary),
            "summary_outside": self.outside,
        }


@dataclass(frozen=True, slots=True)
class ReadNote:
    """One story note planning was shown (ADR-0346 §2:1), never a part.

    Attributes:
        handle: Its label (``N1``, ``N2``, ...).
        text: What it says; ``None`` where the story store no longer shows it.
        outside: Its mark (ADR-0303 §3:1).
    """

    handle: str
    text: str | None
    outside: bool = True

    def rendered(self) -> dict[str, FrozenJson]:
        """The note as the scout is shown it."""
        if self.text is None:
            return {"note": self.handle, "held": False}
        return {"note": self.handle, "text": self.text, "outside": self.outside}


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
class Reading:
    """Everything the observer read for one leaving episode (ADR-0346 §2).

    Attributes:
        leaving: The leaving episode.
        understood: Its understanding's latest version, rendered (§2:5), or ``None``.
        recalled: The labels of what its recall runs returned, in the order returned.
        earlier: The episodes its record points at, oldest first, each with its parts,
            or by its identity alone where it is not held.
        memories: The memories its record points at, each as it stood then.
        stories: The stories its record points at, each with the summary it had then.
        notes: The story notes its planning labels name.
        hints: Its candidates.
        supplied: The placement of every record read, for the meet a write takes
            (ADR-0329 §12:6).
    """

    leaving: ReadEpisode
    understood: dict[str, FrozenJson] | None = None
    recalled: tuple[str, ...] = ()
    earlier: tuple[ReadEpisode, ...] = ()
    memories: tuple[ReadMemory, ...] = ()
    stories: tuple[ReadStory, ...] = ()
    notes: tuple[ReadNote, ...] = ()
    hints: tuple[Hint, ...] = ()
    supplied: tuple[Placement, ...] = ()
    _parts: dict[str, ReadPart] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index every part by its label, once."""
        for one in (self.leaving, *self.earlier):
            for part in one.parts:
                self._parts[part.handle] = part
        for hint in self.hints:
            if hint.confirmation is not None:
                self._parts[hint.confirmation.handle] = hint.confirmation

    @property
    def record(self) -> EpisodicMemory:
        """The leaving episode, as stored."""
        record = self.leaving.record
        if record is None:  # pragma: no cover - the reader reads a held episode
            msg = "the leaving episode is held"
            raise ValueError(msg)
        return record

    def part(self, handle: str) -> ReadPart | None:
        """The part a label names, or ``None``."""
        return self._parts.get(handle)

    def at(self, part: SupportPart) -> ReadPart | None:
        """The part read at ``part``'s address, or ``None`` where none was."""
        return next((one for one in self._parts.values() if one.part == part), None)

    @property
    def leaving_parts(self) -> frozenset[SupportPart]:
        """The leaving episode's parts, its confirmations included (ADR-0346 §3:1)."""
        own = {one.part for one in self.leaving.parts}
        own.update(hint.confirmation.part for hint in self.hints if hint.confirmation)
        return frozenset(own)

    def payload(self) -> dict[str, FrozenJson]:
        """What the scout is shown: one JSON object of quoted source data (§8:5).

        Returns:
            The object.
        """
        leaving = self.leaving.rendered()
        leaving["understood"] = self.understood
        leaving["recalled"] = list(self.recalled)
        leaving["candidates"] = [hint.rendered() for hint in self.hints]
        leaving["confirmations"] = [
            hint.confirmation.rendered() for hint in self.hints if hint.confirmation is not None
        ]
        return {
            "exchange": leaving,
            "earlier": [one.rendered() for one in self.earlier],
            "memories": [one.rendered() for one in self.memories],
            "stories": [one.rendered() for one in self.stories],
            "notes": [one.rendered() for one in self.notes],
        }


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


def input_origin(processing: EpisodeProcessingRecord, message: int | None) -> SupportOrigin:
    """The origin of a support pointing at an input, or one of its messages (ADR-0351 §7:2).

    The part's parties decide it, by ``core``'s one rule
    (:func:`~ai_assistant.core.types.input_support_origin`), which the writer checks
    too, so what the observer proposes is what the writer admits (§11:1): a part whose
    parties are the person's own takes ``user_message``, so your note beside a forward
    is yours, and one whose parties are outside takes ``outside_input``, a forward's
    included. A part of an input the latest understanding version marks relayed takes
    ``outside_input`` where the mark counts (§7:6).

    **A part whose parties are empty or include the assistant's statement takes none**
    (§7:3): a scheduled task's instruction, a marked task's included, is no part a
    support points at, so the reading offers no such part and this refuses one.

    Args:
        processing: The episode's processing record.
        message: The message's position, or ``None`` for the input as a whole.

    Returns:
        The origin.

    Raises:
        ValueError: If no support points at the part (§7:3).
    """
    return input_support_origin(processing, message)


def _offered(processing: EpisodeProcessingRecord, message: int | None) -> bool:
    """Whether a support may point at the input, or one of its messages (ADR-0351 §7:3)."""
    try:
        input_support_origin(processing, message)
    except ValueError:
        return False
    return True


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


def memory_then(memory: Memory, at: datetime) -> Memory | None:
    """``memory`` as it stood at ``at``, from its dated supports and log (ADR-0346 §2:2).

    The supports added at or before ``at``, the operations written at or before it, the
    status they leave, and the open questions raised by then, each open where it was
    resolved after. Its track record and labels are left out, since the scout is shown
    neither. A view, never written: it is built without validation, as a record the
    store held then.

    Args:
        memory: The memory, as the history read returns it now.
        at: The instant asked about.

    Returns:
        The memory as it stood, or ``None`` where it was not yet created at ``at``.
    """
    operations = tuple(one for one in memory.operations if one.at <= at)
    if not operations or operations[0].kind is not MemoryOperationKind.CREATE:
        return None
    supports = tuple(one for one in memory.supports if one.added_at <= at)
    questions = tuple(
        _question_then(one, at) for one in memory.open_questions if one.raised_at <= at
    )
    status = MemoryStatus.CURRENT
    for one in operations[1:]:
        if one.kind in {MemoryOperationKind.END, MemoryOperationKind.REPLACE}:
            status = MemoryStatus.ENDED
        elif one.kind is MemoryOperationKind.MARK_WRONG:
            status = MemoryStatus.WRONG
    return memory.model_copy(
        update={
            "supports": supports,
            "operations": operations,
            "open_questions": questions,
            "status": status,
            "track_record": (),
            "labels": (),
        }
    )


def _question_then(question: OpenQuestion, at: datetime) -> OpenQuestion:
    """An open question as it stood at ``at``: open where it was resolved after."""
    if question.resolved_at is None or question.resolved_at <= at:
        return question
    return question.model_copy(
        update={"resolved_at": None, "resolved_by": None, "resolution": None}
    )


class _Labels:
    """Hands out each kind's next label, once per thing."""

    def __init__(self) -> None:
        self._next: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        number = self._next.get(prefix, 0) + 1
        self._next[prefix] = number
        return f"{prefix}{number}"


@dataclass(slots=True)
class _Pointed:
    """The ids the leaving episode's record points at, each once, in the order met."""

    episodes: dict[str, None] = field(default_factory=dict)
    memories: dict[str, None] = field(default_factory=dict)
    stories: dict[str, None] = field(default_factory=dict)
    notes: dict[str, None] = field(default_factory=dict)
    recalled: dict[str, RecalledItem] = field(default_factory=dict)
    order: list[tuple[str, str]] = field(default_factory=list)

    def add(self, kind: str, record_id: str | None) -> None:
        if not record_id:
            return
        held = {
            "episode": self.episodes,
            "memory": self.memories,
            "story": self.stories,
            "note": self.notes,
        }[kind]
        if record_id not in held:
            held[record_id] = None
            self.order.append((kind, record_id))


def _pointed_at(leaving: EpisodicMemory, processing: EpisodeProcessingRecord) -> _Pointed:  # noqa: C901 — one arm per pointer ADR-0346 §2:1 names
    """What the leaving episode's record points at (ADR-0346 §2:1), its own id left out."""
    pointed = _Pointed()
    for run in (processing.recall, processing.recall_second_run):
        for item in () if run is None else run.items:
            kind = "episode" if item.kind is MemoryKind.EPISODIC else "memory"
            pointed.recalled.setdefault(item.id, item)
            pointed.add(kind, item.id)
            for story in item.stories:
                pointed.add("story", story)
    by_label = {
        LabelKind.STORY: "story",
        LabelKind.EPISODE: "episode",
        LabelKind.NOTE: "note",
        LabelKind.MEMORY: "memory",
    }
    for label in processing.labels:
        named = by_label.get(label.kind)
        if named is not None:
            pointed.add(named, label.id)
    for understood in processing.understanding:
        for referent in _referents(understood):
            if referent.kind in {"episode", "memory", "story"}:
                pointed.add(referent.kind, referent.id)
        for link in understood.story_links:
            if link.kind is StoryMemberKind.STORY:
                pointed.add("story", link.id)
            else:
                pointed.add("episode", episode_address(link.id))
        for answer in understood.answers:
            pointed.add("episode", episode_address(answer.activation_id))
    pointed.episodes.pop(leaving.id, None)
    pointed.order = [(kind, one) for kind, one in pointed.order if one != leaving.id]
    return pointed


def _referents(understood: ActivationUnderstanding) -> tuple[UnderstandingReferent, ...]:
    """Every referent an understanding version resolved, its meaning's first."""
    return (
        *understood.meaning_referents,
        *(one for reference in understood.references for one in reference.referents),
        *(one for relationship in understood.relationships for one in relationship.referents),
    )


class EpisodeReader:
    """Reads what ADR-0346 §2:1 names of one leaving episode, from the stores it holds."""

    def __init__(self, *, memory: MemoryStore, plans: PlanStore, stories: StoryStore) -> None:
        """Wire the reader to its stores.

        Args:
            memory: The memory store episodes and memories are read from.
            plans: The plan store effect records are read from.
            stories: The story store a story's summaries and notes are read from.
        """
        self._memory = memory
        self._plans = plans
        self._stories = stories

    async def read(self, leaving: EpisodicMemory) -> Reading:
        """Read the leaving episode's record and what it points at (ADR-0346 §2).

        Args:
            leaving: The leaving episode, frozen, with a processing record.

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
        then = processing.started_at
        pointed = _pointed_at(leaving, processing)
        found = without_open_episodes(await self._memory.get_many(list(pointed.episodes)))
        held = sorted(
            (
                record
                for one in pointed.episodes
                if isinstance(record := found.get(one), EpisodicMemory) and _readable(record)
            ),
            key=lambda record: (record.occurred_at, record.id),
        )
        # §2:2: nothing after the episode is shown, so an episode that occurred after
        # it is left out whole, never shown in its place.
        earlier_records = [one for one in held if one.occurred_at <= leaving.occurred_at]
        later = {one.id for one in held if one.occurred_at > leaving.occurred_at}
        history = await self._memory.get_history(list(pointed.memories))
        labels = _Labels()
        shown = _Shown(labels, await self._outsides_of([leaving, *earlier_records]))
        answers = _answers([leaving, *earlier_records])
        read_leaving = shown.episode(leaving, answers)
        earlier = [shown.episode(one, answers) for one in earlier_records]
        handles = {one.episode: one.handle for one in earlier}
        handles[leaving.id] = read_leaving.handle
        for episode_id in pointed.episodes:
            if episode_id not in handles and episode_id not in later:
                item = pointed.recalled.get(episode_id)
                gone = ReadEpisode(
                    handle=labels("E"),
                    episode=episode_id,
                    record=None,
                    excerpt=None if item is None else item.excerpt,
                )
                earlier.append(gone)
                handles[episode_id] = gone.handle
        memories: list[ReadMemory] = []
        for memory_id in pointed.memories:
            stored = history.get(memory_id)
            as_then = None if stored is None else memory_then(stored, then)
            item = pointed.recalled.get(memory_id)
            memories.append(
                ReadMemory(
                    handle=labels("M"),
                    memory_id=memory_id,
                    then=as_then,
                    excerpt=None if as_then is not None or item is None else item.excerpt,
                )
            )
        stories = [
            await self._story(labels("S"), story_id, processing.stories_position)
            for story_id in pointed.stories
        ]
        notes = await self._notes(pointed.notes, processing, labels)
        effects = await self._plans.activation_effects([processing.activation_id])
        memory_handles = {one.memory_id: one.handle for one in memories}
        hints = await self._hints(leaving, processing, effects, shown, memory_handles, labels)
        handles.update(memory_handles)
        handles.update((one.story_id, one.handle) for one in stories)
        supplied = [leaving.placement, *(one.placement for one in earlier_records)]
        supplied.extend(one.then.placement for one in memories if one.then is not None)
        # A story's summary or note supplies a record placed for the owner alone,
        # whoever wrote it (ADR-0304 §4:1), so what is written over it inherits that reach.
        supplied.extend(_OWNER_ONLY for one in stories if one.summary is not None)
        supplied.extend(_OWNER_ONLY for one in notes if one.text is not None)
        return Reading(
            leaving=read_leaving,
            understood=_understood(processing, handles, read_leaving),
            recalled=tuple(
                handles[item] for item in pointed.recalled if item in handles and item != leaving.id
            ),
            earlier=tuple(earlier),
            memories=tuple(memories),
            stories=tuple(stories),
            notes=notes,
            hints=hints,
            supplied=tuple(supplied),
        )

    async def _story(self, handle: str, story_id: str, position: int | None) -> ReadStory:
        """A story with the summary of its latest version at or below ``position``.

        ADR-0347 §4:2-§4:3: read through ``summary_at``; by its identity alone where the
        episode records no position, no version lies at or below it, or no text is held.
        """
        if position is None:
            return ReadStory(handle=handle, story_id=story_id, summary=None)
        latest: int | None = None
        cursor: int | None = None
        while True:
            try:
                page = await self._stories.summary_versions(
                    story_id, cursor=cursor, limit=MAX_STORY_PAGE
                )
            except ValueError:
                page = None  # an id as a referent kept it, which names no story
            if page is None:
                break
            for one in page.versions:
                if one.version <= position and (latest is None or one.version > latest):
                    latest = one.version
            if page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        summary = None if latest is None else await self._stories.summary_at(story_id, latest)
        if summary is None:
            return ReadStory(handle=handle, story_id=story_id, summary=None)
        return ReadStory(
            handle=handle,
            story_id=story_id,
            summary=tuple(line.text for line in summary.lines),
            outside=summary.outside,
        )

    async def _notes(
        self,
        wanted: Mapping[str, None],
        processing: EpisodeProcessingRecord,
        labels: _Labels,
    ) -> tuple[ReadNote, ...]:
        """The notes planning was shown, each as the story store holds it (§2:1).

        A note is never edited and its mark never changes (ADR-0303 §3:1), so it is as it
        stood then; one the store no longer shows is shown by its identity alone.
        """
        if not wanted:
            return ()
        held = {
            str(one.note_id): one
            for one in await _shown_notes(self._stories, set(wanted), [processing.activation_id])
        }
        notes: list[ReadNote] = []
        for note_id in wanted:
            note = held.get(note_id)
            notes.append(
                ReadNote(
                    handle=labels("N"),
                    text=None if note is None else note.text,
                    outside=True if note is None else note.outside,
                )
            )
        return tuple(notes)

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

    async def _hints(  # noqa: PLR0913 — what the hints are mapped against, each read once already
        self,
        leaving: EpisodicMemory,
        processing: EpisodeProcessingRecord,
        effects: Sequence[ActivationEffect],
        shown: _Shown,
        memories: Mapping[str, str],
        labels: _Labels,
    ) -> tuple[Hint, ...]:
        """The leaving episode's candidates, as hints (ADR-0329 §3:3, §9:1)."""
        hints: list[Hint] = []
        for done in done_candidates(leaving.id, processing, effects):
            try:
                candidate = candidate_of(done.values)
            except ValueError:
                hints.append(Hint(handle=labels("C"), effect=done.effect, fact=done.fact))
                continue
            hints.append(
                Hint(
                    handle=labels("C"),
                    effect=done.effect,
                    fact=candidate.fact,
                    why=candidate.why,
                    rests_on=shown.resting_on(candidate, leaving),
                    memory=None if candidate.memory is None else memories.get(candidate.memory),
                    note=candidate.note,
                )
            )
        hints.extend(await self._approved(leaving, processing, effects, shown, labels))
        return tuple(hints)

    async def _approved(
        self,
        leaving: EpisodicMemory,
        processing: EpisodeProcessingRecord,
        effects: Sequence[ActivationEffect],
        shown: _Shown,
        labels: _Labels,
    ) -> list[Hint]:
        """The candidates recorded under an approval in the leaving episode (§3:3, §5:5).

        A ``remember`` run under an approval is proposed by its approved-action label, so
        its candidate is the asked call the effect record's question part names, as the
        asking round records it. The asking activation is the one the input's recorded
        answer pointers name whose round is that part's round: the question the input
        answers, which ADR-0346 §2:1 names among what the record points at.
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


def _answers(records: Sequence[EpisodicMemory]) -> dict[str, str]:
    """What each read episode's input replies to, by its recorded answer pointers (§5:1).

    For each episode read, the question its own understanding recorded its input as
    answering (ADR-0321 §3:1), named by its asking activation and round: that round's
    message, where the asking episode is among those read. Nothing else is taken for one:
    an episode's place among those the record points at says nothing of what came
    between, so no adjacency is guessed, and an input that answers no recorded question is
    shown answering nothing (§2:4).
    """
    read = {one.id: one for one in records}
    answers: dict[str, str] = {}
    for record in records:
        processing = record.processing_record
        if processing is None or not processing.understanding:
            continue
        latest = max(processing.understanding, key=lambda one: one.version)
        for answer in latest.answers:
            asking = read.get(episode_address(answer.activation_id))
            asked = None if asking is None else asking.processing_record
            if asked is None or answer.round is None:
                continue
            said = next((one.text for one in asked.rounds if one.id == answer.round), None)
            if said:
                answers[record.id] = said
                break
    return answers


def _understood(
    processing: EpisodeProcessingRecord, handles: Mapping[str, str], leaving: ReadEpisode
) -> dict[str, FrozenJson] | None:
    """The understanding's latest version, rendered (ADR-0346 §2:5).

    Its meaning and ground, its references with what each resolved to, its
    relationships, what it left unresolved, and the questions its input answers. A
    referent the reading holds is named by its label; any other by its kind and the
    excerpt the record kept.
    """
    if not processing.understanding:
        return None
    latest = max(processing.understanding, key=lambda one: one.version)

    def referent(one: UnderstandingReferent) -> dict[str, FrozenJson]:
        label = None
        if one.kind == "input":
            label = leaving.handle
        elif one.id is not None:
            label = handles.get(one.id)
        return {"kind": one.kind, "label": label, "excerpt": one.excerpt}

    return {
        "meaning": latest.meaning,
        "ground": latest.meaning_ground.value,
        "meaning_rests_on": [referent(one) for one in latest.meaning_referents],
        "references": [
            {"phrase": one.phrase, "resolved_to": [referent(r) for r in one.referents]}
            for one in latest.references
        ],
        "relationships": [
            {
                "statement": one.statement,
                "ground": one.ground.value,
                "rests_on": [referent(r) for r in one.referents],
            }
            for one in latest.relationships
        ],
        "unresolved": [
            {"matter": one.matter, "why_it_matters": one.why_it_matters}
            for one in latest.unresolved
        ],
        "answers": [handles.get(episode_address(one.activation_id)) for one in latest.answers],
    }


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


def _readable(record: EpisodicMemory) -> bool:
    """Whether an episode is read as parts: frozen, with a processing record."""
    processing = record.processing_record
    return processing is not None and not processing.is_open


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
        """One episode and its parts, each labelled (ADR-0329 §8:6)."""
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
        return ReadEpisode(handle=handle, episode=record.id, record=record, parts=tuple(parts))

    def _inputs(
        self, record: EpisodicMemory, processing: EpisodeProcessingRecord, answers: str | None
    ) -> list[ReadPart]:
        """The input, or each message it took in (ADR-0328 §4:4, §4:12).

        None where the input's parties are empty or include the assistant's statement
        (ADR-0351 §7:3, in place of ADR-0350 §6:11's ``assistant`` origin): a scheduled
        task's instruction, a marked task's included, is no part a support points at, so
        a support of such an episode points at another part of it, such as a round's
        message. Each part offered takes the origin its parties give (§7:2).
        """
        trigger = processing.trigger
        if not _offered(processing, None):
            return []
        if trigger.messages:
            return [
                self._part(
                    InputPart(episode=record.id, message=index),
                    episode=record,
                    text=one.text,
                    origin=input_origin(processing, index),
                    when=one.sent_at,
                    answers=answers,
                )
                for index, one in enumerate(trigger.messages)
                if one.text and _offered(processing, index)
            ]
        text = episode_text(record)
        if not text:
            return []
        return [
            self._part(
                InputPart(episode=record.id),
                episode=record,
                text=text,
                origin=input_origin(processing, None),
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
        the evidence items of the digests of that result (ADR-0329 §9:6). A part the
        reading did not read is not named.
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
