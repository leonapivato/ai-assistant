"""Tests for Settings validation of the context configuration (ADR-0008)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings, load_settings
from ai_assistant.core.errors import ConfigurationError


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
