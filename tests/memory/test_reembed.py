"""Tests for the re-embedding migration (ADR-0104).

These touch the filesystem and the native ``sqlite-vec`` extension, so the module
is marked ``integration``. Both embedding spaces are ``HashingEmbedder`` at
different widths, which is enough to make the two ``model_id`` values differ and
keeps every case offline and deterministic.

The cases are organised around what ADR-0104 actually rules, because most of the
value here is in the failure paths: the live store is not written before the
swap, an interrupted run resumes without re-embedding what it already did, and
nothing is swapped in that has not been re-read against the source.
"""

from __future__ import annotations

import errno
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlite_vec

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    MemoryRecord,
    MemorySource,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory import reembed as reembed_module
from ai_assistant.memory.reembed import (
    BACKUP_SUFFIX,
    WORK_SUFFIX,
    Reembedder,
    ReembedPlan,
)
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import Embedding

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: Every column of ``records``, for the case that asserts the migration changes
#: none of them. A module-level literal, never caller data.
_ALL_COLUMNS = "SELECT rowid, id, kind, data, expires_at, valid_until, about_person FROM records"

#: The two embedding spaces every case migrates between. Different widths, so the
#: ``vec0`` column is rebuilt too and a copied vector could not accidentally pass.
_OLD = 8
_NEW = 16


def _record(
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
    about_person: str | None = None,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        expires_at=expires_at,
        validity=validity or Validity(),
        about_person=about_person,
    )


async def _seed(path: Path, records: Sequence[MemoryRecord], *, dimensions: int = _OLD) -> None:
    """Write ``records`` into a store tagged with the ``dimensions``-wide embedder."""
    store = SqliteMemoryStore(path=path, embedder=HashingEmbedder(dimensions=dimensions))
    try:
        for record in records:
            await store.add(record)
    finally:
        store.close()


