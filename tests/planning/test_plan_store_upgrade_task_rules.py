"""ADR-0326 §4:2's test, for ADR-0340: a file the release before task rules wrote.

``tests/planning/legacy/plans-before-task-rules.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``989a98ffe``, at the label ``16``),
through its public members alone, never by hand-built SQL. It holds one stop record, one
cascade record, the five spawns' effect records, and five scheduled tasks, each one-off:
``t-pending``, due at an instant and suggesting the line; ``t-done``, due now, pushed and
settled done; ``t-step``, which ``t-done``'s activation spawned, pushed and then pushed
again as a second try; ``t-waiting``, waiting on ``t-pending``; and ``t-cancelled``.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1, ADR-0340 §9:4): carry
every record whole (§4:4), rewrite no row, and move the label to 17, and leave the file
exactly as it found it where the open fails (§4:3). The upgraded file then holds a task
with a rule like any other. The step past 17 retires the cascade record (ADR-0352 §2:6),
which names an activation outside every lineage, so it reaches no task and the table
goes with nothing else changed.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOnRule,
    OccurrenceState,
    RulePush,
    ScheduledTaskAuthor,
    TaskRuleKind,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-task-rules.db"

#: When the previous release wrote the file, and when the head opens it: the day after.
_WROTE_AT = datetime(2026, 10, 24, 12, tzinfo=UTC)
_NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)

_TABLES = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
    "cascade_records",
}
#: The tables once the step past 17 retires ``cascade_records`` (ADR-0352 §6:4).
_TABLES_AFTER = (_TABLES - {"cascade_records"}) | {"approval_requests"}


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
    """Labelled 16, the five record tables, and the records the docstring names."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "16"
    assert set(dumped) == _TABLES
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert dumped["cascade_records"] == [("act-before-cascade",)]
    assert sorted(str(row[0]) for row in dumped["scheduled_tasks"]) == [
        "t-cancelled",
        "t-done",
        "t-pending",
        "t-step",
        "t-waiting",
    ]
    assert len(dumped["activation_effects"]) == 5


async def test_the_previous_releases_file_is_upgraded_and_every_record_read_back(
    legacy: Path,
) -> None:
    """§4:1, §4:2, §4:4: opened, upgraded in place, and every record read back whole."""
    before = _dump(legacy)

    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        export = await store.export()
    finally:
        store.close()

    assert _label(legacy) == "19"
    assert export.schema_version == 27
    assert export.stopped_activations == ("act-before-stopped",)
    effects = {one.id: one for one in export.activation_effects}
    assert effects["spawn-pending"].outcome is ToolOutcome.SUCCEEDED
    assert effects["spawn-done"].outcome is None
    tasks = {one.id: one for one in export.scheduled_tasks}
    assert list(tasks) == ["t-pending", "t-done", "t-step", "t-waiting", "t-cancelled"]
    assert tasks["t-pending"].when == DueAt(at=_WROTE_AT + timedelta(days=2))
    assert tasks["t-pending"].places == (
        ChannelIdentity(channel_type="telegram", instance_id="line"),
    )
    assert tasks["t-done"].when == DueNow()
    assert [one.state for one in tasks["t-done"].occurrences] == [OccurrenceState.DONE]
    (step,) = tasks["t-step"].occurrences
    assert (step.state, step.second_try, step.activations) == (
        OccurrenceState.PENDING,
        True,
        ("act-before-3",),
    )
    assert tasks["t-step"].parent == "act-before-2"
    assert tasks["t-step"].author is ScheduledTaskAuthor.ASSISTANT
    assert tasks["t-waiting"].when == DueAfterTasks(tasks=("t-pending",))
    assert tasks["t-waiting"].occurrences[0].due_at is None
    assert [one.state for one in tasks["t-cancelled"].occurrences] == [OccurrenceState.CANCELLED]
    # The steps move the label and retire the cascade table, and rewrite no row.
    after = _dump(legacy)
    assert set(after) == _TABLES_AFTER
    assert {table: after[table] for table in _TABLES_AFTER if table != "meta"} == {
        table: before.get(table, []) for table in _TABLES_AFTER if table != "meta"
    }


async def test_the_upgraded_file_holds_a_rule_and_keeps_what_it_carried(legacy: Path) -> None:
    """A rule lands beside the carried tasks, its successor is written, and it reopens."""
    first = _NOW + timedelta(hours=7)
    spawn = TaskSpawn(
        id="t-rule",
        person="person:owner",
        author=ScheduledTaskAuthor.PERSON,
        when=DueOnRule(repeats=TaskRuleKind.WEEKDAYS, time_of_day=time(7)),
        instruction="the bins",
        set_in=ChannelIdentity(channel_type="conversation", instance_id="c-1"),
        set_at=_NOW,
        first_due_at=first,
    )
    effect = ActivationEffect(
        id="spawn-rule",
        activation_id="act-after",
        round="r1",
        capability="spawn",
        values_digest="f" * 64,
        decision_id="d-after",
        claimed_at=_NOW,
    )
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        written = await store.write_scheduled_task(
            spawn, effect, match=None, chain_limit=10, pending_limit=50
        )
        await store.mark_occurrence_pushed(
            "t-rule", 1, "act-rule-1", rule=RulePush(successor=first + timedelta(days=1))
        )
        held = await store.scheduled_tasks(["t-rule"])
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert written.answer is TaskWriteAnswer.WRITTEN
        assert await reopened.scheduled_tasks(["t-rule"]) == held
        (task,) = held
        assert [one.state for one in task.occurrences] == [
            OccurrenceState.PUSHED,
            OccurrenceState.PENDING,
        ]
        carried = await reopened.scheduled_tasks(["t-done", "t-step"])
        assert [one.id for one in carried] == ["t-done", "t-step"]
    finally:
        reopened.close()
    assert _label(legacy) == "19"


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER INSERT ON scheduled_tasks BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        SqlitePlanStore(path=legacy, now=_now)

    assert _label(legacy) == "16"
    assert _dump(legacy) == before
