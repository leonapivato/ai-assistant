"""The durable ledger passes both invocation conformance suites (ADR-0192 §2).

``SqliteAuditTrail`` is ADR-0137 §2's *primary production implementation* — the
consumer whose demands shape the contract — so the suites run against it as well
as against the canonical fake, and it is the subject that carries the cases the
fake can only skip: a store that outlives the object holding it, which is what the
restart and two-instance arms are about.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from invocation_ledger_contract import (
    InvocationCompleterContract,
    InvocationLedgerContract,
    LedgerSubject,
)
from permission_builders import action, decision, ruling, tool

from ai_assistant.core.errors import AuditError, AuthorisationSpentError
from ai_assistant.core.types import (
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.testing.cancellation import ResourceLog, ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ai_assistant.testing.cancellation import SuspendedCall

#: Which private method each contract operation does its SQL in. Arming *that* is
#: what parks the worker inside the connection's turn — under ``async with
#: self._lock`` and inside the ``to_thread`` the event loop cannot interrupt — so a
#: second caller genuinely queues rather than racing on an event-loop tick.
_SYNC_METHODS = {
    "claim_invocation": "_claim_sync",
    "complete_invocation": "_complete_sync",
    "open_invocations": "_open_invocations_sync",
    "recent_invocations": "_joined_sync",
    "export_invocations": "_joined_sync",
    "clear": "_clear_sync",
}


class SqliteLedgerHarness:
    """Builds ``SqliteAuditTrail`` subjects on files under one ``tmp_path``.

    On **files** rather than ``":memory:"``: ``store_of`` has to name something a
    second object can open, and that is the whole point of the two arms the fake
    skips. Every trail opened is closed when the case ends.
    """

    def __init__(self, root: Path) -> None:
        """Open trails under ``root``, numbering each fresh store."""
        self._root = root
        self._opened: list[SqliteAuditTrail] = []
        self._stores: dict[int, Path] = {}
        self._suspensions: list[ThreadSuspension] = []
        self._logs: dict[int, ResourceLog] = {}

    def open(
        self,
        *,
        now: Callable[[], Any] | None = None,
        identifiers: Any = None,
        store: object | None = None,
    ) -> LedgerSubject:
        """Return a trail over ``store``, or over a fresh file."""
        fresh = self._root / f"t{len(self._stores)}.db"
        path = store if isinstance(store, Path) else fresh
        trail = (
            SqliteAuditTrail(path=path, identifiers=identifiers)
            if now is None
            else SqliteAuditTrail(path=path, now=now, identifiers=identifiers)
        )
        self._opened.append(trail)
        self._stores[id(trail)] = path
        subject: LedgerSubject = trail
        return subject

    def store_of(self, subject: LedgerSubject) -> object | None:
        """The file this trail was opened on, which a second object can open too."""
        return self._stores.get(id(subject))

    def log_of(self, subject: LedgerSubject) -> ResourceLog:
        """When each armed call was inside this trail's connection.

        The cancellation cases cannot settle "was the second caller blocked?" with
        a timeout — a busy executor makes a caller that got *in* look like one that
        queued — so they read the spans directly. One log per subject, created on
        first ask so ``arm`` and the case agree about which one they are using.
        """
        return self._logs.setdefault(id(subject), ResourceLog())

    def arm(self, subject: LedgerSubject, operation: str) -> SuspendedCall:
        """Park ``operation``'s worker inside the connection's turn.

        The first worker to arrive blocks and every later one runs free, so the
        case suspends the call under test rather than a setup write. The whole
        wrapped call is recorded in :meth:`log_of`'s log — the span the connection
        is genuinely in use for, which is what ADR-0060 §3's overlap check reads.
        """
        trail = subject
        assert isinstance(trail, SqliteAuditTrail)
        attribute = _SYNC_METHODS[operation]
        original = getattr(trail, attribute)
        suspension = ThreadSuspension()
        armed = threading.Event()
        log = self.log_of(subject)

        def blocking(*args: object) -> object:
            with log.inside():
                if not armed.is_set():
                    armed.set()
                    suspension.hold()
                return original(*args)

        setattr(trail, attribute, blocking)
        self._suspensions.append(suspension)
        return suspension

    def dispose(self) -> None:
        """Release anything still parked, then close every trail opened."""
        for suspension in self._suspensions:
            suspension.release()
        for trail in self._opened:
            trail.close()


@pytest.fixture
def sqlite_harness(tmp_path: Path) -> Iterator[SqliteLedgerHarness]:
    """A harness whose trails live under ``tmp_path`` and are closed after the case."""
    harness = SqliteLedgerHarness(tmp_path)
    harness._suspensions = []
    try:
        yield harness
    finally:
        harness.dispose()


class TestSqliteInvocationCompleterContract(InvocationCompleterContract):
    """Runs the durable ledger through the narrow face's shared suite."""

    @pytest.fixture
    def harness(self, sqlite_harness: SqliteLedgerHarness) -> SqliteLedgerHarness:
        return sqlite_harness


