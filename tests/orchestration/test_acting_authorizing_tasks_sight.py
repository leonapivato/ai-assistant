"""A work's authorizing, acting, approval calls and task calls, through its sight (B8d).

ADR-0383 §7:4, §7:5, §7:7, §8:2, milestone 22's B8d. With stores built to withhold, an
unidentified sender's work writes and reads back its own records, the effects it claims
and the requests it asks (§7:4), and nothing of the owner's: a call naming an effect, a
request, a task or a person of the owner's is answered as one naming a record never
written (§8:2). The owner's work, at normal and lowered to weak, reads and writes as
today. An approval's work, another activation than the one that asked, is the owner's,
so it reads the asking work's request and effects whoever's the asking work was. In the
counting build every read answers as today and is counted with the reader ``work``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import pytest
from phases_support import chat_turn
from sight_support import OWNER_WEAK, UNIDENTIFIED, holder, in_a_work, sight_of
from structlog.testing import capture_logs
from task_support import CHAT, LIMITS, activation, pushed, write_task
from test_authorizer_ticket_rules import (
    _PLACE,
    _REQUEST,
    _episode,
    _Hub,
    _Ids,
    _requested,
    _round,
    _ticketed,
)
from test_engine import Harness

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalCard,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    ChannelInput,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordHome,
    RequestedCall,
    Reversibility,
    RiskLevel,
    SightMode,
    TextChannelPayload,
    TicketState,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    OwnRecordsByCapability,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.approval_calls import (
    ApprovalAsker,
    ApprovalCalls,
    CardFacts,
    CardOutcome,
    CardPosted,
    asking,
)
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.authorizer import AuthorizingStage, Verdict
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.phase_path import authorized_round
from ai_assistant.orchestration.task_manager import TaskManager
from ai_assistant.orchestration.task_rules import PersonZones
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeMemoryStore,
    FakePlanStore,
    FakeStoryStore,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import Sight

_AT: Final = datetime(2026, 10, 15, 14, 15, tzinfo=UTC)
#: The activations, each a minted id, so a work's own records are its own (§7:4).
_HOLDER: Final = "0f7a6e2c-1b44-4c62-9d1e-3a5b7c9d0e11"
_ASKING: Final = "5d2c8b1a-7e94-4f03-8a6b-2c4d6e8f0a12"
_OWNERS_ID: Final = "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
_EARLIER: Final = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"
_STRANGERS: Final = "7e8f9a0b-1c2d-4e3f-9a4b-5c6d7e8f9a0b"
_AGAIN: Final = "3b4c5d6e-7f8a-4b9c-8d0e-1f2a3b4c5d6e"
_WITHHOLD: Final = SightMode.WITHHOLD


def _now() -> datetime:
    return _AT


def _owner(activation_id: str = _HOLDER) -> Sight:
    """The owner's work at normal (ADR-0383 §6's first row)."""
    return sight_of(at=_AT, activation_id=activation_id)


def _weak(activation_id: str = _HOLDER) -> Sight:
    """The owner's work, by a link lowered to weak: the same person bound (§6:9)."""
    return sight_of(OWNER_WEAK, at=_AT, activation_id=activation_id)


def _stranger(activation_id: str = _HOLDER) -> Sight:
    """An unidentified sender's work, for the owner (§6's second row)."""
    return sight_of(UNIDENTIFIED, at=_AT, activation_id=activation_id)


def _approvals_work() -> Sight:
    """The sight admission makes for an approval's work, as the engine admits it (§6:5).

    Its input is the outcome, on the approvals, with no sender and no one's words.
    """
    state = admit_channel(
        ChannelInput(target=THE_APPROVALS, payload=TextChannelPayload(text="approved")),
        None,
        clock=_now,
        id_factory=lambda: _HOLDER,
    )
    assert state.sight is not None
    return state.sight


_OWNERS: Final = {"owner-normal": _owner, "owner-weak": _weak}


# --- authorizing and acting under a ticket: an approval's work (ADR-0361 §5) -------------


