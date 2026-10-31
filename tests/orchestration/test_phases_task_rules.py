"""A task the person set coming due on the engine: the sensor's use of a rule (ADR-0340).

The sensor's push of a rule's occurrence (§4:6, §4:8), what its activation's input states
(§7:1), the restarts days later that push an occurrence again beside the latest missed
one (§4:8, §10:4), and the person's zone in the input and the schedule's window (§6:1),
each driven through the engine with the phases wired, over the canonical fakes.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from phases_support import phases_harness, until
from task_support import AT, CHAT, LINE, activation, message, pushed, seams, spawn_effect

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    DueAt,
    DueOnRule,
    OccurrenceState,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    RoundResponse,
    RulePush,
    ScheduledTaskAuthor,
    TaskRuleKind,
    TaskSpawn,
    ToolOutcome,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.task_scheduler import SCHEDULE, TASK_SCHEDULER_DESCRIPTION
from ai_assistant.testing import FakeMemoryStore, FakePlanStore, FakeToolCallingCompleter
from ai_assistant.testing.person_model import FakePersonModelStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import OfferedTool, PlanningExchange, ScheduledTask

#: The person's profile zone: AT, midnight UTC on 1 January 2026, is 19:00 on Wednesday
#: 31 December 2025 there. The hub's ``Settings.timezone`` is UTC.
NEW_YORK: Final = "America/New_York"


def _day(day: int) -> datetime:
    """08:00 in New York, as an instant, on a day of December 2025 (EST, so 13:00 UTC)."""
    return datetime(2025, 12, day, 13, 0, tzinfo=AT.tzinfo)


class _Inputs:
    """Planning's responder: a task's activation says nothing, and its input is kept."""

    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.windows: list[list[str]] = []

    def completer(self) -> FakeToolCallingCompleter:
        def respond(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
            request: dict[str, Any] = json.loads(exchange.briefing)
            if request["place"].get("description") == TASK_SCHEDULER_DESCRIPTION:
                window = request["place_window"]
                self.inputs.extend(str(one["text"]) for one in window if one.get("is_the_input"))
                self.windows.append([str(one["text"]) for one in window])
            return RoundResponse(text="")

        return FakeToolCallingCompleter(response=respond)


async def _harness(inputs: _Inputs, *, zone: str | None = NEW_YORK) -> Harness:
    harness, _ = await _harness_with_people(inputs, zone=zone)
    return harness


async def _harness_with_people(
    inputs: _Inputs, *, zone: str | None = NEW_YORK
) -> tuple[Harness, FakePersonModelStore]:
    memory = FakeMemoryStore(now=lambda: AT)
    people = FakePersonModelStore(now=lambda: AT)
    if zone is not None:
        await people.set_field(
            OWNER_PERSON_ID,
            ProfileField.TIME_ZONE,
            zone,
            act=PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID),
        )
    # The harness's own clock is another instant: this case's is ``AT``, everywhere.
    return phases_harness(
        inputs.completer(),
        task_scheduler=seams(),
        memory=memory,
        plans=FakePlanStore(now=lambda: AT),
        now=lambda: AT,
        person_blocks=PersonBlocks(store=people, memory=memory),
    ), people


async def _daily(plans: PlanStore, first: datetime) -> ScheduledTask:
    """A daily rule at 08:00 the person set, following their zone, first due at ``first``."""
    written = await plans.write_scheduled_task(
        TaskSpawn(
            id=f"task:{activation()}",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.PERSON,
            when=DueOnRule(repeats=TaskRuleKind.DAILY, time_of_day=time(8, 0)),
            places=(CHAT,),
            instruction="remind them to take the pill",
            set_in=CHAT,
            set_at=first - timedelta(days=1),
            first_due_at=first,
        ),
        spawn_effect(activation(), at=first - timedelta(days=1)),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert written.task is not None
    return written.task


async def _ran(harness: Harness, count: int) -> None:
    async def done() -> bool:
        page = await harness.memory.channel_episodes(SCHEDULE, limit=100)
        return len(page.entries) >= count

    await until(done, what=f"{count} scheduled activation(s)")


async def _held(harness: Harness, task_id: str) -> ScheduledTask:
    (held,) = await harness.plans.scheduled_tasks([task_id])
    return held


async def _settled(harness: Harness, task_id: str, count: int) -> ScheduledTask:
    """The task once ``count`` of its occurrences have ended done."""

    async def done() -> bool:
        held = await _held(harness, task_id)
        return sum(one.state is OccurrenceState.DONE for one in held.occurrences) >= count

    await until(done, what=f"{count} occurrence(s) done")
    return await _held(harness, task_id)


def _states(task: ScheduledTask) -> list[tuple[datetime | None, OccurrenceState, int]]:
    return [(one.due_at, one.state, one.pushes) for one in task.occurrences]


async def test_a_rules_first_push_writes_its_successor_and_its_input_states_the_rule() -> None:
    """§4:6, §7:1: pushed on time, its successor pending at the next day's 08:00."""
    inputs = _Inputs()
    harness = await _harness(inputs)
    task = await _daily(harness.plans, AT - timedelta(minutes=1))
    await harness.engine.start()
    try:
        await _ran(harness, 1)
        held = await _settled(harness, task.id, 1)
    finally:
        await harness.engine.aclose()

    assert _states(held) == [
        (AT - timedelta(minutes=1), OccurrenceState.DONE, 1),
        (datetime(2026, 1, 1, 13, 0, tzinfo=AT.tzinfo), OccurrenceState.PENDING, 0),
    ]
    (text,) = inputs.inputs
    assert "it repeats every day at 8:00 AM" in text
    assert "due Wed 31 Dec 2025 18:59 (America/New_York)" in text
    assert "skipped" not in text
    assert "late" not in text


