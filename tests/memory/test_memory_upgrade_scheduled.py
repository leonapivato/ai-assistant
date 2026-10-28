"""ADR-0326 §4:2's test, for ADR-0350's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0350.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``03273b882``, through its public ``add`` and
``advance_walk``, at the label ``16``), never by hand-built SQL. It holds what that
build's ``scripts/upgrade_stores.py`` memory writer wrote, with an eight-dimension
hashing embedder: a memory the user said, one a remember call backs, one the user said
and pinned, three episodes and a walk advanced past two records. Beside them, added
through the same ``add``: an ended activation's episode carrying a planning round, which
that build records with ``"place": null`` (ADR-0350 §12:8) — the record a build before
it would refuse to read, which is why the label moves (#3429).

The head opens a copy and must upgrade it in place by the label alone: never refuse it
(ADR-0326 §5:1), drop nothing and rewrite nothing (§4:4), and leave every record reading
as it did. An episode whose round names its place then round-trips through the upgraded
file, and the previous release, which serves 12 to 16, refuses it (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from memory_continuing_carry import carried, continues_recorded
from memory_parties_carry import origin_recorded, parties_carried

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    ChannelIdentity,
    EpisodicMemory,
    MemoryRecord,
    PlanningRound,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    EPISODE_RECORD_FORMAT,
    JOINED_RECORD_FORMAT,
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    PINNED_RECORD_FORMAT,
    PLACED_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0350.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 25, 21, tzinfo=UTC)

_IDS = {
    "mem-said",
    "mem-remembered",
    "mem-pinned",
    "mem-episode",
    "mem-episode-activation",
    "mem-episode-joined",
    "mem-episode-planned",
}

#: The place a task's activation names for its message (ADR-0350 §6:7, §12:8).
_LINE = ChannelIdentity(channel_type="telegram", instance_id="upgrade-line")


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int, str | None]]:
    """Every row's kind, stored blob, revision and band column, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision), band)
            for record_id, kind, data, revision, band in conn.execute(
                "SELECT id, kind, data, revision, band FROM records"
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


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, a round in it holds ``place: null``, and no
    episode names the ``assistant`` origin, which only this build admits."""
    assert _label(_FIXTURE) == PLACED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    planned = json.loads(rows["mem-episode-planned"][1])
    (round_,) = planned["processing_record"]["rounds"]
    assert round_["place"] is None
    for _, data, _, _ in rows.values():
        assert '"origin":"assistant"' not in data.replace(" ", "")


async def test_the_file_is_upgraded_in_place_by_its_label_alone(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4: the label advances and no stored byte of a record moves.

    The chain goes on to ADR-0349 §10:6's upgrade, which rewrites each episode whose
    understandings record ``continues``: such a row keeps its kind, its revision and its
    band, and its record moves only as that carry says; every other row is byte for
    byte what it was.
    """
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == _IDS
    after = _raw_rows(legacy)
    # ADR-0351 §9's upgrade, later in the chain, rewrites each episode whose trigger
    # records an origin, on the same terms as ADR-0349 §10:6's.
    for record_id, row in before.items():
        if continues_recorded(row[1]) or origin_recorded(row[1]):
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
            _holds(json.loads(after[record_id][1]), parties_carried(carried(json.loads(row[1]))))
        else:
            assert after[record_id] == row


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record the file holds is read back whole."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision, _) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        # ADR-0349 §10:6, ADR-0351 §9: the chain carries ``continues`` onto a sequence,
        # and the trigger's origin onto its parties.
        stored: dict[str, Any] = parties_carried(carried(json.loads(data)))
        stored.pop("revision", None)
        _holds(record.model_dump(mode="json", exclude={"revision"}), stored)
    planned = exported["mem-episode-planned"]
    assert isinstance(planned, EpisodicMemory)
    assert planned.processing_record is not None
    assert [one.place for one in planned.processing_record.rounds] == [None]


async def test_the_walk_resumes_where_it_stood(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them."""
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        assert {record.id for record in rest.records} == _IDS - {"mem-said", "mem-remembered"}
    finally:
        store.close()


async def test_a_round_naming_its_place_round_trips_through_the_upgraded_file(
    legacy: Path,
) -> None:
    """ADR-0350 §12:8: a round of a task's activation names its place, and reads back."""
    store = _open(legacy)
    try:
        held = await store.get("mem-episode-planned")
        assert isinstance(held, EpisodicMemory)
        assert held.processing_record is not None
        placed = held.model_copy(
            update={
                "id": "mem-episode-placed",
                "processing_record": held.processing_record.model_copy(
                    update={
                        "activation_id": "act-upgrade-4",
                        "rounds": (
                            PlanningRound(
                                id="round:upgrade-4:1",
                                recorded_at=_NOW,
                                text="Time to call Mom.",
                                place=_LINE,
                            ),
                        ),
                    }
                ),
            }
        )
        await store.add(placed)
        written = await store.get("mem-episode-placed")
    finally:
        store.close()

    assert isinstance(written, EpisodicMemory)
    assert written.processing_record is not None
    assert [one.place for one in written.processing_record.rounds] == [_LINE]
    assert (await _exported(legacy))["mem-episode-placed"] == written


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
    """ADR-0326 §5:3: the previous release opens 12 to 16, so it refuses the file at 17."""
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
                }
            ),
        )
