"""The SQLite audit trail, against its shared conformance suite and beyond it.

The suite covers what every ``AuditTrail`` owes: write-once, the resolution
invariant, ordering, bounds, and detachment on both paths. What it cannot cover
is the half this implementation exists for — that a decision is still there, and
still says what was approved, after the process that made it has gone (ADR-0036
§2).

The conformance subclass runs against ``:memory:``, so it touches no filesystem
and needs no ``integration`` mark. The tests that open a real file say so.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from audit_trail_contract import AuditTrailContract
from permission_builders import AT, action, decision, ruling, tool

from ai_assistant.core.errors import AuditError, DuplicateDecisionError
from ai_assistant.core.types import DataTier, PermissionOutcome
from ai_assistant.permissions import SqliteAuditTrail

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import AuditTrail


@pytest.fixture
def ephemeral() -> Iterator[SqliteAuditTrail]:
    """An in-memory trail, closed after the test."""
    trail = SqliteAuditTrail()
    try:
        yield trail
    finally:
        trail.close()


class TestSqliteAuditTrailContract(AuditTrailContract):
    """Runs SqliteAuditTrail through the shared AuditTrail conformance suite."""

    @pytest.fixture
    def trail(self, ephemeral: SqliteAuditTrail) -> AuditTrail:
        return ephemeral


async def test_a_refused_write_leaves_the_trail_untouched(ephemeral: SqliteAuditTrail) -> None:
    """A rejected append must not half-happen.

    The contract exercises atomicity against a race; this is the same property
    from the other side — a refusal is not a partial write with an exception on
    top.
    """
    await ephemeral.record(decision("d-1"))

    with pytest.raises(DuplicateDecisionError):
        await ephemeral.record(decision("d-1"))

    assert len(await ephemeral.export()) == 1


async def test_the_refusals_share_one_catchable_base(ephemeral: SqliteAuditTrail) -> None:
    """A caller that only wants "the trail would not accept this" gets one handler."""
    await ephemeral.record(decision("d-1"))

    with pytest.raises(AuditError):
        await ephemeral.record(decision("d-1"))


async def test_a_resolving_deny_citing_an_authorisation_is_refused(
    ephemeral: SqliteAuditTrail,
) -> None:
    """The half of the pointer rule ``PermissionRuling`` already makes unreachable.

    No validated construction produces one, so the value is written in
    afterwards, past the frozen model's guard, the way corrupted state would
    present it. ``record`` revalidates before the pointer check sees it, so the
    assertion is on ``AuditError`` — the family both layers belong to — rather
    than on which one fired.

    Deliberately here rather than in the shared suite: putting it there would
    oblige every implementation to defend against models built outside the
    type's contract.
    """
    confirmed = decision("d-confirm")
    await ephemeral.record(confirmed)
    answer = decision("d-answer", ruled=ruling(PermissionOutcome.DENY), resolves=confirmed.id)
    object.__setattr__(answer.ruling, "authorised_by", confirmed.id)

    with pytest.raises(AuditError):
        await ephemeral.record(answer)

    assert await ephemeral.get("d-answer") is None


async def test_clearing_an_empty_trail_removes_nothing(ephemeral: SqliteAuditTrail) -> None:
    assert await ephemeral.clear() == 0


async def test_two_decisions_a_microsecond_apart_order_correctly(
    ephemeral: SqliteAuditTrail,
) -> None:
    """The sort key is exact, which a float epoch second is not at present-day values.

    ``timestamp()`` returns a double, and a 2026 instant carrying microseconds
    needs sixteen significant digits — right at the edge — so the natural
    implementation can order two adjacent decisions arbitrarily. Ordering is the
    trail's contract, so the key is integer microseconds instead.
    """
    await ephemeral.record(decision("d-first", decided_at=AT))
    await ephemeral.record(decision("d-second", decided_at=AT + timedelta(microseconds=1)))

    assert [each.id for each in await ephemeral.recent()] == ["d-second", "d-first"]


async def test_the_single_resolution_rule_is_also_a_database_constraint(
    ephemeral: SqliteAuditTrail,
) -> None:
    """Defence in depth: the unique index holds even if the check were bypassed.

    Asserted by going around the store's own validation entirely — a second
    resolving row inserted straight into the table — because that is the only
    way to observe the constraint rather than the check in front of it.
    """
    await ephemeral.record(decision("d-confirm"))
    answer = decision(
        "d-answer",
        ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-confirm"),
        resolves="d-confirm",
    )
    await ephemeral.record(answer)

    with pytest.raises(sqlite3.IntegrityError):
        ephemeral._conn.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("d-answer-2", 0, "d-confirm", answer.model_dump_json()),
        )


async def test_a_row_the_model_no_longer_accepts_is_reported_not_returned(
    ephemeral: SqliteAuditTrail,
) -> None:
    """A corrupted or downgraded database is a fault to report, not a record to hand on.

    Returning ``None`` would make a tampered row indistinguishable from a
    decision that was never made, which is exactly the ambiguity an audit trail
    exists to remove.
    """
    ephemeral._conn.execute(
        "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
        ("d-bad", 0, None, '{"id": "d-bad"}'),
    )

    with pytest.raises(AuditError):
        await ephemeral.get("d-bad")
    with pytest.raises(AuditError):
        await ephemeral.export()


@pytest.mark.integration
async def test_a_recorded_decision_survives_the_process_that_made_it(tmp_path: Path) -> None:
    """The reason this implementation exists (ADR-0036 §2).

    ADR-0021 §1 embeds the whole declaration so the trail still says what was
    approved after a restart has rebuilt the registry under different ids. That
    guarantee is about a record that outlives the process, so it is asserted
    across two connections to one file rather than within one object's lifetime.
    """
    path = tmp_path / "audit.db"
    disclosing = tool(discloses=(DataTier.PERSONAL,))
    original = decision("d-1", request=action(tool=disclosing, parameters={"to": "a@example.com"}))

    first = SqliteAuditTrail(path=path)
    await first.record(original)
    first.close()

    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.get("d-1") == original
        assert (await reopened.recent())[0].tool == disclosing
    finally:
        reopened.close()


@pytest.mark.integration
async def test_the_write_once_rule_survives_a_restart(tmp_path: Path) -> None:
    """History cannot be rewritten by replaying a write into a fresh process."""
    path = tmp_path / "audit.db"
    first = SqliteAuditTrail(path=path)
    await first.record(decision("d-1", ruled=ruling(PermissionOutcome.CONFIRM)))
    first.close()

    reopened = SqliteAuditTrail(path=path)
    try:
        with pytest.raises(DuplicateDecisionError):
            await reopened.record(decision("d-1", ruled=ruling(PermissionOutcome.DENY)))
        stored = await reopened.get("d-1")
        assert stored is not None
        assert stored.ruling.outcome is PermissionOutcome.CONFIRM
    finally:
        reopened.close()


@pytest.mark.integration
async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """A Tier 1 store on disk (ADR-0004), following the memory store's precedent."""
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    trail.close()

    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.integration
async def test_opening_an_unusable_path_is_reported_as_an_audit_error(tmp_path: Path) -> None:
    """A failure to open is this layer's error, not a bare ``sqlite3`` one."""
    with pytest.raises(AuditError):
        SqliteAuditTrail(path=tmp_path / "no_such_dir" / "audit.db")
