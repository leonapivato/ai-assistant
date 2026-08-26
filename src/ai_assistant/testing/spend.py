"""The canonical fake's own reading of ADR-0194's spend rules.

**Deliberately a second implementation.** ``ai_assistant.permissions.spend``
carries the production one and nothing here imports it: a fake that borrowed the
subsystem's arithmetic would make the shared conformance suite exercise one
implementation twice, which is the single thing that suite exists not to do. It
is the same choice ``FakeAuditTrail`` already makes about the trail's
revalidation, for the same reason.

Everything here is pure and synchronous. :class:`SpendBooks` holds the
configuration a fake was handed and the reservations it is carrying; the module
functions beside it answer ADR-0194 §1's calendar and §2's arithmetic.
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import CostBasis, SpendAdmissionHandle, SpendPeriod, ToolCost

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

#: ADR-0194 §1's two bounds on a **source** amount: strictly below ``1E15``, and a
#: value expressible with at most nine fractional digits.
_TOO_LARGE: Final = Decimal("1E15")
_FINEST: Final = -9

#: Every `decimal` signal a sized context arms, so a context this module failed to
#: size raises rather than quietly rounding a total the user reads.
_ARMED: Final = [
    decimal.Inexact,
    decimal.Rounded,
    decimal.Overflow,
    decimal.Underflow,
    decimal.Subnormal,
]

_CURRENCY_LETTERS: Final = 3
_LAST_MONTH: Final = 12
_YEAR_ONE: Final = 1
_NUDGES: Final = 4


class SpendTrapError(Exception):
    """A sized computation trapped — ADR-0194 §4's sixth ground.

    Not an ``AssistantError``: the fake translates it into
    ``SpendUndeterminedError`` under an admission and into an indeterminate
    period under a read, exactly as the durable store does.
    """


class Unpriced(StrEnum):
    """Why a cost has no number this mechanism may use (ADR-0194 §4, grounds 1-2).

    The values are the message text each ground states, and the order is §4's:
    the magnitude of a stated price is decided before the currency it was stated
    in, so a foreign cost that is *also* out of range names the amount.
    """

    NOT_COUNTABLE = "the declared cost amount is not countable"
    NO_NUMBER = "the declared cost has no number in the configured currency"


def value_scale(amount: Decimal) -> int:
    """Return the exponent of ``amount``'s last significant digit, zeros aside.

    ADR-0194 §1 tests the number and not its representation, and §2 carries that
    into the arithmetic: ``Decimal("0E-999999999999999999")`` is a zero, and an
    implementation sizing a precision from its raw exponent would ask for one no
    machine can allocate.

    Args:
        amount: A finite ``Decimal``.

    Returns:
        The value's own exponent, or ``0`` for any spelling of zero.
    """
    _, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):
        msg = f"a non-finite Decimal has no scale, got {amount!r}"
        raise ValueError(msg)
    significant = len(digits)
    while significant and digits[significant - 1] == 0:
        significant -= 1
    return 0 if significant == 0 else exponent + (len(digits) - significant)


def countable(amount: Decimal) -> bool:
    """Report whether ADR-0194 §1 lets this mechanism read ``amount``.

    Args:
        amount: The amount to classify.

    Returns:
        ``True`` where it is finite, below ``1E15`` in absolute value, and needs
        at most nine fractional digits.
    """
    # ``copy_abs`` and not ``abs``: the latter rounds to the ambient precision
    # and traps under a hostile context, which ADR-0194 §1 forbids a
    # classification from depending on. Comparison is exact and context-free.
    return amount.is_finite() and value_scale(amount) >= _FINEST and amount.copy_abs() < _TOO_LARGE


def canonical(amount: Decimal) -> Decimal:
    """Return ADR-0194 §2's one representation of a computed total.

    Minimal non-negative scale, no positive exponent, no negative sign — so two
    conforming implementations summing the same rows in any order state the same
    bytes on the wire.

    Args:
        amount: A finite exact sum.

    Returns:
        That value, spelled the one way.
    """
    if not amount.is_finite():
        msg = f"a total must be finite, got {amount!r}"
        raise ValueError(msg)
    _, digits, exponent = amount.as_tuple()
    assert isinstance(exponent, int)  # noqa: S101 - finite, checked above
    coefficient = int("".join(str(digit) for digit in digits))
    if coefficient == 0:
        return Decimal("0")
    if exponent > 0:
        return Decimal(coefficient * 10**exponent)
    scale = -exponent
    while scale > 0 and coefficient % 10 == 0:
        coefficient //= 10
        scale -= 1
    return Decimal((0, tuple(int(d) for d in str(coefficient)), -scale))


def _sized(*operands: Decimal) -> decimal.Context:
    """Return a context in which adding ``operands`` cannot round or overflow.

    Sized from what each operand's own representation needs, never from §1's
    bound: an accounted total is an accumulated value §1 does not govern, and a
    context sized from fifteen-and-nine would trap on a perfectly valid one.
    """
    above = 1
    below = 0
    for operand in operands:
        _, digits, exponent = operand.as_tuple()
        assert isinstance(exponent, int)  # noqa: S101 - callers pass finite values
        above = max(above, exponent + len(digits))
        below = max(below, -exponent)
    return decimal.Context(prec=above + below + 4, Emax=above + 4, Emin=-(below + 4), traps=_ARMED)


def _shrunk(amount: Decimal) -> Decimal:
    """Return ``amount`` carrying no trailing zero below its last significant digit."""
    scale = value_scale(amount)
    _, digits, exponent = amount.as_tuple()
    assert isinstance(exponent, int)  # noqa: S101 - callers pass finite values
    if not any(digits):
        return Decimal(0)
    dropped = scale - exponent
    return Decimal((amount.as_tuple().sign, digits[: len(digits) - dropped], scale))


def add_exactly(amounts: Iterable[Decimal]) -> Decimal:
    """Return the mathematically exact, canonical sum of ``amounts``.

    Each addition runs in its own sized context with ADR-0194 §2's five signals
    armed. The accumulator starts at ``Decimal("0")`` and the answer is
    canonicalised, so a period whose rows are every one of them ``Decimal("-0")``
    totals ``Decimal("0")`` — two spellings of one total on the wire is what §2
    forbids.

    Args:
        amounts: Finite amounts, in any order.

    Returns:
        The exact sum at its minimal non-negative scale.

    Raises:
        SpendTrapError: If any addition trapped.
    """
    running = Decimal("0")
    try:
        for amount in amounts:
            operand = _shrunk(amount)
            running = _sized(running, operand).add(running, operand)
        return canonical(running)
    except (decimal.DecimalException, ValueError) as exc:
        msg = f"the sum trapped: {exc}"
        raise SpendTrapError(msg) from exc


@dataclass(frozen=True, slots=True)
class Bounds:
    """One calendar period, resolved to instants and the offsets at its ends."""

    period: SpendPeriod
    start: datetime
    end: datetime
    start_offset: timedelta
    end_offset: timedelta

    def holds(self, instant: datetime) -> bool:
        """Report whether ``instant`` falls in this half-open ``[start, end)`` period."""
        return self.start <= instant < self.end


def _zone_of(name: str) -> ZoneInfo:
    """Resolve an IANA zone name, refusing an unknown one as configuration."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        msg = f"unknown timezone {name!r}"
        raise ConfigurationError(msg) from exc


