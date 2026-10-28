"""ADR-0326 §4:2's test, for ADR-0345 §13: a file the previous release wrote is upgraded.

``tests/memory/legacy/memory-before-adr-0345.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``2f06b829``, through its public ``add`` and
``advance_walk``, at the label ``15``), never by hand-built SQL. It holds what that
build's ``scripts/upgrade_stores.py`` memory writer wrote, with an eight-dimension
hashing embedder: a memory the user said about Ada and filed under ``family``, one a
remember call backs, one the user said and pinned, three episodes and a walk advanced
past two records. Beside them, added through the same ``add``: a forward from a claimed
sender, a page's evidence item naming its source, an observer's inference backing a
memory as worded, and a memory whose episodes were never held.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop nothing (§4:4), and give every support the holder §2's table gives it, from the
record it points at as this file holds it (§13:1) or from its origin alone where that
record is gone (§13:2). ``about_person`` becomes ``subjects``, each topic a label added by
``migration``, and no memory gains a mark; every support keeps its direction and its
backing, so the inference keeps backing its memory (§13:4).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlite_vec
from memory_continuing_carry import carried, continues_recorded
from memory_parties_carry import holds, origin_recorded, parties_carried

from ai_assistant.core.errors import IncompatibleStateError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodicMemory,
    Memory,
    MemoryRecord,
    MemoryWriterName,
    StatementPart,
    SupportHolder,
    SupportOrigin,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    EPISODE_RECORD_FORMAT,
    JOINED_RECORD_FORMAT,
    MEMORIES_RECORD_FORMAT,
    MEMORY_RECORD_FORMAT,
    PINNED_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0345.db"

#: The instant the head opens the file at: a day after the previous release wrote it.
_NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)

_OWNER = SupportHolder.person(OWNER_PERSON_ID)

_MEMORIES = {
    "mem-said",
    "mem-remembered",
    "mem-pinned",
    "mem-forward",
    "mem-page",
    "mem-drawn",
    "mem-gone",
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


def _holders(record: MemoryRecord) -> list[SupportHolder | None]:
    assert isinstance(record, Memory)
    return [one.holder for one in record.supports]


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label, its memories carry no holder, subject field or mark."""
    assert _label(_FIXTURE) == PINNED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    memories = {key for key, (kind, _, _, _) in rows.items() if kind == "memory"}
    assert memories == _MEMORIES
    for key in memories:
        stored = json.loads(rows[key][1])
        assert "about_person" in stored
        assert "topics" in stored
        assert "subjects" not in stored
        assert all("holder" not in one for one in stored["supports"])
    said = json.loads(rows["mem-said"][1])
    assert (said["about_person"], said["topics"]) == ("Ada", ["family"])


async def test_the_upgrade_assigns_holders_by_the_table(legacy: Path) -> None:
    """§13:1, §13:2: each support's holder is §2's table's, from the record it points at."""
    exported = await _exported(legacy)

    assert _holders(exported["mem-said"]) == [_OWNER]
    assert _holders(exported["mem-remembered"]) == [
        SupportHolder.statement(StatementPart.REMEMBER_CALL)
    ]
    assert _holders(exported["mem-pinned"]) == [_OWNER, _OWNER]
    # A forward's claimed sender, read off the episode the file holds (§2:7).
    assert _holders(exported["mem-forward"]) == [SupportHolder.source("4242", claimed=True)]
    # The source the evidence item's record names, established.
    assert _holders(exported["mem-page"]) == [SupportHolder.source("staff-page", claimed=False)]
    # The user's message whose episode is gone is still the owner's: the origin alone
    # decides it; an outside input whose episode is gone is unknown (§13:2).
    assert _holders(exported["mem-gone"]) == [_OWNER, SupportHolder.unknown()]


