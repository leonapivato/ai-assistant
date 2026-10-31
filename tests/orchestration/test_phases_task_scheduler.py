"""The Task Scheduler on the engine: a spawn, the activation it starts, and the stop (ADR-0350).

Each case drives the engine with the phases wired and the Task Scheduler beside them, over
the canonical fakes, with planning answered by a responder that reads the rendered
request as planning's model would: by the labels it was shown.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from phases_support import open_conversation, phases_harness, said, until, working, written
from task_support import AT, activation, seams, spawn_effect, write_task
from telegram_support import CHAT as LINE_CHAT
from telegram_support import REFERENCE, YieldingTelegram
from understanding_support import understanding_stage

from ai_assistant.core.errors import ModelError, PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationStop,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    EpisodicMemory,
    MessageAuthor,
    OccurrenceState,
    ProcessingStatus,
    ProposedCall,
    RoundResponse,
    ScheduledTaskAuthor,
    TaskSpawn,
    parties_are_outside,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.orchestration.task_manager import PlaceLists
from ai_assistant.orchestration.task_scheduler import SCHEDULE, TASK_SCHEDULER_DESCRIPTION
from ai_assistant.orchestration.telegram import TelegramLineSeams
from ai_assistant.testing import (
    FakeModelProvider,
    FakePlanStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from test_engine import Harness

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import (
        Conversation,
        OfferedTool,
        PlanningExchange,
        ScheduledTask,
    )
    from ai_assistant.testing import FakeConversationStore


def _request(exchange: PlanningExchange) -> dict[str, Any]:
    """The round's rendered request, as planning's model reads it."""
    loaded: dict[str, Any] = json.loads(exchange.briefing)
    return loaded


def _started_by_a_task(request: dict[str, Any]) -> bool:
    return bool(request["place"].get("description") == TASK_SCHEDULER_DESCRIPTION)


def _first_place(request: dict[str, Any]) -> str:
    """The first place label on the place list."""
    return str(request["places"][0]["places"][0]["label"])


def _responder(
    person: Callable[[dict[str, Any]], RoundResponse],
    task: Callable[[dict[str, Any]], RoundResponse],
) -> FakeToolCallingCompleter:
    def respond(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        request = _request(exchange)
        return task(request) if _started_by_a_task(request) else person(request)

    return FakeToolCallingCompleter(response=respond)


def _spawning(**arguments: object) -> Callable[[dict[str, Any]], RoundResponse]:
    """A person's activation that spawns in its first round and then says nothing."""

    def person(request: dict[str, Any]) -> RoundResponse:
        if request["rounds"]:
            return RoundResponse(text="")
        named: dict[str, Any] = {
            key: [_first_place(request)] if value == "first place" else value
            for key, value in arguments.items()
        }
        return RoundResponse(
            calls=(
                ProposedCall(
                    call_id="spawn-1",
                    name="spawn",
                    arguments={"instruction": "say hello", **named},
                ),
            )
        )

    return person


def _silent(_request: dict[str, Any]) -> RoundResponse:
    return RoundResponse(text="")


async def _schedule_episodes(harness: Harness) -> list[EpisodicMemory]:
    """The frozen episodes of the activations the Task Scheduler started."""
    page = await harness.memory.channel_episodes(SCHEDULE, limit=100)
    return [one.record for one in page.entries]


async def _until_scheduled(harness: Harness, count: int) -> list[EpisodicMemory]:
    async def done() -> bool:
        return len(await _schedule_episodes(harness)) >= count

    await until(done, what=f"{count} scheduled activation(s)")
    return await _schedule_episodes(harness)


async def _until_no_tasks(harness: Harness) -> None:
    async def done() -> bool:
        return (await harness.plans.export()).scheduled_tasks == ()

    await until(done, what="the Task Scheduler to hold no task")


async def test_a_spawn_to_start_now_starts_an_activation_that_speaks_where_it_names() -> None:
    """§3:2, §6:7: every spawn goes through the Task Scheduler, now included."""
    completer = _responder(
        _spawning(places="first place"),
        lambda request: RoundResponse(text=f"{_first_place(request)}: hello from the schedule"),
    )
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        (episode,) = await _until_scheduled(harness, 1)

        async def spoken() -> bool:
            return any(
                one.author is MessageAuthor.ASSISTANT and one.text == "hello from the schedule"
                for one in await written(harness, conversation)
            )

        await until(spoken, what="the task's message")
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.COMPLETED
        # §12:8: the round records the place its message went into, its label stripped.
        (round_,) = episode.processing_record.rounds
        assert round_.text == "hello from the schedule"
        assert round_.place == ChannelIdentity(
            channel_type="conversation", instance_id=conversation
        )
        # §12:9: the transcript records the message with the claim it was written under.
        (claim,) = await harness.plans.activation_effects([episode.processing_record.activation_id])
        assert claim.position is not None
        assert await harness.conversation_store.effect_position(conversation, claim.id) == (
            claim.position
        )
        # §7:8: once its occurrence settled and its parent ended, it is removed.
        await _until_no_tasks(harness)
    finally:
        await harness.engine.aclose()


