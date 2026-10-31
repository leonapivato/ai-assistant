"""ADR-0326 §4:2's test, for ADR-0353 §9:6's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0353.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``935d2e4f9``, through its public ``add`` and
``advance_walk``, at the label ``20``), never by hand-built SQL, with an eight-dimension
hashing embedder and invented data. It holds an ended episode whose first understanding
version carries every retired field — a ``supplied`` ground, two references, one of
whose referents its meaning already cites, two relationships, an unresolved matter and
an answer pointer — beside its meaning's referents, story links and ``continues``, and
whose second version carries only a ground; an ended episode whose one version carries
only a ground; an **open** episode, as a hub stopped mid-activation leaves it, whose one
version has a reference; an ended episode that recorded no understanding; a bare episode
with no processing record; and a memory resting on the first episode's input. A walk is
advanced past two records.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop every retired field from every version (ADR-0353 §9:6), add the referents of each
version's references and relationships to its ``meaning_referents``, after the meaning's
own and each once, and change nothing else: each version's meaning, story links and
``continues`` read back unchanged, and every other record reads back whole (§4:4). The
previous release, which serves 12 to 20, then refuses the file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from memory_parties_carry import calls_carried

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryRecord,
    StoryMember,
    StoryMemberKind,
    UnderstandingReferent,
)
from ai_assistant.memory import SqliteMemoryStore
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
    inspect_existing,
)
from ai_assistant.memory._understanding_upgrade import RETIRED_FIELDS, understood_episode
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0353.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 10, 28, 10, 10, tzinfo=UTC)

_IDS: Final = {
    "mem-episode",
    "mem-episode-understood",
    "mem-episode-stated",
    "mem-episode-omitted",
    "mem-episode-open",
    "mem-said",
}

#: The episodes whose versions hold a retired field, which the upgrade rewrites.
_REWRITTEN: Final = {"mem-episode-understood", "mem-episode-stated", "mem-episode-open"}

_EARLIER: Final = UnderstandingReferent(
    kind="episode",
    id="activation:act-earlier",
    source="conversation:chat-1",
    excerpt="book the dentist for Thursday",
)
_MESSAGE: Final = UnderstandingReferent(
    kind="channel_item", id="message:3", source="conversation:chat-1", excerpt="Thursday?"
)
_FACT: Final = UnderstandingReferent(
    kind="memory", id="mem-said", source="memory", excerpt="Maren's dentist is Dr Lind."
)
_STORY: Final = UnderstandingReferent(kind="story", id="story-teeth", source="story", excerpt="")

#: Each rewritten episode's versions' ``meaning_referents`` once upgraded: the meaning's
#: own first, then each reference's and relationship's referent not already held, in
#: the order the version held them — so ``_EARLIER``, which the first reference repeats,
#: and ``_MESSAGE``, which both a reference and a relationship name, are each held once.
_REFERENTS: Final = {
    "mem-episode-understood": [(_EARLIER, _STORY, _MESSAGE, _FACT), ()],
    "mem-episode-stated": [()],
    "mem-episode-open": [(_MESSAGE,)],
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


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


def _versions(data: str) -> list[dict[str, Any]]:
    """The understanding versions a stored blob holds, as stored."""
    processing = json.loads(data).get("processing_record") or {}
    versions: list[dict[str, Any]] = processing.get("understanding", [])
    return versions


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
    """The file is at the previous label, and every version it stores holds the
    retired fields, the first one each of them with a value."""
    assert _label(_FIXTURE) == PARTIES_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    for record_id in _REWRITTEN:
        for version in _versions(rows[record_id][1]):
            assert set(RETIRED_FIELDS) <= set(version), record_id
    first = _versions(rows["mem-episode-understood"][1])[0]
    assert all(first[name] for name in RETIRED_FIELDS)
    assert rows["mem-episode-open"][4] == 1


async def test_every_version_loses_its_retired_fields_and_keeps_what_it_drew_on(
    legacy: Path,
) -> None:
    """§9:6, §16:4: the retired fields go, each version's references' and relationships'
    referents join its ``meaning_referents`` each once, and its meaning, story links and
    ``continues`` read back unchanged."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    for record_id, referents in _REFERENTS.items():
        versions = _processing(exported[record_id]).understanding
        stored = _versions(before[record_id][1])
        assert [one.meaning_referents for one in versions] == referents, record_id
        assert [one.meaning for one in versions] == [one["meaning"] for one in stored]
        assert [
            [one.model_dump(mode="json") for one in version.story_links] for version in versions
        ] == [one["story_links"] for one in stored]
        assert [list(one.continues) for one in versions] == [one["continues"] for one in stored]
        assert [one.unclear for one in versions] == [()] * len(versions)
        assert [one.grounding_dropped for one in versions] == [
            one["grounding_dropped"] for one in stored
        ]
    understood = _processing(exported["mem-episode-understood"]).understanding[0]
    assert understood.story_links == (
        StoryMember(kind=StoryMemberKind.STORY, id="story-teeth"),
        StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-earlier"),
    )
    assert understood.continues == ("act-running",)
    after = _raw_rows(legacy)
    for record_id in _REWRITTEN:
        for version in _versions(after[record_id][1]):
            assert not set(RETIRED_FIELDS) & set(version), record_id
    assert _processing(exported["mem-episode-open"]).is_open


