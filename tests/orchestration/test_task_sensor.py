"""The Task Scheduler's sensor: its pushes and the restart's settlement (ADR-0350 §7, §8).

Over the canonical fakes of the plan store, the memory store and the conversation store,
so each case holds the sensor to their contracts. The restart's clauses are §8:1-§8:7,
the first that applies deciding, after the confirmation §8:11 makes of each message.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from task_support import (
    AT,
    CHAT,
    LINE,
    activation,
    message,
    pushed,
    schedule_episode,
    spawn_effect,
    write_task,
)

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    DueAt,
    MessageAuthor,
    NewMessage,
    OccurrenceState,
    ProcessingReason,
    ProcessingStatus,
    ScheduledOccurrence,
    ToolOutcome,
)
from ai_assistant.orchestration.task_sensor import (
    SensorLimits,
    TaskSchedulerSensor,
    restart_outcome,
)
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import DueOccurrence, ScheduledTask


def _occurrence(*, pushes: int = 1, second_try: bool = False) -> ScheduledOccurrence:
    return ScheduledOccurrence(
        number=1,
        due_at=AT,
        state=OccurrenceState.PUSHED,
        activations=tuple(activation() for _ in range(pushes)),
        second_try=second_try,
    )


class _World:
    """A sensor over the three fakes, recording what it pushed and what it settled."""

    def __init__(self, *, running: frozenset[str] = frozenset()) -> None:
        self.plans = FakePlanStore(now=lambda: AT)
        self.memory = FakeMemoryStore(now=lambda: AT)
        self.conversations = FakeConversationStore(now=lambda: AT)
        self.pushes: list[DueOccurrence] = []
        self.settled: list[ScheduledTask] = []
        self.running = running
        self.sensor = TaskSchedulerSensor(
            plans=self.plans,
            memory=self.memory,
            conversations=self.conversations,
            push=self._push,
            is_running=lambda one: one in self.running,
            settled=self._settled,
            closing=lambda: False,
            persons=(OWNER_PERSON_ID,),
            limits=SensorLimits(recheck=timedelta(seconds=30), push_limit=3),
            now=lambda: AT,
        )

    async def _push(self, due: DueOccurrence) -> None:
        self.pushes.append(due)

    async def _settled(self, task: ScheduledTask) -> None:
        self.settled.append(task)

    async def state(self, task: ScheduledTask) -> ScheduledOccurrence:
        (held,) = await self.plans.scheduled_tasks([task.id])
        return held.occurrences[0]


# --- §8:2-§8:7, read on their own ----------------------------------------------------------


def test_a_step_that_spawned_its_next_ends_interrupted_whatever_else_holds() -> None:
    """§8:2: a spawn in its effect records, so a chain cannot fork."""
    spawned = spawn_effect(activation())

    assert restart_outcome(_occurrence(), [spawned], None, push_limit=3) == (
        OccurrenceState.INTERRUPTED,
        False,
    )


@pytest.mark.parametrize(
    ("status", "reason", "outcome"),
    [
        (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED, OccurrenceState.DONE),
        (
            ProcessingStatus.FAILED,
            ProcessingReason.PROCESSING_FAILED,
            OccurrenceState.COULDNT_FINISH,
        ),
        (ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED, OccurrenceState.STOPPED),
        (ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED, OccurrenceState.INTERRUPTED),
    ],
)
def test_an_episode_that_froze_gives_its_outcome(
    status: ProcessingStatus, reason: ProcessingReason, outcome: OccurrenceState
) -> None:
    """§8:3: an episode frozen with any ending but the restart's close."""
    episode = schedule_episode(activation(), status=status, reason=reason)

    assert restart_outcome(_occurrence(), [], episode, push_limit=3) == (outcome, False)


def test_the_restarts_close_is_settled_by_what_was_claimed() -> None:
    """§8:3 leaves the restart's close to the clauses after it: pushed again (§8:5)."""
    closed = schedule_episode(
        activation(), status=ProcessingStatus.INTERRUPTED, reason=ProcessingReason.HUB_STOPPED
    )

    assert restart_outcome(_occurrence(), [], closed, push_limit=3) == (
        OccurrenceState.PENDING,
        False,
    )