async def test_a_message_naming_a_place_off_its_list_is_refused() -> None:
    """§6:7, §13:3: refused by authorizing; *couldn't finish* goes to its suggested place."""
    completer = _responder(
        _spawning(places="first place"),
        lambda _request: RoundResponse(text="L9: somewhere else"),
    )
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        await _until_scheduled(harness, 1)

        async def told() -> bool:
            return any(one.text == COULDNT_FINISH for one in await written(harness, conversation))

        await until(told, what="the task's couldn't finish")
        texts = [one.text for one in await written(harness, conversation)]
        assert not any("somewhere else" in one for one in texts)
    finally:
        await harness.engine.aclose()


async def test_two_occurrences_due_at_one_instant_start_two_activations() -> None:
    """§7:4, §13:3."""
    harness = phases_harness(_responder(_silent, _silent), task_scheduler=seams())
    await write_task(harness.plans, activation(), when=DueAt(at=AT))
    await write_task(harness.plans, activation(), when=DueAt(at=AT))
    await harness.engine.start()
    try:
        found = await _until_scheduled(harness, 2)
        assert len({one.id for one in found}) == 2
    finally:
        await harness.engine.aclose()


async def test_a_deleted_conversation_cancels_nothing_and_with_no_line_nothing_is_written() -> None:
    """§5:8-§5:9, §13:3: the occurrence still runs, and its empty list writes nothing."""
    spoken: list[dict[str, Any]] = []

    def task(request: dict[str, Any]) -> RoundResponse:
        spoken.append(request)
        return RoundResponse(text="L1: hello")

    harness = phases_harness(_responder(_silent, task), task_scheduler=seams())
    gone = await harness.conversation_store.start()
    place = ChannelIdentity(channel_type="conversation", instance_id=gone.id)
    await write_task(harness.plans, activation(), places=(place,))
    await harness.conversation_store.stamp_deleted(gone.id)
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.COMPLETED
        (request,) = spoken
        assert request["places"] == []
        assert request["place"]["takes_message"] is False
    finally:
        await harness.engine.aclose()


class _DeletedWhilePlanning:
    """The chat space as the place list reads it: its conversation is deleted once planning
    has written the round's message, at the next read, so the list built for the round
    still held it."""

    def __init__(self, store: FakeConversationStore, conversation_id: str) -> None:
        self._store = store
        self._id = conversation_id
        self.planned = False

    async def get(self, conversation_id: str) -> Conversation | None:
        if self.planned and conversation_id == self._id:
            await self._store.stamp_deleted(self._id)
        return await self._store.get(conversation_id)


async def test_a_message_to_a_place_deleted_after_its_list_was_built_is_refused_by_rule() -> None:
    """§5:9, §6:7, #3448: authorizing refuses it, so no message of the round is claimed."""
    space: list[_DeletedWhilePlanning] = []

    def task(request: dict[str, Any]) -> RoundResponse:
        space[0].planned = True
        return RoundResponse(text=f"{_first_place(request)}: time to move the car")

    harness = phases_harness(_responder(_silent, task), task_scheduler=seams())
    gone = await harness.conversation_store.start()
    space.append(_DeletedWhilePlanning(harness.conversation_store, gone.id))
    harness.engine._place_lists = PlaceLists(conversations=cast("ConversationStore", space[0]))
    place = ChannelIdentity(channel_type="conversation", instance_id=gone.id)
    await write_task(harness.plans, activation(), places=(place,))
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        record = episode.processing_record
        assert record is not None
        (round_,) = record.rounds
        assert round_.place == place
        effects = await harness.plans.activation_effects([record.activation_id])
        assert [one for one in effects if not one.is_call and one.round is not None] == []
    finally:
        await harness.engine.aclose()


