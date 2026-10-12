"""The authorizing stage (ADR-0306 §4), driven directly over fakes.

Nothing runs it yet (ADR-0309 §2:6), so every case builds a recorded round by hand, as
the lane that wires the phases will, and reads the decision that came back, what the
canonical ``FakeAuditTrail`` holds, and what the policies were asked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import AuditError
from ai_assistant.core.types import (
    ActivationDigest,
    CapabilityEffect,
    CapabilityResult,
    ChannelContext,
    CostBasis,
    DataTier,
    DigestOutcome,
    EgressBinding,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvidenceItem,
    Idempotency,
    InputOrigin,
    LabelKind,
    MemoryDecisionKind,
    MemorySource,
    NewConversation,
    PermissionOutcome,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    Reversibility,
    RiskLevel,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    ToolCall,
    ToolCost,
    ToolDefinition,
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
    RoundMessage,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
    gets_effect_record,
    read_outside_content,
)
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER,
    RememberCalls,
    remembered_record_id,
)
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanStore,
    FakeStoryStore,
    FakeToolRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import PermissionDecision

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_ACTIVATION: Final = "act-1"
_EPISODE: Final = f"activation:{_ACTIVATION}"
_PLACE: Final = "place:chat"


def _now() -> datetime:
    return _AT


def _tool(name: str, **overrides: Any) -> ToolDefinition:
    """A declaration of one of the thin path's kinds, by ``name``."""
    kinds: dict[str, dict[str, Any]] = {
        # A read that leaves the hub and may carry outside text; changes nothing.
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
        # A booking: in the world, not safe to repeat, its outcome can be unknown.
        "book": {
            "side_effecting": True,
            "reversibility": Reversibility.RECOVERABLE,
            "idempotency": Idempotency.NONE,
            "writes": (DataTier.PERSONAL,),
            "effect": CapabilityEffect.WORLD,
            "leaves_hub": True,
            "result": CapabilityResult.NO_OUTSIDE_TEXT,
            "outcome_can_be_unknown": True,
            "safe_to_repeat": False,
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


def _episode(  # noqa: PLR0913 — one keyword per part of the record a case varies
    episode_id: str = _EPISODE,
    *,
    origin: InputOrigin = InputOrigin.USER,
    rounds: Sequence[PlanningRound] = (),
    labels: Sequence[PlanningLabel] = (),
    digests: Sequence[ActivationDigest] = (),
    derived_from_external: bool = False,
) -> EpisodicMemory:
    """An open episode at ``episode_id``, as admission and planning leave it."""
    record = EpisodeProcessingRecord(
        activation_id=episode_id.removeprefix("activation:"),
        started_at=_AT,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="the words they wrote"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            origin=origin,
        ),
        rounds=tuple(rounds),
        labels=tuple(labels),
        digests=tuple(digests),
    )
    return EpisodicMemory(
        id=episode_id,
        content="",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.5,
            last_updated=_AT,
            derived_from_external=derived_from_external,
        ),
        occurred_at=_AT,
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
        processing_record=record,
    )


def _call(call_id: str, name: str, **arguments: Any) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)


def _round(
    *calls: ProposedCall,
    deliberate: frozenset[str] = frozenset(),
    message: RoundMessage | None = None,
    working: WorkingRecord | None = None,
    notes_marked: bool = False,
) -> RoundToAuthorize:
    """A recorded round proposing ``calls``, each handed on as planning judged it."""
    planning_round = PlanningRound(
        id="round:1",
        recorded_at=_AT,
        calls=calls,
        notes="kept" if notes_marked else None,
        notes_marked=notes_marked,
    )
    return RoundToAuthorize(
        activation_id=_ACTIVATION,
        round=planning_round,
        working=working or WorkingRecord(),
        calls=tuple(
            CallToAuthorize(one, deliberate_repeat=one.call_id in deliberate) for one in calls
        ),
        input_place=_PLACE,
        message=message,
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
        memory_policy: FakeMemoryPolicy | None = None,
        binder: FakeEgressBinder | None = None,
        trail: FakeAuditTrail | None = None,
        episode: EpisodicMemory | None = None,
    ) -> None:
        self.registry = FakeToolRegistry(tools or (_tool("lookup"), _tool("book"), REMEMBER))
        self.policy = policy or FakeActionPolicy()
        self.memory_policy = memory_policy or FakeMemoryPolicy()
        self.trail = trail or FakeAuditTrail(now=_now)
        self.stories = FakeStoryStore(now=_now)
        self.memory = FakeMemoryStore(now=_now)
        self.episode = episode or _episode()
        self.stage = AuthorizingStage(
            registry=self.registry,
            policy=self.policy,
            memory_policy=self.memory_policy,
            trail=self.trail,
            stories=self.stories,
            memory=self.memory,
            binder=binder,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
        )

    async def authorize(self, given: RoundToAuthorize) -> RoundAuthorization:
        if await self.memory.get(self.episode.id) is None:
            await self.memory.add(self.episode)
        return await self.stage.authorize(given)


