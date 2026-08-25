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
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    ToolInvocation,
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


def _allow(decision_id: str, tool_id: str = "smtp") -> PermissionDecision:
    """An ALLOW a claim can be admitted under, over a named tool."""
    return decision(
        decision_id,
        request=action(tool=tool(tool_id, side_effecting=True, idempotency=Idempotency.NONE)),
        ruled=ruling(PermissionOutcome.ALLOW),
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
async def test_a_stored_column_that_disagrees_with_its_blob_is_reported(
    trail: SqliteAuditTrail,
) -> None:
    """``recorded_at_us`` cannot be derived, so it is checked instead.

    ``json_extract`` yields the stored ISO-8601 text, which does not sort as an
    instant — a whole second serialises with no fraction and sorts *after* the same
    second with one — so the ordering column is `_sort_key`'s integer microseconds
    and is genuinely a second copy. It decides no admission; it decides the order a
    listing is served in, and serving a row in the order some other instant would
    put it in is the trail telling the operator something that is not so.
    """
    await _claimed(trail, _allow("d-1"))
    trail._conn.execute("UPDATE invocations SET recorded_at_us = 1")
    trail._conn.commit()  # the raw write is the case's premise, not a half-open transaction

    with pytest.raises(AuditError, match="disagrees with the projection"):
        await trail.export_invocations()
    with pytest.raises(AuditError, match="disagrees with the projection"):
        await trail.recent_invocations()


@pytest.mark.integration
async def test_a_row_whose_record_was_replaced_wholesale_is_reported_where_it_can_be(
    trail: SqliteAuditTrail,
) -> None:
    """Rewriting ``data`` moves the derived columns with it, which is the honest limit.

    A generated column cannot disagree with the blob, so an edit that rewrites the
    blob is not caught by any comparison — the record itself now says something
    else, and no store can tell that from a record legitimately written unless it
    keeps a second, independently protected copy. What the store still refuses is a
    rewrite that does not survive the model, and a `seq` that no longer orders the
    row it names is the residue named in issue #1574.
    """
    await _claimed(trail, _allow("d-1"))
    trail._conn.execute("UPDATE invocations SET data = ?", ('{"id": "x"}',))
    trail._conn.commit()  # the raw write is the case's premise, not a half-open transaction

    with pytest.raises(AuditError, match="no longer validates"):
        await trail.export_invocations()


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
