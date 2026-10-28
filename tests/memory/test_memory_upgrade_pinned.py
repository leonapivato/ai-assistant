"""ADR-0326 §4:2's test, for ADR-0338 §4:4: a file the previous release wrote is upgraded.

``tests/memory/legacy/memory-before-adr-0338.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``c973d57a``, through its public ``add`` and
``advance_walk``, at the label ``14``), never by hand-built SQL. It holds what
``scripts/upgrade_stores.py``'s memory writer wrote at that build, with an eight-dimension
hashing embedder: two memories, a plain episode, an ended activation's episode and one
that took a join, and a walk advanced past two of them. Beside them it holds a memory
resting on the user's message and an observer's inference (ADR-0329 §9:7), added through
the same ``add``.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop nothing and rewrite nothing (§4:4), and leave every record reading as it did. A
pinned support then round-trips through the upgraded file, and raises its memory to "you
confirmed this wording" (ADR-0338 §4:3, ADR-0328 §6:1).
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
    BeliefBand,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRecord,
    MemoryStanding,
    MemoryWriterName,
    PinPart,
    SupportOrigin,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    EPISODE_RECORD_FORMAT,
    JOINED_RECORD_FORMAT,
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink
from ai_assistant.testing.memories import pinned_support

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0338.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 21, 13, tzinfo=UTC)

_IDS = {
    "mem-said",
    "mem-remembered",
    "mem-inferred",
    "mem-episode",
    "mem-episode-activation",
    "mem-episode-joined",
}


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
    """The file is at the previous label, and no record in it names a pin."""
    assert _label(_FIXTURE) == JOINED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    origins = {
        support["origin"]
        for kind, data, _, _ in rows.values()
        if kind == "memory"
        for support in json.loads(data)["supports"]
    }
    assert origins == {"user_message", "remembered", "observer_inference"}
    for _, data, _, _ in rows.values():
        assert '"pinned"' not in data
        assert '"pin"' not in data


async def test_the_file_is_upgraded_in_place_by_its_label_alone(legacy: Path) -> None:
    """ADR-0326 §4:1, §4:4: the label advances and no stored byte of a record moves.

    The band column is among the bytes: no origin a stored support names changes its
    standing, so no memory's band moves.
    """
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
    inferred = exported["mem-inferred"]
    assert isinstance(inferred, Memory)
    assert inferred.standing is MemoryStanding.SAID


async def test_the_walk_resumes_where_it_stood(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them."""
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        assert [record.id for record in rest.records] == [
            "mem-episode",
            "mem-episode-activation",
            "mem-episode-joined",
            "mem-inferred",
        ]
    finally:
        store.close()


async def test_a_pinned_support_round_trips_through_the_upgraded_file(legacy: Path) -> None:
    """ADR-0338 §4:3, §4:4: a pin's support is stored, read back whole, and confirms.

    The memory the user said reaches "you confirmed this wording", in the ``ASSERTED``
    band, and ``search``'s band column says so, since every write refills it.
    """
    store = _open(legacy)
    try:
        read = await store.get("mem-said")
        assert isinstance(read, Memory)
        support = pinned_support("pin-upgrade", when=_NOW, added_at=_NOW)
        pinned = Memory.model_validate(
            read.model_dump()
            | {
                "supports": (*read.supports, support),
                "operations": (
                    *read.operations,
                    MemoryOperation(
                        kind=MemoryOperationKind.ADD_SUPPORT,
                        cites=support.points_at,
                        at=_NOW,
                        by=MemoryWriterName.OBSERVER,
                    ),
                ),
            }
        )
        await store.add(pinned)
        written = await store.get("mem-said")
    finally:
        store.close()

    assert isinstance(written, Memory)
    held = written.support_at(PinPart(pin="pin-upgrade"))
    assert held == support
    assert held.origin is SupportOrigin.PINNED
    assert written.standing is MemoryStanding.CONFIRMED
    assert _raw_rows(legacy)["mem-said"][3] == BeliefBand.ASSERTED.value
    reopened = await _exported(legacy)
    assert reopened["mem-said"] == written


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
    """ADR-0326 §5:3: the previous release opens 12 to 14, so it refuses the file at 15."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(
            str(legacy),
            accepted=frozenset(
                {EPISODE_RECORD_FORMAT, MEMORIES_RECORD_FORMAT, JOINED_RECORD_FORMAT}
            ),
        )
