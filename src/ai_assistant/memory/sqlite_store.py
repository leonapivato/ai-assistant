"""A persistent :class:`~ai_assistant.core.protocols.MemoryStore` on SQLite.

Local-first storage (ADR-0002) with semantic retrieval via ``sqlite-vec`` and an
injected :class:`~ai_assistant.core.protocols.Embedder` (ADR-0006). Records are
stored as JSON alongside their embedding; ``add`` embeds the record's content and
``search`` embeds the query and ranks by vector distance.

The database file is created with owner-only permissions (ADR-0004), and the
embedding model/dimension are recorded so opening the store with a different
embedder fails loudly rather than returning meaningless similarities.

Every mutation — the schema setup included — runs inside one ``BEGIN IMMEDIATE``
transaction, which is what makes each read-then-write sequence here atomic
against a second *process* on the same file and not merely against another
coroutine on this loop. This is the discipline the other four SQLite stores
already keep, and ADR-0083 §12 rules its adoption here **consistency work rather
than a defect fix**: under the hub's exclusivity there is one writing process, so
worth doing so five stores read the same way, not worth blocking the hub on. The
section also names the one condition that makes it urgent again — exclusivity
being relaxed — which is the case ``tests/memory/test_sqlite_store.py``'s forked
cases construct deliberately. Journal mode is untouched: ADR-0083 §12 defers WAL
with reasons and says it still owes its own ADR if taken (#505).
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

import sqlite_vec
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    IncompatibleStateError,
    MemoryStoreConflictError,
    MemoryStoreError,
)
from ai_assistant.core.types import MemoryRecord, MemoryWriteMode, band_of

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import BeliefBand, Embedding, MemoryKind, MemoryWrite

_ADAPTER: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
# ``search`` applies the kind and expiry filters *after* the vector KNN (sqlite-vec
# cannot cleanly pre-filter joined columns within a KNN), so it over-fetches
# candidates to leave room for filtered-out rows. A tracked limitation: a caller
# can still be under-served if more than this multiple of ``limit`` nearer
# neighbours are all filtered out — and for a ``limit`` past ``_VEC_KNN_MAX_K /
# _RESULT_OVERFETCH`` the effective multiple shrinks below this, since the fetch
# is then clamped to the KNN ceiling (see ``_VEC_KNN_MAX_K``).
_RESULT_OVERFETCH = 8
# The KNN ``k`` in ``search``'s query is capped by sqlite-vec itself: a ``k`` above
# this raises ``sqlite3.OperationalError("k value in knn query too large ... the
# limit is 4096")`` instead of running (observed on sqlite-vec 0.1.9). So the
# over-fetch ``limit * _RESULT_OVERFETCH`` is clamped to it, turning an opaque
# crash into a served result. The clamp is semantically safe: a KNN can return no
# more rows than exist, so requesting more candidates than the cap only forgoes
# over-fetch headroom the store already documents it may run short of (issue #115).
# This subsumes the wider signed-64-bit bind range the crash was first theorised
# against — 4096 is the lower, operative ceiling, reached at ``limit > 512``.
_VEC_KNN_MAX_K = 4096
#: Bound parameters ``get_many``'s statement spends on something other than an id
#: — the two read-time comparisons against ``now`` — and therefore the headroom
#: its chunk size must leave under ``SQLITE_MAX_VARIABLE_NUMBER``.
_GET_MANY_FIXED_PARAMS = 2
_OWNER_ONLY = 0o600
#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")
#: One past the largest value ``list_beliefs`` accepts for ``limit``/``offset``:
#: the signed 64-bit ceiling a SQLite bind parameter tops out at (ADR-0073 §2).
_PAGE_BOUND = 2**63


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
    in for the cause rather than chained to it (#680). Which of the two waits below
    runs decides whether the caller sees that or the real failure, which is why it
    presented as an intermittent fault rather than a reproducible one.
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
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_page_bounds(limit: int, offset: int) -> None:
    """Refuse a paging argument outside ``[0, 2**63)`` (ADR-0073 §2).

    The check this backend most needs and the reason the contract states it: a
    negative bound would reach SQLite, which reads ``LIMIT -1`` as *no limit at
    all*, and an over-wide one raises ``OverflowError`` out of the driver — neither
    a ``MemoryStoreError`` nor anything the seam documents.

    Duplicated in :mod:`ai_assistant.memory.store` and the canonical fake rather
    than shared, exactly as ``AuditTrail.recent``'s check is: ``ai_assistant.testing``
    may not import a subsystem (golden rule 1), and ADR-0073 adds nothing to ``core``.

    Raises:
        ValueError: If either value is negative or beyond the signed 64-bit range.
    """
    for name, value in (("limit", limit), ("offset", offset)):
        if not 0 <= value < _PAGE_BOUND:
            msg = f"{name} must be in [0, 2**63), got {value}"
            raise ValueError(msg)


def _newest_revision_first(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """ADR-0073 §2's total order: ``last_updated`` descending, ``id`` ascending.

    Two passes over a stable sort rather than one composite key, because the two
    halves run in opposite directions and ``datetime`` has no negation.
    """
    by_id = sorted(records, key=lambda record: record.id)
    return sorted(by_id, key=lambda record: record.provenance.last_updated, reverse=True)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289).

    Lifecycle deadlines are stored and compared as integer microsecond epochs
    rather than ``REAL`` POSIX seconds. ``datetime.timestamp()`` returns an
    IEEE-754 double whose 53-bit mantissa cannot resolve microseconds near the
    far end of the datetime range: approaching year 9999 its ulp is tens of
    microseconds, so two instants ~1 µs apart collapse to one float and a
    ``deadline > now`` pre-filter can hide a record that must stay live. The
    ``timedelta`` here is exact integer arithmetic (days/seconds/microseconds
    are ints), so no precision is lost at any point in the localizable range.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


class SqliteMemoryStore:
    """A persistent, semantically-searchable ``MemoryStore``."""

    def __init__(
        self,
        *,
        path: Path | str,
        embedder: Embedder,
        now: Clock = _utcnow,
    ) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            embedder: The embedder used for all records; a store is bound to one
                embedding model for its lifetime.
            now: Clock used to decide whether a record has expired; injectable
                for deterministic tests. Defaults to UTC wall-clock. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`: this seam never
                reaches a `core` field validator — the reading becomes an integer
                microsecond epoch (issue #289) — so the producer is the only place
                a naive or indeterminate reading can be caught (ADR-0026 §7).

        Raises:
            IncompatibleStateError: If the store was previously built with a
                different embedding model or dimension. A **deployment** fault
                rather than a store fault (ADR-0083 §6): every stored vector is in
                a foreign space, so serving would be silently wrong, and no
                restart clears it until a human re-embeds or reconfigures.
            MemoryStoreError: If the database cannot be opened or its schema
                cannot be created — the faults that may clear on their own.
        """
        self._embedder = embedder
        self._clock = checked_clock(now, owner="SqliteMemoryStore")
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves every read-then-write sequence here (`_persist_record`'s
            # rowid lookup, `_delete_sync`'s, `_clear_sync`'s count) open to
            # exactly the cross-process interleaving `BEGIN IMMEDIATE` forbids.
            # The two sibling stores in this package connect the same way.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            msg = f"failed to open memory store at {self._path!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built and migrated. SQLite copies the database file's mode onto every
            # rollback journal it creates for it, so a journal opened while the
            # file still carried the process umask is world-readable too — and an
            # interrupted write leaves it on disk holding Tier 1 pages (ADR-0004
            # §1, §4). The `BEGIN IMMEDIATE` below is exactly such a write, and
            # `_migrate_records` inside it can copy every row. `connect`
            # creates the file, so there is something to restrict by the time this
            # runs (#451; `SqliteConversationStore._setup` has the same ordering).
            self._restrict_permissions()
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            # `BEGIN IMMEDIATE` takes the write lock before the schema is
            # inspected, so the whole of create/migrate/verify is **serialised
            # against another process opening the same file** — the guard the
            # mutations below use, applied to setup, as `SqliteAuditTrail._setup`
            # and `SqlitePlanStore._setup` already do. Without it two processes
            # opening a fresh file both find `meta` empty and both insert it, and
            # two upgrading a legacy file both read the pre-migration
            # `PRAGMA table_info` and rebuild `records` twice; the lock makes the
            # loser wait and re-read the finished schema instead.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS records("
                "rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
                "kind TEXT NOT NULL, data TEXT NOT NULL, "
                "expires_at INTEGER, valid_until INTEGER)"
            )
            self._migrate_records(conn)
            self._verify_or_init_meta(conn)
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_records "
                f"USING vec0(embedding float[{self._embedder.dimensions}] distance_metric=cosine)"
            )
            conn.execute("COMMIT")
        except MemoryStoreError, IncompatibleStateError:
            # Never leak the connection when opening fails; closing it also discards
            # the uncommitted `BEGIN IMMEDIATE` above, so a refused open leaves no
            # half-built schema behind. `IncompatibleStateError`
            # is listed alongside rather than covered by it: ADR-0083 §6 puts it
            # *outside* the store-error family on purpose, so it would otherwise
            # fall past every handler here and leave this connection open.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to open memory store at {self._path!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        return conn

    def _migrate_records(self, conn: sqlite3.Connection) -> None:
        """Bring ``expires_at`` and ``valid_until`` to INTEGER microsecond epochs.

        Every legacy table shape is handled by one rebuild: a pre-ADR-0007 table
        (neither column), a post-ADR-0007 table (``expires_at REAL`` only), and
        the current-but-``REAL`` table (both columns ``REAL``) all become a table
        whose lifecycle columns are ``INTEGER`` microsecond epochs. Both are
        backfilled from each record's *exact* ISO instant in its JSON blob
        (ADR-0045 §9), so a value a prior ``REAL`` column had already rounded is
        restored to full precision, and a pre-column table does not resurrect an
        already-expired memory as ``NULL`` (no deadline).

        The rebuild is required rather than an in-place ``ALTER``: SQLite has no
        ``ALTER COLUMN TYPE``, and ``REAL`` affinity would silently re-float any
        integer written to a legacy column, so the *affinity* itself must change.
        We recreate the table and copy the rows rather than ``DROP COLUMN`` (which
        needs SQLite 3.35+); the copy carries each original ``rowid`` forward
        explicitly, so the ``vec_records`` join by rowid stays intact.

        It runs in an **explicit** transaction — its caller's. SQLite auto-commits
        a bare DDL statement when no transaction is open (issue #289 review), so
        without one a failure during the row copy would leave the schema already
        swapped and the values un-backfilled — permanently, since a later open
        would see ``INTEGER`` columns and skip migration, resurrecting expired
        rows. Inside the transaction every statement — the DDL included — rolls
        back together on any failure, and a crash mid-rebuild is covered too: the
        uncommitted transaction is discarded by SQLite on the next open.

        The transaction is :meth:`_setup`'s ``BEGIN IMMEDIATE`` rather than one
        opened here, which is what puts the ``PRAGMA table_info`` read below
        *inside* it. Opened here, the shape check would run outside the write lock
        and two processes upgrading one legacy file could both read the
        pre-migration columns and both rebuild (#526). It also means this method
        must not begin or commit anything of its own: nesting a ``BEGIN`` inside
        the open one raises, and committing here would publish a half-built schema.
        """
        info = {row[1]: str(row[2]).upper() for row in conn.execute("PRAGMA table_info(records)")}
        if info.get("expires_at") == "INTEGER" and info.get("valid_until") == "INTEGER":
            return  # already on the microsecond-epoch schema; nothing to do
        conn.execute(
            "CREATE TABLE records_migrated("
            "rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL, "
            "expires_at INTEGER, valid_until INTEGER)"
        )
        # Stream the source rows through a dedicated read cursor rather than
        # ``fetchall()``, so migrating a large legacy store does not
        # materialise the whole ``records`` table in memory at once. Reads
        # come from ``records`` and writes go to ``records_migrated`` — a
        # different table — so the scan cursor stays valid across the inserts.
        read = conn.execute("SELECT rowid, id, kind, data FROM records")
        for rowid, id_, kind, data in read:
            expires = self._micros_from_json(data, "expires_at")
            valid_until = self._micros_from_json(data, "valid_until", nested="validity")
            conn.execute(
                "INSERT INTO records_migrated"
                "(rowid, id, kind, data, expires_at, valid_until) VALUES (?, ?, ?, ?, ?, ?)",
                (rowid, id_, kind, data, expires, valid_until),
            )
        conn.execute("DROP TABLE records")
        conn.execute("ALTER TABLE records_migrated RENAME TO records")

    def _micros_from_json(self, data: str, key: str, *, nested: str | None = None) -> int | None:
        """Read a stored ISO instant from a record's JSON, as a µs epoch or None.

        Reads ``data[key]`` at the top level, or ``data[nested][key]`` when
        ``nested`` is given (the validity window lives under ``"validity"``). A
        missing container, a missing key, or a ``null`` value all read as
        ``None`` — an absent window end is *open*, exactly as an absent
        ``expires_at`` is *no deadline*. The instant is converted with
        :func:`_to_micros`, so the read-back is exact even at the range extremes
        (issue #289).
        """
        try:
            payload = json.loads(data)
            if nested is not None:
                payload = payload.get(nested) or {}
            raw = payload.get(key)
            if raw is None:
                return None
            instant = datetime.fromisoformat(raw)
        except (ValueError, TypeError, AttributeError) as exc:
            msg = f"failed to read {key!r} from a stored record: {exc}"
            raise MemoryStoreError(msg) from exc
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        return _to_micros(instant)

    def _verify_or_init_meta(self, conn: sqlite3.Connection) -> None:
        want = {
            "embedding_model": self._embedder.model_id,
            "dimensions": str(self._embedder.dimensions),
        }
        existing = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if not existing:
            conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", list(want.items()))
            return
        for key, value in want.items():
            if existing.get(key) != value:
                # ADR-0083 §6. The refusal is right and is kept exactly as it was —
                # every stored vector is in a different space, so `search` would rank
                # on nonsense and report nothing wrong. Only its **class** changes,
                # and only because a resident process has to tell "this deployment
                # cannot serve this store" from "this disk is broken" without
                # matching on this message string. What is detected, and when, is
                # unchanged, so ADR-0024 §2 stays true and no migration contract is
                # created here.
                msg = (
                    f"store was built with {key}={existing.get(key)!r}, "
                    f"but this embedder has {value!r}; re-embedding is required"
                )
                raise IncompatibleStateError(
                    msg,
                    expected=f"{key}={value!r}",
                    found=f"{key}={existing.get(key)!r}",
                    operator_action=(
                        f"re-embed the store at {self._path} against this embedder, or "
                        f"configure the embedder it was built with"
                    ),
                )

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
        this store's data and that this store has no business modifying.

        Skipping it strands no page anywhere this method could not reach, because
        SQLite does not follow such a link either (verified against 3.53.1, and
        asserted in the conversation store's tests): a symlinked ``-journal`` is not
        a hot journal, so SQLite unlinks *the link* at the first statement and writes
        a real file in its place — which inherits the ``0600`` set just above — and a
        symlinked ``-wal`` on a WAL-mode database is refused outright rather than
        written through. What is left is a check-then-chmod race, and winning it
        needs write access to the database's own directory, which is already past
        ADR-0004 §4 by routes this method could never close.

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

    @contextlib.contextmanager
    def _transaction(self, what: str, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read-then-write mutation
        cannot interleave with another writer's — which is how this store's rowid
        lookups hold **across processes** and not merely across coroutines on one
        loop. That matters more here than the wrong return value it also prevents:
        ``records`` and ``vec_records`` are joined by ``rowid`` with no foreign key
        (``vec_records`` is a ``vec0`` virtual table, so SQLite cannot enforce
        one), and a deletion landing between :meth:`_persist_record`'s ``SELECT``
        and its vector write leaves an **orphan vector row** that ``search``'s KNN
        matches and then fails to join (#526). ``immediate=False`` is the read
        form: a deferred transaction, so several ``SELECT``s in one block see one
        consistent snapshot rather than two states either side of a racing write.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`write_atomic` refuses an
        ``INSERT_IF_ABSENT`` collision as ``MemoryStoreConflictError`` without
        leaving any element of the batch behind.

        Raises:
            MemoryStoreError: If the backend fails at any point.
        """
        conn = self._conn
        begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
        try:
            conn.execute(begin)
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise MemoryStoreError(msg) from exc
        try:
            yield conn
        except BaseException as exc:
            # `BaseException`, not `Exception`: ADR-0060's resource clause is
            # unconditional, and a transaction left open on the shared connection
            # is a resource held with nothing running that will release it — the
            # next `BEGIN` fails with "cannot start a transaction within a
            # transaction" and the store is poisoned for every later caller.
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                msg = f"failed to {what}: {exc}"
                raise MemoryStoreError(msg) from exc
            raise
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            msg = f"failed to {what}: {exc}"
            raise MemoryStoreError(msg) from exc

    async def _embed_one(self, text: str) -> Embedding:
        """Embed a single text, mapping any embedder misbehaviour to our error.

        The embedder is an injected contract, so a provider fault, a wrong batch
        cardinality, or a wrong-sized vector must surface as ``MemoryStoreError``
        rather than an arbitrary exception leaking through the store's boundary.
        """
        try:
            vectors = await self._embedder.embed([text])
            if len(vectors) != 1:
                msg = f"embedder returned {len(vectors)} vectors for a single text"
                raise MemoryStoreError(msg)
            vector = vectors[0]
            if len(vector) != self._embedder.dimensions:
                msg = (
                    f"embedder returned a {len(vector)}-dim vector, "
                    f"expected {self._embedder.dimensions}"
                )
                raise MemoryStoreError(msg)
        except MemoryStoreError:
            raise
        except Exception as exc:  # any fault or malformed result from the embedder
            # Also catches a malformed result container/element (e.g. ``None`` or
            # a non-sized vector), whose ``len()`` raises ``TypeError`` here.
            msg = f"embedder failed: {exc}"
            raise MemoryStoreError(msg) from exc
        return vector

    async def add(self, record: MemoryRecord) -> str:
        """Embed the record's content and persist it, returning its id.

        Snapshots the record *before the first await* (issue #286). ``add`` awaits
        the embedder between reading the record and serialising it, and
        ``MemoryBase`` models are mutable, so a caller aliasing the submitted
        record and mutating it across that await could otherwise persist JSON for
        the *new* state alongside a vector computed from the *old* one — a torn
        write a later search matches on an unrelated vector. The stored id, JSON,
        and vector are all derived from this one immutable snapshot, matching the
        shape :meth:`write_atomic` already uses for its batch (ADR-0056).

        Raises:
            MemoryStoreError: If the embedder fails or returns a wrong-sized
                vector, or the write fails (the write is transactional — a
                failure leaves the store unchanged).
        """
        snapshot = record.model_copy(deep=True)
        vector = await self._embed_one(snapshot.content)
        async with self._lock:
            await _run_to_completion(self._add_sync, snapshot, vector)
        return snapshot.id

    def _add_sync(self, record: MemoryRecord, vector: Embedding) -> None:
        # The transaction rolls the partial multi-table write back on any failure,
        # so a later commit cannot persist an inconsistent record/vector pair.
        with self._transaction(f"store memory {record.id!r}"):
            self._persist_record(record, vector)

    def _persist_record(self, record: MemoryRecord, vector: Embedding) -> None:
        """Write one record and its vector into the *open* transaction, no commit.

        Shared by :meth:`add` and :meth:`write_atomic`: an overwrite rewrites every
        column and replaces the vector row; a new id inserts both. The caller owns
        the surrounding transaction — the commit and any rollback — so this is
        equally one standalone write or one element of an atomic batch (ADR-0046
        §4). Raises the underlying :class:`sqlite3.Error` unwrapped, for the caller
        to translate.

        Both callers open that transaction with :meth:`_transaction`, so the write
        lock is already held when the ``SELECT`` below runs and the rowid it reads
        cannot be deleted out from under the vector write that follows (#526).
        """
        conn = self._conn
        blob = sqlite_vec.serialize_float32(list(vector))
        data = record.model_dump_json()
        expires = _to_micros(record.expires_at) if record.expires_at is not None else None
        valid_until = (
            _to_micros(record.validity.valid_until)
            if record.validity.valid_until is not None
            else None
        )
        row = conn.execute("SELECT rowid FROM records WHERE id = ?", (record.id,)).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO records(id, kind, data, expires_at, valid_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (record.id, record.kind, data, expires, valid_until),
            )
            rowid = cursor.lastrowid
        else:
            rowid = row[0]
            conn.execute(
                "UPDATE records SET kind = ?, data = ?, expires_at = ?, valid_until = ? "
                "WHERE rowid = ?",
                (record.kind, data, expires, valid_until, rowid),
            )
            conn.execute("DELETE FROM vec_records WHERE rowid = ?", (rowid,))
        conn.execute("INSERT INTO vec_records(rowid, embedding) VALUES (?, ?)", (rowid, blob))

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """Apply every write in one SQLite transaction — all commit, or none do.

        The whole batch runs inside one transaction: a failure part-way (a
        conflict, or a backend error) rolls the transaction back, so nothing is
        committed — and a crash before ``COMMIT`` leaves nothing on disk, which is
        the durability guarantee (ADR-0046 §4) supersession needs so a window-close
        can never survive without its paired insert (ADR-0045 §8).

        Embedding happens before the lock (like :meth:`add`); the transaction is
        held only for the writes themselves.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id names a
                stored record — physical presence, so an expired or window-closed
                row still collides (ADR-0046 §3). Nothing is written.
            MemoryStoreError: the batch names the same id twice (ADR-0046 §3), or
                any backend failure (with the ``sqlite3`` cause retained). Nothing
                is written.
        """
        # Snapshot every record *before the first await*, so a caller aliasing a
        # submitted record and mutating it across the embedding awaits cannot
        # change the id the duplicate-id check validated, desync content from the
        # embedding computed for it, or otherwise alter the committed write-set
        # (ADR-0046 §3). Everything downstream reads only the immutable snapshot.
        snapshot = [(write.record.model_copy(deep=True), write.mode) for write in writes]
        ids = [record.id for record, _ in snapshot]
        if len(set(ids)) != len(ids):
            msg = "an atomic batch may not write the same id twice"
            raise MemoryStoreError(msg)
        if not snapshot:
            return []
        prepared: list[tuple[MemoryRecord, MemoryWriteMode, Embedding]] = []
        for record, mode in snapshot:
            vector = await self._embed_one(record.content)
            prepared.append((record, mode, vector))
        async with self._lock:
            await _run_to_completion(self._write_atomic_sync, prepared)
        return ids

    def _write_atomic_sync(
        self, prepared: Sequence[tuple[MemoryRecord, MemoryWriteMode, Embedding]]
    ) -> None:
        try:
            with self._transaction("commit an atomic memory batch") as conn:
                for record, mode, vector in prepared:
                    if mode is MemoryWriteMode.INSERT_IF_ABSENT:
                        row = conn.execute(
                            "SELECT rowid FROM records WHERE id = ?", (record.id,)
                        ).fetchone()
                        if row is not None:
                            msg = (
                                f"cannot insert {record.id!r}: "
                                f"a record with that id is already stored"
                            )
                            raise MemoryStoreConflictError(msg)
                    self._persist_record(record, vector)
        except MemoryStoreError:
            # Already rolled back by the transaction, which propagates anything
            # that is not a backend failure unchanged. The in-scope collision is
            # *this*: the presence check above raises MemoryStoreConflictError
            # deterministically for a single writer (§4), and it is already the
            # seam's error (ADR-0028 §5). A raced cross-process INSERT that hit the
            # records.id UNIQUE constraint instead is §5's out-of-scope
            # concurrency, which ADR-0046 §4 does *not* require reclassifying as a
            # conflict; the transaction reports it as a plain MemoryStoreError, so
            # only a verified stored-id collision — never another integrity failure
            # (a NOT NULL or vec constraint) — is reported as recoverable. The
            # presence check now runs under the write lock, so that raced INSERT is
            # itself no longer reachable from a second process (#526).
            raise
        except Exception as exc:
            # Any *other* mid-transaction failure — notably a malformed vector that
            # makes serialization raise after an earlier element was already
            # written — has been rolled back by the transaction but propagates
            # unchanged, and only MemoryStoreError may cross the seam (ADR-0028
            # §5). Without this arm a non-SQLite exception would escape the seam
            # raw.
            msg = f"failed to commit an atomic memory batch: {exc}"
            raise MemoryStoreError(msg) from exc

    def _now(self) -> datetime:
        """The guarded clock's reading, as `memory`'s own error (ADR-0026 §4).

        Read once per operation and reused for every comparison in it, so the
        record-column pre-filter (epoch) and the ``valid_from`` post-filter
        (datetime) judge every record against one consistent instant.

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _now_micros(self) -> int:
        """The guarded clock's reading as an integer microsecond UTC epoch.

        The guard is what makes this comparable with the ``expires_at`` and
        ``valid_until`` microsecond epochs stored on each record: an
        indeterminate reading would otherwise be localized to the *host* offset
        and silently shift every lifecycle decision. Microseconds (not
        :meth:`datetime.timestamp` floats) so the comparison stays exact at the
        range extremes (issue #289).

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        return _to_micros(self._now())

    @staticmethod
    def _decode(data: str) -> MemoryRecord:
        """Decode a stored JSON record, surfacing corruption as ``MemoryStoreError``."""
        try:
            return _ADAPTER.validate_json(data)
        except ValidationError as exc:
            msg = f"stored memory could not be decoded: {exc}"
            raise MemoryStoreError(msg) from exc

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if not readable.

        ``None`` when the record is absent, expired, or not live at now. The hot
        ends — ``expires_at`` and the window's ``valid_until`` — are filtered in
        SQL; the rarer ``valid_from`` (which no in-scope writer sets to the
        future) is checked on the decoded record, so both ends of the window are
        enforced (ADR-0045 §6, §9).

        The clock is read **inside** the lock, and that one reading drives both
        the SQL filter and ``live_at``: a reading taken before acquiring the lock
        could go stale while this call waits behind another and then return a
        record whose retention or validity deadline passed while it blocked.
        """
        async with self._lock:
            now = self._now()
            data = await _run_to_completion(self._get_sync, record_id, _to_micros(now))
        if data is None:
            return None
        record = self._decode(data)
        return record if record.validity.live_at(now) else None

    def _get_sync(self, record_id: str, now: int) -> str | None:
        row = self._conn.execute(
            "SELECT data FROM records WHERE id = ? "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "AND (valid_until IS NULL OR valid_until > ?)",
            (record_id, now, now),
        ).fetchone()
        return None if row is None else row[0]

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        """Return the readable records among ``record_ids``, keyed by id (ADR-0086 §6).

        **One lock acquisition, one clock reading and one read transaction**, never
        a loop over :meth:`_get_sync`. That is this store's way of meeting the
        Protocol's snapshot guarantee rather than the guarantee itself — a loop of
        singles would satisfy a clock-consistency test and buy none of the thing
        this method exists for, since it would take the lock and hop a worker
        thread once per id.

        ``record_ids`` is deduplicated on the first executed line, before the
        lock, so the observation is taken ahead of the first ``await``
        (ADR-0065) and a duplicate costs nothing downstream. An empty argument is
        answered without a round trip.
        """
        wanted = tuple(dict.fromkeys(record_ids))
        if not wanted:
            return {}
        async with self._lock:
            now = self._now()
            rows = await _run_to_completion(self._get_many_sync, wanted, _to_micros(now))
        # The `valid_from` end is checked on the decoded record, exactly as `get`
        # checks it, against the same single reading — so no two entries in one
        # result can disagree about when "now" was (ADR-0045 §6, §9).
        return {
            record.id: record
            for record in (self._decode(data) for data in rows)
            if record.validity.live_at(now)
        }

    def _get_many_sync(self, record_ids: Sequence[str], now: int) -> list[str]:
        """Read every named row, chunked to fit one statement, in one transaction.

        SQLite caps bound parameters per statement (``SQLITE_MAX_VARIABLE_NUMBER``
        — 32,766 on current builds, 999 on older ones), so an ``IN`` clause over an
        argument the contract refuses to cap has to be chunked. The chunks run
        **inside one deferred transaction**, and that is what makes the chunking
        invisible: the ``asyncio.Lock`` serialises coroutines on *this store
        instance* and does nothing about the file, so chunked without one this
        method would read ``a`` in chunk 1, let another process retire ``a`` and
        install ``b``, read ``b`` in chunk 2, and return a pair of values that never
        coexisted — the snapshot violated by the very mechanism introduced to keep
        the promise that this method never refuses on size (ADR-0086 §8).

        The limit is read from the connection rather than assumed, so a build with
        a lower cap chunks smaller instead of failing on "too many SQL variables",
        and a test can narrow it to exercise the boundary for real.

        Only the *placeholders* are interpolated; every value is bound, so the
        assembled text carries no caller data.
        """
        room = self._conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) - _GET_MANY_FIXED_PARAMS
        chunk = max(room, 1)
        base = (
            "SELECT data FROM records "
            "WHERE (expires_at IS NULL OR expires_at > ?) "
            "AND (valid_until IS NULL OR valid_until > ?)"
        )
        rows: list[str] = []
        with self._transaction("read memories in a batch", immediate=False) as conn:
            for start in range(0, len(record_ids), chunk):
                ids = record_ids[start : start + chunk]
                sql = base + f" AND id IN ({', '.join('?' * len(ids))})"
                rows.extend(row[0] for row in conn.execute(sql, [now, now, *ids]))
        return rows

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return the records most relevant to ``query`` by vector similarity.

        Args:
            query: The search text; whitespace-only queries match nothing.
            limit: Maximum number of records to return; ``<= 0`` matches nothing.
            kinds: If given, restrict results to these memory kinds (applied
                after the vector search, so results are over-fetched first).

        Returns:
            Matching records, most relevant first, each carrying a ``score``
            that is the cosine similarity to the query, in ``[0, 1]``. Expired
            records, and records not live at now (a closed or not-yet-open
            validity window, both ends — ADR-0045 §6), are never returned.

        Raises:
            MemoryStoreError: If the embedder fails or returns a wrong-sized
                query vector.

        Note:
            ``kinds`` is materialised on the coroutine's **first executed line**
            and only the copy is read thereafter — ADR-0065 §3's second discharge,
            as ``list_beliefs`` takes. It used to be materialised inside
            :meth:`_search_sync`, past the embedder's ``await`` and the lock's, so
            a caller mutating the list it passed while the embedding was in flight
            was answered from the later version (#436).
        """
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        if limit <= 0 or not query.strip():
            return []
        vector = await self._embed_one(query)
        async with self._lock:
            rows = await _run_to_completion(
                self._search_sync, vector, limit, wanted, self._now_micros()
            )
        return [self._decode(data).model_copy(update={"score": score}) for data, score in rows]

    def _search_sync(
        self,
        vector: Embedding,
        limit: int,
        wanted: frozenset[str] | None,
        now: int,
    ) -> list[tuple[str, float]]:
        # Over-fetch to leave room for kind-, expiry-, and window-filtered rows,
        # clamped to sqlite-vec's KNN ``k`` ceiling so an over-large ``limit``
        # serves a (possibly short) result instead of raising (see _VEC_KNN_MAX_K).
        fetch_k = min(limit * _RESULT_OVERFETCH, _VEC_KNN_MAX_K)
        blob = sqlite_vec.serialize_float32(list(vector))
        rows = self._conn.execute(
            "SELECT r.data, r.kind, r.expires_at, r.valid_until, v.distance FROM vec_records v "
            "JOIN records r ON r.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, fetch_k),
        ).fetchall()
        results: list[tuple[str, float]] = []
        for data, kind, expires_at, valid_until, distance in rows:
            if wanted is not None and kind not in wanted:
                continue
            if expires_at is not None and expires_at <= now:
                continue
            # Window, both ends: the hot ``valid_until`` from its column, and the
            # rare ``valid_from`` from the JSON blob (ADR-0045 §9). Applied in this
            # same post-KNN pass so a filtered row still counts against over-fetch.
            if valid_until is not None and valid_until <= now:
                continue
            valid_from = self._micros_from_json(data, "valid_from", nested="validity")
            if valid_from is not None and valid_from > now:
                continue
            # vec0 uses cosine distance; similarity is 1 - distance, floored at 0.
            results.append((data, max(0.0, 1.0 - distance)))
            if len(results) >= limit:
                break
        return results

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Enumerate live beliefs, newest revision first (ADR-0073 §1).

        **Nothing is applied after the cut.** ADR-0073 §2 binds this read more
        strictly than ``search``: there, a row dropped after the ranking cut costs a
        result the method never owed, but on a paged enumeration it drops a row no
        later page returns. So both filters and both read-time axes are applied to
        the whole candidate set, the set is ordered, and only then is
        ``[offset : offset + limit]`` taken.

        **Where each predicate runs, and why it is not all SQL.** The two lifecycle
        columns are exact integer microsecond epochs, so ``expires_at`` and
        ``valid_until`` are pre-filtered in SQL, as is ``kind`` from its own column.
        The band, the ``valid_from`` end of the window, and the sort key live only
        inside each record's JSON blob, and their stored form is **ISO text of
        variable precision** — pydantic emits ``...T00:00:00Z`` for a whole second
        and ``...T00:00:00.123456Z`` otherwise, and ``'.' < 'Z'``, so a SQL
        ``ORDER BY json_extract(...)`` or a text comparison would order a
        sub-second-precision instant *before* a whole-second one at the same second.
        Those three are therefore decided on the decoded record, where the instants
        are real ``datetime``s — still before the cut, which is what the contract
        requires. Pushing them into SQL soundly would mean new indexed columns and a
        migration, which this read does not need at a personal store's scale
        (tracked as a follow-up).

        The clock is read **inside** the lock and that one reading drives both the
        SQL pre-filter and every ``live_at`` check, so one page is judged against
        one instant — a reading taken before the lock could go stale while this call
        queued behind another (matching :meth:`get`).

        Both ``Sequence`` filters are materialised on the coroutine's **first
        executed line**, before the lock await, and only the copies are read
        thereafter: ADR-0065 §3's second discharge, required of this method by
        ADR-0073 §8. :meth:`search` now does the same; it used to materialise
        ``kinds`` only after two suspension points, which is what #436 fixed, and
        both discharges are proved by ``MemoryStoreContract`` rather than left to
        review.

        Args:
            bands: Belief bands to include; ``None`` is every band, ``()`` none.
            kinds: Memory kinds to include; ``None`` is every kind, ``()`` none.
            limit: Page size; ``0`` returns an empty page.
            offset: How many ordered, filtered records to skip.

        Returns:
            The page, each record a detached snapshot with ``score`` cleared.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            MemoryStoreError: If the store cannot be read, a stored record is
                corrupt, or the injected clock's reading is not conforming.
        """
        wanted_bands = None if bands is None else frozenset(bands)
        wanted_kinds = None if kinds is None else frozenset(str(kind) for kind in kinds)
        _check_page_bounds(limit, offset)
        selects_nothing = (wanted_bands is not None and not wanted_bands) or (
            wanted_kinds is not None and not wanted_kinds
        )
        if limit == 0 or selects_nothing:
            return []

        async with self._lock:
            now = self._now()
            rows = await _run_to_completion(self._list_beliefs_sync, wanted_kinds, _to_micros(now))
        matched = [
            record
            for record in (self._decode(data) for data in rows)
            if record.validity.live_at(now)
            and (wanted_bands is None or band_of(record.provenance.source) in wanted_bands)
        ]
        page = _newest_revision_first(matched)[offset : offset + limit]
        # Cleared, not merely absent: a record re-added after a search carries that
        # query's relevance, and nothing was ranked here (ADR-0073 §2).
        return [record.model_copy(update={"score": None}) for record in page]

    def _list_beliefs_sync(self, kinds: frozenset[str] | None, now: int) -> list[str]:
        """Read every candidate row for one page: the column predicates, unpaged.

        ``kinds`` is non-empty when it is not ``None`` — the caller short-circuits an
        empty filter — so the ``IN`` list always has at least one placeholder. Only
        the *placeholders* are interpolated; every value is bound, so the assembled
        text carries no caller data.
        """
        sql = (
            "SELECT data FROM records "
            "WHERE (expires_at IS NULL OR expires_at > ?) "
            "AND (valid_until IS NULL OR valid_until > ?)"
        )
        params: list[object] = [now, now]
        if kinds is not None:
            sql += f" AND kind IN ({', '.join('?' * len(kinds))})"
            params.extend(sorted(kinds))
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to list beliefs: {exc}"
            raise MemoryStoreError(msg) from exc
        return [row[0] for row in rows]

    async def delete(self, record_id: str) -> bool:
        """Delete one record, returning whether it existed."""
        async with self._lock:
            return await _run_to_completion(self._delete_sync, record_id)

    def _delete_sync(self, record_id: str) -> bool:
        # The early return leaves the (empty) transaction to the context manager's
        # ``COMMIT`` rather than to nothing at all: an open transaction abandoned on
        # the shared connection poisons the next ``BEGIN`` for every later caller.
        with self._transaction(f"delete memory {record_id!r}") as conn:
            row = conn.execute("SELECT rowid FROM records WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return False
            rowid = row[0]
            conn.execute("DELETE FROM vec_records WHERE rowid = ?", (rowid,))
            conn.execute("DELETE FROM records WHERE rowid = ?", (rowid,))
        return True

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed."""
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        # The count is read under the write lock, so the number returned is the
        # number this call actually removed rather than one another process
        # changed between the count and the deletion (#526).
        with self._transaction("clear the memory store") as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM records").fetchone()
            conn.execute("DELETE FROM vec_records")
            conn.execute("DELETE FROM records")
        return int(count)

    async def export(self) -> list[MemoryRecord]:
        """Return a snapshot of every retained (non-expired) record.

        Includes records whose validity window is closed — a superseded belief is
        data the store still holds, so a data-rights export keeps it (ADR-0045 §6,
        amending ADR-0007 §3); only *expired* records are excluded.

        Raises:
            MemoryStoreError: If the store cannot be read or a stored record is
                corrupt.
        """
        async with self._lock:
            rows = await _run_to_completion(self._export_sync, self._now_micros())
        return [self._decode(data) for data in rows]

    def _export_sync(self, now: int) -> list[str]:
        try:
            rows = self._conn.execute(
                "SELECT data FROM records "
                "WHERE expires_at IS NULL OR expires_at > ? ORDER BY rowid",
                (now,),
            ).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to export memories: {exc}"
            raise MemoryStoreError(msg) from exc
        return [row[0] for row in rows]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        async with self._lock:
            return await _run_to_completion(self._purge_expired_sync, self._now_micros())

    def _purge_expired_sync(self, now: int) -> int:
        with self._transaction("purge expired memories") as conn:
            rowids = [
                row[0]
                for row in conn.execute(
                    "SELECT rowid FROM records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                )
            ]
            if not rowids:
                # As in `_delete_sync`: the early return commits the empty
                # transaction rather than abandoning it on the shared connection.
                return 0
            conn.executemany("DELETE FROM vec_records WHERE rowid = ?", [(r,) for r in rowids])
            conn.executemany("DELETE FROM records WHERE rowid = ?", [(r,) for r in rowids])
        return len(rowids)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
