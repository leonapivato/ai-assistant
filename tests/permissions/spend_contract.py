"""Shared conformance suites for the two spend faces (ADR-0194 §5, §11).

Every ``SpendGate`` implementation must pass :class:`SpendGateContract` and every
``SpendLedger`` must pass :class:`SpendLedgerContract`. They are two classes
because they are two Protocols with two consumers — the invoker holds a gate and
never a ledger, an adapter holds a ledger and never a gate — and one subject
satisfies both, because ADR-0194 §5 has one object implement them over the rows
ADR-0192's ledger appends.

**The subject is one object satisfying both faces *and* ``InvocationLedger`` and
``AuditTrail``.** That is not a convenience: an accounted total is a function of
completion rows, so a suite that could not append one would have nothing to sum,
and a suite that could not ``clear()`` could not drive the erasure ADR-0194 §7
makes reset it.

**What is deliberately not here.** Everything ADR-0194 §11 assigns to the
consumer group — ``Settings``' four fields and their load refusals, the invoker's
own call to ``admit_invocation`` and the ``ToolInvoker`` obligations that follow
it, the ``AssistantEngine`` relay, ``wire/codec.py``'s ``Decimal`` row and §6's
``assistant spend`` command. And the two obligations §11 gives *the lane* rather
than this suite: the trapped computation, which no input reaching a conforming
implementation through these Protocols can provoke, and the correspondence of a
returned ``SpendTotal``'s bounds to §1's rule, which only a producer can be held
to.

Named ``*_contract`` (not ``test_*``) so pytest collects it only through a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import decimal
import inspect
import itertools
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import pytest
from permission_builders import action, decision, ruling, tool

from ai_assistant.core.errors import SpendCeilingError, SpendUndeterminedError
from ai_assistant.core.protocols import AuditTrail, InvocationLedger, SpendGate, SpendLedger
from ai_assistant.core.types import (
    CostBasis,
    Idempotency,
    PermissionOutcome,
    SpendAdmissionHandle,
    SpendPeriod,
    SpendTotal,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.testing.cancellation import SuspendedCall


#: A fixed instant well inside every representable range, so a case that is not
#: about the calendar never has to think about one.
NOON = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

#: How long a case waits for something that should already have happened.
_PATIENCE = 2.0


def usd(amount: str) -> ToolCost:
    """A ``PER_CALL`` cost of ``amount`` in the fixtures' configured currency."""
    return ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(amount), currency="USD")


def eur(amount: str) -> ToolCost:
    """A ``PER_CALL`` cost in a currency the fixtures never configure."""
    return ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(amount), currency="EUR")


#: The two costs that carry no amount at all.
FREE = ToolCost(basis=CostBasis.FREE)
UNKNOWN = ToolCost(basis=CostBasis.UNKNOWN)


@dataclass(frozen=True, slots=True)
class Configured:
    """The five values ADR-0194 §5 has a composition root inject.

    Passed to :meth:`SpendHarness.open` as one value rather than as five keywords
    so that a case reads as a configuration rather than as an argument list, and
    so a harness can hand its implementation whatever shape that implementation
    takes them in.
    """

    currency: str | None = None
    day_ceiling: Decimal | None = None
    month_ceiling: Decimal | None = None
    allowance: Decimal | None = None
    timezone: str = "UTC"


#: The configuration most cases start from: both ceilings, a currency, no
#: allowance. A case that is about one of the five states that one by ``replace``.
BOUNDED = Configured(
    currency="USD", day_ceiling=Decimal("100"), month_ceiling=Decimal("1000"), timezone="UTC"
)

#: A reporting currency with no ceiling at all: totals are computed and readable
#: and nothing is ever refused (ADR-0194 §1).
REPORTING = Configured(currency="USD")

#: Nothing configured: no total is stated and nothing is refused.
UNPRICED = Configured()


class ClockFailedError(RuntimeError):
    """What an injected clock raises when a case wants it to fail.

    A plain ``RuntimeError`` subclass on purpose: ADR-0194 §4's third ground is
    "the injected clock raised", whatever it raised, and a suite using an
    ``AssistantError`` here would let an implementation pass by catching the one
    hierarchy it already handles.
    """


@dataclass(eq=False)
class MovableClock:
    """An injected clock a case moves, scripts, or breaks.

    Attributes:
        now: What every unscripted reading returns.
        walk: Readings handed out in order before ``now`` takes over. A case that
            wants to catch an implementation reading the clock twice scripts two
            instants that would answer differently and asserts one of them
            governed both periods.
        failures: How many of the next readings raise :class:`ClockFailedError`.
        reads: How many readings have been taken, which is what a case asserts on
            when the rule is "one reading".
    """

    now: datetime = NOON
    walk: list[datetime] = field(default_factory=list)
    failures: int = 0
    reads: int = 0

    def __call__(self) -> datetime:
        """Take one reading."""
        self.reads += 1
        if self.failures > 0:
            self.failures -= 1
            msg = "the clock could not be read"
            raise ClockFailedError(msg)
        return self.walk.pop(0) if self.walk else self.now

    def moved(self, instant: datetime) -> None:
        """Move to ``instant`` and forget any script."""
        self.now = instant
        self.walk.clear()


@dataclass(eq=False)
class Candidates:
    """An injected id factory a case scripts, and which is well-behaved until it does.

    It starts minting values nothing has seen, because the subject mints ADR-0192
    **row** ids from the same injected factory: a case that armed a repeating
    value at construction would break the claim it needed to arrange its own rows.
    :meth:`script` is what switches it, after the arranging is done.

    Attributes:
        scripted: Candidates handed out in order; a single value repeats forever,
            which is how a case drives a factory that collides with itself.
        raises: Raised instead of the next candidate, then cleared. Typed as
            ``BaseException`` because ADR-0194 §3 divides exactly there.
        calls: How many candidates were asked for — what the refusal cases assert
            is unchanged, since a refusal consults the factory not at all.
    """

    scripted: list[object] = field(default_factory=list)
    raises: BaseException | None = None
    calls: int = 0
    reserved: list[str] = field(default_factory=list)
    _ordinal: itertools.count[int] = field(default_factory=itertools.count)

    def __call__(self) -> object:
        """Hand out the next candidate."""
        self.calls += 1
        if self.raises is not None:
            failure, self.raises = self.raises, None
            raise failure
        if not self.scripted:
            return f"candidate-{next(self._ordinal)}"
        return self.scripted[0] if len(self.scripted) == 1 else self.scripted.pop(0)

    def script(self, *values: object, raises: BaseException | None = None) -> None:
        """Hand out ``values`` from here on, or raise ``raises`` once."""
        self.scripted = list(values)
        self.raises = raises

    def reserve(self, taken: Iterable[str]) -> None:
        """Record ids the store asks not to be minted again (``IdentifierFactory``)."""
        self.reserved.extend(taken)


class SpendSubject(AuditTrail, InvocationLedger, SpendGate, SpendLedger, Protocol):
    """The union of faces ADR-0194 §5 says one object satisfies."""


class SpendHarness(Protocol):
    """How a suite builds and perturbs subjects of one implementation."""

    def open(
        self,
        configured: Configured = BOUNDED,
        *,
        now: MovableClock | None = None,
        identifiers: Any = None,
        store: object | None = None,
        shareable: bool = False,
    ) -> SpendSubject:
        """Return a subject over ``configured``, optionally reopening ``store``.

        ``shareable`` asks for a subject whose store :meth:`store_of` can name, so
        a second holder can be opened over it. It is off by default because the
        cheapest store an implementation has is usually the one nothing else can
        open, and only three cases here need the other kind.
        """
        ...

    def store_of(self, subject: SpendSubject) -> object | None:
        """Return something a second subject can be opened over, or ``None``."""
        ...

    def fail_reads(self, subject: SpendSubject, times: int) -> bool:
        """Make the next ``times`` spend reads fail; report whether it could."""
        ...

    def arm_read(self, subject: SpendSubject) -> SuspendedCall | None:
        """Hold the next admission open *after* its rows are snapshotted."""
        ...

    def wedge_reads(self, subject: SpendSubject) -> bool:
        """Block every later spend read on a **cancellable** wait; report whether it could.

        ADR-0194 §11 has the blocked-gate case driven over a read that is
        cancellation-cooperative *by construction*, which is what makes the
        assertion one about the seam rather than about ADR-0029 §4's excluded
        case. An implementation whose read is a worker thread cannot supply one
        and answers ``False``; which side of §4 its own read falls on is then a
        fact its lane states in a test of its own.
        """
        ...

    def dispose(self) -> None:
        """Release anything parked and close every subject opened."""
        ...


@dataclass(eq=False)
class Rows:
    """Drives ADR-0192 rows into a subject through the ledger's own seam.

    Never by reaching into a store: a completion is *recorded* by claiming under a
    recorded ``ALLOW`` and completing that claim, which is the only way one comes
    to exist in the running system. Each row gets its own decision, because
    ADR-0192 §1's consume gives a side-effecting non-``NATURAL`` authorisation
    exactly one claim.
    """

    subject: SpendSubject
    clock: MovableClock
    _ordinal: itertools.count[int] = field(default_factory=itertools.count)

    async def completed(
        self,
        cost: ToolCost,
        *,
        at: datetime | None = None,
        outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    ) -> ToolInvocation:
        """Append a claim and its completion, both stamped at ``at``."""
        claim = await self.claimed(at=at)
        failure = None if outcome is ToolOutcome.SUCCEEDED else ToolFailureKind.TIMED_OUT
        return await self.subject.complete_invocation(
            claim_id=claim.id, outcome=outcome, incurred_cost=cost, failure_kind=failure
        )

    async def claimed(
        self, *, at: datetime | None = None, declaring: ToolCost = FREE
    ) -> ToolInvocation:
        """Append a claim and leave it open, stamped at ``at``.

        ``declaring`` is the ``ToolCost`` on the tool the claim's decision pins.
        It is a knob because ADR-0194 §2 makes an open claim indeterminate
        "whatever the claim's decision declared": a total that substituted the
        declaration for a figure nobody reported would be stating one nobody made.
        """
        if at is not None:
            self.clock.moved(at)
        ruled = decision(
            f"spend-{next(self._ordinal)}",
            request=action(tool=tool(cost=declaring)),
            ruled=ruling(PermissionOutcome.ALLOW),
        )
        await self.subject.record(ruled)
        return await self.subject.claim_invocation(decision=ruled)

    async def bulk(self, cost: ToolCost, *, count: int, per_decision: int = 25) -> None:
        """Append ``count`` completions of ``cost``, as cheaply as the seam allows.

        Under decisions whose tool is ``NATURAL``, because ADR-0192 §1's consume
        refuses a second claim only on a *spendable* authorisation — "a read gated
        by ADR-0016 §3 is invoked under one ``ALLOW`` as often as the pipeline
        needs it". Several decisions rather than one, because the consume's
        per-decision scan is what a single decision would make quadratic.
        """
        made = 0
        while made < count:
            ruled = decision(
                f"bulk-{next(self._ordinal)}",
                request=action(tool=tool(idempotency=Idempotency.NATURAL)),
                ruled=ruling(PermissionOutcome.ALLOW),
            )
            await self.subject.record(ruled)
            for _ in range(min(per_decision, count - made)):
                claim = await self.subject.claim_invocation(decision=ruled)
                await self.subject.complete_invocation(
                    claim_id=claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=cost
                )
                made += 1


