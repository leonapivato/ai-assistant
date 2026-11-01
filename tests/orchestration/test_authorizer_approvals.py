"""Authorizing a request for a yes and a ticket's call (ADR-0361 §2:3, §5:3-§5:4).

``request_approval`` is ruled by its nested call alone: a deny writes nothing and says
not to ask, and anything else is allowed, carrying the call as ruled. A ticket's call
runs only where §5:3's checks hold against the request the plan store holds, rebuilt
from the request's call and run under the tap's approval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    Reversibility,
    RiskLevel,
    TapOnCard,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.approvals import REQUEST_APPROVAL
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
)
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeMemoryStore,
    FakePlanStore,
    FakeStoryStore,
    FakeToolRegistry,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.authorizer import RoundAuthorization

_AT: Final = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_DAY: Final = timedelta(hours=24)
_ACTIVATION: Final = "act-holder"
_ASKER: Final = "act-asker"

_BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="Book a table for a date.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    parameters_schema={
        "type": "object",
        "properties": {"date": {"type": "string"}},
        "required": ["date"],
        "additionalProperties": False,
    },
)


class _Policy:
    """A call in the world needs the person, one for the date ``never`` is denied."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        if request.parameters.get("date") == "never":
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: never")
        if request.tool.effect is CapabilityEffect.WORLD:
            return PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="test: the world")
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        if not approved:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: refused")
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW, reason="test: approved", authorised_by=confirmed.id
        )


class _Ids:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next = 0

    def __call__(self) -> str:
        self._next += 1
        return f"{self._prefix}:{self._next}"


class _Hub:
    """The stage over fakes, its clock ``at``."""

    def __init__(self, *, at: datetime = _AT) -> None:
        self.at = at
        self.plans = FakePlanStore()
        self.trail = FakeAuditTrail(now=lambda: self.at)
        self.stage = AuthorizingStage(
            registry=FakeToolRegistry((_BOOK, REQUEST_APPROVAL)),
            policy=_Policy(),
            trail=self.trail,
            stories=FakeStoryStore(now=lambda: self.at),
            memory=FakeMemoryStore(now=lambda: self.at),
            plans=self.plans,
            now=lambda: self.at,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
        )

    async def authorize(self, *calls: CallToAuthorize, **round_: Any) -> RoundAuthorization:
        planning_round = PlanningRound(
            id="round:1", recorded_at=self.at, calls=tuple(one.call for one in calls)
        )
        return await self.stage.authorize(
            RoundToAuthorize(
                activation_id=_ACTIVATION,
                round=planning_round,
                working=WorkingRecord(),
                calls=calls,
                input_place="conversation:c-1",
                **round_,
            )
        )


def _asking(date: str) -> CallToAuthorize:
    return CallToAuthorize(
        ProposedCall(
            call_id="ask-1",
            name="request_approval",
            arguments={
                "call": {"capability": "book", "arguments": {"date": date}},
                "why": "You asked me to book the table.",
            },
        )
    )


async def test_a_request_is_ruled_by_its_call_and_carries_the_call_as_ruled() -> None:
    """§2:3, §2:9: written whether or not the ruling needs the person; never needs them."""
    hub = _Hub()
    decided = await hub.authorize(_asking("2026-11-02"))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.call.request.tool.capability == "request_approval"
    assert allowed.call.decision.effect is not None, "claimed under ADR-0306 §5"
    assert allowed.requested is not None
    assert allowed.requested.tool.capability == "book"
    assert dict(allowed.requested.values) == {"date": "2026-11-02"}


async def test_a_request_whose_call_the_policy_denies_is_not_allowed_and_not_to_be_asked() -> None:
    """§2:3: a deny writes nothing, and says it is not allowed and not to be asked about."""
    decided = await _Hub().authorize(_asking("never"))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "do not ask" in verdict.reason
    assert decided.allowed == ()


async def test_a_request_for_a_call_no_tool_takes_writes_nothing() -> None:
    """§2:2-§2:3: a call that cannot be bound is not allowed, so no request is asked."""
    call = CallToAuthorize(
        ProposedCall(
            call_id="ask-1",
            name="request_approval",
            arguments={"call": {"capability": "fly", "arguments": {}}, "why": "To fly."},
        )
    )
    decided = await _Hub().authorize(call)

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert decided.allowed == ()


# --- the ticket (§5:3-§5:4) -------------------------------------------------------------


