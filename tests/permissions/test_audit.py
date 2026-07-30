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
import contextlib
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
from ai_assistant.testing.cancellation import ResourceLog, SuspendedMidWrite, ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import AuditTrail
    from ai_assistant.core.types import PermissionDecision
    from ai_assistant.testing.cancellation import SuspendedCall


def _journal_mode(database: Path) -> int | None:
    """The permission bits of the rollback journal beside ``database``, or ``None``."""
    journal = database.with_name(f"{database.name}-journal")
    return journal.stat().st_mode & 0o777 if journal.exists() else None


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

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[AuditTrail]]:
        """Park a named write's worker thread inside the connection's turn.

        ``arm(operation)`` wraps that operation's ``_<operation>_sync`` — inside
        ``async with self._lock`` and inside the ``to_thread`` the event loop
        cannot interrupt, which is exactly where ADR-0054's bug lived — so the
        first worker to reach it blocks and every later one runs free. Each
        distinct lock site is a separate place the bug can reappear (#370), and
        the sync-method suffix matches the operation name (``record`` →
        ``_record_sync``, ``clear`` → ``_clear_sync``). Blocking there is what
        makes the case deterministic: left to run, a commit finishes in
        microseconds and whether the second caller arrives while the worker still
        holds the connection would be a race, so the invariant would be exercised
        only sometimes.

        Its own trail on its own connection, not the ``ephemeral`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        trail = SqliteAuditTrail(path=":memory:")
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> SuspendedCall:
            original = getattr(trail, f"_{operation}_sync")
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(trail, f"_{operation}_sync", blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=trail, log=log, arm=arm)
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a
            # worker still using it; closing under that is a native crash rather
            # than a reported failure, so give the worker a turn to unwind and
            # let the assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
            trail.close()


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


# --- the schema version marker ----------------------------------------------


def _stored_schema_version(path: Path) -> str | None:
    """Read the ``meta`` marker straight off the file, or ``None`` if there is none."""
    raw = sqlite3.connect(str(path))
    try:
        if not raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone():
            return None
        row = raw.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    finally:
        raw.close()
    return None if row is None else str(row[0])


def _write_legacy_trail(path: Path, decision_id: str) -> PermissionDecision:
    """Seed ``path`` with a pre-marker database holding one decision.

    The pre-ADR-0044 table shape, which is what a real database predating the
    version marker looks like: no ``meta`` table, and no binding columns either.
    """
    old = decision(decision_id, request=action(step_id="step-old"))
    raw_record = json.loads(old.model_dump_json())
    del raw_record["execution_id"]
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, data TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            (decision_id, 0, None, json.dumps(raw_record)),
        )
        legacy.commit()
    finally:
        legacy.close()
    return old


async def test_a_fresh_trail_records_the_schema_version(ephemeral: SqliteAuditTrail) -> None:
    """A database created here is labelled, so a future migration has a marker to read.

    The marker ``SqlitePlanStore`` writes from day one (ADR-0049 §1), which this
    store had none of. Exactly one row, so the label is unambiguous.
    """
    rows = ephemeral._conn.execute(
        "SELECT key, value FROM meta WHERE key = 'schema_version'"
    ).fetchall()

    assert rows == [("schema_version", "1")]


@pytest.mark.integration
async def test_a_pre_marker_database_is_stamped_rather_than_refused(tmp_path: Path) -> None:
    """An existing audit trail with no marker still opens, and gains one.

    The marker arrives after this store had users, so every trail already on disk
    carries none. Refusing them would make a Tier 1 record the user is entitled to
    keep unopenable by the code that wrote it. Backfilling is sound because
    ``_migrate`` is additive and keyed on column presence: it brings any pre-marker
    file to exactly the shape version 1 names, so the stamp records what this open
    established rather than an assumption about what was there before.
    """
    path = tmp_path / "audit.db"
    old = _write_legacy_trail(path, "c-old")
    assert _stored_schema_version(path) is None  # the state every existing trail is in

    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.get("c-old") == old  # the history survives the stamping
        # ...and the migrated, now-labelled schema is fully functional.
        await reopened.record(decision("c-new", request=action(execution_id="exec-a")))
        found = await reopened.pending_confirmation(execution_id="exec-a", step_id="step-1")
        assert found is not None
        assert found.id == "c-new"
    finally:
        reopened.close()

    assert _stored_schema_version(path) == "1"


@pytest.mark.integration
async def test_reopening_a_labelled_trail_keeps_the_one_marker(tmp_path: Path) -> None:
    """A second open neither re-stamps nor trips over the marker already there.

    The stamp is written only where none was found, so reopening cannot lose the
    primary-key race a blind insert would.
    """
    path = tmp_path / "audit.db"
    SqliteAuditTrail(path=path).close()

    reopened = SqliteAuditTrail(path=path)
    try:
        rows = reopened._conn.execute("SELECT key, value FROM meta").fetchall()
    finally:
        reopened.close()

    assert rows == [("schema_version", "1")]


@pytest.mark.integration
async def test_a_failed_migration_leaves_no_marker_behind(tmp_path: Path) -> None:
    """A refused upgrade must not label a database it did not manage to migrate.

    The stamp shares the setup transaction with the create and the migration, so a
    corrupt legacy row rolls back the marker — and the ``meta`` table itself — with
    everything else. The alternative is a database falsely labelled current, which
    the *next* open would then trust and never try to migrate again.
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

    assert _stored_schema_version(path) is None


