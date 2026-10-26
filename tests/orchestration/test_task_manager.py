"""The Task Manager, its cascade and its tidying, planning's calls and the place list.

ADR-0350 §4, §5:8-§5:11, §7:8, §9, §10, over the canonical fakes, with the engine's
account of what runs and its stop stood in for by a record of what was asked.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
from channel_episodes import conversation_episode
from task_support import (
    AT,
    CHAT,
    LIMITS,
    LINE,
    activation,
    message,
    pushed,
    schedule_episode,
    spawn_effect,
    write_task,
)

from ai_assistant.core.errors import ClaimStopped, ConversationStoreError, PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationStop,
    DueAfterTasks,
    DueAt,
    OccurrenceState,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import Unwritten
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.task_manager import (
    PlaceLists,
    ScheduledTaskCalls,
    TaskManager,
    TaskManagerLimits,
)
from ai_assistant.orchestration.task_rules import PersonZones
from ai_assistant.orchestration.task_scheduler import (
    CANCEL_TASK,
    LIST_TASKS,
    SCHEDULE,
    SPAWN,
    ActivationEntry,
    Spawner,
    TaskListing,
    decode_listing,
    encode_listing,
    spawning,
)
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActivationEffect, Conversation, FrozenJson, ToolDefinition


class _World:
    """A Task Manager over the fakes, with a running set and a stop a case reads."""

    def __init__(
        self, *, limits: TaskManagerLimits = LIMITS, plans: FakePlanStore | None = None
    ) -> None:
        self.plans = FakePlanStore(now=lambda: AT) if plans is None else plans
        self.memory = FakeMemoryStore(now=lambda: AT)
        self.running: set[str] = set()
        self.stopped: list[str] = []
        self.woken = 0
        self.manager = TaskManager(
            plans=self.plans,
            memory=self.memory,
            running=lambda: (),
            is_running=lambda one: one in self.running,
            stop_one=self._stop_one,
            wake=self._wake,
            limits=limits,
            zones=PersonZones(default=ZoneInfo("UTC")),
            now=lambda: AT,
        )
        self.calls = ScheduledTaskCalls(manager=self.manager, now=lambda: AT)

    async def _stop_one(self, activation_id: str) -> ActivationStop:
        self.stopped.append(activation_id)
        return ActivationStop.STOPPED

    def _wake(self) -> None:
        self.woken += 1

    async def held(self, task_id: str) -> OccurrenceState | None:
        found = await self.plans.scheduled_tasks([task_id])
        return found[0].occurrences[0].state if found else None


def _call(tool: ToolDefinition, arguments: dict[str, FrozenJson]) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=arguments)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id=f"decision:{activation()}", decided_at=AT
    )
    return ToolCall(request=request, decision=decision)


def _spawner(parent: str, **changes: object) -> Spawner:
    held: dict[str, object] = {
        "activation_id": parent,
        "person": OWNER_PERSON_ID,
        "users_authority": True,
        "set_in": CHAT,
        "places": (f"conversation:{CHAT.instance_id}",),
    }
    held.update(changes)
    return Spawner(**held)  # type: ignore[arg-type]  # each knob is the field's own


async def _spawn(world: _World, spawner: Spawner, **arguments: FrozenJson) -> ToolResult | object:
    call = _call(SPAWN, {"instruction": "check back", **arguments})
    with spawning(spawner):
        return await world.calls.run_claiming(
            call, spawn_effect(spawner.activation_id), match=None, deliberate_repeat=False
        )


# --- the stop's cascade (§9:6) -------------------------------------------------------------


async def test_a_stop_cancels_a_grandchild_below_a_child_that_ended() -> None:
    """§13:3: a stop of a step whose child ended after spawning a grandchild still pending."""
    world = _World()
    step = activation()
    child = await write_task(world.plans, step)
    ran = await pushed(world.plans, child)
    grandchild = await write_task(world.plans, ran, when=DueAt(at=AT + timedelta(days=1)))
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)

    await world.manager.cascade(step)

    # Cancelled, and then removed, since nothing of it or below it is live (§7:8).
    assert await world.held(grandchild.id) is None
    assert not await world.plans.person_scheduled_tasks(OWNER_PERSON_ID, [OccurrenceState.PENDING])
    assert world.stopped == []


async def test_a_next_step_pushed_before_the_cancel_is_stopped_in_turn() -> None:
    """§13:3, §9:6: where a push wins against the cancel, its activation is stopped."""
    world = _World()
    step = activation()
    following = await write_task(world.plans, step)
    started = await pushed(world.plans, following)

    await world.manager.cascade(step)

    assert world.stopped == [started]


async def test_after_a_cascade_record_nothing_below_is_pushed() -> None:
    """§7:5, §13:3: a crash after the record, before the walk cancelled a pending child."""
    world = _World()
    for settled_step in (False, True):
        top = activation()
        if settled_step:
            # A scheduled step whose own occurrence has already settled.
            above = await write_task(world.plans, activation())
            top = await pushed(world.plans, above)
            await world.plans.settle_occurrence(top, OccurrenceState.DONE)
        child = await write_task(world.plans, top)
        await world.plans.record_cascade(top)

        answer = await world.plans.mark_occurrence_pushed(child.id, 1, activation())

        assert answer.value == "cascade_cancelled"
        assert await world.held(child.id) is OccurrenceState.CANCELLED


# --- keeping the schedule (§7:8) -----------------------------------------------------------


async def test_a_task_is_removed_once_nothing_of_it_or_below_it_is_live() -> None:
    """§13:3: removed once §7:8 holds."""
    world = _World()
    task = await write_task(world.plans, activation())
    ran = await pushed(world.plans, task)
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)

    await world.manager.tidy([task.id])

    assert await world.held(task.id) is None


async def test_a_task_is_kept_while_a_task_below_it_is_pending() -> None:
    """§13:3: kept while a task below it is pending, and removed with it after."""
    world = _World()
    task = await write_task(world.plans, activation())
    ran = await pushed(world.plans, task)
    below = await write_task(world.plans, ran, when=DueAt(at=AT + timedelta(hours=1)))
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)

    await world.manager.tidy([task.id])
    assert await world.held(task.id) is OccurrenceState.DONE

    await world.manager.cancel(below.id)
    assert await world.held(below.id) is None
    assert await world.held(task.id) is None


async def test_a_child_that_ended_is_kept_while_its_parent_runs_so_a_wait_can_name_it() -> None:
    """§13:3, §5:4, §7:8: a child spawned now ends before its parent's later round."""
    world = _World()
    parent = activation()
    world.running.add(parent)
    child = await write_task(world.plans, parent)
    ran = await pushed(world.plans, child)
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)
    await world.manager.tidy([child.id])
    assert await world.held(child.id) is OccurrenceState.DONE

    gathered = await _spawn(world, _spawner(parent), after=[child.id])

    assert isinstance(gathered, ToolResult)
    listing = decode_listing(gathered.output)
    assert listing is not None
    assert listing.spawned is not None
    assert listing.spawned.waits_on == (child.id,)


