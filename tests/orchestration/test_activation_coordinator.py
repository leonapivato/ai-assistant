"""One terminal reading, deferred output refusal, and tracked capture cleanup."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs
from test_activation_writer import CommitThenFail, Wiring

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import EpisodicMemory, ProcessingReason, ProcessingStatus
from ai_assistant.orchestration.activation_coordinator import ActivationCoordinator

_AT = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.mark.parametrize("interrupted", [False, True])
async def test_finalization_reads_end_once_and_records_original_processing_cancellation(
    interrupted: bool,
) -> None:
    wiring = Wiring()
    state = await wiring.state()
    tasks: list[asyncio.Task[None]] = []
    readings = 0

    def clock() -> datetime:
        nonlocal readings
        readings += 1
        return _AT

    coordinator = ActivationCoordinator(
        writer=wiring.writer, register=tasks.append, now=clock, payload_limit=1024
    )
    result = await coordinator.finish(
        state,
        failure=asyncio.CancelledError() if interrupted else None,
        check_output=lambda: None,
    )

    assert readings == 1
    assert result.output_failure is None
    assert result.report.state == "recorded"
    assert result.report.episode_id is not None
    episode = await wiring.memory.get(result.report.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.ended_at == _AT
    assert episode.processing_record.status is (
        ProcessingStatus.INTERRUPTED if interrupted else ProcessingStatus.COMPLETED
    )
    assert len(tasks) == 2
    assert all(task.done() for task in tasks)


async def test_output_refusal_uses_actual_index_before_content_and_retains_original_error() -> None:
    wiring = Wiring()
    state = await wiring.state()
    tasks: list[asyncio.Task[None]] = []
    coordinator = ActivationCoordinator(
        writer=wiring.writer, register=tasks.append, now=lambda: _AT, payload_limit=1024
    )
    refusal = OversizedValueError("result is too large", limit=1024, size=1025)

    def check_output() -> None:
        assert state.index_episode_id is not None
        assert wiring.archive.recorded == {}
        raise refusal

    result = await coordinator.finish(state, failure=None, check_output=check_output)

    assert result.output_failure is refusal
    assert result.report.state == "recorded"
    assert result.report.episode_id is not None
    episode = await wiring.memory.get(result.report.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.reason is ProcessingReason.OUTPUT_OVERSIZED
    assert episode.processing_record.status is ProcessingStatus.FAILED
    assert episode.outcome == "the complete reply"


async def test_cleanup_budget_cancels_and_waits_for_the_registered_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiring = Wiring()
    state = await wiring.state()
    tasks: list[asyncio.Task[None]] = []
    coordinator = ActivationCoordinator(
        writer=wiring.writer, register=tasks.append, now=lambda: _AT, payload_limit=1024
    )
    loop = asyncio.get_running_loop()
    reading = loop.time()
    monkeypatch.setattr(loop, "time", lambda: reading)
    held = wiring.memory.suspend_next_operation()
    with capture_logs() as logs:
        parent = asyncio.create_task(
            coordinator.finish(state, failure=None, check_output=lambda: None)
        )
        await held.reached()
        reading += 6
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not parent.done()
        assert not tasks[0].done()
        held.release()
        result = await parent

    assert result.report.state == "degraded"
    assert result.report.episode_id == state.index_episode_id
    assert any(log.get("reason") == "timeout" for log in logs)
    assert len(tasks) == 2
    assert all(task.done() for task in tasks)


async def test_second_cancellation_drains_registered_deletion_compensation() -> None:
    memory = CommitThenFail()
    wiring = Wiring(memory=memory)
    state = await wiring.state()
    tasks: list[asyncio.Task[None]] = []
    coordinator = ActivationCoordinator(
        writer=wiring.writer, register=tasks.append, now=lambda: _AT, payload_limit=1024
    )
    ready = asyncio.Event()
    release = asyncio.Event()

    async def deleted() -> None:
        assert state.conversation_id is not None
        await wiring.conversations.stamp_deleted(state.conversation_id)
        held = wiring.conversations.suspend_next_operation()

        async def gate() -> None:
            await held.reached()
            ready.set()
            await release.wait()
            held.release()

        # This test driver does not own store I/O; the registered safety task does.
        driver = asyncio.create_task(gate())
        drivers.append(driver)

    drivers: list[asyncio.Task[None]] = []
    memory.after = deleted
    parent = asyncio.create_task(coordinator.finish(state, failure=None, check_output=lambda: None))
    await ready.wait()
    parent.cancel()
    await asyncio.sleep(0)
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done()
    assert len(tasks) == 2
    assert not any(task.done() for task in tasks)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await parent
    await asyncio.gather(*drivers)
    assert all(task.done() for task in tasks)
    assert state.index_episode_id is None
    assert await memory.export() == []
    assert wiring.archive.recorded == {}
