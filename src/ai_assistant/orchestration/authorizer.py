"""The authorizing stage: every call of a round checked by rule (ADR-0306 §4).

One orchestration-local phase module (ADR-0309 §2:2), of the kind
:class:`~ai_assistant.orchestration.acting.ActingStage` is. It is named ``authorizer``
and not ``authorizing``, which is the retiring old path's module (ADR-0312 §3, ADR-0309
§5:3). It holds injected seams onto the tool registry, the permission policy, the memory
policy, the audit trail, the story store, the memory store and the egress binder, and it
is **not a Protocol**. It calls no model and runs nothing: each :meth:`AuthorizingStage.
authorize` is one controller step over one recorded planning round (ADR-0309 §3:2), and
what it hands on is the decision acting and planning's next round read.

**Selection first** (§4:10, ADR-0144). Each call names a capability. The registry's
tools for it must all declare alike (ADR-0306 §2:7), the hub fills the arguments the
declaration names ``system_supplied`` (ADR-0254 §3), the fit filter drops the tools the
arguments do not satisfy (ADR-0145 §2), and the least severe tool is selected. A call
that cannot be bound to exactly one tool is not done, with its reason, and no ruling is
sought.

**Then the checks, in order** (§4:1). The policy, ``ActionPolicy``, built without goal
authorizations and goal quotes; its request carries no ``goal`` and no
``intended_action`` (§4:11). Then the outside-content stand-in (§4:4 to §4:6). Then, for
remembering, ``MemoryPolicy`` (§4:3). A call runs only where every check that applies
allows it. A deny, or a memory reject, is *not done* with the reason (§4:9); a confirm,
a stand-in send to the user, or a memory ask is *needs you* (§4:8). Nothing parks and
nothing resumes. The round's message is checked by its place alone (§4:7).

**Recorded and read back before anything runs** (§4:10, ADR-0037 §2 to §3). Every
ruling is bound to its request, appended to the trail, and read back; a trail that hands
back anything other than what was written raises. A call to a capability whose calls get
an effect record carries, on its decision, the id of the record acting will claim it
under, minted before the ruling (ADR-0306 §5:8, §6's ``PermissionDecision.effect``).

**The stand-in** is the built lineage rule. :func:`read_outside_content` computes, over
the activation's whole record, whether it has read outside content, and the fact reaches
the policy as ``planned_with_external_content`` on the call's egress binding, where the
policy applies ADR-0181 §5:2 with ADR-0247 §3's exception. A call that leaves the hub with
no binding to carry the fact gets the rule here, with no exception: it needs the user.

**The duplicate backstop's match is collected once, here** (§5:10, §6:3). Where an
allowed call's capability is not safe to repeat, the activations of the episodes in this
activation's stories are read from the story store as they stand now, and handed on.

**It logs stage and code-owned reason only**, never arguments or rulings' text (ADR-0275
§8).

**What it gives the diagnostic record** (ADR-0314 §4), through the sink the composition
root hands it where the record is on: once the round is checked, or the checking fails,
for each call the verdict of each check it reached and that check's reason, the
message's verdict, and whether the activation had read outside content, with each
ground of ADR-0306 §4:5 that held and the record it rests on, as
:func:`read_outside_content` gives them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.diagnostics import failure_body, write_diagnostic
from ai_assistant.core.errors import (
    AuditError,
    EgressBindingError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ActionRequest,
    ActivationDigest,
    CapabilityEffect,
    CarriedProvenance,
    DiagnosticKind,
    DiagnosticSource,
    DigestOutcome,
    EgressBinding,
    EpisodicMemory,
    LabelKind,
    MemoryDecisionKind,
    PermissionDecision,
    PermissionOutcome,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    SpanCoverage,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    ToolCall,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.outside_content import from_outside, is_outside_episode
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CAPABILITY,
    remembered_proposal,
    remembered_record_id,
)
from ai_assistant.orchestration.selection import (
    Preference,
    eligible_candidates,
    model_supplied_keys,
    select,
)
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        DiagnosticSink,
        EgressBinder,
        MemoryPolicy,
        MemoryStore,
        StoryStore,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        FrozenJson,
        PermissionRuling,
        ToolDefinition,
    )

__all__ = [
    "AllowedCall",
    "AuthorizingStage",
    "CallToAuthorize",
    "CallVerdict",
    "MessageVerdict",
    "OutsideGround",
    "RoundAuthorization",
    "RoundMessage",
    "RoundToAuthorize",
    "Verdict",
    "WorkingRecord",
    "gets_effect_record",
    "read_outside_content",
]

_log = structlog.get_logger(__name__)

# Code-owned reasons, which planning's next round is shown (ADR-0306 §4:9).
_NO_TOOL: Final = "no tool satisfies this capability"
_DISAGREE: Final = "the tools satisfying this capability do not declare alike"
_HUB_FILLS: Final = "the call names an argument the hub fills"
_UNFILLABLE: Final = "the capability names an argument the hub cannot fill"
_UNCHECKABLE: Final = "the arguments could not be checked against the tool's schema"
_NO_FIT: Final = "the arguments fit no tool of this capability"
_TIED: Final = "more than one tool fits equally, and none is chosen"
_UNBINDABLE: Final = "the call could not be bound to where it would go"
_MALFORMED: Final = "the call's arguments do not make a request"
_DENIED: Final = "the permission policy denies this call"
_CONFIRM: Final = "the permission policy asks the user about this call"
_STAND_IN: Final = (
    "the call leaves the assistant, and this activation has read outside content, so it "
    "needs the user"
)
_UNCLAIMED_MEMORY: Final = "remembering is claimed under an effect record, and this is not"
_MEMORY_ASK: Final = "the memory policy asks the user about remembering this"
_MEMORY_REJECT: Final = "the memory policy rejects remembering this"
_ELSEWHERE: Final = "a round's message goes only into the place its input came from"


class Verdict(StrEnum):
    """What authorizing made of one call (ADR-0306 §4:8 to §4:9)."""

    ALLOWED = "allowed"
    """Every check that applies allowed it; acting runs it."""

    NEEDS_YOU = "needs_you"
    """A confirm, the stand-in, or a memory ask: it cannot be done yet."""

    NOT_DONE = "not_done"
    """A deny, a memory reject, or a call no tool could be bound to: never run."""


# --- the input -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallToAuthorize:
    """One call of the round that passed planning's own check (ADR-0307 §5:3 to §5:4).

    Authorizing's own shape, because no phase module imports another (ADR-0309 §2:3): the
    lane that wires the phases fills it from planning's decision.

    Attributes:
        call: The call with ids in place of labels, and without its *looking for* or
            *deliberate repeat* (ADR-0306 §2:10).
        deliberate_repeat: Whether planning marked it a deliberate repeat.
    """

    call: ProposedCall
    deliberate_repeat: bool = False


@dataclass(frozen=True, slots=True)
class RoundMessage:
    """The round's message, and the place it would be written into (ADR-0306 §4:7).

    Attributes:
        text: The message's text.
        place: The place it would go into.
    """

    text: str
    place: str


@dataclass(frozen=True, slots=True)
class WorkingRecord:
    """What the working set holds of the activation's record, whether or not it was kept.

    An append that fails is a capture failure and holds nothing back (ADR-0307 §2:4,
    ADR-0308 §5:2), so the episode in the store may lack a round or a digest planning was
    shown. The lane that wires the phases fills this from the working set, so that what
    the activation read is computed over everything it read.

    Attributes:
        rounds: This activation's rounds. The stage adds the one it is authorizing.
        labels: The labels those rounds assigned, the round being authorized's included.
        digests: This activation's digests, recall's included.
        fetched_outside: Whether a record the activation read before planning, its
            windows' or recall's, rests on outside content (ADR-0181 §4, ADR-0223),
            which neither its episode nor its labels need carry.
        fetched_outside_from: What made ``fetched_outside`` hold, each named once, for
            the diagnostic record (ADR-0314 §4): a fetched episode or memory record by
            its id, a story's marked summary by the story's id, a marked note by its
            id, and a marked moment of where a matter stands by its episode's address.
            Empty where the working set keeps no name for it.
        notes: The story notes planning was shown, as the stories held them, whose
            marks (ADR-0303 §3:1) say whether each ``N`` label is outside content
            read. A note's mark never changes once it is written.

    Raises:
        ValueError: If ``fetched_outside_from`` names something while
            ``fetched_outside`` does not hold: a name says why it holds, and never makes
            it hold.
    """

    rounds: tuple[PlanningRound, ...] = ()
    labels: tuple[PlanningLabel, ...] = ()
    digests: tuple[ActivationDigest, ...] = ()
    fetched_outside: bool = False
    fetched_outside_from: tuple[str, ...] = ()
    notes: tuple[StoryNote, ...] = ()

    def __post_init__(self) -> None:
        """A name is given only where ``fetched_outside`` holds."""
        if self.fetched_outside_from and not self.fetched_outside:
            msg = "what a fetched record rests on is named only where it rests on outside content"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RoundToAuthorize:
    """One recorded planning round, as authorizing takes it.

    Attributes:
        activation_id: The activation the round belongs to.
        round: The round, as planning recorded it, or as it would have been where its
            append failed (ADR-0307 §2:4).
        working: What the working set holds of the activation's record, with the labels
            this round assigned.
        calls: The calls that passed planning's check, in the round's order.
        input_place: The place the activation's input came from, or ``None`` where it
            came from none.
        message: The round's message, where it has one to write.

    Raises:
        ValueError: If two calls share a call id, or a call is not one the round
            proposed under that id and name.
    """

    activation_id: str
    round: PlanningRound
    working: WorkingRecord
    calls: tuple[CallToAuthorize, ...] = ()
    input_place: str | None = None
    message: RoundMessage | None = None

    def __post_init__(self) -> None:
        """Each call is one the round proposed, once."""
        proposed = {one.call_id: one.name for one in self.round.calls}
        ids = [one.call.call_id for one in self.calls]
        if len(set(ids)) != len(ids):
            msg = "a round's calls are authorized once each"
            raise ValueError(msg)
        for one in self.calls:
            if proposed.get(one.call.call_id) != one.call.name:
                msg = "authorizing checks only the calls the round proposed"
                raise ValueError(msg)


# --- the decision ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallVerdict:
    """What authorizing made of one call, as planning's next round reads it.

    Attributes:
        call_id: The provider's id for the call in its round.
        verdict: Allowed, needs you, or not done.
        reason: Why it is not allowed, in code-owned words; ``None`` where it is.
        decision_id: The recorded ``PermissionDecision``, where a ruling was sought.
        effect_id: The effect record the call is or would be claimed under, where its
            capability's calls get one.
    """

    call_id: str
    verdict: Verdict
    reason: str | None = None
    decision_id: str | None = None
    effect_id: str | None = None


@dataclass(frozen=True, slots=True)
class AllowedCall:
    """One call acting may run, as acting's ``AuthorizedCall`` takes it.

    Attributes:
        call: The call as it will be invoked, with the recorded ``ALLOW`` decision that
            authorises it, which names the effect record where the call gets one.
        deliberate_repeat: Whether planning marked the call a deliberate repeat; set only
            on a call to a capability that is not safe to repeat.
    """

    call: ToolCall
    deliberate_repeat: bool = False


@dataclass(frozen=True, slots=True)
class MessageVerdict:
    """What authorizing made of the round's message (ADR-0306 §4:7).

    Attributes:
        place: The place it would go into.
        allowed: Whether it may be written there.
        effect_id: The effect record it is to be claimed under, where it is allowed
            (ADR-0306 §5:3).
        reason: Why it is not allowed; ``None`` where it is.
    """

    place: str
    allowed: bool
    effect_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoundAuthorization:
    """Authorizing's decision for one round: the working-set entry ADR-0309 §3:2 names.

    It carries what acting's ``AuthorizedRound`` is built from (the activation, the round,
    the allowed calls in the round's order and the stories' activations) and what
    planning's next round reads (each call's verdict), so the lane that wires the phases
    hands each phase its own shape without either importing the other (ADR-0309 §2:3).

    Attributes:
        activation_id: The activation the round belongs to.
        round_id: The planning round.
        verdicts: Each call's verdict, in the round's order.
        allowed: The calls acting may run, in the round's order.
        story_activations: The activations of the episodes in this activation's stories,
            taken when the round was authorized (ADR-0306 §5:10); empty where no allowed
            call's capability is unsafe to repeat.
        message: The message's verdict, where the round has one.
        read_outside_content: Whether the activation's record says it had read outside
            content when the round was authorized (ADR-0306 §4:5).
    """

    activation_id: str
    round_id: str
    verdicts: tuple[CallVerdict, ...] = ()
    allowed: tuple[AllowedCall, ...] = ()
    story_activations: tuple[str, ...] = ()
    message: MessageVerdict | None = None
    read_outside_content: bool = False


# --- the rules ---------------------------------------------------------------------------


def gets_effect_record(tool: ToolDefinition) -> bool:
    """Whether a call under ``tool`` gets an effect record (ADR-0306 §5:3).

    A call in the world, and a call to a capability that is not safe to repeat. Acting
    states the same rule for the record it claims; this module may not import acting
    (ADR-0309 §2:3), and a test holds the two to one answer.

    Args:
        tool: The declaration selected for the call.

    Returns:
        Whether the call's decision names an effect record.
    """
    return tool.effect is CapabilityEffect.WORLD or not tool.safe_to_repeat


@dataclass(frozen=True, slots=True)
class OutsideGround:
    """One ground of ADR-0306 §4:5 that held, and the record it rests on (ADR-0314 §4).

    Attributes:
        ground: Which ground, as a code-owned word.
        record: The record it rests on: an episode's or a round's id, a digest's result
            label, a note's id, a story's id for its marked summary, a moment's episode
            address; ``None`` where the working set holds no name for it.
    """

    ground: str
    record: str | None = None


#: The grounds, as :func:`read_outside_content` names them.
_FETCHED_OUTSIDE: Final = "fetched_outside"
_OWN_EPISODE_UNREAD: Final = "own_episode_unread"
_EPISODE_MARKED: Final = "episode_marked"
_TRIGGER_OUTSIDE: Final = "trigger_outside"
_DIGEST_ANSWERED: Final = "digest_answered"
_NOTES_MARKED: Final = "notes_marked"
_NOTE_SHOWN_MARKED: Final = "note_shown_marked"
_EPISODE_SHOWN_UNREAD: Final = "episode_shown_unread"
_OUTSIDE_EPISODE_SHOWN: Final = "outside_episode_shown"


def _digest_identity(digest: ActivationDigest) -> tuple[object, ...]:
    """What tells one digest from another: a digest is never edited (ADR-0308 §5:2).

    Its result label alone does not, since a search's digest and a follow-up's both
    name the result they read; its question and the instant it was recorded do.
    """
    return (digest.result, digest.question, digest.recorded_at)


def _note_is_marked(label_id: str, notes: Sequence[StoryNote]) -> bool:
    """Whether a story note planning was shown under ``label_id`` is marked (ADR-0303 §3:1).

    Read from the notes the working set holds as shown. A note it does not hold, such as
    one an earlier pass labelled, has a mark this stage cannot read, so it counts,
    failing closed.
    """
    held = [one.outside for one in notes if str(one.note_id) == label_id]
    return not held or any(held)


async def read_outside_content(  # noqa: C901, PLR0911, PLR0912 — §4:5's grounds, in order, each able to end the read
    memory: MemoryStore,
    activation_id: str,
    *,
    working: WorkingRecord,
    grounds: list[OutsideGround] | None = None,
) -> bool:
    """Whether the activation's record says it has read outside content (ADR-0306 §4:5).

    Computed over the activation's whole record, every round included (§4:6), and never
    from a value a model, a tool or a plan emits. The record is the activation's episode
    at its address together with ``working``, what the working set holds of it, since an
    append that fails holds nothing back (ADR-0307 §2:4, ADR-0308 §5:2) and so cannot be
    what clears the lineage. It has read outside content where:

    - a record it read before planning rests on outside content
      (``working.fetched_outside``);
    - its episode is marked (ADR-0106 §1), or its trigger came from outside;
    - a digest answered, with or without items (ADR-0308 §5:4);
    - a round's notes are marked, which the hub does where the activation had read
      outside content when they were written (ADR-0307 §4:3, ADR-0303 §3:1);
    - planning was shown a marked story note (an ``N`` label), read from
      ``working.notes``, or one whose mark the working set does not hold, which fails
      closed;
    - or planning was shown an outside episode (an ``E`` label, ADR-0303 §3:2, as
      :func:`~ai_assistant.orchestration.outside_content.is_outside_episode` decides
      it), or one that can no longer be read, which fails closed too.

    Where the activation's own episode cannot be read, or carries no processing record,
    nothing says it has not read outside content, so it has.

    **The grounds that held** (ADR-0314 §4). Where ``grounds`` is handed in, every
    ground is gone through rather than the first that holds, and each that held is
    appended with the record it rests on, for the diagnostic record. The answer is the
    same either way: a read that fails once a ground already held ends the going
    through, since the answer is already yes, and costs only the grounds after it.
    Each ground is appended once per record it rests on: the episode's record and the
    working set hold the same rounds, digests and labels once their appends landed, and
    a round, a digest or a label held twice is counted once, by its identity.

    Args:
        memory: The memory store the episodes are read from.
        activation_id: The activation.
        working: What the working set holds of the activation's record.
        grounds: Where given, collects every ground that held, in order.

    Returns:
        Whether the activation has read outside content.

    Raises:
        MemoryStoreError: If the memory store cannot be read before any ground held;
            once one has, a failed read only ends the going through.
    """
    every = grounds is not None
    held: list[OutsideGround] = [] if grounds is None else grounds

    counted: set[object] = set()

    def first(identity: object) -> bool:
        """Whether ``identity`` is seen here for the first time; noting it."""
        if identity in counted:
            return False
        counted.add(identity)
        return True

    def found(ground: str, record: str | None = None) -> bool:
        """Note ``ground``; whether to stop here, which is unless every ground is asked."""
        held.append(OutsideGround(ground, record))
        return not every

    if working.fetched_outside:
        for fetched in dict.fromkeys(working.fetched_outside_from) or (None,):
            if found(_FETCHED_OUTSIDE, fetched):
                return True
    own = episode_address(activation_id)
    try:
        record = await memory.get(own)
    except Exception:
        # A read the answer no longer needs: once a ground holds it is yes, so going
        # through every ground for the record never raises where the answer alone
        # would not have read at all (ADR-0314 §2:4).
        if every and held:
            return True
        raise
    if not isinstance(record, EpisodicMemory) or record.processing_record is None:
        _log.info("authorizing_record_unread", stage="authorizing", reason="no_episode")
        found(_OWN_EPISODE_UNREAD, own)
        return True
    processing = record.processing_record
    rounds = (*processing.rounds, *working.rounds)
    digests = (*processing.digests, *working.digests)
    labels = (*processing.labels, *working.labels)
    if rests_on_recorded_external_content(record.provenance) and found(_EPISODE_MARKED, own):
        return True
    if from_outside(record) and found(_TRIGGER_OUTSIDE, own):
        return True
    for digest in digests:
        if (
            digest.outcome is DigestOutcome.ANSWERED
            and first((_DIGEST_ANSWERED, *_digest_identity(digest)))
            and found(_DIGEST_ANSWERED, digest.result)
        ):
            return True
    for planned in rounds:
        if (
            planned.notes_marked
            and first((_NOTES_MARKED, planned.id))
            and found(_NOTES_MARKED, planned.id)
        ):
            return True
    for label in labels:
        if (
            label.kind is LabelKind.NOTE
            and _note_is_marked(label.id, working.notes)
            and first((_NOTE_SHOWN_MARKED, label.id))
            and found(_NOTE_SHOWN_MARKED, label.id)
        ):
            return True
    shown = sorted({one.id for one in labels if one.kind is LabelKind.EPISODE} - {own})
    if not shown:
        return bool(held)
    try:
        episodes = await memory.get_many(shown)
    except Exception:
        if every and held:  # as above: the answer is already yes
            return True
        raise
    for episode_id in shown:
        other = episodes.get(episode_id)
        if not isinstance(other, EpisodicMemory):
            if found(_EPISODE_SHOWN_UNREAD, episode_id):
                return True
        elif is_outside_episode(other) and found(_OUTSIDE_EPISODE_SHOWN, episode_id):
            return True
    return bool(held)


def _declared(tool: ToolDefinition) -> tuple[object, ...]:
    """What every tool of one capability must declare alike (ADR-0306 §2:7)."""
    return (
        tool.effect,
        tool.leaves_hub,
        tool.result,
        tool.outcome_can_be_unknown,
        tool.safe_to_repeat,
        tool.model_dump()["parameters_schema"],
        tuple(tool.system_supplied),
    )


def _detached_round(given: RoundToAuthorize) -> RoundToAuthorize:
    """Revalidate and detach the round, so nothing a caller still holds is ruled on."""
    message = given.message
    working = given.working
    return RoundToAuthorize(
        activation_id=str(given.activation_id),
        round=PlanningRound.model_validate(given.round.model_dump()),
        working=WorkingRecord(
            rounds=tuple(PlanningRound.model_validate(one.model_dump()) for one in working.rounds),
            labels=tuple(PlanningLabel.model_validate(one.model_dump()) for one in working.labels),
            digests=tuple(
                ActivationDigest.model_validate(one.model_dump()) for one in working.digests
            ),
            fetched_outside=bool(working.fetched_outside),
            fetched_outside_from=tuple(str(one) for one in working.fetched_outside_from),
            notes=tuple(StoryNote.model_validate(one.model_dump()) for one in working.notes),
        ),
        calls=tuple(
            CallToAuthorize(
                call=ProposedCall.model_validate(one.call.model_dump()),
                deliberate_repeat=bool(one.deliberate_repeat),
            )
            for one in given.calls
        ),
        input_place=None if given.input_place is None else str(given.input_place),
        message=None if message is None else RoundMessage(str(message.text), str(message.place)),
    )


def _detached_request(request: ActionRequest) -> ActionRequest:
    """The copy the policy rules on, taken before it is reached (ADR-0021 §3)."""
    return ActionRequest.model_validate(request.model_dump())


@dataclass(frozen=True, slots=True)
class _Selected:
    """A call bound to one tool, with its arguments complete."""

    tool: ToolDefinition
    parameters: dict[str, FrozenJson]


@dataclass(frozen=True, slots=True)
class _Ruled:
    """A call ruled on: its request and the decision the trail holds."""

    request: ActionRequest
    decision: PermissionDecision
    effect_id: str | None


@dataclass
class _Round:
    """The facts every call of one round is checked against.

    ``checks`` holds, by call id, each check a call reached, for the diagnostic record
    (ADR-0314 §4); ``None`` where the record is off, so nothing is noted.
    """

    activation_id: str
    read_outside: bool
    verdicts: list[CallVerdict] = field(default_factory=list)
    allowed: list[AllowedCall] = field(default_factory=list)
    checks: dict[str, list[dict[str, object]]] | None = None

    def note(self, call: ProposedCall, check: str, verdict: str, reason: str | None) -> None:
        """Note one check ``call`` reached, its verdict and its reason."""
        if self.checks is None:
            return
        self.checks.setdefault(call.call_id, []).append(
            {"check": check, "verdict": verdict, "reason": reason}
        )


# --- the stage ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_decision_id() -> str:
    return f"decision:{uuid4().hex}"


def _new_effect_id() -> str:
    return f"effect:{uuid4().hex}"


def _not_done(call: ProposedCall, reason: str) -> CallVerdict:
    _log.info("authorizing_call_not_done", stage="authorizing")
    return CallVerdict(call.call_id, Verdict.NOT_DONE, reason=reason)


class AuthorizingStage:
    """Check each call of a round by rule, and record every ruling (ADR-0306 §4)."""

    def __init__(  # noqa: PLR0913 — one keyword per seam the checks read, the preference, and the clock and id sources
        self,
        *,
        registry: ToolRegistry,
        policy: ActionPolicy,
        memory_policy: MemoryPolicy,
        trail: AuditTrail,
        stories: StoryStore,
        memory: MemoryStore,
        binder: EgressBinder | None = None,
        preference: Preference | None = None,
        registered_search: frozenset[str] = frozenset(),
        registered_forecast: frozenset[str] = frozenset(),
        now: Callable[[], datetime] = _utcnow,
        new_decision_id: Callable[[], str] = _new_decision_id,
        new_effect_id: Callable[[], str] = _new_effect_id,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the stage to its seams.

        Args:
            registry: The tool registry selection reads.
            policy: The permission policy, built without goal authorizations and goal
                quotes (ADR-0306 §4:11).
            memory_policy: The memory policy remembering also passes (§4:3).
            trail: The audit trail every ruling is recorded in and read back from.
            stories: The story store the backstop's match is collected from (§5:10).
            memory: The memory store the activation's record is read from.
            binder: The egress binding seam, or ``None`` where none is wired.
            preference: The deployment's tool preference sequence (ADR-0144 §4).
            registered_search: The ids of the tools that are this deployment's own
                registered search (ADR-0247 §4), whose calls carry ``closed_loop``.
            registered_forecast: The ids of the tools that are this deployment's own
                configured forecast read (ADR-0260 §6), whose calls carry
                ``forecast_reach``.
            now: The clock a decision's ``decided_at`` is read from.
            new_decision_id: Mints a decision's id.
            new_effect_id: Mints an effect record's id, before the ruling.
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4), or
                ``None`` where the record is off.
        """
        self._registry = registry
        self._policy = policy
        self._memory_policy = memory_policy
        self._trail = trail
        self._stories = stories
        self._memory = memory
        self._binder = binder
        self._preference = Preference() if preference is None else preference
        self._registered_search = frozenset(registered_search)
        self._registered_forecast = frozenset(registered_forecast)
        self._now = checked_clock(now, owner="AuthorizingStage")
        self._new_decision_id = new_decision_id
        self._new_effect_id = new_effect_id
        self._diagnostics = diagnostics

    async def authorize(self, given: RoundToAuthorize) -> RoundAuthorization:
        """Check every call of ``given`` in the round's order, and its message.

        The round is revalidated and detached before the first ``await``, so every check
        reads one snapshot of it.

        Args:
            given: The recorded round, its calls and its message.

        Returns:
            Each call's verdict, the calls acting may run, the stories' activations
            where an allowed call needs them, and the message's verdict.

        Raises:
            AuditError: If the trail refused a ruling's append, or handed back anything
                other than the decision written.
            MemoryStoreError: If the activation's record cannot be read.
            StoryStoreError: If the story store cannot be read, or pages it without end.
            Exception: Whatever the registry, the policies or the binder raised beyond
                the refusals handled here. Nothing has run.
        """
        snapshot = _detached_round(given)
        noting = self._diagnostics is not None
        grounds: list[OutsideGround] | None = [] if noting else None
        progress: list[_Round] = []
        try:
            decided = await self._authorized(snapshot, grounds, noting=noting, progress=progress)
        except Exception as exc:
            reached = progress[0] if progress else None
            await self._returned(snapshot, grounds, None, state=reached, failure=exc)
            raise
        await self._returned(snapshot, grounds, decided, state=progress[0])
        return decided

    async def _authorized(
        self,
        snapshot: RoundToAuthorize,
        grounds: list[OutsideGround] | None,
        *,
        noting: bool,
        progress: list[_Round],
    ) -> RoundAuthorization:
        """Check every call of the detached round, and its message.

        The round's state joins ``progress`` once it exists, so a failure part-way is
        written with the checks it reached.
        """
        held = snapshot.working
        read_outside = await read_outside_content(
            self._memory,
            snapshot.activation_id,
            working=replace(held, rounds=(*held.rounds, snapshot.round)),
            grounds=grounds,
        )
        state = _Round(
            activation_id=snapshot.activation_id,
            read_outside=read_outside,
            checks={} if noting else None,
        )
        progress.append(state)
        for one in snapshot.calls:
            await self._check(one, state)
        stories: tuple[str, ...] = ()
        if any(not one.call.request.tool.safe_to_repeat for one in state.allowed):
            stories = await self._story_activations(snapshot.activation_id)
        return RoundAuthorization(
            activation_id=snapshot.activation_id,
            round_id=snapshot.round.id,
            verdicts=tuple(state.verdicts),
            allowed=tuple(state.allowed),
            story_activations=stories,
            message=self._message(snapshot),
            read_outside_content=read_outside,
        )

    async def _returned(
        self,
        snapshot: RoundToAuthorize,
        grounds: list[OutsideGround] | None,
        decided: RoundAuthorization | None,
        *,
        state: _Round | None = None,
        failure: Exception | None = None,
    ) -> None:
        """Write what authorizing made of the round, or how far it got (ADR-0314 §4)."""

        def body() -> dict[str, object]:
            checks = {} if state is None or state.checks is None else state.checks
            verdicts = {} if decided is None else {one.call_id: one for one in decided.verdicts}
            calls: list[dict[str, object]] = []
            for one in snapshot.calls:
                call_id = one.call.call_id
                verdict = verdicts.get(call_id)
                calls.append(
                    {
                        "call_id": call_id,
                        "name": one.call.name,
                        "checks": checks.get(call_id, []),
                        "verdict": None if verdict is None else verdict.verdict.value,
                        "reason": None if verdict is None else verdict.reason,
                    }
                )
            returned: dict[str, object] = {"round": snapshot.round.id, "calls": calls}
            message = None if decided is None else decided.message
            if message is not None:
                returned["message"] = {
                    "place": message.place,
                    "allowed": message.allowed,
                    "reason": message.reason,
                }
            if state is not None:
                returned["read_outside_content"] = state.read_outside
            returned["grounds"] = [
                {"ground": one.ground, "record": one.record} for one in grounds or ()
            ]
            if failure is not None:
                returned["failure"] = failure_body(failure)
            return returned

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.AUTHORIZING, DiagnosticKind.RETURNED, body
        )

    async def _check(self, one: CallToAuthorize, state: _Round) -> None:
        """Select, rule, record, and apply the checks after the policy, for one call."""
        selected = await self._selected(one.call, state)
        if isinstance(selected, CallVerdict):
            state.note(one.call, "selection", selected.verdict.value, selected.reason)
            state.verdicts.append(selected)
            return
        state.note(one.call, "selection", "passed", None)
        ruled = await self._ruled(one.call, selected, state)
        if isinstance(ruled, CallVerdict):
            state.note(one.call, "request", ruled.verdict.value, ruled.reason)
            state.verdicts.append(ruled)
            return
        verdict = await self._after_the_policy(one.call, ruled, state)
        state.verdicts.append(verdict)
        if verdict.verdict is Verdict.ALLOWED:
            tool = ruled.request.tool
            state.allowed.append(
                AllowedCall(
                    ToolCall(request=ruled.request, decision=ruled.decision),
                    deliberate_repeat=one.deliberate_repeat and not tool.safe_to_repeat,
                )
            )

    async def _selected(self, call: ProposedCall, state: _Round) -> _Selected | CallVerdict:
        """Bind ``call`` to one tool, its hub-filled arguments added (ADR-0144, ADR-0254 §3)."""
        offered = await self._offered(call, state)
        if isinstance(offered, CallVerdict):
            return offered
        candidates, parameters = offered
        eligibility = eligible_candidates(parameters, candidates)
        if eligibility.failure is not None:
            return _not_done(call, _UNCHECKABLE)
        if not eligibility.eligible:
            return _not_done(call, _NO_FIT)
        selection = select(eligibility.eligible, self._preference)
        if selection.tool is None:
            return _not_done(call, _TIED)
        return _Selected(tool=selection.tool, parameters=parameters)

    async def _offered(
        self, call: ProposedCall, state: _Round
    ) -> tuple[list[ToolDefinition], dict[str, FrozenJson]] | CallVerdict:
        """The capability's tools, which must declare alike, and the call's whole arguments.

        The hub fills every argument the declaration names ``system_supplied``, before the
        fit test, and a call whose own arguments name one is refused (ADR-0254 §3).
        """
        candidates = await self._registry.find(call.name)
        if not candidates:
            return _not_done(call, _NO_TOOL)
        first = candidates[0]
        if any(_declared(other) != _declared(first) for other in candidates[1:]):
            return _not_done(call, _DISAGREE)
        arguments: dict[str, FrozenJson] = dict(call.arguments)
        if model_supplied_keys(arguments, first):
            return _not_done(call, _HUB_FILLS)
        fills = self._filled(first.system_supplied, state)
        if fills is None:
            return _not_done(call, _UNFILLABLE)
        return list(candidates), {**arguments, **fills}

    @staticmethod
    def _filled(keys: Sequence[str], state: _Round) -> Mapping[str, FrozenJson] | None:
        """The values the hub fills for ``keys``, or ``None`` where it cannot fill one."""
        known: dict[str, FrozenJson] = {
            EPISODE_ARGUMENT: episode_address(state.activation_id),
            OUTSIDE_CONTENT_ARGUMENT: state.read_outside,
        }
        if any(key not in known for key in keys):
            return None
        return {key: known[key] for key in keys}

    async def _ruled(
        self, call: ProposedCall, selected: _Selected, state: _Round
    ) -> _Ruled | CallVerdict:
        """Bind the egress, build the request, ask the policy, and record the ruling.

        **The kind's carried fact is written here, as the old path writes it**
        (ADR-0247 §4, ADR-0260 §6): ``closed_loop`` exactly for a call to this
        deployment's own registered search, and ``forecast_reach`` exactly for a call to
        its configured forecast read, each decided by the selected tool being the one the
        deployment registered and never by a value a model wrote. The policy reaches
        ADR-0247 §2's configured-provider route only through it, so ADR-0247 §3's
        exception, which the stand-in keeps (ADR-0306 §4:4), holds for the phases' calls.
        """
        tool = selected.tool
        parameters: Mapping[str, FrozenJson] = selected.parameters
        binding: EgressBinding | None = None
        if self._binder is not None:
            try:
                bound = await self._binder.bind(
                    tool,
                    parameters=selected.parameters,
                    provenance=CarriedProvenance(
                        spans={},
                        planned_with_external_content=state.read_outside,
                        coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
                        closed_loop=str(tool.id) in self._registered_search,
                        forecast_reach=str(tool.id) in self._registered_forecast,
                    ),
                )
            except EgressBindingError:
                return _not_done(call, _UNBINDABLE)
            if bound is not None:
                tool, parameters, binding = bound.tool, bound.parameters, bound.binding
        try:
            request = ActionRequest(tool=tool, parameters=parameters, egress_binding=binding)
        except ValidationError, ValueError:
            return _not_done(call, _MALFORMED)
        effect_id = self._new_effect_id() if gets_effect_record(request.tool) else None
        ruling = await self._policy.decide(_detached_request(request))
        # Noted as the policy answers, so a check reached is in the record even where
        # appending its ruling to the trail then fails (ADR-0314 §4).
        state.note(call, "policy", ruling.outcome.value, ruling.reason)
        decision = await self._recorded(request, ruling, effect_id)
        return _Ruled(request=request, decision=decision, effect_id=effect_id)

    async def _recorded(
        self, request: ActionRequest, ruling: PermissionRuling, effect_id: str | None
    ) -> PermissionDecision:
        """Bind the ruling to its request, append it, and read it back (ADR-0037 §2-§3).

        Raises:
            AuditError: If the trail refused the append, holds nothing under the id, or
                holds anything other than the decision written.
        """
        decision = PermissionDecision.from_request(
            request, ruling, id=self._new_decision_id(), decided_at=self._now(), effect=effect_id
        )
        await self._trail.record(decision)
        recorded = await self._trail.get(decision.id)
        if recorded is None or recorded.id != decision.id or recorded != decision:
            msg = "the trail does not hold the decision that was recorded"
            raise AuditError(msg)
        return recorded

    async def _after_the_policy(
        self, call: ProposedCall, ruled: _Ruled, state: _Round
    ) -> CallVerdict:
        """The policy's ruling, then the stand-in, then ``MemoryPolicy`` (§4:1 to §4:9)."""
        decision = ruled.decision

        def verdict(kind: Verdict, reason: str | None = None) -> CallVerdict:
            if kind is not Verdict.ALLOWED:
                _log.info("authorizing_call_not_allowed", stage="authorizing", verdict=kind.value)
            return CallVerdict(
                call.call_id,
                kind,
                reason=reason,
                decision_id=decision.id,
                effect_id=ruled.effect_id,
            )

        outcome = decision.ruling.outcome
        if outcome is PermissionOutcome.DENY:
            return verdict(Verdict.NOT_DONE, _DENIED)
        if outcome is PermissionOutcome.CONFIRM:
            return verdict(Verdict.NEEDS_YOU, _CONFIRM)
        tool = ruled.request.tool
        binding = ruled.request.egress_binding
        carried = isinstance(binding, EgressBinding) and binding.planned_with_external_content
        if tool.leaves_hub and state.read_outside and not carried:
            state.note(call, "stand_in", Verdict.NEEDS_YOU.value, _STAND_IN)
            return verdict(Verdict.NEEDS_YOU, _STAND_IN)
        if tool.leaves_hub:
            state.note(call, "stand_in", "passed", None)
        if tool.capability == REMEMBER_CAPABILITY:
            remembered = await self._remembering(ruled, call, state)
            if remembered is not None:
                kind, reason = remembered
                return verdict(kind, reason)
        return verdict(Verdict.ALLOWED)

    async def _remembering(
        self, ruled: _Ruled, call: ProposedCall, state: _Round
    ) -> tuple[Verdict, str] | None:
        """``MemoryPolicy``'s ruling on what the call would write, where it stops it (§4:3).

        Ruled over the proposal alone. Its conflicts are the writer's to find, and the
        writer rules again over them when the call runs, writing nothing on an ask or a
        reject.
        """
        if ruled.effect_id is None:
            state.note(call, "memory_policy", Verdict.NOT_DONE.value, _UNCLAIMED_MEMORY)
            return Verdict.NOT_DONE, _UNCLAIMED_MEMORY
        try:
            proposal = remembered_proposal(
                ruled.request.parameters,
                record_id=remembered_record_id(ruled.effect_id),
                at=ruled.decision.decided_at,
            )
        except ValueError:
            state.note(call, "memory_policy", Verdict.NOT_DONE.value, _MALFORMED)
            return Verdict.NOT_DONE, _MALFORMED
        ruling = await self._memory_policy.decide(proposal, conflicts=(), relations=None)
        state.note(call, "memory_policy", ruling.kind.value, ruling.reason)
        if ruling.kind is MemoryDecisionKind.ASK_USER:
            return Verdict.NEEDS_YOU, _MEMORY_ASK
        if ruling.kind is MemoryDecisionKind.REJECT:
            return Verdict.NOT_DONE, _MEMORY_REJECT
        return None

    def _message(self, snapshot: RoundToAuthorize) -> MessageVerdict | None:
        """The message's place, and nothing else, checked (§4:7)."""
        message = snapshot.message
        if message is None:
            return None
        if snapshot.input_place is None or message.place != snapshot.input_place:
            _log.info("authorizing_message_not_allowed", stage="authorizing")
            return MessageVerdict(place=message.place, allowed=False, reason=_ELSEWHERE)
        return MessageVerdict(place=message.place, allowed=True, effect_id=self._new_effect_id())

    async def _story_activations(self, activation_id: str) -> tuple[str, ...]:
        """The activations of the episodes in this activation's stories, as they stand now.

        Each story the activation belongs to directly, read whole, page by page; each
        activation once, in the order found (ADR-0306 §5:9, §6:3).

        Raises:
            StoryStoreError: If the store cannot be read, or a page's cursor does not
                move on.
        """
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
        found: list[str] = []
        for header in await self._stories.stories_of(member):
            cursor: int | None = None
            while True:
                page = await self._stories.view(
                    header.story_id, cursor=cursor, limit=MAX_STORY_PAGE
                )
                if page is None:
                    break
                found.extend(
                    entry.member.id
                    for entry in page.entries
                    if entry.member.kind is StoryMemberKind.ACTIVATION
                )
                if page.next_cursor is None:
                    break
                if cursor is not None and page.next_cursor <= cursor:
                    msg = "the story store's cursor did not move on"
                    raise StoryStoreError(msg)
                cursor = page.next_cursor
        return tuple(dict.fromkeys(found))
