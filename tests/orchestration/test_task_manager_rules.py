"""Tasks the person sets, through planning's calls and the Task Manager (ADR-0340).

Spawn's two new arguments and its local times (§3, §8:1), their refusals (§3:5, §4:4) and
the store's (§4:1), the read-back (§6:2), the list pull's fields (§8:2), skipping and
changing (§5), and every rendering in the person's zone (§6:1), over the canonical fakes,
the person's profile zone differing from the hub's ``Settings.timezone``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import pytest
from task_support import CHAT, LIMITS, LINE, activation, spawn_effect

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    DueAfterTasks,
    DueAt,
    DueOnRule,
    OccurrenceState,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    RuleDay,
    ScheduledTaskAuthor,
    TaskRuleKind,
    TaskSpawn,
    TaskWriteAnswer,
    ToolCall,
    ToolResult,
)
from ai_assistant.orchestration.acting import Unwritten
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.task_manager import ScheduledTaskCalls, TaskManager, spawn_when
from ai_assistant.orchestration.task_rules import PersonZones, task_zone
from ai_assistant.orchestration.task_scheduler import (
    CANCEL_TASK,
    LIST_TASKS,
    SPAWN,
    Spawner,
    TaskEntry,
    decode_listing,
    lineage_steps,
    read_back,
    spawning,
    task_input,
    when_text,
)
from ai_assistant.testing import FakeMemoryStore, FakePlanStore
from ai_assistant.testing.person_model import FakePersonModelStore

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson, ScheduledTask, ToolDefinition

#: Friday 23 October 2026, 09:00 in New York, the person's profile zone; 13:00 in UTC,
#: the hub's ``Settings.timezone``.
NOW: Final = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
NEW_YORK: Final = ZoneInfo("America/New_York")
HUB: Final = ZoneInfo("UTC")
#: How a rule naming no zone is said: with the person's zone it follows, named (#3451).
FOLLOWS: Final = " in the person's zone, which it follows (now America/New_York)"
CHAT_PLACE: Final = f"conversation:{CHAT.instance_id}"
LINE_PLACE: Final = f"telegram:{LINE.instance_id}"


async def _people(zone: str | None = "America/New_York") -> FakePersonModelStore:
    people = FakePersonModelStore(now=lambda: NOW)
    if zone is not None:
        await people.set_field(
            OWNER_PERSON_ID,
            ProfileField.TIME_ZONE,
            zone,
            act=PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID),
        )
    return people


class _World:
    """A Task Manager over the fakes, the person's zone New York and the hub's UTC."""

    def __init__(self, people: FakePersonModelStore, *, now: datetime = NOW) -> None:
        self.now = now
        self.plans = FakePlanStore(now=lambda: self.now)
        self.memory = FakeMemoryStore(now=lambda: self.now)
        self.manager = TaskManager(
            plans=self.plans,
            memory=self.memory,
            running=lambda: (),
            is_running=lambda _one: False,
            starting=lambda _one: False,
            wake=lambda: None,
            limits=LIMITS,
            zones=PersonZones(default=HUB, people=people),
            now=lambda: self.now,
        )
        self.calls = ScheduledTaskCalls(manager=self.manager, now=lambda: self.now)

    async def task(self, task_id: str) -> ScheduledTask:
        (held,) = await self.plans.scheduled_tasks([task_id])
        return held


async def _world(zone: str | None = "America/New_York", *, now: datetime = NOW) -> _World:
    return _World(await _people(zone), now=now)


def _call(tool: ToolDefinition, arguments: dict[str, FrozenJson]) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=arguments)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id=f"decision:{activation()}", decided_at=NOW
    )
    return ToolCall(request=request, decision=decision)


def _spawner(**changes: object) -> Spawner:
    held: dict[str, object] = {
        "activation_id": activation(),
        "person": OWNER_PERSON_ID,
        "users_authority": True,
        "set_in": CHAT,
        "places": (CHAT_PLACE,),
    }
    held.update(changes)
    return Spawner(**held)  # type: ignore[arg-type]  # each knob is the field's own


async def _spawn(world: _World, spawner: Spawner | None = None, **arguments: Any) -> object:
    asker = spawner or _spawner()
    call = _call(SPAWN, {"instruction": "remind them to call Mom", **arguments})
    with spawning(asker):
        return await world.calls.run_claiming(
            call,
            spawn_effect(asker.activation_id, at=world.now),
            match=None,
            deliberate_repeat=False,
        )


def _spawned(answer: object) -> TaskEntry:
    assert isinstance(answer, ToolResult), answer
    listing = decode_listing(answer.output)
    assert listing is not None
    assert listing.spawned is not None
    return listing.spawned


def _refused(answer: object) -> str:
    assert isinstance(answer, Unwritten), answer
    return answer.reason


async def _only_task(world: _World) -> ScheduledTask:
    (held,) = await world.plans.person_scheduled_tasks(OWNER_PERSON_ID, [OccurrenceState.PENDING])
    return held


# --- local times (§3:2-§3:5) -------------------------------------------------------------


async def test_a_local_time_is_read_in_the_persons_profile_zone_not_the_hubs() -> None:
    """§3:2-§3:3, §10:4: 20:00 with no offset is 20:00 in New York, said in New York."""
    world = await _world()

    entry = _spawned(await _spawn(world, at="2026-10-23T20:00", connections=[CHAT_PLACE]))

    task = await _only_task(world)
    assert task.when == DueAt(at=datetime(2026, 10, 24, 0, 0, tzinfo=UTC))
    assert entry.falls_due == "at Fri 23 Oct 2026 20:00 (America/New_York)"
    assert entry.read_back == "Tonight, Friday 23 October, at 8:00 PM, here."


async def test_a_local_time_with_no_profile_zone_is_read_in_the_hubs() -> None:
    world = await _world(None)

    await _spawn(world, at="2026-10-23T20:00")

    assert (await _only_task(world)).when == DueAt(at=datetime(2026, 10, 23, 20, 0, tzinfo=UTC))


async def test_a_local_time_is_read_in_the_zone_the_spawn_names() -> None:
    """§3:2: "at 8 Lisbon time", rendered in the person's zone (§6:1)."""
    world = await _world()

    entry = _spawned(await _spawn(world, at="2026-10-23T20:00", zone="Europe/Lisbon"))

    assert (await _only_task(world)).when == DueAt(at=datetime(2026, 10, 23, 19, 0, tzinfo=UTC))
    assert entry.falls_due == "at Fri 23 Oct 2026 15:00 (America/New_York)"


