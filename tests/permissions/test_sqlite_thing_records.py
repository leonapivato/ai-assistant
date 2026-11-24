"""SqliteThingRecordStore passes the shared suite, and what only a file owes (ADR-0381 §3, §4).

The binding runs the store through
:class:`~thing_record_store_contract.ThingRecordStoreContract`. Below it, what only a
persistent store has: the things the hub holds recorded as the owner's in the step that
opens the file (§4:1), and nothing written by an opening that finds them recorded; an
owner-only file; records that survive a reopen; two handles on one file deciding a
repeated write as one store (§3:4); the schema label ADR-0326 §5:3 reads; the seam's error
for a backend fault and a corrupt row; and a cancelled call that keeps the connection until
its worker is done.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from thing_record_store_contract import (
    APPROVALS,
    CALENDAR,
    EVERY_KIND,
    LINE_PLACE,
    MAIL_ACCOUNT,
    OWN_CHAT,
    SCHEDULE,
    START,
    ThingRecordStoreContract,
    ThingRecordStoreFactory,
    recorded,
    ticking,
)

from ai_assistant.core.errors import ThingRecordStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ThingKey,
    ThingRecord,
    ThingRecording,
    ThingRecordingKind,
)
from ai_assistant.permissions import SqliteThingRecordStore
from ai_assistant.permissions.thing_records import THING_RECORDS_SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import ThingRecordStore

pytestmark = pytest.mark.anyio

#: What a hub with the line, one account and the calendar holds as it starts.
_HELD: Final = (OWN_CHAT, LINE_PLACE, SCHEDULE, APPROVALS, MAIL_ACCOUNT, CALENDAR)

#: A naive reading, which no seam may take as an instant (ADR-0026 §4).
_NAIVE: Final = datetime(2026, 11, 24)  # noqa: DTZ001  # the naive reading under test


class TestSqliteThingRecordStoreContract(ThingRecordStoreContract):
    """Runs SqliteThingRecordStore through the shared ThingRecordStore suite."""

    @pytest.fixture
    def opened(self) -> Iterator[list[SqliteThingRecordStore]]:
        held: list[SqliteThingRecordStore] = []
        yield held
        for store in held:
            store.close()

    @pytest.fixture
    def factory(
        self, tmp_path: Path, opened: list[SqliteThingRecordStore]
    ) -> ThingRecordStoreFactory:
        def build(*, now: Callable[[], datetime]) -> ThingRecordStore:
            store = SqliteThingRecordStore(
                path=tmp_path / f"thing_records-{len(opened)}.db", now=now
            )
            opened.append(store)
            return store

        return build


def _open(
    path: Path | str,
    *,
    held: Sequence[ThingKey] = (),
    now: Callable[[], datetime] | None = None,
) -> SqliteThingRecordStore:
    """The store at ``path``, on a ticking clock from ``START`` where none is named."""
    return SqliteThingRecordStore(path=path, held=held, now=now or ticking())


def _sql(path: Path, *statements: str) -> None:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()


def _rows(path: Path) -> list[tuple[str, str, str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT kind, identifier, person, recorded_at FROM records ORDER BY seq"
        ).fetchall()


async def _export(path: Path) -> tuple[ThingRecord, ...]:
    store = _open(path)
    try:
        return await store.export()
    finally:
        store.close()


def _owners(keys: Sequence[ThingKey], at: datetime) -> tuple[ThingRecord, ...]:
    return tuple(ThingRecord(key=key, person=OWNER_PERSON_ID, recorded_at=at) for key in keys)


# --- the start's writes (ADR-0381 §4:1) ----------------------------------------------


async def test_an_opening_records_each_held_thing_as_the_owners_at_one_instant(
    tmp_path: Path,
) -> None:
    path = tmp_path / "thing_records.db"
    store = _open(path, held=_HELD)
    try:
        assert await store.export() == _owners(_HELD, START)
        for key in _HELD:
            assert await store.whose(key) == ThingRecord(
                key=key, person=OWNER_PERSON_ID, recorded_at=START
            )
    finally:
        store.close()


async def test_a_second_opening_holding_the_same_things_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    _open(path, held=_HELD).close()
    before = _rows(path)

    # A clock that fails if read: an opening that writes nothing reads none.
    def unread() -> datetime:
        msg = "the clock was read"
        raise AssertionError(msg)

    _open(path, held=_HELD, now=unread).close()

    assert _rows(path) == before
    assert await _export(path) == _owners(_HELD, START)


async def test_a_thing_held_at_a_later_opening_is_recorded_then(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    first = (OWN_CHAT, SCHEDULE, APPROVALS)
    _open(path, held=first).close()
    later = START + timedelta(days=1)

    _open(path, held=(*first, MAIL_ACCOUNT, CALENDAR), now=lambda: later).close()

    assert await _export(path) == (
        *_owners(first, START),
        *_owners((MAIL_ACCOUNT, CALENDAR), later),
    )


async def test_a_thing_no_longer_held_keeps_its_record(tmp_path: Path) -> None:
    """ADR-0381 §7:1: a record stands after its thing is gone."""
    path = tmp_path / "thing_records.db"
    _open(path, held=_HELD).close()

    _open(path, held=(OWN_CHAT,)).close()

    assert await _export(path) == _owners(_HELD, START)


async def test_a_thing_held_twice_is_recorded_once(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    _open(path, held=(CALENDAR, OWN_CHAT, CALENDAR)).close()

    assert await _export(path) == _owners((CALENDAR, OWN_CHAT), START)


async def test_an_opening_whose_clock_fails_records_nothing(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    _open(path, held=(OWN_CHAT,)).close()

    with pytest.raises(ThingRecordStoreError, match="clock"):
        _open(path, held=(OWN_CHAT, CALENDAR), now=lambda: _NAIVE)

    assert await _export(path) == _owners((OWN_CHAT,), START)


def test_a_new_file_whose_opening_fails_is_left_without_a_schema(tmp_path: Path) -> None:
    """The schema and the start's writes are one step: neither lands without the other."""
    path = tmp_path / "thing_records.db"

    with pytest.raises(ThingRecordStoreError, match="clock"):
        _open(path, held=(OWN_CHAT,), now=lambda: _NAIVE)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_a_held_entry_that_is_not_a_thing_key_is_a_value_error(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"

    with pytest.raises(ValueError, match="ThingKey"):
        _open(path, held=("calendar",))  # type: ignore[arg-type]  # the malformed entry under test

    assert not path.exists()


async def test_an_opening_does_not_rewrite_a_record_a_write_made(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    store = _open(path)
    try:
        written = recorded(await store.record_whose(CALENDAR, person=OWNER_PERSON_ID))
    finally:
        store.close()

    _open(path, held=(CALENDAR,), now=lambda: START + timedelta(days=1)).close()

    assert await _export(path) == (written,)


# --- persistence ---------------------------------------------------------------------


async def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    journal = tmp_path / "thing_records.db-journal"
    journal.write_bytes(b"")
    journal.chmod(0o644)

    store = _open(path, held=_HELD)
    try:
        notes = ThingKey.model_validate({"kind": "source", "identifier": "notes"})
        recorded(await store.record_whose(notes, person=OWNER_PERSON_ID))
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with contextlib.suppress(FileNotFoundError):
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600


async def test_every_record_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    first = _open(path)
    try:
        records = [
            recorded(await first.record_whose(key, person=OWNER_PERSON_ID)) for key in EVERY_KIND
        ]
    finally:
        first.close()

    again = _open(path)
    try:
        assert await again.export() == tuple(records)
        repeat = await again.record_whose(LINE_PLACE, person=OWNER_PERSON_ID)
        assert repeat == ThingRecording(kind=ThingRecordingKind.ALREADY_RECORDED, record=records[1])
    finally:
        again.close()


async def test_two_handles_on_one_file_share_one_store(tmp_path: Path) -> None:
    """The write rule holds across handles, as across processes: the write step decides."""
    path = tmp_path / "thing_records.db"
    one = _open(path)
    other = _open(path)
    try:
        first = recorded(await one.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID))
        again = await other.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID)

        assert again == ThingRecording(kind=ThingRecordingKind.ALREADY_RECORDED, record=first)
        assert await other.whose(MAIL_ACCOUNT) == first
        assert len(_rows(path)) == 1
    finally:
        one.close()
        other.close()


