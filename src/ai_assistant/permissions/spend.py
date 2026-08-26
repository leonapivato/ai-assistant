"""The arithmetic and the calendar a spend ceiling is decided on (ADR-0194).

Everything here is **pure and synchronous**: the configuration a holder was
handed, the period the invoker's current instant falls in, what one declared or
reported ``ToolCost`` contributes, the exact sum of a period's rows, and the
reservations a gate holds between an admission and its release. The store reads
live in :mod:`ai_assistant.permissions.audit`, which is the object ADR-0194 §5
makes the sole runtime holder.

**Not shared with the canonical fake.** ``ai_assistant.testing`` carries its own
implementation of every rule below, exactly as it carries its own copy of the
trail's revalidation. A fake importing this module would make the shared
conformance suite exercise one implementation twice, which is the one thing that
suite exists not to do.

**Two kinds of operand, sized differently** (ADR-0194 §2). A *source* amount — a
configured ceiling, the allowance, a declared amount, a reported one — is bounded
by §1 and needs at most fifteen integer and nine fractional digits. An
*accumulated* operand — the running total part-way through a sum, and the
accounted total where it enters the projection — is bounded by nothing, so its
context is sized from its **own** representation. Sized from §1's bound instead,
an implementation rounds or traps on a valid large accumulator rather than
comparing it exactly.
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import CostBasis, SpendPeriod, ToolCost

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


#: ADR-0194 §1's strict magnitude bound on a **source** amount.
AMOUNT_CEILING: Final = Decimal("1E15")

#: ADR-0194 §1's scale bound on a **source** amount, in fractional digits *of
#: value*: ``Decimal("1.0000000000")`` is countable because its value is ``1``.
AMOUNT_SCALE: Final = 9

#: Slack digits added to every sized context, so that an exactly-sized precision
#: is never the thing a carry runs out of.
_SIZING_SLACK: Final = 3

#: The `decimal` signals a sized context arms. They are a **backstop against a
#: context that was not sized from its operands** and not a reachable state on
#: well-formed input: a failure to size raises rather than answering quietly.
_TRAPS: Final = (
    decimal.Inexact,
    decimal.Rounded,
    decimal.Overflow,
    decimal.Underflow,
    decimal.Subnormal,
)

#: ADR-0194 §1's shape rule for a currency: exactly three uppercase ASCII
#: letters, ISO-4217's alphabetic form, neither normalised nor checked against
#: the live register. ``ToolCost.currency``'s rule and not a second one.
_CURRENCY_LENGTH: Final = 3

#: The twelfth month, so that the month rollover reads as a calendar fact.
_DECEMBER: Final = 12

#: The first year ``datetime`` can express, so an unreachable boundary can be told
#: apart from an unreachable one at the other end.
_FIRST_YEAR: Final = 1

#: How many times a bound is nudged inward before its rendering is given up on.
_RENDERABLE_ATTEMPTS: Final = 4


class SpendArithmeticError(Exception):
    """A sized computation trapped — ADR-0194 §4's sixth ground.

    Deliberately not an ``AssistantError``: it never leaves this module's
    callers, which translate it into ``SpendUndeterminedError`` on the admission
    side and into an indeterminate period on the read side. It exists so those
    two callers can tell a trapped sum from every other failure without catching
    ``decimal``'s own hierarchy at each site.
    """


# --- amounts -----------------------------------------------------------------


def effective_exponent(amount: Decimal) -> int:
    """Return the scale ``amount``'s *value* needs, ignoring trailing zeros.

    ADR-0194 §1 makes countability a test on the number rather than on its
    representation, and §2 carries that into the arithmetic: a zero coefficient
    contributes nothing whatever its exponent, and trailing zeros below the last
    significant digit do not enlarge a context. Without it
    ``Decimal("0E-999999999999999999")`` — countable, numerically zero — would
    demand a precision no machine can allocate.

    Args:
        amount: A finite ``Decimal``.

    Returns:
        The exponent of the value's last significant digit, or ``0`` for a zero.

    Raises:
        ValueError: If ``amount`` is not finite.
    """
    sign, digits, exponent = amount.as_tuple()
    del sign
    if not isinstance(exponent, int):
        msg = f"a non-finite Decimal has no effective exponent, got {amount!r}"
        raise ValueError(msg)
    if not any(digits):
        return 0
    trailing = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing += 1
    return exponent + trailing


def is_countable(amount: Decimal) -> bool:
    """Report whether ``amount`` is countable under ADR-0194 §1.

    Finite; absolute value strictly below :data:`AMOUNT_CEILING`; and a value
    expressible with at most :data:`AMOUNT_SCALE` fractional digits. Everything
    it reads comes from the amount's own ``as_tuple()``, so no ambient
    ``decimal`` precision, rounding mode or trap changes the answer or makes it
    raise.

    Args:
        amount: The amount to classify.

    Returns:
        Whether this mechanism may read it.
    """
    if not amount.is_finite():
        return False
    if effective_exponent(amount) < -AMOUNT_SCALE:
        return False
    # ``copy_abs`` and not ``abs``: the latter is an arithmetic operation that
    # rounds to the ambient precision, so under a hostile context it traps on
    # exactly the values this predicate exists to classify (ADR-0194 §1's
    # context-independence clause). Comparison itself is exact and context-free.
    return amount.copy_abs() < AMOUNT_CEILING


def reduced(amount: Decimal) -> Decimal:
    """Return ``amount`` at the scale its value needs, for sizing and addition.

    ADR-0194 §2's effective-scale clause. A zero of any exponent becomes
    ``Decimal(0)``; ``Decimal("1.500")`` becomes ``Decimal("1.5")``; a positive
    exponent is left alone, because the canonical form of a *result* is applied
    once at the end rather than to every operand.

    Args:
        amount: A finite ``Decimal``.

    Returns:
        The same value, carrying no trailing zero below its last significant
        digit.
    """
    sign, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):
        msg = f"a non-finite Decimal cannot be reduced, got {amount!r}"
        raise ValueError(msg)
    if not any(digits):
        return Decimal(0)
    kept = list(digits)
    while exponent < 0 and kept[-1] == 0:
        kept.pop()
        exponent += 1
    return Decimal((sign, tuple(kept), exponent))


def canonical_total(amount: Decimal) -> Decimal:
    """Return ``amount`` in ADR-0194 §2's **one** representation of a total.

    The exact value at its minimal non-negative scale, never a positive exponent,
    and never a negative sign — so ``Decimal("2.0")``, ``Decimal("2E+1")`` and
    ``Decimal("-0")`` become ``Decimal("2")``, ``Decimal("20")`` and
    ``Decimal("0")``. Computed from ``as_tuple()`` and never through
    ``normalize``, whose answer depends on the ambient context and which spells a
    large integer exponentially — the spelling §2 forbids.

    Args:
        amount: A finite ``Decimal``, the exact result of a sum.

    Returns:
        The one spelling every conforming implementation states.

    Raises:
        ValueError: If ``amount`` is not finite.
    """
    if not amount.is_finite():
        msg = f"a total must be finite, got {amount!r}"
        raise ValueError(msg)
    sign, digits, exponent = amount.as_tuple()
    assert isinstance(exponent, int)  # noqa: S101 - finite, checked above
    if not any(digits):
        return Decimal("0")
    kept = list(digits)
    while exponent < 0 and kept[-1] == 0:
        kept.pop()
        exponent += 1
    while exponent > 0:
        kept.append(0)
        exponent -= 1
    return Decimal((sign, tuple(kept), exponent))


def _context_for(left: Decimal, right: Decimal) -> decimal.Context:
    """Return a context in which ``left + right`` is exact, sized from both.

    Sized from the operands' **own** representations rather than from ADR-0194
    §1's bound, because only one of the two kinds of operand is bounded by it:
    an accounted total is an accumulated value that may honestly exceed
    ``1E15``, and a context sized from §1's fifteen-and-nine would round or trap
    on it.
    """
    integer_digits = 1
    fractional_digits = 0
    for operand in (left, right):
        sign, digits, exponent = operand.as_tuple()
        del sign
        assert isinstance(exponent, int)  # noqa: S101 - callers pass finite values
        integer_digits = max(integer_digits, exponent + len(digits))
        fractional_digits = max(fractional_digits, -exponent)
    precision = integer_digits + fractional_digits + _SIZING_SLACK
    return decimal.Context(
        prec=precision,
        Emax=integer_digits + _SIZING_SLACK,
        Emin=-(fractional_digits + _SIZING_SLACK),
        traps=list(_TRAPS),
    )


def exact_sum(amounts: Iterable[Decimal]) -> Decimal:
    """Return the mathematically exact sum of ``amounts``, in canonical form.

    Every addition runs in a context sized from its own two operands, with
    ADR-0194 §2's five signals trapped, so a failure to size raises rather than
    answering quietly. The accumulator is seeded with ``Decimal("0")`` and the
    result is canonicalised, which is what makes a period whose rows are all
    ``Decimal("-0")`` total ``Decimal("0")`` rather than ``Decimal("-0")``:
    those are two spellings of one total on the wire, which §2 forbids.

    Args:
        amounts: Finite amounts, in any order.

    Returns:
        The exact sum, at its minimal non-negative scale.

    Raises:
        SpendArithmeticError: If any addition trapped, which is a context this
            module failed to size rather than a property of the input.
    """
    total = Decimal("0")
    try:
        for amount in amounts:
            operand = reduced(amount)
            total = _context_for(total, operand).add(total, operand)
        return canonical_total(total)
    except (decimal.DecimalException, ValueError) as exc:
        msg = f"the exact sum could not be computed: {exc}"
        raise SpendArithmeticError(msg) from exc


def exact_projection(accounted: Decimal, contributions: Sequence[Decimal]) -> Decimal:
    """Return the projected total: an accounted total plus every contribution.

    Separate from :func:`exact_sum` only in what it is *called*: ADR-0194 §2
    requires the projection to carry the same one representation the accounted
    total does, because the projection reaches the user through
    ``SpendCeilingError``'s message and a naive ``Decimal("2") + Decimal("1.0")``
    states ``Decimal("3.0")`` where §2 requires ``Decimal("3")``.

    Args:
        accounted: The period's accounted total, already canonical.
        contributions: The declared amounts of every outstanding reservation and
            of the call under admission.

    Returns:
        The exact projection, at its minimal non-negative scale.

    Raises:
        SpendArithmeticError: If any addition trapped.
    """
    return exact_sum([accounted, *contributions])


# --- configuration -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpendConfiguration:
    """The five values ADR-0194 §5 has the composition root read and inject.

    **Explicit constructor values, never a ``Settings`` read** (ADR-0194 §11):
    ``app/composition.py`` is the sole reader of the four spend settings and of
    ``Settings.timezone``, and hands the holder what it read. This class is what
    it hands over, validated once so a holder never carries a configuration its
    own arithmetic cannot use.

    The checks below are the store's ordinary refusal of a malformed caller and
    not a second implementation of §1's load rule: the ``ConfigurationError`` a
    user meets names a ``Settings`` field and is raised where that field is
    validated.

    Attributes:
        currency: The reporting currency, or ``None``. Set alone it configures a
            currency under which totals are computed and readable and refuses
            nothing.
        day_ceiling: The ``CALENDAR_DAY`` ceiling, or ``None`` for unbounded.
        month_ceiling: The ``CALENDAR_MONTH`` ceiling, or ``None`` for unbounded.
        allowance: What an ``UNKNOWN``-priced call is accounted at, or ``None``.
            Strictly greater than zero: the allowance stands for a price nobody
            knows, and a zero would be the silent zero §2 refuses.
        zone: The IANA zone the calendar periods are computed in — the user's one
            answer to "what day is it", read from ``Settings.timezone``.
    """

    currency: str | None = None
    day_ceiling: Decimal | None = None
    month_ceiling: Decimal | None = None
    allowance: Decimal | None = None
    zone: str = "UTC"

    def __post_init__(self) -> None:
        """Refuse a configuration ADR-0194 §1 does not admit."""
        _check_currency(self.currency)
        for name, ceiling in (
            ("day_ceiling", self.day_ceiling),
            ("month_ceiling", self.month_ceiling),
        ):
            _check_ceiling(name, ceiling, self.currency)
        _check_allowance(self.allowance, self.currency)
        _resolve_zone(self.zone)

    @property
    def bounded(self) -> bool:
        """Whether any ceiling is configured at all.

        Where this is false ADR-0194 §3's short-circuit applies unconditionally:
        the admission returns before it reads the clock, reads the store or
        performs any arithmetic, and cannot refuse.
        """
        return self.day_ceiling is not None or self.month_ceiling is not None

    def ceiling_for(self, period: SpendPeriod) -> Decimal | None:
        """Return the ceiling configured for ``period``, or ``None``."""
        return self.day_ceiling if period is SpendPeriod.CALENDAR_DAY else self.month_ceiling

    def resolved_zone(self) -> ZoneInfo:
        """Return the zone, resolved. Validated at construction, so this cannot fail."""
        return _resolve_zone(self.zone)


def _check_currency(currency: str | None) -> None:
    """Require ADR-0194 §1's shape, or nothing at all."""
    if currency is None:
        return
    if len(currency) != _CURRENCY_LENGTH or not (
        currency.isascii() and currency.isupper() and currency.isalpha()
    ):
        msg = f"world_spend_currency must be three uppercase ASCII letters, got {currency!r}"
        raise ConfigurationError(msg)