def _read(path: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(path))
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return [tuple(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _meta(path: Path) -> dict[str, str]:
    return {str(key): str(value) for key, value in _read(path, "SELECT key, value FROM meta")}


class _CountingEmbedder:
    """A ``HashingEmbedder`` that counts what it was asked to embed, and can fail.

    ``fail_after`` is what makes an interruption testable: the run dies partway
    with some chunks already committed, which is the state ADR-0104 §2 is about.
    """

    def __init__(self, *, dimensions: int = _NEW, fail_after: int | None = None) -> None:
        self._inner = HashingEmbedder(dimensions=dimensions)
        self._fail_after = fail_after
        self.embedded = 0

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if self._fail_after is not None and self.embedded >= self._fail_after:
            msg = "the embedding runtime went away"
            raise RuntimeError(msg)
        self.embedded += len(texts)
        return await self._inner.embed(texts)


async def test_a_store_built_by_another_embedder_is_re_embedded_and_opens(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso"), _record("b", "oat milk")])

    target = HashingEmbedder(dimensions=_NEW)
    outcome = await Reembedder(store=store, embedder=target).run()

    assert outcome.swapped
    assert outcome.embedded == 2
    assert _meta(store) == {"embedding_model": target.model_id, "dimensions": str(_NEW)}
    # The store the refusal blocked now opens against the new embedder, which is
    # the whole point of the migration (#425).
    opened = SqliteMemoryStore(path=store, embedder=target)
    try:
        assert {record.id for record in await opened.export()} == {"a", "b"}
        assert [record.id for record in await opened.search("espresso", limit=1)] == ["a"]
    finally:
        opened.close()


async def test_a_store_already_carrying_the_target_tag_is_left_alone(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")], dimensions=_NEW)
    before = store.read_bytes()

    outcome = await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert not outcome.swapped
    assert outcome.plan.required is False
    assert store.read_bytes() == before
    assert not (tmp_path / f"memory.db{WORK_SUFFIX}").exists()
    assert not (tmp_path / f"memory.db{BACKUP_SUFFIX}").exists()


async def test_the_pre_migration_store_is_retained_and_still_readable(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])

    await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    backup = tmp_path / f"memory.db{BACKUP_SUFFIX}"
    assert backup.is_file()
    # Retained means *usable*: it still opens against the embedder that wrote it,
    # which is what makes it a way back rather than a souvenir (ADR-0104 §3).
    old = SqliteMemoryStore(path=backup, embedder=HashingEmbedder(dimensions=_OLD))
    try:
        assert [record.id for record in await old.export()] == ["a"]
    finally:
        old.close()
    assert _meta(backup)["dimensions"] == str(_OLD)


async def test_the_work_file_is_gone_once_the_swap_has_happened(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])

    await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert not (tmp_path / f"memory.db{WORK_SUFFIX}").exists()


async def test_rowids_and_stored_json_survive_the_migration_byte_for_byte(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    records = [
        _record("a", "espresso", expires_at=_WHEN + timedelta(days=365)),
        _record("b", "oat milk", validity=Validity(valid_until=_WHEN + timedelta(days=30))),
        _record("c", "decaf after six", about_person="Sam"),
    ]
    await _seed(store, records)
    before = _read(store, f"{_ALL_COLUMNS} ORDER BY rowid")

    await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    after = _read(store, f"{_ALL_COLUMNS} ORDER BY rowid")
    # Every column, the rowid included: ADR-0104 §1 preserves the rowid because
    # `SqliteMemoryStore.export` orders by it, so renumbering would silently
    # reorder a data-rights export.
    assert after == before


async def test_only_the_vectors_change(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    before = _read(store, "SELECT rowid, embedding FROM vec_records")

    await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    after = _read(store, "SELECT rowid, embedding FROM vec_records")
    assert [row[0] for row in after] == [row[0] for row in before]
    assert after[0][1] != before[0][1]
    widened = after[0][1]
    assert isinstance(widened, bytes)
    assert len(widened) == _NEW * 4  # float32 per dimension


async def test_a_legacy_store_without_the_later_columns_migrates(tmp_path: Path) -> None:
    """The four columns ADR-0104 §1 reads are the four that have always existed.

    Built by hand in the pre-``expires_at`` shape, which is what a store old
    enough to still carry a hashing tag actually looks like — and which the
    current build cannot open at all, since bringing its schema forward would
    mean writing to the live store.
    """
    store = tmp_path / "memory.db"
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [("embedding_model", f"hashing-{_OLD}"), ("dimensions", str(_OLD))],
        )
        conn.execute(
            "CREATE TABLE records(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
            "kind TEXT NOT NULL, data TEXT NOT NULL)"
        )
        record = _record("a", "espresso", expires_at=_WHEN + timedelta(days=365))
        conn.execute(
            "INSERT INTO records(rowid, id, kind, data) VALUES (?, ?, ?, ?)",
            (1, record.id, record.kind, record.model_dump_json()),
        )
        conn.commit()
    finally:
        conn.close()

    target = HashingEmbedder(dimensions=_NEW)
    outcome = await Reembedder(store=store, embedder=target).run()

    assert outcome.swapped
    # The columns the legacy table never had are re-derived from the blob, so the
    # migrated store is the *current* shape without the source being touched.
    rows = _read(store, "SELECT expires_at, valid_until, about_person FROM records")
    assert rows[0][0] is not None
    assert rows[0][1] is None
    assert rows[0][2] is None
    opened = SqliteMemoryStore(path=store, embedder=target)
    try:
        assert [record.id for record in await opened.export()] == ["a"]
    finally:
        opened.close()


async def test_an_interrupted_run_leaves_the_live_store_untouched(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(6)])
    before = store.read_bytes()

    broken = _CountingEmbedder(fail_after=4)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    # The point of build-and-swap: a crash midway never produces a store carrying
    # two model ids, because the live file was never written (ADR-0104 §1).
    assert store.read_bytes() == before
    assert _meta(store)["dimensions"] == str(_OLD)
    assert not (tmp_path / f"memory.db{BACKUP_SUFFIX}").exists()


async def test_a_resumed_run_re_embeds_only_what_is_left(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(6)])

    broken = _CountingEmbedder(fail_after=4)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()
    assert broken.embedded == 4

    resumed = _CountingEmbedder()
    outcome = await Reembedder(store=store, embedder=resumed, batch_size=2).run()

    assert outcome.swapped
    assert outcome.resumed == 4
    assert outcome.embedded == 2
    assert resumed.embedded == 2
    assert len(_read(store, "SELECT rowid FROM records")) == 6


async def test_a_source_that_changed_between_attempts_is_re_embedded_from_scratch(
    tmp_path: Path,
) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(6)])

    broken = _CountingEmbedder(fail_after=4)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    # The hub ran between the two attempts. A resumed scan starts past the cursor
    # and would never revisit the rows below it, so the half-built copy is stale
    # in a way no later chunk corrects (ADR-0104 §2).
    await _seed(store, [_record("late", "a memory written after the interruption")])

    resumed = _CountingEmbedder()
    outcome = await Reembedder(store=store, embedder=resumed, batch_size=2).run()

    assert outcome.resumed == 0
    assert outcome.embedded == 7
    assert len(_read(store, "SELECT rowid FROM records")) == 7