async def test_an_upgraded_memory_an_inference_backs_keeps_that_backing(legacy: Path) -> None:
    """§13:4: the assistant's statement among its holders, its backing and standing kept."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    drawn = exported["mem-drawn"]
    assert isinstance(drawn, Memory)
    inference = next(
        one for one in drawn.supports if one.origin is SupportOrigin.OBSERVER_INFERENCE
    )
    assert inference.backs_as_worded
    assert inference.holder == SupportHolder.statement(StatementPart.OBSERVER_INFERENCE)
    assert drawn.holders == (SupportHolder.statement(StatementPart.OBSERVER_INFERENCE),)
    assert drawn.marks == ()
    assert _raw_rows(legacy)["mem-drawn"][3] == before["mem-drawn"][3]


async def test_a_subject_and_topics_are_carried_as_subjects_and_labels(legacy: Path) -> None:
    """§13:1, §10:2: ``about_person`` becomes ``subjects``, a topic a label by migration."""
    exported = await _exported(legacy)

    said = exported["mem-said"]
    assert isinstance(said, Memory)
    assert (said.subjects, said.involved, said.marks) == (("Ada",), None, ())
    assert [(one.text, one.added_by, one.episode, one.added_at) for one in said.labels] == [
        ("family", MemoryWriterName.MIGRATION, None, _NOW)
    ]
    for key in _MEMORIES - {"mem-said"}:
        other = exported[key]
        assert isinstance(other, Memory)
        assert (other.subjects, other.involved, other.labels, other.marks) == (
            None,
            None,
            (),
            (),
        )


async def test_every_record_reads_back_with_nothing_dropped(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: every row is kept; an episode's bytes and every revision unchanged."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(exported) == set(before) == set(after)
    for record_id, (kind, data, revision, band) in before.items():
        assert after[record_id][2] == revision
        assert after[record_id][3] == band
        if kind != "memory" and origin_recorded(data):
            # ADR-0351 §9: the chain ends in carrying the trigger's origin onto its
            # parties, and, before it, ``continues`` onto a sequence (ADR-0349 §10:6).
            holds(json.loads(after[record_id][1]), parties_carried(carried(json.loads(data))))
            continue
        if kind != "memory" and continues_recorded(data):
            # ADR-0349 §10:6: the chain ends in carrying ``continues`` onto a sequence.
            # Rewritten as the store writes a record, so it may spell out fields added
            # since at their defaults: it reads back as the carried record does.
            assert EpisodicMemory.model_validate_json(after[record_id][1]) == (
                EpisodicMemory.model_validate_json(json.dumps(carried(json.loads(data))))
            )
            continue
        if kind != "memory":
            assert after[record_id] == (kind, data, revision, band)
            continue
        stored: dict[str, Any] = json.loads(data)
        upgraded = exported[record_id]
        assert isinstance(upgraded, Memory)
        assert upgraded.content == stored["content"]
        assert [one.points_at.model_dump(mode="json") for one in upgraded.supports] == [
            one["points_at"] for one in stored["supports"]
        ]
        assert [(one.direction.value, one.backs_as_worded) for one in upgraded.supports] == [
            (one["direction"], one["backs_as_worded"]) for one in stored["supports"]
        ]
        assert len(upgraded.operations) == len(stored["operations"])


async def test_the_walk_resumes_where_it_stood(legacy: Path) -> None:
    """The walk the previous release advanced past two records resumes after them."""
    store = _open(legacy)
    try:
        rest = await store.walk_records("upgrade-check", limit=50)
        ids = [record.id for record in rest.records]
    finally:
        store.close()
    assert "mem-said" not in ids
    assert "mem-gone" in ids


async def test_the_label_advances_and_a_second_open_changes_nothing(legacy: Path) -> None:
    """§13:3: the file is upgraded once, to the new label."""
    await _exported(legacy)
    once = (_label(legacy), _raw_rows(legacy))
    assert once[0] == MEMORY_RECORD_FORMAT

    await _exported(legacy)

    assert (_label(legacy), _raw_rows(legacy)) == once


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 15, so it refuses the file at 16."""
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
                }
            ),
        )


async def test_a_label_written_after_the_upgrade_is_embedded(legacy: Path) -> None:
    """§7:4: the store embeds a memory's labels at its next write, a carried one included."""
    store = _open(legacy)
    try:
        said = await store.get("mem-said")
        assert isinstance(said, Memory)
        await store.add(said)
    finally:
        store.close()
    conn = sqlite3.connect(legacy)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        rows = conn.execute(
            "SELECT l.text, (SELECT COUNT(*) FROM vec_situation_labels v "
            "WHERE v.rowid = l.label_rowid) FROM situation_labels l "
            "JOIN records r ON r.rowid = l.record_rowid WHERE r.id = 'mem-said'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("family", 1)]
