"""Canonical in-memory fakes for ADR-0119's three trace Protocols.

One fake per Protocol, because ADR-0119 §7 splits the seam three ways and the
split is the point: an emitter holds a :class:`~ai_assistant.core.protocols.
TraceSink` and *cannot name* the walk, the ``Engine``'s maintenance operation
holds a :class:`~ai_assistant.core.protocols.TraceRetention`, and only a measure
lane holds the whole :class:`~ai_assistant.core.protocols.TraceStore`. A single
fake would hand every consumer's test the capability its production counterpart
is denied, which is exactly the property ``mypy --strict`` is being asked to
hold.

**They store serialised rows, not objects**, which is how three obligations come
for free rather than by discipline: every read is a detached snapshot, an absent
metric key survives storage as absent, and a row whose ``id`` cannot be read is
representable at all — the case ADR-0119 §13d makes a conformance obligation
because "only the store can see the difference".

**Emission failure is logged rather than raised**, here as in the durable store
(ADR-0119 §5). The fakes log through ``structlog`` with the same event name and
the same three keys, so the shared suite can assert "emission failure is never
silent" against any implementation instead of only against the one with a real
connection.

**They model the resource they do not own** (ADR-0060 §3), through
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the
cancellation case runs against a canonical fake and not only against the
``sqlite3`` store that already gets it right.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.types import EvaluationTrace, TraceChunk, TracePosition
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: The event name every emission failure is logged under, in the fakes and in
#: the durable store alike (ADR-0119 §5). Duplicated rather than shared because
#: ``ai_assistant.testing`` may not import a subsystem (golden rule 1) — the same
#: reason every bound in these fakes is duplicated from its production twin.
TRACE_NOT_RECORDED = "trace_not_recorded"

#: The order key a walk resumes above when it has seen nothing — the store's
#: floor (ADR-0119 §7a). Zero because these fakes key rows from one, exactly as a
#: ``rowid`` does, so no issued position can collide with it.
_FLOOR = 0


def _detached(trace: EvaluationTrace) -> str:
    """Rebuild ``trace`` as a validated :class:`EvaluationTrace` and serialise it.

    Read out of the instance's ``__dict__`` rather than through ``model_dump``,
    for ``SqliteSourceGrantStore._revalidated``'s reason: ``model_dump`` is an
    ordinary overridable method, so a subclass could return a mapping that does
    not describe itself and the store would record a *different* trace from the
    one it was handed.

    Args:
        trace: What the emitter passed.

    Returns:
        The JSON form of a rebuilt, validated copy.

    Raises:
        ValidationError: If the object does not satisfy its own model — a caller
            that wrote past ``frozen=True``. Never allowed to reach the emitter:
            :meth:`FakeTraceSink.emit` records it as an emission failure, because
            ADR-0119 §5 forbids a trace-store fault propagating into the work.
    """
    fields = dict(object.__getattribute__(trace, "__dict__"))
    return EvaluationTrace.model_validate(fields).model_dump_json()


def _hydrate(row: str) -> EvaluationTrace:
    """Rebuild a stored row, refusing one whose ``id`` cannot be read.

    ADR-0119 §3: the ``id`` default exists to *mint* an id for a new trace and
    never to stand in for one a stored row was supposed to carry. A fresh UUID
    here would hand back a trace that no longer identifies the event it came
    from, with deduplication and every cross-trace join then operating on a
    fabricated id — so the absence is a fault to report, and the type cannot see
    it because a defaulted field is silent about which case it is in.

    Args:
        row: The stored JSON.

    Returns:
        The trace it encodes.

    Raises:
        TraceStoreError: If the row is not readable JSON, carries no ``id``, or
            no longer validates.
    """
    try:
        payload = json.loads(row)
    except ValueError as exc:
        msg = f"the trace store holds a row that is not readable JSON: {exc}"
        raise TraceStoreError(msg) from exc
    if not isinstance(payload, dict) or "id" not in payload:
        msg = (
            "the trace store holds a row with no readable id; minting one would "
            "hand back a trace that no longer identifies the event it came from "
            "(ADR-0119 §3)"
        )
        raise TraceStoreError(msg)
    try:
        return EvaluationTrace.model_validate(payload)
    except ValidationError as exc:
        msg = f"the trace store holds a row that no longer validates: {exc}"
        raise TraceStoreError(msg) from exc


class _Rows:
    """The append-only rows the three fakes share, keyed by insertion order.

    A key is issued once and never reissued, which is what makes a held
    :class:`TracePosition` a *bound* rather than a reference: a purge deleting
    rows below one cannot disturb it (ADR-0119 §7a).
    """

    def __init__(self) -> None:
        """Create an empty log with nothing issued."""
        self._rows: list[tuple[int, str]] = []
        self._ids: set[str] = set()
        self._next = 1

    @property
    def ids(self) -> frozenset[str]:
        """The trace ids this log physically holds."""
        return frozenset(self._ids)

    def append(self, trace_id: str, row: str) -> None:
        """Append ``row`` under a fresh key."""
        self._rows.append((self._next, row))
        self._ids.add(trace_id)
        self._next += 1

    def plant(self, row: str) -> None:
        """Append a raw ``row`` nothing validated — the corrupt-row lever.

        The one affordance the Protocol cannot offer and the conformance suite
        needs: ADR-0119 §13d's hydration obligation is about a row a *store*
        holds, and no sequence of ``emit`` calls can produce one.
        """
        self._rows.append((self._next, row))
        self._next += 1

    def decoded(self) -> tuple[EvaluationTrace, ...]:
        """Every row, hydrated, in insertion order."""
        return tuple(_hydrate(row) for _, row in self._rows)

    def after(self, key: int, limit: int) -> tuple[tuple[int, str], ...]:
        """Up to ``limit`` rows keyed above ``key``, in insertion order."""
        return tuple(row for row in self._rows if row[0] > key)[:limit]

    def purge_before(self, instant: UtcInstant) -> int:
        """Drop every row whose trace occurred strictly before ``instant``."""
        kept = []
        removed = 0
        for key, row in self._rows:
            trace = _hydrate(row)
            if trace.occurred_at < instant:
                self._ids.discard(trace.id)
                removed += 1
            else:
                kept.append((key, row))
        self._rows = kept
        return removed


def _read_position(after: TracePosition | None) -> int:
    """Decode ``after`` into this store's order key.

    Args:
        after: The caller-held position, or ``None`` for the floor.

    Returns:
        The key to resume above.

    Raises:
        ValueError: If the token is not one this store's encoding could have
            issued. A caller-held position this store did not issue is a caller
            bug, not recoverable state (ADR-0119 §7a).
    """
    if after is None:
        return _FLOOR
    try:
        key = int(after.token)
    except ValueError as exc:
        msg = f"{after.token!r} is not a position this store issued"
        raise ValueError(msg) from exc
    if key < _FLOOR:
        msg = f"{after.token!r} is not a position this store issued"
        raise ValueError(msg)
    return key


def _checked_limit(limit: int) -> int:
    """Refuse a walk bound of zero or below (ADR-0119 §7a, ADR-0114 §6a).

    Args:
        limit: The bound the caller asked for.

    Returns:
        ``limit``, unchanged.

    Raises:
        ValueError: If it is not strictly positive.
    """
    if limit <= 0:
        msg = f"limit must be strictly positive, got {limit}"
        raise ValueError(msg)
    return limit


class FakeTraceSink:
    """A canonical :class:`~ai_assistant.core.protocols.TraceSink`.

    What an emitter's test is handed: it can append and it cannot read back
    through the Protocol, which is ADR-0119 §7's whole arrangement. The
    :attr:`recorded` property is the *test's* window on what was appended, not a
    seam the code under test could reach.

    It honours the parts of the contract a list gets only if they are written
    down: the detached snapshot, the silent idempotent refusal on a repeated id,
    the swallowed store fault, and the log record that keeps a swallowed fault
    from being a silent one.
    """

    def __init__(self) -> None:
        """Create an empty sink with no scripted failure."""
        self._rows = _Rows()
        self._resource = SuspendableResource()
        self._failure: Exception | None = None

    @property
    def resource(self) -> SuspendableResource:
        """The modelled resource ADR-0060's cancellation case suspends."""
        return self._resource

    @property
    def recorded(self) -> tuple[EvaluationTrace, ...]:
        """Every trace this sink holds, hydrated, in insertion order."""
        return self._rows.decoded()

    def fail_append(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later append (ADR-0119 §5).

        A *store* fault, not a refusal: :meth:`emit` swallows it and logs it, and
        the emitter sees a normal return, because the instrument is subordinate
        to the work it observes.

        Args:
            error: The underlying fault to model. ``None`` scripts a generic one.
        """
        self._failure = error if error is not None else TraceStoreError("the store is unavailable")

    async def emit(self, trace: EvaluationTrace) -> None:
        """Append ``trace``; never let a store fault escape (ADR-0119 §5, §7).

        Args:
            trace: The event to record.
        """
        async with self._resource.held():
            _append(self._rows, trace, failure=self._failure)


class FakeTraceRetention:
    """A canonical :class:`~ai_assistant.core.protocols.TraceRetention`.

    What the ``Engine``'s maintenance operation is handed (ADR-0119 §10): it can
    sweep and it can neither append nor read. :meth:`hold` is the test's way to
    arrange a history, since nothing on this seam can create one.
    """

    def __init__(self, traces: Iterable[EvaluationTrace] = ()) -> None:
        """Create a store holding ``traces``, in the order given.

        Args:
            traces: The history to start from.
        """
        self._rows = _Rows()
        self._resource = SuspendableResource()
        self._failure: Exception | None = None
        self.hold(*traces)

    @property
    def resource(self) -> SuspendableResource:
        """The modelled resource ADR-0060's cancellation case suspends."""
        return self._resource

    @property
    def recorded(self) -> tuple[EvaluationTrace, ...]:
        """Every trace this store holds, hydrated, in insertion order."""
        return self._rows.decoded()

    def hold(self, *traces: EvaluationTrace) -> None:
        """Arrange a history directly, bypassing the seam that has no append."""
        for trace in traces:
            self._rows.append(trace.id, _detached(trace))

    def fail_purge(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later purge.

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                scripts a generic one.
        """
        self._failure = error if error is not None else RuntimeError("the store is unavailable")

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every trace older than ``instant``; return how many.

        Args:
            instant: The horizon; a trace at it is kept.

        Returns:
            How many traces were removed.

        Raises:
            TraceStoreError: If a fault is scripted (:meth:`fail_purge`). This
                one raises: a sweep is not the work being observed, so ADR-0119
                §5's subordination has nothing to say about it.
        """
        async with self._resource.held():
            if self._failure is not None:
                msg = "failed to purge the trace store"
                raise TraceStoreError(msg) from self._failure
            return self._rows.purge_before(instant)


class FakeTraceStore:
    """A canonical :class:`~ai_assistant.core.protocols.TraceStore` — all three seams.

    The whole store, which in production nothing in the request pipeline holds
    (ADR-0119 §7). Its walk is the store's **total insertion order**, never
    ``occurred_at`` order, and it issues a position for every chunk including an
    empty one — so a reader that has caught up can still resume tomorrow.
    """

    def __init__(self, traces: Iterable[EvaluationTrace] = ()) -> None:
        """Create a store holding ``traces``, in the order given.

        Args:
            traces: The history to start from.
        """
        self._rows = _Rows()
        self._resource = SuspendableResource()
        self._append_failure: Exception | None = None
        self._read_failure: Exception | None = None
        self.hold(*traces)

    @property
    def resource(self) -> SuspendableResource:
        """The modelled resource ADR-0060's cancellation case suspends."""
        return self._resource

    @property
    def recorded(self) -> tuple[EvaluationTrace, ...]:
        """Every trace this store holds, hydrated, in insertion order."""
        return self._rows.decoded()

    def hold(self, *traces: EvaluationTrace) -> None:
        """Arrange a history directly, without going through :meth:`emit`."""
        for trace in traces:
            self._rows.append(trace.id, _detached(trace))

    def plant_raw_row(self, row: str) -> None:
        """Plant a row nothing validated — ADR-0119 §13d's hydration lever.

        Args:
            row: The raw stored form, e.g. a trace's JSON with its ``id`` removed.
        """
        self._rows.plant(row)

    def fail_append(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later append (ADR-0119 §5).

        Args:
            error: The underlying fault to model. ``None`` scripts a generic one.
        """
        self._append_failure = (
            error if error is not None else TraceStoreError("the store is unavailable")
        )

    def fail_read(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later walk or purge.

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                scripts a generic one.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("the store is unavailable")
        )

    async def emit(self, trace: EvaluationTrace) -> None:
        """Append ``trace``; never let a store fault escape (ADR-0119 §5, §7).

        Args:
            trace: The event to record.
        """
        async with self._resource.held():
            _append(self._rows, trace, failure=self._append_failure)

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every trace older than ``instant``; return how many.

        Args:
            instant: The horizon; a trace at it is kept.

        Returns:
            How many traces were removed.

        Raises:
            TraceStoreError: If a fault is scripted (:meth:`fail_read`).
        """
        async with self._resource.held():
            self._refuse_if_unreadable("purge the trace store")
            return self._rows.purge_before(instant)

    async def walk(self, *, after: TracePosition | None = None, limit: int) -> TraceChunk:
        """One chunk in insertion order, resuming after ``after`` (ADR-0119 §7a).

        Args:
            after: Where to resume, or ``None`` to start at the floor.
            limit: The most traces to return.

        Returns:
            The chunk, and the position it reached — always present.

        Raises:
            ValueError: If ``limit`` is zero or below, or ``after`` is a position
                this store did not issue.
            TraceStoreError: If a fault is scripted (:meth:`fail_read`), or a row
                cannot be hydrated.
        """
        # Both refusals are local and precede the resource, as ADR-0114 §6a's do:
        # a caller bug is not a reason to queue behind another caller's write.
        bound = _checked_limit(limit)
        resume = _read_position(after)
        async with self._resource.held():
            self._refuse_if_unreadable("read the trace store")
            rows = self._rows.after(resume, bound)
            traces = tuple(_hydrate(row) for _, row in rows)
            reached = rows[-1][0] if rows else resume
            return TraceChunk(traces=traces, position=TracePosition(token=str(reached)))

    def _refuse_if_unreadable(self, what: str) -> None:
        """Raise the scripted read fault, if one is armed.

        Args:
            what: What the caller was doing, read as the tail of ``failed to``.

        Raises:
            TraceStoreError: If a read fault is scripted.
        """
        if self._read_failure is not None:
            msg = f"failed to {what}"
            raise TraceStoreError(msg) from self._read_failure


def _append(rows: _Rows, trace: EvaluationTrace, *, failure: Exception | None) -> None:
    """Append ``trace``, or record why it was not — never raising (ADR-0119 §5).

    Three ways an append does not happen, and all three end the same way: the
    trace is dropped, a Tier 2 log record names the kind, the seam and the
    failure's class, and the caller returns normally. A failure to record a trace
    never propagates into the operation being traced, and it is never silent —
    a missing trace is otherwise indistinguishable from a non-event.

    The repeated id is a *refusal* rather than a fault, and it keeps the first:
    raising is not available here, and overwriting would let a later write
    rewrite the record of an earlier event.

    Args:
        rows: The backing log.
        trace: The event to record.
        failure: A scripted backing-store fault, or ``None``.
    """
    if failure is not None:
        _dropped(trace, failure)
        return
    try:
        row = _detached(trace)
    except ValidationError as exc:
        _dropped(trace, exc)
        return
    if trace.id in rows.ids:
        _dropped(trace, TraceStoreError(f"trace {trace.id!r} is already recorded"))
        return
    rows.append(trace.id, row)


def _dropped(trace: EvaluationTrace, error: Exception) -> None:
    """Log a trace that could not be recorded (ADR-0119 §5).

    The three keys are Tier 2 by construction: the kind and the outcome are enum
    members, the seam is a literal the emitting module wrote, and the error's
    *class* is what ADR-0111 §9 already puts in an operational record — never its
    message, which may quote a row.

    Args:
        trace: The event that was not recorded.
        error: Why it was not.
    """
    _log.warning(
        TRACE_NOT_RECORDED,
        kind=str(trace.kind),
        seam=str(trace.seam),
        error_class=type(error).__name__,
    )


__all__ = [
    "TRACE_NOT_RECORDED",
    "FakeTraceRetention",
    "FakeTraceSink",
    "FakeTraceStore",
]
