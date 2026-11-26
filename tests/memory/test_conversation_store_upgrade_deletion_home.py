"""ADR-0326 §4:2's test, for ADR-0389 §3:3: a conversation file the previous release wrote.

``tests/memory/legacy/conversations-before-adr-0389.db`` was written by the previous
release's own ``SqliteConversationStore`` (the build at ``0c48fe120``, at the label
``15``), through its public API and never by hand-built SQL, with invented data, a
retention of seven days and a grace of an hour: "my devices" a phone and a watch;
``conv-idle``, the owner's, never written into and reclaimed past its retention, which
records its deletion and drops its row in one step; ``conv-dropped``, the shared
things', a message and then its deletion, its row dropped past the grace; ``conv-kept``,
the owner's, on the phone, the watch and the laptop, a question and its answer; and
``conv-owners-gone``, the owner's, and ``conv-shared-gone``, the shared things', each a
message and then its deletion, each row still standing. Beside it,
``conversations-before-adr-0389.json`` is what that build read back from the file
through every read the store answers, written by that code too.

No deletion that build recorded holds a home, which every one this build records does
(ADR-0389 §3:1), so the label moves. The head opens a copy and upgrades it in place:
never refuse it (ADR-0326 §5:1), drop nothing (§4:4), read back every record as that
release did, and write into each deletion its conversation row's home where that row
stands and the owner's domain where it does not (ADR-0389 §3:3), moving no other byte.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import BaseModel

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    ConversationDeletedChange,
    RecordHome,
    Sight,
    SightMode,
)
from ai_assistant.memory._episode_format import (
    CONVERSATION_RECORD_FORMAT,
    CONVERSATION_RECORD_FORMATS,
    HOMED_CONVERSATION_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from sight_equivalence import SIGHTS

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "conversations-before-adr-0389.db"
_READ_BACK: Final = _LEGACY / "conversations-before-adr-0389.json"

#: The instant the previous release read the file back at, and the head opens it at.
_NOW: Final = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)

_CONVERSATIONS: Final = (
    "conv-idle",
    "conv-dropped",
    "conv-kept",
    "conv-owners-gone",
    "conv-shared-gone",
)

_HOME_COLUMNS: Final = ("home_kind", "home_id")
_OWNERS: Final = (RecordHome.owners().kind.value, RecordHome.owners().id)
_SHARED: Final = (RecordHome.shared().kind.value, RecordHome.shared().id)

#: The home each deletion in the file is given: its row's where it stands, and the
#: owner's where it does not, ``conv-dropped`` being the shared things' (ADR-0389 §3:3).
_DELETION_HOMES: Final = {
    "conv-idle": RecordHome.owners(),
    "conv-dropped": RecordHome.owners(),
    "conv-owners-gone": RecordHome.owners(),
    "conv-shared-gone": RecordHome.shared(),
}

#: The owner's sights, one for each domain an owner's act may name and one for none.
_OWNERS_ACTS: Final[dict[str, Sight]] = {
    "from-none": Sight.of_owners_act(None),
    "from-the-owners-domain": Sight.of_owners_act(RecordHome.owners()),
    "from-the-shared-things": Sight.of_owners_act(RecordHome.shared()),
}


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
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
    target = tmp_path / "conversations.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path, mode: SightMode = SightMode.COUNT) -> SqliteConversationStore:
    return SqliteConversationStore(path=path, now=lambda: _NOW, sight_mode=mode)


def _json(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_json(one) for one in value]
    if isinstance(value, dict):
        return {str(key): _json(one) for key, one in value.items()}
    return value


async def _read_back(path: Path) -> dict[str, object]:
    """Every record the previous release read back, read the same way by the head."""
    store = _open(path)
    held: dict[str, object] = {}
    try:
        held["export"] = _json(await store.export())
        held["recent"] = _json(await store.recent())
        held["my_devices"] = _json(await store.my_devices())
        held["stamped"] = _json(await store.stamped_conversation_ids())
        held["awaiting"] = _json(await store.conversations_awaiting())
        held["changes"] = _json(await store.changes(after=0))
        for one in _CONVERSATIONS:
            held[f"get/{one}"] = _json(await store.get(one))
            held[f"transcript/{one}"] = _json(await store.transcript(one))
            held[f"devices/{one}"] = _json(await store.conversation_devices(one))
            held[f"untaken/{one}"] = _json(await store.untaken_messages(one))
            held[f"taken_in/{one}"] = _json(await store.taken_in(one, positions=(1, 2, 3)))
        for device in ("phone", "watch", "laptop"):
            held[f"device_changes/{device}"] = _json(await store.device_changes(device, after=0))
            held[f"device_conversations/{device}"] = _json(await store.device_conversations(device))
    finally:
        store.close()
    return held


async def _deleted(store: SqliteConversationStore) -> set[str]:
    """The conversations whose deletion ``store`` gives back."""
    page = await store.changes(after=0, limit=1000)
    return {
        one.conversation_id for one in page.changes if isinstance(one, ConversationDeletedChange)
    }


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file is at the previous label, its change stream holds no home, and it holds
    the deletions the cases name: two with their rows standing, two dropped."""
    assert _label(_FIXTURE) == HOMED_CONVERSATION_RECORD_FORMAT
    tables = _tables(_FIXTURE)
    columns, rows = tables["chat_changes"]
    assert not set(_HOME_COLUMNS) & set(columns)
    kind, conversation = columns.index("kind"), columns.index("conversation_id")
    deleted = {row[conversation] for row in rows if row[kind] == "conversation_deleted"}
    assert deleted == set(_DELETION_HOMES)
    standing = {row[0] for row in tables["conversations"][1]}
    assert standing == {"conv-kept", "conv-owners-gone", "conv-shared-gone"}


