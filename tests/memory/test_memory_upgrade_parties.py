"""ADR-0326 §4:2's test, for ADR-0351 §9's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0351.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``c81bed5f7``, through its public ``add`` and
``advance_walk``, at the label ``19``), never by hand-built SQL, with an eight-dimension
hashing embedder. It holds an episode of every row of ADR-0351 §9:2's rule, each with its
stored origin: the hub chat's, one on a new conversation, and an open one, at ``user``,
the first carrying two understanding versions and a join from the hub chat and one from
the line; the line's plain input at ``user``, and its input of your note beside two
forwards, one naming its sender's account and one not, at ``outside``, with a version;
an informational event's at ``outside``; and the Task Scheduler's at ``assistant`` and,
for a marked task, at ``outside``. Beside them, two the rule does not cover: a hub chat
input at ``outside``, and a doorbell's input recording a message and a forward, with a
join from the line. A bare episode with no processing record, and three memories whose
supports point at the hub chat's input, the forward and the note beside it, the last
recorded under the rule before ADR-0351 as ``outside_input`` held by unknown. A walk is
advanced past two records.

The head opens a copy and must upgrade it in place: never refuse it (§5:1), drop nothing
(§4:4), give each episode the parties its kind declares and each message its party
(ADR-0351 §9:1, §9:2), give every record the rule does not cover ``None`` (§9:3), rewrite
no support (§9:4) and mark no understanding version or joined input relayed (§9:6). The
previous release, which serves 12 to 19, then refuses the file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from memory_parties_carry import holds, origin_recorded, parties_carried

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputPart,
    Memory,
    MemoryRecord,
    MemorySupport,
    MemoryWriterName,
    StatementPart,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    input_support_origin,
    stamped_support,
    support_holder,
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
    TAKEN_OVER_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.memory._parties_upgrade import parties_episode
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0351.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 10, 27, 13, tzinfo=UTC)

_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
_SAM: Final = SupportHolder.source("77", claimed=True)
_UNKNOWN: Final = SupportHolder.unknown()
_STATEMENT: Final = SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION)

#: §9:2's rule, row by row: each episode's parties, its messages' and its joins'.
_DECLARED: Final[dict[str, tuple[tuple[SupportHolder, ...] | None, list[Any], list[Any]]]] = {
    "mem-episode-chat": ((_OWNER,), [], [[_OWNER], [_OWNER]]),
    "mem-episode-new-chat": ((_OWNER,), [], []),
    "mem-episode-open": ((_OWNER,), [], []),
    "mem-episode-line-plain": ((_OWNER,), [_OWNER], []),
    "mem-episode-line-forward": ((_OWNER, _SAM, _UNKNOWN), [_OWNER, _SAM, _UNKNOWN], []),
    "mem-episode-event": (
        (SupportHolder.source("informational_event:weather", claimed=False),),
        [],
        [],
    ),
    "mem-episode-task": ((_STATEMENT,), [], []),
    "mem-episode-marked": ((_STATEMENT, _UNKNOWN), [], []),
    # §9:3: the records the rule does not cover, each message and join's ``None`` too.
    "mem-episode-chat-outside": (None, [], []),
    "mem-episode-door": (None, [None, None], [[None]]),
}

_IDS: Final = {*_DECLARED, "mem-episode", "mem-said", "mem-forwarded", "mem-noted"}


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
    """The file is at the previous label, and every trigger records an origin, no parties."""
    assert _label(_FIXTURE) == TAKEN_OVER_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == _IDS
    for record_id in _DECLARED:
        trigger = json.loads(rows[record_id][1])["processing_record"]["trigger"]
        assert "origin" in trigger
        assert "parties" not in trigger
        assert all("party" not in one for one in trigger["messages"])
    assert rows["mem-episode-open"][4] == 1


async def test_every_row_of_the_rule_gets_its_parties_and_every_other_record_none(
    legacy: Path,
) -> None:
    """§9:1-§9:3: the trigger's parties, each message's party and each join's, as declared."""
    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    for record_id, (parties, messages, joins) in _DECLARED.items():
        processing = _processing(exported[record_id])
        assert processing.trigger.parties == parties, record_id
        assert [one.party for one in processing.trigger.messages] == messages, record_id
        assert [[one.party for one in join.messages] for join in processing.joined] == joins
        # §9:6: nothing stored before the decision is relayed.
        assert not any(one.relayed for one in processing.understanding)
        assert not any(one.relayed for one in processing.joined)
    assert _processing(exported["mem-episode-open"]).is_open
    bare = exported["mem-episode"]
    assert isinstance(bare, EpisodicMemory)
    assert bare.processing_record is None


