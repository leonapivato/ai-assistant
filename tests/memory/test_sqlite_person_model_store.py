"""SqlitePersonModelStore: the shared conformance suite, plus what only it owes.

The suite holds the contract (ADR-0338 §10); this module holds what belongs to a
*persistent* store: that the file is owner-only (ADR-0004 §4); that the owner, and the
hub's seed of their zone, are written when the store is first created and never again
(§2:1, §3:7); that what it wrote survives a reopen; that a file of another schema is
refused before anything is written (ADR-0326 §5:3); that a broken backend or a corrupt
row surfaces as the seam's own error; that two handles on one file share one store, so
§10:2's one step holds across connections; that the change log is append-only on disk
(§3:5); and that a cancelled call keeps the connection until its worker is done
(ADR-0054).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from person_model_store_contract import (
    MEMORY,
    OTHER_MEMORY,
    PANEL,
    PersonModelStoreContract,
    PersonModelStoreFactory,
    field_suggestion,
    pin_suggestion,
    ticking,
)

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    PersonModelRefusal,
    PersonModelWriteKind,
    PersonRole,
    ProfileField,
)
from ai_assistant.memory.person_model_store import (
    PERSON_MODEL_SCHEMA_VERSION,
    SqlitePersonModelStore,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import PersonModel

pytestmark = pytest.mark.anyio

#: The bound the binding builds with where a case names none: the fake's default.
_FIELD_CHARS_DEFAULT = 200

_CREATED = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


class TestSqlitePersonModelStoreContract(PersonModelStoreContract):
    """Runs SqlitePersonModelStore through the shared PersonModelStore suite."""

    @pytest.fixture
    def factory(self, tmp_path: Path) -> Iterator[PersonModelStoreFactory]:
        opened: list[SqlitePersonModelStore] = []

        def build(
            *,
            field_chars: int = _FIELD_CHARS_DEFAULT,
            now: Callable[[], datetime] | None = None,
        ) -> PersonModelStore:
            path = tmp_path / f"person_model-{len(opened)}.db"
            if now is None:
                store = SqlitePersonModelStore(path=path, field_chars=field_chars)
            else:
                store = SqlitePersonModelStore(path=path, field_chars=field_chars, now=now)
            opened.append(store)
            return store

        yield build
        for store in opened:
            store.close()


def _open(
    path: Path | str,
    *,
    seed_time_zone: str | None = None,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[str], str] | None = None,
) -> SqlitePersonModelStore:
    """The store at ``path``, on a ticking clock from ``_CREATED`` where none is named."""
    if new_id is None:
        return SqlitePersonModelStore(
            path=path,
            field_chars=_FIELD_CHARS_DEFAULT,
            seed_time_zone=seed_time_zone,
            now=now or ticking(_CREATED),
        )
    return SqlitePersonModelStore(
        path=path,
        field_chars=_FIELD_CHARS_DEFAULT,
        seed_time_zone=seed_time_zone,
        now=now or ticking(_CREATED),
        new_id=new_id,
    )


async def _owner(store: SqlitePersonModelStore) -> PersonModel:
    model = await store.read(OWNER_PERSON_ID)
    assert model is not None
    return model


# --- the owner and the seed (§2:1, §3:7) ------------------------------------------


async def test_the_owner_is_created_with_the_store(tmp_path: Path) -> None:
    store = _open(tmp_path / "person_model.db")
    try:
        model = await _owner(store)
    finally:
        store.close()

    assert (model.person.id, model.person.role, model.person.created_at) == (
        OWNER_PERSON_ID,
        PersonRole.OWNER,
        _CREATED,
    )
    assert model.changes == ()


async def test_the_seed_sets_the_owners_zone_and_is_logged_as_the_hubs(tmp_path: Path) -> None:
    store = _open(tmp_path / "person_model.db", seed_time_zone="Europe/Lisbon")
    try:
        model = await _owner(store)
    finally:
        store.close()

    assert model.profile.time_zone == "Europe/Lisbon"
    [change] = model.changes
    assert (change.field, change.old, change.new, change.at) == (
        ProfileField.TIME_ZONE,
        None,
        "Europe/Lisbon",
        _CREATED,
    )
    assert change.act == PersonModelAct(how=PersonActHow.SEED)
    assert change.act.by is None


async def test_no_seed_leaves_the_zone_empty_and_logs_nothing(tmp_path: Path) -> None:
    store = _open(tmp_path / "person_model.db", seed_time_zone=None)
    try:
        model = await _owner(store)
    finally:
        store.close()

    assert all(model.profile.value(field) is None for field in ProfileField)
    assert model.changes == ()


async def test_the_seed_is_written_once_when_the_store_is_first_created(tmp_path: Path) -> None:
    """A reopen with another seed, or after the owner changed the zone, changes nothing."""
    path = tmp_path / "person_model.db"
    first = _open(path, seed_time_zone="Europe/Lisbon")
    try:
        await first.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, None, act=PANEL)
        before = await first.export()
    finally:
        first.close()

    again = _open(path, seed_time_zone="America/New_York")
    try:
        assert await again.export() == before
        assert (await _owner(again)).profile.time_zone is None
    finally:
        again.close()


@pytest.mark.parametrize("zone", ["Mars/Olympus_Mons", "../etc/passwd", "  "])
def test_a_seed_that_is_no_time_zone_is_refused_before_any_file(tmp_path: Path, zone: str) -> None:
    path = tmp_path / "person_model.db"

    with pytest.raises(ValueError, match="seed"):
        _open(path, seed_time_zone=zone)

    assert not path.exists()


async def test_a_creation_whose_clock_reading_fails_leaves_no_store(tmp_path: Path) -> None:
    """The owner and the schema are one step: a refused reading rolls both back."""
    path = tmp_path / "person_model.db"

    with pytest.raises(PersonModelStoreError, match="clock"):
        _open(path, now=lambda: datetime(2026, 10, 21, 9, 0))  # noqa: DTZ001 — the naive reading under test

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    store = _open(path, seed_time_zone="Europe/Lisbon")
    try:
        assert (await _owner(store)).profile.time_zone == "Europe/Lisbon"
    finally:
        store.close()


async def test_a_cleared_store_holds_no_one_after_a_reopen(tmp_path: Path) -> None:
    """§10:5's clear erases the owner, and the seed is the store's first creation alone."""
    path = tmp_path / "person_model.db"
    first = _open(path, seed_time_zone="Europe/Lisbon")
    try:
        await first.clear()
    finally:
        first.close()

    again = _open(path, seed_time_zone="Europe/Lisbon")
    try:
        assert await again.read(OWNER_PERSON_ID) is None
        assert (await again.export()).model_dump() == type(await again.export())().model_dump()
    finally:
        again.close()


# --- persistence -------------------------------------------------------------------


async def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "person_model.db"
    journal = tmp_path / "person_model.db-journal"
    journal.write_bytes(b"")
    journal.chmod(0o644)

    store = _open(path)
    try:
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with contextlib.suppress(FileNotFoundError):
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600


async def test_everything_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "person_model.db"
    first = _open(path, seed_time_zone="Europe/Lisbon")
    try:
        await first.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
        pinned = await first.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        assert pinned.record_id is not None
        await first.remove_pin(OWNER_PERSON_ID, pinned.record_id)
        await first.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY)
        dismissed = await first.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY))
        assert dismissed.record_id is not None
        await first.dismiss_suggestion(OWNER_PERSON_ID, dismissed.record_id)
        await first.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )
        before = await first.export()
        model = await _owner(first)
    finally:
        first.close()

    again = _open(path)
    try:
        assert await again.export() == before
        assert await _owner(again) == model
        # What the reopened store holds still decides: the dismissed one stops another.
        stopped = await again.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY))
        assert stopped.kind is PersonModelWriteKind.UNCHANGED
    finally:
        again.close()


async def test_two_handles_on_one_file_share_one_store(tmp_path: Path) -> None:
    path = tmp_path / "person_model.db"
    one = _open(path)
    other = _open(path)
    try:
        first = await one.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        again = await other.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        recorded = await other.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )
        await one.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

        assert first.kind is PersonModelWriteKind.WRITTEN
        assert (again.kind, again.record_id) == (PersonModelWriteKind.UNCHANGED, first.record_id)
        assert recorded.record_id is not None
        assert (await _owner(other)).suggestions == ()
    finally:
        one.close()
        other.close()


@pytest.mark.parametrize("version", [0, PERSON_MODEL_SCHEMA_VERSION + 1, 7])
async def test_a_file_of_another_schema_is_refused_untouched(tmp_path: Path, version: int) -> None:
    path = tmp_path / "person_model.db"
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE persons(id TEXT PRIMARY KEY)")
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()

    with pytest.raises(PersonModelStoreError, match=f"schema version {version}"):
        _open(path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables == {"persons"}
        assert conn.execute("SELECT count(*) FROM persons").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


@pytest.mark.parametrize("version", [1, PERSON_MODEL_SCHEMA_VERSION + 1, 7])
def test_a_labelled_file_with_no_tables_is_refused_untouched(tmp_path: Path, version: int) -> None:
    """ADR-0326 §5:3: a newer label is refused whether or not the file holds a table."""
    path = tmp_path / "person_model.db"
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()

    with pytest.raises(PersonModelStoreError, match=f"schema version {version}"):
        _open(path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


async def test_accepting_a_suggestion_validates_it_against_the_bound_held_now(
    tmp_path: Path,
) -> None:
    """§3:2: a value recorded under a wider bound is refused at acceptance, nothing written."""
    path = tmp_path / "person_model.db"
    first = _open(path)
    try:
        recorded = await first.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.NAME, "Robin Vale")
        )
        assert recorded.record_id is not None
    finally:
        first.close()

    tighter = SqlitePersonModelStore(path=path, field_chars=5, now=ticking(_CREATED))
    try:
        before = await tighter.export()

        refused = await tighter.accept_suggestion(
            OWNER_PERSON_ID, recorded.record_id, by=OWNER_PERSON_ID
        )

        assert refused.kind is PersonModelWriteKind.REFUSED
        assert refused.refusal is PersonModelRefusal.INVALID_VALUE
        assert refused.reason
        assert await tighter.export() == before
        assert [one.id for one in (await _owner(tighter)).suggestions] == [recorded.record_id]
    finally:
        tighter.close()


def test_a_new_store_writes_its_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "person_model.db"
    _open(path).close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == PERSON_MODEL_SCHEMA_VERSION == 1


def test_a_path_that_cannot_be_opened_is_the_seams_error(tmp_path: Path) -> None:
    with pytest.raises(PersonModelStoreError):
        _open(str(tmp_path / "bad\0name.db"))
    with pytest.raises(PersonModelStoreError):
        _open(tmp_path / "missing" / "person_model.db")


@pytest.mark.parametrize("field_chars", [0, -1, True, 1.5, "200"], ids=repr)
def test_a_bound_below_one_is_refused(tmp_path: Path, field_chars: object) -> None:
    with pytest.raises(ValueError, match="field_chars"):
        SqlitePersonModelStore(path=tmp_path / "person_model.db", field_chars=field_chars)  # type: ignore[arg-type]


async def test_a_closed_backend_is_the_seams_error() -> None:
    store = SqlitePersonModelStore(path=":memory:", field_chars=_FIELD_CHARS_DEFAULT)
    store.close()

    with pytest.raises(PersonModelStoreError):
        await store.read(OWNER_PERSON_ID)
    with pytest.raises(PersonModelStoreError):
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
    with pytest.raises(PersonModelStoreError):
        await store.export()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE persons SET role = 'stranger'",
        "INSERT INTO fields(person_id, field, value) VALUES ('person:owner', 'pronouns', 'x')",
        "INSERT INTO pins(id, person_id, memory_id, pinned_at, act) "
        "VALUES ('pin:x', 'person:owner', 'm', 'not-an-instant', '{\"how\": \"panel\"}')",
        "INSERT INTO marks(id, person_id, memory_id, marked_at) "
        "VALUES ('mark:x', 'person:owner', 'm', '2026-10-21T09:00:00')",
        "INSERT INTO suggestions(id, person_id, kind, proposed, recorded_at, state) "
        "VALUES ('suggestion:x', 'person:owner', 'pin', 'not json', "
        "'2026-10-21T09:00:00+00:00', 'pending')",
    ],
    ids=["unknown-role", "unknown-field", "pin-instant", "naive-mark", "suggestion-json"],
)
async def test_a_corrupt_row_is_the_seams_error(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "person_model.db"
    _open(path).close()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute(statement)
        conn.commit()

    store = _open(path)
    try:
        with pytest.raises(PersonModelStoreError, match="corrupt"):
            await store.export()
    finally:
        store.close()


@pytest.mark.parametrize("zone", ["é" * 200, "a" * 200], ids=["non-ascii", "ascii"])
async def test_a_zone_name_the_file_system_refuses_is_an_invalid_value(
    tmp_path: Path, zone: str
) -> None:
    """§3:2: a name too long for a path is refused as a value, never raised as OSError."""
    store = _open(tmp_path / "person_model.db")
    try:
        before = await store.export()

        written = await store.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, zone, act=PANEL)
        suggested = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.TIME_ZONE, zone)
        )

        assert written.refusal is PersonModelRefusal.INVALID_VALUE
        assert suggested.refusal is PersonModelRefusal.INVALID_VALUE
        assert await store.export() == before
    finally:
        store.close()
    with pytest.raises(ValueError, match="seed"):
        _open(tmp_path / "seeded.db", seed_time_zone=zone)


async def test_a_write_that_fails_after_its_first_statements_leaves_nothing(
    tmp_path: Path,
) -> None:
    """§10:2's one step: the acceptance and the change-log entry roll back with the field."""
    path = tmp_path / "person_model.db"
    store = _open(path)
    try:
        await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )
        before = await store.export()
        with contextlib.closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TRIGGER refuse_fields BEFORE INSERT ON fields "
                "BEGIN SELECT RAISE(ABORT, 'the disk refused the field'); END"
            )
            conn.commit()

        with pytest.raises(PersonModelStoreError, match="refused the field"):
            await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

        assert await store.export() == before
        with contextlib.closing(sqlite3.connect(path)) as conn:
            conn.execute("DROP TRIGGER refuse_fields")
            conn.commit()
        retried = await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)
        assert retried.kind is PersonModelWriteKind.WRITTEN
        model = await _owner(store)
        assert model.profile.address == "Robin"
        assert len(model.changes) == 1
        assert model.suggestions == ()
    finally:
        store.close()


