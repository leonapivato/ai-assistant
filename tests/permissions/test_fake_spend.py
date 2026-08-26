"""The canonical fake passes both spend conformance suites (ADR-0194 §5, §11).

This is what lets ``tools/`` and ``orchestration/`` trust
``ai_assistant.testing.FakeSpendGate`` and ``FakeSpendLedger`` as stand-ins: they
are the same object — one holder satisfies both faces and ADR-0192's ledger over
one row set — held to the same calendar, the same exact arithmetic and the same
reservations a durable holder is.

It is also the subject that carries the cases a worker-thread store cannot reach:
a spend read that is cancellation-cooperative by construction, which is what
ADR-0194 §11's blocked-gate clause asks for.
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
from ai_assistant.testing import FakeSpendGate
from ai_assistant.testing.spend import SpendTrapError

if TYPE_CHECKING:
    from ai_assistant.testing.cancellation import SuspendedCall


class FakeSpendHarness:
    """Builds :class:`FakeSpendGate` subjects for the shared suites.

    ``store_of`` answers ``None``: a dict store does not outlive the object that
    holds it, so the restart cases skip **with their reason stated** rather than
    being omitted — they are proved on the ``sqlite3`` holder, which is the
    implementation whose store genuinely outlives a process.
    """

    def __init__(self) -> None:
        """Start with nothing open and nothing parked."""
        self._parked: list[SuspendedCall] = []

    def open(
        self,
        configured: Configured = BOUNDED,
        *,
        now: MovableClock | None = None,
        identifiers: Any = None,
        store: object | None = None,
        shareable: bool = False,
    ) -> SpendSubject:
        """Return a fresh fake; neither ``store`` nor ``shareable`` is satisfiable."""
        assert store is None, "this harness reports no shareable store"
        del shareable
        clock = now if now is not None else MovableClock()
        built = FakeSpendGate(
            now=clock,
            identifiers=identifiers,
            currency=configured.currency,
            day_ceiling=configured.day_ceiling,
            month_ceiling=configured.month_ceiling,
            allowance=configured.allowance,
            timezone=configured.timezone,
        )
        subject: SpendSubject = built
        return subject

    def store_of(self, subject: SpendSubject) -> object | None:
        """A dict store cannot be opened twice."""
        del subject
        return None

    def fail_reads(self, subject: SpendSubject, times: int) -> bool:
        """Make the next ``times`` spend reads raise, as a backend read would."""
        trail = subject
        assert isinstance(trail, FakeSpendGate)
        original = trail._spend_snapshot
        remaining = [times]

        async def failing() -> Any:
            if remaining[0] > 0:
                remaining[0] -= 1
                msg = "fake: the spend rows could not be read"
                raise RuntimeError(msg)
            return await original()

        trail._spend_snapshot = failing  # type: ignore[method-assign]
        return True

    def arm_read(self, subject: SpendSubject) -> SuspendedCall | None:
        """Hold the next spend read open after its rows are snapshotted."""
        trail = subject
        assert isinstance(trail, FakeSpendGate)
        parked = trail.suspend_next_spend_read()
        self._parked.append(parked)
        return parked

    def wedge_reads(self, subject: SpendSubject) -> bool:
        """Block every later spend read on a wait a cancellation can reach.

        A bare ``asyncio.Event`` and deliberately not the modelled resource: the
        resource's suspension absorbs its own cancellation (ADR-0054's shape),
        which is the *other* side of ADR-0029 §4 and is what this lever must not
        be. Cancellation-cooperative by construction is what ADR-0194 §11 asks a
        blocked-gate fixture to be driven over.
        """
        trail = subject
        assert isinstance(trail, FakeSpendGate)
        never = asyncio.Event()

        async def wedged() -> Any:
            await never.wait()
            return []  # pragma: no cover - the wait is never released

        trail._spend_snapshot = wedged  # type: ignore[method-assign]
        return True

    def dispose(self) -> None:
        """Release anything the suite left parked."""
        for parked in self._parked:
            parked.release()


class FakeSpendFixtures:
    """The subject and the harness, supplied to both suites the same way.

    ``gate`` and ``ledger`` are overridden here rather than left to the suite's
    defaults so they take ``self`` alone and the Protocol-triad check can
    *evaluate* them: that check reads what a fixture produces rather than what its
    body mentions, and a subject fixture needing another fixture is a deliberate
    false negative there. The harness stays for the cases that inject a clock, a
    factory or a configuration.
    """

    @pytest.fixture
    def harness(self) -> Any:
        """The binding's way of building further subjects."""
        return FakeSpendHarness()

    @pytest.fixture
    def gate(self) -> Any:
        """The canonical fake itself, under its default configuration."""
        return FakeSpendGate(
            currency=BOUNDED.currency,
            day_ceiling=BOUNDED.day_ceiling,
            month_ceiling=BOUNDED.month_ceiling,
        )

    @pytest.fixture
    def ledger(self) -> Any:
        """The canonical fake itself, under its default configuration."""
        return FakeSpendGate(
            currency=BOUNDED.currency,
            day_ceiling=BOUNDED.day_ceiling,
            month_ceiling=BOUNDED.month_ceiling,
        )


