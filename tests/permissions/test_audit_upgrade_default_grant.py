"""ADR-0326 §4:2's test, for ADR-0380 §3:2: the audit trail before the default grant.

``tests/permissions/legacy/audit-before-adr-0380.db`` was written by the previous
release's own ``SqliteAuditTrail`` (the build at ``522da83f3``, at the label ``6``),
through its public ``record``, ``claim_invocation`` and ``complete_invocation`` alone,
never by hand-built SQL. It holds two decisions, each holding by value the declaration
that build declared, which had no default grant:

- ``d-before-email``, a ``CONFIRM`` on ``send_email``;
- ``d-before-pin``, an ``ALLOW`` on ``pin_memory``, with the invocation it was claimed
  and completed by.

A declaration with no default grant leaves the field out of its dump, so each stored
decision validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stays ``6``. The head opens a copy, reads every record back as it was, each
declaration with no default grant (ADR-0380 §3:1), and a decision it then records holds
the declaration this build declares, default grant and all.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.types import (
    ActionRequest,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolOutcome,
)
from ai_assistant.orchestration.person_calls import PIN
from ai_assistant.permissions import SqliteAuditTrail
from ai_assistant.tools.send_email import EMAIL

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "audit-before-adr-0380.db"

#: When the previous release wrote its first decision, and when the head opens the file.
_WROTE_AT: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=1)

_DECISIONS: Final = ("d-before-email", "d-before-pin")


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "audit.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _label(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        (value,) = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return str(value)


def _stored(path: Path) -> dict[str, str]:
    """Each decision as the bytes the file holds it in."""
    with sqlite3.connect(path) as conn:
        return {str(one): str(data) for one, data in conn.execute("SELECT id, data FROM decisions")}


def _open(path: Path) -> SqliteAuditTrail:
    return SqliteAuditTrail(path=path, now=lambda: _NOW)


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 6, the decisions the docstring names, and no declaration with a grant."""
    assert _label(_FIXTURE) == "6"
    stored = _stored(_FIXTURE)
    assert sorted(stored) == sorted(_DECISIONS)
    assert all('"default_grant"' not in data for data in stored.values())


async def test_every_record_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4, ADR-0380 §3:1: each whole, each declaration with no grant."""
    trail = _open(legacy)
    try:
        decisions = {one.id: one for one in await trail.export()}
        invocations = await trail.export_invocations()
    finally:
        trail.close()

    assert sorted(decisions) == sorted(_DECISIONS)
    assert {key: (one.tool.capability, one.ruling.outcome) for key, one in decisions.items()} == {
        "d-before-email": ("send_email", PermissionOutcome.CONFIRM),
        "d-before-pin": ("pin_memory", PermissionOutcome.ALLOW),
    }
    assert all(one.tool.default_grant is None for one in decisions.values())
    assert [(one.invocation.decision_id, one.invocation.outcome) for one in invocations] == [
        ("d-before-pin", None),
        ("d-before-pin", ToolOutcome.SUCCEEDED),
    ]
    assert {key: one.model_dump_json() for key, one in decisions.items()} == _stored(legacy)
    assert _label(legacy) == "6"


async def test_a_stored_declaration_differs_from_this_builds_by_its_default_grant_alone(
    legacy: Path,
) -> None:
    """The one change across the release: what an earlier decision pinned lacks the grant.

    So a decision recorded before the field never equals a request built from the
    declaration this build declares, as after any edit to a declaration (ADR-0380's
    consequences).
    """
    trail = _open(legacy)
    try:
        decisions = {one.id: one for one in await trail.export()}
    finally:
        trail.close()

    for decision, current in (
        (decisions["d-before-email"], EMAIL),
        (decisions["d-before-pin"], PIN),
    ):
        assert current.default_grant is not None
        assert decision.tool != current
        assert decision.tool == current.model_copy(update={"default_grant": None})


async def test_a_decision_recorded_after_holds_its_default_grant_across_a_reopen(
    legacy: Path,
) -> None:
    """The opened file keeps a declaration with its grant, at the label it had."""
    trail = _open(legacy)
    try:
        await trail.record(
            PermissionDecision.from_request(
                ActionRequest(tool=PIN, parameters={"memory": "M2"}),
                PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="ruled allow"),
                id="d-after-pin",
                decided_at=_NOW,
            )
        )
    finally:
        trail.close()

    reopened = _open(legacy)
    try:
        read = await reopened.get("d-after-pin")
    finally:
        reopened.close()

    assert read is not None
    assert read.tool == PIN
    assert read.tool.default_grant == PIN.default_grant
    assert _label(legacy) == "6"
