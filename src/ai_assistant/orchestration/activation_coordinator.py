"""Bound terminal capture separately from processing and drain its safety work."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import OversizedValueError
from ai_assistant.orchestration.activation_cleanup import drain_registered
from ai_assistant.orchestration.activation_writer import capture_loss

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import EpisodeCaptureReport, EpisodeProcessingRecord
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.activation_writer import ActivationWriter


@dataclass(frozen=True)
class FinalizedActivation:
    """The capture receipt and any deferred public-output refusal, independently."""

    report: EpisodeCaptureReport
    output_failure: OversizedValueError | None = None


class ActivationCoordinator:
    """Finalize an ended pass once, retaining every child in the engine's drain."""

    def __init__(
        self,
        *,
        writer: ActivationWriter,
        register: Callable[[asyncio.Task[None]], None],
        register_safety: Callable[[asyncio.Task[None]], None],
        now: Clock,
        payload_limit: int,
    ) -> None:
        """Receive the deterministic writer, shutdown registration and capture settings."""
        self._writer = writer
        self._register = register
        self._register_safety = register_safety
        self._clock = checked_clock(now, owner="ActivationCoordinator")
        self._payload_limit = payload_limit

    async def finish(
        self,
        state: ActivationState,
        *,
        failure: BaseException | None,
        check_output: Callable[[], None],
    ) -> FinalizedActivation:
        """Take one end reading and attempt bounded recording without retrying work.

        A processing cancellation has already been caught by the lifetime owner.
        The independent cleanup child is shielded from it; a later cancellation
        cancels ordinary writes but waits for their safety path to terminate.
        """
        report = state.degraded_report()
        output_failure: OversizedValueError | None = None
        try:
            ended_at = self._clock()
            processing = state.processing(ended_at, failure)
        except Exception:
            capture_loss("terminal", "metadata")
            return FinalizedActivation(report)

        def checked_output() -> EpisodeProcessingRecord:
            nonlocal output_failure
            if failure is None:
                try:
                    check_output()
                except OversizedValueError as exc:
                    output_failure = exc
            return state.processing(ended_at, failure or output_failure)

        timer = asyncio.timeout(5.0)

        async def recording() -> None:
            nonlocal report
            async with timer:
                report = await self._writer.write(
                    state,
                    processing,
                    payload_limit=self._payload_limit,
                    checked_output=checked_output,
                    drain=self._safety,
                )

        task = asyncio.create_task(recording())
        self._register(task)
        try:
            await drain_registered(task, cancel_on_interrupt=True)
        except asyncio.CancelledError:
            capture_loss("cleanup", "cancelled")
            raise
        except Exception:
            capture_loss("cleanup", "timeout" if timer.expired() else "failed")
        # The writer may have appended an intent row before its cancellation or
        # failure. Its address remains a legacy index fact, never a receipt.
        if report.state != "recorded":
            report = state.degraded_report()
        return FinalizedActivation(report, output_failure)

    async def _safety(self, work: Awaitable[None]) -> None:
        async def run() -> None:
            await work

        task = asyncio.create_task(run())
        self._register_safety(task)
        await drain_registered(task, cancel_on_interrupt=False)
