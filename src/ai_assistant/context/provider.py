"""The context provider: assembles ``CurrentContext`` from internal sources.

``AssemblingContextProvider`` runs its sources concurrently and merges their
contributions into a single :class:`~ai_assistant.core.types.CurrentContext`
(ADR-0008). It is the only piece here that implements the cross-subsystem
``ContextProvider`` contract; the sources it composes are internal.

Assembly is advisory: a source that raises is skipped (its facet degrades to
absent) so a flaky optional source cannot take down the request pipeline. Only a
genuine wiring bug — two sources claiming the same field, or a missing *required*
field — surfaces as :class:`~ai_assistant.core.errors.ContextError`.
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import ContextError
from ai_assistant.core.types import CurrentContext

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.context.sources import ContextSource

_log = structlog.get_logger(__name__)

_DRAIN_SECONDS: Final = 1.0
"""How long a cancelled source is joined for before it is abandoned (ADR-0033 §1).

It sizes *cleanup*, not work: the drain waits only for sources already told to
stop, and a cooperative one unwinds in a single event-loop turn. It is
deliberately unrelated to ``source_timeout``, which sizes I/O and (because
``asyncio.timeout`` fires exactly once) is no bound on a source that suppresses
cancellation anyway. Its exact value is not a correctness parameter — no
conforming source can observe it — which is why it is a constant rather than a
constructor argument.
"""

_abandoned: set[asyncio.Task[Mapping[str, object]]] = set()
"""Strong references to tasks that outlived the drain (ADR-0033 §3).

``asyncio`` holds only weak references to running tasks, so an abandoned one can
be garbage-collected mid-flight — turning a leak this module describes into
non-deterministic behaviour it does not. Entries are dropped as they complete.
"""


def _forget_abandoned(task: asyncio.Task[Mapping[str, object]], *, name: str) -> None:
    """Drop an abandoned task's reference and record its outcome (ADR-0033 §3).

    ``asyncio.wait`` does not consume a pending task's exception, so a straggler
    that fails after the request is over leaves one unread. The abandoned
    ``gather`` happens to mark it retrieved anyway — it keeps a done-callback on
    each child and reads the exception once its own future is done — so what
    this adds is not silence-avoidance but *visibility*: without it a
    straggler's late failure would vanish into that implementation detail with
    nothing recorded.
    """
    _abandoned.discard(task)
    if task.cancelled():  # it accepted cancellation after all, just late
        _log.debug("abandoned context source was cancelled", source=name)
        return
    exc = task.exception()
    # The failure's class, not its message: a source wraps calendars, tasks and
    # email, so its message can quote the Tier 1 content it was fetching
    # (ADR-0004 §5), exactly as the degradation log below already guards against.
    _log.debug(
        "abandoned context source finished",
        source=name,
        error=None if exc is None else type(exc).__name__,
    )


def _safe_name(source: ContextSource) -> str:
    """A source's name, or a placeholder if even that access raises."""
    try:
        return source.name
    except Exception:  # a pathological source whose name property fails
        return "<unknown>"


def _log_safe_name(source: ContextSource) -> str:
    """:func:`_safe_name`, made total over ``BaseException`` (ADR-0033 §3).

    Resolved while a required source's failure is waiting to be re-raised, so a
    hostile ``name`` must not replace it — masking the failure is exactly what
    this module exists to prevent. :func:`_safe_name` stops at ``Exception``,
    which is enough where its result goes into a message about to be raised
    anyway, and not enough on a path whose only job is to preserve someone
    else's exception.
    """
    try:
        return _safe_name(source)
    except BaseException:  # nothing resolved here may pre-empt the pending failure
        return "<unknown>"