async def test_a_work_store_built_for_a_different_target_is_discarded(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(4)])

    broken = _CountingEmbedder(dimensions=_NEW, fail_after=2)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    other = _CountingEmbedder(dimensions=32)
    outcome = await Reembedder(store=store, embedder=other, batch_size=2).run()

    assert outcome.resumed == 0
    assert outcome.embedded == 4
    assert _meta(store)["dimensions"] == "32"


async def test_a_work_store_missing_a_record_is_refused_rather_than_swapped(
    tmp_path: Path,
) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(6)])

    broken = _CountingEmbedder(fail_after=4)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    # A chunk the cursor claims but the store does not hold — the exact failure a
    # count-only check would pass and §3's re-read is written for.
    work = tmp_path / f"memory.db{WORK_SUFFIX}"
    conn = sqlite3.connect(str(work))
    try:
        conn.execute("DELETE FROM records WHERE rowid = 1")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MemoryStoreError, match="was not swapped in"):
        await Reembedder(store=store, embedder=_CountingEmbedder(), batch_size=2).run()

    assert _meta(store)["dimensions"] == str(_OLD)


async def test_a_work_store_whose_record_was_edited_is_refused(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(6)])

    broken = _CountingEmbedder(fail_after=4)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    work = tmp_path / f"memory.db{WORK_SUFFIX}"
    conn = sqlite3.connect(str(work))
    try:
        conn.execute("UPDATE records SET kind = 'tampered' WHERE rowid = 1")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MemoryStoreError, match="differs from the live store"):
        await Reembedder(store=store, embedder=_CountingEmbedder(), batch_size=2).run()

    assert _meta(store)["dimensions"] == str(_OLD)


async def test_the_swapped_in_store_carries_no_migration_scaffolding(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])

    await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert set(_meta(store)) == {"embedding_model", "dimensions"}


async def test_an_occupied_backup_path_refuses_before_anything_is_swapped(
    tmp_path: Path,
) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    backup = tmp_path / f"memory.db{BACKUP_SUFFIX}"
    backup.write_text("somebody else's file")

    with pytest.raises(IncompatibleStateError) as caught:
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert "move or delete" in caught.value.operator_action
    assert backup.read_text() == "somebody else's file"
    assert _meta(store)["dimensions"] == str(_OLD)


async def test_a_backup_link_left_by_an_interrupted_swap_is_reused(tmp_path: Path) -> None:
    """A link to *this store's own inode* is a previous attempt's, not a stranger's."""
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    backup = tmp_path / f"memory.db{BACKUP_SUFFIX}"
    backup.hardlink_to(store)

    outcome = await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert outcome.swapped
    assert _meta(backup)["dimensions"] == str(_OLD)


async def test_a_sidecar_beside_the_store_refuses_before_any_embedding(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    (tmp_path / "memory.db-wal").write_bytes(b"committed pages a rename would destroy")

    embedder = _CountingEmbedder()
    with pytest.raises(IncompatibleStateError, match="another process") as caught:
        await Reembedder(store=store, embedder=embedder).run()

    assert embedder.embedded == 0
    assert "stop whatever has" in caught.value.operator_action


async def test_a_wal_mode_store_refuses_before_any_embedding(tmp_path: Path) -> None:
    """WAL survives a close in the header, so it presents as sidecar-free."""
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    assert not (tmp_path / "memory.db-wal").exists()

    embedder = _CountingEmbedder()
    with pytest.raises(IncompatibleStateError, match="WAL mode"):
        await Reembedder(store=store, embedder=embedder).run()

    assert embedder.embedded == 0
    assert _meta(store)["dimensions"] == str(_OLD)


async def test_an_absent_store_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MemoryStoreError, match="no memory store at"):
        Reembedder(store=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=_NEW)).plan()


async def test_a_file_that_is_not_a_memory_store_is_refused(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    store.write_text("not a database")

    with pytest.raises(MemoryStoreError):
        Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).plan()


async def test_an_undecodable_record_aborts_and_names_it(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("UPDATE records SET data = ? WHERE id = 'a'", ('{"broken": true}',))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MemoryStoreError, match="'a'"):
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert _meta(store)["dimensions"] == str(_OLD)


class _WrongWidthEmbedder:
    """Returns vectors of the wrong width, which must not reach the store."""

    model_id = "wrong-width"
    dimensions = _NEW

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        return [[0.0] * (_NEW + 1) for _ in texts]


