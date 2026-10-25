"""The Task Manager, and planning's three calls on the Task Scheduler (ADR-0350 §4, §9, §10).

**The Task Manager** (§10) is the one way in from outside for managing activations and
scheduled tasks: a surface of commands and queries the assistant does not perceive
(ADR-0292 §1:3), not a spoke on a channel. Its queries are what is running, live from the
engine; what is scheduled, from the Task Scheduler; and what ran lately, from the
schedule's episodes (§10:2). Its commands are the stop, with its cascade (§9:6), which is
the one stop ``AssistantEngine.stop_activation`` runs (§10:3); cancel (§9:5); and replace
(§9:4). No operation reaches the local API (§10:6): the engine holds this object, and the
hub chat's stop control and the line's ``/stop`` reach its stop through the engine's.

**Inside, the same operations serve** (§10:4): planning's list pull is its queries, and
planning's cancel and its spawn that replaces a task are its commands under §4:4's checks,
each with one implementation here. :class:`ScheduledTaskCalls` is acting's runner for the
three capabilities, over this one :class:`TaskManager`.

**What keeps the schedule tidy** (§7:8). A task is kept while anything of it or below it
is live, while a task the Task Scheduler holds waits on it, and while its parent still
runs; once none of these holds it is removed. The store decides all but the last, which
is the engine's state: :meth:`TaskManager.tidy` asks the store to remove a task only
where its parent is not running, and walks up from each task removed to the task above it
and to the tasks it waited on, which may now be removable in turn.

**The place list** (§5:10-§5:13). :class:`PlaceLists` builds an activation's list when it
is shown: the line's chat, where the line is connected, and, for an activation the Task
Scheduler started, its task's suggested places that are not gone, marked as suggested;
for every other activation, the conversation its input came from. A conversation is gone
once deleted, and the line's chat once the line is disconnected or the settings name
another chat (§5:8). Nothing is cancelled because a place is gone (§5:9).

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import ConversationStoreError, MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ActivationStop,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    InputOrigin,
    OccurrenceState,
    ScheduledTaskAuthor,
    TaskRefusal,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import Unwritten
from ai_assistant.orchestration.channel_kinds import place_channel, place_of
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.person_block import activation_person
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.task_scheduler import (
    AFTER_ARGUMENT,
    AT_ARGUMENT,
    CANCEL_TASK_CAPABILITY,
    DELAY_ARGUMENT,
    INSTRUCTION_ARGUMENT,
    LIST_TASKS_CAPABILITY,
    PLACES_ARGUMENT,
    REPLACES_ARGUMENT,
    SCHEDULE,
    SPAWN_CAPABILITY,
    TASK_ARGUMENT,
    ActivationEntry,
    ListedPlace,
    Spawner,
    TaskEntry,
    TaskListing,
    current_spawner,
    encode_listing,
    local_time,
    outcome_text,
    place_description,
    when_text,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
    from zoneinfo import ZoneInfo

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ConversationStore, MemoryStore, PlanStore
    from ai_assistant.core.types import (
        FrozenJson,
        ProcessingReason,
        ProcessingStatus,
        ScheduledTask,
        ScheduledTaskCancel,
        ScheduledTaskWrite,
        TaskWhen,
        ToolCall,
    )
    from ai_assistant.orchestration.acting import ClaimingAnswer, OwnRecordsAnswer
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "PlaceLists",
    "ScheduledTaskCalls",
    "TaskManager",
    "TaskManagerLimits",
    "TaskSchedulerSeams",
    "spawn_when",
]

_log = structlog.get_logger(__name__)

#: How much of a text the listing shows of it in brief.
_BRIEF_CHARS: Final = 160

#: The channel headings a place list groups its places under (§5:10).
_HUB_CHAT: Final = "The hub's chat"
_TELEGRAM: Final = "Telegram"

#: The code-owned reasons a call is refused, each as planning is shown it (§4:4-§4:5).
_REFUSAL_TEXT: Final = {
    TaskRefusal.UNKNOWN_TASK: "not done: the Task Scheduler holds no such task",
    TaskRefusal.ANOTHER_PERSONS: "not done: that task is another person's",
    TaskRefusal.NOT_ITS_SPAWN: (
        "not done: this activation may cancel or replace only a task it spawned, since its "
        "input does not carry the person's authority"
    ),
    TaskRefusal.NOTHING_PENDING: "not done: nothing of that task is pending",
    TaskRefusal.INVALID_WAIT: (
        "not done: it waits on a task that is not the person's or not held, or it replaces a "
        "task without waiting on each task that one still waits on"
    ),
    TaskRefusal.CHAIN_LIMIT: "not done: the chain of steps would exceed the chain limit",
    TaskRefusal.PENDING_LIMIT: (
        "not done: it would take the person's pending scheduled tasks past the pending limit"
    ),
}
_NOT_OFFERED: Final = (
    "not done: the Task Scheduler's calls are offered only to a person's activation started "
    "from a conversation, the line or the Task Scheduler"
)
_EARLIER_THAN_NOW: Final = "not done: the instant it would fall due is earlier than now"
_NO_OFFSET: Final = "not done: an instant states its UTC offset, such as 2026-10-25T20:00:00-04:00"
_ONE_WHEN: Final = "not done: give at most one of at, delay_minutes and after"
_OFF_THE_LIST: Final = "not done: it suggests a place that is not on this activation's place list"
_MALFORMED: Final = "not done: the call's arguments are malformed"
_STORE_FAULT: Final = "not done: the Task Scheduler could not be read or written"


def _brief(text: str) -> str:
    """``text`` on one line, cut to :data:`_BRIEF_CHARS`."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _BRIEF_CHARS else f"{flat[: _BRIEF_CHARS - 1]}…"


