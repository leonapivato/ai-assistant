"""The authorizing stage: every call of a round checked by rule (ADR-0306 §4).

One orchestration-local phase module (ADR-0309 §2:2), of the kind
:class:`~ai_assistant.orchestration.acting.ActingStage` is. It is named ``authorizer``
and not ``authorizing``, which is the retiring old path's module (ADR-0312 §3, ADR-0309
§5:3). It holds injected seams onto the tool registry, the permission policy, the audit
trail, the story store, the memory store and the egress binder, and it is **not a
Protocol**. It calls no model and runs nothing: each :meth:`AuthorizingStage.
authorize` is one controller step over one recorded planning round (ADR-0309 §3:2), and
what it hands on is the decision acting and planning's next round read.

**Selection first** (§4:10, ADR-0144). Each call names a capability. The registry's
tools for it must all declare alike (ADR-0306 §2:7), the hub fills the arguments the
declaration names ``system_supplied`` (ADR-0254 §3), the fit filter drops the tools the
arguments do not satisfy (ADR-0145 §2), and the least severe tool is selected. A call
that cannot be bound to exactly one tool is not done, with its reason, and no ruling is
sought.

**Then the checks, in order** (§4:1). The policy, ``ActionPolicy`` (§4:11). Then the
outside-content stand-in (§4:4 to §4:6). Then, for a candidate or a person model's call,
its rule below. A call runs only where every check that applies allows it. A deny is
*not done* with the reason (§4:9); a confirm, or a stand-in send to the user, is *needs
you* (§4:8). Nothing parks and nothing resumes. The round's message is checked by its
place alone (§4:7), and so is each ``text`` call, which is the round's message in the form
of a call (ADR-0356 §7:7): never by the policy or the outside-content rule.

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

**A candidate** (ADR-0329 §5). A ``remember`` call records a candidate and passes no
``MemoryPolicy`` (§5:6): the observer's writes do. Authorizing rules by rule, with no
model, that one with *confirm* set needs you (§5:2), and under a ticket it runs as any
approved call does, the policy's recorded allow its deciding decision (§5:3). A candidate
it cannot read is not done. ADR-0328 §13's interim, under which remembering passed
``MemoryPolicy`` here, is retired with the composition root's switch.

**An email** (ADR-0357 §2:5-§2:10). Its tool's own checks run before it is ruled on: a
recipient that is not an address comes back saying an address is needed, since no
ADR-0148 §5:2 source resolves a person to one in this build; an attachment comes back;
and an email from the assistant's address comes back, since none is connected. One from
the user's address needs their yes, by rule, beside the policy's allow, which stays the
deciding decision, so it never runs without their yes to that exact email (§2:10).

**The person model's calls** (ADR-0338 §8:5). Every ``set_profile``, ``pin`` and
``unpin`` call needs the person's yes, by rule and with no model: a source of *needs you*
beside the policy's confirm, the stand-in's and a candidate's *confirm*, with the
policy's recorded allow as the deciding decision (ADR-0321 §4:17). Under a ticket it runs
as any approved call does (ADR-0361 §5:4); a deny still refuses it, and the policy's
confirm still asks.

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

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final, cast
from uuid import uuid4

import structlog
from pydantic import BaseModel, ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.diagnostics import failure_body, write_diagnostic
from ai_assistant.core.errors import (
    AuditError,
    EgressBindingError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ActionRequest,
    ActivationDigest,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalRequestState,
    CapabilityEffect,
    CarriedProvenance,
    DiagnosticKind,
    DiagnosticSource,
    DigestOutcome,
    EgressBinding,
    EpisodicMemory,
    LabelKind,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    SpanCoverage,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    TapOnCard,
    TicketState,
    ToolCall,
    ToolOutcome,
    canonical_json_bytes,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.approvals import (
    ALREADY_ON_A_CARD,
    CALL_ARGUMENT,
    NESTED_REPEAT_KEY,
    REQUEST_APPROVAL_CAPABILITY,
    nested_call,
)
from ai_assistant.orchestration.message_tools import (
    ATTACHMENTS_ARGUMENT,
    BCC_ARGUMENT,
    CC_ARGUMENT,
    EMAIL_CAPABILITY,
    FROM_ARGUMENT,
    FROM_ASSISTANT,
    FROM_USER,
    TO_ARGUMENT,
)
from ai_assistant.orchestration.outside_content import from_outside, is_outside_episode
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CAPABILITIES
from ai_assistant.orchestration.remembering import (
    CONFIRM_ARGUMENT,
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CAPABILITY,
    candidate_of,
)
from ai_assistant.orchestration.selection import (
    Preference,
    eligible_candidates,
    model_supplied_keys,
    select,
)
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        DiagnosticSink,
        EgressBinder,
        MemoryStore,
        PlanStore,
        StoryStore,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        ActivationEffect,
        FrozenJson,
        FrozenJsonMapping,
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
    "shown_values",
    "values_digest",
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
#: ADR-0329 §5:2: a candidate whose wording planning asked the user to confirm.
_CONFIRM_WORDING: Final = "the user is asked to confirm this wording before it is kept"
#: ADR-0338 §8:5: a change to the person's profile or pins, which runs only on their yes.
_PERSON_MODEL_YES: Final = "a change to the person's profile or pins runs only on their yes"
_ELSEWHERE: Final = "a round's message goes only into the place its input came from"
#: ADR-0357 §2:10: an email from the user's address, which runs only on their yes to it.
_USERS_ADDRESS_YES: Final = (
    "an email from the user's own address runs only on their yes to this exact email"
)
#: ADR-0357 §2:9: no address of the assistant's own is connected in this build, so an
#: email that names none, or names the assistant's, comes back saying so.
_ONLY_THE_USERS: Final = (
    "no address of the assistant's own is connected, so only the user's address is "
    f"available: name {FROM_ARGUMENT} {FROM_USER!r} to send from it, which needs their yes"
)
_NOT_A_SENDER: Final = (
    f"{FROM_ARGUMENT!r} names the assistant's address, {FROM_ASSISTANT!r}, or the user's, "
    f"{FROM_USER!r}"
)
#: ADR-0357 §2:8: nothing can be attached to an email in this build.
_CANNOT_ATTACH: Final = "nothing can be attached to an email yet, so it was not sent"
#: ADR-0350 §6:7: the reason a message of an activation the Task Scheduler started is
#: refused where it names no place on its place list.
_OFF_THE_LIST: Final = (
    "a message of an activation the Task Scheduler started goes only into the one place on "
    "its place list that it names by its place label"
)
#: ADR-0350 §5:9, §6:7: the reason such a message is refused where the place it names was
#: on the list as built for the round and is gone when authorizing checks it (#3448).
_GONE_SINCE: Final = (
    "the place this message names is gone since its place list was built: a conversation "
    "deleted, or the line disconnected, so no message goes into it"
)
_UNKNOWN_REPEAT: Final = (
    "a deliberate repeat of a call whose earlier outcome is unknown or not yet written "
    "needs the user's yes"
)

#: ADR-0361 §2:3: why ``request_approval``'s own decision allows it.
_RULED_BY_ITS_CALL: Final = (
    "request_approval is ruled by the call it asks about, whose own decision ruled it"
)
#: ADR-0361 §5:3: why a ticket's call runs nothing, in words planning reads.
_TICKET_NOT_HELD: Final = (
    "the ticket is not this work's: only the work holding the approval's input can use it"
)
_TICKET_UNREAD: Final = "the ticket could not be read from the hub's records, so nothing ran"
_TICKET_NOT_GRANTED: Final = "no ticket was granted: the person did not approve that request"
_TICKET_USED: Final = "the ticket is used: it runs its call once"
_TICKET_VOID: Final = "the ticket is void: the work that held it ended without running it"
_TICKET_EXPIRED: Final = "the ticket has expired: running the call takes a new request"
_TICKET_NOT_THE_CALL: Final = (
    "the call the ticket holds can no longer run as the person approved it"
)


def _held_by_this_rounds_requests(state: _Round) -> None:
    """A direct call this round's own request asks about waits on its card (§2:3, §2:8).

    The round's calls are ruled before any request of it is written, so a direct call
    identical to the call a ``request_approval`` of the same round asks about, in either
    order, is held back as already asked: planning narrowed it, and it runs only under
    the ticket a tap grants.
    """
    asked = [one.requested for one in state.allowed if one.requested is not None]
    if not asked:
        return
    held: set[str] = set()
    for one in state.allowed:
        if one.requested is not None or one.call.decision.approval is not None:
            continue
        request = one.call.request
        try:
            same = RequestedCall(
                tool=request.tool, values=request.parameters, binding=request.egress_binding
            )
        except ValidationError, ValueError:
            continue
        if any(each.same_call(same) for each in asked):
            held.add(str(one.call.decision.id))
    if not held:
        return
    state.allowed = [one for one in state.allowed if str(one.call.decision.id) not in held]
    state.verdicts = [
        replace(one, verdict=Verdict.NEEDS_YOU, reason=ALREADY_ON_A_CARD)
        if one.decision_id in held
        else one
        for one in state.verdicts
    ]


def _not_asked(reason: str | None) -> str:
    """ADR-0361 §2:3: a nested call refused by the ruling is not to be asked about."""
    why = "" if reason is None else f" ({reason})"
    return f"not allowed{why}, so no request was written: do not ask the person about it"


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
        ticket: Where planning ran a ticket by its ``A`` label (ADR-0361 §5:2), the
            approval request it names; ``None`` otherwise. It is a claim to check: the
            call runs under the ticket only where §5:3's checks hold against the request
            as the plan store holds it, and is rebuilt from the call the request holds.
    """

    call: ProposedCall
    deliberate_repeat: bool = False
    ticket: str | None = None


