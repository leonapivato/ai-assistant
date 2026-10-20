"""The commit step: one model call per finding, and the checks code makes (ADR-0329 §9-§11).

**What the step is shown** (§9:3): only the finding's claim; the parts it rests on, each
with the message it answers where it is a reply; and the memories the observer's search
finds similar to the claim, with their supports and open questions. A reliance finding
is shown the reliance call and the memory it named as well (§14:2). Nothing else of the
reading reaches it, so a manipulated or confused scout can propose, but cannot launder
content into a memory it does not rest on.

**What it decides** (§9:4): the memory's wording, which supports to add and, for each,
its direction, whether it backs the claim as worded, how sure the reading is, its
about-when and its note; and which of ADR-0328 §5's operations to apply, or that nothing
is kept. Its decisions follow §§10-11, which its instruction states.

**What code sets and checks** (§9:5), never a model: each support's origin, its
``when``, its source details and its added at and by; that every part a support points
at is one the finding rests on, read from a stored episode; the admission of the
assistant's own words (§10:1); §9:7's rule for an observer's inference; §11:5's floor;
and, before a retirement is proposed, ADR-0328 §6:5's refusal of a lower standing, which
raises a ``conflict`` question instead (§13:1); and that the leaving episode carries the
write (§8:2). A decision that fails a check is not
written, and the finding's outcome says so. Source details are carried only where the
records a support points at state them (ADR-0328 §4:13), and no part the observer reads
records an ``Attestation``, so it sets none.

**The admission of the assistant's own words** (§10) is held on every memory, not only
one about the user: code cannot tell what a claim is about, so it takes the stricter
reading. A support pointing at a round's message is admitted only beside a ``for``
support pointing at the user's own message in a later episode than that round's, which
is the leaving episode or one after it, as the step's note on it says the user asked to
keep or confirmed what the message said. Without one, the decision is refused whole.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from ai_assistant.core.types import (
    BeliefBand,
    ConfirmationPart,
    EpisodicMemory,
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemoryStanding,
    MemorySupport,
    MemoryWriterName,
    Message,
    ObserverInferencePart,
    OpenQuestionKind,
    Placement,
    ReadingCertainty,
    Role,
    SupportDirection,
    SupportOrigin,
    TrackRecordEntry,
    origin_standing,
    part_episode,
    standing_rank,
)
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.observer.reading import ORIGIN_WORDS, STANDING_WORDS
from ai_assistant.orchestration.support_parts import (
    episodes_to_read,
    part_content,
    remember_activations,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        FrozenJson,
        ObservationFinding,
        SupportPart,
    )
    from ai_assistant.orchestration.observer.reading import (
        EpisodeReader,
        Reading,
        ReadPart,
        Reliance,
    )

__all__ = [
    "INFERENCE_FLOOR",
    "AddSupports",
    "Blocked",
    "Checked",
    "CommitReply",
    "CommitView",
    "Create",
    "RaiseQuestion",
    "RecordUse",
    "Resolve",
    "Similar",
    "Unwritten",
    "checked",
    "commit_messages",
    "commit_view",
    "meets_floor",
    "narrows",
]

#: §11:5: the distinct episodes an inference's counted ``for`` supports, other than an
#: observer's inference, point at, at least.
INFERENCE_FLOOR: Final = 3

#: Why the observer proposes a memory, on every proposal it makes: code-owned words.
_RATIONALE: Final = "the observer kept this from an episode that left the episode window"

_ASSISTANT_ORIGINS: Final = frozenset(
    {SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE}
)

_RETIRING: Final[dict[str, MemoryOperationKind]] = {
    "end": MemoryOperationKind.END,
    "mark_wrong": MemoryOperationKind.MARK_WRONG,
    "replace": MemoryOperationKind.REPLACE,
}

#: What a ``conflict`` question asks, in words, before the newer claim it carries.
_CONFLICT_ASKS: Final = "Newer evidence, at a lower standing than this memory's, says: "

type _Certainty = Literal["sure", "likely", "unsure"]


class _ProposedSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    part: str
    direction: Literal["for", "against"]
    backs_as_worded: bool = False
    how_sure: _Certainty
    about_when: AwareDatetime | None = None
    note: str = ""


class _ProposedInference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    how_sure: _Certainty
    note: str = ""


class _ProposedResolve(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    memory: str
    question: str
    part: str
    note: str


class CommitReply(BaseModel):
    """The commit step's whole reply (its instruction's shape).

    A key this shape, or a shape nested in it, does not name is dropped, as the scout's
    reply drops one: the fields it names are validated as before, so a missing required
    field or a value of the wrong kind still fails the reply whole.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    action: Literal[
        "create",
        "add",
        "end",
        "mark_wrong",
        "replace",
        "recheck",
        "single_observation",
        "nothing",
    ] = "nothing"
    wording: str | None = None
    memory: str | None = None
    supports: tuple[_ProposedSupport, ...] = ()
    inference: _ProposedInference | None = None
    cites: str | None = None
    asks: str | None = None
    resolves: _ProposedResolve | None = None
    track_record: Literal["held_up", "let_down", "neither"] | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class Similar:
    """One stored memory the commit step is shown, under its label (§9:3).

    Attributes:
        handle: Its label (``M1``, ``M2``, ...).
        memory: The memory, as read.
        supports: Each support's part resolved to readable content, or ``None`` for gone.
        questions: Its open questions' ids, by the labels they are shown under.
    """

    handle: str
    memory: Memory
    supports: tuple[str | None, ...]
    questions: dict[str, str] = field(default_factory=dict)

    def rendered(self) -> dict[str, FrozenJson]:
        """The memory as the commit step is shown it, attributed from the record."""
        stopped = self.memory.stopped
        open_ = {question_id: handle for handle, question_id in self.questions.items()}
        return {
            "memory": self.handle,
            "claim": self.memory.content,
            "stands": STANDING_WORDS[self.memory.standing],
            "status": self.memory.status.value,
            "supports": [
                {
                    "from": ORIGIN_WORDS[support.origin],
                    "outside": support.outside,
                    "direction": support.direction.value,
                    "backs_as_worded": support.backs_as_worded,
                    "counted": support.points_at not in stopped,
                    "at": None if support.when is None else support.when.isoformat(),
                    "text": "(gone)" if text is None else text,
                }
                for support, text in zip(self.memory.supports, self.supports, strict=True)
            ],
            "open_questions": [
                {"question": open_[one.id], "asks": one.asks}
                for one in self.memory.open_questions
                if one.id in open_
            ],
        }


