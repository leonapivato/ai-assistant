"""ADR-0326 §4:2's test, for ADR-0383 §5:1's home: a memory file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0383.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``23f569c53``, at the label ``27``), never by
hand-built SQL, with an eight-dimension hashing embedder and invented data: that build
opened a copy of ``memory-before-adr-0378.db``, upgrading it in place to 27, and then
stored, through its public ``add``, one more episode, ``mem-no-one``, whose facts say its
work was for no one. Beside it are the earlier file's episodes, each for the owner, one
an unidentified sender's, an **open** episode, a bare episode with no processing record,
and a memory.

No record that build wrote holds a home, which every episode and memory this build
writes does: a build at 27 would fail on the read, which is why the label moves
(ADR-0326 §2:3, §5:3). The head opens a copy and upgrades it in place: never refuse it
(§5:1), drop nothing (§4:4), and write the owner's domain into every record it holds,
the episode for no one included (ADR-0383 §5:1), moving no other byte of any row. The
previous release, which serves 12 to 27, refuses the upgraded file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from memory_home_carry import OWNERS_HOME, homed_row

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    EpisodicMemory,
    Memory,
    MemoryRecord,
    RecordHome,
    RecordHomeKind,
    WorkForKind,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    CAME_THROUGH_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0383.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

#: The episode whose facts say its work was for no one, and the unidentified sender's.
_NO_ONE: Final = "mem-no-one"
_UNLINKED: Final = "mem-unlinked"
_OPEN: Final = "mem-open"
_MEMORY: Final = "mem-said"

#: Every row the file holds.
_IDS: Final = frozenset(
    {
        "mem-chat",
        "mem-line",
        "mem-event",
        "mem-task",
        "mem-approval",
        _OPEN,
        "mem-bare",
        _MEMORY,
        _UNLINKED,
        "mem-lowered",
        _NO_ONE,
    }
)


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int, str | None, int]]:
    """Every row's kind, stored blob, revision, band and openness, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision), band, int(is_open))
            for record_id, kind, data, revision, band, is_open in conn.execute(
                "SELECT id, kind, data, revision, band, is_open FROM records"
            )
        }


def _vectors(path: Path) -> dict[int, bytes]:
    """Every stored vector, by its row, read out of band."""
    with sqlite3.connect(path) as conn:
        conn.enable_load_extension(True)
        import sqlite_vec  # noqa: PLC0415 — the extension is this test's alone

        sqlite_vec.load(conn)
        return {
            int(rowid): bytes(embedding)
            for rowid, embedding in conn.execute("SELECT rowid, embedding FROM vec_records")
        }


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "memory.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: _NOW,
    )


async def _exported(path: Path) -> dict[str, MemoryRecord]:
    store = _open(path)
    try:
        return {record.id: record for record in await store.export()}
    finally:
        store.close()


def _holds(read: object, written: object) -> None:
    """``read`` holds everything ``written`` held, unchanged, and may add fields to it."""
    if isinstance(written, dict):
        assert isinstance(read, dict)
        for key, value in written.items():
            assert key in read, key
            _holds(read[key], value)
    elif isinstance(written, list):
        assert isinstance(read, list)
        assert len(read) == len(written)
        for one, other in zip(read, written, strict=True):
            _holds(one, other)
    else:
        assert read == written


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, holds an episode for no one, and no home."""
    assert _label(_FIXTURE) == CAME_THROUGH_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    assert not any("home" in json.loads(row[1]) for row in rows.values())
    no_one = json.loads(rows[_NO_ONE][1])["processing_record"]["facts"]
    assert no_one["for_whom"]["kind"] == WorkForKind.NO_ONE.value
    unlinked = json.loads(rows[_UNLINKED][1])["processing_record"]["facts"]
    assert unlinked["authority"]["unidentified"] is True
    assert rows[_OPEN][4] == 1
    assert rows[_MEMORY][0] == "memory"


async def test_every_record_takes_the_owners_domain(legacy: Path) -> None:
    """ADR-0383 §5:1: every record is the owner's, the episode for no one included."""
    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    assert {record.home for record in exported.values()} == {RecordHome.owners()}
    no_one = exported[_NO_ONE]
    assert isinstance(no_one, EpisodicMemory)
    assert no_one.processing_record is not None
    assert no_one.processing_record.facts is not None
    # Its facts are left as they were: whom its work was for is not its home.
    assert no_one.processing_record.facts.for_whom.kind is WorkForKind.NO_ONE
    assert isinstance(exported[_MEMORY], Memory)
    assert exported[_MEMORY].home.kind is RecordHomeKind.PERSON


async def test_the_upgrade_writes_the_home_and_moves_nothing_else(legacy: Path) -> None:
    """ADR-0326 §4:4: every row is kept, byte for byte save the home set last, with its
    kind, revision, band, openness and vector."""
    before = _raw_rows(legacy)
    vectors = _vectors(legacy)

    await _exported(legacy)

    assert _raw_rows(legacy) == {key: homed_row(row) for key, row in before.items()}
    assert _vectors(legacy) == vectors


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: each record holds everything the stored row held, plus its home,
    through every read that gives one back."""
    before = _raw_rows(legacy)
    store = _open(legacy)
    try:
        exported = {record.id: record for record in await store.export()}
        fetched = await store.get_many(sorted(_IDS))
    finally:
        store.close()

    for record_id, row in before.items():
        stored = json.loads(row[1])
        read = exported[record_id].model_dump(mode="json", exclude={"revision"})
        assert read.pop("home") == OWNERS_HOME
        _holds(read, stored)
        assert exported[record_id].revision == row[2]
    for record_id, record in fetched.items():
        assert record == exported[record_id]


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    await _exported(legacy)
    once = (_label(legacy), _raw_rows(legacy))

    await _exported(legacy)

    assert (_label(legacy), _raw_rows(legacy)) == once


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade."""
    path = tmp_path / "memory.db"
    _open(path).close()
    assert _label(path) == MEMORY_RECORD_FORMAT


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 27, so it refuses the file at 28."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})


async def test_a_record_written_after_the_upgrade_keeps_its_own_home(legacy: Path) -> None:
    """A write after the upgrade carries the home it was given, the shared things
    included, and the upgrade never runs over it again."""
    store = _open(legacy)
    try:
        bare = await store.get("mem-bare")
        assert isinstance(bare, EpisodicMemory)
        await store.add(bare.model_copy(update={"id": "mem-shared", "home": RecordHome.shared()}))
    finally:
        store.close()

    exported = await _exported(legacy)

    assert exported["mem-shared"].home == RecordHome.shared()
    assert exported["mem-bare"].home == RecordHome.owners()