# --- planning's calls (§4) -----------------------------------------------------------------


async def test_a_spawn_is_refused_on_its_spawners_stop_record() -> None:
    """§3:3, §13:3: the store refuses it, writing nothing."""
    world = _World()
    parent = activation()
    await world.plans.record_stop(parent)

    with pytest.raises(ClaimStopped):
        await _spawn(world, _spawner(parent))
    assert (
        await world.plans.person_scheduled_tasks(OWNER_PERSON_ID, [OccurrenceState.PENDING]) == ()
    )


async def test_a_spawn_is_refused_at_the_chain_limit() -> None:
    """§9:7, §13:3."""
    world = _World(limits=TaskManagerLimits(chain_limit=1, pending_limit=50, listing_bound=20))
    first = await write_task(world.plans, activation(), chain_limit=1)
    step = await pushed(world.plans, first)

    refused = await _spawn(world, _spawner(step, set_in=SCHEDULE))

    assert isinstance(refused, Unwritten)
    assert "chain limit" in refused.reason


async def test_a_spawn_is_refused_at_the_pending_limit() -> None:
    """§9:8, §13:3."""
    world = _World(limits=TaskManagerLimits(chain_limit=10, pending_limit=1, listing_bound=20))
    await write_task(world.plans, activation(), when=DueAt(at=AT + timedelta(hours=1)))

    refused = await _spawn(world, _spawner(activation()), delay_minutes=5)

    assert isinstance(refused, Unwritten)
    assert "pending limit" in refused.reason


async def test_a_replace_of_a_task_with_nothing_pending_is_refused() -> None:
    """§9:4, §13:3."""
    world = _World()
    task = await write_task(world.plans, activation())
    ran = await pushed(world.plans, task)
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)

    refused = await _spawn(world, _spawner(activation()), replaces=task.id, delay_minutes=5)

    assert isinstance(refused, Unwritten)
    assert "nothing of that task is pending" in refused.reason


