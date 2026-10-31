"""ADR-0326 §4:2's test, for ADR-0356 §13:5's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0356.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``dd8d77e35``, through its public ``add``, at the
label ``21``), never by hand-built SQL, with an eight-dimension hashing embedder and
invented data. It holds an ended episode whose two rounds proposed a search and a
tidy-up, with notes, a marked round and a label; an **open** episode, as a hub stopped
mid-activation leaves it, whose one round proposed a spawn; a bare episode with no
processing record; and a memory resting on the ended episode's second round's message.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
carry every processing record to ``schema_version`` 12 with ``call_records`` empty
(§13:5), and change nothing else: every other field of every record reads back whole
(§4:4). The previous release, which serves 12 to 21, then refuses the file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    EpisodeProcessingRecord,
    EpisodicMemory,
    Memory,
    MemoryRecord,
    RoundMessagePart,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._calls_upgrade import called_episode
from ai_assistant.memory._episode_format import (
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

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0356.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 10, 30, 10, 1, tzinfo=UTC)

_IDS: Final = {"mem-episode", "mem-episode-open", "mem-episode-bare", "mem-said"}

#: The episodes with a processing record, which the upgrade rewrites.
_REWRITTEN: Final = {"mem-episode", "mem-episode-open"}


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
    """The file is at the previous label, and every processing record it stores is at
    version 11, with no call's entry."""
    assert _label(_FIXTURE) == UNDERSTOOD_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    for record_id in _REWRITTEN:
        processing = json.loads(rows[record_id][1])["processing_record"]
        assert processing["schema_version"] == 11
        assert "call_records" not in processing
    assert rows["mem-episode-open"][4] == 1
    assert "processing_record" not in json.loads(rows["mem-episode-bare"][1]) or (
        json.loads(rows["mem-episode-bare"][1])["processing_record"] is None
    )


async def test_every_episode_reopens_with_no_call_entry_and_every_other_record_whole(
    legacy: Path,
) -> None:
    """§13:5, §14:9: an episode stored before the upgrade reopens with ``call_records``
    empty and every other record whole."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    for record_id in _REWRITTEN:
        processing = _processing(exported[record_id])
        assert (processing.schema_version, processing.call_records) == (12, ())
        stored = json.loads(before[record_id][1])["processing_record"]
        dumped = processing.model_dump(mode="json")
        assert dumped.pop("schema_version") == 12
        assert dumped.pop("call_records") == []
        assert {key: value for key, value in stored.items() if key != "schema_version"} == dumped
    ended = _processing(exported["mem-episode"])
    assert [one.id for one in ended.rounds] == ["round-1", "round-2"]
    assert [call.name for call in ended.rounds[0].calls] == ["search_memory", "tidy_story"]
    assert _processing(exported["mem-episode-open"]).is_open
    said = exported["mem-said"]
    assert isinstance(said, Memory)
    (support,) = said.supports
    assert support.points_at == RoundMessagePart(episode="mem-episode", round="round-2")


async def test_every_other_row_is_kept_and_the_rest_byte_for_byte(legacy: Path) -> None:
    """ADR-0326 §4:4: a rewritten row keeps its kind, revision, band and openness, and
    every row the upgrade does not rewrite is byte for byte what it was: the memory and
    the bare episode."""
    before = _raw_rows(legacy)

    await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(after) == set(before) == _IDS
    for record_id, row in before.items():
        if record_id in _REWRITTEN:
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
        else:
            assert after[record_id] == row, record_id


def test_a_record_the_upgrade_cannot_read_leaves_the_file_as_it_was_found(legacy: Path) -> None:
    """ADR-0326 §4:3: a round no build wrote is refused as the store's error, every row
    rewritten before it rolls back, and the open holds no lock."""
    with sqlite3.connect(legacy) as conn:
        (data,) = conn.execute(
            "SELECT data FROM records WHERE id = ?", ("mem-episode-open",)
        ).fetchone()
        stored = json.loads(data)
        stored["processing_record"]["rounds"][0]["follows"] = "round-open-1"
        conn.execute(
            "UPDATE records SET data = ? WHERE id = ?", (json.dumps(stored), "mem-episode-open")
        )
    conn.close()
    before = _raw_rows(legacy)

    with pytest.raises(MemoryStoreError, match="could not be decoded"):
        _open(legacy)

    assert _label(legacy) == UNDERSTOOD_RECORD_FORMAT
    assert _raw_rows(legacy) == before
    probe = sqlite3.connect(legacy, timeout=0, isolation_level=None)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("ROLLBACK")
    finally:
        probe.close()


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    await _exported(legacy)
    once = (_label(legacy), _raw_rows(legacy))

    await _exported(legacy)

    assert (_label(legacy), _raw_rows(legacy)) == once


def test_the_upgrade_of_one_record_is_idempotent() -> None:
    """A record already at version 12 comes back unchanged, reporting no change."""
    rows = _raw_rows(_FIXTURE)
    stored = json.loads(rows["mem-episode"][1])
    assert called_episode(stored)
    carried = json.dumps(stored)
    assert not called_episode(stored)
    assert json.dumps(stored) == carried
    assert not called_episode(json.loads(rows["mem-episode-bare"][1]))
    assert not called_episode(json.loads(rows["mem-said"][1]))


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade."""
    path = tmp_path / "memory.db"
    _open(path).close()
    assert _label(path) == MEMORY_RECORD_FORMAT


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 21, so it refuses the file at 22."""
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
                }
            ),
        )
