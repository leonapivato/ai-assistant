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
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import sqlite_vec
from pydantic import TypeAdapter

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import MemoryRecord

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding, MemoryKind

_ADAPTER: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
# When filtering by kind we over-fetch nearest neighbours, since the kind filter
# is applied after the vector search.
_KIND_OVERFETCH = 8
_OWNER_ONLY = 0o600


class SqliteMemoryStore:
    """A persistent, semantically-searchable ``MemoryStore``."""

    def __init__(self, *, path: Path | str, embedder: Embedder) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            embedder: The embedder used for all records; a store is bound to one
                embedding model for its lifetime.

        Raises:
            MemoryStoreError: If the store was previously built with a different
                embedding model or dimension.
        """
        self._embedder = embedder
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
                "kind TEXT NOT NULL, data TEXT NOT NULL)"
            )
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
        try:
            row = conn.execute("SELECT rowid FROM records WHERE id = ?", (record.id,)).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO records(id, kind, data) VALUES (?, ?, ?)",
                    (record.id, record.kind, data),
                )
                rowid = cursor.lastrowid
            else:
                rowid = row[0]
                conn.execute(
                    "UPDATE records SET kind = ?, data = ? WHERE rowid = ?",
                    (record.kind, data, rowid),
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

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent."""
        async with self._lock:
            data = await asyncio.to_thread(self._get_sync, record_id)
        return None if data is None else _ADAPTER.validate_json(data)

    def _get_sync(self, record_id: str) -> str | None:
        row = self._conn.execute("SELECT data FROM records WHERE id = ?", (record_id,)).fetchone()
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
            that is the cosine similarity to the query, in ``[0, 1]``.

        Raises:
            MemoryStoreError: If the embedder fails or returns a wrong-sized
                query vector.
        """
        if limit <= 0 or not query.strip():
            return []
        vector = await self._embed_one(query)
        async with self._lock:
            rows = await asyncio.to_thread(self._search_sync, vector, limit, kinds)
        return [
            _ADAPTER.validate_json(data).model_copy(update={"score": score}) for data, score in rows
        ]

    def _search_sync(
        self,
        vector: Embedding,
        limit: int,
        kinds: Sequence[MemoryKind] | None,
    ) -> list[tuple[str, float]]:
        wanted = {str(kind) for kind in kinds} if kinds is not None else None
        fetch_k = limit if wanted is None else limit * _KIND_OVERFETCH
        blob = sqlite_vec.serialize_float32(list(vector))
        rows = self._conn.execute(
            "SELECT r.data, r.kind, v.distance FROM vec_records v "
            "JOIN records r ON r.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, fetch_k),
        ).fetchall()
        results: list[tuple[str, float]] = []
        for data, kind, distance in rows:
            if wanted is not None and kind not in wanted:
                continue
            # vec0 uses cosine distance; similarity is 1 - distance, floored at 0.
            results.append((data, max(0.0, 1.0 - distance)))
            if len(results) >= limit:
                break
        return results

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
