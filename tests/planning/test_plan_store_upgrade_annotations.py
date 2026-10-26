"""ADR-0326 §4:2's test, for ADR-0346: a file holding observation records from before it.

``tests/planning/legacy/plans-before-annotations.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``52a0179a``, through its public
``record_stop``, ``claim_activation_effect``, ``finish_activation_effect`` and
``write_observation``, at the label ``14``), never by hand-built SQL. Beside one stop
record and one effect record it holds three observation records: one processed, its
findings covering a create and a finding not kept, both made under the retired ``commit``
step; one waiting after a failed attempt with a pending finding carrying its supply; and
one skipped.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1): carry every record
whole (§4:4), each reading back with ADR-0346's fields empty since nothing was recorded
of them (no ``declines``, no ``annotations``, and no ``unclear`` and nothing ``asked``
on an outcome, §4:5, §4:6, §6:5, §6:8), move the label to 15, and leave the file exactly
as it found it where the open fails (§4:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    CandidateDecline,
    FindingAnnotations,
    ObservationRecord,
    ObserverStep,
    PlacementReach,
    ProposedNarrowing,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-annotations.db"

#: The instant the head opens the file at: the day after the previous release wrote it.
_NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)

_EPISODES = tuple(f"activation:act-before-{index}" for index in range(1, 4))


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


def _with_nothing_new(blob: dict[str, Any]) -> dict[str, Any]:
    """A stored record as this build must read it: ADR-0346's fields empty."""
    return {
        **blob,
        "declines": [],
        "findings": [
            one
            | {
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
    """Labelled 14, the three record tables, and records written with none of ADR-0346's."""
    dumped = _dump(_FIXTURE)
    blobs = _blobs(_FIXTURE)

    assert _label(_FIXTURE) == "14"
    assert set(dumped) == {"meta", "stopped_activations", "activation_effects", "observations"}
    assert sorted(blobs) == list(_EPISODES)
    assert not any("declines" in blob for blob in blobs.values())
    findings = [one for blob in blobs.values() for one in blob["findings"]]
    assert len(findings) == 3
    assert not any("annotations" in one for one in findings)
    calls = [
        call["step"] for blob in blobs.values() for a in blob["attempts"] for call in a["calls"]
    ]
    assert ObserverStep.COMMIT.value in calls


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

    assert _label(legacy) == "18"
    assert export.schema_version == 26
    assert export.stopped_activations == ("act-before-stopped",)
    assert [one.id for one in export.activation_effects] == ["effect-before-remember"]
    assert export.observations == read
    for record in read:
        assert record.model_dump(mode="json") == _with_nothing_new(blobs[record.episode])
        assert record.declines == ()
        assert all(one.annotations is None for one in record.findings)
    # No row is rewritten: the step moves the label and nothing else.
    after = _dump(legacy)
    assert {table: after[table] for table in before if table != "meta"} == {
        table: rows for table, rows in before.items() if table != "meta"
    }


async def test_the_upgraded_file_takes_annotations_and_declines_and_keeps_them(
    legacy: Path,
) -> None:
    """A waiting record gains a finding's annotations and a decline, kept across a reopen."""
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        (waiting,) = await store.observations(["activation:act-before-2"])
        (pending,) = waiting.findings
        annotated = pending.model_copy(
            update={
                "annotations": FindingAnnotations(
                    subjects=("Ana",),
                    why="Family.",
                    narrowing=ProposedNarrowing(reach=PlacementReach.OWNER, note="Private."),
                )
            }
        )
        record = ObservationRecord.model_validate(
            {
                **waiting.model_dump(),
                "findings": (annotated,),
                "declines": (CandidateDecline(candidate="effect-x", reason="Trivia."),),
            }
        )
        stored = await store.write_observation(record, expected_revision=waiting.revision)
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert await reopened.observations(["activation:act-before-2"]) == (stored,)
        assert stored.findings[0].annotations is not None
        assert stored.declines[0].reason == "Trivia."
    finally:
        reopened.close()
    assert _label(legacy) == "18"


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER INSERT ON observations BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "14"
    assert _dump(legacy) == before