class _Withholding(_Hub):
    """Authorizing over stores built to withhold, the request written by its asking work."""

    def __init__(self) -> None:
        super().__init__()
        self.plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
        self.memory = FakeMemoryStore(now=_now, sight_mode=_WITHHOLD)
        self.stories = FakeStoryStore(now=_now, sight_mode=_WITHHOLD)
        self.stage = AuthorizingStage(
            stores=holder(stories=self.stories, memory=self.memory, plans=self.plans),
            registry=self.registry,
            policy=self.policy,
            trail=self.trail,
            now=_now,
            new_decision_id=_Ids("decision"),
            new_effect_id=_Ids("effect"),
        )

    async def asked(self, call: RequestedCall, *, by: Sight) -> ApprovalRequest:
        """A request for ``call``, asked by the work whose sight is ``by``, then tapped yes.

        Written through the asking work's bound store, as its runner writes it (§7:5);
        the tap is the owner's own act.
        """
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
            home=RecordHome.owners(),
            id="effect:ask",
            activation_id=_ASKING,
            round="round:ask",
            capability="request_approval",
            values_digest="0" * 64,
            decision_id="decision:ask",
            claimed_at=_AT,
            request=request.id,
        )
        written = await self.plans.bound(by).write_approval_request(request, effect, match=None)
        assert written.request is not None
        step = await self.plans.answer_approval_request(
            request.id,
            ApprovalRequestState.APPROVED,
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT),
        )
        return step.request

    async def ruled(self, sight: Sight, requested: RequestedCall) -> Any:
        """Authorizing's ruling of the ticket's call, in the work whose sight is ``sight``."""
        await self.memory.add(_episode(_HOLDER))
        given = replace(_round(_ticketed(requested)), activation_id=_HOLDER, input_place=_PLACE)
        return await self.stage.authorize(given, sight=sight)


class _Ran:
    """The invocation seam, noting each call it runs."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        del timeout
        self.calls.append(call)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


def _acting(plans: PlanStore, ran: _Ran | None = None) -> ActingStage:
    return ActingStage(
        stores=holder(plans=plans),
        invoker=ran or _Ran(),
        own_records=OwnRecordsByCapability({}),
        timeout=timedelta(seconds=5),
        now=_now,
    )


@pytest.mark.parametrize("asking_work", [_owner, _stranger], ids=["owners", "unidentified"])
async def test_an_approvals_work_reads_the_asking_works_request_and_effects(
    asking_work: Any,
) -> None:
    """The approval's work is another activation than the one that asked; §7:4 makes
    nothing of the asking work's its own, but its sight, the owner's, sees the request
    (its home the request's person's) and the asking work's effects (their home the
    owner's, whom that work was for, ADR-0383 §4:4), so the ticket runs and is spent."""
    hub = _Withholding()
    requested = _requested()
    await hub.asked(requested, by=asking_work(_ASKING))
    sight = _approvals_work()

    decided = await hub.ruled(sight, requested)
    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    ran = _Ran()
    acted = await _acting(hub.plans, ran).act(
        authorized_round(decided), home=RecordHome.owners(), sight=sight, held=HeldResults()
    )

    (one,) = acted.calls
    assert one.outcome is ActedOutcome.DONE, one.reason
    assert len(ran.calls) == 1
    bound = hub.plans.bound(sight)
    (spent,) = await bound.approval_requests([_REQUEST])
    assert spent.ticket is TicketState.USED
    asked = await bound.activation_effects([_ASKING])
    assert [effect.id for effect in asked] == ["effect:ask"]


async def test_a_ticket_naming_the_owners_request_is_answered_as_one_never_written() -> None:
    """§8:2: an unidentified sender's work naming a request its sight does not see is
    told what naming a request never written tells it, and nothing runs."""
    requested = _requested()
    seen = _Withholding()
    await seen.asked(requested, by=_owner(_ASKING))
    never = _Withholding()

    told = await seen.ruled(_stranger(), requested)
    unwritten = await never.ruled(_stranger(), requested)

    (verdict,) = told.verdicts
    (expected,) = unwritten.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert (verdict.verdict, verdict.reason) == (expected.verdict, expected.reason)
    assert told.allowed == ()
    (request,) = await seen.plans.approval_requests([_REQUEST])
    assert request.ticket is TicketState.HELD


@pytest.mark.parametrize("sight", _OWNERS.values(), ids=_OWNERS.keys())
async def test_the_owners_work_runs_the_ticket_at_normal_and_at_weak(sight: Any) -> None:
    """The owner's work, at either level, reads the request as today (§6:9)."""
    hub = _Withholding()
    requested = _requested()
    await hub.asked(requested, by=_owner(_ASKING))

    decided = await hub.ruled(sight(), requested)

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason


# --- acting: the work's own effects (§7:4) and the owner's withheld (§8:2) ---------------


_BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="A booking: in the world, not safe to repeat.",
    risk_level=RiskLevel.LOW,
    reads=(),
    writes=(),
    discloses=(),
    side_effecting=True,
    reversibility=Reversibility.IRREVERSIBLE,
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=True,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    cost=ToolCost(basis=CostBasis.FREE),
)


def _booking(activation_id: str, *, stories: tuple[str, ...] = ()) -> AuthorizedRound:
    """One booking, claimed under an effect record, in ``activation_id``'s round."""
    request = ActionRequest(tool=_BOOK, parameters={"date": "2026-11-01"})
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id=f"decision:{activation_id}",
        decided_at=_AT,
        effect=f"effect:{activation_id}",
    )
    return AuthorizedRound(
        activation_id=activation_id,
        round_id=f"round:{activation_id}",
        calls=(AuthorizedCall(ToolCall(request=request, decision=decision)),),
        story_activations=stories,
    )


async def _booked(plans: FakePlanStore, sight: Sight, activation_id: str, **round_: Any) -> Any:
    acted = await _acting(plans).act(
        _booking(activation_id, **round_), home=RecordHome.owners(), sight=sight, held=HeldResults()
    )
    (one,) = acted.calls
    return one


async def test_a_work_claims_and_finishes_its_own_effects_and_reads_them_back() -> None:
    """§7:4, §7:5: an unidentified sender's work's effect record is its own: claimed,
    finished and read back through its bound store, whose sight sees nothing else."""
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
    sight = _stranger(_STRANGERS)

    one = await _booked(plans, sight, _STRANGERS)

    assert one.outcome is ActedOutcome.DONE, one.reason
    (effect,) = await plans.bound(sight).activation_effects([_STRANGERS])
    assert effect.outcome is ToolOutcome.SUCCEEDED


async def test_a_claim_matching_the_owners_done_effect_is_answered_as_one_never_written() -> None:
    """§8:2: the duplicate backstop reads the effects the claiming work's store holds, so
    an unidentified sender's work matching an effect of the owner's is answered as where
    none was written; the owner's own next work is refused as today."""
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
    earlier = await _booked(plans, _owner(_EARLIER), _EARLIER)
    assert earlier.outcome is ActedOutcome.DONE

    owners = await _booked(plans, _owner(_OWNERS_ID), _OWNERS_ID, stories=(_EARLIER,))
    strangers = await _booked(plans, _stranger(_STRANGERS), _STRANGERS, stories=(_EARLIER,))
    never = await _booked(
        FakePlanStore(now=_now, sight_mode=_WITHHOLD),
        _stranger(_STRANGERS),
        _STRANGERS,
        stories=(_EARLIER,),
    )

    assert owners.outcome is ActedOutcome.NOT_DONE
    assert (strangers.outcome, strangers.reason) == (never.outcome, never.reason)
    assert strangers.outcome is ActedOutcome.DONE


# --- the approval calls: a work's own request and its card (ADR-0361 §2) ------------------


class _Cards:
    """The line's poster: records each card on its request through the store it is handed."""

    async def post(
        self, request: ApprovalRequest, facts: CardFacts, *, plans: PlanStore
    ) -> CardPosted:
        del facts
        await plans.record_approval_card(
            str(request.id), ApprovalCard(place=CHAT, position=1, token=None)
        )
        return CardPosted(CardOutcome.SENT)


def _asker(activation_id: str) -> ApprovalAsker:
    return ApprovalAsker(
        person=OWNER_PERSON_ID,
        activation_id=activation_id,
        round_id=f"round:{activation_id}",
        requested={"decision:ask": RequestedCall(tool=_BOOK, values={"date": "2026-11-02"})},
    )


def _ask_call() -> ToolCall:
    from test_approval_calls import _call as asking_call  # noqa: PLC0415

    return asking_call()


def _ask_effect(activation_id: str) -> ActivationEffect:
    return ActivationEffect(
        home=RecordHome.owners(),
        id=f"effect:{activation_id}",
        activation_id=activation_id,
        round=f"round:{activation_id}",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision:ask",
        claimed_at=_AT,
    )