async def test_a_replace_that_would_move_a_task_past_its_wait_is_refused() -> None:
    """§9:4, §13:3: a task waiting on named tasks is replaced only with a valid wait."""
    world = _World()
    parent = activation()
    waited = await write_task(world.plans, parent, when=DueAt(at=AT + timedelta(hours=1)))
    gather = await write_task(world.plans, parent, when=DueAfterTasks(tasks=(waited.id,)))

    refused = await _spawn(world, _spawner(parent), replaces=gather.id, delay_minutes=5)

    assert isinstance(refused, Unwritten)
    assert "waits" in refused.reason
    assert await world.held(gather.id) is OccurrenceState.PENDING


async def test_a_spawn_into_the_past_or_off_the_list_writes_nothing() -> None:
    """§4:5, §5:6: an instant earlier than now, and a place off the list."""
    world = _World()
    parent = activation()

    past = await _spawn(world, _spawner(parent), at="2025-12-31T23:00:00+00:00")
    off = await _spawn(world, _spawner(parent), places=["telegram:other/9"])

    assert isinstance(past, Unwritten)
    assert isinstance(off, Unwritten)
    assert (
        await world.plans.person_scheduled_tasks(OWNER_PERSON_ID, [OccurrenceState.PENDING]) == ()
    )


async def test_a_step_stating_no_places_carries_its_tasks_places_forward() -> None:
    """§5:6, §13:3: the same work continuing."""
    world = _World()
    step = activation()
    carried = (f"conversation:{CHAT.instance_id}", f"telegram:{LINE.instance_id}")

    spawned = await _spawn(world, _spawner(step, set_in=SCHEDULE, places=(), carried=carried))

    assert isinstance(spawned, ToolResult)
    listing = decode_listing(spawned.output)
    assert listing is not None
    assert listing.spawned is not None
    assert listing.spawned.places == carried


async def test_a_cancel_without_the_persons_authority_names_only_its_own_spawn() -> None:
    """§4:4: refused as not done, with the reason, and writes nothing."""
    world = _World()
    task = await write_task(world.plans, activation(), when=DueAt(at=AT + timedelta(hours=1)))

    with spawning(_spawner(activation(), users_authority=False)):
        refused = await world.calls.run(_call(CANCEL_TASK, {"task": task.id}))
    with spawning(_spawner(activation())):
        done = await world.calls.run(_call(CANCEL_TASK, {"task": task.id}))

    assert isinstance(refused, NotDone)
    assert isinstance(done, ToolResult)
    assert done.outcome is ToolOutcome.SUCCEEDED
    assert await world.held(task.id) is None


async def test_the_list_pull_shows_each_pending_task_with_its_parent() -> None:
    """§4:6: so planning can tell which belong together."""
    world = _World()
    parent = activation()
    one = await write_task(world.plans, parent, when=DueAt(at=AT + timedelta(hours=1)))
    other = await write_task(world.plans, parent, when=DueAt(at=AT + timedelta(hours=2)))

    with spawning(_spawner(activation())):
        answer = await world.calls.run(_call(LIST_TASKS, {}))

    assert isinstance(answer, ToolResult)
    listing = decode_listing(answer.output)
    assert listing is not None
    assert listing.listed
    assert [(entry.task_id, entry.parent) for entry in listing.scheduled] == [
        (one.id, parent),
        (other.id, parent),
    ]
    assert "the person's message" in listing.scheduled[0].parent_text


async def test_a_call_with_no_spawner_is_not_done() -> None:
    """§3:4: offered only to an activation offered spawn."""
    world = _World()

    assert isinstance(await world.calls.run(_call(LIST_TASKS, {})), NotDone)
    refused = await world.calls.run_claiming(
        _call(SPAWN, {"instruction": "x"}),
        spawn_effect(activation()),
        match=None,
        deliberate_repeat=False,
    )
    assert isinstance(refused, Unwritten)


# --- the place list (§5:8-§5:11) ------------------------------------------------------------


async def test_a_task_suggesting_two_places_one_deleted_still_lists_the_other() -> None:
    """§5:8, §13:3."""
    conversations = FakeConversationStore(now=lambda: AT)
    kept = await conversations.start()
    gone = await conversations.start()
    await conversations.stamp_deleted(gone.id)
    lists = PlaceLists(conversations=conversations)

    shown = await lists.shown(
        input_place=None,
        suggested=[f"conversation:{gone.id}", f"conversation:{kept.id}"],
    )

    assert [(one.place, one.suggested) for one in shown] == [(f"conversation:{kept.id}", True)]