def _span(zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the instants beyond which no value is representable in UTC and ``zone``."""
    floor = datetime.min.replace(tzinfo=UTC)
    peak = datetime.max.replace(tzinfo=UTC)
    early = (floor + timedelta(days=2)).astimezone(zone).utcoffset() or timedelta(0)
    late = (peak - timedelta(days=2)).astimezone(zone).utcoffset() or timedelta(0)
    return floor - min(early, timedelta(0)), peak - max(late, timedelta(0))


def _edge(day: date, zone: ZoneInfo, span: tuple[datetime, datetime]) -> datetime:
    """Return ADR-0194 §1's boundary instant for civil date ``day``, clamped.

    The boundary is the earliest instant whose local civil date is at least
    ``day``. ``fold`` is stated rather than defaulted, which is what selects the
    earlier instant of a repeated midnight and the transition instant itself where
    midnight does not exist; where the whole civil date is skipped it lands on the
    first instant of the next date that exists, making ``day``'s own period
    zero-length.
    """
    low, high = span
    try:
        civil = datetime(day.year, day.month, day.day, tzinfo=zone, fold=0)
        # Converted to UTC before anything is compared to it or added to it:
        # arithmetic on a zone-aware value moves its *wall clock*, so a
        # representability check made on one asks about a different instant.
        return min(max(civil.astimezone(UTC), low), high)
    except OverflowError, ValueError, OSError:
        return low if day.year <= _YEAR_ONE else high


def _step(first: date, period: SpendPeriod) -> date | None:
    """Return the first civil date after ``first``'s period, or ``None`` beyond range."""
    try:
        if period is SpendPeriod.CALENDAR_DAY:
            return first + timedelta(days=1)
        return (
            date(first.year + 1, 1, 1)
            if first.month == _LAST_MONTH
            else date(first.year, first.month + 1, 1)
        )
    except OverflowError, ValueError:
        return None


def _with_offset(
    bound: datetime, zone: ZoneInfo, span: tuple[datetime, datetime]
) -> tuple[datetime, timedelta]:
    """Return ``bound`` and its own offset, nudged until their sum is representable.

    ``SpendTotal`` requires each bound plus its own offset to land inside
    ``datetime``'s range, because that is the addition the CLI performs.
    """
    low, high = span
    for _ in range(_NUDGES):
        offset = bound.astimezone(zone).utcoffset() or timedelta(0)
        try:
            bound + offset
        except OverflowError, ValueError:
            bound = min(max(bound - offset, low), high)
            continue
        return bound, offset
    msg = f"no representable rendering for a boundary in {zone.key!r}"
    raise SpendTrapError(msg)


@dataclass(eq=False)
class SpendBooks:
    """One fake's spend configuration and the reservations it is carrying.

    The reservations are keyed by an internal ordinal rather than by the handle
    text, because ADR-0194 §3 resolves a release to a *reservation* when
    ``release_admission`` is called and defers only its application. Handles are
    remembered for the holder's whole lifetime and not merely while outstanding: a
    re-minted retired value would let a stale release drop a live reservation.

    Attributes:
        currency: The reporting currency, or ``None``.
        day_ceiling: The ``CALENDAR_DAY`` ceiling, or ``None``.
        month_ceiling: The ``CALENDAR_MONTH`` ceiling, or ``None``.
        allowance: What an unpriced call is accounted at, or ``None``.
        timezone: The IANA zone the calendar periods are computed in.
    """

    currency: str | None = None
    day_ceiling: Decimal | None = None
    month_ceiling: Decimal | None = None
    allowance: Decimal | None = None
    timezone: str = "UTC"

    _held: dict[int, Decimal] = field(default_factory=dict, init=False)
    _named: dict[str, int] = field(default_factory=dict, init=False)
    _queued: list[int] = field(default_factory=list, init=False)
    _seen: set[str] = field(default_factory=set, init=False)
    _ordinal: int = field(default=0, init=False)
    _nonce: str = field(default_factory=lambda: uuid4().hex, init=False)

    def __post_init__(self) -> None:
        """Refuse a configuration ADR-0194 §1 does not admit."""
        if self.currency is not None and (
            len(self.currency) != _CURRENCY_LETTERS
            or not (self.currency.isascii() and self.currency.isupper() and self.currency.isalpha())
        ):
            msg = (
                f"world_spend_currency must be three uppercase ASCII letters, got {self.currency!r}"
            )
            raise ConfigurationError(msg)
        for name, ceiling in (
            ("world_spend_day_ceiling", self.day_ceiling),
            ("world_spend_month_ceiling", self.month_ceiling),
        ):
            if ceiling is None:
                continue
            self._needs_currency(name)
            if not ceiling.is_finite() or ceiling < 0 or not countable(ceiling):
                msg = f"{name} must be a countable amount of at least zero, got {ceiling!r}"
                raise ConfigurationError(msg)
        if self.allowance is not None:
            self._needs_currency("world_spend_unknown_allowance")
            if (
                not self.allowance.is_finite()
                or not self.allowance > 0
                or not countable(self.allowance)
            ):
                msg = (
                    "world_spend_unknown_allowance must be a countable amount greater than "
                    f"zero, got {self.allowance!r}"
                )
                raise ConfigurationError(msg)
        _zone_of(self.timezone)

    def _needs_currency(self, field_name: str) -> None:
        """Refuse an amount configured with no currency to state it in."""
        if self.currency is None:
            msg = f"{field_name} needs world_spend_currency, which is not set"
            raise ConfigurationError(msg)

    @property
    def bounded(self) -> bool:
        """Whether any ceiling is configured, which is what turns the gate on."""
        return not (self.day_ceiling is None and self.month_ceiling is None)

    def ceiling(self, period: SpendPeriod) -> Decimal | None:
        """Return the ceiling configured for ``period``, or ``None``."""
        return self.day_ceiling if period is SpendPeriod.CALENDAR_DAY else self.month_ceiling

    # --- the calendar ---------------------------------------------------

    def periods(self, instant: datetime) -> tuple[Bounds, ...]:
        """Return both periods containing ``instant``, from that one reading."""
        zone = _zone_of(self.timezone)
        span = _span(zone)
        local = min(max(instant, span[0]), span[1]).astimezone(zone).date()
        resolved: list[Bounds] = []
        for period in SpendPeriod:
            first = local if period is SpendPeriod.CALENDAR_DAY else local.replace(day=1)
            after = _step(first, period)
            opened = _edge(first, zone, span)
            closed = span[1] if after is None else _edge(after, zone, span)
            opened, start_offset = _with_offset(opened, zone, span)
            closed, end_offset = _with_offset(max(closed, opened), zone, span)
            if closed < opened:
                closed, end_offset = opened, start_offset
            resolved.append(
                Bounds(
                    period=period,
                    start=opened,
                    end=closed,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )
        return tuple(resolved)

    # --- what one cost contributes ---------------------------------------

    def declared(self, cost: ToolCost) -> Decimal | Unpriced:
        """Return what ``cost`` adds to a projection, or the ground that refuses it.

        The magnitude test comes first, which is ADR-0194 §4's own order: an
        out-of-range amount is a price somebody *stated*, and the allowance — which
        stands for a price nobody knows — never reaches it.
        """
        if cost.amount is not None and not countable(cost.amount):
            return Unpriced.NOT_COUNTABLE
        if cost.basis is CostBasis.FREE:
            return Decimal("0")
        if cost.basis is CostBasis.PER_CALL and cost.currency == self.currency:
            assert cost.amount is not None  # noqa: S101 - ToolCost's own invariant
            return cost.amount
        return Unpriced.NO_NUMBER if self.allowance is None else self.allowance

    def reported(self, cost: ToolCost) -> Decimal | None:
        """Return what a completion's reported ``cost`` adds, or ``None`` if unmeasurable."""
        contribution = self.declared(cost)
        return None if isinstance(contribution, Unpriced) else contribution

    # --- reservations -----------------------------------------------------

    def settle(self) -> None:
        """Apply every recorded release; called at the start of a critical section."""
        while self._queued:
            self._held.pop(self._queued.pop(0), None)

    def standing(self) -> list[Decimal]:
        """Return the declared amount of every reservation still outstanding."""
        return list(self._held.values())

    def hold(self, amount: Decimal) -> int:
        """Record a reservation of ``amount`` and return its internal key."""
        self._ordinal += 1
        self._held[self._ordinal] = amount
        return self._ordinal

    def drop(self, key: int) -> None:
        """Remove a reservation whose handle will never be delivered."""
        self._held.pop(key, None)

    def name(self, key: int, handle: str) -> None:
        """Attach a delivered handle to the reservation ``key`` names."""
        self._named[handle] = key

    def retire(self, handle: str) -> None:
        """Resolve ``handle`` to a reservation now and queue that reservation."""
        key = self._named.pop(handle, None)
        if key is not None:
            self._queued.append(key)

    def mint(self, factory: Callable[[], object]) -> SpendAdmissionHandle:
        """Return a handle no value this holder has ever delivered equals.

        The factory supplies opacity and nothing else: a candidate the type
        refuses, one already delivered, and a factory raising an ``Exception`` are
        each replaced by a value generated here, and none of the three costs the
        call. A ``CancelledError`` propagates, which is why only ``Exception`` is
        caught.
        """
        drawn: SpendAdmissionHandle | None = None
        try:
            drawn = SpendAdmissionHandle.model_validate({"handle": factory()})
        except Exception:
            drawn = None
        if drawn is None or drawn.handle in self._seen:
            drawn = self._grown()
        self._seen.add(drawn.handle)
        return drawn

    def _grown(self) -> SpendAdmissionHandle:
        """Return this holder's own next handle, distinct by construction."""
        while True:
            self._ordinal += 1
            grown = f"{self._nonce}.{self._ordinal}"
            if grown not in self._seen:
                return SpendAdmissionHandle(handle=grown)


def measurable(
    bounds: Bounds, rows: Iterable[tuple[datetime, ToolCost | None, bool]], books: SpendBooks
) -> Sequence[Decimal] | None:
    """Return each contribution in ``bounds``, or ``None`` where it cannot be told.

    ``rows`` are ``(recorded_at, incurred_cost, completed)`` triples: a claim
    carries no cost, and its ``completed`` flag is what tells an *open* claim —
    which states that an act may have happened and does not state what it cost —
    from one whose completion is simply recorded elsewhere.
    """
    contributions: list[Decimal] = []
    for recorded_at, cost, completed in rows:
        if not bounds.holds(recorded_at):
            continue
        if cost is None:
            if not completed:
                return None
            continue
        contribution = books.reported(cost)
        if contribution is None:
            return None
        contributions.append(contribution)
    return contributions
