"""Tests for the persistent SQLite-backed MemoryStore.

These touch the filesystem and the native ``sqlite-vec`` extension, so the module
is marked ``integration``. They use the deterministic ``HashingEmbedder`` so
retrieval is reproducible and offline.
"""

from __future__ import annotations

import asyncio
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import sqlite_vec
from memory_store_contract import MemoryStoreContract

from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    MemoryWrite,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _NOW


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


def _semantic(
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(),
        expires_at=expires_at,
        validity=validity or Validity(),
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


async def test_write_atomic_rolls_back_a_mid_batch_backend_failure(
    make_store: Callable[..., SqliteMemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fault-injection the shared suite cannot drive (ADR-0046 §Consequences): make
    # the *second* element's vector write fail mid-transaction and assert the first
    # element's row AND its vector row did not persist — proving a real rollback,
    # not per-element commits — and that the raised error is MemoryStoreError with
    # the sqlite3 exception retained as its cause, never a leaked provider error
    # (ADR-0028 §5). Without this an accidental per-element commit passes every
    # logical case while violating §4's all-or-nothing.
    store = make_store()
    real = sqlite_vec.serialize_float32
    calls = {"n": 0}

    def flaky(vector: object) -> bytes:
        calls["n"] += 1
        if calls["n"] >= 2:  # the second element's vector: a malformed blob
            return b"\x00"  # a bad float32 blob makes the vec_records INSERT raise
        return cast("bytes", real(vector))

    monkeypatch.setattr("ai_assistant.memory.sqlite_store.sqlite_vec.serialize_float32", flaky)
    with pytest.raises(MemoryStoreError) as exc_info:
        await store.write_atomic(
            [
                MemoryWrite(record=_semantic("a", "first element")),
                MemoryWrite(record=_semantic("b", "second element")),
            ]
        )
    monkeypatch.undo()

    assert not isinstance(exc_info.value, MemoryStoreConflictError)  # a fault, not a conflict
    assert isinstance(exc_info.value.__cause__, sqlite3.Error)  # sqlite3 cause retained
    assert await store.get("a") is None  # the first element rolled back...
    assert await store.get("b") is None
    # ...its record row and its vector row both, not just the payload.
    assert store._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM vec_records").fetchone()[0] == 0


async def test_write_atomic_recovers_to_neither_write_after_a_crash(tmp_path: Path) -> None:
    # ADR-0046 §4's durability obligation, which the in-process fault test above
    # cannot reach: a process killed mid-batch (after the first transactional write,
    # before COMMIT) must recover, on reopen, to *neither* write committed — never
    # the window-close alone, the ADR-0045 §8 regression this primitive prevents.
    db = tmp_path / "crash.db"
    child = Path(__file__).parent / "_atomic_crash_child.py"

    # Run the child off the event loop: subprocess.run blocks, and the crash test
    # only needs the child to have finished before it reopens the database.
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(child), str(db)],
        capture_output=True,
        text=True,
        check=False,
    )

    # 42 is the child's mid-batch injection point; 99 would mean the batch ran to
    # completion (no crash), 0/other a clean exit — either would void the test.
    assert result.returncode == 42, f"child did not crash mid-batch: {result.stderr}"

    reopened = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8))
    try:
        target = await reopened.get("T")
        assert target is not None  # T not left window-closed: the UPSERT rolled back
        assert target.validity.valid_until is None  # still the open, pre-batch record
        assert await reopened.get("P") is None  # the correction never landed
    finally:
        reopened.close()


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


