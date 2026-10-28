"""ADR-0326 §4:2's test, for ADR-0352 §6:5's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0352.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``ec497f438``, through its public ``add`` and
``advance_walk``, at the label ``18``), never by hand-built SQL, with an eight-dimension
hashing embedder. It holds a memory the user said and three episodes that build's
``scripts/upgrade_stores.py`` memory writer builds, one of them an activation that took a
join and a takeover, and a walk advanced past two records. Beside them, added through
the same ``add``: an activation frozen ``stopped``, as that build freezes one that was
absorbed or whose input was taken, naming nobody, since no build before ADR-0352 recorded
who took a matter; and an **open** episode, as a hub stopped mid-activation leaves it.

Every episode that build wrote omits ``taken_over_by``, and every one this build writes
carries it, ``null`` where nobody took the matter: a build at 18 would fail on the read,
which is why the label moves (ADR-0326 §2:3, §5:3). The head opens a copy and must upgrade
it in place by the label alone: never refuse it (§5:1), drop nothing and rewrite nothing
(§4:4), and leave every record reading as it did. The open episode then freezes naming
its taker through the upgraded file, and the previous release, which serves 12 to 18,
refuses the file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from memory_parties_carry import origin_recorded, parties_carried

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    ControllerRule,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryRecord,
    Placement,
    ProcessingReason,
    ProcessingStatus,
    UnderstandingOmission,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    CONTINUING_RECORD_FORMAT,
    EPISODE_RECORD_FORMAT,
    JOINED_RECORD_FORMAT,
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    PINNED_RECORD_FORMAT,
    PLACED_RECORD_FORMAT,
    SCHEDULED_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink
from ai_assistant.testing.activation import ended_pass

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0352.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 26, 13, tzinfo=UTC)

_IDS = {
    "mem-said",
    "mem-episode",
    "mem-episode-activation",
    "mem-episode-joined",
    "mem-episode-stopped",
    "mem-episode-open",
}

_STOPPED = "mem-episode-stopped"
_OPEN = "mem-episode-open"

#: The activation that took the open one's matter, as the freeze names it (ADR-0352 §5:2).
_TAKER = "act-upgrade-absorber"


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int, str | None, int]]:
    """Every row's kind, stored blob, revision, band and openness, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision), band, int(is_open))
            for record_id, kind, data, revision, band, is_open in conn.execute(
                "SELECT id, kind, data, revision, band, is_open FROM records"
            )
        }


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


def _record(episode: MemoryRecord | None) -> EpisodeProcessingRecord:
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    return episode.processing_record


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, no row names a taker, one episode is frozen
    ``stopped`` and one is open."""
    assert _label(_FIXTURE) == CONTINUING_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    for _, data, _, _, _ in rows.values():
        assert "taken_over_by" not in data
    stopped = json.loads(rows[_STOPPED][1])["processing_record"]
    assert (stopped["status"], stopped["reason"]) == ("interrupted", "stopped")
    assert rows[_OPEN][4] == 1
    assert json.loads(rows[_OPEN][1])["processing_record"]["status"] is None


async def test_the_file_is_upgraded_in_place_by_its_label_alone(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4: the label advances and no stored byte of a record moves.

    The chain goes on to ADR-0351 §9's upgrade, which rewrites each episode whose trigger
    records an origin: such a row keeps its kind, its revision, its band and its
    openness, and every other row is byte for byte what it was.
    """
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    after = _raw_rows(legacy)
    for record_id, row in before.items():
        if origin_recorded(row[1]):
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
            _holds(json.loads(after[record_id][1]), parties_carried(json.loads(row[1])))
        else:
            assert after[record_id] == row


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record the file holds is read back whole, naming no taker."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision, _, _) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        # ADR-0351 §9: the chain ends in carrying the trigger's origin onto its parties.
        stored: dict[str, Any] = parties_carried(json.loads(data))
        stored.pop("revision", None)
        _holds(record.model_dump(mode="json", exclude={"revision"}), stored)
        if isinstance(record, EpisodicMemory) and record.processing_record is not None:
            assert record.processing_record.taken_over_by is None
    assert _record(exported[_STOPPED]).reason is ProcessingReason.STOPPED
    assert _record(exported[_OPEN]).is_open


async def test_the_walk_resumes_where_it_stood(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them, and
    waits at the open episode (ADR-0286 §5)."""
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        assert {record.id for record in rest.records} == _IDS - {
            "mem-said",
            "mem-episode",
            _OPEN,
        }
    finally:
        store.close()


async def test_the_open_episode_freezes_naming_its_taker_through_the_upgraded_file(
    legacy: Path,
) -> None:
    """ADR-0352 §5:2, §6:6: the freezing revision of an episode the old build opened
    names the activation that took its matter, and it reads back."""
    store = _open(legacy)
    try:
        held = await store.get(_OPEN)
        assert isinstance(held, EpisodicMemory)
        record = _record(held)
        frozen = held.model_copy(
            update={
                "content": "The user said actually, Saturday.",
                "placement": Placement(),
                "processing_record": EpisodeProcessingRecord.model_validate(
                    {
                        **dict(record),
                        "status": ProcessingStatus.INTERRUPTED,
                        "reason": ProcessingReason.STOPPED,
                        "ended_at": _NOW,
                        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
                        "stages": ended_pass(_NOW, ControllerRule.STOPPED),
                        "taken_over_by": _TAKER,
                    }
                ),
            }
        )
        await store.add(frozen)
        written = await store.get(_OPEN)
    finally:
        store.close()

    assert _record(written).taken_over_by == _TAKER
    assert (await _exported(legacy))[_OPEN] == written


async def test_an_episode_the_old_build_froze_never_gains_a_taker(legacy: Path) -> None:
    """ADR-0352 §6:6: only the freezing revision names a taker, so a record frozen at
    18 naming nobody keeps naming nobody."""
    store = _open(legacy)
    try:
        held = await store.get(_STOPPED)
        assert isinstance(held, EpisodicMemory)
        named = held.model_copy(
            update={
                "processing_record": EpisodeProcessingRecord.model_validate(
                    {**dict(_record(held)), "taken_over_by": _TAKER}
                )
            }
        )
        with pytest.raises(MemoryStoreError):
            await store.add(named)
        assert await store.get(_STOPPED) == held
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
    """ADR-0326 §5:3: the previous release opens 12 to 18, so it refuses the file at 19."""
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
                }
            ),
        )
