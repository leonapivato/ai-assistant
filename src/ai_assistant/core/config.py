"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
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
from ai_assistant.core.types import Reversibility, RiskLevel, describe_untrusted

#: The string an operator sets a setting to in the environment to select its
#: ``None`` value — "disable this entirely". Environment variables arrive as
#: strings, so any nullable setting whose *default* is not ``None``
#: (``confirm_at_risk``, ``confirm_at_reversibility``, ``episode_retention``)
#: would otherwise be un-disable-able from the environment: omitting the variable
#: restores the default, and neither a scale member nor a duration literal spells
#: ``None``. Case-insensitive, and distinct from every ``RiskLevel`` and
#: ``Reversibility`` member value and from every duration form, so it cannot
#: collide with a real value on any field that opts into it.
_DISABLE_SENTINEL = "none"


def _disabled_if_sentinel(value: object) -> object:
    """Map the disable sentinel to ``None`` before the field's own validation.

    A per-field :class:`BeforeValidator` rather than the model-wide
    ``env_parse_none_str``: that switch would turn a literal ``"none"`` into
    ``None`` on *every* setting, so no other field could ever take ``"none"`` as
    a value in its own right — it would arrive as ``None`` and be judged against
    that field's own type instead. Restricting the sentinel to the fields that
    opt in keeps the disable path where it belongs, and leaves every other field
    free to say for itself what ``"none"`` means. Any other value — a scale member, an
    enum instance passed directly, a duration, an already-``None`` — falls through
    unchanged, so bad input is still refused by the validation that follows.
    """
    if isinstance(value, str) and value.strip().lower() == _DISABLE_SENTINEL:
        return None
    return value


#: A permission threshold on the risk / reversibility scale, or ``None`` to
#: disable that gate. The :class:`BeforeValidator` accepts the environment
#: disable sentinel (:data:`_DISABLE_SENTINEL`) as ``None``.
_RiskThreshold = Annotated[RiskLevel | None, BeforeValidator(_disabled_if_sentinel)]
_ReversibilityThreshold = Annotated[Reversibility | None, BeforeValidator(_disabled_if_sentinel)]

# The duration alias that also carries this sentinel (``_OptionalDuration``) is
# defined further down, beside ``_only_a_duration``: it composes this validator
# with that one, so it cannot be stated before that one exists.


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