@pytest.mark.parametrize("version", [0, THING_RECORDS_SCHEMA_VERSION + 1, 7])
async def test_a_file_of_another_schema_is_refused_untouched(tmp_path: Path, version: int) -> None:
    path = tmp_path / "thing_records.db"
    _sql(path, "CREATE TABLE records(id TEXT PRIMARY KEY)", f"PRAGMA user_version = {version}")

    with pytest.raises(ThingRecordStoreError, match=f"schema version {version}"):
        _open(path, held=_HELD)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables == {"records"}
        assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


@pytest.mark.parametrize("version", [1, THING_RECORDS_SCHEMA_VERSION + 1, 7])
def test_a_labelled_file_with_no_tables_is_refused_untouched(tmp_path: Path, version: int) -> None:
    """ADR-0326 §5:3: a newer label is refused whether or not the file holds a table."""
    path = tmp_path / "thing_records.db"
    _sql(path, f"PRAGMA user_version = {version}")

    with pytest.raises(ThingRecordStoreError, match=f"schema version {version}"):
        _open(path, held=_HELD)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_a_new_store_writes_its_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    _open(path).close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0] == THING_RECORDS_SCHEMA_VERSION == 1
        )


def test_a_path_that_cannot_be_opened_is_the_seams_error(tmp_path: Path) -> None:
    with pytest.raises(ThingRecordStoreError):
        _open(str(tmp_path / "bad\0name.db"))
    with pytest.raises(ThingRecordStoreError):
        _open(tmp_path / "missing" / "thing_records.db")


