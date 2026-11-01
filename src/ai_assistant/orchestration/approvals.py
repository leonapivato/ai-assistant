"""The Approvals channel's declarations: its kind, its two calls and its shapes (ADR-0361).

**Approvals** is a built-in channel with exactly one place, **the approvals** (§3:1). It is
a medium the hub hosts: it holds the approval requests ``request_approval`` writes, each
with its ticket, in the plan store (§3:2), and the assistant reaches it only through its
sensor (:mod:`~ai_assistant.orchestration.approval_sensor`) and its actuator, the direct
write ``request_approval`` makes (§3:3). It is fully private: its kind takes no spoke on
any device, and a person reaches it only by a tap on a card and the panel's query (§4).

This module is what the rest of the package shares of it, and runs nothing. It imports no
phase module, so every phase module may read it (ADR-0309 §2:3):

- **Its kind** (:data:`APPROVALS_KIND`, §3:6), in
  :class:`~ai_assistant.orchestration.channel_kinds.ChannelKind`'s shape, as the Task
  Scheduler's is declared (ADR-0350 §2:6): its place runs activations side by side, takes
  no message from a person or from the assistant, shows no running work and expects no
  reply; it pushes and cannot be pulled; it has no window and no approval giver; and its
  audience is private. ``core``'s register declares its inputs' parties empty.
- **The two calls** planning is offered (§2:1, §5:2): :data:`REQUEST_APPROVAL`, a
  capability whose call writes a request, and :data:`RUN_APPROVED_TOOL`, the tool a
  ticket is run by, by its ``A`` label alone, which is no capability: planning's check
  turns it into the call its ticket holds (ADR-0321 §4:2).
- **A ticket** (:class:`Ticket`, §5:1), what an activation holding an approval's input is
  shown and may run once.
- **The hub's renderings** of the approval's input (§6:1-§6:2): its outcome, stated by the
  hub from the record and carrying no one's words.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.channel_validation import APPROVALS
from ai_assistant.core.types import (
    ApprovalRequestState,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    TicketState,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.channel_kinds import (
    Audience,
    ChannelKind,
    Direction,
    Reach,
    WindowSource,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import ApprovalRequest, FrozenJson

__all__ = [
    "ALREADY_ON_A_CARD",
    "APPROVALS_DESCRIPTION",
    "APPROVALS_KIND",
    "APPROVAL_CAPABILITIES",
    "ARGUMENTS_KEY",
    "CALL_ARGUMENT",
    "CAPABILITY_KEY",
    "NESTED_REPEAT_KEY",
    "REQUEST_APPROVAL",
    "REQUEST_APPROVAL_CAPABILITY",
    "RUN_APPROVED_DESCRIPTION",
    "RUN_APPROVED_LABEL",
    "RUN_APPROVED_SCHEMA",
    "RUN_APPROVED_TOOL",
    "THE_APPROVALS",
    "WHY_ARGUMENT",
    "Ticket",
    "approval_input",
    "nested_call",
    "ticket_of",
]

#: The approvals, the Approvals channel's one place (ADR-0361 §3:1). Every activation an
#: outcome starts is admitted on it, so its episode is indexed by it (ADR-0292 §10:5).
THE_APPROVALS: Final = ChannelIdentity(channel_type=APPROVALS, instance_id="approvals")

#: What planning is shown of the approvals' place (ADR-0292 §8:1), for an activation an
#: outcome started: no one is waiting on a reply here, and its messages go into the places
#: on its place list (§6:7).
APPROVALS_DESCRIPTION: Final = (
    "Approvals: the person answered a request for their yes, or it expired, and that "
    "started this activation. No one is waiting on a reply here; a message you write goes "
    "into the one place on your place list that it names."
)

#: ADR-0361 §3:6: what the Approvals channel's kind declares, each row in the ADR-0292
#: clause its name gives, as the Task Scheduler's kind declares its own (ADR-0350 §2:6).
APPROVALS_KIND: Final = ChannelKind(
    channel_type=APPROVALS,
    channels="exactly one, built in, Approvals",
    direction=Direction.IN,
    reach=Reach.PUSHES,
    input="an approval request answered by a tap, or expired",
    push_filter=None,
    authors=(
        "the request's person, stated by the hub from the record; no author is "
        "established as the user"
    ),
    places="exactly one, the approvals",
    window=WindowSource.NONE,
    window_items=None,
    sent="nothing: its place takes no message from a person or from the assistant",
    description=APPROVALS_DESCRIPTION,
    text_only=True,
    message_limit=None,
    audience=Audience.PRIVATE,
    approval_giver=None,
)

# --- the two calls (ADR-0361 §2, §5) -------------------------------------------------------

REQUEST_APPROVAL_CAPABILITY: Final = "request_approval"

#: ADR-0361 §5:2: the tool a ticket is run by. No capability: planning's check turns a
#: call to it into the call its ticket holds, as an approved action's (ADR-0321 §4:2).
RUN_APPROVED_TOOL: Final = "run_approved"

#: Every capability this module declares.
APPROVAL_CAPABILITIES: Final = frozenset({REQUEST_APPROVAL_CAPABILITY})

#: ``request_approval``'s two arguments (§2:1).
CALL_ARGUMENT: Final = "call"
WHY_ARGUMENT: Final = "why"
#: The nested call's parts: its capability's name and its exact arguments.
CAPABILITY_KEY: Final = "capability"
ARGUMENTS_KEY: Final = "arguments"
#: The nested call's deliberate-repeat mark, as planning's check moves it out of the
#: nested arguments (ADR-0306 §2:10): the request records it (ADR-0361 §2:6).
NESTED_REPEAT_KEY: Final = "deliberate_repeat"

#: ADR-0361 §2:2, §5:4: why a direct call comes back needing the person while a request
#: for the very same call still waits on them: it is not asked about again, and nothing
#: is approved. Shared by authorizing, which rules it, and planning, which says it.
ALREADY_ON_A_CARD: Final = (
    "already asked for on a card, and the request waits on the person: it is not asked "
    "again, and nothing is approved"
)

#: ``run_approved``'s one argument (§5:2).
RUN_APPROVED_LABEL: Final = "label"

#: The bound, in characters, on ``why`` (core's ``APPROVAL_WHY_MAX_CHARS``).
_WHY_MAX: Final = 4_000

# The words are drafted lean and flagged for the coordinator's descriptions walk (the
# brief's §2:10 words): what the call does; when to use it and when not; what planning
# chooses; what comes back. The effects part is generated from the declaration (T2).
_REQUEST_APPROVAL_DESCRIPTION: Final = (
    "Ask the person for their yes to one call, on a card they tap. "
    "Some calls need the person's yes before they run: when a call comes back needing it, "
    "ask with this call, with the same capability and arguments, and never with a "
    "question in words. Explain in why what the call does and the arguments that matter. "
    "The person answers on the card, Approve or Deny; a yes written in a conversation "
    "approves nothing. A yes runs nothing: it grants a ticket, which run_approved runs "
    "once. Never approve on anyone's behalf. There is no other way to get a yes. "
    "Comes back saying the request was written and waits on the person, that the hub "
    "page's approvals panel shows it, and how its card went on the line; or, writing "
    "nothing, why not: the call is not one you are offered or its arguments do not fit, "
    "it is not allowed and is not to be asked about, or the same request already waits "
    "on the person, and since when."
)

_REQUEST_APPROVAL_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "object",
    "properties": {
        CALL_ARGUMENT: {
            "type": "object",
            "description": (
                "The call to approve: capability, its name as you are offered it, and "
                "arguments, exactly the arguments you would call it with."
            ),
            "properties": {
                CAPABILITY_KEY: {"type": "string", "minLength": 1},
                ARGUMENTS_KEY: {"type": "object"},
                NESTED_REPEAT_KEY: {"type": "boolean"},
            },
            "required": [CAPABILITY_KEY, ARGUMENTS_KEY],
            "additionalProperties": False,
        },
        WHY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": _WHY_MAX,
            "description": (
                "Why the call is needed, in your own words: what it does and the arguments "
                "that matter. The card shows it to the person."
            ),
        },
    },
    "required": [CALL_ARGUMENT, WHY_ARGUMENT],
    "additionalProperties": False,
}

#: ADR-0361 §2:1, §2:9, §3:3: ``request_approval``, the Approvals channel's actuator. Its
#: effect is the assistant's own records, a request written into the plan store; it never
#: leaves the hub, its result is the hub's own text, and it is not safe to repeat, so it
#: is claimed and recorded under ADR-0306 §5 with an effect record naming its request. It
#: is ruled by its nested call alone (§2:3).
REQUEST_APPROVAL: Final = ToolDefinition(
    id=REQUEST_APPROVAL_CAPABILITY,
    capability=REQUEST_APPROVAL_CAPABILITY,
    description=_REQUEST_APPROVAL_DESCRIPTION,
    risk_level=RiskLevel.LOW,
    # A request expires, or is answered, and nothing runs on it by itself (§5:1).
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.OWN_RECORDS,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=False,
    safe_to_repeat=False,
    parameters_schema=_REQUEST_APPROVAL_SCHEMA,
)

#: ``run_approved``'s words (§5:2-§5:3, §5:8), drafted lean and flagged as the brief asks.
RUN_APPROVED_DESCRIPTION: Final = (
    "Run the call a ticket holds, once. A ticket is the person's yes to one request, "
    "shown to you under an A label; its arguments are the ones the person approved, "
    "filled in for you. Run it only while the situation is the one the person approved; "
    "where it has changed or too long has passed, run nothing, say why in your notes, and "
    "ask again with request_approval. Comes back with what the call came to; or, running "
    "nothing, why not: the label names no ticket you were shown, or the ticket is used, "
    "void, expired or not yours to use."
)

#: ``run_approved``'s schema: the ticket's label, and a *looking for* where the call its
#: ticket holds may bring text someone else wrote (ADR-0306 §2:8).
RUN_APPROVED_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "object",
    "properties": {
        RUN_APPROVED_LABEL: {
            "type": "string",
            "minLength": 1,
            "description": "The ticket, by the A label you were shown it under.",
        },
        "looking_for": {
            "type": "string",
            "description": (
                "What you are looking for in the call's result. Give it where the ticket "
                "says its result may carry text someone else wrote; otherwise leave it out."
            ),
        },
    },
    "required": [RUN_APPROVED_LABEL],
    "additionalProperties": False,
}


def nested_call(arguments: Mapping[str, FrozenJson]) -> tuple[str, dict[str, FrozenJson]] | None:
    """The call a ``request_approval`` call holds: its capability and its arguments.

    ``None`` where its ``call`` is not an object naming a capability and holding its
    arguments as an object.
    """
    call = arguments.get(CALL_ARGUMENT)
    if not isinstance(call, Mapping):
        return None
    capability = call.get(CAPABILITY_KEY)
    nested = call.get(ARGUMENTS_KEY)
    if not isinstance(capability, str) or not capability.strip():
        return None
    if not isinstance(nested, Mapping):
        return None
    return capability, dict(nested)


# --- a ticket (ADR-0361 §5) -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ticket:
    """A ticket an activation holds, as planning is shown it (ADR-0361 §5:1-§5:3).

    The approval request a tap approved, with its ticket still held: its exact call, for
    the request's person, usable once. Planning shows it under an ``A`` label naming the
    request and runs it by that label alone (§5:2); planning's check fills in the values
    and the binding recorded with the request, and authorizing reads the request again
    for §5:3's checks.

    Attributes:
        request: The approval request, as the plan store held it when the round read it.
    """

    request: ApprovalRequest

    @property
    def request_id(self) -> str:
        """The request, which the ticket's ``A`` label names (§5:5's spending key)."""
        return str(self.request.id)


def ticket_of(request: ApprovalRequest, *, at: datetime) -> Ticket | None:
    """``request``'s ticket, where it holds one still usable at ``at`` (§5:1, §5:7).

    Approved, its ticket held, and not expired.
    """
    if request.state is not ApprovalRequestState.APPROVED:
        return None
    if request.ticket is not TicketState.HELD or at >= request.expires_at:
        return None
    return Ticket(request=request)


# --- the approval's input (ADR-0361 §6:1-§6:2) ---------------------------------------------

_OUTCOMES: Final = {
    ApprovalRequestState.APPROVED: (
        "A request for the person's yes was approved: they tapped Approve on its card. "
        "The yes runs nothing by itself: it grants a ticket for the request's exact call, "
        "usable once."
    ),
    ApprovalRequestState.DENIED: (
        "A request for the person's yes was denied: they tapped Deny on its card. No "
        "ticket was granted, and nothing runs."
    ),
    ApprovalRequestState.EXPIRED: (
        "A request for the person's yes expired before anyone answered it. No ticket was "
        "granted, and nothing runs."
    ),
}


def approval_input(request: ApprovalRequest) -> str:
    """The input an approval's activation is given, stated by the hub (§6:1-§6:2).

    The outcome and a reference to the request, structured and carrying no one's words:
    the request's ``why`` and its call are context the input brings, never the input. The
    ticket's ``A`` label is planning's, minted where the ticket is shown (§5:1).

    Raises:
        ValueError: If the request is still pending, which starts no activation (§3:7).
    """
    outcome = _OUTCOMES.get(request.state)
    if outcome is None:
        msg = "only a request answered or expired starts an activation (ADR-0361 §3:7)"
        raise ValueError(msg)
    return f"{outcome} Request: {request.id}."