async def test_a_wrong_shaped_batch_from_the_embedder_aborts(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])

    embedder: Embedder = _WrongWidthEmbedder()
    with pytest.raises(MemoryStoreError, match="expected 16"):
        await Reembedder(store=store, embedder=embedder).run()

    assert _meta(store)["dimensions"] == str(_OLD)


async def test_progress_is_reported_per_committed_chunk(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(5)])
    seen: list[tuple[int, int]] = []

    def record_progress(done: int, total: int) -> None:
        seen.append((done, total))

    await Reembedder(store=store, embedder=_CountingEmbedder(), batch_size=2).run(
        progress=record_progress
    )

    assert seen == [(2, 5), (4, 5), (5, 5)]


async def test_a_plan_reports_what_a_run_would_do(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(3)])

    plan = Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).plan()

    assert plan.required
    assert plan.source_model == f"hashing-{_OLD}"
    assert plan.source_dimensions == _OLD
    assert plan.target_model == f"hashing-{_NEW}"
    assert plan.records == 3
    assert plan.resumable == 0
    assert plan.outstanding == 3
    assert plan.work.name == f"memory.db{WORK_SUFFIX}"
    assert plan.backup.name == f"memory.db{BACKUP_SUFFIX}"


def test_a_batch_size_below_one_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        Reembedder(
            store=tmp_path / "memory.db",
            embedder=HashingEmbedder(dimensions=_NEW),
            batch_size=0,
        )


async def test_an_empty_store_migrates_to_the_new_tag(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [])

    target = HashingEmbedder(dimensions=_NEW)
    outcome = await Reembedder(store=store, embedder=target).run()

    assert outcome.swapped
    assert outcome.embedded == 0
    assert _meta(store) == {"embedding_model": target.model_id, "dimensions": str(_NEW)}


async def test_a_store_with_unreadable_metadata_is_reported_not_a_traceback(
    tmp_path: Path,
) -> None:
    """Every ``meta`` value is text somebody could have edited (review round 1)."""
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("UPDATE meta SET value = 'unknown' WHERE key = 'dimensions'")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MemoryStoreError, match="not a number"):
        Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).plan()


async def test_a_work_store_with_an_unreadable_cursor_is_discarded(tmp_path: Path) -> None:
    store = tmp_path / "memory.db"
    await _seed(store, [_record(str(index), f"memory {index}") for index in range(4)])

    broken = _CountingEmbedder(fail_after=2)
    with pytest.raises(MemoryStoreError, match="embedder failed"):
        await Reembedder(store=store, embedder=broken, batch_size=2).run()

    work = tmp_path / f"memory.db{WORK_SUFFIX}"
    conn = sqlite3.connect(str(work))
    try:
        conn.execute("UPDATE meta SET value = 'halfway' WHERE key = 'reembed_cursor'")
        conn.commit()
    finally:
        conn.close()

    # Unusable is unusable: the work store is discarded, exactly as it is when its
    # target or its source fingerprint does not match.
    outcome = await Reembedder(store=store, embedder=_CountingEmbedder(), batch_size=2).run()

    assert outcome.resumed == 0
    assert outcome.embedded == 4


async def test_a_source_written_after_verification_is_not_swapped_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap between the re-read and the rename, narrowed (review round 1, finding 2).

    The instance lock stops the hub but is advisory (ADR-0083 §10), so it does not
    stop a ``sqlite3`` shell left open on the same machine. A write landing in this
    window would otherwise be thrown away by the rename with nothing reporting it.
    """
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    verify = reembed_module._verify

    def _verify_then_write(
        source: sqlite3.Connection,
        work: sqlite3.Connection,
        plan: ReembedPlan,
        embedder: Embedder,
    ) -> None:
        verify(source, work, plan, embedder)
        late = _record("late", "written behind the lock's back")
        interloper = sqlite3.connect(str(store))
        try:
            interloper.execute(
                "INSERT INTO records(id, kind, data) VALUES (?, ?, ?)",
                (late.id, late.kind, late.model_dump_json()),
            )
            interloper.commit()
        finally:
            interloper.close()

    monkeypatch.setattr(reembed_module, "_verify", _verify_then_write)

    with pytest.raises(MemoryStoreError, match="changed while the re-embedded store"):
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    # The write survived, and the live store was not replaced by a copy missing it.
    assert _meta(store)["dimensions"] == str(_OLD)
    assert len(_read(store, "SELECT rowid FROM records")) == 2


async def test_a_same_sized_write_after_verification_is_still_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stat fields alone would miss this (review round 2, finding 2).

    A same-sized update inside one timestamp tick leaves inode, size and
    ``st_mtime_ns`` where they were. SQLite's file change counter moves anyway,
    which is why the fingerprint reads it.
    """
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    verify = reembed_module._verify

    def _verify_then_overwrite(
        source: sqlite3.Connection,
        work: sqlite3.Connection,
        plan: ReembedPlan,
        embedder: Embedder,
    ) -> None:
        verify(source, work, plan, embedder)
        before = store.stat()
        interloper = sqlite3.connect(str(store))
        try:
            # Same id, same-length content: the row is rewritten in place.
            interloper.execute(
                "UPDATE records SET data = ? WHERE id = 'a'",
                (_record("a", "ESPRESSO").model_dump_json(),),
            )
            interloper.commit()
        finally:
            interloper.close()
        # The premise of the case: the stat fields did not move.
        after = store.stat()
        assert (after.st_ino, after.st_size) == (before.st_ino, before.st_size)

    monkeypatch.setattr(reembed_module, "_verify", _verify_then_overwrite)

    with pytest.raises(MemoryStoreError, match="changed while the re-embedded store"):
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert _meta(store)["dimensions"] == str(_OLD)