async def test_every_other_record_reads_back_byte_for_byte(legacy: Path) -> None:
    """ADR-0326 §4:4: every row is kept; a rewritten one keeps its kind, revision, band
    and openness, and every row the upgrade does not rewrite is byte for byte what it was:
    the memory and the bare episode. The chain goes on to ADR-0356 §13:5's upgrade, which
    rewrites every episode with a processing record, the one that recorded no
    understanding included, to carry it to version 12."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(exported) == set(before) == set(after) == _IDS
    for record_id, row in before.items():
        if record_id in _REWRITTEN or calls_carried(row[1]):
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
        else:
            assert after[record_id] == row, record_id


async def test_a_rewritten_episode_changes_nothing_but_its_versions(legacy: Path) -> None:
    """§9:6: "It changes nothing else of the version, and drops no episode": outside its
    versions, a rewritten episode's stored blob is what it was, field for field."""
    before = _raw_rows(legacy)

    await _exported(legacy)

    after = _raw_rows(legacy)
    for record_id in _REWRITTEN:
        old, new = json.loads(before[record_id][1]), json.loads(after[record_id][1])
        old_processing = old.pop("processing_record")
        new_processing = new.pop("processing_record")
        assert new == old, record_id
        old_versions = old_processing.pop("understanding")
        new_versions = new_processing.pop("understanding")
        # ADR-0356 §13:5, at the chain's end: the record is carried to version 12 with
        # no call's entry.
        assert (old_processing.pop("schema_version"), new_processing.pop("schema_version")) == (
            11,
            12,
        )
        assert new_processing.pop("call_records") == []
        assert new_processing == old_processing, record_id
        for was, now in zip(old_versions, new_versions, strict=True):
            kept = {name: value for name, value in was.items() if name not in RETIRED_FIELDS}
            kept.pop("meaning_referents")
            now.pop("meaning_referents")
            assert now.pop("unclear") == []
            assert now == kept, record_id


async def test_the_walk_resumes_where_it_stood(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them, and
    waits at the open episode (ADR-0286 §5)."""
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
    finally:
        store.close()
    read = [record.id for record in rest.records]
    assert "mem-episode" not in read
    assert "mem-episode-understood" not in read
    assert "mem-episode-open" not in read


def test_a_record_the_upgrade_cannot_read_leaves_the_file_as_it_was_found(legacy: Path) -> None:
    """ADR-0326 §4:3: a version whose referent no build wrote is refused as the store's
    error, every row rewritten before it rolls back, and the open holds no lock."""
    with sqlite3.connect(legacy) as conn:
        (data,) = conn.execute(
            "SELECT data FROM records WHERE id = ?", ("mem-episode-open",)
        ).fetchone()
        stored = json.loads(data)
        stored["processing_record"]["understanding"][0]["references"][0]["referents"][0]["kind"] = (
            "neither"
        )
        conn.execute(
            "UPDATE records SET data = ? WHERE id = ?", (json.dumps(stored), "mem-episode-open")
        )
    conn.close()
    before = _raw_rows(legacy)

    with pytest.raises(MemoryStoreError, match="could not be decoded"):
        _open(legacy)

    assert _label(legacy) == PARTIES_RECORD_FORMAT
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
    """A record already in ADR-0353's shape comes back unchanged, reporting no change."""
    rows = _raw_rows(_FIXTURE)
    stored = json.loads(rows["mem-episode-understood"][1])
    assert understood_episode(stored)
    carried = json.dumps(stored)
    assert not understood_episode(stored)
    assert json.dumps(stored) == carried
    assert not understood_episode(json.loads(rows["mem-episode"][1]))
    assert not understood_episode(json.loads(rows["mem-episode-omitted"][1]))


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade."""
    path = tmp_path / "memory.db"
    _open(path).close()
    assert _label(path) == MEMORY_RECORD_FORMAT


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 20, so it refuses the file at 21."""
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
                }
            ),
        )
