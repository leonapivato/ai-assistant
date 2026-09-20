"""Production engine admission enters finalization before cancellation can arrive."""

from __future__ import annotations

import asyncio

import pytest
from test_activation_state import _admitted
from test_engine import Harness

from ai_assistant.core.types import EpisodicMemory, ProcessingStatus
from ai_assistant.orchestration.activation_state import ActivationScope, active_state


async def test_activation_processing_starts_only_after_registration() -> None:
    harness = Harness()
    state = _admitted()

    async def work() -> str:
        assert asyncio.current_task() in harness.engine._inflight
        assert active_state() is state
        return "completed answer"

    value, report = await harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )

    assert value == "completed answer"
    assert report is not None
    assert report.state == "recorded"
    assert active_state() is None


async def test_immediate_admitted_cancellation_records_without_starting_processing() -> None:
    harness = Harness()
    state = _admitted()
    began = False

    async def work() -> str:
        nonlocal began
        began = True
        return "must not run"

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not began
    episode = await harness.memory.get(f"activation:{state.activation_id}")
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED
    assert active_state() is None


async def test_shutdown_snapshot_waits_for_capture_children_created_after_it() -> None:
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = Harness(closers=(close,))
    state = _admitted()
    processing = asyncio.Event()
    release = asyncio.Event()
    held = harness.memory.suspend_next_operation()

    async def work() -> str:
        processing.set()
        await release.wait()
        return "answer"

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    await processing.wait()
    closing = asyncio.create_task(harness.engine.aclose())
    await asyncio.sleep(0)
    release.set()
    await held.reached()
    assert not task.done()
    assert not closing.done()
    assert not closed.is_set()
    held.release()
    _, report = await task
    await closing
    assert report is not None
    assert report.state == "recorded"
    assert closed.is_set()


async def test_unadmitted_resume_restatement_records_nothing() -> None:
    harness = Harness()
    before = await harness.memory.export()

    async def work() -> str:
        assert active_state() is None
        return "same settled answer"

    value, report = await harness.engine._activation_task(
        ActivationScope(), work, seam="resume", check_output=lambda _: None
    )

    assert value == "same settled answer"
    assert report is None
    assert await harness.memory.export() == before