def _check_ceiling(name: str, ceiling: Decimal | None, currency: str | None) -> None:
    """Require a finite, non-negative, countable ceiling, and a currency to state it in."""
    if ceiling is None:
        return
    if currency is None:
        msg = f"{name} needs world_spend_currency, which is not set"
        raise ConfigurationError(msg)
    if not ceiling.is_finite():
        msg = f"{name} must be finite, got {ceiling!r}"
        raise ConfigurationError(msg)
    if ceiling < 0:
        msg = f"{name} must not be negative, got {ceiling!r}"
        raise ConfigurationError(msg)
    if not is_countable(ceiling):
        msg = (
            f"{name} must be countable — below {AMOUNT_CEILING} and to at most "
            f"{AMOUNT_SCALE} fractional digits, got {ceiling!r}"
        )
        raise ConfigurationError(msg)


def _check_allowance(allowance: Decimal | None, currency: str | None) -> None:
    """Require a finite, countable allowance strictly greater than zero.

    Zero is refused in every spelling ``Decimal`` admits for it —
    ``Decimal("0")``, ``Decimal("-0")``, ``Decimal("0.00")``, ``Decimal("0E-9")``
    — which ``> 0`` decides for all four at once, and so is any negative value: a
    negative allowance would let an ``UNKNOWN`` estimate *lower* a projection and
    admit a call already at its ceiling.
    """
    if allowance is None:
        return
    if currency is None:
        msg = "world_spend_unknown_allowance needs world_spend_currency, which is not set"
        raise ConfigurationError(msg)
    if not allowance.is_finite():
        msg = f"world_spend_unknown_allowance must be finite, got {allowance!r}"
        raise ConfigurationError(msg)
    if not allowance > 0:
        msg = f"world_spend_unknown_allowance must be greater than zero, got {allowance!r}"
        raise ConfigurationError(msg)
    if not is_countable(allowance):
        msg = (
            f"world_spend_unknown_allowance must be countable — below {AMOUNT_CEILING} "
            f"and to at most {AMOUNT_SCALE} fractional digits, got {allowance!r}"
        )
        raise ConfigurationError(msg)


