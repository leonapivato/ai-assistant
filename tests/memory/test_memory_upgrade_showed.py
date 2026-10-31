"""ADR-0326 §4:2's test, for ADR-0358 §11's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0358.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``65ef84a58``, through its public ``add``, at the
label ``22``), never by hand-built SQL, with an eight-dimension hashing embedder and
invented data. It holds an ended episode whose call entries are a done look-up, a tidy-up
started with no outcome, a refused spawn and a sent message; an **open** episode, as a hub
stopped mid-activation leaves it, with one done look-up's entry; a bare episode with no
processing record; and a memory resting on the message call's words.

No entry that build wrote holds ``showed``, and every one this build writes carries it,
``null`` where it keeps nothing: a build at 22 would fail on the read, which is why the
label moves (ADR-0326 §2:3, §5:3). The head opens a copy and must upgrade it in place by
the label alone: never refuse it (§5:1), drop nothing and rewrite nothing (§4:4), and
read every entry back whole with the addition empty (ADR-0358 §11:6, §11:8). The open
episode then takes an entry keeping what its call showed through the upgraded file, and
the previous release, which serves 12 to 22, refuses the file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    CallOutcomeKind,
    CallShowed,
    EpisodeProcessingRecord,
    EpisodicMemory,
    Memory,
    MemoryRecord,
    MessageCallPart,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    ShownRecord,
    ShownRecordKind,
    ShownText,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    CALLED_RECORD_FORMAT,
    CONTINUING_RECORD_FORMAT,
    EPISODE_RECORD_FORMAT,
    JOINED_RECORD_FORMAT,
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    PARTIES_RECORD_FORMAT,
    PINNED_RECORD_FORMAT,
    PLACED_RECORD_FORMAT,
    SCHEDULED_RECORD_FORMAT,
    TAKEN_OVER_RECORD_FORMAT,
    UNDERSTOOD_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0358.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)

_IDS: Final = {"mem-episode", "mem-episode-open", "mem-episode-bare", "mem-said"}

_OPEN: Final = "mem-episode-open"


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


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, its records at version 12, every call's entry
    without the addition, and one episode open."""
    assert _label(_FIXTURE) == CALLED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    entries = 0
    for record_id in ("mem-episode", _OPEN):
        processing = json.loads(rows[record_id][1])["processing_record"]
        assert processing["schema_version"] == 12
        for entry in processing["call_records"]:
            assert "showed" not in entry
            entries += 1
    assert entries == 5
    assert rows[_OPEN][4] == 1


async def test_the_file_is_upgraded_in_place_by_its_label_alone(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4: the label advances and no stored byte of a record moves."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    assert _raw_rows(legacy) == before


async def test_every_entry_reads_back_whole_keeping_nothing_of_what_it_showed(
    legacy: Path,
) -> None:
    """ADR-0358 §11:6, §11:8: every stored entry is carried whole with the addition empty,
    and every other record reads back as it was written (ADR-0326 §4:2)."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision, _, _) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        stored: dict[str, Any] = json.loads(data)
        stored.pop("revision", None)
        _holds(record.model_dump(mode="json", exclude={"revision"}), stored)
    ended = _processing(exported["mem-episode"])
    assert ended.schema_version == 12
    assert [entry.outcome for entry in ended.call_records] == [
        CallOutcomeKind.DONE,
        None,
        CallOutcomeKind.REFUSED,
        CallOutcomeKind.DONE,
    ]
    assert all(entry.showed is None for entry in ended.call_records)
    delivered = ended.call_records[-1].delivered
    assert delivered is not None
    assert delivered.words == "Thursday at 3 is booked."
    opened = _processing(exported[_OPEN])
    assert opened.is_open
    assert [entry.showed for entry in opened.call_records] == [None]
    said = exported["mem-said"]
    assert isinstance(said, Memory)
    (support,) = said.supports
    assert support.points_at == MessageCallPart(
        episode="mem-episode", round="round-2", call_id="call-4"
    )


async def test_the_open_episode_keeps_what_a_later_call_showed_through_the_upgraded_file(
    legacy: Path,
) -> None:
    """ADR-0358 §11:2, ADR-0356 §8:6: an episode the old build opened is extended by an
    entry keeping what its call showed, by reference, and it reads back."""
    showed = CallShowed(
        parts=(
            ShownText(text="The matter's view:"),
            ShownRecord(kind=ShownRecordKind.STORY, id="story-teeth", summary_version=2),
        )
    )
    store = _open(legacy)
    try:
        held = await store.get(_OPEN)
        assert isinstance(held, EpisodicMemory)
        record = _processing(held)
        later = PlanningRound(
            id="round-open-2",
            follows="round-open-1",
            recorded_at=_NOW,
            calls=(ProposedCall(call_id="call-open-2", name="read_story", arguments={}),),
        )
        entry = RecordedCall(
            round="round-open-2",
            call_id="call-open-2",
            capability="read_story",
            effect=False,
            outcome=CallOutcomeKind.DONE,
            recorded_at=_NOW,
            showed=showed,
        )
        extended = held.model_copy(
            update={
                "processing_record": EpisodeProcessingRecord.model_validate(
                    {
                        **dict(record),
                        "rounds": (*record.rounds, later),
                        "call_records": (*record.call_records, entry),
                    }
                )
            }
        )
        await store.add(extended)
        written = await store.get(_OPEN)
    finally:
        store.close()

    assert _processing(written).call_records[-1].showed == showed
    assert (await _exported(legacy))[_OPEN] == written


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
    """ADR-0326 §5:3: the previous release opens 12 to 22, so it refuses the file at 23."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(
            str(legacy),
            accepted=frozenset(
                {
                    EPISODE_RECORD_FORMAT,
                    MEMORIES_RECORD_FORMAT,
                    JOINED_RECORD_FORMAT,
                    PINNED_RECORD_FORMAT,
                    PLACED_RECORD_FORMAT,
                    SCHEDULED_RECORD_FORMAT,
                    CONTINUING_RECORD_FORMAT,
                    TAKEN_OVER_RECORD_FORMAT,
                    PARTIES_RECORD_FORMAT,
                    UNDERSTOOD_RECORD_FORMAT,
                    CALLED_RECORD_FORMAT,
                }
            ),
        )