class TestSqliteInvocationLedgerContract(InvocationLedgerContract):
    """Runs the durable ledger through the wide face's shared suite."""

    @pytest.fixture
    def harness(self, sqlite_harness: SqliteLedgerHarness) -> SqliteLedgerHarness:
        return sqlite_harness


# --- the columns are a filter, never the record ------------------------------
# ADR-0192 §2's reads narrow by `decision_id`, `completes` and `outcome` and order
# by `recorded_at_us` and `seq`, and every one of them *acts*: the consume is
# decided over the claims a filter returns, a completion is admitted against a row
# it found open, and a listing attributes an act to the authorisation the join
# paired it with.
#
# The four that decide anything are `GENERATED ALWAYS ... VIRTUAL` over the blob, so
# the disagreement is unreachable rather than merely reported — including in the
# direction validation cannot cover, where a tampered column *hides* a row from the
# index that filters by it. The two that must stay stored are checked against the
# record wherever a read returns the row. Only reachable from this binding: reaching
# a column at all needs the store's own SQL.


def _allow(decision_id: str, tool_id: str = "smtp", *, keyed: bool = False) -> PermissionDecision:
    """An ALLOW a claim can be admitted under, over a named tool.

    ``keyed`` opens ADR-0029 §5's retry arm, which is the only arm an instant
    decides and so the only one a reordered append order could move.
    """
    definition = (
        tool(
            tool_id,
            side_effecting=True,
            idempotency=Idempotency.KEYED,
            idempotency_window=timedelta(seconds=10),
        )
        if keyed
        else tool(tool_id, side_effecting=True, idempotency=Idempotency.NONE)
    )
    return decision(
        decision_id, request=action(tool=definition), ruled=ruling(PermissionOutcome.ALLOW)
    )


@pytest.fixture
def trail(tmp_path: Path) -> Iterator[SqliteAuditTrail]:
    """A trail on a real file, closed when the case ends."""
    opened = SqliteAuditTrail(path=tmp_path / "audit.db")
    try:
        yield opened
    finally:
        opened.close()


async def _claimed(trail: SqliteAuditTrail, authorisation: PermissionDecision) -> ToolInvocation:
    """Record ``authorisation`` and claim one invocation under it."""
    await trail.record(authorisation)
    return await trail.claim_invocation(decision=authorisation)


async def _fail(trail: SqliteAuditTrail, claim: ToolInvocation) -> ToolInvocation:
    """Complete ``claim`` retryably, which is the state §1's retry arm reads."""
    return await trail.complete_invocation(
        claim_id=claim.id,
        outcome=ToolOutcome.FAILED,
        incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
        failure_kind=ToolFailureKind.UNAVAILABLE,
    )


class _StepClock:
    """A clock the case moves by hand, so the window's boundary is exact."""

    def __init__(self) -> None:
        """Start at the epoch-anchored instant every case below measures from."""
        self.at = 0

    def __call__(self) -> datetime:
        """Return the instant the case has wound to."""
        return _ORIGIN + timedelta(seconds=self.at)


