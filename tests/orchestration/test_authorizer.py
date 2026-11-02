"""The authorizing stage (ADR-0306 §4), driven directly over fakes.

Nothing runs it yet (ADR-0309 §2:6), so every case builds a recorded round by hand, as
the lane that wires the phases will, and reads the decision that came back, what the
canonical ``FakeAuditTrail`` holds, and what the policies were asked.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.errors import AuditError, MemoryStoreError
from ai_assistant.core.types import (
    ActivationDigest,
    ActivationUnderstanding,
    CapabilityEffect,
    CapabilityResult,
    ChannelContext,
    CostBasis,
    DataTier,
    DiagnosticKind,
    DiagnosticSource,
    DigestOutcome,
    EgressBinding,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvidenceItem,
    Idempotency,
    LabelKind,
    Memory,
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
    StoryNote,
    StoryNoteAuthor,
    SupportHolder,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolResult,
    UnderstandingProducer,
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
    OutsideGround,
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
    REMEMBER_CANDIDATE,
    CandidateCalls,
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
    parties: tuple[SupportHolder, ...] = OWNERS_WORDS,
    understanding: Sequence[ActivationUnderstanding] = (),
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
            parties=parties,
        ),
        understanding=tuple(understanding),
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


def _fact(fact: str) -> dict[str, Any]:
    """A candidate's arguments, as planning writes them (ADR-0329 §3:1)."""
    return {"fact": fact, "why": "worth keeping", "rests_on_this_stimulus": True}


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
        binder: FakeEgressBinder | None = None,
        trail: FakeAuditTrail | None = None,
        episode: EpisodicMemory | None = None,
        diagnostics: FakeDiagnosticSink | None = None,
    ) -> None:
        self.registry = FakeToolRegistry(
            tools or (_tool("lookup"), _tool("book"), REMEMBER_CANDIDATE)
        )
        self.policy = policy or FakeActionPolicy()
        self.trail = trail or FakeAuditTrail(now=_now)
        self.stories = FakeStoryStore(now=_now)
        self.memory = FakeMemoryStore(now=_now)
        self.episode = episode or _episode()
        self.stage = AuthorizingStage(
            registry=self.registry,
            policy=self.policy,
            trail=self.trail,
            stories=self.stories,
            memory=self.memory,
            binder=binder,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
            diagnostics=diagnostics,
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
        REMEMBER_CANDIDATE,
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
        _round(_call("c1", "remember_fact", **_fact("tea"), **{EPISODE_ARGUMENT: "activation:x"}))
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
    hub = _Hub(episode=_episode(parties=UNIDENTIFIED_WORDS))

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
    hub = _Hub(tool, binder=binder, episode=_episode(parties=UNIDENTIFIED_WORDS))

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


def _version(*, relayed: bool) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=1,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="a pasted email from the school",
        relayed=relayed,
    )


@pytest.mark.parametrize(
    ("episode", "read"),
    [
        (_episode(), False),
        (_episode(parties=UNIDENTIFIED_WORDS), True),
        # ADR-0351 §5:13: the user's own words that understanding marks relayed.
        (_episode(understanding=(_version(relayed=True),)), True),
        (_episode(understanding=(_version(relayed=False),)), False),
        (_episode(derived_from_external=True), True),
        # ADR-0308 §5:4: a digest that answered counts, even with no items.
        (_episode(digests=(_digest(DigestOutcome.ANSWERED),)), True),
        (_episode(digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),)), True),
        (_episode(digests=(_digest(DigestOutcome.FAILED),)), False),
        (_episode(rounds=(_marked_round(),)), True),
        # A story's note planning was shown, whose mark the working set does not hold:
        # it cannot be read, so it counts, failing closed.
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
        (_episode("activation:other", parties=UNIDENTIFIED_WORDS), True),
        # #2870: its evidence is outside content planning is shown (ADR-0308 §5:5).
        (
            _episode("activation:other", digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),)),
            True,
        ),
        # A digest that answered nothing shows planning no evidence of another episode.
        (_episode("activation:other", digests=(_digest(DigestOutcome.ANSWERED),)), False),
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