@dataclass(frozen=True, slots=True)
class CommitView:
    """Exactly what one commit call is shown, kept so its labels map back (§9:3).

    Attributes:
        finding: The finding.
        leaving: The leaving episode.
        parts: The parts the finding rests on, as read.
        similar: The memories shown.
        reliance: The reliance call a reliance finding is about.
        yes_inputs: For each yes a confirmation part names, the yes's input, which a
            question rests on in the confirmation's place (§13:2). Not shown.
        supplied: The placement of every record the call is supplied beyond the
            reading: the memories, the episodes their supports were resolved from, and
            any part read again (§12:6).
    """

    finding: ObservationFinding
    leaving: EpisodicMemory
    parts: tuple[ReadPart, ...]
    similar: tuple[Similar, ...]
    reliance: Reliance | None = None
    yes_inputs: dict[str, ReadPart] = field(default_factory=dict)
    supplied: tuple[Placement, ...] = ()

    def part(self, handle: str) -> ReadPart | None:
        """The part a label names, among those shown."""
        return next((one for one in self.parts if one.handle == handle), None)

    def memory(self, handle: str | None) -> Similar | None:
        """The memory a label names, among those shown."""
        return next((one for one in self.similar if one.handle == handle), None)

    def payload(self) -> dict[str, FrozenJson]:
        """What the commit step is shown: one JSON object of quoted source data (§8:5)."""
        shown: dict[str, FrozenJson] = {
            "claim": self.finding.claim,
            "parts": [one.rendered(answers=True) for one in self.parts],
            "memories": [one.rendered() for one in self.similar],
        }
        if self.reliance is not None:
            held = next(one for one in self.similar if one.memory.id == self.reliance.memory.id)
            shown["relied_on"] = {"memory": held.handle, "shaped": self.reliance.shaped}
        return shown


@dataclass(frozen=True, slots=True)
class Create:
    """A new memory proposed through ``ingest``, retiring at most one (§12:2, §12:4).

    ``asked_on`` is the support a ``policy_ask`` question rests on, where the policy
    asks (§13:1-§13:2): the new memory's leading support, ``against``, never a
    confirmation or an inference; ``None`` where none can be.
    """

    memory: Memory
    retiring: MemoryRetirement | None = None
    asked_on: MemorySupport | None = None
    rationale: str = _RATIONALE


@dataclass(frozen=True, slots=True)
class AddSupports:
    """Supports added to a memory that states the claim as worded (§12:3)."""

    target: Memory
    supports: tuple[MemorySupport, ...]


@dataclass(frozen=True, slots=True)
class RaiseQuestion:
    """An open question raised on a memory (§13:1), resting on one support (§13:2)."""

    target: Memory
    kind: OpenQuestionKind
    asks: str
    support: MemorySupport


@dataclass(frozen=True, slots=True)
class Resolve:
    """An open question resolved by the support added from the user's answer (§13:5)."""

    target: Memory
    question: str
    support: MemorySupport
    note: str


@dataclass(frozen=True, slots=True)
class RecordUse:
    """A track-record entry on a memory a reliance named (§14:1-§14:4)."""

    memory: Memory
    entry: TrackRecordEntry


