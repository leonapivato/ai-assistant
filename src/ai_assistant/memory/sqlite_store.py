"""A persistent :class:`~ai_assistant.core.protocols.MemoryStore` on SQLite.

Local-first storage (ADR-0002) with semantic retrieval via ``sqlite-vec`` and an
injected :class:`~ai_assistant.core.protocols.Embedder` (ADR-0006). Records are
stored as JSON alongside their embedding; ``add`` embeds the record's content and
``search`` embeds the query and ranks by vector distance.

The database file is created with owner-only permissions (ADR-0004), and the
embedding model/dimension are recorded so opening the store with a different
embedder fails loudly rather than returning meaningless similarities.
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
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.types import MemoryRecord, MemoryWriteMode

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding, MemoryKind, MemoryWrite

_ADAPTER: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
# ``search`` applies the kind and expiry filters *after* the vector KNN (sqlite-vec
# cannot cleanly pre-filter joined columns within a KNN), so it over-fetches
# candidates to leave room for filtered-out rows. A tracked limitation: a caller
# can still be under-served if more than this multiple of ``limit`` nearer
# neighbours are all filtered out.
_RESULT_OVERFETCH = 8
_OWNER_ONLY = 0o600


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
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[Exception] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except Exception as exc:  # relayed to the caller once the thread has finished
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
            MemoryStoreError: If the store was previously built with a different
                embedding model or dimension.
        """
        self._embedder = embedder
        self._clock = checked_clock(now, owner="SqliteMemoryStore")
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            msg = f"failed to open memory store at {self._path!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
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
            conn.commit()
            self._restrict_permissions()
        except MemoryStoreError:
            conn.close()  # never leak the connection when opening fails
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

        It runs in an **explicit** transaction. SQLite auto-commits a bare DDL
        statement when no transaction is open (issue #289 review), so without the
        ``BEGIN`` a failure during the row copy would leave the schema already
        swapped and the values un-backfilled — permanently, since a later open
        would see ``INTEGER`` columns and skip migration, resurrecting expired
        rows. Inside the transaction every statement — the DDL included — rolls
        back together on any failure.
        """
        info = {row[1]: str(row[2]).upper() for row in conn.execute("PRAGMA table_info(records)")}
        if info.get("expires_at") == "INTEGER" and info.get("valid_until") == "INTEGER":
            return  # already on the microsecond-epoch schema; nothing to do
        conn.execute("BEGIN")
        try:
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
            conn.commit()
        except Exception:
            # A backfill failure (e.g. a corrupt legacy JSON blob) or any error
            # must undo the whole rewrite, DDL included, so a reopen re-attempts a
            # clean migration rather than finding a half-swapped schema. A crash
            # mid-rebuild is covered too: the uncommitted BEGIN is discarded by
            # SQLite on the next open.
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise

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
                msg = (
                    f"store was built with {key}={existing.get(key)!r}, "
                    f"but this embedder has {value!r}; re-embedding is required"
                )
                raise MemoryStoreError(msg)

    def _restrict_permissions(self) -> None:
        if self._path != ":memory:":
            Path(self._path).chmod(_OWNER_ONLY)

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
        conn = self._conn
        try:
            self._persist_record(record, vector)
            conn.commit()
        except sqlite3.Error as exc:
            # Roll back the partial multi-table write so a later commit cannot
            # persist an inconsistent record/vector pair. A rollback failure
            # (e.g. the connection is closed) must not mask the original cause.
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            msg = f"failed to store memory {record.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc

    def _persist_record(self, record: MemoryRecord, vector: Embedding) -> None:
        """Write one record and its vector into the *open* transaction, no commit.

        Shared by :meth:`add` and :meth:`write_atomic`: an overwrite rewrites every
        column and replaces the vector row; a new id inserts both. The caller owns
        the surrounding transaction — the commit and any rollback — so this is
        equally one standalone write or one element of an atomic batch (ADR-0046
        §4). Raises the underlying :class:`sqlite3.Error` unwrapped, for the caller
        to translate.
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
        conn = self._conn
        try:
            for record, mode, vector in prepared:
                if mode is MemoryWriteMode.INSERT_IF_ABSENT:
                    row = conn.execute(
                        "SELECT rowid FROM records WHERE id = ?", (record.id,)
                    ).fetchone()
                    if row is not None:
                        msg = (
                            f"cannot insert {record.id!r}: a record with that id is already stored"
                        )
                        raise MemoryStoreConflictError(msg)
                self._persist_record(record, vector)
            conn.commit()
        except MemoryStoreError:
            # The in-scope collision is *this*: the presence check above raises
            # MemoryStoreConflictError deterministically for a single writer (§4).
            # Roll the whole batch back and propagate it unchanged — it is already
            # the seam's error (ADR-0028 §5). A raced cross-process INSERT that hit
            # the records.id UNIQUE constraint instead is §5's out-of-scope
            # concurrency, which ADR-0046 §4 does *not* require reclassifying as a
            # conflict; it falls through below as MemoryStoreError, so only a
            # verified stored-id collision — never another integrity failure (a
            # NOT NULL or vec constraint) — is reported as recoverable.
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except Exception as exc:
            # Any *other* mid-transaction failure — a backend error, or a
            # malformed vector that makes serialization raise after an earlier
            # element was already written — must still roll the whole batch back,
            # and only MemoryStoreError may cross the seam (ADR-0028 §5). Catching
            # sqlite3.Error alone would let a non-SQLite exception escape with the
            # transaction still open, leaving a committable partial batch.
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
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
        """
        if limit <= 0 or not query.strip():
            return []
        vector = await self._embed_one(query)
        async with self._lock:
            rows = await _run_to_completion(
                self._search_sync, vector, limit, kinds, self._now_micros()
            )
        return [self._decode(data).model_copy(update={"score": score}) for data, score in rows]

    def _search_sync(
        self,
        vector: Embedding,
        limit: int,
        kinds: Sequence[MemoryKind] | None,
        now: int,
    ) -> list[tuple[str, float]]:
        wanted = {str(kind) for kind in kinds} if kinds is not None else None
        # Over-fetch to leave room for kind-, expiry-, and window-filtered rows.
        fetch_k = limit * _RESULT_OVERFETCH
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

    async def delete(self, record_id: str) -> bool:
        """Delete one record, returning whether it existed."""
        async with self._lock:
            return await _run_to_completion(self._delete_sync, record_id)

    def _delete_sync(self, record_id: str) -> bool:
        conn = self._conn
        try:
            row = conn.execute("SELECT rowid FROM records WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return False
            rowid = row[0]
            conn.execute("DELETE FROM vec_records WHERE rowid = ?", (rowid,))
            conn.execute("DELETE FROM records WHERE rowid = ?", (rowid,))
            conn.commit()
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            msg = f"failed to delete memory {record_id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        return True

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed."""
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        conn = self._conn
        try:
            (count,) = conn.execute("SELECT COUNT(*) FROM records").fetchone()
            conn.execute("DELETE FROM vec_records")
            conn.execute("DELETE FROM records")
            conn.commit()
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            msg = f"failed to clear the memory store: {exc}"
            raise MemoryStoreError(msg) from exc
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
        conn = self._conn
        try:
            rowids = [
                row[0]
                for row in conn.execute(
                    "SELECT rowid FROM records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                )
            ]
            if not rowids:
                return 0
            conn.executemany("DELETE FROM vec_records WHERE rowid = ?", [(r,) for r in rowids])
            conn.executemany("DELETE FROM records WHERE rowid = ?", [(r,) for r in rowids])
            conn.commit()
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            msg = f"failed to purge expired memories: {exc}"
            raise MemoryStoreError(msg) from exc
        return len(rowids)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
