"""ADR-0326 §4:2's test, for ADR-0328 §16: a file the previous release wrote is upgraded.

``tests/memory/legacy/memory-before-adr-0328.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``bc74b6ac``, through its public ``add`` and
``advance_walk``, at the label ``12``), never by hand-built SQL. It holds every kind of
record that release could store: two episodes (one an activation's, with its processing
record), five semantic records (asserted, inferred citing two held episodes and one gone,
inferred over outside content, attested by a source with a retention deadline, and one
whose validity had closed), two preference records (one with a context and a strength,
one plain) and two procedural records (one with steps, one with none); and a walk
advanced past three of them.

The head opens a copy and must upgrade it in place, by §16's table: never refuse it
(§16:8), drop nothing (§16:1), and leave every episode as it was (§16:7).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Attestation,
    BeliefBand,
    EpisodicMemory,
    LegacyPart,
    Memory,
    MemoryOperationKind,
    MemoryStanding,
    MemoryStatus,
    MemoryWriterName,
    PlacementReach,
    PlacementSetter,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
)
from ai_assistant.memory import SqliteMemoryStore, sqlite_store
from ai_assistant.memory._episode_format import EPISODE_RECORD_FORMAT, MEMORY_RECORD_FORMAT
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "memory-before-adr-0328.db"

#: The instant the head opens the file at: the day after the previous release wrote it.
_NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)

#: The records §16 upgrades, and the wording §16:3 gives each.
_WORDINGS = {
    "semantic-asserted": "The user's sister is called Ada.",
    "semantic-inferred": "The user lives in Lisbon.",
    "semantic-tainted": "The user is flying to Porto on Friday.",
    "semantic-external": "Dentist appointment on Thursday at 9.",
    "semantic-retired": "The user works at Acme.",
    "preference-context": "The user prefers mornings. (context: appointments)",
    "preference-plain": "The user likes short answers.",
    "procedural-steps": (
        "Booking a trip. Steps: 1. Check the calendar; 2. Ask about the budget; "
        "3. Book the cheapest flight"
    ),
    "procedural-bare": "Answering in Portuguese.",
}

_EPISODES = ("episode-bare", "activation:act-legacy-1")


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _raw_rows(path: Path) -> dict[str, tuple[str, dict[str, Any], int]]:
    """Every row's kind, decoded blob and revision, read out of band."""
    with sqlite3.connect(path) as conn:
        return {
            str(record_id): (str(kind), json.loads(data), int(revision))
            for record_id, kind, data, revision in conn.execute(
                "SELECT id, kind, data, revision FROM records"
            )
        }


