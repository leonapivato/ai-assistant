"""ADR-0326 §4:2's test, for ADR-0379 §3:2's record of the check: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0379.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``0df2ac27e``, at the label ``25``), never by
hand-built SQL, with an eight-dimension hashing embedder and invented data: that build
opened a copy of ``memory-before-adr-0358.db``, upgrading it in place to 25, so it holds an
ended episode whose call entries are a done look-up, a tidy-up started with no outcome, a
refused spawn and a sent message; an **open** episode, as a hub stopped mid-activation
leaves it, with one done look-up's entry; a bare episode with no processing record; and a
memory.

No entry that build wrote holds ``check``, and every one this build writes does, ``null``
where the check never reached its call: a build at 25 would fail on the read, which is why
the label moves (ADR-0326 §2:3, §5:3). The head opens a copy and upgrades it in place by the
label alone: never refuse it (§5:1), drop nothing (§4:4), rewrite no row, and read each
stored entry as one the check never reached. The previous release, which serves 12 to 25,
refuses the upgraded file (§5:3).
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
    CallCheck,
    CallCheckKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryRecord,
    Sureness,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    UNREAD_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0379.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 24, 19, 0, tzinfo=UTC)

_ENDED: Final = "mem-episode"
_OPEN: Final = "mem-episode-open"
_ROWS: Final = frozenset({_ENDED, _OPEN, "mem-episode-bare", "mem-said"})


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


def _entries(stored: str) -> list[dict[str, object]]:
    """A stored episode's call entries, read out of band."""
    processing = json.loads(stored).get("processing_record") or {}
    return list(processing.get("call_records", []))


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
    """The file is at the previous label, one episode is open, five entries are held, and
    none holds a check."""
    assert _label(_FIXTURE) == UNREAD_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _ROWS
    assert [record_id for record_id, row in rows.items() if row[4]] == [_OPEN]
    entries = [entry for row in rows.values() for entry in _entries(row[1])]
    assert len(entries) == 5
    assert not any("check" in entry for entry in entries)


async def test_every_record_reopens_whole_and_no_entry_is_checked(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: every record reads back as it was stored, and every entry as
    one the check never reached."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == set(before)
    for record_id, row in before.items():
        stored = json.loads(row[1])
        stored.pop("revision", None)
        _holds(exported[record_id].model_dump(mode="json", exclude={"revision"}), stored)
    for record_id in (_ENDED, _OPEN):
        entries = _processing(exported[record_id]).call_records
        assert entries, record_id
        assert all(one.check is None for one in entries), record_id
    assert _processing(exported[_OPEN]).is_open


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
    """ADR-0326 §5:3: the previous release opens 12 to 25, so it refuses the file at 26."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})


async def test_a_checked_entry_is_stored_and_read_back(legacy: Path) -> None:
    """ADR-0379 §3:2: the check's record is kept on the entry, whole, across a reopen."""
    exported = await _exported(legacy)
    ended = exported[_ENDED]
    assert isinstance(ended, EpisodicMemory)
    processing = _processing(ended)
    check = CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=(
            CheckRun(
                checked_for=CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE),
                outcome=CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK),
            ),
            CheckRun(
                checked_for=CheckedFor.anyone(),
                outcome=CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT),
            ),
        ),
    )
    first, *rest = processing.call_records
    written = ended.model_copy(
        update={
            "id": "mem-checked",
            "processing_record": processing.model_copy(
                update={
                    "activation_id": "8e1d3c52-6b2f-4f0e-9d1a-2c7e5b9f0a14",
                    "call_records": (first.model_copy(update={"check": check}), *rest),
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
    held = _processing(again["mem-checked"]).call_records
    assert held[0].check == check
    assert [one.check for one in held[1:]] == [None] * len(rest)
