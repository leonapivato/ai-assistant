"""ADR-0326 §4:2's test, for ADR-0349 §10:6: a file the previous release wrote is upgraded.

``tests/memory/legacy/memory-before-adr-0349.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``3257c4d4d``, through its public ``add`` and
``advance_walk``, at the label ``17``), never by hand-built SQL. It holds what that
build's ``scripts/upgrade_stores.py`` memory writer wrote, with an eight-dimension
hashing embedder: three memories, three episodes, one of them an activation that took a
join and a takeover, whose understanding versions record ``continues`` as ``null`` and
as one activation's id, and a walk advanced past two records. Beside them, added through
the same ``add``: an **open** episode, as a hub stopped mid-activation leaves it, whose
one understanding version continues another activation.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop nothing (§4:4), and carry each stored ``continues`` onto the sequence ADR-0349
§10:2 makes it, one id as a one-element sequence and ``null`` as an empty one, while
every other record, and every other field of a rewritten one, reads as it did.
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
    ActivationUnderstanding,
    EpisodicMemory,
    Memory,
    MemoryRecord,
    UnderstandingGround,
    UnderstandingProducer,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._continuing_upgrade import continuing_episode
from ai_assistant.memory._episode_format import (
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

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0349.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW = datetime(2026, 10, 26, 13, tzinfo=UTC)

_IDS = {
    "mem-said",
    "mem-remembered",
    "mem-pinned",
    "mem-episode",
    "mem-episode-activation",
    "mem-episode-joined",
    "mem-episode-open",
}

#: The episodes whose understandings record ``continues``, and what each held, version by
#: version, as the previous release stored it.
_CONTINUING: dict[str, list[str | None]] = {
    "mem-episode-joined": [None, "act-upgrade-line"],
    "mem-episode-open": ["act-upgrade-web"],
}


def _raw_rows(path: Path) -> dict[str, tuple[str, str, int, str | None, int]]:
    """Every row's kind, stored blob, revision, band and openness, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), str(data), int(revision), band, int(is_open))
            for record_id, kind, data, revision, band, is_open in conn.execute(
                "SELECT id, kind, data, revision, band, is_open FROM records"
            )
        }


def _held(data: str) -> list[object]:
    """What each understanding version of a stored record holds in ``continues``."""
    record = json.loads(data)
    return [one.get("continues") for one in record["processing_record"]["understanding"]]


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
    """The file is at the previous label, and its understandings hold one id or ``null``."""
    assert _label(_FIXTURE) == SCHEDULED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    for record_id, held in _CONTINUING.items():
        assert _held(rows[record_id][1]) == held
    assert rows["mem-episode-open"][4] == 1


async def test_each_stored_continues_becomes_a_sequence(legacy: Path) -> None:
    """§10:6: one id becomes a one-element sequence, and ``null`` an empty one."""
    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    after = _raw_rows(legacy)
    for record_id, held in _CONTINUING.items():
        episode = exported[record_id]
        assert isinstance(episode, EpisodicMemory)
        assert episode.processing_record is not None
        expected = [() if one is None else (one,) for one in held]
        assert [one.continues for one in episode.processing_record.understanding] == expected
        assert _held(after[record_id][1]) == [list(one) for one in expected]


async def test_only_the_episodes_that_record_continues_are_rewritten(legacy: Path) -> None:
    """ADR-0326 §4:4: every row is kept; a rewritten one keeps its kind, revision, band
    and openness, and every other row is byte for byte what it was.

    The chain goes on to ADR-0351 §9's upgrade, which rewrites every episode whose
    trigger records an origin, so those are rewritten too, on the same terms.
    """
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(exported) == set(before) == set(after) == _IDS
    for record_id, row in before.items():
        if record_id in _CONTINUING or origin_recorded(row[1]):
            kind, _, revision, band, is_open = row
            assert (after[record_id][0], *after[record_id][2:]) == (kind, revision, band, is_open)
            assert after[record_id][1] != row[1]
        else:
            assert after[record_id] == row


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record the file holds is read back whole, ``continues`` carried."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision, _, _) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        stored: dict[str, Any] = json.loads(data)
        stored.pop("revision", None)
        continuing_episode(stored)
        _holds(record.model_dump(mode="json", exclude={"revision"}), parties_carried(stored))


