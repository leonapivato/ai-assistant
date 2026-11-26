"""ADR-0326 §4:2's test, for ADR-0377 §4:1: a file the release before a tap's record wrote.

``tests/planning/legacy/plans-before-tap-person.db`` was written by the previous release's
own ``SqlitePlanStore`` (the build at ``ec3645ec3``, at the label ``20``), through its
public members alone, never by hand-built SQL. It holds one stop record and five approval
requests for ``person:owner``, each a ``web_search`` with the effect record that wrote it,
none of whose answers records who tapped:

- ``q-before-line``, approved by a tap on its card on the line, its ticket held, its card
  carrying ``tok-before-line``, its outcome pushed;
- ``q-before-panel``, denied by a tap on the hub page's panel, its outcome pushed;
- ``q-before-void``, approved on the panel, its ticket made void;
- ``q-before-pending``, pending, its card carrying ``tok-before-pending``;
- ``q-before-expired``, written a day earlier and expired, its outcome pushed.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1): move the label to 21,
carry every record (§4:4), and give each answer who tapped, and nothing else: an answer
reads as the request's person's, since ADR-0361 §4:8 carried out a tap from no one else,
its level not recorded, never a level, which a check reads as none (ADR-0377 §4:3, §4:4).
A request with no answer is not rewritten. A file it cannot carry so is refused and left
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
from record_homes import decoded_tables, homeless_tables
from request_tappers import decoded, untapped

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalGiver,
    ApprovalRequestState,
    ApprovalStepAnswer,
    ApprovalTap,
    Sureness,
    TicketState,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "plans-before-tap-person.db"

#: When the previous release wrote the file, and when the head opens it: an hour later.
_WROTE_AT: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=1)

_ANSWERED: Final = ["q-before-line", "q-before-panel", "q-before-void"]
_UNANSWERED: Final = ["q-before-pending", "q-before-expired"]
_REQUESTS: Final = [
    "q-before-line",
    "q-before-panel",
    "q-before-void",
    "q-before-pending",
    "q-before-expired",
]
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
    """Labelled 20, its tables and requests as the docstring names, no answer naming a tapper."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "20"
    assert set(dumped) == _TABLES
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert len(dumped["activation_effects"]) == len(_REQUESTS)
    assert dumped["scheduled_tasks"] == []
    records = {row[0]: json.loads(row[-1]) for row in dumped["approval_requests"]}
    assert sorted(records) == sorted(_REQUESTS)
    assert {one: records[one]["state"] for one in _REQUESTS} == {
        "q-before-line": "approved",
        "q-before-panel": "denied",
        "q-before-void": "approved",
        "q-before-pending": "pending",
        "q-before-expired": "expired",
    }
    answers = {one: records[one]["answer"] for one in _REQUESTS}
    assert [one for one, answer in answers.items() if answer is None] == _UNANSWERED
    assert all(set(answers[one]) == {"who", "at"} for one in _ANSWERED)


async def test_every_answer_is_upgraded_to_the_requests_person_at_no_recorded_level(
    legacy: Path,
) -> None:
    """ADR-0377 §4:3: the request's person's; its level not recorded, read as none (§4:4)."""
    store = _open(legacy)
    try:
        export = await store.export()
        read = await store.approval_requests(_REQUESTS)
        by_token = await store.approval_request_by_token("tok-before-line")
    finally:
        store.close()

    assert _label(legacy) == "22"
    assert export.schema_version == 32
    assert [one.id for one in export.approval_requests] == _REQUESTS
    assert read == export.approval_requests
    answers = {one.id: one.answer for one in read}
    assert answers == {
        "q-before-line": ApprovalTap(
            who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD,
            at=_WROTE_AT + timedelta(minutes=3),
            person=OWNER_PERSON_ID,
        ),
        "q-before-panel": ApprovalTap(
            who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
            at=_WROTE_AT + timedelta(minutes=4),
            person=OWNER_PERSON_ID,
        ),
        "q-before-void": ApprovalTap(
            who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
            at=_WROTE_AT + timedelta(minutes=5),
            person=OWNER_PERSON_ID,
        ),
        "q-before-pending": None,
        "q-before-expired": None,
    }
    assert all(
        one is None or (one.level is None and one.level_read is Sureness.NONE)
        for one in answers.values()
    )
    assert by_token is not None
    assert by_token.answer == answers["q-before-line"]


