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

import asyncio
import json
import sqlite3
import threading
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
    from ai_assistant.core.types import PermissionDecision


@pytest.fixture
def ephemeral() -> Iterator[SqliteAuditTrail]:
    """An in-memory trail, closed after the test."""
    trail = SqliteAuditTrail(path=":memory:")
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


async def test_the_per_binding_resolution_rule_is_also_a_database_constraint(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0044 §2b's partial unique index holds even if the checked read were bypassed.

    Asserted by inserting a second resolution of the same concrete binding —
    naming a *different* CONFIRM, so the ``decisions_resolves`` index does not
    catch it — straight into the table, past the store's own validation. Only the
    ``decisions_binding_resolution`` index constrains this, which is the whole
    point of having it beneath the check.
    """
    bind: dict[str, object] = {"execution_id": "exec-a"}  # step_id defaults to "step-1"
    await ephemeral.record(decision("c-1", request=action(**bind)))
    await ephemeral.record(decision("c-2", request=action(**bind)))
    answer = decision(
        "r-1",
        request=action(**bind),
        ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-1"),
        resolves="c-1",
    )
    await ephemeral.record(answer)
    sibling = decision(
        "r-2", request=action(**bind), ruled=ruling(PermissionOutcome.DENY), resolves="c-2"
    )

    with pytest.raises(sqlite3.IntegrityError):
        ephemeral._conn.execute(
            "INSERT INTO decisions("
            "id, decided_at_us, resolves, execution_id, step_id, outcome, data"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("r-2", 0, "c-2", "exec-a", "step-1", "deny", sibling.model_dump_json()),
        )


@pytest.mark.integration
async def test_a_pre_binding_database_is_migrated_and_stays_usable(tmp_path: Path) -> None:
    """A trail written before ADR-0044 grows the binding columns on reopen (§1).

    ``step_id`` and ``outcome`` are backfilled from each row's JSON so the
    per-binding index and the recovery query see them; ``execution_id`` stays
    ``NULL``, since a pre-ADR-0044 decision belongs to no execution — a
    non-concrete binding §2b never constrains. The legacy record stays readable,
    and the reopened trail records and recovers a new concrete binding, proving
    the migrated schema is fully functional.
    """
    path = tmp_path / "audit.db"
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, data TEXT NOT NULL)"
        )
        old = decision("c-old", request=action(step_id="step-old"))
        raw = json.loads(old.model_dump_json())
        del raw["execution_id"]  # a genuinely pre-ADR-0044 record had no such key
        legacy.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("c-old", 0, None, json.dumps(raw)),
        )
        legacy.commit()
    finally:
        legacy.close()

    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.get("c-old") == old  # readable, execution_id defaults to None
        row = reopened._conn.execute(
            "SELECT execution_id, step_id, outcome FROM decisions WHERE id = ?", ("c-old",)
        ).fetchone()
        assert row == (None, "step-old", "confirm")  # step_id/outcome backfilled, execution_id NULL

        # The migrated schema supports the new binding features end to end.
        await reopened.record(decision("c-new", request=action(execution_id="exec-a")))
        found = await reopened.pending_confirmation(execution_id="exec-a", step_id="step-1")
        assert found is not None
        assert found.id == "c-new"
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_corrupt_legacy_row_is_reported_as_an_audit_error_not_a_raw_json_error(
    tmp_path: Path,
) -> None:
    """A malformed blob in a pre-ADR-0044 table is reported, not left to escape.

    Migration reads each legacy row's JSON to backfill the binding columns. A
    blob that is not JSON must surface as this layer's ``AuditError`` — the same
    "reported, not returned" rule ``_decode`` applies at read time — rather than a
    bare ``JSONDecodeError`` leaking past ``_setup``'s ``sqlite3``/``OSError``
    boundary and aborting construction with a foreign exception.
    """
    path = tmp_path / "audit.db"
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, data TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("c-bad", 0, None, "{not valid json"),
        )
        legacy.commit()
    finally:
        legacy.close()

    with pytest.raises(AuditError):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
async def test_a_second_trail_opens_a_migrated_legacy_database_without_failing(
    tmp_path: Path,
) -> None:
    """Concurrent upgrade is serialised, so a second opener does not double-ALTER.

    ``_setup`` takes the write lock (``BEGIN IMMEDIATE``) before it inspects the
    schema, so two processes upgrading one pre-ADR-0044 file cannot both run
    ``ALTER TABLE ... ADD COLUMN`` — the loser waits and re-reads the migrated
    columns, its ``missing`` set coming back empty. Exercised sequentially here
    (the observable outcome of that serialisation): a second trail opens the
    already-migrated file cleanly, and both read the legacy record and drive the
    new binding features.
    """
    path = tmp_path / "audit.db"
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, data TEXT NOT NULL)"
        )
        old = decision("c-old", request=action(step_id="step-1"))
        raw = json.loads(old.model_dump_json())
        del raw["execution_id"]
        legacy.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("c-old", 0, None, json.dumps(raw)),
        )
        legacy.commit()
    finally:
        legacy.close()

    first = SqliteAuditTrail(path=path)
    second = SqliteAuditTrail(path=path)  # the already-migrated file opens cleanly
    try:
        assert await first.get("c-old") == old
        assert await second.get("c-old") == old
        await first.record(decision("c-a", request=action(execution_id="exec-a")))
        found = await second.pending_confirmation(execution_id="exec-a", step_id="step-1")
        assert found is not None
        assert found.id == "c-a"
    finally:
        first.close()
        second.close()


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
def test_the_rollback_journal_is_owner_only_too(tmp_path: Path) -> None:
    """A sidecar holds the same Tier 1 pages the database does.

    A rollback journal created at the ambient umask would expose recorded
    decisions to any local account that can traverse the directory, for as long
    as a write transaction is open. It does not happen — SQLite gives a journal
    the mode of the database file it belongs to, and the chmod above runs before
    any write — but that is a property of another project's file layer, so it is
    asserted rather than assumed.
    """
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    try:
        trail._conn.execute("BEGIN IMMEDIATE")
        trail._conn.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("d-1", 0, None, decision("d-1").model_dump_json()),
        )
        sidecars = [each for each in tmp_path.iterdir() if each != path]
        assert sidecars, "expected a rollback journal while a write is open"
        assert all(each.stat().st_mode & 0o777 == 0o600 for each in sidecars)
        trail._conn.rollback()
    finally:
        trail.close()


@pytest.mark.integration
async def test_clear_counts_what_it_actually_deleted(tmp_path: Path) -> None:
    """Two trails on one file: the count must cover rows this instance never wrote.

    A ``SELECT COUNT(*)`` in front of the delete reads before SQLite opens the
    write transaction, so a row appended by the other instance in between would
    be erased and not counted — and the ``asyncio.Lock`` is per instance, so it
    arbitrates nothing here. The count therefore comes from the delete itself.
    """
    path = tmp_path / "audit.db"
    first = SqliteAuditTrail(path=path)
    second = SqliteAuditTrail(path=path)
    try:
        await first.record(decision("d-1"))
        await second.record(decision("d-2", decided_at=AT + timedelta(hours=1)))

        assert await first.clear() == 2
        assert await second.export() == []
    finally:
        first.close()
        second.close()


@pytest.mark.integration
async def test_opening_an_unusable_path_is_reported_as_an_audit_error(tmp_path: Path) -> None:
    """A failure to open is this layer's error, not a bare ``sqlite3`` one."""
    with pytest.raises(AuditError):
        SqliteAuditTrail(path=tmp_path / "no_such_dir" / "audit.db")


async def test_a_limit_wider_than_sqlite_can_bind_returns_everything(
    ephemeral: SqliteAuditTrail,
) -> None:
    """A Python int has no width; SQLite's bound parameter does.

    ``limit=10**1000`` is strictly positive, so it passes the contract's only
    check, and binding it raises ``OverflowError`` — neither ``ValueError`` nor
    ``AuditError``, so it would leave this layer's error boundary through a
    hole. A bound above any possible row count means "all of them", which is
    what a caller asking for it wants.
    """
    await ephemeral.record(decision("d-1"))
    await ephemeral.record(decision("d-2", decided_at=AT + timedelta(hours=1)))

    found = await ephemeral.recent(limit=10**1000)

    assert [each.id for each in found] == ["d-2", "d-1"]


async def _spin(iterations: int = 50) -> None:
    """Yield to the event loop repeatedly so a pending cancellation can unwind."""
    for _ in range(iterations):
        await asyncio.sleep(0)


@pytest.mark.integration
async def test_cancelling_a_record_does_not_release_the_connection(tmp_path: Path) -> None:
    """A cancelled append must not free the lock while its worker thread runs (ADR-0054).

    ``asyncio.to_thread`` cannot interrupt a running worker, so a cancellation that
    unwound the awaiting coroutine here would release the connection lock while the
    worker was still mid-transaction on the shared connection. This blocks a worker
    inside ``record``, cancels the awaiting task, and asserts the lock stays held
    until the worker finishes, then that a second append lands on an intact trail.
    """
    trail = SqliteAuditTrail(path=tmp_path / "cancel.db")
    entered = threading.Event()
    release = threading.Event()
    original_record = trail._record_sync

    def blocking_record(snapshot: PermissionDecision) -> None:
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_record(snapshot)

    trail._record_sync = blocking_record  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(trail.record(decision("d-1")))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        assert trail._lock.locked()

        first.cancel()
        await _spin()
        # The invariant: cancellation did NOT release the lock — the worker is
        # still running, so the connection is still exclusively held.
        assert trail._lock.locked()

        second = asyncio.ensure_future(
            trail.record(decision("d-2", decided_at=AT + timedelta(hours=1)))
        )
        await _spin()
        assert not second.done()
        assert trail._lock.locked()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second  # must not raise on a concurrently-used connection

        # The connection is intact: the deferred-to-completion first append
        # committed, and the second landed cleanly on top of it.
        assert await trail.get("d-1") is not None
        assert await trail.get("d-2") is not None
        assert not trail._lock.locked()
    finally:
        release.set()
        trail.close()
