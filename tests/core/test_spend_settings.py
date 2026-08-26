"""The four spend settings ADR-0194 §1 adds, and what each refuses at load.

§11 assigns these fixtures to the **consumer group**, because it is that group
that lands the four fields: no admission fixture reaches them, since a valid gate
fixture supplies a currency without being asked. What is driven here is therefore
the load rule and only the load rule — the dependency between the amounts and the
currency, the numeric floors, the countability predicate at both of its
boundaries, and the currency's own shape.

**The refusal a user meets is a ``ConfigurationError`` naming the field**, which
is why the cases that go through the environment go through
:func:`~ai_assistant.core.config.load_settings`: that is the function an operator
actually runs into, and the wrapper is what turns pydantic's ``ValidationError``
into the class ``CLAUDE.md`` says configuration failures wear. The direct
constructions beside them assert the same rules on values the environment cannot
spell — a ``Decimal`` object rather than its string form.

Refs: ADR-0194 §1, §2, §11.
"""

from __future__ import annotations

import decimal
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings, load_settings
from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterator

#: ``Settings`` reads every field a construction here does not name from the
#: environment, so an ambient ``ASSISTANT_*`` is what these assertions would
#: otherwise measure (#1368).
pytestmark = pytest.mark.usefixtures("hermetic_assistant_env")

#: The three amount-valued settings, which share one countability rule and differ
#: only in their floor.
_AMOUNTS: Final = (
    "world_spend_month_ceiling",
    "world_spend_day_ceiling",
    "world_spend_unknown_allowance",
)

#: The two ceilings, which admit zero. The allowance does not.
_CEILINGS: Final = ("world_spend_month_ceiling", "world_spend_day_ceiling")


def _configured(**overrides: object) -> Settings:
    """Build a ``Settings`` with a reporting currency and the given overrides."""
    return Settings(world_spend_currency="USD", **overrides)  # type: ignore[arg-type]


# --- the defaults, and what "unset" means (§1) --------------------------------


def test_all_four_default_to_unset() -> None:
    """Unset means unbounded, and no default amount is minted (ADR-0194 §1)."""
    settings = Settings()
    assert settings.world_spend_currency is None
    assert settings.world_spend_month_ceiling is None
    assert settings.world_spend_day_ceiling is None
    assert settings.world_spend_unknown_allowance is None


def test_the_mechanism_adds_exactly_four_fields_and_no_fifth() -> None:
    """§1 fixes the count: "no lane adds a fifth"."""
    named = {field for field in Settings.model_fields if field.startswith("world_spend")}
    assert named == {
        "world_spend_currency",
        "world_spend_month_ceiling",
        "world_spend_day_ceiling",
        "world_spend_unknown_allowance",
    }


# --- the dependency on a currency (§1) ----------------------------------------


@pytest.mark.parametrize("field", _AMOUNTS)
def test_an_amount_with_no_currency_is_refused_and_the_message_names_it(field: str) -> None:
    """A configured ceiling that does not bind is the failure §11 lands these to stop.

    Without this, ``world_spend_day_ceiling=Decimal("10")`` loads beside no
    currency and silently caps nothing.
    """
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: Decimal("10")})  # type: ignore[arg-type]


def test_a_currency_may_be_set_alone_and_configures_a_reporting_currency() -> None:
    """§1: set alone it computes totals, states them, and refuses nothing."""
    settings = Settings(world_spend_currency="USD")
    assert settings.world_spend_currency == "USD"
    assert settings.world_spend_month_ceiling is None
    assert settings.world_spend_day_ceiling is None


