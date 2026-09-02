"""A durable :class:`~ai_assistant.core.protocols.RoutingTrail` on SQLite (ADR-0197 §9).

Every other place a model's choice reaches an effect in this system leaves a durable
record: a plan's steps become ``StepExecution`` rows, a permission ruling becomes a
``PermissionDecision``, a source read becomes a ``SourceReadRecord``, an authorised call
becomes a ``ToolInvocation`` (ADR-0192), a memory write becomes a ``MemoryDecision``. A
routed ``forget`` would be the sole exception — and it is the one that destroys the only
evidence of itself, since ``AssistantEngine.forget`` relays ``MemoryStore.delete`` and
nothing more. This is the store that closes that.

**One row per decision, and never per effect.** ADR-0197 §9 writes the row *before* the
act it precedes, so the row states what was **decided** and cannot state what happened:
"a row written before the call cannot say whether the call succeeded without being
rewritten, and rewriting is what an append-only trail is not". The pass's own
``RouteOutcome`` is where what happened is reported. A confirm-owed route therefore
writes **two** rows joined by ``route_id`` — the router's, that this operation on this
subject was put to the user, and the user's answer — which is ADR-0192's own shape,
where an authorisation and the act that spends it are two rows rather than one
rewritten.

**Why here and not in ``orchestration/``.** ADR-0004 §7 charters this subsystem for the
record half of "gated **and** recorded", ADR-0097 §3 answered it in this system's words
for the source-read case, and ADR-0197 §9 places this one beside them: ``orchestration``
consumes contracts and holds no store today, and the routing stage reaches this one by
injection like every other.

**Why not the existing** :class:`~ai_assistant.permissions.audit.SqliteAuditTrail`.
ADR-0197 §9 makes the routing trail a **fourth row kind** that joins neither of ADR-0186
§10's two partitions: a routed operation is never a ``PermissionDecision`` and never a
``SourceReadRecord``. ``PermissionDecision.tool`` is a required ``ToolDefinition``
embedded by value and a routed act has no declaration, so synthesising one would put a
fabricated record into the store whose entire premise is that its records are not
fabricated.

**One class satisfying two Protocols**, structurally: the routing stage names
:class:`~ai_assistant.core.protocols.RoutingRecorder` and can reach only
:meth:`SqliteRoutingTrail.record`, while a future hub-owned read surface (ADR-0197 §11)
names :class:`~ai_assistant.core.protocols.RoutingTrail` and can read. What the split
forecloses is worse than a cursor: a stage handed the whole trail could call ``clear``
and **erase the record of its own decisions**.

The on-disk schema carries a ``meta("schema_version")`` marker, the shape
:mod:`ai_assistant.permissions.reads` and :mod:`ai_assistant.permissions.grants` already
write (ADR-0049 §1). There is no ``_migrate`` here and that is not an omission: version 1
is the first shape this store has ever had, so there is no population of pre-marker files
in the wild and an unlabelled database is one this code is creating now.

Local-first (ADR-0002), and **locally only**: ADR-0197 §9 classifies this a Tier 1 local
store, so ADR-0155 §1's residency clause governs it and nothing here may reach a remote
service. The database file lives under ``Settings.data_dir`` and is created owner-only
(ADR-0004 §4, ADR-0084 §9), and ``ai-assistant-purge`` destroys it as part of destroying
the data directory, with no per-store step (ADR-0126 §1).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.errors import RoutingTrailError
from ai_assistant.core.types import RouteApproval, RoutedOperationRecord
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages the
#: database does, so ADR-0004 §4 reaches them too. SQLite copies the database file's mode
#: onto a sidecar **it creates**, which is what makes restricting the file before the
#: first statement sufficient for those — but that inheritance does not reach one that is
#: *already there*: a ``-journal`` left behind by a crash, or a ``-wal``/``-shm`` from a
#: process that put this file into WAL mode, keeps its own mode across a reopen and then
#: takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")


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
    worker's own result or failure and is re-raised once the thread has finished:
    the caller's task still cancels; what is prevented is connection reuse.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the caller
    is then answered out of an empty ``outcome``, an ``IndexError`` standing in for
    the cause rather than chained to it (#680).

    **The completion wait is submitted at most once** (#697). Absorbing a
    cancellation hands the loop a blocking ``done.wait`` job on the default
    executor; a copy that submits a fresh one per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it. Repeated cancellation of one blocked call then
    occupies the whole pool, which turns one stalled store operation into a process
    that cannot run any thread work at all. Reusing the future costs a local and
    bounds the helper at two executor jobs however many cancellations arrive.

    **The eighth copy of this helper rather than an import from a sibling**, which is
    the tree's established position rather than a fresh choice: each SQLite store
    carries its own, and #506 and #563 already track consolidating the family
    (``_restrict_permissions`` and the transaction idiom respectively). A private
    import from :mod:`ai_assistant.permissions.reads` would make one store's helper
    silently govern another's, and would leave the other six out of the arrangement
    anyway.
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
            # The signal is one job, reused: see the docstring.
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


#: The exclusive upper bound ADR-0197 §9 puts on the cap, inheriting ADR-0185 §6's:
#: "every strictly positive integer below ``2**63``", which is ``Settings``' own
#: ``lt=2**63`` and is exactly the width SQLite can bind. Restated here because the cap is
#: bound as the prune's ``OFFSET`` on **every** append, so a wider one is a store that
#: raises ``OverflowError`` out of its own error boundary on the first record.
_MAX_ROWS_EXCLUSIVE = 2**63

#: The exclusive upper bound on ``recent``'s ``limit``. ADR-0186 §3 requires the refusal
#: **locally and before any I/O**, and ADR-0197 §9 restates it: a Python int is unbounded,
#: and binding one wider than SQLite's signed 64-bit parameter raises ``OverflowError`` —
#: neither ``ValueError`` nor ``RoutingTrailError``, so it would leave this layer's error
#: boundary through a hole. Refused rather than clamped, unlike ``SqliteSourceReadTrail``'s,
#: because ADR-0197 §9 states the domain as ``[1, 2**63)`` rather than as "strictly
#: positive": a bound the store cannot bind is a request it cannot honour, and answering
#: it as though it had been asked for something narrower is the silent substitution
#: ADR-0186 §3 refuses.
_MAX_LIMIT_EXCLUSIVE = 2**63

#: The only on-disk schema this code understands, recorded in ``meta`` so a future schema
#: change has a marker to migrate *from*.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code cannot
#: read is refused *before* the ``routes`` table is created or read — creating a table is
#: a write, and the refusal precedes any write (ADR-0049 §1's ordering, applied here).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The row. ``seq`` is **recording order** and is the store's own rather than a field on
#: the ``core`` model — ADR-0197 §9 requires the prune and both reads to be ordered by the
#: sequence of ``record`` calls and never by ``decided_at``, which is caller-supplied and
#: which a host clock corrected backwards would send the prune after the rows it just
#: wrote. ADR-0083 §10 makes the hub "the only process that opens the … databases", so
#: that sequence is well-defined.
#:
#: ``AUTOINCREMENT`` rather than a bare ``INTEGER PRIMARY KEY``: without it SQLite is free
#: to reuse a rowid once the largest row is gone, and ``clear()`` removes every row
#: including the largest. A reused sequence would make a later row sort before an earlier
#: one, which is the one thing this column exists to prevent.
#:
#: ``id`` is ``UNIQUE`` so the append-once guarantee survives even a bug in the checked
#: read below. ``route_id`` is **not** unique and is indexed instead: a confirm-owed route
#: is two rows under one id by design, and the index is what keeps the state-machine read
#: inside ``record``'s transaction from scanning the whole horizon on every append. The
#: blob is the record; the three columns beside it exist only so SQLite can order,
#: constrain and join.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS routes("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
    "id TEXT NOT NULL UNIQUE, "
    "route_id TEXT NOT NULL, "
    "data TEXT NOT NULL)"
)

_CREATE_ROUTE_INDEX = "CREATE INDEX IF NOT EXISTS routes_by_route ON routes(route_id)"

_NEWEST_FIRST = "SELECT data FROM routes ORDER BY seq DESC"

_RECORDING_ORDER = "SELECT data FROM routes ORDER BY seq ASC"

#: ADR-0197 §9's prune, as one statement inside the transaction that appends. The subquery
#: names the ``seq`` of the row ``max_rows`` places down from the newest; everything at or
#: below it is over the cap. With fewer than ``max_rows + 1`` rows the subquery is empty,
#: ``seq <= NULL`` is ``NULL``, and nothing is deleted — which is why no count is read
#: first.
#:
#: **Blind to a route's state by construction.** There is no predicate here but the
#: sequence, so no prune can be conditioned on a row's ``approval``, ``operation`` or
#: ``route_id`` — including the tempting exemption for a live park's ``OWED`` row, which
#: ADR-0197 §9 refuses by name: "a bound with an exception is a bound an adversary chooses
#: the shape of, and a client that opens parks and abandons them would pin rows the bound
#: exists to evict".
_PRUNE = (
    "DELETE FROM routes WHERE seq <= (SELECT seq FROM routes ORDER BY seq DESC LIMIT 1 OFFSET ?)"
)

#: The answers a route may end on (ADR-0197 §9). Named once so the state machine below
#: reads as the rule rather than as two member comparisons repeated.
_ANSWERS = frozenset({RouteApproval.GIVEN, RouteApproval.REFUSED})


class SqliteRoutingTrail:
    """A persistent, append-only, validating routing trail (ADR-0197 §9).

    Structurally implements both :class:`~ai_assistant.core.protocols.RoutingTrail` and
    :class:`~ai_assistant.core.protocols.RoutingRecorder`, as ``SqliteSourceReadTrail``
    satisfies its own pair. A composition root passes one object to the routing stage and
    to a future read surface alike; what the stage cannot do is *name* ``recent``,
    ``export`` or ``clear``.

    **Rows are stored as their JSON dump and rebuilt on every read**, which is how
    ADR-0021 §4's "detached, validated snapshot" is obtained here without a copy step to
    forget: serialising rebuilds every reachable value, so there is no object graph shared
    with the caller in either direction, and the store cannot hand back a caller-supplied
    subclass.

    **Atomicity** comes from an :class:`asyncio.Lock` around the whole of :meth:`record`,
    with the id check, the ``route_id`` check, the route state machine, the insert and the
    prune running in one ``to_thread`` call inside a single SQLite transaction (ADR-0197
    §9). Two concurrent appends carrying a colliding ``route_id`` therefore cannot both
    observe no conflict and both append; exactly one succeeds and the other raises, and
    the loser's act does not proceed.

    **The store is a record and never a resolution.** Its ``route_id`` rule is a
    consistency check over the rows it **retains**, and never a fact about a park it is
    not the authority for — which is why an answer arriving under a ``route_id`` retaining
    no row is accepted. The park table is the state and knows which ids are live; this
    knows only what it still holds.
    """

    def __init__(self, *, path: Path | str, max_rows: int) -> None:
        """Open (or create) the trail at ``path``, bounded at ``max_rows`` rows.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral trail.
                **Required, with no default**, for ``SqliteAuditTrail``'s reason:
                durability is the whole point, so a default would let the ordinary
                construction produce a trail that forgets everything on restart.
            max_rows: ``Settings.routing_trail_max_rows``. **Required with no default**,
                so a composition states the bound rather than inheriting one this module
                invented; ``Settings`` carries the figure and its argument (ADR-0197 §9).

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``. ``bool`` is an ``int``
                in Python, so ``max_rows=True`` would otherwise be a trail that holds
                **one** row — every routed decision but the last pruned away, and the
                store whose whole point is that a *model* chose to destroy something has
                an answer reporting one decision however many were taken.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``. ``Settings`` refuses both at load; this is the same rule
                restated where the invariant is actually *used*. A trail built in a test
                or from a future configuration that reads no setting must not be able to
                hold a cap that is at capacity before its first append, and must not be
                able to hold one **wider than SQLite can bind**: the cap is bound as the
                prune's ``OFFSET``, and a Python int past that width raises
                ``OverflowError`` — neither ``ValueError`` nor ``RoutingTrailError``, so
                it would leave this layer's error boundary through a hole, on the first
                ``record`` rather than at construction. There is no unlimited spelling and
                none is accepted here either.
            RoutingTrailError: If the database cannot be opened or initialised.
        """
        # **The type check is what makes the range check mean anything**: `bool` is an
        # `int`, so `True` passes every comparison below while meaning a cap of one.
        if type(max_rows) is not int:
            msg = (
                f"the routing trail's cap must be exactly an int, got {max_rows!r} of type "
                f"{type(max_rows).__name__}; a bool passes every comparison below while "
                f"meaning a cap of one (ADR-0197 §9)"
            )
            raise TypeError(msg)
        if not 0 < max_rows < _MAX_ROWS_EXCLUSIVE:
            msg = (
                f"the routing trail's cap must be strictly positive and below 2**63, got "
                f"{max_rows}; there is no unlimited spelling, no sentinel and no zero, and "
                f"a wider cap is one the backing store cannot bind (ADR-0197 §9)"
            )
            raise ValueError(msg)
        self._max_rows = max_rows
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL raises it
            # out of the driver rather than a ``sqlite3.Error``, and a bad path is this
            # layer's fault to report rather than a raw builtin escaping past the
            # ``RoutingTrailError`` boundary this constructor documents. Doubly so here:
            # the constructor already documents ``ValueError`` for the cap it refuses, so
            # an untranslated one from the path reads as that instead (#1933).
            msg = f"failed to open the routing trail at {self._path!r}: {exc}"
            raise RoutingTrailError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is built.
            # SQLite copies the database file's mode onto every rollback journal it
            # creates for it, so a journal opened while the file still carried the process
            # umask is world-readable too — and an interrupted write leaves it on disk
            # holding Tier 1 pages (ADR-0004 §1, §4). `connect` creates the file, so there
            # is something to restrict by the time this runs (#489).
            self._restrict_permissions()
            # `BEGIN IMMEDIATE` takes the write lock before the schema is inspected, so
            # create-and-index is serialised against another process opening the same file.
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                conn.execute(_CREATE_ROUTE_INDEX)
                if not labelled:
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except RoutingTrailError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the routing trail at {self._path!r}: {exc}"
            raise RoutingTrailError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — :data:`_SIDECARS`
        names every file SQLite *may* keep, and a cleanly closed database has none of them
        — so absence is tolerated one name at a time. Nothing else is: a sidecar this
        process cannot restrict is a Tier 1 file it is about to write through, so that
        failure propagates and the open fails.

        A *symlink* under a sidecar's name is skipped rather than followed. ``chmod``
        follows links, and ``os.chmod(follow_symlinks=False)`` is unsupported on Linux, so
        restricting one would silently narrow a file that holds none of this store's data.

        A no-op in memory, where there is no file to restrict.
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
        ``routes`` table is created or read.

        Returns:
            Whether the database already carries a ``schema_version``. ``False`` means it
            does not, and :meth:`_setup` stamps one.

        Raises:
            RoutingTrailError: If the stored version is not one this code understands, is
                not an integer at all, or is not a single unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code created
            # — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing `meta` declared
            # without one, so a corrupt or hand-built file can hold conflicting markers.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the routing trail at {self._path!r} holds {len(rows)} schema_version rows "
                f"({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise RoutingTrailError(msg)
        raw = rows[0][0]
        msg = f"the routing trail at {self._path!r} holds a non-numeric schema_version {raw!r}"
        # The marker this code writes is always TEXT, but `meta` may predate it with a
        # column of no declared type. `int(float("inf"))` raises `OverflowError`, which is
        # neither `ValueError` nor an `AssistantError` and would leave this layer's
        # boundary through a hole. `bool` is an `int`, so it is named rather than left to
        # read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise RoutingTrailError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise RoutingTrailError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the routing trail at {self._path!r} has schema_version={stored}, but this "
                f"code supports only version {_SCHEMA_VERSION}; refusing to open it rather "
                f"than read it blindly"
            )
            raise RoutingTrailError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write, which
        is what puts :meth:`_record_sync`'s two *reads* under it: the id check and the
        route's retained rows both decide whether the append may happen, so a deferred
        begin would let a second process observe the same free id, or the same absent
        answer, between them and the append. The ``asyncio`` lock closes that within one
        process; this closes it against the file. It is also what makes the append and
        ADR-0197 §9's prune one act, so there is no window in which the store is over its
        cap.

        Raises:
            RoutingTrailError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=RoutingTrailError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, record: RoutedOperationRecord) -> None:
        """Append ``record`` (ADR-0197 §9).

        Raises:
            RoutingTrailError: If the record does not satisfy its own model, if its ``id``
                is already recorded under a differing record, if its ``route_id`` is held
                by a retained row of another route, if the sequence is one the route state
                machine does not admit, or if the database refuses the write. One class
                for all of them, because the caller's recourse is identical however the
                write failed: the act this row precedes does not proceed. Pydantic's
                ``ValidationError`` is deliberately not allowed to escape.
        """
        snapshot = _revalidated(record)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)

    def _record_sync(self, snapshot: RoutedOperationRecord) -> None:
        """Check, insert and prune, as one transaction (ADR-0197 §9)."""
        with self._transaction(f"record routed operation {snapshot.id!r}") as conn:
            held = conn.execute("SELECT data FROM routes WHERE id = ?", (snapshot.id,)).fetchone()
            if held is not None:
                if _decode(str(held[0])) == snapshot:
                    # Idempotent over the **whole** frozen record, never over the id
                    # alone: a retried write appends nothing and is not an error, while a
                    # repeating id factory carrying a different decision is refused. The
                    # prune is skipped with it — nothing was appended, so nothing can have
                    # taken the store over its cap.
                    return
                msg = (
                    f"routed operation row {snapshot.id!r} is already recorded with different "
                    f"content; the trail is append-only, so history cannot be rewritten by "
                    f"replaying a write, and the act this row precedes does not proceed"
                )
                raise RoutingTrailError(msg)
            siblings = [
                _decode(str(row[0]))
                for row in conn.execute(
                    "SELECT data FROM routes WHERE route_id = ? ORDER BY seq ASC",
                    (snapshot.route_id,),
                ).fetchall()
            ]
            _check_route(snapshot, siblings)
            conn.execute(
                "INSERT INTO routes(id, route_id, data) VALUES (?, ?, ?)",
                (snapshot.id, snapshot.route_id, snapshot.model_dump_json()),
            )
            # The offset is `max_rows` rather than `max_rows - 1`: the subquery names the
            # newest row that is *over* the cap, and everything at or below its `seq`
            # goes. Inside the transaction that appends, which is why ADR-0197 §9 adds no
            # scheduler job for it.
            conn.execute(_PRUNE, (self._max_rows,))

    # --- the read path ----------------------------------------------------

    async def recent(self, *, limit: int) -> tuple[RoutedOperationRecord, ...]:
        """Return up to ``limit`` rows, newest-**recorded** first.

        Raises:
            ValueError: If ``limit`` is outside ``[1, 2**63)``. Refused locally and before
                any I/O (ADR-0186 §3): SQLite reads ``LIMIT -1`` as *no limit at all*, so
                the one call offering a bounded read of a Tier 1 store would become the
                unbounded read it exists to avoid, and a Python int wider than a signed
                64-bit parameter raises ``OverflowError`` out of this layer's boundary.
            RoutingTrailError: If the trail cannot be read.
        """
        if not 0 < limit < _MAX_LIMIT_EXCLUSIVE:
            msg = f"limit must be strictly positive and below 2**63, got {limit}"
            raise ValueError(msg)
        async with self._lock:
            rows = await _run_to_completion(self._newest_first_sync, limit)
        return tuple(_decode(row) for row in rows)

    def _newest_first_sync(self, limit: int) -> Sequence[str]:
        """Read newest-recorded first, bounded.

        A static statement with a bound parameter rather than an interpolated ``LIMIT``:
        the bound is the whole point of ``recent``, and a query assembled from a variable
        is how it stops being one.
        """
        try:
            rows = self._conn.execute(f"{_NEWEST_FIRST} LIMIT ?", (limit,)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the routing trail: {exc}"
            raise RoutingTrailError(msg) from exc
        return [str(row[0]) for row in rows]

    async def export(self) -> tuple[RoutedOperationRecord, ...]:
        """Return every row the store holds, in recording order (ADR-0004 §6).

        **The horizon rather than the history**: what the store still holds after
        ADR-0197 §9's prune, and decisions older than the cap are gone.

        Raises:
            RoutingTrailError: If the trail cannot be read.
        """
        async with self._lock:
            rows = await _run_to_completion(self._recording_order_sync)
        return tuple(_decode(row) for row in rows)

    def _recording_order_sync(self) -> Sequence[str]:
        try:
            rows = self._conn.execute(_RECORDING_ORDER).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the routing trail: {exc}"
            raise RoutingTrailError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> None:
        """Destroy every row, for ADR-0007's deletion right.

        Wholesale by design (ADR-0021 §4): the user may burn the book, and nobody may tear
        out a page. This and the prune are the only deletions this store performs.

        Raises:
            RoutingTrailError: If the trail cannot be cleared.
        """
        async with self._lock:
            await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> None:
        """Delete everything in one statement.

        Only ``routes`` is emptied: the ``meta`` schema marker describes the file's shape
        rather than the user's history, so burning the book leaves a database this code
        can still open.
        """
        with self._transaction("clear the routing trail") as conn:
            conn.execute("DELETE FROM routes")

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _check_route(
    snapshot: RoutedOperationRecord, siblings: Sequence[RoutedOperationRecord]
) -> None:
    """Enforce ADR-0197 §9's ``route_id`` rule over the rows the store **retains**.

    Never a fact about a park this store is not the authority for: an answer arriving
    under a ``route_id`` retaining **no** row is accepted, and no ``OWED`` row is required
    to admit one. That is forced by the bound — pruning is by recording order alone, so a
    live park's ``OWED`` row can be pruned while the park is still registered and still
    claimable, and requiring the row would make a *retention* setting decide whether a
    user's approval of a live confirmation is honoured. An orphan ``GIVEN`` costs an
    operator one join that finds no ``OWED``; the refusal would cost the user the
    operation they had just approved and leave the park claimed, its slot released and
    nothing done.

    Args:
        snapshot: The row about to be appended.
        siblings: The rows the store retains under the same ``route_id``, in recording
            order.

    Raises:
        RoutingTrailError: If a retained row of this route disagrees about what the route
            is, or if the sequence is one a route cannot take.
    """
    if not siblings:
        return
    for row in siblings:
        if (row.operation, row.subject, row.conversation_id) != (
            snapshot.operation,
            snapshot.subject,
            snapshot.conversation_id,
        ):
            msg = (
                f"route {snapshot.route_id!r} is already held by a retained row about "
                f"{row.operation.value} on {row.subject!r}; filing two decisions as one route "
                f"would join a destructive act to an authorisation nobody gave it"
            )
            raise RoutingTrailError(msg)
    held = {row.approval for row in siblings}
    if RouteApproval.NOT_OWED in held or snapshot.approval is RouteApproval.NOT_OWED:
        msg = (
            f"route {snapshot.route_id!r} is a read-only route and is exactly one NOT_OWED "
            f"row; a second row of any kind under it — an answer included — is refused "
            f"(ADR-0197 §9)"
        )
        raise RoutingTrailError(msg)
    if snapshot.approval is RouteApproval.OWED and RouteApproval.OWED in held:
        msg = (
            f"route {snapshot.route_id!r} already retains an OWED row; one question was put "
            f"to the user, so a second would be two questions filed as one"
        )
        raise RoutingTrailError(msg)
    if snapshot.approval in _ANSWERS and held & _ANSWERS:
        answered = next(iter(held & _ANSWERS))
        msg = (
            f"route {snapshot.route_id!r} was already answered {answered.value}; a trail "
            f"holding two answers to one question states two incompatible claims about what "
            f"one person decided (ADR-0197 §9)"
        )
        raise RoutingTrailError(msg)


def _revalidated(record: RoutedOperationRecord) -> RoutedOperationRecord:
    """Rebuild ``record`` as a validated :class:`RoutedOperationRecord`.

    ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one. A copy alone
    detaches without checking, so a record corrupted past its frozen model's guard — a
    ``decided_at`` written back as naive, or a confirm-owed row given ``NOT_OWED`` — would
    be stored and then make every later read of the trail incoherent.

    Rebuilt as a ``RoutedOperationRecord`` specifically, not as ``type(record)``: a
    caller's subclass could carry extra fields, and ``extra="forbid"`` refuses them here
    rather than letting them vanish at serialisation and make the stored record differ from
    the one that reloads.

    Raises:
        RoutingTrailError: If the record does not satisfy its own model.
    """
    try:
        return RoutedOperationRecord.model_validate(record.model_dump())
    except ValidationError as exc:
        msg = f"routed operation {record.id!r} is not a valid record: {exc}"
        raise RoutingTrailError(msg) from exc


def _decode(data: str) -> RoutedOperationRecord:
    """Rebuild a stored row from its JSON.

    Raises:
        RoutingTrailError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to hand
            on.
    """
    try:
        return RoutedOperationRecord.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the routing trail holds a record that no longer validates: {exc}"
        raise RoutingTrailError(msg) from exc


__all__ = ["SqliteRoutingTrail"]