async def test_a_naive_injected_clock_is_the_subsystems_error(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """Inverted by ADR-0026: the reading used to be attributed UTC here.

    This seam never reaches a `core` validator — the reading becomes a float
    through ``timestamp()`` — so the producer guard is the whole protection.
    """
    store = make_store(now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001  naive clock
    await store.add(_semantic("1", "coffee", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    with pytest.raises(MemoryStoreError, match="SqliteMemoryStore"):
        await store.get("1")
    with pytest.raises(MemoryStoreError, match="SqliteMemoryStore"):
        await store.search("coffee")


async def test_purge_expired_removes_only_expired_and_returns_count(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    store = make_store()
    await store.add(_semantic("live", "keeps"))
    await store.add(_semantic("dead", "goes", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    assert await store.purge_expired() == 1
    assert await store.get("live") is not None
    assert await store.purge_expired() == 0


def _write_legacy_db(
    path: Path, records: list[MemoryRecord], *, with_expires_at: bool = False
) -> None:
    """Create a legacy database whose ``records`` table predates a column.

    ``with_expires_at=False`` is the pre-ADR-0007 shape (neither ``expires_at``
    nor ``valid_until``). ``with_expires_at=True`` is the intermediate
    post-ADR-0007, pre-ADR-0045 shape: ``expires_at`` present, ``valid_until``
    absent — the table variant whose ``valid_until`` migration must run on its own.
    """
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    legacy.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [("embedding_model", "hashing-8"), ("dimensions", "8")],
    )
    if with_expires_at:
        legacy.execute(
            "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL, expires_at REAL)"
        )
        legacy.executemany(
            "INSERT INTO records(id, kind, data, expires_at) VALUES (?, ?, ?, ?)",
            [(r.id, r.kind, r.model_dump_json(), _epoch_or_none(r.expires_at)) for r in records],
        )
    else:
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


def _epoch_or_none(instant: datetime | None) -> float | None:
    return instant.timestamp() if instant is not None else None


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


def _valid_until_column(store: SqliteMemoryStore, record_id: str) -> float | None:
    """Read the raw ``records.valid_until`` column for a record, bypassing decode.

    The migration's whole job is to *populate this column* from the JSON blob, so
    a test of the backfill must assert the column itself — ``get``/``search``
    decode ``valid_from`` from JSON and could pass with the column empty, and
    ``search`` over an unpopulated ``vec_records`` yields nothing regardless.
    """
    row = store._conn.execute(
        "SELECT valid_until FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    assert row is not None
    return cast("float | None", row[0])


async def test_migration_backfills_valid_until_column_from_json(tmp_path: Path) -> None:
    # A pre-ADR-0045 database carries a record's closed window only in its JSON
    # blob; search filters valid_until from the column, so migration must backfill
    # it or a retired legacy belief would resurface in search (ADR-0045 §9). Assert
    # the column itself, not a read path that reads the window back out of JSON.
    retired_deadline = datetime(2026, 1, 2, tzinfo=UTC)
    db = tmp_path / "legacy.db"
    _write_legacy_db(
        db,
        [
            _semantic(
                "retired", "legacy coffee retired", validity=Validity(valid_until=retired_deadline)
            ),
            _semantic("live", "legacy coffee live"),
        ],
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert "valid_until" in columns
        # The backfill populated the column for the retired record and left the
        # live one NULL (= open) — the property search's column pre-filter relies on.
        assert _valid_until_column(store, "retired") == retired_deadline.timestamp()
        assert _valid_until_column(store, "live") is None
        # And the read paths honour it: retired is hidden from get, retained by export.
        assert await store.get("retired") is None
        assert await store.get("live") is not None
        assert {r.id for r in await store.export()} == {"retired", "live"}
    finally:
        store.close()


async def test_migration_adds_valid_until_to_a_post_expires_at_table(
    tmp_path: Path,
) -> None:
    # The intermediate shape: expires_at already present, valid_until absent. Only
    # the valid_until migration block should run, and it must backfill the closed
    # window from JSON just the same.
    retired_deadline = datetime(2026, 1, 2, tzinfo=UTC)
    db = tmp_path / "intermediate.db"
    _write_legacy_db(
        db,
        [
            _semantic(
                "retired", "legacy coffee retired", validity=Validity(valid_until=retired_deadline)
            ),
            _semantic("live", "legacy coffee live"),
        ],
        with_expires_at=True,
    )

    store = SqliteMemoryStore(path=db, embedder=HashingEmbedder(dimensions=8), now=_fixed_now)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(records)")}
        assert {"expires_at", "valid_until"} <= columns
        # The valid_until block ran on its own and backfilled the column.
        assert _valid_until_column(store, "retired") == retired_deadline.timestamp()
        assert _valid_until_column(store, "live") is None
        assert await store.get("retired") is None
        assert {r.id for r in await store.export()} == {"retired", "live"}
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


class TestSqliteMemoryStoreContract(MemoryStoreContract):
    """Runs SqliteMemoryStore through the shared MemoryStore conformance suite.

    Inherits this module's ``integration`` mark (native sqlite-vec + filesystem);
    ``make_store`` closes the store on teardown.
    """

    @pytest.fixture
    def store(self, make_store: Callable[..., SqliteMemoryStore]) -> MemoryStore:
        return make_store()

    @pytest.fixture
    def store_factory(
        self, make_store: Callable[..., SqliteMemoryStore]
    ) -> Callable[[Callable[[], datetime]], MemoryStore]:
        return lambda now: make_store(now=now)
