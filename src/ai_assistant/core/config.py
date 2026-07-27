"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    ``None`` on *every* setting, so no other field could ever take ``"none"`` as
    a value in its own right — it would arrive as ``None`` and be judged against
    that field's own type instead. Restricting the sentinel to the four threshold
    fields keeps the disable path where it belongs, and leaves every other field
    free to say for itself what ``"none"`` means. Any other value — a scale member, an
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


#: The shape of a pydantic-ai model spec: a non-empty ``provider`` and a non-empty
#: ``model``, separated by the first colon. The character classes are not invented
#: — they are the ones pydantic-ai's own ``known_model_names()`` actually uses
#: (``-``, ``.``, ``/`` in a provider; those plus further ``:`` in a model name,
#: as in ``bedrock:us.anthropic.claude-...``), checked against all 602 of its
#: colon-bearing names, none of which this rejects.
#:
#: What it deliberately does **not** do is decide whether the named provider
#: exists or is installed. That is the models layer's knowledge, not
#: configuration's (golden rule 4 confines provider SDKs to ``models/``, and the
#: import contract forbids ``core`` from importing ``pydantic_ai`` at all), so
#: this validates the *form* of a spec and nothing about the vendor behind it —
#: see ADR-0062 §2.
_MODEL_SPEC_PATTERN: Final = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9._\-/]*:[A-Za-z0-9][A-Za-z0-9._\-/:]*\Z"
)

#: What separates one fallback spec from the next in a single environment
#: variable — ``ASSISTANT_FALLBACK_MODELS=openai:gpt-5,anthropic:claude-x``.
_SPEC_SEPARATOR: Final = ","


def _model_spec_is_well_formed(value: str) -> str:
    """Reject a model spec that is not ``"provider:model"`` shaped.

    A malformed spec is a configuration mistake, and this is the last moment it
    can be reported as one: pydantic-ai resolves a spec **lazily, at the first
    completion**, so an unvalidated typo surfaces as a ``ModelError`` on a user's
    request rather than at load. That matters most for a *fallback*, which is only
    ever reached once the primary has already failed — see ADR-0062 §2.

    Args:
        value: The spec as configured.

    Returns:
        The spec unchanged.

    Raises:
        ValueError: If the spec is not ``"provider:model"`` shaped.
    """
    if _MODEL_SPEC_PATTERN.match(value) is None:
        msg = (
            f"malformed model spec {value!r}; expected pydantic-ai's "
            f"'provider:model' form, e.g. 'anthropic:claude-opus-4-8'"
        )
        raise ValueError(msg)
    return value


def _split_model_specs(value: object) -> object:
    """Parse a comma-separated list of model specs from a single string.

    pydantic-settings treats a list- or tuple-typed field as *complex* and parses
    its environment value as **JSON**, which would make the fallback list read
    ``ASSISTANT_FALLBACK_MODELS='["openai:gpt-5"]'`` — quoting, brackets, and a
    parse error that names JSON rather than the mistake. ``NoDecode`` on the field
    turns that decoding off so the raw string arrives here instead; this is
    pydantic-settings' own documented hook for the case, so source precedence
    (environment over ``.env`` over defaults) is untouched — the value is still
    resolved by the ordinary source chain and only its *decoding* changes.

    Whitespace around a spec is stripped and empty segments are dropped, so a
    trailing comma or a space after one is not a malformed spec. An empty or
    all-whitespace value therefore means "no fallbacks", the same as omitting the
    variable.

    Only an **exact** built-in ``str``, ``list``, or ``tuple`` is accepted — a
    ``str`` is parsed as above; a ``list`` or ``tuple`` falls through untouched,
    as tests and ``Settings(...)`` callers pass. **Anything else is refused**,
    not silently coerced. This is an allowlist rather than a denylist of the
    unordered types on purpose: pydantic's lax mode would turn any iterable into
    a tuple in traversal order, and ADR-0062 §1 makes the *written* order the
    operator's statement of preference, so an input whose order is not a
    statement — a ``set``/``frozenset``, a one-shot iterator, or any other
    iterable that merely happens to iterate in some order — would let the
    router's primary fallback differ between processes for one configuration
    (issue #359). Naming only the ordered forms that are accepted closes that
    class completely, where a denylist would miss a custom unordered iterable
    that is neither a set nor an iterator.

    **Exact** type, not ``isinstance``, and that is load-bearing: a *subclass*
    can override the very method the order rests on — a ``list``/``tuple``
    subclass its ``__iter__``, a ``str`` subclass its ``split`` — to yield its
    contents in an order of its choosing (a set's, say), so ``isinstance`` would
    readmit exactly the nondeterminism this refuses. Requiring the built-in makes
    that step the uninterceptable C one, so the stored order is the order — the
    same reason, and the same defence, as :func:`canonical_utc` accepting only an
    exact ``datetime``. The operator-facing path is unaffected: an environment
    variable and a ``.env`` entry both arrive as an exact ``str``, so this only
    ever constrains untyped code constructing :class:`Settings` directly.

    Args:
        value: The raw configured value.

    Returns:
        A tuple of specs if ``value`` was an exact ``str``; an exact ``list`` or
        ``tuple`` unchanged.

    Raises:
        ValueError: If ``value`` is anything else, whose order cannot be trusted
            to carry the operator's preference.
    """
    if type(value) is str:
        return tuple(part.strip() for part in value.split(_SPEC_SEPARATOR) if part.strip())
    if type(value) is list or type(value) is tuple:
        return value
    if isinstance(value, AbstractSet):
        unordered = "an unordered set"
    elif isinstance(value, Iterator):
        unordered = "a one-shot iterator"
    else:
        unordered = f"a {type(value).__name__}"
    msg = (
        f"fallback_models must be an ordered sequence (a comma-separated string, a list, or "
        f"a tuple), not {unordered}: ADR-0062 §1 makes the written order the router's "
        f"preference, so an order-free value would let the primary fallback vary between "
        f"processes for one configuration"
    )
    raise ValueError(msg)