def _resolve_zone(zone: str) -> ZoneInfo:
    """Resolve an IANA zone name, refusing an unknown one as configuration."""
    try:
        return ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        msg = f"unknown timezone {zone!r}"
        raise ConfigurationError(msg) from exc


# --- what one cost contributes ------------------------------------------------


class DeclaredFault(StrEnum):
    """Why a *declared* cost could not be reduced to a number (ADR-0194 §4).

    The first two of §4's six grounds, in that section's order: they are facts
    about the call and need no I/O, so they are decided before anything is read.
    The values are the message text each ground states.
    """

    NOT_COUNTABLE = "the declared cost amount is not countable"
    NO_NUMBER = "the declared cost has no number in the configured currency"


def declared_contribution(cost: ToolCost, config: SpendConfiguration) -> Decimal | DeclaredFault:
    """Return what ``cost`` adds to a projection, or which ground refuses the call.

    ADR-0194 §2: a ``FREE`` basis contributes zero; a ``PER_CALL`` basis in the
    configured currency contributes its amount; an ``UNKNOWN`` basis, and a cost
    denominated in any other currency, contribute the allowance where one is
    configured and otherwise have no number at all.

    **The countability test comes first**, which is §4's own order and is what
    makes a foreign-currency cost whose amount is also out of range name the
    amount rather than the currency. An out-of-range amount is a price somebody
    *stated*, so the allowance never reaches it: substituting a small number for a
    large stated one would defeat both the admission and the account.

    Args:
        cost: The pinned declaration on the definition this call's decision pins.
        config: The holder's configuration.

    Returns:
        The amount to add, or the ground that refuses.
    """
    if cost.amount is not None and not is_countable(cost.amount):
        return DeclaredFault.NOT_COUNTABLE
    if cost.basis is CostBasis.FREE:
        return Decimal("0")
    if cost.basis is CostBasis.PER_CALL and cost.currency == config.currency:
        assert cost.amount is not None  # noqa: S101 - ToolCost's own invariant
        return cost.amount
    return config.allowance if config.allowance is not None else DeclaredFault.NO_NUMBER


