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
import structlog
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import MemoryRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding, MemoryKind

_log = structlog.get_logger(__name__)

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


#: The one stored key this store may read as UTC — and deliberately only this one.
#:
#: ADR-0023 §3 permits attribution "exactly where provenance is known — in the
#: adapter that decoded the value, which knows it wrote UTC". This store knows it
#: for ``expires_at`` and for nothing else: the field carried a UTC-attributing
#: validator on construction, :meth:`SqliteMemoryStore._add_sync` indexes it as
#: ``expires_at.timestamp()``, and :meth:`_expires_epoch_from_json` reads a naive
#: one as UTC — three places that all treat a stored deadline as UTC.
#:
#: A ``MemoryRecord`` holds three further instants: ``occurred_at``,
#: ``valid_until`` and ``provenance.last_updated``. Until ADR-0023 they had **no
#: validator at all**, so the store wrote exactly what it was handed and
#: established nothing. A legacy naive ``occurred_at`` of ``09:00`` may be a
#: user's own wall clock, and reading it as ``09:00Z`` would be the fabrication
#: §3 exists to forbid — done by the one layer with no grounds to. They are left
#: to fail loudly, and what to do for them is #167/#168's recorded decision, not
#: this decoder's guess.
#:
#: Keyed by name rather than inferred from the model, so a free-text field that
#: happens to parse as a date is never rewritten.
_INSTANT_KEYS = frozenset({"expires_at"})


def _utc_attributed(value: object, *, key: str | None) -> tuple[object, bool]:
    """Return ``value`` with naive instants read as UTC, and whether any changed."""
    if isinstance(value, dict):
        rebuilt: dict[str, object] = {}
        changed = False
        for name, item in value.items():
            rebuilt[name], item_changed = _utc_attributed(item, key=name)
            changed = changed or item_changed
        return rebuilt, changed
    if isinstance(value, list):
        pairs = [_utc_attributed(item, key=key) for item in value]
        return [item for item, _ in pairs], any(item_changed for _, item_changed in pairs)
    if key in _INSTANT_KEYS and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value, False
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC).isoformat(), True
    return value, False


def _utc_attributed_json(data: str) -> str | None:
    """Re-render ``data`` with naive instants read as UTC, or ``None`` if unchanged.

    ``None`` covers both "nothing to repair" and "not even JSON", so the caller
    reports the original validation failure rather than a second, less
    informative one.
    """
    try:
        decoded = json.loads(data)
    except ValueError:
        return None
    repaired, changed = _utc_attributed(decoded, key=None)
    return json.dumps(repaired) if changed else None