@dataclass(frozen=True, slots=True)
class TaskManagerLimits:
    """ADR-0350 §12:5's settings the Task Manager reads.

    Attributes:
        chain_limit: The longest chain of steps a spawn may extend (§9:7).
        pending_limit: The most pending occurrences one person may have (§9:8).
        listing_bound: The most items each part of a listing shows (§4:6, §10:2).
    """

    chain_limit: int
    pending_limit: int
    listing_bound: int


class PlaceLists:
    """Build an activation's place list when it is shown (ADR-0350 §5:8, §5:11).

    It reads the conversation store for whether a conversation is gone, and asks
    ``line_connected`` whether the line is connected; the line's chat is the one the
    settings name, or none where no line is configured.
    """

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        line: ChannelIdentity | None = None,
        line_connected: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """Wire the builder.

        Args:
            conversations: The chat space, whose conversations are places.
            line: The line's chat, as the settings name it, or ``None`` with no line.
            line_connected: Whether the line is connected now; ``None`` reads it as
                connected wherever it is configured.
        """
        self._conversations = conversations
        self._line = line
        self._line_connected = line_connected

    async def shown(
        self, *, input_place: ChannelIdentity | None, suggested: Sequence[str] | None
    ) -> tuple[ListedPlace, ...]:
        """The place list, as it stands now.

        Args:
            input_place: The place the activation's input came from.
            suggested: For an activation the Task Scheduler started, its task's suggested
                places; ``None`` for every other activation.

        Returns:
            The places, the hub chat's before the line's, each once.
        """
        places: list[ListedPlace] = []
        if suggested is None:
            if (
                input_place is not None
                and input_place.channel_type == "conversation"
                and await self._held(input_place)
            ):
                places.append(
                    ListedPlace(
                        input_place, _HUB_CHAT, "the conversation this activation's input came from"
                    )
                )
        else:
            for one in dict.fromkeys(suggested):
                channel = place_channel(one)
                if channel is None or channel.channel_type != "conversation":
                    continue
                if await self._held(channel):
                    places.append(
                        ListedPlace(channel, _HUB_CHAT, place_description(channel), suggested=True)
                    )
        line = await self._connected_line()
        if line is not None:
            mark = suggested is not None and place_of(line) in suggested
            input_line = suggested is None and input_place == line
            places.append(
                ListedPlace(
                    line,
                    _TELEGRAM,
                    "the person's Telegram chat with their assistant"
                    + (", where this activation's input came from" if input_line else ""),
                    suggested=mark,
                )
            )
        return tuple(places)

    async def _held(self, channel: ChannelIdentity) -> bool:
        """Whether a conversation is still held: one deleted is gone (§5:8)."""
        try:
            return await self._conversations.get(channel.instance_id) is not None
        except ConversationStoreError:
            _log.warning("place_list_unread", stage="planning", reason="store_failed")
            return False

    async def _connected_line(self) -> ChannelIdentity | None:
        """The line's chat, where the line is connected (§5:11)."""
        if self._line is None:
            return None
        if self._line_connected is None:
            return self._line
        try:
            return self._line if await self._line_connected() else None
        except Exception:  # whether it is connected is not known: it stays listed
            _log.warning("place_list_unread", stage="planning", reason="line_unknown")
            return self._line


