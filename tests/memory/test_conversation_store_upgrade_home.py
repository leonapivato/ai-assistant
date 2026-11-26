"""ADR-0326 §4:2's test, for ADR-0383 §5:1's home: a conversation file the previous release wrote.

``tests/memory/legacy/conversations-before-adr-0383.db`` was written by the previous
release's own ``SqliteConversationStore`` (the build at ``6de223e7a``, at the label
``14``), through its public API and never by hand-built SQL, with invented data: "my
devices" a phone and a watch; ``conv-kept``, where the phone asked about the lake, the
assistant asked back with two options, the phone answered through a gateway, the
assistant answered under a claim, the phone wrote a message it then deleted, the
assistant wrote a message cut short under a second claim, and the phone asked again, the
first and third taken in by an activation and a turn recorded; ``conv-quiet``, an
assistant's message alone, its devices then set to the watch; ``conv-empty``, never
written into; and ``conv-gone``, a message and then the conversation's deletion.
Beside it, ``conversations-before-adr-0383.json`` is what that build read back from the
file through every read the store answers, written by that code too.

No conversation and no message that build wrote holds a home, which every one this
build writes does (ADR-0386 §4:1, §4:2), so the label moves. The head opens a copy and
upgrades it in place: never refuse it (ADR-0326 §5:1), drop nothing (§4:4), read back
every record as that release did, and write the owner's domain into every conversation
and every message the file holds, the deleted message's marker and the deleted
conversation's tombstone included, whoever the works that wrote them were for (ADR-0383
§5:1), moving no other byte. No device row or bookkeeping row gains a home (§3), and of
the change stream a conversation's deletion alone, by the next label's upgrade, chained
after this one (ADR-0389 §3:3, ADR-0326 §4:5).
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
    MessageAuthor,
    NewMessage,
    RecordHome,
    SendOutcome,
    TranscriptMessage,
)
from ai_assistant.memory._episode_format import (
    CAME_THROUGH_CONVERSATION_RECORD_FORMAT,
    CONVERSATION_RECORD_FORMAT,
    CONVERSATION_RECORD_FORMATS,
    HOMED_CONVERSATION_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "conversations-before-adr-0383.db"
_READ_BACK: Final = _LEGACY / "conversations-before-adr-0383.json"

#: The instant the head opens the file at: an hour after the previous release wrote it,
#: the instant that release read it back at.
_NOW: Final = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

_CONVERSATIONS: Final = ("conv-kept", "conv-quiet", "conv-empty", "conv-gone")

#: The columns the upgrade adds to the conversations' and the messages' rows, and to no
#: other table's.
_HOME_COLUMNS: Final = ("home_kind", "home_id")
_HOMED: Final = ("conversations", "messages")
_OWNERS: Final = (RecordHome.owners().kind.value, RecordHome.owners().id)
_OWNERS_JSON: Final = RecordHome.owners().model_dump(mode="json")


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


def _open(path: Path) -> SqliteConversationStore:
    return SqliteConversationStore(path=path, now=lambda: _NOW, new_id=lambda: "head-1")


def _homeless(value: Any) -> Any:
    """``value`` with each conversation's and each message's home taken out, each held to
    be the owner's.

    The previous release's read-back has no home on any conversation or message: the
    head's adds it (ADR-0383 §5:1), and every other byte must read back the same. A
    conversation is told by its ``started_at``, a message by its ``written_at``.
    """
    if isinstance(value, dict):
        if "started_at" in value or "written_at" in value:
            assert value.get("home") == _OWNERS_JSON, value
            value = {key: one for key, one in value.items() if key != "home"}
        return {key: _homeless(one) for key, one in value.items()}
    if isinstance(value, list):
        return [_homeless(one) for one in value]
    return value


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
            held[f"taken_in/{one}"] = _json(
                await store.taken_in(one, positions=(1, 2, 3, 4, 5, 6, 7))
            )
        held["effect/effect-1"] = await store.effect_position("conv-kept", "effect-1")
        held["effect/effect-2"] = await store.effect_position("conv-kept", "effect-2")
        for device in ("phone", "watch"):
            held[f"device_changes/{device}"] = _json(await store.device_changes(device, after=0))
            held[f"device_conversations/{device}"] = _json(await store.device_conversations(device))
    finally:
        store.close()
    return held


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file is at the previous label, and no conversation or message in it holds a home."""
    assert _label(_FIXTURE) == CAME_THROUGH_CONVERSATION_RECORD_FORMAT
    tables = _tables(_FIXTURE)
    for name in _HOMED:
        columns, _ = tables[name]
        assert not set(_HOME_COLUMNS) & set(columns), name
    assert sorted(row[0] for row in tables["conversations"][1]) == sorted(_CONVERSATIONS)
    assert len(tables["messages"][1]) == 8


