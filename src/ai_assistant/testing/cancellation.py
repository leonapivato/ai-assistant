"""Scaffolding for the cancellation obligation ``core.protocols`` states (ADR-0060).

``core/protocols.py``'s module clause says a method that acquires a resource must
not orphan it under cancellation. A conformance suite can only observe that from
outside, and the observation needs one thing the Protocols deliberately do not
provide: a way to hold a call open *inside* the resource it acquired, so the
suite can cancel it there and watch what a second caller can reach. ADR-0060 §3
requires exactly that shape — "with an operation blocked mid-flight, cancelling
the awaiting task must not let a **second** call reach the resource until the
first operation's work has actually finished" — and notes why the weaker version
is worthless: a case that only asserts ``CancelledError`` escapes passes the
*pre*-ADR-0054 code, which raised correctly and released the lock anyway.

So each suite's cancellation case takes a hook, and the types here are what the
hook hands back. Two mechanisms, because the implementations split two ways:

* :class:`ThreadSuspension` — the work runs in a worker thread, which is the
  ADR-0054 shape every ``sqlite3``-backed store has: ``async with self._lock``
  around an ``asyncio.to_thread`` the event loop cannot interrupt.
* :class:`LoopSuspension`, driven by :class:`SuspendableResource` — the work
  suspends on the event loop, which is how a canonical fake models a resource it
  does not really have. ``FakeToolInvoker`` is the reference for that idea
  (ADR-0060 §3); this is the same trick applied to a store's connection rather
  than to a task's cancellation count.

Both satisfy :class:`SuspendedCall`, which is all a suite depends on.

Nothing here is a mechanism ``core`` promotes. ADR-0060 refuses a shared home for
ADR-0054's ``_run_to_completion`` precisely so that subsystems depend on the
*obligation* and not on one way of meeting it; this module is test-side
observation equipment, lives in ``ai_assistant.testing`` with the fakes, and is
unreachable from production code (``lint-imports``).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING, Protocol, final

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

#: How long either side waits for the other before declaring the scenario broken.
#: Generous — it is only ever reached when a test has hung, and a hung suite that
#: fails with a message beats one that fails with a timeout somewhere upstream.
_WAIT_SECONDS = 5.0


async def settle(turns: int = 50) -> None:
    """Yield to the event loop repeatedly, so pending work can reach a stable point.

    A cancellation delivered to another task, or a second caller queueing on a
    lock, needs the loop to run before either is observable. Turns rather than a
    sleep: a duration would trade determinism for wall-clock, and everything a
    conformance case waits on here is loop-bound.
    """
    for _ in range(turns):
        await asyncio.sleep(0)


@final
class ResourceLog:
    """When each call was inside the resource, recorded as it enters and leaves.

    The conformance cases cannot settle "was the second caller blocked?" with a
    wall-clock wait. A timeout cannot tell a caller queued on the resource from
    one that got *in* and was merely slow to finish — a busy executor is enough
    to make the second look like the first — so a timing-based case can pass the
    exact bug it exists to catch. This answers the question directly instead: two
    calls were inside at once, or they were not. It is read after the scenario
    has finished, so nothing races the reading.

    Appends only, from whichever thread is inside the resource; ``list.append``
    is atomic, and every read happens after the scenario is over.
    """

    def __init__(self) -> None:
        """Create an empty log."""
        self._events: list[int] = []

    @contextlib.contextmanager
    def inside(self) -> Iterator[None]:
        """Record one call's time inside the resource."""
        self._events.append(1)
        try:
            yield
        finally:
            self._events.append(-1)

    @property
    def overlapped(self) -> bool:
        """Whether any call entered the resource while another was still inside."""
        depth = 0
        for event in self._events:
            depth += event
            if depth > 1:
                return True
        return False

    @property
    def visits(self) -> int:
        """How many calls have entered the resource so far."""
        return self._events.count(1)


class SuspendedCall(Protocol):
    """Levers over one call held open inside the resource it acquired.

    What a conformance suite needs to drive ADR-0060's case, and no more: wait
    until the call is *demonstrably* inside the resource, then let it out. How
    the call was made to stop there is the implementation's business.

    ADR-0065's input-observation cases take the same two levers over a call held
    at its **first await** rather than inside a resource. The positions differ,
    and so do the clauses they serve, but "wait until it is there, then let it go"
    is the whole of what either case needs — so they share this shape instead of
    declaring a second copy of it.
    """

    async def reached(self) -> None:
        """Wait until the suspended call has arrived at its suspension point.

        Raises:
            AssertionError: If it never arrives.
        """
        ...

    def release(self) -> None:
        """Let the suspended call finish.

        Idempotent, so a suite can release in a ``finally`` without tracking
        whether it already did.
        """
        ...


