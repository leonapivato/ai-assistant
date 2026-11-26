"""ADR-0326 §4:2's test, for ADR-0383 §5:1's home: a plan file the previous release wrote.

``tests/planning/legacy/plans-before-adr-0383.db`` was written by the previous release's
own ``SqlitePlanStore`` (the build at ``308d5d64d``, at the label ``21``), through its
public members alone and never by hand-built SQL, with invented data: one stop record;
nine effect records, a call done, one not done with its reason, one whose outcome is
unknown, one spending a question part, a message done at its position, a message never
finished, the *couldn't finish* message settled absent by its place, a spawn's effect
written with its task, and ``request_approval``'s effect written with its request; and
four observation records, one processed with two findings, one skipped, one waiting after
a failed attempt, and one stuck after a second write. Beside it,
``plans-before-adr-0383.json`` is what that build read back from the file through every
read of either record, written by that code too.

No effect record and no observation record that build wrote holds a home, which every
one this build writes does (ADR-0386 §5), so the label moves. The head opens a copy and
upgrades it in place: never refuse it (ADR-0326 §5:1), drop nothing (§4:4), read back
every record as that release did, and write the owner's domain into every effect and
every observation record, in its blob and in its row's two home columns, whoever the
works that wrote them were for (ADR-0383 §5:1), moving no other byte. No task, request or
stop record gains a home (§3). A file it cannot carry so is refused and left exactly as it
was found (ADR-0326 §4:3, §5:1).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import BaseModel
from record_homes import OWNERS_COLUMNS, OWNERS_JSON, decoded_tables, homeless_tables

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ObservationState,
    QuestionPart,
    RecordHome,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "plans-before-adr-0383.db"
_READ_BACK: Final = _LEGACY / "plans-before-adr-0383.json"

#: When the previous release wrote the file, and the instant both builds read it at: an
#: hour later.
_WROTE_AT: Final = datetime(2026, 11, 26, 9, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=1)

_ACTIVATIONS: Final = ["act-before-1", "act-before-2", "act-before-3", "act-before-stopped"]
_EPISODES: Final = [f"activation:{one}" for one in _ACTIVATIONS]
_EFFECTS: Final = [
    "effect-before-done",
    "effect-before-failed",
    "effect-before-unknown",
    "effect-before-part",
    "effect-before-sent",
    "effect-before-open",
    "effect-before-couldnt",
    "effect-before-spawn",
    "effect-before-request",
]
_TABLES: Final = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
    "approval_requests",
}
_HOME_COLUMNS: Final = ("home_kind", "home_id")


def _now() -> datetime:
    return _NOW


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "plans.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=path, now=_now)


def _label(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        (value,) = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return str(value)


def _columns(path: Path, table: str) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")]


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


def _json(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_json(one) for one in value]
    return value


def _homeless(value: Any) -> Any:
    """``value`` with each effect's and each observation's home taken off, each held to be
    the owner's.

    The previous release's read-back has no home on any record: the head's adds it
    (ADR-0383 §5:1), and every other byte must read back the same. An effect is told by
    its ``claimed_at``, an observation record by its ``attempts``.
    """
    if isinstance(value, dict):
        if "claimed_at" in value or "attempts" in value:
            assert value.get("home") == OWNERS_JSON, value
            value = {key: one for key, one in value.items() if key != "home"}
        return {key: _homeless(one) for key, one in value.items()}
    if isinstance(value, list):
        return [_homeless(one) for one in value]
    return value


async def _read_back(path: Path) -> dict[str, object]:
    """Every read the previous release's read-back recorded, made the same way by the head."""
    store = _open(path)
    try:
        return {
            "export": _json(await store.export()),
            "activation_effects": _json(await store.activation_effects(_ACTIVATIONS)),
            "part_effects": _json(
                await store.part_effects([QuestionPart(round="r-before-asked", part=1)])
            ),
            "observations": _json(await store.observations(_EPISODES)),
            "observer_calls_since": await store.observer_calls_since(_WROTE_AT),
        }
    finally:
        store.close()


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 21, its tables and records as the docstring names, none holding a home."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "21"
    assert set(dumped) == _TABLES
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert sorted(str(row[0]) for row in dumped["activation_effects"]) == sorted(_EFFECTS)
    assert sorted(str(row[0]) for row in dumped["observations"]) == sorted(_EPISODES)
    assert [str(row[0]) for row in dumped["scheduled_tasks"]] == ["task-before"]
    assert [str(row[0]) for row in dumped["approval_requests"]] == ["q-before"]
    for table in ("activation_effects", "observations"):
        assert not set(_HOME_COLUMNS) & set(_columns(_FIXTURE, table))
        assert not any("home" in json.loads(str(row[3])) for row in dumped[table])
    states = {str(row[0]): json.loads(str(row[3]))["state"] for row in dumped["observations"]}
    assert sorted(states.values()) == sorted(one.value for one in ObservationState)


async def test_every_record_reads_back_as_that_release_read_it_with_the_owners_home(
    legacy: Path,
) -> None:
    """§4:1, §4:2, §4:4, ADR-0383 §5:1: upgraded in place, every read whole, each record the
    owner's."""
    read_back = json.loads(_READ_BACK.read_text(encoding="utf-8"))

    head = await _read_back(legacy)

    assert _label(legacy) == "22"
    export = head["export"]
    assert isinstance(export, dict)
    assert export["schema_version"] == 32
    assert read_back["export"]["schema_version"] == 31
    head["export"] = {**export, "schema_version": 31}
    assert _homeless(head) == read_back