@dataclass(frozen=True, slots=True)
class Unwritten:
    """Nothing to write, and the code-owned reason why (§16:1)."""

    reason: FindingUnwritten


@dataclass(frozen=True, slots=True)
class Blocked:
    """A write the supply's placement keeps off a wider stored memory (§12:6).

    An operation writes no placement (ADR-0328 §5:2), so a question, a resolution or an
    entry resting on a supply narrower than the memory it would be written on cannot be
    written without widening that supply. It is not dropped: the attempt fails, and the
    finding is retried and in the end set aside as stuck, kept for an explicit re-run
    (§16:4-§16:5).
    """


type _Primary = Create | AddSupports | RaiseQuestion | RecordUse | Unwritten | Blocked


@dataclass(frozen=True, slots=True)
class Checked:
    """A commit decision after code's checks: what to write (§9:5).

    Attributes:
        primary: The one write the decision makes, or why it makes none.
        resolve: A question the decision resolves beside it (§13:5), or ``None``.
    """

    primary: _Primary
    resolve: Resolve | None = None


async def commit_view(  # noqa: PLR0913 — the finding, what it is read against, and the stores
    finding: ObservationFinding,
    reading: Reading,
    *,
    reader: EpisodeReader,
    memory: MemoryStore,
    plans: PlanStore,
    similar: int,
) -> CommitView | None:
    """What one commit call is shown for ``finding`` (§9:3).

    Each part the finding rests on is taken from the reading, or read again from the
    store by its address where the reading no longer holds it: a finding recorded in an
    earlier attempt keeps what it rests on however the window has moved since (§16:4).
    The parts are labelled afresh for the call, ``P1`` to ``Pn``, since the call sees
    only them.

    Args:
        finding: The finding.
        reading: This attempt's reading.
        reader: Reads a part again by its address.
        memory: The memory store the similar memories are searched in.
        plans: The plan store a remember call's effect record is read from.
        similar: The most memories the search returns.

    Returns:
        The view, or ``None`` where a part it rests on no longer resolves in a stored
        episode, or the memory a reliance finding names is not read: either fails
        §9:5's check.

    Raises:
        MemoryStoreError: If the memory store cannot be read.
        PlanningError: If the plan store cannot be read.
    """
    reliance = None if finding.relied_on is None else reading.reliance(finding.relied_on)
    if finding.relied_on is not None and reliance is None:
        return None
    yes_inputs = {
        part.episode: InputPart(episode=part.episode)
        for part in finding.rests_on
        if isinstance(part, ConfirmationPart)
    }
    wanted = (*finding.rests_on, *yes_inputs.values())
    held = {part: read for part in wanted if (read := reading.at(part)) is not None}
    supplied: list[Placement] = []
    missing = [part for part in wanted if part not in held]
    if missing:
        again = await reader.parts_at(missing)
        held.update(again.parts)
        supplied.extend(again.supplied)
    if any(part not in held for part in finding.rests_on):
        return None
    parts = tuple(
        replace(held[part], handle=f"P{index}")
        for index, part in enumerate(finding.rests_on, start=1)
    )
    found = await memory.search(finding.claim, limit=similar, kinds=(MemoryKind.MEMORY,))
    memories = [one for one in found.records if isinstance(one, Memory)]
    # §9:3: the memories the search finds, and for a reliance the memory it named (§14:2);
    # a candidate's named memory reaches the step only where the search finds it too.
    named = [] if reliance is None else [reliance.memory]
    for one in named:
        if all(present.id != one.id for present in memories):
            memories.append(one)
    shown, episodes = await _resolved(memories, memory=memory, plans=plans)
    supplied.extend(one.memory.placement for one in shown)
    supplied.extend(episodes)
    return CommitView(
        finding=finding,
        leaving=reading.leaving.record,
        parts=parts,
        similar=shown,
        reliance=reliance,
        yes_inputs={episode: held[part] for episode, part in yes_inputs.items() if part in held},
        supplied=tuple(supplied),
    )


async def _resolved(
    memories: Sequence[Memory], *, memory: MemoryStore, plans: PlanStore
) -> tuple[tuple[Similar, ...], tuple[Placement, ...]]:
    """Each memory with its supports' parts resolved to readable content (ADR-0328 §15:2).

    Returns:
        The memories as shown, and the placement of every episode read to resolve their
        supports, which the commit call is supplied with them (§12:6).
    """
    if not memories:
        return (), ()
    # ADR-0286 §6:4: an open episode, an asking one among them, has no readable record.
    found = without_open_episodes(await memory.get_many(list(episodes_to_read(memories))))
    episodes = {key: one for key, one in found.items() if isinstance(one, EpisodicMemory)}
    activations = remember_activations(memories, episodes)
    effects: dict[str, ActivationEffect] = {}
    if activations:
        effects = {one.id: one for one in await plans.activation_effects(list(activations))}
    shown: list[Similar] = []
    asked = 0
    for index, one in enumerate(memories, start=1):
        questions: dict[str, str] = {}
        for question in one.open_questions:
            if not question.resolved:
                asked += 1
                questions[f"Q{asked}"] = question.id
        shown.append(
            Similar(
                handle=f"M{index}",
                memory=one,
                supports=tuple(
                    part_content(
                        support.points_at,
                        episodes=episodes,
                        effects=effects,
                        carried=support.carries,
                    )
                    for support in one.supports
                ),
                questions=questions,
            )
        )
    return tuple(shown), tuple(one.placement for one in episodes.values())