async def test_an_instant_with_its_offset_is_taken_as_it_is() -> None:
    world = await _world()

    await _spawn(world, at="2026-10-23T20:00:00+02:00")

    assert (await _only_task(world)).when == DueAt(at=datetime(2026, 10, 23, 18, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    ("local", "due"),
    [
        # §3:4: the gap's 02:30 is the first instant after it, 03:00 EDT.
        ("2027-03-14T02:30", datetime(2027, 3, 14, 7, 0, tzinfo=UTC)),
        # §3:4: the repeated 01:30 is the earlier, EDT's.
        ("2026-11-01T01:30", datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
    ],
)
async def test_a_one_off_in_a_daylight_saving_gap_and_in_a_repeat(
    local: str, due: datetime
) -> None:
    """§10:4: a local time in a gap, and one in a repeat, for a one-off."""
    world = await _world()

    await _spawn(world, at=local)

    assert (await _only_task(world)).when == DueAt(at=due)


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        # §3:5: a UTC offset and a zone name together.
        ({"at": "2026-10-23T20:00:00-04:00", "zone": "America/New_York"}, "never both"),
        # §3:5: a zone zoneinfo does not resolve.
        ({"at": "2026-10-23T20:00", "zone": "Mars/Olympus_Mons"}, "not an IANA zone"),
        ({"at": "2026-10-23T20:00", "zone": "../etc/passwd"}, "not an IANA zone"),
        # A zone with nothing to read in it.
        ({"delay_minutes": 10, "zone": "Europe/Lisbon"}, "only with at or rule"),
        ({"zone": "Europe/Lisbon"}, "only with at or rule"),
        # ADR-0350 §4:5, read in the person's zone: 08:00 this morning has passed.
        ({"at": "2026-10-23T08:00"}, "earlier than now"),
        ({"at": "2026-10-23T20:00", "rule": {"repeats": "daily", "time": "20:00"}}, "at most one"),
    ],
)
async def test_each_refusal_of_a_local_time_writes_nothing(
    arguments: dict[str, Any], reason: str
) -> None:
    world = await _world()

    assert reason in _refused(await _spawn(world, **arguments))
    assert (await world.plans.export()).scheduled_tasks == ()


