"""ADR-0326 §4:2's test, for ADR-0378 §8:2: a conversation file the previous release wrote.

``tests/memory/legacy/conversations-before-adr-0378.db`` was written by the previous
release's own ``SqliteConversationStore`` (the build at ``cf43988d8``, at the label
``13``), never by hand-built SQL: that build opened a copy of
``conversations-before-adr-0350.db``, upgrading it in place to 13, and then wrote, through
its public ``append_message``, one more user's message from the phone into ``conv-kept``.
So ``conv-kept`` holds three standing user's messages from the phone, an assistant's
question and a deleted message's marker; ``conv-quiet`` an assistant's message alone.

No message that build wrote records the device it came through. The head opens a copy
and upgrades it in place: never refuse it (ADR-0326 §5:1), add the ``came_through``
column, set it on each standing user's message to the device it is written from (ADR-0378
§8:2), change no other stored byte (§4:4), and read every record back. A message written
through another device then round-trips, and the previous release, which serves 12 and 13,
refuses the upgraded file (§5:3).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    DeletedMessage,
    MessageAuthor,
    NewMessage,
    SendOutcome,
    TranscriptMessage,
)
from ai_assistant.memory._episode_format import (
    CLAIMED_CONVERSATION_RECORD_FORMAT,
    CONVERSATION_RECORD_FORMAT,
    CONVERSATION_RECORD_FORMATS,
    inspect_existing,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "conversations-before-adr-0378.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 24, 19, tzinfo=UTC)

#: Every table the previous release kept, with what identifies a row in it.
_TABLES: Final = {
    "conversations": "id",
    "messages": "conversation_id, position",
    "chat_devices": "device_id",
    "conversation_devices": "conversation_id, device_id",
    "chat_changes": "seq",
    "taken_in": "conversation_id, position",
}


def _rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, by the columns the previous release wrote."""
    with sqlite3.connect(path) as conn:
        held: dict[str, list[tuple[Any, ...]]] = {}
        for table, key in _TABLES.items():
            columns = [
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})")
                if row[1] != "came_through"
            ]
            held[table] = conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY {key}"  # noqa: S608 — names read from the file's own schema
            ).fetchall()
        return held


def _columns(path: Path, table: str) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def _came_through(path: Path) -> list[tuple[str, int, str | None, str | None]]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT conversation_id, position, device_id, came_through FROM messages "
            "ORDER BY conversation_id, position"
        ).fetchall()


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "conversations.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path) -> SqliteConversationStore:
    return SqliteConversationStore(path=path, now=lambda: _NOW)


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, and its messages have no column for the device."""
    assert _label(_FIXTURE) == CLAIMED_CONVERSATION_RECORD_FORMAT
    assert "came_through" not in _columns(_FIXTURE, "messages")
    assert "effect_id" in _columns(_FIXTURE, "messages")
    messages = _rows(_FIXTURE)["messages"]
    assert len(messages) == 6


async def test_the_file_is_upgraded_in_place(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4; ADR-0378 §8:2: the column is added and set, nothing else moves.

    Each standing user's message came through the device it is written from; the
    assistant's message and the deleted message's marker carry none.
    """
    before = _rows(legacy)

    _open(legacy).close()

    assert _label(legacy) == CONVERSATION_RECORD_FORMAT
    assert "came_through" in _columns(legacy, "messages")
    assert _rows(legacy) == before
    assert _came_through(legacy) == [
        ("conv-kept", 1, "phone", "phone"),
        ("conv-kept", 2, None, None),
        ("conv-kept", 3, "phone", "phone"),
        ("conv-kept", 4, None, None),
        ("conv-kept", 5, "phone", "phone"),
        ("conv-quiet", 1, None, None),
    ]


async def test_every_record_reads_back_as_having_come_through_itself(legacy: Path) -> None:
    """ADR-0326 §4:2, ADR-0378 §8:2: every message is read back, a user's as having come
    through the device it is written from, on every read."""
    store = _open(legacy)
    try:
        exported = await store.export()
        kept = await store.transcript("conv-kept")
        quiet = await store.transcript("conv-quiet")
        changes = await store.changes(after=0)
        waiting = await store.untaken_messages("conv-kept")
    finally:
        store.close()

    assert kept is not None
    assert quiet is not None
    first, question, reply, deleted, later = kept.entries
    assert isinstance(first, TranscriptMessage)
    assert isinstance(question, TranscriptMessage)
    assert isinstance(reply, TranscriptMessage)
    assert isinstance(later, TranscriptMessage)
    assert deleted == DeletedMessage(conversation_id="conv-kept", position=4)
    assert [(one.author, one.device_id, one.came_through) for one in (first, reply, later)] == [
        (MessageAuthor.USER, "phone", "phone")
    ] * 3
    assert later.text == "And the week after?"
    assert question.came_through is None
    (said,) = quiet.entries
    assert isinstance(said, TranscriptMessage)
    assert said.came_through is None
    assert [(one.position, one.came_through) for one in exported.messages] == [
        (1, None),
        (1, "phone"),
        (2, None),
        (3, "phone"),
        (5, "phone"),
    ]
    added = [one.message for one in changes.changes if one.kind == "message_added"]
    assert {(one.conversation_id, one.position, one.came_through) for one in added} == {
        ("conv-kept", 1, "phone"),
        ("conv-kept", 2, None),
        ("conv-kept", 3, "phone"),
        ("conv-kept", 5, "phone"),
        ("conv-quiet", 1, None),
    }
    assert [(one.position, one.came_through) for one in waiting] == [(5, "phone")]


async def test_a_message_through_another_device_round_trips(legacy: Path) -> None:
    """ADR-0378 §4:2: a message written through a gateway keeps it, across a reopen."""
    store = _open(legacy)
    try:
        written = await store.append_message(
            "conv-kept",
            NewMessage(
                author=MessageAuthor.USER,
                text="From the browser.",
                device_id="phone",
                message_id="phone-msg-4",
                came_through="gateway-1",
            ),
        )
    finally:
        store.close()

    assert (written.outcome, written.position) == (SendOutcome.RECORDED, 6)
    reopened = _open(legacy)
    try:
        page = await reopened.transcript("conv-kept")
    finally:
        reopened.close()
    assert page is not None
    last = page.entries[-1]
    assert isinstance(last, TranscriptMessage)
    assert (last.device_id, last.came_through) == ("phone", "gateway-1")


async def test_a_deleted_messages_marker_keeps_no_device_it_came_through(legacy: Path) -> None:
    """ADR-0293 §5:12: the marker keeps the ids alone, so the device it came through goes."""
    store = _open(legacy)
    try:
        assert await store.delete_message("conv-kept", 1) is True
    finally:
        store.close()

    assert _came_through(legacy)[0] == ("conv-kept", 1, "phone", None)


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    _open(legacy).close()
    once = (_label(legacy), _columns(legacy, "messages"), _rows(legacy), _came_through(legacy))

    _open(legacy).close()

    assert (
        _label(legacy),
        _columns(legacy, "messages"),
        _rows(legacy),
        _came_through(legacy),
    ) == once


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade, and has the column."""
    path = tmp_path / "conversations.db"
    _open(path).close()
    assert _label(path) == CONVERSATION_RECORD_FORMAT
    assert "came_through" in _columns(path, "messages")


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 and 13, so it refuses the file at 14."""
    _open(legacy).close()

    with pytest.raises(IncompatibleStateError):
        inspect_existing(
            str(legacy), accepted=CONVERSATION_RECORD_FORMATS - {CONVERSATION_RECORD_FORMAT}
        )