async def _ask(plans: FakePlanStore, *senders: Any, activation_id: str) -> object:
    runner = ApprovalCalls(
        stores=holder(plans=plans), expiry=timedelta(hours=24), now=_now, cards=_Cards()
    )
    with in_a_work(*senders, at=_AT, activation_id=activation_id), asking(_asker(activation_id)):
        return await runner.run_claiming(
            _ask_call(), _ask_effect(activation_id), match=None, deliberate_repeat=False
        )


async def test_a_work_asks_its_own_request_and_its_card_is_recorded_through_its_sight() -> None:
    """§7:4, §7:5: the request an unidentified sender's work asks is its own: written,
    its card recorded on it, and read back through its bound store."""
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)

    answer = await _ask(plans, UNIDENTIFIED, activation_id=_STRANGERS)

    assert isinstance(answer, ToolResult), answer
    (request,) = await plans.bound(_stranger(_STRANGERS)).person_approval_requests(
        OWNER_PERSON_ID, tuple(ApprovalRequestState)
    )
    assert request.activation_id == _STRANGERS
    assert request.cards


async def test_a_duplicate_of_the_owners_pending_request_is_checked_as_if_none_were_written() -> (
    None
):
    """§2:8 read through the bound store: the owner's work is told its request already
    waits; an unidentified sender's work, which does not see the owner's, is answered as
    where none was written, and its own request is written."""
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
    assert isinstance(await _ask(plans, activation_id=_OWNERS_ID), ToolResult)

    again = await _ask(plans, activation_id=_AGAIN)
    strangers = await _ask(plans, UNIDENTIFIED, activation_id=_STRANGERS)
    never = await _ask(
        FakePlanStore(now=_now, sight_mode=_WITHHOLD), UNIDENTIFIED, activation_id=_STRANGERS
    )

    assert not isinstance(again, ToolResult)
    assert "already waits" in str(again)
    assert isinstance(strangers, ToolResult)
    assert type(strangers) is type(never)
    assert strangers.output == never.output


# --- the Task Manager, as a work's task calls use it (ADR-0350 §4, §10) -----------------------


def _manager(plans: FakePlanStore, memory: FakeMemoryStore) -> TaskManager:
    return TaskManager(
        stores=holder(plans=plans, memory=memory),
        plans=plans,
        memory=memory,
        running=lambda: (),
        is_running=lambda _one: False,
        starting=lambda _one: False,
        wake=lambda: None,
        limits=LIMITS,
        zones=PersonZones(default=ZoneInfo("UTC")),
        now=_now,
    )


async def _tasks_world() -> tuple[TaskManager, FakePlanStore, str]:
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
    manager = _manager(plans, FakeMemoryStore(now=_now, sight_mode=_WITHHOLD))
    task = await write_task(plans, activation())
    return manager, plans, task.id


async def test_a_task_of_the_owners_is_withheld_from_an_unidentified_senders_task_calls() -> None:
    """§8:2: listing, cancelling and a ticket's tap: each answers an unidentified sender's
    work as for a task or request never written, and nothing is cancelled."""
    manager, plans, task_id = await _tasks_world()
    hub = _Withholding()
    hub.plans = plans
    await hub.asked(_requested(), by=_owner(_ASKING))

    with in_a_work(UNIDENTIFIED, at=_AT):
        scheduled = await manager.scheduled(OWNER_PERSON_ID)
        cancelled = await manager.cancel(task_id, person=OWNER_PERSON_ID)
        never = await manager.cancel("task:never-written", person=OWNER_PERSON_ID)
        tap = await manager.ticket_tap(_REQUEST)

    assert scheduled == ()
    assert (cancelled.task, cancelled.reason) == (never.task, never.reason)
    assert tap is None
    (held,) = await plans.scheduled_tasks([task_id])
    assert held.pending


@pytest.mark.parametrize("senders", [(), (OWNER_WEAK,)], ids=["normal", "weak"])
async def test_the_owners_task_calls_read_and_write_as_today(senders: tuple[Any, ...]) -> None:
    manager, plans, task_id = await _tasks_world()
    hub = _Withholding()
    hub.plans = plans
    await hub.asked(_requested(), by=_owner(_ASKING))

    with in_a_work(*senders, at=_AT):
        scheduled = await manager.scheduled(OWNER_PERSON_ID)
        tap = await manager.ticket_tap(_REQUEST)
        cancelled = await manager.cancel(task_id, person=OWNER_PERSON_ID)

    assert [one.task_id for one in scheduled] == [task_id]
    assert tap is not None
    assert cancelled.task is not None


