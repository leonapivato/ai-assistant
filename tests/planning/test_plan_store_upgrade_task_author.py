"""ADR-0326 §4:2's test, for ADR-0368 §6:3: a file the release before a task's setter wrote.

``tests/planning/legacy/plans-before-task-author.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``db9203e1d``, at the label ``19``),
through its public members alone, never by hand-built SQL. It holds one stop record, the
five spawns' effect records, and five scheduled tasks for ``person:owner``, three the
person set and two the assistant set, none recording who set it:

- ``t-person-at``, the person's, due at an instant and suggesting the line;
- ``t-person-rule``, the person's, on a weekday rule, its first occurrence pushed and its
  successor pending;
- ``t-person-cancelled``, the person's, set in the line and cancelled;
- ``t-assistant-done``, the assistant's, due now, marked outside content, pushed and
  settled done;
- ``t-assistant-waiting``, the assistant's, waiting on ``t-person-at``.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1): move the label to 20,
carry every record (§4:4), and give each task who set it, and nothing else: a task the
person set records the person it is for, at normal, and one the assistant set no person,
at none, neither recording a connection (ADR-0368 §6:1, §6:4; #3678's "every existing
task carries the owner's authority"). A file it cannot carry so is refused and left
exactly as it was found (§4:3, §5:1).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from task_setters import decoded, unset

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    ActivationEffect,
    ChannelIdentity,
    DueNow,
    OccurrencePush,
    OccurrenceState,
    RulePush,
    ScheduledTaskAuthor,
    Sureness,
    TaskSpawn,
    TaskWriteAnswer,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "plans-before-task-author.db"

#: When the previous release wrote the file, and when the head opens it: an hour later.
_WROTE_AT: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=1)

_PERSONS: Final = ["t-person-at", "t-person-rule", "t-person-cancelled"]
_ASSISTANTS: Final = ["t-assistant-done", "t-assistant-waiting"]
_TASKS: Final = [*_PERSONS, *_ASSISTANTS]
_TABLES: Final = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
    "approval_requests",
}


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


def _open(path: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=path, now=_now)


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 19, its tables and tasks as the docstring names, none recording a setter."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "19"
    assert set(dumped) == _TABLES
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert len(dumped["activation_effects"]) == len(_TASKS)
    records = {row[0]: json.loads(row[-1]) for row in dumped["scheduled_tasks"]}
    assert sorted(records) == sorted(_TASKS)
    assert {one: records[one]["author"] for one in _TASKS} == {
        **dict.fromkeys(_PERSONS, "person"),
        **dict.fromkeys(_ASSISTANTS, "assistant"),
    }
    assert not any("author_person" in one or "setting_level" in one for one in records.values())


async def test_every_task_is_upgraded_to_record_who_set_it(legacy: Path) -> None:
    """ADR-0368 §6:1: the person's at normal as the person it is for; the assistant's none."""
    store = _open(legacy)
    try:
        export = await store.export()
        read = await store.scheduled_tasks(_TASKS)
    finally:
        store.close()

    assert _label(legacy) == "20"
    assert export.schema_version == 30
    tasks = {one.id: one for one in export.scheduled_tasks}
    assert list(tasks) == _TASKS
    assert {
        one.id: (one.author_person, one.setting_level, one.setting_connection)
        for one in export.scheduled_tasks
    } == {
        **dict.fromkeys(_PERSONS, (OWNER_PERSON_ID, Sureness.NORMAL, None)),
        **dict.fromkeys(_ASSISTANTS, (None, Sureness.NONE, None)),
    }
    assert read == export.scheduled_tasks
    assert all(one.author is ScheduledTaskAuthor.PERSON for one in read[:3])


async def test_every_other_record_and_field_is_carried_as_it_stands(legacy: Path) -> None:
    """ADR-0326 §4:4: each task gains the three fields alone; no other row moves."""
    before = _dump(legacy)

    _open(legacy).close()

    after = _dump(legacy)
    assert set(after) == _TABLES
    untouched = _TABLES - {"meta", "scheduled_tasks"}
    assert {table: after[table] for table in untouched} == {
        table: before[table] for table in untouched
    }
    assert unset(after["scheduled_tasks"]) == decoded(before["scheduled_tasks"])
    states = {
        one[0]: [step["state"] for step in one[-1]["occurrences"]]
        for one in decoded(after["scheduled_tasks"])
    }
    assert states == {
        "t-person-at": ["pending"],
        "t-person-rule": ["pushed", "pending"],
        "t-person-cancelled": ["cancelled"],
        "t-assistant-done": ["done"],
        "t-assistant-waiting": ["pending"],
    }


async def test_the_upgraded_file_reopens_as_it_is(legacy: Path) -> None:
    """The step is taken once: a second open at 20 rewrites nothing."""
    _open(legacy).close()
    upgraded = _dump(legacy)

    _open(legacy).close()

    assert _dump(legacy) == upgraded


async def test_an_upgraded_task_keeps_who_set_it_through_its_steps(legacy: Path) -> None:
    """The rule's next push writes its successor; a cancel and a reopen keep the setter."""
    store = _open(legacy)
    try:
        pushed = await store.mark_occurrence_pushed(
            "t-person-rule",
            2,
            "act-after-rule-2",
            rule=RulePush(successor=_WROTE_AT + timedelta(days=2)),
        )
        cancelled = await store.cancel_scheduled_task("t-person-at")
        held = await store.scheduled_tasks(["t-person-rule", "t-person-at"])
    finally:
        store.close()

    reopened = _open(legacy)
    try:
        assert await reopened.scheduled_tasks(["t-person-rule", "t-person-at"]) == held
    finally:
        reopened.close()
    assert pushed is OccurrencePush.PUSHED
    assert cancelled.task is not None
    rule, at = held
    assert [one.state for one in rule.occurrences] == [
        OccurrenceState.PUSHED,
        OccurrenceState.PUSHED,
        OccurrenceState.PENDING,
    ]
    assert [one.state for one in at.occurrences] == [OccurrenceState.CANCELLED]
    assert {(one.author_person, one.setting_level) for one in held} == {
        (OWNER_PERSON_ID, Sureness.NORMAL)
    }