def _first_failure(
    tasks: Sequence[asyncio.Task[Mapping[str, object]]],
) -> BaseException | None:
    """The exception of the first task (in source order) that failed, or ``None``.

    ``asyncio.wait(return_when=FIRST_EXCEPTION)`` returns as soon as any task
    raises but neither says which nor retrieves the exception. Reading it here
    reconstructs the first-exception propagation ``asyncio.gather`` used to give
    the success path, and — by calling ``task.exception()`` — marks the failure
    retrieved so it leaves no unread exception behind. Source order rather than
    completion order is chosen because it is deterministic and matches the merge
    loop; the two coincide for the only wiring that fails today, a single
    required source beside optional ones.

    A cancelled task is skipped: ``task.exception()`` raises ``CancelledError`` on
    one, and a task cancelled at this point can only be one the drain will handle.
    """
    for task in tasks:
        if not task.done() or task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            return exc
    return None


def _is_required(source: ContextSource) -> bool:
    """Whether ``source``'s failure aborts assembly rather than degrading it.

    ADR-0026 §4's optional marker, read as ``getattr(source, "required", False)``
    and deliberately not a ``ContextSource`` Protocol member: a Protocol member
    is mandatory for structural conformance and supplies no default, so declaring
    it would make every existing source non-conforming and a bare
    ``source.required`` would raise ``AttributeError`` inside the very
    degradation path it selects. **Absent means optional**, which is the safe
    default and keeps ADR-0008 §2's seam additive.

    A marker that *raises* is read as absent, for the same reason
    :func:`_safe_name` is defensive: the degradation path must not itself fail on
    a misbehaving source.
    """
    try:
        return bool(getattr(source, "required", False))
    except Exception:  # a source whose marker raises is not thereby required
        return False