def _exactly_an_integer(value: object) -> object:
    """Refuse a value that is not an integer but would be coerced into one.

    pydantic's non-strict ``int`` coercion accepts ``True`` as ``1`` because
    ``bool`` is an ``int`` subclass, so ``Settings(observation_batch_size=True)``
    loaded a one-item batch instead of refusing a flag where a count belongs — and
    every bound the field carries (``ge``, ``le``, ``lt``) is satisfied by the
    ``1`` that arrives, so nothing downstream can tell the difference.

    The code **below** settings already refuses this, on the stated ground that a
    flag is not a count: ``ObservationStage._check_batch_size``,
    ``LearningLoop._check_tuning``, ``Engine.__init__``, and
    ``ModelBackedObserver._check_bound`` each exclude ``bool`` before their range
    check. Because :class:`Settings` hands them an *already coerced* integer,
    those guards can never fire on the settings path; they only ever protect the
    constructor seam a test or a second composition root reaches directly. This
    validator makes the configuration layer state the same rule the four layers
    under it already state, rather than leaving it the one layer that does not
    (issue #471).

    An **allowlist of the two forms an integer setting is ever supplied in**, not
    a denylist of ``bool``, and that is load-bearing: ``bool`` is not the only type
    that converts to an integer while meaning something else. ``numpy.bool_`` is a
    flag by any reading and is *not* a ``bool`` subclass, so a denylist named after
    ``bool`` would let ``np.bool_(True)`` through to the same ``1`` — and ``numpy``
    is a direct dependency here (ADR-0024's embedder), so that is a value this
    codebase can actually produce. Naming what is accepted closes the class
    completely, where a denylist would have to grow a case for every foreign
    scalar; the same allowlist reasoning, for the same reason, as
    :func:`_split_model_specs`.

    The two forms:

    - An **exact** ``int``. Exact, not ``isinstance``, because every value this
      refuses — ``bool``, and any other ``int`` subclass whose instances mean
      something other than their integer value — is precisely an ``isinstance``
      match. A ``float``, a ``Decimal``, and a foreign numeric scalar are refused
      with it, which is what the layers below already do: ``RetryPolicy`` checks
      ``type(self.max_attempts) is not int``, and ``_check_batch_size`` refuses a
      ``float`` "rather than compared, since a non-integral limit reaches
      ``ConversationStore.turns`` and fails far from the mistake".
    - A ``str``, which is what an environment variable and a ``.env`` entry are;
      it falls through to the field's ordinary parsing, so the operator-facing
      path is untouched. ``isinstance`` rather than exact here, deliberately: the
      string is *re-parsed* into an integer rather than trusted for its identity,
      so a subclass can misrepresent nothing by being one — unlike a ``str``
      subclass in :func:`_split_model_specs`, which can override the ``split``
      the fallback order rests on.

    **Reachable only from untyped code constructing** :class:`Settings`
    **directly**, the same reachability :func:`_split_model_specs`' guard was
    written for (#359): ``ASSISTANT_OBSERVATION_BATCH_SIZE=True`` already fails
    int parsing at load, so no environment or ``.env`` value reaches this.

    Args:
        value: The raw configured value.

    Returns:
        ``value`` unchanged, for the field's own validation to judge.

    Raises:
        ValueError: If ``value`` is neither an exact ``int`` nor a ``str``.
    """
    # The allowlist below already refuses a ``bool`` — it is not an exact ``int``.
    # This branch changes the *message*, not the outcome: ``bool`` is the case
    # #471 was filed for and the one the four layers below name in their own
    # errors, so it is worth saying in their words rather than as one more
    # unaccepted type.
    if isinstance(value, bool):
        msg = (
            f"expected an integer, got the flag {describe_untrusted(value)}: a flag is not a count"
        )
        raise ValueError(msg)
    if type(value) is int or isinstance(value, str):
        return value
    # `describe_untrusted` rather than `!r`, for both the value and its type: this
    # branch is reached by *arbitrary* objects, and a `__repr__` that raises would
    # otherwise replace the `ValueError` pydantic turns into a `ValidationError`
    # with whatever it threw — the diagnostic destroying the diagnosis, which is
    # the promise that helper exists to keep. Pydantic renders such an input as
    # "<unprintable X object>" on its own, so without this the guard would be the
    # only thing in the chain that could not survive being told about it. The bool
    # branch above cannot be reached by one — `bool` has two values and a final
    # type — but uses the same helper so this function has one rule, not two.
    msg = (
        f"expected an integer or its decimal spelling, got {describe_untrusted(value)} "
        f"of type {describe_untrusted(type(value))}; only an exact int or a str is "
        f"accepted, so nothing that merely converts to an integer — a foreign boolean "
        f"scalar, a float, a Decimal — is silently coerced into one"
    )
    raise ValueError(msg)


#: An integer-valued setting: an exact ``int``, or the ``str`` an operator spells
#: one as. See :func:`_exactly_an_integer` for what it refuses and why.
#: Applied to **every** ``int``-typed field on :class:`Settings`, including the two
#: hour-of-day ordinals, because the defect is a property of the type rather than
#: of any one field and fixing a subset would leave the model inconsistent with
#: itself (#471). ``tests/core/test_config.py`` pins that coverage per field.
_IntegerSetting = Annotated[int, BeforeValidator(_exactly_an_integer)]