async def test_every_record_reads_back_as_the_previous_release_read_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: nothing dropped, and every unbound read as it was."""
    head = await _read_back(legacy)

    assert _label(legacy) == CONVERSATION_RECORD_FORMAT
    assert head == json.loads(_READ_BACK.read_text())


async def test_the_upgrade_writes_each_deletions_home_and_moves_nothing_else(
    legacy: Path,
) -> None:
    """ADR-0389 §3:3, ADR-0326 §4:4: the change stream gains the columns, set on deletions.

    A deletion whose conversation's row stands is given that row's home, the owner's
    and the shared things' alike; one whose row is gone, the owner's domain, the shared
    things' ``conv-dropped`` included. No other change row gains one; the label row
    moves; no other table changes.
    """
    before = _tables(legacy)
    _open(legacy).close()
    after = _tables(legacy)

    assert set(after) == set(before)
    for name, (columns, rows) in before.items():
        if name in {"chat_changes", "episode_record_format"}:
            continue
        assert after[name] == (columns, rows), name
    columns, rows = before["chat_changes"]
    kind, conversation = columns.index("kind"), columns.index("conversation_id")
    homes = {"conv-shared-gone": _SHARED}
    assert after["chat_changes"] == (
        (*columns, *_HOME_COLUMNS),
        [
            (
                *row,
                *(
                    homes.get(row[conversation], _OWNERS)
                    if row[kind] == "conversation_deleted"
                    else (None, None)
                ),
            )
            for row in rows
        ],
    )
    assert after["episode_record_format"] == (("version",), [(CONVERSATION_RECORD_FORMAT,)])


@pytest.mark.parametrize("mode", list(SightMode))
async def test_each_deletion_is_read_by_the_home_the_upgrade_gave_it(
    legacy: Path, mode: SightMode
) -> None:
    """ADR-0389 §3:2, §7: the first two by their conversations' homes, the dropped ones as
    the owner's, for the owner's sight in either build and for every other withholding.
    """
    store = _open(legacy, mode)
    try:
        sights = {**_OWNERS_ACTS, **SIGHTS}
        for name, sight in sights.items():
            withholds = mode is SightMode.WITHHOLD or name in _OWNERS_ACTS
            expected = {
                one for one, home in _DELETION_HOMES.items() if not withholds or sight.sees(home)
            }
            assert await _deleted(store.bound(sight)) == expected, name
        assert await _deleted(store.bound(_OWNERS_ACTS["from-the-shared-things"])) == {
            "conv-shared-gone"
        }
    finally:
        store.close()


async def test_a_deletion_with_no_home_is_held_by_no_bound_store(legacy: Path) -> None:
    """ADR-0389 §3:4, ADR-0383 §5:3: a deletion left with no home is no one's.

    After the upgrade, one deletion's home is cleared out of band; the unbound store gives
    it back as before, and no bound store does, the owner's sight from none included.
    """
    _open(legacy).close()
    with sqlite3.connect(legacy) as conn:
        conn.execute(
            "UPDATE chat_changes SET home_kind = NULL, home_id = NULL "
            "WHERE kind = 'conversation_deleted' AND conversation_id = 'conv-owners-gone'"
        )
    store = _open(legacy, SightMode.WITHHOLD)
    try:
        assert "conv-owners-gone" in await _deleted(store)
        for name, sight in {**_OWNERS_ACTS, **SIGHTS}.items():
            assert "conv-owners-gone" not in await _deleted(store.bound(sight)), name
        assert await _deleted(store.bound(_OWNERS_ACTS["from-none"])) == {
            "conv-idle",
            "conv-dropped",
            "conv-shared-gone",
        }
    finally:
        store.close()


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """ADR-0326 §4:3: the upgrade ran once, and the upgraded file is opened as it stands."""
    _open(legacy).close()
    once = _tables(legacy)
    _open(legacy).close()

    assert _tables(legacy) == once


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 15, so it refuses the file at 16."""
    _open(legacy).close()

    with pytest.raises(IncompatibleStateError):
        inspect_existing(
            str(legacy), accepted=CONVERSATION_RECORD_FORMATS - {CONVERSATION_RECORD_FORMAT}
        )


def test_a_fresh_store_is_written_at_the_new_label_with_the_columns(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade, and has both columns."""
    path = tmp_path / "conversations.db"
    _open(path).close()

    assert _label(path) == CONVERSATION_RECORD_FORMAT
    columns, _ = _tables(path)["chat_changes"]
    assert set(_HOME_COLUMNS) <= set(columns)


async def test_a_deletion_written_by_this_build_carries_its_home(tmp_path: Path) -> None:
    """ADR-0389 §3:1: a stamp writes the conversation's home on the deletion's own row.

    The reclaim's is the shared suite's, read through every sight after the drop.
    """
    path = tmp_path / "conversations.db"
    store = _open(path)
    try:
        shared = await store.start(home=RecordHome.shared())
        assert await store.stamp_deleted(shared.id) is True
    finally:
        store.close()
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT kind, home_kind, home_id FROM chat_changes ORDER BY seq"
        ).fetchall()
    assert rows == [("conversation_deleted", *_SHARED)]