def _with_later_defaults(stored: dict[str, Any]) -> dict[str, Any]:
    """An episode's stored blob, with the defaults of fields added since it was written.

    And as ADR-0351 §9 carries it: its trigger's ``origin`` gives way to its parties,
    the owner's for a hub chat input of the origin ``user`` (§9:2), which is the one
    activation this file holds.
    """
    record = stored.get("processing_record")
    if record is None:
        return stored
    assert record["trigger"]["origin"] == "user"  # the hub chat's, §9:2
    trigger = {name: one for name, one in record["trigger"].items() if name != "origin"}
    owner = SupportHolder.person(OWNER_PERSON_ID).model_dump(mode="json")
    added: dict[str, Any] = {"joined": [], "stories_position": None, "taken_over_by": None}
    return {
        **stored,
        "processing_record": added | record | {"trigger": trigger | {"parties": [owner]}},
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


async def _upgraded(path: Path) -> dict[str, Any]:
    store = _open(path)
    try:
        return {record.id: record for record in await store.export()}
    finally:
        store.close()


def test_the_fixture_is_what_the_previous_release_wrote() -> None:
    """The file is at the previous label and holds each kind it could store."""
    assert _label(_FIXTURE) == EPISODE_RECORD_FORMAT
    kinds = {kind for kind, _, _ in _raw_rows(_FIXTURE).values()}
    assert kinds == {"episodic", "semantic", "preference", "procedural"}


async def test_the_file_is_upgraded_in_place_and_its_label_advances(legacy: Path) -> None:
    """§16:1, §16:8: the head opens the file, upgrades it, and never refuses it."""
    before = _raw_rows(legacy)

    exported = await _upgraded(legacy)

    # ADR-0326 §4:5: the upgrades chain, so the file reaches this build's own label,
    # through ADR-0328's and then ADR-0332's.
    assert _label(legacy) == MEMORY_RECORD_FORMAT
    # Nothing dropped: every row is still there, at its id (ADR-0326 §4:4).
    assert set(_raw_rows(legacy)) == set(before)
    # The retired record is history, which export still shows.
    assert set(exported) == set(before)


async def test_no_episode_is_rewritten(legacy: Path) -> None:
    """§16:7: an episode keeps every field it had, its processing record included.

    The chain goes on to ADR-0351 §9's upgrade, which rewrites the activation's episode
    to carry its trigger's parties in place of its origin; the bare episode, which has no
    processing record, is byte for byte what it was.
    """
    before = _raw_rows(legacy)

    exported = await _upgraded(legacy)

    after = _raw_rows(legacy)
    for record_id in _EPISODES:
        assert after[record_id][0] == before[record_id][0]
        if "processing_record" not in before[record_id][1]:
            assert after[record_id][:2] == before[record_id][:2]
        episode = exported[record_id]
        assert isinstance(episode, EpisodicMemory)
        # A field a later decision adds at its default is the one difference: ADR-0332
        # §7:2's ``joined`` and ADR-0347 §4:1's ``stories_position`` on the processing
        # record.
        assert episode.model_dump(mode="json", exclude={"revision"}) == _with_later_defaults(
            before[record_id][1]
        )


async def test_each_legacy_record_becomes_a_memory_at_its_id(legacy: Path) -> None:
    """§16:2-§16:6, record by record."""
    before = _raw_rows(legacy)

    exported = await _upgraded(legacy)

    after = _raw_rows(legacy)
    for record_id, wording in _WORDINGS.items():
        _, stored, revision = before[record_id]
        upgraded = exported[record_id]
        assert isinstance(upgraded, Memory), record_id
        assert after[record_id][0] == "memory"
        # §16:3: the wording.
        assert upgraded.content == wording
        # §16:2: the envelope's fields, unchanged; ``about_person`` and ``topics`` are
        # carried as ADR-0345 §13:1 and §10:2 carry them.
        for field in ("validity", "expires_at", "placement"):
            assert upgraded.model_dump(mode="json")[field] == stored[field], (record_id, field)
        about = stored.get("about_person")
        assert upgraded.subjects == (None if about is None else (about,)), record_id
        assert [label.text for label in upgraded.labels] == list(stored.get("topics") or ())
        # The upgrade is no caller's write: the revision is carried, not reissued.
        assert upgraded.revision == revision
        # §16:4: one legacy support pointing at the record's own id, carrying it whole.
        (support,) = upgraded.supports
        assert support.points_at == LegacyPart(record=record_id)
        assert upgraded.model_dump(mode="json")["supports"][0]["carries"] == stored
        assert support.direction is SupportDirection.FOR
        assert support.backs_as_worded
        assert support.how_sure is None
        assert support.added_by is MemoryWriterName.MIGRATION
        assert support.added_at == _NOW
        # §16:6: the create cites it, by migration, at the record's last_updated.
        create = upgraded.operations[0]
        assert create.kind is MemoryOperationKind.CREATE
        assert create.cites == support.points_at
        assert create.by is MemoryWriterName.MIGRATION
        assert create.at == _instant(stored["provenance"]["last_updated"])
        # §16:10: legacy, at inference.
        assert upgraded.is_legacy
        assert upgraded.standing is MemoryStanding.INFERENCE
        assert upgraded.band is BeliefBand.DERIVED


async def test_a_legacy_supports_origin_follows_the_records_outside_content(
    legacy: Path,
) -> None:
    """§16:4: ``legacy_outside`` where the record rested on recorded external content."""
    exported = await _upgraded(legacy)

    outside = {
        record_id
        for record_id in _WORDINGS
        if exported[record_id].supports[0].origin is SupportOrigin.LEGACY_OUTSIDE
    }
    assert outside == {"semantic-tainted", "semantic-external"}
    for record_id in set(_WORDINGS) - outside:
        assert exported[record_id].supports[0].origin is SupportOrigin.LEGACY
    assert exported["semantic-tainted"].rests_on_outside_content
    assert not exported["semantic-asserted"].rests_on_outside_content


async def test_a_legacy_supports_when_and_source_details(legacy: Path) -> None:
    """§16:5: the latest held cited episode, else the confirming instant, else unknown."""
    exported = await _upgraded(legacy)

    def when(record_id: str) -> datetime | None:
        upgraded = exported[record_id]
        assert isinstance(upgraded, Memory)
        return upgraded.supports[0].when

    # Cites the activation's episode, the bare episode and one the store does not
    # hold: the latest held one's occurred_at.
    assert when("semantic-inferred") == datetime(2026, 9, 28, 12, tzinfo=UTC)
    assert when("preference-context") == datetime(2026, 9, 26, 10, tzinfo=UTC)
    # Cites nothing, and was confirmed: its last_confirmed_at.
    assert when("semantic-asserted") == datetime(2026, 9, 29, 12, tzinfo=UTC)
    assert when("semantic-external") == datetime(2026, 10, 1, 1, tzinfo=UTC)
    # Neither: unknown.
    assert when("procedural-bare") is None
    assert exported["semantic-external"].supports[0].source_details == Attestation(
        reported_by="work-calendar", reported_at=datetime(2026, 10, 1, 1, tzinfo=UTC)
    )
    assert exported["semantic-asserted"].supports[0].source_details is None


async def test_a_record_whose_validity_had_ended_is_ended(legacy: Path) -> None:
    """§16:6: an end at the validity end, citing the same support, and ``ended``."""
    exported = await _upgraded(legacy)

    retired = exported["semantic-retired"]
    assert retired.status is MemoryStatus.ENDED
    end = retired.operations[-1]
    assert end.kind is MemoryOperationKind.END
    assert end.cites == retired.supports[0].points_at
    assert end.at == datetime(2026, 9, 27, 12, tzinfo=UTC)
    assert end.by is MemoryWriterName.MIGRATION
    for record_id in set(_WORDINGS) - {"semantic-retired"}:
        assert exported[record_id].status is MemoryStatus.CURRENT
        assert len(exported[record_id].operations) == 1


async def test_the_envelope_survives_as_it_was(legacy: Path) -> None:
    """§16:2's fields, on the records that set them to something other than the default."""
    exported = await _upgraded(legacy)

    asserted = exported["semantic-asserted"]
    assert isinstance(asserted, Memory)
    # ADR-0345 §13:1, §10:2: the subject is carried as ``subjects``, the topic as a label
    # added by ``migration``.
    assert asserted.subjects == ("Ada",)
    assert asserted.involved is None
    assert [(one.text, one.added_by) for one in asserted.labels] == [
        ("family", MemoryWriterName.MIGRATION)
    ]
    placement = exported["semantic-inferred"].placement
    assert placement.reach is PlacementReach.OWNER
    assert placement.set_by is PlacementSetter.DERIVED
    assert exported["semantic-external"].expires_at == datetime(2026, 10, 31, 12, tzinfo=UTC)


async def test_the_upgraded_store_reads_as_it_did(legacy: Path) -> None:
    """Every read still answers: the walk resumes where it stood, and search finds by content.

    A record's vector is kept: it embeds the record's content, which a search for
    that content still finds.
    """
    store = _open(legacy)
    try:
        # The walk reads what is readable: the retired record is history (ADR-0045 §6).
        rest = await store.walk_records("legacy-walk", limit=50)
        assert [record.id for record in rest.records] == [
            "semantic-inferred",
            "semantic-tainted",
            "semantic-external",
            "preference-context",
            "preference-plain",
            "procedural-steps",
            "procedural-bare",
        ]
        found = await store.search("The user's sister is called Ada.", limit=1)
        assert [record.id for record in found.records] == ["semantic-asserted"]
        listed = {record.id for record in await store.list_beliefs()}
        # Memories only, the retired one not live; never an episode (§11:2).
        assert listed == set(_WORDINGS) - {"semantic-retired"}
    finally:
        store.close()


async def test_the_upgrade_persists_each_memorys_band_for_band_scoped_reads(
    legacy: Path,
) -> None:
    """§7:11's persisted band is written for every upgraded memory, as §6 computes it.

    Every legacy memory stands at inference (§16:10), so the formerly asserted and
    attested records become ``DERIVED`` in the column band-scoped reads filter on, and
    a ``DERIVED`` search and listing find them while an ``ASSERTED`` or ``ATTESTED`` one
    finds none.
    """
    store = _open(legacy)
    try:
        listed = {record.id for record in await store.list_beliefs(bands=[BeliefBand.DERIVED])}
        assert listed == set(_WORDINGS) - {"semantic-retired"}
        for band in (BeliefBand.ASSERTED, BeliefBand.ATTESTED):
            assert await store.list_beliefs(bands=[band]) == []
        found = await store.search(
            "The user's sister is called Ada.", limit=1, bands=[BeliefBand.DERIVED]
        )
        assert [record.id for record in found.records] == ["semantic-asserted"]
        found = await store.search(
            "Dentist appointment on Thursday at 9.", limit=1, bands=[BeliefBand.DERIVED]
        )
        assert [record.id for record in found.records] == ["semantic-external"]
    finally:
        store.close()
    with sqlite3.connect(legacy) as conn:
        bands = dict(conn.execute("SELECT id, band FROM records WHERE kind = 'memory'"))
    assert bands == dict.fromkeys(_WORDINGS, BeliefBand.DERIVED.value)


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """The upgrade runs once: a file already at the new label is not upgraded again."""
    await _upgraded(legacy)
    once = _raw_rows(legacy)

    await _upgraded(legacy)

    assert _raw_rows(legacy) == once


def test_an_upgrade_that_cannot_finish_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """ADR-0326 §4:3: an upgrade completes or leaves the file untouched.

    One legacy record's blob is made undecodable out of band, after another has
    already been reached, so the upgrade fails partway through its own transaction.
    """
    with sqlite3.connect(legacy) as conn:
        conn.execute(
            "UPDATE records SET data = ? WHERE id = 'procedural-bare'", ('{"kind": "procedural"}',)
        )
    before = legacy.read_bytes()

    with pytest.raises(MemoryStoreError, match="ADR-0328"):
        _open(legacy)

    assert legacy.read_bytes() == before
    assert _label(legacy) == EPISODE_RECORD_FORMAT


#: A batch small enough that the fixture's rows span three (#3188 item 1): the upgrade
#: reads the file in batches of ``_BACKFILL_CHUNK`` rows, which at its own size holds the
#: whole fixture in its first.
_SMALL_BATCH = 4


@pytest.fixture
def small_batches(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower the upgrade's batch size, so the fixture spans more than two batches."""
    rows = len(_raw_rows(_FIXTURE))
    assert rows > 2 * _SMALL_BATCH, "the fixture no longer spans three batches"
    monkeypatch.setattr(sqlite_store, "_BACKFILL_CHUNK", _SMALL_BATCH)
    return _SMALL_BATCH


def _rowid(path: Path, record_id: str) -> int:
    with sqlite3.connect(path) as conn:
        (rowid,) = conn.execute("SELECT rowid FROM records WHERE id = ?", (record_id,)).fetchone()
    return int(rowid)


async def test_the_upgrade_continues_past_its_first_batch(legacy: Path, small_batches: int) -> None:
    """Every batch is upgraded, not the first alone, and the label advances after the last.

    The fixture's legacy records run through all three batches, the last of them in the
    last, so an upgrade that stopped after one batch, or skipped a row between two,
    would leave a legacy record unconverted under the advanced label.
    """
    assert _rowid(legacy, "procedural-bare") > 2 * small_batches

    _open(legacy).close()

    after = _raw_rows(legacy)
    assert {record_id for record_id, (kind, _, _) in after.items() if kind == "memory"} == set(
        _WORDINGS
    )
    with sqlite3.connect(legacy) as conn:
        unbanded = [row for (row,) in conn.execute("SELECT id FROM records WHERE band IS NULL")]
    assert unbanded == []
    assert _label(legacy) == MEMORY_RECORD_FORMAT
    exported = await _upgraded(legacy)
    assert {record_id: exported[record_id].content for record_id in _WORDINGS} == _WORDINGS


def test_a_failure_in_a_later_batch_rolls_back_the_batches_before_it(
    legacy: Path, small_batches: int
) -> None:
    """ADR-0326 §4:3, across batches: a later batch's failure leaves the file as it was.

    The undecodable record is in the last batch, after two whole batches have been
    upgraded, so an upgrade that committed batch by batch would keep them, and one that
    read the first batch alone would never reach the record and advance the label over
    it.
    """
    assert _rowid(legacy, "procedural-bare") > 2 * small_batches
    with sqlite3.connect(legacy) as conn:
        conn.execute(
            "UPDATE records SET data = ? WHERE id = 'procedural-bare'", ('{"kind": "procedural"}',)
        )
    before = legacy.read_bytes()

    with pytest.raises(MemoryStoreError, match="ADR-0328"):
        _open(legacy)

    assert legacy.read_bytes() == before
    assert _label(legacy) == EPISODE_RECORD_FORMAT
    assert {kind for kind, _, _ in _raw_rows(legacy).values()} == {
        "episodic",
        "semantic",
        "preference",
        "procedural",
    }