def _only_a_real_number(value: object) -> object:
    """Refuse a value that is not a real number but would be coerced into one.

    The ``float`` half of the defect :func:`_exactly_an_integer` closes for
    integers (issue #500, split from #471). pydantic's non-strict ``float``
    coercion accepts ``True`` as ``1.0`` — ``bool`` is an ``int`` subclass and an
    integer converts to a float — so ``Settings(model_timeout_seconds=True)``
    loaded a one-second deadline rather than refusing a flag where a measurement
    belongs. Both bounds these fields carry (``gt=0``, ``allow_inf_nan=False``)
    are satisfied by the ``1.0`` that arrives, so nothing downstream can tell.

    The code **below** settings already refuses it. ``RetryPolicy.__post_init__``
    is the sole consumer of all three real-valued settings and excludes ``bool``
    for precisely these three knobs, on the stated ground that "a boolean timeout
    is a mistake worth naming rather than coercing to 1.0". Because
    ``RetryPolicy.from_settings`` is handed an *already coerced* float, that
    exclusion can never fire on the settings path; it only ever protects the
    constructor seam. This validator makes the configuration layer state the rule
    the layer under it already states — the same argument, on a second type, that
    #471 made for counts.

    An **allowlist of the forms a real-valued setting is supplied in**, not a
    denylist of ``bool``, for the reason :func:`_exactly_an_integer` sets out:
    ``numpy.bool_`` is a flag, is *not* a ``bool`` subclass (nor an ``int`` or
    ``float`` one), coerces to the same ``1.0``, and ``numpy`` is a direct
    dependency here (ADR-0024's embedder). A denylist named after ``bool`` would
    let it through to exactly this failure, one type name away.

    The accepted forms, and why each is spelled as it is:

    - A ``float``, by ``isinstance``. A subclass is safe to admit *and provably
      so*: pydantic normalises one to a built-in ``float`` before storing it, so
      the value the rest of the system sees is a plain float whatever was offered
      — and no ``float`` subclass impersonates a flag anyway, since ``bool`` is
      not one. Exactness here would only refuse ``numpy.float64``, which means
      precisely its own value.
    - An **exact** ``int``, because a whole number of seconds is how an operator
      or a caller writes one (``model_timeout_seconds=60``) and ``RetryPolicy``
      accepts it too (``isinstance(value, (int, float))``) — refusing it would
      make configuration stricter than the layer it configures, for no gain.
      Exact rather than ``isinstance``, because ``isinstance(True, int)`` *is*
      the defect: only exactness refuses the flag while still accepting the
      integer it impersonates.
    - A ``str``, which is what an environment variable and a ``.env`` entry are;
      it falls through to the field's ordinary parsing, so the operator-facing
      path is untouched. ``isinstance``, for the reason
      :func:`_exactly_an_integer` gives — the string is re-parsed rather than
      trusted for its identity, so a subclass can misrepresent nothing by being
      one.

    **Reachable only from untyped code constructing** :class:`Settings`
    **directly** (#500): ``ASSISTANT_MODEL_TIMEOUT_SECONDS=True`` already fails
    float parsing at load, so no environment or ``.env`` value reaches this.

    Args:
        value: The raw configured value.

    Returns:
        ``value`` unchanged, for the field's own validation to judge.

    Raises:
        ValueError: If ``value`` is none of the three accepted forms.
    """
    # As in `_exactly_an_integer`, the allowlist below already refuses a `bool`;
    # this branch changes the *message*, not the outcome, so the mistake is named
    # in the words `RetryPolicy` uses for it rather than reported as one more
    # unaccepted type.
    if isinstance(value, bool):
        msg = (
            f"expected a real number, got the flag {describe_untrusted(value)}: "
            f"a flag is not a measurement"
        )
        raise ValueError(msg)
    if isinstance(value, float) or type(value) is int or isinstance(value, str):
        return value
    # `describe_untrusted` rather than `!r`, for both the value and its type, for
    # the reason spelled out in `_exactly_an_integer`: this branch is reached by
    # arbitrary objects, and a `__repr__` that raises would otherwise replace the
    # `ValueError` pydantic turns into a `ValidationError` with whatever it threw.
    msg = (
        f"expected a real number or its decimal spelling, got {describe_untrusted(value)} "
        f"of type {describe_untrusted(type(value))}; only a float, an exact int, or a str "
        f"is accepted, so nothing that merely converts to a real number — a foreign boolean "
        f"scalar, a Decimal, a NumPy integer — is silently coerced into one"
    )
    raise ValueError(msg)


#: A real-valued setting: a ``float``, an exact ``int``, or the ``str`` an operator
#: spells one as. See :func:`_only_a_real_number` for what it refuses and why.
#: Applied to **every** ``float``-typed field on :class:`Settings`, because the
#: defect is a property of the type rather than of any one field (#500).
#: ``tests/core/test_config.py`` pins that coverage per field.
_RealSetting = Annotated[float, BeforeValidator(_only_a_real_number)]