def _note(note_id: int, *, outside: bool) -> StoryNote:
    """A story note as the story store holds it: the owner's, or a marked one planning wrote."""
    return StoryNote(
        note_id=note_id,
        text="I prefer the morning." if not outside else "The email said 9:10.",
        author=StoryNoteAuthor.PLANNING if outside else StoryNoteAuthor.OWNER,
        written_during="act-0" if outside else None,
        outside=outside,
        written_at=_AT,
    )


_N1: Final = PlanningLabel(label="N1", kind=LabelKind.NOTE, id="7")


@pytest.mark.parametrize(
    ("notes", "read"),
    [
        # #2875: a note the owner wrote is never marked (ADR-0303 §3:1), so it is not
        # outside content read.
        ((_note(7, outside=False),), False),
        # ADR-0303 §3:6, ADR-0306 §4:5: a marked note planning reads is.
        ((_note(7, outside=True),), True),
        # Held notes that are not the one labelled leave its mark unread: fails closed.
        ((_note(8, outside=False),), True),
    ],
)
async def test_a_note_planning_was_shown_counts_by_its_mark(
    notes: tuple[StoryNote, ...], *, read: bool
) -> None:
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode())

    working = WorkingRecord(labels=(_N1,), notes=notes)
    assert await read_outside_content(memory, _ACTIVATION, working=working) is read


async def test_a_note_held_in_the_episode_record_is_read_by_its_mark_too() -> None:
    """A label an earlier append recorded is read against the notes the working set holds."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(labels=(_N1,)))

    working = WorkingRecord(notes=(_note(7, outside=False),))
    assert await read_outside_content(memory, _ACTIVATION, working=working) is False


async def test_a_note_the_owner_wrote_leaves_a_call_leaving_the_hub_and_a_remember_allowed() -> (
    None
):
    """#2875 through the stage: the note's mark, not its label, decides the stand-in."""
    hub = _Hub()
    held = WorkingRecord(labels=(_N1,), notes=(_note(7, outside=False),))

    decided = await hub.authorize(
        _round(
            _call("c1", "lookup", q="x"),
            _call("c2", "remember_fact", **_fact("likes mornings")),
            working=held,
        )
    )

    assert decided.read_outside_content is False
    assert [one.verdict for one in decided.verdicts] == [Verdict.ALLOWED, Verdict.ALLOWED]
    (_, remembered) = decided.allowed
    assert remembered.call.request.parameters[OUTSIDE_CONTENT_ARGUMENT] is False


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


async def test_a_candidate_after_outside_content_is_marked_and_allowed() -> None:
    """ADR-0329 §3:4, §5:6: the hub marks it, and no MemoryPolicy stops it here.

    Under ADR-0328 §13's interim this needed the user, since a derived proposal resting
    on outside content is never committed unconfirmed (ADR-0106 §6); a candidate writes
    no memory, and the observer's writes carry that floor.
    """
    hub = _Hub(episode=_episode(parties=UNIDENTIFIED_WORDS))

    decided = await hub.authorize(_round(_call("c1", "remember_fact", **_fact("the 9:10 runs"))))

    assert decided.verdicts[0].verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.call.request.parameters[OUTSIDE_CONTENT_ARGUMENT] is True


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


def _texts(*messages: RoundMessage) -> RoundToAuthorize:
    """A round whose calls are ``text`` calls, each handed on as the message it is."""
    calls = tuple(
        ProposedCall(call_id=str(one.call_id), name="text", arguments={"words": one.text})
        for one in messages
    )
    given = _round()
    return replace(
        given,
        round=given.round.model_copy(update={"calls": calls}),
        call_messages=messages,
    )


async def test_a_text_call_is_checked_by_its_place_alone_as_the_rounds_message_is() -> None:
    """ADR-0356 §7:7, §14:9: each ``text`` call has a verdict of its own, by its id, from
    the message place check: into the input's place it is allowed, with an effect id of
    its own (§7:8); off it, refused with the reason; and it is no call ruled on."""
    hub = _Hub()

    decided = await hub.authorize(
        _texts(
            RoundMessage("Booked.", _PLACE, "c1"),
            RoundMessage("Psst.", "place:elsewhere", "c2"),
            RoundMessage("And done.", _PLACE, "c3"),
        )
    )

    assert decided.verdicts == ()
    assert decided.allowed == ()
    assert decided.message is None
    here, there, again = decided.call_messages
    assert [one.call_id for one in decided.call_messages] == ["c1", "c2", "c3"]
    assert (here.allowed, again.allowed, there.allowed) == (True, True, False)
    assert here.effect_id is not None
    assert again.effect_id is not None
    assert here.effect_id != again.effect_id
    assert there.effect_id is None
    assert there.reason is not None