async def _recorded(trail: FakeAuditTrail, decision_id: str | None) -> PermissionDecision:
    assert decision_id is not None
    recorded = await trail.get(decision_id)
    assert recorded is not None
    return recorded


# --- one allowed call ----------------------------------------------------------------------


async def test_an_allowed_call_is_selected_ruled_recorded_and_handed_on() -> None:
    """§4:1, §4:10: selection, the policy, the record read back, and the call for acting."""
    hub = _Hub()

    decided = await hub.authorize(_round(_call("c1", "lookup", q="trains to Lyon")))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    assert verdict.reason is None
    assert verdict.effect_id is None
    recorded = await _recorded(hub.trail, verdict.decision_id)
    assert recorded.ruling.outcome is PermissionOutcome.ALLOW
    assert recorded.effect is None
    (allowed,) = decided.allowed
    assert allowed.call.decision == recorded
    assert allowed.call.request.tool.id == "lookup"
    assert dict(allowed.call.request.parameters) == {"q": "trains to Lyon"}
    # §4:11: the phases' request carries no goal and no intended action.
    assert allowed.call.request.goal is None
    assert allowed.call.request.intended_action is None
    assert decided.story_activations == ()
    assert decided.read_outside_content is False
    assert decided.round_id == "round:1"


async def test_a_call_that_gets_an_effect_record_carries_its_id_on_every_decision() -> None:
    """ADR-0306 §5:8, §6: the id is minted before the ruling and set on its decision."""
    hub = _Hub(policy=FakeActionPolicy(deny_at=RiskLevel.HIGH))
    risky = _tool("book", id="book-risky", capability="book_risky", risk_level=RiskLevel.HIGH)
    hub.registry.register(risky)

    decided = await hub.authorize(
        _round(_call("c1", "book", q="room for two"), _call("c2", "book_risky", q="suite"))
    )

    booked, refused = decided.verdicts
    assert booked.verdict is Verdict.ALLOWED
    assert booked.effect_id == "effect:1"
    assert (await _recorded(hub.trail, booked.decision_id)).effect == "effect:1"
    # A denied call to such a capability names the record it would have been claimed under.
    assert refused.verdict is Verdict.NOT_DONE
    assert refused.effect_id == "effect:2"
    assert (await _recorded(hub.trail, refused.decision_id)).effect == "effect:2"


def test_which_calls_get_a_record_is_actings_rule() -> None:
    """Authorizing restates acting's rule, which it may not import; the two agree."""
    shapes = [
        _tool("lookup"),
        _tool("book"),
        REMEMBER,
        _tool("lookup", safe_to_repeat=False),
        _tool(
            "book",
            effect=CapabilityEffect.OWN_RECORDS,
            leaves_hub=False,
            outcome_can_be_unknown=False,
            safe_to_repeat=True,
        ),
    ]
    for tool in shapes:
        assert gets_effect_record(tool) is acting.gets_effect_record(tool)


# --- the policy's rulings ---------------------------------------------------------------------


