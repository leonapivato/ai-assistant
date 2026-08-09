"""The durable trace store on SQLite — the seventh hub-owned database (ADR-0119 §6).

One file, ``traces.db``, under ``Settings.data_dir``, holding one append-only
table. It satisfies all three of ADR-0119 §7's Protocols structurally, so the
composition root hands each collaborator exactly the seam it is entitled to.

**A Tier 2 store, and the only one in this tree** (ADR-0004 §1). Everything a
trace is *about* is Tier 1, so a trace references it — ids, counts, scores,
durations — and never contains it; ADR-0119 §2 makes that a property of
:class:`~ai_assistant.core.types.EvaluationTrace` rather than of this module, so
nothing here needs to redact, filter or inspect what it stores.

**The whole trace is stored as its JSON dump and rebuilt on every read.** That is
how ADR-0119 §13b's detached-snapshot obligation is met without a copy step to
forget — serialising rebuilds every reachable value, so no object graph is shared
with the caller in either direction — and it is also what discharges §13d's
round-trip obligation *structurally*: an absent metric key and an absent
:class:`~ai_assistant.core.types.TraceRecordSet` key are absent from the JSON, so
they come back absent. A schema with ``NOT NULL DEFAULT 0`` columns would erase,
silently and at the persistence layer, the distinction the fault path depends on
— "not observed" is not zero, and an unobserved id set is not an empty one.

**``id`` is a column as well as a JSON field**, which is what lets the store see
the one thing the type cannot: a row whose id cannot be read. The ``id`` default
on ``EvaluationTrace`` exists to *mint* an id for a new trace, and a defaulted
field is silent about the difference between "no id was supplied because this is
a new trace" and "no id was read because the row or the query lost the column".
So :func:`_hydrate` refuses the second rather than minting (ADR-0119 §3).

**Nothing here fails the work it observes** (§5). ``emit`` swallows every store
fault and logs it; only ``walk`` and ``purge_before`` — a measure's read and the
hub's sweep, neither of which is the work being traced — raise.

Local-first (ADR-0002) and locally only. The database file is created owner-only
(ADR-0004 §4, ADR-0084 §9), following the precedent
:mod:`ai_assistant.memory.sqlite_store` set — and it holds no Tier 1 data at all,
so the restriction is defence in depth here rather than the guarantee it is
elsewhere.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.types import (
    EvaluationTrace,
    TraceChunk,
    TracePosition,
    fault_class_of,
)
from ai_assistant.evaluation._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: The event name every emission failure is logged under (ADR-0119 §5). The
#: canonical fakes log the same name with the same keys, so the shared
#: conformance suite can assert "emission failure is never silent" against any
#: implementation.
TRACE_NOT_RECORDED = "trace_not_recorded"

#: What an emission-failure record carries in place of a trace's own kind and
#: seam when the trace could not be revalidated — so the one path on which those
#: fields are *not* known to be Tier 2 writes nothing derived from them (§2, §5).
UNREADABLE_TRACE_FIELD = "unreadable"

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Restricted for the reason
#: :mod:`ai_assistant.permissions.grants` states, and kept identical to the other
#: six stores rather than relaxed for a Tier 2 file: the family is what #506 will
#: consolidate, and a store that opted out would be the one that has to be
#: brought back in.
_SIDECARS = ("-journal", "-wal", "-shm")

#: The only on-disk schema this code understands, recorded in ``meta`` so a future
#: schema change has a marker to migrate *from* — the seam ADR-0049 §1 describes.
#: There is no ``_migrate`` and that is not an omission: version 1 is the first
#: shape this store has ever had, so an unlabelled database is one this code is
#: creating now.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``traces`` table is created or read.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the ``occurred_at`` sort key counts from. Any fixed instant would do.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The order key a walk resumes above when it has seen nothing — the store's
#: floor (ADR-0119 §7a). ``AUTOINCREMENT`` starts at one, so no issued position
#: can collide with it.
_FLOOR = 0

#: **``AUTOINCREMENT``, not a bare ``INTEGER PRIMARY KEY``**, and the difference
#: is ADR-0119 §7a's. A plain rowid is reused after the highest row is deleted, so
#: a key could be issued twice — and a held :class:`TracePosition` would stop
#: being a *bound* and start being a reference to a different trace. Retention
#: deletes from the old end (§10), so the reuse window is narrow rather than
#: absent; making it structurally impossible costs one keyword.
#:
#: ``id`` is ``UNIQUE`` so the idempotency rule survives a bug in the check that
#: enforces it, the way ``grants_revokes`` backs up the grant store's own check.
#: The columns beside ``data`` exist only so SQLite can order, constrain and
#: narrow; the blob is the record, and nothing else is projected out of it —
#: least of all a metric, whose *absence* is a fact a column cannot hold (§3).
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS traces("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "occurred_at_us INTEGER NOT NULL, data TEXT NOT NULL)"
)

#: The purge narrows on ``occurred_at_us`` and nothing else. There is no index on
#: ``seq``: it is the primary key, so the walk is already an index scan.
_INDEXES = ("CREATE INDEX IF NOT EXISTS traces_occurred ON traces(occurred_at_us)",)

#: One chunk of the walk: **insertion order**, never ``occurred_at`` order
#: (ADR-0119 §7a). The emitter stamps the instant, so two traces can carry the
#: same one and a slow sink can land an earlier instant after a later one; an
#: order over instants is therefore neither total nor stable.
_WALK = "SELECT seq, data FROM traces WHERE seq > ? ORDER BY seq LIMIT ?"

_INSERT = "INSERT INTO traces(id, occurred_at_us, data) VALUES (?, ?, ?)"

_PURGE = "DELETE FROM traces WHERE occurred_at_us < ?"


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    The worker records its own outcome and sets a :class:`threading.Event` when it
    physically returns. This coroutine waits on *that* signal — not on the
    cancellable state of any task — so the lock is held for the whole life of the
    worker even if the awaiting task, or a blanket :func:`asyncio.all_tasks`
    cancellation, is cancelled. An absorbed cancellation takes precedence over the
    worker's own result and is re-raised once the thread has finished: the
    caller's task still cancels; what is prevented is connection reuse.

    **The completion wait is submitted at most once** (#697): a copy that
    submitted a fresh one per cancellation would leave every earlier one running,
    and repeated cancellation of one blocked call would occupy the whole executor.

    **The seventh copy of this helper rather than an import from a sibling**,
    which is the tree's established position rather than a fresh choice: each
    SQLite store carries its own, #506 and #563 already track consolidating the
    family, and this package is a leaf that may import nothing but ``core``.

    Args:
        fn: The synchronous work to run.
        *args: Its arguments.

    Returns:
        Whatever ``fn`` returned.

    Raises:
        BaseException: Whatever the worker raised, once it has finished; or the
            absorbed cancellation, which takes precedence.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[BaseException] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except BaseException as exc:  # relayed to the caller once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    waiting: asyncio.Future[Any] | None = None
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``: a float epoch second carrying microsecond precision
    needs sixteen significant digits at present-day values, right at the edge of a
    double, so two instants a microsecond apart could compare equal or invert —
    and this key decides what a purge deletes.

    Args:
        instant: A ``UtcInstant``, already normalised to UTC by ``core``.

    Returns:
        Whole microseconds since 1970-01-01T00:00:00Z.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _detached(trace: EvaluationTrace) -> EvaluationTrace:
    """Rebuild ``trace`` as a validated :class:`EvaluationTrace`.

    Read out of the instance's ``__dict__`` rather than through ``model_dump``,
    for ``SqliteSourceGrantStore._revalidated``'s reason: ``model_dump`` is an
    ordinary overridable method, so a subclass could return a mapping that does
    not describe itself and the store would record a *different* trace from the
    one it was handed.

    Args:
        trace: What the emitter passed.

    **Everything the store goes on to use comes from the returned snapshot**, not
    from the argument: the id it keys the row on, the instant it sorts by, the
    JSON it stores, and the kind and seam a failure record names. A caller that
    wrote past ``frozen=True`` therefore cannot make the stored row and the
    validated object disagree, and cannot put an unvalidated string anywhere.

    Args:
        trace: What the emitter passed.

    Returns:
        A rebuilt, validated copy.

    Raises:
        ValidationError: If the object does not satisfy its own model — a caller
            that wrote past ``frozen=True``. It never reaches the emitter:
            :meth:`SqliteTraceStore.emit` records it as an emission failure,
            because ADR-0119 §5 forbids a trace-store fault propagating into the
            work being traced.
    """
    fields = dict(object.__getattribute__(trace, "__dict__"))
    return EvaluationTrace.model_validate(fields)


def _hydrate(row: str) -> EvaluationTrace:
    """Rebuild a stored row, refusing one whose ``id`` cannot be read.

    ADR-0119 §3 and §13d: this is the one place the type's default could quietly
    fabricate an identity, and only the store can see the difference. A fresh
    UUID here would hand back a trace that no longer identifies the event it came
    from, with deduplication and every cross-trace join then operating on a
    fabricated id.

    Args:
        row: The stored JSON.

    Returns:
        The trace it encodes, as a detached snapshot.

    Raises:
        TraceStoreError: If the row is not readable JSON, carries no ``id``, or no
            longer validates — a corrupted or downgraded database, which is a
            fault to report rather than a record to hand on.
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