async def test_the_walk_resumes_and_the_open_episode_stays_open(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them, and
    stops at the open episode, which is still open (ADR-0286 §12)."""
    exported = await _exported(legacy)
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        opened = await store.open_episodes(limit=50)
    finally:
        store.close()

    assert "mem-said" not in {record.id for record in rest.records}
    assert [one.record.id for one in opened] == ["mem-episode-open"]
    episode = exported["mem-episode-open"]
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.is_open


async def test_an_understanding_continuing_two_round_trips_through_the_upgraded_file(
    legacy: Path,
) -> None:
    """§10:2: a version naming two activations, written to the upgraded file, reads back."""
    store = _open(legacy)
    try:
        held = await store.get("mem-episode-joined")
        assert isinstance(held, EpisodicMemory)
        assert held.processing_record is not None
        version = ActivationUnderstanding(
            version=1,
            recorded_at=_NOW,
            producer=UnderstandingProducer.INTERPRETATION,
            meaning="Make both Sunday.",
            meaning_ground=UnderstandingGround.STATED,
            continues=("act-upgrade-line", "act-upgrade-web"),
        )
        both = held.model_copy(
            update={
                "id": "mem-episode-both",
                "processing_record": held.processing_record.model_copy(
                    update={"activation_id": "act-upgrade-both", "understanding": (version,)}
                ),
            }
        )
        await store.add(both)
        written = await store.get("mem-episode-both")
    finally:
        store.close()

    assert isinstance(written, EpisodicMemory)
    assert written.processing_record is not None
    assert written.processing_record.understanding[0].continues == (
        "act-upgrade-line",
        "act-upgrade-web",
    )
    assert (await _exported(legacy))["mem-episode-both"] == written


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


def test_an_episode_that_cannot_be_upgraded_leaves_the_file_as_it_was(legacy: Path) -> None:
    """ADR-0326 §4:3: the upgrade completes or leaves the file as it found it. A stored
    ``continues`` of a shape no release wrote is refused, and nothing is written."""
    with sqlite3.connect(legacy) as conn:
        (data,) = conn.execute(
            "SELECT data FROM records WHERE id = ?", ("mem-episode-joined",)
        ).fetchone()
        stored = json.loads(data)
        stored["processing_record"]["understanding"][1]["continues"] = "   "
        conn.execute(
            "UPDATE records SET data = ? WHERE id = ?", (json.dumps(stored), "mem-episode-joined")
        )
    before = (_label(legacy), _raw_rows(legacy))

    with pytest.raises(MemoryStoreError):
        _open(legacy)

    assert (_label(legacy), _raw_rows(legacy)) == before


async def test_an_earlier_upgrade_reads_an_episode_that_records_continues(tmp_path: Path) -> None:
    """ADR-0326 §4:5: the chain holds where an earlier upgrade reads such an episode.

    ADR-0345 §13's upgrade, earlier in the chain, reads the episode a memory's support
    points at to give the support its holder. Over a copy of the file the release before
    ADR-0345 wrote (label 15), one memory's support is pointed at the episode whose
    understandings hold ``continues`` as ``null`` and as an id: the store opens it,
    the support gains its holder from that episode, and the episode is carried.
    """
    path = tmp_path / "memory.db"
    shutil.copyfile(_FIXTURE.parent / "memory-before-adr-0345.db", path)
    with sqlite3.connect(path) as conn:
        (data,) = conn.execute("SELECT data FROM records WHERE id = ?", ("mem-said",)).fetchone()
        # The support and the operations citing it point at the episode together.
        pointed = str(data).replace('"mem-episode-activation"', '"mem-episode-joined"')
        assert pointed != data
        conn.execute("UPDATE records SET data = ? WHERE id = ?", (pointed, "mem-said"))
        (joined,) = conn.execute(
            "SELECT data FROM records WHERE id = ?", ("mem-episode-joined",)
        ).fetchone()
    assert _held(joined) == [None, "act-upgrade-line"]

    exported = await _exported(path)

    assert _label(path) == MEMORY_RECORD_FORMAT
    said = exported["mem-said"]
    assert isinstance(said, Memory)
    assert said.supports[0].points_at.model_dump()["episode"] == "mem-episode-joined"
    assert said.supports[0].holder is not None
    episode = exported["mem-episode-joined"]
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert [one.continues for one in episode.processing_record.understanding] == [
        (),
        ("act-upgrade-line",),
    ]


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 17, so it refuses the file at 18."""
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
                }
            ),
        )


@pytest.mark.parametrize(
    ("held", "carried"),
    [(None, []), ("act-1", ["act-1"]), (["act-1"], ["act-1"]), ([], [])],
)
def test_the_carry_is_idempotent_and_reports_what_it_moved(
    held: object, carried: list[str]
) -> None:
    """The pure carry: one id or ``null`` moves and says so; a sequence stays and says not."""
    stored: dict[str, Any] = {
        "processing_record": {"understanding": [{"continues": held}, {"meaning": "x"}]}
    }

    moved = continuing_episode(stored)

    assert moved is (held is None or isinstance(held, str))
    assert stored["processing_record"]["understanding"] == [
        {"continues": carried},
        {"meaning": "x"},
    ]
    assert continuing_episode(stored) is False
