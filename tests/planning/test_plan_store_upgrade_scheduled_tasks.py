"""ADR-0326 §4:2's test, for ADR-0350: a file the release before the Task Scheduler wrote.

``tests/planning/legacy/plans-before-scheduled-tasks.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``bc60580f8``, through its public
``record_stop``, ``claim_activation_effect``, ``finish_activation_effect`` and
``write_observation``, at the label ``15``), never by hand-built SQL. It holds one stop
record, three effect records — a call finished, a message claimed with no outcome, and a
call spending a question part — and one observation record.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1, ADR-0350 §12:4): add
the empty ``scheduled_tasks`` table, carry every record whole (§4:4), move the label
forward from 15 (§4:5), and leave the file exactly as it found it where the open fails
(§4:3). The ``cascade_records`` table label 16 added is never created on the way past 17
(ADR-0352 §6:4). The upgraded file then holds a scheduled task like any other.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ChannelIdentity,
    DueNow,
    QuestionPart,
    ScheduledTaskAuthor,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-scheduled-tasks.db"

#: The instant the head opens the file at: the day after the previous release wrote it.
_NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)

_TABLES_BEFORE = {"meta", "stopped_activations", "activation_effects", "observations"}


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
    """Labelled 15, the three record tables, and the records the docstring names."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "15"
    assert set(dumped) == _TABLES_BEFORE
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert sorted(str(row[0]) for row in dumped["activation_effects"]) == [
        "effect-before-call",
        "effect-before-message",
        "effect-before-part",
    ]
    assert [str(row[0]) for row in dumped["observations"]] == ["activation:act-before-1"]


async def test_the_previous_releases_file_is_upgraded_and_every_record_read_back(
    legacy: Path,
) -> None:
    """§4:1, §4:2, §4:4: opened, upgraded in place, and every record read back whole."""
    before = _dump(legacy)

    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        export = await store.export()
        observations = await store.observations(["activation:act-before-1"])
    finally:
        store.close()

    assert _label(legacy) == "19"
    assert export.schema_version == 29
    assert export.stopped_activations == ("act-before-stopped",)
    effects = {one.id: one for one in export.activation_effects}
    assert list(effects) == ["effect-before-call", "effect-before-message", "effect-before-part"]
    assert effects["effect-before-call"].outcome is ToolOutcome.SUCCEEDED
    assert effects["effect-before-message"].outcome is None
    assert effects["effect-before-part"].part == QuestionPart(round="q-round", part=1)
    assert export.observations == observations
    assert [one.episode for one in observations] == ["activation:act-before-1"]
    assert export.scheduled_tasks == ()
    # The steps move the label and add the one empty table, and rewrite no row.
    after = _dump(legacy)
    assert set(after) == {*_TABLES_BEFORE, "scheduled_tasks", "approval_requests"}
    assert after["scheduled_tasks"] == []
    assert {table: after[table] for table in before if table != "meta"} == {
        table: rows for table, rows in before.items() if table != "meta"
    }


async def test_the_upgraded_file_holds_a_scheduled_task_and_keeps_what_it_carried(
    legacy: Path,
) -> None:
    """The carried records still decide what they decided, and a spawn lands and reopens."""
    spawn = TaskSpawn(
        id="t-after",
        person="person:owner",
        author=ScheduledTaskAuthor.PERSON,
        when=DueNow(),
        instruction="remind me to call",
        set_in=ChannelIdentity(channel_type="conversation", instance_id="c-1"),
        set_at=_NOW,
    )
    effect = ActivationEffect(
        id="spawn-after",
        activation_id="act-after",
        round="r1",
        capability="spawn",
        values_digest="c" * 64,
        decision_id="d-after",
        claimed_at=_NOW,
    )
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        with pytest.raises(ClaimStopped):
            await store.write_scheduled_task(
                spawn,
                effect.model_copy(update={"activation_id": "act-before-stopped"}),
                match=None,
                chain_limit=10,
                pending_limit=50,
            )
        written = await store.write_scheduled_task(
            spawn, effect, match=None, chain_limit=10, pending_limit=50
        )
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert written.answer is TaskWriteAnswer.WRITTEN
        assert await reopened.scheduled_tasks(["t-after"]) == (written.task,)
        spent = await reopened.part_effects([QuestionPart(round="q-round", part=1)])
        assert [one.id for one in spent] == ["effect-before-part"]
    finally:
        reopened.close()
    assert _label(legacy) == "19"


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER INSERT ON observations BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "15"
    assert _dump(legacy) == before