def commit_messages(view: CommitView, instruction: RenderedPrompt) -> list[Message]:
    """The commit step's one call for a finding: its instruction and what it is shown.

    Args:
        view: What the call is shown.
        instruction: ``OBSERVER_COMMIT_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5); the
            call's given entry records its ``prompt`` key (ADR-0335 §9:1).

    Returns:
        The conversation the commit step's route completes.
    """
    return [
        Message(role=Role.SYSTEM, content=instruction.text),
        Message(role=Role.USER, content=json.dumps(view.payload(), ensure_ascii=True)),
    ]


def meets_floor(memory: Memory) -> bool:
    """Whether a memory clears §11:5's evidence floor, as code checks it.

    A memory whose standing is above inference needs no bar (§11:7). One at inference
    alone needs its counted ``for`` supports, other than an observer's inference and a
    round's message (which counts toward no evidence bar, §10:2), to point at
    :data:`INFERENCE_FLOOR` distinct episodes at least, and fewer counted ``against``
    supports than ``for`` ones.

    Args:
        memory: The memory as it would be created.

    Returns:
        Whether it may be created.
    """
    if memory.standing is not MemoryStanding.INFERENCE:
        return True
    return _clears_floor(memory.counted_supports)


def _floor_episodes(supports: Iterable[MemorySupport]) -> set[str]:
    """The distinct episodes §11:5's floor counts among ``supports``.

    Those its ``for`` supports point at, other than an observer's inference and a
    round's message, which counts toward no evidence bar (§10:2).
    """
    return {
        episode
        for one in supports
        if one.direction is SupportDirection.FOR
        and one.origin is not SupportOrigin.OBSERVER_INFERENCE
        and one.origin not in _ASSISTANT_ORIGINS
        and (episode := part_episode(one.points_at)) is not None
    }


def _clears_floor(counted: Sequence[MemorySupport]) -> bool:
    """§11:5 over ``counted``: enough distinct episodes, and fewer ``against`` than ``for``."""
    supporting = [one for one in counted if one.direction is SupportDirection.FOR]
    against = [one for one in counted if one.direction is SupportDirection.AGAINST]
    return len(_floor_episodes(supporting)) >= INFERENCE_FLOOR and len(against) < len(supporting)


def _strength(support: MemorySupport) -> int:
    """How strongly a support bears on a claim: backing it as worded, for it, or against."""
    if support.direction is SupportDirection.AGAINST:
        return 0
    return 2 if support.backs_as_worded else 1


def _carried(supports: Iterable[MemorySupport], context: _Context, *, creates: bool) -> None:
    """§8:2: a write the leaving episode carries, never one new in another episode.

    The observer commits only findings that come from the leaving episode, and
    inferences it completes; a later episode only corrects or qualifies such a finding,
    and what is new in it waits until it is due. So the leaving episode holds a support
    of every write, and:

    - a new memory's claim comes from the leaving episode: one of its supports pointing
      at the leaving episode is ``for`` the claim, and no other episode's is ``for`` it
      more strongly, backing it as worded where the leaving episode's does not;
    - on any write, where the leaving episode holds a ``for`` support, no later
      episode's is ``for`` the claim more strongly. A support against what the leaving
      episode is for corrects it, and one for what the leaving episode is only against
      qualifies it, so neither is compared.

    A round's message of another episode is not compared, since it counts only through
    the user's keep beside it (§10:1-§10:2), which is compared in its place; nor is an
    observer's inference, code's own reading of the others.

    Raises:
        _Refused: ``check_failed`` where the leaving episode does not carry the write.
    """
    leaving = context.view.leaving
    own: list[MemorySupport] = []
    other: list[MemorySupport] = []
    for one in supports:
        if one.origin is SupportOrigin.OBSERVER_INFERENCE:
            continue
        if part_episode(one.points_at) == leaving.id:
            own.append(one)
        elif one.origin not in _ASSISTANT_ORIGINS and one.direction is SupportDirection.FOR:
            other.append(one)
    strongest = max(
        (_strength(one) for one in own if one.direction is SupportDirection.FOR), default=None
    )
    if not own or (creates and strongest is None):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    compared = other if creates else _later(other, context)
    if strongest is not None and any(_strength(one) > strongest for one in compared):
        raise _Refused(FindingUnwritten.CHECK_FAILED)