def _read_position(after: TracePosition | None) -> int:
    """Decode ``after`` into this store's order key.

    Args:
        after: The caller-held position, or ``None`` for the floor.

    Returns:
        The ``seq`` to resume above.

    Raises:
        ValueError: If the token is not one this store's encoding could have
            issued. A caller-held position this store did not issue is a caller
            bug, not the recoverable state ADR-0111 §7 discards for a *durable*
            cursor (ADR-0119 §7a). A well-formed key this store has not reached
            yet is **not** refused: a position is a bound, and authenticating
            issuance is not something the token carries.
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

    Refused rather than clamped or passed through: SQLite reads ``LIMIT -1`` as
    *no limit at all*, so the one bounded read of this store would become the
    unbounded one it exists to avoid.

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


class SqliteTraceStore:
    """A persistent, append-only ``TraceStore`` — the seventh database (ADR-0119 §6).

    Structurally implements :class:`~ai_assistant.core.protocols.TraceStore`, and
    therefore :class:`~ai_assistant.core.protocols.TraceSink` and
    :class:`~ai_assistant.core.protocols.TraceRetention` too, which is ADR-0119
    §7's "one concrete implements all three". A composition root may pass one of
    these to every emitter as the sink and to the ``Engine``'s maintenance
    operation as the retention seam; what an emitter cannot do is *name*
    :meth:`walk`, because ``mypy --strict`` runs over ``src`` and ``tests`` and
    the attribute is not on the annotated type.

    **Exclusion** comes from an :class:`asyncio.Lock` around each operation, with
    the SQL running in one worker call inside a single ``BEGIN IMMEDIATE``
    transaction. ``IMMEDIATE`` is what makes the append's duplicate check and its
    insert one step against a second *process* on the same file, not merely
    against another coroutine on this loop.

    **No busy timeout is set here, and that is the family's posture rather than
    this store's choice** (#564): no SQLite store in this tree sets one
    deliberately, so setting one here alone would make a seventh store diverge
    from six.
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the trace store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** A measure spans weeks and #829's
                baseline spans a window, so a store that forgot every event on
                restart would satisfy the type and defeat the leg; an ephemeral
                store is available and has to be asked for. It lives under
                ``Settings.data_dir`` in a real deployment (ADR-0119 §6), which is
                the composition root's choice rather than this class's.

        Raises:
            TraceStoreError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection.

        Returns:
            The open connection.

        Raises:
            TraceStoreError: If the database cannot be opened or initialised.
        """
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``.
            msg = f"failed to open the trace store at {self._path!r}: {exc}"
            raise TraceStoreError(msg) from exc
        try:
            # Restricted *before* the first statement, for the reason the six
            # other stores restrict theirs there: SQLite copies the database
            # file's mode onto every journal it creates, and the ``BEGIN
            # IMMEDIATE`` below is such a write (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                for statement in _INDEXES:
                    conn.execute(statement)
                if not labelled:
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except TraceStoreError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the trace store at {self._path!r}: {exc}"
            raise TraceStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault. A *symlink*
        under a sidecar's name is skipped rather than followed, because ``chmod``
        follows links and narrowing a file this store has no business modifying is
        worse than leaving it. A no-op in memory.

        **Duplicated from the six other SQLite stores on purpose** (#506).
        """
        if self._path == ":memory:":
            return
        database = Path(self._path)
        database.chmod(_OWNER_ONLY)
        for suffix in _SIDECARS:
            sidecar = database.with_name(database.name + suffix)
            if sidecar.is_symlink():
                continue
            with contextlib.suppress(FileNotFoundError):
                sidecar.chmod(_OWNER_ONLY)

    def _check_schema_version(self, conn: sqlite3.Connection) -> bool:
        """Refuse a labelled schema this code cannot read; say whether one is labelled.

        Runs inside the setup transaction, after ``meta`` exists and **before** the
        ``traces`` table is created or read.

        Args:
            conn: The connection the setup transaction is open on.

        Returns:
            Whether the database already carries a ``schema_version``.

        Raises:
            TraceStoreError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single
                unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the trace store at {self._path!r} holds {len(rows)} schema_version rows "
                f"({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise TraceStoreError(msg)
        raw = rows[0][0]
        msg = f"the trace store at {self._path!r} holds a non-numeric schema_version {raw!r}"
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise TraceStoreError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise TraceStoreError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the trace store at {self._path!r} has schema_version={stored}, but this "
                f"code supports only version {_SCHEMA_VERSION}; refusing to open it rather "
                f"than read it blindly"
            )
            raise TraceStoreError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first
        write, which is what puts :meth:`_append_sync`'s duplicate *read* under
        it: the check decides whether the append may happen, so a deferred begin
        would let a second process observe the same free id between the check and
        the insert. The ``UNIQUE`` index is the backstop; this is the rule.

        Args:
            what: What the caller is doing, read as the tail of ``failed to``.
            immediate: Whether to take the write lock at ``BEGIN``.

        Returns:
            The transaction context manager.
        """
        return transaction(self._conn, what, error=TraceStoreError, immediate=immediate)

    # --- the write seam ----------------------------------------------------

    async def emit(self, trace: EvaluationTrace) -> None:
        """Append ``trace``. **No trace-store failure escapes** (ADR-0119 §5, §7).

        Three ways an append does not happen, and all three end the same way: the
        trace is dropped, a Tier 2 log record names the kind, the seam and the
        failure's class, and the caller returns normally. A failure to record a
        trace never propagates into the operation being traced, and it is never
        silent — a missing trace is otherwise indistinguishable from a non-event,
        which is the specific way an instrument lies.

        The repeated id is a *refusal* rather than a fault, and it keeps the
        first: raising is not available here, and overwriting would let a later
        write rewrite the record of an earlier event.

        Args:
            trace: The event to record, already stamped by the emitter's clock.

        Raises:
            CancelledError: A cancellation delivered from outside is re-raised
                once the worker has physically finished (ADR-0060 §1). It is a
                ``BaseException``, so the blanket ``except Exception`` below
                cannot absorb it, and an instrument that did would defeat the
                shutdown drain rather than subordinate itself to it.
        """
        try:
            snapshot = _detached(trace)
        except ValidationError as exc:
            # No snapshot, so nothing about this object is known to be Tier 2 —
            # see :func:`_dropped`.
            _dropped(None, exc)
            return
        try:
            async with self._lock:
                await _run_to_completion(
                    self._append_sync,
                    snapshot.id,
                    _sort_key(snapshot.occurred_at),
                    snapshot.model_dump_json(),
                )
        except Exception as exc:  # every store fault, and nothing that is not one
            _dropped(snapshot, exc)

    def _append_sync(self, trace_id: str, occurred_at_us: int, row: str) -> None:
        """Insert the row unless its id is already present, as one transaction.

        Args:
            trace_id: The trace's minted id.
            occurred_at_us: Its instant, as the purge's sort key.
            row: Its JSON.

        Raises:
            TraceStoreError: If the id is already recorded, or the backend fails.
        """
        with self._transaction(f"record trace {trace_id!r}") as conn:
            if conn.execute("SELECT 1 FROM traces WHERE id = ?", (trace_id,)).fetchone():
                msg = f"trace {trace_id!r} is already recorded; the stored one is kept"
                raise TraceStoreError(msg)
            conn.execute(_INSERT, (trace_id, occurred_at_us, row))

    # --- the retention seam ------------------------------------------------

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every trace older than ``instant``; return how many (ADR-0119 §10).

        Args:
            instant: The horizon. A trace whose ``occurred_at`` is strictly before
                it is deleted; one at the instant is kept.

        Returns:
            How many traces were removed.

        Raises:
            TraceStoreError: If the store cannot be written. This one raises: a
                sweep is not the work being observed.
        """
        async with self._lock:
            return await _run_to_completion(self._purge_sync, _sort_key(instant))

    def _purge_sync(self, horizon_us: int) -> int:
        """Delete below the horizon in one statement, counting what it removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it: a separate count is read before SQLite opens
        the write transaction, so a second connection could append between the two
        and be swept without being counted.

        Args:
            horizon_us: The horizon, as a sort key.

        Returns:
            How many rows were removed.
        """
        with self._transaction("purge the trace store") as conn:
            removed = conn.execute(_PURGE, (horizon_us,)).rowcount
        return int(removed)

    # --- the walk ----------------------------------------------------------

    async def walk(self, *, after: TracePosition | None = None, limit: int) -> TraceChunk:
        """One chunk in insertion order, resuming after ``after`` (ADR-0119 §7a).

        Args:
            after: Where to resume, or ``None`` to start at the store's floor.
            limit: The most traces to return.

        Returns:
            The chunk, and the position it reached — **always** present. A chunk
            shorter than ``limit`` means nothing further is present *yet*, never
            that the walk is over.

        Raises:
            ValueError: If ``limit`` is zero or below, or ``after`` is a position
                this store did not issue. Both are refused **before** the lock:
                a caller bug is not a reason to queue behind another caller's
                write.
            TraceStoreError: If the store cannot be read, or holds a row that
                cannot be hydrated.
        """
        bound = _checked_limit(limit)
        resume = _read_position(after)
        async with self._lock:
            rows = await _run_to_completion(self._walk_sync, resume, bound)
        traces = tuple(_hydrate(str(row[1])) for row in rows)
        reached = int(rows[-1][0]) if rows else resume
        return TraceChunk(traces=traces, position=TracePosition(token=str(reached)))

    def _walk_sync(self, resume: int, limit: int) -> Sequence[tuple[int, str]]:
        """Read one chunk of the walk.

        A **deferred** transaction rather than the write form: this reads and
        writes nothing, and taking the write lock would make a measure's read
        contend with the emitters it is measuring.

        Args:
            resume: The ``seq`` to read above.
            limit: The most rows to return.

        Returns:
            ``(seq, data)`` pairs in insertion order.

        Raises:
            TraceStoreError: If the store cannot be read.
        """
        with self._transaction("read the trace store", immediate=False) as conn:
            rows = conn.execute(_WALK, (resume, limit)).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _dropped(snapshot: EvaluationTrace | None, error: Exception) -> None:
    """Log a trace that could not be recorded (ADR-0119 §5).

    The three keys are Tier 2 by construction: the kind is an enum member, the
    seam is a bounded lowercase label, and the error's *class* is what ADR-0111
    §9 already puts in an operational record — never its message, which may quote
    a row.

    **Read off the revalidated snapshot and never off the caller's object**, and
    ``None`` when there is no snapshot because revalidation is what failed. This
    is the trap ADR-0119 §2 names one level down for a fault class: "the refused
    name is not diverted to the log, which is the trap in the obvious fix", and
    ADR-0004 §5 is unconditional — "Logs are Tier 2 only". ``frozen=True`` refuses
    ``trace.seam = …`` and not ``trace.__dict__["seam"] = …``, so a caller that
    wrote past the model puts an arbitrary string on the object; reading it here
    would take the value the store just refused for carrying content and write it
    to the log instead. So the record says a trace was lost and which class lost
    it, and the reserved literal is the whole of what stands in for the rest —
    exactly the shape :data:`~ai_assistant.core.types.UNREPRESENTABLE_FAULT_CLASS`
    takes for the same problem.

    **The error's class goes through the same total conversion a trace's
    ``fault_class`` does** (:func:`~ai_assistant.core.types.fault_class_of`), and
    reading ``type(error).__name__`` here directly would be the leak this function
    exists to prevent, one field over: a provider may raise
    ``type("X" * 65, (Exception,), {})``, and ADR-0119 §2 admits an exception's
    class name only because *the pattern bounds it* — "a name is not a licence to
    carry a payload". A log record is Tier 2 unconditionally (ADR-0004 §5), so the
    bound has to hold on this side of the seam too.

    Args:
        snapshot: The validated copy of the event, or ``None`` if the trace could
            not be revalidated at all.
        error: Why it was not recorded.
    """
    _log.warning(
        TRACE_NOT_RECORDED,
        kind=str(snapshot.kind) if snapshot is not None else UNREADABLE_TRACE_FIELD,
        seam=str(snapshot.seam) if snapshot is not None else UNREADABLE_TRACE_FIELD,
        error_class=fault_class_of(error),
    )


__all__ = ["TRACE_NOT_RECORDED", "UNREADABLE_TRACE_FIELD", "SqliteTraceStore"]