@dataclass(frozen=True, slots=True)
class RoundMessage:
    """The round's message, and the place it would be written into (ADR-0306 §4:7).

    A ``text`` call is the round's message in the form of a call (ADR-0356 §7:7), and is
    checked as one: by its place alone.

    Attributes:
        text: The message's text: a ``text`` call's words.
        place: The place it would go into; ``None`` where a message of an activation the
            Task Scheduler started names no place on its list (ADR-0350 §6:7).
        call_id: The ``text`` call it is, by the id the round proposed it under; ``None``
            for the round's own message.
    """

    text: str
    place: str | None
    call_id: str | None = None


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
        call_messages: Each ``text`` call of the round that passed planning's check, as
            the message it is (ADR-0356 §7:7), in the round's order: checked by its place
            alone, never by the policy or the outside-content rule, and so never among
            ``calls``.
        places: For an activation the Task Scheduler started, the places on its place
            list as built for the round, which its message may go into in place of the
            place its input came from (ADR-0350 §6:7); ``None`` for every other.
        gone: Those of ``places`` that are gone as the list stands when authorizing
            checks the message, a place gone since the list was built (§5:8-§5:9).
        person: The person the activation is for, whose tickets alone it may run
            (ADR-0361 §5:3); ``None`` where it is no person's.
        tickets: The approval requests whose tickets the activation holds the input of
            (ADR-0361 §5:6): the approval's own, or one a take brought it.
        taken_places: For an activation that is not the Task Scheduler's, the places an
            input it took by a take came from that take a message, which its messages
            may go into beside its input's (ADR-0361 §7:3, ADR-0306 §4:7).

    Raises:
        ValueError: If two calls or message calls share a call id, a message call names
            no call the round proposed, or a call is not one the round proposed under
            that id and name. A ticket run by its label is recorded under
            ``run_approved`` and handed on as its capability's call (ADR-0361 §5:2), so it
            is matched by its id alone.
    """

    activation_id: str
    round: PlanningRound
    working: WorkingRecord
    calls: tuple[CallToAuthorize, ...] = ()
    input_place: str | None = None
    message: RoundMessage | None = None
    call_messages: tuple[RoundMessage, ...] = ()
    places: tuple[str, ...] | None = None
    gone: tuple[str, ...] = ()
    person: str | None = None
    tickets: frozenset[str] = frozenset()
    taken_places: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Each call is one the round proposed, once."""
        proposed = {one.call_id: one.name for one in self.round.calls}
        ids = [one.call.call_id for one in self.calls]
        messages = [one.call_id for one in self.call_messages]
        if len(set(ids) | set(messages)) != len(ids) + len(messages):
            msg = "a round's calls are authorized once each"
            raise ValueError(msg)
        if any(one is None or one not in proposed for one in messages):
            msg = "a message call checked is one the round proposed, by its id"
            raise ValueError(msg)
        for one in self.calls:
            named = proposed.get(one.call.call_id)
            if named is None or (one.ticket is None and named != one.call.name):
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
            capability's calls get one, or where it runs under an approval.
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
            on a call to a capability that is not safe to repeat. For a call that runs
            under a ticket, the mark recorded with its request (ADR-0361 §2:6).
        requested: For a ``request_approval`` call, the call it asks about as ruled
            here, with the values the hub filled in and its binding (ADR-0361 §2:3,
            §2:6), which its request records; ``None`` on every other call.
    """

    call: ToolCall
    deliberate_repeat: bool = False
    requested: RequestedCall | None = None


@dataclass(frozen=True, slots=True)
class MessageVerdict:
    """What authorizing made of the round's message (ADR-0306 §4:7).

    Attributes:
        place: The place it would go into, or ``None`` where it names none.
        allowed: Whether it may be written there.
        effect_id: The effect record it is to be claimed under, where it is allowed
            (ADR-0306 §5:3).
        reason: Why it is not allowed; ``None`` where it is.
        call_id: The ``text`` call it rules on, by its id; ``None`` for the round's own
            message (ADR-0356 §7:7).
    """

    place: str | None
    allowed: bool
    effect_id: str | None = None
    reason: str | None = None
    call_id: str | None = None


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
        call_messages: Each ``text`` call's verdict, by its call id, in the round's order
            (ADR-0356 §7:7).
        read_outside_content: Whether the activation's record says it had read outside
            content when the round was authorized (ADR-0306 §4:5).
    """

    activation_id: str
    round_id: str
    verdicts: tuple[CallVerdict, ...] = ()
    allowed: tuple[AllowedCall, ...] = ()
    story_activations: tuple[str, ...] = ()
    message: MessageVerdict | None = None
    call_messages: tuple[MessageVerdict, ...] = ()
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