def _times(unit: Decimal, count: int) -> Decimal:
    """Return ``unit * count`` exactly, whatever the ambient context is.

    ``Decimal.__mul__`` rounds to the ambient precision, so the expected value of
    a total needing twenty-nine significant digits cannot be computed with it —
    the case would then assert the subject matches a figure the *suite* rounded.
    Composed from the coefficient instead, which is integer arithmetic.
    """
    sign, digits, exponent = unit.as_tuple()
    assert isinstance(exponent, int)
    coefficient = int("".join(str(digit) for digit in digits)) * count
    return Decimal(f"{'-' if sign else ''}{coefficient}E{exponent}")


def _earliest_local(day: date, zone: ZoneInfo) -> datetime:
    """ADR-0194 §1's boundary for ``day``, computed here rather than borrowed.

    "The earliest instant whose local civil date is greater than or equal to
    ``day``", found by walking forward from well before it — minute by minute and
    then second by second — rather than by constructing a wall-clock midnight.
    That is deliberately *not* how either implementation computes it: the
    correspondence §5 declines to put on the model is checked at the producer, and
    checking it against a second copy of the producer's own algorithm would check
    nothing.
    """
    from_utc = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=36)
    coarse = next(
        from_utc + timedelta(minutes=step)
        for step in range(72 * 60 + 1)
        if (from_utc + timedelta(minutes=step)).astimezone(zone).date() >= day
    )
    start = coarse - timedelta(minutes=1)
    return next(
        start + timedelta(seconds=step)
        for step in range(61)
        if (start + timedelta(seconds=step)).astimezone(zone).date() >= day
    )


def totals_by_period(totals: Sequence[SpendTotal]) -> dict[SpendPeriod, SpendTotal]:
    """Index a ``spend_totals`` result, for cases that are not about its order."""
    return {total.period: total for total in totals}


#: How a refusal names **which** of ADR-0194 §4's six grounds applied.
#:
#: §4 fixes the *fact* each message states and leaves the wording to an
#: implementation, so a shared suite needs a vocabulary or it cannot compare two
#: of them. This is that vocabulary: a conforming message names its ground in one
#: of these terms, and the ordering cases below are decided on it. Nothing here
#: widens §4 — a message may say more, and none of these patterns matches a
#: message about a different ground, which is what makes the ordering assertions
#: about order rather than about phrasing.
GROUND = {
    "amount": r"not countable",
    "unpriced": r"no number",
    "clock": r"clock",
    "store": r"store",
    "period": r"cannot be measured",
    "trap": r"trapped",
}


class SpendLedgerContract:
    """What every ``SpendLedger`` must do (ADR-0194 §5, §11).

    Subclassed by one binding per implementation, which supplies ``harness`` and
    the ``ledger`` fixture the Protocol-triad check evaluates.
    """

    @pytest.fixture
    def harness(self) -> SpendHarness:
        """The binding's way of building and perturbing subjects."""
        raise NotImplementedError

    @pytest.fixture
    def ledger(self) -> SpendLedger:
        """One subject in its default configuration, built with no other fixture."""
        raise NotImplementedError

    async def test_spend_totals_returns_both_periods_in_the_fixed_order(
        self, ledger: SpendLedger
    ) -> None:
        """The tuple is ``CALENDAR_DAY`` then ``CALENDAR_MONTH``, whatever is configured.

        Asserted as the exact sequence of ``period`` values rather than by looking
        each entry up: ADR-0194 §5 states the order as part of the contract, and a
        producer returning the month first satisfies every totals, coherence and
        error-ordering case here while changing what every reader of the surface
        sees.
        """
        stated = await ledger.spend_totals()

        assert [total.period for total in stated] == [
            SpendPeriod.CALENDAR_DAY,
            SpendPeriod.CALENDAR_MONTH,
        ]

    async def test_an_unconfigured_currency_states_no_total_at_all(
        self, harness: SpendHarness
    ) -> None:
        """With no currency, nothing is summed and both absences are the *other* one.

        ``currency`` is what discriminates ``accounted``'s two absences (ADR-0194
        §5), so this is the state a reader must be able to tell from an
        indeterminate period — and the bounds are still stated, because a period
        exists whether or not anybody priced it.
        """
        subject = harness.open(UNPRICED)

        stated = await subject.spend_totals()

        assert [total.currency for total in stated] == [None, None]
        assert [total.accounted for total in stated] == [None, None]
        assert [total.ceiling for total in stated] == [None, None]
        assert all(total.period_start < total.period_end for total in stated)

    async def test_a_reporting_currency_states_a_total_with_no_ceiling(
        self, harness: SpendHarness
    ) -> None:
        """A currency alone computes totals and configures no bound (ADR-0194 §1)."""
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).completed(usd("12.50"))

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("12.50")
        assert stated[SpendPeriod.CALENDAR_DAY].ceiling is None
        assert stated[SpendPeriod.CALENDAR_MONTH].accounted == Decimal("12.50")

    async def test_an_indeterminate_period_is_returned_rather_than_raised(
        self, harness: SpendHarness
    ) -> None:
        """An open claim states ``accounted=None`` beside a present ``currency``.

        ADR-0194 §5 permits this member exactly one raised class and only where it
        can produce no value at all; a period nobody can measure is a value.
        """
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).claimed()

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].currency == "USD"
        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
        assert stated[SpendPeriod.CALENDAR_MONTH].accounted is None

    async def test_a_raising_clock_refuses_the_read(self, harness: SpendHarness) -> None:
        """A clock that raised leaves no period to state, so the read refuses."""
        clock = MovableClock(failures=1)
        subject = harness.open(REPORTING, now=clock)

        with pytest.raises(SpendUndeterminedError, match="clock"):
            await subject.spend_totals()

    async def test_a_failed_store_read_refuses_the_read(self, harness: SpendHarness) -> None:
        """A store that could not answer refuses, and never as its own error type."""
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        if not harness.fail_reads(subject, 1):
            pytest.skip("this implementation holds no store a read can fail against")

        with pytest.raises(SpendUndeterminedError):
            await subject.spend_totals()

    async def test_both_entries_come_from_one_reading_of_the_clock(
        self, harness: SpendHarness
    ) -> None:
        """A clock stepping between reads cannot pair periods that do not contain each other.

        The script would put the day in September and the month in August if the
        implementation read twice; one reading makes the month contain the day,
        which is asserted as containment rather than as a count so that an
        implementation caching a reading is held to the same rule.
        """
        clock = MovableClock(
            now=datetime(2026, 9, 1, 0, 30, tzinfo=UTC),
            walk=[datetime(2026, 8, 31, 23, 30, tzinfo=UTC)],
        )
        subject = harness.open(REPORTING, now=clock)

        stated = totals_by_period(await subject.spend_totals())

        day = stated[SpendPeriod.CALENDAR_DAY]
        month = stated[SpendPeriod.CALENDAR_MONTH]
        assert month.period_start <= day.period_start
        assert day.period_end <= month.period_end

    async def test_the_pair_is_one_a_single_snapshot_could_have_produced(
        self, harness: SpendHarness
    ) -> None:
        """A completion landing between two aggregations must not be in one and not the other.

        The fixture is built so there are exactly **two** admissible pairs and it
        names them. The weaker "the day never exceeds the month" is what the same
        fixture invites and is not the rule: ``(0, 10)`` — the day aggregated
        before the append and the month after it — satisfies containment, is a
        state no snapshot of the rows was ever in, and is exactly what ADR-0194
        §5's one-snapshot rule forbids.
        """
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        rows = Rows(subject, clock)
        held = harness.arm_read(subject)
        if held is None:
            pytest.skip("this implementation exposes no point between the two aggregations")

        reading = asyncio.ensure_future(subject.spend_totals())
        await held.reached()
        await rows.completed(usd("10"))
        held.release()
        stated = totals_by_period(await asyncio.wait_for(reading, _PATIENCE))

        pair = (
            stated[SpendPeriod.CALENDAR_DAY].accounted,
            stated[SpendPeriod.CALENDAR_MONTH].accounted,
        )
        assert pair in {(Decimal("0"), Decimal("0")), (Decimal("10"), Decimal("10"))}

    async def test_a_period_containing_a_transition_carries_two_offsets(
        self, harness: SpendHarness
    ) -> None:
        """The offsets are the ones in force at the two bounds, and they differ here.

        ADR-0194 §5 carries two offsets rather than one precisely because a period
        containing a transition has different offsets at its ends, and a single
        offset would misrender exactly the periods §1's boundary rule was written
        to get right.
        """
        clock = MovableClock(now=datetime(2026, 3, 15, 12, tzinfo=UTC))
        subject = harness.open(replace(REPORTING, timezone="America/New_York"), now=clock)

        stated = totals_by_period(await subject.spend_totals())

        month = stated[SpendPeriod.CALENDAR_MONTH]
        assert month.start_offset == timedelta(hours=-5)
        assert month.end_offset == timedelta(hours=-4)

    async def test_an_offset_carrying_seconds_is_stated_unrounded(
        self, harness: SpendHarness
    ) -> None:
        """``Asia/Manila``'s ``-15:56:08`` is what the clock contract says was in force.

        A whole-minute rule would make a ``SpendTotal`` unable to state it, leaving
        the producer to leak a validation failure, round the offset, or fail to
        return the value it owes.
        """
        clock = MovableClock(now=datetime(1800, 6, 15, 12, tzinfo=UTC))
        subject = harness.open(replace(REPORTING, timezone="Asia/Manila"), now=clock)

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].start_offset == timedelta(
            hours=-15, minutes=-56, seconds=-8
        )