async def test_a_deleted_conversation_leaves_the_line_or_nothing() -> None:
    """§5:9, §13:3: nothing is cancelled; the line is the fallback, and with none, nothing."""
    conversations = FakeConversationStore(now=lambda: AT)
    gone = await conversations.start()
    await conversations.stamp_deleted(gone.id)
    suggested = [f"conversation:{gone.id}"]

    with_line = await PlaceLists(conversations=conversations, line=LINE).shown(
        input_place=None, suggested=suggested
    )
    without = await PlaceLists(conversations=conversations).shown(
        input_place=None, suggested=suggested
    )

    assert [(one.place, one.suggested) for one in with_line] == [
        (f"telegram:{LINE.instance_id}", False)
    ]
    assert without == ()


async def test_an_activation_not_a_tasks_lists_its_input_conversation_and_the_line() -> None:
    """§5:11: the conversation its input came from, and the line's chat where connected."""
    conversations = FakeConversationStore(now=lambda: AT)
    here = await conversations.start()
    channel = CHAT.model_copy(update={"instance_id": here.id})

    async def disconnected() -> bool:
        return False

    shown = await PlaceLists(conversations=conversations, line=LINE).shown(
        input_place=channel, suggested=None
    )
    no_line = await PlaceLists(
        conversations=conversations, line=LINE, line_connected=disconnected
    ).shown(input_place=channel, suggested=None)

    assert [one.heading for one in shown] == ["The hub's chat", "Telegram"]
    assert [one.place for one in no_line] == [f"conversation:{here.id}"]


async def test_a_cancel_and_a_push_racing_are_decided_by_whichever_lands_first() -> None:
    """§7:5, §13:3: totally ordered in the store; the loser writes nothing."""
    world = _World()
    cancelled_first = await write_task(world.plans, activation())
    pushed_first = await write_task(world.plans, activation())

    await world.manager.cancel(cancelled_first.id)
    late_push = await world.plans.mark_occurrence_pushed(cancelled_first.id, 1, activation())
    started = await pushed(world.plans, pushed_first)
    late_cancel = await world.manager.cancel(pushed_first.id)

    assert late_push.value == "not_pending"
    assert late_cancel.task is None
    assert late_cancel.reason is not None
    assert late_cancel.reason.value == "nothing_pending"
    (held,) = await world.plans.scheduled_tasks([pushed_first.id])
    assert held.occurrences[0].pushed_to == started


async def test_overlapping_waits_are_all_removed_whichever_order_the_walk_meets_them() -> None:
    """§7:8: a task kept by one waiting on it is removed once that one is, in one walk."""
    for order in ((0, 1), (1, 0)):
        world = _World()
        parent = activation()
        first = await write_task(world.plans, parent)
        await world.plans.settle_occurrence(await pushed(world.plans, first), OccurrenceState.DONE)
        second = await write_task(world.plans, parent, when=DueAfterTasks(tasks=(first.id,)))
        await world.plans.settle_occurrence(await pushed(world.plans, second), OccurrenceState.DONE)
        waits = (second.id, first.id)
        gather = await write_task(
            world.plans, parent, when=DueAfterTasks(tasks=(waits[order[0]], waits[order[1]]))
        )
        await world.plans.settle_occurrence(await pushed(world.plans, gather), OccurrenceState.DONE)

        await world.manager.tidy([gather.id])

        assert (await world.plans.export()).scheduled_tasks == ()


class _GetFails(FakeConversationStore):
    """A conversation store whose reads of a conversation fail."""

    async def get(self, conversation_id: str) -> Conversation | None:
        msg = "the conversation store is busy"
        raise ConversationStoreError(msg)


async def test_a_conversation_that_cannot_be_read_stays_on_the_list() -> None:
    """§5:8: a failed read is no answer that the conversation was deleted."""
    conversations = _GetFails(now=lambda: AT)

    shown = await PlaceLists(conversations=conversations).shown(
        input_place=None, suggested=["conversation:c-9"]
    )

    assert [(one.place, one.suggested) for one in shown] == [("conversation:c-9", True)]


# --- a replaced task's parent, and where an ended step spoke (#3449, #3445) ---------------


async def _listing(world: _World) -> TaskListing:
    with spawning(_spawner(activation())):
        answer = await world.calls.run(_call(LIST_TASKS, {}))
    assert isinstance(answer, ToolResult)
    listing = decode_listing(answer.output)
    assert listing is not None
    return listing


