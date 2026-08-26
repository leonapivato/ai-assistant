"""The three spend types' own invariants (ADR-0194 §5).

Every one of them is **intrinsic** in ADR-0016 §2's sense — decided from the
value alone, needing no zone database, the same answer for every consumer — which
is the property the zone name §5 declines to carry could not have had. So they
are driven as hostile constructions here rather than through a producer: a
producer case passes against an implementation that simply never builds the
offending value, and what a model refuses is a fact about the *type*.

**What is deliberately not here.** The correspondence of a returned
``SpendTotal``'s bounds to ADR-0194 §1's rule, which §5 puts on the *producer*
rather than on a validator — checked in ``tests/permissions/test_sqlite_spend.py``
and ``tests/permissions/test_fake_spend.py``, which is the only place that can
compare against the rule instead of against a second implementation of it.
"""

from __future__ import annotations

import decimal
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import SpendAdmissionHandle, SpendPeriod, SpendTotal

#: A period every case that is not about the calendar can build on.
_DAY = {
    "period": SpendPeriod.CALENDAR_DAY,
    "period_start": datetime(2026, 8, 25, tzinfo=UTC),
    "period_end": datetime(2026, 8, 26, tzinfo=UTC),
    "start_offset": timedelta(0),
    "end_offset": timedelta(0),
}


def total(**overrides: Any) -> SpendTotal:
    """Build a ``SpendTotal``, overriding whichever field a case is about."""
    return SpendTotal(**{**_DAY, **overrides})


def test_spend_period_has_exactly_two_members_in_the_fixed_order() -> None:
    """ADR-0194 §5: two members, no ordering semantics, and the order is contract.

    The declaration order is what every surface states them in — the tuple
    ``spend_totals`` returns, a refusal naming two periods, the CLI's rendering —
    so that two conforming implementations state the same facts in the same
    sequence.
    """
    assert list(SpendPeriod) == [SpendPeriod.CALENDAR_DAY, SpendPeriod.CALENDAR_MONTH]


def test_a_handle_is_an_identifier_and_not_a_bare_string() -> None:
    """``Identifier`` refuses the blank handle and strips, so two spellings are one.

    That is what makes ADR-0194 §3's distinctness rule testable on the *validated*
    value: a holder checking uniqueness before construction would hold two
    reservations under one key.
    """
    assert SpendAdmissionHandle(handle="  h  ").handle == "h"
    with pytest.raises(ValidationError):
        SpendAdmissionHandle(handle="   ")
    with pytest.raises(ValidationError):
        SpendAdmissionHandle(handle="h", extra="no")  # type: ignore[call-arg]


@pytest.mark.parametrize("code", ["", "usd", "US", "USDD", "USÐ"])
def test_a_currency_that_is_not_iso_4217_shaped_raises(code: str) -> None:
    """``EncodableText`` is the base the field layers on and is not the whole rule.

    It admits every one of these, and a ``SpendTotal`` carrying one would state a
    currency ADR-0194 §1 refuses as configuration — which a renderer would then
    print.
    """
    with pytest.raises(ValidationError):
        total(currency=code)


def test_a_well_shaped_currency_is_carried_unnormalised() -> None:
    """Shape only: neither normalised nor checked against the live register."""
    assert total(currency="USD").currency == "USD"


@pytest.mark.parametrize(
    "offset",
    [timedelta(hours=24), timedelta(hours=-24), timedelta(hours=25)],
    ids=["exactly-a-day", "minus-a-day", "beyond"],
)
def test_an_offset_at_or_beyond_a_day_raises(offset: timedelta) -> None:
    """The ±24-hour bound is strict, and it is the whole of the range rule."""
    with pytest.raises(ValidationError):
        total(start_offset=offset)
    with pytest.raises(ValidationError):
        total(end_offset=offset)


@pytest.mark.parametrize(
    "offset",
    [timedelta(hours=-15, minutes=-56, seconds=-8), timedelta(hours=15, minutes=13, seconds=42)],
    ids=["asia-manila", "america-metlakatla"],
)
def test_an_offset_carrying_seconds_constructs_unrounded(offset: timedelta) -> None:
    """``core/clock.py`` names these two as the widest the tz database carries.

    A whole-minute rule passes every refusing case above and makes a
    ``SpendTotal`` unable to state the offset actually in force for a reading
    ``checked_clock`` accepts.
    """
    assert total(start_offset=offset).start_offset == offset


def test_reversed_bounds_raise_and_equal_bounds_construct() -> None:
    """A zero-length period is a value ADR-0194 §1's skipped-date case produces.

    A validator that admitted the reversed pair, or refused the equal one, passes
    every other case in this module.
    """
    with pytest.raises(ValidationError):
        total(period_start=datetime(2026, 8, 27, tzinfo=UTC))
    same = datetime(2026, 8, 25, tzinfo=UTC)
    assert total(period_start=same, period_end=same).period_end == same