class SpendGateContract:
    """What every ``SpendGate`` must do (ADR-0194 §§1-4, §11).

    Subclassed by one binding per implementation, which supplies ``harness`` and
    the ``gate`` fixture the Protocol-triad check evaluates.
    """

    @pytest.fixture
    def harness(self) -> SpendHarness:
        """The binding's way of building and perturbing subjects."""
        raise NotImplementedError

    @pytest.fixture
    def gate(self) -> SpendGate:
        """One subject in its default configuration, built with no other fixture."""
        raise NotImplementedError

    # --- the comparison ----------------------------------------------------

    async def test_a_projection_equal_to_the_ceiling_is_admitted(
        self, harness: SpendHarness
    ) -> None:
        """Refusal is **strictly** above, so equality admits (ADR-0194 §3)."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("90"))

        handle = await subject.admit_invocation(estimate=usd("10"))

        assert isinstance(handle, SpendAdmissionHandle)

    async def test_one_cent_over_the_ceiling_is_refused(self, harness: SpendHarness) -> None:
        """A projection above a configured ceiling refuses, naming the numbers."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("90"))

        with pytest.raises(SpendCeilingError) as refusal:
            await subject.admit_invocation(estimate=usd("10.01"))

        assert "100.01" in str(refusal.value)
        assert "100" in str(refusal.value)

    async def test_a_free_call_is_admitted_with_the_total_already_at_the_ceiling(
        self, harness: SpendHarness
    ) -> None:
        """``FREE`` contributes zero, so a projection at the ceiling is still equality."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("100"))

        assert await subject.admit_invocation(estimate=FREE)

    async def test_a_zero_contribution_is_refused_against_a_total_already_over(
        self, harness: SpendHarness
    ) -> None:
        """A zero estimate changes what the projection *adds*, never whether it happens.

        Reachable by ADR-0194 §2's stated overrun — a declaration the reported cost
        exceeded — and it is the case every other zero-estimate fixture misses:
        those all meet a ledger that would have admitted anyway, so an
        implementation short-circuiting a zero contribution to an immediate grant
        passes them all and then lets the world be reached here.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("101"))

        for estimate in (FREE, usd("0")):
            with pytest.raises(SpendCeilingError):
                await subject.admit_invocation(estimate=estimate)

    async def test_a_zero_contribution_is_refused_against_a_period_it_cannot_measure(
        self, harness: SpendHarness
    ) -> None:
        """The other half of the same rule: an unmeasurable period refuses a zero too."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).claimed()

        for estimate in (FREE, usd("0")):
            with pytest.raises(SpendUndeterminedError):
                await subject.admit_invocation(estimate=estimate)

    async def test_a_zero_ceiling_binds_rather_than_meaning_no_ceiling(
        self, harness: SpendHarness
    ) -> None:
        """``Decimal("0")`` is a ceiling, and an ``if ceiling:`` test loses it.

        The smallest positive countable estimate is refused while a ``FREE`` call
        and a zero-amount one are admitted at equality. An implementation testing
        truthiness rather than ``is None`` admits the positive call and passes
        every other ceiling case here.
        """
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("0"), month_ceiling=Decimal("0"))
        )

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("0.000000001"))
        assert await subject.admit_invocation(estimate=FREE)
        assert await subject.admit_invocation(estimate=usd("0"))

    async def test_a_zero_ceiling_is_stated_as_a_ceiling_on_the_read_path(
        self, harness: SpendHarness
    ) -> None:
        """``spend_totals`` states ``Decimal("0")``, asserted on its tuple.

        Never on truthiness and never on the field's mere presence: a
        ``configured_ceiling or None`` at the producer passes every admission case
        above — the gate refuses correctly — and then tells a user their period has
        no ceiling while every priced call they make is being refused.
        """
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("0"), month_ceiling=Decimal("0"))
        )

        stated = totals_by_period(await subject.spend_totals())

        day = stated[SpendPeriod.CALENDAR_DAY]
        assert day.ceiling is not None
        assert day.ceiling.as_tuple() == (0, (0,), 0)
        assert day.accounted == Decimal("0")

    async def test_both_ceilings_bind_independently(self, harness: SpendHarness) -> None:
        """Only the day crossed refuses, and only the month crossed refuses too.

        The second is what catches an implementation that checks one ceiling and
        stops: the day total stays well under its own bound while the month is
        spent, so an implementation testing the day alone admits.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("990"), at=datetime(2026, 8, 20, 12, tzinfo=UTC))
        await rows.completed(usd("95"), at=NOON)

        with pytest.raises(SpendCeilingError) as day_crossed:
            await subject.admit_invocation(estimate=usd("6"))
        assert "calendar_day" in str(day_crossed.value)

        clock.moved(NOON)
        with pytest.raises(SpendCeilingError) as month_crossed:
            await subject.admit_invocation(estimate=usd("4"))
        assert "calendar_month" in str(month_crossed.value)
        assert "calendar_day" not in str(month_crossed.value)

    async def test_a_projection_crossing_both_ceilings_names_both_in_order(
        self, harness: SpendHarness
    ) -> None:
        """One error, both periods, ``CALENDAR_DAY`` then ``CALENDAR_MONTH``.

        ADR-0194 §4 fixes that there is no precedence, so a suite driving only the
        single-crossing cases leaves two conforming implementations free to report
        different periods.
        """
        clock = MovableClock()
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("10"), month_ceiling=Decimal("100")), now=clock
        )
        rows = Rows(subject, clock)
        await rows.completed(usd("90"), at=datetime(2026, 8, 20, 12, tzinfo=UTC))
        await rows.completed(usd("9"), at=NOON)

        with pytest.raises(SpendCeilingError) as refusal:
            await subject.admit_invocation(estimate=usd("2"))

        stated = str(refusal.value)
        assert stated.index("calendar_day") < stated.index("calendar_month")

    async def test_nothing_is_refused_where_no_ceiling_is_configured(
        self, harness: SpendHarness
    ) -> None:
        """A raising clock, a broken store and an open claim all admit (ADR-0194 §3).

        The short-circuit returns before any of the three is consulted, which is
        what makes "no ceiling configured means no ceiling" unconditional in fact
        rather than only in wording.
        """
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).claimed()

        assert await subject.admit_invocation(estimate=usd("10"))
        clock.failures = 1
        assert await subject.admit_invocation(estimate=usd("10"))
        if harness.fail_reads(subject, 1):
            assert await subject.admit_invocation(estimate=usd("10"))

    async def test_an_unmeasurable_estimate_is_admitted_where_no_ceiling_is_configured(
        self, harness: SpendHarness
    ) -> None:
        """Each estimate state that refuses *with* a ceiling is admitted without one.

        Without these the clause above is discharged by an implementation that
        tests the estimate before it tests whether a ceiling exists: it passes
        every case listed there and still refuses a call in the one configuration
        that must refuse nothing.
        """
        subject = harness.open(REPORTING)

        for estimate in (usd("1E15"), UNKNOWN, eur("1")):
            assert await subject.admit_invocation(estimate=estimate)

    # --- what has no number -------------------------------------------------

    async def test_an_unknown_estimate_is_refused_with_no_allowance_configured(
        self, harness: SpendHarness
    ) -> None:
        """An unpriced declaration has no number, so it refuses — and not as a crossing.

        Nothing measured a ceiling here, which is why ADR-0194 §4 keeps two
        classes: the assertion that this is *not* a ``SpendCeilingError`` is the
        point.
        """
        subject = harness.open()

        with pytest.raises(SpendUndeterminedError) as refusal:
            await subject.admit_invocation(estimate=UNKNOWN)

        assert not isinstance(refusal.value, SpendCeilingError)

    async def test_an_unknown_estimate_is_admitted_at_the_allowance(
        self, harness: SpendHarness
    ) -> None:
        """With an allowance the unpriced call is accounted at what the user stated.

        The arithmetic stays a real bound: the same call is refused where the
        allowance would carry the projection past the ceiling.
        """
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, allowance=Decimal("5")), now=clock)
        await Rows(subject, clock).completed(usd("95"))

        assert await subject.admit_invocation(estimate=UNKNOWN)

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=UNKNOWN)

    async def test_a_foreign_currency_estimate_is_refused_with_no_allowance(
        self, harness: SpendHarness
    ) -> None:
        """A cost in another currency is never converted, so it has no number here."""
        subject = harness.open()

        with pytest.raises(SpendUndeterminedError) as refusal:
            await subject.admit_invocation(estimate=eur("1"))

        assert not isinstance(refusal.value, SpendCeilingError)

    async def test_an_unknown_completion_makes_the_period_indeterminate(
        self, harness: SpendHarness
    ) -> None:
        """A reported ``UNKNOWN`` cost is never zero and never omitted (ADR-0194 §2)."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(UNKNOWN)

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd("1"))

    async def test_an_unknown_completion_is_determinate_at_the_allowance(
        self, harness: SpendHarness
    ) -> None:
        """The same row contributes the allowance where one is configured."""
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, allowance=Decimal("5")), now=clock)
        await Rows(subject, clock).completed(UNKNOWN)

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("5")

    async def test_a_foreign_currency_completion_makes_the_period_indeterminate(
        self, harness: SpendHarness
    ) -> None:
        """``EUR 90`` in a ``USD`` ledger is not 90, and adding it would convert at 1.0.

        Driven on the reported side in its own right, because an implementation
        refusing a declared ``EUR`` estimate correctly can still add an ``EUR 90``
        completion straight into a ``USD`` total — stating ``accounted=90`` with
        confidence, which is worse than an indeterminate total that says what it
        does not know.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(eur("90"))

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd("10"))

    async def test_a_foreign_currency_completion_contributes_the_allowance(
        self, harness: SpendHarness
    ) -> None:
        """With an allowance it contributes **that**, asserted as its own value not as 90."""
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, allowance=Decimal("5")), now=clock)
        await Rows(subject, clock).completed(eur("90"))

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("5")

    async def test_a_free_completion_contributes_zero_and_leaves_both_totals_determinate(
        self, harness: SpendHarness
    ) -> None:
        """A reported ``FREE`` carries no amount and is **not** an unknown price.

        An accumulator treating every completion carrying no amount as ``UNKNOWN``
        passes the declared-``FREE`` and reported-``UNKNOWN`` cases beside this
        one, then makes the period indeterminate and blocks a call nothing should
        have blocked.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(FREE)

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
        assert stated[SpendPeriod.CALENDAR_MONTH].accounted == Decimal("0")
        assert await subject.admit_invocation(estimate=usd("100"))

    async def test_an_indeterminate_outcome_completion_is_counted(
        self, harness: SpendHarness
    ) -> None:
        """A row nobody knows the fate of still carries a price the provider charged.

        An accumulator filtering that outcome out reports zero for a call that was
        billed and admits spend past the ceiling — and ADR-0194 §2's rule that no
        row is excluded "because the act may not have happened" is exactly what it
        would be violating. Asserted in the total *and* in the next admission.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("95"), outcome=ToolOutcome.INDETERMINATE)

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("95")
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("6"))

    @pytest.mark.parametrize("allowance", [None, Decimal("5")])
    @pytest.mark.parametrize("declaring", [FREE, usd("1")])
    async def test_an_open_claim_makes_the_period_indeterminate_whatever_was_declared(
        self, harness: SpendHarness, allowance: Decimal | None, declaring: ToolCost
    ) -> None:
        """A claim states an act *may* have happened and states nothing about its cost.

        Not the allowance, which stands for a price nobody knows, and not the
        declaration, which nobody reported — a total that used either would state a
        figure no completion carries.
        """
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, allowance=allowance), now=clock)
        await Rows(subject, clock).claimed(declaring=declaring)

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
        assert stated[SpendPeriod.CALENDAR_DAY].currency == "USD"

    async def test_a_claim_whose_completion_was_refused_stays_indeterminate(
        self, harness: SpendHarness
    ) -> None:
        """The completion append not landing is what leaves the claim open (ADR-0192 §7)."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        await rows.claimed()
        with pytest.raises(Exception):  # noqa: B017, PT011 - the class is ADR-0192's, not this ADR's
            await subject.complete_invocation(
                claim_id="no-such-claim", outcome=ToolOutcome.SUCCEEDED, incurred_cost=FREE
            )

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None

    async def test_a_period_rollover_clears_an_indeterminate_total(
        self, harness: SpendHarness
    ) -> None:
        """Indeterminacy is a state of one period and ends when *that* period does.

        The day clears at the day boundary while the month, which still contains
        the row, does not — and only the month's own rollover clears it. That
        asymmetry is the whole content of "a state of one period": an
        implementation persisting a flag rather than recomputing from the rows
        clears both at once, or neither.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(UNKNOWN, at=NOON)

        clock.moved(NOON + timedelta(days=1))
        rolled = totals_by_period(await subject.spend_totals())
        assert rolled[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
        assert rolled[SpendPeriod.CALENDAR_MONTH].accounted is None

        clock.moved(datetime(2026, 9, 2, 12, tzinfo=UTC))
        cleared = totals_by_period(await subject.spend_totals())
        assert cleared[SpendPeriod.CALENDAR_MONTH].accounted == Decimal("0")
        assert await subject.admit_invocation(estimate=usd("100"))

    async def test_an_unmeasurable_earlier_day_refuses_only_where_that_period_is_capped(
        self, harness: SpendHarness
    ) -> None:
        """ADR-0194 §2's per-period narrowing, driven where the two periods disagree.

        Every other indeterminacy case here puts the unmeasurable row in the
        current day and makes both periods indeterminate at once. With the row in
        an **earlier** day and only the day ceiling configured, the month is
        indeterminate, the day is not, and the call is admitted — a bound the user
        never stated must not refuse work they authorised.
        """
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, month_ceiling=None), now=clock)
        await Rows(subject, clock).completed(UNKNOWN, at=datetime(2026, 8, 20, 12, tzinfo=UTC))
        clock.moved(NOON)

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
        assert stated[SpendPeriod.CALENDAR_MONTH].accounted is None
        assert await subject.admit_invocation(estimate=usd("10"))

    async def test_the_mirror_refuses_where_the_month_is_the_capped_one(
        self, harness: SpendHarness
    ) -> None:
        """With only the month ceiling set, the same row refuses."""
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, day_ceiling=None), now=clock)
        await Rows(subject, clock).completed(UNKNOWN, at=datetime(2026, 8, 20, 12, tzinfo=UTC))
        clock.moved(NOON)

        with pytest.raises(SpendUndeterminedError) as refusal:
            await subject.admit_invocation(estimate=usd("10"))

        assert "calendar_month" in str(refusal.value)
        assert "calendar_day" not in str(refusal.value)

    async def test_both_indeterminate_periods_are_named_in_order(
        self, harness: SpendHarness
    ) -> None:
        """A current-day open claim is in the month too, so the message names both."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).claimed()

        with pytest.raises(SpendUndeterminedError) as refusal:
            await subject.admit_invocation(estimate=usd("1"))

        stated = str(refusal.value)
        assert stated.index("calendar_day") < stated.index("calendar_month")

    async def test_only_configured_periods_are_named(self, harness: SpendHarness) -> None:
        """The rule is over *configured* periods, since ADR-0194 §2 refuses on no other."""
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, day_ceiling=None), now=clock)
        await Rows(subject, clock).claimed()

        with pytest.raises(SpendUndeterminedError) as refusal:
            await subject.admit_invocation(estimate=usd("1"))

        assert "calendar_day" not in str(refusal.value)
        assert "calendar_month" in str(refusal.value)

    async def test_a_reporting_currency_alone_refuses_nothing_while_indeterminate(
        self, harness: SpendHarness
    ) -> None:
        """A total is stated and nothing is refused, even with the period unmeasurable."""
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).claimed()

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None
        assert await subject.admit_invocation(estimate=usd("1000000"))

    # --- ADR-0194 §4's grounds, and their order -----------------------------

    async def test_a_non_countable_declared_amount_refuses_the_call(
        self, harness: SpendHarness
    ) -> None:
        """ADR-0194 §4's first ground: a stated price this mechanism cannot add.

        And not a crossing: no ceiling was reached, and the projection could not be
        formed at all.
        """
        subject = harness.open()

        with pytest.raises(SpendUndeterminedError, match=GROUND["amount"]) as refusal:
            await subject.admit_invocation(estimate=usd("1E15"))

        assert not isinstance(refusal.value, SpendCeilingError)

    async def test_a_raising_clock_refuses_the_call(self, harness: SpendHarness) -> None:
        """ADR-0194 §4's third ground, and the message names no period.

        A clock that raised leaves no period to name, so an implementation
        inventing one would be stating a fact about a budget nothing measured.
        """
        subject = harness.open(now=MovableClock(failures=1))

        with pytest.raises(SpendUndeterminedError, match=GROUND["clock"]) as refusal:
            await subject.admit_invocation(estimate=usd("1"))

        assert "calendar_" not in str(refusal.value)

    async def test_a_failed_store_read_refuses_the_call(self, harness: SpendHarness) -> None:
        """ADR-0194 §4's fourth ground, translated rather than propagated.

        No backend exception type escapes either member: ``tools/`` never sees a
        store's own error class through this seam.
        """
        subject = harness.open()
        if not harness.fail_reads(subject, 1):
            pytest.skip("this implementation holds no store a read can fail against")

        with pytest.raises(SpendUndeterminedError, match=GROUND["store"]):
            await subject.admit_invocation(estimate=usd("1"))

    async def test_a_non_countable_amount_is_named_before_a_raising_clock(
        self, harness: SpendHarness
    ) -> None:
        """Ground 1 before ground 3: a fact about the call needs no I/O.

        Each ground's isolated case passes under either order, and the messages
        send an operator to different repairs — so the pairs are what pin it.
        """
        subject = harness.open(now=MovableClock(failures=1))

        with pytest.raises(SpendUndeterminedError, match=GROUND["amount"]):
            await subject.admit_invocation(estimate=usd("1E15"))

    async def test_a_non_countable_amount_is_named_before_its_own_currency(
        self, harness: SpendHarness
    ) -> None:
        """Grounds 1 and 2 together, which are both facts about the same estimate.

        A ``EUR`` cost of ``1E15`` with no allowance: an implementation checking
        the currency before the magnitude passes every case above and fails here.
        """
        subject = harness.open()

        with pytest.raises(SpendUndeterminedError, match=GROUND["amount"]):
            await subject.admit_invocation(estimate=eur("1E15"))

    async def test_an_unpriced_cost_is_named_before_a_raising_clock(
        self, harness: SpendHarness
    ) -> None:
        """Grounds 2 and 3 together: the estimate is read before the clock.

        An implementation reading the clock before it looks at the estimate at all
        passes every other ordering case and fails this one.
        """
        subject = harness.open(now=MovableClock(failures=1))

        with pytest.raises(SpendUndeterminedError, match=GROUND["unpriced"]):
            await subject.admit_invocation(estimate=UNKNOWN)

    async def test_a_raising_clock_is_named_before_a_failed_store_read(
        self, harness: SpendHarness
    ) -> None:
        """Ground 3 before ground 4: the period is what selects the rows."""
        clock = MovableClock(failures=1)
        subject = harness.open(now=clock)
        if not harness.fail_reads(subject, 1):
            pytest.skip("this implementation holds no store a read can fail against")

        with pytest.raises(SpendUndeterminedError, match=GROUND["clock"]):
            await subject.admit_invocation(estimate=usd("1"))

    async def test_a_failed_store_read_is_named_before_an_indeterminate_period(
        self, harness: SpendHarness
    ) -> None:
        """Ground 4 before ground 5: indeterminacy is a property of rows already read."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).claimed()
        if not harness.fail_reads(subject, 1):
            pytest.skip("this implementation holds no store a read can fail against")

        with pytest.raises(SpendUndeterminedError, match=GROUND["store"]):
            await subject.admit_invocation(estimate=usd("1"))

    async def test_an_unmeasurable_period_is_never_reported_as_an_overspend(
        self, harness: SpendHarness
    ) -> None:
        """Ground 5 before the crossing: a crossing is knowable only last.

        The projection here would also cross, so an implementation comparing before
        it checks measurability tells the operator they overspent when the truth is
        that nobody can say.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("99"))
        await rows.claimed()

        with pytest.raises(SpendUndeterminedError, match=GROUND["period"]) as refusal:
            await subject.admit_invocation(estimate=usd("50"))

        assert not isinstance(refusal.value, SpendCeilingError)

    async def test_a_cancellation_is_never_translated_into_either_class(
        self, harness: SpendHarness
    ) -> None:
        """A ``BaseException`` that is not an ``Exception`` propagates unchanged.

        ADR-0194 §4's exemption: a cancellation is neither a refusal nor a budget
        fact, and ADR-0029 §4 and ADR-0031 already own how one is classified.
        Delivered here through the injected id factory, which is the one
        collaborator the member calls on the granted path.
        """
        factory = Candidates()
        subject = harness.open(identifiers=factory)
        factory.script(raises=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await subject.admit_invocation(estimate=usd("1"))

    # --- reservations, and the handles that retire them ---------------------

    async def test_release_admission_is_not_a_coroutine_function(self, gate: SpendGate) -> None:
        """The signature is contract, not habit (ADR-0194 §5).

        An implementation declaring it ``async`` satisfies every behavioural clause
        below and reintroduces the suspension point the synchronous signature
        removes — after which a cancellation can be delivered inside it and the
        invoker's ``finally`` needs an ``await`` to reach it.
        """
        assert not inspect.iscoroutinefunction(gate.release_admission)

        # The call's own value, not a variable of the declared type: what is under
        # test is that it is `None` and not an awaitable, which is exactly what
        # mypy reads off the signature and is why the ignore is specific.
        released = gate.release_admission(  # type: ignore[func-returns-value]
            SpendAdmissionHandle(handle="never-minted")
        )

        assert released is None

    async def test_a_release_raises_nothing_whatever_it_is_handed(
        self, harness: SpendHarness
    ) -> None:
        """An unknown handle, one already released, and one taken with no ceiling.

        It is called from a ``finally`` whose call has already succeeded or already
        failed, so a member that could raise there would substitute a book-keeping
        failure for the outcome the caller was about to report.
        """
        subject = harness.open()
        held = await subject.admit_invocation(estimate=usd("1"))
        subject.release_admission(held)
        subject.release_admission(held)
        subject.release_admission(SpendAdmissionHandle(handle="never-minted"))

        unbounded = harness.open(REPORTING)
        subject.release_admission(await unbounded.admit_invocation(estimate=usd("1")))

    async def test_a_release_lowers_no_accounted_total(self, harness: SpendHarness) -> None:
        """The accounted total is read from rows, which a release does not touch."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("40"))
        held = await subject.admit_invocation(estimate=usd("10"))

        subject.release_admission(held)

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("40")

    async def test_a_reservation_survives_the_period_it_was_taken_in(
        self, harness: SpendHarness
    ) -> None:
        """It is counted whichever period is current, and released after a rollover.

        ADR-0194 §3: a call admitted before midnight can complete after it, so a
        reservation that lapsed at the boundary would leave that call counted in
        neither period while it ran.
        """
        clock = MovableClock(now=datetime(2026, 8, 25, 23, 50, tzinfo=UTC))
        subject = harness.open(now=clock)
        held = await subject.admit_invocation(estimate=usd("95"))

        clock.moved(datetime(2026, 8, 26, 0, 10, tzinfo=UTC))
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("10"))

        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("10"))

    async def test_outstanding_reservations_carry_their_own_amounts(
        self, harness: SpendHarness
    ) -> None:
        """Unequal amounts, because equal ones let a *count* stand in for a sum.

        Reservations of 1 and 9 against a ceiling of 15: a further estimate of 6
        projects 16 and is refused, where an implementation holding a count and
        reusing one amount projects 8 and admits. Releasing each in turn then shows
        that only that handle's own amount leaves the projection, which one release
        cannot.
        """
        capped = replace(BOUNDED, day_ceiling=Decimal("15"), month_ceiling=Decimal("15"))
        subject = harness.open(capped)
        small = await subject.admit_invocation(estimate=usd("1"))
        large = await subject.admit_invocation(estimate=usd("9"))

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("6"))

        subject.release_admission(small)
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("7"))
        subject.release_admission(large)
        assert await subject.admit_invocation(estimate=usd("15"))

    async def test_the_double_count_window_is_an_over_count(self, harness: SpendHarness) -> None:
        """A reservation standing beside its own completion counts the call twice.

        The direction is deliberate — the mechanism over-counts for one operation
        rather than under-counting for one — and asserting it is what stops an
        implementation "fixing" the window by releasing before the completion
        lands, which is the one interleaving that can admit spend it should refuse.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        held = await subject.admit_invocation(estimate=usd("60"))
        await rows.completed(usd("60"))

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))

        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("1"))

    # --- minting a handle ---------------------------------------------------

    async def test_two_admissions_receive_distinct_handles_from_one_repeated_value(
        self, harness: SpendHarness
    ) -> None:
        """A factory that repeats itself is disambiguated rather than trusted.

        Two reservations sharing a handle are one reservation, so the other's
        amount silently leaves the projection and a later call is admitted against
        a total that omits an admitted one. Driven by releasing one and asserting
        the other still stands.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        factory.script("h")

        first = await subject.admit_invocation(estimate=usd("10"))
        second = await subject.admit_invocation(estimate=usd("10"))

        assert first.handle != second.handle
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("20"))
        subject.release_admission(first)
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("21"))
        assert await subject.admit_invocation(estimate=usd("20"))

    async def test_a_retired_handle_value_is_never_delivered_again(
        self, harness: SpendHarness
    ) -> None:
        """Distinctness is over the holder's **lifetime**, not the outstanding set.

        The worse case of the two, because the release rule makes the damage
        silent: a stale release of a re-minted value cannot be told from a release
        of the live reservation now carrying it, and dropping the live one admits
        spend the ceiling should have refused.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        factory.script("h")

        first = await subject.admit_invocation(estimate=usd("10"))
        subject.release_admission(first)
        second = await subject.admit_invocation(estimate=usd("10"))
        assert second.handle != first.handle

        subject.release_admission(first)
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("21"))
        assert await subject.admit_invocation(estimate=usd("20"))

    async def test_candidates_that_collide_only_after_validation_are_disambiguated(
        self, harness: SpendHarness
    ) -> None:
        """``"h"`` and ``" h "`` are two raw strings and one handle.

        ``Identifier`` strips, so an implementation comparing raw factory output
        passes the case above and holds two reservations under one key here. The
        third value differs only by a Unicode space that same type strips.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        # The third candidate is the same handle again, spelled with a Unicode
        # figure space `Identifier` strips — which is the point of the case.
        factory.script("h", " h ", " h ")  # noqa: RUF001

        first = await subject.admit_invocation(estimate=usd("10"))
        second = await subject.admit_invocation(estimate=usd("10"))

        assert first.handle != second.handle
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("20"))
        subject.release_admission(first)
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("21"))

    @pytest.mark.parametrize(
        "candidate", ["   ", "\ud800", 17], ids=["blank", "surrogate", "not-a-str"]
    )
    async def test_a_candidate_the_type_refuses_costs_the_call_nothing(
        self, harness: SpendHarness, candidate: object
    ) -> None:
        """A handle is delivered, the reservation stands, and no third class escapes.

        ADR-0194 §5 closes ``admit_invocation``'s ``Exception`` set at two classes,
        so neither a ``ValidationError`` from building the handle nor the factory's
        own exception may reach ``tools/``. A suite driving only factories whose
        values validate leaves that path untested.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("80"))
        factory.script(candidate)

        held = await subject.admit_invocation(estimate=usd("10"))

        assert isinstance(held, SpendAdmissionHandle)
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("11"))
        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("11"))

    async def test_a_factory_that_raises_costs_the_call_nothing(
        self, harness: SpendHarness
    ) -> None:
        """A misbehaving handle generator is not a fact about anybody's budget.

        Deliberately not a refusal: ADR-0194 §4 enumerates
        ``SpendUndeterminedError`` over six ways *the spend* could not be reduced
        to a number, and a factory that raised is none of them.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("80"))
        factory.script(raises=RuntimeError("the factory is broken"))

        held = await subject.admit_invocation(estimate=usd("10"))

        assert isinstance(held, SpendAdmissionHandle)
        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("20"))

    async def test_a_generated_fallback_is_never_re_delivered_by_the_factory(
        self, harness: SpendHarness
    ) -> None:
        """The collision *between* the two sources, which neither case above reaches.

        The holder keeps one delivered set or it keeps two. An implementation
        checking a candidate only against what its **factory** produced, while its
        own generator's outputs live in a second set nothing checks, re-delivers
        the fallback here — after which the stale release drops a live reservation
        and the ceiling admits spend it should have refused.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        factory.script("   ")

        grown = (await subject.admit_invocation(estimate=usd("10"))).handle
        subject.release_admission(SpendAdmissionHandle(handle=grown))
        factory.script(grown)
        second = await subject.admit_invocation(estimate=usd("10"))

        assert second.handle != grown
        subject.release_admission(SpendAdmissionHandle(handle=grown))
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("21"))
        assert await subject.admit_invocation(estimate=usd("20"))

    async def test_a_refusal_consults_the_factory_not_at_all(self, harness: SpendHarness) -> None:
        """The mint sits on the far side of the comparison, and a raising factory proves it.

        An implementation minting before it compares turns a call this mechanism
        **refused** into a cancelled one, which ADR-0029 §4 then classifies
        ``INDETERMINATE`` for a side-effecting tool — telling a user the act may
        have happened when the ceiling stopped it before any callable existed.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("100"))
        counted = factory.calls

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))
        assert factory.calls == counted

        factory.script(raises=asyncio.CancelledError())
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))

    async def test_an_undetermined_refusal_consults_the_factory_not_at_all(
        self, harness: SpendHarness
    ) -> None:
        """The same pair on a guaranteed ``SpendUndeterminedError`` (§4's first ground)."""
        factory = Candidates()
        subject = harness.open(identifiers=factory)
        counted = factory.calls

        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd("1E15"))
        assert factory.calls == counted

        factory.script(raises=asyncio.CancelledError())
        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd("1E15"))

    # --- the races the reservation exists for -------------------------------

    async def test_two_concurrent_admissions_admit_exactly_one(self, harness: SpendHarness) -> None:
        """The property, and a sequential case cannot show it (ADR-0194 §3).

        An accounted total of 90, a ceiling of 100 and two declared estimates of
        10: both admissions read 90, and without a reservation both project exactly
        100, are admitted at equality, and 110 leaves. A suite that drove the two
        in sequence with a release between them passes against an implementation
        that reserves nothing.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("90"))

        outcomes = await asyncio.gather(
            subject.admit_invocation(estimate=usd("10")),
            subject.admit_invocation(estimate=usd("10")),
            return_exceptions=True,
        )

        granted = [one for one in outcomes if isinstance(one, SpendAdmissionHandle)]
        refused = [one for one in outcomes if isinstance(one, SpendCeilingError)]
        assert len(granted) == 1
        assert len(refused) == 1
        subject.release_admission(granted[0])
        assert await subject.admit_invocation(estimate=usd("10"))

    async def test_a_release_landing_inside_a_running_admission_is_not_applied_to_it(
        self, harness: SpendHarness
    ) -> None:
        """ADR-0194 §3's take-effect rule, and both halves of it.

        Accounted 90, one reservation of 10, a ceiling of 100, a second estimate of
        10. The second admission snapshots its rows; the outstanding call's
        completion is appended and its handle released while it is paused; and the
        second is **refused**, because the snapshot of 90 still carries the
        reservation standing in for the completion just appended, and 90 plus 10
        plus 10 is 110. The release itself returns without waiting for the paused
        admission, which is the other half.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("90"))
        held = await subject.admit_invocation(estimate=usd("10"))
        parked = harness.arm_read(subject)
        if parked is None:
            pytest.skip("this implementation exposes no point inside a running admission")

        second = asyncio.ensure_future(subject.admit_invocation(estimate=usd("10")))
        await parked.reached()
        await rows.completed(usd("10"))
        subject.release_admission(held)
        parked.release()

        with pytest.raises(SpendCeilingError):
            await asyncio.wait_for(second, _PATIENCE)

    async def test_a_release_names_its_reservation_when_it_is_called(
        self, harness: SpendHarness
    ) -> None:
        """ADR-0194 §3's resolution-at-call-time rule, which the pair above never reaches.

        A release naming a handle **no reservation carries** is discarded there and
        then. An implementation that queued the raw value and matched it when the
        queue drains passes the unknown-handle case, both halves of the race above
        and every lifetime-uniqueness case — and retires here a reservation taken
        *after* the release that supposedly names it, which is the one interleaving
        in which an unknown handle is not a no-op.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        parked = harness.arm_read(subject)
        if parked is None:
            pytest.skip("this implementation exposes no point inside a running admission")
        factory.script("chosen")

        admission = asyncio.ensure_future(subject.admit_invocation(estimate=usd("10")))
        await parked.reached()
        subject.release_admission(SpendAdmissionHandle(handle="chosen"))
        parked.release()
        held = await asyncio.wait_for(admission, _PATIENCE)

        assert held.handle == "chosen"
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("21"))
        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("21"))

    async def test_a_cancellation_inside_the_admission_strands_no_reservation(
        self, harness: SpendHarness
    ) -> None:
        """The projection is what the assertion is on, not the exception alone.

        A ``CancelledError`` delivered after the admission would have reserved
        leaves no reservation nobody holds a handle for — asserted by a later
        admission that only fits if nothing was left standing — and propagates
        unchanged, which is the assertion that is *not* sufficient on its own.
        """
        clock = MovableClock()
        factory = Candidates()
        subject = harness.open(now=clock, identifiers=factory)
        await Rows(subject, clock).completed(usd("70"))
        factory.script(raises=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await subject.admit_invocation(estimate=usd("29"))

        assert await subject.admit_invocation(estimate=usd("30"))

    async def test_a_release_returns_while_an_admission_is_blocked_on_its_store(
        self, harness: SpendHarness
    ) -> None:
        """ADR-0194 §3's liveness rule: a release cannot be made to wait.

        Were it made to wait on the admission's exclusion, an invocation whose
        callable had already returned would block in its ``finally`` behind
        another invocation's store I/O and outlast the ``timeout`` its own caller
        set — to a call that had already succeeded. Driven with two: one blocked
        inside the critical section on a store that never answers, and one already
        admitted whose handle is released while the first is still blocked. The
        assertion is the ordering — the release finished while the admission had
        not — which an implementation that serialised releases behind admissions
        cannot produce.
        """
        subject = harness.open()
        held = await subject.admit_invocation(estimate=usd("10"))
        if not harness.wedge_reads(subject):
            pytest.skip("this implementation's spend read is not cancellation-cooperative")
        order: list[str] = []

        blocked = asyncio.ensure_future(subject.admit_invocation(estimate=usd("10")))
        blocked.add_done_callback(lambda _: order.append("admission"))
        await asyncio.sleep(0)
        subject.release_admission(held)
        order.append("release")

        assert order == ["release"]
        blocked.cancel()
        with pytest.raises(asyncio.CancelledError):
            await blocked

    async def test_a_release_in_a_finally_lands_while_its_task_is_being_cancelled(
        self, harness: SpendHarness
    ) -> None:
        """A synchronous call in a ``finally`` completes whatever the task's state is.

        ADR-0194 §5's third property: the invoker's ``finally`` reaches the release
        with no ``await``, so unwinding under a cancellation cannot lose it. The
        reservation is asserted gone by an admission that only fits without it.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("70"))
        held = await subject.admit_invocation(estimate=usd("10"))
        parked = asyncio.Event()

        async def invoking() -> None:
            try:
                await parked.wait()
            finally:
                subject.release_admission(held)

        task = asyncio.ensure_future(invoking())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert await subject.admit_invocation(estimate=usd("30"))

    async def test_a_gate_blocked_on_its_store_lets_the_caller_s_deadline_expire(
        self, harness: SpendHarness
    ) -> None:
        """The window the admission newly occupies is inside the caller's deadline.

        ADR-0194 §3 puts the admission inside the deadline ``invoke`` already
        enforces, and what that buys is ADR-0029 §4's guarantee and no stronger
        one: the seam stops waiting, not that the gate stops working. Driven over
        a read that is cancellation-cooperative by construction, which is what
        makes this an assertion about the seam rather than about §4's excluded
        case — an implementation whose read absorbs its own cancellation states
        which side it falls on in its own lane's tests instead.
        """
        subject = harness.open()
        if not harness.wedge_reads(subject):
            pytest.skip("this implementation's spend read is not cancellation-cooperative")

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await subject.admit_invocation(estimate=usd("10"))

    # --- ADR-0194 §1's calendar, on real zones ------------------------------

    async def test_a_repeated_midnight_selects_the_earlier_instant(
        self, harness: SpendHarness
    ) -> None:
        """``America/Havana`` ends DST at 01:00, so 2026-11-01 00:00 happens twice.

        §1's one selection — the earliest instant whose local civil date is at
        least ``D`` — answers it with no case distinguished, and a row on each side
        of the selected instant is what shows the choice was made rather than
        inherited from whatever ``fold`` a default supplied.
        """
        boundary = datetime(2026, 11, 1, 4, tzinfo=UTC)
        clock = MovableClock()
        subject = harness.open(replace(REPORTING, timezone="America/Havana"), now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("7"), at=boundary - timedelta(seconds=1))
        await rows.completed(usd("11"), at=boundary)
        clock.moved(datetime(2026, 11, 1, 17, tzinfo=UTC))

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].period_start == boundary
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("11")

    async def test_a_midnight_that_does_not_exist_selects_the_transition_instant(
        self, harness: SpendHarness
    ) -> None:
        """``America/Santiago`` starts DST at 24:00, so 2026-09-06 00:00 never happens.

        The boundary is the transition instant itself, which is the earliest one
        whose local date has reached the sixth.
        """
        boundary = datetime(2026, 9, 6, 4, tzinfo=UTC)
        clock = MovableClock()
        subject = harness.open(replace(REPORTING, timezone="America/Santiago"), now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("7"), at=boundary - timedelta(seconds=1))
        await rows.completed(usd("11"), at=boundary)
        clock.moved(datetime(2026, 9, 6, 17, tzinfo=UTC))

        stated = totals_by_period(await subject.spend_totals())

        assert stated[SpendPeriod.CALENDAR_DAY].period_start == boundary
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("11")

    async def test_a_skipped_civil_date_leaves_its_neighbours_sharing_one_boundary(
        self, harness: SpendHarness
    ) -> None:
        """``Pacific/Apia`` has no instant whose local date is 2011-12-30.

        What is asserted is what the Protocol can observe: ``spend_totals``
        selects a period from the *current* instant, and no instant selects a
        skipped date — so the two **adjacent** daily periods and the single
        boundary they share are the observable consequence of the skipped date's
        period being zero-length.
        """
        shared = datetime(2011, 12, 30, 10, tzinfo=UTC)
        clock = MovableClock(now=shared - timedelta(hours=1))
        subject = harness.open(replace(REPORTING, timezone="Pacific/Apia"), now=clock)

        before = totals_by_period(await subject.spend_totals())
        clock.moved(shared + timedelta(hours=1))
        after = totals_by_period(await subject.spend_totals())

        assert before[SpendPeriod.CALENDAR_DAY].period_end == shared
        assert after[SpendPeriod.CALENDAR_DAY].period_start == shared

    async def test_a_completion_on_a_boundary_belongs_to_the_following_period(
        self, harness: SpendHarness
    ) -> None:
        """The half-open ``[start, end)`` rule, which a before/after pair never tests.

        An implementation comparing ``recorded_at <= period_end`` passes every
        row-on-each-side case above, counts a midnight completion in **both**
        periods, and refuses a call that should be admitted.
        """
        boundary = datetime(2026, 8, 26, tzinfo=UTC)
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).completed(usd("13"), at=boundary)

        clock.moved(boundary - timedelta(hours=1))
        ending = totals_by_period(await subject.spend_totals())
        clock.moved(boundary + timedelta(hours=1))
        following = totals_by_period(await subject.spend_totals())

        assert ending[SpendPeriod.CALENDAR_DAY].period_end == boundary
        assert ending[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
        assert following[SpendPeriod.CALENDAR_DAY].period_start == boundary
        assert following[SpendPeriod.CALENDAR_DAY].accounted == Decimal("13")

    async def test_a_month_whose_end_is_unrepresentable_is_closed_at_the_latest_instant(
        self, harness: SpendHarness
    ) -> None:
        """``Pacific/Kiritimati`` carries a late-9999 boundary into year 10000.

        The period is closed at the latest instant representable in both UTC and
        the zone rather than refused: what is lost is the membership of a handful
        of instants no clock this system accepts can reach.
        """
        clock = MovableClock(now=datetime(9999, 12, 30, 12, tzinfo=UTC))
        subject = harness.open(replace(REPORTING, timezone="Pacific/Kiritimati"), now=clock)

        stated = totals_by_period(await subject.spend_totals())

        month = stated[SpendPeriod.CALENDAR_MONTH]
        assert month.period_end < datetime.max.replace(tzinfo=UTC)
        assert month.period_end + month.end_offset <= datetime.max.replace(tzinfo=UTC)

    async def test_a_month_whose_start_is_unrepresentable_is_opened_at_the_earliest_instant(
        self, harness: SpendHarness
    ) -> None:
        """The **same** rule at the other end, which a late-clamp-only implementation misses.

        At ``0001-01-02T00:00:00Z`` in a positive-offset zone the current month's
        civil start carries a local midnight earlier than the earliest instant
        there is, so an implementation constructing that midnight raises
        ``OverflowError`` where §1 requires a clamped ``start``. The negative-offset
        mirror needs no clamp and returns the ordinary boundary, which is what
        pins the clamp to the case that needs it.
        """
        clock = MovableClock(now=datetime(1, 1, 2, tzinfo=UTC))
        east = harness.open(replace(REPORTING, timezone="Etc/GMT-7"), now=clock)
        west = harness.open(
            replace(REPORTING, timezone="Etc/GMT+7"), now=MovableClock(now=clock.now)
        )

        clamped = totals_by_period(await east.spend_totals())[SpendPeriod.CALENDAR_MONTH]
        ordinary = totals_by_period(await west.spend_totals())[SpendPeriod.CALENDAR_MONTH]

        assert clamped.period_start == datetime.min.replace(tzinfo=UTC)
        assert ordinary.period_start == datetime(1, 1, 1, 7, tzinfo=UTC)

    async def test_the_zone_decides_which_period_a_row_falls_in(
        self, harness: SpendHarness
    ) -> None:
        """``Settings.timezone``'s whole influence is period selection (ADR-0194 §1).

        Identical rows and identical spend settings under two zones put a row on
        opposite sides of the current day's boundary — the zone doing its job and
        not a second spend knob.
        """
        recorded = datetime(2026, 8, 25, 2, tzinfo=UTC)
        reading = datetime(2026, 8, 25, 12, tzinfo=UTC)
        utc_clock = MovableClock(now=reading)
        west_clock = MovableClock(now=reading)
        in_utc = harness.open(REPORTING, now=utc_clock)
        in_west = harness.open(replace(REPORTING, timezone="Etc/GMT+7"), now=west_clock)
        await Rows(in_utc, utc_clock).completed(usd("5"), at=recorded)
        await Rows(in_west, west_clock).completed(usd("5"), at=recorded)
        utc_clock.moved(reading)
        west_clock.moved(reading)

        under_utc = totals_by_period(await in_utc.spend_totals())
        under_west = totals_by_period(await in_west.spend_totals())

        assert under_utc[SpendPeriod.CALENDAR_DAY].accounted == Decimal("5")
        assert under_west[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")

    # --- ADR-0194 §1's countability, at both of its boundaries --------------

    @pytest.mark.parametrize(
        ("amount", "readable"),
        [
            ("1E15", False),
            ("999999999999999.999999999", True),
            ("0.000000001", True),
            ("0.0000000001", False),
            ("1.0000000000", True),
        ],
        ids=["at-the-bound", "below-it", "nine-digits", "a-tenth-digit", "trailing-zeros"],
    )
    async def test_a_declared_amount_is_classified_at_both_bounds(
        self, harness: SpendHarness, amount: str, readable: bool
    ) -> None:
        """The magnitude bound is strict and the scale bound is independent of it.

        Named values rather than "something outside the range", so an
        implementation writing ``<=`` where ADR-0194 §1 says strictly less than
        fails, and so does one that dropped the fractional-digit half. The
        trailing-zeros case is what the predicate's wording exists for: the test is
        on the *value*, so ``Decimal("1.0000000000")`` is countable.
        """
        widest = Decimal("999999999999999.999999999")
        subject = harness.open(replace(BOUNDED, day_ceiling=widest, month_ceiling=widest))

        if readable:
            assert await subject.admit_invocation(estimate=usd(amount))
        else:
            with pytest.raises(SpendUndeterminedError, match=GROUND["amount"]):
                await subject.admit_invocation(estimate=usd(amount))

    @pytest.mark.parametrize(
        ("amount", "readable"),
        [("1E15", False), ("999999999999999.999999999", True), ("0.0000000001", False)],
        ids=["at-the-bound", "below-it", "a-tenth-digit"],
    )
    async def test_a_reported_amount_is_classified_at_both_bounds(
        self, harness: SpendHarness, amount: str, readable: bool
    ) -> None:
        """The other consequence of the same predicate: the period, not the call."""
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        await Rows(subject, clock).completed(usd(amount))

        stated = totals_by_period(await subject.spend_totals())

        expected = Decimal(amount) if readable else None
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == expected

    async def test_a_non_countable_reported_amount_names_the_period_not_the_amount(
        self, harness: SpendHarness
    ) -> None:
        """§4's first and fifth grounds are both available here and only one is right.

        An implementation classifying the row under the *declaration* ground passes
        the totals half above and every isolated ground case, then sends an
        operator looking at a ``ToolCost`` when what they need is to know which
        period cannot be measured and that the month will still be unmeasurable
        tomorrow.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("1E15"))

        with pytest.raises(SpendUndeterminedError, match=GROUND["period"]) as refusal:
            await subject.admit_invocation(estimate=usd("1"))

        stated = str(refusal.value)
        assert stated.index("calendar_day") < stated.index("calendar_month")

    @pytest.mark.parametrize("amount", ["1E15", "0.0000000001"])
    async def test_the_allowance_is_never_substituted_for_an_amount_out_of_range(
        self, harness: SpendHarness, amount: str
    ) -> None:
        """An out-of-range amount is a price somebody *stated* (ADR-0194 §1).

        The allowance stands for a price nobody knows, and substituting a small
        number for a large stated one would defeat both the admission and the
        account — so a configured allowance changes nothing here, in either
        direction.
        """
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, allowance=Decimal("1")), now=clock)
        await Rows(subject, clock).completed(usd(amount))

        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd(amount))
        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted is None

    async def test_an_exotic_zero_is_countable_everywhere_it_is_read(
        self, harness: SpendHarness
    ) -> None:
        """``Decimal("0E-999999999999999999")`` is a zero with an unusable exponent.

        Countable under ADR-0194 §1 — finite, below the bound, needing no
        fractional digit — and carried through the arithmetic to the same answer
        ``Decimal("0")`` would give. An implementation sizing a context from
        ``as_tuple().exponent`` fails this by exhausting memory rather than by
        returning a wrong number, which is ADR-0194 §2's effective-scale clause.
        """
        exotic = "0E-999999999999999999"
        clock = MovableClock()
        subject = harness.open(replace(BOUNDED, day_ceiling=Decimal(exotic)), now=clock)
        await Rows(subject, clock).completed(usd(exotic))

        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("0")
        assert stated[SpendPeriod.CALENDAR_DAY].ceiling == Decimal("0")
        assert await subject.admit_invocation(estimate=usd(exotic))

    async def test_an_exotic_zero_allowance_is_refused_by_the_holder(
        self, harness: SpendHarness
    ) -> None:
        """The allowance must be strictly above zero in **every** spelling of zero.

        Driven as its own case so a lane cannot read the countability obligation
        above as licence to accept it. ADR-0194 §11 puts the ``ConfigurationError``
        a *user* meets on ``Settings``, which is the consumer group's; what the
        holder owes is to refuse the malformed value it is handed, which is the
        disposition this store already takes to every other argument.
        """
        for spelling in ("0", "-0", "0.00", "0E-9", "0E-999999999999999999"):
            with pytest.raises(Exception):  # noqa: B017, PT011 - the class is the holder's
                harness.open(replace(BOUNDED, allowance=Decimal(spelling)))

    async def test_a_non_countable_ceiling_is_refused_by_the_holder(
        self, harness: SpendHarness
    ) -> None:
        """A ceiling the arithmetic cannot read is refused where it is handed over."""
        for ceiling in ("1E15", "0.0000000001", "-1"):
            with pytest.raises(Exception):  # noqa: B017, PT011 - the class is the holder's
                harness.open(replace(BOUNDED, day_ceiling=Decimal(ceiling)))

    # --- ADR-0194 §2's exact arithmetic and one representation --------------

    async def test_a_total_is_stated_at_its_minimal_non_negative_scale(
        self, harness: SpendHarness
    ) -> None:
        """Rows of ``0.1``, ``0.9`` and ``1`` total ``Decimal("2")`` in every order.

        Asserted on ``as_tuple()`` and not on ``==``, which ``Decimal("2.0")``
        satisfies: ADR-0087 §4's relation is indistinguishability, so two spellings
        of one number are two values and only one of them is what a conforming
        implementation states.
        """
        for order in ((0, 1, 2), (2, 1, 0), (1, 0, 2), (2, 0, 1)):
            clock = MovableClock()
            subject = harness.open(REPORTING, now=clock)
            rows = Rows(subject, clock)
            amounts = ("0.1", "0.9", "1")
            for index in order:
                await rows.completed(usd(amounts[index]))

            stated = totals_by_period(await subject.spend_totals())

            accounted = stated[SpendPeriod.CALENDAR_DAY].accounted
            assert accounted is not None
            assert accounted.as_tuple() == (0, (2,), 0)

    async def test_a_total_of_negative_zeros_is_stated_as_zero(self, harness: SpendHarness) -> None:
        """``Decimal("-0")`` is a cost a completion may honestly carry (ADR-0194 §2).

        ``ToolCost`` refuses a negative amount with ``<``, and ``Decimal("-0") < 0``
        is false. An accumulator seeded from the first row rather than from zero
        preserves the sign and fails exactly here, while a suite asserting only
        equality passes it, since ``Decimal("-0") == Decimal("0")``.
        """
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("-0"))
        await rows.completed(usd("-0"))

        stated = totals_by_period(await subject.spend_totals())

        accounted = stated[SpendPeriod.CALENDAR_DAY].accounted
        assert accounted is not None
        assert accounted.as_tuple() == (0, (0,), 0)

    async def test_a_positive_exponent_is_written_out_in_full(self, harness: SpendHarness) -> None:
        """Two rows of ``Decimal("1E+1")`` sum to ``2E+1`` under ``+`` and must state ``20``.

        Driven through aggregation and not only as a hostile construction, because
        the two catch different implementations: one that canonicalised scale and
        sign but left the exponent alone passes every other representation case and
        fails a ``SpendTotal`` outright.
        """
        clock = MovableClock()
        subject = harness.open(REPORTING, now=clock)
        rows = Rows(subject, clock)
        await rows.completed(usd("1E+1"))
        await rows.completed(usd("1E+1"))

        stated = totals_by_period(await subject.spend_totals())

        accounted = stated[SpendPeriod.CALENDAR_DAY].accounted
        assert accounted is not None
        assert accounted.as_tuple() == (0, (2, 0), 0)

    async def test_the_projected_figure_a_refusal_states_is_canonical(
        self, harness: SpendHarness
    ) -> None:
        """The projection reaches the user through the message, so it obeys §2 too.

        An accounted total of ``2`` and a declared estimate of ``1.0`` project
        ``Decimal("3.0")`` under a naive sum where §2 requires ``Decimal("3")``. An
        implementation canonicalising the ledger's total and not the projection
        passes every case above and states the wrong number in the one place a user
        reads it.
        """
        clock = MovableClock()
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("2.5"), month_ceiling=Decimal("2.5")), now=clock
        )
        await Rows(subject, clock).completed(usd("2"))

        with pytest.raises(SpendCeilingError) as refusal:
            await subject.admit_invocation(estimate=usd("1.0"))

        assert "3.0" not in str(refusal.value)
        assert "3" in str(refusal.value)

    async def test_a_declared_negative_zero_projects_as_zero(self, harness: SpendHarness) -> None:
        """The projection's sign obeys §2 as the accounted total's does."""
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("0"), month_ceiling=Decimal("0"))
        )

        assert await subject.admit_invocation(estimate=usd("-0"))

    async def test_an_exact_sum_is_stated_under_a_hostile_ambient_context(
        self, harness: SpendHarness
    ) -> None:
        """The result is what conformance pins, never a precision or a rounding mode.

        Driven in the **admitted** direction, because a suite that drove only
        refusals does not discharge it: an implementation computing in the
        caller's context would round or trap exactly here, where it must admit and
        state an exact figure.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        parts = ("11.111111111", "22.222222222", "33.333333333")
        for part in parts:
            await rows.completed(usd(part))
        hostile = decimal.Context(
            prec=10,
            traps=[decimal.Inexact, decimal.Rounded, decimal.Overflow, decimal.Underflow],
        )

        with decimal.localcontext(hostile):
            stated = totals_by_period(await subject.spend_totals())
            admitted = await subject.admit_invocation(estimate=usd("1"))

        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("66.666666666")
        assert admitted is not None

    async def test_countability_is_decided_without_the_ambient_context(
        self, harness: SpendHarness
    ) -> None:
        """No ``decimal`` exception leaks and no classification moves (ADR-0194 §1)."""
        subject = harness.open()
        hostile = decimal.Context(
            prec=10,
            traps=[decimal.Inexact, decimal.Rounded, decimal.Overflow, decimal.Underflow],
        )

        with decimal.localcontext(hostile):
            with pytest.raises(SpendUndeterminedError, match=GROUND["amount"]):
                await subject.admit_invocation(estimate=usd("0.0000000001"))
            assert await subject.admit_invocation(estimate=usd("1.0000000000"))

    async def test_an_accounted_total_beyond_a_default_context_is_exact(
        self, harness: SpendHarness
    ) -> None:
        """The accumulated operand ADR-0194 §1's predicate does **not** bound.

        §1 governs inputs and not results, so an accounted total over rows nothing
        bounds may honestly exceed ``1E15`` — and beyond ``1E19`` with nine
        fractional digits it needs more significant digits than a default 28-digit
        context carries. An implementation that sized its context from the fifteen
        integer and nine fractional digits §1 bounds a *source* amount to, instead
        of from the accumulator's own ``as_tuple()``, rounds or traps here rather
        than comparing it exactly.

        One fixture, two reads of the same number: the total is stated digit for
        digit, so rounding it is a failure rather than a near miss, and the
        projection over it refuses against a ceiling it plainly exceeds.

        It costs rows in the ten thousands, which is §1's own arithmetic: each row
        is below ``1E15``, so exceeding ``1E19`` takes ten thousand of them. There
        is no cheaper fixture for this property, and it is built once rather than
        twice for that reason.
        """
        widest = "999999999999999.999999999"
        count = 10_001
        clock = MovableClock()
        subject = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("1"), month_ceiling=Decimal("1")), now=clock
        )
        await Rows(subject, clock).bulk(usd(widest), count=count)

        stated = totals_by_period(await subject.spend_totals())

        accounted = stated[SpendPeriod.CALENDAR_DAY].accounted
        assert accounted is not None
        assert accounted.as_tuple() == _times(Decimal(widest), count).as_tuple()
        assert accounted > Decimal("1E19")
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))

    # --- the ways a refusal clears (ADR-0194 §4) ----------------------------

    async def test_a_refusal_is_lifted_by_releasing_the_call_it_counted(
        self, harness: SpendHarness
    ) -> None:
        """The one way a refusal clears with no act outside the mechanism.

        Not a relaxation but the projection ceasing to count a call that is no
        longer in flight, and the message from the first attempt states the
        **projected** figure that crossed rather than only the accounted one — a
        user reading "90 against a ceiling of 100" beside a refusal would have no
        way to see the reservation and the declaration that made 101.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("90"))
        held = await subject.admit_invocation(estimate=usd("10"))

        with pytest.raises(SpendCeilingError) as refusal:
            await subject.admit_invocation(estimate=usd("1"))
        assert "101" in str(refusal.value)

        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("1"))

    async def test_a_refusal_is_lifted_by_the_period_rolling_over(
        self, harness: SpendHarness
    ) -> None:
        """Time, which is the remedy ADR-0194 §8 names beside the allowance."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("100"), at=NOON)

        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))

        clock.moved(datetime(2026, 9, 1, 12, tzinfo=UTC))
        assert await subject.admit_invocation(estimate=usd("1"))

    async def test_a_refusal_is_lifted_by_a_claim_gaining_its_completion(
        self, harness: SpendHarness
    ) -> None:
        """The indeterminacy ends, which ends the refusal §2's rule caused."""
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        claim = await rows.claimed()

        with pytest.raises(SpendUndeterminedError):
            await subject.admit_invocation(estimate=usd("1"))

        await subject.complete_invocation(
            claim_id=claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=usd("1")
        )
        assert await subject.admit_invocation(estimate=usd("1"))

    async def test_a_refusal_is_lifted_when_the_clock_or_the_store_answers(
        self, harness: SpendHarness
    ) -> None:
        """A transient failure is transient, and neither ground is reached from a turn.

        Each of ADR-0194 §4's lifting paths is driven through the suite's own
        fixtures — the configuration, the clock and the rows — and none through a
        tool call, which is §4's point that no route from inside a turn reaches any
        of them.
        """
        clock = MovableClock(failures=1)
        subject = harness.open(now=clock)

        with pytest.raises(SpendUndeterminedError, match=GROUND["clock"]):
            await subject.admit_invocation(estimate=usd("1"))
        assert await subject.admit_invocation(estimate=usd("1"))

        if harness.fail_reads(subject, 1):
            with pytest.raises(SpendUndeterminedError, match=GROUND["store"]):
                await subject.admit_invocation(estimate=usd("1"))
            assert await subject.admit_invocation(estimate=usd("1"))

    async def test_a_refusal_is_lifted_by_raising_the_ceiling(self, harness: SpendHarness) -> None:
        """Configuration is the relief valve, and it lives outside the turn.

        A second holder over the **same** store under a higher ceiling is what a
        user changing their configuration and restarting produces, and it is the
        only shape a suite can drive without reaching into a holder's own state.
        """
        clock = MovableClock()
        subject = harness.open(now=clock, shareable=True)
        await Rows(subject, clock).completed(usd("100"))
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("1"))

        store = harness.store_of(subject)
        if store is None:
            pytest.skip("this implementation holds no store a second holder can open")
        raised = harness.open(
            replace(BOUNDED, day_ceiling=Decimal("200"), month_ceiling=Decimal("2000")),
            now=clock,
            store=store,
        )

        assert await raised.admit_invocation(estimate=usd("1"))

    # --- one instant, and a clock that steps -------------------------------

    async def test_an_admission_selects_both_periods_from_one_instant(
        self, harness: SpendHarness
    ) -> None:
        """A gate reading the clock once **per period** admits a call no instant permits.

        A day ceiling of 100 and a month ceiling of 1000, 999 accounted earlier in
        August, nothing on August 31, 99 on September 1, and an estimate of 2. Read
        wholly at August 31 the month projects 1001 and crosses; read wholly at
        September 1 the day projects 101 and crosses; and **no** instant crosses
        both. So a refusal naming both is as much a failure here as an admission,
        and which one is named is left to the instant the implementation read.

        Every other clock case steps the clock *between* calls, so an
        implementation reading it once per period inside a single admission passes
        all of them; this is the only place the admission half is driven.
        """
        august = datetime(2026, 8, 31, 12, tzinfo=UTC)
        september = datetime(2026, 9, 1, 12, tzinfo=UTC)
        clock = MovableClock()
        subject = harness.open(now=clock)
        rows = Rows(subject, clock)
        await rows.bulk(usd("999"), count=1, per_decision=1)
        clock.moved(september)
        await rows.completed(usd("99"), at=september)
        clock.walk.extend([august, september, august, september])
        clock.now = september

        with pytest.raises(SpendCeilingError) as refusal:
            await subject.admit_invocation(estimate=usd("2"))

        named = str(refusal.value)
        assert ("calendar_day" in named) != ("calendar_month" in named)

    async def test_a_clock_stepped_back_inside_one_period_still_counts_its_rows(
        self, harness: SpendHarness
    ) -> None:
        """§2 counts every row in the calendar interval, not the rows before *now*.

        A ledger filtering at ``recorded_at <= now`` computes zero here and admits,
        while passing every rollover case beside it.
        """
        clock = MovableClock()
        subject = harness.open(now=clock)
        await Rows(subject, clock).completed(usd("90"), at=datetime(2026, 8, 25, 15, tzinfo=UTC))

        clock.moved(datetime(2026, 8, 25, 10, tzinfo=UTC))
        stated = totals_by_period(await subject.spend_totals())
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("90")
        with pytest.raises(SpendCeilingError):
            await subject.admit_invocation(estimate=usd("20"))

    async def test_a_reservation_survives_a_clock_stepped_back_across_a_boundary(
        self, harness: SpendHarness
    ) -> None:
        """No combination of rollover and step admits an outstanding pair that crosses.

        The reservation is counted whichever period is current, so neither
        direction of step can lose it. Asserted of an **outstanding** pair and
        deliberately not of one whose first call has completed and been released:
        rows do not move between periods, so a clock stepped back across a boundary
        selects a period whose rows exclude a completion recorded after the step —
        which ADR-0194 §2 states as a limit the ceiling does not promise, and which
        a suite asserting otherwise would be requiring history to be rewritten.
        """
        late = datetime(2026, 8, 25, 23, 50, tzinfo=UTC)
        clock = MovableClock(now=late)
        subject = harness.open(now=clock)
        held = await subject.admit_invocation(estimate=usd("60"))

        for reading in (datetime(2026, 8, 26, 0, 10, tzinfo=UTC), late):
            clock.moved(reading)
            with pytest.raises(SpendCeilingError):
                await subject.admit_invocation(estimate=usd("50"))

        subject.release_admission(held)
        assert await subject.admit_invocation(estimate=usd("50"))

    # --- the producer obligation §5 declines to put on the model ------------

    @pytest.mark.parametrize(
        ("zone", "reading"),
        [
            ("America/Havana", datetime(2026, 11, 1, 17, tzinfo=UTC)),
            ("America/Santiago", datetime(2026, 9, 6, 17, tzinfo=UTC)),
            ("Pacific/Apia", datetime(2011, 12, 31, 3, tzinfo=UTC)),
            ("America/New_York", datetime(2026, 3, 15, 12, tzinfo=UTC)),
            ("Asia/Manila", datetime(1800, 6, 15, 12, tzinfo=UTC)),
        ],
    )
    async def test_the_producer_states_the_bounds_and_offsets_section_one_computes(
        self, harness: SpendHarness, zone: str, reading: datetime
    ) -> None:
        """The correspondence ADR-0194 §5 declines to put on the model.

        A lane treating this as belt-and-braces beside a model validator has misread
        §5: there is no such validator, by decision, and this is the whole of where the
        correspondence is checked. Both bounds and **both** offsets, the second being
        what a single-offset model would have misrendered on exactly the periods §1's
        rule exists for.
        """
        resolved = ZoneInfo(zone)
        subject = harness.open(
            Configured(currency="USD", timezone=zone), now=MovableClock(now=reading)
        )

        stated = totals_by_period(await subject.spend_totals())

        local = reading.astimezone(resolved).date()
        for period, first, following in (
            (SpendPeriod.CALENDAR_DAY, local, local + timedelta(days=1)),
            (
                SpendPeriod.CALENDAR_MONTH,
                local.replace(day=1),
                date(local.year + (local.month == 12), local.month % 12 + 1, 1),
            ),
        ):
            entry = stated[period]
            assert entry.period_start == _earliest_local(first, resolved)
            assert entry.period_end == _earliest_local(following, resolved)
            assert entry.start_offset == entry.period_start.astimezone(resolved).utcoffset()
            assert entry.end_offset == entry.period_end.astimezone(resolved).utcoffset()

    async def test_a_period_containing_a_transition_states_two_different_offsets(
        self, harness: SpendHarness
    ) -> None:
        """Asserted to **differ**, which is the case a single offset would have lost."""
        subject = harness.open(
            Configured(currency="USD", timezone="America/New_York"),
            now=MovableClock(now=datetime(2026, 3, 15, 12, tzinfo=UTC)),
        )

        month = totals_by_period(await subject.spend_totals())[SpendPeriod.CALENDAR_MONTH]

        assert month.start_offset != month.end_offset
