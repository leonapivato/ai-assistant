"""ADR-0326 §4:2's test, for ADR-0383 §5:1's home: a notification file the previous release wrote.

``tests/memory/legacy/notifications-before-adr-0383.db`` was written by the previous
release's own ``SqliteNotificationStore`` (the build at ``3741e3773``, which wrote no
label), through its public API and never by hand-built SQL, with invented data and the
canonical policy fake: standing preferences reaching ``calendar`` by interruption; a
dentist's appointment ruled ``INTERRUPT``, spending a unit of budget; a parcel and a bill
ruled ``HOLD``, the bill then dismissed; and the dentist offered again, a duplicate
``DROP`` that wrote nothing. Beside it, ``notifications-before-adr-0383.json`` is what
that build read back from the file, written by that code too.

No record that build wrote holds a home, which every record this build writes does
(ADR-0386 §3:1), and the file carries no label, so the store gains its first (ADR-0383
§13). The head opens a copy and upgrades it in place: never refuse it (ADR-0326 §5:1),
drop nothing (§4:4), read back every record as that release did, write the owner's domain
into every record (ADR-0383 §5:1), and move no other byte: not the preferences, and not
the spend ledger, which outlives the records (ADR-0130 §5).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.errors import NotificationStoreError
from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    RecordHome,
)
from ai_assistant.memory.notification_store import (
    NOTIFICATION_SCHEMA_VERSION,
    SqliteNotificationStore,
)
from ai_assistant.testing import FakeNotificationPolicy, FakeTraceSink

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "notifications-before-adr-0383.db"
_READ_BACK: Final = _LEGACY / "notifications-before-adr-0383.json"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

_RECORDS: Final = ("note-1", "note-2", "note-3")

#: The columns the upgrade adds to the records' rows, and no other table's.
_HOME_COLUMNS: Final = ("home_kind", "home_id")
_OWNERS: Final = (RecordHome.owners().kind.value, RecordHome.owners().id)


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _tables(path: Path) -> dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]]:
    """Every table's columns and rows, in rowid order, read out of band."""
    with sqlite3.connect(path) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        held: dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]] = {}
        for name in names:
            cursor = conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')  # noqa: S608 — names read from the file's own catalogue
            columns = tuple(one[0] for one in cursor.description)
            held[name] = (columns, cursor.fetchall())
    return held


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "notifications.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path) -> SqliteNotificationStore:
    return SqliteNotificationStore(
        path=path, traces_sink=FakeTraceSink(), now=lambda: _NOW, new_id=lambda: "head-1"
    )


def _previous() -> dict[str, Any]:
    loaded = json.loads(_READ_BACK.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _homeless(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each record with its home taken out, each held to be the owner's."""
    for record in records:
        assert record["home"] == RecordHome.owners().model_dump(mode="json"), record
    return [{key: one for key, one in record.items() if key != "home"} for record in records]


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file carries no label, its records no home, and its ledger a spent unit."""
    assert _label(_FIXTURE) == 0
    tables = _tables(_FIXTURE)
    columns, rows = tables["notifications"]
    assert not set(_HOME_COLUMNS) & set(columns)
    assert sorted(row[0] for row in rows) == list(_RECORDS)
    assert len(tables["notification_interruptions"][1]) == 1
    assert len(tables["notification_preferences"][1]) == 1


async def test_every_record_reads_back_as_the_previous_release_read_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4, ADR-0383 §5:1: nothing dropped, every record the owner's."""
    store = _open(legacy)
    try:
        exported = [one.model_dump(mode="json") for one in await store.export()]
        held = [one.model_dump(mode="json") for one in await store.held(limit=50)]
        preferences = (await store.preferences()).model_dump(mode="json")
    finally:
        store.close()

    previous = _previous()
    assert _label(legacy) == NOTIFICATION_SCHEMA_VERSION == 1
    assert _homeless(exported) == previous["export"]
    assert _homeless(held) == previous["held"]
    assert preferences == previous["preferences"]


async def test_the_upgrade_writes_the_home_and_moves_nothing_else(legacy: Path) -> None:
    """ADR-0326 §4:4: only the records' rows change, each gaining the owner's domain."""
    before = _tables(legacy)
    _open(legacy).close()
    after = _tables(legacy)

    assert set(after) == set(before)
    for name, (columns, rows) in before.items():
        if name == "notifications":
            continue
        assert after[name] == (columns, rows), name
    columns, rows = before["notifications"]
    assert after["notifications"] == (
        (*columns, *_HOME_COLUMNS),
        [(*row, *_OWNERS) for row in rows],
    )


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """ADR-0326 §4:3: the upgrade ran once, and the labelled file is opened as it stands."""
    _open(legacy).close()
    once = _tables(legacy)
    _open(legacy).close()

    assert _tables(legacy) == once
    assert _label(legacy) == NOTIFICATION_SCHEMA_VERSION


async def test_an_upgraded_record_still_speaks_for_its_key(legacy: Path) -> None:
    """ADR-0215 §2: the dentist's record suppresses its key across the upgrade."""
    store = _open(legacy)
    try:
        again = NotificationCandidate(
            candidate_key="dentist",
            producer="upcoming",
            notification_class="calendar",
            summary="About dentist.",
            noticed_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(days=29),
            confidence=0.8,
            sensitivity=DataTier.PERSONAL,
        )
        ruling = await store.admit(again, home=RecordHome.owners(), policy=FakeNotificationPolicy())
    finally:
        store.close()

    assert ruling.kind is NotificationDispositionKind.DROP
    assert ruling.reason is NotificationCondition.DUPLICATE


def test_a_label_this_build_does_not_write_is_refused_and_the_file_left_as_it_was(
    legacy: Path,
) -> None:
    """ADR-0326 §5:3: a later label is one this code does not understand."""
    with sqlite3.connect(legacy) as conn:
        conn.execute(f"PRAGMA user_version = {NOTIFICATION_SCHEMA_VERSION + 1}")
    before = _tables(legacy)

    with pytest.raises(NotificationStoreError, match="schema version 2"):
        _open(legacy)

    assert _tables(legacy) == before
    assert _label(legacy) == NOTIFICATION_SCHEMA_VERSION + 1


def test_a_new_file_is_made_at_the_label(tmp_path: Path) -> None:
    """A file no build wrote is made at this layout, with the home's columns."""
    path = tmp_path / "notifications.db"
    _open(path).close()

    assert _label(path) == NOTIFICATION_SCHEMA_VERSION
    columns, rows = _tables(path)["notifications"]
    assert columns[-2:] == _HOME_COLUMNS
    assert rows == []