# --- the rule (§4) -----------------------------------------------------------------------


async def test_a_weekdays_rule_writes_its_first_occurrence_and_says_it_back() -> None:
    """§4:2, §4:5: set on a Friday morning at 07:00 past, it first falls on Monday."""
    world = await _world()

    entry = _spawned(
        await _spawn(world, rule={"repeats": "weekdays", "time": "07:00"}, connections=[CHAT_PLACE])
    )

    task = await _only_task(world)
    assert task.when == DueOnRule(repeats=TaskRuleKind.WEEKDAYS, time_of_day=time(7, 0))
    assert [one.due_at for one in task.occurrences] == [datetime(2026, 10, 26, 11, 0, tzinfo=UTC)]
    assert entry.repeats == f"every weekday at 7:00 AM{FOLLOWS}"
    assert entry.falls_due == (
        f"every weekday at 7:00 AM{FOLLOWS}; next at Mon 26 Oct 2026 07:00 (America/New_York)"
    )
    assert entry.read_back == (
        f"Every weekday at 7:00 AM{FOLLOWS}; next: Monday 26 October, at 7:00 AM, here."
    )


async def test_a_daily_rule_set_before_its_time_today_falls_today() -> None:
    world = await _world()

    entry = _spawned(await _spawn(world, rule={"repeats": "daily", "time": "19:00"}))

    assert entry.read_back == (
        f"Every day at 7:00 PM{FOLLOWS}; next: Tonight, Friday 23 October, at 7:00 PM. "
        "It suggests no place."
    )


async def test_a_weekly_rule_on_two_days_names_both() -> None:
    world = await _world()

    entry = _spawned(
        await _spawn(
            world, rule={"repeats": "weekly", "days": ["thursday", "monday"], "time": "18:30"}
        )
    )

    assert entry.repeats == f"every Monday and Thursday at 6:30 PM{FOLLOWS}"
    assert (await _only_task(world)).occurrences[0].due_at == datetime(
        2026, 10, 26, 22, 30, tzinfo=UTC
    )


async def test_a_rule_naming_a_zone_is_computed_and_said_in_it() -> None:
    """§4:3, §6:1: a change of the person's zone does not move it; it names its zone."""
    world = await _world("Asia/Tokyo")

    entry = _spawned(
        await _spawn(world, rule={"repeats": "weekdays", "time": "09:30"}, zone="America/New_York")
    )

    task = await _only_task(world)
    assert task.occurrences[0].due_at == datetime(2026, 10, 23, 13, 30, tzinfo=UTC)
    assert task_zone(task, ZoneInfo("Asia/Tokyo")) == NEW_YORK
    assert entry.read_back == (
        "Every weekday at 9:30 AM America/New_York time; next: Today, Friday 23 October, "
        "at 9:30 AM America/New_York time. It suggests no place."
    )


async def test_a_rule_with_a_from_and_an_until_says_both_back() -> None:
    world = await _world()

    entry = _spawned(
        await _spawn(
            world,
            rule={"repeats": "daily", "time": "20:00", "from": "2026-10-27", "until": "2026-11-30"},
        )
    )

    assert entry.read_back == (
        f"Every day at 8:00 PM{FOLLOWS}, from Tuesday 27 October, until Monday 30 November; next: "
        "Tuesday 27 October, at 8:00 PM. It suggests no place."
    )


