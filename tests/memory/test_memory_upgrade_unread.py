"""ADR-0326 §4:2's test, for ADR-0374 §5:1's mark: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0374.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``d48cc1e3c``, at the label ``24``), never by
hand-built SQL, with an eight-dimension hashing embedder and invented data: that build
opened a copy of ``memory-before-adr-0368.db``, upgrading it in place to 24, so every
episode with a processing record holds who sent each input and the work's facts as that
build wrote them, and then stored, through its public ``add``, two more hub chat
episodes: one from an account no link ties, at none, and one from the owner's link
lowered to weak. Beside them, as in the earlier file, an **open** episode, a bare episode
with no processing record, and a memory.

No sender that build wrote holds ``links_unread``, and every one this build writes does:
a build at 24 would fail on the read, which is why the label moves (ADR-0326 §2:3,
§5:3), though 24 was never deployed (it is a release's, §2:4). The head opens a copy and
upgrades it in place by the label alone: never refuse it (§5:1), drop nothing (§4:4),
rewrite no row, and read each stored sender as one whose links were read (ADR-0374 §7).
The previous release, which serves 12 to 24, refuses the upgraded file (§5:3).
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
    OWNER_PERSON_ID,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputSender,
    MemoryRecord,
    Sureness,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    FACTS_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0374.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)

#: The episodes with a processing record, each recording who sent it at 24.
_WITH_SENDERS: Final = (
    "mem-chat",
    "mem-line",
    "mem-event",
    "mem-task",
    "mem-approval",
    "mem-open",
    "mem-unlinked",
    "mem-lowered",
)

#: Every row the file holds.
_ROWS: Final = (*_WITH_SENDERS, "mem-bare", "mem-said")

_OPEN: Final = "mem-open"


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


def _mentions(stored: object, key: str) -> bool:
    """Whether any dict inside ``stored`` holds ``key``."""
    if isinstance(stored, dict):
        return key in stored or any(_mentions(one, key) for one in stored.values())
    if isinstance(stored, list):
        return any(_mentions(one, key) for one in stored)
    return False


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


def _every_sender(processing: EpisodeProcessingRecord) -> list[InputSender]:
    """Every sender the record holds: its trigger's, each message's, each join's."""
    held = list(processing.trigger.senders)
    held.extend(one.sender for one in processing.trigger.messages if one.sender is not None)
    for joined in processing.joined:
        held.extend(one.sender for one in joined.messages if one.sender is not None)
    return held


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, one episode is open, every episode with a
    processing record holds its senders, and none holds the mark."""
    assert _label(_FIXTURE) == FACTS_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == set(_ROWS)
    assert [record_id for record_id, row in rows.items() if row[4]] == [_OPEN]
    for record_id, row in rows.items():
        stored = json.loads(row[1])
        assert not _mentions(stored, "links_unread"), record_id
        if record_id in _WITH_SENDERS:
            assert _mentions(stored, "senders"), record_id


async def test_every_record_reopens_whole_and_no_sender_is_marked(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4; ADR-0374 §7: every record reads back as it was stored, and
    every sender reads as one whose links were read."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == set(before)
    for record_id in _WITH_SENDERS:
        senders = _every_sender(_processing(exported[record_id]))
        assert not any(one.links_unread for one in senders), record_id
        stored = json.loads(before[record_id][1])
        stored.pop("revision", None)
        read = exported[record_id].model_dump(mode="json", exclude={"revision"})
        _holds(read, stored)

    assert _processing(exported["mem-chat"]).trigger.senders == (
        InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL),
    )
    assert _processing(exported["mem-unlinked"]).trigger.senders == (
        InputSender(person=None, level=Sureness.NONE),
    )
    assert _processing(exported["mem-lowered"]).trigger.senders == (
        InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK),
    )
    line = _processing(exported["mem-line"])
    assert len(line.trigger.messages) == 2
    assert len(line.joined) == 2
    assert _processing(exported[_OPEN]).is_open


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
    """ADR-0326 §5:3: the previous release opens 12 to 24, so it refuses the file at 25."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})


async def test_a_marked_sender_is_stored_and_read_back(legacy: Path) -> None:
    """ADR-0374 §5:1: the mark is fixed on the episode with the sender, so a record this
    build writes keeps it across a reopen."""
    exported = await _exported(legacy)
    chat = exported["mem-unlinked"]
    assert isinstance(chat, EpisodicMemory)
    processing = _processing(chat)
    marked = InputSender(person=None, level=Sureness.NONE, links_unread=True)
    written = chat.model_copy(
        update={
            "id": "mem-marked",
            "processing_record": processing.model_copy(
                update={
                    "activation_id": "4f1c1a52-9a5e-4a8e-9a43-6b0a4f1d2e03",
                    "trigger": processing.trigger.model_copy(update={"senders": (marked,)}),
                }
            ),
        }
    )
    store = _open(legacy)
    try:
        await store.add(EpisodicMemory.model_validate_json(written.model_dump_json()))
    finally:
        store.close()

    again = await _exported(legacy)
    assert _processing(again["mem-marked"]).trigger.senders == (marked,)
