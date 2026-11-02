"""ADR-0326 §4:2's test, for ADR-0361: a file the release before the approval requests wrote.

``tests/planning/legacy/plans-before-approvals.db`` was written by the previous release's
own ``SqlitePlanStore`` (the build at ``1c03cc54b``, at the label ``18``), through its
public members alone, never by hand-built SQL. It holds:

- one stop record, ``act-before-stopped``;
- three effect records of ``act-before-1`` and ``act-before-2``: a call finished, a
  message claimed with no outcome, and a call spending a question part;
- one observation record, of ``activation:act-before-1``;
- two scheduled tasks spawned by ``act-before-spawner``, ``t-before-pending``, due at an
  instant, and ``t-before-pushed``, pushed to ``act-before-task`` and settled done, with
  their spawns' effect records.

The head opens a copy and must upgrade it in place (ADR-0326 §4:1, ADR-0361 §8:2): add
the empty ``approval_requests`` table, carry every record whole (§4:4), move the label to
19 (§4:5), and leave the file exactly as it found it where the open fails (§4:3). The
upgraded file then holds a request like any other, and the pushed mark on its outcome
outlives a reopen (ADR-0361 §3:7).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ApprovalGiver,
    ApprovalOutcomePush,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    ApprovalWriteAnswer,
    CostBasis,
    Idempotency,
    OccurrenceState,
    QuestionPart,
    RequestedCall,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.testing import with_phase_declaration

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).parent / "legacy" / "plans-before-approvals.db"

#: When the previous release wrote the file, and when the head opens it: the day after.
_WROTE_AT = datetime(2026, 10, 31, 12, tzinfo=UTC)
_NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)

_TABLES_BEFORE = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
}

_EFFECTS = [
    "effect-before-call",
    "effect-before-message",
    "effect-before-part",
    "spawn-t-before-pending",
    "spawn-t-before-pushed",
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


def _request() -> ApprovalRequest:
    """A request as ``request_approval`` writes it, the day after the file was written."""
    tool = ToolDefinition(
        **with_phase_declaration(  # type: ignore[arg-type]  # heterogeneous test kwargs
            {
                "id": "stays",
                "capability": "book_stay",
                "description": "Book a stay.",
                "risk_level": RiskLevel.HIGH,
                "reversibility": Reversibility.IRREVERSIBLE,
                "side_effecting": True,
                "reads": (),
                "writes": (),
                "discloses": (),
                "cost": ToolCost(basis=CostBasis.FREE),
                "idempotency": Idempotency.NONE,
                "parameters_schema": {
                    "type": "object",
                    "properties": {"hotel": {"type": "string"}},
                    "required": ["hotel"],
                },
            }
        )
    )
    return ApprovalRequest(
        id="q-after",
        person="person:owner",
        activation_id="act-after",
        round="r1",
        call=RequestedCall(tool=tool, values={"hotel": "the Ritz"}),
        why="You asked me to book the stay.",
        written_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )


def _asking(request: ApprovalRequest) -> ActivationEffect:
    return ActivationEffect(
        id="ask-after",
        activation_id=request.activation_id,
        round=request.round,
        capability="request_approval",
        values_digest="e" * 64,
        decision_id="d-ask-after",
        claimed_at=_NOW,
        request=request.id,
    )


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 18, the five tables, and the records the docstring names."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "18"
    assert set(dumped) == _TABLES_BEFORE
    assert dumped["stopped_activations"] == [("act-before-stopped",)]
    assert sorted(str(row[0]) for row in dumped["activation_effects"]) == sorted(_EFFECTS)
    assert [str(row[0]) for row in dumped["observations"]] == ["activation:act-before-1"]
    assert sorted(str(row[0]) for row in dumped["scheduled_tasks"]) == [
        "t-before-pending",
        "t-before-pushed",
    ]


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
    assert export.schema_version == 29
    assert export.stopped_activations == ("act-before-stopped",)
    effects = {one.id: one for one in export.activation_effects}
    assert list(effects) == _EFFECTS
    assert effects["effect-before-call"].outcome is ToolOutcome.SUCCEEDED
    assert effects["effect-before-message"].outcome is None
    assert effects["effect-before-part"].part == QuestionPart(round="q-round", part=1)
    assert all(one.ticket is None and one.request is None for one in effects.values())
    assert [one.episode for one in export.observations] == ["activation:act-before-1"]
    tasks = {one.id: one for one in export.scheduled_tasks}
    assert tasks["t-before-pending"].occurrences[0].state is OccurrenceState.PENDING
    assert tasks["t-before-pending"].occurrences[0].due_at == _WROTE_AT + timedelta(days=2)
    assert tasks["t-before-pushed"].occurrences[0].state is OccurrenceState.DONE
    assert export.approval_requests == ()
    # The step moves the label and adds the one empty table, and rewrites no row.
    after = _dump(legacy)
    assert set(after) == {*_TABLES_BEFORE, "approval_requests"}
    assert after["approval_requests"] == []
    assert {table: after[table] for table in before if table != "meta"} == {
        table: rows for table, rows in before.items() if table != "meta"
    }


async def test_the_upgraded_file_holds_a_request_and_keeps_what_it_carried(
    legacy: Path,
) -> None:
    """The carried records still decide what they decided, and a request lands and reopens.

    The stop record still refuses a request of the stopped activation, the spent part is
    still found, and a request's outcome marked pushed, its activation never admitted,
    is found with its mark after a reopen, so a restart can push it again (§3:7).
    """
    request = _request()
    store = SqlitePlanStore(path=legacy, now=_now)
    try:
        stopped = request.model_copy(update={"activation_id": "act-before-stopped"})
        with pytest.raises(ClaimStopped):
            await store.write_approval_request(
                stopped,
                _asking(request).model_copy(update={"activation_id": "act-before-stopped"}),
                match=None,
            )
        written = await store.write_approval_request(request, _asking(request), match=None)
        tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=_NOW)
        await store.answer_approval_request("q-after", ApprovalRequestState.APPROVED, tap)
        pushed = await store.mark_approval_outcome_pushed("q-after", "act-approval")
    finally:
        store.close()

    reopened = SqlitePlanStore(path=legacy, now=_now)
    try:
        assert written.answer is ApprovalWriteAnswer.WRITTEN
        assert pushed is ApprovalOutcomePush.PUSHED
        (found,) = await reopened.pushed_approval_outcomes()
        assert (found.id, found.pushed_to, found.state) == (
            "q-after",
            "act-approval",
            ApprovalRequestState.APPROVED,
        )
        assert await reopened.mark_approval_outcome_pushed("q-after", "act-again") is (
            ApprovalOutcomePush.NOT_DUE
        )
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

    assert _label(legacy) == "18"
    assert _dump(legacy) == before
