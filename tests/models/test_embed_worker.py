"""Tests for the embedder's owned worker threads (ADR-0118 §7).

The deadline itself is not tested here — it belongs to ``BoundedEmbedder`` and is
pinned in ``test_bounded_embedder.py``. What this module pins is the *containment*
the ADR obliges the dispatching implementation to carry: where the work runs, that
nothing joins it, and that what a stopped caller leaves behind cannot accumulate.

Every blocking callable below is released before the test returns, including on a
failing run. A daemon thread left parked on an event would otherwise survive the
test and be counted by the next one.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ai_assistant.models._embed_worker import OwnedWorkers, WorkersExhaustedError

if TYPE_CHECKING:
    from collections.abc import Iterator

# A bound on *failure*: nothing waits this long on a passing run. Generous on
# purpose — it is never the thing being measured.
_RENDEZVOUS_TIMEOUT_SECONDS = 10.0


class _Blocking:
    """A callable that parks its worker until the test lets it go.

    Not a sleep: the window a test needs is held open for exactly as long as the
    test needs it, so nothing here depends on how fast the machine is.
    """

    def __init__(self, result: str = "done") -> None:
        self.entered = threading.Event()
        self.proceed = threading.Event()
        self.timed_out = False
        self._result = result

    def __call__(self) -> str:
        self.entered.set()
        if not self.proceed.wait(timeout=_RENDEZVOUS_TIMEOUT_SECONDS):
            # Recorded rather than raised: a run that only "passed" because this
            # callable gave up waiting must not look green.
            self.timed_out = True
        return self._result

    def release(self) -> None:
        self.proceed.set()


@pytest.fixture
def released() -> Iterator[list[_Blocking]]:
    """Collects blocking callables and releases every one on the way out."""
    blockers: list[_Blocking] = []
    try:
        yield blockers
    finally:
        for blocker in blockers:
            blocker.release()


def _workers(*, max_abandoned: int = 2) -> OwnedWorkers:
    return OwnedWorkers(thread_name="test-embed-worker", max_abandoned=max_abandoned)


async def _until_abandoned_settles(workers: OwnedWorkers) -> None:
    """Wait for the count to reach zero, or give up and let the assertion report it.

    The release happens on the worker thread, so waiting on the loop alone would be
    a race on a busy machine — and a bare ``settle`` that usually passed would be
    the worst of both.
    """
    for _ in range(int(_RENDEZVOUS_TIMEOUT_SECONDS * 100)):
        if workers.abandoned == 0:
            return
        await asyncio.sleep(0.01)


async def _abandon_one(workers: OwnedWorkers, blocker: _Blocking) -> asyncio.Task[str]:
    """Start ``blocker`` on a worker, then stop waiting for it.

    Returns the cancelled task, already settled, so the caller can assert on it.
    """
    task = asyncio.ensure_future(workers.run(blocker))
    await asyncio.to_thread(blocker.entered.wait, _RENDEZVOUS_TIMEOUT_SECONDS)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


async def test_the_result_comes_back() -> None:
    assert await _workers().run(lambda: "vectors") == "vectors"


async def test_the_callables_exception_arrives_unwrapped() -> None:
    # The internal vocabulary stops at this seam: whatever the work raised is what
    # the caller catches, so the embedder can translate at its own boundary rather
    # than unpicking a wrapper this layer added.
    sentinel = RuntimeError("the backend said no")

    def failing() -> str:
        raise sentinel

    with pytest.raises(RuntimeError) as caught:
        await _workers().run(failing)

    assert caught.value is sentinel


async def test_the_work_runs_on_a_daemon_thread_this_object_owns() -> None:
    """ADR-0118 §7's second and third clauses, at their narrowest.

    A daemon thread, so neither hub shutdown nor interpreter shutdown joins it —
    "a containment mechanism that makes process exit wait on work that will not
    return has moved the hang rather than bounded it". And a thread this object
    started, so an abandoned worker consumes none of the capacity the SQLite
    stores take from the loop's default executor.
    """
    observed: list[threading.Thread] = []

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="default-executor") as pool:
        asyncio.get_running_loop().set_default_executor(pool)
        await _workers().run(lambda: observed.append(threading.current_thread()))

    [worker] = observed
    assert worker.daemon
    assert worker.name == "test-embed-worker"
    assert worker is not threading.current_thread()
    # Not merely "some other thread": not one of the default executor's, which is
    # the pool `asyncio.to_thread` and every SQLite store's `_run_to_completion`
    # share. Named rather than counted, because a pool creates its threads lazily
    # and an unused pool has none to compare against.
    assert not worker.name.startswith("default-executor")


async def test_an_occupied_default_executor_does_not_delay_the_work() -> None:
    """The corollary, stated behaviourally so a refactor back to ``to_thread`` fails.

    The default executor is given exactly one thread and that thread is occupied.
    An implementation that submitted there would queue behind it and never finish;
    this one is unaffected, which is the property ADR-0118 §7 asks for read in the
    other direction — the stores and the embedder do not compete for one pool.
    """
    occupied = _Blocking()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            loop = asyncio.get_running_loop()
            loop.set_default_executor(pool)
            hogged = loop.run_in_executor(pool, occupied)
            await asyncio.to_thread(occupied.entered.wait, _RENDEZVOUS_TIMEOUT_SECONDS)

            async with asyncio.timeout(_RENDEZVOUS_TIMEOUT_SECONDS):
                assert await _workers().run(lambda: "vectors") == "vectors"

            occupied.release()
            await hogged
    finally:
        occupied.release()


async def test_a_cancelled_caller_abandons_its_worker_and_the_count_says_so(
    released: list[_Blocking],
) -> None:
    # The deadline stops the caller waiting; it does not stop the worker
    # (ADR-0118 §7). The count is what makes that abandonment honest rather than
    # a leak nobody is counting.
    workers = _workers()
    blocker = _Blocking()
    released.append(blocker)

    await _abandon_one(workers, blocker)

    assert workers.abandoned == 1


async def test_an_abandoned_worker_releases_the_count_when_it_finishes(
    released: list[_Blocking],
) -> None:
    """A backend that recovers clears the bound, and clears it at once.

    The count is keyed to the *worker* rather than to the coroutine, and the worker
    is finished the instant its callable returns — so the release happens before
    the (discarded) result is delivered, and a caller that abandoned one worker is
    not refused by a thread that has already stopped working.
    """
    workers = _workers()
    blocker = _Blocking()
    released.append(blocker)
    await _abandon_one(workers, blocker)

    blocker.release()
    await _until_abandoned_settles(workers)

    assert workers.abandoned == 0
    assert await workers.run(lambda: "vectors") == "vectors"


async def test_a_call_at_the_bound_is_refused_and_starts_nothing(
    released: list[_Blocking],
) -> None:
    """ADR-0118 §7's containment, at the moment it bites.

    "A wedged worker means the next call is refused at once instead of dispatching
    a second one." Two abandoned workers is this seam's bound, so the third call is
    the one refused — and it must be refused *before* a thread is started, or the
    bound would be a report rather than a containment.
    """
    workers = _workers(max_abandoned=2)
    for _ in range(2):
        blocker = _Blocking()
        released.append(blocker)
        await _abandon_one(workers, blocker)

    started = threading.Event()
    with pytest.raises(WorkersExhaustedError, match="abandoned embedding worker"):
        await workers.run(started.set)

    assert workers.abandoned == 2
    assert not started.is_set(), "the refused call started a worker anyway"


async def test_healthy_concurrent_calls_are_not_refused(released: list[_Blocking]) -> None:
    """The bound is over *abandoned* workers, and this is why that matters.

    ``Embedder.embed`` is reached concurrently — ``SqliteMemoryStore.search``
    embeds an interactive query on the same loop that runs the scheduler's write
    path — so a reservation held by any *running* worker would turn ordinary
    concurrency into a fault. More calls run at once here than the abandoned bound
    admits, and none of them is refused.
    """
    workers = _workers(max_abandoned=1)
    blockers = [_Blocking(result=f"batch-{index}") for index in range(4)]
    released.extend(blockers)

    calls = [asyncio.ensure_future(workers.run(blocker)) for blocker in blockers]
    for blocker in blockers:
        await asyncio.to_thread(blocker.entered.wait, _RENDEZVOUS_TIMEOUT_SECONDS)
    for blocker in blockers:
        blocker.release()

    async with asyncio.timeout(_RENDEZVOUS_TIMEOUT_SECONDS):
        assert await asyncio.gather(*calls) == ["batch-0", "batch-1", "batch-2", "batch-3"]
    assert not any(blocker.timed_out for blocker in blockers)
    assert workers.abandoned == 0


async def test_a_worker_that_finished_first_is_not_counted_as_abandoned() -> None:
    """The race the shared lock closes, driven at the window where it happens.

    A cancellation arriving as the worker returns has two possible outcomes and
    **both must settle at zero**: either the delivery won, and the call returns its
    result with nothing to abandon, or the cancellation won by a hair and the count
    is released by the ``finally`` already running. What must not happen is a count
    that survives a thread which has stopped — the seam would then refuse calls
    forever over work that finished.
    """
    workers = _workers()
    finished = threading.Event()

    def quick() -> str:
        finished.set()
        return "vectors"

    task = asyncio.ensure_future(workers.run(quick))
    await asyncio.to_thread(finished.wait, _RENDEZVOUS_TIMEOUT_SECONDS)
    # The worker has returned; the delivery is still in flight on the loop. Cancel
    # into exactly that window.
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await _until_abandoned_settles(workers)

    assert workers.abandoned == 0
    assert await workers.run(lambda: "vectors") == "vectors"


@pytest.mark.parametrize("bound", [0, -1])
def test_a_bound_below_one_is_rejected(bound: int) -> None:
    # Zero would refuse every call after the first abandonment, which is a seam
    # switched off rather than a seam contained.
    with pytest.raises(ValueError, match="max_abandoned must be >= 1"):
        OwnedWorkers(thread_name="test-embed-worker", max_abandoned=bound)


def test_the_callable_is_not_run_on_the_calling_thread() -> None:
    """A guard on the guard: :class:`_Blocking` must really park a *worker*.

    If ``run`` ever executed inline, every rendezvous above would deadlock rather
    than fail, and a reader would have no way to tell the two apart.
    """
    caller = threading.current_thread()
    observed: list[threading.Thread] = []

    async def drive() -> None:
        await _workers().run(lambda: observed.append(threading.current_thread()))

    asyncio.run(drive())

    assert len(observed) == 1
    assert observed[0] is not caller
