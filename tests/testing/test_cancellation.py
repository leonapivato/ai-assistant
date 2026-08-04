"""Regression tests for the cancellation scaffolding itself (ADR-0060).

The conformance suites lean on ``ai_assistant.testing.cancellation`` to hold a
call open inside a resource and let it go again. Most of that machinery is
exercised transitively by the suites that use it; what needs a test of its own is
a failure mode the suites *cannot* surface because it only bites on their own
teardown — a :class:`ThreadSuspension.reached` wait abandoned by an outer
cancellation (#376).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ai_assistant.testing.cancellation import (
    ThreadSuspension,
    settle,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Comfortably below ``cancellation._WAIT_SECONDS`` (5.0): a released worker frees
#: its thread at once, so a probe that needs that thread runs immediately, while
#: an unwoken worker would hold it until the ceiling and blow this bound.
_PROMPT_SECONDS = 1.0


@contextlib.contextmanager
def _single_worker_pool() -> Iterator[None]:
    """Route this loop's ``to_thread`` work through exactly one thread.

    ``reached`` calls ``asyncio.to_thread`` internally, so the test cannot route
    the wait itself; capping the default executor at one worker is what makes
    "the abandoned wait is still holding a thread" observable — a probe can only
    run once that one worker is free. Nothing is restored because nothing is
    displaced: each test gets its own loop, a loop builds its default executor
    lazily, and this installs one before any ``to_thread`` has run (the pattern
    ``tests/models/test_fastembed_embedder.py`` uses).
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        asyncio.get_running_loop().set_default_executor(pool)
        yield


class _WatchedEvent:
    """A ``threading.Event`` that announces when a thread has entered ``wait``.

    Substituted for a :class:`ThreadSuspension`'s internal event so the test can
    block until the ``reached`` worker is *demonstrably* inside ``Event.wait`` —
    a deterministic latch in place of a sleep. ``wait`` sets :attr:`entered`
    before it blocks, so once :attr:`entered` is set the executor job is running
    and can no longer be cancelled out of the queue: the orphaned worker the test
    needs is guaranteed to have formed. Only the members ``ThreadSuspension``
    calls (``wait``/``set``) are provided.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self.entered = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        """Announce arrival, then delegate to the wrapped event."""
        self.entered.set()
        return self._event.wait(timeout)

    def set(self) -> None:
        """Wake the wrapped event."""
        self._event.set()


async def test_release_frees_a_reached_wait_abandoned_by_cancellation() -> None:
    """A cancelled ``reached`` wait is woken by ``release``, not left until the ceiling.

    Cancelling the task awaiting ``reached`` cannot stop the worker thread already
    inside ``Event.wait`` — its future is simply dropped. Before #376 that worker
    stayed blocked until ``_WAIT_SECONDS`` because ``release`` woke only the
    *hold* side; repeated, it would occupy the default executor's workers and
    stall unrelated async tests. The fix has ``release`` wake the ``reached`` side
    too, so the orphaned worker frees its thread promptly.
    """
    loop = asyncio.get_running_loop()
    with _single_worker_pool(), ThreadPoolExecutor(max_workers=1) as watch_pool:
        suspension = ThreadSuspension()
        watched = _WatchedEvent()
        suspension._reached = watched  # type: ignore[assignment]  # instrument the wait

        # A reached() wait with no worker to arrive: its to_thread takes the sole
        # thread and would sit in Event.wait until the ceiling.
        waiting = asyncio.ensure_future(suspension.reached())
        # Latch, not a sleep: block until the worker is inside Event.wait, so the
        # executor job is running and the cancel below orphans it rather than
        # merely dropping an unstarted job from the queue. Watched on a separate
        # thread because the sole default-executor thread is the one we are
        # waiting on.
        entered = await loop.run_in_executor(watch_pool, watched.entered.wait, _PROMPT_SECONDS)
        assert entered, "the reached() worker never entered its wait"

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        # The orphaned worker really holds the sole thread: a probe cannot run.
        probe = asyncio.ensure_future(asyncio.to_thread(lambda: None))
        await settle()
        assert not probe.done(), "the abandoned worker should still hold the sole thread"

        # The fix: release() wakes the orphan, so its thread frees and the probe
        # runs well within the prompt bound. Unfixed, the worker would hold it
        # until _WAIT_SECONDS and this would time out.
        suspension.release()
        await asyncio.wait_for(probe, timeout=_PROMPT_SECONDS)


async def test_release_before_arrival_still_ends_a_reached_wait() -> None:
    """``release`` ends a ``reached`` wait even when the worker never arrived.

    The abandonment shape without the cancel: ``hold`` is never called, so the
    only thing that can end the wait is ``release``. This pins the wake directly,
    independently of the executor-occupancy reasoning above.
    """
    suspension = ThreadSuspension()
    waiting = asyncio.ensure_future(suspension.reached())

    suspension.release()

    await asyncio.wait_for(waiting, timeout=_PROMPT_SECONDS)


async def test_the_lever_leaves_the_default_executor_exactly_as_it_found_it() -> None:
    """``worker_finished_before_the_first_check``'s scope claim, on both states.

    Restoring a *fresh* pool rather than the prior one looks identical from inside
    the block and is wrong outside it: an executor a fixture installed to constrain
    or observe the loop's thread use would be silently dropped — ``_single_worker_pool``
    above installs exactly that — and a pool the loop had already built lazily for
    an earlier call would be stranded with its threads running and nothing holding
    it. Every store case that uses this lever does some store work first, so the
    second is the ordinary case rather than the exotic one.

    Asserted against whatever the loop was carrying rather than against ``None``,
    because the property is "as it found it" and the initial state is the fixture's
    business. ``set_default_executor`` is write-only and refuses ``None``, so the
    loop's own attribute is the only way to observe either side of this.
    """
    loop = asyncio.get_running_loop()
    found = loop._default_executor  # type: ignore[attr-defined]

    with worker_finished_before_the_first_check():
        assert loop._default_executor is not found  # type: ignore[attr-defined]

    assert loop._default_executor is found  # type: ignore[attr-defined]

    installed = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(installed)
    try:
        with worker_finished_before_the_first_check():
            pass

        assert loop._default_executor is installed  # type: ignore[attr-defined]
    finally:
        # This case has to leave the loop as *it* found it for the same reason the
        # lever does. Closing `installed` while the loop still points at it hands
        # the next `to_thread` a shut-down pool — harmless under a per-test loop,
        # a `RuntimeError` under a wider-scoped one — so the restore comes first.
        loop._default_executor = found  # type: ignore[attr-defined]
        installed.shutdown(wait=False)