async def test_a_deny_is_not_done_and_a_confirm_needs_you() -> None:
    """§4:2, §4:8, §4:9: neither runs, both are recorded, and nothing parks."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=RiskLevel.MEDIUM, deny_at=RiskLevel.HIGH))
    hub.registry.register(_tool("lookup", id="ask", capability="ask", risk_level=RiskLevel.MEDIUM))
    hub.registry.register(_tool("lookup", id="no", capability="no", risk_level=RiskLevel.HIGH))

    decided = await hub.authorize(_round(_call("c1", "ask", q="x"), _call("c2", "no", q="y")))

    asked, denied = decided.verdicts
    assert asked.verdict is Verdict.NEEDS_YOU
    assert asked.reason is not None
    assert (await _recorded(hub.trail, asked.decision_id)).ruling.outcome is (
        PermissionOutcome.CONFIRM
    )
    assert denied.verdict is Verdict.NOT_DONE
    assert denied.reason is not None
    assert (await _recorded(hub.trail, denied.decision_id)).ruling.outcome is (
        PermissionOutcome.DENY
    )
    assert decided.allowed == ()
    # §4:8: nothing resumes a confirm, so it carries no lifetime and no question.
    assert (await _recorded(hub.trail, asked.decision_id)).expires_at is None


# --- selection --------------------------------------------------------------------------------


async def test_a_call_no_tool_can_take_is_not_done_and_rules_nothing() -> None:
    """ADR-0144, ADR-0145 §2: no tool, no fit, a tie, or disagreeing tools."""
    hub = _Hub(_tool("lookup"), _tool("lookup", id="lookup-b"), _tool("book"))
    hub.registry.register(_tool("book", id="book-b", safe_to_repeat=True))

    decided = await hub.authorize(
        _round(
            _call("c1", "nothing"),
            _call("c2", "lookup", q=3),
            _call("c3", "lookup", q="tie"),
            _call("c4", "book", q="disagree"),
        )
    )

    assert [one.verdict for one in decided.verdicts] == [Verdict.NOT_DONE] * 4
    assert [one.reason for one in decided.verdicts] == [
        "no tool satisfies this capability",
        "the arguments fit no tool of this capability",
        "more than one tool fits equally, and none is chosen",
        "the tools satisfying this capability do not declare alike",
    ]
    assert all(one.decision_id is None for one in decided.verdicts)
    assert hub.policy.requests == []
    assert await hub.trail.recent() == []


async def test_a_call_naming_an_argument_the_hub_fills_is_refused() -> None:
    """ADR-0254 §3: a model that reaches for a system-supplied argument is a fault."""
    hub = _Hub()

    decided = await hub.authorize(
        _round(_call("c1", "remember", statement="tea", **{EPISODE_ARGUMENT: "activation:x"}))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason == "the call names an argument the hub fills"
    assert hub.policy.requests == []


async def test_a_capability_naming_an_argument_the_hub_cannot_fill_is_not_done() -> None:
    hub = _Hub(_tool("lookup", system_supplied=("locale",)))

    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    assert decided.verdicts[0].reason == "the capability names an argument the hub cannot fill"


async def test_an_unbindable_egress_call_is_not_done() -> None:
    """ADR-0152 §9: the seam refused, so no ruling is sought."""
    binder = FakeEgressBinder()
    keyword = _tool("lookup").model_dump()["parameters_schema"]
    keyword["properties"]["to"] = {
        "type": "string",
        "x-egress-destination": "smtp",
        "x-egress-tier": "personal",
    }
    hub = _Hub(_tool("lookup", parameters_schema=keyword), binder=binder)

    decided = await hub.authorize(_round(_call("c1", "lookup", q="x", to="a@example.com")))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason == "the call could not be bound to where it would go"
    assert verdict.decision_id is None


# --- the stand-in -----------------------------------------------------------------------------


async def test_after_outside_content_a_call_leaving_the_hub_needs_you_and_one_inside_runs() -> None:
    """§4:4: no standing permission for a call that leaves the hub; the message is untouched."""
    hub = _Hub(episode=_episode(origin=InputOrigin.OUTSIDE))

    decided = await hub.authorize(
        _round(
            _call("c1", "lookup", q="x"),
            _call("c2", "book", q="y"),
            message=RoundMessage("On it.", _PLACE),
        )
    )

    looked, booked = decided.verdicts
    assert decided.read_outside_content is True
    assert looked.verdict is Verdict.NEEDS_YOU
    assert booked.verdict is Verdict.NEEDS_YOU
    assert looked.reason is not None
    assert "outside content" in looked.reason
    # The policy allowed each: the stand-in is the check after it (§4:1).
    assert (await _recorded(hub.trail, looked.decision_id)).ruling.outcome is (
        PermissionOutcome.ALLOW
    )
    assert decided.allowed == ()
    assert decided.message is not None
    assert decided.message.allowed is True


async def test_the_fact_reaches_the_policy_on_the_binding_where_there_is_one() -> None:
    """§4:6: ``planned_with_external_content`` on the call's egress binding."""
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder, episode=_episode(origin=InputOrigin.OUTSIDE))

    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    (verdict,) = decided.verdicts
    recorded = await _recorded(hub.trail, verdict.decision_id)
    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.planned_with_external_content is True
    # The fake policy's ADR-0181 §5 floor confirms it: needs you.
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert recorded.ruling.outcome is PermissionOutcome.CONFIRM


