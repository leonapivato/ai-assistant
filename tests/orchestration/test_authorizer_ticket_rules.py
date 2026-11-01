"""Authorizing a ticket's call by the rules every approved call keeps (ADR-0361 §5:4).

A call that passes §5:3's checks is checked, claimed and recorded as the call its ticket
holds, and ADR-0321 §4:3, §4:7, §4:8, §4:10, §4:11, §4:15-§4:17 and §6 hold for it:
the policy is asked fresh and a deny is never overridden, a confirm is resolved on
route (a), the stand-in is lifted, an egress call is rebound to the binding the card
showed, and a deliberate repeat's retry is admitted under it. The yes path these rules
first served retired with ADR-0361 §11; a ticket is the only approval made now.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalEnd,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    CarriedProvenance,
    ChannelContext,
    CostBasis,
    DataTier,
    EgressBinding,
    EpisodeProcessingRecord,
    EpisodicMemory,
    Idempotency,
    MemorySource,
    NewConversation,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningRound,
    ProposedCall,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    RequestedCall,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    TapOnCard,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    WholeTextReply,
)
from ai_assistant.orchestration import acting
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundAuthorization,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
    shown_values,
    values_digest,
)
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
)
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeMemoryStore,
    FakePlanStore,
    FakeStoryStore,
    FakeToolRegistry,
)
from ai_assistant.testing.parties import OWNERS_WORDS

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson

_AT: Final = datetime(2026, 10, 15, 14, 15, tzinfo=UTC)
_ASKING: Final = "act-0"
_HOLDER: Final = "act-1"
_PLACE: Final = "approvals:approvals"
_REQUEST: Final = "approval:1"


def _now() -> datetime:
    return _AT


def _tool(name: str, **overrides: Any) -> ToolDefinition:
    """A declaration of one of the thin path's kinds, by ``name``."""
    kinds: dict[str, dict[str, Any]] = {
        # A read that leaves the hub; changes nothing, safe to repeat.
        "lookup": {
            "side_effecting": False,
            "reversibility": Reversibility.REVERSIBLE,
            "idempotency": Idempotency.NATURAL,
            "effect": CapabilityEffect.NONE,
            "leaves_hub": True,
            "result": CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
            "outcome_can_be_unknown": False,
            "safe_to_repeat": True,
        },
        # A booking: in the world, not safe to repeat; the policy confirms it at MEDIUM.
        "book": {
            "side_effecting": True,
            "reversibility": Reversibility.RECOVERABLE,
            "idempotency": Idempotency.NONE,
            "writes": (DataTier.PERSONAL,),
            "effect": CapabilityEffect.WORLD,
            "leaves_hub": False,
            "result": CapabilityResult.NO_OUTSIDE_TEXT,
            "outcome_can_be_unknown": True,
            "safe_to_repeat": False,
            "risk_level": RiskLevel.MEDIUM,
        },
    }
    fields: dict[str, Any] = {
        "id": name,
        "capability": name,
        "description": f"The {name} capability.",
        "risk_level": RiskLevel.LOW,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "parameters_schema": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        },
        **kinds[name],
    }
    fields.update(overrides)
    return ToolDefinition(**fields)


_BOOK: Final = _tool("book")
_LOOKUP: Final = _tool("lookup")


def _episode(activation_id: str) -> EpisodicMemory:
    """An episode at ``activation_id``'s address, as admission and planning leave it."""
    record = EpisodeProcessingRecord(
        activation_id=activation_id,
        started_at=_AT,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="the words they wrote"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
    )
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        occurred_at=_AT,
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
        processing_record=record,
    )


def _requested(
    tool: ToolDefinition | None = None,
    *,
    binding: EgressBinding | None = None,
    deliberate_repeat: bool = False,
    **values: Any,
) -> RequestedCall:
    return RequestedCall(
        tool=_BOOK if tool is None else tool,
        values=values or {"q": "table for two at 8"},
        binding=binding,
        deliberate_repeat=deliberate_repeat,
    )