async def test_the_change_log_is_append_only_on_disk(tmp_path: Path) -> None:
    """§3:5: an entry is neither rewritten nor removed while its person is held."""
    path = tmp_path / "person_model.db"
    store = _open(path)
    try:
        await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
    finally:
        store.close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE changes SET new = 'someone else'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM changes")


# --- arguments and ids ---------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.set_field(OWNER_PERSON_ID, "name", "Robin", act=PANEL),
        lambda s: s.set_field(OWNER_PERSON_ID, ProfileField.NAME, 7, act=PANEL),
        lambda s: s.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin", act="panel"),
        lambda s: s.add_pin(OWNER_PERSON_ID, "memory:\ud800", act=PANEL),
        lambda s: s.record_suggestion(OWNER_PERSON_ID, "a suggestion"),
        lambda s: s.accept_suggestion(OWNER_PERSON_ID, "suggestion:1", by=" "),
    ],
    ids=[
        "field-not-a-field",
        "value-not-text",
        "act-not-an-act",
        "surrogate-id",
        "not-a-proposal",
        "blank-by",
    ],
)
async def test_a_malformed_argument_is_a_value_error_before_any_read(
    tmp_path: Path, call: Callable[[SqlitePersonModelStore], object]
) -> None:
    store = _open(tmp_path / "person_model.db")
    try:
        before = await store.export()
        store.close()  # anything that reached the backend would now fail otherwise

        with pytest.raises(ValueError):  # noqa: PT011 — each argument's own message
            await call(store)  # type: ignore[misc]  # each call is a coroutine

    finally:
        store.close()
    assert before.persons


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.set_field(
            OWNER_PERSON_ID,
            ProfileField.NAME,
            "Robin",
            act=PANEL.model_copy(update={"by": ""}),
        ),
        lambda s: s.add_pin(
            OWNER_PERSON_ID, MEMORY, act=PANEL.model_copy(update={"how": PersonActHow.SEED})
        ),
        lambda s: s.record_suggestion(
            OWNER_PERSON_ID, pin_suggestion(MEMORY).model_copy(update={"episode_id": ""})
        ),
        lambda s: s.record_suggestion(
            OWNER_PERSON_ID,
            field_suggestion(ProfileField.NAME, "Robin").model_copy(update={"part": None}),
        ),
    ],
    ids=["blank-by", "seed-act-naming-a-person", "blank-episode", "field-without-its-part"],
)
async def test_a_model_that_skipped_its_validation_is_refused_before_any_write(
    tmp_path: Path, call: Callable[[SqlitePersonModelStore], object]
) -> None:
    """An instance copied past validation is a ``ValueError``; the model stays readable."""
    store = _open(tmp_path / "person_model.db")
    try:
        before = await store.export()

        with pytest.raises(ValueError, match="not a valid"):
            await call(store)  # type: ignore[misc]  # each call is a coroutine

        assert await store.export() == before
        assert await store.read(OWNER_PERSON_ID) is not None
    finally:
        store.close()