def _later(supports: Sequence[MemorySupport], context: _Context) -> list[MemorySupport]:
    """The supports pointing at an episode after the leaving one, by ``(occurred_at, id)``.

    A support whose part the view does not hold is counted as later, failing closed.
    """
    leaving = context.view.leaving
    key = (leaving.occurred_at, leaving.id)
    occurred = {one.part: (one.occurred_at, one.episode) for one in context.view.parts}
    return [one for one in supports if (at := occurred.get(one.points_at)) is None or at > key]


def _completed(memory: Memory, context: _Context) -> bool:
    """§8:2: whether the leaving episode completes an inference.

    It does where §11:5's floor holds over the supports pointing at the leaving
    episode and the episodes before it, the leaving episode among those it counts. A
    later episode's support qualifies the inference but never completes it: what it
    adds waits until that episode is due.
    """
    leaving = context.view.leaving
    key = (leaving.occurred_at, leaving.id)
    occurred = {one.part: (one.occurred_at, one.episode) for one in context.view.parts}
    by_then = [
        one
        for one in memory.counted_supports
        if (at := occurred.get(one.points_at)) is not None and at <= key
    ]
    return leaving.id in _floor_episodes(by_then) and _clears_floor(by_then)


@dataclass(frozen=True, slots=True)
class _Context:
    """What every check of one decision reads: the view, the instant and the minter."""

    view: CommitView
    now: datetime
    mint: Callable[[], str]
    placement: Placement


class _Blocked(Exception):  # noqa: N818 — a control-flow signal: the whole decision is blocked
    pass


class _Refused(Exception):  # noqa: N818 — a control-flow signal carrying a code-owned reason
    def __init__(self, reason: FindingUnwritten) -> None:
        super().__init__(reason.value)
        self.reason = reason


def checked(
    reply: CommitReply,
    view: CommitView,
    *,
    now: datetime,
    mint: Callable[[], str],
    placement: Placement,
) -> Checked:
    """A commit decision after every check code makes (§9:5, §10, §11:5, §13:1).

    Args:
        reply: The commit step's parsed reply.
        view: What it was shown.
        now: The instant every support, operation and entry is stamped with.
        mint: Mints a fresh id for a new memory or question.
        placement: The narrowest placement over every record the run was supplied
            (§12:6).

    Returns:
        What to write, or why nothing is.
    """
    context = _Context(view=view, now=now, mint=mint, placement=placement)
    if view.reliance is not None:
        return Checked(primary=_track_record(reply, context))
    try:
        supports = _supports(reply, context)
        _admitted(supports, context)
        primary = _primary(reply, supports, context)
        resolve = _resolve(reply, supports, context)
    except _Refused as refused:
        return Checked(primary=Unwritten(refused.reason))
    except _Blocked:
        return Checked(primary=Blocked())
    return Checked(primary=primary, resolve=resolve)


def _track_record(reply: CommitReply, context: _Context) -> _Primary:
    """§14:2: held up, let down, or nothing recorded."""
    reliance = context.view.reliance
    if reliance is None or reply.track_record in {None, "neither"}:
        return Unwritten(FindingUnwritten.NOT_KEPT)
    if narrows(context.placement, reliance.memory):
        return Blocked()
    entry = TrackRecordEntry(
        episode=context.view.leaving.id,
        relied_at=reliance.relied_at,
        held_up=reply.track_record == "held_up",
        note=reply.note,
        recorded_at=context.now,
        recorded_by=MemoryWriterName.OBSERVER,
    )
    return RecordUse(memory=reliance.memory, entry=entry)


def _supports(reply: CommitReply, context: _Context) -> dict[str, MemorySupport]:
    """Each support the reply gives, by its part's label, its code-owned fields set (§9:5).

    Raises:
        _Refused: ``check_failed`` where a label names no part the finding rests on, a
            part is named twice, or a support is malformed.
    """
    supports: dict[str, MemorySupport] = {}
    for proposed in reply.supports:
        read = context.view.part(proposed.part)
        if read is None or proposed.part in supports:
            raise _Refused(FindingUnwritten.CHECK_FAILED)
        direction = SupportDirection(proposed.direction)
        confirmation = read.origin is SupportOrigin.CONFIRMATION
        try:
            supports[proposed.part] = MemorySupport(
                points_at=read.part,
                origin=read.origin,
                direction=direction,
                note=proposed.note,
                backs_as_worded=proposed.backs_as_worded and direction is SupportDirection.FOR,
                how_sure=ReadingCertainty.SURE
                if confirmation
                else ReadingCertainty(proposed.how_sure),
                when=read.when,
                about_when=proposed.about_when,
                added_at=context.now,
                added_by=MemoryWriterName.OBSERVER,
            )
        except ValidationError as exc:
            raise _Refused(FindingUnwritten.CHECK_FAILED) from exc
    return supports