def reported_contribution(cost: ToolCost, config: SpendConfiguration) -> Decimal | None:
    """Return what a completion row's reported ``cost`` adds to an accounted total.

    The same classification as :func:`declared_contribution` with the other
    consequence: where the cost has no number this mechanism may add, the
    period's accounted total is **indeterminate** rather than the call being
    refused (ADR-0194 §2). A reported amount that is not countable is §1's case
    and reaches the same absence — and never the allowance.

    Args:
        cost: The figure the tool reported, as ADR-0192's completion row carries
            it.
        config: The holder's configuration.

    Returns:
        The amount to add, or ``None`` where this row makes its period
        indeterminate.
    """
    contribution = declared_contribution(cost, config)
    return None if isinstance(contribution, DeclaredFault) else contribution


# --- the calendar --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodBounds:
    """One calendar period, resolved to instants and the offsets at its ends.

    Attributes:
        period: Which period this is.
        start: The inclusive start instant, in UTC.
        end: The exclusive end instant, in UTC. Equal to :attr:`start` on a
            zero-length period, which ADR-0194 §1's skipped-civil-date case
            produces.
        start_offset: The UTC offset in force at :attr:`start`.
        end_offset: The UTC offset in force at :attr:`end`.
    """

    period: SpendPeriod
    start: datetime
    end: datetime
    start_offset: timedelta
    end_offset: timedelta

    def contains(self, instant: datetime) -> bool:
        """Report whether ``instant`` falls in this half-open ``[start, end)`` period.

        The half-open rule is what puts a completion recorded **exactly on** a
        shared boundary in the *following* period and not in the one that ends
        there. An implementation comparing ``<= end`` counts a midnight completion
        in both and refuses a call that should be admitted.
        """
        return self.start <= instant < self.end