async def test_a_scheduled_activations_text_call_goes_only_into_a_place_on_its_list() -> None:
    """ADR-0356 §7:7, ADR-0350 §6:7: a place on the list, and none gone since or off it."""
    hub = _Hub()
    given = replace(
        _texts(
            RoundMessage("Time for the pills.", "telegram:ref/42", "c1"),
            RoundMessage("Time for the pills.", "conversation:c-1", "c2"),
            RoundMessage("Time for the pills.", "conversation:gone", "c3"),
            RoundMessage("Time for the pills.", None, "c4"),
        ),
        input_place=None,
        places=("conversation:c-1", "telegram:ref/42"),
        gone=("conversation:c-1",),
    )

    decided = await hub.authorize(given)

    assert [one.allowed for one in decided.call_messages] == [True, False, False, False]
    gone = decided.call_messages[1]
    assert gone.reason is not None
    assert "gone since it was shown" in gone.reason


def test_a_text_call_checked_names_a_call_the_round_proposed_once() -> None:
    """ADR-0356 §7:7: a message call is one the round proposed, never also ruled on."""
    given = _texts(RoundMessage("Booked.", _PLACE, "c1"))
    with pytest.raises(ValueError, match="proposed, by its id"):
        replace(given, call_messages=(RoundMessage("Booked.", _PLACE, "c9"),))
    with pytest.raises(ValueError, match="authorized once each"):
        replace(
            given,
            calls=(CallToAuthorize(given.round.calls[0]),),
        )


async def test_a_scheduled_activations_message_goes_only_into_a_place_on_its_list() -> None:
    """ADR-0350 §6:7, §13:3: the place it names, on its list; none, or one off it, refused."""
    hub = _Hub()
    places = ("conversation:c-1", "telegram:ref/42")

    def scheduled(place: str | None) -> RoundToAuthorize:
        return replace(
            _round(message=RoundMessage("Time for the pills.", place)),
            input_place=None,
            places=places,
        )

    on_it = await hub.authorize(scheduled("telegram:ref/42"))
    off_it = await hub.authorize(scheduled("conversation:gone"))
    none = await hub.authorize(scheduled(None))

    assert on_it.message is not None
    assert on_it.message.allowed is True
    assert on_it.message.effect_id is not None
    for refused in (off_it, none):
        assert refused.message is not None
        assert refused.message.allowed is False
        assert refused.message.effect_id is None


async def test_a_scheduled_activations_message_to_a_place_gone_since_its_list_is_refused() -> None:
    """ADR-0350 §5:9, §6:7, #3448: refused by rule, with nothing claimed, saying it is gone."""
    hub = _Hub()
    places = ("conversation:c-1", "telegram:ref/42")
    given = replace(
        _round(message=RoundMessage("Time to move the car.", "conversation:c-1")),
        input_place=None,
        places=places,
        gone=("conversation:c-1",),
    )

    gone = await hub.authorize(given)
    other = await hub.authorize(
        replace(given, message=RoundMessage("Time to move the car.", "telegram:ref/42"))
    )

    assert gone.message is not None
    assert gone.message.allowed is False
    assert gone.message.effect_id is None
    assert gone.message.reason is not None
    assert "gone since it was shown" in gone.message.reason
    assert other.message is not None
    assert other.message.allowed is True


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


class _NoneSimilar:
    """A candidate's lookup that finds nothing similar (ADR-0329 §4:1)."""

    async def similar(self, fact: str, *, limit: int) -> tuple[Memory, ...]:
        del fact, limit
        return ()


