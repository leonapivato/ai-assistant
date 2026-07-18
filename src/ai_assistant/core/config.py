"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Model layer -----------------------------------------------------
    # The assistant is model-agnostic; this names the default model the
    # orchestration layer reaches for when a caller doesn't specify one.
    # Format follows pydantic-ai's "provider:model" convention.
    default_model: str = Field(
        default="anthropic:claude-opus-4-8",
        description="Default model in pydantic-ai 'provider:model' form.",
    )

    # --- Context ---------------------------------------------------------
    # Used to localise the situational context (ADR-0008). ``timezone`` is an
    # IANA name (validated when the clock source is wired); working hours are a
    # local-time window, end-exclusive.
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


def load_settings() -> Settings:
    """Load and validate settings from the environment.

    Kept as a function (rather than a module-level singleton) so tests can
    construct isolated ``Settings`` instances without import-time side effects.
    """
    return Settings()
