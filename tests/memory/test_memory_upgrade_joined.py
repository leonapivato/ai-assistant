"""ADR-0326 §4:2's test, for ADR-0332 §7:8: a file the previous release wrote is upgraded.

``tests/memory/legacy/memory-before-adr-0332.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``59fd87c4``, through its public ``add`` and
``advance_walk``, at the label ``13``), never by hand-built SQL. It holds what
``scripts/upgrade_stores.py``'s memory writer wrote at that build, with an eight-dimension
hashing embedder: two memories, a plain episode and an ended activation's episode, and a
walk advanced past two of them. It holds two activation episodes beside them: one ended,
whose processing record carries an understanding version, a stage that ran and the
messages its trigger took in, and one still **open**, as a hub stopped mid-activation
leaves it.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop nothing and rewrite nothing (§4:4), and leave every record reading as it did, with
``joined`` and ``continues`` at their defaults (ADR-0332 §7:2, §7:4).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from memory_continuing_carry import carried, continues_recorded
from memory_parties_carry import origin_recorded, parties_carried

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    JoinedInput,
    Memory,
    MemoryRecord,
    MemoryWriterName,
    ProcessingReason,
    ProcessingStatus,
    RecordedInputMessage,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0332.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 21, 13, tzinfo=UTC)

_IDS = {
    "mem-said",
    "mem-remembered",
    "mem-episode",
    "mem-episode-activation",
    "activation:act-understood-1",
    "activation:act-open-1",
}

_OPEN = "activation:act-open-1"


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int]]:
    """Every row's kind, stored blob and revision, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision))
            for record_id, kind, data, revision in conn.execute(
                "SELECT id, kind, data, revision FROM records"
            )
        }


def _holds(read: object, written: object) -> None:
    """``read`` holds everything ``written`` held, unchanged, and may add fields to it.

    Deep, so a field this build adds at its default inside a nested model, as
    ``joined`` is inside the processing record, is the only difference admitted.
    """
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


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


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


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label and holds episodes with processing records."""
    assert _label(_FIXTURE) == MEMORIES_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    processed = {
        record_id
        for record_id, (_, data, _) in rows.items()
        if json.loads(data).get("processing_record") is not None
    }
    assert processed == {"mem-episode-activation", "activation:act-understood-1", _OPEN}
    for _, data, _ in rows.values():
        assert '"joined"' not in data
        assert '"continues"' not in data


async def test_the_file_is_upgraded_in_place_by_its_label_alone(legacy: Path) -> None:
    """§7:8, ADR-0326 §4:1, §4:4: the label advances and no stored byte of a record moves."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    after = _raw_rows(legacy)
    assert set(exported) == _IDS
    # The chain goes on to ADR-0345 §13's upgrade, which rewrites each memory, to
    # ADR-0349 §10:6's, which rewrites each episode whose understandings record
    # ``continues``, and to ADR-0351 §9's, which rewrites each whose trigger records an
    # origin: every other episode's row is byte for byte what it was, and a rewritten
    # row keeps its kind, its revision and its band.
    for record_id, row in before.items():
        rewritten = continues_recorded(row[1]) or origin_recorded(row[1])
        if row[0] == "memory" or rewritten:
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
        else:
            assert after[record_id] == row
        if row[0] != "memory" and rewritten:
            _holds(json.loads(after[record_id][1]), parties_carried(carried(json.loads(row[1]))))


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record the file holds is read back, its new fields at default."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        # ADR-0349 §10:6, ADR-0351 §9: the chain carries ``continues`` onto a sequence,
        # and the trigger's origin onto its parties.
        stored: dict[str, Any] = parties_carried(carried(json.loads(data)))
        stored.pop("revision", None)
        # ADR-0345 §13:1, §10:2: a memory's subject is carried as ``subjects`` and its
        # topics as labels added by ``migration``.
        if isinstance(record, Memory):
            about = stored.pop("about_person", None)
            topics = stored.pop("topics", None) or []
            assert record.subjects == (None if about is None else (about,))
            assert [(one.text, one.added_by) for one in record.labels] == [
                (topic, MemoryWriterName.MIGRATION) for topic in topics
            ]
        _holds(record.model_dump(mode="json", exclude={"revision"}), stored)
        if isinstance(record, EpisodicMemory) and record.processing_record is not None:
            assert record.processing_record.joined == ()
            assert all(one.continues == () for one in record.processing_record.understanding)


async def test_the_walk_and_the_open_episode_survive(legacy: Path) -> None:
    """The walk resumes where it stood, and the open episode is still open (ADR-0286 §12).

    The walk stops at the open episode, as it did before the upgrade.
    """
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        assert [record.id for record in rest.records] == [
            "mem-episode",
            "mem-episode-activation",
            "activation:act-understood-1",
        ]
        held_open = await store.open_episodes(limit=10)
        assert [one.record.id for one in held_open] == [_OPEN]
    finally:
        store.close()


async def test_an_upgraded_open_episode_takes_a_join_and_freezes(legacy: Path) -> None:
    """After the upgrade the episode a hub left open extends with ``joined`` (§3:16)."""
    store = _open(legacy)
    try:
        stored = await store.get(_OPEN)
        assert isinstance(stored, EpisodicMemory)
        record = stored.processing_record
        assert record is not None
        joined_at = record.started_at + timedelta(seconds=1)
        joined = JoinedInput(
            joined_at=joined_at,
            channel=record.trigger.target,  # type: ignore[arg-type]  # a channel identity here
            messages=(RecordedInputMessage(text="and four people", sent_at=joined_at),),
        )
        extended = stored.model_copy(
            update={"processing_record": record.model_copy(update={"joined": (joined,)})}
        )
        await store.add(extended)
        ended = joined_at + timedelta(seconds=1)
        frozen_record = EpisodeProcessingRecord.model_validate(
            {
                **dict(extended.processing_record or record),
                "status": ProcessingStatus.COMPLETED,
                "reason": ProcessingReason.RETURNED,
                "ended_at": ended,
                "understanding_omitted": UnderstandingOmission.NOT_REACHED,
                "stages": (
                    StageEntry(
                        stage=ControllerStage.END,
                        due=ControllerRule.NOTHING_DUE,
                        started_at=ended,
                        ended_at=ended,
                        outcome=StageOutcome.DONE,
                    ),
                ),
            }
        )
        await store.add(extended.model_copy(update={"processing_record": frozen_record}))
        read = await store.get(_OPEN)
        assert isinstance(read, EpisodicMemory)
        assert read.processing_record is not None
        assert read.processing_record.joined == (joined,)
        assert not read.processing_record.is_open
    finally:
        store.close()


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
    """ADR-0326 §5:3: the previous release opens 12 and 13, so it refuses the file at 14."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=frozenset({12, MEMORIES_RECORD_FORMAT}))
