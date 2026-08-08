"""Running an embedder's blocking work off the loop, and containing what it leaks.

The whole of ADR-0118 §7's containment lives here, so
``fastembed_embedder.py`` stays about the *adapter* rather than about how it
survived a backend that stopped returning:

* the work runs on a **daemon thread the embedder owns**, never on the event
  loop's default executor;
* neither hub shutdown nor interpreter shutdown joins it;
* the number of **abandoned** workers alive at once is bounded, and a call
  arriving with the bound already reached is refused at once rather than
  dispatching another one.

**Why not the default executor, and why not a ``ThreadPoolExecutor``.** ADR-0118
§7 reuses ADR-0093 §7's ruling rather than re-deriving it, and
``ai_assistant.readers._source`` is that ruling already built; its module
docstring records both halves of the verification. ``concurrent.futures.thread``
registers an interpreter-exit hook that joins its workers, so ``serve()`` returns,
``asyncio.run`` finishes, and the process then waits on the same stalled work one
layer lower down. ``asyncio.to_thread`` is out for a second reason on top of that
one: it uses the loop's **default** executor, which every SQLite store in this
process also submits to through ADR-0054's ``_run_to_completion`` helper — so a
pool filled by abandoned embedding threads does not degrade embedding, it stalls
every store operation in the hub behind a queue that will not drain (ADR-0118's
Context verifies this). A daemon thread the embedder owns meets both clauses.

**This module is deliberately not shared with** ``readers/_source.py``. Golden
rule 1 forbids one subsystem importing another's concrete module, and the two
shapes are not the same anyway: a reader's ``OneWorker`` bounds *all* outstanding
work at one, because a read holds nothing and the scheduler invokes it serially.
Neither is true here — see :class:`OwnedWorkers` for what that changes and why.

**Abandoning a stalled embedding worker is safe for the store and fatal for the
seam, and ADR-0118 §7 says so in terms.** ADR-0093 §7 could call abandonment
harmless because "a read holds no lock, opens no transaction, writes nothing"; an
abandoned embedding worker can hold ``FastEmbedEmbedder._load_lock``, so nothing
corrupts and no later embed succeeds. Containment therefore buys a live hub with a
dead capability, not a live hub that recovers — recovery from a fully wedged seam
is a hub restart, which ADR-0083 §5 makes a legible remedy.

Every exception this module raises is an **internal vocabulary** class. The
embedder wraps them at its own seam, because only it knows what its documented
boundary promises.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

#: How many **abandoned** workers may be alive before a new call is refused.
#:
#: The property ADR-0118 §7 asks for is that accumulation is bounded — "what must
#: not happen is a scheduler quietly accumulating one stuck thread per interval"
#: (ADR-0093 §7, which §7 reuses). This is the bound, and it is deliberately
#: **not** ADR-0093 §7's literal "at most one outstanding worker": that figure is
#: written for a calendar reader the scheduler invokes serially, and this seam is
#: invoked concurrently — ``SqliteMemoryStore.search`` embeds an interactive query
#: on the same loop that runs the scheduler's write path. A reservation held by
#: *any* running worker would turn ordinary concurrency into a fault, which
#: ADR-0118 §8 nowhere accepts (it changes ``search``'s failure mode to a deadline
#: expiry and to nothing else), and would contradict ``FastEmbedTextModel``'s
#: standing requirement that two in-flight calls reach one loaded model at once.
#:
#: So the count is over workers whose caller has *stopped waiting* — the only ones
#: that can accumulate, because a healthy worker finishes and releases itself. Two
#: rather than one because the shared conformance suite
#: (``tests/models/embedder_contract.py``) requires an ``embed`` issued while one
#: abandoned worker is still running to complete, on the ground that no
#: ``Embedder`` owns an event-loop resource to withhold. The wedged case is still
#: contained: a backend that stops returning strands the second worker too, and
#: every call after that is refused at once, every interval, with a named fault.
_MAX_ABANDONED_WORKERS: Final = 2


class WorkersExhaustedError(Exception):
    """Too many abandoned workers are still alive to start another (ADR-0118 §7).

    A thread blocked in a backend that has stopped returning cannot be killed, so
    the deadline abandons it — and ADR-0060 requires that a resource never be
    "left held with nothing running that will release it". Bounding the abandoned
    count is the strongest form of that available when the runtime will not give
    the thread back: the count cannot grow, the seam keeps reporting the fault on
    every call, and a backend that recovers releases the workers and clears it.

    Nothing is started when this is raised.
    """


class _RunState:
    """Whether one dispatch's worker has finished, and whether it was abandoned.

    Guarded by the owning :class:`OwnedWorkers`' lock, never on its own — the two
    flags are read and written together with the shared count, and separating
    their guards is what would let a worker that finishes exactly as its caller is
    cancelled be counted as abandoned forever.
    """

    __slots__ = ("abandoned", "finished")

    def __init__(self) -> None:
        self.finished = False
        self.abandoned = False


class OwnedWorkers:
    """Runs blocking callables on daemon threads this object owns.

    One instance per embedder. It is not general infrastructure and is deliberately
    not in ``core``: ADR-0118 §7's clauses are an *embedder implementation's*
    obligations, discharged where the dispatch is written, and the shape they force
    is only safe given what an embedding worker does and does not hold.

    **A fresh thread per call rather than a pool**, which is ``readers/_source.py``'s
    choice too. A pool with a fixed set of consumers re-creates the defect: a wedged
    consumer removes capacity, and when every consumer is wedged the queue backs up
    and the hang is back one layer down. A thread per call has no queue to back up,
    and what bounds it is the abandoned count rather than a worker budget.
    """

    def __init__(self, *, thread_name: str, max_abandoned: int = _MAX_ABANDONED_WORKERS) -> None:
        """Create the dispatcher.

        Args:
            thread_name: What each daemon thread calls itself, for an operator
                reading a stack dump. It names the embedder, never a document.
            max_abandoned: How many abandoned workers may be alive before a new
                call is refused. Injected so a test can drive the bound without
                stranding real threads; production uses
                :data:`_MAX_ABANDONED_WORKERS`.

        Raises:
            ValueError: If ``max_abandoned`` is below one. A bound of zero would
                refuse every call after the first abandonment, including the
                overlapping call the shared conformance suite requires to
                complete, and would make the seam unusable rather than contained.
        """
        if max_abandoned < 1:
            msg = f"max_abandoned must be >= 1, got {max_abandoned}"
            raise ValueError(msg)
        self._thread_name = thread_name
        self._max_abandoned = max_abandoned
        self._lock = threading.Lock()
        self._abandoned = 0

    @property
    def abandoned(self) -> int:
        """How many abandoned workers are still alive."""
        with self._lock:
            return self._abandoned

    async def run[T](self, work: Callable[[], T]) -> T:
        """Run ``work`` on a fresh daemon thread and await its result.

        No deadline is applied here, and that is ADR-0118 §2: the deadline belongs
        to the decorating ``Embedder`` the composition root wires, so that it
        composes over *every* implementation rather than binding this one. What
        arrives here on expiry is the cancellation that deadline delivers, which
        is handled exactly as any other cancellation is.

        Args:
            work: The blocking callable.

        Returns:
            Whatever ``work`` returned.

        Raises:
            WorkersExhaustedError: If the abandoned bound is already reached.
                Nothing is started.
            CancelledError: Re-raised unchanged if the awaiting task is cancelled
                — including by the seam's own deadline. The worker is abandoned,
                not joined: it holds nothing another caller's *safety* depends on
                (ADR-0060 §5), and joining it would move the hang rather than bound
                it.
            Exception: Whatever ``work`` raised, unwrapped, for the caller to
                translate at its own seam.
        """
        with self._lock:
            if self._abandoned >= self._max_abandoned:
                msg = (
                    f"{self._abandoned} abandoned embedding worker(s) are still running; "
                    f"the embedding backend has stopped returning and this call is refused "
                    f"rather than stranding another thread"
                )
                raise WorkersExhaustedError(msg)

        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[T] = loop.create_future()
        state = _RunState()
        worker = threading.Thread(
            target=self._work,
            args=(loop, outcome, work, state),
            name=self._thread_name,
            # The whole of §7's exit clause, in one flag.
            daemon=True,
        )
        # A host out of thread resources raises here. Nothing has been counted yet
        # and no worker exists to count, so there is nothing to release — unlike
        # `readers/_source.py`, whose reservation is taken before the start and
        # therefore has to be undone on this path.
        worker.start()

        try:
            return await outcome
        except BaseException:
            # Including `CancelledError`, which is re-raised unchanged. The count
            # is taken under the same lock the worker releases it under, so a
            # worker that finished between the cancellation being requested and
            # this line is not counted as abandoned.
            with self._lock:
                if not state.finished and not state.abandoned:
                    state.abandoned = True
                    self._abandoned += 1
            _abandon(outcome)
            raise

    def _work[T](
        self,
        loop: asyncio.AbstractEventLoop,
        outcome: asyncio.Future[T],
        work: Callable[[], T],
        state: _RunState,
    ) -> None:
        """The daemon thread's body: run ``work``, release, then deliver.

        **Released before the result is delivered, and the order is deliberate**,
        as it is in ``readers/_source.py``. The count is keyed to the *worker*
        rather than to the coroutine, and the worker is finished the instant
        ``work`` returns — so releasing first is both true and the only order under
        which a backend that recovers clears the bound at the moment it recovers
        rather than one delivery later.
        """
        result: T | None = None
        failure: BaseException | None = None
        try:
            result = work()
        except BaseException as exc:
            failure = exc
        finally:
            with self._lock:
                state.finished = True
                if state.abandoned:
                    self._abandoned -= 1
        # A closed loop raises `RuntimeError`: the process is going away and nobody
        # is waiting for this. Exactly the case the daemon flag exists for.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(_deliver, outcome, result, failure)


def _deliver[T](
    outcome: asyncio.Future[T], result: T | None, failure: BaseException | None
) -> None:
    """Settle the future on the loop thread, unless it was already settled."""
    if outcome.done():
        return
    if failure is not None:
        outcome.set_exception(failure)
    else:
        # `result` is `T` whenever `failure` is None; the union is only there
        # because a thread cannot return two values through a `finally`.
        outcome.set_result(result)  # type: ignore[arg-type]


def _abandon[T](outcome: asyncio.Future[T]) -> None:
    """Stop caring about a future whose worker is still running.

    Without this, a worker that eventually fails sets an exception nobody
    retrieves, and asyncio logs "Future exception was never retrieved" against a
    call whose caller already got its deadline error — a spurious traceback on the
    one path an operator most needs to read cleanly.
    """
    outcome.add_done_callback(_swallow)


def _swallow[T](outcome: asyncio.Future[T]) -> None:
    """Retrieve and discard an abandoned worker's failure."""
    if not outcome.cancelled():
        outcome.exception()
