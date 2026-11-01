"""ADR-0326 §4:2's test, for ADR-0362 §2:2: a file the release before the request form wrote.

``tests/memory/legacy/person-model-before-adr-0362.db`` was written by the previous
release's own ``SqlitePersonModelStore`` (the build at ``ee87e6ed0``, at the label ``1``),
through its public members alone, never by hand-built SQL. It holds the owner, seeded with
the zone ``Europe/Lisbon``, and an act of every form that release could write:

- four changes: the seed's zone, a name set on the panel, an address set by a yes naming
  its question part, and a language set by accepting a field suggestion;
- three pins: one on the panel, one by a yes, and one on the panel since removed;
- two style marks, one removed;
- three suggestions: the field suggestion accepted, a pin suggestion pending, and one
  dismissed.

``PersonModelAct``'s request form is left out of a dump where it is unset (§2:2), so each
stored act validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stays ``1``. The head opens a copy, writes nothing to open it, and reads every
record back as it was, each act serialising to the bytes the file holds. The opened file
then holds an act of the request form beside them, which outlives a reopen.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    PersonModelWriteKind,
    ProfileField,
    QuestionPart,
    SuggestionState,
)
from ai_assistant.memory.person_model_store import (
    PERSON_MODEL_SCHEMA_VERSION,
    SqlitePersonModelStore,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

_FIXTURE: Final = Path(__file__).parent / "legacy" / "person-model-before-adr-0362.db"

#: The first instant the previous release recorded, one second per write after it.
_WROTE_AT: Final = datetime(2026, 10, 31, 12, tzinfo=UTC)

#: The bound on a field's length the file was written under, and the head opens it with.
_FIELD_CHARS: Final = 200

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
_SEED: Final = PersonModelAct(how=PersonActHow.SEED)
_BY_A_YES: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    approval=QuestionPart(round="round-before-1", part=1),
    episode_id="activation:act-before-yes",
)
_BY_A_SUGGESTION: Final = PersonModelAct(
    how=PersonActHow.SUGGESTION, by=OWNER_PERSON_ID, episode_id="activation:act-before-said"
)
_BY_A_TICKET: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    request="q-after-1",
    episode_id="activation:act-after-approval",
)


def _at(seconds: int) -> datetime:
    return _WROTE_AT + timedelta(seconds=seconds)


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "person_model.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (value,) = conn.execute("PRAGMA user_version").fetchone()
    return int(value)


def _dump(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every table's rows, read out of band and in a fixed order."""
    with sqlite3.connect(path) as conn:
        tables = [
            str(name)
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)  # noqa: S608 — names read from the file's own catalogue
            for table in tables
        }


def _stored_acts(path: Path) -> list[str]:
    """The acts the file holds, as the bytes it holds them in, changes then pins."""
    with sqlite3.connect(path) as conn:
        changes = [str(act) for (act,) in conn.execute("SELECT act FROM changes ORDER BY seq")]
        pins = [str(act) for (act,) in conn.execute("SELECT act FROM pins ORDER BY seq")]
    return changes + pins


def _open(path: Path) -> SqlitePersonModelStore:
    return SqlitePersonModelStore(path=path, field_chars=_FIELD_CHARS)


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file is at the label the head writes, which this change does not move."""
    assert _label(_FIXTURE) == 1
    assert PERSON_MODEL_SCHEMA_VERSION == 1


async def test_the_head_opens_it_writing_nothing_and_keeps_its_label(legacy: Path) -> None:
    """ADR-0326 §4's note, ADR-0362 §2:2: the upgrade is empty and the label stays."""
    before = _dump(legacy)

    store = _open(legacy)
    try:
        assert await store.read(OWNER_PERSON_ID) is not None
    finally:
        store.close()

    assert _label(legacy) == 1
    assert _dump(legacy) == before


async def test_every_record_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: each record whole, an act of every earlier form among them."""
    store = _open(legacy)
    try:
        model = await store.read(OWNER_PERSON_ID)
        exported = await store.export()
    finally:
        store.close()

    assert model is not None
    assert model.profile.model_dump() == {
        "name": "Robin Vale",
        "address": "Robin",
        "assistant_name": None,
        "time_zone": "Europe/Lisbon",
        "language": "Portuguese",
    }
    assert [(one.field, one.old, one.new, one.at, one.act) for one in model.changes] == [
        (ProfileField.TIME_ZONE, None, "Europe/Lisbon", _at(0), _SEED),
        (ProfileField.NAME, None, "Robin Vale", _at(1), _PANEL),
        (ProfileField.ADDRESS, None, "Robin", _at(2), _BY_A_YES),
        (ProfileField.LANGUAGE, None, "Portuguese", _at(4), _BY_A_SUGGESTION),
    ]
    assert model.changes[-1].suggestion_id == "suggestion-before-1"
    assert [(one.id, one.memory_id, one.act, one.removed_at) for one in model.pins] == [
        ("pin-before-4", "memory:before-diet", _PANEL, None),
        ("pin-before-5", "memory:before-sister", _BY_A_YES, None),
        ("pin-before-6", "memory:before-removed", _PANEL, _at(11)),
    ]
    assert [(one.id, one.memory_id, one.removed_at) for one in model.style_marks] == [
        ("mark-before-7", "memory:before-style", None),
        ("mark-before-8", "memory:before-style-removed", _at(14)),
    ]
    assert [(one.id, one.state) for one in exported.suggestions] == [
        ("suggestion-before-1", SuggestionState.ACCEPTED),
        ("suggestion-before-2", SuggestionState.PENDING),
        ("suggestion-before-3", SuggestionState.DISMISSED),
    ]
    assert [one.id for one in model.suggestions] == ["suggestion-before-2"]


async def test_each_stored_act_serialises_to_the_bytes_the_file_holds(legacy: Path) -> None:
    """ADR-0362 §2:2: ``request`` is left out where unset, so no stored act moves."""
    store = _open(legacy)
    try:
        model = await store.read(OWNER_PERSON_ID)
    finally:
        store.close()

    assert model is not None
    read = [one.act for one in model.changes] + [one.act for one in model.pins]
    assert [act.model_dump_json() for act in read] == _stored_acts(legacy)
    assert all(act.request is None for act in read)


async def test_the_opened_file_holds_an_act_of_the_request_form_across_a_reopen(
    legacy: Path,
) -> None:
    """§2:1: a change and a pin made under a ticket, beside the earlier forms."""
    store = _open(legacy)
    try:
        changed = await store.set_field(
            OWNER_PERSON_ID, ProfileField.ASSISTANT_NAME, "Iris", act=_BY_A_TICKET
        )
        pinned = await store.add_pin(OWNER_PERSON_ID, "memory:after-tea", act=_BY_A_TICKET)
    finally:
        store.close()
    assert changed.kind is PersonModelWriteKind.WRITTEN
    assert pinned.kind is PersonModelWriteKind.WRITTEN

    reopened = _open(legacy)
    try:
        model = await reopened.read(OWNER_PERSON_ID)
    finally:
        reopened.close()

    assert model is not None
    assert [one.act for one in model.changes] == [
        _SEED,
        _PANEL,
        _BY_A_YES,
        _BY_A_SUGGESTION,
        _BY_A_TICKET,
    ]
    assert [one.act for one in model.pins][-1] == _BY_A_TICKET
    assert _label(legacy) == 1