async def test_a_rule_in_a_daylight_saving_gap_falls_at_the_first_instant_after_it() -> None:
    """§4:9, §10:4: a rule's first occurrence in the gap, for a rule."""
    world = await _world(now=datetime(2027, 3, 13, 12, 0, tzinfo=UTC))

    await _spawn(world, rule={"repeats": "daily", "time": "02:30", "from": "2027-03-14"})

    assert (await _only_task(world)).occurrences[0].due_at == datetime(
        2027, 3, 14, 7, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        # §4:4: an until earlier than its from.
        (
            {"repeats": "daily", "time": "20:00", "from": "2026-11-02", "until": "2026-11-01"},
            "until is earlier than its from",
        ),
        # §4:4: no occurrence later than now before its until.
        ({"repeats": "daily", "time": "08:00", "until": "2026-10-23"}, "no occurrence later"),
        # §4:2: a weekly rule with no day, and a daily one naming days.
        ({"repeats": "weekly", "time": "08:00"}, "names one or more days"),
        ({"repeats": "daily", "days": ["monday"], "time": "08:00"}, "names one or more days"),
        ({"repeats": "weekly", "days": ["monday", "monday"], "time": "08:00"}, "names one"),
        # §4:2: to the minute.
        ({"repeats": "daily", "time": "08:00:30"}, "to the minute"),
        ({"repeats": "daily", "time": "eight"}, "to the minute"),
        ({"repeats": "daily", "time": "08:00", "until": "soon"}, "malformed"),
    ],
)
async def test_each_refusal_of_a_rule_writes_nothing(rule: dict[str, Any], reason: str) -> None:
    world = await _world()

    assert reason in _refused(await _spawn(world, rule=rule))
    assert (await world.plans.export()).scheduled_tasks == ()


async def test_a_rule_from_an_activation_without_the_persons_authority_is_refused() -> None:
    """§4:1, §9:2, §10:4: the plan store's refusal, said as not done, writing nothing."""
    world = await _world()

    reason = _refused(
        await _spawn(
            world, _spawner(users_authority=False), rule={"repeats": "daily", "time": "20:00"}
        )
    )

    assert "only a task the person asked for may repeat" in reason
    assert (await world.plans.export()).scheduled_tasks == ()


# --- skipping and changing (§5) ----------------------------------------------------------


async def _rule_task(world: _World, rule: dict[str, Any]) -> ScheduledTask:
    _spawned(await _spawn(world, rule=rule, connections=[CHAT_PLACE]))
    return await _only_task(world)


async def test_a_skip_is_a_replace_whose_from_is_the_day_after() -> None:
    """§5:1, §10:4: "skip tomorrow's" for a daily task, said back whole."""
    world = await _world()
    daily = await _rule_task(world, {"repeats": "daily", "time": "20:00"})

    entry = _spawned(
        await _spawn(
            world,
            rule={"repeats": "daily", "time": "20:00", "from": "2026-10-24"},
            replaces=daily.id,
        )
    )

    task = await _only_task(world)
    assert task.id != daily.id
    assert task.occurrences[0].due_at == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    assert entry.read_back == (
        f"Every day at 8:00 PM{FOLLOWS}, from Saturday 24 October; next: Tomorrow, Saturday "
        "24 October, at 8:00 PM, here."
    )


async def test_make_it_nine_on_a_rule_whose_from_has_passed_replaces_it() -> None:
    """§5:3, §4:4, §10:4: a from that has passed constrains nothing, so a replace keeps it."""
    world = await _world(now=datetime(2026, 10, 20, 13, 0, tzinfo=UTC))
    daily = await _rule_task(world, {"repeats": "daily", "time": "20:00", "from": "2026-10-21"})
    world.now = NOW

    _spawned(
        await _spawn(
            world,
            rule={"repeats": "daily", "time": "21:00", "from": "2026-10-21"},
            replaces=daily.id,
        )
    )

    task = await _only_task(world)
    assert task.occurrences[0].due_at == datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
    assert task.places == (CHAT,)


async def test_a_skip_of_a_bounded_rules_last_occurrence_is_a_cancel() -> None:
    """§5:1, §10:4: its replace would yield nothing, so the skip is the cancel, which ends it."""
    world = await _world()
    daily = await _rule_task(world, {"repeats": "daily", "time": "20:00", "until": "2026-10-23"})

    replace = await _spawn(
        world,
        rule={"repeats": "daily", "time": "20:00", "from": "2026-10-24", "until": "2026-10-23"},
        replaces=daily.id,
    )
    cancelled = await world.manager.cancel(daily.id, person=OWNER_PERSON_ID)

    assert "until is earlier than its from" in _refused(replace)
    assert cancelled.task is not None
    assert [one.state for one in cancelled.task.occurrences] == [OccurrenceState.CANCELLED]
    assert not await world.plans.person_scheduled_tasks(OWNER_PERSON_ID, [OccurrenceState.PENDING])