def _only_a_duration(value: object) -> object:
    """Refuse a value that is not a duration but would be coerced into one.

    The ``timedelta`` half of #500. pydantic's non-strict ``timedelta`` coercion
    reads a bare number as *seconds*, and ``True`` is a number by inheritance, so
    ``Settings(conversation_tombstone_grace=True)`` loaded a one-second grace
    rather than refusing a flag where a duration belongs — and one second clears
    the ``gt=timedelta(0)`` every one of these fields carries, so the flag loads
    as a plausible horizon exactly as it did for a count and a measurement.

    The refusal has to be **narrower than "anything that is not a timedelta"**:
    every one of these settings is documented as parsed from an ISO-8601 or
    ``HH:MM:SS`` string in the environment, and a bare number of seconds is a
    form pydantic has always accepted from a direct caller. Refusing either would
    break a legitimate input to close a defect neither causes — so this names the
    forms a duration setting is supplied in, and refuses only what is left.

    The accepted forms:

    - A ``timedelta``, by **exact** type. The one place this guard is stricter
      than :func:`_only_a_real_number`, and for a verified reason: pydantic
      *preserves* a ``timedelta`` subclass instance in the model (it does not
      normalise it the way it normalises a ``float`` subclass) while applying
      ``gt`` natively, so a subclass whose comparison operators disagree with its
      own length clears the load-time bound intact and is then handed to the
      subsystems that compare against it. ``ConversationStore``'s reclaim sweep
      is one: ``now - conversation.deleted_at >= self._grace`` puts the
      configured value on the **right** of the comparison, where Python's
      reflected-operand priority hands the decision to the subclass, so a
      week-old tombstone can be made ineligible forever — dropping ADR-0074 §8's
      guarantee without changing a stated setting. Nor can the store's own
      constructor guard catch it: ``isinstance(tombstone_grace, timedelta) or
      tombstone_grace <= timedelta(0)`` admits the subclass by ``isinstance`` and
      then lets it answer the ``<=`` for itself. That is this module's whole
      argument one level deeper — the layer below states a rule it cannot enforce
      on a value configuration has already accepted. Requiring the built-in makes
      those comparisons the uninterceptable ones, the same defence, for the same
      reason, as :func:`_split_model_specs`' exact ``list``.
    - An **exact** ``int`` or an **exact** ``float`` — a number of seconds.
      Exact, because ``isinstance(True, int)`` is the whole defect here: only
      exactness refuses the flag while still accepting the ``1`` it impersonates.
    - A ``str``, the environment and ``.env`` form, re-parsed rather than trusted
      for its identity (hence ``isinstance``), which also carries the disable
      sentinel through to :func:`_disabled_if_sentinel` on the fields that opt in.
    - ``None``, passed through for the field's **own** annotation to judge, which
      is the only thing that knows whether this duration has a ``None`` spelling:
      it does for ``confirmation_ttl`` (no lifetime), ``episode_retention`` and
      ``deferral_ttl`` (ADR-0074 §7, ADR-0078 §6), and deliberately does not for
      ``conversation_tombstone_grace``, where ADR-0074 §8 declines to offer one.
      Deciding that here would duplicate — and could contradict — the annotation.

    An allowlist rather than a denylist of ``bool``, for the reason
    :func:`_exactly_an_integer` sets out at length: ``numpy.bool_`` is a flag that
    is not a ``bool`` subclass, ``numpy`` is a direct dependency, and it coerces
    to the same one second.

    **Reachable only from untyped code constructing** :class:`Settings`
    **directly** (#500): ``ASSISTANT_CONFIRMATION_TTL=True`` already fails
    duration parsing at load.

    Args:
        value: The raw configured value.

    Returns:
        ``value`` unchanged, for the field's own validation to judge.

    Raises:
        ValueError: If ``value`` is none of the accepted forms.
    """
    # Message-only, as in the two guards above: the allowlist would refuse a
    # `bool` regardless, but this is the case #500 was filed for and it is worth
    # naming in the same words.
    if isinstance(value, bool):
        msg = (
            f"expected a duration, got the flag {describe_untrusted(value)}: "
            f"a flag is not a duration"
        )
        raise ValueError(msg)
    if (
        value is None
        or type(value) is timedelta
        or type(value) is int
        or type(value) is float
        or isinstance(value, str)
    ):
        return value
    # `describe_untrusted` for the reason given in `_exactly_an_integer`: the
    # diagnostic must not be able to destroy the diagnosis.
    msg = (
        f"expected a duration, got {describe_untrusted(value)} of type "
        f"{describe_untrusted(type(value))}; only a timedelta, an exact int or float of "
        f"seconds, or the str an operator spells a duration as, is accepted, so nothing "
        f"that merely converts to a duration — a foreign boolean scalar, a Decimal, a "
        f"NumPy scalar — is silently coerced into one"
    )
    raise ValueError(msg)


