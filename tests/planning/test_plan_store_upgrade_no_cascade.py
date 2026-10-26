"""ADR-0326 §4:2's test, for ADR-0352: a file the release before the cascade's removal wrote.

``tests/planning/legacy/plans-before-no-cascade.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``a57545310``, at the label ``17``),
through its public members alone, never by hand-built SQL. It holds:

- two stop records, ``act-before-stopped`` and ``act-cascaded``, and two cascade
  records, ``act-cascaded``, written before its stop record as ``Engine._stop`` wrote
  them, and ``act-cascaded-alone``, naming an activation that set up nothing;
- below ``act-cascaded``: ``t-below-pending``, due at an instant; ``t-below-pushed``,
  pushed to ``act-below-pushed`` with its outcome unwritten; ``t-grandchild``, which
  ``act-below-pushed`` spawned, still pending; and ``t-below-rule``, a rule the person
  set, first pushed to ``act-below-rule``, its successor pending;
- outside every cascaded lineage, all spawned by ``act-free``: ``t-free``, pending;
  ``t-waiter``, waiting on ``t-below-pending``; and ``t-free-pushed``, pushed to
  ``act-free-pushed`` with its outcome unwritten;
- the seven spawns' effect records.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1, ADR-0352 §2:6,
§6:4): in one step, end *cancelled* every pending occurrence below a cascade record, as
ADR-0350 §7:5's push step refused it before; give a stop record to the activation of
every occurrence below one that is pushed with its outcome unwritten, so ADR-0350 §8:1
ends it *stopped* at start; drop the cascade records; carry every other record as it
stands (ADR-0326 §4:4); move the label to 18; and leave the file exactly as it found it
where the open fails (§4:3).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import OccurrencePush, OccurrenceState, ScheduledTask
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-no-cascade.db"

#: When the previous release wrote the file, and when the head opens it: the day after.
_WROTE_AT = datetime(2026, 10, 26, 12, tzinfo=UTC)
_NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)

_TABLES_BEFORE = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
    "cascade_records",
}
_TABLES_AFTER = _TABLES_BEFORE - {"cascade_records"}

_TASKS = [
    "t-below-pending",
    "t-below-pushed",
    "t-below-rule",
    "t-grandchild",
    "t-free",
    "t-waiter",
    "t-free-pushed",
]


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


def _states(task: ScheduledTask) -> list[OccurrenceState]:
    return [one.state for one in task.occurrences]


async def _opened(path: Path) -> tuple[dict[str, ScheduledTask], tuple[str, ...]]:
    """Open the file with the head, and read back its tasks and stop records."""
    store = SqlitePlanStore(path=path, now=_now)
    try:
        export = await store.export()
    finally:
        store.close()
    return {one.id: one for one in export.scheduled_tasks}, export.stopped_activations


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 17, the five record tables, and the records the docstring names."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "17"
    assert set(dumped) == _TABLES_BEFORE
    assert dumped["cascade_records"] == [("act-cascaded",), ("act-cascaded-alone",)]
    assert dumped["stopped_activations"] == [("act-before-stopped",), ("act-cascaded",)]
    assert sorted(str(row[0]) for row in dumped["scheduled_tasks"]) == sorted(_TASKS)
    assert len(dumped["activation_effects"]) == len(_TASKS)


async def test_a_pending_occurrence_below_a_cascade_record_ends_cancelled(legacy: Path) -> None:
    """ADR-0352 §2:6, §7:9: cancelled at the upgrade, and no cascade record is left.

    Each pending occurrence whose task's lineage carries one ends *cancelled* at the
    instant the head opens the file: the task its activation spawned, the grandchild a
    pushed activation below it spawned, and the successor of a rule below it, so the rule
    ends. A task outside every cascaded lineage is untouched, and one waiting on a task
    the upgrade ended falls due when it ended (ADR-0350 §5:4).
    """
    tasks, _ = await _opened(legacy)

    assert _label(legacy) == "18"
    assert list(tasks) == _TASKS
    for task_id in ("t-below-pending", "t-grandchild"):
        (occurrence,) = tasks[task_id].occurrences
        assert (occurrence.state, occurrence.ended_at) == (OccurrenceState.CANCELLED, _NOW)
    assert _states(tasks["t-below-rule"]) == [OccurrenceState.PUSHED, OccurrenceState.CANCELLED]
    assert not tasks["t-below-rule"].pending
    assert _states(tasks["t-free"]) == [OccurrenceState.PENDING]
    assert tasks["t-free"].occurrences[0].due_at == _WROTE_AT + timedelta(days=3)
    (waiting,) = tasks["t-waiter"].occurrences
    assert (waiting.state, waiting.due_at) == (OccurrenceState.PENDING, _NOW)
    after = _dump(legacy)
    assert set(after) == _TABLES_AFTER, "the cascade records are dropped"


async def test_a_pushed_occurrence_below_a_cascade_record_gets_a_stop_record(
    legacy: Path,
) -> None:
    """ADR-0352 §2:6, §7:9: so ADR-0350 §8:1 ends it *stopped* and never pushes it again.

    The upgrade writes the stop record and leaves the occurrence pushed: the restart's
    settle reads a pushed occurrence's activation for a stop record and ends it stopped
    (``tests/orchestration/test_task_sensor.py``,
    ``test_a_stop_cut_off_by_the_restart_ends_it_stopped_and_pushes_nothing``). Here that
    read and that settle are made at the store, and the occurrence is then never pushed
    again. A pushed occurrence outside every cascaded lineage gets no stop record.
    """
    tasks, stopped = await _opened(legacy)

    assert set(stopped) == {
        "act-before-stopped",
        "act-cascaded",
        "act-below-pushed",
        "act-below-rule",
    }
    assert "act-free-pushed" not in stopped
    assert tasks["t-below-pushed"].occurrences[0].pushed_to == "act-below-pushed"
    assert tasks["t-below-rule"].occurrences[0].pushed_to == "act-below-rule"
    assert tasks["t-free-pushed"].occurrences[0].pushed_to == "act-free-pushed"

    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        pushed = ["act-below-pushed", "act-below-rule", "act-free-pushed"]
        assert await store.stopped_activations(pushed) == ("act-below-pushed", "act-below-rule")
        settled = await store.settle_occurrence("act-below-pushed", OccurrenceState.STOPPED)
        assert _states(settled) == [OccurrenceState.STOPPED]
        assert await store.mark_occurrence_pushed("t-below-pushed", 1, "act-again") is (
            OccurrencePush.NOT_PENDING
        )
    finally:
        store.close()


async def test_every_other_record_is_carried_as_it_stands(legacy: Path) -> None:
    """ADR-0326 §4:4: the effect and observation records, and the untouched tasks' rows."""
    before = _dump(legacy)

    await _opened(legacy)

    after = _dump(legacy)
    assert after["activation_effects"] == before["activation_effects"]
    assert after["observations"] == before["observations"]
    untouched = {"t-below-pushed", "t-free", "t-free-pushed"}
    assert [row for row in after["scheduled_tasks"] if row[0] in untouched] == [
        row for row in before["scheduled_tasks"] if row[0] in untouched
    ]
    assert set(after["stopped_activations"]) >= set(before["stopped_activations"])


async def test_the_upgraded_file_reopens_as_it_is(legacy: Path) -> None:
    """The step is taken once: a second open at 18 changes nothing."""
    first = await _opened(legacy)
    dumped = _dump(legacy)

    assert await _opened(legacy) == first
    assert _dump(legacy) == dumped
    assert _label(legacy) == "18"


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: a blanked cascade record is damage, and the open rolls back every step."""
    with sqlite3.connect(legacy) as conn:
        conn.execute(
            "UPDATE cascade_records SET activation_id = '  ' WHERE activation_id = ?",
            ("act-cascaded-alone",),
        )
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "17"
    assert _dump(legacy) == before