class _HeldAdmission(FakePlanStore):
    """A plan store whose admission read is held right after the pushed write (§9:10)."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.asked: list[str] = []

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        if not self.entered.is_set():
            self.asked.extend(activation_ids)
            self.entered.set()
            await self.release.wait()
        return await super().stopped_activations(activation_ids)


async def test_a_stop_of_a_pushed_id_with_admission_held_starts_nothing() -> None:
    """§9:10, §13:3: a stop of a pushed id answers stopped, and nothing then starts."""
    plans = _HeldAdmission()
    harness = phases_harness(_responder(_silent, _silent), task_scheduler=seams(), plans=plans)
    task = await write_task(plans, activation())
    await harness.engine.start()
    try:
        await asyncio.wait_for(plans.entered.wait(), 5)
        (pushed_id,) = plans.asked

        assert await harness.engine.stop_activation(pushed_id) is ActivationStop.STOPPED
        plans.release.set()

        async def ended() -> bool:
            held = await plans.scheduled_tasks([task.id])
            return not held or held[0].occurrences[0].state is OccurrenceState.STOPPED

        await until(ended, what="the occurrence to end stopped")
        assert await harness.memory.get(f"activation:{pushed_id}") is None
        assert await _schedule_episodes(harness) == []
    finally:
        await harness.engine.aclose()


class _Clock:
    """A clock a case steps forward, so a task it set comes due without a wait."""

    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> datetime:
        return self.now


async def test_a_stop_command_leaves_what_its_activation_spawned_and_it_still_falls_due() -> None:
    """ADR-0352 §2:1-§2:4, §7:7: the stop cancels nothing below, and the reminder runs."""
    entered = asyncio.Event()
    release = asyncio.Event()
    reminded: list[str] = []

    class _Held(FakeToolCallingCompleter):
        async def respond(
            self, exchange: PlanningExchange, tools: Sequence[OfferedTool], **_: Any
        ) -> RoundResponse:
            request = _request(exchange)
            if _started_by_a_task(request):
                reminded.append("ran")
                return RoundResponse(text="")
            if not request["rounds"]:
                return RoundResponse(
                    calls=(
                        ProposedCall(
                            call_id="spawn-1",
                            name="spawn",
                            arguments={"instruction": "check the notes", "delay_minutes": 40},
                        ),
                    )
                )
            entered.set()
            await release.wait()
            return RoundResponse(text="")

    clock = _Clock()
    harness = phases_harness(_Held(), task_scheduler=seams(), now=clock)
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "remind me"))
        await asyncio.wait_for(entered.wait(), 5)
        running = await working(harness, conversation)
        (reminder,) = (await harness.plans.export()).scheduled_tasks

        assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
        release.set()

        held = await harness.plans.export()
        assert running in held.stopped_activations
        (kept,) = held.scheduled_tasks
        assert kept.id == reminder.id
        assert kept.pending, "the reminder stays pending (§2:4)"

        clock.now = AT + timedelta(minutes=41)

        async def ran() -> bool:
            return bool(reminded)

        await until(ran, what="the reminder to fall due and run")
        await _until_scheduled(harness, 1)
    finally:
        await harness.engine.aclose()


async def test_a_late_occurrence_says_so_in_its_input() -> None:
    """§8:9: pushed however late, and its input says so with the instant it was due."""
    seen: list[str] = []

    def task(request: dict[str, Any]) -> RoundResponse:
        (current,) = [one for one in request["place_window"] if one.get("is_the_input")]
        seen.append(str(current["text"]))
        return RoundResponse(text="")

    harness = phases_harness(_responder(_silent, task), task_scheduler=seams())
    await write_task(harness.plans, activation(), when=DueAt(at=AT - timedelta(hours=3)))
    await harness.engine.start()
    try:
        await _until_scheduled(harness, 1)
        (text,) = seen
        assert "late" in text
        assert "check the listings" in text
    finally:
        await harness.engine.aclose()


class _Unreachable(FakeModelProvider):
    """An understanding model that is down: every completion fails."""

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        msg = "the model is down"
        raise ModelError(msg)


async def test_a_failure_before_planning_still_writes_couldnt_finish_where_suggested() -> None:
    """§5:8, §6:7: the list is built at the start, so *couldn't finish* reaches its place."""
    harness = phases_harness(
        _responder(_silent, _silent),
        task_scheduler=seams(),
        understanding=understanding_stage(model=_Unreachable()),
    )
    conversation = await harness.conversation_store.start()
    place = ChannelIdentity(channel_type="conversation", instance_id=conversation.id)
    await write_task(harness.plans, activation(), places=(place,))
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.FAILED

        async def told() -> bool:
            messages = await written(harness, conversation.id)
            return any(one.text == COULDNT_FINISH for one in messages)

        await until(told, what="couldn't finish in the suggested conversation")
    finally:
        await harness.engine.aclose()


