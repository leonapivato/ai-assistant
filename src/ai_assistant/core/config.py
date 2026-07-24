"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import Reversibility, RiskLevel

#: The string an operator sets a permission threshold to in the environment to
#: **disable** that gate entirely — "never gate on this field alone", i.e. the
#: field's ``None`` value. Environment variables arrive as strings, so a
#: non-None-default gate (``confirm_at_risk``, ``confirm_at_reversibility``)
#: would otherwise be un-disable-able from the environment: omitting the variable
#: restores the default, and no scale member spells ``None``. Case-insensitive,
#: and distinct from every ``RiskLevel``/``Reversibility`` member value, so it
#: cannot collide with a real threshold.
_THRESHOLD_DISABLE_SENTINEL = "none"


def _disable_threshold(value: object) -> object:
    """Map the disable sentinel to ``None`` before a threshold's scale validation.

    A per-field :class:`BeforeValidator` rather than the model-wide
    ``env_parse_none_str``: that switch would turn a literal ``"none"`` into
    ``None`` on *every* setting, including ``str``-typed ones like
    ``default_model`` where ``"none"`` is a legitimate value rather than a request
    to disable anything. Restricting the sentinel to the four threshold fields
    keeps the disable path where it belongs. Any other value — a scale member, an
    enum instance passed directly, an already-``None`` — falls through unchanged,
    so off-scale input is still refused by the scale validation that follows.
    """
    if isinstance(value, str) and value.strip().lower() == _THRESHOLD_DISABLE_SENTINEL:
        return None
    return value


#: A permission threshold on the risk / reversibility scale, or ``None`` to
#: disable that gate. The :class:`BeforeValidator` accepts the environment
#: disable sentinel (:data:`_THRESHOLD_DISABLE_SENTINEL`) as ``None``.
_RiskThreshold = Annotated[RiskLevel | None, BeforeValidator(_disable_threshold)]
_ReversibilityThreshold = Annotated[Reversibility | None, BeforeValidator(_disable_threshold)]


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
    # ``allow_inf_nan=False`` matters: ``gt=0`` rejects NaN but happily accepts
    # infinity, which would silently disable the deadline or unbound backoff.
    model_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        allow_inf_nan=False,
        description="Deadline for a single model attempt, in seconds.",
    )
    model_max_attempts: int = Field(
        default=3, ge=1, description="Total model attempts, including the first. 1 disables retry."
    )
    model_backoff_base_seconds: float = Field(
        default=0.5,
        gt=0,
        allow_inf_nan=False,
        description="Backoff ceiling after the first failure; doubles per retry.",
    )
    model_backoff_max_seconds: float = Field(
        default=30.0,
        gt=0,
        allow_inf_nan=False,
        description="Upper bound on the backoff ceiling, in seconds.",
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

    # --- Orchestration ---------------------------------------------------
    # How long a parked confirmation stands before an answer to it is refused as
    # stale (StepRunner._check_fresh, ADR-0036 §1, #243). A deployment value, not
    # a contract one. ``None`` (the default) means no lifetime — the pre-#243
    # behaviour, refusing no legitimate answer — which is why StepRunner declines
    # to invent one (ADR-0037 §4). ``gt=timedelta(0)`` mirrors the runner's own
    # non-positive guard: a zero or negative lifetime would expire every
    # confirmation the instant it was recorded, making the flow unanswerable by
    # misconfiguration, so it is refused at load rather than per answer. Parsed
    # from an ISO-8601 duration or ``HH:MM:SS`` string in the environment
    # (e.g. ``ASSISTANT_CONFIRMATION_TTL=PT1H`` or ``01:00:00``).
    confirmation_ttl: timedelta | None = Field(
        default=None,
        gt=timedelta(0),
        description="Lifetime of a parked confirmation before its answer is refused as stale.",
    )

    # --- Permissions -----------------------------------------------------
    # The four thresholds ThresholdActionPolicy gates on (ADR-0036 §1). These are
    # the *user's* configuration, not the contract's — ADR-0021 §5 records that
    # "confirm at or above MEDIUM" is a deployment setting, not a decision the
    # policy makes for the operator — so they belong here rather than hardcoded at
    # the composition root (#239, the scope PR #237 cut per ADR-0036 §1). The
    # defaults reproduce the policy constructor's own defaults exactly, so an
    # unset deployment keeps today's behaviour: confirm at or above MEDIUM risk,
    # confirm on an IRREVERSIBLE effect, deny nothing outright.
    #
    # Each is the scale it names or ``None``. pydantic parses the lowercase member
    # value from the environment (e.g. ``ASSISTANT_CONFIRM_AT_RISK=high``,
    # ``ASSISTANT_DENY_AT_REVERSIBILITY=irreversible``) and refuses anything off
    # the scale at load, as a ConfigurationError. To **disable** a gate entirely —
    # "never confirm/deny on this field alone", the field's ``None`` — set the
    # variable to ``none`` (case-insensitive), the sentinel a per-field
    # BeforeValidator maps to ``None`` before scale validation
    # (:data:`_THRESHOLD_DISABLE_SENTINEL`); this matters most for the two confirm
    # gates, whose non-None defaults omission cannot reach.
    #
    # No cross-field ordering is imposed: the policy accepts a deny threshold below
    # its matching confirm one (the combination is still a maximum, so the result
    # only ever denies where it would otherwise ask — strictly safer), so imposing
    # an order here would be this layer deciding how cautious the operator is
    # allowed to be. The floors — off-device disclosure and unknown cost — are the
    # contract's and take no setting.
    confirm_at_risk: _RiskThreshold = Field(
        default=RiskLevel.MEDIUM,
        description=(
            "Risk at or above which an action needs confirmation; 'none' never confirms on risk."
        ),
    )
    confirm_at_reversibility: _ReversibilityThreshold = Field(
        default=Reversibility.IRREVERSIBLE,
        description=(
            "Reversibility at or above which an action needs confirmation; "
            "'none' never confirms on reversibility."
        ),
    )
    deny_at_risk: _RiskThreshold = Field(
        default=None,
        description=(
            "Risk at or above which an action is refused outright; 'none' never denies on risk."
        ),
    )
    deny_at_reversibility: _ReversibilityThreshold = Field(
        default=None,
        description=(
            "Reversibility at or above which an action is refused outright; "
            "'none' never denies on reversibility."
        ),
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
