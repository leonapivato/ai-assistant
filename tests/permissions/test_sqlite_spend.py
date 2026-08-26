"""The durable holder passes both spend conformance suites (ADR-0194 §5, §11).

``SqliteAuditTrail`` is ADR-0137 §2's *primary production implementation* — the
consumer whose demands shape the contract — so the suites run against it as well
as against the canonical fake, and it is the subject that carries the cases the
fake can only skip: a store that outlives the object holding it, which is what
ADR-0194 §7's derived-total and §11's reopen clauses are about.

The lane-only cases at the foot of this module are the four ADR-0194 §11 gives
*the lane* rather than the shared suite: the trapped computation, the reopen, the
erasure interleavings, and which of ADR-0029 §4's two sides this holder's own
read falls on.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from spend_contract import (
    BOUNDED,
    FREE,
    REPORTING,
    Configured,
    MovableClock,
    Rows,
    SpendGateContract,
    SpendHarness,
    SpendLedgerContract,
    SpendSubject,
    totals_by_period,
    usd,
)

from ai_assistant.core.errors import SpendCeilingError, SpendUndeterminedError
from ai_assistant.core.types import SpendPeriod, ToolOutcome
from ai_assistant.permissions import spend as spend_module
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.testing.cancellation import LoopSuspension, ThreadSuspension

#: How long a case waits for something that should already have happened.
_WAITING = 2.0

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.testing.cancellation import SuspendedCall


def _configuration(configured: Configured) -> SpendConfiguration:
    """Read the suite's configuration into the shape this implementation takes."""
    return SpendConfiguration(
        currency=configured.currency,
        day_ceiling=configured.day_ceiling,
        month_ceiling=configured.month_ceiling,
        allowance=configured.allowance,
        zone=configured.timezone,
    )


class SqliteSpendHarness:
    """Builds ``SqliteAuditTrail`` subjects on files under one ``tmp_path``.

    On **files** rather than ``":memory:"``: ``store_of`` has to name something a
    second object can open, and that is the whole point of the reopen cases.
    Every trail opened is closed when the case ends.
    """

    def __init__(self, root: Path) -> None:
        """Open trails under ``root``, numbering each fresh store."""
        self._root = root
        self._opened: list[SqliteAuditTrail] = []
        self._stores: dict[int, object] = {}
        self._parked: list[ThreadSuspension] = []
        self._loop_parked: list[LoopSuspension] = []

    def open(
        self,
        configured: Configured = BOUNDED,
        *,
        now: MovableClock | None = None,
        identifiers: Any = None,
        store: object | None = None,
        shareable: bool = False,
    ) -> SpendSubject:
        """Return a trail over ``store``, over a fresh file, or over memory.

        ``":memory:"`` unless a case asks for a store a second holder can open,
        because a file pays a commit's worth of disk for every append and the
        ten-thousand-row case would spend two minutes on it. What that costs is
        nothing the suite asserts: the ``sqlite3`` semantics under test are the
        same either way, and the reopen cases ask for a file by name.
        """
        fresh = self._root / f"s{len(self._stores)}.db"
        path = store if store is not None else (fresh if shareable else ":memory:")
        trail = SqliteAuditTrail(
            path=path,  # type: ignore[arg-type]  # a Path or the str the suite handed back
            now=now if now is not None else MovableClock(),
            identifiers=identifiers,
            spend=_configuration(configured),
        )
        self._opened.append(trail)
        self._stores[id(trail)] = path
        subject: SpendSubject = trail
        return subject

    def store_of(self, subject: SpendSubject) -> object | None:
        """The file this trail was opened on, or ``None`` where it lives in memory."""
        held = self._stores.get(id(subject))
        return None if held == ":memory:" else held

    def fail_reads(self, subject: SpendSubject, times: int) -> bool:
        """Make the next ``times`` spend reads meet a backend that will not answer."""
        trail = subject
        assert isinstance(trail, SqliteAuditTrail)
        original = trail._spend_rows_sync
        remaining = [times]

        def failing(*args: object) -> object:
            if remaining[0] > 0:
                remaining[0] -= 1
                msg = "sqlite: the spend rows could not be read"
                raise OSError(msg)
            return original(*args)  # type: ignore[arg-type]

        trail._spend_rows_sync = failing  # type: ignore[method-assign, assignment]
        return True

    def arm_read(self, subject: SpendSubject) -> SuspendedCall | None:
        """Park the next spend read once its rows are in hand and its lock is released.

        After the snapshot, and deliberately not before it: ADR-0194 §3's
        take-effect rule is that a release landing between an admission's row
        snapshot and its comparison is not applied to that admission, and a
        suspension armed before the snapshot passes against an implementation that
        applies one.

        And after the **connection lock**, not inside it. Parking the worker inside
        ``_spend_rows_sync`` holds the one ``sqlite3`` connection open, so the
        completion append every one of these cases lands while the admission is
        parked would queue behind it and the case would deadlock — which is also
        why an earlier version of this harness could not have caught an admission
        that read outside that lock.
        """
        trail = subject
        assert isinstance(trail, SqliteAuditTrail)
        original = trail._spend_rows
        parked = LoopSuspension()
        armed = [False]

        async def blocking(periods: Any) -> Any:
            taken = await original(periods)
            if not armed[0]:
                armed[0] = True
                await parked.hold()
            return taken

        trail._spend_rows = blocking  # type: ignore[method-assign]
        self._loop_parked.append(parked)
        return parked

    def wedge_reads(self, subject: SpendSubject) -> bool:
        """A worker-thread read is not cancellation-cooperative, so this cannot be had.

        ADR-0029 §4's third bullet in as many words: ``_run_to_completion``
        absorbs a cancellation until the ``sqlite3`` worker physically finishes,
        because releasing the lock while the worker still holds the connection
        would let a second caller use it concurrently. Which side of §4 that puts
        this holder on is stated in a case of its own below, rather than left as
        an inherited default nobody looked at.
        """
        del subject
        return False

    def dispose(self) -> None:
        """Release anything still parked, then close every trail opened."""
        for parked in self._parked:
            parked.release()
        for waiting in self._loop_parked:
            waiting.release()
        for trail in self._opened:
            trail.close()