class SqliteMemoryStore:
    """A persistent, semantically-searchable ``MemoryStore``."""

    def __init__(
        self,
        *,
        path: Path | str,
        embedder: Embedder,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            embedder: The embedder used for all records; a store is bound to one
                embedding model for its lifetime.
            now: Clock used to decide whether a record has expired; injectable
                for deterministic tests. Defaults to UTC wall-clock.

        Raises:
            MemoryStoreError: If the store was previously built with a different
                embedding model or dimension.
        """
        self._embedder = embedder
        self._now = now
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
                "kind TEXT NOT NULL, data TEXT NOT NULL, expires_at REAL)"
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
        """Add and backfill the ``expires_at`` column for a pre-ADR-0007 table.

        Records written before this slice carry their retention deadline only
        inside the JSON blob. Adding the column alone would leave it ``NULL`` and
        resurrect already-expired memories, so we backfill it from each record's
        stored ``expires_at`` (transactionally, within the setup commit).
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
        if "expires_at" in columns:
            return
        conn.execute("ALTER TABLE records ADD COLUMN expires_at REAL")
        for rowid, data in conn.execute("SELECT rowid, data FROM records").fetchall():
            expires = self._expires_epoch_from_json(data)
            if expires is not None:
                conn.execute("UPDATE records SET expires_at = ? WHERE rowid = ?", (expires, rowid))

    def _expires_epoch_from_json(self, data: str) -> float | None:
        """Read a record's retention deadline from its JSON, as an epoch or None."""
        try:
            raw = json.loads(data).get("expires_at")
            if raw is None:
                return None
            deadline = datetime.fromisoformat(raw)
        except (ValueError, TypeError, AttributeError) as exc:
            msg = f"failed to read a retention deadline during migration: {exc}"
            raise MemoryStoreError(msg) from exc
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return deadline.timestamp()

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
        try:
            row = conn.execute("SELECT rowid FROM records WHERE id = ?", (record.id,)).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO records(id, kind, data, expires_at) VALUES (?, ?, ?, ?)",
                    (record.id, record.kind, data, expires),
                )
                rowid = cursor.lastrowid
            else:
                rowid = row[0]
                conn.execute(
                    "UPDATE records SET kind = ?, data = ?, expires_at = ? WHERE rowid = ?",
                    (record.kind, data, expires, rowid),
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

    def _now_epoch(self) -> float:
        # Normalise a naive clock result to UTC so expiry is consistent with the
        # UTC-normalised expires_at stored on each record (rather than host-local).
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.timestamp()

    @staticmethod
    def _decode(data: str) -> MemoryRecord:
        """Decode a stored JSON record, reading a legacy naive deadline as UTC.

        ADR-0023 §3 makes ``core`` reject a naive datetime, because a shared type
        cannot know whether attributing UTC restores a fact or invents one, and
        moves attribution to "the adapter that decoded the value, which knows it
        wrote UTC and may therefore say so". This store knows that of exactly one
        field — see :data:`_INSTANT_KEYS`, which is why the repair is scoped to a
        single key rather than to every instant a record holds.

        Without it a persisted naive ``expires_at`` would stop decoding the
        moment ``core`` tightened, and a live record would become unreadable —
        which ADR-0004 §6 and ADR-0007 §3 forbid, since a row a user may view,
        export and delete may not be dropped or hidden by a migration. That is
        the constraint that makes rejecting it not an available option here.

        The repair is attempted only after a strict pass has failed, so a
        conforming row costs nothing; anything still invalid afterwards is
        genuine corruption and is reported as such.

        **The warning it emits is a diagnostic, not the data-rights record.** It
        names no identifier and carries no record content — logs are Tier 2 and
        may hold neither (ADR-0004 §5) — so it says that a row was read this way,
        not which. Whether the assumption must additionally be carried per row,
        through ``MemoryStore.export()``, is a ``core`` contract question ADR-0023
        §3 reserves; it is tracked in #168, not answered here.

        Raises:
            MemoryStoreError: If the row cannot be decoded even with UTC read
                into a naive deadline.
        """
        try:
            return _ADAPTER.validate_json(data)
        except ValidationError as exc:
            repaired = _utc_attributed_json(data)
            if repaired is None:
                msg = f"stored memory could not be decoded: {exc}"
                raise MemoryStoreError(msg) from exc
            try:
                record = _ADAPTER.validate_json(repaired)
            except ValidationError as retry_exc:
                msg = f"stored memory could not be decoded: {retry_exc}"
                raise MemoryStoreError(msg) from retry_exc
            _log.warning(
                "stored_deadline_read_as_utc",
                detail="a stored naive expires_at was read as UTC (ADR-0023 §3)",
            )
            return record

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent or expired."""
        async with self._lock:
            data = await asyncio.to_thread(self._get_sync, record_id, self._now_epoch())
        return None if data is None else self._decode(data)

    def _get_sync(self, record_id: str, now: float) -> str | None:
        row = self._conn.execute(
            "SELECT data FROM records WHERE id = ? AND (expires_at IS NULL OR expires_at > ?)",
            (record_id, now),
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
            records are never returned.

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
        # Over-fetch to leave room for kind- and expiry-filtered rows.
        fetch_k = limit * _RESULT_OVERFETCH
        blob = sqlite_vec.serialize_float32(list(vector))
        rows = self._conn.execute(
            "SELECT r.data, r.kind, r.expires_at, v.distance FROM vec_records v "
            "JOIN records r ON r.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, fetch_k),
        ).fetchall()
        results: list[tuple[str, float]] = []
        for data, kind, expires_at, distance in rows:
            if wanted is not None and kind not in wanted:
                continue
            if expires_at is not None and expires_at <= now:
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
        """Return a snapshot of all live (non-expired) records.

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
