"""The Approvals channel's sensor: one loop that pushes each request's outcome (ADR-0361 §3).

**One loop** (§3:4), which the engine starts with the hub and stops with it, as it does
the Task Scheduler's sensor (ADR-0350 §7:1). It wakes on every write to a request and at
the earliest expiry, sleeping no longer than the recheck interval (ADR-0350 §12:5). It
compares wall-clock instants in UTC, never elapsed sleep.

**At each look** it reads what is due at now (``PlanStore.due_approval_outcomes``): each
request whose expiry has passed and that is still pending, or approved with its ticket
still held, it ends *expired* or makes its ticket void at that expiry, in one store step
(§3:5, §5:7); then it pushes every request answered or expired whose outcome no push has
marked, each as an input of its own (§3:4). The push itself — the pushed mark, naming the
id the activation will be admitted under, in one step that refuses where it is already
marked, and the admission — is the engine's, handed in as ``push``.

**After a restart** (§3:7). Before it pushes anything, the sensor reads every outcome
marked pushed (``PlanStore.pushed_approval_outcomes``) whose activation is not running
here. One whose activation was never admitted — no episode stands at its address, since
admission writes the episode before any of its processing runs (ADR-0286 §2:1) — is
pushed again, under the activation its mark names. One that was admitted and that a
restart cut off held its ticket in work that ended without running it, so a ticket still
held is made void (§5:7): running the call takes a new request. An outcome that ended
*expired* while the hub was down is expired and pushed at the first look.

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import ApprovalRequestState, TicketState
from ai_assistant.orchestration.defects import is_defect, log_defect

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import ApprovalRequest

__all__ = ["ApprovalsSensor"]

_log = structlog.get_logger(__name__)

#: How long the loop rests after a read of the requests failed, before it reads again.
_BACKOFF_SECONDS: Final = 5.0


class ApprovalsSensor:
    """The Approvals channel's sensor (§3:4-§3:7): the loop, and the restart's pass."""

    def __init__(  # noqa: PLR0913 — the two stores, the engine's two seams, the bound and the clock
        self,
        *,
        plans: PlanStore,
        memory: MemoryStore,
        push: Callable[[ApprovalRequest, str | None], Awaitable[None]],
        is_running: Callable[[str], bool],
        closing: Callable[[], bool],
        recheck: timedelta,
        now: Clock,
    ) -> None:
        """Wire the sensor.

        Args:
            plans: The plan store, which holds the Approvals channel's content.
            memory: The memory store, whose episode at an activation's address says it
                was admitted (ADR-0286 §2:1).
            push: Marks one outcome pushed and admits its activation: the engine's. Given
                the activation an earlier mark named, it admits under that id and marks
                nothing. It returns once the activation is admitted or refused.
            is_running: Whether an activation is running here, pushed or admitted.
            closing: Whether the engine's shutdown has begun.
            recheck: The longest it sleeps before it looks again (ADR-0350 §12:5).
            now: The wall clock, in UTC.
        """
        self._plans = plans
        self._memory = memory
        self._push = push
        self._is_running = is_running
        self._closing = closing
        self._recheck = recheck
        self._now = now
        self._woken = asyncio.Event()
        self._stopped = False
        #: Whether the restart's pass is still owed: it runs before anything is pushed,
        #: and again at the next look where a store failure cut it short.
        self._restart_owed = True
        #: Whether no pass has finished yet: only the pass at the hub's start reads an
        #: admitted activation not running here as one a restart cut off, since every
        #: later one ended in this process, which voided what it held itself.
        self._at_start = True

    def wake(self) -> None:
        """Wake the loop: a request was written, answered, expired or its ticket voided."""
        self._woken.set()

    def close(self) -> None:
        """End the loop at its next look; an activation it admitted is the drain's."""
        self._stopped = True
        self._woken.set()

    def _done(self) -> bool:
        return self._stopped or self._closing()

    async def run(self) -> None:
        """The sensor's long-running task: the restart's pass, then the loop.

        Raises:
            CancelledError: Where a shutdown cancelled it.
        """
        while not self._done():
            self._woken.clear()
            if self._restart_owed:
                self._restart_owed = not await self.settle_restart()
                self._at_start = self._at_start and self._restart_owed
            wait = (
                min(self._recheck.total_seconds(), _BACKOFF_SECONDS)
                if self._restart_owed
                else await self.look()
            )
            if self._done():
                return
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(wait):
                    await self._woken.wait()

    async def look(self) -> float:
        """Expire what is past its expiry, push every outcome due; how long to sleep after.

        Returns:
            Seconds until the earliest expiry still ahead, at most the recheck interval;
            a short backoff where the requests could not be read.
        """
        recheck = self._recheck.total_seconds()
        at = self._now()
        try:
            due = await self._plans.due_approval_outcomes(at)
            for one in due.expiring:
                # §3:5, §5:7: a pending request ends expired, and a ticket still held
                # expires with it; either is one step, which refuses where a tap landed.
                await self._plans.expire_approval_request(str(one.id), at)
            if due.expiring:
                due = await self._plans.due_approval_outcomes(at)
        except PlanningError:
            _log.warning("approval_sensor_unread", stage="approval_sensor", reason="store_failed")
            return min(recheck, _BACKOFF_SECONDS)
        for one in due.outcomes:
            if self._done():
                break
            if not await self._pushed(one, None):
                # The pushed mark may have landed: the restart's pass settles what it left.
                self._restart_owed = True
        if due.next_expiry_at is None:
            return recheck
        return max(0.0, min(recheck, (due.next_expiry_at - self._now()).total_seconds()))

    async def _pushed(self, request: ApprovalRequest, activation_id: str | None) -> bool:
        """Push one outcome; whether it was. A failure is logged and the loop goes on."""
        try:
            await self._push(request, activation_id)
        except asyncio.CancelledError:
            raise
        except PlanningError:
            _log.warning(
                "approval_sensor_push_failed", stage="approval_sensor", reason="store_failed"
            )
            return False
        except Exception as exc:  # the sensor runs as long as the hub: a defect is logged
            if is_defect(exc):
                log_defect(
                    "approval_sensor_push_failed", exc, stage="approval_sensor", activation_id=None
                )
            else:
                _log.warning(
                    "approval_sensor_push_failed", stage="approval_sensor", reason="failed"
                )
            return False
        return True

    async def settle_restart(self) -> bool:
        """Push again each outcome never admitted, and void what a cut-off holder held (§3:7).

        Never raises but for a cancellation.

        Returns:
            Whether every outcome marked pushed was read and settled.
        """
        try:
            pushed = await self._plans.pushed_approval_outcomes()
        except PlanningError:
            _log.warning(
                "approval_restart_unsettled", stage="approval_sensor", reason="store_failed"
            )
            return False
        complete = True
        for request in pushed:
            activation_id = request.pushed_to
            if activation_id is None or self._is_running(activation_id):
                continue
            try:
                admitted = await self._memory.get(f"activation:{activation_id}") is not None
                if admitted:
                    if self._at_start:
                        await self._void_held(request)
                    continue
            except PlanningError, MemoryStoreError:
                _log.warning(
                    "approval_restart_unsettled", stage="approval_sensor", reason="store_failed"
                )
                complete = False
                continue
            _log.info("approval_restart_pushed_again", stage="approval_sensor")
            complete = await self._pushed(request, activation_id) and complete
        return complete

    async def _void_held(self, request: ApprovalRequest) -> None:
        """§5:7: the work holding the input ended without running the ticket.

        Raises:
            PlanningError: If the store cannot be written.
        """
        if request.state is ApprovalRequestState.APPROVED and request.ticket is TicketState.HELD:
            await self._plans.void_approval_ticket(str(request.id))
            _log.info("approval_ticket_void", stage="approval_sensor", reason="holder_cut_off")
