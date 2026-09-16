"""The simulated booking provider's configuration, refused at the read (ADR-0273 §1, §5).

ADR-0273 §10's **arms 2 and 12**: *"``Settings`` refuses a partial configuration, one arm
naming the refusal"*, and *"a configured amount or currency outside the readers' accepted
domains is refused when the configuration is read, one arm per refused shape; **and the
§2 record bound likewise**, one arm each for ``0``, a negative, a boolean, a non-integer
and a value outside the accepted range, each asserting that the configuration is refused
and **no provider is built**"*.

**Why the refusal has to be here and not at the first quote.** ADR-0267 §4's mint and
ADR-0271 §2's charge reading each *"raise nothing"* by design: a configuration carrying a
JSON float, a negative amount, ``"NaN"`` or a malformed currency would start a
deployment, pass every arm on its own fixtures, and then silently yield **no quote and no
charge** at the moment the walkthrough needed one. §5 says so in terms — *"a bad
configuration has no other place to be caught"*.

**And it is not a boolean flag** (§1). There is no ``booking_enabled`` field: a flag
beside an incomplete configuration makes *enabled but unusable* a representable state,
which is the half-configured provider ADR-0260 §11 refused for the forecaster.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The connection, the endpoint, the window, the price, the charge and the bound —
#: ADR-0273 §1's whole configuration, from which each case removes or replaces one.
_WHOLE: Final[Mapping[str, object]] = {
    "booking_connection": "conn-0001",
    "booking_endpoint": "https://bookings.example.invalid",
    "booking_available_from": date(2026, 10, 1),
    "booking_available_to": date(2026, 10, 7),
    "booking_price_amount": "120.00",
    "booking_price_currency": "EUR",
    "booking_billed_amount": "140.00",
    "booking_billed_currency": "USD",
    "booking_retained_records": 2,
}


def _settings(**overrides: object) -> Settings:
    """Load settings with the whole booking configuration, one field replaced."""
    return Settings(**{**_WHOLE, **overrides})  # type: ignore[arg-type]  # a case supplies a refused shape


# --------------------------------------------------------------------------- #
# arm 1 (here as its Settings half): absent by default
# --------------------------------------------------------------------------- #


def test_a_default_settings_configures_no_booking_provider() -> None:
    """Every ``booking_*`` field defaults to absent (ADR-0273 §1).

    The composition root's branch reads exactly these, so a default deployment builds
    no provider object at all — asserted over the settings here and over the built
    registry and seam in ``tests/tools/test_booking_registration.py``.
    """
    settings = Settings()

    assert settings.booking_connection is None
    assert settings.booking_endpoint is None
    assert settings.booking_available_from is None
    assert settings.booking_available_to is None
    assert settings.booking_price_amount is None
    assert settings.booking_price_currency is None
    assert settings.booking_billed_amount is None
    assert settings.booking_billed_currency is None
    assert settings.booking_retained_records is None
    assert settings.booking_indeterminate_date is None


def test_no_boolean_flag_enables_the_provider() -> None:
    """There is no ``booking_enabled`` field, and §1 rules one out by name.

    *"A boolean flag beside an incomplete configuration is not an implementation of
    this clause"*: it makes *enabled but unusable* a representable state. Asserted over
    the model's own fields rather than by reading the source, so a lane that added one
    would fail this rather than merely contradict a comment.
    """
    assert "booking_enabled" not in Settings.model_fields
    flags = [
        name
        for name, field in Settings.model_fields.items()
        if name.startswith("booking_") and field.annotation in {bool, bool | None}
    ]
    assert flags == []


# --------------------------------------------------------------------------- #
# arm 2: half-configured is refused, and the refusal names what is missing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("omitted", sorted(_WHOLE))
def test_a_half_configured_provider_is_refused(omitted: str) -> None:
    """Every one of the nine, removed on its own, is a refusal (ADR-0273 §1).

    Parametrised over all nine rather than over a representative: §1's clause is that
    *"a deployment supplying **some but not all** is refused"*, and a validator that
    happened to ignore one field would pass a single-case arm.
    """
    with pytest.raises(ValidationError) as caught:
        _settings(**{omitted: None})

    assert omitted in str(caught.value)


def test_the_refusal_names_what_is_set_and_what_is_missing() -> None:
    """Arm 2's *"one arm naming the refusal"* (ADR-0273 §1).

    An operator who half-configured the provider reads which fields they set and which
    they did not, and is told what to do about it — set the rest, or unset the lot.
    Nothing else in the system will tell them: the quiet reading is a deployment that
    starts and whose planner proposes a booking it has no provider for.
    """
    with pytest.raises(ValidationError) as caught:
        Settings(booking_connection="conn-0001")

    message = str(caught.value)
    assert "booking_connection is set" in message
    assert "booking_endpoint" in message
    assert "booking_retained_records" in message
    assert "ADR-0273" in message


def test_a_whole_configuration_loads() -> None:
    """The nine together are accepted, which is what makes the arms above a refusal.

    Stated because an arm that only ever asserts refusals passes just as well over a
    validator that refuses everything.
    """
    settings = _settings()

    assert settings.booking_connection == "conn-0001"
    assert settings.booking_price_amount == Decimal("120.00")
    assert settings.booking_billed_amount == Decimal("140.00")
    assert settings.booking_billed_currency == "USD"
    assert settings.booking_retained_records == 2


# --------------------------------------------------------------------------- #
# arm 12: every refused shape of an amount, a currency and the record bound
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["booking_price_amount", "booking_billed_amount"])
@pytest.mark.parametrize(
    ("shape", "why"),
    [
        (1.5, "a JSON float is never a price (ADR-0254 §4)"),
        (True, "a flag is not a price, though bool is an int"),
        ("-1", "a negative amount"),
        (Decimal("-0.01"), "a negative amount, spelled as a Decimal"),
        ("NaN", "a string Decimal accepts and no reading admits"),
        ("Infinity", "likewise"),
        ("-Infinity", "likewise"),
        ("not-a-number", "a string Decimal does not accept at all"),
    ],
)
def test_a_configured_amount_outside_the_readers_domain_is_refused(
    field: str, shape: object, why: str
) -> None:
    """One arm per refused amount shape (ADR-0273 §5, ADR-0267 §4).

    §5 fixes the domain as *"a JSON **string** a ``Decimal`` accepts or a JSON
    **integer**, whose ``Decimal`` is **finite and not negative**"*, and names the two
    an implementation reaches by accident: a **flag**, because ``bool`` is a subclass of
    ``int``, and ``"NaN"``/``"Infinity"``, because they are strings ``Decimal``
    **accepts**. A float is ADR-0254 §4's own refusal taken at the configuration.
    """
    with pytest.raises(ValidationError, match=field):
        _settings(**{field: shape})
    assert why  # the reason is the case's own documentation


@pytest.mark.parametrize("field", ["booking_price_currency", "booking_billed_currency"])
@pytest.mark.parametrize("shape", ["usd", "EURO", "EU", "", "E1R", "€€€"])
def test_a_configured_currency_outside_iso_4217s_shape_is_refused(field: str, shape: str) -> None:
    """One arm per refused currency shape (ADR-0273 §5, ADR-0267 §1).

    **Shape and never a register**: ``"usd"`` is refused rather than upcased, because
    silently repairing it *"would treat a lowercase code and a typo'd one differently
    for no reason a caller can see"*, and validating against the live table would make
    a record's decoding depend on a list that changes when currencies are withdrawn.
    """
    with pytest.raises(ValidationError, match=field):
        _settings(**{field: shape})


@pytest.mark.parametrize(
    ("shape", "why"),
    [
        (0, "0 would prune the record its own booking had just inserted"),
        (-1, "a negative bound"),
        (True, "a flag, which a naive integer reader admits — bool being an int"),
        (1.5, "a JSON float is not a count"),
        ("two", "a string that spells no integer"),
        ("1.5", "a decimal spelling of a non-integer"),
        (2**63, "outside the range this reader accepts for an integer field"),
    ],
)
def test_a_configured_record_bound_outside_its_domain_is_refused(shape: object, why: str) -> None:
    """One arm per refused bound (ADR-0273 §5's own five, plus the range).

    §5 fixes the domain's **floor** — ``n >= 1``, *"a store that retains at least the
    booking just made is the weakest bound this decision admits"* — and leaves the
    accepted range to the lane, *"requiring only that whatever range it fixes is
    enforced **at the read** and never at the first prune"*.

    **``"3"`` is not among the refused shapes, and that is a stated reading of §5.**
    That clause lists *"a non-integer — a JSON float, or a string"*, written against a
    JSON document; §5 also fixes *"no field names, no file format and no ``Settings``
    shape"*, and under this lane's environment-variable shape the decimal spelling is
    the only spelling an integer has. So the allowlist is ``_IntegerSetting``'s own,
    applied unchanged: an exact ``int`` or the ``str`` an operator spells one as, and
    nothing that merely converts.
    """
    with pytest.raises(ValidationError, match="booking_retained_records"):
        _settings(booking_retained_records=shape)
    assert why


def test_the_decimal_spelling_of_the_record_bound_is_the_environments_own() -> None:
    """``"3"`` loads as ``3``, which is what an environment variable can say.

    The other half of the case above: a refusal list that also refused this would make
    the setting unreachable from the one place a deployment configures it.
    """
    assert _settings(booking_retained_records="3").booking_retained_records == 3


def test_an_empty_availability_window_is_refused() -> None:
    """A window ending before it begins configures a provider with no available day.

    Every arm §10 states over an *available* day would then pass vacuously, which is the
    failure the refusal exists to prevent rather than a tidiness rule.
    """
    with pytest.raises(ValidationError, match="booking_available_to"):
        _settings(booking_available_from=date(2026, 10, 7), booking_available_to=date(2026, 10, 1))


def test_an_uncertain_day_without_a_provider_is_refused() -> None:
    """A day nothing would read is refused (ADR-0273 §1, §4).

    ``app/composition.py`` constructs no booking integration at all unless the nine are
    set, so an uncertain day beside them is a value nothing reads —
    ``_the_forecast_cost_is_whole_and_only_where_a_provider_is``'s second refusal, one
    provider along and for exactly its reason.
    """
    with pytest.raises(ValidationError, match="booking_indeterminate_date"):
        Settings(booking_indeterminate_date=date(2026, 10, 5))


def test_an_uncertain_day_beside_a_whole_configuration_loads() -> None:
    """And it is accepted where a provider is configured, which §4 requires."""
    settings = _settings(booking_indeterminate_date=date(2026, 10, 5))

    assert settings.booking_indeterminate_date == date(2026, 10, 5)
