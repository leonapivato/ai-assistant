"""ADR-0326 §4:2's test, for #3205: a file holding findings from before their carry.

``tests/planning/legacy/plans-before-observation-carry.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``08685731``, through its public
``record_stop``, ``claim_activation_effect``, ``finish_activation_effect`` and
``write_observation``, at the label ``13``), never by hand-built SQL. Beside one stop
record and one effect record it holds five observation records (ADR-0329 §16:1): one
processed over two attempts, its findings covering a create, a track-record entry, a
replace naming two memories, a finding not kept and an ask; one waiting after a failed
attempt with a finding committed and one pending, written twice; one whose last attempt
was left open by a hub that stopped; one stuck with a pending finding; and one skipped.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1): carry every record
whole (§4:4), each finding reading back with ``supply`` and ``written`` empty since
nothing was recorded of either (ADR-0329 §12:6, §16:4), and with ADR-0346's
annotations, declines, unclear and asked empty too, move the label through 14 to 15, and leave
the file exactly as it found it where the open fails (§4:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    MemoryOperationKind,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    Placement,
    PlacementReach,
    PlacementSetter,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-observation-carry.db"

#: The instant the head opens the file at: the day after the previous release wrote it.
_NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)

_EPISODES = tuple(f"activation:act-legacy-{index}" for index in range(1, 6))


def _now() -> datetime:
    return _NOW


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "plans.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _label(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        (value,) = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return str(value)


def _dump(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every table's rows, read out of band and in a fixed order."""
    with sqlite3.connect(path) as conn:
        tables = [
            str(name)
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)  # noqa: S608 — names read from the file's own catalogue
            for table in tables
        }


def _blobs(path: Path) -> dict[str, dict[str, Any]]:
    """Each observation record's stored blob, by episode, as JSON."""
    with sqlite3.connect(path) as conn:
        return {
            str(episode): json.loads(str(data))
            for episode, data in conn.execute("SELECT episode_id, data FROM observations")
        }


def _with_empty_carry(blob: dict[str, Any]) -> dict[str, Any]:
    """A stored record as this build must read it: each finding's carry empty.

    And ADR-0346's fields empty with it: no decline on the record, no annotations on a
    finding, and no ``unclear`` and nothing ``asked`` on an outcome (§4:5, §4:6, §6:5).
    """
    return {
        **blob,
        "declines": [],
        "findings": [
            one
            | {
                "supply": None,
                "written": [],
                "annotations": None,
                "further_candidates": [],
                "framed": [],
                "outcome": None
                if one.get("outcome") is None
                else one["outcome"] | {"unclear": [], "asked": []},
            }
            for one in blob["findings"]
        ],
    }


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 13, the three record tables, and findings written with no carry."""
    dumped = _dump(_FIXTURE)
    blobs = _blobs(_FIXTURE)

    assert _label(_FIXTURE) == "13"
    assert set(dumped) == {"meta", "stopped_activations", "activation_effects", "observations"}
    assert len(dumped["stopped_activations"]) == 1
    assert len(dumped["activation_effects"]) == 1
    assert sorted(blobs) == list(_EPISODES)
    findings = [one for blob in blobs.values() for one in blob["findings"]]
    assert len(findings) == 9
    assert not any({"supply", "written"} & set(one) for one in findings)
    assert {blob["state"] for blob in blobs.values()} == {state.value for state in ObservationState}


async def test_the_previous_releases_file_is_upgraded_and_every_record_read_back(
    legacy: Path,
) -> None:
    """§4:1, §4:2, §4:4: opened, upgraded in place, and every record read back whole."""
    before = _dump(legacy)
    blobs = _blobs(legacy)

    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        export = await store.export()
        read = await store.observations(list(_EPISODES))
    finally:
        store.close()

    assert _label(legacy) == "19"
    assert export.stopped_activations == ("act-legacy-stopped",)
    assert [one.id for one in export.activation_effects] == ["effect-legacy-remember"]
    assert export.observations == read
    assert [one.episode for one in read] == list(_EPISODES)
    for record in read:
        assert record.model_dump(mode="json") == _with_empty_carry(blobs[record.episode])
        assert all(one.supply is None and one.written == () for one in record.findings)
    # No row is rewritten: the step moves the label and nothing else.
    after = _dump(legacy)
    assert {table: after[table] for table in before if table != "meta"} == {
        table: rows for table, rows in before.items() if table != "meta"
    }


async def test_the_upgraded_file_behaves_as_the_previous_release_left_it(legacy: Path) -> None:
    """The carried records still decide what they decided: the queue, the budget, a write."""
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        held = {one.episode: one for one in await store.observations(list(_EPISODES))}
        assert [episode for episode, one in held.items() if one.attemptable(_NOW)] == [
            "activation:act-legacy-2",
            "activation:act-legacy-3",
        ]
        # Every model call each record holds is counted, the open attempt's included.
        assert await store.observer_calls_since(datetime(2026, 10, 18, tzinfo=UTC)) == 13
        # The conditional write holds on the revision the previous release issued.
        waiting = held["activation:act-legacy-2"]
        with pytest.raises(PlanningError):
            await store.write_observation(waiting, expected_revision=0)
        rewritten = await store.write_observation(waiting, expected_revision=waiting.revision)
        assert rewritten.revision > max(one.revision for one in held.values())
    finally:
        store.close()


async def test_the_upgraded_file_takes_a_findings_carry_and_keeps_it(legacy: Path) -> None:
    """A pending finding gains its carry at once, and a reopen neither re-upgrades nor loses it."""
    narrowed = Placement(
        reach=PlacementReach.OWNER,
        set_by=PlacementSetter.DERIVED,
        set_at=_NOW - timedelta(minutes=1),
    )
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        (waiting,) = await store.observations(["activation:act-legacy-2"])
        committed, pending = waiting.findings
        carried = pending.model_copy(
            update={
                "supply": narrowed,
                "written": (
                    ObservationWrite(
                        memory="memory-home", operations=(MemoryOperationKind.CREATE,)
                    ),
                ),
            }
        )
        record = ObservationRecord.model_validate(
            {**waiting.model_dump(), "findings": (committed, carried)}
        )
        stored = await store.write_observation(record, expected_revision=waiting.revision)
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert await reopened.observations(["activation:act-legacy-2"]) == (stored,)
        assert stored.findings[1].supply == narrowed
        assert len((await reopened.export()).observations) == len(_EPISODES)
    finally:
        reopened.close()
    assert _label(legacy) == "19"


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER INSERT ON observations BEGIN SELECT 1; END")
    before = _dump(legacy)
    with sqlite3.connect(legacy) as conn:
        schema = sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "13"
    assert _dump(legacy) == before
    with sqlite3.connect(legacy) as conn:
        assert sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()) == (
            schema
        )


def test_the_fixture_records_validate_as_this_build_reads_them() -> None:
    """Each stored blob is a record this build reads unchanged but for the empty carry.

    The upgrade rewrites no observation record, so a blob this build could not read
    would be a record the upgrade failed to carry; this pins that none is.
    """
    for blob in _blobs(_FIXTURE).values():
        record = ObservationRecord.model_validate_json(json.dumps(blob))
        assert json.loads(record.model_dump_json()) == _with_empty_carry(blob)