def period_bounds(
    instant: datetime, config: SpendConfiguration, period: SpendPeriod
) -> PeriodBounds:
    """Return the period of ``period``'s kind that contains ``instant``.

    ADR-0194 §1's rule, whole: the boundary for a civil date ``D`` in the
    configured zone is the **earliest instant whose local civil date is greater
    than or equal to ``D``**, a period's ``start`` is that boundary for its own
    first date, and its ``end`` is that boundary for the first date of the
    following period.

    **That one selection covers every transition a zone may carry**, with no case
    distinguished here. Where ``D``'s civil midnight is repeated across a backward
    transition it selects the earlier of the two instants; where midnight does not
    exist across a forward transition it selects the transition instant itself;
    and where the whole civil date is skipped — ``Pacific/Apia`` has no instant
    whose local date is 2011-12-30 — it selects the first instant of the next date
    that exists, which makes that date's period zero-length. ``fold`` is set
    **explicitly**, because accepting whatever a default supplies is what §1
    forbids: ``fold=0`` is what selects the earlier instant of a repeated midnight
    and the pre-transition offset of a missing one, and both are the rule's own
    answer.

    **Both ends are clamped** to what is representable as a ``UtcInstant`` *and*
    as a civil time in the zone. A positive-offset zone reaches the lower clamp
    first — at ``0001-01-02T00:00:00Z`` in ``Etc/GMT-7`` the current month begins
    on a civil date whose local midnight is earlier than the earliest instant
    there is — and a positive-offset zone reaches the upper one first, which
    ``Pacific/Kiritimati`` does by carrying a late-9999 boundary into year 10000.
    Nothing is refused on either ground; what is lost is the membership of a
    handful of instants no clock this system accepts can reach.

    Args:
        instant: The invoker's current instant, in UTC.
        config: The holder's configuration, for its zone.
        period: Which period to compute.

    Returns:
        The resolved bounds and the offsets in force at them.
    """
    zone = config.resolved_zone()
    earliest, latest = _representable_range(zone)
    anchor = min(max(instant, earliest), latest)
    local_date = anchor.astimezone(zone).date()
    first = local_date if period is SpendPeriod.CALENDAR_DAY else local_date.replace(day=1)
    following = _following_date(first, period)
    start = _clamped_boundary(first, zone, earliest, latest)
    end = latest if following is None else _clamped_boundary(following, zone, earliest, latest)
    end = max(end, start)
    start, start_offset = _renderable(start, zone, earliest, latest)
    end, end_offset = _renderable(end, zone, earliest, latest)
    if end < start:
        end, end_offset = start, start_offset
    return PeriodBounds(
        period=period, start=start, end=end, start_offset=start_offset, end_offset=end_offset
    )