async def test_a_record_at_rowid_zero_or_below_is_migrated(tmp_path: Path) -> None:
    """``rowid`` is an explicit primary key here, so it need not be positive.

    Reviewed as minor (round 2, finding 3) and fixed rather than filed because the
    fix removes a sentinel instead of adding one: SQLite has no integer below its
    own minimum ``rowid``, so ``0`` as "nothing copied yet" silently skipped every
    row at or below it and surfaced as a count mismatch nobody could act on.
    """
    store = tmp_path / "memory.db"
    await _seed(store, [_record("positive", "espresso")])
    conn = sqlite3.connect(str(store))
    try:
        for rowid, record_id in ((0, "zero"), (-5, "negative")):
            record = _record(record_id, f"memory at rowid {rowid}")
            conn.execute(
                "INSERT INTO records(rowid, id, kind, data) VALUES (?, ?, ?, ?)",
                (rowid, record.id, record.kind, record.model_dump_json()),
            )
        conn.commit()
    finally:
        conn.close()

    outcome = await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert outcome.swapped
    assert outcome.embedded == 3
    assert _read(store, "SELECT rowid FROM records ORDER BY rowid") == [(-5,), (0,), (1,)]


async def test_an_unflushable_rename_is_a_warning_not_a_failed_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory ``fsync`` is refused on some filesystems (review round 2, finding 1)."""
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])

    real = os.fsync

    def _refuse_directories(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "fsync not supported on this filesystem")
        real(fd)

    monkeypatch.setattr(os, "fsync", _refuse_directories)

    outcome = await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    # The swap *happened*. Only its durability is unconfirmed, and the two are
    # different facts.
    assert outcome.swapped
    assert not outcome.durable
    assert _meta(store)["dimensions"] == str(_NEW)


async def test_a_symlinked_backup_path_is_refused_and_the_original_survives(
    tmp_path: Path,
) -> None:
    """A symlink is a name for the path, not for the inode (review round 3, blocker).

    ``Path.stat`` follows it and reports the live store's inode, so it looked like
    a previous attempt's own hard link. After the rename it would resolve to the
    *new* store, leaving the old inode with no name at all — the migration would
    delete the thing it reports having kept, and say so in the same breath.
    """
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    backup = tmp_path / f"memory.db{BACKUP_SUFFIX}"
    backup.symlink_to(store)

    with pytest.raises(IncompatibleStateError, match="has nowhere to go") as caught:
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert "hard link" in caught.value.expected
    # Nothing was swapped, so the original is still the live store rather than a
    # dangling name for one that was unlinked.
    assert _meta(store)["dimensions"] == str(_OLD)
    assert backup.is_symlink()


async def test_a_backup_path_on_another_inode_is_refused_even_at_the_same_number(
    tmp_path: Path,
) -> None:
    """The check reads the device too: an inode number is unique per filesystem."""
    store = tmp_path / "memory.db"
    await _seed(store, [_record("a", "espresso")])
    backup = tmp_path / f"memory.db{BACKUP_SUFFIX}"
    backup.write_text("a different file that happens to be here")

    with pytest.raises(IncompatibleStateError, match="has nowhere to go"):
        await Reembedder(store=store, embedder=HashingEmbedder(dimensions=_NEW)).run()

    assert backup.read_text() == "a different file that happens to be here"