#: A duration setting with no ``None`` spelling (ADR-0074 §8's tombstone grace).
#: See :func:`_only_a_duration` for the forms it accepts and why.
_DurationSetting = Annotated[timedelta, BeforeValidator(_only_a_duration)]

#: A duration setting whose ``None`` is reached by *omission* — its default is
#: ``None``, so it needs no environment spelling for "unset" and deliberately does
#: not opt into the disable sentinel (``confirmation_ttl``).
_NullableDuration = Annotated[timedelta | None, BeforeValidator(_only_a_duration)]

#: A retention horizon, or ``None`` for "keep forever" — reachable from the
#: environment only through the disable sentinel, since the default is finite
#: (ADR-0074 §7). The nullable duration *with* the sentinel, where
#: :data:`_NullableDuration` is the one without it.
#:
#: pydantic runs the **last** ``BeforeValidator`` listed here first, so
#: :func:`_only_a_duration` sees the value exactly as it was configured and
#: :func:`_disabled_if_sentinel` then maps the sentinel. The order is not
#: load-bearing — the guard accepts both the sentinel ``str`` and the ``None`` it
#: becomes — but it is stated because the reversal is easy to read backwards.
_OptionalDuration = Annotated[
    timedelta | None,
    BeforeValidator(_disabled_if_sentinel),
    BeforeValidator(_only_a_duration),
]


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


