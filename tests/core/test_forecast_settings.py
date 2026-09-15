"""ADR-0260 §11's nine settings, and the half-set states that stop the deployment.

§13's arm (b-prime), the ``Settings`` half: "a ``Settings`` naming a non-finite or
out-of-range coordinate, a ``forecast_max_days`` outside ``1..3``, a non-positive
``forecast_max_day_chars`` or ``forecast_max_response_bytes``, **or any half-set pair**
— connection without origin or the reverse, one coordinate without the other, one cost
field without the other, coordinates or costs with no provider pair, **and a connection
and origin with both coordinates unset** — **does not start**."

**Every domain is closed and a value outside it stops the deployment**, which §11 calls
"the fail-fast ``Settings`` already performs on the search pair rather than a new
posture". The per-field guards a ``float`` or an ``int`` setting inherits from its type
— a flag is not a measurement, a foreign scalar is not a number — are
``tests/core/test_config.py``'s, discovered from the model so that these fields joined
them the day they were added; what is here is what ADR-0260 decides about **these**
fields in particular.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings

#: A whole forecast configuration: the four fields ADR-0260 §11 makes "one pair of
#: pairs". Every case below starts from this and breaks exactly one thing.
_WHOLE: Final[dict[str, Any]] = {
    "forecast_connection": "forecast-account",
    "forecast_origin": "https://forecast.example.invalid",
    "forecast_latitude": 41.1579,
    "forecast_longitude": -8.6291,
}


def _settings(**fields: Any) -> Settings:
    """Construct ``Settings`` from a mapping whose keys the cases parametrise over.

    The dynamic keyword is the point of the cases below — they name the *real* field
    names so that a rename fails here rather than passing vacuously — and it is the one
    thing mypy cannot check, since it sees a single ``**dict`` offered against every
    field's own type at once. Confining the ``Any`` to this helper keeps that gap one
    line wide, which is ``tests/core/test_config.py``'s own shape for it.

    Args:
        fields: The settings to supply.

    Returns:
        The loaded settings.
    """
    return Settings(**fields)


def test_a_deployment_that_configures_none_of_the_four_loads() -> None:
    """The shipped default: no forecast provider, and three bounds that already bind.

    ADR-0260 §11 ships each bound "with a value … so that no deployment is unbounded by
    omission", and §12's L1 authorises no byte: "a deployment that configures none is
    unchanged in every respect".
    """
    settings = _settings()

    assert settings.forecast_connection is None
    assert settings.forecast_origin is None
    assert settings.forecast_latitude is None
    assert settings.forecast_longitude is None
    assert settings.forecast_cost_per_call is None
    assert settings.forecast_cost_currency is None
    assert settings.forecast_max_days == 3
    assert settings.forecast_max_day_chars == 2048
    assert settings.forecast_max_response_bytes == 1024 * 1024


def test_a_whole_configuration_loads() -> None:
    """The positive arm, so every refusal below is about the clause it names."""
    settings = _settings(**_WHOLE)

    assert settings.forecast_connection == "forecast-account"
    assert settings.forecast_latitude == pytest.approx(41.1579)


@pytest.mark.parametrize(
    "absent",
    [
        pytest.param("forecast_connection", id="no-connection"),
        pytest.param("forecast_origin", id="no-origin"),
        pytest.param("forecast_latitude", id="no-latitude"),
        pytest.param("forecast_longitude", id="no-longitude"),
    ],
)
def test_a_half_set_configuration_does_not_start(absent: str) -> None:
    """ADR-0260 §11: the four are **one pair of pairs**, refused half-set.

    "A connection and an origin without a coordinate would start a deployment whose
    ``request`` must answer a proposal it has no place to build, so the four are one pair
    of pairs and the load-time refusal covers every half-set combination of them."

    **Every one of the four absences is a case**, because a validator written as two
    pairwise checks would admit exactly the combination §11 names as the reason the four
    are one rule — and the quiet reading is the unsafe one: "later" here is a turn whose
    planner asked for a forecast and whose forecaster was never built, which an operator
    would read as the mechanism being inert rather than as their configuration having
    half-landed.
    """
    fields = {name: value for name, value in _WHOLE.items() if name != absent}

    with pytest.raises(ValidationError, match=absent):
        Settings(**fields)


def test_a_provider_pair_with_no_coordinate_does_not_start() -> None:
    """§13's arm (b-prime) names this case in its own right.

    "**And a connection and origin with both coordinates unset**" — the combination two
    pairwise validators would let through, and the one §11 states the whole rule for.
    """
    with pytest.raises(ValidationError, match="forecast_latitude, forecast_longitude"):
        _settings(
            forecast_connection=_WHOLE["forecast_connection"],
            forecast_origin=_WHOLE["forecast_origin"],
        )


def test_a_coordinate_with_no_provider_pair_does_not_start() -> None:
    """The mirror: a place to read for and nowhere to read it from.

    §11's refusal is over the four together, so this is the same clause seen from the
    other side rather than a second rule.
    """
    with pytest.raises(ValidationError, match="forecast_connection, forecast_origin"):
        _settings(
            forecast_latitude=_WHOLE["forecast_latitude"],
            forecast_longitude=_WHOLE["forecast_longitude"],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("forecast_latitude", 90.1, id="latitude-above"),
        pytest.param("forecast_latitude", -90.1, id="latitude-below"),
        pytest.param("forecast_longitude", 180.1, id="longitude-above"),
        pytest.param("forecast_longitude", -180.1, id="longitude-below"),
        pytest.param("forecast_latitude", float("nan"), id="latitude-nan"),
        pytest.param("forecast_latitude", float("inf"), id="latitude-infinity"),
        pytest.param("forecast_longitude", float("-inf"), id="longitude-negative-infinity"),
    ],
)
def test_a_coordinate_outside_its_domain_does_not_start(field: str, value: float) -> None:
    """§11: finite, ``-90..90`` and ``-180..180`` **inclusive**; NaN and either infinity
    refused.

    "A coordinate that is not a place would compose a request no provider documents an
    answer for." NaN is the sharpest of the seven: it makes every comparison false rather
    than answering, so a range check written as ``if value > maximum`` would admit it
    while a deployment configured a place nowhere on earth.
    """
    with pytest.raises(ValidationError, match=field):
        _settings(**{**_WHOLE, field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("forecast_latitude", 90.0, id="latitude-at-the-pole"),
        pytest.param("forecast_latitude", -90.0, id="latitude-at-the-other-pole"),
        pytest.param("forecast_longitude", 180.0, id="longitude-at-the-antimeridian"),
        pytest.param("forecast_longitude", -180.0, id="longitude-at-the-other-side"),
        pytest.param("forecast_latitude", 0.0, id="latitude-at-the-equator"),
    ],
)
def test_a_coordinate_at_its_boundary_loads(field: str, value: float) -> None:
    """§11's domain is **inclusive**, and the boundary is where that is decidable.

    Zero is here for its own reason: it is a real place, so a validator reading falsiness
    rather than absence would refuse the equator and the prime meridian.
    """
    assert getattr(_settings(**{**_WHOLE, field: value}), field) == pytest.approx(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("forecast_max_days", 0, id="days-zero"),
        pytest.param("forecast_max_days", -1, id="days-negative"),
        pytest.param("forecast_max_days", 4, id="days-above-the-ceiling"),
        pytest.param("forecast_max_day_chars", 0, id="chars-zero"),
        pytest.param("forecast_max_day_chars", -1, id="chars-negative"),
        pytest.param("forecast_max_response_bytes", 0, id="bytes-zero"),
        pytest.param("forecast_max_response_bytes", -1, id="bytes-negative"),
    ],
)
def test_a_bound_outside_its_domain_does_not_start(field: str, value: int) -> None:
    """§11: ``1..3`` for the days, strictly positive for the other two.

    "A zero or negative bound is refused rather than read as 'no limit': a bound whose
    value makes every successful read unrepresentable is a misconfiguration and never a
    policy." The ceiling of three is §7's, and it is part of the **domain** rather than
    a default: it is what keeps §7's servicing precedence true in *every* configuration,
    so no deployment can make one forecast read take more than three of ADR-0226 §6's
    budget of ten.
    """
    with pytest.raises(ValidationError, match=field):
        _settings(**{field: value})


@pytest.mark.parametrize("value", [1, 2, 3])
def test_every_admitted_day_count_loads(value: int) -> None:
    """§11's whole domain for the days, walked rather than sampled.

    Three cases and not one, because the interesting ends are both of them: ``1`` is the
    narrowest a deployment can ask for and ``3`` is §7's ceiling, and a validator that
    got either end wrong would pass a case that only tried the middle.
    """
    assert _settings(forecast_max_days=value).forecast_max_days == value


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"forecast_cost_per_call": Decimal("0.001")}, id="figure-alone"),
        pytest.param({"forecast_cost_currency": "EUR"}, id="currency-alone"),
    ],
)
def test_half_a_per_call_figure_does_not_start(fields: dict[str, Any]) -> None:
    """§11, ADR-0236 §1: both or neither.

    ``ToolCost`` needs an amount *and* an ISO-4217 code for a ``PER_CALL`` basis, so a
    lone amount is a figure denominated in nothing and a lone code is a register for no
    figure. The quiet reading — silently falling back to ``UNKNOWN`` — is the unsafe one:
    an operator who set one variable believes their reads are priced, and would meet the
    cost floor on every one of them with no indication that their configuration had
    half-landed.
    """
    with pytest.raises(ValidationError, match="a declared per-call cost needs both"):
        _settings(**{**_WHOLE, **fields})


def test_a_per_call_figure_with_no_provider_does_not_start() -> None:
    """§11, ADR-0236 §2: "only where a forecast provider is configured".

    A per-call figure for a forecaster no deployment builds is a value nothing reads:
    ``app/composition.py`` constructs no forecast integration at all unless the four
    fields are set, so the pair would reach no builder and no declaration.
    """
    with pytest.raises(ValidationError, match="no forecast provider is configured"):
        _settings(forecast_cost_per_call=Decimal("0.001"), forecast_cost_currency="EUR")


def test_a_zero_figure_is_a_price_and_loads() -> None:
    """ADR-0236 §3 through §11: ``FREE`` is unreachable and zero is the spelling.

    "A deployment that wants the read to run without one states the provider's cost,
    which for a free provider is zero in the currency it states" — a positive assertion
    carrying a register, rather than a basis that claims the figure is known to be
    nothing.
    """
    settings = _settings(
        **_WHOLE, forecast_cost_per_call=Decimal("0"), forecast_cost_currency="EUR"
    )

    assert settings.forecast_cost_per_call == Decimal("0")
    assert settings.forecast_cost_currency == "EUR"


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("eur", id="lower-case"),
        pytest.param("EURO", id="four-letters"),
        pytest.param("EU", id="two-letters"),
        pytest.param("E1R", id="a-digit"),
    ],
)
def test_a_malformed_currency_code_does_not_start(code: str) -> None:
    """ADR-0236 §2 through §11: three uppercase ASCII letters, shape only.

    Validated by the **same** validator ``world_spend_currency`` and
    ``web_search_cost_currency`` carry rather than by a copy of it, which is what makes
    "``ToolCost.currency``'s rule and not a third one" a property of the code.
    """
    with pytest.raises(ValidationError, match="three uppercase ASCII letters"):
        _settings(**_WHOLE, forecast_cost_per_call=Decimal("0.001"), forecast_cost_currency=code)


@pytest.mark.parametrize(
    "amount",
    [
        pytest.param(Decimal("-0.001"), id="negative"),
        pytest.param(Decimal("NaN"), id="nan"),
        pytest.param(Decimal("Infinity"), id="infinity"),
        pytest.param(Decimal("1E15"), id="at-the-ceiling"),
        pytest.param(Decimal("0.0000000001"), id="ten-fractional-digits"),
    ],
)
def test_a_figure_outside_adr_0194_s_domain_does_not_start(amount: Decimal) -> None:
    """ADR-0194 §1's predicate, reached by the validator the search pair already uses.

    "Admitting an uncountable one would mean a declaration that loads, registers, rules
    ``ALLOW`` and is then refused at the gate with ``SpendUndeterminedError`` on every
    call." One decorator names both provider fields, so the two cannot drift.
    """
    with pytest.raises(ValidationError, match="forecast_cost_per_call"):
        _settings(**_WHOLE, forecast_cost_per_call=amount, forecast_cost_currency="EUR")


@pytest.mark.parametrize("field", ["forecast_connection", "forecast_origin"])
def test_a_blank_reference_or_origin_does_not_start(field: str) -> None:
    """The blank the environment makes easy to produce.

    ``ASSISTANT_FORECAST_ORIGIN=`` sets the variable to the empty string, not to
    nothing, so without this a cleared variable reads as *configured* and only fails much
    later — at a bind, or at a parse inside the transport. Refused by the **same**
    validator the mail and search pairs carry, so one mistake reads one way whichever
    integration it is made on.
    """
    with pytest.raises(ValidationError, match="must hold text"):
        _settings(**{**_WHOLE, field: "   "})