async def test_a_candidate_is_recorded_once_through_actings_own_records_seam() -> None:
    """ADR-0306 §3:2, §3:3, §5:9: recorded directly, and refused as already done again."""
    hub = _Hub()
    plans = FakePlanStore()
    stage = ActingStage(
        plans=plans,
        invoker=_NoInvoker(),
        own_records=OwnRecordsByCapability(
            {"remember_fact": CandidateCalls(similar=_NoneSimilar(), limit=5)}
        ),
        timeout=timedelta(seconds=5),
        now=_now,
    )

    first = await hub.authorize(_round(_call("c1", "remember_fact", **_fact("likes tea"))))
    acted = await stage.act(_for_acting(first), held=HeldResults())
    again = await hub.authorize(_round(_call("c1", "remember_fact", **_fact("likes tea"))))
    repeated = await stage.act(_for_acting(again), held=HeldResults())

    assert acted.calls[0].outcome is ActedOutcome.DONE
    (effect,) = await plans.activation_effects([_ACTIVATION])
    assert effect.decision_id == first.verdicts[0].decision_id
    assert repeated.calls[0].outcome is ActedOutcome.NOT_DONE
    # A candidate writes no memory (ADR-0329 §3:3): the store holds the episode alone.
    assert [one.id for one in await hub.memory.export()] == [hub.episode.id]


class _NoInvoker:
    """A ``ToolInvoker`` no call of these cases reaches."""

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        del call, timeout
        raise AssertionError


# --- ADR-0314 §4: what authorizing gives the diagnostic record ------------------------------

_DIAGNOSED: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"


def _diagnosed_clock() -> datetime:
    return _AT


async def test_each_call_is_written_with_every_check_it_reached() -> None:
    """§4: each check's verdict and reason, the message's verdict, and what was read."""
    sink = FakeDiagnosticSink()
    hub = _Hub(policy=FakeActionPolicy(deny_at=RiskLevel.HIGH), diagnostics=sink)
    hub.registry.register(
        _tool("book", id="book-risky", capability="book_risky", risk_level=RiskLevel.HIGH)
    )
    given = _round(
        _call("c1", "lookup", q="trains"),
        _call("c2", "book_risky", q="suite"),
        _call("c3", "missing"),
        message=RoundMessage("On it.", _PLACE),
    )

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock):
        decided = await hub.authorize(given)

    (entry,) = sink.of(DiagnosticSource.AUTHORIZING, DiagnosticKind.RETURNED)
    body = entry.model_dump(mode="json")["body"]
    calls = {one["call_id"]: one for one in body["calls"]}
    assert [one["check"] for one in calls["c1"]["checks"]] == ["selection", "policy", "stand_in"]
    assert calls["c1"]["verdict"] == "allowed"
    policy = calls["c2"]["checks"][-1]
    assert (policy["check"], policy["verdict"]) == ("policy", "deny")
    assert isinstance(policy["reason"], str)
    assert (calls["c2"]["verdict"], calls["c2"]["reason"]) == (
        "not_done",
        decided.verdicts[1].reason,
    )
    assert calls["c3"]["checks"] == [
        {"check": "selection", "verdict": "not_done", "reason": decided.verdicts[2].reason}
    ]
    assert body["message"] == {"place": _PLACE, "allowed": True, "reason": None}
    assert body["read_outside_content"] is False
    assert body["grounds"] == []


async def test_the_stand_in_and_every_ground_that_held_are_written() -> None:
    """§4: whether the activation had read outside content, each ground and its record."""
    sink = FakeDiagnosticSink()
    episode = _episode(
        parties=UNIDENTIFIED_WORDS,
        digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),),
        rounds=(_marked_round("round:0"),),
    )
    hub = _Hub(episode=episode, diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock):
        decided = await hub.authorize(_round(_call("c1", "lookup", q="trains")))

    (entry,) = sink.of(DiagnosticSource.AUTHORIZING)
    body = entry.model_dump(mode="json")["body"]
    assert decided.read_outside_content is True
    assert body["grounds"] == [
        {"ground": "trigger_outside", "record": _EPISODE},
        {"ground": "digest_answered", "record": "R1"},
        {"ground": "notes_marked", "record": "round:0"},
    ]
    (call,) = body["calls"]
    assert call["checks"][-1] == {
        "check": "stand_in",
        "verdict": "needs_you",
        "reason": decided.verdicts[0].reason,
    }