async def test_the_task_managers_operations_from_outside_run_with_no_work() -> None:
    """ADR-0350 §10:1-§10:4: the queries and the cancel serve from outside too, one
    implementation each, as the owner's own acts over the stores unbound (B10); a work's
    forms, with no work running, read nothing and fail (ADR-0383 §7:7)."""
    manager, _, task_id = await _tasks_world()

    scheduled = await manager.scheduled_outside_a_work(OWNER_PERSON_ID)
    recent = await manager.recent_outside_a_work(OWNER_PERSON_ID, supply=None)
    for works in (
        manager.scheduled(OWNER_PERSON_ID),
        manager.recent(OWNER_PERSON_ID, supply=None),
        manager.cancel(task_id),
        manager.ticket_tap(_REQUEST),
    ):
        with pytest.raises(RuntimeError, match="sight"):
            await works
    cancelled = await manager.cancel_outside_a_work(task_id)

    assert [one.task_id for one in scheduled] == [task_id]
    assert recent == ()
    assert cancelled.task is not None
    assert not cancelled.task.pending


# --- the engine's read of a task's lineage, its window (ADR-0350 §6:5) ------------------------


async def test_a_tasks_lineage_is_read_by_its_works_sight() -> None:
    """§7:7, §8:2: the schedule's window is the task's work's read; a sight that does not
    see the owner's tasks reads the current step alone, as where none was written, and
    links no episode."""
    plans = FakePlanStore(now=_now, sight_mode=_WITHHOLD)
    harness = Harness(plans=plans, memory=FakeMemoryStore(now=_now, sight_mode=_WITHHOLD))
    empty = Harness(
        plans=FakePlanStore(now=_now, sight_mode=_WITHHOLD),
        memory=FakeMemoryStore(now=_now, sight_mode=_WITHHOLD),
    )
    first = await write_task(plans, activation())
    ran = await pushed(plans, first)
    following = await write_task(plans, ran)
    now_running = await pushed(plans, following)
    zone = ZoneInfo("UTC")
    try:
        owners, _ = await harness.engine._lineage(
            following, now_running, zone, sight=_owner(now_running)
        )
        strangers = await harness.engine._lineage(
            following, now_running, zone, sight=_stranger(now_running)
        )
        never = await empty.engine._lineage(
            following, now_running, zone, sight=_stranger(now_running)
        )
    finally:
        await harness.engine.aclose()
        await empty.engine.aclose()

    assert strangers == never
    assert len(owners) > len(strangers[0])


# --- the counting build (§11:1) ---------------------------------------------------------------


async def test_in_the_counting_build_every_read_is_counted_as_a_works() -> None:
    """§11:1: the stores answer as today, and each read the stages make for a work writes
    its count with the reader ``work`` and the work's bounds."""
    hub = _Hub(policy=FakeActionPolicy(confirm_at=None))
    requested = _requested()
    await hub.approved(requested)
    manager = _manager(hub.plans, hub.memory)

    with capture_logs() as logs:
        decided = await hub.authorize(_round(_ticketed(requested)))
        with in_a_work(at=_AT):
            scheduled = await manager.scheduled(OWNER_PERSON_ID)
            tap = await manager.ticket_tap(_REQUEST)

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    assert scheduled == ()
    assert tap is not None
    counts = [one for one in logs if one["event"] == "sight_counted"]
    assert {(one["store"], one["member"]) for one in counts} >= {
        ("plans", "approval_requests"),
        ("plans", "person_scheduled_tasks"),
    }
    assert {one["reader"] for one in counts} == {"work"}
    assert all(one["bounds"] == ["person_owner"] for one in counts)


async def test_an_engine_chat_turn_counts_authorizings_and_the_paths_reads_as_a_works() -> None:
    """Through the engine: authorizing's read of the activation's record and the path's
    re-read of what it showed are counted, each a work's read bound to the owner."""
    from test_phases_recall import _BOOKED, _harness, _seeded  # noqa: PLC0415 — one harness

    harness = _harness(await _seeded(_BOOKED))
    with capture_logs() as logs:
        await chat_turn(harness, "book the campsite at Pine Flat")
    counts = [one for one in logs if one["event"] == "sight_counted"]
    members = {(one["store"], one["member"]) for one in counts}
    assert {("memory", "get"), ("memory", "get_history")} <= members
    assert all(one["reader"] == "work" for one in counts)
    assert all(one["bounds"] == ["person_owner"] for one in counts)