async def test_a_task_written_after_the_upgrade_records_what_its_spawn_states(
    legacy: Path,
) -> None:
    """A spawn lands beside the carried tasks with the setter it states, and reopens."""
    spawn = TaskSpawn(
        id="t-after",
        person=OWNER_PERSON_ID,
        author=ScheduledTaskAuthor.PERSON,
        author_person=OWNER_PERSON_ID,
        setting_level=Sureness.WEAK,
        setting_connection=OWN_CHAT_CONNECTION,
        when=DueNow(),
        instruction="remind me to call",
        set_in=ChannelIdentity(channel_type="conversation", instance_id="c-1"),
        set_at=_NOW,
    )
    effect = ActivationEffect(
        id="spawn-t-after",
        activation_id="act-after",
        round="r1",
        capability="spawn",
        values_digest="f" * 64,
        decision_id="d-after",
        claimed_at=_NOW,
    )
    store = _open(legacy)
    try:
        written = await store.write_scheduled_task(
            spawn, effect, match=None, chain_limit=10, pending_limit=50
        )
    finally:
        store.close()

    reopened = _open(legacy)
    try:
        (task,) = await reopened.scheduled_tasks(["t-after"])
        everything = await reopened.export()
    finally:
        reopened.close()
    assert written.answer is TaskWriteAnswer.WRITTEN
    assert (task.author_person, task.setting_level, task.setting_connection) == (
        OWNER_PERSON_ID,
        Sureness.WEAK,
        "conversation",
    )
    assert [one.id for one in everything.scheduled_tasks] == [*_TASKS, "t-after"]


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER UPDATE ON scheduled_tasks BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        _open(legacy)

    assert _label(legacy) == "19"
    assert _dump(legacy) == before


@pytest.mark.parametrize(
    "damage",
    [
        "not json",
        "[]",
        '{"id":"t-person-at","author":"person"}',
        '{"id":"t-person-at","person":"person:owner","author":"robot"}',
        '{"id":"t-person-at","person":"person:owner","author":["person"]}',
        '{"id":"t-person-at","person":"person:owner","author":"person","setting_level":"strong"}',
    ],
    ids=["not-json", "not-an-object", "no-person", "no-author", "author-not-text", "set-already"],
)
async def test_a_task_no_earlier_release_wrote_is_refused_as_damage(
    legacy: Path, damage: str
) -> None:
    """ADR-0326 §5:1: refused, and the file left exactly as it was found (§4:3)."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE scheduled_tasks SET data = ? WHERE id = 't-person-at'", (damage,))
    before = _dump(legacy)

    with pytest.raises(PlanningError, match="t-person-at"):
        _open(legacy)

    assert _label(legacy) == "19"
    assert _dump(legacy) == before
