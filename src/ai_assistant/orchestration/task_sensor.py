"""The Task Scheduler's sensor: one loop that pushes each due occurrence (ADR-0350 §7, §8).

**One loop** (§7:1), which the engine starts with the hub and stops with it, as it does
the line's reader; it is not a row of ADR-0083 §7's scheduler. It sleeps until the
earliest instant an occurrence falls due, for no longer than the recheck interval, and
every write to a scheduled task wakes it, so a task due now is pushed straight away
(§7:2). It compares wall-clock instants in UTC, never elapsed sleep, and pushes every
pending occurrence due at or before now (§7:3), each as an input of its own: it groups
nothing (§7:4). The push itself — the pushed mark, naming the id the activation will be
admitted under, and the admission — is the engine's, handed in as ``push``.

**After a restart** (§8:1-§8:7). Before it pushes anything, and after the engine has
closed the open episodes a dead process left (ADR-0286 §7:2), the sensor settles each
occurrence marked pushed whose activation is not running. Where the store holds a stop
record for it, the occurrence ends *stopped*. Otherwise it first confirms that
activation's messages (§8:11), then the first of these that applies decides:

1. its effect records hold a spawn: *interrupted*, never pushed again, so a chain cannot
   fork (§8:2);
2. its episode froze with any ending but the restart's close: the outcome that ending
   gives (§8:3, §7:6);
3. a message it claimed is done: *done* (§8:4);
4. not itself a second try, and it claimed no effect, or only messages each not done:
   pushed again, at most the push limit of times in all, then *interrupted* (§8:5);
5. not itself a second try, its pushes under the limit, and it claimed only messages, any
   of them unknown or with no outcome written: pushed once more as a **second try**
   (§8:6);
6. otherwise *interrupted*, never pushed again (§8:7).

**Confirming delivery** (§8:11). For each message the activation claimed whose outcome
is unknown or none written, the sensor asks the kind of its place whether it can confirm
(:func:`~ai_assistant.orchestration.channel_kinds.confirms_delivery`). The hub chat can:
the transcript records each assistant message with the effect record it was claimed
under (§12:9), so ``ConversationStore.effect_position`` answers, and the record is settled
*done* at that position, or *not done*. Where the kind cannot, or the place is gone, the
record is left as it was. So a hub chat message is read, never guessed; only one the
place cannot confirm, as on the line, takes the second try.

**Whom it settles** (§12:3). The restart reads the pushed occurrences by person and state,
of each person the hub serves: today the owner alone (ADR-0338 §2:2).

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    PlanningError,
    UnknownConversationError,
)
from ai_assistant.core.types import EpisodicMemory, OccurrenceState, ToolOutcome
from ai_assistant.orchestration.channel_kinds import confirms_delivery, place_channel
from ai_assistant.orchestration.defects import is_defect, log_defect
from ai_assistant.orchestration.task_scheduler import SPAWN_CAPABILITY, occurrence_outcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ConversationStore, MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        DueOccurrence,
        ScheduledOccurrence,
        ScheduledTask,
    )

__all__ = ["SensorLimits", "TaskSchedulerSensor", "restart_outcome"]

_log = structlog.get_logger(__name__)

#: How long the loop rests after a read of the schedule failed, before it reads again.
_BACKOFF_SECONDS: Final = 5.0


@dataclass(frozen=True, slots=True)
class SensorLimits:
    """ADR-0350 §12:5's settings the sensor reads.

    Attributes:
        recheck: The longest it sleeps before it looks for due occurrences again (§7:2).
        push_limit: The most times one occurrence is pushed (§8:5).
    """

    recheck: timedelta
    push_limit: int


@dataclass(frozen=True, slots=True)
class _Settled:
    """How a restart settles one pushed occurrence: its outcome, or its push again."""

    state: OccurrenceState
    second_try: bool = False


def restart_outcome(
    occurrence: ScheduledOccurrence,
    effects: Sequence[ActivationEffect],
    episode: EpisodicMemory | None,
    *,
    push_limit: int,
) -> tuple[OccurrenceState, bool]:
    """How a restart settles an occurrence its activation was cut off in (§8:2-§8:7).

    Read after the stop record (§8:1) and after the activation's messages were confirmed
    (§8:11), the first clause that applies deciding.

    Args:
        occurrence: The occurrence, as pushed to the activation.
        effects: The activation's effect records, as confirmed.
        episode: The activation's episode, or ``None`` where none is held.
        push_limit: §12:5's push limit.

    Returns:
        The state the occurrence takes, ``pending`` to push it again, and whether that
        push is a second try.
    """
    if any(one.is_call and one.capability == SPAWN_CAPABILITY for one in effects):
        return OccurrenceState.INTERRUPTED, False
    ended = None if episode is None else occurrence_outcome(episode)
    if ended is not None:
        return ended, False
    messages = [one for one in effects if not one.is_call]
    calls = [one for one in effects if one.is_call]
    if any(one.outcome is ToolOutcome.SUCCEEDED for one in messages):
        return OccurrenceState.DONE, False
    under = occurrence.pushes < push_limit
    if not occurrence.second_try and not calls:
        if all(one.outcome is ToolOutcome.FAILED for one in messages):
            return (
                (OccurrenceState.PENDING, False) if under else (OccurrenceState.INTERRUPTED, False)
            )
        if under:
            return OccurrenceState.PENDING, True
    return OccurrenceState.INTERRUPTED, False


class TaskSchedulerSensor:
    """The Task Scheduler's sensor (§7, §8): the loop, and the restart's settlement."""

    def __init__(  # noqa: PLR0913 — the three stores, the engine's three seams, the people it settles for, the bounds and the clock
        self,
        *,
        plans: PlanStore,
        memory: MemoryStore,
        conversations: ConversationStore,
        push: Callable[[DueOccurrence], Awaitable[None]],
        is_running: Callable[[str], bool],
        settled: Callable[[ScheduledTask], Awaitable[None]],
        closing: Callable[[], bool],
        persons: Sequence[str],
        limits: SensorLimits,
        now: Clock,
        retry: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Wire the sensor.

        Args:
            plans: The plan store, which holds the Task Scheduler's content.
            memory: The memory store an activation's episode is read from.
            conversations: The chat space, whose transcript confirms delivery (§8:11).
            push: Marks one due occurrence pushed and admits its activation: the
                engine's. It returns once the activation is admitted or refused.
            is_running: Whether an activation is running, admitted or pushed.
            settled: Told each task whose occurrence a restart settled, so it may be
                removed (§7:8).
            closing: Whether the engine's shutdown has begun.
            persons: The people whose pushed occurrences a restart settles.
            limits: §12:5's recheck interval and push limit.
            now: The wall clock, in UTC (§7:3).
            retry: Writes again what the engine failed to write when an activation it
                admitted ended, run before each look; ``None`` writes nothing.
        """
        self._plans = plans
        self._memory = memory
        self._conversations = conversations
        self._push = push
        self._is_running = is_running
        self._settled = settled
        self._closing = closing
        self._persons = tuple(persons)
        self._limits = limits
        self._now = now
        self._retry = retry
        self._woken = asyncio.Event()
        self._stopped = False
        #: Whether a pushed occurrence may be left unsettled: a restart's settlement that
        #: could not finish, or a push that failed after its pushed mark was written. The
        #: loop settles again before each look until none is (§8:1).
        self._unsettled = False

    def wake(self) -> None:
        """Wake the loop: a task was written, or an occurrence ended (§7:2, §7:7)."""
        self._woken.set()

    def close(self) -> None:
        """End the loop at its next look; an activation it admitted is the drain's."""
        self._stopped = True
        self._woken.set()

    def _done(self) -> bool:
        return self._stopped or self._closing()

    async def run(self) -> None:
        """The sensor's long-running task: the restart's settlement, then the loop.

        Raises:
            CancelledError: Where a shutdown cancelled it.
        """
        self._unsettled = True
        while not self._done():
            self._woken.clear()
            if self._retry is not None:
                await self._retry()
            if self._unsettled:
                # §8:1: what a restart, or a store failure, left pushed and running
                # nowhere is settled before anything is pushed; until it is, nothing is.
                # The flag is taken before the pass, so a request made during it holds.
                self._unsettled = False
                if not await self.settle_restart():
                    self._unsettled = True
            if self._unsettled:
                wait = min(self._limits.recheck.total_seconds(), _BACKOFF_SECONDS)
            else:
                wait = await self.look()
            if self._done():
                return
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(wait):
                    await self._woken.wait()

    async def look(self) -> float:
        """Push every occurrence due now, each on its own; how long to sleep after.

        Returns:
            Seconds until the earliest pending occurrence falls due, at most the recheck
            interval; a short backoff where the schedule could not be read.
        """
        recheck = self._limits.recheck.total_seconds()
        at = self._now()
        try:
            due = await self._plans.due_occurrences(at)
        except PlanningError:
            _log.warning("task_sensor_unread", stage="task_sensor", reason="store_failed")
            return min(recheck, _BACKOFF_SECONDS)
        for one in due.due:
            if self._done():
                break
            await self._pushed(one)
        if due.next_due_at is None:
            return recheck
        return max(0.0, min(recheck, (due.next_due_at - self._now()).total_seconds()))

    async def _pushed(self, due: DueOccurrence) -> None:
        """Push one due occurrence; a failure is logged and the loop goes on."""
        try:
            await self._push(due)
        except asyncio.CancelledError:
            raise
        except PlanningError:
            # The pushed mark may have landed: the next look settles what it left.
            self._unsettled = True
            _log.warning("task_sensor_push_failed", stage="task_sensor", reason="store_failed")
        except Exception as exc:  # the sensor runs as long as the hub: a defect is logged
            self._unsettled = True
            if is_defect(exc):
                log_defect("task_sensor_push_failed", exc, stage="task_sensor", activation_id=None)
            else:
                _log.warning("task_sensor_push_failed", stage="task_sensor", reason="failed")

    # --- after a restart (§8) ---

    async def settle_restart(self) -> bool:
        """Settle each pushed occurrence whose activation is not running (§8:1-§8:7).

        Never raises but for a cancellation: an occurrence a store failure kept from
        being settled now stays pushed, and is settled at a later call.

        Returns:
            Whether every such occurrence was settled.
        """
        complete = True
        for person in self._persons:
            try:
                held = await self._plans.person_scheduled_tasks(person, [OccurrenceState.PUSHED])
            except PlanningError:
                _log.warning("task_restart_unsettled", stage="task_sensor", reason="store_failed")
                complete = False
                continue
            for task in held:
                for one in task.occurrences:
                    activation = one.pushed_to
                    if activation is None or self._is_running(activation):
                        continue
                    complete = await self._settle_one(task, one, activation) and complete
        return complete

    async def _settle_one(
        self, task: ScheduledTask, occurrence: ScheduledOccurrence, activation_id: str
    ) -> bool:
        """Settle one occurrence; whether it was, a store failure leaving it pushed."""
        try:
            if activation_id in await self._plans.stopped_activations([activation_id]):
                settled = await self._plans.settle_occurrence(
                    activation_id, OccurrenceState.STOPPED
                )
            else:
                if not await self.confirm(activation_id):
                    # §8:11: a transcript that could not be read is no answer, so nothing
                    # is settled from a guess: it is read again at a later call.
                    return False
                effects = await self._plans.activation_effects([activation_id])
                record = await self._memory.get(f"activation:{activation_id}")
                episode = record if isinstance(record, EpisodicMemory) else None
                state, second_try = restart_outcome(
                    occurrence, effects, episode, push_limit=self._limits.push_limit
                )
                settled = await self._plans.settle_occurrence(
                    activation_id, state, second_try=second_try
                )
        except PlanningError, MemoryStoreError:
            _log.warning("task_restart_unsettled", stage="task_sensor", reason="store_failed")
            return False
        _log.info("task_restart_settled", stage="task_sensor", task=task.id)
        await self._settled(settled)
        return True

    async def confirm(self, activation_id: str) -> bool:
        """Confirm each of the activation's messages whose outcome is unknown (§8:11).

        Returns:
            Whether every message a kind can confirm was read: ``False`` where a
            transcript could not be read, which leaves its record as it was.

        Raises:
            PlanningError: If the plan store cannot be read or written.
        """
        complete = True
        for effect in await self._plans.activation_effects([activation_id]):
            if effect.is_call or effect.outcome not in {None, ToolOutcome.INDETERMINATE}:
                continue
            channel = None if effect.place is None else place_channel(effect.place)
            if channel is None or not confirms_delivery(channel.channel_type):
                continue
            try:
                position = await self._conversations.effect_position(channel.instance_id, effect.id)
            except UnknownConversationError:
                # The place is gone, which is no answer that it was not sent (§8:11).
                continue
            except ConversationStoreError:
                _log.warning(
                    "task_delivery_unconfirmed", stage="task_sensor", reason="store_failed"
                )
                complete = False
                continue
            await self._plans.confirm_message_effect(
                effect.id, delivered=position is not None, position=position
            )
        return complete
