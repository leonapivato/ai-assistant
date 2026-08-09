"""A durable :class:`~ai_assistant.core.protocols.SourceGrantStore` on SQLite (ADR-0097 §4).

ADR-0004 §7 charters this subsystem for both halves of one sentence — "Access to
Tier 0/1 data **and** every side-effecting tool call is gated by the
``permissions/`` layer and recorded in an audit trail" — and only the second had
ever been built. This module is the first half arriving, in the shape ADR-0021 §3
predicted it would take: a second Protocol beside ``ActionPolicy``, backed by a
store rather than by a field.

**The record is the audit record** (ADR-0097 §4). There is no separate log of
grants because there is nothing a log could say that the store does not: the only
writes are appends, a revocation *is* an append, and nothing may be edited or
selectively removed — so this store cannot hold a history that differs from what
happened. ADR-0021 §4's argument is taken over whole: the user may burn the book,
and nobody may tear out a page.

**Where it departs from :mod:`ai_assistant.permissions.audit`, deliberately.**
``SqliteAuditTrail._check_resolution`` refuses a resolution "timestamped before
the confirmation it answers"; :meth:`SqliteSourceGrantStore._check_revocation`
has no such rule, and ADR-0097 §4 rules it out by name. ``decided_at`` is
caller-supplied and this store reads no clock, so a host clock corrected
backwards would make every truthfully-timestamped revocation refusable until
wall-clock time caught up — a large enough correction making a grant
**permanently unrevokable**, which is the one property ``VISION.md`` names that
this store exists to deliver, defeated by an invariant that was protecting
nothing. Liveness is derived from the ``revokes`` relation alone and nothing here
compares two instants.

Local-first (ADR-0002), and **locally only**: ADR-0097 §4 applies ADR-0004 §2's
residency clause to this store by name, so nothing here may reach a remote
service. The database file is created owner-only (ADR-0004 §4, ADR-0084 §9),
following the precedent :mod:`ai_assistant.memory.sqlite_store` set.

**Nothing here mints a grant** (ADR-0097 §8). This module offers no path from a
``Settings`` value, a source path, an already-ingested belief, an upgrade or a
first run to a record: the only way a row appears is a caller handing
:meth:`SqliteSourceGrantStore.record` a ``SourceGrant``, and ADR-0097 §9 makes
the hub's grant operations the only holder of this seam.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.errors import GrantError, InvalidGrantError
from ai_assistant.core.types import SourceGrant
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.types import GrantScope

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance
#: does not reach one that is *already there*: a ``-journal`` left behind by a
#: crash, or a ``-wal``/``-shm`` from a process that put this file into WAL mode,
#: keeps its own mode across a reopen and then takes Tier 1 pages (#490).
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
    cancellation, is cancelled. Nothing here is an :class:`asyncio.Task`: the work
    runs on an executor future and the fallback wait is another, so a task sweep
    finds nothing to cancel out from under the running thread. An absorbed
    cancellation takes precedence over the worker's own result or failure and is
    re-raised once the thread has finished: the caller's task still cancels; what
    is prevented is connection reuse, not the cancellation itself.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the
    caller is then answered out of an empty ``outcome``, an ``IndexError`` standing
    in for the cause rather than chained to it (#680).

    **The completion wait is submitted at most once**, which is where this copy
    diverges from the five it was taken from (#697). Absorbing a cancellation
    hands the loop a blocking ``done.wait`` job on the default executor; a copy
    that submits a fresh one per cancellation leaves every earlier one running,
    because nothing can interrupt a thread parked in ``Event.wait`` before the
    worker sets it. Repeated cancellation of one blocked call then occupies the
    whole pool — measured at eight of eight, starving an unrelated
    ``run_in_executor`` — which turns one stalled store operation into a process
    that cannot run any thread work at all. Reusing the future costs a local and
    bounds the helper at two executor jobs however many cancellations arrive.

    **The sixth copy of this helper rather than an import from a sibling**, which
    is the tree's established position rather than a fresh choice: each SQLite
    store carries its own, and #506 and #563 already track consolidating the family
    (``_restrict_permissions`` and the transaction idiom respectively). A private
    import from :mod:`ai_assistant.permissions.audit` would make one store's
    helper silently govern another's, and would leave the other four out of the
    arrangement anyway.
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

#: The only on-disk schema this code understands, recorded in ``meta`` so a future
#: schema change has a marker to migrate *from* — the seam ADR-0049 §1 describes
#: and the shape :mod:`ai_assistant.permissions.audit` and
#: :mod:`ai_assistant.planning.sqlite_store` already write.
#:
#: **There is no ``_migrate`` here and that is not an omission.** Version 1 is the
#: first shape this store has ever had, so unlike the audit trail there is no
#: population of pre-marker files in the wild to bring forward: an unlabelled
#: database is one this code is creating now, and :meth:`SqliteSourceGrantStore.
#: _check_schema_version` stamps it rather than migrating it.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``grants`` table is created or read —
#: creating a table is a write, and the refusal precedes any write (ADR-0049 §1's
#: ordering, applied here).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the sort key counts from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The columns beside the ``data`` blob exist only so SQLite can order, constrain
# and narrow; the blob is the record. ``source`` and ``revokes`` are the two the
# liveness query reads, and ``decided_at_us`` is the ordering key ``recent`` and
# ``export`` share. ``scope`` is deliberately *not* projected: it is a sequence,
# it is only ever tested for membership, and a column holding a serialised list
# would invite a ``LIKE`` that answers a different question than ``in``.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS grants("
    "id TEXT PRIMARY KEY, source TEXT NOT NULL, decided_at_us INTEGER NOT NULL, "
    "revokes TEXT, data TEXT NOT NULL)"
)

_INDEXES = (
    # A *unique* index, so the one-revocation-per-grant rule (ADR-0097 §4)
    # survives even a bug in `_check_revocation`. SQLite treats NULLs as
    # distinct, so it constrains revoking rows only and leaves granting records
    # unaffected. The mechanical sibling of `decisions_resolves` on the trail.
    "CREATE UNIQUE INDEX IF NOT EXISTS grants_revokes ON grants(revokes)",
    "CREATE INDEX IF NOT EXISTS grants_order ON grants(decided_at_us DESC, id ASC)",
    # The liveness lookup narrows on `source` first, so the index is on it. There
    # is no index expressing "live", because liveness is *derived* from the
    # `revokes` relation (ADR-0097 §4) rather than stored — the anti-join below
    # is what computes it, and an index that claimed to store it would be a
    # second answer free to disagree with the first.
    "CREATE INDEX IF NOT EXISTS grants_source ON grants(source, revokes)",
)

_ORDERED = "SELECT data FROM grants ORDER BY decided_at_us DESC, id ASC"

#: The live grants for one source: granting records (``revokes IS NULL``) that no
#: recorded revocation names. **Liveness is the anti-join and nothing else** —
#: ADR-0097 §4 forbids deciding it by comparing ``decided_at`` values, so no
#: instant appears in this statement at all. The scope test is not here on
#: purpose: ``use in grant.scope`` is a membership test over a decoded tuple, and
#: doing it in SQL would mean matching text against a serialised sequence.
#:
#: Unbounded rather than ``LIMIT 1``: ADR-0097 §4 guarantees at most one row, and
#: a store holding two is corrupt rather than a store to silently pick from.
#: :meth:`SqliteSourceGrantStore._live_sync` reports that instead.
_LIVE_FOR_SOURCE = (
    "SELECT data FROM grants AS g "
    "WHERE g.revokes IS NULL AND g.source = ? "
    "AND NOT EXISTS (SELECT 1 FROM grants AS r WHERE r.revokes = g.id)"
)


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``. Ordering is part of ``recent``'s contract (ADR-0097
    §10), and a float epoch second carrying microsecond precision needs sixteen
    significant digits at present-day values — right at the edge of a double, so
    two records a microsecond apart could compare equal or invert. The subtraction
    below is exact.

    ``decided_at`` is a ``UtcInstant``, already normalised to UTC by ``core``, so
    this is a key over *instants* — which is what makes the DST repeated hour sort
    correctly rather than by wall clock.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


class SqliteSourceGrantStore:
    """A persistent, append-only, validating ``SourceGrantStore``.

    Structurally implements :class:`~ai_assistant.core.protocols.SourceGrantStore`
    and therefore :class:`~ai_assistant.core.protocols.SourceGrants` too, which is
    ADR-0097 §3's "one implementation satisfies both seams" — so a composition root
    may pass one of these to the hub's grant operations as the store and to a
    reader driver as the query seam, and the driver still cannot *name* ``record``.

    **Records are stored as their JSON dump and rebuilt on every read**, which is
    how ADR-0097 §4's "detached, validated snapshot" is obtained here without a
    copy step to forget: serialising rebuilds every reachable value, so there is no
    object graph shared with the caller in either direction, and the store cannot
    hand back a caller-supplied subclass.

    **The snapshot is taken from the instance's own field state**, not from
    ``model_dump()`` — see :func:`_revalidated`. That is the one place this parts
    company with ``SqliteAuditTrail._revalidated``'s otherwise identical shape, and
    ADR-0097 §10 makes it a conformance clause rather than a nicety.

    **Atomicity** (ADR-0097 §4) comes from an :class:`asyncio.Lock` around the
    whole of :meth:`record`, with the duplicate check, the live-grant check, the
    revocation invariants and the insert running in one worker call inside a single
    ``BEGIN IMMEDIATE`` transaction. Two concurrent grants for one source therefore
    cannot both observe none live, which is the guarantee the atomicity clause
    exists for.

    **No busy timeout is set here, and that is the family's posture rather than
    this store's choice** (#564): no SQLite store in this tree sets one
    deliberately, so under cross-process contention ``BEGIN IMMEDIATE`` surfaces
    ``SQLITE_BUSY`` after the driver's default. Setting one here alone would make a
    store diverge from six; #564 is where the family changes together, and
    #563 holds the transaction-idiom half of the same question.
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the grant store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                implementation exists — a grant the user made must still be on file
                after a restart, and ADR-0097 §4 makes the record itself the audit
                record — so a default would let the ordinary construction produce a
                store that forgets every authorisation on restart. An ephemeral
                store is available and has to be asked for.

                It lives under ``Settings.data_dir`` in a real deployment
                (ADR-0097 §4, §9), which is the composition root's choice rather
                than this class's: every other store in this tree is handed its
                path the same way.

        Raises:
            GrantError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``, and a
            # bad path is this layer's fault to report rather than a raw builtin
            # escaping past its error boundary (#238 records the same hole on the
            # audit trail; it is closed here rather than reproduced).
            msg = f"failed to open the grant store at {self._path!r}: {exc}"
            raise GrantError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built. SQLite copies the database file's mode onto every rollback
            # journal it creates for it, so a journal opened while the file still
            # carried the process umask is world-readable too — and an interrupted
            # write leaves it on disk holding Tier 1 pages (ADR-0004 §1, §4). The
            # `BEGIN IMMEDIATE` below is exactly such a write. `connect` creates
            # the file, so there is something to restrict by the time this runs
            # (#489; the six other SQLite stores have the same ordering).
            self._restrict_permissions()
            # `BEGIN IMMEDIATE` takes the write lock before the schema is
            # inspected, so the whole of create/index is **serialised against
            # another process opening the same file** — the same guard
            # `_record_sync` uses, applied to setup.
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                for statement in _INDEXES:
                    conn.execute(statement)
                if not labelled:
                    # Stamped *after* the create above, and inside the same
                    # transaction, so a failure rolls the marker — and the `meta`
                    # table itself — back with it rather than leaving a database
                    # falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except GrantError:
            # A refused schema version is already this layer's error; it still
            # leaves a connection to close before it propagates.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the grant store at {self._path!r}: {exc}"
            raise GrantError(msg) from exc
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
        this store's data and that this store has no business modifying. SQLite does
        not follow such a link either, so nothing is stranded: a symlinked
        ``-journal`` is not a hot journal and is unlinked at the first statement, and
        a symlinked ``-wal`` on a WAL-mode database is refused outright.

        A no-op in memory, where there is no file to restrict.

        **Duplicated from the six other SQLite stores on purpose** (#506): the
        family shares this method by copy today, and consolidating it is that
        issue's, not this lane's.
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
        ``grants`` table is created or read.

        Returns:
            Whether the database already carries a ``schema_version``. ``False``
            means it does not, and :meth:`_setup` stamps one.

        **An unlabelled database is stamped rather than migrated**, and here that
        is a statement about history rather than leniency. The audit trail
        backfills because its marker arrived after it already had users; this store
        ships *with* its marker, so version 1 is the only shape it has ever
        written and an unlabelled file is one this open is creating. There is
        nothing to migrate from and no ``_migrate`` to run.

        **Any other stored version is refused**, newer or older, matching
        ``SqliteAuditTrail`` and ``SqlitePlanStore`` (ADR-0049 §1). Reading it
        blindly would let a downgrade construct successfully and fail later with a
        raw SQLite error — a fault to report at open. When a version 2 exists the
        *older* branch becomes a migrate-and-restamp; nothing here presumes it
        stays a refusal.

        Raises:
            GrantError: If the stored version is not one this code understands, is
                not an integer at all, or is not a single unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code
            # created — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing
            # `meta` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers. Reading the first row would then let an
            # unsupported version through the refusal below on the strength of a
            # sibling row that agrees.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the grant store at {self._path!r} holds {len(rows)} schema_version rows "
                f"({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise GrantError(msg)
        raw = rows[0][0]
        msg = f"the grant store at {self._path!r} holds a non-numeric schema_version {raw!r}"
        # The marker this code writes is always TEXT, but a hand-built `meta` may
        # declare no type, in which case SQLite hands back whatever was stored — a
        # REAL, a BLOB, a NULL. Only a string or an integer is parsed;
        # `int(float("inf"))` raises `OverflowError`, which is neither
        # `ValueError` nor an `AssistantError` and would leave this layer's
        # boundary through a hole. `bool` is an `int` in Python, so it is named
        # rather than left to read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise GrantError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise GrantError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the grant store at {self._path!r} has schema_version={stored}, but this "
                f"code supports only version {_SCHEMA_VERSION}; refusing to open it rather "
                f"than read it blindly"
            )
            raise GrantError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first
        write, which is what puts :meth:`_record_sync`'s *reads* under it: the
        free-id check, the live-grant check and the revocation invariants all
        decide whether the append may happen, so a deferred begin would let a
        second process observe the same free id or the same unrevoked grant
        between them and the append — and ADR-0097 §4's one-live-grant-per-source
        guarantee would be a race. The ``asyncio`` lock closes that within one
        process; this closes it against the file. ``immediate=False`` is the read
        form, a deferred transaction for several ``SELECT``s that must see one
        snapshot.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`record` refuses a second
        live grant as ``InvalidGrantError`` without leaving a row behind.

        Raises:
            GrantError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=GrantError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, grant: SourceGrant) -> str:
        """Append ``grant`` and return its id.

        Write-once and atomic over the duplicate check, the live-grant check, the
        revocation invariants and the append (ADR-0097 §4): without atomicity the
        one-live-grant-per-source guarantee is a race.

        Raises:
            InvalidGrantError: If the record does not satisfy its own model, if its
                id is already recorded, if it grants a source that already has a
                live grant, or if it revokes and fails any of ADR-0097 §4's
                invariants. Pydantic's ``ValidationError`` is deliberately not
                allowed to escape: ``CONTRIBUTING`` has this layer raise only from
                the ``AssistantError`` hierarchy, and a caller handling "the store
                would not accept this" should not need a second handler for the
                shape of the refusal.
            GrantError: If the database refuses the write.
        """
        snapshot = _revalidated(grant)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: SourceGrant) -> None:
        """Validate against what is stored and insert, as one transaction."""
        with self._transaction(f"record grant {snapshot.id!r}") as conn:
            if conn.execute("SELECT 1 FROM grants WHERE id = ?", (snapshot.id,)).fetchone():
                msg = (
                    f"grant {snapshot.id!r} is already recorded; the store is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise InvalidGrantError(msg)
            if snapshot.revokes is None:
                self._check_no_live_grant(conn, snapshot)
            else:
                self._check_revocation(conn, snapshot)
            conn.execute(
                "INSERT INTO grants(id, source, decided_at_us, revokes, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    snapshot.source,
                    _sort_key(snapshot.decided_at),
                    snapshot.revokes,
                    snapshot.model_dump_json(),
                ),
            )

    def _check_no_live_grant(self, conn: sqlite3.Connection, grant: SourceGrant) -> None:
        """Refuse a second live grant for one source (ADR-0097 §4).

        The **same statement** :meth:`_live_sync` reads, rather than a second one
        selecting existence: two spellings of "is this source granted" are two
        answers free to drift apart, and the one that drifted would still pass its
        own half of the suite. Only the first row is needed here, so ``fetchone``
        does the bounding that a ``LIMIT`` would.

        Raises:
            InvalidGrantError: If ``grant``'s source already has a live grant.
        """
        if conn.execute(_LIVE_FOR_SOURCE, (grant.source,)).fetchone():
            msg = (
                f"source {grant.source!r} already has a live grant; at most one grant "
                f"per source is live at any instant, and narrowing or widening is a "
                f"revocation followed by a new grant (ADR-0097 §2, §4)"
            )
            raise InvalidGrantError(msg)

    def _check_revocation(self, conn: sqlite3.Connection, revocation: SourceGrant) -> None:
        """Enforce ADR-0097 §4's invariant on a revoking record.

        Five refusals, and **no sixth on the timestamp**. That absence is the
        decision, not an oversight: see this module's docstring, and ADR-0097 §4,
        which rules that "a revocation is never refused for its timestamp —
        including one that predates the grant it revokes".

        Raises:
            InvalidGrantError: If the named grant is absent, is itself a
                revocation, is already revoked, names a different ``source``, or
                transcribes a different ``scope``.
        """
        row = conn.execute(
            "SELECT data FROM grants WHERE id = ?", (str(revocation.revokes),)
        ).fetchone()
        if row is None:
            msg = (
                f"grant {revocation.revokes!r} is not recorded, so nothing revokes it (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        target = _decode(row[0])
        if target.revokes is not None:
            msg = (
                f"record {target.id!r} is itself a revocation; only a granting record "
                f"can be revoked (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if conn.execute("SELECT 1 FROM grants WHERE revokes = ?", (revocation.revokes,)).fetchone():
            msg = (
                f"grant {target.id!r} is already revoked; a grant revoked twice is a "
                f"history that says the user withdrew one thing twice (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if target.source != revocation.source:
            msg = (
                f"revocation {revocation.id!r} names source {revocation.source!r} but "
                f"grant {target.id!r} is about {target.source!r}; a revoking record "
                f"transcribes what it withdraws (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if target.scope != revocation.scope:
            msg = (
                f"revocation {revocation.id!r} transcribes scope {revocation.scope!r} but "
                f"grant {target.id!r} authorised {target.scope!r}; there is no partial "
                f"revocation (ADR-0097 §2, §4)"
            )
            raise InvalidGrantError(msg)

    # --- the read path ----------------------------------------------------

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """The live grant covering ``source`` for ``use``, or ``None``.

        ``source`` is compared with SQLite's ``=`` on a ``TEXT`` column and nothing
        else — no strip, no case-fold, no normalising of any kind. A store that
        normalised here would change what a grant covers, which is the one place a
        store could be "helpful" and be wrong (ADR-0097 §9).

        The **record** rather than a boolean, so a caller can name what authorised
        the read; detached, because this is the one answer §5's gate rests on and
        ``frozen=True`` would not stop a caller widening ``scope`` through
        ``__dict__`` on a shared object.

        Raises:
            GrantError: If the store cannot be read, holds a record that no longer
                validates, or holds two live grants for one source.
        """
        async with self._lock:
            rows = await _run_to_completion(self._live_sync, source)
        for row in rows:
            grant = _decode(row)
            if use in grant.scope:
                return grant
        return None

    def _live_sync(self, source: str) -> Sequence[str]:
        """Read the live grants for ``source``, refusing a store that holds two.

        ADR-0097 §4 guarantees at most one, and :meth:`_check_no_live_grant` is
        what keeps it true. A file that nonetheless holds two has been corrupted or
        hand-edited, and picking one of them would answer the gate from a store
        that cannot say what the user granted. Reported rather than resolved, and
        the report fails the read **closed**: a driver treats a ``GrantError`` as
        "not a grant" (ADR-0097 §5a).
        """
        try:
            rows = self._conn.execute(_LIVE_FOR_SOURCE, (source,)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the live grant for source {source!r}: {exc}"
            raise GrantError(msg) from exc
        if len(rows) > 1:
            msg = (
                f"the grant store holds {len(rows)} live grants for source {source!r}, "
                f"where ADR-0097 §4 allows one; the store is corrupt"
            )
            raise GrantError(msg)
        return [str(row[0]) for row in rows]

    async def recent(self, *, limit: int = 50) -> list[SourceGrant]:
        """Return up to ``limit`` records, newest first, ties broken by id ascending.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021
        §4, ADR-0073 §2): the row count here grows with grant churn rather than
        with the number of sources.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Refused rather than
                clamped or passed through: SQLite reads ``LIMIT -1`` as *no limit
                at all*, so the one call offering a bounded read of a Tier 1 store
                would become the unbounded read it exists to avoid.
            GrantError: If the store cannot be read, or holds a record that no
                longer validates.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        # Clamped *upward* only. A Python int has no width, and binding one wider
        # than SQLite's signed 64-bit parameter raises `OverflowError` — neither
        # `ValueError` nor `GrantError`, so it would leave this layer's error
        # boundary through a hole. Clamping serves what was asked for: a bound
        # above any possible row count means "all of them", which is what the
        # query then returns. This is not the `limit=-1` case, where clamping
        # would have served something the caller did not ask for.
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, min(limit, _MAX_SQLITE_INT))
        return [_decode(row) for row in rows]

    async def export(self) -> list[SourceGrant]:
        """Return every record, in the same order as :meth:`recent`.

        ADR-0007 §3's export right, and ``AuditTrail.export``'s shape. A revoked
        grant is **still here** (ADR-0097 §4, §6): the history says what the user
        granted and withdrew, and a record removed on revocation would leave every
        belief from that source reading as unauthorised.

        Raises:
            GrantError: If the store cannot be read, or holds a record that no
                longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, None)
        return [_decode(row) for row in rows]

    def _ordered_sync(self, limit: int | None) -> Sequence[str]:
        """Read records newest-first, optionally bounded.

        Two static statements rather than one interpolated ``LIMIT``: the bound is
        the whole point of ``recent``, and a query assembled from a variable is how
        it stops being one.
        """
        try:
            rows = (
                self._conn.execute(_ORDERED).fetchall()
                if limit is None
                else self._conn.execute(f"{_ORDERED} LIMIT ?", (limit,)).fetchall()
            )
        except sqlite3.Error as exc:
            msg = f"failed to read the grant store: {exc}"
            raise GrantError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Wholesale by design (ADR-0097 §4, ADR-0021 §4): the user may burn the book,
        and nobody may tear out a page. There is no ``delete(id)`` for the same
        reason — a selective delete is the page torn out.

        Raises:
            GrantError: If the store cannot be cleared.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        """Delete everything in one statement, counting what the delete removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it. A separate count is read before SQLite opens the
        write transaction, so a second store on the same file could append between
        the two and be erased without being counted — and each instance has its own
        ``asyncio.Lock``, which arbitrates nothing across them. One statement makes
        the number exact by construction rather than by transaction discipline.

        Only ``grants`` is emptied: the ``meta`` schema marker describes the file's
        shape rather than the user's history, so burning the book leaves a database
        this code can still open.
        """
        with self._transaction("clear the grant store") as conn:
            removed = conn.execute("DELETE FROM grants").rowcount
        return int(removed)

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _revalidated(grant: SourceGrant) -> SourceGrant:
    """Rebuild ``grant`` as a validated :class:`SourceGrant`.

    ADR-0097 §4 asks for a *validated* snapshot, not merely a detached one. A copy
    alone detaches without checking, so a record corrupted past its frozen model's
    guard would be stored and make every later read incoherent — a naive
    ``decided_at`` makes ``recent`` raise on comparing it against the aware values
    beside it, and an **emptied ``scope``** authorises nothing while still
    occupying the source's one live-grant slot, so the real grant could not be
    recorded until this one was revoked.

    Rebuilt as a ``SourceGrant`` specifically, not as ``type(grant)``: a caller's
    subclass could carry extra fields, and ``extra="forbid"`` refuses them here
    rather than letting them vanish at serialisation and make the stored record
    differ from the one that reloads.

    **And rebuilt from the instance's field state rather than from
    ``model_dump()``**, which is where this parts company with
    ``SqliteAuditTrail._revalidated``'s otherwise identical shape. ``model_dump``
    is an ordinary overridable method, so a ``SourceGrant`` subclass can return a
    mapping that does not describe itself — a ``FACET``-only instance whose dump
    says ``(FACET, INGEST)`` — and the store would then append a *wider grant than
    the one it was handed*. That is not the caller-falsifies-its-own-record case
    ADR-0018 §3 puts outside a store's reach: the object presented is a valid
    narrow grant and the record kept is a different one, which is precisely what
    "stores a detached, validated snapshot" denies. ``__dict__`` is where pydantic
    keeps validated field state, and it is read through ``object.__getattribute__``
    so that the read itself dispatches no user code either.

    **Where this stops, stated rather than left to the next reader.** A caller that
    controls ``__getattribute__`` also controls what it asks the store to record in
    the first place, and ADR-0018 §3 draws that boundary in as many words. What is
    closed here is the narrower and real case — a *sanctioned* extension point
    sitting between the object and its snapshot.

    **The refusal names the id out of the same mapping**, never through
    ``grant.id``. A record whose ``__dict__`` is missing a field — the deletion
    beside the substitution this function exists to catch — has no ``id``
    attribute at all, so composing the message from one would raise a bare
    ``AttributeError`` out of the handler and replace the refusal this layer owes
    with a builtin escaping its error boundary. ``fields.get`` answers ``None``
    for the field that is gone and still names the record when it is present,
    which is the whole of what the message is for.

    Raises:
        InvalidGrantError: If the record does not satisfy its own model. The
            subclass rather than the ``GrantError`` base: here the base is the
            *store fault* and only the subclass says "your record was refused",
            which is the distinction ADR-0097 §5a keeps alive when it has a driver
            fail closed on one and refuse on the other.
    """
    fields = dict(object.__getattribute__(grant, "__dict__"))
    try:
        return SourceGrant.model_validate(fields)
    except ValidationError as exc:
        msg = f"grant {fields.get('id')!r} is not a valid record: {exc}"
        raise InvalidGrantError(msg) from exc


def _decode(data: str) -> SourceGrant:
    """Rebuild a stored grant from its JSON.

    Raises:
        GrantError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to
            hand on. The **base** class here, not ``InvalidGrantError``: nothing
            the caller handed in was refused, the store itself is unreadable, and a
            driver's fail-closed branch is exactly the right response.
    """
    try:
        return SourceGrant.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the grant store holds a record that no longer validates: {exc}"
        raise GrantError(msg) from exc


__all__ = ["SqliteSourceGrantStore"]