def test_a_ceiling_with_no_currency_reaches_the_operator_as_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The class a user meets is ``ConfigurationError``, not ``ValidationError``."""
    monkeypatch.setenv("ASSISTANT_WORLD_SPEND_DAY_CEILING", "10")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


# --- the numeric floors (§1) --------------------------------------------------


@pytest.mark.parametrize("field", _CEILINGS)
def test_a_negative_ceiling_is_refused(field: str) -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        _configured(**{field: Decimal("-1")})


def test_a_negative_allowance_is_refused() -> None:
    """The one direction the mechanism must never move in (§11).

    A negative allowance would let an ``UNKNOWN`` estimate *lower* a projection and
    admit a call already at its ceiling.
    """
    with pytest.raises(ValidationError, match="must be greater than zero"):
        _configured(world_spend_unknown_allowance=Decimal("-1"))


@pytest.mark.parametrize("spelling", ["0", "-0", "0.00", "0E-9", "0E-999999999999999999"])
def test_a_zero_allowance_is_refused_in_every_spelling_decimal_admits(spelling: str) -> None:
    """§1 requires the allowance strictly greater than zero, in every spelling.

    ``0E-999999999999999999`` is *countable* under §1 and is refused here for an
    entirely different reason, which is why it is driven beside the others: a lane
    cannot read the countability obligation as licence to accept it (§11).
    """
    with pytest.raises(ValidationError, match="must be greater than zero"):
        _configured(world_spend_unknown_allowance=Decimal(spelling))


@pytest.mark.parametrize("spelling", ["0", "-0", "0.00", "0E-9"])
@pytest.mark.parametrize("field", _CEILINGS)
def test_a_zero_ceiling_loads_because_zero_is_a_ceiling_that_binds(
    field: str, spelling: str
) -> None:
    """§11's zero-ceiling clause starts here: zero is configuration, not absence."""
    settings = _configured(**{field: Decimal(spelling)})
    assert getattr(settings, field) == Decimal("0")


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", _AMOUNTS)
def test_a_non_finite_amount_is_refused(field: str, value: str) -> None:
    """``Decimal`` admits ``Infinity`` and ``NaN``; neither survives a running total.

    ``NaN`` is the worse of the two, because every comparison against it is false
    rather than answering — a ceiling that refuses nothing while looking configured.
    """
    with pytest.raises(ValidationError, match=field):
        _configured(**{field: Decimal(value)})


# --- countability, at both of its boundaries (§1, §11) ------------------------


@pytest.mark.parametrize("field", _AMOUNTS)
def test_the_magnitude_bound_is_strict_at_the_number_itself(field: str) -> None:
    """§11 pins the bound by naming the value rather than asking for one outside it."""
    with pytest.raises(ValidationError, match="must be countable"):
        _configured(**{field: Decimal("1E15")})


@pytest.mark.parametrize("field", _AMOUNTS)
def test_the_largest_countable_value_below_that_bound_loads(field: str) -> None:
    settings = _configured(**{field: Decimal("999999999999999.999999999")})
    assert getattr(settings, field) == Decimal("999999999999999.999999999")


@pytest.mark.parametrize("field", _AMOUNTS)
def test_nine_fractional_digits_are_countable_and_a_tenth_is_not(field: str) -> None:
    """The scale bound is pinned independently of magnitude (§11).

    An implementation cannot satisfy it with an over-magnitude fixture, and one
    that dropped the fractional-digit half of the predicate passes every other
    countability case here.
    """
    settings = _configured(**{field: Decimal("0.000000001")})
    assert getattr(settings, field) == Decimal("0.000000001")
    with pytest.raises(ValidationError, match="must be countable"):
        _configured(**{field: Decimal("0.0000000001")})


@pytest.mark.parametrize("field", _AMOUNTS)
def test_countability_is_a_test_on_the_value_and_not_on_the_representation(field: str) -> None:
    """§1: ``Decimal("1.0000000000")`` is countable because its value is ``1``."""
    settings = _configured(**{field: Decimal("1.0000000000")})
    assert getattr(settings, field).as_tuple() == Decimal("1.0000000000").as_tuple()


@pytest.mark.parametrize("field", _CEILINGS)
def test_an_exotic_zero_is_countable_as_a_ceiling(field: str) -> None:
    """``Decimal("0E-999999999999999999")`` is finite, below the bound, and zero-valued.

    §1's context-independence clause is what makes classifying it cheap: nothing
    here sizes anything from the raw exponent.
    """
    settings = _configured(**{field: Decimal("0E-999999999999999999")})
    assert getattr(settings, field) == Decimal("0")


