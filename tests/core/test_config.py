"""Tests for Settings validation of the context configuration (ADR-0008)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings, load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import Reversibility, RiskLevel


def test_defaults_are_valid() -> None:
    settings = Settings()
    assert settings.timezone == "UTC"
    assert settings.working_hours_start < settings.working_hours_end


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown timezone"):
        Settings(timezone="Mars/Olympus_Mons")


def test_empty_working_hours_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="working-hours window"):
        Settings(working_hours_start=17, working_hours_end=9)


def test_load_settings_wraps_invalid_config_as_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_TIMEZONE", "Nowhere/Void")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_load_settings_succeeds_with_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_TIMEZONE", "America/New_York")
    settings = load_settings()
    assert settings.timezone == "America/New_York"


@pytest.mark.parametrize("value", ["EROR", "verbose", "", "TRACE"])
def test_unknown_log_level_is_rejected(value: str) -> None:
    # A typo used to fall back to INFO silently, so an operator who set DEBUG to
    # diagnose something got neither the level nor any indication why.
    with pytest.raises(ValidationError):
        Settings(log_level=value)


@pytest.mark.parametrize("value", ["debug", "Warning", "critical"])
def test_log_level_is_normalised_to_upper_case(value: str) -> None:
    assert Settings(log_level=value).log_level == value.upper()


def test_confirmation_ttl_defaults_to_none() -> None:
    # No lifetime by default preserves the pre-#243 behaviour: no legitimate
    # answer to a parked confirmation is refused (#310).
    assert Settings().confirmation_ttl is None


def test_confirmation_ttl_accepts_a_positive_duration() -> None:
    assert Settings(confirmation_ttl=timedelta(hours=1)).confirmation_ttl == timedelta(hours=1)


def test_confirmation_ttl_accepts_an_explicit_none() -> None:
    assert Settings(confirmation_ttl=None).confirmation_ttl is None


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1), timedelta(hours=-1)])
def test_non_positive_confirmation_ttl_is_rejected(value: timedelta) -> None:
    # Mirrors StepRunner's own non-positive guard: a zero or negative lifetime
    # expires every confirmation the instant it is recorded, making the flow
    # unanswerable by misconfiguration (#310). Refused at load, not per answer.
    with pytest.raises(ValidationError):
        Settings(confirmation_ttl=value)


def test_confirmation_ttl_parses_an_iso_duration_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_CONFIRMATION_TTL", "PT1H")
    assert load_settings().confirmation_ttl == timedelta(hours=1)


def test_load_settings_rejects_a_non_positive_confirmation_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_CONFIRMATION_TTL", "PT0S")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_permission_threshold_defaults_reproduce_the_policy_defaults() -> None:
    # Unset, the four thresholds must match ThresholdActionPolicy's own
    # constructor defaults so a deployment that configures nothing keeps today's
    # gate: confirm at or above MEDIUM risk, confirm on an IRREVERSIBLE effect,
    # deny nothing outright (#239).
    settings = Settings()
    assert settings.confirm_at_risk is RiskLevel.MEDIUM
    assert settings.confirm_at_reversibility is Reversibility.IRREVERSIBLE
    assert settings.deny_at_risk is None
    assert settings.deny_at_reversibility is None


def test_permission_thresholds_accept_scale_members() -> None:
    settings = Settings(
        confirm_at_risk=RiskLevel.HIGH,
        confirm_at_reversibility=Reversibility.RECOVERABLE,
        deny_at_risk=RiskLevel.CRITICAL,
        deny_at_reversibility=Reversibility.IRREVERSIBLE,
    )
    assert settings.confirm_at_risk is RiskLevel.HIGH
    assert settings.confirm_at_reversibility is Reversibility.RECOVERABLE
    assert settings.deny_at_risk is RiskLevel.CRITICAL
    assert settings.deny_at_reversibility is Reversibility.IRREVERSIBLE


def test_permission_thresholds_accept_an_explicit_none() -> None:
    # None is a meaningful value on every knob — "never gate on this field alone"
    # — not a stand-in for the default, so it must round-trip (#239).
    settings = Settings(
        confirm_at_risk=None,
        confirm_at_reversibility=None,
        deny_at_risk=None,
        deny_at_reversibility=None,
    )
    assert settings.confirm_at_risk is None
    assert settings.confirm_at_reversibility is None


def test_permission_thresholds_below_their_confirm_pair_are_accepted() -> None:
    # The policy accepts a deny threshold below its matching confirm one — the
    # result only ever denies where it would otherwise ask, strictly safer — so
    # config imposes no ordering either (#239, ADR-0021 §5).
    settings = Settings(confirm_at_risk=RiskLevel.HIGH, deny_at_risk=RiskLevel.MEDIUM)
    assert settings.deny_at_risk is RiskLevel.MEDIUM


# "none" is the disable sentinel, not an off-scale value — it is tested as the
# disable path below. "" strips to "" (not the sentinel) and "MEDIUM" is the
# wrong case, so both still fall through to scale validation and are refused.
@pytest.mark.parametrize("value", ["extreme", "MEDIUM", ""])
def test_off_scale_risk_threshold_is_rejected(value: str) -> None:
    # Only a lowercase member value is on the scale; anything else fails at load.
    with pytest.raises(ValidationError):
        Settings(confirm_at_risk=value)  # type: ignore[arg-type]  # invalid input under test


@pytest.mark.parametrize("value", ["permanent", "Irreversible", "unknown"])
def test_off_scale_reversibility_threshold_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(deny_at_reversibility=value)  # type: ignore[arg-type]  # invalid input under test


@pytest.mark.parametrize("sentinel", ["none", "NONE", "None", " none "])
def test_disable_sentinel_maps_a_threshold_to_none(sentinel: str) -> None:
    # The sentinel a string-only channel (env) needs to reach a gate's ``None``:
    # "never gate on this field alone". Case-insensitive, whitespace-tolerant, and
    # it must not collide with any scale member (#239).
    settings = Settings(confirm_at_risk=sentinel, deny_at_reversibility=sentinel)  # type: ignore[arg-type]  # sentinel string under test
    assert settings.confirm_at_risk is None
    assert settings.deny_at_reversibility is None


def test_permission_thresholds_parse_member_values_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_CONFIRM_AT_RISK", "high")
    monkeypatch.setenv("ASSISTANT_DENY_AT_REVERSIBILITY", "irreversible")
    settings = load_settings()
    assert settings.confirm_at_risk is RiskLevel.HIGH
    assert settings.deny_at_reversibility is Reversibility.IRREVERSIBLE


@pytest.mark.parametrize(
    ("env_var", "field"),
    [
        ("ASSISTANT_CONFIRM_AT_RISK", "confirm_at_risk"),
        ("ASSISTANT_CONFIRM_AT_REVERSIBILITY", "confirm_at_reversibility"),
        ("ASSISTANT_DENY_AT_RISK", "deny_at_risk"),
        ("ASSISTANT_DENY_AT_REVERSIBILITY", "deny_at_reversibility"),
    ],
)
def test_each_threshold_can_be_disabled_from_the_environment(
    env_var: str, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The disable path over the production channel: every gate, including the two
    # whose non-None default omission cannot reach, reaches ``None`` via its env
    # var set to the sentinel. Without this an operator can tighten a gate but not
    # switch it off — the configurability #239 exists to deliver.
    monkeypatch.setenv(env_var, "none")
    assert getattr(load_settings(), field) is None


def test_load_settings_rejects_an_off_scale_threshold_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_DENY_AT_RISK", "catastrophic")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()
