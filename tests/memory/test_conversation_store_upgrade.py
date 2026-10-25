"""ADR-0326 §4:2's test, for ADR-0350 §12:9: a conversation file the previous release wrote.

``tests/memory/legacy/conversations-before-adr-0350.db`` was written by the previous
release's own ``SqliteConversationStore`` (the build at ``03273b882``, through its
public members, at the label ``12``), never by hand-built SQL. It holds "my devices"
(the phone); ``conv-kept``, on the phone and the laptop, with a recorded turn, a user's
message, an assistant's question with two options, the user's reply to it, an
assistant's cut-off message the user deleted, and the reader's bookkeeping of the two
user's messages; ``conv-quiet``, holding an assistant's message alone; and
``conv-deleted``, stamped deleted with the user's message it held.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
add the ``effect_id`` column, drop nothing and change no stored byte of a row (§4:4),
and read every record back as it was. Every message the file holds carries no claim; a
claimed message then round-trips through the upgraded file, and the previous release,
which serves 12 alone, refuses it (§5:3).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    ChatDevice,
    DeletedMessage,
    DeviceAccess,
    MessageAuthor,
    MessageDeletedChange,
    NewMessage,
    SendOutcome,
    TranscriptMessage,
)
from ai_assistant.memory._episode_format import (
    CONVERSATION_RECORD_FORMAT,
    EPISODE_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "conversations-before-adr-0350.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 25, 21, tzinfo=UTC)

_PHONE = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_LAPTOP = ChatDevice(device_id="laptop", access=DeviceAccess.READ)

#: Every table the previous release kept, with what identifies a row in it.
_TABLES = {
    "conversations": "id",
    "messages": "conversation_id, position",
    "chat_devices": "device_id",
    "conversation_devices": "conversation_id, device_id",
    "chat_changes": "seq",
    "taken_in": "conversation_id, position",
}


def _rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table the previous release kept, read out of band.

    Each table's columns are the ones the previous release wrote, so a column the
    upgrade adds is not among them.
    """
    with sqlite3.connect(path) as conn:
        held: dict[str, list[tuple[Any, ...]]] = {}
        for table, key in _TABLES.items():
            columns = [
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})")
                if row[1] != "effect_id"
            ]
            held[table] = conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY {key}"  # noqa: S608 — names read from the file's own schema
            ).fetchall()
        return held


def _columns(path: Path, table: str) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


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
    """The file is at the previous label, and its messages have no claim column."""
    assert _label(_FIXTURE) == EPISODE_RECORD_FORMAT
    assert "effect_id" not in _columns(_FIXTURE, "messages")
    rows = _rows(_FIXTURE)
    assert [row[0] for row in rows["conversations"]] == ["conv-deleted", "conv-kept", "conv-quiet"]
    assert len(rows["messages"]) == 5


