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
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from audit_trail_contract import AuditTrailContract
from permission_builders import AT, action, decision, ruling, tool
from recipient_builders import ALICE
from recipient_builders import binding as egress_binding
from recipient_builders import request as egress_request

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidAuthorisationError,
)
from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    CoverageUnrecordedBinding,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    SpanCoverage,
)
from ai_assistant.permissions import SqliteAuditTrail, audit
from ai_assistant.permissions.audit import (
    _run_to_completion,
)
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import AuditTrail, RecipientGrantResolution
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


#: The private method each locked operation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn. Spelled out rather
#: than derived from the operation name, because ``recent`` and ``export`` share one
#: ordered reader: ``_ordered_sync`` is named for what it does, not for the two
#: contract methods that each take the lock around it. Wrapping the shared helper
#: still exercises both sites separately, because the case arms immediately before
#: the site under test calls it.
_SYNC_METHODS = {
    "record": "_record_sync",
    "clear": "_clear_sync",
    "get": "_get_sync",
    "recent": "_ordered_sync",
    "export": "_ordered_sync",
}


class TestSqliteAuditTrailContract(AuditTrailContract):
    """Runs SqliteAuditTrail through the shared AuditTrail conformance suite."""

    @pytest.fixture
    def trail(self, ephemeral: SqliteAuditTrail) -> AuditTrail:
        return ephemeral

    def trail_over(self, resolution: RecipientGrantResolution) -> AuditTrail:
        """An empty in-memory trail resolving route-(b) pointers against ``resolution``.

        The factory ADR-0193 §15 adds to the suite. Not closed by the case: an
        in-memory database dies with its connection and its connection dies with
        the object, so there is nothing to release that outliving the test would
        leak — the same reason ``ephemeral`` above is the only fixture that closes.
        """
        return SqliteAuditTrail(path=":memory:", recipient_grants=resolution)

    async def store_as_history(self, trail: AuditTrail, recorded: PermissionDecision) -> None:
        """Insert ``recorded`` through this store's own write, minus its validation.

        The seeding the suite's second factory asks for (ADR-0247 §12 Arm D"'), and
        deliberately **not** a hand-written ``INSERT``: ``_record_sync`` is the
        statement and the encoding this store actually writes rows with, so the fixture
        is the current bytes rather than a shape no build ever produced — the same
        reason ``_record_as_legacy`` below rewrites a recorded row instead of composing
        one. What is skipped is exactly what an earlier build did not perform:
        ``record``'s standing-shape validation, which runs before the lock and refuses
        this row going forward.
        """
        assert isinstance(trail, SqliteAuditTrail), trail
        trail._record_sync(recorded, None)

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[AuditTrail]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps the private method that operation does its SQL in
        (:data:`_SYNC_METHODS`) — inside ``async with self._lock`` and inside the
        ``to_thread`` the event loop cannot interrupt, which is exactly where
        ADR-0054's bug lived — so the first worker to reach it blocks and every
        later one runs free. Each distinct lock site is a separate place the bug can
        reappear, the locked *reads* included (#370, #397). Blocking there is what
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
            attribute = _SYNC_METHODS[operation]
            original = getattr(trail, attribute)
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(trail, attribute, blocking)
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


@contextlib.contextmanager
def _traced(trail: SqliteAuditTrail) -> Iterator[list[str]]:
    """Collect every statement the trail's connection runs inside the block."""
    statements: list[str] = []
    trail._conn.set_trace_callback(statements.append)
    try:
        yield statements
    finally:
        trail._conn.set_trace_callback(None)


def _assert_one_immediate_transaction(
    statements: list[str], *, what: str, closes: str = "COMMIT"
) -> None:
    """Assert ``what`` ran inside exactly one ``BEGIN IMMEDIATE`` that it closed.

    Three properties, each of which a change to how the transaction is *spelled*
    can break without breaking any behavioural test:

    * the **first** statement is ``BEGIN IMMEDIATE``, so the duplicate-id and
      resolution checks sit inside the write lock rather than in front of it —
      the window #526 is about, which a staged race cannot see, because a race
      can only prove the lock excludes, never *when* it was taken;
    * exactly **one** ``BEGIN``, since a second on the shared connection raises;
    * the **last** statement closes it — ``COMMIT``, or ``ROLLBACK`` where the
      block was left by a refusal — so no arm abandons an open transaction that
      would poison the next caller's ``BEGIN``.

    ``SqliteMemoryStore`` has carried the same assertion since #526
    (``_assert_opens_with_the_write_lock``); this is that pin for this store.
    """
    assert statements, f"{what} ran no SQL at all"
    opened = statements[0].strip()
    assert opened.upper() == "BEGIN IMMEDIATE", (
        f"{what} began with {opened!r}. The write lock has to be the *first* "
        f"statement: a `BEGIN IMMEDIATE` issued any later leaves every read before "
        f"it outside the transaction, which is the exposure #526 names."
    )
    begins = [one for one in statements if one.strip().upper().startswith("BEGIN")]
    assert len(begins) == 1, f"{what} opened {len(begins)} transactions: {begins}"
    assert statements[-1].strip().upper() == closes, (
        f"{what} ended with {statements[-1]!r} rather than {closes}, so it left a "
        f"transaction open on the shared connection"
    )


async def test_recording_opens_and_closes_exactly_one_immediate_transaction(
    ephemeral: SqliteAuditTrail,
) -> None:
    """Both arms of ``record``: the append, and the refusal that leaves it early.

    The refusal is the one that matters structurally — ``DuplicateDecisionError``
    is not a ``sqlite3.Error``, so it leaves the block by an exception the
    transaction still has to be closed on the way out of.
    """
    with _traced(ephemeral) as statements:
        await ephemeral.record(decision("d-1"))
    _assert_one_immediate_transaction(statements, what="record")

    with _traced(ephemeral) as statements, pytest.raises(DuplicateDecisionError):
        await ephemeral.record(decision("d-1"))
    _assert_one_immediate_transaction(statements, what="record (refused)", closes="ROLLBACK")

    assert ephemeral._conn.in_transaction is False
    assert await ephemeral.record(decision("d-2")) == "d-2"  # the trail is not poisoned

    # `clear` is here because it was the one write path outside the discipline
    # (#563): it ran under a bare `with conn:`, which opens the *deferred*
    # transaction the driver would have opened at the DELETE anyway.
    with _traced(ephemeral) as statements:
        assert await ephemeral.clear() == 2
    _assert_one_immediate_transaction(statements, what="clear")


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


_GOAL = "goal-1"


@pytest.mark.parametrize("subject", ["0" * 64, None], ids=["with a digest", "without one"])
async def test_a_standing_egress_row_scoped_to_a_goal_is_refused(
    ephemeral: SqliteAuditTrail, subject: str | None
) -> None:
    """Route (d) is retired, so no standing row may carry a goal scope (ADR-0309 §5).

    The goal authorizations a route-(d) pointer resolved to are gone, so the row is
    refused from its shape alone — the answer a trail holding no authorization store
    always gave such a row — and nothing is written.
    """
    scoped = decision(
        "d-route-d",
        request=egress_request(egress_binding(ALICE)),
        ruled=ruling(
            PermissionOutcome.ALLOW,
            authorised_by="a1",
            authorised_subject=subject,
            authorised_goal=_GOAL,
        ),
    )

    with pytest.raises(InvalidAuthorisationError, match="route \\(d\\) is retired"):
        await ephemeral.record(scoped)

    assert await ephemeral.export() == []


async def test_a_resolving_allow_scoped_to_a_goal_is_refused(ephemeral: SqliteAuditTrail) -> None:
    """Route (a) rests on the user's answer about this call and carries no goal scope."""
    with pytest.raises(InvalidAuthorisationError, match="scopes its authorisation to a goal"):
        await ephemeral.record(
            decision(
                "d-route-a",
                request=egress_request(egress_binding(ALICE)),
                ruled=ruling(PermissionOutcome.ALLOW, authorised_by="d-0", authorised_goal=_GOAL),
                resolves="d-0",
            )
        )

    assert await ephemeral.export() == []


@pytest.mark.parametrize("subject", ["0" * 64, None], ids=["with a digest", "without one"])
async def test_a_goal_scope_on_a_decision_recording_no_egress_call_is_refused(
    ephemeral: SqliteAuditTrail, subject: str | None
) -> None:
    """A row naming no egress call is on no standing route, so its goal scope is refused."""
    with pytest.raises(InvalidAuthorisationError, match="scopes its authorisation to a goal"):
        await ephemeral.record(
            decision(
                "d-no-egress",
                request=action(),
                ruled=ruling(
                    PermissionOutcome.ALLOW,
                    authorised_by="g-1",
                    authorised_subject=subject,
                    authorised_goal=_GOAL,
                ),
            )
        )

    assert await ephemeral.export() == []


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


async def test_a_fresh_trail_records_the_schema_version(ephemeral: SqliteAuditTrail) -> None:
    """A database created here is labelled, so a future migration has a marker to read.

    The marker ``SqlitePlanStore`` writes from day one (ADR-0049 §1), which this
    store had none of. Exactly one row, so the label is unambiguous. Version 5 is
    the record without a step or an execution, in a table without their columns
    (ADR-0318 §6:1), which is what this code writes.
    """
    rows = ephemeral._conn.execute(
        "SELECT key, value FROM meta WHERE key = 'schema_version'"
    ).fetchall()

    assert rows == [("schema_version", "5")]


async def test_a_fresh_trail_keeps_no_step_no_execution_and_no_binding_index(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0318 §6:1: the trail stores and compares no ``step_id`` or ``execution_id``.

    The columns ADR-0044 kept them in left with them, with the ``outcome`` column and
    the two indexes only its per-binding rule read.
    """
    columns = {row[1] for row in ephemeral._conn.execute("PRAGMA table_info(decisions)")}
    indexes = {row[1] for row in ephemeral._conn.execute("PRAGMA index_list(decisions)")}

    assert columns.isdisjoint({"execution_id", "step_id", "outcome"})
    assert indexes.isdisjoint({"decisions_binding_resolution", "decisions_binding"})


def _write_premarker_trail(path: Path) -> None:
    """Seed ``path`` with a ``decisions`` table and no marker, as code before it wrote."""
    legacy = sqlite3.connect(str(path))
    try:
        legacy.execute(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, data TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
            ("c-old", 0, None, '{"id": "c-old"}'),
        )
        legacy.commit()
    finally:
        legacy.close()


@pytest.mark.integration
async def test_a_pre_marker_database_is_refused_rather_than_migrated(tmp_path: Path) -> None:
    """A trail holding decisions and no marker predates it, and nothing reads it.

    No reader is written for a store from before the cutover (ADR-0309 §6:4), so it is
    refused at open — inside the setup transaction, before any create — and the file
    is left exactly as it arrived: no ``meta`` table, no marker, no new table.
    """
    path = tmp_path / "audit.db"
    _write_premarker_trail(path)

    with pytest.raises(AuditError, match="predates the marker"):
        SqliteAuditTrail(path=path)

    assert _stored_schema_version(path) is None
    assert _tables(path) == {"decisions"}


def _tables(path: Path) -> set[str]:
    """Every table name the file at ``path`` holds."""
    raw = sqlite3.connect(str(path))
    try:
        return {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        raw.close()


def _downstamp(path: Path, version: str) -> None:
    """Relabel an existing trail, leaving every table and every row alone."""
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (version,))
        raw.commit()
    finally:
        raw.close()


@pytest.mark.integration
@pytest.mark.parametrize("stored", ["1", "2", "3", "4"])
async def test_an_older_marker_is_refused_rather_than_restamped(
    tmp_path: Path, stored: str
) -> None:
    """Every version before 5 was openable and restamped; none is now (ADR-0309 §6:4).

    A version-4 row carries ``step_id`` and ``execution_id`` and does not decode as the
    record this code writes (ADR-0318 §6:1), and no reader is written for a store from
    before the cutover, so an older marker is refused at open and left as it was.
    """
    path = tmp_path / "audit.db"
    SqliteAuditTrail(path=path).close()
    _downstamp(path, stored)

    with pytest.raises(AuditError, match="can open only version 5"):
        SqliteAuditTrail(path=path)

    assert _stored_schema_version(path) == stored


@pytest.mark.integration
async def test_the_current_marker_is_refused_at_open_by_code_at_the_previous_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0271 §8's P0, from the other side: the downgrade this bump makes reportable.

    The marker moves ahead of the widening so that code *predating* it refuses such
    a trail at **open** rather than at the first row it cannot decode. Only the
    openable set is moved back, because that constant is the whole of what "code at
    the previous version" means to this check — ``_SCHEMA_VERSION`` itself is what
    that code would *write*, and nothing here writes.

    **Refused, and before any read.** The decisions this trail holds are still
    there afterwards and still decode for code that may open the file, and the
    marker is untouched: the refusal runs inside the setup transaction, ahead of
    the create, the migration and every read of a row.
    """
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
        kept = await trail.get("c-1")
    finally:
        trail.close()
    assert _stored_schema_version(path) == "5"

    monkeypatch.setattr(audit, "_OPENABLE_VERSIONS", frozenset({4}))
    with pytest.raises(AuditError, match="can open only version 4"):
        SqliteAuditTrail(path=path)

    monkeypatch.undo()
    assert _stored_schema_version(path) == "5", "a refused open leaves the marker alone"
    reopened = SqliteAuditTrail(path=path)
    try:
        assert await reopened.get("c-1") == kept  # ...and leaves the records alone
    finally:
        reopened.close()


@pytest.mark.integration
async def test_the_current_marker_is_refused_before_a_decisions_table_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same refusal on a bare file, where "before any read" is checkable directly.

    A marked file with no ``decisions`` table yet proves the ordering the populated
    case can only assert the consequences of: the refusal precedes the create, so
    code that cannot account for the label writes nothing to the file at all
    (ADR-0049 §1's ordering).
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '5')")
        raw.commit()
    finally:
        raw.close()

    monkeypatch.setattr(audit, "_OPENABLE_VERSIONS", frozenset({4}))
    with pytest.raises(AuditError, match="schema_version=5"):
        SqliteAuditTrail(path=path)

    assert "decisions" not in _tables(path)
    assert _stored_schema_version(path) == "5"


_STORE_SHAPE = (
    "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
    "resolves TEXT, expires_at_us INTEGER, data TEXT NOT NULL)"
)

#: The current marker, so an open reaches the shape checks rather than refusing an
#: unmarked file that already holds a ``decisions`` table (ADR-0309 §6:4).
_MARKED = (
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "INSERT INTO meta(key, value) VALUES ('schema_version', '5')",
)


def _seed(path: Path, *statements: str) -> None:
    """Run ``statements`` against ``path`` on a connection of somebody else's.

    Used two ways: to write a whole ``decisions`` table this store never made — behind
    the current marker, so what the open goes on to refuse is the table's own shape
    and nothing else — and to attach something to a file a previous open left
    behind.
    """
    raw = sqlite3.connect(str(path))
    try:
        for statement in statements:
            raw.execute(statement)
        raw.commit()
    finally:
        raw.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "create",
    [
        # No primary key at all: `record` refuses a duplicate id by a checked read
        # inside the write transaction, and the key is the net beneath it. Without
        # one, two rows can stand under a single id — which every read that
        # resolves an id then answers from whichever it met first.
        pytest.param(
            "CREATE TABLE decisions(id TEXT, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, "
            "expires_at_us INTEGER, data TEXT NOT NULL)",
            id="no primary key",
        ),
        # A composite key is the same hole wearing a key: `id` still reports as
        # position 1, and one id can still appear twice as long as the second
        # column differs.
        pytest.param(
            "CREATE TABLE decisions(id TEXT, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, "
            "expires_at_us INTEGER, data TEXT NOT NULL, PRIMARY KEY (id, decided_at_us))",
            id="a composite primary key",
        ),
        # A retyped column: nothing rewrites it, and the blob every read decodes
        # would come back as whatever INTEGER affinity made of it.
        pytest.param(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, "
            "expires_at_us INTEGER, data INTEGER NOT NULL)",
            id="a retyped data column",
        ),
        # A column this store keeps nullable, arriving NOT NULL: every ordinary
        # decision writes NULL there, so the whole store is unwritable — refused at
        # open rather than at the first record.
        pytest.param(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT NOT NULL, "
            "expires_at_us INTEGER, data TEXT NOT NULL)",
            id="a resolves column that is NOT NULL",
        ),
        # A collation, which neither the columns nor the index definitions show:
        # `PRAGMA table_info` says plain `TEXT`, and every index over the column
        # inherits the collation instead of restating it, so every definition still
        # matches verbatim — while `WHERE id = ?` has become case-insensitive and
        # `get("A")` answers with the record written as "a".
        pytest.param(
            "CREATE TABLE decisions(id TEXT COLLATE NOCASE PRIMARY KEY, "
            "decided_at_us INTEGER NOT NULL, "
            "resolves TEXT, "
            "expires_at_us INTEGER, data TEXT NOT NULL)",
            id="a case-insensitive id",
        ),
        # The same move against the resolution pointer rather than the id: a
        # resolution naming "A" would resolve the confirmation recorded as "a".
        pytest.param(
            "CREATE TABLE decisions(id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
            "resolves TEXT COLLATE NOCASE, "
            "expires_at_us INTEGER, data TEXT NOT NULL)",
            id="a case-insensitive resolves",
        ),
    ],
)
async def test_a_foreign_decisions_table_is_refused(create: str, tmp_path: Path) -> None:
    """``CREATE TABLE IF NOT EXISTS`` is not a migration, and this is the other table.

    The same exposure the ``invocations`` check closes, on the table it could not be
    used on: the create is a no-op against a table of that name whatever shape it
    has, so a file arriving with a foreign ``decisions`` keeps it. The shape is what
    the store's own invariants stand on — ADR-0036 §2's single resolution and
    ADR-0192 §2's one id space are both decided by a checked read whose net is a
    constraint on this table — so a shape that is not this one is refused rather
    than written into (issue #1575).

    Refused with nothing left behind: the check shares the setup transaction with
    the creates, so the file is exactly what it was.
    """
    path = tmp_path / "audit.db"
    _seed(path, *_MARKED, create)

    with pytest.raises(AuditError, match="decisions table"):
        SqliteAuditTrail(path=path)

    assert _tables(path) == {"decisions", "meta"}, "a refused open leaves the file as it arrived"


@pytest.mark.integration
async def test_a_decisions_index_that_is_not_the_defined_one_is_refused(tmp_path: Path) -> None:
    """The columns are only half the shape; the uniqueness is the other half.

    ``CREATE UNIQUE INDEX IF NOT EXISTS`` is a no-op against an index of that name
    however it was declared, so a file arriving with a *non-unique*
    ``decisions_resolves`` keeps it — and ADR-0036 §2's one-resolution-per-
    confirmation rule loses the net beneath its checked read, which is exactly what
    a second process racing the check would then walk through.

    Held by comparing the stored definition rather than by introspection, because a
    partial index's ``WHERE`` is reported by no ``PRAGMA``.
    """
    path = tmp_path / "audit.db"
    _seed(path, *_MARKED, _STORE_SHAPE, "CREATE INDEX decisions_resolves ON decisions(resolves)")

    with pytest.raises(AuditError, match="'decisions_resolves'"):
        SqliteAuditTrail(path=path)

    assert _tables(path) == {"decisions", "meta"}


@pytest.mark.integration
@pytest.mark.parametrize("table", ["meta", "decisions", "invocations"])
async def test_a_trigger_this_store_did_not_define_is_refused(table: str, tmp_path: Path) -> None:
    """Holding the objects a store *names* leaves the objects nothing names open.

    A trigger is attached to a table rather than replacing anything on it, so it is
    invisible to every check that compares a definition — and it is the one object
    that decides what a write actually does. ``BEFORE INSERT ... RAISE(IGNORE)``
    discards every row silently, and SQLite reports the ignored insert as a success:
    without this refusal, ``record`` returns the identifier of a decision that
    ``get`` then cannot find, which is a trail claiming a durable write that never
    happened (ADR-0004 §7). On ``meta`` the same move eats the restamp, leaving a
    version-1 marker over a version-2 shape — the downgrade ADR-0049 §1's marker
    exists to make reportable.
    """
    path = tmp_path / "audit.db"
    SqliteAuditTrail(path=path).close()
    _seed(path, f"CREATE TRIGGER discard BEFORE INSERT ON {table} BEGIN SELECT RAISE(IGNORE); END")

    with pytest.raises(AuditError, match="trigger 'discard'"):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
async def test_a_foreign_trigger_on_a_differently_cased_table_is_refused(tmp_path: Path) -> None:
    """SQLite folds an identifier's case; ``sqlite_master`` keeps the spelling.

    A file whose table is declared ``Decisions`` is the very table every statement
    here reads — ``CREATE TABLE IF NOT EXISTS decisions`` is a no-op against it, and
    ``PRAGMA table_info(decisions)`` describes it — so the columns, the indexes and
    the collations all check out. But ``sqlite_master.tbl_name`` records
    ``"Decisions"``, so a trigger attached to it is looked up under a name this
    store does not define unless the lookup folds too, and the silent discard is
    back.
    """
    path = tmp_path / "audit.db"
    _seed(
        path,
        *_MARKED,
        _STORE_SHAPE.replace("CREATE TABLE decisions", "CREATE TABLE Decisions"),
        "CREATE TRIGGER discard BEFORE INSERT ON Decisions BEGIN SELECT RAISE(IGNORE); END",
    )

    with pytest.raises(AuditError, match="trigger 'discard'"):
        SqliteAuditTrail(path=path)


@pytest.mark.integration
async def test_a_decisions_table_carrying_an_extra_column_still_opens(tmp_path: Path) -> None:
    """Tolerant of what a later version of this store would add, and only of that.

    A later version may add a column by ``ALTER TABLE ... ADD COLUMN``, so a check
    that refused an unknown column would refuse this store's own next shape read by
    this store's own previous code. What it must not tolerate is a *key* it does not know about,
    which is why the primary key is checked whole rather than only at ``id``.
    """
    path = tmp_path / "audit.db"
    _seed(path, *_MARKED, _STORE_SHAPE, "ALTER TABLE decisions ADD COLUMN whatever_comes_next TEXT")

    trail = SqliteAuditTrail(path=path)
    try:
        assert await trail.record(decision("d-1")) == "d-1"
        assert await trail.get("d-1") is not None
    finally:
        trail.close()


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

    assert rows == [("schema_version", "5")]


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

    with pytest.raises(AuditError, match="can open only version"):
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
    this code cannot account for is a fault to report, not records to hand on. The
    marker is moved past the current version rather than to it: ``'5'`` would name
    the shape this code writes, and the refusal under test is for the one it does
    not know.
    """
    path = tmp_path / "audit.db"
    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
    finally:
        trail.close()

    raw = sqlite3.connect(str(path))
    try:
        raw.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(AuditError, match="can open only version"):
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
    """A marker stored as INTEGER 5 rather than '5' still names version 5.

    The type guard refuses what cannot be read as a version; it must not refuse a
    version legibly stored in the other of SQLite's two integral forms, which is
    what an untyped ``meta`` column yields for an unquoted literal.
    """
    path = tmp_path / "audit.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value)")
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', 5)")
        raw.commit()
    finally:
        raw.close()

    trail = SqliteAuditTrail(path=path)
    try:
        await trail.record(decision("c-1"))
        assert len(await trail.export()) == 1
    finally:
        trail.close()

    assert _stored_schema_version(path) == "5"


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
        raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '5')")
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

    assert _stored_schema_version(path) == "5"
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
    file. Setup's ``BEGIN IMMEDIATE`` is exactly such a write.

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

    def observing(trail: SqliteAuditTrail, conn: sqlite3.Connection) -> int | None:
        stored = original(trail, conn)
        observed.append(_journal_mode(path))
        return stored

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


async def test_a_path_the_driver_refuses_outright_is_still_an_audit_error() -> None:
    """A path with an embedded NUL leaves ``sqlite3.connect`` as a ``ValueError``.

    Neither a ``sqlite3.Error`` nor an ``OSError``, so a constructor catching only
    those lets a bare builtin escape the ``AuditError`` boundary this constructor
    documents — a caller with one handler for "the trail would not open" meets a
    second exception type it was never told about (#238). No filesystem is
    touched: the driver refuses the argument before it opens anything.
    """
    with pytest.raises(AuditError, match="failed to open"):
        SqliteAuditTrail(path="audit\x00.db")


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

    def blocking_record(
        snapshot: PermissionDecision, refusal: InvalidAuthorisationError | None
    ) -> None:
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_record(snapshot, refusal)

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


async def test_a_base_exception_from_the_worker_reaches_the_caller() -> None:
    """ADR-0054's relay carries every failure, not only the ``Exception`` half (#680).

    ``_run_to_completion`` answers out of its relay lists alone whenever the worker
    finished before the wait loop's first check. A failure the relay never captured
    leaves both lists empty, so the caller is answered from an empty ``outcome`` —
    an ``IndexError`` standing in for the cause and not chained to it.

    The lever forces that path every time. Without it, which of the two paths a
    caller gets is a race, and a case that only sometimes reaches the defect is not
    evidence about it. ``KeyboardInterrupt`` stands in for the class; ``SystemExit``
    and a ``CancelledError`` raised by the work itself are the other members.

    Its own copy of the helper, deliberately: ADR-0060 refuses this shape a shared
    home, so each copy is a separate place the relay could be narrow (#680).
    """

    def aborts() -> None:
        raise KeyboardInterrupt

    with worker_finished_before_the_first_check(), pytest.raises(KeyboardInterrupt):
        await _run_to_completion(aborts)


async def test_repeated_cancellation_does_not_consume_the_executor() -> None:
    """Absorbing a cancellation costs one executor job, however many arrive (#697).

    Each absorbed cancellation hands the loop something to wait on. A copy that
    submits a fresh blocking ``done.wait`` per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it — so repeated cancellation of *one* blocked call
    occupies the whole default pool and starves unrelated thread work, which turns
    a single stalled store operation into a process that can run none.

    Pinned in this module rather than once for the family, because ADR-0060
    refuses this helper a shared home: each copy is a separate place the reuse can
    be lost, and a single pin on one copy is exactly how six later copies came to
    be written with the defect rather than without it (#697).

    The pool is deliberately small and the probe is the assertion: counting
    threads would measure the executor's growth policy, while the probe measures
    the property — that something else can still run. The cancellation is still
    re-raised at the end, because a "fix" that stopped absorbing it would bound
    the pool by abandoning ADR-0054's invariant instead.

    The bounded executor is installed as this loop's default because the helper
    submits to ``None``; pytest-asyncio gives each test its own loop, so the
    substitution dies with the test and only the pool needs shutting down.
    """
    workers = 4
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=workers)
    loop.set_default_executor(executor)
    release = threading.Event()
    entered = threading.Event()

    def blocked() -> str:
        entered.set()
        if not release.wait(timeout=5):  # pragma: no cover - only on a hang
            msg = "the blocked worker was never released"
            raise AssertionError(msg)
        return "done"

    call = asyncio.ensure_future(_run_to_completion(blocked))
    try:
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        for _ in range(workers * 3):
            call.cancel()
            await _spin()

        probe = loop.run_in_executor(executor, lambda: "probe")
        finished, _ = await asyncio.wait([probe], timeout=1)
        assert finished, "the absorbed cancellations consumed the whole executor"

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
    finally:
        # Released and settled *before* the pool is shut down, so a failing run
        # reports the assertion above rather than a "cannot schedule new futures
        # after shutdown" from the helper still submitting into a closing pool.
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        executor.shutdown(wait=True)


# --- A row recorded before ADR-0181's origin field ----------------------------
# ADR-0184 §5 and §10 put these here rather than in the shared conformance suite,
# for ADR-0049 §5's reason: the behaviour is a property of a store that persists a
# **serialised payload** and rebuilds it, and the canonical fake holds objects
# rather than bytes, so no shared case could seed the row. ``record``'s refusal of
# the same shape is a different matter and *is* in the suite, because a test can
# construct such a decision directly.
#
# Kept in one block so a rebase across another lane's edits moves it whole.


def _egress_decision(decision_id: str = "d-egress", **overrides: object) -> PermissionDecision:
    """A parked egress ``CONFIRM``, of the shape a real `send_email` park has."""
    binding = EgressBinding(
        spans=(
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("a@example.com"),
                tier=DataTier.PERSONAL,
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="a@example.com",
                    canonical="a@example.com",
                ),
            ),
        ),
        account=BoundAccount(identity="work@example.com", reference="conn-0001"),
        transport_endpoint="smtp://mail.example.com:587",
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )
    fields: dict[str, object] = {
        "parameters": {"to": "a@example.com"},
        "egress_binding": binding,
    }
    fields.update(overrides)
    return decision(
        decision_id,
        request=action(**fields),
        ruled=ruling(PermissionOutcome.CONFIRM),
    )


def _stored(trail: SqliteAuditTrail, decision_id: str) -> dict[str, Any]:
    """The row's ``data`` column, decoded as JSON — the bytes, not a model."""
    row = trail._conn.execute("SELECT data FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    assert row is not None, f"no row for {decision_id!r}"
    decoded: dict[str, Any] = json.loads(str(row[0]))
    return decoded


def _rewrite(trail: SqliteAuditTrail, decision_id: str, payload: dict[str, Any]) -> None:
    """Put ``payload`` back into the row's ``data`` column and commit.

    Committed, so the implicit transaction this ``UPDATE`` opened is not still open
    when a later ``record`` starts one of its own.
    """
    trail._conn.execute(
        "UPDATE decisions SET data = ? WHERE id = ?", (json.dumps(payload), decision_id)
    )
    trail._conn.commit()


async def _record_as_legacy(trail: SqliteAuditTrail, recorded: PermissionDecision) -> None:
    """Record ``recorded``, then rewrite its row as a pre-ADR-0181 build wrote it.

    Rewritten rather than hand-built, so the fixture is the **current** encoding
    minus exactly the keys that epoch had not begun writing. A hand-written row could
    drift from what the trail actually stores and would then be testing a shape no
    build ever produced.

    **Two keys rather than one since ADR-0233 §14**, and that is the epochs being
    ordered rather than a widening: a build predating ``planned_with_external_content``
    necessarily predates ``coverage`` too, so a genuine pre-origin row lacks both.
    A row lacking only ``planned_with_external_content`` is the shape ADR-0184 §10
    asked for and ADR-0233 §14 makes **unsatisfiable** — it is nobody's epoch, and
    ``test_a_stored_row_missing_only_the_origin_now_raises`` is where that is pinned.

    Seeded through the ``data`` column directly because ADR-0184 §4 makes the row
    unproducible through ``record``, which now refuses the shape outright — the
    write half of the same decision these cases pin the read half of.
    """
    await trail.record(recorded)
    legacy = _stored(trail, recorded.id)
    del legacy["egress_binding"]["planned_with_external_content"]
    del legacy["egress_binding"]["coverage"]
    # A row of either older epoch carries no ``closed_loop`` either: ADR-0238 §13
    # added that member after both, and every older shape forbids an extra key. The
    # ladder is in time order, so a rung is the current encoding minus every member
    # added after it (ADR-0184 §2) — so ``forecast_reach`` goes with it, ADR-0260 §11
    # having added the next such member on the leaf.
    del legacy["egress_binding"]["closed_loop"]
    del legacy["egress_binding"]["forecast_reach"]
    _rewrite(trail, recorded.id, legacy)


async def _record_as_coverage_legacy(trail: SqliteAuditTrail, recorded: PermissionDecision) -> None:
    """Record ``recorded``, then rewrite its row as a pre-ADR-0233 build wrote it.

    :func:`_record_as_legacy` one epoch on, and the middle rung of ADR-0233 §14's
    ladder: the current encoding minus ``coverage`` alone, which is exactly what a
    build between ADR-0181 §3 and ADR-0233 §4 wrote.
    """
    await trail.record(recorded)
    legacy = _stored(trail, recorded.id)
    del legacy["egress_binding"]["coverage"]
    # A row of either older epoch carries no ``closed_loop`` either: ADR-0238 §13
    # added that member after both, and every older shape forbids an extra key. The
    # ladder is in time order, so a rung is the current encoding minus every member
    # added after it (ADR-0184 §2) — so ``forecast_reach`` goes with it, ADR-0260 §11
    # having added the next such member on the leaf.
    del legacy["egress_binding"]["closed_loop"]
    del legacy["egress_binding"]["forecast_reach"]
    _rewrite(trail, recorded.id, legacy)


# --- §3, §10: the discrimination, over a real store ---------------------------


async def test_a_stored_row_carrying_the_origin_decodes_as_a_whole_binding(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§3's first row, over bytes rather than a dict.

    The baseline the other two are read against: a row this build wrote decodes with
    its binding whole and its origin intact, so nothing below is evidence that the
    trail simply stopped reading the field.
    """
    recorded = _egress_decision()
    await ephemeral.record(recorded)

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert isinstance(got.egress_binding, EgressBinding)
    assert got.egress_binding.planned_with_external_content is False
    assert got.egress_binding == recorded.egress_binding


async def test_a_stored_row_missing_both_added_keys_decodes_as_the_origin_sibling(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§3's second row as ADR-0233 §15 restates it: **both** keys removed.

    The same JSON with the two keys a pre-ADR-0181 build never wrote removed decodes
    carrying an ``OriginUnrecordedBinding`` — not a projection, not a marker: every
    other fact the row holds comes back, which is the second test ADR-0184's Context
    sets. The user reading their trail sees the connected account, the occurrence in
    both its supplied and canonical forms and the payload description, and learns
    exactly one thing more, that the origin of this call was never recorded.

    **The key set moved because the epochs are ordered, not because the tolerance
    widened**: ADR-0184 §1's roster is that clause's with the second name added and
    its narrowness untouched (ADR-0233 §14).
    """
    recorded = _egress_decision()
    await _record_as_legacy(ephemeral, recorded)

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert isinstance(got.egress_binding, OriginUnrecordedBinding)
    assert got.egress_binding.account == BoundAccount(
        identity="work@example.com", reference="conn-0001"
    )
    assert got.egress_binding.transport_endpoint == "smtp://mail.example.com:587"
    assert got.egress_binding.spans == recorded.egress_binding.spans  # type: ignore[union-attr]  # built whole above
    assert got.egress_binding.canonical_destination_set == (
        CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="a@example.com"),
    )


async def test_a_stored_row_missing_only_the_origin_now_raises(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0233 §15's fourth replacement case, and the sharpest of the five.

    The shape ADR-0184 §10 asked for — the current JSON with **only**
    ``planned_with_external_content`` removed — is exactly what ADR-0233 §14 makes
    **unsatisfiable**. Such a row still carries ``coverage``, which
    ``OriginUnrecordedBinding`` does not declare, so ``extra="forbid"`` refuses it
    there; and it lacks ``planned_with_external_content``, which both other rungs
    require. No epoch ever wrote it, no member of the union declares a row of that
    shape, and it raises.

    This is the case that fails an implementation which widened the tolerance rather
    than shaping it — ADR-0184 §10's own reason for the case it stated, arriving at
    the combination a matrix would admit and a ladder does not.
    """
    recorded = _egress_decision()
    await ephemeral.record(recorded)
    neither_epoch = _stored(ephemeral, "d-egress")
    del neither_epoch["egress_binding"]["planned_with_external_content"]
    _rewrite(ephemeral, "d-egress", neither_epoch)

    with pytest.raises(AuditError, match="no longer validates"):
        await ephemeral.get("d-egress")


async def test_a_stored_row_missing_only_the_coverage_decodes_as_the_middle_rung(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0233 §15's second replacement case: the epoch this ADR mints a shape for.

    The current JSON with **exactly** ``coverage`` removed decodes carrying a
    ``CoverageUnrecordedBinding``, and every other fact the row holds comes back —
    including ``planned_with_external_content``, which such a row *did* record. That
    is the whole reason the origin guard does not catch this epoch, and therefore the
    reason ADR-0233 §14 states each refusal for it rather than inheriting one.
    """
    recorded = _egress_decision()
    await _record_as_coverage_legacy(ephemeral, recorded)

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert isinstance(got.egress_binding, CoverageUnrecordedBinding)
    assert not isinstance(got.egress_binding, EgressBinding)
    assert got.egress_binding.planned_with_external_content is False
    assert got.egress_binding.account == BoundAccount(
        identity="work@example.com", reference="conn-0001"
    )
    assert got.egress_binding.transport_endpoint == "smtp://mail.example.com:587"
    assert got.egress_binding.spans == recorded.egress_binding.spans  # type: ignore[union-attr]  # built whole above
    assert got.egress_binding.canonical_destination_set == (
        CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="a@example.com"),
    )


async def test_a_returned_coverage_legacy_decision_fabricates_no_coverage_on_the_way_out(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0233 §14's nothing-is-fabricated clause, over the dump.

    ``coverage`` is required with no default and ADR-0233 §5 forbids a seam inventing
    one, so every member of ``SpanCoverage`` is out; the model does not carry the
    member at all, so there is no key to emit. Asserted over the **whole** dump, so a
    lane that moved the fact elsewhere in the record is caught too.
    """
    await _record_as_coverage_legacy(ephemeral, _egress_decision())

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert "coverage" not in json.dumps(got.model_dump(mode="json"))
    assert "coverage" not in got.model_dump()["egress_binding"]


async def test_the_trail_reads_the_coverage_legacy_shape_and_refuses_to_write_one(
    ephemeral: SqliteAuditTrail,
) -> None:
    """ADR-0233 §14's write clause on the concrete store, beside the read it mirrors.

    ADR-0184 §4's second clause extended by cause: the same value the trail hands
    *out* of a row it cannot be handed *into* one, so the shape cannot be minted into
    a trail and back-dated as history it is not.
    """
    await _record_as_coverage_legacy(ephemeral, _egress_decision())
    read_back = await ephemeral.get("d-egress")
    assert read_back is not None
    assert isinstance(read_back.egress_binding, CoverageUnrecordedBinding)

    with pytest.raises(AuditError, match="records no coverage"):
        await ephemeral.record(read_back.model_copy(update={"id": "d-forged"}))

    assert await ephemeral.get("d-forged") is None


async def test_a_stored_row_missing_the_origin_and_faulty_elsewhere_still_raises(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§3's third row, §10's fifth clause: the case a widened tolerance fails.

    ADR-0184 admits a row whose **only** difference from a current one is the absent
    origin. A row that is also faulty elsewhere satisfies neither arm of the union
    and is a corrupted or downgraded database exactly as before — otherwise the
    representation would quietly become a general tolerance for rows the model
    rejects, which is the opposite of what an audit trail is for.

    The narrowness used to be a hand-written predicate over a ``ValidationError``'s
    shape; it is now a property of the types, so a lane cannot widen it by loosening
    a check.
    """
    await _record_as_legacy(ephemeral, _egress_decision())
    also_broken = _stored(ephemeral, "d-egress")
    del also_broken["egress_binding"]["account"]
    _rewrite(ephemeral, "d-egress", also_broken)

    with pytest.raises(AuditError, match="no longer validates"):
        await ephemeral.get("d-egress")


async def test_a_stored_row_carrying_an_undeclared_member_still_raises(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§3's fourth row: a row from a schema neither model knows is not a legacy row.

    ``extra="forbid"`` on the shared base is what makes this hold for **both** arms
    of the union at once. Without it the row would decode as whichever arm ignored
    the key, and a downgraded database would be served as history.
    """
    await _record_as_legacy(ephemeral, _egress_decision())
    from_the_future = _stored(ephemeral, "d-egress")
    from_the_future["egress_binding"]["schema_epoch"] = 2
    _rewrite(ephemeral, "d-egress", from_the_future)

    with pytest.raises(AuditError, match="no longer validates"):
        await ephemeral.get("d-egress")


# --- §5, §10: what the four history readers answer ----------------------------


async def test_one_legacy_row_no_longer_denies_the_user_every_other_row(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§5's first clause, §10's sixth: the all-or-nothing failure this closes.

    ``recent`` and ``export`` select every matching row and map the decode over the
    whole list, so before ADR-0184 **one** unreadable row denied the user every
    other row in the trail — and ADR-0021 §4 says ``export`` is what discharges
    ADR-0004 §6's portability obligation for this store, so two such rows defeated
    that obligation wholesale.

    The subject is deliberately **one legacy row among several ordinary ones**, as
    §10 requires: a case over a trail whose only row is the legacy one would pass an
    implementation that still failed the whole list, and would not satisfy the
    clause.
    """
    await ephemeral.record(_egress_decision("d-before"))
    await _record_as_legacy(ephemeral, _egress_decision())
    await ephemeral.record(
        decision("d-after", request=action(parameters={"to": "after@example.com"}))
    )

    exported = await ephemeral.export()
    recent = await ephemeral.recent(limit=50)

    assert {held.id for held in exported} == {"d-before", "d-egress", "d-after"}
    assert [held.id for held in recent] == [held.id for held in exported]
    legacy = next(held for held in exported if held.id == "d-egress")
    assert isinstance(legacy.egress_binding, OriginUnrecordedBinding)


async def test_get_returns_the_legacy_row_by_id(ephemeral: SqliteAuditTrail) -> None:
    """§5's first clause for the one reader with a production consumer today.

    ``StepRunner._recorded`` reads through ``get``, so this is the read that decides
    whether a named legacy decision is legible at all. It answers as history; the
    runner then narrows the union and refuses to *resume* it (ADR-0184 §8's fourth
    clause), which is a different question from whether it can be read.
    """
    await _record_as_legacy(ephemeral, _egress_decision())

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert got.id == "d-egress"
    assert isinstance(got.egress_binding, OriginUnrecordedBinding)


async def test_a_returned_legacy_decision_fabricates_no_origin_on_the_way_out(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§10's seventh clause: an export is a faithful copy of what the row says.

    The whole design turns on fabricating nothing, and a dump is where a fabrication
    would surface: a defaulted ``False`` would state that no external material was
    selected, on behalf of a lane that made no selection, and a ``True`` would be
    worse. The model does not carry the member at all, so there is no key to emit —
    asserted over the **whole** dump rather than under ``egress_binding`` alone, so a
    lane that moved the fact somewhere else in the record is caught too.
    """
    await _record_as_legacy(ephemeral, _egress_decision())

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert "planned_with_external_content" not in json.dumps(got.model_dump(mode="json"))
    assert "planned_with_external_content" not in got.model_dump()["egress_binding"]


async def test_a_row_carrying_the_origin_round_trips_unchanged(
    ephemeral: SqliteAuditTrail,
) -> None:
    """Nothing changes for a row written by this build.

    The tolerance is reached only by the one legacy shape, so a current row decodes
    with its binding whole.
    """
    recorded = _egress_decision()
    await ephemeral.record(recorded)

    got = await ephemeral.get("d-egress")

    assert got is not None
    assert got.egress_binding == recorded.egress_binding
    assert isinstance(got.egress_binding, EgressBinding)
    assert got.egress_binding.planned_with_external_content is False


async def test_the_trail_reads_the_shape_and_refuses_to_write_one(
    ephemeral: SqliteAuditTrail,
) -> None:
    """§4's second clause on the concrete store, beside the read it is the mirror of.

    The shared suite holds every implementation to the refusal; this pins the pair on
    the one store that can hold such a row at all, so the asymmetry is legible in one
    place: the same value the trail hands *out* of a row it cannot be handed *into*
    one. An epoch that has ended is readable and unappendable.
    """
    await _record_as_legacy(ephemeral, _egress_decision())
    read_back = await ephemeral.get("d-egress")
    assert read_back is not None
    assert isinstance(read_back.egress_binding, OriginUnrecordedBinding)

    with pytest.raises(AuditError, match="records no origin"):
        await ephemeral.record(read_back.model_copy(update={"id": "d-forged"}))

    assert await ephemeral.get("d-forged") is None