async def test_a_clean_activation_binds_the_fact_false_and_runs() -> None:
    tool = _tool("lookup")
    binder = FakeEgressBinder()
    binder.register_egress(tool, reference="conn-1", identity="me@example.com")
    hub = _Hub(tool, binder=binder)

    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    (allowed,) = decided.allowed
    binding = allowed.call.request.egress_binding
    assert binding is not None
    assert binding.planned_with_external_content is False


# --- what the activation has read --------------------------------------------------------------


def _digest(outcome: DigestOutcome, *items: str) -> ActivationDigest:
    return ActivationDigest(
        result="R1",
        question="what trains run",
        outcome=outcome,
        evidence=tuple(EvidenceItem(text=one, source="R1") for one in items),
        recorded_at=_AT,
    )


def _marked_round(round_id: str = "round:0") -> PlanningRound:
    return PlanningRound(id=round_id, recorded_at=_AT, notes="seen", notes_marked=True)


@pytest.mark.parametrize(
    ("episode", "read"),
    [
        (_episode(), False),
        (_episode(origin=InputOrigin.OUTSIDE), True),
        (_episode(derived_from_external=True), True),
        # ADR-0308 §5:4: a digest that answered counts, even with no items.
        (_episode(digests=(_digest(DigestOutcome.ANSWERED),)), True),
        (_episode(digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),)), True),
        (_episode(digests=(_digest(DigestOutcome.FAILED),)), False),
        (_episode(rounds=(_marked_round(),)), True),
        # A story's note planning was shown: its mark is not read here, so it counts.
        (_episode(labels=(PlanningLabel(label="N1", kind=LabelKind.NOTE, id="7"),)), True),
    ],
)
async def test_the_record_says_whether_outside_content_was_read(
    episode: EpisodicMemory, *, read: bool
) -> None:
    """ADR-0306 §4:5: an outside trigger, digested evidence, or a marked note."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(episode)

    assert await read_outside_content(memory, _ACTIVATION, working=WorkingRecord()) is read


@pytest.mark.parametrize(
    "working",
    [
        WorkingRecord(rounds=(_marked_round("round:1"),)),
        WorkingRecord(digests=(_digest(DigestOutcome.ANSWERED),)),
        WorkingRecord(labels=(PlanningLabel(label="N1", kind=LabelKind.NOTE, id="7"),)),
        # A record the windows or recall brought rests on outside content (ADR-0181 §4).
        WorkingRecord(fetched_outside=True),
    ],
)
async def test_what_the_working_set_holds_counts_where_its_append_failed(
    working: WorkingRecord,
) -> None:
    """ADR-0307 §2:4, ADR-0308 §5:2: a failed append clears no lineage."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode())

    assert await read_outside_content(memory, _ACTIVATION, working=working) is True


async def test_a_failed_digest_append_still_counts_through_the_stage() -> None:
    """The adversarial round-1 case: evidence read, nothing kept, no notes written."""
    hub = _Hub()
    held = WorkingRecord(digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),))

    decided = await hub.authorize(_round(_call("c1", "book", q="seat"), working=held))

    assert decided.read_outside_content is True
    assert decided.verdicts[0].verdict is Verdict.NEEDS_YOU


async def test_a_fetched_record_resting_on_outside_content_counts_through_the_stage() -> None:
    """The architecture round-1 case: understanding read an outside record, before any
    round was planned or recorded, and a call leaving the hub needs you."""
    hub = _Hub()
    held = WorkingRecord(fetched_outside=True)

    decided = await hub.authorize(_round(_call("c1", "book", q="seat"), working=held))

    assert decided.read_outside_content is True
    assert decided.verdicts[0].verdict is Verdict.NEEDS_YOU