async def test_a_round_whose_checking_fails_is_written_as_far_as_it_got() -> None:
    """§4: the returned entry is written once checking returns or fails."""
    sink = FakeDiagnosticSink()
    hub = _Hub(trail=_ForgetfulTrail(now=_now), diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock), pytest.raises(AuditError):
        await hub.authorize(_round(_call("c1", "lookup", q="x")))

    (entry,) = sink.of(DiagnosticSource.AUTHORIZING)
    body = entry.model_dump(mode="json")["body"]
    assert body["failure"]["class"] == "AuditError"
    (call,) = body["calls"]
    assert [(one["check"], one["verdict"]) for one in call["checks"]] == [
        ("selection", "passed"),
        ("policy", "allow"),
    ]
    assert call["verdict"] is None


async def test_with_the_record_off_nothing_is_written_and_nothing_changes() -> None:
    """§2:1: the same decision, and no entry."""
    sink = FakeDiagnosticSink()
    hub = _Hub()

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock):
        decided = await hub.authorize(_round(_call("c1", "lookup", q="trains")))

    assert decided.verdicts[0].verdict is Verdict.ALLOWED
    assert sink.recorded == ()


async def test_without_grounds_asked_the_read_stops_at_the_first_that_holds() -> None:
    """The answer alone: no further read is made once one ground held."""
    memory = _Unreadable(now=_now)

    assert await read_outside_content(
        memory, _ACTIVATION, working=WorkingRecord(fetched_outside=True)
    )


async def test_asked_for_its_grounds_a_failed_read_after_one_held_keeps_the_answer() -> None:
    """§2:4: going through every ground never changes the answer, or raises for it."""
    grounds: list[OutsideGround] = []

    read = await read_outside_content(
        _Unreadable(now=_now),
        _ACTIVATION,
        working=WorkingRecord(fetched_outside=True),
        grounds=grounds,
    )

    assert read is True
    assert grounds == [OutsideGround("fetched_outside")]


async def test_asked_for_its_grounds_a_failed_read_before_any_held_still_raises() -> None:
    with pytest.raises(MemoryStoreError):
        await read_outside_content(
            _Unreadable(now=_now), _ACTIVATION, working=WorkingRecord(), grounds=[]
        )


async def test_an_unreadable_shown_episode_is_a_ground_with_its_id() -> None:
    memory = FakeMemoryStore(now=_now)
    shown = PlanningLabel(label="E1", kind=LabelKind.EPISODE, id="activation:other")
    await memory.add(_episode(labels=(shown,)))
    grounds: list[OutsideGround] = []

    assert await read_outside_content(memory, _ACTIVATION, working=WorkingRecord(), grounds=grounds)
    assert grounds == [OutsideGround("episode_shown_unread", "activation:other")]


def _follow_up(*items: str) -> ActivationDigest:
    """A follow-up's digest: it names the result it reads again, R1, as the search's does."""
    return ActivationDigest(
        result="R1",
        question="which of them runs latest",
        outcome=DigestOutcome.ANSWERED,
        evidence=tuple(EvidenceItem(text=one, source="R1") for one in items),
        recorded_at=_AT + timedelta(minutes=1),
    )


async def test_each_ground_is_noted_once_where_the_record_and_working_set_both_hold_it() -> None:
    """#2895, ADR-0314 §4: once the appends landed, the episode's record and the working
    set hold the same rounds, digests and labels, and each is one ground, not two."""
    marked = _marked_round("round:0")
    digests = (_digest(DigestOutcome.ANSWERED, "the 9:10"), _follow_up("the 23:40"))
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(rounds=(marked,), digests=digests, labels=(_N1,)))
    working = WorkingRecord(
        rounds=(marked,), digests=digests, labels=(_N1,), notes=(_note(7, outside=True),)
    )
    grounds: list[OutsideGround] = []

    read = await read_outside_content(memory, _ACTIVATION, working=working, grounds=grounds)

    assert read is True
    # The search's digest and the follow-up's are two digests, each of R1.
    assert grounds == [
        OutsideGround("digest_answered", "R1"),
        OutsideGround("digest_answered", "R1"),
        OutsideGround("notes_marked", "round:0"),
        OutsideGround("note_shown_marked", "7"),
    ]