def _admitted(supports: dict[str, MemorySupport], context: _Context) -> None:
    """§10:1-§10:2: a round's message only beside the user's later keep or confirmation.

    Raises:
        _Refused: ``check_failed`` where a support pointing at a round's message has no
            ``for`` support beside it pointing at the user's own message in a later
            episode than that round's, the leaving episode or one after it.
    """
    view = context.view
    leaving = view.leaving.occurred_at
    for handle, support in supports.items():
        if support.origin not in _ASSISTANT_ORIGINS:
            continue
        said = view.part(handle)
        if said is None:  # pragma: no cover - every support's label was checked above
            raise _Refused(FindingUnwritten.CHECK_FAILED)
        kept = any(
            (other := view.part(key)) is not None
            and one.origin is SupportOrigin.USER_MESSAGE
            and one.direction is SupportDirection.FOR
            and other.occurred_at > said.occurred_at
            and other.occurred_at >= leaving
            for key, one in supports.items()
        )
        if not kept:
            raise _Refused(FindingUnwritten.CHECK_FAILED)


def _primary(  # noqa: PLR0911 — one arm per action §9:4 names
    reply: CommitReply, supports: dict[str, MemorySupport], context: _Context
) -> _Primary:
    """The one write the reply's action makes, checked."""
    match reply.action:
        case "nothing":
            return Unwritten(FindingUnwritten.NOT_KEPT)
        case "single_observation":
            return Unwritten(FindingUnwritten.SINGLE_OBSERVATION)
        case "recheck":
            target = _target(reply, context)
            if not supports or not (reply.asks or "").strip():
                raise _Refused(FindingUnwritten.CHECK_FAILED)
            _carried(supports.values(), context, creates=False)
            if narrows(context.placement, target):
                return Blocked()
            first = next(iter(supports.values()))
            return RaiseQuestion(
                target=target,
                kind=OpenQuestionKind.RECHECK,
                asks=reply.asks or "",
                support=_question_support(first, first.direction, supports, context),
            )
        case "add":
            target = _target(reply, context)
            if not supports or not _confirms_only_as_worded(supports, target, context):
                raise _Refused(FindingUnwritten.CHECK_FAILED)
            if reply.inference is not None or narrows(context.placement, target):
                # An inference about a stored claim is a create the policy may reinforce,
                # since one operation adds one support (§12:3, §9:7); and so is an add
                # whose supply is placed narrower than the memory, since a fold takes
                # the meet (§12:6) where an operation writes no placement (ADR-0328
                # §5:2).
                return _created(reply, supports, context, wording=target.content)
            _carried(supports.values(), context, creates=False)
            return AddSupports(target=target, supports=tuple(supports.values()))
        case _:
            return _created(reply, supports, context, wording=reply.wording)


def _target(reply: CommitReply, context: _Context) -> Memory:
    shown = context.view.memory(reply.memory)
    if shown is None:
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    return shown.memory


def _created(
    reply: CommitReply,
    supports: dict[str, MemorySupport],
    context: _Context,
    *,
    wording: str | None,
) -> _Primary:
    """A new memory, retiring at most one, checked (§9:7, §9:8, §11:5, §12:4, §13:1)."""
    inference = _inference(reply, supports, context)
    if any(
        one.origin is SupportOrigin.CONFIRMATION and not one.backs_as_worded
        for one in supports.values()
    ):
        # ADR-0328 §4:6: a confirmation is added only to the memory it backs as worded
        # or one its ingest retires, never to a new memory as anything else.
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    confirmed = {
        read.text
        for handle, one in supports.items()
        if one.origin is SupportOrigin.CONFIRMATION
        and one.backs_as_worded
        and (read := context.view.part(handle)) is not None
    }
    if len(confirmed) > 1:
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    # §5:5: a memory a confirmation backs as worded carries exactly the fact it showed.
    content = next(iter(confirmed)) if confirmed else (wording or "").strip()
    ordered = _ordered([*([] if inference is None else [inference]), *supports.values()])
    if not content or not ordered or not _backs(ordered[0]):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    try:
        memory = Memory(
            id=f"observed:{context.mint()}",
            content=content,
            supports=tuple(ordered),
            operations=(
                MemoryOperation(
                    kind=MemoryOperationKind.CREATE,
                    cites=ordered[0].points_at,
                    note=reply.note,
                    at=context.now,
                    by=MemoryWriterName.OBSERVER,
                ),
            ),
            placement=context.placement,
        )
    except ValidationError as exc:
        raise _Refused(FindingUnwritten.CHECK_FAILED) from exc
    if not meets_floor(memory):
        raise _Refused(FindingUnwritten.BELOW_FLOOR)
    _carried(memory.supports, context, creates=True)
    if inference is not None and not _completed(memory, context):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    try:
        asked_on = _question_support(ordered[0], SupportDirection.AGAINST, supports, context)
    except _Refused:
        asked_on = None
    kind = _RETIRING.get(reply.action)
    if kind is None:
        return Create(memory=memory, asked_on=asked_on)
    return _retiring(reply, Create(memory=memory, asked_on=asked_on), kind, supports, context)