async def test_a_record_the_rule_does_not_cover_reopens_and_each_part_is_held_by_unknown(
    legacy: Path,
) -> None:
    """§9:3, §7: it validates and reopens, and a support a write adds on each of its parts,
    a forward's included, takes ``outside_input`` and is held by unknown."""
    await _exported(legacy)
    store = _open(legacy)
    try:
        door = await store.get("mem-episode-door")
    finally:
        store.close()
    assert isinstance(door, EpisodicMemory)
    processing = _processing(door)
    assert processing.trigger.messages[1].forwarded_from is not None

    for message in (None, 0, 1):
        origin = input_support_origin(processing, message)
        added = MemorySupport(
            points_at=InputPart(episode=door.id, message=message),
            origin=origin,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=_NOW,
            added_at=_NOW,
            added_by=MemoryWriterName.OBSERVER,
        )
        assert (origin, stamped_support(added, door).holder) == (
            SupportOrigin.OUTSIDE_INPUT,
            _UNKNOWN,
        )


async def test_no_support_is_rewritten(legacy: Path) -> None:
    """§9:4: each memory's row is byte for byte what it was, its supports' holders included.

    The note beside the forward was recorded ``outside_input`` held by unknown under the
    rule before the decision, and keeps that, though a support a write adds on it now is
    yours; the rule the store's upgrade gives a stored support's holder by keeps it too.
    """
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    after = _raw_rows(legacy)
    for record_id in ("mem-said", "mem-forwarded", "mem-noted"):
        assert after[record_id] == before[record_id]
    held = {
        record_id: [(one.origin, one.holder) for one in record.supports]
        for record_id, record in exported.items()
        if isinstance(record, Memory)
    }
    assert held == {
        "mem-said": [(SupportOrigin.USER_MESSAGE, _OWNER)],
        "mem-forwarded": [(SupportOrigin.OUTSIDE_INPUT, _SAM)],
        "mem-noted": [(SupportOrigin.OUTSIDE_INPUT, _UNKNOWN)],
    }
    forward, noted = exported["mem-episode-line-forward"], exported["mem-noted"]
    assert isinstance(forward, EpisodicMemory)
    assert isinstance(noted, Memory)
    (stored,) = noted.supports
    assert support_holder(stored, forward) == stored.holder == _UNKNOWN
    assert input_support_origin(_processing(forward), 0) is SupportOrigin.USER_MESSAGE


async def test_only_the_episodes_with_a_processing_record_are_rewritten(legacy: Path) -> None:
    """ADR-0326 §4:4: every row is kept; a rewritten one keeps its kind, revision, band and
    openness, and every other row is byte for byte what it was."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(exported) == set(before) == set(after) == _IDS
    for record_id, row in before.items():
        if origin_recorded(row[1]):
            assert (after[record_id][0], *after[record_id][2:]) == (row[0], *row[2:])
            assert "origin" not in json.loads(after[record_id][1])["processing_record"]["trigger"]
        else:
            assert after[record_id] == row


async def test_every_record_reads_back_as_it_was_written(legacy: Path) -> None:
    """ADR-0326 §4:2: every record is read back whole, its trigger's origin carried away."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    for record_id, (_, data, revision, _, _) in before.items():
        record = exported[record_id]
        assert record.revision == revision
        stored: dict[str, Any] = parties_carried(json.loads(data))
        stored.pop("revision", None)
        holds(record.model_dump(mode="json", exclude={"revision"}), stored)


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
    assert "mem-episode-open" not in read


def test_a_record_the_upgrade_cannot_read_leaves_the_file_as_it_was_found(legacy: Path) -> None:
    """ADR-0326 §4:3: a forward whose sender no build wrote is refused as the store's
    error, every row rewritten before it rolls back, and the open holds no lock."""
    with sqlite3.connect(legacy) as conn:
        (data,) = conn.execute(
            "SELECT data FROM records WHERE id = ?", ("mem-episode-line-forward",)
        ).fetchone()
        stored = json.loads(data)
        stored["processing_record"]["trigger"]["messages"][1]["forwarded_from"]["account_id"] = (
            "broken"
        )
        conn.execute(
            "UPDATE records SET data = ? WHERE id = ?",
            (json.dumps(stored), "mem-episode-line-forward"),
        )
    conn.close()
    before = _raw_rows(legacy)

    with pytest.raises(MemoryStoreError, match="could not be decoded"):
        _open(legacy)

    assert _label(legacy) == TAKEN_OVER_RECORD_FORMAT
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
    """A record already carrying its parties comes back unchanged, reporting no change."""
    rows = _raw_rows(_FIXTURE)
    stored = json.loads(rows["mem-episode-line-forward"][1])
    assert parties_episode(stored)
    carried = json.dumps(stored)
    assert not parties_episode(stored)
    assert json.dumps(stored) == carried
    assert not parties_episode(json.loads(rows["mem-episode"][1]))


def test_a_fresh_store_is_written_at_the_new_label(tmp_path: Path) -> None:
    """A store first opened by this build has nothing to upgrade."""
    path = tmp_path / "memory.db"
    _open(path).close()
    assert _label(path) == MEMORY_RECORD_FORMAT


async def test_an_older_build_refuses_the_upgraded_file(legacy: Path) -> None:
    """ADR-0326 §5:3: the previous release opens 12 to 19, so it refuses the file at 20."""
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
                }
            ),
        )