async def test_the_file_is_upgraded_in_place(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4: the column is added, the label advances, no row's byte moves.

    Every message the file held carries no claim, since no build before this one
    recorded one.
    """
    before = _rows(legacy)

    _open(legacy).close()

    assert _label(legacy) == CONVERSATION_RECORD_FORMAT
    assert _columns(legacy, "messages")[-1] == "effect_id"
    assert _rows(legacy) == before
    with sqlite3.connect(legacy) as conn:
        claims = conn.execute("SELECT effect_id FROM messages").fetchall()
    assert claims == [(None,)] * 5


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record the file holds is read back whole, through the seam."""
    store = _open(legacy)
    try:
        exported = await store.export()
        kept = await store.transcript("conv-kept")
        quiet = await store.transcript("conv-quiet")
        devices = await store.conversation_devices("conv-kept")
        mine = await store.my_devices()
        taken = await store.taken_in("conv-kept", positions=[1, 2, 3, 4])
        stamped = await store.stamped_conversation_ids()
        changes = await store.changes(after=0)
    finally:
        store.close()

    assert [one.id for one in exported.conversations] == ["conv-quiet", "conv-kept"]
    kept_row = exported.conversations[1]
    assert kept_row.last_turn_at is not None
    assert [(one.conversation_id, one.position, one.effect_id) for one in exported.messages] == [
        ("conv-quiet", 1, None),
        ("conv-kept", 1, None),
        ("conv-kept", 2, None),
        ("conv-kept", 3, None),
    ]
    assert kept is not None
    assert quiet is not None
    first, question, reply, deleted = kept.entries
    assert isinstance(first, TranscriptMessage)
    assert (first.author, first.text, first.device_id, first.message_id) == (
        MessageAuthor.USER,
        "When is the dentist?",
        "phone",
        "phone-msg-1",
    )
    assert isinstance(question, TranscriptMessage)
    assert (question.author, question.text, question.replies_to, question.options) == (
        MessageAuthor.ASSISTANT,
        "Thursday at nine.",
        1,
        ("Thanks", "Move it"),
    )
    assert isinstance(reply, TranscriptMessage)
    assert (reply.text, reply.replies_to, reply.message_id) == ("Thanks", 2, "phone-msg-2")
    assert deleted == DeletedMessage(conversation_id="conv-kept", position=4)
    (said,) = quiet.entries
    assert isinstance(said, TranscriptMessage)
    assert (said.author, said.text) == (MessageAuthor.ASSISTANT, "Your parcel arrived.")
    assert [one.model_dump() for one in exported.messages] == [
        {**one.model_dump(), "effect_id": None} for one in (said, first, question, reply)
    ]
    assert devices == (_LAPTOP, _PHONE)
    assert mine == (_PHONE,)
    assert taken == {1: "act-upgrade-1", 3: "act-upgrade-1"}
    assert stamped == ["conv-deleted"]
    assert [one.kind for one in changes.changes] == [
        "devices_changed",
        "conversation_started",
        "devices_changed",
        "message_added",
        "message_added",
        "message_added",
        "message_deleted",
        "conversation_started",
        "message_added",
        "conversation_deleted",
    ]
    assert any(isinstance(one, MessageDeletedChange) for one in changes.changes)


async def test_the_messages_it_held_answer_for_no_claim(legacy: Path) -> None:
    """ADR-0350 §12:9: no message written before the column was claimed under anything."""
    store = _open(legacy)
    try:
        for position in (1, 2, 3, 4):
            assert await store.effect_position("conv-kept", f"effect-{position}") is None
        assert await store.effect_position("conv-quiet", "effect-1") is None
    finally:
        store.close()


async def test_a_claimed_message_round_trips_through_the_upgraded_file(legacy: Path) -> None:
    """ADR-0350 §12:9: a message written under a claim is answered for, and repeated not.

    Its position follows the file's own, the deleted message's included, which is never
    reused (ADR-0293 §5:12).
    """
    store = _open(legacy)
    try:
        claimed = NewMessage(
            author=MessageAuthor.ASSISTANT, text="Time to call Mom.", effect_id="e-1"
        )
        written = await store.append_message("conv-kept", claimed)
        again = await store.append_message("conv-kept", claimed)
    finally:
        store.close()

    assert (written.outcome, written.position) == (SendOutcome.RECORDED, 5)
    assert (again.outcome, again.position) == (SendOutcome.REPEATED, 5)
    reopened = _open(legacy)
    try:
        assert await reopened.effect_position("conv-kept", "e-1") == 5
        exported = await reopened.export()
    finally:
        reopened.close()
    assert [(one.position, one.effect_id) for one in exported.messages if one.position == 5] == [
        (5, "e-1")
    ]


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    _open(legacy).close()
    once = (_label(legacy), _columns(legacy, "messages"), _rows(legacy))

    _open(legacy).close()

    assert (_label(legacy), _columns(legacy, "messages"), _rows(legacy)) == once


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade, and has the column."""
    path = tmp_path / "conversations.db"
    _open(path).close()
    assert _label(path) == CONVERSATION_RECORD_FORMAT
    assert "effect_id" in _columns(path, "messages")


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 alone, so it refuses the file at 13."""
    _open(legacy).close()

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=frozenset({EPISODE_RECORD_FORMAT}))