def _inference(
    reply: CommitReply, supports: dict[str, MemorySupport], context: _Context
) -> MemorySupport | None:
    """§9:7: an observer's inference, beside supports that are for and back nothing as worded.

    Raises:
        _Refused: ``check_failed`` where an inference is given beside a support that is
            against the memory or backs it as worded.
    """
    proposed = reply.inference
    if proposed is None:
        return None
    if any(
        one.direction is not SupportDirection.FOR or one.backs_as_worded
        for one in supports.values()
    ):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    leaving = context.view.leaving
    return MemorySupport(
        points_at=ObserverInferencePart(episode=leaving.id),
        origin=SupportOrigin.OBSERVER_INFERENCE,
        direction=SupportDirection.FOR,
        note=proposed.note,
        backs_as_worded=True,
        how_sure=ReadingCertainty(proposed.how_sure),
        when=leaving.occurred_at,
        added_at=context.now,
        added_by=MemoryWriterName.OBSERVER,
    )


def _backs(support: MemorySupport) -> bool:
    return support.direction is SupportDirection.FOR and support.backs_as_worded


def _ordered(supports: Sequence[MemorySupport]) -> list[MemorySupport]:
    """Supports with the one to cite first: the highest-standing backing support.

    A create cites the first, and a ``SUPERSEDE`` ends its targets citing it (ADR-0328
    §11:7), so the strongest backing support leads; the rest keep the step's order.
    """
    return sorted(
        supports,
        key=lambda one: (not _backs(one), -standing_rank(origin_standing(one.origin))),
    )


def _retiring(
    reply: CommitReply,
    created: Create,
    kind: MemoryOperationKind,
    supports: dict[str, MemorySupport],
    context: _Context,
) -> _Primary:
    """One proposal carrying the new memory and the retirement it cites (§12:4, §13:1).

    Raises:
        _Refused: ``check_failed`` where the target was not shown, the cited support
            does not back the new memory as worded (§12:5), or an end's about-when lies
            after its instant (ADR-0328 §5:10).
    """
    target = _target(reply, context)
    memory = created.memory
    if narrows(context.placement, target):
        # §12:6: the retired memory would carry what the supply placed narrower, and an
        # operation writes no placement (ADR-0328 §5:2): the new memory is proposed alone,
        # and the policy rules over the conflict as over any other.
        return created
    if reply.cites == "inference":
        cited = next(
            (one for one in memory.supports if one.origin is SupportOrigin.OBSERVER_INFERENCE),
            None,
        )
    else:
        cited = None if reply.cites is None else supports.get(reply.cites)
    if cited is None or not _backs(cited):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    if cited.origin is SupportOrigin.CONFIRMATION and target.band is BeliefBand.ASSERTED:
        # §12:4: no confirmation the observer builds covers an assertion (§5:7), so
        # another support backing the new memory as worded is cited, or nothing retires.
        cited = next(
            (
                one
                for one in memory.backing_supports
                if one.origin is not SupportOrigin.CONFIRMATION
            ),
            None,
        )
        if cited is None:
            return created
    if (
        kind is MemoryOperationKind.END
        and cited.about_when is not None
        and cited.about_when > context.now
    ):
        raise _Refused(FindingUnwritten.CHECK_FAILED)
    if standing_rank(origin_standing(cited.origin)) < standing_rank(target.standing):
        # ADR-0328 §6:5 refuses the retirement, and the whole proposal with it (§12:5):
        # the open question it needs is raised instead (§13:1).
        return RaiseQuestion(
            target=target,
            kind=OpenQuestionKind.CONFLICT,
            asks=_CONFLICT_ASKS + memory.content,
            support=_question_support(cited, SupportDirection.AGAINST, supports, context),
        )
    try:
        retiring = MemoryRetirement(
            memory=target, kind=kind, cites=cited.points_at, note=reply.note
        )
    except ValidationError as exc:
        raise _Refused(FindingUnwritten.CHECK_FAILED) from exc
    return Create(memory=memory, retiring=retiring, asked_on=created.asked_on)