def _following_date(first: date, period: SpendPeriod) -> date | None:
    """Return the first civil date of the period after ``first``, or ``None``.

    ``None`` where that date is beyond what ``datetime.date`` can express — the
    day after 9999-12-31, or the month after 9999-12 — which is the upper clamp's
    case reached one step earlier than the boundary computation would reach it.
    """
    try:
        if period is SpendPeriod.CALENDAR_DAY:
            return first + timedelta(days=1)
        if first.month == _DECEMBER:
            return date(first.year + 1, 1, 1)
        return date(first.year, first.month + 1, 1)
    except OverflowError, ValueError:
        return None


def _boundary(day: date, zone: ZoneInfo) -> datetime | None:
    """Return ADR-0194 §1's boundary instant for ``day``, or ``None`` if unreachable."""
    try:
        civil = datetime(day.year, day.month, day.day, tzinfo=zone, fold=0)
        return civil.astimezone(UTC)
    except OverflowError, ValueError, OSError:
        return None


def _clamped_boundary(day: date, zone: ZoneInfo, earliest: datetime, latest: datetime) -> datetime:
    """Return ``day``'s boundary, clamped into the representable range."""
    raw = _boundary(day, zone)
    if raw is None:
        return earliest if day.year <= _FIRST_YEAR else latest
    return min(max(raw, earliest), latest)