@pytest.mark.parametrize(
    ("shown", "read"),
    [
        (_episode("activation:other"), False),
        (_episode("activation:other", rounds=(_marked_round(),)), True),
        # Shown with its outside mark, notes or none (ADR-0181 §4's disjunction).
        (_episode("activation:other", derived_from_external=True), True),
        # Its input is withheld, but its understood meaning is shown (ADR-0303 §3:2).
        (_episode("activation:other", origin=InputOrigin.OUTSIDE), True),
    ],
)
async def test_an_episode_planning_was_shown_counts_by_its_marks(
    shown: EpisodicMemory, *, read: bool
) -> None:
    """ADR-0307 §4:3, ADR-0181 §4: an episode shown as outside content is read."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode())
    await memory.add(shown)
    label = PlanningLabel(label="E1", kind=LabelKind.EPISODE, id="activation:other")

    working = WorkingRecord(labels=(label,))
    assert await read_outside_content(memory, _ACTIVATION, working=working) is read


async def test_an_episode_planning_was_shown_that_is_gone_fails_closed() -> None:
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode())
    gone = PlanningLabel(label="E1", kind=LabelKind.EPISODE, id="activation:gone")

    working = WorkingRecord(labels=(gone,))
    assert await read_outside_content(memory, _ACTIVATION, working=working) is True


async def test_an_activation_with_no_readable_record_has_read_outside_content() -> None:
    """Nothing says it has not, so it fails closed."""
    memory = FakeMemoryStore(now=_now)
    assert await read_outside_content(memory, _ACTIVATION, working=WorkingRecord()) is True


# --- remembering --------------------------------------------------------------------------------


async def test_remembering_is_filled_by_the_hub_and_passes_memory_policy() -> None:
    """§4:3, ADR-0254 §3: the hub fills the episode and the mark; MemoryPolicy rules."""
    hub = _Hub()

    decided = await hub.authorize(_round(_call("c1", "remember", statement="likes tea")))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert dict(allowed.call.request.parameters) == {
        "statement": "likes tea",
        EPISODE_ARGUMENT: _EPISODE,
        OUTSIDE_CONTENT_ARGUMENT: False,
    }
    (asked,) = hub.memory_policy.calls
    assert asked.proposal.proposed.id == remembered_record_id("effect:1")
    assert asked.proposal.proposed.provenance.source is MemorySource.INFERRED
    assert asked.conflicts == ()


@pytest.mark.parametrize(
    ("kind", "verdict"),
    [
        (MemoryDecisionKind.ASK_USER, Verdict.NEEDS_YOU),
        (MemoryDecisionKind.REJECT, Verdict.NOT_DONE),
        (MemoryDecisionKind.STORE_TEMPORARY, Verdict.ALLOWED),
    ],
)
async def test_memory_policy_ask_needs_you_and_reject_is_not_done(
    kind: MemoryDecisionKind, verdict: Verdict
) -> None:
    hub = _Hub(memory_policy=FakeMemoryPolicy(kind))

    decided = await hub.authorize(_round(_call("c1", "remember", statement="likes tea")))

    assert decided.verdicts[0].verdict is verdict
    assert len(decided.allowed) == (1 if verdict is Verdict.ALLOWED else 0)


async def test_remembering_after_outside_content_is_marked_and_needs_you() -> None:
    """ADR-0106 §6: a tainted derived proposal is never committed unconfirmed."""
    hub = _Hub(episode=_episode(origin=InputOrigin.OUTSIDE))

    decided = await hub.authorize(_round(_call("c1", "remember", statement="the 9:10 runs")))

    assert decided.verdicts[0].verdict is Verdict.NEEDS_YOU
    (asked,) = hub.memory_policy.calls
    assert asked.proposal.proposed.provenance.derived_from_external is True


# --- the match and the message ----------------------------------------------------------------


async def test_a_call_not_safe_to_repeat_takes_its_stories_activations_once() -> None:
    """§5:10, §6:3: this activation's stories, as they stand when the round is authorized."""
    hub = _Hub()
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    other = StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-0")
    await hub.stories.create([other, member], actor=StoryActor.OWNER)
    await hub.stories.create(
        [StoryMember(kind=StoryMemberKind.ACTIVATION, id="unrelated")], actor=StoryActor.OWNER
    )

    decided = await hub.authorize(
        _round(_call("c1", "book", q="room"), deliberate=frozenset({"c1"}))
    )

    assert set(decided.story_activations) == {"act-0", _ACTIVATION}
    (allowed,) = decided.allowed
    assert allowed.deliberate_repeat is True