def _question_support(
    support: MemorySupport,
    direction: SupportDirection,
    supports: dict[str, MemorySupport],
    context: _Context,
) -> MemorySupport:
    """The support a question rests on, added to the memory it is about (§13:2).

    Never a confirmation, which ADR-0328 §4:6 adds to no other memory, nor an observer's
    inference: for a confirmation the question rests on the yes's input instead, and for
    an inference on a support that inference reads.

    Raises:
        _Refused: ``check_failed`` where no such support was read.
    """
    part: SupportPart = support.points_at
    origin = support.origin
    when = support.when
    if isinstance(part, ConfirmationPart):
        read = context.view.yes_inputs.get(part.episode)
        if read is None:
            raise _Refused(FindingUnwritten.CHECK_FAILED)
        part, origin, when = read.part, read.origin, read.when
    elif isinstance(part, ObserverInferencePart):
        other = next(iter(supports.values()), None)
        if other is None:
            raise _Refused(FindingUnwritten.CHECK_FAILED)
        part, origin, when = other.points_at, other.origin, other.when
    if origin in _ASSISTANT_ORIGINS:
        # §10:1: the assistant's words are added only beside the user's keep, and a
        # question rests on one support, so it rests on that keep instead.
        keep = next(
            (
                one
                for one in supports.values()
                if one.origin is SupportOrigin.USER_MESSAGE
                and one.direction is SupportDirection.FOR
            ),
            None,
        )
        if keep is None:
            raise _Refused(FindingUnwritten.CHECK_FAILED)
        part, origin, when = keep.points_at, keep.origin, keep.when
    return MemorySupport(
        points_at=part,
        origin=origin,
        direction=direction,
        note=support.note,
        backs_as_worded=False,
        how_sure=support.how_sure if origin is not SupportOrigin.CONFIRMATION else None,
        when=when,
        about_when=support.about_when,
        added_at=context.now,
        added_by=MemoryWriterName.OBSERVER,
    )


def _resolve(
    reply: CommitReply, supports: dict[str, MemorySupport], context: _Context
) -> Resolve | None:
    """§13:5: a question the answer resolves, citing the support added from it.

    A resolve that names a memory, a question or a part the step was not shown is
    dropped, with the rest of the decision written as checked, and so is one whose
    support, as it would be added, points at another episode than the leaving one
    (§8:2). One resting on a supply narrower than the memory blocks the whole decision
    (:class:`Blocked`).

    Raises:
        _Blocked: Where the supply would narrow the memory the question is on.
    """
    proposed = reply.resolves
    if proposed is None:
        return None
    shown = context.view.memory(proposed.memory)
    support = supports.get(proposed.part)
    question = None if shown is None else shown.questions.get(proposed.question)
    if shown is None or support is None or question is None or not proposed.note.strip():
        return None
    try:
        added: MemorySupport | None = _question_support(
            support, support.direction, supports, context
        )
    except _Refused:
        added = None
    if added is not None and part_episode(added.points_at) != context.view.leaving.id:
        # §8:2: an answer another episode gave, the user's keep standing in for the
        # assistant's words included, waits until that episode is due.
        return None
    if narrows(context.placement, shown.memory):
        raise _Blocked
    if added is None:
        return None
    return Resolve(target=shown.memory, question=question, support=added, note=proposed.note)


def narrows(supply: Placement, target: Memory) -> bool:
    """Whether the run's supply would narrow a stored memory's placement (§12:6).

    The meet over the supply and the memory is narrower in reach, or decided by a
    stronger setter (ADR-0217 §3:3): a ``DERIVED`` owner-only supply narrows an
    owner-only memory the owner placed, since the owner's lifting of the one would
    otherwise lift the other. An operation on a stored memory writes no placement
    (ADR-0328 §5:2), so a write resting on such a supply is proposed through
    ``ingest``, whose fold takes the meet, or not made.

    Args:
        supply: The meet over every record the run was supplied.
        target: The stored memory.

    Returns:
        Whether a write onto ``target`` would widen what ``supply`` reaches.
    """
    held = target.placement
    meet = Placement.narrowest_of((supply, held))
    return meet.reach is not held.reach or meet.set_by is not held.set_by


def _agreement_form(content: str) -> str:
    """ADR-0121 §1's comparison form: NFC, case folded, whitespace runs collapsed, stripped."""
    return " ".join(unicodedata.normalize("NFC", content).casefold().split())


def _confirms_only_as_worded(
    supports: dict[str, MemorySupport], target: Memory, context: _Context
) -> bool:
    """ADR-0328 §4:6: a confirmation is added only where its wording agrees, backing it.

    A confirmation backs a stored memory as worded only where the statement the approved
    part showed agrees with the memory's wording under ADR-0121 §1's predicate, and it is
    added to no memory where it does not.
    """
    for handle, support in supports.items():
        if support.origin is not SupportOrigin.CONFIRMATION:
            continue
        read = context.view.part(handle)
        if (
            read is None
            or not support.backs_as_worded
            or _agreement_form(read.text) != _agreement_form(target.content)
        ):
            return False
    return True
