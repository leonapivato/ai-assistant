"""ADR-0326 §4:2's test, for the memory store's home columns: a file the previous release wrote.

``tests/memory/legacy/memory-before-home-columns.db`` was written by the previous
release's own ``SqliteMemoryStore`` (the build at ``d1f9fa1d0``, at the label ``28``),
never by hand-built SQL, with an eight-dimension hashing embedder and invented data: that
build opened a copy of ``memory-before-adr-0383.db``, upgrading it in place to 28, and
then stored, through its public ``add``, one more episode, ``mem-shared``, in the hub's
shared things. Beside it are the earlier file's episodes and memory, each the owner's.

That build keeps a record's home inside the record alone. This one keeps it in two
columns too, ``home_kind`` and ``home_id``, which a bound store's statements compare
(ADR-0383 §7:3; #3732), so the label moves (ADR-0326 §2:3, §5:3). The head opens a copy
and upgrades it in place: never refuse it (§5:1), drop nothing and move no other byte of
any row (§4:4), and fill each row's columns from its record as the store's decoder reads
it. A row whose home cannot be read gets none, which withholds it from every sight
(ADR-0383 §5:3), and the upgrade does not fail on it. The previous release, which serves
12 to 28, refuses the upgraded file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import OWNER_PERSON_ID, MemoryRecord, RecordHome, SightMode
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    HOME_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    inspect_existing,
)
from ai_assistant.memory._sight import made_by
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink
from sight_equivalence import SIGHTS

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "memory-before-home-columns.db"
_BEFORE_THE_HOME: Final = _LEGACY / "memory-before-adr-0383.db"

#: The instant the head opens the file at.
_NOW: Final = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

_SHARED: Final = "mem-shared"

#: Every row the file holds.
_IDS: Final = frozenset(
    {
        "mem-chat",
        "mem-line",
        "mem-event",
        "mem-task",
        "mem-approval",
        "mem-open",
        "mem-bare",
        "mem-said",
        "mem-unlinked",
        "mem-lowered",
        "mem-no-one",
        _SHARED,
    }
)

_OWNERS: Final = ("person", OWNER_PERSON_ID)
_NONE: Final = (None, None)

#: Rows no write leaves, planted by hand over a copy: a payload that is not JSON, one
#: that is not UTF-8, and a record with its home removed. None has a home to read.
_UNREADABLE: Final = {
    "mem-bare": "'{not json'",
    "mem-said": "CAST(x'ff' AS TEXT)",
    "mem-task": "json_remove(data, '$.home')",
}


def _columns(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [str(row[1]) for row in conn.execute("PRAGMA table_info(records)")]


def _rows(path: Path) -> dict[str, tuple[object, ...]]:
    """Every row's columns as the previous release kept them, read out of band."""
    with sqlite3.connect(path) as conn:
        conn.text_factory = bytes
        return {
            row[0].decode(): tuple(row[1:])
            for row in conn.execute(
                "SELECT id, rowid, kind, data, expires_at, valid_until, valid_from, "
                "about_person, revision, occurred_at, channel_type, channel_instance, "
                "is_open, band FROM records"
            )
        }


def _data(row: tuple[object, ...]) -> str:
    """The record a row of :func:`_rows` stores, as text."""
    data = row[2]
    assert isinstance(data, bytes)
    return data.decode()


def _homes(path: Path) -> dict[str, tuple[object, object]]:
    """Every row's home columns, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (home_kind, home_id)
            for record_id, home_kind, home_id in conn.execute(
                "SELECT id, home_kind, home_id FROM records"
            )
        }


def _vectors(path: Path) -> dict[int, bytes]:
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


def _open(path: Path, mode: SightMode = SightMode.WITHHOLD) -> SqliteMemoryStore:
    return SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: _NOW,
        sight_mode=mode,
    )


async def _exported(path: Path) -> dict[str, MemoryRecord]:
    store = _open(path)
    try:
        return {record.id: record for record in await store.export()}
    finally:
        store.close()


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at 28, keeps no home column, and holds a record in each home."""
    assert _label(_FIXTURE) == HOME_RECORD_FORMAT
    assert "home_kind" not in _columns(_FIXTURE)
    rows = _rows(_FIXTURE)
    assert set(rows) == _IDS
    homes = {key: json.loads(_data(row))["home"] for key, row in rows.items()}
    assert homes.pop(_SHARED) == {"kind": "shared", "id": None}
    assert {json.dumps(home) for home in homes.values()} == {
        json.dumps({"kind": "person", "id": OWNER_PERSON_ID})
    }