class _AdmissionReadFailsOnce(FakePlanStore):
    """A plan store whose first admission read fails, after the pushed mark landed."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.failed = False

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        if not self.failed:
            self.failed = True
            msg = "the plan store is busy"
            raise PlanningError(msg)
        return await super().stopped_activations(activation_ids)


async def test_a_push_whose_admission_read_failed_is_settled_and_pushed_again() -> None:
    """§8:1, §8:5: an occurrence a store failure left pushed and running nowhere."""
    plans = _AdmissionReadFailsOnce()
    harness = phases_harness(_responder(_silent, _silent), task_scheduler=seams(), plans=plans)
    task = await write_task(plans, activation())
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        assert plans.failed
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.COMPLETED

        async def done() -> bool:
            held = await plans.scheduled_tasks([task.id])
            return not held or held[0].occurrences[0].state is OccurrenceState.DONE

        await until(done, what="the occurrence to end done")
    finally:
        await harness.engine.aclose()


async def test_an_outside_marked_tasks_text_is_withheld_from_planning() -> None:
    """ADR-0307 §9:2, ADR-0350 §6:3: its input is outside content, read by understanding."""
    seen: list[dict[str, Any]] = []

    def task(request: dict[str, Any]) -> RoundResponse:
        seen.append(request)
        return RoundResponse(text="")

    harness = phases_harness(_responder(_silent, task), task_scheduler=seams())
    parent = activation()
    spawned = await harness.plans.write_scheduled_task(
        TaskSpawn(
            id="task:marked",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.ASSISTANT,
            when=DueNow(),
            instruction="forward the parcel number",
            set_in=ChannelIdentity(channel_type="conversation", instance_id="c-1"),
            set_at=AT,
            outside_content=True,
        ),
        spawn_effect(parent),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert spawned.task is not None
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        assert episode.processing_record is not None
        assert parties_are_outside(episode.processing_record.trigger.parties)
        (request,) = seen
        assert "parcel number" not in json.dumps(request)
    finally:
        await harness.engine.aclose()


async def test_a_task_whose_conversation_was_deleted_speaks_on_the_line() -> None:
    """§5:8-§5:9, §13:3: nothing is cancelled, and the line is the fallback."""
    fake = FakeTelegramBotClient(chat_id=LINE_CHAT, first_message_id=700)
    line = TelegramLineSeams(
        client=YieldingTelegram(fake),
        intake=FakeTelegramIntakeRecord(),
        reference=REFERENCE,
        poll_wait=timedelta(seconds=1),
        poll_bound=timedelta(seconds=2),
        send_bound=timedelta(seconds=1),
        start_wait=timedelta(milliseconds=5),
    )
    harness = phases_harness(
        _responder(
            _silent, lambda request: RoundResponse(text=f"{_first_place(request)}: time to call")
        ),
        task_scheduler=seams(),
        telegram=line,
    )
    # The harness's connection records hold no account, so the line is read as connected
    # wherever it is configured, as its own suite drives it.
    harness.engine._place_lists = PlaceLists(
        conversations=harness.conversation_store, line=line.channel
    )
    gone = await harness.conversation_store.start()
    place = ChannelIdentity(channel_type="conversation", instance_id=gone.id)
    task = await write_task(harness.plans, activation(), places=(place,))
    await harness.conversation_store.stamp_deleted(gone.id)
    await harness.engine.start()
    try:
        await _until_scheduled(harness, 1)

        async def spoken() -> bool:
            return any(body == "time to call" for _, body in fake.messages)

        await until(spoken, what="the task's message on the line")

        async def done() -> bool:
            held = await harness.plans.scheduled_tasks([task.id])
            return not held or held[0].occurrences[0].state is OccurrenceState.DONE

        await until(done, what="the occurrence to end done")
    finally:
        await harness.engine.aclose()


class _OutcomeWriteFailsOnce(FakePlanStore):
    """A plan store whose first write of an occurrence's outcome fails."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.failed = False

    async def settle_occurrence(
        self, activation_id: str, state: OccurrenceState, /, *, second_try: bool = False
    ) -> ScheduledTask:
        if not self.failed and state is not OccurrenceState.PENDING:
            self.failed = True
            msg = "the plan store is busy"
            raise PlanningError(msg)
        return await super().settle_occurrence(activation_id, state, second_try=second_try)