async def test_a_closed_backend_is_the_seams_error() -> None:
    store = SqliteThingRecordStore(path=":memory:")
    store.close()

    with pytest.raises(ThingRecordStoreError):
        await store.whose(CALENDAR)
    with pytest.raises(ThingRecordStoreError):
        await store.record_whose(CALENDAR, person=OWNER_PERSON_ID)
    with pytest.raises(ThingRecordStoreError):
        await store.export()


_A_RECORD = (
    "INSERT INTO records(kind, identifier, person, recorded_at) "
    "VALUES ({kind}, {identifier}, {person}, {recorded_at})"
)


def _row(**values: str) -> str:
    fields = {
        "kind": "'source'",
        "identifier": "'calendar'",
        "person": "'person:owner'",
        "recorded_at": "'2026-11-24T09:00:00+00:00'",
    }
    return _A_RECORD.format(**(fields | values))


@pytest.mark.parametrize(
    ("statement", "at_the_calendars_key"),
    [
        (_row(person="'person:sam'"), True),
        (_row(person="'group:anyone'"), True),
        (_row(recorded_at="'not-an-instant'"), True),
        (_row(kind="'device'"), False),
        (_row(identifier="' calendar'"), False),
    ],
    ids=["person", "anyone", "instant", "kind", "identifier"],
)
async def test_a_corrupt_row_is_the_seams_error(
    tmp_path: Path, statement: str, *, at_the_calendars_key: bool
) -> None:
    """A row that is not a record is a fault, never read as the owner's (ADR-0381 §5:1)."""
    path = tmp_path / "thing_records.db"
    _open(path).close()
    _sql(path, statement)

    store = _open(path)
    try:
        with pytest.raises(ThingRecordStoreError, match="corrupt"):
            await store.export()
        if at_the_calendars_key:
            with pytest.raises(ThingRecordStoreError, match="corrupt"):
                await store.whose(CALENDAR)
            with pytest.raises(ThingRecordStoreError, match="corrupt"):
                await store.record_whose(CALENDAR, person=OWNER_PERSON_ID)
    finally:
        store.close()
    assert len(_rows(path)) == 1


async def test_a_write_whose_clock_fails_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "thing_records.db"
    store = _open(path, now=lambda: _NAIVE)
    try:
        with pytest.raises(ThingRecordStoreError, match="clock"):
            await store.record_whose(CALENDAR, person=OWNER_PERSON_ID)

        assert await store.whose(CALENDAR) is None
    finally:
        store.close()
    assert _rows(path) == []


async def test_a_cancelled_call_keeps_the_connection_until_its_worker_is_done(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    readings = iter([True, False])

    def slow_clock() -> datetime:
        if next(readings):
            entered.set()
            release.wait(timeout=5)
        return START

    store = _open(tmp_path / "thing_records.db", now=slow_clock)
    try:
        first = asyncio.create_task(store.record_whose(CALENDAR, person=OWNER_PERSON_ID))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(store.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID))
        await asyncio.sleep(0.05)
        assert not second.done()  # the lock is still held for the running worker

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert recorded(await second).key == MAIL_ACCOUNT
        assert [one.key for one in await store.export()] == [CALENDAR, MAIL_ACCOUNT]
    finally:
        release.set()
        store.close()