class _Ids:
    """Ids minted in order under one prefix."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next = 0

    def __call__(self) -> str:
        self._next += 1
        return f"{self._prefix}:{self._next}"


class _Hub:
    """The stage and every fake it reads, wired once per test."""

    def __init__(
        self,
        *tools: ToolDefinition,
        policy: FakeActionPolicy | None = None,
        binder: FakeEgressBinder | None = None,
    ) -> None:
        self.registry = FakeToolRegistry(tools or (_LOOKUP, _BOOK, REMEMBER_CANDIDATE))
        self.policy = policy or FakeActionPolicy()
        self.trail = FakeAuditTrail(now=_now)
        self.stories = FakeStoryStore(now=_now)
        self.memory = FakeMemoryStore(now=_now)
        self.plans = FakePlanStore(now=_now)
        self.stage = AuthorizingStage(
            registry=self.registry,
            policy=self.policy,
            trail=self.trail,
            stories=self.stories,
            memory=self.memory,
            binder=binder,
            plans=self.plans,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
        )

    async def approved(self, call: RequestedCall) -> ApprovalRequest:
        """A request for ``call``, written and approved by a tap (ADR-0361 §2:6, §4:9)."""
        request = ApprovalRequest(
            id=_REQUEST,
            person=OWNER_PERSON_ID,
            activation_id=_ASKING,
            round="round:ask",
            call=call,
            why="You asked me to.",
            written_at=_AT,
            expires_at=_AT + timedelta(hours=24),
        )
        effect = ActivationEffect(
            id="effect:ask",
            activation_id=_ASKING,
            round="round:ask",
            capability="request_approval",
            values_digest="0" * 64,
            decision_id="decision:ask",
            claimed_at=_AT,
            request=request.id,
        )
        await self.plans.write_approval_request(request, effect, match=None)
        step = await self.plans.answer_approval_request(
            request.id,
            ApprovalRequestState.APPROVED,
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT),
        )
        return step.request

    async def authorize(self, given: RoundToAuthorize) -> RoundAuthorization:
        episode = _episode(given.activation_id)
        if await self.memory.get(episode.id) is None:
            await self.memory.add(episode)
        return await self.stage.authorize(given)


def _call(call_id: str, name: str, **arguments: Any) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)


def _round(
    *calls: tuple[ProposedCall, str | None], deliberate: frozenset[str] = frozenset()
) -> RoundToAuthorize:
    """The holder's round, each call handed on with the ticket it runs, where it runs one."""
    planning_round = PlanningRound(
        id="round:y", recorded_at=_AT, calls=tuple(call for call, _ in calls)
    )
    return RoundToAuthorize(
        activation_id=_HOLDER,
        round=planning_round,
        working=WorkingRecord(),
        calls=tuple(
            CallToAuthorize(call, deliberate_repeat=call.call_id in deliberate, ticket=ticket)
            for call, ticket in calls
        ),
        input_place=_PLACE,
        person=OWNER_PERSON_ID,
        tickets=frozenset({_REQUEST}),
    )


def _ticketed(call: RequestedCall, **arguments: Any) -> tuple[ProposedCall, str]:
    """The ticket's call as planning's check hands it on, its values the request's (§5:2)."""
    values = arguments or dict(call.values)
    return _call("c1", str(call.tool.capability), **values), _REQUEST


async def _recorded(trail: FakeAuditTrail, decision_id: str | None) -> PermissionDecision:
    assert decision_id is not None
    recorded = await trail.get(decision_id)
    assert recorded is not None
    return recorded


# --- a ticket's call, ruled fresh (ADR-0321 §4:3, §4:7, §4:8, §4:10) ------------------------


