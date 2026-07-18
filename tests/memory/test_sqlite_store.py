"""Tests for the persistent SQLite-backed MemoryStore.

These touch the filesystem and the native ``sqlite-vec`` extension, so the module
is marked ``integration``. They use the deterministic ``HashingEmbedder`` so
retrieval is reproducible and offline.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _NOW


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


def _semantic(record_id: str, content: str, *, expires_at: datetime | None = None) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(),
        expires_at=expires_at,
    )


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


class _FlakyEmbedder:
    """A misbehaving embedder for exercising the store's error boundary.

    Returns valid vectors until one of the fault flags is set: ``fail`` yields a
    wrong-sized vector, ``boom`` raises (mimicking a provider outage), and
    ``malformed`` returns a contract-violating result element (``None``).
    """

    def __init__(self) -> None:
        self._inner = HashingEmbedder(dimensions=8)
        self.fail = False
        self.boom = False
        self.malformed = False

    @property
    def model_id(self) -> str:
        return "flaky-8"

    @property
    def dimensions(self) -> int:
        return 8

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if self.boom:
            msg = "provider outage"
            raise RuntimeError(msg)
        if self.malformed:
            return cast("list[Embedding]", [None for _ in texts])  # non-sized element
        if self.fail:
            return [[0.0, 0.0, 0.0] for _ in texts]  # wrong length (3 != 8)
        return await self._inner.embed(texts)


@pytest.fixture
def make_store(tmp_path: Path) -> Iterator[Callable[..., SqliteMemoryStore]]:
    """Build stores that are closed on teardown so temp files release cleanly."""
    created: list[SqliteMemoryStore] = []

    def _make(
        *,
        embedder: Embedder | None = None,
        dimensions: int = 256,
        now: Callable[[], datetime] = _fixed_now,
    ) -> SqliteMemoryStore:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=embedder if embedder is not None else HashingEmbedder(dimensions=dimensions),
            now=now,
        )
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


def test_store_conforms_to_protocol(make_store: Callable[..., SqliteMemoryStore]) -> None:
    assert isinstance(make_store(), MemoryStore)


async def test_add_and_get_round_trips_typed_record(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()

    await store.add(_preference("p1", "prefers concise replies"))
    got = await store.get("p1")

    assert isinstance(got, PreferenceMemory)
    assert got.id == "p1"
    assert got.preference == "prefers concise replies"


async def test_get_missing_returns_none(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    assert await store.get("nope") is None


async def test_search_ranks_by_similarity_and_scores(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("c1", "coffee tea"))
    await store.add(_semantic("c2", "coffee milk"))
    await store.add(_semantic("r1", "rocket ship"))

    results = await store.search("coffee")

    assert {results[0].id, results[1].id} == {"c1", "c2"}
    assert results[-1].id == "r1"
    assert results[0].score is not None
    assert results[0].score > results[-1].score  # type: ignore[operator]


async def test_add_overwrites_same_id(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()

    await store.add(_semantic("1", "old note about tea"))
    await store.add(_semantic("1", "new note about coffee"))

    got = await store.get("1")
    assert got is not None
    assert got.content == "new note about coffee"


async def test_search_filters_by_kind(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("s", "coffee fact"))
    await store.add(_preference("p", "coffee preference"))

    results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

    assert [r.id for r in results] == ["p"]


async def test_empty_query_matches_nothing(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("1", "some content"))
    assert await store.search("   ") == []


async def test_non_positive_limit_matches_nothing(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "coffee"))

    assert await store.search("coffee", limit=0) == []
    assert await store.search("coffee", limit=-3) == []


async def test_failed_write_leaves_store_unchanged(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)
    await store.add(_semantic("1", "original content"))

    embedder.fail = True
    with pytest.raises(MemoryStoreError):
        await store.add(_semantic("1", "corrupt overwrite"))

    embedder.fail = False
    got = await store.get("1")
    assert got is not None
    assert got.content == "original content"  # the failed overwrite did not apply
    assert [r.id for r in await store.search("original")] == ["1"]  # still consistent


async def test_rollback_on_mid_transaction_failure(
    make_store: Callable[..., SqliteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store()
    await store.add(_semantic("1", "original content"))

    # A malformed serialized vector makes the vec_records INSERT fail *after* the
    # record UPDATE/DELETE in an overwrite, so this exercises the rollback path
    # itself (not the up-front length guard).
    monkeypatch.setattr(
        "ai_assistant.memory.sqlite_store.sqlite_vec.serialize_float32",
        lambda _vector: b"\x00",
    )
    with pytest.raises(MemoryStoreError):
        await store.add(_semantic("1", "overwrite that fails mid-write"))

    monkeypatch.undo()
    got = await store.get("1")
    assert got is not None
    assert got.content == "original content"  # UPDATE/DELETE were rolled back


async def test_embedder_exception_is_wrapped_as_store_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)

    embedder.boom = True
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.add(_semantic("1", "content"))
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.search("content")

    embedder.boom = False
    embedder.malformed = True  # a non-sized result element must not leak a TypeError
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await store.add(_semantic("1", "content"))


async def test_wrong_sized_query_vector_raises_store_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    embedder = _FlakyEmbedder()
    store = make_store(embedder=embedder)
    await store.add(_semantic("1", "content"))

    embedder.fail = True  # search now embeds the query to a wrong-sized vector
    with pytest.raises(MemoryStoreError, match="expected 8"):
        await store.search("content")


async def test_connect_failure_is_wrapped(tmp_path: Path) -> None:
    # A path under a non-existent directory makes sqlite3.connect() itself raise,
    # before any connection exists to close.
    missing = tmp_path / "no_such_dir" / "memory.db"
    with pytest.raises(MemoryStoreError, match="failed to open memory store"):
        SqliteMemoryStore(path=missing, embedder=HashingEmbedder(dimensions=8))


async def test_setup_failure_is_wrapped_and_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force a failure *after* the connection is opened; the store must translate
    # it to MemoryStoreError and close the half-open connection (no leak).
    captured: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _capturing_connect(database: str, *, check_same_thread: bool = True) -> sqlite3.Connection:
        conn = real_connect(database, check_same_thread=check_same_thread)
        captured.append(conn)
        return conn

    def _boom(_conn: object) -> None:
        raise sqlite3.OperationalError("cannot load extension")

    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite3.connect", _capturing_connect)
    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite_vec.load", _boom)

    with pytest.raises(MemoryStoreError, match="failed to open memory store"):
        SqliteMemoryStore(path=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=8))

    assert len(captured) == 1  # a connection was opened
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")  # ...and closed on the failure path


async def test_delete_removes_record_and_reports_existence(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "a fact"))

    assert await store.delete("1") is True
    assert await store.get("1") is None
    assert await store.search("fact") == []  # vector row gone too
    assert await store.delete("1") is False  # already gone


async def test_clear_removes_all_and_returns_count(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "one"))
    await store.add(_semantic("2", "two"))

    assert await store.clear() == 2
    assert await store.get("1") is None
    assert await store.search("one") == []
    assert await store.clear() == 0


async def test_export_returns_live_records_only(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("live", "still valid"))
    await store.add(_semantic("dead", "gone", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    exported = await store.export()

    assert [r.id for r in exported] == ["live"]
    assert isinstance(exported[0], SemanticMemory)  # typed, not a blob


async def test_expired_records_are_hidden_from_get_and_search(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "coffee fact", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))
    await store.add(_semantic("2", "coffee fact live"))

    assert await store.get("1") is None
    assert [r.id for r in await store.search("coffee")] == ["2"]  # expired one filtered out


async def test_purge_expired_removes_only_expired_and_returns_count(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("live", "keeps"))
    await store.add(_semantic("dead", "goes", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    assert await store.purge_expired() == 1
    assert await store.get("live") is not None
    assert await store.purge_expired() == 0


def _write_legacy_db(path: Path, records: list[MemoryRecord]) -> None:
    """Create a pre-ADR-0007 database (records table without expires_at)."""
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    legacy.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [("embedding_model", "hashing-8"), ("dimensions", "8")],
    )
    legacy.execute(
        "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
        "kind TEXT NOT NULL, data TEXT NOT NULL)"
    )
    legacy.executemany(
        "INSERT INTO records(id, kind, data) VALUES (?, ?, ?)",
        [(r.id, r.kind, r.model_dump_json()) for r in records],
    )
    legacy.commit()
    legacy.close()


async def test_migration_adds_expires_at_column_and_accepts_writes(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _write_legacy_db(db, [])

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert "expires_at" in columns
        await store.add(_semantic("1", "post-migration write"))
        assert await store.get("1") is not None
    finally:
        store.close()


async def test_migration_backfills_expiry_so_legacy_expired_stays_forgotten(
    tmp_path: Path,
) -> None:
    # Pre-ADR-0007 records carry expires_at only inside their JSON. Migration must
    # backfill it, or an already-expired legacy memory would come back to life.
    db = tmp_path / "legacy.db"
    _write_legacy_db(
        db,
        [
            _semantic("expired", "legacy expired", expires_at=datetime(2026, 1, 2, tzinfo=UTC)),
            _semantic("live", "legacy live"),
        ],
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        assert await store.get("expired") is None  # backfilled deadline honoured
        assert await store.get("live") is not None
        assert [r.id for r in await store.export()] == ["live"]
        assert await store.purge_expired() == 1
    finally:
        store.close()


async def test_export_wraps_corrupt_stored_record(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("1", "fine"))
    store._conn.execute("UPDATE records SET data = ? WHERE id = ?", ("not-json", "1"))
    store._conn.commit()

    with pytest.raises(MemoryStoreError, match="could not be decoded"):
        await store.export()


async def test_persists_across_reopen(make_store: Callable[..., SqliteMemoryStore]) -> None:
    store = make_store()
    await store.add(_semantic("1", "durable memory"))
    store.close()

    reopened = make_store()
    got = await reopened.get("1")
    assert got is not None
    assert got.content == "durable memory"


async def test_reopening_with_different_embedder_raises(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store(dimensions=256)
    await store.add(_semantic("1", "x"))
    store.close()

    with pytest.raises(MemoryStoreError, match="re-embedding is required"):
        make_store(dimensions=128)


def test_database_file_is_owner_only(
    make_store: Callable[..., SqliteMemoryStore], tmp_path: Path
) -> None:
    make_store()
    mode = (tmp_path / "memory.db").stat().st_mode & 0o777
    assert mode == 0o600
