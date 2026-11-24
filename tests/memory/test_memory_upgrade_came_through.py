"""ADR-0326 §4:2's test, for ADR-0378 §7:1's record: a memory file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0378.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``cf43988d8``, at the label ``26``), never by
hand-built SQL, with an eight-dimension hashing embedder and invented data: that build
opened a copy of ``memory-before-adr-0374.db``, upgrading it in place to 26, so it holds
hub chat episodes whose triggers record their senders and no messages, a line episode
with a hub chat input joined to it, an **open** episode, a bare episode with no
processing record, and a memory.

No message that build wrote records a device, and no trigger ``message_devices``, which
every trigger this build writes does: a build at 26 would fail on the read, which is why
the label moves (ADR-0326 §2:3, §5:3). The head opens a copy and upgrades it in place by
the label alone: never refuse it (§5:1), drop nothing (§4:4), rewrite no row, and read
each stored message as one recording neither device, which is a message that came
through the device it is written from (ADR-0378 §8:2). The previous release, which
serves 12 to 26, refuses the upgraded file (§5:3).
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
from ai_assistant.core.types import (
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryRecord,
    RecordedMessageDevices,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    CHECKED_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0378.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 24, 19, 0, tzinfo=UTC)

#: A hub chat episode, and the line episode a hub chat input joined.
_CHAT: Final = "mem-chat"
_LINE: Final = "mem-line"


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int, str | None, int]]:
    """Every row's kind, stored blob, revision, band and openness, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision), band, int(is_open))
            for record_id, kind, data, revision, band, is_open in conn.execute(
                "SELECT id, kind, data, revision, band, is_open FROM records"
            )
        }


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


def _stored_messages(stored: str) -> list[dict[str, object]]:
    """Every message a stored episode's trigger and joined inputs record, out of band."""
    processing = json.loads(stored).get("processing_record") or {}
    trigger = processing.get("trigger") or {}
    joined = processing.get("joined") or []
    return [*trigger.get("messages", []), *(m for one in joined for m in one["messages"])]


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


def _processing(record: MemoryRecord | None) -> EpisodeProcessingRecord:
    assert isinstance(record, EpisodicMemory)
    assert record.processing_record is not None
    return record.processing_record


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
    """The file is at the previous label, holds hub chat inputs, and records no device."""
    assert _label(_FIXTURE) == CHECKED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert {_CHAT, _LINE} <= set(rows)
    messages = [one for row in rows.values() for one in _stored_messages(row[1])]
    assert messages
    assert not any("device_id" in one or "came_through" in one for one in messages)
    assert not any("message_devices" in row[1] for row in rows.values())
    line = json.loads(rows[_LINE][1])["processing_record"]
    assert [one["channel"]["channel_type"] for one in line["joined"]] == [
        "telegram",
        "conversation",
    ]


async def test_every_record_reopens_whole_with_no_device_recorded(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4; ADR-0378 §8:2: every record reads back as it was stored, and
    every message as having come through the device it is written from."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == set(before)
    for record_id, row in before.items():
        stored = json.loads(row[1])
        stored.pop("revision", None)
        _holds(exported[record_id].model_dump(mode="json", exclude={"revision"}), stored)
    for record in exported.values():
        if not isinstance(record, EpisodicMemory) or record.processing_record is None:
            continue
        processing = record.processing_record
        assert processing.trigger.message_devices == ()
        held = (
            *processing.trigger.messages,
            *(m for one in processing.joined for m in one.messages),
        )
        assert all(one.device_id is None and one.came_through is None for one in held)


async def test_the_upgrade_moves_the_label_alone(legacy: Path) -> None:
    """ADR-0326 §4:4: no row is rewritten; every one is byte for byte what it was."""
    before = _raw_rows(legacy)

    await _exported(legacy)

    assert _raw_rows(legacy) == before
    assert _label(legacy) == MEMORY_RECORD_FORMAT


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
    """ADR-0326 §5:3: the previous release opens 12 to 26, so it refuses the file at 27."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})


async def test_a_hub_chat_inputs_devices_are_stored_and_read_back(legacy: Path) -> None:
    """ADR-0378 §7:1: the two devices are kept on the trigger and on a joined message,
    whole, across a reopen."""
    exported = await _exported(legacy)
    chat, line = exported[_CHAT], exported[_LINE]
    assert isinstance(chat, EpisodicMemory)
    assert isinstance(line, EpisodicMemory)
    devices = (
        RecordedMessageDevices(position=1, device_id="web-leo", came_through="hub"),
        RecordedMessageDevices(position=2, device_id="hub", came_through="hub"),
    )
    chat_processing = _processing(chat)
    written_chat = chat.model_copy(
        update={
            "id": "mem-chat-through",
            "processing_record": chat_processing.model_copy(
                update={
                    "activation_id": "3b0e8a5e-2a64-4c1f-9b36-0c7d1d2f8e51",
                    "trigger": chat_processing.trigger.model_copy(
                        update={"message_devices": devices}
                    ),
                }
            ),
        }
    )
    line_processing = _processing(line)
    telegram, from_chat = line_processing.joined
    named = tuple(
        one.model_copy(update={"device_id": "web-leo", "came_through": "gateway-1"})
        for one in from_chat.messages
    )
    written_line = line.model_copy(
        update={
            "id": "mem-line-through",
            "processing_record": line_processing.model_copy(
                update={
                    "activation_id": "9d5f7c1a-4e2b-4a8f-8c3d-6b1e0f2a7d94",
                    "joined": (telegram, from_chat.model_copy(update={"messages": named})),
                }
            ),
        }
    )
    store = _open(legacy)
    try:
        for one in (written_chat, written_line):
            await store.add(EpisodicMemory.model_validate_json(one.model_dump_json()))
    finally:
        store.close()

    again = await _exported(legacy)
    assert _processing(again["mem-chat-through"]).trigger.message_devices == devices
    joined = _processing(again["mem-line-through"]).joined
    assert [(one.device_id, one.came_through) for one in joined[1].messages] == [
        ("web-leo", "gateway-1")
    ] * len(named)
    assert all(one.device_id is None for one in joined[0].messages)