class TestFakeSpendGateContract(FakeSpendFixtures, SpendGateContract):
    """Runs the canonical fake through the gate's shared conformance suite."""


class TestFakeSpendLedgerContract(FakeSpendFixtures, SpendLedgerContract):
    """Runs the canonical fake through the ledger's shared conformance suite."""


def test_the_harness_satisfies_the_suites_own_protocol() -> None:
    """The harness is what the suites are written against, so it is pinned here."""
    harness: SpendHarness = FakeSpendHarness()

    assert harness.store_of(harness.open()) is None


# ---------------------------------------------------------------------------
# The obligations ADR-0194 §11 gives *the lane*, driven against this holder
# ---------------------------------------------------------------------------


async def test_a_trapped_sum_refuses_the_admission_naming_the_trap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0194 §4's sixth ground, driven at the seam this implementation owns.

    §11 gives it to the lane rather than to the shared suite: §2 requires a context
    sized from its own operands, under which the traps are a backstop and not a
    reachable state, so no input a suite can supply through the Protocol makes a
    *conforming* implementation trap — and an obligation stated there would either
    pass vacuously or reach past the Protocol into an implementation's arithmetic.
    """
    harness = FakeSpendHarness()
    clock = MovableClock()
    subject = harness.open(now=clock)
    await Rows(subject, clock).completed(usd("1"))

    def trapping(*_: object) -> Decimal:
        raise SpendTrapError("the context was not sized")

    monkeypatch.setattr("ai_assistant.testing.permissions.add_exactly", trapping)

    with pytest.raises(SpendUndeterminedError, match="trapped"):
        await subject.admit_invocation(estimate=usd("1"))


async def test_a_trapped_sum_leaves_the_read_indeterminate_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The **read** side of the same trap, which is not the same fixture.

    An implementation translating a trap correctly inside ``admit_invocation`` can
    still leak the ``decimal`` exception out of ``spend_totals``, or raise
    ``SpendUndeterminedError`` from it, and pass every admission-side assertion.
    """
    harness = FakeSpendHarness()
    clock = MovableClock()
    subject = harness.open(REPORTING, now=clock)
    await Rows(subject, clock).completed(usd("1"))

    def trapping(*_: object) -> Decimal:
        raise SpendTrapError("the context was not sized")

    monkeypatch.setattr("ai_assistant.testing.permissions.add_exactly", trapping)

    stated = totals_by_period(await subject.spend_totals())

    assert stated[SpendPeriod.CALENDAR_DAY].currency == "USD"
    assert stated[SpendPeriod.CALENDAR_DAY].accounted is None


async def test_erasure_resets_the_total_and_lifts_a_refusal() -> None:
    """ADR-0194 §7 and §4's sixth lifting path, asserted from the outside.

    Nothing preserves a total across an erasure and no counter outlives one: the
    user who erases the trail has made a deliberate, wholesale act about their own
    record, and the ceiling is not a lock against that user.
    """
    harness = FakeSpendHarness()
    clock = MovableClock()
    subject = harness.open(now=clock)
    await Rows(subject, clock).completed(usd("101"))
    with pytest.raises(SpendCeilingError):
        await subject.admit_invocation(estimate=FREE)

    await subject.clear()

    stated = totals_by_period(await subject.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
    assert await subject.admit_invocation(estimate=usd("50"))


async def test_an_erased_invocation_s_spend_is_not_counted() -> None:
    """ADR-0192 §6's ordering inherited, with this ADR's budget consequence added.

    The erasure wins, a completion whose claim it erased is refused, and nothing is
    minted to recover the spend of the invocation that was erased — which would be
    the spend counter outliving an erasure ADR-0194 §7 forbids.
    """
    harness = FakeSpendHarness()
    clock = MovableClock()
    subject = harness.open(now=clock)
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


async def test_an_understated_declaration_is_admitted_and_its_overrun_is_recorded() -> None:
    """ADR-0194 §2's stated overrun, end to end.

    The ceiling promises that no invocation *begins* while the projection exceeds
    it, and not that the accounted total never exceeds one: a declared estimate can
    understate what a call turned out to cost. So the call is admitted, the row
    that carried the total past the ceiling is **counted** rather than excused, and
    the next call is refused.
    """
    harness = FakeSpendHarness()
    clock = MovableClock()
    subject = harness.open(now=clock)
    rows = Rows(subject, clock)
    held = await subject.admit_invocation(estimate=usd("1"))
    await rows.completed(usd("140"))
    subject.release_admission(held)

    stated = totals_by_period(await subject.spend_totals())
    assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("140")
    with pytest.raises(SpendCeilingError):
        await subject.admit_invocation(estimate=FREE)
