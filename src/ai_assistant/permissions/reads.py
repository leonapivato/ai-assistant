"""A durable :class:`~ai_assistant.core.protocols.SourceReadTrail` on SQLite (ADR-0185).

ADR-0004 §7 makes access to Tier 0/1 data gated by the ``permissions/`` layer
**and recorded in an audit trail**. ADR-0097 built the gate for a source read;
this builds the record, which ADR-0139 §6 fired into a lane of its own and
ADR-0185 decided. One row per **attempt** — completed, refused, unanswerable,
failed, discarded or unconfirmed alike — written by the same driver that held the
gate, never by the reader.

**Why here and not in ``readers/`` or a new subsystem.** ADR-0004 §7 charters this
subsystem for both halves in one sentence, and ADR-0097 §3 already answered the
question in this system's words: "A source grant is not a new responsibility; it
is the half the package was chartered with, arriving." The recording half is the
same sentence's other clause. ``readers/`` is disqualified by construction: a
``Reader`` "holds no store handle, no writer, no policy and no engine".

**Why not the existing** :class:`~ai_assistant.permissions.audit.SqliteAuditTrail`.
ADR-0097 §4's reason applied to a read: ``PermissionDecision.tool`` is a required
``ToolDefinition`` embedded by value, a read has no declaration, and synthesising
one would put "a fabricated record into the one store whose entire premise is that
its records are not fabricated". ``SqliteAuditTrail``'s invariants compare
``tool``, ``parameters_digest``, ``step_id`` and ``execution_id``, none of which a
read has.

**One class satisfying two Protocols**, structurally: a driver names
:class:`~ai_assistant.core.protocols.SourceReadRecorder` and can reach only
:meth:`SqliteSourceReadTrail.record`, while the hub's read-trail operations name
:class:`~ai_assistant.core.protocols.SourceReadTrail` and can read. That is
ADR-0185 §4's split, and what it forecloses is ADR-0093 §5's cursor — "It may not
be derived from durable state recording what previous runs read."

The on-disk schema carries a ``meta("schema_version")`` marker, the shape
:mod:`ai_assistant.permissions.grants` and :mod:`ai_assistant.planning.sqlite_store`
already write (ADR-0049 §1). There is no ``_migrate`` here and that is not an
omission: version 1 is the first shape this store has ever had, so there is no
population of pre-marker files in the wild and an unlabelled database is one this
code is creating now.

Local-first (ADR-0002), and **locally only**: ADR-0155 §1's residency clause
governs this store, so nothing here may reach a remote service. The database file
is created owner-only (ADR-0004 §4), following the precedent
:mod:`ai_assistant.memory.sqlite_store` set.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.types import SourceReadRecord
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
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

    **The seventh copy of this helper rather than an import from a sibling**, which
    is the tree's established position rather than a fresh choice: each SQLite store
    carries its own, and #506 and #563 already track consolidating the family
    (``_restrict_permissions`` and the transaction idiom respectively). A private
    import from :mod:`ai_assistant.permissions.grants` would make one store's helper
    silently govern another's, and would leave the other five out of the arrangement
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


#: The widest value SQLite will bind to an INTEGER parameter. A Python int is
#: unbounded, so ``recent`` clamps to this before binding ``LIMIT``.
_MAX_SQLITE_INT = 2**63 - 1

#: The exclusive upper bound ADR-0185 §6 puts on the cap — "every strictly positive
#: integer below ``2**63``", which is ``Settings``' own ``lt=2**63`` and is exactly
#: the width SQLite can bind. Restated here because the cap is bound as the prune's
#: ``OFFSET`` on **every** append, so a wider one is a store that raises
#: ``OverflowError`` out of its own error boundary on the first record.
_MAX_ROWS_EXCLUSIVE = 2**63

#: The only on-disk schema this code understands, recorded in ``meta`` so a future
#: schema change has a marker to migrate *from*.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``reads`` table is created or read —
#: creating a table is a write, and the refusal precedes any write (ADR-0049 §1's
#: ordering, applied here).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The row. ``seq`` is **recording order** and is the store's own rather than a
#: field on the ``core`` model — ADR-0185 §6 requires the prune and both reads to
#: be ordered by the sequence of ``record`` calls and never by ``checked_at``,
#: which is caller-supplied and which a host clock corrected backwards would send
#: the prune after the rows it just wrote. ADR-0083 §10 makes the hub "the only
#: process that opens the … databases", so that sequence is well-defined.
#:
#: ``AUTOINCREMENT`` rather than a bare ``INTEGER PRIMARY KEY``: without it SQLite
#: is free to reuse a rowid once the largest row is gone, and ``clear()`` removes
#: every row including the largest. A reused sequence would make a later row sort
#: before an earlier one, which is the one thing this column exists to prevent.
#:
#: ``id`` is ``UNIQUE`` so the write-once guarantee survives even a bug in the
#: checked read below, exactly as the audit trail's ``decisions_resolves`` index
#: backs its own check. The blob is the record; the two columns beside it exist
#: only so SQLite can order and constrain.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS reads("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
    "id TEXT NOT NULL UNIQUE, "
    "data TEXT NOT NULL)"
)

_NEWEST_FIRST = "SELECT data FROM reads ORDER BY seq DESC"

_RECORDING_ORDER = "SELECT data FROM reads ORDER BY seq ASC"

#: ADR-0185 §6's prune, as one statement inside the transaction that appends. The
#: subquery names the ``seq`` of the row ``max_rows`` places down from the newest;
#: everything at or below it is over the cap. With fewer than ``max_rows + 1`` rows
#: the subquery is empty, ``seq <= NULL`` is ``NULL``, and nothing is deleted —
#: which is why no count is read first.
#:
#: **Content-blind by construction.** There is no predicate here but the sequence,
#: so no prune can be conditioned on a record's ``source``, ``use``, ``outcome``,
#: ``grant`` or ``produced`` — the property that keeps a uniform horizon from being
#: the page torn out of the book (ADR-0021 §4, ADR-0097 §4).
_PRUNE = "DELETE FROM reads WHERE seq <= (SELECT seq FROM reads ORDER BY seq DESC LIMIT 1 OFFSET ?)"


class SqliteSourceReadTrail:
    """A persistent, append-only, validating source-read trail (ADR-0185 §4, §6).

    Structurally implements both :class:`~ai_assistant.core.protocols.SourceReadTrail`
    and :class:`~ai_assistant.core.protocols.SourceReadRecorder`, as
    ``SqliteSourceGrantStore`` satisfies ``SourceGrants`` and ``SourceGrantStore``
    at once. A composition root passes one object to a driver and to the hub's
    read-trail operations alike; what the driver cannot do is *name* ``recent``.

    **Records are stored as their JSON dump and rebuilt on every read**, which is
    how ADR-0021 §4's "detached, validated snapshot" is obtained here without a copy
    step to forget: serialising rebuilds every reachable value, so there is no
    object graph shared with the caller in either direction, and the store cannot
    hand back a caller-supplied subclass.

    **Atomicity** comes from an :class:`asyncio.Lock` around the whole of
    :meth:`record`, with the duplicate check, the insert and the prune running in
    one ``to_thread`` call inside a single SQLite transaction (ADR-0185 §12). Two
    concurrent appends therefore cannot both observe a free id, and there is no
    window in which the store is over its cap.

    **The trail is never consulted to decide anything** (ADR-0185 §8). No liveness,
    no scope, no grant history, no bound, no schedule, no cursor and no skip
    decision is derived from it; ``SourceGrants.live`` remains the only answer to
    whether a read may happen. Nothing here offers a query that would make the
    alternative convenient.
    """

    def __init__(self, *, path: Path | str, max_rows: int) -> None:
        """Open (or create) the trail at ``path``, bounded at ``max_rows`` rows.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral trail.
                **Required, with no default**, for ``SqliteAuditTrail``'s reason:
                durability is the whole point, so a default would let the ordinary
                construction produce a trail that forgets everything on restart.
            max_rows: ``Settings.source_read_trail_max_rows``. **Required with no
                default**, so a composition states the bound rather than inheriting
                one this module invented; ``Settings`` carries the figure and its
                argument (ADR-0185 §6).

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``. ``bool`` is an
                ``int`` in Python, so ``max_rows=True`` would otherwise be a trail
                that holds **one** row — every read but the last pruned away, and a
                store whose whole point is that "was this source read after I revoked
                it" has an answer reporting one attempt however many happened. It is
                the flag-where-a-count-belongs hazard ``Settings``' own
                ``_exactly_an_integer`` refuses at load, restated here.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``. ``Settings`` refuses both at load; this is the same rule
                restated where the invariant is actually *used*, exactly as
                ``UpcomingEventStage`` restates its lead window's. A trail built in a
                test or from a future configuration that reads no setting must not be
                able to hold a cap that is at capacity before its first append, and
                must not be able to hold one **wider than SQLite can bind**: the cap
                is bound as the prune's ``OFFSET``, and a Python int past that width
                raises ``OverflowError`` — neither ``ValueError`` nor
                ``ReadTrailError``, so it would leave this layer's error boundary
                through a hole, on the first ``record`` rather than at construction.
                There is no unlimited spelling and none is accepted here either.
            ReadTrailError: If the database cannot be opened or initialised.
        """
        # **The type check is what makes the range check mean anything**, and it is
        # `UpcomingEventStage`'s argument for `lead` applied to a count: `bool` is an
        # `int`, so `True` passes every comparison below while meaning a cap of one.
        if type(max_rows) is not int:
            msg = (
                f"the read trail's cap must be exactly an int, got {max_rows!r} of type "
                f"{type(max_rows).__name__}; a bool passes every comparison below while "
                f"meaning a cap of one (ADR-0185 §6)"
            )
            raise TypeError(msg)
        # Clamping is not available here, and that is the difference from `recent`: a
        # bound above any possible row count is what a caller *asked for* there, while
        # a cap this store cannot bind is a configuration it cannot honour at all.
        if not 0 < max_rows < _MAX_ROWS_EXCLUSIVE:
            msg = (
                f"the read trail's cap must be strictly positive and below 2**63, got "
                f"{max_rows}; there is no unlimited spelling, no sentinel and no zero, "
                f"and a wider cap is one the backing store cannot bind (ADR-0185 §6)"
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
        except (sqlite3.Error, OSError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            msg = f"failed to open the source-read trail at {self._path!r}: {exc}"
            raise ReadTrailError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built. SQLite copies the database file's mode onto every rollback
            # journal it creates for it, so a journal opened while the file still
            # carried the process umask is world-readable too — and an interrupted
            # write leaves it on disk holding Tier 1 pages (ADR-0004 §1, §4).
            # `connect` creates the file, so there is something to restrict by the
            # time this runs (#489; the other SQLite stores have the same ordering).
            self._restrict_permissions()
            # `BEGIN IMMEDIATE` takes the write lock before the schema is inspected,
            # so create-and-index is serialised against another process opening the
            # same file.
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                if not labelled:
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except ReadTrailError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the source-read trail at {self._path!r}: {exc}"
            raise ReadTrailError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — :data:`_SIDECARS`
        names every file SQLite *may* keep, and a cleanly closed database has none of
        them — so absence is tolerated one name at a time. Nothing else is: a sidecar
        this process cannot restrict is a Tier 1 file it is about to write through, so
        that failure propagates and the open fails.

        A *symlink* under a sidecar's name is skipped rather than followed. ``chmod``
        follows links, and ``os.chmod(follow_symlinks=False)`` is unsupported on
        Linux, so restricting one would silently narrow a file that holds none of
        this store's data and that this store has no business modifying. It strands
        no page anywhere this method could not reach: SQLite does not follow such a
        link either — a symlinked ``-journal`` is not a hot journal, so SQLite unlinks
        *the link* at the first statement and writes a real file in its place, which
        inherits the ``0600`` set just above.

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
        ``reads`` table is created or read.

        Returns:
            Whether the database already carries a ``schema_version``. ``False``
            means it does not, and :meth:`_setup` stamps one.

        **An unlabelled database is one this code is creating now.** Unlike the
        audit trail there is no pre-marker population in the wild: version 1 is the
        first shape this store has ever had, so absent is not a legacy state to
        migrate but a file being created. Any *stored* value that is not 1 is either
        a database written by code that knows a schema this one does not, or a
        corrupt marker, and reading it blindly would let a downgrade construct
        successfully and fail later with a raw SQLite error.

        Raises:
            ReadTrailError: If the stored version is not one this code understands,
                is not an integer at all, or is not a single unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code
            # created — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing
            # `meta` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers. A store that cannot say which version it is is a
            # store this code cannot read.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the source-read trail at {self._path!r} holds {len(rows)} schema_version "
                f"rows ({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise ReadTrailError(msg)
        raw = rows[0][0]
        msg = f"the source-read trail at {self._path!r} holds a non-numeric schema_version {raw!r}"
        # The marker this code writes is always TEXT, but `meta` may predate it with
        # a column of no declared type, in which case SQLite hands back whatever was
        # stored — a REAL, a BLOB, a NULL. Only a string or an integer is parsed;
        # `int(float("inf"))` raises `OverflowError`, which is neither `ValueError`
        # nor an `AssistantError` and would leave this layer's boundary through a
        # hole. `bool` is an `int` in Python, so it is named rather than left to read
        # as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise ReadTrailError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise ReadTrailError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the source-read trail at {self._path!r} has schema_version={stored}, but "
                f"this code supports only version {_SCHEMA_VERSION}; refusing to open it "
                f"rather than read it blindly"
            )
            raise ReadTrailError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write,
        which is what puts :meth:`_record_sync`'s duplicate *read* under it: that
        read decides whether the append may happen, so a deferred begin would let a
        second process observe the same free id between it and the append. The
        ``asyncio`` lock closes that within one process; this closes it against the
        file. It is also what makes the append and ADR-0185 §6's prune one act, so
        there is no window in which the store is over its cap.

        Raises:
            ReadTrailError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=ReadTrailError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` and return its id.

        Raises:
            ReadTrailError: If the record does not satisfy its own model, if its id
                is already recorded, or if the database refuses the write. One class
                for all three, because the driver's recourse is identical however
                the write failed (ADR-0185 §12). Pydantic's ``ValidationError`` is
                deliberately not allowed to escape: CONTRIBUTING has this layer
                raise only from the ``AssistantError`` hierarchy.
        """
        snapshot = _revalidated(read)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: SourceReadRecord) -> None:
        """Check, insert and prune, as one transaction (ADR-0185 §12, §6)."""
        with self._transaction(f"record source read {snapshot.id!r}") as conn:
            if conn.execute("SELECT 1 FROM reads WHERE id = ?", (snapshot.id,)).fetchone():
                msg = (
                    f"source read {snapshot.id!r} is already recorded; the trail is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise ReadTrailError(msg)
            conn.execute(
                "INSERT INTO reads(id, data) VALUES (?, ?)",
                (snapshot.id, snapshot.model_dump_json()),
            )
            # The offset is `max_rows` rather than `max_rows - 1`: the subquery names
            # the newest row that is *over* the cap, and everything at or below its
            # `seq` goes. Three statements inside the transaction that appends, which
            # is why ADR-0185 §6 adds no scheduler job for it.
            conn.execute(_PRUNE, (self._max_rows,))

    # --- the read path ----------------------------------------------------

    async def recent(self, *, limit: int = 50) -> list[SourceReadRecord]:
        """Return up to ``limit`` records, newest-**recorded** first.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Refused rather than
                clamped or passed through: SQLite reads ``LIMIT -1`` as *no limit at
                all*, so the one call offering a bounded read of a Tier 1 store
                would become the unbounded read it exists to avoid.
            ReadTrailError: If the trail cannot be read.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        # Clamped *upward* only. A Python int has no width, and binding one wider
        # than SQLite's signed 64-bit parameter raises `OverflowError` — neither
        # `ValueError` nor `ReadTrailError`, so it would leave this layer's error
        # boundary through a hole. A bound above any possible row count means "all
        # of them", which is what the query then returns.
        async with self._lock:
            rows = await _run_to_completion(self._newest_first_sync, min(limit, _MAX_SQLITE_INT))
        return [_decode(row) for row in rows]

    def _newest_first_sync(self, limit: int) -> Sequence[str]:
        """Read newest-recorded first, bounded.

        A static statement with a bound parameter rather than an interpolated
        ``LIMIT``: the bound is the whole point of ``recent``, and a query assembled
        from a variable is how it stops being one.
        """
        try:
            rows = self._conn.execute(f"{_NEWEST_FIRST} LIMIT ?", (limit,)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the source-read trail: {exc}"
            raise ReadTrailError(msg) from exc
        return [str(row[0]) for row in rows]

    async def export(self) -> list[SourceReadRecord]:
        """Return every record the store holds, in recording order (ADR-0004 §6).

        **The horizon rather than the history** (ADR-0185 §10): what the store still
        holds after ADR-0185 §6's prune, and reads older than the cap are gone.

        Raises:
            ReadTrailError: If the trail cannot be read.
        """
        async with self._lock:
            rows = await _run_to_completion(self._recording_order_sync)
        return [_decode(row) for row in rows]

    def _recording_order_sync(self) -> Sequence[str]:
        try:
            rows = self._conn.execute(_RECORDING_ORDER).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the source-read trail: {exc}"
            raise ReadTrailError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Wholesale by design (ADR-0021 §4, ADR-0185 §6): the user may burn the book,
        and nobody may tear out a page. This and the prune are the only deletions
        this store performs.

        Raises:
            ReadTrailError: If the trail cannot be cleared.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        """Delete everything in one statement, counting what the delete removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it: a separate count is read before SQLite opens the
        write transaction, so a second trail on the same file could append between
        the two and be erased without being counted.

        Only ``reads`` is emptied: the ``meta`` schema marker describes the file's
        shape rather than the user's history, so burning the book leaves a database
        this code can still open.
        """
        with self._transaction("clear the source-read trail") as conn:
            removed = conn.execute("DELETE FROM reads").rowcount
        return int(removed)

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _revalidated(read: SourceReadRecord) -> SourceReadRecord:
    """Rebuild ``read`` as a validated :class:`SourceReadRecord`.

    ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one. A copy
    alone detaches without checking, so a record corrupted past its frozen model's
    guard — a ``checked_at`` written back as naive, or a ``REFUSED`` row given a
    ``grant`` — would be stored and then make every later read of the trail
    incoherent.

    Rebuilt as a ``SourceReadRecord`` specifically, not as ``type(read)``: a
    caller's subclass could carry extra fields, and ``extra="forbid"`` refuses them
    here rather than letting them vanish at serialisation and make the stored record
    differ from the one that reloads.

    Raises:
        ReadTrailError: If the record does not satisfy its own model.
    """
    try:
        return SourceReadRecord.model_validate(read.model_dump())
    except ValidationError as exc:
        msg = f"source read {read.id!r} is not a valid record: {exc}"
        raise ReadTrailError(msg) from exc


def _decode(data: str) -> SourceReadRecord:
    """Rebuild a stored record from its JSON.

    Raises:
        ReadTrailError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to
            hand on.
    """
    try:
        return SourceReadRecord.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the source-read trail holds a record that no longer validates: {exc}"
        raise ReadTrailError(msg) from exc


__all__ = ["SqliteSourceReadTrail"]