async def test_a_message_done_ends_it_done() -> None:
    """§8:4."""
    world = _World()
    one = activation()
    done = await message(world.plans, one, CHAT, outcome=ToolOutcome.SUCCEEDED, position=3)

    assert restart_outcome(_occurrence(), [done], None, push_limit=3) == (
        OccurrenceState.DONE,
        False,
    )


async def test_nothing_claimed_or_only_messages_not_done_is_pushed_again_to_the_limit() -> None:
    """§8:5: pushed again, at most the push limit of times in all, then interrupted."""
    world = _World()
    one = activation()
    refused = await message(world.plans, one, CHAT, outcome=ToolOutcome.FAILED)

    assert restart_outcome(_occurrence(pushes=1), [], None, push_limit=3)[0] is (
        OccurrenceState.PENDING
    )
    assert restart_outcome(_occurrence(pushes=2), [refused], None, push_limit=3)[0] is (
        OccurrenceState.PENDING
    )
    assert restart_outcome(_occurrence(pushes=3), [], None, push_limit=3) == (
        OccurrenceState.INTERRUPTED,
        False,
    )


async def test_a_message_of_unknown_outcome_takes_one_second_try() -> None:
    """§8:6: pushed once more, as a second try, which is never tried a third time."""
    world = _World()
    unknown = await message(world.plans, activation(), LINE, outcome=ToolOutcome.INDETERMINATE)
    unwritten = await message(world.plans, activation(), LINE)

    assert restart_outcome(_occurrence(), [unknown], None, push_limit=3) == (
        OccurrenceState.PENDING,
        True,
    )
    assert restart_outcome(_occurrence(), [unwritten], None, push_limit=3) == (
        OccurrenceState.PENDING,
        True,
    )
    assert restart_outcome(_occurrence(second_try=True), [unknown], None, push_limit=3) == (
        OccurrenceState.INTERRUPTED,
        False,
    )


def test_a_second_try_cut_off_before_it_claimed_anything_ends_interrupted() -> None:
    """§13:3: a second try cut off by a second restart before it claimed anything."""
    assert restart_outcome(_occurrence(pushes=2, second_try=True), [], None, push_limit=3) == (
        OccurrenceState.INTERRUPTED,
        False,
    )


def test_a_call_in_the_world_cut_off_is_never_repeated() -> None:
    """§8:7: a call claimed, not a message, ends it interrupted."""
    call = spawn_effect(activation()).model_copy(update={"capability": "book"})

    assert restart_outcome(_occurrence(), [call], None, push_limit=3) == (
        OccurrenceState.INTERRUPTED,
        False,
    )


# --- the restart, against the stores --------------------------------------------------------


async def test_three_restarts_end_interrupted_with_no_fourth_push() -> None:
    """§13:3: two restarts before anything was claimed, a third after a line message."""
    world = _World()
    parent = activation()
    task = await write_task(world.plans, parent, places=(LINE,))
    for restart in range(3):
        cut = await pushed(world.plans, task)
        if restart == 2:
            await message(world.plans, cut, LINE)
        await world.sensor.settle_restart()

    occurrence = await world.state(task)
    assert occurrence.state is OccurrenceState.INTERRUPTED
    assert occurrence.pushes == 3


async def test_a_hub_chat_message_confirmed_recorded_ends_done_with_no_second_try() -> None:
    """§8:11, §13:3: the transcript recorded it, so the record is done and so is it."""
    world = _World()
    conversation = await world.conversations.start()
    place = CHAT.model_copy(update={"instance_id": conversation.id})
    task = await write_task(world.plans, activation(), places=(place,))
    cut = await pushed(world.plans, task)
    claimed = await message(world.plans, cut, place)
    receipt = await world.conversations.append_message(
        conversation.id,
        NewMessage(author=MessageAuthor.ASSISTANT, text="time for the pills", effect_id=claimed.id),
    )

    await world.sensor.settle_restart()

    occurrence = await world.state(task)
    assert occurrence.state is OccurrenceState.DONE
    assert not occurrence.second_try
    (record,) = await world.plans.activation_effects([cut])
    assert (record.outcome, record.position) == (ToolOutcome.SUCCEEDED, receipt.position)