def _digest_identity(digest: ActivationDigest) -> str:
    """What tells one digest from another: its whole value, since it is never edited.

    Its result label alone does not, since a search's digest and a follow-up's both
    name the result they read, and no part of it short of the whole does either: two
    digests may share a result, a question and an instant and differ in evidence. The
    episode's copy and the working set's of one digest are one value (ADR-0308 §5:2).
    """
    return digest.model_dump_json()


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
            and first((_DIGEST_ANSWERED, _digest_identity(digest)))
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


def shown_values(tool: ToolDefinition, values: FrozenJsonMapping) -> dict[str, FrozenJson]:
    """A call's values as an exact line shows them (ADR-0321 §2:5).

    Every value but those the declaration names ``system_supplied``, which the hub fills
    in itself; the *looking for* argument and the *deliberate repeat* mark never reach
    authorizing (ADR-0306 §2:10). Two calls with the same tool and binding are the same
    call shown exactly where these are equal.

    Args:
        tool: The declaration the call is under.
        values: The call's values.

    Returns:
        The values a question shows.
    """
    excluded = set(tool.system_supplied)
    return {key: value for key, value in values.items() if key not in excluded}


def values_digest(request: ActionRequest) -> str:
    """The digest of a call's values the duplicate backstop compares (ADR-0306 §5).

    Acting states the same digest for the record it claims; this module may not import
    acting (ADR-0309 §2:3), and a test holds the two to one answer, as it does
    :func:`gets_effect_record`. Authorizing reads it to find the effects a deliberate
    repeat's claim would match (ADR-0321 §6:1).

    Args:
        request: The call as ruled on.

    Returns:
        A lowercase SHA-256 hex digest.
    """
    arguments = shown_values(request.tool, request.parameters)
    binding = request.egress_binding
    bound: dict[str, object] | None = None
    if isinstance(binding, EgressBinding):
        bound = {
            "account": binding.account.model_dump(mode="json"),
            "transport_endpoint": binding.transport_endpoint,
            "canonical_destination_set": [
                member.model_dump(mode="json") for member in binding.canonical_destination_set
            ],
        }
    document = cast("FrozenJson", {"arguments": arguments, "binding": bound})
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _same_values(one: FrozenJsonMapping, other: FrozenJsonMapping) -> bool:
    """Whether two calls' values are the same JSON, by their canonical encoding.

    Python's equality is not JSON's: ``True == 1`` and ``1 == 1.0``, so two calls whose
    values differ as JSON, and whose parameters digests differ, would compare equal
    (ADR-0321 §4:4, §4:11 require the values to be identical).
    """
    return canonical_json_bytes(cast("FrozenJson", dict(one))) == canonical_json_bytes(
        cast("FrozenJson", dict(other))
    )