async def test_a_replaced_task_is_described_by_the_parent_it_inherited() -> None:
    """§4:6, §9:4: the parent is the replaced task's, so its words are that parent's."""
    world = _World()
    step = activation()
    await world.memory.add(schedule_episode(step))
    task = await write_task(
        world.plans, step, when=DueAt(at=AT + timedelta(hours=3)), set_in=SCHEDULE
    )
    replacer = activation()

    answer = await _spawn(world, _spawner(replacer), replaces=task.id, delay_minutes=120)

    assert isinstance(answer, ToolResult)
    spawned = decode_listing(answer.output)
    assert spawned is not None
    assert spawned.spawned is not None
    assert spawned.spawned.parent == step
    assert spawned.spawned.parent_text.startswith("spawned by a scheduled step")
    (listed,) = (await _listing(world)).scheduled
    assert listed.parent == step
    assert listed.parent_text == spawned.spawned.parent_text


async def test_a_parents_words_tell_its_own_time_not_the_replacing_spawns() -> None:
    """§4:6: "spawned by your message on Monday", the message the parent began with."""
    world = _World()
    parent = activation()
    began = AT - timedelta(days=2)
    await world.memory.add(
        conversation_episode(CHAT.instance_id, f"activation:{parent}", occurred_at=began)
    )
    task = await write_task(world.plans, parent, when=DueAt(at=AT + timedelta(hours=3)))

    await _spawn(world, _spawner(activation()), replaces=task.id, delay_minutes=120)

    (listed,) = (await _listing(world)).scheduled
    assert listed.parent == parent
    assert listed.parent_text == (
        "spawned by the person's message in a conversation in the hub's chat, "
        "Tue 30 Dec 2025 00:00 (UTC)"
    )


class _EffectsUnread(FakePlanStore):
    """A plan store whose effect records cannot be read."""

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        del activation_ids
        msg = "the plan store is busy"
        raise PlanningError(msg)


async def test_an_ended_step_says_where_its_messages_went_or_that_it_wrote_none() -> None:
    """#3445, ADR-0350 §12:8: from the effect records, done, not known, or none."""
    world = _World()
    line, unknown, silent = activation(), activation(), activation()
    for one in (line, unknown, silent):
        await world.memory.add(schedule_episode(one))
    await message(world.plans, line, LINE, outcome=ToolOutcome.SUCCEEDED, position=3)
    await message(world.plans, unknown, CHAT, outcome=ToolOutcome.FAILED)
    await message(world.plans, unknown, LINE, outcome=ToolOutcome.INDETERMINATE)
    await message(world.plans, silent, CHAT, outcome=ToolOutcome.FAILED)

    ended = {one.activation_id: one for one in (await _listing(world)).recent}

    line_place = f"telegram:{LINE.instance_id}"
    assert (ended[line].wrote_into, ended[line].may_have_written_into) == ((line_place,), ())
    assert (ended[unknown].wrote_into, ended[unknown].may_have_written_into) == (
        (),
        (line_place,),
    )
    assert (ended[silent].wrote_into, ended[silent].may_have_written_into) == ((), ())


async def test_where_ended_steps_spoke_is_left_unsaid_where_the_records_cannot_be_read() -> None:
    """#3445: an unread record is no answer that a step wrote nothing."""
    world = _World(plans=_EffectsUnread(now=lambda: AT))
    step = activation()
    await world.memory.add(schedule_episode(step))

    (entry,) = (await _listing(world)).recent

    assert entry.activation_id == step
    assert entry.wrote_into is None


def test_where_a_step_spoke_survives_the_listings_encoding_and_an_older_one_reads_as_unsaid() -> (
    None
):
    """#3445: a listing recorded before the fields decodes with nothing said of them."""
    entry = ActivationEntry(
        activation_id="step",
        started="Mon 26 Oct 2026 00:32 (UTC)",
        place="a scheduled step, started by the Task Scheduler",
        status="completed (returned)",
        input=None,
        outside=False,
        wrote_into=("telegram:ref/42",),
        may_have_written_into=("conversation:c-1",),
    )
    encoded = encode_listing(TaskListing(recent=(entry,), listed=True))
    assert decode_listing(encoded) == TaskListing(recent=(entry,), listed=True)

    assert isinstance(encoded, dict)
    older = dict(encoded)
    recent = [dict(one) for one in older["recent"]]
    for one in recent:
        del one["wrote_into"], one["may_have_written_into"]
    older["recent"] = recent
    decoded = decode_listing(older)
    assert decoded is not None
    (old,) = decoded.recent
    assert (old.wrote_into, old.may_have_written_into) == (None, ())