@final
class ThreadSuspension:
    """A :class:`SuspendedCall` for work that runs in a worker thread.

    The implementation side calls :meth:`hold` *from the worker*; the suite side
    awaits :meth:`reached` and calls :meth:`release`. Blocking the worker is what
    makes the case deterministic: without it, whether the thread is still using
    the connection when the second caller arrives is a race between a disk commit
    and an event-loop tick, and a test that only sometimes exercises the
    invariant is not evidence about it.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased suspension."""
        self._entered = threading.Event()
        self._released = threading.Event()

    def hold(self) -> None:
        """Announce arrival and block the worker until the suite releases it.

        Raises:
            AssertionError: If the suite never releases it.
        """
        self._entered.set()
        if not self._released.wait(_WAIT_SECONDS):  # pragma: no cover - only on a hang
            msg = "the suspended worker was never released"
            raise AssertionError(msg)

    async def reached(self) -> None:
        """Wait — without blocking the event loop — until the worker is inside.

        Raises:
            AssertionError: If the worker never arrives.
        """
        if not await asyncio.to_thread(self._entered.wait, _WAIT_SECONDS):
            msg = "the call never reached its suspension point"  # pragma: no cover
            raise AssertionError(msg)  # pragma: no cover - only on a hang

    def release(self) -> None:
        """Let the worker finish."""
        self._released.set()


@final
class DetachedWork:
    """A :class:`SuspendedCall` for work an ``await`` hands off and cannot recall.

    The shape ``asyncio.to_thread`` has, and the one ADR-0060 §5 records for
    ``FastEmbedEmbedder``: cancelling the awaiting coroutine raises straight away
    while the work runs on to completion and releases what it holds by itself.
    Deliberately *not* :class:`LoopSuspension`'s run-to-completion shape — a fake
    that deferred here would model a stronger seam than the one it stands in for.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased suspension."""
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self) -> None:
        """Suspend the caller until released, or until it is cancelled.

        Raises:
            CancelledError: Immediately, if the awaiting task is cancelled — the
                work is abandoned rather than joined, which is what the caller
                would see from ``asyncio.to_thread``.
        """
        self._entered.set()
        await self._released.wait()

    async def reached(self) -> None:
        """Wait until the suspended call has reached the handoff."""
        async with asyncio.timeout(_WAIT_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the work finish."""
        self._released.set()


@final
class LoopSuspension:
    """A :class:`SuspendedCall` for work that suspends on the event loop.

    Handed out by :meth:`SuspendableResource.suspend_next`; the resource awaits
    :meth:`hold` while it is inside its own lock.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased suspension."""
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self) -> None:
        """Suspend the caller until released, surviving its own cancellation.

        This is ADR-0054's ``_run_to_completion`` in miniature, and it is the
        whole point of the fake modelling anything: the wait is on the *work's*
        completion, not on the cancellable state of the awaiting task, so a
        cancellation delivered here does not unwind out of the enclosing lock
        while the work is still notionally using the resource. The cancellation
        is then re-raised — deferred, never absorbed, which is the module
        clause's second paragraph.

        The wait is a **loop**, not one `shield`-and-re-await, and that matters:
        a second cancellation arriving while the deferred wait runs would
        otherwise escape and unwind out of the lock with the work still pending
        — the exact bug the clause forbids, reintroduced by the fake. ADR-0054's
        helper loops for this reason (``while not done.is_set()``); a fake that
        did not would certify a weaker seam than the one it stands in for.

        Raises:
            CancelledError: Re-raised once the work has finished, if any
                cancellation arrived while it was running. The *first* one, so
                a caller cancelled twice still sees the cancellation it asked
                for rather than a later duplicate.
        """
        self._entered.set()
        work = asyncio.ensure_future(self._released.wait())
        cancellation: asyncio.CancelledError | None = None
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
        if cancellation is not None:
            raise cancellation

    async def reached(self) -> None:
        """Wait until the suspended call is inside the resource."""
        async with asyncio.timeout(_WAIT_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the suspended call finish."""
        self._released.set()


@final
class SuspendableResource:
    """A fake's stand-in for the one connection a durable store serialises.

    A canonical fake owns no connection, so on its own it cannot be a subject for
    ADR-0060's resource clause — and a suite whose only subjects are the three
    ``sqlite3`` stores tests the contract on exactly the implementations that
    already got it right once. This gives a fake the thing the rule is about: a
    resource entered under a lock, which a suite can hold open and cancel inside.

    A fake wraps the body of a durable write in :meth:`held`. A suite arms
    :meth:`suspend_next` first, so the *next* entry stops inside and stays there
    until released — with the lock still held, so a second caller queues rather
    than reaching the resource beside it.
    """

    def __init__(self) -> None:
        """Create a free resource with nothing armed."""
        self._lock = asyncio.Lock()
        self._armed: LoopSuspension | None = None
        self._log = ResourceLog()

    @property
    def log(self) -> ResourceLog:
        """When each call was inside this resource (ADR-0060's case reads it)."""
        return self._log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next entry to :meth:`held` to suspend inside the resource.

        Returns:
            The handle the suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed. Two would silently
                make the second one a no-op, and a case that armed twice is a
                case whose author expected something the resource does not do.
        """
        if self._armed is not None:
            msg = "a suspension is already armed on this resource"
            raise RuntimeError(msg)
        self._armed = LoopSuspension()
        return self._armed

    @contextlib.asynccontextmanager
    async def held(self) -> AsyncIterator[None]:
        """Hold the resource for the duration of the block.

        Uncontended, acquiring the lock does not yield, so wrapping a fake's
        write in this adds no interleaving point that was not there before — the
        atomicity a fake obtains from running to completion on one event loop is
        unchanged, and under contention it is strictly reinforced.
        """
        async with self._lock:
            armed, self._armed = self._armed, None
            with self._log.inside():
                if armed is not None:
                    await armed.hold()
                yield
