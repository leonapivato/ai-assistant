"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_assistant.core.errors import ConfigurationError


class Settings(BaseSettings):
    """Typed application settings.

    Values are read from environment variables (optionally via a local ``.env``
    file) using the ``ASSISTANT_`` prefix, e.g. ``ASSISTANT_LOG_LEVEL=DEBUG``.
    """

    model_config = SettingsConfigDict(
        env_prefix="ASSISTANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---------------------------------------------------------
    log_level: str = Field(default="INFO", description="Root log level.")

    @field_validator("log_level")
    @classmethod
    def _log_level_is_known(cls, value: str) -> str:
        """Reject an unrecognised level, and normalise case.

        Without this a typo (``EROR``) silently fell back to INFO, so an
        operator who set DEBUG to diagnose something, or WARNING to quieten a
        service, got neither and no indication why. Validating here also keeps
        the promise ``load_settings`` makes for every other setting: bad
        configuration fails at load, as a ``ConfigurationError``.
        """
        normalised = value.upper()
        if normalised not in logging.getLevelNamesMapping():
            known = ", ".join(sorted(logging.getLevelNamesMapping()))
            msg = f"unknown log level {value!r}; expected one of: {known}"
            raise ValueError(msg)
        return normalised

    # --- Model layer -----------------------------------------------------
    # The assistant is model-agnostic; this names the default model the
    # orchestration layer reaches for when a caller doesn't specify one.
    # Format follows pydantic-ai's "provider:model" convention.
    default_model: str = Field(
        default="anthropic:claude-opus-4-8",
        description="Default model in pydantic-ai 'provider:model' form.",
    )

    # Resilience knobs for the model layer. The deadline is per attempt, so the
    # worst-case wall time of a call is roughly
    # ``max_attempts * timeout + total backoff``.
    model_timeout_seconds: float = Field(
        default=60.0, gt=0, description="Deadline for a single model attempt, in seconds."
    )
    model_max_attempts: int = Field(
        default=3, ge=1, description="Total model attempts, including the first. 1 disables retry."
    )
    model_backoff_base_seconds: float = Field(
        default=0.5, gt=0, description="Backoff ceiling after the first failure; doubles per retry."
    )
    model_backoff_max_seconds: float = Field(
        default=30.0, gt=0, description="Upper bound on the backoff ceiling, in seconds."
    )

    # --- Context ---------------------------------------------------------
    # Used to localise the situational context (ADR-0008). ``timezone`` is an
    # IANA name; working hours are a local-time window, end-exclusive. Both are
    # validated here, so a malformed value fails at load rather than per request.
    timezone: str = Field(default="UTC", description="IANA timezone for local-time context.")
    working_hours_start: int = Field(
        default=9, ge=0, le=23, description="First hour of the working-hours window (local)."
    )
    working_hours_end: int = Field(
        default=17,
        ge=1,
        le=24,
        description="End hour of the working-hours window (local, exclusive).",
    )

    @field_validator("timezone")
    @classmethod
    def _timezone_is_known(cls, value: str) -> str:
        """Reject a timezone that is not a known IANA zone."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown timezone {value!r}"
            raise ValueError(msg) from exc
        return value

    @model_validator(mode="after")
    def _backoff_bounds_are_ordered(self) -> Settings:
        """Require the backoff cap to be at least the base delay."""
        if self.model_backoff_max_seconds < self.model_backoff_base_seconds:
            msg = (
                f"invalid backoff window: model_backoff_max_seconds="
                f"{self.model_backoff_max_seconds} must be >= "
                f"model_backoff_base_seconds={self.model_backoff_base_seconds}"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _working_hours_are_a_range(self) -> Settings:
        """Require the working-hours window to be a non-empty range."""
        if self.working_hours_start >= self.working_hours_end:
            msg = (
                f"invalid working-hours window: start={self.working_hours_start} "
                f"must be < end={self.working_hours_end}"
            )
            raise ValueError(msg)
        return self


def load_settings() -> Settings:
    """Load and validate settings from the environment.

    Kept as a function (rather than a module-level singleton) so tests can
    construct isolated ``Settings`` instances without import-time side effects.

    Raises:
        ConfigurationError: If any setting is missing or invalid (e.g. an unknown
            timezone or an empty working-hours window).
    """
    try:
        return Settings()
    except ValidationError as exc:
        msg = f"invalid configuration: {exc}"
        raise ConfigurationError(msg) from exc