async def test_no_story_is_read_where_every_allowed_call_is_safe_to_repeat() -> None:
    hub = _Hub()
    await hub.stories.create(
        [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)], actor=StoryActor.OWNER
    )

    decided = await hub.authorize(_round(_call("c1", "lookup", q="x")))

    assert decided.story_activations == ()


async def test_the_message_goes_only_into_the_inputs_place() -> None:
    """§4:7: checked by its place alone; an allowed one gets an effect id (§5:3)."""
    hub = _Hub()

    here = await hub.authorize(_round(message=RoundMessage("Done soon.", _PLACE)))
    there = await hub.authorize(_round(message=RoundMessage("Psst.", "place:elsewhere")))
    silent = await hub.authorize(_round())

    assert here.message is not None
    assert here.message.allowed is True
    assert here.message.effect_id is not None
    assert there.message is not None
    assert there.message.allowed is False
    assert there.message.effect_id is None
    assert silent.message is None


# --- the record read back ---------------------------------------------------------------------


class _ForgetfulTrail(FakeAuditTrail):
    """A trail that accepts every append and hands back nothing."""

    async def get(self, decision_id: str) -> PermissionDecision | None:
        del decision_id
        return None


async def test_a_trail_that_does_not_hand_back_the_decision_stops_the_round() -> None:
    """ADR-0037 §2-§3: nothing runs on a ruling the trail does not hold."""
    hub = _Hub(trail=_ForgetfulTrail(now=_now))

    with pytest.raises(AuditError):
        await hub.authorize(_round(_call("c1", "lookup", q="x")))


def test_a_round_hands_on_only_the_calls_it_proposed() -> None:
    planning_round = PlanningRound(id="round:1", recorded_at=_AT, calls=(_call("c1", "lookup"),))

    with pytest.raises(ValueError, match="proposed"):
        RoundToAuthorize(
            activation_id=_ACTIVATION,
            round=planning_round,
            working=WorkingRecord(),
            calls=(CallToAuthorize(_call("c1", "book")),),
        )
    with pytest.raises(ValueError, match="once"):
        RoundToAuthorize(
            activation_id=_ACTIVATION,
            round=planning_round,
            working=WorkingRecord(),
            calls=(CallToAuthorize(_call("c1", "lookup")), CallToAuthorize(_call("c1", "lookup"))),
        )


# --- through acting ---------------------------------------------------------------------------


def _for_acting(decided: RoundAuthorization) -> AuthorizedRound:
    """The conversion the wiring lane makes: authorizing's decision as acting's input."""
    return AuthorizedRound(
        activation_id=decided.activation_id,
        round_id=decided.round_id,
        calls=tuple(
            AuthorizedCall(one.call, deliberate_repeat=one.deliberate_repeat)
            for one in decided.allowed
        ),
        story_activations=decided.story_activations,
    )


async def test_a_remembered_statement_is_written_once_through_actings_own_records_seam() -> None:
    """ADR-0306 §3:2, §3:3, §5:9: written directly, and refused as already done again."""
    hub = _Hub()
    writer = FakeMemoryWriter(store=hub.memory, policy=FakeMemoryPolicy(), now=_now)
    plans = FakePlanStore()
    stage = ActingStage(
        plans=plans,
        invoker=_NoInvoker(),
        own_records=OwnRecordsByCapability({"remember": RememberCalls(writer=writer, now=_now)}),
        timeout=timedelta(seconds=5),
        now=_now,
    )

    first = await hub.authorize(_round(_call("c1", "remember", statement="likes tea")))
    acted = await stage.act(_for_acting(first), held=HeldResults())
    again = await hub.authorize(_round(_call("c1", "remember", statement="likes tea")))
    repeated = await stage.act(_for_acting(again), held=HeldResults())

    assert acted.calls[0].outcome is ActedOutcome.DONE
    written = await hub.memory.get(remembered_record_id("effect:1"))
    assert written is not None
    assert written.provenance.evidence == (_EPISODE,)
    (effect,) = await plans.activation_effects([_ACTIVATION])
    assert effect.decision_id == first.verdicts[0].decision_id
    assert repeated.calls[0].outcome is ActedOutcome.NOT_DONE
    assert await hub.memory.get(remembered_record_id("effect:2")) is None


class _NoInvoker:
    """A ``ToolInvoker`` no call of these cases reaches."""

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        del call, timeout
        raise AssertionError