async def _approved(
    plans: FakePlanStore,
    *,
    person: str = OWNER_PERSON_ID,
    state: ApprovalRequestState = ApprovalRequestState.APPROVED,
) -> ApprovalRequest:
    """A request written and answered by a tap, as ``request_approval`` and a tap leave it."""
    request = ApprovalRequest(
        id="approval:1",
        person=person,
        activation_id=_ASKER,
        round="round:ask",
        call=RequestedCall(tool=_BOOK, values={"date": "2026-11-02"}),
        why="You asked me to book the table.",
        written_at=_AT,
        expires_at=_AT + _DAY,
    )
    effect = ActivationEffect(
        id="effect:ask",
        activation_id=_ASKER,
        round="round:ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision:ask",
        claimed_at=_AT,
        request=request.id,
    )
    await plans.write_approval_request(request, effect, match=None)
    step = await plans.answer_approval_request(
        request.id, state, ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT)
    )
    return step.request


def _running(request: ApprovalRequest) -> CallToAuthorize:
    """The ticket's call, as planning's check hands it on (§5:2)."""
    return CallToAuthorize(
        ProposedCall(call_id="run-1", name="book", arguments={"date": "2026-11-02"}),
        ticket=str(request.id),
    )


async def test_a_held_ticket_runs_its_call_under_the_taps_approval() -> None:
    """§5:2-§5:4: rebuilt from the request, ruled fresh, the confirm resolved by the yes."""
    hub = _Hub()
    request = await _approved(hub.plans)
    decided = await hub.stage.authorize(
        _ticket_round(hub, request, tickets=frozenset({str(request.id)}))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    (allowed,) = decided.allowed
    approval = allowed.call.decision.approval
    assert approval is not None
    assert isinstance(approval.how, TapOnCard)
    assert approval.how.request == request.id
    assert approval.given.activation_id == _ACTIVATION
    assert allowed.call.decision.effect is not None


async def test_a_ticket_this_work_does_not_hold_is_refused() -> None:
    """§5:6: only the work holding the approval's input can use its ticket."""
    hub = _Hub()
    request = await _approved(hub.plans)
    decided = await hub.stage.authorize(_ticket_round(hub, request, tickets=frozenset()))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "only the work holding" in verdict.reason
    assert decided.allowed == ()


async def test_a_ticket_past_its_expiry_is_refused() -> None:
    """§5:3, §3:5: a ticket expires with its request."""
    hub = _Hub()
    request = await _approved(hub.plans)
    hub.at = _AT + _DAY
    decided = await hub.stage.authorize(
        _ticket_round(hub, request, tickets=frozenset({str(request.id)}))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "expired" in verdict.reason


async def test_a_ticket_used_or_void_is_refused() -> None:
    """§5:3, §5:5, §5:7: a ticket runs its call once, and none once void."""
    hub = _Hub()
    request = await _approved(hub.plans)
    await hub.plans.void_approval_ticket(str(request.id))
    decided = await hub.stage.authorize(
        _ticket_round(hub, request, tickets=frozenset({str(request.id)}))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "void" in verdict.reason


async def test_a_denied_request_or_another_persons_grants_no_ticket() -> None:
    """§5:3, §5:9: approved by its person, or no ticket was granted."""
    hub = _Hub()
    denied = await _approved(hub.plans, state=ApprovalRequestState.DENIED)
    decided = await hub.stage.authorize(
        _ticket_round(hub, denied, tickets=frozenset({str(denied.id)}))
    )
    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "no ticket was granted" in verdict.reason

    other = _Hub()
    theirs = await _approved(other.plans, person="someone-else")
    decided = await other.stage.authorize(
        _ticket_round(other, theirs, tickets=frozenset({str(theirs.id)}))
    )
    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE


def _ticket_round(
    hub: _Hub, request: ApprovalRequest, *, tickets: frozenset[str]
) -> RoundToAuthorize:
    call = _running(request)
    planning_round = PlanningRound(
        id="round:1",
        recorded_at=hub.at,
        calls=(ProposedCall(call_id="run-1", name="run_approved", arguments={"label": "A1"}),),
    )
    return RoundToAuthorize(
        activation_id=_ACTIVATION,
        round=planning_round,
        working=WorkingRecord(),
        calls=(call,),
        input_place="approvals:approvals",
        person=OWNER_PERSON_ID,
        tickets=tickets,
    )
