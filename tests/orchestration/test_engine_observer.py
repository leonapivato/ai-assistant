"""The engine's runs of the observer (ADR-0329 §7:6, §16:6).

``Engine.observe_episodes`` is concrete maintenance surface, the body of the scheduler's
``observer`` row; a run also starts, nobody waiting on it, each time an activation's
episode is frozen. Each case wires a stand-in observer whose run a case holds open, so
what is asserted is the engine's part — the refusal, the trace, one run at a time, the
run once more after a freeze during one, and the drain — and never the observer's own,
which ``test_observer_stage.py`` holds. That a composed engine starts a run when an
activation freezes is ``tests/app/test_observer_end_to_end.py``'s.
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
import structlog.testing
from test_engine import Harness

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import TraceOutcome
from ai_assistant.orchestration.observer import Observer, RunOutcome


class _Observer:
    """A stand-in observer: counts its runs, and holds each open until released."""

    def __init__(self, *, outcome: RunOutcome | None = None, fail: bool = False) -> None:
        self.outcome = outcome or RunOutcome(processed=2, waiting=1)
        self.fail = fail
        self.runs = 0
        self.running = 0
        self.most_at_once = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def run(self) -> RunOutcome:
        self.runs += 1
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        self.entered.set()
        try:
            await self.release.wait()
            if self.fail:
                msg = "the user's sister Imogen"
                raise RuntimeError(msg)
            return self.outcome
        finally:
            self.running -= 1


def _wired(observer: _Observer) -> Harness:
    """The engine with ``observer`` where the composition root puts the real one."""
    harness = Harness()
    harness.engine._observer = cast("Observer", observer)
    return harness


async def _settled(harness: Harness) -> None:
    """Wait for the run a freeze started, and any it went round again for."""
    task = harness.engine._observing
    assert task is not None
    await asyncio.wait_for(task, timeout=5)


async def test_it_refuses_where_no_observer_is_wired() -> None:
    harness = Harness()

    with pytest.raises(ConfigurationError, match="no observer is wired"):
        await harness.engine.observe_episodes()


async def test_it_runs_the_observer_and_traces_its_counts_alone() -> None:
    """ADR-0119 §8: one ``OPERATION`` trace, its counts and nothing of any episode."""
    observer = _Observer()
    harness = _wired(observer)

    outcome = await harness.engine.observe_episodes()

    assert outcome == observer.outcome
    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "observe_episodes"
    assert trace.outcome is TraceOutcome.OK
    assert trace.metrics == {
        "busy": False,
        "processed": 2,
        "skipped": 0,
        "waiting": 1,
        "stuck": 0,
        "held": False,
    }


async def test_a_freeze_starts_a_run_nobody_waits_on() -> None:
    """§7:6: the activation is not held for the run."""
    observer = _Observer()
    observer.release.clear()
    harness = _wired(observer)

    harness.engine._observe_soon()
    await asyncio.wait_for(observer.entered.wait(), timeout=5)

    assert observer.runs == 1
    task = harness.engine._observing
    assert task is not None
    assert not task.done(), "the run is still going, and the freeze has long returned"
    assert task in harness.engine._inflight, "tracked, so shutdown drains it"
    observer.release.set()
    await _settled(harness)
    assert not harness.trace_sink.recorded, "a run a freeze started is not an operation"


async def test_freezes_during_a_run_start_no_second_and_one_more_run_follows() -> None:
    """§16:6: one run at a time; an episode frozen meanwhile is not left for the timer."""
    observer = _Observer()
    observer.release.clear()
    harness = _wired(observer)

    harness.engine._observe_soon()
    await asyncio.wait_for(observer.entered.wait(), timeout=5)
    harness.engine._observe_soon()
    harness.engine._observe_soon()
    observer.release.set()
    await _settled(harness)

    assert observer.most_at_once == 1
    assert observer.runs == 2, "the two freezes during the run ask for one more, together"


async def test_a_freeze_after_a_run_ended_starts_a_new_one() -> None:
    observer = _Observer()
    harness = _wired(observer)

    harness.engine._observe_soon()
    await _settled(harness)
    harness.engine._observe_soon()
    await _settled(harness)

    assert observer.runs == 2


async def test_a_failing_run_is_logged_by_its_class_and_raises_nowhere() -> None:
    """ADR-0004 §5, ADR-0329 §15:7: a code-owned reason, never the error's message."""
    observer = _Observer(fail=True)
    harness = _wired(observer)

    with structlog.testing.capture_logs() as logs:
        harness.engine._observe_soon()
        await _settled(harness)

    (event,) = [one for one in logs if one["event"] == "observer_run_failed"]
    assert event["error_class"] == "RuntimeError"
    assert "Imogen" not in repr(logs)
    task = harness.engine._observing
    assert task is not None
    assert task.exception() is None


async def test_a_closing_engine_starts_no_run_and_drains_the_one_going() -> None:
    """ADR-0042 §2: the run a freeze started is drained before the stores close."""
    observer = _Observer()
    observer.release.clear()
    harness = _wired(observer)
    harness.engine._observe_soon()
    await asyncio.wait_for(observer.entered.wait(), timeout=5)

    closing = asyncio.create_task(harness.engine.aclose())
    await asyncio.sleep(0)
    harness.engine._observe_soon()
    assert not closing.done(), "the drain waits for the run"
    observer.release.set()
    await asyncio.wait_for(closing, timeout=5)

    assert observer.runs == 1
    with pytest.raises(RuntimeError):
        await harness.engine.observe_episodes()