def _same_model(one: BaseModel | None, other: BaseModel | None) -> bool:
    """Whether two declarations or bindings are the same, by value and by their JSON.

    Their JSON compared by its canonical encoding, as :func:`_same_values` compares
    values: a ``True`` against a ``1`` differs, and an object's key order does not.
    """
    if one is None or other is None:
        return one is None and other is None
    return one == other and canonical_json_bytes(
        cast("FrozenJson", one.model_dump(mode="json"))
    ) == canonical_json_bytes(cast("FrozenJson", other.model_dump(mode="json")))


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
                ticket=None if one.ticket is None else str(one.ticket),
            )
            for one in given.calls
        ),
        input_place=None if given.input_place is None else str(given.input_place),
        message=None if message is None else _detached_message(message),
        call_messages=tuple(_detached_message(one) for one in given.call_messages),
        places=None if given.places is None else tuple(str(one) for one in given.places),
        gone=tuple(str(one) for one in given.gone),
        person=None if given.person is None else str(given.person),
        tickets=frozenset(str(one) for one in given.tickets),
        taken_places=tuple(str(one) for one in given.taken_places),
    )


def _detached_message(message: RoundMessage) -> RoundMessage:
    """A message's copy, so nothing a caller still holds is checked."""
    return RoundMessage(
        str(message.text),
        None if message.place is None else str(message.place),
        None if message.call_id is None else str(message.call_id),
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


@dataclass(frozen=True, slots=True)
class _Shown:
    """A ticket's call, its checks held (ADR-0361 §5:3-§5:4).

    ``request`` is the call rebuilt from the request's, its binding through
    ``EgressBinder.rebind`` (§5:2, ADR-0321 §4:2), and ``approval`` the tap's, whose form
    names the request. ``repeat`` is the deliberate-repeat mark the request recorded.
    """

    approval: Approval
    request: ActionRequest
    repeat: bool = False


@dataclass
class _Round:
    """The facts every call of one round is checked against.

    ``checks`` holds, by call id, each check a call reached, for the diagnostic record
    (ADR-0314 §4); ``None`` where the record is off, so nothing is noted. ``rounds`` are
    this activation's rounds the working set holds, the one being authorized included;
    ``stories`` are read once, the first time a call needs them.
    """

    activation_id: str
    read_outside: bool
    rounds: tuple[PlanningRound, ...] = ()
    verdicts: list[CallVerdict] = field(default_factory=list)
    allowed: list[AllowedCall] = field(default_factory=list)
    checks: dict[str, list[dict[str, object]]] | None = None
    stories: tuple[str, ...] | None = None
    person: str | None = None
    tickets: frozenset[str] = frozenset()

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


def _is_delivered(effect: ActivationEffect) -> bool:
    """Whether ``effect`` is a message done, its position written (ADR-0306 §5:5)."""
    return (
        not effect.is_call
        and effect.outcome is ToolOutcome.SUCCEEDED
        and effect.position is not None
    )


def _ruled_verdict(
    call: ProposedCall, kind: Verdict, reason: str | None, decision: PermissionDecision
) -> CallVerdict:
    """A verdict on a call ruled under an approval, naming its deciding decision."""
    if kind is not Verdict.ALLOWED:
        _log.info("authorizing_call_not_allowed", stage="authorizing", verdict=kind.value)
    return CallVerdict(
        call.call_id, kind, reason=reason, decision_id=decision.id, effect_id=decision.effect
    )


def _not_done(call: ProposedCall, reason: str) -> CallVerdict:
    _log.info("authorizing_call_not_done", stage="authorizing")
    return CallVerdict(call.call_id, Verdict.NOT_DONE, reason=reason)


def _needs_you_by_rule(request: ActionRequest) -> tuple[str, str] | None:
    """The check that needs the user's yes by rule, and why, or ``None`` where none does.

    A person model's call (ADR-0338 §8:5), and an email from the user's own address,
    whatever allows an email from the assistant's (ADR-0357 §2:10).
    """
    capability = str(request.tool.capability)
    if capability in PERSON_MODEL_CAPABILITIES:
        return "person_model", _PERSON_MODEL_YES
    if capability == EMAIL_CAPABILITY and request.parameters.get(FROM_ARGUMENT) == FROM_USER:
        return "email", _USERS_ADDRESS_YES
    return None


#: The recipient arguments of an email, in the order a coming back names them.
_RECIPIENTS: Final = (TO_ARGUMENT, CC_ARGUMENT, BCC_ARGUMENT)

#: What an email address looks like before its protocol's canonicaliser reads it: one
#: ``@`` between a local part and a domain, with no space. A recipient that is not one is
#: a person, as planning was shown them.
_ADDRESS: Final = re.compile(r"[^@\s]+@[^@\s]+")


def _email_comes_back(arguments: Mapping[str, FrozenJson]) -> str | None:
    """Why an email runs nothing before it is ruled on, or ``None`` (ADR-0357 §2:7-§2:9).

    A recipient that is not an address is a person, resolved to an address only from a
    source ADR-0148 §5:2 allows and before the ruling, so the ruling covers the address
    it goes to (§2:7). This build wires no such source, so a person comes back saying an
    address is needed, and nothing is guessed. An attachment comes back, since nothing can
    be attached yet (§2:8). And an email from the assistant's address, which ``from``
    names or which it is sent from where ``from`` is left out, comes back, since no such
    address is connected: sending in the user's name is always named (§2:9). Whether the
    rest fits the schema is selection's, after this.
    """
    for argument in _RECIPIENTS:
        value = arguments.get(argument)
        recipients = [value] if isinstance(value, str) else value
        if not isinstance(recipients, list | tuple):
            continue
        for number, one in enumerate(recipients, 1):
            if isinstance(one, str) and _ADDRESS.fullmatch(one.strip()) is None:
                return (
                    f"no address is known for {argument!r} recipient {number}, which is not an "
                    "address: an email goes to an address, so name theirs"
                )
    attachments = arguments.get(ATTACHMENTS_ARGUMENT)
    if attachments is not None and attachments not in ([], ()):
        return _CANNOT_ATTACH
    sender = arguments.get(FROM_ARGUMENT, FROM_ASSISTANT)
    if sender == FROM_ASSISTANT:
        return _ONLY_THE_USERS
    if sender != FROM_USER:
        return _NOT_A_SENDER
    return None


class AuthorizingStage:
    """Check each call of a round by rule, and record every ruling (ADR-0306 §4)."""

    def __init__(  # noqa: PLR0913 — one keyword per seam the checks read, the preference, and the clock and id sources
        self,
        *,
        registry: ToolRegistry,
        policy: ActionPolicy,
        trail: AuditTrail,
        stories: StoryStore,
        memory: MemoryStore,
        binder: EgressBinder | None = None,
        plans: PlanStore | None = None,
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
            trail: The audit trail every ruling is recorded in and read back from.
            stories: The story store the backstop's match is collected from (§5:10).
            memory: The memory store the activation's record is read from.
            binder: The egress binding seam, or ``None`` where none is wired.
            plans: The plan store whose records a ticket's checks and a pending
                request's are read from (ADR-0361 §2:8, §5:3), and the effects a
                deliberate repeat's claim would match (ADR-0321 §6:1). ``None`` where
                none is wired, and then no ticket runs, nothing is found waiting on a
                card, and a deliberate repeat is left to the claim, which refuses one
                matching an unknown effect.
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
        self._trail = trail
        self._stories = stories
        self._memory = memory
        self._binder = binder
        self._plans = plans
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
            rounds=(*held.rounds, snapshot.round),
            checks={} if noting else None,
            person=snapshot.person,
            tickets=snapshot.tickets,
        )
        progress.append(state)
        for one in snapshot.calls:
            await self._check(one, state)
        _held_by_this_rounds_requests(state)
        stories: tuple[str, ...] = ()
        if any(not one.call.request.tool.safe_to_repeat for one in state.allowed):
            stories = await self._stories_of(state)
        return RoundAuthorization(
            activation_id=snapshot.activation_id,
            round_id=snapshot.round.id,
            verdicts=tuple(state.verdicts),
            allowed=tuple(state.allowed),
            story_activations=stories,
            message=None if snapshot.message is None else self._message(snapshot, snapshot.message),
            call_messages=tuple(self._message(snapshot, one) for one in snapshot.call_messages),
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
            if decided is not None and decided.call_messages:
                returned["call_messages"] = [
                    {
                        "call_id": one.call_id,
                        "place": one.place,
                        "allowed": one.allowed,
                        "reason": one.reason,
                    }
                    for one in decided.call_messages
                ]
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
        """Select, rule, record, and apply the checks after the policy, for one call.

        A ticket (ADR-0361 §5:2) and a ``request_approval`` (§2:3) each take their own
        path first; every other call is checked as every call is.
        """
        if one.ticket is not None:
            await self._check_ticket(one, state)
            return
        if one.call.name == REQUEST_APPROVAL_CAPABILITY:
            await self._check_request(one, state)
            return
        if one.call.name == EMAIL_CAPABILITY:
            # ADR-0357 §2:7-§2:9, §6:1: the email tool's own checks, before the ruling.
            back = _email_comes_back(one.call.arguments)
            if back is not None:
                state.note(one.call, "email", Verdict.NOT_DONE.value, back)
                state.verdicts.append(_not_done(one.call, back))
                return
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
        tool = ruled.request.tool
        repeat = one.deliberate_repeat and not tool.safe_to_repeat
        if (
            verdict.verdict is Verdict.ALLOWED
            and repeat
            and await self._matches_unknown(ruled.request, state)
        ):
            # ADR-0321 §6:1: the claim would refuse it as already done; it needs you.
            state.note(one.call, "repeat", Verdict.NEEDS_YOU.value, _UNKNOWN_REPEAT)
            verdict = replace(verdict, verdict=Verdict.NEEDS_YOU, reason=_UNKNOWN_REPEAT)
        if verdict.verdict is not Verdict.NOT_DONE:
            verdict = await self._needing_you(one.call, verdict, ruled.request, state)
        state.verdicts.append(verdict)
        if verdict.verdict is Verdict.ALLOWED:
            state.allowed.append(
                AllowedCall(
                    ToolCall(request=ruled.request, decision=ruled.decision),
                    deliberate_repeat=repeat,
                )
            )

    async def _needing_you(
        self, call: ProposedCall, verdict: CallVerdict, request: ActionRequest, state: _Round
    ) -> CallVerdict:
        """A call identical to one a pending request holds waits on its card (ADR-0361 §2:8).

        Whether the fresh checks would allow it or need the person: a call allowed now
        that ran while its request waited would run again on the ticket a tap grants
        (ADR-0321 §4:12 as ADR-0361 §11 amends it). A refusal stays a refusal, and a call
        that runs under a ticket never reaches here.
        """
        if await self._waiting_on_a_card(request, state):
            _log.info("authorizing_call_already_requested", stage="authorizing")
            state.note(call, "requested", "waiting", ALREADY_ON_A_CARD)
            return replace(verdict, verdict=Verdict.NEEDS_YOU, reason=ALREADY_ON_A_CARD)
        return verdict

    async def _waiting_on_a_card(self, request: ActionRequest, state: _Round) -> bool:
        """Whether a pending request for the person holds this very call (ADR-0361 §2:8).

        The same capability, values and binding, not yet expired. A store that cannot
        be read is no answer that none waits, so the call goes back needing the person.
        """
        if self._plans is None or state.person is None:
            return False
        try:
            asked = RequestedCall(
                tool=request.tool, values=request.parameters, binding=request.egress_binding
            )
            pending = await self._plans.person_approval_requests(
                state.person, [ApprovalRequestState.PENDING]
            )
        except ValidationError, ValueError:
            return False
        except PlanningError:
            _log.warning("authorizing_requests_unread", stage="authorizing")
            return True
        now = self._now()
        return any(one.expires_at > now and one.call.same_call(asked) for one in pending)

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
        self,
        request: ActionRequest,
        ruling: PermissionRuling,
        effect_id: str | None,
        *,
        resolves: str | None = None,
        shown: _Shown | None = None,
    ) -> PermissionDecision:
        """Bind the ruling to its request, append it, and read it back (ADR-0037 §2-§3).

        Where ``shown`` is given the decision names its approval and the part this call
        is (ADR-0321 §4:8); ``resolves`` names the confirm a route (a) decision answers
        (§4:7).

        Raises:
            AuditError: If the trail refused the append, holds nothing under the id, or
                holds anything other than the decision written.
        """
        decision = PermissionDecision.from_request(
            request,
            ruling,
            id=self._new_decision_id(),
            decided_at=self._now(),
            resolves=resolves,
            effect=effect_id,
            approval=None if shown is None else shown.approval,
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
        """The policy's ruling, the stand-in, then the person model's or a candidate's rule.

        ADR-0306 §4:1 to §4:9, and ADR-0338 §8:5's rule for the person model's calls.
        """
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
        yours = _needs_you_by_rule(ruled.request)
        if yours is not None:
            # By rule, beside the policy's allow, which stays the deciding decision
            # (ADR-0321 §4:17).
            check, reason = yours
            state.note(call, check, Verdict.NEEDS_YOU.value, reason)
            return verdict(Verdict.NEEDS_YOU, reason)
        if tool.capability == REMEMBER_CAPABILITY:
            remembered = self._candidate(ruled, call, state)
            if remembered is not None:
                kind, reason = remembered
                return verdict(kind, reason)
        return verdict(Verdict.ALLOWED)

    @staticmethod
    def _candidate(
        ruled: _Ruled, call: ProposedCall, state: _Round, *, approved: bool = False
    ) -> tuple[Verdict, str] | None:
        """Where a ``remember`` that records a candidate stops (ADR-0329 §5:2-§5:3, §5:6).

        No ``MemoryPolicy``: a candidate writes no memory. It is claimed under an effect
        record, which is what a candidate is joined to (§3:3), and read as a candidate,
        or it is not done. Where *confirm* is set it needs you, by rule and with no
        model, unless it runs under a yes (``approved``), which is that confirmation.
        """
        if ruled.effect_id is None:
            state.note(call, "candidate", Verdict.NOT_DONE.value, _UNCLAIMED_MEMORY)
            return Verdict.NOT_DONE, _UNCLAIMED_MEMORY
        try:
            candidate = candidate_of(ruled.request.parameters)
        except ValueError:
            state.note(call, "candidate", Verdict.NOT_DONE.value, _MALFORMED)
            return Verdict.NOT_DONE, _MALFORMED
        if candidate.confirm and not approved:
            state.note(call, CONFIRM_ARGUMENT, Verdict.NEEDS_YOU.value, _CONFIRM_WORDING)
            return Verdict.NEEDS_YOU, _CONFIRM_WORDING
        return None

    # --- asking, and running a ticket (ADR-0361 §2, §5) ---------------------------------

    async def _check_request(self, one: CallToAuthorize, state: _Round) -> None:  # noqa: PLR0911 — each way the nested call is refused is a return of its own
        """Rule a ``request_approval`` call by the call it asks about (ADR-0361 §2:3, §2:9).

        The nested call is selected and ruled as every call is (ADR-0306 §4:1). Where the
        policy denies it, or no tool takes it, the request is not written, and the call
        comes back not allowed and not to be asked about (ADR-0321 §2:10's second case).
        Otherwise the request is written, whether or not the ruling needs the person:
        planning may narrow what runs freely, never widen it. ``request_approval`` itself
        never needs the person and the stand-in never applies to it, so its own decision
        is an allow resting on that ruling, naming the effect record its write claims.
        """
        call = one.call
        nested = nested_call(call.arguments)
        if nested is None:
            state.note(call, "request", Verdict.NOT_DONE.value, _MALFORMED)
            state.verdicts.append(_not_done(call, _MALFORMED))
            return
        capability, arguments = nested
        held = call.arguments.get(CALL_ARGUMENT)
        marked = isinstance(held, Mapping) and held.get(NESTED_REPEAT_KEY) is True
        inner = ProposedCall(call_id=call.call_id, name=capability, arguments=arguments)
        if capability == EMAIL_CAPABILITY:
            back = _email_comes_back(inner.arguments)
            if back is not None:
                state.note(call, "email", Verdict.NOT_DONE.value, back)
                state.verdicts.append(_not_done(call, back))
                return
        selected = await self._selected(inner, state)
        if isinstance(selected, CallVerdict):
            state.note(call, "selection", selected.verdict.value, selected.reason)
            state.verdicts.append(_not_done(call, _not_asked(selected.reason)))
            return
        ruled = await self._ruled(inner, selected, state)
        if isinstance(ruled, CallVerdict):
            state.note(call, "request", ruled.verdict.value, ruled.reason)
            state.verdicts.append(_not_done(call, _not_asked(ruled.reason)))
            return
        verdict = await self._after_the_policy(inner, ruled, state)
        if verdict.verdict is Verdict.NOT_DONE:
            state.verdicts.append(
                CallVerdict(
                    call.call_id,
                    Verdict.NOT_DONE,
                    reason=_not_asked(verdict.reason),
                    decision_id=verdict.decision_id,
                )
            )
            return
        own = await self._selected(call, state)
        if isinstance(own, CallVerdict):
            state.verdicts.append(own)
            return
        try:
            request = ActionRequest(tool=own.tool, parameters=own.parameters)
            requested = RequestedCall(
                tool=ruled.request.tool,
                values=ruled.request.parameters,
                binding=ruled.request.egress_binding,
                deliberate_repeat=marked and not ruled.request.tool.safe_to_repeat,
            )
        except ValidationError, ValueError:
            state.verdicts.append(_not_done(call, _MALFORMED))
            return
        effect_id = self._new_effect_id()
        ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason=_RULED_BY_ITS_CALL)
        state.note(call, "request", Verdict.ALLOWED.value, None)
        decision = await self._recorded(request, ruling, effect_id)
        state.verdicts.append(_ruled_verdict(call, Verdict.ALLOWED, None, decision))
        state.allowed.append(
            AllowedCall(
                ToolCall(request=request, decision=decision),
                deliberate_repeat=one.deliberate_repeat,
                requested=requested,
            )
        )

    async def _check_ticket(self, one: CallToAuthorize, state: _Round) -> None:
        """Run a ticket's call under its approval, or refuse it saying why (ADR-0361 §5:3).

        Refused, not done, unless every check holds; it is never run as an ordinary call.
        """
        ticketed = await self._ticket_shown(one, state)
        if isinstance(ticketed, str):
            state.note(one.call, "ticket", "failed", ticketed)
            state.verdicts.append(_not_done(one.call, ticketed))
            return
        state.note(one.call, "ticket", "held", None)
        await self._check_approved(one, ticketed, state)

    async def _ticket_shown(self, one: CallToAuthorize, state: _Round) -> _Shown | str:  # noqa: PLR0911 — each of §5:3's checks is a return of its own
        """Check §5:3's facts against the records, and rebuild the ticket's call (§5:2).

        The label named a ticket this round was shown (planning's check); here, read
        afresh from the plan store, the request was approved by its person, the activation
        calling holds the approval's input (§5:6), the ticket is unused and not void, and
        it has not expired. The call is rebuilt from the request's: its declaration still
        offered, its values its own, its binding through ``EgressBinder.rebind`` (§5:2,
        ADR-0321 §4:2, §4:16). Each failing check is said in words planning reads.

        Returns:
            The rebuilt call and the tap's approval where every check holds; otherwise
            why not.
        """
        request_id = one.ticket
        if request_id is None or request_id not in state.tickets:
            return _TICKET_NOT_HELD
        if self._plans is None:
            return _TICKET_UNREAD
        try:
            found = await self._plans.approval_requests([request_id])
        except PlanningError:
            _log.warning("authorizing_ticket_unread", stage="authorizing")
            return _TICKET_UNREAD
        request = found[0] if found else None
        answer = None if request is None else request.answer
        if (
            request is None
            or answer is None
            or request.state is not ApprovalRequestState.APPROVED
            or state.person is None
            or request.person != state.person
        ):
            return _TICKET_NOT_GRANTED
        if request.ticket is TicketState.USED:
            return _TICKET_USED
        if request.ticket is not TicketState.HELD:
            return _TICKET_VOID
        if self._now() >= request.expires_at:
            return _TICKET_EXPIRED
        held = request.call
        if one.call.name != held.tool.capability:
            return _TICKET_NOT_THE_CALL
        rebuilt = await self._rebuilt(held)
        if rebuilt is None:
            return _TICKET_NOT_THE_CALL
        approval = Approval(
            who=answer.who,
            how=TapOnCard(
                request=request.id,
                activation_id=request.activation_id,
                round=request.round,
                expires_at=request.expires_at,
            ),
            given=ApprovalGiven(activation_id=state.activation_id, at=answer.at),
            ends=ApprovalEnd.WHEN_USED_OR_EXPIRED,
        )
        return _Shown(approval=approval, request=rebuilt, repeat=held.deliberate_repeat)

    async def _rebuilt(self, asked: RequestedCall) -> ActionRequest | None:
        """The call a request holds, rebuilt from its record, or ``None`` where it differs.

        The registry must still offer the very declaration the card showed, and the
        values recorded with the request are the values it sends, whatever the proposal
        carries beside the label (ADR-0361 §5:2, ADR-0321 §4:2). Its binding comes through
        ``EgressBinder.rebind``, which re-derives it and refuses one unequal to the
        binding shown (§4:16), so the coverage is the binding that was shown, never one
        derived over the proposal's arguments (#2847).
        """
        offered = await self._registry.find(asked.tool.capability)
        if not any(_same_model(one, asked.tool) for one in offered):
            return None
        tool: ToolDefinition = asked.tool
        parameters: FrozenJsonMapping = asked.values
        binding: EgressBinding | None = None
        if self._binder is not None:
            try:
                bound = await self._binder.rebind(
                    asked.tool, parameters=asked.values, approved=asked.binding
                )
            except EgressBindingError:
                return None
            if bound is not None:
                tool, parameters, binding = bound.tool, bound.parameters, bound.binding
        if not (
            _same_model(tool, asked.tool)
            and _same_values(parameters, asked.values)
            and _same_model(binding, asked.binding)
        ):
            return None
        try:
            return ActionRequest(tool=tool, parameters=parameters, egress_binding=binding)
        except ValidationError, ValueError:
            return None

    async def _check_approved(self, one: CallToAuthorize, shown: _Shown, state: _Round) -> None:
        """Rule a ticket's call fresh, and record it (ADR-0361 §5:4, ADR-0321 §4:3-§4:17).

        The policy is asked as for every call. A deny refuses it, and is recorded naming
        no approval: a yes never overrides one (§4:12). A confirm, the lineage rule's
        included, is resolved on route (a): the confirm is recorded naming the approval,
        ``ActionPolicy.resolve`` is asked with ``approved=True``, and the resolving
        decision records ``resolves`` naming it (§4:7). An allow is recorded naming the
        approval. The approval then lifts the outside-content stand-in and stands for a
        candidate's *confirm* (ADR-0329 §5:3), and a deliberate repeat's claim passes an
        unknown match (§6:2). Every call under an approval gets an effect
        record, its id minted before the ruling (§4:10).
        """
        call = one.call
        request = shown.request
        effect_id = self._new_effect_id()
        ruling = await self._policy.decide(_detached_request(request))
        state.note(call, "policy", ruling.outcome.value, ruling.reason)
        if ruling.outcome is PermissionOutcome.DENY:
            denied = await self._recorded(request, ruling, effect_id)
            state.verdicts.append(_ruled_verdict(call, Verdict.NOT_DONE, _DENIED, denied))
            return
        if ruling.outcome is PermissionOutcome.CONFIRM:
            confirm = await self._recorded(request, ruling, effect_id, shown=shown)
            resolved = await self._policy.resolve(confirm, approved=True)
            state.note(call, "resolve", resolved.outcome.value, resolved.reason)
            if resolved.outcome is not PermissionOutcome.ALLOW:
                denied = await self._recorded(request, resolved, effect_id, resolves=confirm.id)
                state.verdicts.append(_ruled_verdict(call, Verdict.NOT_DONE, _DENIED, denied))
                return
            decision = await self._recorded(
                request, resolved, effect_id, resolves=confirm.id, shown=shown
            )
        else:
            decision = await self._recorded(request, ruling, effect_id, shown=shown)
        tool = request.tool
        if tool.leaves_hub:
            state.note(call, "stand_in", "lifted", None)
        if tool.capability == REMEMBER_CAPABILITY:
            ruled = _Ruled(request=request, decision=decision, effect_id=effect_id)
            remembered = self._candidate(ruled, call, state, approved=True)
            if remembered is not None and remembered[0] is Verdict.NOT_DONE:
                state.verdicts.append(
                    _ruled_verdict(call, Verdict.NOT_DONE, remembered[1], decision)
                )
                return
        state.verdicts.append(_ruled_verdict(call, Verdict.ALLOWED, None, decision))
        state.allowed.append(
            AllowedCall(
                ToolCall(request=request, decision=decision),
                deliberate_repeat=shown.repeat and not tool.safe_to_repeat,
            )
        )

    async def _matches_unknown(self, request: ActionRequest, state: _Round) -> bool:
        """Whether a deliberate repeat's claim would match an unknown effect (ADR-0321 §6:1).

        The effects the claim would match are this activation's and those of the
        activations of the episodes in its stories (ADR-0306 §5:9 to §5:10): a call of
        the same capability and values digest whose outcome is unknown or not yet
        written. A done match the repeat passes, and one not done never matches.

        Raises:
            PlanningError: If the plan store cannot be read.
            StoryStoreError: If the story store cannot be read.
        """
        if self._plans is None:
            return False
        stories = await self._stories_of(state)
        match = tuple(dict.fromkeys((state.activation_id, *stories)))
        digest = values_digest(request)
        return any(
            effect.is_call
            and effect.capability == request.tool.capability
            and effect.values_digest == digest
            and effect.outcome in {None, ToolOutcome.INDETERMINATE}
            for effect in await self._plans.activation_effects(match)
        )

    async def _stories_of(self, state: _Round) -> tuple[str, ...]:
        """The activations of this activation's stories, read once per round (§5:10)."""
        if state.stories is None:
            state.stories = await self._story_activations(state.activation_id)
        return state.stories

    def _message(self, snapshot: RoundToAuthorize, message: RoundMessage) -> MessageVerdict:
        """A message's place, and nothing else, checked (§4:7).

        The round's own message, or a ``text`` call, which is the round's message in the
        form of a call and is checked by the same rule (ADR-0356 §7:7): no place is
        widened (§7:10).
        """
        if snapshot.places is not None:
            # ADR-0350 §6:7: the one place on its list it names, a place gone since the
            # list was built included, and none off it.
            if message.place is None or message.place not in snapshot.places:
                _log.info("authorizing_message_not_allowed", stage="authorizing")
                return MessageVerdict(
                    place=message.place,
                    allowed=False,
                    reason=_OFF_THE_LIST,
                    call_id=message.call_id,
                )
            if message.place in snapshot.gone:
                _log.info("authorizing_message_not_allowed", stage="authorizing")
                return MessageVerdict(
                    place=message.place,
                    allowed=False,
                    reason=_GONE_SINCE,
                    call_id=message.call_id,
                )
            return MessageVerdict(
                place=message.place,
                allowed=True,
                effect_id=self._new_effect_id(),
                call_id=message.call_id,
            )
        if message.place is None or (
            message.place != snapshot.input_place
            # ADR-0361 §7:3: or a place an input taken by a take came from.
            and message.place not in snapshot.taken_places
        ):
            _log.info("authorizing_message_not_allowed", stage="authorizing")
            return MessageVerdict(
                place=message.place, allowed=False, reason=_ELSEWHERE, call_id=message.call_id
            )
        return MessageVerdict(
            place=message.place,
            allowed=True,
            effect_id=self._new_effect_id(),
            call_id=message.call_id,
        )

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