@pytest.mark.integration
async def test_a_newer_schema_is_refused_before_the_decisions_table_exists(
    tmp_path: Path,
) -> None:
    """A database labelled newer than this code understands is refused, and untouched.

    Refused *before* ``decisions`` is created or migrated — creating a table is a
    write, and code that cannot read the label must not write to the file at all.
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="supports only version"):
        SqliteAuditTrail(path=path)

    check = sqlite3.connect(str(path))
    try:
        tables = {
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        check.close()
    assert "decisions" not in tables


@pytest.mark.integration
async def test_a_newer_marker_on_a_populated_trail_is_refused_rather_than_read(
    tmp_path: Path,
) -> None:
    """A downgrade is reported at open, not deferred to the first raw SQLite error.

    The same rule the trail applies to a row that no longer validates: a database
    this code cannot account for is a fault to report, not records to hand on.
    """
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
    finally:
        trail.close()

    raw = sqlite3.connect(str(path))
    try:
        raw.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="supports only version"):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
async def test_a_non_numeric_marker_is_reported_as_an_audit_error(tmp_path: Path) -> None:
    """A corrupt marker surfaces as this layer's error, not a bare ``ValueError``.

    ``int('')`` raises past ``_setup``'s ``sqlite3``/``OSError`` boundary, so the
    parse is guarded — the same "reported, not returned" rule ``_decode`` applies.
    """
    path = tmp_path / "audit.db"
    SqliteAuditTrail(path=path).close()

    raw = sqlite3.connect(str(path))
    try:
        raw.execute("UPDATE meta SET value = 'one' WHERE key = 'schema_version'")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="non-numeric schema_version"):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
@pytest.mark.parametrize(
    "stored",
    [
        pytest.param(float("inf"), id="a-non-finite-real"),
        pytest.param(1.5, id="a-fractional-real"),
        pytest.param(b"\x01", id="a-blob"),
        pytest.param(None, id="no-value-at-all"),
    ],
)
async def test_a_marker_of_the_wrong_type_is_reported_as_an_audit_error(
    tmp_path: Path, stored: object
) -> None:
    """A marker SQLite hands back as anything but text or an integer is refused.

    The marker this code writes is always TEXT, but ``CREATE TABLE IF NOT EXISTS``
    accepts a pre-existing ``meta`` whose ``value`` column declares no type — and
    such a column stores whatever it is given. ``int(float('inf'))`` raises
    ``OverflowError``, which is neither a ``ValueError`` nor an ``AssistantError``,
    so an unguarded parse would abort construction with an exception no caller of
    this layer can be asked to handle.
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value)")  # no declared type
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (stored,))
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="non-numeric schema_version"):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
async def test_an_integer_marker_of_the_supported_version_is_accepted(tmp_path: Path) -> None:
    """A marker stored as INTEGER 1 rather than '1' still names version 1.

    The type guard refuses what cannot be read as a version; it must not refuse a
    version legibly stored in the other of SQLite's two integral forms, which is
    what an untyped ``meta`` column yields for an unquoted literal.
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value)")
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', 1)")
        raw.commit()
    finally:
        raw.close()

    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
        assert len(await trail.export()) == 1
    finally:
        trail.close()


@pytest.mark.integration
async def test_conflicting_markers_are_refused_rather_than_resolved_by_row_order(
    tmp_path: Path,
) -> None:
    """Two disagreeing markers refuse the open; the first row does not win.

    ``meta``'s primary key makes duplicates unreachable in a table this code
    created, but ``CREATE TABLE IF NOT EXISTS`` accepts a pre-existing ``meta``
    declared without one — so a corrupt or hand-built file can hold both a
    supported and an unsupported version. Reading only the first row would let the
    unsupported one through on the strength of its sibling, which is the refusal
    failing open on exactly the malformed input it exists for.
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT, value TEXT NOT NULL)")  # no primary key
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="2 schema_version rows"):
        SqliteAuditTrail(path=path)

    check = sqlite3.connect(str(path))
    try:
        tables = {
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        check.close()
    assert "decisions" not in tables  # refused before any record table was created


@pytest.mark.integration
async def test_clearing_the_trail_leaves_it_openable(tmp_path: Path) -> None:
    """Burning the book erases the history, not the label the file is read by.

    ``clear`` is wholesale over *decisions*; the marker describes the file's shape,
    so an emptied trail still opens rather than looking like a pre-marker one.
    """
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
        assert await trail.clear() == 1
    finally:
        trail.close()

    assert _stored_schema_version(path) == "1"
    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.export() == []
    finally:
        reopened.close()


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


async def test_resolution_of_reports_an_unreadable_trail_as_an_audit_error(
    ephemeral: SqliteAuditTrail,
) -> None:
    """A read failure must raise, not return ``None`` (ADR-0059 §2).

    ``None`` on an unreadable trail would let recovery classify a still-resolved
    step as trail-unanswerable and route it to cancellation, discarding a durable
    ruling. Closing the connection is the reachable "closed store" the boundary
    names; the query then hits ``sqlite3`` and must surface as this layer's error.
    """
    ephemeral.close()

    with pytest.raises(AuditError):
        await ephemeral.resolution_of(execution_id="exec-a", step_id="step-1")


async def test_resolution_of_reports_a_corrupt_resolution_row_not_none(
    ephemeral: SqliteAuditTrail,
) -> None:
    """A resolution row that no longer validates is reported, like ``get``/``export``.

    Returning ``None`` for a row the model rejects would make a tampered
    resolution indistinguishable from an unresolved binding — the ambiguity the
    ``AuditError`` boundary exists to remove.
    """
    ephemeral._conn.execute(
        "INSERT INTO decisions("
        "id, decided_at_us, resolves, execution_id, step_id, outcome, data"
        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r-bad", 0, "c-1", "exec-a", "step-1", "allow", '{"id": "r-bad"}'),
    )

    with pytest.raises(AuditError):
        await ephemeral.resolution_of(execution_id="exec-a", step_id="step-1")


async def test_resolution_of_rejects_a_projection_that_disagrees_with_the_record(
    ephemeral: SqliteAuditTrail,
) -> None:
    """The blob is the record; a tampered index column must not misroute a ruling (ADR-0059 §2).

    The ``execution_id``/``step_id`` columns are only the fast filter ``record``
    maintains — the decoded decision is authoritative. A resolution whose column
    was tampered to match a binding its blob does not name is a corrupt store, and
    ``resolution_of`` must report it rather than hand it back as another binding's
    ruling — the recovery it feeds would otherwise *act* on a mis-attributed
    resolution.
    """
    bind: dict[str, object] = {"execution_id": "exec-b"}  # the resolution genuinely names exec-b
    await ephemeral.record(decision("c-1", request=action(**bind)))
    await ephemeral.record(
        decision(
            "r-1",
            request=action(**bind),
            ruled=ruling(PermissionOutcome.ALLOW, authorised_by="c-1"),
            resolves="c-1",
        )
    )
    # Tamper only the projection column, leaving the JSON blob (which names exec-b) intact.
    ephemeral._conn.execute("UPDATE decisions SET execution_id = ? WHERE id = ?", ("exec-a", "r-1"))

    with pytest.raises(AuditError):
        await ephemeral.resolution_of(execution_id="exec-a", step_id="step-1")


async def test_resolution_of_rejects_a_confirm_masquerading_as_a_resolution(
    ephemeral: SqliteAuditTrail,
) -> None:
    """A tampered ``resolves`` projection must not turn a pending CONFIRM into a resolution.

    ``_BINDING_RESOLUTION`` selects on ``resolves IS NOT NULL``, so corrupting only
    that column makes a still-pending ``CONFIRM`` (or a direct decision) match. Its
    binding blob agrees with the query, so the binding check passes — but the
    decoded record resolves nothing, so it is not a resolution at all. The
    ALLOW-or-DENY guarantee rests on the blob's ``resolves``, not the column: a
    corrupt store is reported, never returned as the question it actually is.
    """
    await ephemeral.record(decision("c-1", request=action(execution_id="exec-a")))
    assert await ephemeral.resolution_of(execution_id="exec-a", step_id="step-1") is None

    # Tamper only the resolves projection; the blob is still a pending CONFIRM.
    ephemeral._conn.execute("UPDATE decisions SET resolves = ? WHERE id = ?", ("d-phantom", "c-1"))

    with pytest.raises(AuditError):
        await ephemeral.resolution_of(execution_id="exec-a", step_id="step-1")


async def test_expires_at_is_persisted_and_read_back(ephemeral: SqliteAuditTrail) -> None:
    """The durable deadline survives ``record`` → read, in the blob and the column (ADR-0059 §1).

    The blob round-trips the value like every other field; the ``expires_at_us``
    column is the queryable projection a future expiry filter reads without
    decoding every record.
    """
    deadline = AT + timedelta(hours=1)
    parked = decision("c-1", ruled=ruling(PermissionOutcome.CONFIRM), expires_at=deadline)
    await ephemeral.record(parked)

    reloaded = await ephemeral.get("c-1")
    assert reloaded is not None
    assert reloaded.expires_at == deadline
    row = ephemeral._conn.execute(
        "SELECT expires_at_us FROM decisions WHERE id = ?", ("c-1",)
    ).fetchone()
    assert row[0] is not None


async def test_a_decision_with_no_lifetime_stores_a_null_deadline(
    ephemeral: SqliteAuditTrail,
) -> None:
    """``expires_at is None`` — no lifetime — is a ``NULL`` column, its single meaning (§1)."""
    await ephemeral.record(decision("d-1"))

    row = ephemeral._conn.execute(
        "SELECT expires_at_us FROM decisions WHERE id = ?", ("d-1",)
    ).fetchone()
    assert row[0] is None


@pytest.mark.integration
async def test_a_pre_0059_database_grows_the_deadline_column(tmp_path: Path) -> None:
    """A table with the ADR-0044 columns but no deadline column grows it ``NULL`` (§1).

    ``expires_at`` did not exist before ADR-0059, so a legacy row is left ``NULL``
    — "no lifetime", the same shape the ADR-0044 ``execution_id`` migration used —
    and stays readable. The reopened trail then records and reads a new deadline
    end to end, proving the migrated schema is fully functional.
    """
    path = tmp_path / "audit.db"
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, execution_id TEXT, step_id TEXT, outcome TEXT, data TEXT NOT NULL)"
        )
        old = decision("c-old", request=action(step_id="step-1"))
        raw = json.loads(old.model_dump_json())
        del raw["expires_at"]  # a genuinely pre-ADR-0059 record had no such key
        legacy.execute(
            "INSERT INTO decisions("
            "id, decided_at_us, resolves, execution_id, step_id, outcome, data"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c-old", 0, None, None, "step-1", "confirm", json.dumps(raw)),
        )
        legacy.commit()
    finally:
        legacy.close()

    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.get("c-old") == old  # readable, expires_at defaults to None
        row = reopened._conn.execute(
            "SELECT expires_at_us FROM decisions WHERE id = ?", ("c-old",)
        ).fetchone()
        assert row == (None,)  # a legacy row has no deadline

        deadline = AT + timedelta(hours=1)
        await reopened.record(
            decision(
                "c-new",
                request=action(execution_id="exec-a"),
                ruled=ruling(PermissionOutcome.CONFIRM),
                expires_at=deadline,
            )
        )
        found = await reopened.get("c-new")
        assert found is not None
        assert found.expires_at == deadline
    finally:
        reopened.close()


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
def test_a_journal_opened_during_setup_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0004 §1, §4 reach the sidecars, and reach them from the first write (#489).

    SQLite copies the *database file's* mode onto every rollback journal it creates
    for it, so restricting the file after the schema is built and migrated leaves
    every journal opened in between carrying the process umask — and an interrupted
    write leaves that journal on disk holding Tier 1 pages beside a ``0600`` base
    file. Setup's ``BEGIN IMMEDIATE`` is exactly such a write, and :meth:`_migrate`
    inside it can rewrite the whole ``decisions`` table.

    Observed **inside** ``_setup`` rather than after it, because that is the only
    place the difference is visible: by the time the constructor returns the
    transaction has committed, and a journal provoked afterwards inherits ``0600``
    under either ordering — which is why the case this replaces passed on the
    unfixed code. The hook is ``_check_schema_version``, which runs inside that
    transaction, after the ``meta`` schema has already forced a page write.

    The file is pre-created ``0644`` so the case does not depend on the runner's
    umask — and because reopening an existing trail is the common path anyway.
    """
    path = tmp_path / "audit.db"
    path.touch()
    path.chmod(0o644)
    observed: list[int | None] = []
    original = SqliteAuditTrail._check_schema_version

    def observing(trail: SqliteAuditTrail, conn: sqlite3.Connection) -> bool:
        labelled = original(trail, conn)
        observed.append(_journal_mode(path))
        return labelled

    monkeypatch.setattr(SqliteAuditTrail, "_check_schema_version", observing)

    SqliteAuditTrail(path=path).close()

    assert observed[0] is not None, "setup should have opened a journal"
    assert observed == [0o600]


@pytest.mark.integration
def test_a_sidecar_that_was_already_there_is_restricted_at_open(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches a sidecar this process did not create either (#490).

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one that is already on disk: a ``-wal``/``-shm`` left by a
    process that put this file into WAL mode, or a ``-journal`` left by a crash,
    keeps its own mode across a reopen and then takes Tier 1 pages.

    Planted at ``0644`` and asserted after a *reopen*, because that is the only
    shape that can fail: a sidecar SQLite makes for an already-``0600`` file is
    ``0600`` however this store is written. Nothing in this codebase sets
    ``journal_mode``, so in the default rollback-journal mode SQLite neither reads
    nor writes these two — the mode asserted is this store's own chmod and nothing
    else.
    """
    path = tmp_path / "audit.db"
    SqliteAuditTrail(path=path).close()
    sidecars = [path.with_name(f"{path.name}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    SqliteAuditTrail(path=path).close()

    assert [each.stat().st_mode & 0o777 for each in sidecars] == [0o600, 0o600]


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
