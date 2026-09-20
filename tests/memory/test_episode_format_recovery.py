"""Rejected M36 stores retain their crash-recovery files byte for byte."""

from __future__ import annotations

import contextlib
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.testing import FakeEmbedder, FakeTraceSink

pytestmark = pytest.mark.integration


def _open(path: Path, kind: str) -> SqliteMemoryStore | SqliteConversationStore:
    if kind == "conversation":
        return SqliteConversationStore(path=path)
    return SqliteMemoryStore(path=path, embedder=FakeEmbedder(), traces_sink=FakeTraceSink())


def _seed(path: Path) -> None:
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("CREATE TABLE crash_probe(value BLOB)")
        conn.execute("BEGIN")
        conn.executemany("INSERT INTO crash_probe VALUES (zeroblob(4096))", [()] * 100)
        conn.execute("COMMIT")


def _crash(path: Path) -> None:
    child = Path(__file__).with_name("_format_crash_child.py")
    result = subprocess.run(  # noqa: S603 — fixed Python fixture and pytest-owned path
        [sys.executable, str(child), str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 42, result.stderr
    journal = Path(f"{path}-journal")
    assert journal.read_bytes()[:8] == bytes.fromhex("d9d505f920a163d7")


def _snapshot(path: Path) -> dict[str, tuple[bytes, int]]:
    files = (path, *(Path(f"{path}{suffix}") for suffix in ("-journal", "-wal", "-shm")))
    return {
        file.name: (file.read_bytes(), stat.S_IMODE(file.stat().st_mode))
        for file in files
        if file.exists()
    }


@pytest.mark.parametrize("kind", ["conversation", "memory"])
@pytest.mark.parametrize("format_version", [None, 99])
def test_incompatible_hot_journal_is_rejected_without_recovery(
    tmp_path: Path, kind: str, format_version: int | None
) -> None:
    path = tmp_path / "old.db"
    _seed(path)
    if format_version is not None:
        with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.execute("CREATE TABLE episode_record_format(version INTEGER NOT NULL)")
            conn.execute("INSERT INTO episode_record_format VALUES (?)", (format_version,))
    _crash(path)
    path.chmod(0o644)
    before = _snapshot(path)
    with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
        _open(path, kind)
    assert _snapshot(path) == before
    # Negative control: this is a hot journal, not inert sidecar bytes. A normal
    # writable read recovers it and changes the original that rejection preserved.
    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT DISTINCT length(value) FROM crash_probe").fetchall() == [
            (4096,)
        ]
    assert _snapshot(path) != before
    assert not Path(f"{path}-journal").exists()


def test_hot_conversation_schema_without_eligibility_is_not_recovered(tmp_path: Path) -> None:
    path = tmp_path / "old-index.db"
    _seed(path)
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("CREATE TABLE episode_record_format(version INTEGER NOT NULL)")
        conn.execute("INSERT INTO episode_record_format VALUES (1)")
        conn.execute("CREATE TABLE turns(episode_id TEXT)")
    _crash(path)
    before = _snapshot(path)
    with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
        _open(path, "conversation")
    assert _snapshot(path) == before


@pytest.mark.parametrize("kind", ["conversation", "memory"])
def test_current_format_hot_journal_recovers_normally_after_probe(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "current.db"
    _open(path, kind).close()
    _seed(path)
    _crash(path)
    _open(path, kind).close()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT DISTINCT length(value) FROM crash_probe").fetchall() == [
            (4096,)
        ]
    assert not Path(f"{path}-journal").exists()


@pytest.mark.parametrize("kind", ["conversation", "memory"])
def test_rejected_wal_database_and_shared_memory_are_unchanged(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "wal.db"
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE old_records(content TEXT)")
        conn.execute("INSERT INTO old_records VALUES ('committed in WAL')")
        before = _snapshot(path)
        with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
            _open(path, kind)
        assert _snapshot(path) == before


@pytest.mark.parametrize("kind", ["conversation", "memory"])
@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_rejection_does_not_remove_a_sidecar_symlink(
    tmp_path: Path, kind: str, suffix: str
) -> None:
    path = tmp_path / "old.db"
    _seed(path)
    other = tmp_path / "unrelated"
    other.write_bytes(b"unrelated content")
    sidecar = Path(f"{path}{suffix}")
    sidecar.symlink_to(other)
    before = _snapshot(path)
    with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
        _open(path, kind)
    assert _snapshot(path) == before
    assert sidecar.is_symlink()
    assert other.read_bytes() == b"unrelated content"


@pytest.mark.parametrize("kind", ["conversation", "memory"])
def test_rejected_closed_wal_database_creates_no_sidecars(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "closed-wal.db"
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE old_records(content TEXT)")
        conn.execute("INSERT INTO old_records VALUES ('checkpointed before close')")
    before = _snapshot(path)
    assert set(before) == {path.name}
    with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
        _open(path, kind)
    assert _snapshot(path) == before


@pytest.mark.parametrize("kind", ["conversation", "memory"])
@pytest.mark.parametrize("current", [False, True])
def test_hot_database_symlink_uses_the_target_recovery_files(
    tmp_path: Path, kind: str, current: bool
) -> None:
    path = tmp_path / "actual.db"
    if current:
        _open(path, kind).close()
    _seed(path)
    _crash(path)
    alias = tmp_path / "alias.db"
    alias.symlink_to(path)
    before = _snapshot(path)
    if current:
        _open(alias, kind).close()
        with contextlib.closing(sqlite3.connect(path)) as conn:
            assert conn.execute("SELECT DISTINCT length(value) FROM crash_probe").fetchall() == [
                (4096,)
            ]
        assert not Path(f"{path}-journal").exists()
    else:
        with pytest.raises(IncompatibleStateError, match="fresh M36 data directory"):
            _open(alias, kind)
        assert _snapshot(path) == before
    assert alias.is_symlink()