#: A pydantic-ai ``"provider:model"`` spec, validated for form.
_ModelSpec = Annotated[str, AfterValidator(_model_spec_is_well_formed)]


class EmbedderKind(StrEnum):
    """Which :class:`~ai_assistant.core.protocols.Embedder` the app wires (ADR-0006 §2).

    A **mode selector**, not a free-form model spec: ADR-0024 vendors exactly one
    on-device model (there is no arbitrary-model path), so the only choice this
    exposes is *which of the two realizable embedders* the composition root wires
    into the memory store. It is deliberately not the ``"provider:model"`` shape
    :data:`_ModelSpec` carries — that names one of a family of chat models, whereas
    here there is a single vendored embedder and its deterministic test stand-in.

    Values:
        ON_DEVICE: The vendored, on-device model (``FastEmbedEmbedder``, ADR-0024).
            The default, because "on-device embedding is the default" is ADR-0006
            §2's firm decision: memory content is Tier-1 personal data (ADR-0004)
            and must not leave the device merely to be indexed.
        HASHING: The deterministic, dependency-free ``HashingEmbedder``. Its
            similarity is **not** semantic (a hashed bag-of-words); it exists for
            tests, offline use, and CI, where loading the real ONNX model is
            undesirable. Selecting it makes retrieval non-semantic, so it is never
            the default.
    """

    ON_DEVICE = "on-device"
    HASHING = "hashing"


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
    default_model: _ModelSpec = Field(
        default="anthropic:claude-opus-4-8",
        description="Default model in pydantic-ai 'provider:model' form.",
    )

    # The rest of the router's preference order (ADR-0062, #353). The composition
    # root routes over ``(default_model, *fallback_models)``, so an empty list —
    # the default, and what an unset deployment gets — reproduces today's
    # single-route behaviour exactly.
    #
    # Comma-separated in the environment, not JSON: see ``_split_model_specs``.
    # A duplicate is refused rather than accepted (``_fallbacks_are_alternatives``);
    # and a route's *model* override (ADR-0013 §2, one provider appearing as
    # several routes) is deliberately not expressible here — ADR-0062 §4.
    fallback_models: Annotated[
        tuple[_ModelSpec, ...], NoDecode, BeforeValidator(_split_model_specs)
    ] = Field(
        default=(),
        description=(
            "Further models to route to when the default fails, most preferred "
            "first, comma-separated (e.g. 'openai:gpt-5,anthropic:claude-x')."
        ),
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

    # --- Memory ----------------------------------------------------------
    # Which embedder the composition root wires into the persistent memory store
    # (ADR-0006 §2). The default is the on-device model, because "on-device
    # embedding is the default" is ADR-0006 §2's firm privacy decision (ADR-0004):
    # memory content is embedded to be indexed, and that content must not leave the
    # device merely to build an index. A mode selector rather than a model spec —
    # ADR-0024 vendors exactly one embedding model, so the only realizable choices
    # are that model and the deterministic ``HashingEmbedder`` for tests/offline/CI
    # (which makes retrieval non-semantic, hence never the default). Parsed from its
    # member value in the environment (``ASSISTANT_EMBEDDER=hashing``); anything off
    # the two members is refused at load as a ConfigurationError.
    embedder: EmbedderKind = Field(
        default=EmbedderKind.ON_DEVICE,
        description=(
            "Which embedder backs semantic memory retrieval: 'on-device' (the "
            "default, ADR-0006 §2) or 'hashing' (deterministic, non-semantic; "
            "tests/offline/CI)."
        ),
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
    def _fallbacks_are_alternatives(self) -> Settings:
        """Require every fallback to name a model the router does not already try.

        A route that repeats an earlier one is never reached in a state where it
        could succeed: routing moves on only after the earlier route failed
        *routably*, and a routable failure — the provider is down, throttled, or
        refusing our credentials (``ModelError.routable``) — is a property of the
        provider, not of the individual request. So the duplicate re-sends the
        same prompt to the same place, pays for it, and fails the same way.

        Refusing it rather than silently collapsing it is the point: a duplicate
        is a reliable sign the operator meant something else (a second vendor, or
        a different model at the same one), and deduplicating it quietly would
        leave them believing they had a fallback they do not have. This is the
        same reasoning as refusing a malformed spec, applied to a spec that is
        well-formed but useless — ADR-0062 §3.

        Raises:
            ValueError: If a fallback repeats ``default_model`` or an earlier
                fallback.
        """
        seen = {self.default_model: "default_model"}
        for position, spec in enumerate(self.fallback_models, start=1):
            origin = seen.get(spec)
            if origin is not None:
                msg = (
                    f"fallback_models[{position - 1}]={spec!r} repeats {origin}; "
                    f"a repeated route is never tried in a state where it could "
                    f"succeed, so name a different model or drop it"
                )
                raise ValueError(msg)
            seen[spec] = f"fallback_models[{position - 1}]"
        return self

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
