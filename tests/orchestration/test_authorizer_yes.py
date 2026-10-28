"""Authorizing a yes (ADR-0321 §4, §6:1), driven directly over fakes.

Every case builds, by hand, what the yes path reads: the asking activation's stored
episode with the round that asked (§2:8), its message's delivery record in the plan
store (ADR-0306 §5:5), and the yes's activation's round proposing the approved call by
its part, as the wiring lane will hand it over. It then reads the decision that came
back and what the canonical ``FakeAuditTrail`` holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    AnsweredQuestion,
    ApprovalEnd,
    ApprovalGiver,
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    CarriedProvenance,
    ChannelContext,
    CostBasis,
    DataTier,
    DiagnosticKind,
    DiagnosticSource,
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
    QuestionPart,
    RecordedChannelTrigger,
    RecordedTextInput,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
    WholeTextReply,
)
from ai_assistant.orchestration import acting
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    OwnRecordsByCapability,
)
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundAuthorization,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
    YesContext,
    shown_values,
    values_digest,
)
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
)
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeDiagnosticSink,
    FakeEgressBinder,
    FakeMemoryStore,
    FakePlanStore,
    FakeStoryStore,
    FakeToolRegistry,
)
from ai_assistant.testing.parties import OWNERS_WORDS, UNIDENTIFIED_WORDS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import FrozenJson, MemoryRecord

_AT: Final = datetime(2026, 10, 15, 14, 15, tzinfo=UTC)
_ASKING: Final = "act-0"
_YES: Final = "act-1"
_QUESTION: Final = "round:q"
_PLACE: Final = "conversation:chat"
_PART: Final = QuestionPart(round=_QUESTION, part=1)


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


def _episode(
    activation_id: str, *, rounds: Sequence[PlanningRound] = (), outside: bool = False
) -> EpisodicMemory:
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
            parties=UNIDENTIFIED_WORDS if outside else OWNERS_WORDS,
        ),
        rounds=tuple(rounds),
    )
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        occurred_at=_AT,
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
        processing_record=record,
    )


def _asked(
    tool: ToolDefinition = _BOOK,
    *,
    part: int = 1,
    binding: EgressBinding | None = None,
    deliberate_repeat: bool = False,
    **values: Any,
) -> AskedCall:
    return AskedCall(
        part=part,
        tool=tool,
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
        plans: bool = True,
        diagnostics: FakeDiagnosticSink | None = None,
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
            plans=self.plans if plans else None,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
            diagnostics=diagnostics,
        )

    async def asked(
        self,
        *asked: AskedCall,
        activation_id: str = _ASKING,
        round_id: str = _QUESTION,
        delivered: ToolOutcome | None = ToolOutcome.SUCCEEDED,
        outside: bool = False,
        place: str = _PLACE,
    ) -> None:
        """Store the asking activation's episode, and its question's delivery record."""
        await self.memory.add(
            _episode(
                activation_id,
                rounds=(PlanningRound(id=round_id, recorded_at=_AT, asked=asked),),
                outside=outside,
            )
        )
        effect = ActivationEffect(
            id=f"effect:message-{activation_id}-{round_id}",
            activation_id=activation_id,
            round=round_id,
            place=place,
            claimed_at=_AT,
        )
        await self.plans.claim_activation_effect(effect, match=None)
        if delivered is ToolOutcome.SUCCEEDED:
            await self.plans.finish_activation_effect(effect.id, delivered, position=3)
        elif delivered is ToolOutcome.FAILED:
            await self.plans.finish_activation_effect(effect.id, delivered, reason="no medium")
        elif delivered is not None:
            await self.plans.finish_activation_effect(effect.id, delivered)

    async def authorize(
        self, given: RoundToAuthorize, *, outside: bool = False
    ) -> RoundAuthorization:
        episode = _episode(given.activation_id, outside=outside)
        if await self.memory.get(episode.id) is None:
            await self.memory.add(episode)
        return await self.stage.authorize(given)


def _yes(  # noqa: PLR0913 — one keyword per part of the pointer a case varies
    *,
    parts: tuple[int, ...] = (),
    authority: bool = True,
    activation_id: str = _ASKING,
    round_id: str | None = _QUESTION,
    place: str | None = None,
    position: int | None = None,
    who: ApprovalGiver = ApprovalGiver.USER_THROUGH_HUB_CHAT,
) -> YesContext:
    return YesContext(
        answers=(
            AnsweredQuestion(
                activation_id=activation_id,
                round=round_id,
                place=place,
                position=position,
                parts=parts,
            ),
        ),
        given_at=_AT,
        users_authority=authority,
        who=who,
    )


def _call(call_id: str, name: str, **arguments: Any) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)


def _round(
    *calls: tuple[ProposedCall, QuestionPart | None],
    yes: YesContext | None = None,
    activation_id: str = _YES,
    deliberate: frozenset[str] = frozenset(),
    working: WorkingRecord | None = None,
) -> RoundToAuthorize:
    """The yes's activation's round, each call handed on with its approved part."""
    planning_round = PlanningRound(
        id="round:y", recorded_at=_AT, calls=tuple(call for call, _ in calls)
    )
    return RoundToAuthorize(
        activation_id=activation_id,
        round=planning_round,
        working=working or WorkingRecord(),
        calls=tuple(
            CallToAuthorize(call, deliberate_repeat=call.call_id in deliberate, approved_part=part)
            for call, part in calls
        ),
        input_place=_PLACE,
        yes=yes,
    )


def _approved_booking(**arguments: Any) -> tuple[ProposedCall, QuestionPart]:
    return _call("c1", "book", **(arguments or {"q": "table for two at 8"})), _PART


async def _recorded(trail: FakeAuditTrail, decision_id: str | None) -> PermissionDecision:
    assert decision_id is not None
    recorded = await trail.get(decision_id)
    assert recorded is not None
    return recorded


# --- a yes that holds ----------------------------------------------------------------------


async def test_a_confirmed_booking_runs_on_route_a_under_the_approval() -> None:
    """§4:4-§4:8, §4:14: the facts hold; the confirm ruled fresh is resolved on route (a)."""
    hub = _Hub()
    asked = _asked()
    await hub.asked(asked)

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW
    assert deciding.resolves is not None
    confirm = await _recorded(hub.trail, deciding.resolves)
    assert confirm.ruling.outcome is PermissionOutcome.CONFIRM
    ((resolved, approved),) = hub.policy.resolutions
    assert resolved == confirm
    assert approved is True
    # Both decisions about the call that runs name the approval and its part (§4:8),
    # and the deciding one the effect record it is claimed under (§4:10, §4:14).
    for one in (confirm, deciding):
        assert one.approval is not None
        assert one.approved_part == _PART
        assert one.effect == verdict.effect_id
    approval = deciding.approval
    assert approval is not None
    assert approval.who is ApprovalGiver.USER_THROUGH_HUB_CHAT
    assert approval.how.activation_id == _ASKING
    assert approval.how.round == _QUESTION
    assert approval.covers == (_PART,)
    assert approval.given.activation_id == _YES
    assert approval.given.at == _AT
    assert approval.ends is ApprovalEnd.WHEN_USED
    (allowed,) = decided.allowed
    assert allowed.asked == asked
    assert allowed.call.decision == deciding
    assert allowed.call.decision.authorises(allowed.call.request)
    assert dict(allowed.call.request.parameters) == dict(asked.values)


async def test_the_values_are_the_recorded_ones_whatever_the_proposal_carries() -> None:
    """§4:2: nothing planning sends beside the label changes the values shown."""
    hub = _Hub()
    asked = _asked()
    await hub.asked(asked)

    decided = await hub.authorize(_round(_approved_booking(q="the whole restaurant"), yes=_yes()))

    (allowed,) = decided.allowed
    assert dict(allowed.call.request.parameters) == {"q": "table for two at 8"}


async def test_an_allow_outright_still_names_the_approval_and_an_effect() -> None:
    """The dispatcher's ruling: the facts are checked for every approved call (§4:10)."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    asked = _asked(_LOOKUP, q="trains to Lyon")
    await hub.asked(asked)

    decided = await hub.authorize(
        _round((_call("c1", "lookup", q="trains to Lyon"), _PART), yes=_yes())
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW
    assert deciding.resolves is None
    assert deciding.approval is not None
    # A lookup gets no effect record of its own; under an approval it does (§4:10).
    assert deciding.effect is not None
    assert hub.policy.resolutions == []
    (allowed,) = decided.allowed
    # Acting takes it: an approved call's decision names its effect (ADR-0321 §4:10).
    AuthorizedCall(allowed.call, deliberate_repeat=allowed.deliberate_repeat)


async def test_the_approval_lifts_the_stand_in() -> None:
    """§4:12, §4:17: the policy's allow decides, and the yes lifts the stand-in."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    asked = _asked(_LOOKUP, q="trains to Lyon")
    await hub.asked(asked)
    given = _round((_call("c1", "lookup", q="trains to Lyon"), _PART), yes=_yes())

    decided = await hub.authorize(given, outside=True)

    assert decided.read_outside_content is True
    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW
    assert deciding.approval is not None


async def test_without_the_approval_the_stand_in_still_needs_you() -> None:
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    given = _round((_call("c1", "lookup", q="trains to Lyon"), None))

    decided = await hub.authorize(given, outside=True)

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.request is not None
    assert dict(verdict.request.parameters) == {"q": "trains to Lyon"}


async def test_a_yes_covers_every_part_shown_or_only_the_parts_it_names() -> None:
    """§3:6: an empty part list approves every part the question showed."""
    hub = _Hub()
    first = _asked(part=1, q="table at 8")
    second = _asked(part=2, q="table at 9")
    await hub.asked(first, second)
    second_part = QuestionPart(round=_QUESTION, part=2)

    every = await hub.authorize(
        _round((_call("c1", "book", q="table at 9"), second_part), yes=_yes())
    )
    named = await hub.authorize(
        _round((_call("c1", "book", q="table at 9"), second_part), yes=_yes(parts=(2,)))
    )

    for decided, covers in ((every, (_PART, second_part)), (named, (second_part,))):
        (allowed,) = decided.allowed
        assert allowed.asked == second
        approval = allowed.call.decision.approval
        assert approval is not None
        assert approval.covers == covers
        assert allowed.call.decision.approved_part == second_part


async def test_a_pointer_by_place_and_position_finds_the_question() -> None:
    hub = _Hub()
    await hub.asked(_asked())

    decided = await hub.authorize(
        _round(_approved_booking(), yes=_yes(round_id=None, place=_PLACE, position=3))
    )

    assert decided.verdicts[0].verdict is Verdict.ALLOWED
    assert decided.allowed[0].call.decision.approval is not None


# --- a yes that does not hold: fail closed (§4:5) ---------------------------------------------


async def _failing(hub: _Hub, given: RoundToAuthorize) -> None:
    """The call does not run under an approval; the confirm goes back as needing you."""
    decided = await hub.authorize(given)
    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    recorded = await _recorded(hub.trail, verdict.decision_id)
    assert recorded.ruling.outcome is PermissionOutcome.CONFIRM
    assert recorded.approval is None
    assert recorded.approved_part is None
    assert hub.policy.resolutions == []
    assert decided.allowed == ()
    assert verdict.request is not None


async def test_no_pointer_runs_nothing_under_an_approval() -> None:
    hub = _Hub()
    await hub.asked(_asked())

    await _failing(hub, _round(_approved_booking()))


async def test_a_yes_without_the_users_authority_approves_nothing() -> None:
    """§3:3: an email or an event saying yes approves nothing."""
    hub = _Hub()
    await hub.asked(_asked())

    await _failing(hub, _round(_approved_booking(), yes=_yes(authority=False)))


@pytest.mark.parametrize(
    "delivered", [None, ToolOutcome.FAILED, ToolOutcome.INDETERMINATE], ids=str
)
async def test_a_question_not_shown_approves_nothing(delivered: ToolOutcome | None) -> None:
    """§4:4 *shown*: the question's message has a done delivery record."""
    hub = _Hub()
    await hub.asked(_asked(), delivered=delivered)

    await _failing(hub, _round(_approved_booking(), yes=_yes()))


@pytest.mark.parametrize(
    ("place", "position"), [(_PLACE, 4), ("place:elsewhere", 3)], ids=["position", "place"]
)
async def test_a_transcript_pointer_naming_no_delivered_message_approves_nothing(
    place: str, position: int
) -> None:
    """An H-label pointer's round is found only through a delivery record it names."""
    hub = _Hub()
    await hub.asked(_asked())

    await _failing(
        hub,
        _round(_approved_booking(), yes=_yes(round_id=None, place=place, position=position)),
    )


async def test_a_pointer_whose_round_and_place_disagree_approves_nothing() -> None:
    hub = _Hub()
    await hub.asked(_asked())

    await _failing(
        hub,
        _round(_approved_booking(), yes=_yes(round_id="round:other", place=_PLACE, position=3)),
    )


async def test_a_part_the_yes_did_not_name_is_not_approved() -> None:
    """§3:6: a partial yes approves only the parts it names."""
    hub = _Hub()
    await hub.asked(_asked(part=1), _asked(part=2, q="table at 9"))

    await _failing(hub, _round(_approved_booking(), yes=_yes(parts=(2,))))


async def test_a_part_of_another_question_is_not_approved() -> None:
    hub = _Hub()
    await hub.asked(_asked())
    other = QuestionPart(round="round:other", part=1)

    await _failing(hub, _round((_call("c1", "book", q="table for two at 8"), other), yes=_yes()))


async def test_a_part_the_round_did_not_record_is_not_approved() -> None:
    hub = _Hub()
    await hub.asked(_asked())
    unrecorded = QuestionPart(round=_QUESTION, part=2)

    await _failing(
        hub, _round((_call("c1", "book", q="table for two at 8"), unrecorded), yes=_yes())
    )


async def test_a_call_to_another_capability_is_not_the_call_shown() -> None:
    hub = _Hub()
    await hub.asked(_asked(_LOOKUP, q="x"))

    await _failing(hub, _round(_approved_booking(), yes=_yes()))


async def test_a_declaration_no_longer_offered_is_not_the_call_shown() -> None:
    """§4:4 *exactly the call shown*: the same tool, by value."""
    hub = _Hub()
    await hub.asked(_asked(_tool("book", description="The booking, as it was.")))

    await _failing(hub, _round(_approved_booking(), yes=_yes()))


async def test_a_part_already_run_is_not_run_again() -> None:
    """§4:4 *not already run*: no effect record carries the part."""
    hub = _Hub()
    await hub.asked(_asked())
    spent = ActivationEffect(
        id="effect:spent",
        activation_id="act-elsewhere",
        round="round:z",
        capability="book",
        values_digest="0" * 64,
        decision_id="decision:spent",
        claimed_at=_AT,
        part=_PART,
    )
    await hub.plans.claim_activation_effect(spent, match=None)

    await _failing(hub, _round(_approved_booking(), yes=_yes()))


async def test_a_yes_in_the_activation_that_asked_approves_nothing() -> None:
    """§3:1, §4:1: an answer is an activation of its own."""
    hub = _Hub()
    await hub.asked(_asked(), activation_id=_YES)

    await _failing(hub, _round(_approved_booking(), yes=_yes(activation_id=_YES)))


async def test_without_a_plan_store_nothing_runs_under_an_approval() -> None:
    hub = _Hub(plans=False)
    await hub.asked(_asked())

    await _failing(hub, _round(_approved_booking(), yes=_yes()))


async def test_a_failed_fact_with_an_outright_allow_runs_as_an_ordinary_call() -> None:
    """The dispatcher's ruling: no approval, and the call runs as any allowed call."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.asked is None
    assert allowed.call.decision.approval is None


# --- a deny is never overridden (§4:3, §4:12) ------------------------------------------------


async def test_a_deny_refuses_an_approved_call() -> None:
    hub = _Hub(policy=FakeActionPolicy(deny_at=RiskLevel.MEDIUM))
    await hub.asked(_asked())

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

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
    """§4:3, §4:7: route (a)'s resolve may deny, and then nothing runs."""
    hub = _Hub(policy=_RefusingResolution())
    await hub.asked(_asked())

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.DENY
    assert deciding.resolves is not None
    assert deciding.approval is None
    assert decided.allowed == ()


# --- egress: the shown binding, through rebind (§4:2, §4:16, #2847) --------------------------


async def test_an_approved_egress_call_rebinds_to_the_binding_shown() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder)
    bound = await binder.bind(
        tool,
        parameters={"q": "trains to Lyon"},
        provenance=_carried(outside=True),
    )
    assert bound is not None
    asked = _asked(tool, binding=bound.binding, q="trains to Lyon")
    await hub.asked(asked)

    decided = await hub.authorize(
        _round((_call("c1", "lookup", q="trains to Lyon"), _PART), yes=_yes())
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.call.request.egress_binding == asked.binding
    deciding = await _recorded(hub.trail, verdict.decision_id)
    # The lineage rule's confirm, resolved on route (a) (§4:7).
    assert deciding.resolves is not None


async def test_an_egress_call_shown_without_its_binding_is_not_the_call_shown() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder, policy=FakeActionPolicy(confirm_at=None))
    await hub.asked(_asked(tool, q="trains to Lyon"))

    decided = await hub.authorize(
        _round((_call("c1", "lookup", q="trains to Lyon"), _PART), yes=_yes())
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    assert decided.allowed[0].call.decision.approval is None


def _carried(*, outside: bool) -> CarriedProvenance:
    return CarriedProvenance(
        spans={},
        planned_with_external_content=outside,
        coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
    )


# --- already asked and waiting (§4:11) --------------------------------------------------------


async def _linked(hub: _Hub, *activations: str) -> None:
    await hub.stories.create(
        [StoryMember(kind=StoryMemberKind.ACTIVATION, id=one) for one in activations],
        actor=StoryActor.OWNER,
    )


async def test_a_call_still_waiting_on_you_comes_back_already_asked() -> None:
    hub = _Hub()
    await hub.asked(_asked())
    await _linked(hub, _ASKING, _YES)

    decided = await hub.authorize(_round((_call("c1", "book", q="table for two at 8"), None)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.already_asked == _PART
    assert verdict.request is not None


async def test_a_call_asked_in_this_activation_is_found_waiting() -> None:
    hub = _Hub()
    await hub.asked(_asked(), activation_id=_YES)

    decided = await hub.authorize(_round((_call("c1", "book", q="table for two at 8"), None)))

    assert decided.verdicts[0].already_asked == _PART


@pytest.mark.parametrize("case", ["unlinked", "other_values", "not_shown", "used"])
async def test_a_call_not_waiting_is_asked_about_again(case: str) -> None:
    hub = _Hub()
    await hub.asked(_asked(), delivered=None if case == "not_shown" else ToolOutcome.SUCCEEDED)
    if case != "unlinked":
        await _linked(hub, _ASKING, _YES)
    if case == "used":
        spent = ActivationEffect(
            id="effect:spent",
            activation_id="act-elsewhere",
            round="round:z",
            capability="book",
            values_digest="0" * 64,
            decision_id="decision:spent",
            claimed_at=_AT,
            part=_PART,
        )
        await hub.plans.claim_activation_effect(spent, match=None)
    values = "table at 9" if case == "other_values" else "table for two at 8"

    decided = await hub.authorize(_round((_call("c1", "book", q=values), None)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.already_asked is None


_LOOSE: Final = _tool(
    "book",
    parameters_schema={
        "type": "object",
        "properties": {
            "q": {
                "type": ["boolean", "integer", "number", "array"],
                "items": {"type": ["boolean", "integer", "number"]},
            }
        },
        "required": ["q"],
        "additionalProperties": False,
    },
)


@pytest.mark.parametrize(
    ("shown", "proposed"),
    [(True, 1), (False, 0), (1, 1.0), ([True], [1]), ([1], [1.0])],
    ids=["true-1", "false-0", "1-1.0", "nested-true-1", "nested-1-1.0"],
)
async def test_values_equal_in_python_but_not_as_json_are_not_waiting(
    shown: Any, proposed: Any
) -> None:
    """§4:11: the same values means the same JSON, never Python's ``True == 1``."""
    hub = _Hub(_LOOSE)
    await hub.asked(_asked(_LOOSE, q=shown))
    await _linked(hub, _ASKING, _YES)

    decided = await hub.authorize(_round((_call("c1", "book", q=proposed), None)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.already_asked is None


async def test_a_call_allowed_now_but_still_waiting_on_you_does_not_run() -> None:
    """§4:11: any proposed call identical to one waiting goes back as already asked.

    Run while its question waited, it would run again on the yes that answers it.
    """
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    await hub.asked(_asked(_LOOKUP, q="trains to Lyon"), outside=True)
    await _linked(hub, _ASKING, _YES)

    plain = await hub.authorize(_round((_call("c1", "lookup", q="trains to Lyon"), None)))
    unauthorized = await hub.authorize(
        _round((_call("c1", "lookup", q="trains to Lyon"), _PART), yes=_yes(authority=False))
    )

    for decided in (plain, unauthorized):
        (verdict,) = decided.verdicts
        assert verdict.verdict is Verdict.NEEDS_YOU
        assert verdict.already_asked == _PART
        assert verdict.reason is not None
        assert verdict.request is not None
        assert decided.allowed == ()


async def test_a_refusal_stays_a_refusal_while_a_question_waits() -> None:
    hub = _Hub(policy=FakeActionPolicy(deny_at=RiskLevel.MEDIUM))
    await hub.asked(_asked())
    await _linked(hub, _ASKING, _YES)

    decided = await hub.authorize(_round((_call("c1", "book", q="table for two at 8"), None)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.already_asked is None


_REORDERED: Final = _tool(
    "book",
    parameters_schema={
        "additionalProperties": False,
        "required": ["q"],
        "properties": {"q": {"type": "string"}},
        "type": "object",
    },
)


async def test_a_declaration_with_its_keys_reordered_is_the_same_declaration() -> None:
    """§4:4, §4:11: the same tool by value; an object's key order changes nothing."""
    assert list(_REORDERED.parameters_schema) != list(_BOOK.parameters_schema)
    hub = _Hub(_REORDERED)
    await hub.asked(_asked())
    await _linked(hub, _ASKING, _YES)

    approved = await hub.authorize(_round(_approved_booking(), yes=_yes()))
    waiting = await hub.authorize(
        _round((_call("c1", "book", q="table for two at 8"), None), activation_id=_YES)
    )

    assert approved.verdicts[0].verdict is Verdict.ALLOWED
    assert approved.allowed[0].call.decision.approval is not None
    assert waiting.verdicts[0].already_asked == _PART


async def test_the_same_json_values_are_waiting() -> None:
    hub = _Hub(_LOOSE)
    await hub.asked(_asked(_LOOSE, q=[True, 2]))
    await _linked(hub, _ASKING, _YES)

    decided = await hub.authorize(_round((_call("c1", "book", q=[True, 2]), None)))

    assert decided.verdicts[0].already_asked == _PART


# --- a retry after an unknown outcome (§6:1) --------------------------------------------------


async def _earlier(hub: _Hub, outcome: ToolOutcome | None) -> None:
    """A booking this activation made earlier, with ``outcome``."""
    request = ActionRequest(tool=_BOOK, parameters={"q": "table for two at 8"})
    effect = ActivationEffect(
        id="effect:earlier",
        activation_id=_YES,
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
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    await _earlier(hub, outcome)

    decided = await hub.authorize(
        _round((_call("c1", "book", q="table for two at 8"), None), deliberate=frozenset({"c1"}))
    )

    (ruled,) = decided.verdicts
    assert ruled.verdict is verdict
    if verdict is Verdict.NEEDS_YOU:
        assert ruled.deliberate_repeat is True
        assert ruled.request is not None
        assert decided.allowed == ()


async def test_a_retry_approved_by_a_yes_runs_under_the_approval() -> None:
    """§6:2: the claim admits a deliberate repeat under an approval; nothing else does."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    await _earlier(hub, ToolOutcome.INDETERMINATE)
    asked = _asked(deliberate_repeat=True)
    await hub.asked(asked)

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

    (allowed,) = decided.allowed
    assert allowed.deliberate_repeat is True
    assert allowed.call.decision.approval is not None


# --- through acting: spent once (§4:9) --------------------------------------------------------


class _CountingInvoker:
    """A ``ToolInvoker`` that does each call and counts it."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        del timeout
        self.calls.append(call)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


def _for_acting(decided: RoundAuthorization) -> AuthorizedRound:
    return AuthorizedRound(
        activation_id=decided.activation_id,
        round_id=decided.round_id,
        calls=tuple(
            AuthorizedCall(one.call, deliberate_repeat=one.deliberate_repeat)
            for one in decided.allowed
        ),
        story_activations=decided.story_activations,
    )


async def test_a_yes_runs_its_call_once() -> None:
    """§8:1: a yes runs it once, and a second yes to the same part does not run it again."""
    hub = _Hub()
    await hub.asked(_asked())
    invoker = _CountingInvoker()
    stage = ActingStage(
        plans=hub.plans,
        invoker=invoker,
        own_records=OwnRecordsByCapability({}),
        timeout=timedelta(seconds=5),
        now=_now,
    )

    first = await hub.authorize(_round(_approved_booking(), yes=_yes()))
    acted = await stage.act(_for_acting(first), held=HeldResults())
    again = await hub.authorize(_round(_approved_booking(), yes=_yes(), activation_id="act-2"))

    assert acted.calls[0].outcome is ActedOutcome.DONE
    assert len(invoker.calls) == 1
    (effect,) = await hub.plans.part_effects([_PART])
    assert effect.decision_id == first.verdicts[0].decision_id
    # The part is spent: the next yes's facts fail, and the call needs you again.
    assert again.verdicts[0].verdict is Verdict.NEEDS_YOU
    assert again.allowed == ()


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


# --- the input --------------------------------------------------------------------------------


def test_when_a_yes_was_given_is_an_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        YesContext(
            answers=(AnsweredQuestion(activation_id=_ASKING, round=_QUESTION),),
            given_at=datetime(2026, 10, 15, 14, 15),  # noqa: DTZ001 — the naive value refused
        )


async def test_another_questions_unreadable_records_never_decide_this_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0322 §3:1: each question is checked against its own records alone.

    The yes names two questions. The first's records cannot be read, and the call to
    authorize is the second's part, so the first pointer is never read and the call runs
    under the second's approval.
    """
    hub = _Hub()
    asked = _asked()
    await hub.asked(asked)
    read = hub.plans.activation_effects

    async def unreadable_for_the_other(
        activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        if "act-other" in activation_ids:
            msg = "the other question's records cannot be read"
            raise PlanningError(msg)
        return await read(activation_ids)

    monkeypatch.setattr(hub.plans, "activation_effects", unreadable_for_the_other)
    yes = YesContext(
        answers=(
            AnsweredQuestion(activation_id="act-other", round="round:other"),
            AnsweredQuestion(activation_id=_ASKING, round=_QUESTION),
        ),
        given_at=_AT,
        users_authority=True,
    )

    decided = await hub.authorize(_round(_approved_booking(), yes=yes))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.approval is not None
    assert deciding.approval.how.round == _QUESTION


@pytest.mark.parametrize("unreadable", ["delivery", "episode"])
async def test_a_question_whose_records_cannot_be_read_sends_back_its_call_alone(
    monkeypatch: pytest.MonkeyPatch, unreadable: str
) -> None:
    """ADR-0322 §3:1: a failure sends back only its own question's calls.

    The yes approves two questions and planning proposes both calls in one round. The
    first question's delivery record, or its asking episode, cannot be read: its call
    goes back as needing you, and the second runs under its own approval.
    """
    hub = _Hub()
    await hub.asked(_asked(), activation_id="act-a", round_id="round:a")
    await hub.asked(_asked(), activation_id="act-b", round_id="round:b")
    effects, episodes = hub.plans.activation_effects, hub.memory.get

    async def effects_unread(activation_ids: Sequence[str], /) -> tuple[ActivationEffect, ...]:
        if "act-a" in activation_ids:
            msg = "act-a's delivery records cannot be read"
            raise PlanningError(msg)
        return await effects(activation_ids)

    async def episode_unread(record_id: str) -> MemoryRecord | None:
        if record_id == "activation:act-a":
            msg = "act-a's episode cannot be read"
            raise MemoryStoreError(msg)
        return await episodes(record_id)

    if unreadable == "delivery":
        monkeypatch.setattr(hub.plans, "activation_effects", effects_unread)
    else:
        monkeypatch.setattr(hub.memory, "get", episode_unread)
    yes = YesContext(
        answers=(
            AnsweredQuestion(activation_id="act-a", round="round:a"),
            AnsweredQuestion(activation_id="act-b", round="round:b"),
        ),
        given_at=_AT,
        users_authority=True,
    )
    calls = (
        (_call("c1", "book", q="table for two at 8"), QuestionPart(round="round:a", part=1)),
        (_call("c2", "book", q="table for two at 8"), QuestionPart(round="round:b", part=1)),
    )

    decided = await hub.authorize(_round(*calls, yes=yes))

    assert [one.verdict for one in decided.verdicts] == [Verdict.NEEDS_YOU, Verdict.ALLOWED]
    (allowed,) = decided.allowed
    approval = allowed.call.decision.approval
    assert approval is not None
    assert approval.how.activation_id == "act-b"


async def test_two_asking_activations_resolving_to_one_round_approve_nothing() -> None:
    """ADR-0322 §3:3: which question asked the call cannot be told, so it fails closed."""
    hub = _Hub()
    await hub.asked(_asked(), activation_id="act-a", round_id="round:shared")
    await hub.asked(_asked(), activation_id="act-b", round_id="round:shared")
    yes = YesContext(
        answers=(
            AnsweredQuestion(activation_id="act-a", round="round:shared"),
            AnsweredQuestion(activation_id="act-b", round="round:shared"),
        ),
        given_at=_AT,
        users_authority=True,
    )
    part = QuestionPart(round="round:shared", part=1)

    await _failing(hub, _round((_call("c1", "book", q="table for two at 8"), part), yes=yes))


async def test_a_part_no_pointer_names_the_round_of_is_not_approved() -> None:
    """ADR-0322 §3:3: a call runs only under the approval of the question that asked it."""
    hub = _Hub()
    await hub.asked(_asked())
    await hub.asked(_asked(), activation_id="act-2", round_id="round:2")

    decided = await hub.authorize(
        _round(_approved_booking(), yes=_yes(activation_id="act-2", round_id="round:2"))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert decided.allowed == ()


def test_a_yes_carries_a_pointer_and_names_each_question_once() -> None:
    """ADR-0322 §2:7: an input with no pointer carries no yes, nor one naming a question twice."""
    with pytest.raises(ValueError, match="at least one pointer"):
        YesContext(answers=(), given_at=_AT)
    with pytest.raises(ValueError, match="each question it approves once"):
        YesContext(
            answers=(
                AnsweredQuestion(activation_id=_ASKING, round=_QUESTION),
                AnsweredQuestion(activation_id=_ASKING, round=_QUESTION, parts=(1,)),
            ),
            given_at=_AT,
        )


async def test_the_diagnostic_record_names_the_fact_that_failed() -> None:
    """ADR-0314 §4: each check a call reached, the approval's included."""
    sink = FakeDiagnosticSink()
    hub = _Hub(diagnostics=sink)
    await hub.asked(_asked())

    with diagnosed_activation("3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35", clock=_now):
        await hub.authorize(_round(_approved_booking(), yes=_yes(authority=False)))
        await hub.authorize(_round(_approved_booking(), yes=_yes()))

    failed, held = (
        entry.model_dump(mode="json")["body"]["calls"][0]["checks"][0]
        for entry in sink.of(DiagnosticSource.AUTHORIZING, DiagnosticKind.RETURNED)
    )
    assert failed == {"check": "approval", "verdict": "failed", "reason": "not_the_users_authority"}
    assert held == {"check": "approval", "verdict": "held", "reason": None}


# --- ADR-0323 §4:8-§4:9: *shown to you* in a place whose kind establishes the user --------


async def test_a_question_shown_on_the_telegram_line_is_shown_and_its_who_is_the_lines() -> None:
    """§4:8: the line's chat is a place whose kind establishes the user; §4:9: its who."""
    hub = _Hub()
    await hub.asked(_asked(), place="telegram:conn-0001/424242")

    decided = await hub.authorize(
        _round(_approved_booking(), yes=_yes(who=ApprovalGiver.USER_THROUGH_TELEGRAM))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    deciding = await _recorded(hub.trail, verdict.decision_id)
    assert deciding.approval is not None
    assert deciding.approval.who is ApprovalGiver.USER_THROUGH_TELEGRAM


@pytest.mark.parametrize(
    "place",
    ["informational_event:mail-1", "place:chat", "elsewhere"],
    ids=["an-event", "an-unknown-kind", "no-kind"],
)
async def test_a_question_done_in_a_place_no_kind_establishes_the_user_in_is_not_shown(
    place: str,
) -> None:
    """§4:8: a done delivery elsewhere was not shown to you, so nothing is approved."""
    hub = _Hub()
    await hub.asked(_asked(), place=place)

    decided = await hub.authorize(_round(_approved_booking(), yes=_yes()))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
