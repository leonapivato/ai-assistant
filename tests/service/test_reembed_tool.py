"""Tests for the offline re-embedding tool's entry point (ADR-0104 §4, §5).

The mechanism has its own suite under ``tests/memory/test_reembed.py``. What is
on test here is everything the entry point owns: the instance lock, the exit
codes, the disclosure, and the fact that this module drives the migration without
naming a single ``memory`` type.

Named ``_tool`` rather than mirroring ``service/reembed.py`` exactly, because
``tests/`` carries no ``__init__.py`` and two test modules with one basename
collide at collection.
"""

from __future__ import annotations

import asyncio
import errno
import os
import sqlite3
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.service import datadir, reembed
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The width the store is seeded at, so it differs from ``HashingEmbedder``'s
#: default — which is what ``ASSISTANT_EMBEDDER=hashing`` wires, and therefore
#: what the tool migrates *to*.
_SEEDED = 8


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The tool's configuration, injected the way ``test_hub`` injects the hub's."""
    loaded = Settings(data_dir=data_dir, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(reembed, "load_settings", lambda: loaded)
    return loaded


async def _seed(data_dir: Path, count: int = 2) -> None:
    """Write a store tagged with an embedder the configured one does not match."""
    store = SqliteMemoryStore(
        path=data_dir / "memory.db", embedder=HashingEmbedder(dimensions=_SEEDED)
    )
    try:
        for index in range(count):
            await store.add(
                SemanticMemory(
                    id=str(index),
                    content=f"memory {index}",
                    fact=f"memory {index}",
                    provenance=Provenance(
                        source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN
                    ),
                )
            )
    finally:
        store.close()


def _tag(store: Path) -> str:
    conn = sqlite3.connect(str(store))
    try:
        (value,) = conn.execute("SELECT value FROM meta WHERE key = 'embedding_model'").fetchone()
    finally:
        conn.close()
    return str(value)


def test_it_migrates_the_store_and_reports_what_it_did(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_seed(data_dir))

    code = reembed.main([])

    assert code == EXIT_OK
    assert _tag(data_dir / "memory.db") == HashingEmbedder().model_id
    out = capsys.readouterr().out
    # ADR-0104 §4's disclosure: which model, and how many records.
    assert f"hashing-{_SEEDED}" in out
    assert "records: 2" in out
    assert "2 records re-embedded" in out
    assert str(data_dir / "memory.db.pre-reembed") in out


def test_a_dry_run_changes_nothing(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_seed(data_dir))

    code = reembed.main(["--dry-run"])

    assert code == EXIT_OK
    assert _tag(data_dir / "memory.db") == f"hashing-{_SEEDED}"
    assert not (data_dir / "memory.db.pre-reembed").exists()
    assert "nothing was changed" in capsys.readouterr().out


def test_a_store_already_on_the_configured_embedder_is_reported_as_done(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = SqliteMemoryStore(path=data_dir / "memory.db", embedder=HashingEmbedder())
    store.close()

    code = reembed.main([])

    assert code == EXIT_OK
    assert "Nothing to do" in capsys.readouterr().out


def test_a_deployment_with_no_store_yet_is_not_a_failure(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = reembed.main([])

    assert code == EXIT_OK
    assert "Nothing to migrate" in capsys.readouterr().out


def test_a_held_instance_lock_is_refused_immediately(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_seed(data_dir))
    holder = InstanceLock(data_dir / LOCK_FILENAME)
    assert holder.acquire()
    try:
        code = reembed.main([])
    finally:
        holder.release()

    # Restartable, not a deployment fault: the operator stops the hub and runs it
    # again. Nothing was touched.
    assert code == EXIT_RESTART
    assert _tag(data_dir / "memory.db") == f"hashing-{_SEEDED}"
    err = capsys.readouterr().err
    assert str(data_dir / LOCK_FILENAME) in err
    assert "Stop the hub" in err


def test_the_lock_is_released_again_when_the_run_finishes(
    settings: Settings, data_dir: Path
) -> None:
    asyncio.run(_seed(data_dir))

    assert reembed.main([]) == EXIT_OK

    after = InstanceLock(data_dir / LOCK_FILENAME)
    assert after.acquire()
    after.release()


def test_a_store_this_build_cannot_replace_stays_down(
    settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An ``IncompatibleStateError`` earns 78: restarting unchanged never succeeds."""
    asyncio.run(_seed(data_dir))
    (data_dir / "memory.db-wal").write_bytes(b"a sidecar the swap must not rename over")

    code = reembed.main([])

    assert code == EXIT_DEPLOYMENT
    err = capsys.readouterr().err
    assert "what to do:" in err


def test_a_settings_failure_is_reported_and_stays_down(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> Settings:
        msg = "ASSISTANT_DATA_DIR must be absolute"
        raise ConfigurationError(msg)

    monkeypatch.setattr(reembed, "load_settings", _boom)

    assert reembed.main([]) == EXIT_DEPLOYMENT
    assert "must be absolute" in capsys.readouterr().err


def test_an_interruption_says_the_work_is_kept(
    settings: Settings,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(_seed(data_dir))

    def _interrupt(_: object) -> None:
        raise KeyboardInterrupt

    # Raised from *inside* the run, which is where a Ctrl-C actually lands.
    monkeypatch.setattr(datadir, "prepare", _interrupt)

    assert reembed.main([]) == EXIT_RESTART
    assert "run this again" in capsys.readouterr().err


class TestProgress:
    """The throttle exists so a large store does not scroll thousands of lines."""

    def test_it_prints_once_per_whole_percent(self, capsys: pytest.CaptureFixture[str]) -> None:
        progress = reembed._Progress()
        for done in range(1, 201):
            progress.report(done, 200)

        # 200 chunks, 101 distinct whole percentages (0 through 100).
        assert len(capsys.readouterr().out.splitlines()) == 101

    def test_the_last_chunk_always_prints(self, capsys: pytest.CaptureFixture[str]) -> None:
        progress = reembed._Progress()
        progress.report(199, 200)
        progress.report(200, 200)

        assert capsys.readouterr().out.splitlines()[-1] == "  200/200 records (100%)"

    def test_an_empty_store_is_a_hundred_percent(self, capsys: pytest.CaptureFixture[str]) -> None:
        reembed._Progress().report(0, 0)

        assert capsys.readouterr().out.strip() == "0/0 records (100%)"


def test_an_unflushable_rename_is_reported_as_a_warning_and_still_succeeds(
    settings: Settings,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(_seed(data_dir))

    real = os.fsync

    def _refuse_directories(fd: int) -> None:
        # Only the swap's directory fsync: the instance lock fsyncs its own file
        # on the way in, and failing that would be a different test.
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "fsync not supported on this filesystem")
        real(fd)

    monkeypatch.setattr(os, "fsync", _refuse_directories)

    code = reembed.main([])

    # The migration happened, so the exit code says so; the durability caveat goes
    # to stderr rather than turning a completed swap into a reported failure.
    assert code == EXIT_OK
    assert _tag(data_dir / "memory.db") == HashingEmbedder().model_id
    captured = capsys.readouterr()
    assert "records re-embedded" in captured.out
    assert "could not be flushed to disk" in captured.err
