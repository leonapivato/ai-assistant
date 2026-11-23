"""ADR-0326 §4:2's test, for ADR-0368 §2's episode record: a file the previous release wrote.

``tests/memory/legacy/memory-before-adr-0368.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``e6a25ddac``, through its public ``add``, at the
label ``23``), never by hand-built SQL, with an eight-dimension hashing embedder and
invented data. It holds one ended episode of each kind of input that build took: the hub
chat's; the line's, of a message the owner wrote and a forward, with two inputs that
joined it, from the line and from the hub chat; an informational event's; a task's
occurrence; and an approval's outcome. Beside them, an **open** episode on the hub chat,
as a hub stopped mid-activation leaves it, which an approval's outcome joined; a bare
episode with no processing record; and a memory resting on the hub chat's episode.

No record that build wrote holds who sent an input or a work's three facts, and every
one this build writes carries them: a build at 23 would fail on the read, which is why
the label moves (ADR-0326 §2:3, §5:3). The head opens a copy and must upgrade it in
place: never refuse it (§5:1), drop nothing (§4:4), and carry each episode with **what
the channel-type rule said of it** (#3642: "A work from before the upgrade still reads
whole. Its three facts are filled in from what was recorded then"), which is held here
against that rule as it still runs (``work_facts.todays_path``). The previous release,
which serves 12 to 23, refuses the upgraded file (§5:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from memory_facts_carry import episode_without_facts

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputSender,
    Memory,
    MemoryRecord,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import (
    MEMORY_RECORD_FORMAT,
    MEMORY_RECORD_FORMATS,
    SHOWED_RECORD_FORMAT,
    inspect_existing,
)
from ai_assistant.memory._facts_upgrade import facts_episode
from ai_assistant.models import HashingEmbedder
from ai_assistant.orchestration.work_facts import disagreements, todays_path
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0368.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)

#: The episodes with a processing record, which the upgrade rewrites.
_REWRITTEN: Final = (
    "mem-chat",
    "mem-line",
    "mem-event",
    "mem-task",
    "mem-approval",
    "mem-open",
)

#: The records the upgrade leaves byte for byte: the bare episode and the memory.
_UNTOUCHED: Final = ("mem-bare", "mem-said")

_OPEN: Final = "mem-open"

#: Who sent each message of the hub chat and the line, as the rule had it.
_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)

#: The owner's work, carrying the owner's authority: an owner's message they wrote.
_OWNERS: Final = WorkFacts(
    for_whom=WorkFor.for_person(OWNER_PERSON_ID),
    authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
    level=Sureness.NORMAL,
)

#: The owner's work, carrying no authority: a forward's, at the owner's level.
_FORWARDED: Final = _OWNERS.model_copy(update={"authority": WorkAuthority.none()})

#: The owner's work no person sent: an event's, a task's or an approval's.
_SENT_BY_NO_ONE: Final = WorkFacts(
    for_whom=WorkFor.for_person(OWNER_PERSON_ID),
    authority=WorkAuthority.none(),
    level=Sureness.NONE,
)


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


def _mentions(stored: object, key: str) -> bool:
    """Whether any dict inside ``stored`` holds ``key``."""
    if isinstance(stored, dict):
        return key in stored or any(_mentions(one, key) for one in stored.values())
    if isinstance(stored, list):
        return any(_mentions(one, key) for one in stored)
    return False


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
    """The file is at the previous label, one episode is open, and no record holds who sent
    an input or a work's facts."""
    assert _label(_FIXTURE) == SHOWED_RECORD_FORMAT
    rows = _raw_rows(_FIXTURE)
    assert set(rows) == {*_REWRITTEN, *_UNTOUCHED}
    assert [record_id for record_id, row in rows.items() if row[4]] == [_OPEN]
    for record_id, row in rows.items():
        stored = json.loads(row[1])
        for key in ("senders", "sender", "facts"):
            assert not _mentions(stored, key), (record_id, key)