async def test_every_other_byte_is_carried_as_it_stands(legacy: Path) -> None:
    """§4:4: each effect and observation row gains the owner's home, blob and columns, and
    nothing else moves; the issuer is kept, and no task, request or stop record changes."""
    before = _dump(legacy)

    _open(legacy).close()

    after = _dump(legacy)
    assert set(after) == _TABLES
    for table in ("activation_effects", "observations"):
        assert _columns(legacy, table)[-2:] == list(_HOME_COLUMNS)
        assert {tuple(row[-2:]) for row in after[table]} == {OWNERS_COLUMNS}
    records = _TABLES - {"meta"}
    assert homeless_tables({table: after[table] for table in records}) == decoded_tables(
        {table: before[table] for table in records}
    )
    assert dict(after["meta"]) == {**dict(before["meta"]), "schema_version": "22"}


async def test_the_upgraded_file_reopens_as_it_is(legacy: Path) -> None:
    """The step is taken once: a second open at 22 rewrites nothing."""
    _open(legacy).close()
    upgraded = _dump(legacy)

    _open(legacy).close()

    assert _dump(legacy) == upgraded


async def test_the_upgraded_file_keeps_each_record_its_own_home_across_writes(
    legacy: Path,
) -> None:
    """A carried record keeps the owner's domain through a finish and a rewrite (§4:6), and
    a record written after the upgrade in the shared things keeps that, across a reopen."""
    shared = RecordHome.shared()
    store = _open(legacy)
    try:
        await store.finish_activation_effect(
            "effect-before-open", ToolOutcome.SUCCEEDED, position=9
        )
        (waiting,) = await store.observations(["activation:act-before-3"])
        rewritten = await store.write_observation(
            waiting.model_copy(update={"state": ObservationState.STUCK, "next_attempt_at": None}),
            expected_revision=waiting.revision,
        )
        await store.claim_activation_effect(
            ActivationEffect(
                id="effect-after",
                activation_id="act-after",
                home=shared,
                round="r-after",
                place="conversation:chat-before",
                claimed_at=_NOW,
            ),
            match=None,
        )
    finally:
        store.close()

    reopened = _open(legacy)
    try:
        homes = {
            one.id: one.home
            for one in await reopened.activation_effects(["act-before-3", "act-after"])
        }
        observed = await reopened.observations(["activation:act-before-3"])
    finally:
        reopened.close()
    assert homes == {
        "effect-before-open": RecordHome.owners(),
        "effect-before-couldnt": RecordHome.owners(),
        "effect-after": shared,
    }
    assert observed == (rewritten,)
    assert rewritten.home == RecordHome.owners()


async def test_a_home_no_write_may_carry_is_refused_on_the_upgraded_file(legacy: Path) -> None:
    """ADR-0386 §6: the upgraded file refuses it as a fresh one does, writing nothing."""
    store = _open(legacy)
    try:
        upgraded = _dump(legacy)
        (held,) = await store.observations(["activation:act-before-1"])
        with pytest.raises(PlanningError):
            await store.write_observation(
                held.model_copy(update={"home": RecordHome.person("person:sam")}),
                expected_revision=held.revision,
            )
    finally:
        store.close()

    assert _dump(legacy) == upgraded


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER UPDATE ON observations BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        _open(legacy)

    assert _label(legacy) == "21"
    assert _dump(legacy) == before
    for table in ("activation_effects", "observations"):
        assert not set(_HOME_COLUMNS) & set(_columns(legacy, table))


@pytest.mark.parametrize(
    ("table", "key", "damage"),
    [
        ("activation_effects", "effect-before-done", "not json"),
        ("activation_effects", "effect-before-sent", "[]"),
        (
            "activation_effects",
            "effect-before-done",
            '{"id":"effect-before-done","home":{"kind":"shared","id":null}}',
        ),
        ("activation_effects", "effect-before-done", '{"id":"effect-before-done","r":"\\ud800"}'),
        ("observations", "activation:act-before-2", "not json"),
        ("observations", "activation:act-before-2", '"a string"'),
        (
            "observations",
            "activation:act-before-2",
            '{"episode":"activation:act-before-2","home":null}',
        ),
    ],
    ids=[
        "an-effect-not-json",
        "an-effect-not-an-object",
        "an-effect-homed-already",
        "an-effect-unencodable",
        "an-observation-not-json",
        "an-observation-not-an-object",
        "an-observation-homed-already",
    ],
)
async def test_a_record_no_earlier_release_wrote_is_refused_as_damage(
    legacy: Path, table: str, key: str, damage: str
) -> None:
    """ADR-0326 §5:1: refused, and the file left exactly as it was found (§4:3)."""
    column = "id" if table == "activation_effects" else "episode_id"
    with sqlite3.connect(legacy) as conn:
        conn.execute(f"UPDATE {table} SET data = ? WHERE {column} = ?", (damage, key))  # noqa: S608 — names from the parameters above
    before = _dump(legacy)

    with pytest.raises(PlanningError, match=key):
        _open(legacy)

    assert _label(legacy) == "21"
    assert _dump(legacy) == before