def spawn_when(arguments: Mapping[str, FrozenJson], *, now: datetime) -> TaskWhen | str:
    """A spawn's when, from its arguments, or why it is refused (ADR-0350 §5:1-§5:2).

    An instant states its offset, a delay is resolved to an instant now, and a spawn
    naming none falls due now; an instant earlier than now is refused (§4:5).
    """
    stated = [name for name in (AT_ARGUMENT, DELAY_ARGUMENT, AFTER_ARGUMENT) if name in arguments]
    if len(stated) > 1:
        return _ONE_WHEN
    if not stated:
        return DueNow()
    if AT_ARGUMENT in arguments:
        return _instant(arguments[AT_ARGUMENT], now=now)
    if DELAY_ARGUMENT in arguments:
        return _delay(arguments[DELAY_ARGUMENT], now=now)
    return _after(arguments[AFTER_ARGUMENT])


def _instant(text: FrozenJson, *, now: datetime) -> TaskWhen | str:
    """An instant stated with its UTC offset, not earlier than now (§5:2, §4:5)."""
    if not isinstance(text, str):
        return _MALFORMED
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return _MALFORMED
    if at.tzinfo is None or at.utcoffset() is None:
        return _NO_OFFSET
    if at < now:
        return _EARLIER_THAN_NOW
    try:
        return DueAt(at=at)
    except ValueError:
        return _MALFORMED


def _delay(minutes: FrozenJson, *, now: datetime) -> TaskWhen | str:
    """A delay from now, resolved to an instant when the task is set (§5:1)."""
    if isinstance(minutes, bool) or not isinstance(minutes, int | float) or not minutes > 0:
        return _MALFORMED
    try:
        return DueAt(at=now + timedelta(minutes=float(minutes)))
    except OverflowError, ValueError:
        return _MALFORMED


def _after(named: FrozenJson) -> TaskWhen | str:
    """The hub event named tasks ending, by the tasks' ids (§5:4)."""
    if not isinstance(named, list | tuple) or not all(isinstance(one, str) for one in named):
        return _MALFORMED
    try:
        return DueAfterTasks(tasks=tuple(str(one) for one in named))
    except ValueError:
        return _MALFORMED