#: A fixed instant, so the window boundary is about the values and not the runtime.
_ORIGIN = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("id", "i-elsewhere", id="id"),
        pytest.param("decision_id", "d-other", id="decision_id"),
        pytest.param("completes", "i-something", id="completes"),
        pytest.param("outcome", "SUCCEEDED", id="outcome"),
    ],
)
async def test_a_column_the_record_derives_cannot_be_altered_at_all(
    trail: SqliteAuditTrail, column: str, value: str
) -> None:
    """The four columns that decide an admission are the blob, not a copy of it.

    This is the direction a validating read cannot cover. Holding a decoded row to
    the columns it was **found by** catches a row served under the wrong decision;
    it cannot catch a row a tampered column *hides*, because a read narrowed by
    that column never sees what the narrowing removed — and hiding an open claim
    from the claims-under read is exactly how a spent authorisation would admit a
    second act (ADR-0192 §1).

    Deriving the column closes it by construction: there is only one value, so
    there is nothing to disagree, and SQLite refuses the write outright. The
    consume is asserted after the refusal, because "the write failed" is only
    interesting if the rule it protects still holds.
    """
    authorisation = _allow("d-1")
    await _claimed(trail, authorisation)
    await trail.record(_allow("d-other"))

    with pytest.raises(sqlite3.OperationalError, match="generated column"):
        trail._conn.execute(f"UPDATE invocations SET {column} = ?", (value,))  # noqa: S608 — literal
    trail._conn.rollback()

    with pytest.raises(AuthorisationSpentError):
        await trail.claim_invocation(decision=authorisation)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("seq", 99, id="the-append-order"),
        pytest.param("recorded_at_us", 1, id="the-listing-order"),
        pytest.param("data", '{"id": "x"}', id="the-record-itself"),
    ],
)
async def test_a_column_the_record_cannot_derive_is_refused_by_the_table(
    trail: SqliteAuditTrail, column: str, value: object
) -> None:
    """The two stored columns are closed by the table being append-only, not by a check.

    ``seq`` is absent from :class:`ToolInvocation` and ``recorded_at_us`` is
    `_sort_key`'s integer microseconds, which ``json_extract`` cannot produce from
    the ISO-8601 text the blob holds — so neither can be derived, and for both the
    hazard is the one no comparison reaches. Swapping two claims' ``seq`` moves the
    claim ADR-0192 §1's retry window is measured from. Altering ``recorded_at_us``
    pushes a row past a bounded listing's ``LIMIT``, where it is never decoded and
    never compared, and the caller is handed a wrong page with every row on it
    valid — and validating rows the bound *excludes* would mean reading the whole
    table to serve a page.

    ADR-0021 §4 already says nothing recorded is rewritten and this store issues no
    ``UPDATE`` against the table, so saying that to SQLite costs nothing and closes
    both. ``data`` is here too: it is what a tamperer would move once the derived
    columns stopped being movable.
    """
    await _claimed(trail, _allow("d-1"))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        trail._conn.execute(f"UPDATE invocations SET {column} = ?", (value,))  # noqa: S608 — literal
    trail._conn.rollback()

    assert len(await trail.export_invocations()) == 1


@pytest.mark.integration
async def test_the_retry_window_cannot_be_moved_by_reordering_the_ordinals(
    trail: SqliteAuditTrail,
) -> None:
    """The concrete consequence the append-only table exists to deny.

    ADR-0192 §1 measures the idempotency window from the **first** claim in the
    ledger's append order, so an implementation whose ordinals can be swapped
    measures a third attempt from the second claim and admits it outside the
    window. Driven at the ADR's own figures — a claim at ``t=0`` completed
    retryable, a second at ``t=9`` completed the same way, a third at ``t=18``.
    """
    clock = _StepClock()
    trail = SqliteAuditTrail(path=trail._path, now=clock)
    try:
        authorisation = _allow("d-1", tool_id="smtp", keyed=True)
        first = await _claimed(trail, authorisation)
        await _fail(trail, first)
        clock.at = 9
        second = await trail.claim_invocation(decision=authorisation)
        await _fail(trail, second)

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            trail._conn.execute("UPDATE invocations SET seq = 99 WHERE seq = 1")
        trail._conn.rollback()

        clock.at = 18
        with pytest.raises(AuthorisationSpentError, match="window"):
            await trail.claim_invocation(decision=authorisation)
    finally:
        trail.close()


@pytest.mark.integration
async def test_a_row_paired_with_a_record_of_another_decision_is_reported(
    trail: SqliteAuditTrail,
) -> None:
    """The join is held to the two *records*, not to the two columns it matched.

    ``RecordedInvocation`` carries the tool and the capability off the decision the
    join found. The ``decisions`` table's ``id`` is a stored primary key — it
    predates this lane and is not this lane's to restructure — so a row whose blob
    was replaced with another decision's keeps the ``id`` the join matches on, and
    the listing would report the act as having been authorised for a tool nobody
    approved it for.
    """
    await _claimed(trail, _allow("d-1", tool_id="smtp"))
    imposter = _allow("d-2", tool_id="wire-transfer")
    trail._conn.execute(
        "UPDATE decisions SET data = ? WHERE id = 'd-1'", (imposter.model_dump_json(),)
    )
    trail._conn.commit()  # the raw write is the case's premise, not a half-open transaction

    with pytest.raises(AuditError, match="the store is corrupt"):
        await trail.export_invocations()
