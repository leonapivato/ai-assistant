"""ADR-0168 §8's ten figures, and the two orderings that make four of them bind.

The generic guards in ``test_config.py`` already hold every one of these to "a
flag is not a count", "a flag is not a duration" and its own default; what is
here is the part those cannot reach — each field's own range, and the two
cross-field refusals §8 states.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings

_GATEWAY_FIELDS = (
    "gateway_port",
    "gateway_session_ttl",
    "gateway_session_idle_timeout",
    "gateway_max_sessions",
    "gateway_max_hub_connections",
    "gateway_max_request_bytes",
    "gateway_record_interval",
    "gateway_read_timeout",
    "gateway_max_browser_connections",
    "gateway_max_pending_connections",
)


def test_the_ten_figures_are_all_present_with_adr_0168_section_8_defaults() -> None:
    """§8's table, transcribed. A default that drifts is two gateways disagreeing."""
    settings = Settings()

    assert settings.gateway_port == 8422
    assert settings.gateway_session_ttl == timedelta(hours=12)
    assert settings.gateway_session_idle_timeout == timedelta(hours=1)
    assert settings.gateway_max_sessions == 8
    assert settings.gateway_max_hub_connections == 8
    assert settings.gateway_max_request_bytes == 1024 * 1024
    assert settings.gateway_record_interval == timedelta(minutes=1)
    assert settings.gateway_read_timeout == timedelta(seconds=30)
    assert settings.gateway_max_browser_connections == 64
    assert settings.gateway_max_pending_connections == 8


def test_the_ten_figures_are_exactly_ten() -> None:
    """A tripwire on the *count*, because §8 names ten and the Consequences say ten.

    An eleventh `gateway_*` field is a figure no ADR names, which is the
    underdetermination §8 opens by refusing — and ADR-0172's own opening bullet
    says it "adds no eleventh". Discovering that here is cheaper than in review.
    """
    named = {name for name in Settings.model_fields if name.startswith("gateway_")}

    assert named == set(_GATEWAY_FIELDS)


@pytest.mark.parametrize("name", _GATEWAY_FIELDS)
def test_no_gateway_figure_is_nullable(name: str) -> None:
    """None takes a value meaning "off" (ADR-0168 §8).

    "A gateway with no session expiry, no session ceiling and no request bound is
    a resident process that a single local caller can exhaust", so ``None`` is not
    the disabled sentinel ADR-0083 §7 allows a scheduler interval — it is a value
    the field does not have.
    """
    with pytest.raises(ValidationError):
        Settings(**{name: None})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize(
    "name",
    ["gateway_max_sessions", "gateway_max_hub_connections", "gateway_max_request_bytes"],
)
@pytest.mark.parametrize("value", [0, -1])
def test_every_integer_figure_is_refused_unless_strictly_positive(name: str, value: int) -> None:
    """§8: "refused at settings load unless it is strictly positive"."""
    with pytest.raises(ValidationError):
        Settings(**{name: value})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize(
    "name",
    [
        "gateway_session_ttl",
        "gateway_session_idle_timeout",
        "gateway_record_interval",
        "gateway_read_timeout",
    ],
)
@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_every_duration_figure_is_refused_unless_strictly_positive(
    name: str, value: timedelta
) -> None:
    """The ``gt=timedelta(0)`` half of §8's rule, for the four durations."""
    with pytest.raises(ValidationError):
        Settings(**{name: value})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize("value", [0, 1023, 65536, -1])
def test_the_port_is_refused_unless_it_is_a_valid_non_privileged_port(value: int) -> None:
    """§8 refuses ``gateway_port`` "unless it is a valid non-privileged TCP port".

    Below 1024 the listener needs privilege a gateway has no business holding, and
    above 65535 there is no port to bind — both of which arrive as an errno at
    bind rather than as the value the operator was given, which is why load is
    where they surface.
    """
    with pytest.raises(ValidationError):
        Settings(gateway_port=value)


@pytest.mark.parametrize("value", [1024, 8422, 65535])
def test_the_port_admits_the_whole_non_privileged_range(value: int) -> None:
    """The refusal narrows nothing legitimate."""
    assert Settings(gateway_port=value).gateway_port == value


def test_an_idle_bound_above_the_session_lifetime_is_refused() -> None:
    """§8: refused "unless it is no greater than ``gateway_session_ttl``".

    "An idle bound above the absolute lifetime is a limit that can never bind" —
    and a limit that cannot bind is an absent one, not a weaker one, so an
    operator who set it is holding a defence they do not have.
    """
    with pytest.raises(ValidationError, match="can never bind"):
        Settings(
            gateway_session_ttl=timedelta(hours=1), gateway_session_idle_timeout=timedelta(hours=2)
        )


def test_an_idle_bound_equal_to_the_session_lifetime_is_admitted() -> None:
    """ "No greater than" is the bound, so equal is admitted and only above refused."""
    settings = Settings(
        gateway_session_ttl=timedelta(hours=3), gateway_session_idle_timeout=timedelta(hours=3)
    )

    assert settings.gateway_session_idle_timeout == settings.gateway_session_ttl


def test_a_pending_ceiling_above_the_connection_ceiling_is_refused() -> None:
    """§8's second ordering, on its first one's reason exactly."""
    with pytest.raises(ValidationError, match="can never bind"):
        Settings(gateway_max_browser_connections=4, gateway_max_pending_connections=5)


def test_a_pending_ceiling_equal_to_the_connection_ceiling_is_admitted() -> None:
    """Equal binds — every connection may be unadmitted at once, which is coherent."""
    settings = Settings(gateway_max_browser_connections=4, gateway_max_pending_connections=4)

    assert settings.gateway_max_pending_connections == 4


def test_the_gateway_figures_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator-facing path, which is the only one a deployment reaches."""
    monkeypatch.setenv("ASSISTANT_GATEWAY_PORT", "9001")
    monkeypatch.setenv("ASSISTANT_GATEWAY_SESSION_TTL", "PT2H")
    monkeypatch.setenv("ASSISTANT_GATEWAY_MAX_SESSIONS", "3")

    settings = Settings()

    assert settings.gateway_port == 9001
    assert settings.gateway_session_ttl == timedelta(hours=2)
    assert settings.gateway_max_sessions == 3