async def test_an_outcome_the_store_failed_to_take_is_settled_and_what_waits_runs() -> None:
    """§7:6-§7:7: a task waiting on one whose outcome write failed still falls due."""
    plans = _OutcomeWriteFailsOnce()
    harness = phases_harness(_responder(_silent, _silent), task_scheduler=seams(), plans=plans)
    parent = activation()
    first = await write_task(plans, parent, instruction="the first step")
    await write_task(
        plans, parent, when=DueAfterTasks(tasks=(first.id,)), instruction="the gathering step"
    )
    await harness.engine.start()
    try:
        await _until_scheduled(harness, 2)
        assert plans.failed
        await _until_no_tasks(harness)
    finally:
        await harness.engine.aclose()


async def test_a_child_that_ends_before_its_scheduled_parent_is_removed_with_it() -> None:
    """§7:8: once the parent ends, nothing of it or below it is live, so all are removed."""
    child_done = asyncio.Event()

    class _Parent(FakeToolCallingCompleter):
        async def respond(
            self, exchange: PlanningExchange, tools: Sequence[OfferedTool], **_: Any
        ) -> RoundResponse:
            request = _request(exchange)
            window = json.dumps(request["place_window"])
            if "the child step" in window:
                child_done.set()
                return RoundResponse(text="")
            if not request["rounds"]:
                spawn = ProposedCall(
                    call_id="spawn-1",
                    name="spawn",
                    arguments={"instruction": "the child step"},
                )
                return RoundResponse(calls=(spawn,))
            # The parent's next round runs on until its child has ended.
            await asyncio.wait_for(child_done.wait(), 5)
            for _attempt in range(500):
                if len(await _schedule_episodes(harness)) >= 1:
                    break
                await asyncio.sleep(0.002)
            return RoundResponse(text="")

    harness = phases_harness(_Parent(), task_scheduler=seams())
    await write_task(harness.plans, activation(), instruction="the parent step")
    await harness.engine.start()
    try:
        await _until_scheduled(harness, 2)
        await _until_no_tasks(harness)
    finally:
        await harness.engine.aclose()


async def test_a_known_outcome_the_store_failed_to_take_is_written_as_decided() -> None:
    """§7:6: a step that spawned its next and completed ends done, never interrupted."""

    def step(request: dict[str, Any]) -> RoundResponse:
        if request["rounds"]:
            return RoundResponse(text="")
        spawn = ProposedCall(
            call_id="spawn-1",
            name="spawn",
            arguments={"instruction": "the next step", "delay_minutes": 1440},
        )
        return RoundResponse(calls=(spawn,))

    plans = _OutcomeWriteFailsOnce()
    harness = phases_harness(_responder(_silent, step), task_scheduler=seams(), plans=plans)
    first = await write_task(plans, activation(), instruction="the first step")
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.COMPLETED

        async def settled() -> bool:
            held = await plans.scheduled_tasks([first.id])
            return bool(held) and held[0].occurrences[0].state is OccurrenceState.DONE

        await until(settled, what="the first step to end done")
        assert plans.failed
        (following,) = [one for one in (await plans.export()).scheduled_tasks if one.id != first.id]
        assert following.pending
    finally:
        await harness.engine.aclose()


