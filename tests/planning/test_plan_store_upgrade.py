"""ADR-0326 §4:2's test, for ADR-0329 §16:10: a file the previous release wrote is upgraded.

``tests/planning/legacy/plans-before-adr-0329.db`` was written by the previous release's
own ``SqlitePlanStore`` (the build at ``4ad67aa5``, through its public ``record_stop``,
``claim_activation_effect`` and ``finish_activation_effect``, at the label ``12``),
never by hand-built SQL. It holds two stop records and eight effect records: a call
done, one not done with its reason, one unknown and one never finished; a message done
at its position, one never finished and the *couldn't finish* message, which names no
round; and a ``remember`` call run under an approval, spending its question part.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1, §5:1): carry every
record whole (§4:4), move the label through 13 and 14 to the head's 15 (§4:5), add the empty
observation table, and leave the file exactly as it found it where the open fails (§4:3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ObservationRecord,
    ObservationState,
    QuestionPart,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-adr-0329.db"

#: The instant the head opens the file at: the day after the previous release wrote it.
_NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


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


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file is labelled 12 and holds the two tables that release wrote, and no other."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "12"
    assert set(dumped) == {"meta", "stopped_activations", "activation_effects"}
    assert len(dumped["stopped_activations"]) == 2
    assert len(dumped["activation_effects"]) == 8


async def test_the_previous_releases_file_is_upgraded_and_every_record_read_back(
    legacy: Path,
) -> None:
    """§4:1, §4:2, §4:4: opened, upgraded in place, and every record read back whole."""
    before = _dump(legacy)
    held_effects = {
        str(row[0]): ActivationEffect.model_validate_json(str(row[3]))
        for row in before["activation_effects"]
    }

    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        export = await store.export()
    finally:
        store.close()

    assert _label(legacy) == "18"
    assert export.stopped_activations == ("act-legacy-stopped", "act-legacy-stopped-2")
    assert {one.id: one for one in export.activation_effects} == held_effects
    # Claim order is the order the previous release claimed them in.
    assert [one.id for one in export.activation_effects] == [
        str(row[0]) for row in sorted(before["activation_effects"], key=lambda row: row[2])
    ]
    assert export.observations == ()
    after = _dump(legacy)
    assert after["stopped_activations"] == before["stopped_activations"]
    assert after["activation_effects"] == before["activation_effects"]
    assert after["observations"] == []


async def test_the_upgraded_file_behaves_as_the_previous_release_left_it(legacy: Path) -> None:
    """The carried records still decide what they decided: a spent part, a stop, a backstop."""
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        spent = await store.part_effects([QuestionPart(round="q-legacy", part=1)])
        assert [one.id for one in spent] == ["effect-approved"]
        with pytest.raises(ClaimStopped):
            await store.claim_activation_effect(
                ActivationEffect(
                    id="effect-after",
                    activation_id="act-legacy-stopped-2",
                    round="r9",
                    place="c-legacy",
                    claimed_at=_NOW,
                ),
                match=None,
            )
        repeat = ActivationEffect(
            id="effect-again",
            activation_id="act-legacy-9",
            round="r9",
            capability="remember",
            values_digest="b" * 64,
            decision_id="d-again",
            claimed_at=_NOW,
        )
        assert (
            await store.claim_activation_effect(repeat, match=("act-legacy-1",))
            is ActivationEffectClaim.ALREADY_DONE
        )
    finally:
        store.close()


async def test_the_upgraded_file_takes_observation_records_and_keeps_them(
    legacy: Path,
) -> None:
    """The new table is usable at once, and a reopen neither re-upgrades nor loses it."""
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        stored = await store.write_observation(
            ObservationRecord(episode="activation:act-legacy-1", state=ObservationState.SKIPPED),
            expected_revision=0,
        )
        await store.finish_activation_effect("effect-open", ToolOutcome.FAILED, reason="late")
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert await reopened.observations(["activation:act-legacy-1"]) == (stored,)
        assert len((await reopened.export()).activation_effects) == 8
    finally:
        reopened.close()
    assert _label(legacy) == "18"


@pytest.mark.parametrize(
    "spoil",
    [
        # A table of the new name already there, of the wrong shape: the shape check after
        # the upgrade step refuses it.
        "CREATE TABLE observations(episode_id TEXT PRIMARY KEY, data TEXT NOT NULL)",
        # A trigger on a table the store writes: refused after the upgrade step too.
        "CREATE TRIGGER spoiled AFTER INSERT ON activation_effects BEGIN SELECT 1; END",
    ],
    ids=["a-wrong-shaped-observations-table", "a-trigger"],
)
async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path, spoil: str) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute(spoil)
    before = _dump(legacy)
    with sqlite3.connect(legacy) as conn:
        schema = sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "12"
    assert _dump(legacy) == before
    with sqlite3.connect(legacy) as conn:
        assert sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()) == (
            schema
        )


def test_the_fixture_records_validate_as_this_build_reads_them() -> None:
    """Each stored blob is a record this build's ``ActivationEffect`` reads unchanged.

    The upgrade rewrites no effect record, so a blob this build could not read would be
    a record the upgrade failed to carry; this pins that none is.
    """
    with sqlite3.connect(_FIXTURE) as conn:
        blobs = [str(data) for (data,) in conn.execute("SELECT data FROM activation_effects")]

    for blob in blobs:
        record = ActivationEffect.model_validate_json(blob)
        assert json.loads(record.model_dump_json()) == json.loads(blob)