async def test_a_push_whose_persons_zone_cannot_be_read_waits_and_is_pushed_after() -> None:
    """§3:3, §4:6: nothing is pushed on a guessed zone; a later look pushes it in theirs."""
    inputs = _Inputs()
    harness, people = await _harness_with_people(inputs)
    task = await _daily(harness.plans, AT - timedelta(minutes=1))
    people.fail_next()
    with structlog.testing.capture_logs() as captured:
        await harness.engine.start()
        try:
            await _ran(harness, 1)
            held = await _settled(harness, task.id, 1)
        finally:
            await harness.engine.aclose()

    # The fault met the push's read of the zone, and nothing was pushed on it.
    assert [one["event"] for one in captured].count("task_zone_unread") == 1
    assert held.occurrences[0].pushes == 1
    assert held.occurrences[1].due_at == datetime(2026, 1, 1, 13, 0, tzinfo=AT.tzinfo)
    (text,) = inputs.inputs
    assert "(America/New_York)" in text


async def test_a_rule_missed_for_three_days_pushes_one_late_occurrence_that_skipped_two() -> None:
    """§4:8, §10:4: the pending one and the next skipped; the latest pushed, late."""
    inputs = _Inputs()
    harness = await _harness(inputs)
    task = await _daily(harness.plans, _day(29))
    await harness.engine.start()
    try:
        await _ran(harness, 1)
        held = await _settled(harness, task.id, 1)
    finally:
        await harness.engine.aclose()

    assert _states(held) == [
        (_day(29), OccurrenceState.SKIPPED, 0),
        (_day(30), OccurrenceState.SKIPPED, 0),
        (_day(31), OccurrenceState.DONE, 1),
        (datetime(2026, 1, 1, 13, 0, tzinfo=AT.tzinfo), OccurrenceState.PENDING, 0),
    ]
    (text,) = inputs.inputs
    assert "due Wed 31 Dec 2025 08:00 (America/New_York)" in text
    assert "it skipped 2 earlier occurrences" in text
    assert "late: it was started only Wed 31 Dec 2025 19:00 (America/New_York)" in text