class _Minting:
    """A ``new_id`` that mints ``fixed`` first, then fresh ids."""

    def __init__(self, *fixed: str) -> None:
        self.fixed = list(fixed)
        self.minted = 0

    def __call__(self, kind: str) -> str:
        if self.fixed:
            return self.fixed.pop(0)
        self.minted += 1
        return f"{kind}:fresh-{self.minted}"


async def test_an_id_a_held_record_carries_is_minted_again(tmp_path: Path) -> None:
    """No two records answer to one id, across pins, marks and suggestions."""
    minting = _Minting("record:one", "record:one", "record:one")
    store = _open(tmp_path / "person_model.db", new_id=minting)
    try:
        pinned = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        marked = await store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY)
        suggested = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY))
    finally:
        store.close()

    assert pinned.record_id == "record:one"
    assert marked.record_id == "mark:fresh-1"
    assert suggested.record_id == "suggestion:fresh-2"


async def test_a_factory_that_keeps_minting_a_held_id_fails_the_write_untouched(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "person_model.db", new_id=lambda _kind: "record:one")
    try:
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        before = await store.export()

        with pytest.raises(PersonModelStoreError, match="minted"):
            await store.add_pin(OWNER_PERSON_ID, OTHER_MEMORY, act=PANEL)
        with pytest.raises(PersonModelStoreError, match="minted"):
            await store.add_style_mark(OWNER_PERSON_ID, MEMORY)

        assert await store.export() == before
    finally:
        store.close()


async def test_a_cancelled_call_keeps_the_connection_until_its_worker_is_done(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    minted = iter(["mark:slow", "mark:second"])

    def slow_id(_kind: str) -> str:
        attempt = next(minted)
        if attempt == "mark:slow":
            entered.set()
            release.wait(timeout=5)
        return attempt

    store = _open(tmp_path / "person_model.db", new_id=slow_id)
    try:
        first = asyncio.create_task(store.add_style_mark(OWNER_PERSON_ID, MEMORY))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY))
        await asyncio.sleep(0.05)
        assert not second.done()  # the lock is still held for the running worker

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second).record_id == "mark:second"
        marks = [one.id for one in (await store.export()).style_marks]
        assert marks == ["mark:slow", "mark:second"]
    finally:
        release.set()
        store.close()