def test_countability_does_not_consult_the_ambient_decimal_context(
    hostile_decimal_context: None,
) -> None:
    """§1's predicate reads ``as_tuple()`` and no ``getcontext()``.

    Under a precision of ten with traps armed, an implementation reaching for
    ``abs`` or ``quantize`` traps on exactly the values this predicate classifies.
    """
    del hostile_decimal_context
    settings = _configured(world_spend_month_ceiling=Decimal("999999999999999.999999999"))
    assert settings.world_spend_month_ceiling == Decimal("999999999999999.999999999")
    with pytest.raises(ValidationError, match="must be countable"):
        _configured(world_spend_month_ceiling=Decimal("1E15"))


@pytest.fixture
def hostile_decimal_context() -> Iterator[None]:
    """Run one test under a precision of ten with every ADR-0194 §2 trap armed."""
    previous = decimal.getcontext()
    hostile = decimal.Context(
        prec=10,
        traps=[
            decimal.Inexact,
            decimal.Rounded,
            decimal.Overflow,
            decimal.Underflow,
            decimal.Subnormal,
        ],
    )
    decimal.setcontext(hostile)
    try:
        yield
    finally:
        decimal.setcontext(previous)


# --- the currency's own shape (§1) --------------------------------------------


@pytest.mark.parametrize("value", ["", "usd", "US", "USDD", "US$", "ÜSD"])
def test_a_currency_off_iso_4217s_alphabetic_shape_is_refused(value: str) -> None:
    """Shape only — three uppercase ASCII letters, ``ToolCost.currency``'s own rule.

    ``ASSISTANT_WORLD_SPEND_CURRENCY=`` sets the variable to the empty string
    rather than to nothing, which is why the blank is refused rather than read as
    unconfigured.
    """
    with pytest.raises(ValidationError, match="three uppercase ASCII letters"):
        Settings(world_spend_currency=value)


def test_a_well_formed_currency_is_neither_normalised_nor_checked_against_the_register() -> None:
    """§1 validates shape and nothing else, so an unassigned code loads."""
    assert Settings(world_spend_currency="USD").world_spend_currency == "USD"
    assert Settings(world_spend_currency="ZZZ").world_spend_currency == "ZZZ"


# --- what §1 explicitly does *not* refuse -------------------------------------


def test_a_day_ceiling_above_the_month_ceiling_is_accepted() -> None:
    """§1: nothing refuses a configuration on that ground; the month simply binds.

    A settings validator quietly imposing ``day <= month`` passes every dependency
    and crossing fixture and rejects a configuration this ADR calls valid.
    """
    settings = _configured(
        world_spend_day_ceiling=Decimal("100"), world_spend_month_ceiling=Decimal("10")
    )
    assert settings.world_spend_day_ceiling == Decimal("100")
    assert settings.world_spend_month_ceiling == Decimal("10")


def test_the_environment_spells_the_whole_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The four arrive from the environment as the ``Decimal`` values they name."""
    monkeypatch.setenv("ASSISTANT_WORLD_SPEND_CURRENCY", "USD")
    monkeypatch.setenv("ASSISTANT_WORLD_SPEND_MONTH_CEILING", "100.00")
    monkeypatch.setenv("ASSISTANT_WORLD_SPEND_DAY_CEILING", "10.00")
    monkeypatch.setenv("ASSISTANT_WORLD_SPEND_UNKNOWN_ALLOWANCE", "0.01")
    settings = load_settings()
    assert settings.world_spend_currency == "USD"
    # The scale the operator wrote is carried, not normalised (ADR-0087 §4).
    assert settings.world_spend_month_ceiling is not None
    assert settings.world_spend_month_ceiling.as_tuple() == Decimal("100.00").as_tuple()
    assert settings.world_spend_day_ceiling == Decimal("10")
    assert settings.world_spend_unknown_allowance == Decimal("0.01")