class AssemblingContextProvider:
    """Assembles ``CurrentContext`` by merging a set of internal context sources.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ContextProvider`.
    """

    def __init__(
        self, sources: Sequence[ContextSource], *, source_timeout: float | None = 5.0
    ) -> None:
        """Initialise the provider.

        Args:
            sources: The context sources to compose. Their field contributions
                must be disjoint; overlap is treated as a wiring bug.
            source_timeout: Per-source deadline in seconds; a source that exceeds
                it is skipped (its facet degrades to absent) so a hung source
                cannot stall assembly. ``None`` disables it, and with it any
                bound on how long :meth:`assemble` may take — the caller then
                owns that deadline and is expected to impose one (ADR-0033 §4).
                A caller's deadline *is* effective even against a source that
                suppresses cancellation: :meth:`assemble` observes its sources
                with ``asyncio.wait`` rather than awaiting a bare
                ``asyncio.gather``, so a caller's cancellation of :meth:`assemble`
                surfaces promptly and is routed through the bounded drain instead
                of being swallowed by a source that ignores it (issue #231).
                ``source_timeout`` itself is *not* that bound: ``asyncio.timeout``
                fires exactly once, so a suppressing source defeats a numeric
                per-source deadline as readily as it defeats ``None``. The bounds
                that survive that case are the caller's own deadline and the
                post-failure drain, neither of which a ``source_timeout`` value
                turns off.
        """
        self._sources = tuple(sources)
        self._source_timeout = source_timeout

    async def assemble(self) -> CurrentContext:
        """Merge all sources' contributions into a single ``CurrentContext``.

        Raises:
            ContextError: If two sources contribute the same field, the merged
                contributions cannot form a valid context (a required facet is
                missing — e.g. its source failed), or a source marked ``required``
                failed — chiefly ``ClockContextSource`` on a non-conforming clock
                (ADR-0026 §4). A required source's failure of any other type
                propagates as itself, unwrapped.
        """
        contributions = await self._gather_contributions()
        merged: dict[str, object] = {}
        for source, contribution in zip(self._sources, contributions, strict=True):
            for key, value in contribution.items():
                if key in merged:
                    msg = (
                        f"context sources collided on field {key!r} "
                        f"(at source {_safe_name(source)!r})"
                    )
                    raise ContextError(msg)
                merged[key] = value
        try:
            return CurrentContext.model_validate(merged)
        except ValidationError as exc:
            msg = f"could not assemble a valid context: {exc}"
            raise ContextError(msg) from exc

    async def _gather_contributions(self) -> list[Mapping[str, object]]:
        """Run every source concurrently, bounding what a failure or a cancel leaves.

        The sources run as tasks *observed* by ``asyncio.wait`` rather than
        *awaited* by ``asyncio.gather``, and that choice is load-bearing on two
        paths, not one:

        - **A required source fails.** ``wait(return_when=FIRST_EXCEPTION)``
          returns the moment the first task raises — exactly as ``gather``
          propagated the first exception (:func:`_first_failure` recovers which,
          in source order). The siblings are then cancelled and drained before
          that exception is re-raised, unchanged. This only became reachable with
          ADR-0026 §4's required sources: before them ``_safe_contribute``
          degraded everything and nothing raised. A required source failing fast
          beside an optional one blocked in I/O would otherwise return to the
          caller while that source ran on — to its own timeout, or forever when
          ``source_timeout`` is ``None`` — still able to perform a late side
          effect for a request that is over.
        - **The caller cancels ``assemble()``.** Because ``asyncio.wait``
          observes its tasks instead of awaiting them, a caller's
          ``CancelledError`` — its own ``asyncio.timeout``, a shutdown, a
          cancelled request — surfaces here promptly and is routed through the
          same bounded drain. A bare ``await gather(*tasks)`` did not: ``gather``
          does not yield a cancellation until every child has finished, so a
          source that suppresses ``CancelledError`` swallowed the caller's
          deadline whole and this method never returned (issue #231). ADR-0033
          §4's "with ``source_timeout=None`` the caller owns the deadline" is only
          a real offer once the caller's cancellation is actually observed.

        **A source that unwinds within ``_DRAIN_SECONDS`` is finished when this
        method returns or raises**; anything still running past that budget is
        abandoned, still running, and logged (ADR-0033 §§1-3) — whether it is
        ignoring cancellation or merely slow to unwind, a distinction the
        assembler cannot draw. The weaker claim is the true one: nothing the
        assembler can do stops a task that suppresses ``CancelledError``, so
        awaiting it without a bound would not contain it — it would only add the
        caller to what it blocks.

        Raises:
            BaseException: Whatever a ``required`` source raised, unchanged; or
                the caller's own cancellation, re-raised after the drain.
        """
        tasks = [asyncio.ensure_future(self._safe_contribute(source)) for source in self._sources]
        if not tasks:
            # `asyncio.wait` rejects an empty set, and there is nothing to gather,
            # drain, or fail over when there are no sources.
            return []
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        except BaseException:
            # The caller cancelled us (its deadline, a shutdown), or the loop is
            # tearing down. Cancel and drain the siblings on the way out —
            # bounded, so a suppressing source cannot hold the caller's
            # cancellation the way a bare `gather` let it hold a required failure
            # (issue #231) — then re-raise whatever we caught.
            await self._drain(tasks)
            raise
        failure = _first_failure(tasks)
        if failure is not None:
            await self._drain(tasks)
            raise failure
        return [task.result() for task in tasks]

    async def _drain(self, tasks: Sequence[asyncio.Task[Mapping[str, object]]]) -> None:
        """Cancel every task, then join it for at most ``_DRAIN_SECONDS``.

        ``asyncio.wait`` rather than an awaited ``gather``: it *observes* the
        tasks instead of awaiting them and does not re-cancel what is still
        pending, which makes it the only one of the obvious spellings that
        actually bounds this. An ``asyncio.timeout`` wrapped around a ``gather``
        does not — its deadline delivers a cancellation into the gather, which
        re-cancels the same suppressing source and goes on awaiting it
        (ADR-0033 §1). For a source that unwinds promptly this returns in one
        event-loop turn.

        The budget bounds *awaiting*, not wall-clock time. A source that blocks
        the loop in its cleanup — a synchronous ``time.sleep``, a tight CPU loop
        — suspends every timer in the process, this one included; nothing a
        single-threaded loop offers can pre-empt that, and `CONTRIBUTING.md`'s
        "No blocking calls on async code paths" is what rules it out.

        Registration of the stragglers is in a ``finally``, and reads
        ``task.done()`` rather than ``asyncio.wait``'s ``pending`` set, because
        the caller can cancel *this* method mid-drain: the ``await`` then raises
        and every promise ``_abandon`` makes — the strong reference, the
        warning, the retrieved outcome — would be skipped for tasks that outlive
        the method anyway.
        """
        for task in tasks:
            task.cancel()
        interrupted = True
        try:
            await asyncio.wait(tasks, timeout=_DRAIN_SECONDS)
            interrupted = False
        finally:
            stragglers = [
                (task, source)
                for task, source in zip(tasks, self._sources, strict=True)
                if not task.done()
            ]
            if stragglers:
                self._abandon(stragglers, interrupted=interrupted)

    def _abandon(
        self,
        stragglers: Sequence[tuple[asyncio.Task[Mapping[str, object]], ContextSource]],
        *,
        interrupted: bool,
    ) -> None:
        """Give up on tasks still running after the drain, loudly (ADR-0033 §§2-3).

        They may still complete or perform a late side effect; abandoning them
        does not stop that, and joining them would not have either.
        Responsibility for what they do next is the source author's — this log
        is the only signal there will be.

        It does not claim they *ignored* cancellation: a source merely slow to
        unwind lands here too, and the assembler cannot tell the two apart.
        ``interrupted`` separates the one distinction it *can* draw — a drain
        that spent its budget from one the caller cut short — because
        attributing a caller's cancellation to a slow source would point the
        diagnostic at the wrong party.
        """
        named = [(task, _log_safe_name(source)) for task, source in stragglers]
        event = (
            "cancellation drain interrupted; abandoning context sources still running"
            if interrupted
            else "context sources outlasted the cancellation drain; abandoning them still running"
        )
        _log.warning(
            event,
            sources=[name for _, name in named],
            drain_seconds=_DRAIN_SECONDS,
        )
        for task, name in named:
            _abandoned.add(task)
            task.add_done_callback(functools.partial(_forget_abandoned, name=name))

    async def _safe_contribute(self, source: ContextSource) -> Mapping[str, object]:
        """Return a source's contribution, degrading an *optional* failure to an empty one.

        Covers a raise, a timeout (a hung source), and a fault raised while
        *consuming* the returned mapping (a lazy/faulting ``Mapping``) — the
        contribution is materialised here, under the guard, so nothing escapes to
        the merge loop.

        **A source marked ``required`` is not degraded** (ADR-0026 §4). Without
        that distinction the clock source's ``ContextError`` would be swallowed
        and the caller would see only a later "could not assemble a valid
        context" from the missing fields, with the owner label and the cause both
        lost. The decision is taken on a marker the *source* carries
        (:func:`_is_required`) and deliberately **not** on the error's type: a
        future optional source is entitled to raise ``ContextError``, and typing
        the decision would make it abort the request, which is exactly the
        degradation rule ADR-0008 §4 keeps.

        Raises:
            BaseException: Whatever a ``required`` source raised, re-raised
                unchanged — its type and cause are the diagnosis.
        """
        required = _is_required(source)
        try:
            async with asyncio.timeout(self._source_timeout):
                contribution = await source.contribute()
            return dict(contribution)  # materialise now, so a lazy failure degrades here
        except TimeoutError:
            if required:
                raise
            _log.warning(
                "context source timed out; skipping",
                source=_safe_name(source),
                timeout=self._source_timeout,
            )
            return {}
        except Exception as exc:  # advisory: a failing *optional* source degrades, not aborts
            if required:
                raise
            # Resolve the name defensively — the degradation path must not itself
            # raise if a misbehaving source's ``name`` also fails.
            #
            # The failure's *class*, not str(exc): a source wraps calendars,
            # tasks and email, so its exception message can quote the very Tier 1
            # content it was fetching, which ADR-0004 §5 keeps out of logs. The
            # key-based redaction net cannot catch that — an `error` key looks
            # innocuous — so the call site has to.
            _log.warning(
                "context source failed; skipping",
                source=_safe_name(source),
                error=type(exc).__name__,
            )
            return {}