def test_a_bound_plus_its_own_offset_must_be_representable() -> None:
    """The invariant that makes the required rendering total (ADR-0194 §5).

    A renderer performs exactly these two additions, so without this the range and
    ordering rules admit a value it cannot print — and the offsets and the clamps
    reach the two ends separately and never together.
    """
    floor = datetime.min.replace(tzinfo=UTC)
    peak = datetime.max.replace(tzinfo=UTC)
    with pytest.raises(ValidationError):
        total(period_start=floor, period_end=peak, start_offset=timedelta(hours=-1))
    with pytest.raises(ValidationError):
        total(period_start=floor, period_end=peak, end_offset=timedelta(hours=1))
    assert total(
        period_start=floor,
        period_end=peak,
        start_offset=timedelta(hours=1),
        end_offset=timedelta(hours=-1),
    )


@pytest.mark.parametrize("absent", ["ceiling", "accounted"])
def test_an_amount_without_a_currency_raises(absent: str) -> None:
    """``currency`` is what discriminates ``accounted``'s two absences.

    An amount standing without one would state a figure in no currency at all, and
    would leave the discriminator unable to tell "none configured" from
    "indeterminate".
    """
    with pytest.raises(ValidationError):
        total(**{absent: Decimal("1")})


@pytest.mark.parametrize(
    ("ceiling", "admitted"),
    [
        ("0", True),
        ("-0", True),
        ("2", True),
        ("20", True),
        ("2.0", True),
        ("0.000000001", True),
        ("999999999999999.999999999", True),
        ("1E15", False),
        ("0.0000000001", False),
        ("-1", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_a_ceiling_is_exactly_what_section_one_admits(ceiling: str, admitted: bool) -> None:
    """Finite, at least zero, and countable — and **nothing else** (ADR-0194 §5).

    A ceiling is an *input*: it is the value the user configured and nothing
    computes it, so §2's one-representation rule — which governs results — does
    not reach it, and ``Decimal("2.0")`` is carried as written. ``Decimal("-0")``
    is admitted for the same reason and on the clause's own words: it is finite,
    it is not less than zero, and it is countable. Applying one numeric validator
    to this field and to ``accounted`` is what this pair of cases exists to stop.
    """
    if admitted:
        assert total(currency="USD", ceiling=Decimal(ceiling)).ceiling == Decimal(ceiling)
    else:
        with pytest.raises(ValidationError):
            total(currency="USD", ceiling=Decimal(ceiling))


@pytest.mark.parametrize(
    ("accounted", "admitted"),
    [
        ("2", True),
        ("20", True),
        ("0", True),
        ("0.000000001", True),
        ("10000000000000000000", True),
        ("2.0", False),
        ("2E+1", False),
        ("-0", False),
        ("-1", False),
        ("0.0000000001", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_an_accounted_total_carries_the_one_representation(accounted: str, admitted: bool) -> None:
    """A computed total has exactly one spelling, and it is **not** bounded in magnitude.

    A model accepting a second spelling would accept a value this mechanism cannot
    produce and would put bytes on the wire no conforming implementation states;
    one refusing a total above ``1E15`` would refuse a value §1's predicate never
    governed, since that predicate is over inputs. ``Decimal("2E+0")`` is
    deliberately not a case: it and ``Decimal("2")`` are ``(0, (2,), 0)`` in
    ``Decimal``'s own representation, so no validator can tell them apart.
    """
    if admitted:
        assert total(currency="USD", accounted=Decimal(accounted)).accounted == Decimal(accounted)
    else:
        with pytest.raises(ValidationError):
            total(currency="USD", accounted=Decimal(accounted))


def test_no_validator_consults_a_zone_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Driven with **no zone database reachable at all** (ADR-0194 §5).

    §5 shapes these fields so that acceptance and rendering never depend on the
    consumer's installed ``tzdata``; this is what stops a later lane
    reintroducing a lookup, since a validator that consulted one would pass every
    other case in this module.
    """
    monkeypatch.setattr("zoneinfo.TZPATH", ())
    monkeypatch.setitem(sys.modules, "tzdata", None)

    assert total(currency="USD", accounted=Decimal("1"), ceiling=Decimal("2"))
    with pytest.raises(ValidationError):
        total(start_offset=timedelta(hours=24))
    with pytest.raises(ValidationError):
        total(currency="usd")


def test_every_invariant_is_decided_without_the_ambient_decimal_context() -> None:
    """A hostile context changes no classification and leaks no ``decimal`` exception.

    ADR-0194 §1's context-independence rule reaches the model as well as the
    arithmetic: a validator reaching for ``abs`` or ``quantize`` would trap here on
    exactly the values it exists to classify.
    """
    hostile = decimal.Context(
        prec=10, traps=[decimal.Inexact, decimal.Rounded, decimal.Overflow, decimal.Underflow]
    )

    with decimal.localcontext(hostile):
        assert total(currency="USD", ceiling=Decimal("999999999999999.999999999"))
        assert total(currency="USD", accounted=Decimal("10000000000000000000"))
        with pytest.raises(ValidationError):
            total(currency="USD", ceiling=Decimal("1E15"))


def test_a_spend_total_is_frozen_and_forbids_extra_fields() -> None:
    """The exact schema ADR-0194 §5 fixes, and no field beyond it."""
    stated = total(currency="USD", accounted=Decimal("1"))

    with pytest.raises(ValidationError):
        total(currency="USD", zone="Europe/Rome")
    with pytest.raises(ValidationError):
        stated.accounted = Decimal("2")