@pytest.fixture
def sqlite_spend(tmp_path: Path) -> Iterator[SqliteSpendHarness]:
    """A harness whose trails live under ``tmp_path`` and are closed after the case."""
    harness = SqliteSpendHarness(tmp_path)
    try:
        yield harness
    finally:
        harness.dispose()


class TestSqliteSpendGateContract(SpendGateContract):
    """Runs the durable holder through the gate's shared conformance suite."""

    @pytest.fixture
    def harness(self, sqlite_spend: SqliteSpendHarness) -> SqliteSpendHarness:
        return sqlite_spend

    @pytest.fixture
    def gate(self, sqlite_spend: SqliteSpendHarness) -> Any:
        return sqlite_spend.open()


class TestSqliteSpendLedgerContract(SpendLedgerContract):
    """Runs the durable holder through the ledger's shared conformance suite."""

    @pytest.fixture
    def harness(self, sqlite_spend: SqliteSpendHarness) -> SqliteSpendHarness:
        return sqlite_spend

    @pytest.fixture
    def ledger(self, sqlite_spend: SqliteSpendHarness) -> Any:
        return sqlite_spend.open()


def test_the_harness_satisfies_the_suites_own_protocol(tmp_path: Path) -> None:
    """The harness is what the suites are written against, so it is pinned here."""
    harness: SpendHarness = SqliteSpendHarness(tmp_path)
    try:
        assert harness.store_of(harness.open()) is None
        assert harness.store_of(harness.open(shareable=True)) is not None
    finally:
        harness.dispose()


# ---------------------------------------------------------------------------
# The four obligations ADR-0194 §11 gives *the lane* rather than the shared suite
# ---------------------------------------------------------------------------


