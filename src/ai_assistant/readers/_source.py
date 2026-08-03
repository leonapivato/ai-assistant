"""Acquiring a filesystem source's bytes, and doing it off the event loop.

The whole of ADR-0093 §7's I/O discipline lives here, so a reader's own module is
about what it *read* rather than about how it survived reading it:

* a source is **opened non-blockingly**, its descriptor is then checked to be a
  **regular file**, and only then is anything read;
* the byte cap is enforced **on the read itself** — at most the cap plus one byte
  is ever consumed;
* the work runs on a **daemon thread the reader owns**, never on the event loop's
  default executor, under a deadline the reader owns, with **at most one
  outstanding worker**.

**Why a daemon thread and not a ``ThreadPoolExecutor``.** ADR-0093 §7 requires
the worker be *terminable at process exit*: "neither service shutdown nor
interpreter shutdown may join it, and a read blocked indefinitely may not delay
or prevent the hub exiting. A daemon thread meets this; a ``ThreadPoolExecutor``
does not." The reason is specific and verified: ``concurrent.futures.thread``
registers an interpreter-exit hook that joins its workers, so ``serve()`` returns,
``asyncio.run`` finishes, and the process then waits on the same stalled syscall
one layer lower down. ``asyncio.to_thread`` is out for the neighbouring reason —
it uses the loop's **default** executor, which ``asyncio.run`` shuts down (i.e.
joins) before returning, so a stalled read hangs teardown after the job has
already failed and reported.

**Abandoning a stalled worker is safe, and it is safe for a reason specific to
this seam.** A read holds no lock, opens no transaction, writes nothing, and its
result is discarded the moment the deadline fires — so there is no state to
corrupt by walking away and nothing for a later run to reconcile. The thread ends
when the kernel returns or when the process does (ADR-0093 §7).

Every exception this module raises is an **internal vocabulary** class, never a
:class:`~ai_assistant.core.errors.ReaderError`. The reader wraps them at its own
seam, because only the reader knows its declared identity and §8's message rule
is written in terms of it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
import threading
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: How much one ``os.read`` asks for. Large enough that an 8 MiB source is a
#: handful of syscalls, small enough that the cap below is never overshot by
#: more than the one byte §7 permits — the request is clamped to the remaining
#: budget, so the chunk size bounds nothing on its own.
_CHUNK_BYTES: Final = 1 << 16

#: ``O_NONBLOCK`` is the load-bearing flag and the rest is hygiene. On POSIX,
#: opening a FIFO for reading **blocks until a writer appears**, so a descriptor
#: check written to reject a FIFO is never reached — the hazard survives the
#: clause written to close it. Opening non-blockingly returns immediately for a
#: FIFO, which is what lets the regular-file test run at all; for a regular file
#: the flag is a no-op, so nothing is paid for the guard (ADR-0093 §7).
#:
#: ``O_CLOEXEC`` is unrelated to the ADR and is ordinary hygiene: a descriptor on
#: the user's calendar must not survive into a child process.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC


class SourceUnavailableError(Exception):
    """The configured source could not be opened or read at all.

    Wraps the ``OSError`` the platform raised — a missing file, a permission
    denial, a stalled mount — so the reader has one class to catch. The cause is
    preserved; its **message** is not logged, because for a missing
    ``/home/alice/Private/therapy.ics`` that message *is* that path (ADR-0093 §8).
    """


class SourceNotRegularFileError(Exception):
    """The descriptor is open but does not name a regular file (ADR-0093 §7).

    A directory, a FIFO, a socket, a device. Decided on the **descriptor**, never
    on the path before opening it, which additionally closes the swap between the
    two operations.

    A directory is the case worth naming, because it is the one a deployment will
    actually hit: ``vdirsyncer``'s default ``filesystem`` storage writes one
    ``.ics`` per item into a directory, and this reader supports the
    ``singlefile`` arrangement instead. Widening §7 to accept a directory is
    **#649**, not a smaller version of this reader.
    """


class SourceTooLargeError(Exception):
    """The source exceeded ``calendar_max_bytes`` (ADR-0093 §5, §7).

    Refused, never truncated: "a truncated reading is indistinguishable from a
    source that simply has fewer entries, and a consumer cannot tell which it
    holds". A deployment with a genuinely larger calendar widens the cap or
    narrows the window, and does so knowingly.
    """


class ReadDeadlineExpiredError(Exception):
    """The read did not finish within ``calendar_read_timeout`` (ADR-0093 §7).

    The reader's **own** deadline, which the corpus already distinguishes from a
    cancellation delivered from outside: ``core/protocols.py``'s cancellation
    preamble allows a deadline "a method itself raises to enforce a deadline it
    owns" to be its own control flow.
    """


class ReadAlreadyOutstandingError(Exception):
    """A worker from an earlier read is still running (ADR-0093 §7).

    A thread blocked in a stalled syscall cannot be killed, so the deadline
    abandons it — and ADR-0060 requires that a resource be "still held exclusively
    by work the method started", never "left held with nothing running that will
    release it". One abandoned worker, with no second read started behind it, is
    the strongest form of that available when the kernel will not give the thread
    back: the count is bounded at one, the reader keeps reporting the fault on
    every tick, and a mount that recovers releases the worker. What must not
    happen is a scheduler quietly accumulating one stuck thread per interval.
    """


def acquire(path: Path, *, max_bytes: int) -> bytes:
    """Open ``path`` and return its bytes, or raise. **Blocking** (ADR-0093 §7).

    Called only from inside :meth:`OneWorker.run`'s thread. Every step here —
    resolving the path, opening it, the ``fstat``, the reads — can block
    indefinitely on a stalled NFS or FUSE mount even for a perfectly ordinary
    regular file, which is exactly why none of it may run on the event loop.

    Args:
        path: The absolute source path, already validated for shape at load.
        max_bytes: ``calendar_max_bytes``. At most ``max_bytes + 1`` bytes are
            consumed; the cap is enforced **on the read**, never by a size check
            performed before it. A source checked for size and then read is a
            source that can grow or be replaced in between, so the cap would
            describe a file that no longer exists by the time the bytes are
            consumed. Reading one byte past the cap and refusing is the form that
            cannot come apart.

    Returns:
        The source's bytes, at most ``max_bytes`` of them.

    Raises:
        SourceUnavailableError: If the platform refused the open or a read.
        SourceNotRegularFileError: If the descriptor is not a regular file.
        SourceTooLargeError: If the source is larger than ``max_bytes``.
    """
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
    except OSError as exc:
        raise SourceUnavailableError from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            msg = "the configured source is not a regular file"
            raise SourceNotRegularFileError(msg)
        return _read_capped(descriptor, max_bytes)
    except OSError as exc:
        raise SourceUnavailableError from exc
    finally:
        # `os.close` on a descriptor this function opened; a failure here is not
        # the read's failure and must not mask the read's own outcome.
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _read_capped(descriptor: int, max_bytes: int) -> bytes:
    """Read at most ``max_bytes + 1`` bytes, refusing as soon as the cap is passed.

    Raises:
        SourceTooLargeError: As soon as more than ``max_bytes`` bytes have arrived.
        OSError: Propagated for the caller to wrap.
    """
    chunks: list[bytes] = []
    consumed = 0
    # One byte of headroom, and no more: enough to *observe* that the source is
    # over the cap, never enough to hold a byte the cap forbids.
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(_CHUNK_BYTES, remaining))
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > max_bytes:
            msg = f"the configured source is larger than the {max_bytes}-byte cap"
            raise SourceTooLargeError(msg)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class OneWorker:
    """Runs one blocking callable off the loop, under a deadline, one at a time.

    Owned by the reader, one instance per reader. It is not general infrastructure
    and is deliberately not in `core`: ADR-0093 §7's clauses are a *reader's*
    obligations, and the shape they force — abandon the thread, keep the
    reservation — is only safe because a read holds nothing (see this module's
    docstring).
    """

    def __init__(self, *, thread_name: str) -> None:
        """Create the worker.

        Args:
            thread_name: What the daemon thread calls itself, for an operator
                reading a stack dump. Tier 2, and supplied by the reader as its
                declared identity — never a path (ADR-0093 §7).
        """
        self._thread_name = thread_name
        self._lock = threading.Lock()
        self._busy = False

    @property
    def outstanding(self) -> bool:
        """Whether a worker from some earlier read is still running."""
        with self._lock:
            return self._busy

    async def run[T](self, work: Callable[[], T], *, seconds: float) -> T:
        """Run ``work`` on a fresh daemon thread and await it under ``seconds``.

        Args:
            work: The blocking callable. It must hold no lock and own no
                transaction, because the deadline path abandons it.
            seconds: ``calendar_read_timeout``, as a float of seconds. Not spelled
                ``timeout`` because that name asks for ``asyncio.timeout``, which
                cancels what it wraps — and there is nothing here to cancel: the
                thread is in a syscall and finishes when the kernel says so.

        Returns:
            Whatever ``work`` returned.

        Raises:
            ReadAlreadyOutstandingError: If a worker is still running. Nothing is
                started.
            ReadDeadlineExpiredError: If ``seconds`` elapses first. The thread is
                abandoned and the reservation stays held until *it* finishes.
            CancelledError: Re-raised unchanged if the caller is cancelled. The
                reservation stays held for the same reason — the thread is still
                in the syscall, and a guard released on "the coroutine exited"
                would clear while the worker is alive (ADR-0093 §7).
            Exception: Whatever ``work`` raised, unwrapped, for the reader to
                translate at its own seam.
        """
        with self._lock:
            if self._busy:
                msg = "a read is already outstanding"
                raise ReadAlreadyOutstandingError(msg)
            self._busy = True

        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[T] = loop.create_future()
        worker = threading.Thread(
            target=self._work,
            args=(loop, outcome, work),
            name=self._thread_name,
            # The whole of §7's exit clause, in one flag.
            daemon=True,
        )
        try:
            worker.start()
        except BaseException:
            # **The reservation is released here and nowhere else on this path,
            # because there is no worker to release it.** `_work`'s `finally` is
            # the only other release, and it never runs if the thread never
            # started — so a host out of thread resources would wedge this reader
            # permanently: every later `read()` refused for an outstanding worker
            # that does not exist, long after the resources recovered. ADR-0060
            # forbids exactly that state, a resource "left held with nothing
            # running that will release it", and the abandonment rule is only
            # honest while the count is bounded by *running* work.
            with self._lock:
                self._busy = False
            raise

        try:
            # `asyncio.wait` rather than `asyncio.wait_for`, because `wait_for`
            # **cancels** what it is waiting on when the timeout fires. There is
            # nothing to cancel: the thread is in a syscall and will finish when
            # the kernel says so, and the future is the only place its outcome
            # can land. `wait` leaves it alone, which is what makes abandonment
            # honest rather than a cancellation that does not cancel anything.
            done, _pending = await asyncio.wait({outcome}, timeout=seconds)
        except BaseException:
            # Including `CancelledError`, which is re-raised unchanged.
            _abandon(outcome)
            raise
        if not done:
            _abandon(outcome)
            msg = f"the read did not complete within {seconds}s"
            raise ReadDeadlineExpiredError(msg)
        return outcome.result()

    def _work[T](
        self, loop: asyncio.AbstractEventLoop, outcome: asyncio.Future[T], work: Callable[[], T]
    ) -> None:
        """The daemon thread's body: run ``work``, release, then deliver.

        **Released before the result is delivered, and the order is deliberate.**
        The reservation is keyed to the *worker* rather than to the coroutine
        (ADR-0093 §7), and the worker is finished the instant ``work`` returns —
        so releasing first is both true and the only order under which a caller
        that awaits a read and immediately starts another is not refused by a
        thread that has already stopped working.
        """
        result: T | None = None
        failure: BaseException | None = None
        try:
            result = work()
        except BaseException as exc:
            failure = exc
        finally:
            with self._lock:
                self._busy = False
        # A closed loop raises `RuntimeError`: the process is going away and
        # nobody is waiting for this. Exactly the case the daemon flag exists for.
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
    read whose caller already got its ``ReaderError`` — a spurious traceback in an
    operator's log, on the one path §8 works hardest to keep quiet.
    """
    outcome.add_done_callback(_swallow)


def _swallow[T](outcome: asyncio.Future[T]) -> None:
    """Retrieve and discard an abandoned worker's failure."""
    if not outcome.cancelled():
        outcome.exception()