async def test_every_other_record_and_field_is_carried_as_it_stands(legacy: Path) -> None:
    """ADR-0326 §4:4: each answer gains the two fields alone; no other row moves."""
    before = _dump(legacy)

    _open(legacy).close()

    after = _dump(legacy)
    assert set(after) == _TABLES
    untouched = _TABLES - {"meta", "approval_requests"}
    # The step past 21 writes each effect's and observation's home (ADR-0383 §5:1).
    assert homeless_tables({table: after[table] for table in untouched}) == decoded_tables(
        {table: before[table] for table in untouched}
    )
    assert untapped(after["approval_requests"]) == decoded(before["approval_requests"])
    unanswered = [row for row in before["approval_requests"] if row[0] in _UNANSWERED]
    assert [row for row in after["approval_requests"] if row[0] in _UNANSWERED] == unanswered
    states = {
        one[0]: (one[-1]["state"], one[-1]["ticket"]) for one in decoded(after["approval_requests"])
    }
    assert states == {
        "q-before-line": ("approved", "held"),
        "q-before-panel": ("denied", None),
        "q-before-void": ("approved", "void"),
        "q-before-pending": ("pending", None),
        "q-before-expired": ("expired", None),
    }


async def test_the_upgraded_file_reopens_as_it_is(legacy: Path) -> None:
    """The step is taken once: a second open at 21 rewrites nothing."""
    _open(legacy).close()
    upgraded = _dump(legacy)

    _open(legacy).close()

    assert _dump(legacy) == upgraded


async def test_a_tap_after_the_upgrade_records_its_tapper_beside_the_carried_ones(
    legacy: Path,
) -> None:
    """ADR-0377 §4:1: a tap landing on the upgraded file records who and how sure, and both
    it and a carried answer outlive a step and a reopen."""
    tap = ApprovalTap(
        who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD,
        at=_NOW,
        person=OWNER_PERSON_ID,
        level=Sureness.WEAK,
    )
    store = _open(legacy)
    try:
        step = await store.answer_approval_request(
            "q-before-pending", ApprovalRequestState.APPROVED, tap
        )
        voided = await store.void_approval_ticket("q-before-line")
        held = await store.approval_requests(["q-before-pending", "q-before-line"])
    finally:
        store.close()

    reopened = _open(legacy)
    try:
        assert await reopened.approval_requests(["q-before-pending", "q-before-line"]) == held
    finally:
        reopened.close()
    assert step.answer is ApprovalStepAnswer.CHANGED
    assert voided.answer is ApprovalStepAnswer.CHANGED
    pending, line = held
    assert pending.answer == tap
    assert pending.ticket is TicketState.HELD
    assert line.answer is not None
    assert (line.answer.person, line.answer.level) == (OWNER_PERSON_ID, None)
    assert line.ticket is TicketState.VOID


async def test_a_failed_upgrade_leaves_the_file_as_it_found_it(legacy: Path) -> None:
    """§4:3: the upgrade completes or leaves the file as it found it, the label included."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TRIGGER spoiled AFTER UPDATE ON approval_requests BEGIN SELECT 1; END")
    before = _dump(legacy)

    with pytest.raises(PlanningError):
        _open(legacy)

    assert _label(legacy) == "20"
    assert _dump(legacy) == before


@pytest.mark.parametrize(
    ("request_id", "damage"),
    [
        ("q-before-line", "not json"),
        ("q-before-pending", "[]"),
        ("q-before-line", '{"id":"q-before-line","answer":{"who":"x","at":"y"}}'),
        ("q-before-line", '{"id":"q-before-line","person":"person:owner","answer":"tapped"}'),
        (
            "q-before-line",
            '{"id":"q-before-line","person":"person:owner",'
            '"answer":{"who":"x","at":"y","person":"person:owner"}}',
        ),
        (
            "q-before-line",
            '{"id":"q-before-line","person":"person:owner",'
            '"answer":{"who":"x","at":"y","level":"normal"}}',
        ),
        (
            "q-before-line",
            '{"id":"q-before-line","person":"person:owner",'
            '"answer":{"who":"x","at":"y"},"why":"\\ud800"}',
        ),
    ],
    ids=[
        "not-json",
        "not-an-object",
        "no-person",
        "answer-not-an-object",
        "tapped-already",
        "level-already",
        "unencodable",
    ],
)
async def test_a_request_no_earlier_release_wrote_is_refused_as_damage(
    legacy: Path, request_id: str, damage: str
) -> None:
    """ADR-0326 §5:1: refused, and the file left exactly as it was found (§4:3)."""
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE approval_requests SET data = ? WHERE id = ?", (damage, request_id))
    before = _dump(legacy)

    with pytest.raises(PlanningError, match=request_id):
        _open(legacy)

    assert _label(legacy) == "20"
    assert _dump(legacy) == before