class TaskManager:
    """The Task Manager's queries and commands, with one implementation each (§10:4).

    The engine builds it over the one plan store, the memory store the schedule's episodes
    are read from, and its own account of what runs; its stop is the engine's.
    """

    def __init__(  # noqa: PLR0913 — the two stores, the engine's three seams, the sensor's wake, the bounds, the zone, the clock and the id source
        self,
        *,
        plans: PlanStore,
        memory: MemoryStore,
        running: Callable[[], Iterable[ActivationState]],
        is_running: Callable[[str], bool],
        stop_one: Callable[[str], Awaitable[ActivationStop]],
        wake: Callable[[], None],
        limits: TaskManagerLimits,
        zone: ZoneInfo,
        now: Clock,
        new_task_id: Callable[[], str] | None = None,
    ) -> None:
        """Wire the Task Manager.

        Args:
            plans: The plan store, which holds the Task Scheduler's content.
            memory: The memory store the schedule's episodes are read from (§7:9).
            running: The activations the engine holds as running.
            is_running: Whether an activation is running, admitted or pushed.
            stop_one: Stops one running or pushed activation, as ``stop_activation``
                does, without the cascade: the cascade's walk stops each it finds.
            wake: Wakes the sensor, which every write to a task does (§7:2).
            limits: §12:5's chain, pending and listing bounds.
            zone: The zone the hub's renderings tell local time in.
            now: The clock a spawn's now is read from.
            new_task_id: Mints a scheduled task's id.
        """
        self._plans = plans
        self._memory = memory
        self._running = running
        self._is_running = is_running
        self._stop_one = stop_one
        self._wake = wake
        self._limits = limits
        self._zone = zone
        self._now = now
        self._new_task_id = new_task_id or (lambda: f"task:{uuid.uuid4().hex}")

    # --- the queries (§10:2) ---

    async def listing(self, spawner: Spawner) -> TaskListing:
        """The list pull: the three queries, for the person ``spawner`` is for (§4:6).

        Raises:
            PlanningError: If the plan store cannot be read.
            MemoryStoreError: If the schedule's episodes cannot be read.
        """
        return TaskListing(
            running=self.running(
                spawner.person,
                asker=spawner.activation_id,
                supply=spawner.supply,
                shown=spawner.sees_running,
            ),
            scheduled=await self.scheduled(spawner.person),
            recent=await self.recent(spawner.person, supply=spawner.supply),
            listed=True,
        )

    def running(
        self, person: str, *, asker: str | None, supply: TurnSupply | None, shown: bool = True
    ) -> tuple[ActivationEntry, ...]:
        """What is running for ``person``, live from the engine (§4:6, §10:2).

        Each as ADR-0332 §4:1 shows one: its input, under §4:2's predicate where an
        audience is given, and nothing to a viewer whose author is not established
        (§4:3, ``shown``). One whose input's origin is outside is shown with its text
        withheld (§4:7). Bounded by the listing bound, oldest first.
        """
        if not shown:
            return ()
        entries: list[tuple[datetime, ActivationEntry]] = []
        for one in self._running():
            episode = None if one.capture is None else one.capture.written
            if (
                one.activation_id is None
                or one.activation_id == asker
                or one.started_at is None
                or one.ended
                or activation_person(one.trigger) != person
                or episode is None
                or (supply is not None and not admitted_to_understanding(supply, (episode,)))
            ):
                continue
            outside = one.trigger.origin is InputOrigin.OUTSIDE
            text = " ".join(message.text for message in one.whole_input) or _payload_text(one)
            entries.append(
                (
                    one.started_at,
                    ActivationEntry(
                        activation_id=one.activation_id,
                        started=local_time(one.started_at, self._zone),
                        place=place_description(one.place),
                        status="running",
                        input=None if outside or not text else _brief(text),
                        outside=outside,
                    ),
                )
            )
        entries.sort(key=lambda item: item[0])
        return tuple(entry for _, entry in entries[: self._limits.listing_bound])

    async def scheduled(self, person: str) -> tuple[TaskEntry, ...]:
        """``person``'s pending scheduled tasks, each with its parent (§4:6, §10:2).

        Raises:
            PlanningError: If the plan store cannot be read.
        """
        held = await self._plans.person_scheduled_tasks(person, [OccurrenceState.PENDING])
        return tuple(self.entry(one) for one in held[: self._limits.listing_bound])

    async def recent(
        self, person: str, *, supply: TurnSupply | None
    ) -> tuple[ActivationEntry, ...]:
        """The activations the Task Scheduler started for ``person`` that ended last (§7:9).

        Read from the schedule's episodes, newest first, bounded by the listing bound.

        Raises:
            MemoryStoreError: If the episodes cannot be read.
        """
        page = await self._memory.channel_episodes(SCHEDULE, limit=self._limits.listing_bound)
        shown: list[ActivationEntry] = []
        for row in reversed(page.entries):
            record = row.record
            processing = record.processing_record
            if processing is None or processing.is_open:
                continue
            if activation_person(processing.trigger) != person:
                continue
            if supply is not None and not admitted_to_understanding(supply, (record,)):
                continue
            outside = processing.trigger.origin is InputOrigin.OUTSIDE
            payload = processing.trigger.payload
            text = getattr(payload, "text", None)
            status = _ended_text(processing.status, processing.reason)
            shown.append(
                ActivationEntry(
                    activation_id=processing.activation_id,
                    started=local_time(processing.started_at, self._zone),
                    place=place_description(SCHEDULE),
                    status=status,
                    input=None if outside or not isinstance(text, str) else _brief(text),
                    outside=outside,
                )
            )
        return tuple(shown)

    def entry(self, task: ScheduledTask) -> TaskEntry:
        """``task`` as a listing shows it, with the hub's renderings from its record."""
        occurrence = task.occurrences[0]
        who = (
            "a scheduled step"
            if task.set_in.channel_type == SCHEDULE.channel_type
            else "the person's message"
            if task.author is ScheduledTaskAuthor.PERSON
            else "the assistant"
        )
        return TaskEntry(
            task_id=task.id,
            state=outcome_text(occurrence),
            falls_due=when_text(task, self._zone),
            waits_on=task.when.tasks if isinstance(task.when, DueAfterTasks) else (),
            instruction=None if task.outside_content else _brief(task.instruction),
            outside=task.outside_content,
            places=tuple(place_of(one) for one in task.places),
            parent=task.parent,
            parent_text=(
                f"spawned by {who} in {place_description(task.set_in)}, "
                f"{local_time(task.set_at, self._zone)}"
            ),
            author=task.author.value,
        )

    # --- the commands (§10:2) ---

    async def spawn(  # noqa: PLR0913 — the spawner, what it states, the record it is claimed under, and the claim's two
        self,
        spawner: Spawner,
        *,
        instruction: str,
        when: TaskWhen,
        places: tuple[ChannelIdentity, ...],
        replaces: str | None,
        effect: ActivationEffect,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ScheduledTaskWrite:
        """Write a spawn's task, claiming its effect record in the one step (§3:3).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawner.
            PlanningError: If the spawn does not validate or the store fails.
        """
        spawn = TaskSpawn(
            id=self._new_task_id(),
            person=spawner.person,
            author=spawner.author,
            when=when,
            places=places,
            instruction=instruction,
            set_in=spawner.set_in,
            set_at=self._now(),
            outside_content=spawner.read_outside_content,
            replaces=replaces,
        )
        written = await self._plans.write_scheduled_task(
            spawn,
            effect,
            match=match,
            deliberate_repeat=deliberate_repeat,
            replace_any=spawner.users_authority,
            chain_limit=self._limits.chain_limit,
            pending_limit=self._limits.pending_limit,
        )
        if written.answer is TaskWriteAnswer.WRITTEN:
            self._wake()
            if replaces is not None:
                await self.tidy([replaces])
        return written

    async def cancel(
        self, task_id: str, *, person: str | None = None, spawned_by: str | None = None
    ) -> ScheduledTaskCancel:
        """Cancel what is pending of a task (§9:5); it stops nothing running.

        ``person`` and ``spawned_by`` are §4:4's checks for planning's cancel; the Task
        Manager's command and the cascade give neither.

        Raises:
            PlanningError: If the store fails.
        """
        cancelled = await self._plans.cancel_scheduled_task(
            task_id, person=person, spawned_by=spawned_by
        )
        if cancelled.task is not None:
            self._wake()
            await self.tidy([task_id])
        return cancelled

    async def replace(
        self, task_id: str, *, instruction: str, when: TaskWhen
    ) -> ScheduledTaskWrite:
        """The Task Manager's replace command, from outside (§9:4, §10:2).

        A structured act naming one operation (§10:5): it writes the new task, which takes
        the replaced task's parent, suggested places and chain length, claimed under an
        effect record of the command's own, and is the person's act.

        Raises:
            PlanningError: If the store fails, or the task is not held.
        """
        held = await self._plans.scheduled_tasks([task_id])
        if not held:
            msg = f"the Task Scheduler holds no task {task_id}"
            raise PlanningError(msg)
        replaced = held[0]
        command = str(uuid.uuid4())
        effect = _command_effect(command, self._now())
        spawner = Spawner(
            activation_id=command,
            person=replaced.person,
            users_authority=True,
            set_in=replaced.set_in,
        )
        written = await self.spawn(
            spawner,
            instruction=instruction,
            when=when,
            places=(),
            replaces=task_id,
            effect=effect,
            match=None,
            deliberate_repeat=False,
        )
        if written.answer is TaskWriteAnswer.WRITTEN:
            await self._plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)
        return written

    async def cascade(self, activation_id: str) -> None:
        """Stop what is still live below a stopped activation (ADR-0350 §9:6).

        The walk runs down through the tasks the activation spawned, and the tasks their
        activations spawned in turn, whether or not those activations have ended: it
        cancels every pending occurrence, stops every activation pushed or running, and
        acts on nothing that has ended. Where a push won against its cancel (§7:5), the
        activation it names is stopped in turn. Whatever a failure leaves of the walk,
        the cascade record already written keeps everything below from being pushed.
        """
        frontier = [activation_id]
        seen: set[str] = set()
        while frontier:
            try:
                below = await self._plans.spawned_tasks(frontier)
            except PlanningError:
                _log.warning("task_cascade_cut_short", stage="stop", reason="store_failed")
                return
            frontier = []
            for task in below:
                if task.id in seen:
                    continue
                seen.add(task.id)
                current = await self._cancel_below(task)
                for one in current.occurrences:
                    if one.pushed_to is not None:
                        await self._stop_below(one.pushed_to)
                frontier.extend(current.activations)

    async def _cancel_below(self, task: ScheduledTask) -> ScheduledTask:
        """Cancel ``task``'s pending occurrences in a cascade, and read it as it stands."""
        if task.pending:
            try:
                cancelled = await self.cancel(task.id)
            except PlanningError:
                _log.warning("task_cascade_cancel_failed", stage="stop", reason="store_failed")
                return task
            if cancelled.task is not None:
                return cancelled.task
        try:
            held = await self._plans.scheduled_tasks([task.id])
        except PlanningError:
            return task
        return held[0] if held else task

    async def _stop_below(self, activation_id: str) -> None:
        try:
            await self._stop_one(activation_id)
        except PlanningError:
            # The mark is set where it runs, and the cascade record holds the rest.
            _log.warning("task_cascade_stop_unrecorded", stage="stop", reason="store_failed")

    # --- keeping the schedule (§7:8) ---

    async def tidy(self, task_ids: Iterable[str]) -> None:
        """Remove each named task once nothing of it or below it is live (§7:8).

        A task whose parent still runs is kept. Each task removed may let the task above
        it, and the tasks it waited on, go in turn. Never raises but for a cancellation:
        a removal not made now is made at a later tidy, and nothing reads a task kept a
        little longer as anything but kept.
        """
        work = list(dict.fromkeys(task_ids))
        seen: set[str] = set()
        while work:
            task_id = work.pop()
            if task_id in seen:
                continue
            seen.add(task_id)
            try:
                held = await self._plans.scheduled_tasks([task_id])
                if not held or self._is_running(held[0].parent):
                    continue
                task = held[0]
                if not await self._plans.remove_scheduled_task(task_id):
                    continue
                above = await self._plans.scheduled_lineage(task.parent)
            except PlanningError:
                _log.warning("task_tidy_failed", stage="task_scheduler", reason="store_failed")
                continue
            if above:
                work.append(above[-1].id)
            if isinstance(task.when, DueAfterTasks):
                work.extend(task.when.tasks)

    async def parent_ended(self, activation_id: str) -> None:
        """An activation ended: the tasks it spawned may now be removed (§7:8)."""
        try:
            spawned = await self._plans.spawned_tasks([activation_id])
        except PlanningError:
            _log.warning("task_tidy_failed", stage="task_scheduler", reason="store_failed")
            return
        if spawned:
            await self.tidy(one.id for one in spawned)