async def test_the_task_managers_replace_computes_a_rules_first_occurrence() -> None:
    world = await _world()
    one_off = (await _spawn(world, at="2026-10-23T20:00"), await _only_task(world))[1]

    written = await world.manager.replace(
        one_off.id,
        instruction="the bins",
        when=DueOnRule(repeats=TaskRuleKind.WEEKDAYS, time_of_day=time(7, 0)),
    )

    assert written.answer is TaskWriteAnswer.WRITTEN
    assert written.task is not None
    assert written.task.occurrences[0].due_at == datetime(2026, 10, 26, 11, 0, tzinfo=UTC)


async def test_the_task_managers_replace_refuses_a_rule_with_no_occurrence_left() -> None:
    world = await _world()
    one_off = (await _spawn(world, at="2026-10-23T20:00"), await _only_task(world))[1]

    with pytest.raises(PlanningError, match="no occurrence later than now"):
        await world.manager.replace(
            one_off.id,
            instruction="the bins",
            when=DueOnRule(
                repeats=TaskRuleKind.DAILY,
                time_of_day=time(7, 0),
                until_date=date(2026, 10, 23),
            ),
        )


async def test_the_task_managers_replace_refuses_a_zone_that_does_not_resolve() -> None:
    """§3:5, §4:3: never computed in the person's zone instead; the task stays pending."""
    world = await _world()
    one_off = (await _spawn(world, at="2026-10-23T20:00"), await _only_task(world))[1]

    with pytest.raises(PlanningError, match="not an IANA zone name"):
        await world.manager.replace(
            one_off.id,
            instruction="the bins",
            when=DueOnRule(
                repeats=TaskRuleKind.DAILY, time_of_day=time(7, 0), zone="Mars/Olympus_Mons"
            ),
        )

    assert (await _only_task(world)).id == one_off.id


# --- a person's zone that cannot be read (§3:3) ------------------------------------------


async def test_a_spawn_whose_persons_zone_cannot_be_read_is_refused_writing_nothing() -> None:
    """§3:3: a local time is never read in a guessed zone."""
    people = await _people()
    world = _World(people)
    people.fail_next()

    reason = _refused(await _spawn(world, at="2026-10-23T20:00"))

    assert "zone could not be read" in reason
    assert (await world.plans.export()).scheduled_tasks == ()


async def test_a_cancel_or_list_whose_zone_cannot_be_read_does_nothing() -> None:
    people = await _people()
    world = _World(people)
    _spawned(await _spawn(world, at="2026-10-23T20:00"))
    task = await _only_task(world)

    people.fail_next()
    with spawning(_spawner()):
        cancelled = await world.calls.run(_call(CANCEL_TASK, {"task": task.id}))
    people.fail_next()
    with spawning(_spawner()):
        listed = await world.calls.run(_call(LIST_TASKS, {}))

    assert isinstance(cancelled, NotDone)
    assert "zone could not be read" in cancelled.reason
    assert isinstance(listed, NotDone)
    assert (await _only_task(world)).id == task.id


# --- the read-back (§6:2) ----------------------------------------------------------------


async def test_a_task_suggesting_no_place_says_so_and_the_line_only_where_connected() -> None:
    """§6:2, §10:4: with the line's chat on the place list, it may still message there."""
    world = await _world()

    without = _spawned(await _spawn(world, at="2026-10-23T17:00"))
    with_line = _spawned(
        await _spawn(world, _spawner(places=(CHAT_PLACE, LINE_PLACE)), at="2026-10-23T17:00")
    )

    assert without.read_back == "Today, Friday 23 October, at 5:00 PM. It suggests no place."
    assert with_line.read_back == (
        "Today, Friday 23 October, at 5:00 PM. It suggests no place, and may still message "
        "the person on Telegram."
    )


async def test_a_task_suggesting_the_line_says_on_telegram() -> None:
    world = await _world()

    entry = _spawned(
        await _spawn(
            world,
            _spawner(places=(CHAT_PLACE, LINE_PLACE)),
            at="2026-10-24T08:00",
            connections=[LINE_PLACE, CHAT_PLACE],
        )
    )

    assert entry.read_back == "Tomorrow, Saturday 24 October, at 8:00 AM, on Telegram and here."