async def test_two_digests_differing_only_in_evidence_are_two_grounds() -> None:
    """Under one clock reading, of one result and one question, two digests are still two;
    each copy the episode's record and the working set both hold is counted once."""
    digests = (
        _digest(DigestOutcome.ANSWERED, "the 9:10"),
        _digest(DigestOutcome.ANSWERED, "the 9:40"),
    )
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(digests=digests))
    grounds: list[OutsideGround] = []

    working = WorkingRecord(digests=digests)
    assert await read_outside_content(memory, _ACTIVATION, working=working, grounds=grounds)
    assert grounds == [
        OutsideGround("digest_answered", "R1"),
        OutsideGround("digest_answered", "R1"),
    ]


async def test_one_note_shown_under_two_labels_is_one_ground() -> None:
    """The ground rests on the note, which planning was shown twice."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(labels=(_N1,)))
    again = PlanningLabel(label="N2", kind=LabelKind.NOTE, id="7")
    grounds: list[OutsideGround] = []

    working = WorkingRecord(labels=(_N1, again), notes=(_note(7, outside=True),))
    assert await read_outside_content(memory, _ACTIVATION, working=working, grounds=grounds)
    assert grounds == [OutsideGround("note_shown_marked", "7")]


async def test_a_fetched_ground_is_noted_once_for_each_thing_that_set_it() -> None:
    """#2895: ``fetched_outside`` names what it rests on, each once, in the order seen."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode())
    working = WorkingRecord(
        fetched_outside=True,
        fetched_outside_from=("activation:other", "story:trip", "7", "activation:other"),
    )
    grounds: list[OutsideGround] = []

    assert await read_outside_content(memory, _ACTIVATION, working=working, grounds=grounds)
    assert grounds == [
        OutsideGround("fetched_outside", "activation:other"),
        OutsideGround("fetched_outside", "story:trip"),
        OutsideGround("fetched_outside", "7"),
    ]


async def test_naming_what_was_fetched_never_makes_the_fetched_ground_hold() -> None:
    """The answer is the flag's: a name says why it holds, and never makes it hold."""
    with pytest.raises(ValueError, match="named only where"):
        WorkingRecord(fetched_outside_from=("activation:other",))


async def test_without_grounds_asked_a_named_fetched_record_still_ends_the_read_at_once() -> None:
    """The answer alone stops at the first fetched record, reading nothing more."""
    working = WorkingRecord(fetched_outside=True, fetched_outside_from=("a", "b"))

    assert await read_outside_content(_Unreadable(now=_now), _ACTIVATION, working=working)


async def test_the_diagnostic_record_shows_each_ground_once_with_its_record() -> None:
    """#2895 through the stage: the authorizing entry lists each ground once, named."""
    sink = FakeDiagnosticSink()
    marked = _marked_round("round:0")
    digest = _digest(DigestOutcome.ANSWERED, "the 9:10")
    episode = _episode(rounds=(marked,), digests=(digest,))
    hub = _Hub(episode=episode, diagnostics=sink)
    working = WorkingRecord(
        rounds=(marked,),
        digests=(digest,),
        fetched_outside=True,
        fetched_outside_from=("activation:other",),
    )

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_clock):
        decided = await hub.authorize(_round(_call("c1", "lookup", q="trains"), working=working))

    (entry,) = sink.of(DiagnosticSource.AUTHORIZING)
    body = entry.model_dump(mode="json")["body"]
    assert decided.read_outside_content is True
    assert body["grounds"] == [
        {"ground": "fetched_outside", "record": "activation:other"},
        {"ground": "digest_answered", "record": "R1"},
        {"ground": "notes_marked", "record": "round:0"},
    ]


class _Unreadable(FakeMemoryStore):
    """A memory store whose every read fails."""

    async def get(self, memory_id: str) -> None:
        del memory_id
        msg = "the store is down"
        raise MemoryStoreError(msg)