#: The per-user data directory's name under ``Path.home()`` — the default
#: :attr:`Settings.data_dir` (ADR-0083 §2). Moved here from the composition root
#: with the field: the *value* is unchanged, so no deployment's directory moves;
#: what changed is that the default now sits beside the setting that names it.
_DEFAULT_DATA_DIRNAME: Final = ".ai-assistant"


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

    # --- The resident process (ADR-0083) ---------------------------------
    # Where the hub's state lives, and how long its graceful drain gets.
    #
    # ``data_dir`` is the hub's most basic configuration item and did not exist
    # as a setting at all: the data directory was only ``build_engine``'s
    # ``data_dir=`` keyword, resolved by a private helper. ADR-0083 §2 makes it a
    # field so it is readable through ``Settings`` like everything else, and §1
    # then makes it the thing **exclusive ownership and the instance lock are
    # keyed to**. ADR-0084 §9 derives the hub's socket path from the same field,
    # deliberately, so a hub and a client cannot disagree about where the data is.
    #
    # **The variable is ``ASSISTANT_DATA_DIR``** — the ``env_prefix`` above
    # applied to the field name. ADR-0083 §2's prose printed
    # ``AI_ASSISTANT_DATA_DIR``, which was wrong when written; its own amendment
    # note and ADR-0084 §9 carry the correction and #535 is the record. The
    # failure that name would cause is **silent**: ``extra="ignore"`` means an
    # operator exporting it gets no error and lands on the default directory.
    #
    # The default is a factory rather than a literal because ``Path.home()`` is
    # read at load, not at import — the same ``~/.ai-assistant`` the composition
    # root resolved before, so no existing behaviour changes and the field is
    # purely additive. ``build_engine`` keeps its ``data_dir=`` keyword, which
    # overrides this when given: it is the injection seam every existing test
    # uses (§2).
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / _DEFAULT_DATA_DIRNAME,
        description=(
            "Directory the hub owns exclusively: the five SQLite stores, the "
            "instance lock, and any transport-local artefact (ADR-0083 §1, §2). "
            "Must be absolute; it is canonicalised at load (ADR-0084 §1)."
        ),
    )

    @field_validator("data_dir")
    @classmethod
    def _data_dir_is_absolute_and_canonical(cls, value: Path) -> Path:
        """Refuse a relative directory, and canonicalise the rest (ADR-0084 §1).

        "A relative value is therefore rejected at settings load, and the path is
        canonicalised before either side derives anything from it." The failure it
        prevents is one nobody would diagnose from its symptom: a hub started at
        boot with a working directory of ``/`` and a setting of ``state`` uses
        ``/state``, while a CLI run from a project directory uses
        ``<project>/state`` — **both read the same setting and disagree**, and
        under ADR-0084 §9 the visible result is a client truthfully reporting the
        hub down. One setting locating both the data and the door is the property
        §9 rests on, and it only holds if the value means one directory.

        Canonicalising **here** rather than in each reader is what makes that true
        by construction: two readers that each resolve are two chances to resolve
        differently, and the composition root and the hub are exactly those two
        readers.

        ``~`` is expanded before the test rather than rejected with the relative
        paths. ``Path`` does no expansion, so ``~/.ai-assistant`` would otherwise
        be refused while the *default* — the very same directory, spelled through
        ``Path.home()`` — is accepted, which is a distinction an operator has no
        way to anticipate.
        """
        expanded = value.expanduser()
        if not expanded.is_absolute():
            msg = (
                f"data_dir must be an absolute path, got {str(value)!r}; a relative "
                f"value resolves against each process's working directory, so the hub "
                f"and a client reading the same setting would reach different "
                f"directories (ADR-0084 §1)"
            )
            raise ValueError(msg)
        return Path(os.path.realpath(expanded))

    # The budget for phase A of the hub's two-phase shutdown (ADR-0083 §4): how
    # long tracked in-flight work is given to finish **on its own** before the
    # remainder is cancelled and awaited unbounded.
    #
    # **The name is §4's, verbatim, and the type is §7's.** §4 names
    # ``Settings.shutdown_drain_seconds, default 30 seconds``; §7 requires that
    # "every duration this ADR adds is a ``timedelta`` refused at load time
    # unless it is finite and strictly positive". A ``float`` of seconds would
    # match the name and break the rule, so the name is kept and the type is a
    # duration — parsed from an ISO-8601 or ``HH:MM:SS`` string in the
    # environment like every other one (``ASSISTANT_SHUTDOWN_DRAIN_SECONDS=PT45S``).
    #
    # ``gt=timedelta(0)`` is not housekeeping here. §7 is explicit that "a
    # ``shutdown_drain_seconds`` of zero silently deletes §4's phase A", and
    # phase A is the whole mechanism that keeps the graceful path reachable
    # before a supervisor's stop timeout turns into ``SIGKILL`` — which destroys
    # exactly the ADR-0029 §4 bookkeeping the drain exists to preserve.
    shutdown_drain_seconds: _DurationSetting = Field(
        default=timedelta(seconds=30),
        gt=timedelta(0),
        description=(
            "How long shutdown waits for in-flight work to finish on its own before "
            "cancelling the remainder and awaiting it (ADR-0083 §4). Positive and finite."
        ),
    )

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

    # Which model reads the episodic stream (ADR-0077 §3). A **first-class named
    # setting** rather than an accident of ``default_model``, because an
    # observation's prompt is accumulated history — the most sensitive data the
    # system holds — and the roadmap demands that choice be explicit and separable
    # from the route the user's answers come from.
    #
    # **Unset — the default — means the observer reads through the route already
    # configured for conversation** (``default_model``). That is chosen over
    # off-by-default and over a required second spec for one reason: it *widens
    # nothing*. ADR-0004 §2's property is that user data reaches only providers the
    # user explicitly configured, and a default naming no new provider cannot
    # breach it; an off-by-default observer would make leg 3 unreachable without
    # configuration, and a required second spec would make the commonest correct
    # setup — one provider used for everything — an error.
    #
    # It is deliberately **not** part of ``fallback_models``' preference order, and
    # the composition root builds it as a route of its own that **never falls
    # back** (ADR-0013 §4, §6): fallback buys reliability by widening the set of
    # providers that see a prompt, and for a deferrable job over accumulated
    # history the reliability is worth nothing and the widening is the one cost
    # that matters. Naming ``default_model`` here explicitly is therefore *not* the
    # same as leaving it unset in general — it is the same route, still without
    # fallback — so no duplicate check applies to it.
    observer_model: _ModelSpec | None = Field(
        default=None,
        description=(
            "Model that reads the episodic stream when observing, in pydantic-ai "
            "'provider:model' form. Unset means the same route conversation uses. "
            "Never falls back, whichever route it names."
        ),
    )

    # Resilience knobs for the model layer. The deadline is per attempt, so the
    # worst-case wall time of a call is roughly
    # ``max_attempts * timeout + total backoff``.
    # ``allow_inf_nan=False`` matters: ``gt=0`` rejects NaN but happily accepts
    # infinity, which would silently disable the deadline or unbound backoff.
    model_timeout_seconds: _RealSetting = Field(
        default=60.0,
        gt=0,
        allow_inf_nan=False,
        description="Deadline for a single model attempt, in seconds.",
    )
    model_max_attempts: _IntegerSetting = Field(
        default=3, ge=1, description="Total model attempts, including the first. 1 disables retry."
    )
    model_backoff_base_seconds: _RealSetting = Field(
        default=0.5,
        gt=0,
        allow_inf_nan=False,
        description="Backoff ceiling after the first failure; doubles per retry.",
    )
    model_backoff_max_seconds: _RealSetting = Field(
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
    working_hours_start: _IntegerSetting = Field(
        default=9, ge=0, le=23, description="First hour of the working-hours window (local)."
    )
    working_hours_end: _IntegerSetting = Field(
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
    confirmation_ttl: _NullableDuration = Field(
        default=None,
        gt=timedelta(0),
        description="Lifetime of a parked confirmation before its answer is refused as stale.",
    )

    # --- Conversations (ADR-0074) ----------------------------------------
    # How long a captured episode is retained, and how long a deleted
    # conversation's tombstone outlives the deletion that stamped it. Both are
    # parsed from an ISO-8601 duration or ``HH:MM:SS`` string in the environment
    # (``ASSISTANT_EPISODE_RETENTION=P7D``, ``ASSISTANT_CONVERSATION_TOMBSTONE_GRACE=PT1H``).
    #
    # ``episode_retention`` **defaults to a finite duration, and that is the whole
    # decision** (ADR-0074 §7). It is the right *shape* to copy from
    # ``confirmation_ttl`` above and exactly the wrong default to inherit: that
    # field defaults to ``None``, which there means "a parked confirmation never
    # goes stale" and here would mean **unbounded episodic retention** — an
    # ever-growing Tier 1 log of everything the user has ever typed, with no cap
    # decision behind it (ADR-0007 §5 deferred size caps), which is precisely what
    # §7 rejects. An implementation that copied the default along with the type
    # would ship the opposite of the ADR while looking like it followed it. So
    # ``None`` here means "keep forever", it is the user's deliberate choice, and it
    # is reachable only by setting the variable to the disable sentinel — which is
    # also what switches conversation reclaim off entirely (§7).
    #
    # ``conversation_tombstone_grace`` is **positive and finite with no ``None``
    # spelling** (§8), because "no grace" and "infinite grace" are the two values
    # that break the deletion protocol — the first drops the index immediately,
    # orphaning the late write the tombstone exists to catch; the second keeps every
    # deleted conversation's index forever — and a nullable field spells one of
    # them. ``gt=timedelta(0)`` refuses the first at load, as ``confirmation_ttl``
    # refuses its own non-positive values.
    episode_retention: _OptionalDuration = Field(
        default=timedelta(days=30),
        gt=timedelta(0),
        description=(
            "How long a captured conversation turn's episode is retained. Finite by "
            "default (ADR-0074 §7); set it to 'none' to keep episodes forever, which "
            "also stops idle conversations being reclaimed."
        ),
    )
    conversation_tombstone_grace: _DurationSetting = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
        description=(
            "How long a deleted conversation's tombstone survives the deletion, so a "
            "capture that commits late is still swept (ADR-0074 §8). Positive and finite."
        ),
    )

    # --- Observation (ADR-0077) ------------------------------------------
    # The two per-call bounds on an observation pass. Both are **named here rather
    # than left to the implementation** (ADR-0077 §1, §2, following ADR-0074 §9.3):
    # two conforming stages picking 20 and 2,000 would send categorically different
    # amounts of Tier 1 data to a model while each believed it conformed.
    #
    # ``observation_batch_size`` is how many of a conversation's most recent turns
    # one pass reads. Positive, because a zero batch observes nothing while
    # reporting health; and bounded **above** by ``2**63`` because the batch is
    # read through ``ConversationStore.turns``, whose ``limit`` outside
    # ``[0, 2**63)`` is a ``ValueError`` by its own contract. A setting the store
    # would refuse must fail at load, not at the first observation — which is what
    # ``load_settings`` promises for every other value here. The default is
    # deliberately small: a handful of exchanges, not a month of transcript,
    # because this batch is both a prompt and an egress.
    #
    # ``observation_max_proposals`` is the most beliefs one pass may return; excess
    # is discarded rather than queued (a queue is durable state nothing ratifies,
    # and the episodes remain in the store for a later pass). Five is ADR-0077 §2's
    # selectivity bar in numbers — a batch that genuinely yields more durable
    # beliefs than that is a batch worth observing twice.
    observation_batch_size: _IntegerSetting = Field(
        default=20,
        ge=1,
        lt=2**63,
        description=("How many of a conversation's most recent turns one observation pass reads."),
    )
    observation_max_proposals: _IntegerSetting = Field(
        default=5,
        ge=1,
        description="The most beliefs one observation pass may propose; excess is discarded.",
    )

    # --- Deferred questions (ADR-0078) -----------------------------------
    # The two tunings the deferral queue is built with. Both reach the store's
    # **constructor** and are validated there in the `_check_tuning` shape
    # (ADR-0022 §4a), so each is read once per store and never per operation — which
    # is the other half of ADR-0078 §2's rule that live configuration never reaches
    # back into a question already asked. `deferral_ttl` is stamped onto each record
    # as its `retention`/`expires_at` at admission; nothing consults the setting
    # again, so shortening it tomorrow cannot drop a rejected key 29 days early and
    # re-ask a question the user already declined.
    #
    # `deferral_ttl` is parsed from an ISO-8601 duration or `HH:MM:SS` string
    # (`ASSISTANT_DEFERRAL_TTL=P7D`), and **defaults to a finite 30 days, which is
    # the whole decision** (ADR-0078 §6). The codebase holds both shapes and the
    # choice between them is the mistake ADR-0074 §7 warned about:
    # `confirmation_ttl` above defaults to `None`, which there means a parked
    # confirmation never goes stale, and here would mean a never-expiring queue of
    # machine-asked questions — precisely the undignified pile §7 exists to prevent.
    # A permission confirmation gates an action the user just asked for and is
    # worthless once stale; a memory deferral is generated *by the system*, at
    # whatever rate the observer runs. So this belongs with `episode_retention`, and
    # 30 days is deliberately that field's horizon: a deferred question is about a
    # belief, and for an observed one the *evidence* is episodes on that clock, so a
    # question outliving them would ask the user to adjudicate something the system
    # can no longer explain. `None` — reachable only through the disable sentinel —
    # is the user's deliberate "ask me forever": the question never lapses and its
    # record is never purged, in the same words `episode_retention` already uses.
    #
    # `deferral_queue_limit` bounds the **answerable** queue (`PENDING` and before
    # its deadline); lapsed and resolved rows awaiting a sweep do not count against
    # it, so a queue cannot be held shut by questions nobody can answer. At the cap
    # `defer` refuses the new question rather than evicting an old one, and the
    # refusal is reported to whoever proposed. It is **strictly positive with no
    # "unlimited" spelling**: a cap of 0 is at capacity before its first admission,
    # so every `ASK_USER` proposal is refused and the drop ADR-0078 exists to end
    # returns in full, by configuration, while the system reports health — exactly
    # the class of value ADR-0022 §4a refuses at construction, and the reason
    # `confirmation_ttl` and `conversation_tombstone_grace` both carry their own
    # positive bound. An *uncapped* queue is what §7 exists to prevent, and
    # `deferral_ttl`'s `None` is already the deliberate escape at the other axis.
    # The default matches the bounded default page size of `DeferralStore.pending`,
    # so the whole answerable queue fits one page and §7's "the cap is legible from
    # the first page" is true in the strongest sense — and fifty unanswered
    # machine-asked questions is already past dignified. `lt=2**63` keeps it inside
    # the integer domain every count in these backends lives in, as
    # `observation_batch_size` does for its own.
    deferral_ttl: _OptionalDuration = Field(
        default=timedelta(days=30),
        gt=timedelta(0),
        description=(
            "How long a deferred memory question stays answerable, stamped onto each "
            "question at admission (ADR-0078 §6). Finite by default; set it to 'none' to "
            "be asked forever, which also stops those questions ever being purged."
        ),
    )
    deferral_queue_limit: _IntegerSetting = Field(
        default=50,
        gt=0,
        lt=2**63,
        description=(
            "The most answerable deferred questions the queue holds; beyond it a new "
            "question is refused rather than an old one evicted (ADR-0078 §7). Positive, "
            "with no unlimited spelling."
        ),
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
    # (:data:`_DISABLE_SENTINEL`); this matters most for the two confirm
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