async def test_a_task_waiting_on_named_tasks_says_when_they_end_and_no_time() -> None:
    """§6:2, §10:4."""
    world = await _world()
    _spawned(await _spawn(world, at="2026-10-23T20:00"))
    first = await _only_task(world)

    entry = _spawned(await _spawn(world, after=[first.id]))

    assert entry.read_back == "When the tasks it waits on have all ended. It suggests no place."
    assert entry.falls_due == "once every task it waits on has ended"


# --- every rendering in the person's zone (§6:1) -----------------------------------------


async def _assistants_task(world: _World, *, when: DueAt | DueAfterTasks) -> ScheduledTask:
    written = await world.plans.write_scheduled_task(
        TaskSpawn(
            id=f"task:{activation()}",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.ASSISTANT,
            when=when,
            places=(CHAT,),
            instruction="check back on the flight",
            set_in=CHAT,
            set_at=world.now,
        ),
        spawn_effect(activation(), at=world.now),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert written.task is not None
    return written.task


async def test_a_task_the_assistant_set_renders_in_the_persons_zone_everywhere() -> None:
    """§6:1, §10:4: its spawn's result, the list pull and the Task Manager's queries."""
    world = await _world()
    spawned = _spawned(await _spawn(world, _spawner(users_authority=False), at="2026-10-24T08:00"))
    task = await _assistants_task(world, when=DueAt(at=datetime(2026, 10, 24, 12, 0, tzinfo=UTC)))

    with spawning(_spawner()):
        listed = await world.calls.run(_call(LIST_TASKS, {}))
    scheduled = await world.manager.scheduled(OWNER_PERSON_ID)

    assert spawned.author == "assistant"
    assert spawned.falls_due == "at Sat 24 Oct 2026 08:00 (America/New_York)"
    assert isinstance(listed, ToolResult)
    listing = decode_listing(listed.output)
    assert listing is not None
    shown = {one.task_id: one for one in listing.scheduled}
    assert shown[task.id].falls_due == "at Sat 24 Oct 2026 08:00 (America/New_York)"
    assert shown[task.id].parent_text.endswith("Fri 23 Oct 2026 09:00 (America/New_York)")
    assert {one.task_id: one.falls_due for one in scheduled}[task.id] == (
        "at Sat 24 Oct 2026 08:00 (America/New_York)"
    )
    # With no profile zone, the same task renders in the hub's.
    assert when_text(task, HUB, now=NOW) == "at Sat 24 Oct 2026 12:00 (UTC)"


async def test_the_list_pull_shows_a_rules_words_and_its_next_occurrence() -> None:
    """§8:2."""
    world = await _world()
    await _rule_task(world, {"repeats": "weekdays", "time": "07:00"})

    with spawning(_spawner()):
        listed = await world.calls.run(_call(LIST_TASKS, {}))

    assert isinstance(listed, ToolResult)
    listing = decode_listing(listed.output)
    assert listing is not None
    (entry,) = listing.scheduled
    assert entry.repeats == f"every weekday at 7:00 AM{FOLLOWS}"
    assert entry.falls_due.endswith("next at Mon 26 Oct 2026 07:00 (America/New_York)")
    assert entry.read_back is None


async def test_an_occurrences_input_states_its_rule_and_how_many_it_skipped() -> None:
    """§7:1: beside ADR-0350 §6:2's facts, in the person's zone; late stated as a fact."""
    world = await _world()
    task = await _rule_task(world, {"repeats": "daily", "time": "08:00"})

    text = task_input(
        task,
        due_at=datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
        second_try=False,
        zone=NEW_YORK,
        late_at=datetime(2026, 10, 26, 13, 0, tzinfo=UTC),
        skipped=2,
        now=datetime(2026, 10, 26, 13, 0, tzinfo=UTC),
    )

    assert text.startswith("remind them to call Mom\n\n(A scheduled task: ")
    assert "it repeats every day at 8:00 AM" in text
    assert "due Mon 26 Oct 2026 08:00 (America/New_York)" in text
    assert "it skipped 2 earlier occurrences" in text
    assert "late: it was started only Mon 26 Oct 2026 09:00 (America/New_York)" in text


async def test_a_one_off_occurrences_input_states_no_rule_and_no_skip() -> None:
    world = await _world()
    task = await _assistants_task(world, when=DueAt(at=datetime(2026, 10, 24, 12, 0, tzinfo=UTC)))

    text = task_input(
        task, due_at=task.occurrences[0].due_at, second_try=False, zone=NEW_YORK, late_at=None
    )

    assert "repeats" not in text
    assert "skipped" not in text
    assert "set by the assistant in a conversation in the hub's chat, Fri 23 Oct 2026 09:00" in text
    assert "due Sat 24 Oct 2026 08:00 (America/New_York)" in text


async def test_the_schedules_window_tells_a_rules_step_by_the_occurrence_that_spawned_it() -> None:
    """§6:1, ADR-0350 §6:5: a step below a rule's second occurrence is that one's."""
    world = await _world(now=datetime(2026, 10, 20, 13, 0, tzinfo=UTC))
    daily = await _rule_task(world, {"repeats": "daily", "time": "08:00"})
    first, second = activation(), activation()
    from ai_assistant.core.types import RulePush  # noqa: PLC0415 — this case's alone

    due = daily.occurrences[0].due_at
    assert due is not None
    await world.plans.mark_occurrence_pushed(
        daily.id, 1, first, rule=RulePush(successor=due + timedelta(days=1))
    )
    await world.plans.settle_occurrence(first, OccurrenceState.DONE)
    await world.plans.mark_occurrence_pushed(
        daily.id, 2, second, rule=RulePush(successor=due + timedelta(days=2))
    )
    step = await world.plans.write_scheduled_task(
        TaskSpawn(
            id=f"task:{activation()}",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.PERSON,
            when=DueAt(at=due + timedelta(days=1, hours=1)),
            instruction="follow up",
            set_in=CHAT,
            set_at=world.now,
        ),
        spawn_effect(second, at=world.now),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert step.task is not None
    held = await world.task(daily.id)

    steps = lineage_steps((held, step.task), {}, NEW_YORK)

    # The occurrence pushed to the step's parent is the second, still running.
    assert steps[1].text.startswith("Step 1, running, or about to start: ")


def test_read_back_of_a_task_due_now() -> None:
    from ai_assistant.core.types import (  # noqa: PLC0415 — this case's alone
        DueNow,
        ScheduledOccurrence,
    )
    from ai_assistant.core.types import ScheduledTask as Task  # noqa: PLC0415 — this case's alone

    task = Task(
        id="task:now",
        person=OWNER_PERSON_ID,
        author=ScheduledTaskAuthor.PERSON,
        when=DueNow(),
        places=(CHAT,),
        instruction="check the oven",
        parent=activation(),
        set_in=CHAT,
        set_at=NOW,
        chain_length=1,
        occurrences=(ScheduledOccurrence(number=1, due_at=NOW),),
    )

    assert read_back(task, NEW_YORK, now=NOW, line=False) == "Now, here."


def test_spawn_when_resolves_a_rule_to_its_first_instant_in_the_zone_given() -> None:
    stated = spawn_when(
        {"rule": {"repeats": "weekly", "days": [RuleDay.SUNDAY.value], "time": "10:00"}},
        now=NOW,
        zone=NEW_YORK,
    )

    assert not isinstance(stated, str)
    assert stated.first_due_at == datetime(2026, 10, 25, 14, 0, tzinfo=UTC)


async def test_a_pending_occurrence_computed_before_a_zone_change_says_so() -> None:
    """ADR-0340 §4:3, §6:1, §8:2, #3451: the list pull and the occurrence's input."""
    world = await _world()
    task = await _rule_task(world, {"repeats": "daily", "time": "07:00"})
    (due,) = [one.due_at for one in task.occurrences]
    assert due is not None
    los_angeles = ZoneInfo("America/Los_Angeles")

    falls_due = when_text(task, los_angeles, now=NOW)
    told = task_input(task, due_at=due, second_try=False, zone=los_angeles, late_at=None, now=NOW)

    stale = (
        ", computed while the person's zone was an earlier one, so this one comes at "
        "7:00 AM in that zone, and the ones after it at 7:00 AM in America/Los_Angeles"
    )
    assert falls_due == (
        "every day at 7:00 AM in the person's zone, which it follows (now "
        f"America/Los_Angeles); next at Sat 24 Oct 2026 04:00 (America/Los_Angeles){stale}"
    )
    assert f"due Sat 24 Oct 2026 04:00 (America/Los_Angeles){stale}" in told
    assert "computed while" not in when_text(task, NEW_YORK, now=NOW)