async def test_every_record_reopens_whole_with_what_the_rule_said_of_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: every record reads back, each episode holding everything it
    held, with who sent it and its facts added as the channel-type rule had them."""
    before = _raw_rows(legacy)

    exported = await _exported(legacy)

    assert _label(legacy) == MEMORY_RECORD_FORMAT
    assert set(exported) == set(before)
    for record_id in _REWRITTEN:
        stored = json.loads(before[record_id][1])
        stored.pop("revision", None)
        read = exported[record_id].model_dump(mode="json", exclude={"revision"})
        _holds(episode_without_facts(read), stored)

    chat = _processing(exported["mem-chat"])
    assert chat.trigger.senders == (_OWNER,)
    assert chat.facts == _OWNERS

    # The line: the forward was sent by the owner, who forwarded it, so both messages
    # record the owner; its parties are not the owner's alone, so it carries none.
    line = _processing(exported["mem-line"])
    assert line.trigger.senders == (_OWNER,)
    assert [one.sender for one in line.trigger.messages] == [_OWNER, _OWNER]
    assert line.facts == _FORWARDED
    assert [one.senders for one in line.joined] == [(_OWNER,), (_OWNER,)]
    assert [one.facts for one in line.joined] == [_FORWARDED, _FORWARDED]
    assert line.facts_now == _FORWARDED

    for record_id in ("mem-event", "mem-task", "mem-approval"):
        held = _processing(exported[record_id])
        assert held.trigger.senders == (), record_id
        assert held.facts == _SENT_BY_NO_ONE, record_id

    # The open episode: an approval's outcome joined it, sent by no person.
    opened = _processing(exported[_OPEN])
    assert opened.is_open
    assert opened.facts == _OWNERS
    (approval,) = opened.joined
    assert [one.sender for one in approval.messages] == [None]
    assert approval.facts == _OWNERS

    said = exported["mem-said"]
    assert isinstance(said, Memory)


async def test_the_facts_carried_are_what_todays_path_says(legacy: Path) -> None:
    """#3642: the facts an old work is given are what the rule still running says of it,
    so the readers can move to the facts without an old work reading otherwise."""
    exported = await _exported(legacy)

    for record_id in _REWRITTEN:
        record = _processing(exported[record_id])
        assert record.facts is not None
        assert disagreements(record.facts, todays_path(record.trigger)) == (), record_id


async def test_every_other_row_is_kept_and_the_rest_byte_for_byte(legacy: Path) -> None:
    """ADR-0326 §4:4: a rewritten row keeps its kind, revision, band and openness, and
    every row the upgrade does not rewrite is byte for byte what it was."""
    before = _raw_rows(legacy)

    await _exported(legacy)

    after = _raw_rows(legacy)
    assert set(after) == set(before)
    for record_id in _REWRITTEN:
        assert (after[record_id][0], *after[record_id][2:]) == (
            before[record_id][0],
            *before[record_id][2:],
        )
    for record_id in _UNTOUCHED:
        assert after[record_id] == before[record_id], record_id


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
    """ADR-0326 §5:3: the previous release opens 12 to 23, so it refuses the file at 24."""
    await _exported(legacy)

    with pytest.raises(IncompatibleStateError):
        inspect_existing(str(legacy), accepted=MEMORY_RECORD_FORMATS - {MEMORY_RECORD_FORMAT})


def test_a_record_the_upgrade_cannot_read_leaves_the_file_as_it_was(legacy: Path) -> None:
    """ADR-0326 §4:3: an episode whose record holds no trigger fails the open, and the
    file is left as the store found it, at its label, every row unchanged."""
    with sqlite3.connect(legacy) as conn:
        (data,) = conn.execute("SELECT data FROM records WHERE id = 'mem-chat'").fetchone()
        stored: dict[str, Any] = json.loads(data)
        stored["processing_record"]["trigger"] = "not a trigger"
        conn.execute("UPDATE records SET data = ? WHERE id = 'mem-chat'", (json.dumps(stored),))
    before = (_label(legacy), _raw_rows(legacy))

    with pytest.raises(MemoryStoreError):
        _open(legacy)

    assert (_label(legacy), _raw_rows(legacy)) == before


def test_the_carry_is_idempotent() -> None:
    """A record carried once comes back the same, and reports no change."""
    rows = _raw_rows(_FIXTURE)
    for record_id in _REWRITTEN:
        stored = json.loads(rows[record_id][1])
        assert facts_episode(stored), record_id
        again = json.loads(json.dumps(stored))
        assert not facts_episode(again), record_id
        assert again == stored, record_id
    bare = json.loads(rows["mem-bare"][1])
    assert not facts_episode(bare)