async def test_a_trapped_sum_refuses_the_admission_naming_the_trap(
    sqlite_spend: SqliteSpendHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0194 §4's sixth ground, driven at the seam this implementation owns.

    §11 gives it to the lane rather than to the shared suite, because §2 requires
    a context sized from its own operands — under which the traps are a backstop
    rather than a reachable state, so no input a suite can supply through the
    Protocol makes a *conforming* implementation trap. Dropping the ground because
    no well-formed input reaches it would leave the case unclassified, which is
    the failure §4 keeps two classes to prevent.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(now=clock)
    await Rows(subject, clock).completed(usd("1"))

    def trapping(*_: object) -> Decimal:
        raise spend_module.SpendArithmeticError("the context was not sized")

    monkeypatch.setattr("ai_assistant.permissions.audit.exact_sum", trapping)

    with pytest.raises(SpendUndeterminedError, match="trapped"):
        await subject.admit_invocation(estimate=usd("1"))


async def test_a_trapped_sum_leaves_the_read_indeterminate_rather_than_raising(
    sqlite_spend: SqliteSpendHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The **read** side of the same trap, and it is not the same fixture.

    An implementation translating a trap correctly inside ``admit_invocation`` can
    still leak the ``decimal`` exception out of ``spend_totals``, or raise
    ``SpendUndeterminedError`` from it, and pass every admission-side assertion.
    ADR-0194 §5 permits that member exactly one raised class and only where it
    cannot produce the values at all; a trapped sum is not that case.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(REPORTING, now=clock)
    await Rows(subject, clock).completed(usd("1"))

    def trapping(*_: object) -> Decimal:
        raise spend_module.SpendArithmeticError("the context was not sized")

    monkeypatch.setattr("ai_assistant.permissions.audit.exact_sum", trapping)

    stated = totals_by_period(await subject.spend_totals())

    assert stated[SpendPeriod.CALENDAR_DAY].currency == "USD"
    assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
    assert stated[SpendPeriod.CALENDAR_MONTH].accounted is None


async def test_a_reopened_holder_rebuilds_the_total_from_the_rows(
    sqlite_spend: SqliteSpendHarness, tmp_path: Path
) -> None:
    """ADR-0194 §7: the accounted total is derived and no cache is authoritative.

    A holder that keeps a correct in-process cache and initialises it to zero on
    construction passes every aggregation, rollover and erasure case above, then
    reports zero after a restart and admits calls against spend the store still
    holds.
    """
    clock = MovableClock()
    first = sqlite_spend.open(now=clock, shareable=True)
    await Rows(first, clock).completed(usd("95"))
    before = totals_by_period(await first.spend_totals())
    with pytest.raises(SpendCeilingError):
        await first.admit_invocation(estimate=usd("10"))
    store = sqlite_spend.store_of(first)

    reopened = sqlite_spend.open(now=MovableClock(now=clock.now), store=store)

    after = totals_by_period(await reopened.spend_totals())
    assert after[SpendPeriod.CALENDAR_DAY].accounted == before[SpendPeriod.CALENDAR_DAY].accounted
    with pytest.raises(SpendCeilingError):
        await reopened.admit_invocation(estimate=usd("10"))


async def test_a_reopened_holder_rebuilds_indeterminacy_from_a_persisted_claim(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """A separate fixture, because it catches a different implementation.

    The case above reconstructs a *number* from completion rows; a holder that
    re-reads those correctly while holding open claims in memory alone passes it,
    and then, after a restart, states that period's ``accounted`` as a figure and
    admits a call where ADR-0194 §2 requires ``accounted=None`` and a refusal.
    Indeterminacy is a fact about the rows the store holds, not about the process
    that observed them being appended. It then ends where §2 says it ends and not
    before.
    """
    clock = MovableClock()
    first = sqlite_spend.open(now=clock, shareable=True)
    claim = await Rows(first, clock).claimed()
    store = sqlite_spend.store_of(first)

    reopened = sqlite_spend.open(now=MovableClock(now=clock.now), store=store)

    stated = totals_by_period(await reopened.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].currency == "USD"
    assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
    with pytest.raises(SpendUndeterminedError) as refusal:
        await reopened.admit_invocation(estimate=usd("1"))
    assert "calendar_day" in str(refusal.value)

    await reopened.complete_invocation(
        claim_id=claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=usd("1")
    )
    assert await reopened.admit_invocation(estimate=usd("1"))


async def test_erasing_the_persisted_claim_also_ends_the_indeterminacy(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """The other of the two ways ADR-0194 §2 says that state ends."""
    clock = MovableClock()
    first = sqlite_spend.open(now=clock, shareable=True)
    await Rows(first, clock).claimed()
    store = sqlite_spend.store_of(first)
    reopened = sqlite_spend.open(now=MovableClock(now=clock.now), store=store)
    with pytest.raises(SpendUndeterminedError):
        await reopened.admit_invocation(estimate=usd("1"))

    await reopened.clear()

    stated = totals_by_period(await reopened.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
    assert await reopened.admit_invocation(estimate=usd("1"))


async def test_erasure_resets_the_total_and_lifts_a_refusal(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """ADR-0194 §7 and §4's sixth lifting path, asserted from the outside.

    Nothing preserves a total across an erasure and no counter outlives one: the
    user who erases the trail has made a deliberate, wholesale act about their own
    record, and the ceiling is not a lock against that user.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(now=clock)
    await Rows(subject, clock).completed(usd("101"))
    with pytest.raises(SpendCeilingError):
        await subject.admit_invocation(estimate=FREE)

    await subject.clear()

    stated = totals_by_period(await subject.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
    assert stated[SpendPeriod.CALENDAR_MONTH].accounted == Decimal("0")
    assert await subject.admit_invocation(estimate=usd("50"))


async def test_an_erased_invocation_s_spend_is_not_counted_in_either_ordering(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """ADR-0192 §6's ordering inherited, with this ADR's budget consequence added.

    The erasure wins, a completion whose claim it erased is refused, and nothing is
    minted to recover the spend of the invocation that was erased — which would be
    the spend counter outliving an erasure that ADR-0194 §7 forbids.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(now=clock)
    rows = Rows(subject, clock)
    await rows.completed(usd("40"))
    claim = await rows.claimed()

    await subject.clear()

    with pytest.raises(Exception):  # noqa: B017, PT011 - the class is ADR-0192's
        await subject.complete_invocation(
            claim_id=claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=usd("40")
        )
    stated = totals_by_period(await subject.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")

    await rows.completed(usd("40"))
    after = totals_by_period(await subject.spend_totals())
    assert after[SpendPeriod.CALENDAR_DAY].accounted == Decimal("40")


async def test_an_understated_declaration_is_admitted_and_its_overrun_is_recorded(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """ADR-0194 §2's stated overrun, end to end.

    The ceiling promises that no invocation *begins* while the projection exceeds
    it, and does not promise that the accounted total never exceeds one: a declared
    estimate can understate what a call turned out to cost. So the call is
    admitted, the row that carried the total past the ceiling is **counted** rather
    than excused, and the next call is refused. This is the property this ADR
    promises and the one it does not, asserted rather than described.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(now=clock)
    rows = Rows(subject, clock)
    held = await subject.admit_invocation(estimate=usd("1"))
    await rows.completed(usd("140"))
    subject.release_admission(held)

    stated = totals_by_period(await subject.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("140")
    with pytest.raises(SpendCeilingError):
        await subject.admit_invocation(estimate=FREE)


def _park_the_worker(subject: SpendSubject) -> ThreadSuspension:
    """Block the ``sqlite3`` worker itself inside the read, not the coroutine above it.

    The harness's own ``arm_read`` parks on the event loop *after* the read has
    returned, which is what the race cases need. This one parks where ADR-0029 §4's
    third bullet lives: inside the worker thread ``_run_to_completion`` waits on and
    absorbs a cancellation for.
    """
    trail = subject
    assert isinstance(trail, SqliteAuditTrail)
    original = trail._spend_rows_sync
    parked = ThreadSuspension()

    def blocking(*args: object) -> object:
        parked.hold()
        return original(*args)  # type: ignore[arg-type]

    trail._spend_rows_sync = blocking  # type: ignore[method-assign, assignment]
    return parked


async def test_this_holder_s_wedged_read_outlives_its_caller_s_deadline(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """Which of ADR-0029 §4's two sides **this** implementation's read falls on.

    The deadline is **outlived**, and that is conforming: ``_run_to_completion``
    absorbs a cancellation until the ``sqlite3`` worker physically finishes,
    because releasing the connection while the worker still holds it would let a
    second caller use it concurrently (ADR-0054). §4's third bullet rules it in as
    many words — "a tool that suppresses its own cancellation can outlive its
    deadline, and no seam can prevent that … This is a genuine hole and the honest
    position is that it is unclosable from this side".

    What is *not* conforming is a lane that writes only cooperative-fake fixtures,
    inherits that absorption without noticing, and leaves a reader of its tests
    believing the deadline is a hard bound. So the fact is stated here: the timeout
    below expires only after the parked worker is released, and the case measures
    that rather than asserting a bound this holder does not have.
    """
    subject = sqlite_spend.open()
    parked = _park_the_worker(subject)

    admission = asyncio.ensure_future(subject.admit_invocation(estimate=usd("1")))
    await parked.reached()
    admission.cancel()
    await asyncio.sleep(0.05)

    assert not admission.done(), "the read absorbed the cancellation, as ADR-0054 has it"
    parked.release()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(admission, _WAITING)

    # And the holder closes cleanly with that read already finished, which is what
    # a shutdown reaches it as.
    assert isinstance(subject, SqliteAuditTrail)
    subject.close()


async def test_a_spend_read_holds_the_one_connection_against_an_append(
    sqlite_spend: SqliteSpendHarness,
) -> None:
    """The read takes the connection's own lock, as every other method of this store does.

    One ``sqlite3`` connection admits one transaction: two workers inside it can
    meet a ``BEGIN`` while one is already open, and what that produces is a refusal
    the ceiling had nothing to do with — or a disturbed transaction boundary on the
    *append*, which is ADR-0054's reason for the exclusion in the first place. The
    hazard is timing-dependent, so it is pinned as the exclusion rather than as the
    failure: with the read's worker parked, a completion append **does not
    complete** until it is released.

    Its complement — that the lock is *released* before the comparison, so an
    append can land while the admission sits between its snapshot and its decision
    — is the shared suite's, driven over both implementations.
    """
    clock = MovableClock()
    subject = sqlite_spend.open(REPORTING, now=clock)
    claim = await Rows(subject, clock).claimed()
    parked = _park_the_worker(subject)

    reading = asyncio.ensure_future(subject.spend_totals())
    await parked.reached()
    appending = asyncio.ensure_future(
        subject.complete_invocation(
            claim_id=claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=usd("1")
        )
    )
    await asyncio.sleep(0.05)

    assert not appending.done(), "the append reached the connection beside a spend read"
    parked.release()
    assert await asyncio.wait_for(appending, _WAITING)
    assert await asyncio.wait_for(reading, _WAITING)