async def test_every_record_reads_back_as_the_previous_release_read_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: nothing dropped, and every conversation and message the owner's."""
    head = await _read_back(legacy)

    assert _label(legacy) == CONVERSATION_RECORD_FORMAT
    # The export's label moves with its shape (ADR-0039 §10): 7 then, 8 for the home.
    exported = head["export"]
    assert isinstance(exported, dict)
    assert exported["schema_version"] == 8
    head["export"] = {**exported, "schema_version": 7}
    assert _homeless(head) == json.loads(_READ_BACK.read_text())


async def test_the_upgrade_writes_the_home_and_moves_nothing_else(legacy: Path) -> None:
    """ADR-0326 §4:4, ADR-0383 §5:1: only the conversations' and the messages' rows change.

    Each gains the owner's domain, the deleted conversation's tombstone and the deleted
    message's marker included; the label row moves. The next label's upgrade, chained
    after this one, gives the change stream the two columns and the deletion of
    ``conv-gone``, whose row stands, that row's home, the owner's (ADR-0389 §3:3);
    nothing else moves.
    """
    before = _tables(legacy)
    _open(legacy).close()
    after = _tables(legacy)

    assert set(after) == set(before)
    for name, (columns, rows) in before.items():
        if name in {*_HOMED, "chat_changes", "episode_record_format"}:
            continue
        assert after[name] == (columns, rows), name
    for name in _HOMED:
        columns, rows = before[name]
        assert after[name] == ((*columns, *_HOME_COLUMNS), [(*row, *_OWNERS) for row in rows])
    columns, rows = before["chat_changes"]
    kind = columns.index("kind")
    assert any(row[kind] == "conversation_deleted" for row in rows)
    assert after["chat_changes"] == (
        (*columns, *_HOME_COLUMNS),
        [
            (*row, *(_OWNERS if row[kind] == "conversation_deleted" else (None, None)))
            for row in rows
        ],
    )
    assert after["episode_record_format"] == (("version",), [(CONVERSATION_RECORD_FORMAT,)])


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """ADR-0326 §4:3: the upgrade ran once, and the upgraded file is opened as it stands."""
    _open(legacy).close()
    once = _tables(legacy)
    _open(legacy).close()

    assert _tables(legacy) == once


async def test_writes_after_the_upgrade_carry_their_homes(legacy: Path) -> None:
    """ADR-0386 §4: a conversation started and a message written carry the home each was given.

    Across a reopen, so it is the file's, not the connection's.
    """
    store = _open(legacy)
    try:
        started = await store.start(home=RecordHome.shared())
        written = await store.append_message(
            "conv-quiet",
            NewMessage(
                author=MessageAuthor.ASSISTANT, text="Still here.", home=RecordHome.shared()
            ),
        )
    finally:
        store.close()
    assert started.id == "head-1"
    assert (written.outcome, written.position) == (SendOutcome.RECORDED, 2)

    reopened = _open(legacy)
    try:
        got = await reopened.get("head-1")
        page = await reopened.transcript("conv-quiet")
        kept = await reopened.get("conv-quiet")
    finally:
        reopened.close()
    assert got is not None
    assert got.home == RecordHome.shared()
    assert kept is not None
    assert kept.home == RecordHome.owners()
    assert page is not None
    assert [
        (one.position, one.home) for one in page.entries if isinstance(one, TranscriptMessage)
    ] == [
        (1, RecordHome.owners()),
        (2, RecordHome.shared()),
    ]


async def test_deleting_a_message_keeps_its_home_with_the_marker(legacy: Path) -> None:
    """ADR-0383 §4:6: a deletion clears every property but the ids and changes no home."""
    store = _open(legacy)
    try:
        assert await store.delete_message("conv-kept", 1) is True
    finally:
        store.close()

    with sqlite3.connect(legacy) as conn:
        row = conn.execute(
            "SELECT deleted, text, home_kind, home_id FROM messages "
            "WHERE conversation_id = 'conv-kept' AND position = 1"
        ).fetchone()
    assert row == (1, None, *_OWNERS)


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 14, so it refuses the upgraded file."""
    _open(legacy).close()

    with pytest.raises(IncompatibleStateError):
        inspect_existing(
            str(legacy),
            accepted=CONVERSATION_RECORD_FORMATS
            - {HOMED_CONVERSATION_RECORD_FORMAT, CONVERSATION_RECORD_FORMAT},
        )


def test_a_fresh_store_is_written_at_the_new_label_with_the_columns(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade, and has both columns."""
    path = tmp_path / "conversations.db"
    _open(path).close()

    assert _label(path) == CONVERSATION_RECORD_FORMAT
    tables = _tables(path)
    for name in _HOMED:
        columns, _ = tables[name]
        assert set(_HOME_COLUMNS) <= set(columns), name