async def test_each_rows_columns_take_its_records_home(legacy: Path) -> None:
    """The upgrade fills the columns from each decoded record, the shared one included,
    and moves the label."""
    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    assert _homes(legacy) == {
        key: (("shared", None) if key == _SHARED else _OWNERS) for key in _IDS
    }
    assert exported[_SHARED].home == RecordHome.shared()


async def test_the_upgrade_moves_nothing_else(legacy: Path) -> None:
    """ADR-0326 §4:4: every row is kept byte for byte, with its vector; only the two
    columns are added."""
    before = _rows(legacy)
    vectors = _vectors(legacy)

    await _exported(legacy)

    assert _rows(legacy) == before
    assert _vectors(legacy) == vectors
    assert _columns(legacy)[-2:] == ["home_kind", "home_id"]


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record decodes from the row as it was stored, through each
    read that gives one back."""
    before = _rows(legacy)
    store = _open(legacy, SightMode.COUNT)
    try:
        exported = {record.id: record for record in await store.export()}
        fetched = await store.get_many(sorted(_IDS))
    finally:
        store.close()

    for record_id, row in before.items():
        stored = SqliteMemoryStore._decode(_data(row))
        assert exported[record_id] == stored.model_copy(update={"revision": row[7]})
        assert fetched[record_id] == exported[record_id]


@pytest.mark.parametrize("sight_name", list(SIGHTS))
async def test_each_sight_sees_what_the_upgraded_columns_name(
    legacy: Path, sight_name: str
) -> None:
    """ADR-0383 §7:3 over an upgraded file: a withholding store gives back exactly the
    records whose decoded home the sight sees."""
    exported = await _exported(legacy)
    sight = SIGHTS[sight_name]
    store = _open(legacy)
    try:
        given = await store.bound(sight).export()
    finally:
        store.close()

    assert {record.id for record in given} == {
        record.id
        for record in exported.values()
        if sight.sees(record.home, made_by=made_by(record))
    }


async def test_a_row_whose_home_cannot_be_read_gets_none_and_the_upgrade_does_not_fail(
    legacy: Path,
) -> None:
    """ADR-0383 §5:3: a row the decoder cannot read, or whose home it cannot read, is
    kept with no home in its columns, and withheld from every sight; every other row is
    filled as before."""
    with sqlite3.connect(legacy) as conn:
        for record_id, payload in _UNREADABLE.items():
            conn.execute(
                f"UPDATE records SET data = {payload} WHERE id = ?",  # noqa: S608 — module literals
                (record_id,),
            )
    before = _rows(legacy)

    store = _open(legacy)
    try:
        assert _label(legacy) == MEMORY_RECORD_FORMAT
        assert _rows(legacy) == before
        homes = _homes(legacy)
        assert {key: homes[key] for key in _UNREADABLE} == dict.fromkeys(_UNREADABLE, _NONE)
        assert all(homes[key] != _NONE for key in _IDS - set(_UNREADABLE))
        for sight in SIGHTS.values():
            bound = store.bound(sight)
            given = {record.id for record in await bound.export()}
            assert not given & set(_UNREADABLE)
            for record_id in _UNREADABLE:
                assert await bound.get(record_id) is None
    finally:
        store.close()


async def test_a_file_from_before_the_home_is_carried_to_the_columns(tmp_path: Path) -> None:
    """Upgrades chain (ADR-0326 §4:5): a file at 27 takes the owner's domain into every
    record and then into every row's columns, in one open."""
    path = tmp_path / "memory.db"
    shutil.copyfile(_BEFORE_THE_HOME, path)

    exported = await _exported(path)

    assert _label(path) == MEMORY_RECORD_FORMAT
    assert set(_homes(path).values()) == {_OWNERS}
    assert {record.home for record in exported.values()} == {RecordHome.owners()}


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    await _exported(legacy)
    once = (_label(legacy), _rows(legacy), _homes(legacy))

    await _exported(legacy)

    assert (_label(legacy), _rows(legacy), _homes(legacy)) == once


def test_a_fresh_store_is_written_at_the_new_label_with_the_columns(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade."""
    path = tmp_path / "memory.db"
    _open(path).close()
    assert _label(path) == MEMORY_RECORD_FORMAT
    assert _columns(path)[-2:] == ["home_kind", "home_id"]


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 28, so it refuses the file at 29."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})