def _ended_text(status: ProcessingStatus | None, reason: ProcessingReason | None) -> str:
    """How an ended activation's episode froze, in words."""
    if status is None:
        return "ended"
    return status.value if reason is None else f"{status.value} ({reason.value})"


def _payload_text(state: ActivationState) -> str:
    text = getattr(state.trigger.payload, "text", None)
    return text if isinstance(text, str) else ""


def _command_effect(command: str, at: datetime) -> ActivationEffect:
    """The effect record a Task Manager's replace is claimed under (§10:2)."""
    return ActivationEffect(
        id=f"effect:{uuid.uuid4().hex}",
        activation_id=command,
        capability=SPAWN_CAPABILITY,
        values_digest="0" * 64,
        decision_id=f"command:{command}",
        claimed_at=at,
    )


class ScheduledTaskCalls:
    """Acting's runner for spawn, cancel and the list pull (ADR-0350 §4:3, §10:4).

    Structurally acting's ``OwnRecordsCalls`` and its ``ClaimingOwnRecordsCalls``: each
    call runs directly against the plan store, through the one :class:`TaskManager`, and
    is awaited to its end. Who calls is read from :func:`current_spawner`, which the
    phases open around acting, never from what the call carries.
    """

    def __init__(self, *, manager: TaskManager, now: Clock) -> None:
        """Wire the runner.

        Args:
            manager: The Task Manager, whose operations the calls are.
            now: The clock a delay and an instant are read against.
        """
        self._manager = manager
        self._now = now

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run a cancel or a list pull; a spawn reaches :meth:`run_claiming` alone."""
        spawner = current_spawner()
        if spawner is None:
            return NotDone(reason=_NOT_OFFERED)
        capability = str(call.request.tool.capability)
        try:
            if capability == LIST_TASKS_CAPABILITY:
                listing = await self._manager.listing(spawner)
                return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))
            if capability == CANCEL_TASK_CAPABILITY:
                return await self._cancel(spawner, call.request.parameters)
        except PlanningError, MemoryStoreError:
            _log.warning("task_call_not_done", stage="acting", reason="store_failed")
            return NotDone(reason=_STORE_FAULT)
        return NotDone(reason=_MALFORMED)

    async def _cancel(
        self, spawner: Spawner, arguments: Mapping[str, FrozenJson]
    ) -> OwnRecordsAnswer:
        task_id = arguments.get(TASK_ARGUMENT)
        if not isinstance(task_id, str) or not task_id.strip():
            return NotDone(reason=_MALFORMED)
        cancelled = await self._manager.cancel(
            task_id,
            person=spawner.person,
            spawned_by=None if spawner.users_authority else spawner.activation_id,
        )
        if cancelled.reason is not None or cancelled.task is None:
            reason = TaskRefusal.UNKNOWN_TASK if cancelled.reason is None else cancelled.reason
            _log.info("task_call_not_done", stage="acting", reason=reason.value)
            return NotDone(reason=_REFUSAL_TEXT[reason])
        listing = TaskListing(cancelled=self._manager.entry(cancelled.task))
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))

    async def run_claiming(  # noqa: PLR0911 — each of §4:5's refusals is a return of its own
        self,
        call: ToolCall,
        effect: ActivationEffect,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ClaimingAnswer:
        """Run a spawn, its task and its effect claim written in one step (§3:3).

        Refused, writing nothing, where its instant is earlier than now, it suggests a
        place off its activation's list, or the store refuses it (§4:5).

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
        """
        spawner = current_spawner()
        if spawner is None or str(call.request.tool.capability) != SPAWN_CAPABILITY:
            return Unwritten(reason=_NOT_OFFERED)
        arguments = call.request.parameters
        instruction = arguments.get(INSTRUCTION_ARGUMENT)
        if not isinstance(instruction, str) or not instruction.strip():
            return Unwritten(reason=_MALFORMED)
        when = spawn_when(arguments, now=self._now())
        if isinstance(when, str):
            return Unwritten(reason=when)
        places = _suggested(spawner, arguments)
        if isinstance(places, str):
            return Unwritten(reason=places)
        replaces = arguments.get(REPLACES_ARGUMENT)
        if replaces is not None and not isinstance(replaces, str):
            return Unwritten(reason=_MALFORMED)
        try:
            written = await self._manager.spawn(
                spawner,
                instruction=instruction,
                when=when,
                places=places,
                replaces=replaces,
                effect=effect,
                match=match,
                deliberate_repeat=deliberate_repeat,
            )
        except ValueError:
            return Unwritten(reason=_MALFORMED)
        if written.answer is TaskWriteAnswer.ALREADY_DONE:
            return ActivationEffectClaim.ALREADY_DONE
        if written.answer is TaskWriteAnswer.ALREADY_USED:
            return ActivationEffectClaim.ALREADY_USED
        if written.task is None:
            reason = TaskRefusal.UNKNOWN_TASK if written.reason is None else written.reason
            _log.info("task_call_not_done", stage="acting", reason=reason.value)
            return Unwritten(reason=_REFUSAL_TEXT[reason])
        listing = TaskListing(spawned=self._manager.entry(written.task))
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=encode_listing(listing))


def _suggested(
    spawner: Spawner, arguments: Mapping[str, FrozenJson]
) -> tuple[ChannelIdentity, ...] | str:
    """The places a spawn suggests, each on its activation's list, or why not (§5:6).

    A spawn stating none from an activation the Task Scheduler started carries its own
    task's suggested places forward.
    """
    named = arguments.get(PLACES_ARGUMENT)
    if named is None:
        chosen = spawner.carried
    elif isinstance(named, list | tuple) and all(isinstance(one, str) for one in named):
        chosen = tuple(str(one) for one in named)
        if any(one not in spawner.places for one in chosen):
            return _OFF_THE_LIST
    else:
        return _MALFORMED
    channels: list[ChannelIdentity] = []
    for one in dict.fromkeys(chosen):
        channel = place_channel(one)
        if channel is None:
            return _MALFORMED
        channels.append(channel)
    return tuple(channels)


@dataclass(frozen=True, slots=True)
class TaskSchedulerSeams:
    """What the composition root hands the engine for the Task Scheduler (ADR-0350 §12:5).

    Attributes:
        limits: The chain, pending and listing bounds.
        recheck: The sensor's recheck interval (§7:2).
        lateness_grace: How long after it was due an occurrence may be pushed before its
            input says it is late (§8:9).
        push_limit: The most times one occurrence is pushed (§8:5).
        zone: The IANA name of the zone the hub's renderings tell local time in.
        persons: The people whose pushed occurrences a restart settles (§8:1).
    """

    limits: TaskManagerLimits
    recheck: timedelta
    lateness_grace: timedelta
    push_limit: int
    zone: str
    persons: tuple[str, ...]