async def test_a_confirmed_booking_runs_on_route_a_under_the_ticket() -> None:
    """The confirm ruled fresh is resolved on route (a), and both decisions name the tap."""
    hub = _Hub()
    requested = _requested()
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW
    assert deciding.resolves is not None
    confirm = await _recorded(hub.trail, deciding.resolves)
    assert confirm.ruling.outcome is PermissionOutcome.CONFIRM
    ((resolved, approved),) = hub.policy.resolutions
    assert resolved == confirm
    assert approved is True
    for one in (confirm, deciding):
        assert one.approval is not None
        assert one.approved_part is None
        assert one.effect == verdict.effect_id
    approval = deciding.approval
    assert approval is not None
    assert approval.who is ApprovalGiver.USER_TAP_ON_HUB_PANEL
    assert isinstance(approval.how, TapOnCard)
    assert approval.how.request == _REQUEST
    assert approval.covers == ()
    assert approval.given.activation_id == _HOLDER
    assert approval.ends is ApprovalEnd.WHEN_USED_OR_EXPIRED
    (allowed,) = decided.allowed
    assert allowed.call.decision == deciding
    assert allowed.call.decision.authorises(allowed.call.request)
    assert dict(allowed.call.request.parameters) == dict(requested.values)


async def test_the_values_are_the_requests_whatever_the_proposal_carries() -> None:
    """§5:2: nothing planning sends beside the label changes the values the card showed."""
    hub = _Hub()
    requested = _requested()
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested, q="the whole restaurant")))

    (allowed,) = decided.allowed
    assert dict(allowed.call.request.parameters) == {"q": "table for two at 8"}


async def test_an_allow_outright_still_names_the_approval_and_an_effect() -> None:
    """ADR-0321 §4:10: every call under an approval gets an effect record."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    requested = _requested(_LOOKUP, q="trains to Lyon")
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW
    assert deciding.resolves is None
    assert deciding.approval is not None
    # A lookup gets no effect record of its own; under a ticket it does.
    assert deciding.effect is not None
    assert hub.policy.resolutions == []


async def test_a_declaration_no_longer_offered_is_not_the_call_the_card_showed() -> None:
    """§5:2: the registry still offers the very declaration the request holds."""
    hub = _Hub()
    requested = _requested(_tool("book", description="The booking, as it was."))
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert decided.allowed == ()


# --- a deny is never overridden (ADR-0321 §4:3, §4:11) --------------------------------------


async def test_a_deny_refuses_a_tickets_call() -> None:
    hub = _Hub(policy=FakeActionPolicy(deny_at=RiskLevel.MEDIUM))
    requested = _requested()
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    recorded = await _recorded(hub.trail, verdict.decision_id)
    assert recorded.ruling.outcome is PermissionOutcome.DENY
    assert recorded.approval is None
    assert hub.policy.resolutions == []
    assert decided.allowed == ()


class _RefusingResolution(FakeActionPolicy):
    """A policy that no longer accepts a confirmation it is asked to resolve."""

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        self.resolutions.append((confirmed, approved))
        return PermissionRuling(outcome=PermissionOutcome.DENY, reason="the ceiling is spent")


async def test_a_resolution_that_denies_refuses_the_call() -> None:
    """ADR-0321 §4:3, §4:7: route (a)'s resolve may deny, and then nothing runs."""
    hub = _Hub(policy=_RefusingResolution())
    requested = _requested()
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.DENY
    assert deciding.resolves is not None
    assert deciding.approval is None
    assert decided.allowed == ()


# --- egress: the binding the card showed, through rebind (ADR-0321 §4:16, #2847) ------------


async def test_a_tickets_egress_call_rebinds_to_the_binding_requested() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder)
    bound = await binder.bind(
        tool, parameters={"q": "trains to Lyon"}, provenance=_carried(outside=True)
    )
    assert bound is not None
    requested = _requested(tool, binding=bound.binding, q="trains to Lyon")
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    (allowed,) = decided.allowed
    assert allowed.call.request.egress_binding == requested.binding
    deciding = await _recorded(hub.trail, verdict.decision_id)
    # The lineage rule's confirm, resolved on route (a) (ADR-0321 §4:7).
    assert deciding.resolves is not None


async def test_an_egress_call_requested_without_its_binding_is_not_the_call_shown() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder, policy=FakeActionPolicy(confirm_at=None))
    requested = _requested(tool, q="trains to Lyon")
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert decided.allowed == ()