class _OutcomeWriteHeld(FakePlanStore):
    """A plan store that fails every outcome write until a case lets it through."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.refusing = True
        self.refused = asyncio.Event()

    async def settle_occurrence(
        self, activation_id: str, state: OccurrenceState, /, *, second_try: bool = False
    ) -> ScheduledTask:
        if self.refusing and state is not OccurrenceState.PENDING:
            self.refused.set()
            msg = "the plan store is busy"
            raise PlanningError(msg)
        return await super().settle_occurrence(activation_id, state, second_try=second_try)


async def test_a_stop_of_an_ended_activation_awaiting_its_outcome_changes_nothing() -> None:
    """ADR-0295 §1:6, ADR-0350 §9:6: no cascade record, and its pending child is kept."""

    def step(request: dict[str, Any]) -> RoundResponse:
        if request["rounds"]:
            return RoundResponse(text="")
        spawn = ProposedCall(
            call_id="spawn-1",
            name="spawn",
            arguments={"instruction": "the next step", "delay_minutes": 1440},
        )
        return RoundResponse(calls=(spawn,))

    plans = _OutcomeWriteHeld()
    harness = phases_harness(_responder(_silent, step), task_scheduler=seams(), plans=plans)
    first = await write_task(plans, activation(), instruction="the first step")
    await harness.engine.start()
    try:
        (episode,) = await _until_scheduled(harness, 1)
        await asyncio.wait_for(plans.refused.wait(), 5)
        assert episode.processing_record is not None
        ended = episode.processing_record.activation_id

        assert await harness.engine.stop_activation(ended) is ActivationStop.ALREADY_ENDED

        held = await plans.export()
        assert ended not in held.stopped_activations
        (following,) = [one for one in held.scheduled_tasks if one.id != first.id]
        assert following.pending
        plans.refusing = False

        async def settled() -> bool:
            found = await plans.scheduled_tasks([first.id])
            return bool(found) and found[0].occurrences[0].state is OccurrenceState.DONE

        await until(settled, what="the first step to end done")
    finally:
        await harness.engine.aclose()


# --- ADR-0352 §2: a step stopped while it writes its next one --------------------------


class _SpawnHeld(FakePlanStore):
    """A plan store that holds a spawn's write before it reaches the store, until released."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.holding = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def write_scheduled_task(self, *args: Any, **kwargs: Any) -> Any:
        if self.holding:
            self.entered.set()
            await self.release.wait()
        return await super().write_scheduled_task(*args, **kwargs)


class _Step(FakeToolCallingCompleter):
    """A scheduled step that spawns its next step in its first round.

    Its second round waits on :attr:`release` once :attr:`entered` is set, so a case can
    stop it after its next step's write has landed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def respond(
        self, exchange: PlanningExchange, tools: Sequence[OfferedTool], **_: Any
    ) -> RoundResponse:
        request = _request(exchange)
        if not request["rounds"]:
            return RoundResponse(
                calls=(
                    ProposedCall(
                        call_id="spawn-1",
                        name="spawn",
                        arguments={"instruction": "the next step", "delay_minutes": 60},
                    ),
                )
            )
        self.entered.set()
        await self.release.wait()
        return RoundResponse(text="")


async def _pushed_to(plans: FakePlanStore, task: ScheduledTask) -> str:
    async def pushed() -> bool:
        (held,) = await plans.scheduled_tasks([task.id])
        return held.occurrences[0].pushed_to is not None

    await until(pushed, what="the first step to be pushed")
    (held,) = await plans.scheduled_tasks([task.id])
    activation_id = held.occurrences[0].pushed_to
    assert activation_id is not None
    return activation_id


async def test_a_step_stopped_before_its_next_steps_write_lands_writes_no_next_step() -> None:
    """ADR-0352 §2 (ADR-0350 §3:3), §7:7: the stop record first, so the spawn is refused."""
    plans = _SpawnHeld()
    step = _Step()
    harness = phases_harness(step, task_scheduler=seams(), plans=plans)
    first = await write_task(plans, activation(), instruction="the first step")
    plans.holding = True
    await harness.engine.start()
    try:
        await asyncio.wait_for(plans.entered.wait(), 5)
        running = await _pushed_to(plans, first)

        assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
        plans.release.set()
        step.release.set()
        (episode,) = await _until_scheduled(harness, 1)

        assert episode.processing_record is not None
        assert episode.processing_record.activation_id == running
        assert await plans.spawned_tasks([running]) == (), "the spawn was refused"
    finally:
        await harness.engine.aclose()


async def test_a_step_stopped_after_its_next_steps_write_landed_leaves_it_pending() -> None:
    """ADR-0352 §2:4, §3:1, §7:7: the next step stays, and what is still live lists it."""
    plans = _SpawnHeld()
    step = _Step()
    harness = phases_harness(step, task_scheduler=seams(), plans=plans)
    first = await write_task(plans, activation(), instruction="the first step")
    await harness.engine.start()
    try:
        await asyncio.wait_for(step.entered.wait(), 5)
        running = await _pushed_to(plans, first)
        (following,) = await plans.spawned_tasks([running])

        assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
        step.release.set()
        await _until_scheduled(harness, 1)

        (kept,) = await plans.spawned_tasks([running])
        assert kept.id == following.id
        assert kept.pending, "a next step whose write landed first stays"
        manager = harness.engine.task_manager
        assert manager is not None
        left = await manager.still_live(running, person=OWNER_PERSON_ID, viewer=None, supply=None)
        assert [one.task_id for one in left.tasks] == [following.id]
    finally:
        await harness.engine.aclose()
