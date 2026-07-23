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
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import sqlite_vec
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import MemoryRecord

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding, MemoryKind

_ADAPTER: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
# ``search`` applies the kind and expiry filters *after* the vector KNN (sqlite-vec
# cannot cleanly pre-filter joined columns within a KNN), so it over-fetches
# candidates to leave room for filtered-out rows. A tracked limitation: a caller
# can still be under-served if more than this multiple of ``limit`` nearer
# neighbours are all filtered out.
_RESULT_OVERFETCH = 8
_OWNER_ONLY = 0o600


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
                reaches a `core` field validator — the reading becomes a float
                through ``timestamp()`` — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).

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
                "kind TEXT NOT NULL, data TEXT NOT NULL, expires_at REAL, valid_until REAL)"
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
        """Add and backfill the ``expires_at`` and ``valid_until`` columns.

        Records written before a column existed carry the value only inside their
        JSON blob. Adding a column alone would leave it ``NULL``: for
        ``expires_at`` that resurrects already-expired memories (pre-ADR-0007
        tables); for ``valid_until`` ``NULL`` correctly *means* "open" so no row
        is wrongly hidden, but we still backfill it so an already-retired belief
        (a closed window persisted in JSON) keeps its column filter after the
        upgrade. Both backfills run transactionally within the setup commit, from
        each record's stored value (ADR-0045 §9). The two columns are migrated
        independently, so a table that has one but not the other is handled.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
        if "expires_at" not in columns:
            conn.execute("ALTER TABLE records ADD COLUMN expires_at REAL")
            for rowid, data in conn.execute("SELECT rowid, data FROM records").fetchall():
                expires = self._epoch_from_json(data, "expires_at")
                if expires is not None:
                    conn.execute(
                        "UPDATE records SET expires_at = ? WHERE rowid = ?", (expires, rowid)
                    )
        if "valid_until" not in columns:
            conn.execute("ALTER TABLE records ADD COLUMN valid_until REAL")
            for rowid, data in conn.execute("SELECT rowid, data FROM records").fetchall():
                valid_until = self._epoch_from_json(data, "valid_until", nested="validity")
                if valid_until is not None:
                    conn.execute(
                        "UPDATE records SET valid_until = ? WHERE rowid = ?", (valid_until, rowid)
                    )

    def _epoch_from_json(self, data: str, key: str, *, nested: str | None = None) -> float | None:
        """Read a stored ISO instant from a record's JSON, as a UTC epoch or None.

        Reads ``data[key]`` at the top level, or ``data[nested][key]`` when
        ``nested`` is given (the validity window lives under ``"validity"``). A
        missing container, a missing key, or a ``null`` value all read as
        ``None`` — an absent window end is *open*, exactly as an absent
        ``expires_at`` is *no deadline*.
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
        return instant.timestamp()

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

        Raises:
            MemoryStoreError: If the embedder fails or returns a wrong-sized
                vector, or the write fails (the write is transactional — a
                failure leaves the store unchanged).
        """
        vector = await self._embed_one(record.content)
        async with self._lock:
            await asyncio.to_thread(self._add_sync, record, vector)
        return record.id

    def _add_sync(self, record: MemoryRecord, vector: Embedding) -> None:
        conn = self._conn
        blob = sqlite_vec.serialize_float32(list(vector))
        data = record.model_dump_json()
        expires = record.expires_at.timestamp() if record.expires_at is not None else None
        valid_until = (
            record.validity.valid_until.timestamp()
            if record.validity.valid_until is not None
            else None
        )
        try:
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
            conn.commit()
        except sqlite3.Error as exc:
            # Roll back the partial multi-table write so a later commit cannot
            # persist an inconsistent record/vector pair. A rollback failure
            # (e.g. the connection is closed) must not mask the original cause.
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            msg = f"failed to store memory {record.id!r}: {exc}"
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

    def _now_epoch(self) -> float:
        """The guarded clock's reading as a POSIX timestamp, in UTC.

        The guard is what makes this comparable with the UTC ``expires_at`` and
        ``valid_until`` stored on each record: an indeterminate reading would
        otherwise be read as *host-local* by ``timestamp()`` and silently shift
        every lifecycle decision by the host offset.

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        return self._now().timestamp()

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
            data = await asyncio.to_thread(self._get_sync, record_id, now.timestamp())
        if data is None:
            return None
        record = self._decode(data)
        return record if record.validity.live_at(now) else None

    def _get_sync(self, record_id: str, now: float) -> str | None:
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
            rows = await asyncio.to_thread(
                self._search_sync, vector, limit, kinds, self._now_epoch()
            )
        return [self._decode(data).model_copy(update={"score": score}) for data, score in rows]

    def _search_sync(
        self,
        vector: Embedding,
        limit: int,
        kinds: Sequence[MemoryKind] | None,
        now: float,
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
            valid_from = self._epoch_from_json(data, "valid_from", nested="validity")
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
            return await asyncio.to_thread(self._delete_sync, record_id)

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
            return await asyncio.to_thread(self._clear_sync)

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
            rows = await asyncio.to_thread(self._export_sync, self._now_epoch())
        return [self._decode(data) for data in rows]

    def _export_sync(self, now: float) -> list[str]:
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
            return await asyncio.to_thread(self._purge_expired_sync, self._now_epoch())

    def _purge_expired_sync(self, now: float) -> int:
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
