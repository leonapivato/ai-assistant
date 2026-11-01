"""The Approvals channel's sensor: its look and the restart's pass (ADR-0361 §3:4-§3:7).

Driven over the canonical plan store and memory store, with the engine's push stood in
for by a recorder, so each case holds the sensor to what it reads and writes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
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
    RequestedCall,
    Reversibility,
    RiskLevel,
    TicketState,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.approval_sensor import ApprovalsSensor
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

_AT: Final = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_DAY: Final = timedelta(hours=24)
_RECHECK: Final = timedelta(seconds=30)
_TAP: Final = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT)

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
    },
)


class _Clock:
    def __init__(self) -> None:
        self.at = _AT

    def __call__(self) -> datetime:
        return self.at


class _Pushes:
    """The engine's push, recorded: each request, and the id an earlier mark named."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, str | None]] = []

    async def __call__(self, request: ApprovalRequest, activation_id: str | None) -> None:
        self.pushed.append((str(request.id), activation_id))


def _sensor(
    plans: FakePlanStore, memory: FakeMemoryStore, pushes: _Pushes, clock: _Clock
) -> ApprovalsSensor:
    return ApprovalsSensor(
        plans=plans,
        memory=memory,
        push=pushes,
        is_running=lambda _activation: False,
        closing=lambda: False,
        recheck=_RECHECK,
        now=clock,
    )


async def _written(plans: FakePlanStore, request_id: str, *, at: datetime = _AT) -> ApprovalRequest:
    request = ApprovalRequest(
        id=request_id,
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round="round:ask",
        call=RequestedCall(tool=_BOOK, values={"date": request_id}),
        why="You asked me to book the table.",
        written_at=at,
        expires_at=at + _DAY,
    )
    effect = ActivationEffect(
        id=f"effect:{request_id}",
        activation_id="act-ask",
        round="round:ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id=f"decision:{request_id}",
        claimed_at=at,
        request=request_id,
    )
    await plans.write_approval_request(request, effect, match=None)
    return request


async def test_a_look_pushes_each_answered_outcome_and_sleeps_until_the_next_expiry() -> None:
    """§3:4: each outcome on its own; the sleep the earliest expiry, at most the recheck."""
    plans, memory, pushes, clock = FakePlanStore(), FakeMemoryStore(), _Pushes(), _Clock()
    await _written(plans, "approval:a")
    await _written(plans, "approval:b")
    await plans.answer_approval_request("approval:a", ApprovalRequestState.DENIED, _TAP)
    sensor = _sensor(plans, memory, pushes, clock)

    wait = await sensor.look()

    assert pushes.pushed == [("approval:a", None)]
    assert wait == _RECHECK.total_seconds(), "the next expiry is a day off"
    clock.at = _AT + _DAY - timedelta(seconds=10)
    assert 0 < await sensor.look() <= 10, "and sleeps until it, nearer than the recheck"


async def test_a_request_past_its_expiry_ends_expired_and_is_pushed() -> None:
    """§3:5, §3:7: a pending request ends expired at 24 hours, and its outcome is pushed."""
    plans, memory, pushes, clock = FakePlanStore(), FakeMemoryStore(), _Pushes(), _Clock()
    await _written(plans, "approval:a")
    await _written(plans, "approval:b")
    await plans.answer_approval_request("approval:b", ApprovalRequestState.APPROVED, _TAP)
    await plans.mark_approval_outcome_pushed("approval:b", "act-b")
    clock.at = _AT + _DAY

    await _sensor(plans, memory, pushes, clock).look()

    expired, approved = await plans.approval_requests(["approval:a", "approval:b"])
    assert expired.state is ApprovalRequestState.EXPIRED
    assert expired.ticket is None
    assert approved.ticket is TicketState.VOID, "a ticket expires with its request"
    assert pushes.pushed == [("approval:a", None)], "an outcome already pushed is not again"


async def test_after_a_restart_an_outcome_never_admitted_is_pushed_again_under_its_mark() -> None:
    """§3:7: one never admitted is pushed again; one admitted that a restart cut off is void."""
    plans, memory, pushes, clock = FakePlanStore(), FakeMemoryStore(), _Pushes(), _Clock()
    await _written(plans, "approval:a")
    await _written(plans, "approval:b")
    for one in ("approval:a", "approval:b"):
        await plans.answer_approval_request(one, ApprovalRequestState.APPROVED, _TAP)
    await plans.mark_approval_outcome_pushed("approval:a", "act-never")
    await plans.mark_approval_outcome_pushed("approval:b", "act-admitted")
    from observer_support import episode  # noqa: PLC0415 — a sibling helper

    await memory.add(episode("act-admitted"))

    assert await _sensor(plans, memory, pushes, clock).settle_restart()

    assert pushes.pushed == [("approval:a", "act-never")]
    (cut_off,) = await plans.approval_requests(["approval:b"])
    assert cut_off.ticket is TicketState.VOID, "running the call takes a new request"


async def test_the_loop_wakes_on_a_write_and_stops_with_the_hub() -> None:
    """§3:4: every write to a request wakes it; it ends at its next look once closed."""
    plans, memory, pushes, clock = FakePlanStore(), FakeMemoryStore(), _Pushes(), _Clock()
    sensor = _sensor(plans, memory, pushes, clock)
    running = asyncio.ensure_future(sensor.run())
    await asyncio.sleep(0.01)
    await _written(plans, "approval:a")
    await plans.answer_approval_request("approval:a", ApprovalRequestState.APPROVED, _TAP)
    sensor.wake()
    for _ in range(100):
        if pushes.pushed:
            break
        await asyncio.sleep(0.01)
    assert pushes.pushed == [("approval:a", None)]
    sensor.close()
    await asyncio.wait_for(running, 1)