def _carried(*, outside: bool) -> CarriedProvenance:
    return CarriedProvenance(
        spans={},
        planned_with_external_content=outside,
        coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
    )


# --- a retry after an unknown outcome (ADR-0321 §6) ------------------------------------------


async def _earlier(hub: _Hub, outcome: ToolOutcome | None) -> None:
    """A booking this activation made earlier, with ``outcome``."""
    request = ActionRequest(tool=_BOOK, parameters={"q": "table for two at 8"})
    effect = ActivationEffect(
        id="effect:earlier",
        activation_id=_HOLDER,
        round="round:earlier",
        capability="book",
        values_digest=values_digest(request),
        decision_id="decision:earlier",
        claimed_at=_AT,
    )
    await hub.plans.claim_activation_effect(effect, match=None)
    if outcome is not None:
        await hub.plans.finish_activation_effect(effect.id, outcome)


@pytest.mark.parametrize(
    ("outcome", "verdict"),
    [
        (ToolOutcome.INDETERMINATE, Verdict.NEEDS_YOU),
        (None, Verdict.NEEDS_YOU),
        (ToolOutcome.SUCCEEDED, Verdict.ALLOWED),
    ],
    ids=["unknown", "unwritten", "done"],
)
async def test_a_deliberate_repeat_of_an_unknown_effect_needs_you(
    outcome: ToolOutcome | None, verdict: Verdict
) -> None:
    """§6:1: authorizing rules it so, reading the effect records the claim would match."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    await _earlier(hub, outcome)

    decided = await hub.authorize(
        _round((_call("c1", "book", q="table for two at 8"), None), deliberate=frozenset({"c1"}))
    )

    (ruled,) = decided.verdicts
    assert ruled.verdict is verdict
    if verdict is Verdict.NEEDS_YOU:
        assert decided.allowed == ()


async def test_a_retry_under_a_ticket_runs_under_the_approval() -> None:
    """§6:2: the claim admits a deliberate repeat under an approval; nothing else does."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    await _earlier(hub, ToolOutcome.INDETERMINATE)
    requested = _requested(deliberate_repeat=True)
    await hub.approved(requested)

    decided = await hub.authorize(_round(_ticketed(requested)))

    (allowed,) = decided.allowed
    assert allowed.deliberate_repeat is True
    assert allowed.call.decision.approval is not None


# --- the digest acting claims under, stated twice --------------------------------------------


def test_the_values_digest_is_actings() -> None:
    """ADR-0309 §2:3: restated here, held to one answer with acting's."""
    tool = _tool("lookup")
    for request in (
        ActionRequest(tool=_BOOK, parameters={"q": "table"}),
        ActionRequest(tool=tool, parameters={"q": "x"}),
        ActionRequest(
            tool=REMEMBER_CANDIDATE,
            parameters={
                "fact": "likes tea",
                "why": "a taste",
                "rests_on_input": True,
                EPISODE_ARGUMENT: "activation:a",
                OUTSIDE_CONTENT_ARGUMENT: False,
            },
        ),
    ):
        call = ToolCall(request=request, decision=_allowed(request))
        assert values_digest(request) == acting.values_digest(call)


async def test_the_digest_with_a_binding_is_actings() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    bound = await binder.bind(tool, parameters={"q": "x"}, provenance=_carried(outside=False))
    assert bound is not None
    request = ActionRequest(tool=tool, parameters={"q": "x"}, egress_binding=bound.binding)

    call = ToolCall(request=request, decision=_allowed(request))

    assert values_digest(request) == acting.values_digest(call)


def _allowed(request: ActionRequest) -> PermissionDecision:
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="decision:d",
        decided_at=_AT,
    )


def test_the_shown_values_leave_out_what_the_hub_fills() -> None:
    """§2:5: ``system_supplied`` is left out."""
    values: dict[str, FrozenJson] = {
        "fact": "s",
        EPISODE_ARGUMENT: "activation:a",
        OUTSIDE_CONTENT_ARGUMENT: True,
    }

    assert shown_values(REMEMBER_CANDIDATE, values) == {"fact": "s"}