@pytest.mark.parametrize("second_try", [False, True])
async def test_a_push_again_days_later_is_pushed_itself_beside_the_latest_missed(
    *, second_try: bool
) -> None:
    """§4:8, §10:4: no next occurrence written by the push again; the successor's own push
    finds the latest missed one, once with no effect claimed and once as a second try."""
    inputs = _Inputs()
    harness = await _harness(inputs)
    task = await _daily(harness.plans, _day(27))
    cut_off = activation()
    await harness.plans.mark_occurrence_pushed(
        task.id, 1, cut_off, rule=RulePush(successor=_day(28))
    )
    if second_try:
        # A message on the line, whose delivery the line cannot confirm (ADR-0350 §8:6).
        await message(harness.plans, cut_off, LINE)
    await harness.engine.start()
    try:
        await _ran(harness, 2)
        held = await _settled(harness, task.id, 2)
    finally:
        await harness.engine.aclose()

    first = held.occurrences[0]
    assert first.state is OccurrenceState.DONE
    assert first.pushes == 2
    assert first.second_try is second_try
    assert _states(held)[1:] == [
        (_day(28), OccurrenceState.SKIPPED, 0),
        (_day(29), OccurrenceState.SKIPPED, 0),
        (_day(30), OccurrenceState.SKIPPED, 0),
        (_day(31), OccurrenceState.DONE, 1),
        (datetime(2026, 1, 1, 13, 0, tzinfo=AT.tzinfo), OccurrenceState.PENDING, 0),
    ]
    assert sum("a second try" in one for one in inputs.inputs) == int(second_try)
    assert sum("it skipped 3 earlier occurrences" in one for one in inputs.inputs) == 1


async def test_a_restart_days_after_a_confirmed_message_settles_it_and_pushes_the_latest() -> None:
    """§10:4: its message confirmed done ends it done; then the latest missed, late."""
    inputs = _Inputs()
    harness = await _harness(inputs)
    task = await _daily(harness.plans, _day(29))
    said = await pushed_rule(harness.plans, task, successor=_day(30))
    await message(harness.plans, said, CHAT, outcome=ToolOutcome.SUCCEEDED)
    await harness.engine.start()
    try:
        await _ran(harness, 1)
        held = await _settled(harness, task.id, 2)
    finally:
        await harness.engine.aclose()

    assert _states(held) == [
        (_day(29), OccurrenceState.DONE, 1),
        (_day(30), OccurrenceState.SKIPPED, 0),
        (_day(31), OccurrenceState.DONE, 1),
        (datetime(2026, 1, 1, 13, 0, tzinfo=AT.tzinfo), OccurrenceState.PENDING, 0),
    ]
    (text,) = inputs.inputs
    assert "it skipped 1 earlier occurrence," in text
    assert "late:" in text


async def pushed_rule(plans: PlanStore, task: ScheduledTask, *, successor: datetime) -> str:
    """Push a rule's first occurrence to a fresh activation, with its successor."""
    one = activation()
    await plans.mark_occurrence_pushed(task.id, 1, one, rule=RulePush(successor=successor))
    return one


async def test_a_task_the_assistant_set_is_told_in_the_persons_zone_in_input_and_window() -> None:
    """§6:1, §10:4: its activation's input and the schedule's window, in the profile's zone,
    not ``Settings.timezone``'s."""
    inputs = _Inputs()
    harness = await _harness(inputs)
    above = await _step(harness.plans, activation(), due=AT - timedelta(hours=1))
    ran = await pushed(harness.plans, above)
    await harness.plans.settle_occurrence(ran, OccurrenceState.DONE)
    await _step(harness.plans, ran, due=AT)
    await harness.engine.start()
    try:
        await _ran(harness, 1)
    finally:
        await harness.engine.aclose()

    (text,) = inputs.inputs
    assert "set by the assistant in a conversation in the hub's chat, Wed 31 Dec 2025 19:00" in text
    assert "(America/New_York)" in text
    assert "(UTC)" not in text
    (window,) = inputs.windows
    assert window[1].startswith("Step 1, Wed 31 Dec 2025 19:00 (America/New_York), done:")


async def test_with_no_profile_zone_the_input_is_told_in_the_hubs() -> None:
    inputs = _Inputs()
    harness = await _harness(inputs, zone=None)
    await _step(harness.plans, activation(), due=AT)
    await harness.engine.start()
    try:
        await _ran(harness, 1)
    finally:
        await harness.engine.aclose()

    (text,) = inputs.inputs
    assert "due Thu 01 Jan 2026 00:00 (UTC)" in text


async def _step(plans: PlanStore, parent: str, *, due: datetime) -> ScheduledTask:
    """A one-off step the assistant set, spawned by ``parent``."""
    written = await plans.write_scheduled_task(
        TaskSpawn(
            id=f"task:{activation()}",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.ASSISTANT,
            when=DueAt(at=due),
            places=(CHAT,),
            instruction="check back on the flight",
            set_in=CHAT,
            set_at=AT,
        ),
        spawn_effect(parent, at=AT),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert written.task is not None
    return written.task