async def test_a_hub_chat_message_confirmed_absent_is_pushed_again_unmarked() -> None:
    """§8:11, §13:3: confirmed not done, so §8:5 pushes it again, no second try."""
    world = _World()
    conversation = await world.conversations.start()
    place = CHAT.model_copy(update={"instance_id": conversation.id})
    task = await write_task(world.plans, activation(), places=(place,))
    cut = await pushed(world.plans, task)
    await message(world.plans, cut, place)

    await world.sensor.settle_restart()

    occurrence = await world.state(task)
    assert occurrence.state is OccurrenceState.PENDING
    assert not occurrence.second_try
    (record,) = await world.plans.activation_effects([cut])
    assert record.outcome is ToolOutcome.FAILED


async def test_a_line_message_of_unknown_outcome_takes_the_second_try() -> None:
    """§8:12, §13:3: the line cannot confirm, so the record is left and it is tried once."""
    world = _World()
    task = await write_task(world.plans, activation(), places=(LINE,))
    cut = await pushed(world.plans, task)
    await message(world.plans, cut, LINE, outcome=ToolOutcome.INDETERMINATE)

    await world.sensor.settle_restart()

    occurrence = await world.state(task)
    assert (occurrence.state, occurrence.second_try) == (OccurrenceState.PENDING, True)
    (record,) = await world.plans.activation_effects([cut])
    assert record.outcome is ToolOutcome.INDETERMINATE


async def test_a_stop_cut_off_by_the_restart_ends_it_stopped_and_pushes_nothing() -> None:
    """§8:1, §13:3: the stop record was written, the episode never froze as stopped."""
    world = _World()
    task = await write_task(world.plans, activation())
    cut = await pushed(world.plans, task)
    await world.plans.record_stop(cut)

    await world.sensor.settle_restart()
    look = await world.sensor.look()

    assert (await world.state(task)).state is OccurrenceState.STOPPED
    assert world.pushes == []
    assert look > 0


async def test_a_step_whose_next_ran_and_was_removed_is_never_pushed_again() -> None:
    """§8:2, §13:3: its spawn's effect record outlives the task it wrote."""
    world = _World()
    task = await write_task(world.plans, activation())
    cut = await pushed(world.plans, task)
    following = await write_task(world.plans, cut)
    ran = await pushed(world.plans, following)
    await world.plans.settle_occurrence(ran, OccurrenceState.DONE)
    assert await world.plans.remove_scheduled_task(following.id)

    await world.sensor.settle_restart()

    assert (await world.state(task)).state is OccurrenceState.INTERRUPTED
    await world.sensor.look()
    assert world.pushes == []


async def test_a_running_activations_occurrence_is_left_to_it() -> None:
    """§8:1 settles only an occurrence whose activation is not running."""
    task_world = _World()
    task = await write_task(task_world.plans, activation())
    cut = await pushed(task_world.plans, task)
    task_world.running = frozenset({cut})

    await task_world.sensor.settle_restart()

    assert (await task_world.state(task)).state is OccurrenceState.PUSHED


# --- the loop's pushes (§7:2-§7:4) ----------------------------------------------------------


async def test_two_occurrences_due_at_one_instant_are_pushed_each_on_its_own() -> None:
    """§7:4, §13:3: the sensor groups nothing."""
    world = _World()
    one = await write_task(world.plans, activation(), when=DueAt(at=AT))
    other = await write_task(world.plans, activation(), when=DueAt(at=AT))

    await world.sensor.look()

    assert [(due.task.id, due.number) for due in world.pushes] == [(one.id, 1), (other.id, 1)]


async def test_the_loop_sleeps_until_the_next_due_instant_within_the_recheck() -> None:
    """§7:2: until the earliest due instant, for no longer than the recheck interval."""
    world = _World()
    await write_task(world.plans, activation(), when=DueAt(at=AT + timedelta(seconds=5)))

    assert await world.sensor.look() == 5.0
    assert world.pushes == []