def _representable_range(zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the earliest and latest instants representable in UTC *and* in ``zone``.

    A west-of-UTC zone binds at the early end, because the civil time at
    ``datetime.min`` there is earlier than ``datetime.min``; an east-of-UTC zone
    binds at the late end. The offsets are probed two days inside each extreme,
    which is comfortably clear of both while being close enough that no zone's
    offset differs there — the tz database carries no transitions at either end
    of its range.
    """
    floor = datetime.min.replace(tzinfo=UTC)
    peak = datetime.max.replace(tzinfo=UTC)
    low_offset = (floor + timedelta(days=2)).astimezone(zone).utcoffset() or timedelta(0)
    high_offset = (peak - timedelta(days=2)).astimezone(zone).utcoffset() or timedelta(0)
    earliest = floor + max(timedelta(0), -low_offset)
    latest = peak - max(timedelta(0), high_offset)
    return earliest, latest


def _renderable(
    bound: datetime, zone: ZoneInfo, earliest: datetime, latest: datetime
) -> tuple[datetime, timedelta]:
    """Return ``bound`` and its own offset, nudged until the pair is renderable.

    ``SpendTotal`` requires each bound **plus its own offset** to land inside
    ``datetime``'s range, because that is the addition the required renderer
    performs. The clamp above sizes the range from an offset probed at the
    extreme; a zone whose offset at the clamped bound differs from the probe
    would leave the pair one step outside, so this closes the loop on the value
    actually in hand rather than on the probe.
    """
    for _ in range(_RENDERABLE_ATTEMPTS):
        offset = bound.astimezone(zone).utcoffset() or timedelta(0)
        try:
            bound + offset
        except OverflowError, ValueError:
            bound = min(max(bound - offset, earliest), latest)
            continue
        return bound, offset
    msg = f"no representable rendering for a period boundary in {zone.key!r}"
    raise SpendArithmeticError(msg)


# --- reservations --------------------------------------------------------------


@dataclass(eq=False)
class Reservations:
    """The in-memory reservations one holder is carrying (ADR-0194 §3).

    **Never a row, never durable, never a ``PermissionDecision``.** The set is
    discarded when the process restarts, which is the one way an unreleased
    reservation ever ends; the accounted total is rebuilt from ADR-0192's rows
    and loses nothing with it.

    **Keyed by an internal ordinal and not by the handle text**, because a
    release resolves the handle to a *reservation* when it is called and only the
    moment of application is deferred. An implementation recording the raw value
    and matching it when the queue drains loses a live reservation: a release of a
    value the holder has never delivered, queued while an admission is paused,
    then meets that admission minting the same value and retires a reservation
    taken **after** the release that supposedly names it.
    """

    #: Every value this holder has **ever** delivered as a handle. Lifetime scope
    #: and not the outstanding set: a value re-minted after its first reservation
    #: was released makes a stale release — which must be a no-op — drop the *live*
    #: reservation now carrying it, after which a later admission projects a total
    #: omitting a call already in flight.
    delivered: set[str] = field(default_factory=set)

    _amounts: dict[int, Decimal] = field(default_factory=dict)
    _keys: dict[str, int] = field(default_factory=dict)
    _pending: list[int] = field(default_factory=list)
    _next_key: int = 0

    def apply_pending(self) -> None:
        """Apply every recorded release. Called at the **start** of a critical section.

        A release takes effect here and never inside an admission already running:
        an implementation that let one land between an admission's row snapshot and
        its comparison admits a call it must refuse, because the reservation is the
        conservative stand-in for a completion the snapshot may not yet show.
        """
        while self._pending:
            self._amounts.pop(self._pending.pop(0), None)

    def outstanding(self) -> list[Decimal]:
        """Return the declared amount of every reservation still standing."""
        return list(self._amounts.values())

    def reserve(self, amount: Decimal) -> int:
        """Record a reservation of ``amount`` and return its internal key."""
        self._next_key += 1
        self._amounts[self._next_key] = amount
        return self._next_key

    def discard(self, key: int) -> None:
        """Remove a reservation whose handle will never be delivered.

        ADR-0194 §3's no-stranded-reservation rule: where ``admit_invocation``
        has recorded a reservation and does not deliver its handle — a
        ``CancelledError`` between the two is the reachable case — it removes the
        reservation before the exception leaves the member.
        """
        self._amounts.pop(key, None)

    def bind(self, key: int, handle: str) -> None:
        """Attach the delivered ``handle`` to the reservation ``key`` names."""
        self._keys[handle] = key
        self.delivered.add(handle)

    def release(self, handle: str) -> None:
        """Resolve ``handle`` to a reservation now, and queue that reservation.

        A handle identifying no reservation outstanding at this moment — an
        unknown value, or one already retired — is discarded here and nothing is
        recorded. Touches no store, performs no I/O, and cannot block.
        """
        key = self._keys.pop(handle, None)
        if key is not None:
            self._pending.append(key)
