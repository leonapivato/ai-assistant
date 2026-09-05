"""Application configuration, loaded from the environment and ``.env``.

Settings are validated once at startup via pydantic-settings. Read secrets and
tunables from here rather than calling ``os.environ`` directly, so every
configuration knob is discoverable, typed, and validated in one place.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import Reversibility, RiskLevel, describe_untrusted

#: The string an operator sets a setting to in the environment to select its
#: ``None`` value — "disable this entirely". Environment variables arrive as
#: strings, so any nullable setting whose *default* is not ``None``
#: (``confirm_at_risk``, ``confirm_at_reversibility``, ``episode_retention``,
#: ``deferral_ttl``, ``trace_retention``)
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
    flag is not a count: ``_check_batch_size`` in ``orchestration/observation.py``,
    ``_check_tuning`` in ``orchestration/loop.py``, ``Engine.__init__``, and
    ``_check_bound`` in ``learning/observer.py`` each exclude ``bool`` before their
    range check. Because :class:`Settings` hands them an *already coerced* integer,
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
      it does for ``confirmation_ttl`` (no lifetime), ``episode_retention``,
      ``deferral_ttl`` and ``trace_retention`` (ADR-0074 §7, ADR-0078 §6,
      ADR-0119 §10), and deliberately does not for
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


def _split_configured_list(value: object) -> object:
    """Parse a comma-separated list out of a single environment string.

    pydantic-settings treats a tuple-typed field as *complex* and parses its
    environment value as **JSON**, which would make an owner write
    ``ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES='["nPHONE1CNTRL"]'`` — quoting,
    brackets, and a parse error naming JSON rather than the mistake. ``NoDecode``
    on the field turns that decoding off so the raw string arrives here, which is
    pydantic-settings' own documented hook: source precedence is untouched and
    only the *decoding* changes. :func:`_split_model_specs` takes the same shape
    for the same reason.

    **What it does not borrow from that function is the ordered-input guard**, and
    the difference is what the order means. ADR-0062 §1 makes the written order of
    ``fallback_models`` the operator's statement of preference, so an input whose
    order is not a statement had to be refused; ADR-0174 §8 rules the opposite for
    these two lists — "The list is read as a **set** of identities… order carries
    no meaning" — so there is nothing an unordered input could misrepresent, and a
    refusal keyed on ordering would be ceremony rather than a defence.

    Whitespace around an element is stripped and empty segments are dropped, so a
    trailing comma is not an element. An empty or all-whitespace value therefore
    means "no elements", the same as omitting the variable.

    Args:
        value: The raw configured value.

    Returns:
        A tuple of elements if ``value`` was an exact ``str``; anything else
        unchanged, for the field's own validation to judge.
    """
    if type(value) is str:
        return tuple(part.strip() for part in value.split(_SPEC_SEPARATOR) if part.strip())
    return value


#: A list an owner writes as one comma-separated environment variable. Empty is a
#: real value on both fields that use it, and it is their default.
_ConfiguredList = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_split_configured_list)]


def _refuse_a_non_overlay_address(
    value: str | None, *, setting: str, loopback_is: str, unset_means: str
) -> str | None:
    """Refuse at load what ADR-0124 §2 forbids a listener to bind.

    > The remote listener binds only to an address that exists on that overlay. It
    > may not bind a wildcard address, an address of a physical interface, or any
    > address reachable from the public internet, and a configuration that would
    > have it do so is refused at load time rather than bound.

    **What is decidable from the string alone is decided here, and the rest is
    decided before the bind rather than by it.** A wildcard, a name, a loopback or
    link-local address and a globally-routable one are properties of the value;
    *which* private address belongs to the overlay is a fact only the overlay agent
    holds, so the process that binds refuses an address the agent does not place on
    the overlay. Neither half is sufficient alone — this one would pass a LAN
    address on ``eth0``, and the agent check alone would let a wildcard reach a
    process that has already opened its stores — and together they are "refused…
    rather than bound".

    **A name is refused rather than resolved.** Resolving one is a lookup whose
    answer another party supplies, and the address a listener binds would then be a
    fact about a resolver rather than about this deployment; ADR-0124 §1's rule that
    a destination never comes "from a discovery mechanism" is the same principle on
    the other end of the hop.

    **Shared by two settings rather than restated for the second**, which is
    ADR-0174 §8's own instruction: ``gateway_remote_address`` carries "the five
    refusals ``hub_remote_address`` already carries, **in the same shape** and for
    the same reasons (ADR-0124 §2)". Two copies of five conditions is the drift
    ADR-0089 §2 records finding in the section defining its own prevention, so what
    is per-caller here is only the wording a refusal uses — the setting to correct,
    what its loopback sibling is, and what unsetting it leaves running.

    Args:
        value: The configured address, or ``None`` when the listener is off.
        setting: The field being validated, so a refusal names the one to edit.
        loopback_is: What this listener's loopback sibling is, as a clause
            completing "a loopback address, which is not on the overlay; …".
        unset_means: What unsetting the field leaves bound, as a noun phrase
            completing "or unset it to …".

    Returns:
        The address, stripped of surrounding space, or ``None``.

    Raises:
        ValueError: If the value is not an IP address, or is one ADR-0124 §2
            forbids. Reported as a ``ConfigurationError`` by ``load_settings``,
            which is a stay-down deployment fault (ADR-0083 §5).
    """
    if value is None:
        return None
    text = value.strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        msg = (
            f"{setting}={value!r} is not an IP address. The remote listener "
            f"binds a literal address that exists on the overlay (ADR-0124 §2); a name "
            f"would make the bound address a fact about a resolver. Run your overlay "
            f"agent's status command and use the address it reports for this machine"
        )
        raise ValueError(msg) from exc
    # A sequence of pairs rather than a mapping keyed on the predicate: there
    # are only two booleans, so a dictionary would collapse five conditions
    # into two entries and silently report the wrong reason.
    forbidden = (
        (
            address.is_unspecified,
            "a wildcard address, which would put the listener on every interface this "
            "machine has, including any reachable from the public internet",
        ),
        (address.is_loopback, f"a loopback address, which is not on the overlay; {loopback_is}"),
        (address.is_multicast, "a multicast address, which no listener may hold"),
        (address.is_link_local, "a link-local address, which is not on the overlay"),
        (
            address.is_global,
            "reachable from the public internet, where the population that can attempt "
            "the credential is everyone — which is the door ADR-0124 §2 refuses to open",
        ),
    )
    for holds, reason in forbidden:
        if holds:
            msg = (
                f"{setting}={value!r} is {reason}. Configure the address your "
                f"overlay agent reports for this machine, or unset it to {unset_means}"
            )
            raise ValueError(msg)
    return text


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

#: ADR-0084 §3's named default for :attr:`Settings.hub_max_frame_bytes` — 16 MiB.
#: Set generously on purpose: exceeding it must surface as an error a client can
#: read rather than as a quietly shortened payload, and ADR-0084 §3 sizes it so
#: that a belief whose evidence has grown past the limit is unreachable for any
#: belief this system currently produces while #473's semantic bound is open.
_DEFAULT_MAX_FRAME_BYTES: Final = 16 * 1024 * 1024

#: ADR-0134 §1's floor for the delivery outbox's byte bound — the 1 MiB ADR-0131
#: §5a named, kept as the lower half of the rule that replaced it. It binds only
#: where a deployment has lowered `hub_max_frame_bytes` beneath it; everywhere
#: else the frame ceiling is the greater of the two and the range decides.
_MIN_OUTBOX_BYTES: Final = 1024 * 1024

#: ADR-0085 §8d's floor. 512 for the envelope reserve plus 256 for either connect
#: payload is 768, and 1024 leaves room for both handshake frames and a small
#: request besides. Below it the hub "would pass every startup step in ADR-0083 §3
#: and then refuse every client, including the CLI — indistinguishable from a hub
#: that is down, which is ruling 4's failure" (ADR-0084 §3).
#:
#: The figure is repeated here rather than imported because ``core`` depends on
#: nothing else in ``ai_assistant`` (golden rule 2), and the two packages that hold
#: it as a constant — ``orchestration`` and ``wire`` — are both below that rule.
_MIN_FRAME_BYTES: Final = 1024

#: ADR-0084 §3's upper bound: a frame must be **representable by the framing**,
#: and the 4-byte big-endian prefix caps what follows it at ``2**32 - 1`` bytes.
#: Without this "a setting of 5 GiB would be accepted at load and would be a limit
#: the contract declares but the wire cannot encode, so the in-process engine would
#: accept a value the client provably cannot send".
_MAX_FRAME_BYTES: Final = 2**32 - 1

#: ADR-0093 §7a's ceiling on either arm of the calendar window. Ten years is far
#: past any calendar anyone reads and far short of the representable limit, which
#: is the whole requirement of the number: it exists so that
#: ``read_at ± calendar_window_*`` is always a representable instant.
#:
#: Repeated here rather than imported from ``ai_assistant.readers`` for the reason
#: ``_MIN_FRAME_BYTES`` is repeated: ``core`` depends on nothing else in
#: ``ai_assistant`` (golden rule 2), and the package holding it as a constant is
#: below that rule. ``tests/readers/test_calendar_settings.py`` pins the two
#: together, so the duplication cannot drift.
_MAX_CALENDAR_WINDOW: Final = timedelta(days=3650)

#: ADR-0140 §12's ceiling on the email window's one arm, for ADR-0093 §7a's reason
#: applied unchanged: ``> 0`` alone admits ``timedelta.max``, and the ceiling is
#: what makes an overflow unreachable *from configuration alone*. It does not make
#: it unreachable from configuration **and** a clock, which is why ADR-0140 §3
#: states a saturation clause of its own rather than leaning on this figure.
#:
#: The same number as ``_MAX_CALENDAR_WINDOW`` and deliberately its own constant:
#: two ADRs name a ceiling for two different windows, and one of them moving is
#: not the other moving. ``tests/readers/test_email_settings.py`` pins it to the
#: reader's copy, exactly as the calendar's is pinned.
_MAX_EMAIL_WINDOW: Final = timedelta(days=3650)

#: ADR-0200 §6's named default for :attr:`Settings.hub_max_spoken_audio_bytes` —
#: 512 KiB of **decoded** audio, bounding a recording and a rendering alike.
#:
#: The arithmetic, so a reader can check the figure rather than accept it: ADR-0200
#: §9 carries audio as base64 text, four bytes of payload for every three of audio
#: plus two of JSON quoting, so 512 KiB of audio is about 683 KiB on the wire —
#: inside ``gateway_max_request_bytes``' 1 MiB default with room for the request
#: line, the headers and the rest of the arguments, and far inside ADR-0085 §8c's
#: ~16 MiB payload limit. Read the other way, 512 KiB is about three minutes of
#: speech at a 24 kbit/s Opus bitrate: a long press and a short monologue. The two
#: bounds meet where they should and the new one binds first.
_DEFAULT_MAX_SPOKEN_AUDIO_BYTES: Final = 512 * 1024

#: ADR-0168 §8's named default for :attr:`Settings.gateway_max_request_bytes` — one
#: mebibyte, bounding a browser request *whole*. Its own constant rather than a
#: reuse of any frame figure: it "is the gateway's own bound and does not replace
#: the hub's", so one of them moving is not the other moving.
_DEFAULT_GATEWAY_REQUEST_BYTES: Final = 1024 * 1024

#: The lowest port ADR-0168 §8 admits for :attr:`Settings.gateway_port`, which is
#: refused "unless it is a valid non-privileged TCP port". Below 1024 a listener
#: needs privilege the gateway has no business holding, and a browser reaching one
#: would be reaching a process that started as root.
_LOWEST_UNPRIVILEGED_PORT: Final = 1024

#: The highest port TCP can express, and the other half of §8's validity clause.
_HIGHEST_PORT: Final = 65535


#: ADR-0194 §1's countability bound: an amount this mechanism may read has an
#: absolute value **strictly** below this. Fifteen integer digits in any real
#: currency's major unit exceeds any plausible ceiling by orders of magnitude, and
#: the bound is what makes §2's exact arithmetic sizeable rather than aspirational.
_SPEND_AMOUNT_CEILING: Final = Decimal("1E15")

#: The other half of that predicate: a countable amount's **value** is expressible
#: with at most this many fractional digits, which carries every currency's minor
#: unit and every nano-unit price a metered API quotes.
_SPEND_AMOUNT_SCALE: Final = 9

#: ISO-4217's alphabetic form, which is ``ToolCost.currency``'s rule (ADR-0016 §4)
#: and not a second one.
_SPEND_CURRENCY_LENGTH: Final = 3


def _spend_effective_exponent(amount: Decimal) -> int:
    """Return the scale ``amount``'s *value* needs, ignoring trailing zeros.

    ADR-0194 §1 makes countability "a test on the number and not on its
    representation", so ``Decimal("1.0000000000")`` is countable because its value
    is ``1`` and ``Decimal("0E-999999999999999999")`` is countable because its
    value is zero. Everything read comes from the amount's own ``as_tuple()``, so
    no ambient ``decimal`` precision, rounding mode or trap changes the answer or
    makes this raise (§1's context-independence clause).

    Args:
        amount: A finite ``Decimal``.

    Returns:
        The exponent of the value's last significant digit, or ``0`` for a zero.
    """
    _sign, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover — callers check finiteness first
        return 0
    if not any(digits):
        return 0
    trailing = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing += 1
    return exponent + trailing


def _spend_is_countable(amount: Decimal) -> bool:
    """Report whether ``amount`` is countable under ADR-0194 §1.

    **This is a second implementation of §1's predicate, deliberately**, and not a
    second *source* for it. The store that runs the arithmetic carries its own
    (``permissions.spend``), and ``core`` may import no subsystem (golden rule 2);
    both implement the ADR's clause rather than each other. The split is the one
    ADR-0194 §1 and §11 already draw: the ``ConfigurationError`` a user meets names
    a ``Settings`` field and is raised **here**, where that field is validated,
    while the store's own check is its ordinary refusal of a malformed caller.

    Args:
        amount: The amount to classify.

    Returns:
        Whether this mechanism may read it.
    """
    if not amount.is_finite():
        return False
    if _spend_effective_exponent(amount) < -_SPEND_AMOUNT_SCALE:
        return False
    # ``copy_abs`` and not ``abs``: the latter is an arithmetic operation that
    # rounds to the ambient precision, so under a hostile context it traps on
    # exactly the values this predicate exists to classify.
    return amount.copy_abs() < _SPEND_AMOUNT_CEILING


def _checked_spend_amount(
    value: Decimal | None, field: str | None, *, floor: str
) -> Decimal | None:
    """Return ``value`` if ADR-0194 §1 admits it as a spend amount, else raise.

    Shared by the two ceilings and the allowance because §1 gives them one
    countability rule and two different floors, and a single function is what keeps
    the countability half from drifting between them.

    Args:
        value: The configured amount, or ``None`` for unset.
        field: The setting's name, for the message the operator reads.
        floor: ``"zero"`` where §1 admits zero — a ceiling — and ``"positive"``
            where it does not — the allowance.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If the amount is non-finite, below its floor, or not countable.
            pydantic reports it as a ``ValidationError`` naming the field, which
            ``load_settings`` reports as a ``ConfigurationError``.
    """
    if value is None:
        return value
    name = field if field is not None else "the spend amount"
    if not value.is_finite():
        msg = f"{name} must be finite, got {value!r}"
        raise ValueError(msg)
    if floor == "positive":
        if not value > 0:
            msg = f"{name} must be greater than zero, got {value!r}"
            raise ValueError(msg)
    elif value < 0:
        msg = f"{name} must not be negative, got {value!r}"
        raise ValueError(msg)
    if not _spend_is_countable(value):
        msg = (
            f"{name} must be countable — below {_SPEND_AMOUNT_CEILING} and to at most "
            f"{_SPEND_AMOUNT_SCALE} fractional digits, got {value!r}"
        )
        raise ValueError(msg)
    return value


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
            "Directory the hub owns exclusively: the seven SQLite stores, the "
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

    # The hub scheduler's three job intervals (ADR-0083 §7). One field per job,
    # with the ADR's own default, because §7 requires exactly that: "Each interval
    # is a ``Settings`` field with the default above, which is what ADR-0077 §8
    # asks for: 'Cadence then becomes configuration rather than a contract
    # change.'" The defaults are named in the ADR rather than left to the
    # implementation, following ADR-0074 §9.3.
    #
    # **All three are ``_OptionalDuration``, and the ``None`` is load-bearing.**
    # §7: "Every duration this ADR adds is a ``timedelta`` refused at load time
    # unless it is finite and strictly positive… **'Disabled' is ``None``, never
    # ``0``**". Both halves matter and for the same reason: the scheduler
    # re-arms a job from its *completion*, so an interval of zero would make a
    # job due again the instant it finished — a retention purge turned into a hot
    # loop against SQLite. ``gt=timedelta(0)`` refuses that at load, and the
    # sentinel gives "off" a spelling that cannot be confused with "as fast as
    # possible", which is the one confusion a scheduler cannot afford because the
    # two look identical in a config file.
    retention_purge_interval: _OptionalDuration = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
        description=(
            "How often the hub sweeps expired memory records and purgeable deferred "
            "questions (ADR-0083 §7). Set it to 'none' to disable the job; never 0."
        ),
    )
    conversation_sweep_interval: _OptionalDuration = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
        description=(
            "How often the hub finishes pending conversation deletions and then reclaims "
            "what retention has emptied (ADR-0083 §7). Set it to 'none' to disable the "
            "job; never 0."
        ),
    )
    # **Ships armed, at fifteen minutes** (ADR-0218 §5, §7), which partially
    # supersedes ADR-0083 §7's job-table row in its **Default** cell. The disabled
    # default had one stated reason and ADR-0212 spent it: "Enabling it on a timer
    # before the cursor exists buys repeated cost and no new coverage". With the
    # watermark, a tick with nothing unobserved reads one bounded listing, calls no
    # model and reports nothing observed, and a pass strictly advances rather than
    # re-reading the window it read last time. What the disabled default left is a
    # hub whose user model does not accumulate at all unless somebody remembers to
    # run a command, which is #1737.
    #
    # **`None` is still the spelling of "off"**, and still the only one (ADR-0083
    # §7's convention, unchanged): an operator who wants the job off sets the
    # disable sentinel and one who wants a different cadence sets a duration.
    # Neither is new surface, and neither is a `0`.
    #
    # **Fifteen minutes is bought against the serial loop rather than against
    # cost** (ADR-0218 §7). The tick decides latency, not spend — a tick with no due
    # candidate performs one bounded read and returns — so asking more often costs
    # almost nothing, and what it does cost is ADR-0083 §7's serial loop. Against
    # `scheduler_run_budget`'s five minutes this holds the job's share of that loop
    # to about a third of its own period, leaving the hourly purge and sweep the
    # rest. The user-visible figure it buys is one quiet window plus one interval —
    # twenty-five minutes at these defaults — to the first run that reaches a
    # conversation with nothing queued ahead of it.
    observation_interval: _OptionalDuration = Field(
        default=timedelta(minutes=15),
        gt=timedelta(0),
        description=(
            "How often the hub looks for a conversation whose turns are due to be "
            "distilled into beliefs (ADR-0218 §5). Armed by default; set it to "
            "'none' to disable the job, never 0."
        ),
    )
    # ADR-0218 §2's due test, in two durations. A candidate is **due** when it is
    # quiet, **or** aged, **or** full, and a scheduled pass is performed only
    # against a due candidate. The third arm gets **no field of its own**: its
    # threshold is `observation_batch_size`, because the condition it tests is
    # exactly "a whole page is available to read", and a second count would let the
    # two disagree about what a page is (§7).
    #
    # **Ten minutes for the quiet window, and it is measured on `last_active_at`**
    # (§1) — the instant a turn *begins*, never the instant one was recorded, so a
    # conversation whose next turn is in flight is not called quiet. Long enough
    # that a pause to read, to think or to fetch a coffee does not end the
    # exchange; short enough that a conversation finished before lunch is a belief
    # by lunch. It is the figure most likely to be tuned by a deployment, which is
    # why it is a field.
    #
    # **Two hours for the max age, and three constraints fix it** (§7). It is well
    # above the quiet window, so a conversation with any ordinary pause is served
    # by the quiet arm and the backstop stays the exception. It is far below
    # `episode_retention`'s 30 days, so a continuously-active conversation's oldest
    # unobserved turns are distilled long before they can expire. And it is below
    # the time the full-page arm takes in the regime this backstop is for — a
    # conversation trickling one recorded turn per quiet window, which is
    # `observation_batch_size` quiet windows, 200 minutes at these figures — so the
    # arm binds rather than being a field that never fires.
    #
    # **Neither is nullable, and ADR-0084 §3's departure is the precedent** (§7).
    # "The job is off" is a coherent deployment and is spelled once, on the
    # interval above. A quiet window of `None` would have to mean "observe
    # mid-conversation", which is a *policy* §1 ruled against rather than a way of
    # turning anything off; a max age of `None` would leave the full-page arm alone
    # to bound a trickling conversation, which it does not — a conversation
    # receiving one turn an hour is never quiet and takes twenty hours to fill a
    # page. One field means off, so a reader does not have to work out which of
    # three nulls disabled the job.
    #
    # **No cross-field refusal**, between these two or against `episode_retention`
    # (§7). A max age at or below the quiet window makes every candidate aged
    # before it is quiet and the job a pure age trigger — a policy an operator can
    # state, and refusing it at load would reject a configuration that behaves
    # exactly as its author asked. A rule against `episode_retention` is worse: that
    # field is nullable and `None` means "keep forever", so the comparison has a
    # branch that means nothing, and the setting it would police is the user's
    # deliberate choice. Both interactions are named in ADR-0218's Consequences
    # instead, which is where a figure an operator should think about belongs when
    # refusing it would be wrong.
    observation_quiet_window: _DurationSetting = Field(
        default=timedelta(minutes=10),
        gt=timedelta(0),
        description=(
            "How long a conversation must have been inactive before a scheduled "
            "observation reads it (ADR-0218 §1). Positive and finite."
        ),
    )
    observation_max_unobserved_age: _DurationSetting = Field(
        default=timedelta(hours=2),
        gt=timedelta(0),
        description=(
            "How long a conversation's oldest unobserved turn may wait before a "
            "scheduled observation reads it whether or not the conversation has gone "
            "quiet (ADR-0218 §2). Positive and finite."
        ),
    )
    # **Leg 7's consolidation job, and the precondition its absence used to
    # enforce.** ADR-0111 §4's second clause makes a per-operation deadline "a
    # precondition of being chunked at all", and its prose is explicit that this
    # "must be checked rather than assumed": "a job whose chunk reaches an
    # operation with no deadline is not a job that may be chunked under this ADR,
    # and its lane owes that operation a deadline before it may be scheduled."
    # Until that deadline existed the field was withheld rather than shipped with a
    # `None` default, because a disabled default is ADR-0083 §7's instrument for a
    # job that *may* be armed, while §4's bar is stricter: the configuration must
    # not be reachable at all.
    #
    # **The check now comes out bounded, which is what admits the field.** A
    # chunk's model call is bounded by `model_timeout_seconds`; its writes reach
    # the `Embedder` through `MemoryStore.write_atomic`, and that seam carries
    # `embedding_timeout_seconds` since ADR-0118 — applied by the composition root
    # at the single wiring point every consumer goes through (§2), so no unbounded
    # embedder is wired into anything the hub can reach. That was #820, and closing
    # it is what ADR-0111 §11 left to "an implementation lane's act against this
    # text once ratified".
    #
    # **Disabled by default, and for none of observation's reasons.** Observation
    # ships off because it has no durable cursor, so a periodic run re-reads the
    # same window and buys repeated cost with no new coverage; consolidation has
    # one — ADR-0111 §1's walk position, advanced strictly after each chunk's
    # effects — so an armed run resumes rather than repeats. What the default
    # expresses instead is that this job spends a model call per chunk and is the
    # first *chunked* job on ADR-0083 §7's serial loop, so arming it is a decision
    # about cost and about a sibling's worst-case delay (one run budget plus one
    # chunk) that a fresh install must not make by omission.
    consolidation_interval: _OptionalDuration = Field(
        default=None,
        gt=timedelta(0),
        description=(
            "How often the hub distils stored records into durable beliefs, one bounded "
            "run per tick (ADR-0083 §7, ADR-0111 §4). Disabled by default; set a "
            "duration to enable it, and 'none' to disable it again. Never 0."
        ),
    )

    # --- What bounds one chunked run (ADR-0111 §4) -----------------------
    # Two bounds doing different jobs, neither substituting for the other. The
    # *chunk count* bounds what a crash discards and what a run may overrun by;
    # the *run budget* bounds how long a chunked job delays its siblings on
    # ADR-0083 §7's serial loop. Bounding only by count leaves a run's duration a
    # function of per-record cost — a model call, here — which is unknowable at
    # configuration time; bounding only by time leaves the unit of loss unbounded,
    # so a slower machine discards more work on interruption.
    #
    # These are the *scheduler's* mechanics rather than a job's quality
    # parameters: they bound a run, not what a run may conclude, which is the
    # division ADR-0103 §5 draws and ADR-0106 §12 leaves to leg 8.
    #
    # **They landed ahead of the job that reads them, which was ADR-0111 §4's
    # marked clause rather than an oversight.** §4 states that "``Settings`` gains
    # ``scheduler_run_budget``, a ``timedelta`` defaulting to five minutes, and
    # ``scheduler_chunk_size``", so the obligation was the ADR's and did not wait on
    # a caller. A chunked job arriving without them would be deciding its own bounds
    # on the way past, which is what naming the figures was meant to prevent
    # (ADR-0074 §9.3). That reader is now here: leg 7's consolidation walk hands
    # ``scheduler_chunk_size`` to ``MemoryStore.walk_records`` as its ``limit``.
    scheduler_run_budget: _DurationSetting = Field(
        default=timedelta(minutes=5),
        gt=timedelta(0),
        description=(
            "How long one chunked scheduled run may spend before returning with its "
            "work unfinished (ADR-0111 §4). Checked at a chunk boundary, so a run "
            "overruns by at most one chunk's duration."
        ),
    )
    # ``_IntegerSetting`` rather than a bare ``int`` for the reason every integer
    # setting here carries it: ``bool`` is an ``int`` subclass, so ``True`` would
    # otherwise load as a chunk size of one. The range is
    # ``MemoryStore.walk_records``' own, so a configured chunk size is always an
    # admissible limit and the two figures cannot disagree — a setting the store
    # would refuse must fail at load, not on the job's first scheduled run hours
    # later inside a background task.
    #
    # Fifty is small on purpose (ADR-0111 §4): the chunk is both the unit of loss
    # and the unit of overrun, and this job spends a model call per chunk, so a
    # deployment whose per-record cost is high wants it lower — which is precisely
    # why it is a field rather than a constant.
    scheduler_chunk_size: _IntegerSetting = Field(
        default=50,
        ge=1,
        lt=2**63,
        description=(
            "How many records one chunk of a scheduled walk examines (ADR-0111 §4). "
            "Bounded by records *examined* rather than returned, so the figure stays "
            "a real bound over a run of ineligible records."
        ),
    )

    # --- The local API's transport (ADR-0084 §3) -------------------------
    # The four figures ADR-0084 §3 names rather than leaving to the
    # implementation, "following ADR-0083 §7, which named every scheduler interval
    # for ADR-0074 §9.3's reason: 'a "bounded default" with no figure is two
    # conforming stores handing the same continuation different history.'"
    #
    # **None of them is nullable, and that is the one place ADR-0084 departs from
    # ADR-0083 §7's convention.** There, ``None`` means "disabled", because a
    # scheduler job that never runs is a coherent deployment. Here it is not: a hub
    # with no frame cap or no read deadline has exactly the failure §3 exists to
    # prevent, so "off" is not an available value and a zero is a misconfiguration
    # rather than a way to express it. A ``hub_max_connections`` of 0 would refuse
    # every client including the CLI and would look from outside exactly like a hub
    # that is down — ADR-0084's ruling 4 failure produced by a config typo, and load
    # time is where it should surface.
    #
    # ``hub_max_frame_bytes`` is the **hub's** setting and its value is
    # authoritative: the connect reply carries it to the client, which enforces the
    # number it was told rather than one of its own (ADR-0084 §3). It bounds what
    # the 4-byte length prefix counts — envelope and payload together — and the
    # *contract* limit an engine measures is this less ADR-0085 §8b's 512-byte
    # envelope reserve, which the composition root subtracts (#572).
    hub_max_frame_bytes: _IntegerSetting = Field(
        default=_DEFAULT_MAX_FRAME_BYTES,
        ge=_MIN_FRAME_BYTES,
        le=_MAX_FRAME_BYTES,
        description=(
            "The largest frame the hub will read or write, envelope and payload "
            "together (ADR-0084 §3). Bounded below by ADR-0085 §8d's floor and above "
            "by what the 4-byte length prefix can express."
        ),
    )
    # ``hub_max_spoken_audio_bytes`` is the **fourth** byte ceiling and is nobody
    # else's (ADR-0200 §6). It is measured on the **decoded** audio, not on its
    # base64 form, because decoded length is what an inference call costs — and it
    # is the same figure in both directions for the reason ADR-0085 §8's limit is
    # symmetric, so a client is never silently less capable than the engine it
    # stands in for. What differs is the *outcome*: an oversized utterance is
    # refused with ``OversizedValueError`` locally and before any I/O (base64
    # decoding is not I/O), while an oversized rendering **degrades** under ADR-0200
    # §4, because the answer already exists and still travels as ``outcome.reply``.
    #
    # Without it the only ceiling on a transcription would be the payload limit:
    # 16 MiB of audio is on the order of ninety minutes, and one press would buy an
    # inference nobody budgeted. A bound on the recording is the only place that
    # cost can be refused before it is incurred.
    hub_max_spoken_audio_bytes: _IntegerSetting = Field(
        default=_DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
        ge=1,
        description=(
            "The largest spoken recording or rendering, in bytes of decoded audio "
            "(ADR-0200 §6). An oversized utterance is refused locally before any "
            "I/O; an oversized rendering degrades the spoken turn."
        ),
    )
    hub_read_timeout: _DurationSetting = Field(
        default=timedelta(seconds=30),
        gt=timedelta(0),
        description=(
            "How long a connection may stall — mid-frame, or waiting for the next "
            "frame's prefix — before the hub closes it (ADR-0084 §3). Positive."
        ),
    )
    hub_max_connections: _IntegerSetting = Field(
        default=64,
        ge=1,
        description=(
            "How many connections the hub serves at once; beyond it the listener "
            "refuses rather than queueing without bound (ADR-0084 §3)."
        ),
    )
    hub_max_pending_handshakes: _IntegerSetting = Field(
        default=8,
        ge=1,
        description=(
            "How many accepted connections may be waiting to complete the handshake "
            "(ADR-0084 §3). Never above hub_max_connections."
        ),
    )

    @model_validator(mode="after")
    def _the_pending_ceiling_can_bind(self) -> Settings:
        """Refuse a handshake ceiling above the total (ADR-0084 §3).

        "``hub_max_pending_handshakes`` is refused unless it is **no greater than
        ``hub_max_connections``**, since a pending ceiling above the total is a
        limit that can never bind." A limit that cannot bind is not a weaker limit
        but an absent one, and an operator who set it believes they hold a defence
        against the cheapest state a misbehaving peer can accumulate.

        Returns:
            ``self``, once the two ceilings are ordered.

        Raises:
            ValueError: If the pending ceiling exceeds the connection ceiling.
        """
        if self.hub_max_pending_handshakes > self.hub_max_connections:
            msg = (
                f"hub_max_pending_handshakes={self.hub_max_pending_handshakes} exceeds "
                f"hub_max_connections={self.hub_max_connections}, so the pending ceiling "
                f"can never bind; lower it to at most the connection ceiling"
            )
            raise ValueError(msg)
        return self

    # --- The delivery seam (ADR-0131 §5a) --------------------------------
    # **Named here because naming them elsewhere is what ADR-0093 §5 forbids.**
    # That section's figures "are therefore named in §7a rather than left to its
    # lane — *that rule cannot be invoked here and satisfied elsewhere*", and
    # ADR-0074 §9.3's reason stands behind it: "a 'bounded default' with no figure
    # is two conforming stores handing the same continuation different history."
    # Two conforming hubs with different lease, capacity and availability is the
    # same failure with the nouns changed, so ADR-0131 §5a fixes all five and this
    # block transcribes them.
    #
    # **None is nullable**, for the reason the hub's own ceilings above are not: a
    # hub serving delivery with no lease, no outbox bound, no budget bound or no
    # connection sub-bound has exactly the failure the clause naming it exists to
    # prevent, so "off" is not an available value.
    hub_notification_lease: _DurationSetting = Field(
        default=timedelta(seconds=120),
        gt=timedelta(0),
        description=(
            "How long a delivery taken by a device stays unavailable to any other "
            "poll before returning to the outbox (ADR-0131 §3, §5a). Positive. It "
            "binds only a device that took a delivery and did not acknowledge it, so "
            "it is not a latency budget for the ordinary case — it is how long a "
            "*dead* device withholds a notification from a live one."
        ),
    )
    hub_notification_outbox_entries: _IntegerSetting = Field(
        default=256,
        ge=1,
        description=(
            "How many entries the delivery outbox holds, leased or not, before an "
            "enqueue drops the oldest to make room (ADR-0131 §3, §5a). A ceiling on "
            "how many unheard notifications survive an absence."
        ),
    )
    hub_notification_outbox_bytes: _IntegerSetting = Field(
        default=_DEFAULT_MAX_FRAME_BYTES,
        ge=1,
        description=(
            "How many bytes the delivery outbox holds across every entry, counting "
            "everything it persists for each (ADR-0131 §3, §5a). Never below "
            "hub_max_frame_bytes. Defaults to the greater of 1 MiB and this hub's "
            "configured hub_max_frame_bytes (ADR-0134 §1). What stops a few large "
            "notifications defeating the count bound."
        ),
    )
    # **The default is ADR-0134 §1's rule, resolved from the *configured* frame
    # ceiling rather than from ADR-0084 §3's named default for it.** ADR-0131 §5a
    # gave this field a default of 1 MiB and a range of `>= hub_max_frame_bytes`,
    # which contradict each other on any hub whose frame ceiling exceeds 1 MiB —
    # the shipped one does, at 16 MiB, so an unconfigured hub was refused at load
    # by the ADR's own two figures. ADR-0134 supersedes the Default column alone and
    # replaces the figure with a rule: "the greater of 1 MiB and this hub's
    # `hub_max_frame_bytes`". The range is untouched and is what the rule satisfies.
    #
    # **The literal below is that rule's answer for the shipped frame ceiling, not
    # the rule.** `_resolve_outbox_bytes` is the rule; this default is what a reader
    # of `model_fields` sees and what an operator gets on an unmodified deployment.
    # A field default cannot read a sibling field, which is why the resolution is a
    # `mode="before"` validator — the shape ADR-0134 §2 points at when it says
    # "filling an absent value before validation keeps the public field a
    # non-nullable integer and needs no such marker".

    hub_max_notification_budget: _DurationSetting = Field(
        default=timedelta(seconds=300),
        gt=timedelta(0),
        description=(
            "The longest a single next_notification poll may occupy a connection "
            "(ADR-0131 §4, §5a). Positive. A budget above it is refused rather than "
            "clamped, since accepting a budget and honouring a shorter one tells the "
            "client, by acceptance, that its budget was accepted."
        ),
    )
    hub_max_delivery_connections: _IntegerSetting = Field(
        default=8,
        ge=1,
        description=(
            "How many delivery connections the hub holds at once, across every "
            "listener (ADR-0131 §5, §5a). Strictly below hub_max_connections, so a "
            "slot for an ordinary session always remains."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _resolve_outbox_bytes(cls, values: Any) -> Any:
        """Fill an absent outbox byte bound from ADR-0134 §1's rule.

        > **Normative.** ``hub_notification_outbox_bytes`` defaults to the greater
        > of 1 MiB and this hub's ``hub_max_frame_bytes`` — the configured value,
        > not ADR-0084 §3's named default for that field.

        **The configured ceiling, which is the whole point of the rule.** A static
        default computed from ADR-0084 §3's *named* 16 MiB agrees with §1 on an
        unmodified deployment and diverges the moment an operator lowers the frame
        ceiling: at a 512 KiB ceiling the rule says 1 MiB and a static default says
        16 MiB, which is looser than ratified rather than equal to it. Reading the
        sibling's configured value is what makes this the rule instead of one of its
        answers — and a field default cannot read a sibling, which is why this is a
        ``before`` validator.

        **Filling before validation is the shape ADR-0134 §2 points at**, and it is
        chosen for what it keeps *out* of the surface: "a nullable field, or an
        out-of-range marker like ``0`` or ``-1`` — would each put a value in the
        settings surface that §5a ruled out when it said ''off' is not an available
        value'." Absence is distinguished here, where it is still visible, so the
        public field stays a non-nullable integer with no sentinel to misread.

        A ceiling this cannot parse is left alone rather than guessed at: the field
        validators report the real fault, and inventing a resolution from a value
        that is not a number would bury it.

        Args:
            values: The merged raw settings, before field validation.

        Returns:
            The same mapping, with the outbox bound filled where it was absent.
        """
        if not isinstance(values, dict) or "hub_notification_outbox_bytes" in values:
            return values
        ceiling = values.get("hub_max_frame_bytes", _DEFAULT_MAX_FRAME_BYTES)
        try:
            configured = int(ceiling)
        except TypeError, ValueError:
            return values
        values["hub_notification_outbox_bytes"] = max(_MIN_OUTBOX_BYTES, configured)
        return values

    @model_validator(mode="after")
    def _the_delivery_bounds_can_hold(self) -> Settings:
        """Order ADR-0131 §5a's two dependent figures against what they rest on.

        Both are checked here rather than as field constraints because both are
        *relations* between two settings, which is the shape
        :meth:`_the_pending_ceiling_can_bind` already handles and the place
        ADR-0131 §5a names: "Both are checked at load, in the model validator that
        already orders ``hub_max_pending_handshakes`` against
        ``hub_max_connections``."

        **The outbox floor is the constraint that makes the byte bound a bound
        rather than a trap.** An outbox smaller than one frame could hold no entry
        a device could receive and would evict every notification the instant it
        arrived — a hub that silently delivers nothing, which is this leg's whole
        failure produced by a config typo.

        **The connection sub-bound is strict, and the strictness is the
        load-bearing half.** Delivery connections are long-lived and ordinary
        sessions are not, so without a sub-bound a handful of pollers occupy every
        slot indefinitely and the owner's CLI cannot connect at all — a hub that is
        unreachable for a reason that is not legible, which is ADR-0083's ruling 4
        failure. Equality would leave zero slots for an ordinary session, so it is
        refused along with anything above it.

        Returns:
            ``self``, once both relations hold.

        Raises:
            ValueError: If the outbox byte bound is below the frame ceiling, or the
                delivery sub-bound is not strictly below the connection ceiling.
        """
        if self.hub_notification_outbox_bytes < self.hub_max_frame_bytes:
            msg = (
                f"hub_notification_outbox_bytes={self.hub_notification_outbox_bytes} is below "
                f"hub_max_frame_bytes={self.hub_max_frame_bytes}, so the outbox could hold no "
                f"entry a device could receive and would evict every notification the instant "
                f"it arrived; raise it to at least the frame ceiling (ADR-0131 §5a, "
                f"ADR-0134 §1)"
            )
            raise ValueError(msg)
        if self.hub_max_delivery_connections >= self.hub_max_connections:
            msg = (
                f"hub_max_delivery_connections={self.hub_max_delivery_connections} is not below "
                f"hub_max_connections={self.hub_max_connections}, so pollers could take every "
                f"slot and leave none for an ordinary session; lower it below the connection "
                f"ceiling (ADR-0131 §5, §5a)"
            )
            raise ValueError(msg)
        return self

    # --- The remote listener (ADR-0124 §2) -------------------------------
    # **Off unless configured on, and the loopback socket is bound either way.**
    # ADR-0124 §2: "A hub with no remote-listener configuration binds only ADR-0084
    # §1's loopback socket, and the loopback socket is bound whether or not the
    # remote listener is." So the address is the switch, and its default is
    # ``None`` — there is no separate boolean, because two settings that can
    # disagree about whether a listener exists is one more state than the hub has.
    #
    # **The two ceilings above are *not* repeated here**, and that is ADR-0124 §7's
    # clause rather than an omission: "Adding it may not let the hub's total
    # concurrent connections exceed ``hub_max_connections``, and a connection
    # awaiting admission on the remote listener counts against
    # ``hub_max_pending_handshakes``." A per-listener figure is exactly the mistake
    # that clause exists to forbid — "two listeners each honouring the figure
    # independently would mean the hub honours neither".
    hub_remote_address: str | None = Field(
        default=None,
        description=(
            "The overlay address the hub's remote listener binds, or unset to bind "
            "only the loopback socket (ADR-0124 §2). A literal IP address on the "
            "overlay — never a name, a wildcard, or a public address."
        ),
    )
    # Inside IANA's dynamic/private range (49152-65535), where no registry can
    # assign a conflicting service, with the last two digits recalling ADR-0084.
    # Named here rather than left to the implementation, following ADR-0083 §7's
    # rule that "a 'bounded default' with no figure" is two deployments disagreeing.
    hub_remote_port: _IntegerSetting = Field(
        default=50084,
        ge=1,
        le=65535,
        description=(
            "The port the hub's remote listener binds on its overlay address "
            "(ADR-0124 §2). Ignored when hub_remote_address is unset."
        ),
    )

    # **This names the agent's *location*, and a location is not an identity.**
    # ADR-0124 §4 makes the overlay agent's answer the fact every remote admission
    # turns on, and the temptation is to read its third clause — "not an ordinary
    # configuration value… no configuration setting may override that identity" —
    # as forbidding this field too. It does not: that clause governs the *client's
    # enrolled hub identity*, whose deliberate absence from `Settings` is recorded
    # on `remote_hub_address` below. The identity still comes from an agent, over a
    # local interface, and nothing here lets a peer assert one.
    #
    # **What makes the difference is that the path carries conditions.** The two
    # packaged defaults are trusted because the operating system's access control
    # protects them (`service.overlay.TAILSCALE_SOCKETS`), and a configured path is
    # held to the same custody before it is used — ADR-0084 §1's ancestry walk, and
    # a socket owned by root or by the hub's own uid. So the trust still rests on
    # the OS rather than on the operator having typed carefully, and ADR-0124 §4's
    # posture is preserved rather than traded away. Unset changes nothing: the two
    # defaults are looked at exactly as before.
    #
    # It exists because ADR-0124's remote surface had no locally reachable producer
    # without it (#918) — the leg 9 QA run could reach §§6-8 only from outside the
    # application, under a mount namespace, so nothing routine could ever
    # re-verify them. ADR-0125 §2's bar for an additive `Settings` field is "a
    # deployment asking for it", and #919 is one asking.
    hub_overlay_agent_socket: str | None = Field(
        default=None,
        description=(
            "The Unix socket of the overlay agent this machine runs, or unset to "
            "look at the two paths the daemon is packaged to use (ADR-0124 §4). A "
            "configured path is held to the same custody conditions as the data "
            "directory, and the socket must be owned by root or by the hub's uid. "
            "Ignored when hub_remote_address is unset."
        ),
    )

    @field_validator("hub_remote_address")
    @classmethod
    def _the_remote_listener_binds_only_an_overlay_address(cls, value: str | None) -> str | None:
        """Refuse at load what ADR-0124 §2 forbids the hub's listener to bind.

        The five refusals and the reasoning behind them live in
        :func:`_refuse_a_non_overlay_address`, which ADR-0174 §8 obliged this field
        to share with ``gateway_remote_address`` — "the five refusals
        ``hub_remote_address`` already carries, in the same shape and for the same
        reasons". The half that cannot be decided from the string is
        :mod:`ai_assistant.service.remote`'s, which refuses to bind an address the
        overlay agent does not report as the hub's own.

        Args:
            value: The configured address, or ``None`` when the listener is off.

        Returns:
            The address, stripped of surrounding space, or ``None``.

        Raises:
            ValueError: If the value is not an IP address, or is one ADR-0124 §2
                forbids. Reported as a ``ConfigurationError`` by ``load_settings``,
                which is a stay-down deployment fault (ADR-0083 §5).
        """
        return _refuse_a_non_overlay_address(
            value,
            setting="hub_remote_address",
            loopback_is=(
                "the loopback transport is ADR-0084 §1's Unix socket and is bound "
                "whether or not this listener is"
            ),
            unset_means="bind only the loopback socket",
        )

    # --- Reaching a hub on another machine (ADR-0124 §1) -----------------
    # **The client's half of the hop, and it is two settings holding one fact.**
    # ADR-0124 §1 requires a client to obtain "its destination from configuration
    # and never from a discovery mechanism, a redirect, or anything a peer tells
    # it", so the address is the switch here exactly as `hub_remote_address` is on
    # the other end: unset means the hub on this machine, over ADR-0084 §1's Unix
    # socket, and there is no separate boolean for the same reason — two settings
    # that can disagree about which transport is in use is one more state than a
    # deployment has.
    #
    # **What is deliberately *not* here is the enrolled hub identity**, and its
    # absence is ADR-0124 §4's third clause rather than an omission: "the enrolled
    # hub identity is held beside the credential, in the same Tier 0 place and by
    # the same mechanism (§6), and it is **not an ordinary configuration value**…
    # no configuration setting may override that identity." That is what stops §4's
    # check from being circular: a configuration edit moves the *destination* and
    # leaves the identity that destination must match exactly where it was, in the
    # device's keyring. A `Settings` field for it would hand an attacker with an
    # editor both halves at once.
    #
    # **The value is validated in `wire`, not here**, which is the one place this
    # pair departs from `hub_remote_address` above. The refusals are the same five
    # (`wire.address.check_remote_address`), but a `Settings` validator would make
    # every command on the *hub's* machine — where this is unset and irrelevant —
    # answer for a value only a client reads, and would put a `wire` rule in `core`
    # where `wire` cannot be named. So the value is held as written and refused
    # where the destination is composed, which is before anything is opened.
    remote_hub_address: str | None = Field(
        default=None,
        description=(
            "The overlay address of the hub this device connects to, or unset to use "
            "the hub on this machine over its Unix socket (ADR-0124 §1). A literal IP "
            "address on the overlay — never a name, which would make the address "
            "dialled a fact about a resolver."
        ),
    )
    remote_hub_port: _IntegerSetting = Field(
        default=50084,
        ge=1,
        le=65535,
        description=(
            "The port the hub's remote listener binds (ADR-0124 §2). Must match the "
            "hub's hub_remote_port. Ignored when remote_hub_address is unset."
        ),
    )

    # **The client's own overlay agent, and the name says whose machine it is on.**
    # ADR-0124 §4's second clause has the client obtain the hub's identity "from the
    # overlay agent on its own machine" — so this is a fact about the *local*
    # machine, which is why it is not `remote_hub_overlay_agent_socket`: everything
    # else in this section (`remote_hub_address`, `remote_hub_port`) states a fact
    # about the hub being dialled, and a socket on the far end is not something this
    # device could open. Nor is it `hub_*`, which throughout this file means "this
    # machine acting as a hub".
    #
    # **Two fields rather than one, and a two-device deployment is the reason.** The
    # obvious economy is to let `hub_overlay_agent_socket` serve both ends, and it
    # would work on the single machine where hub and client are the same host. It
    # breaks precisely where ADR-0124 exists: on two devices these are two daemons on
    # two machines, and one field would make the hub's socket path govern a client
    # that never runs a hub — silently, since the client would read a value the hub's
    # operator set for an entirely different process.
    #
    # **The custody conditions are the hub's, because they are the same conditions.**
    # A configured path is held to ADR-0084 §1's ancestry walk and to a socket owned
    # by root or by this process's uid, by the same function the hub runs
    # (`wire.overlay.check_configured_socket`) — whoever owns that socket answers for
    # the overlay, and on this end that decides which hub this device will talk to.
    # Only the wording of a refusal is the client's own. Unset changes nothing: the
    # two packaged defaults are looked at exactly as before.
    #
    # It exists for #937, the client half of the gap #918 opened and #919's QA run
    # met: with the hub's socket configurable and the client's not, a single-machine
    # run could drive one side of §4 from configuration and had to reach the other
    # from outside the application. ADR-0125 §2's bar for an additive `Settings`
    # field is "a deployment asking for it", and that run is one asking.
    # **Its "ignored when" widened, and ADR-0174 §8 is the clause that widened it.**
    # This field used to be documented as ignored when ``remote_hub_address`` is
    # unset, which stopped being true when the gateway acquired a remote browser
    # listener: "a gateway may dial its hub over loopback and still serve browsers
    # over the overlay, so the condition widens to cover a set
    # ``gateway_remote_address``. No eleventh agent-socket field is owed, and the
    # custody conditions ``wire/overlay.py`` enforces on that socket are applied
    # unchanged."
    client_overlay_agent_socket: str | None = Field(
        default=None,
        description=(
            "The Unix socket of the overlay agent this machine runs, used to identify "
            "the hub before dialling it and to identify a browsing device at the "
            "gateway's remote listener, or unset to look at the two paths the daemon "
            "is packaged to use (ADR-0124 §4, ADR-0174 §3, §8). A configured path is "
            "held to the same custody conditions as the data directory, and the socket "
            "must be owned by root or by this process's uid. Ignored when both "
            "remote_hub_address and gateway_remote_address are unset."
        ),
    )

    # --- The browser gateway (ADR-0168 §8) -------------------------------
    # The ten figures ADR-0168 §8 names rather than leaving to the implementation,
    # on the ground it took from ADR-0084 §3, which took it from ADR-0083 §7 and
    # ADR-0093 §5: "a 'bounded default' with no figure is two conforming stores
    # handing the same continuation different history", and it "binds with more
    # force on a limit whose whole job is to refuse".
    #
    # **None of them is nullable, and none takes a value meaning "off"** — ADR-0084
    # §3's reason restated by §8 for a second resident process: "A gateway with no
    # session expiry, no session ceiling and no request bound is a resident process
    # that a single local caller can exhaust", and "a one-shot CLI could shrug this
    # off; a process that runs for weeks cannot."
    #
    # **The gateway owes the resource figures with more force than the hub does.**
    # ADR-0084 §3's own ceilings are "robustness, not secrecy", because "the `0600`
    # bit already scopes a peer to the owning user". A TCP loopback port carries no
    # such bit (ADR-0168 §2, §3), so the peer these bound is not hypothetical.
    #
    # These are the *spoke's* settings, which is why they sit beside the client's
    # own and not beside the `hub_*` block: everything named `hub_*` in this file is
    # a fact about this machine acting as a hub, and a gateway never is one.
    gateway_port: _IntegerSetting = Field(
        default=8422,
        ge=_LOWEST_UNPRIVILEGED_PORT,
        le=_HIGHEST_PORT,
        description=(
            "The loopback TCP port the gateway serves browsers on (ADR-0168 §2, §8). "
            "A valid non-privileged port; the address is loopback and is not "
            "configurable, since no Settings value may widen it (ADR-0168 §2)."
        ),
    )
    gateway_session_ttl: _DurationSetting = Field(
        default=timedelta(hours=12),
        gt=timedelta(0),
        description=(
            "How long a web session admits anything after it was minted, whatever it "
            "is used for (ADR-0168 §4, §8). Positive. A session ends at the earlier "
            "of this and gateway_session_idle_timeout, and in any case when the "
            "gateway process ends."
        ),
    )
    gateway_session_idle_timeout: _DurationSetting = Field(
        default=timedelta(hours=1),
        gt=timedelta(0),
        description=(
            "How long a web session survives without admitting a request (ADR-0168 "
            "§4, §8). Positive, and never above gateway_session_ttl."
        ),
    )
    gateway_max_sessions: _IntegerSetting = Field(
        default=8,
        gt=0,
        description=(
            "How many live web sessions the gateway holds; a mint beyond it is "
            "refused rather than evicting an existing session (ADR-0168 §4, §8)."
        ),
    )
    gateway_bootstrap_ttl: _DurationSetting = Field(
        default=timedelta(minutes=10),
        gt=timedelta(0),
        description=(
            "How long a disclosed bootstrap value still admits a browser (ADR-0182 "
            "§3). Positive. Measured on a monotonic source from the disclosure that "
            "promoted it, and deliberately unrelated to the session bounds: it "
            "bounds a value that is not a session, so no load-time check relates it "
            "to gateway_session_ttl or gateway_session_idle_timeout."
        ),
    )
    gateway_max_hub_connections: _IntegerSetting = Field(
        default=8,
        gt=0,
        description=(
            "How many connections to the hub the gateway holds at once (ADR-0168 §8). "
            "A browser request needing one beyond it is refused, naming the limit — "
            "never queued, and never served by opening a further connection."
        ),
    )
    gateway_max_request_bytes: _IntegerSetting = Field(
        default=_DEFAULT_GATEWAY_REQUEST_BYTES,
        gt=0,
        description=(
            "The largest browser request the gateway will read — request line, "
            "headers and body together, not the body alone (ADR-0168 §8). Enforced "
            "incrementally, before the bytes past it are buffered."
        ),
    )
    gateway_record_interval: _DurationSetting = Field(
        default=timedelta(minutes=1),
        gt=timedelta(0),
        description=(
            "The interval within which each distinct pair of request class and "
            "refusal condition is recorded at most once (ADR-0168 §6, §8). Positive. "
            "What stops a caller able to drive a refusal from driving a record per "
            "attempt."
        ),
    )
    gateway_read_timeout: _DurationSetting = Field(
        default=timedelta(seconds=30),
        gt=timedelta(0),
        description=(
            "How long a browser connection may go without completing a request "
            "before the gateway closes it (ADR-0168 §8). Positive. An unadmitted "
            "connection is closed this long after it was accepted whatever arrives; "
            "an admitted one, this long after its last complete request."
        ),
    )
    gateway_max_browser_connections: _IntegerSetting = Field(
        default=64,
        gt=0,
        description=(
            "How many browser connections the gateway holds at once, admitted and "
            "unadmitted together; beyond it the listener refuses rather than "
            "queueing (ADR-0168 §8)."
        ),
    )
    gateway_max_pending_connections: _IntegerSetting = Field(
        default=8,
        gt=0,
        description=(
            "How many *unadmitted* browser connections the gateway holds at once — "
            "those carrying no request a live session admitted (ADR-0168 §8). Never "
            "above gateway_max_browser_connections. The tighter budget keys on "
            "admission rather than on activity, because admission is the property a "
            "peer cannot fake."
        ),
    )
    # **The eleventh figure, and ADR-0175 §8 is the ADR that names it.** ADR-0168 §8
    # named ten and ADR-0172 added none; this one is the first field a later decision
    # adds to the block, and it is added rather than derived because "a 'bounded
    # default' with no figure is two conforming stores handing the same continuation
    # different history" (ADR-0084 §3, ADR-0083 §7).
    #
    # **One figure paces two things on purpose** (§8). It is what the gateway hands
    # ``next_notification`` as its ``budget``, and it is the interval within which
    # ADR-0175 §4 obliges a write on every open delivery stream — because the write a
    # browser observes *is* the completion of the poll the budget bounds. A second
    # heartbeat figure could disagree with this one and neither disagreement has a
    # defensible reading.
    #
    # **No load-time check relates it to ``hub_max_notification_budget``** (§8), which
    # is another process's setting and may be another machine's. The default sits an
    # order of magnitude below that ceiling's own 300 s default so an owner who tunes
    # one has a wide margin; meeting the ceiling is a request the hub received and
    # declined, reported as one under ADR-0168 §9.
    gateway_notification_budget: _DurationSetting = Field(
        default=timedelta(seconds=20),
        gt=timedelta(0),
        description=(
            "How long the gateway asks the hub to hold a notification poll, and the "
            "interval within which it writes on every open delivery stream (ADR-0175 "
            "§4, §8). Positive, never nullable, and takes no value meaning 'off'. Not "
            "validated against hub_max_notification_budget, which is another process's "
            "setting; a budget the hub declines is reported as a declined request."
        ),
    )

    # --- The gateway's remote browser listener (ADR-0174 §8) --------------
    # **Three fields, and none of them is a budget.** ADR-0174 §8 adds one switch
    # and two lists to the block above and spends no new figure — §8 makes ADR-0168
    # §8's ceilings *totals* across both listeners instead, "because a second
    # listener is the natural place to double a budget by accident" (ADR-0124 §7).
    #
    # **The address is the switch, and it is nullable for that reason alone.**
    # ADR-0168 §8's rule that "none of them is nullable, and none takes a value
    # meaning 'off'" is stated over the ten fields in that ADR's own table and is
    # untouched; ADR-0174 §8: "``gateway_remote_address`` is nullable *because it is
    # the switch*, which is ADR-0124 §2's shape for the hub's own remote listener…
    # A boundary that is off unless configured on needs a value meaning off."
    #
    # **No second port figure.** §8: "the two listeners differ in address, so one
    # port cannot collide with the other, and a second figure would buy an owner
    # nothing they cannot get by changing the one."
    gateway_remote_address: str | None = Field(
        default=None,
        description=(
            "The overlay address the gateway's remote browser listener binds, on "
            "gateway_port, or unset to serve browsers over the loopback listener "
            "alone (ADR-0174 §2, §8). A literal IP address on the overlay — never a "
            "name, a wildcard, a loopback address, or a public one."
        ),
    )
    # **A permission the owner wrote, which is why an empty default means "nobody"
    # and a stranded one is refused rather than ignored.** §8: "Empty is the default
    # and means **no device may exchange**, so a gateway configured on serves its
    # assets and mints no remote session until the owner names a device."
    gateway_remote_browser_devices: _ConfiguredList = Field(
        default=(),
        description=(
            "The overlay identities of the devices whose browsers may exchange a "
            "bootstrap value at this gateway, comma-separated (ADR-0174 §4, §8). "
            "Read as a set: order carries no meaning, a repeat changes nothing, and "
            "no element is matched by prefix, suffix or pattern. Empty — the default "
            "— means no device may exchange. Listing a device is not an enrolment, "
            "not a grant and not a principal."
        ),
    )
    gateway_remote_host_names: _ConfiguredList = Field(
        default=(),
        description=(
            "Additional authorities the remote browser listener admits a Host header "
            "to name, comma-separated and compared literally with gateway_port "
            "appended (ADR-0174 §6, §8). The gateway resolves nothing: a name here is "
            "admitted as a Host value and never used as a destination. Empty — the "
            "default — means the bound address is the only authority."
        ),
    )

    # --- The remote browser listener's TLS material (ADR-0202 §8) ---------
    # **Two fields, both paths, and no third.** §8: "``gateway_remote_address``
    # remains the switch (ADR-0174 §8); a field by which this listener could serve
    # plain HTTP is what §2 refuses; and a renewal interval is not this system's to
    # hold, because §4 makes renewal an owner act." No port figure is added either —
    # ADR-0174 §8's "no second port figure" clause is applied unchanged.
    #
    # **Paths rather than a fixed location**, because "the overlay agent decides
    # where it writes, and it differs by vendor, by platform and by how the owner
    # invoked it. A fixed path would be this system asserting a fact about a program
    # it does not own" — the shape ``client_overlay_agent_socket`` already has one
    # field over.
    #
    # **What is *not* checked here is everything that needs the machine.** §8 splits
    # the check across two places, as ADR-0174 §8's does: this class refuses what it
    # can decide "without touching the filesystem or importing a subsystem" — a blank
    # value, one with no UTF-8 form, and the three combinations below — and the
    # gateway refuses at start what only the machine can answer, because the custody
    # predicate lives in ``wire/custody.py`` and golden rule 2 forbids ``core``
    # importing a subsystem.
    gateway_remote_tls_certificate: str | None = Field(
        default=None,
        description=(
            "The path to the certificate the remote browser listener serves, obtained "
            "by the overlay for this machine's own overlay name (ADR-0202 §1, §8). "
            "Set together with gateway_remote_tls_key and with "
            "gateway_remote_address; unset with both of them. Read once, when the "
            "gateway starts, and never re-read: a renewed certificate takes effect at "
            "the next start."
        ),
    )
    gateway_remote_tls_key: str | None = Field(
        default=None,
        description=(
            "The path to the private key of gateway_remote_tls_certificate, generated "
            "on this machine and never leaving it (ADR-0202 §1, §3, §8). Set together "
            "with the certificate and with gateway_remote_address; unset with both of "
            "them. The gateway reads it, and refuses to start on a file owned by "
            "another user or granting any permission to group or other."
        ),
    )

    @field_validator("gateway_remote_tls_certificate", "gateway_remote_tls_key")
    @classmethod
    def _the_tls_paths_are_paths_a_gateway_could_open(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """Refuse a value that names no file at all (ADR-0202 §8).

        > ``Settings`` refuses at load what it can decide without touching the
        > filesystem or importing a subsystem: a value that is blank or has no UTF-8
        > form, and the three combinations above.

        All three conditions are about the *value* rather than about the filesystem,
        which is what keeps them here: a blank path names nothing on any machine; a
        path with no UTF-8 form is one :func:`os.fsencode` cannot round-trip, so the
        refusal that named it could not itself be built — the reason
        :mod:`ai_assistant.wire.custody` gives for escaping every pathname it
        reports; and a path carrying a NUL is one no system call will accept, on any
        machine, ever. Existence, custody, permissions and usability are the
        gateway's, at start, on the machine that holds the file.

        **The NUL is refused here rather than caught there, and adversarial review is
        why it is refused at all.** A pathname with an embedded NUL passed both other
        conditions and then reached ``Path.stat``, which raises ``ValueError`` —
        *not* ``OSError``, because no system call is ever attempted — so the
        gateway's own refusal, which is phrased around a file it could not read, was
        skipped and the operator got a bare traceback in place of a sentence. Adding
        a second ``except`` there would have been the narrower fix and the wrong one:
        the condition is decidable from the value alone, which is exactly what §8's
        split puts in this class.

        Args:
            value: The configured path, or ``None`` where the listener is off.
            info: The field being validated, for the name in the refusal.

        Returns:
            The path, stripped of surrounding space, or ``None``.

        Raises:
            ValueError: If the value is blank, has no UTF-8 form, or carries a NUL.
        """
        if value is None:
            return None
        path = value.strip()
        if not path:
            msg = (
                f"{info.field_name} is blank, which names no file on any machine "
                f"(ADR-0202 §8). Set it to the path the overlay wrote the certificate "
                f"and key to, or unset it together with gateway_remote_address"
            )
            raise ValueError(msg)
        try:
            path.encode("utf-8")
        except UnicodeEncodeError as exc:
            # A lone surrogate is a `str` Python holds and UTF-8 cannot express. The
            # gateway would have to name it in a refusal, and building that message
            # would fail exactly where the fault is — the condition
            # `wire.custody.displayable` exists to keep out of a refusal's own text.
            msg = (
                f"{info.field_name} has no UTF-8 form, so a refusal naming the path "
                f"could not itself be written (ADR-0202 §8)"
            )
            raise ValueError(msg) from exc
        if "\x00" in path:
            msg = (
                f"{info.field_name} carries a NUL character, which no pathname on any "
                f"system may contain (ADR-0202 §8). Set it to the path the overlay wrote "
                f"the certificate and key to"
            )
            raise ValueError(msg)
        return path

    @model_validator(mode="after")
    def _the_listener_is_configured_with_a_certificate_or_not_at_all(self) -> Settings:
        """Refuse the three configurations §8 names, each in its own words.

        > Three configurations are **refused at settings load**: either field set
        > while ``gateway_remote_address`` is unset; either field unset while
        > ``gateway_remote_address`` is set; and one set while the other is unset.
        > Each is a configuration no reading makes true, and none is ignored silently
        > — the rule ADR-0174 §8 applies to its two lists, for the reason it gives.

        **The pair is judged first, and the order is what makes each message the
        useful one.** A half-configured pair is a member of whichever of the other
        two conditions the address happens to select, and telling an owner who wrote
        one path that "the listener is off" would name the setting they got right.
        So the split pair is reported as a split pair, and the two remaining
        conditions then see a pair that is wholly set or wholly unset.

        **Neither path is checked against the filesystem here**, which is §8's split:
        a path that exists, is the owner's, and carries a certificate the key belongs
        to is a fact about the machine, and the gateway refuses at start on all of
        it.

        Returns:
            ``self``, once the pair and the switch agree.

        Raises:
            ValueError: If the pair is split, stranded, or missing under a
                configured listener.
        """
        certificate = self.gateway_remote_tls_certificate
        key = self.gateway_remote_tls_key
        if (certificate is None) != (key is None):
            set_field, unset_field = (
                ("gateway_remote_tls_certificate", "gateway_remote_tls_key")
                if key is None
                else ("gateway_remote_tls_key", "gateway_remote_tls_certificate")
            )
            msg = (
                f"{set_field} is set while {unset_field} is unset. The remote browser "
                f"listener terminates TLS itself and needs both halves of one pair "
                f"(ADR-0202 §8) — a certificate with no key serves nothing and a key "
                f"with no certificate proves nothing. Set both, or unset both together "
                f"with gateway_remote_address"
            )
            raise ValueError(msg)
        if self.gateway_remote_address is None and certificate is not None:
            msg = (
                f"gateway_remote_tls_certificate={certificate!r} and "
                f"gateway_remote_tls_key are set while gateway_remote_address is unset, "
                f"so the listener they would serve is off and nothing would ever read "
                f"them (ADR-0202 §8). Set gateway_remote_address to the overlay address "
                f"the gateway should serve browsers on, or unset both paths"
            )
            raise ValueError(msg)
        if self.gateway_remote_address is not None and certificate is None:
            msg = (
                f"gateway_remote_address={self.gateway_remote_address!r} is set, so the "
                f"remote browser listener serves HTTPS and nothing else — there is no "
                f"setting that makes it serve plain HTTP and no fallback to it "
                f"(ADR-0202 §2). Set gateway_remote_tls_certificate and "
                f"gateway_remote_tls_key to the pair your overlay obtained for this "
                f"machine's own overlay name, or unset gateway_remote_address to serve "
                f"browsers over the loopback listener alone"
            )
            raise ValueError(msg)
        return self

    @field_validator("gateway_remote_address")
    @classmethod
    def _the_browser_listener_binds_only_an_overlay_address(cls, value: str | None) -> str | None:
        """Refuse at load what ADR-0174 §2 forbids the browser listener to bind.

        > The remote browser listener binds only an address that exists on that
        > overlay. It may not bind a wildcard address, an address of a physical
        > interface, a loopback address, or any address reachable from the public
        > internet, and a configuration that would have it do so is refused at load
        > rather than bound.

        The five conditions and their reasoning are
        :func:`_refuse_a_non_overlay_address`'s, shared with ``hub_remote_address``
        because ADR-0174 §8 says to share them: "the five refusals
        ``hub_remote_address`` already carries, **in the same shape** and for the
        same reasons (ADR-0124 §2)". The physical-interface limb is not decidable
        from the string — nothing in ``192.168.1.5`` says whether it is an overlay
        address or an ``eth0`` one — so ADR-0124 §2's own split applies and
        :class:`~ai_assistant.interfaces.gateway.server.Gateway` refuses at start
        what only the overlay agent knows.

        Args:
            value: The configured address, or ``None`` when the listener is off.

        Returns:
            The address, stripped of surrounding space, or ``None``.

        Raises:
            ValueError: If the value is not an IP address, or is one ADR-0174 §2
                forbids.
        """
        return _refuse_a_non_overlay_address(
            value,
            setting="gateway_remote_address",
            loopback_is=(
                "the loopback listener is ADR-0168 §2's own, binds 127.0.0.1 by "
                "construction, and is bound whether or not this one is"
            ),
            unset_means="serve browsers over the loopback listener alone",
        )

    @model_validator(mode="after")
    def _no_remote_browser_permission_is_stranded(self) -> Settings:
        """Refuse a list written about a listener that is off (ADR-0174 §8).

        > Either list being non-empty while ``gateway_remote_address`` is unset is
        > **refused at settings load**. Both are permissions the owner wrote about a
        > listener, so a configuration that carries one while the listener is off is
        > one no reading makes true, and neither is ignored silently.

        **This is the one place these fields depart from the corpus's usual
        companion-setting shape, and §8 gives the reason:** ``hub_remote_port`` and
        ``client_overlay_agent_socket`` are documented as "ignored when" their switch
        is unset, and "a port number and a socket path are neutral facts, and a
        neutral fact going unread costs the owner nothing. A list of devices that may
        exchange a credential, and a list of authorities the door will answer to, are
        **permissions** — an owner who wrote one and got silence has a configuration
        that says something the running process does not do."

        Returns:
            ``self``, once neither list is stranded.

        Raises:
            ValueError: If either list is non-empty while the address is unset.
        """
        if self.gateway_remote_address is not None:
            return self
        stranded = {
            "gateway_remote_browser_devices": self.gateway_remote_browser_devices,
            "gateway_remote_host_names": self.gateway_remote_host_names,
        }
        for name, written in stranded.items():
            if written:
                msg = (
                    f"{name}={list(written)!r} is set while gateway_remote_address is "
                    f"unset, so the remote browser listener it grants a permission on is "
                    f"off and nothing would ever read it (ADR-0174 §8). Set "
                    f"gateway_remote_address to the overlay address the gateway should "
                    f"serve browsers on, or unset {name}"
                )
                raise ValueError(msg)
        return self

    @field_validator("gateway_remote_browser_devices")
    @classmethod
    def _every_listed_device_is_an_identity_an_agent_could_report(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Refuse an element no overlay agent could ever report (ADR-0174 §8).

        > Every element of ``gateway_remote_browser_devices`` is held to the
        > invariant this system already holds an overlay identity to — non-blank,
        > encodable as UTF-8, and at most ``MAX_OVERLAY_IDENTITY_BYTES`` bytes
        > encoded — and the check is **split across two places, because golden rule 2
        > puts the bound outside ``core``**. ``Settings`` refuses at load what it can
        > decide without importing anything: an element that is blank or has no UTF-8
        > form. The **gateway refuses at start**, before it binds or discloses a
        > bootstrap value, an element over the byte bound, reading the constant the
        > wire seam owns.

        **The split is golden rule 2, not a compromise**, and §8 says so:
        ``MAX_OVERLAY_IDENTITY_BYTES`` is defined in ``ai_assistant.wire.overlay``
        and in ``ai_assistant.service.overlay`` and in neither case in ``core``, "so
        a ``Settings`` validator enforcing it would be ``core`` importing a
        subsystem, which golden rule 2 forbids and ``lint-imports`` fails on, while a
        ``Settings`` validator restating ``128`` would be the second copy the clause
        above refuses."

        **Why an up-front check at all:** an identity failing the invariant is one
        the agent can never report, so without it "the owner's named device is
        refused at every exchange with nothing saying why: the configuration would be
        silently unsatisfiable".

        Args:
            value: The configured identities.

        Returns:
            The identities, each stripped of surrounding space.

        Raises:
            ValueError: If an element is blank or has no UTF-8 form.
        """
        listed: list[str] = []
        for position, element in enumerate(value):
            identity = element.strip()
            if not identity:
                msg = (
                    f"gateway_remote_browser_devices[{position}] is blank. An overlay "
                    f"agent never reports a blank identity, so a blank element could "
                    f"never name a device and the configuration would be silently "
                    f"unsatisfiable (ADR-0174 §8); remove it, or name the device's "
                    f"stable overlay identity"
                )
                raise ValueError(msg)
            try:
                identity.encode("utf-8")
            except UnicodeEncodeError as exc:
                # A lone surrogate is a ``str`` Python holds and UTF-8 cannot
                # express, so it can never equal an identity the agent reported —
                # the same condition ``wire.overlay._stable_id`` refuses on the
                # producing side, arriving here from the configuration instead.
                msg = (
                    f"gateway_remote_browser_devices[{position}] has no UTF-8 form, so "
                    f"it can never equal an identity the overlay agent reports and the "
                    f"device it names could never be admitted (ADR-0174 §8)"
                )
                raise ValueError(msg) from exc
            listed.append(identity)
        return tuple(listed)

    @model_validator(mode="after")
    def _the_gateway_bounds_can_bind(self) -> Settings:
        """Refuse a gateway bound that can never bind (ADR-0168 §8).

        Two orderings, one reason, which §8 states once and applies twice: an idle
        timeout above the absolute lifetime "is a limit that can never bind", and so
        is a pending ceiling above the total connection ceiling. A limit that cannot
        bind is not a weaker limit but an absent one, and an operator who set it
        believes they hold a defence they do not — the same argument
        :meth:`_the_pending_ceiling_can_bind` makes for the hub's own pair.

        Returns:
            ``self``, once both pairs are ordered.

        Raises:
            ValueError: If the idle timeout exceeds the session lifetime, or the
                pending ceiling exceeds the browser-connection ceiling.
        """
        if self.gateway_session_idle_timeout > self.gateway_session_ttl:
            msg = (
                f"gateway_session_idle_timeout={self.gateway_session_idle_timeout} exceeds "
                f"gateway_session_ttl={self.gateway_session_ttl}, so the idle bound can "
                f"never bind; lower it to at most the session lifetime"
            )
            raise ValueError(msg)
        if self.gateway_max_pending_connections > self.gateway_max_browser_connections:
            msg = (
                f"gateway_max_pending_connections={self.gateway_max_pending_connections} "
                f"exceeds gateway_max_browser_connections="
                f"{self.gateway_max_browser_connections}, so the pending ceiling can never "
                f"bind; lower it to at most the browser-connection ceiling"
            )
            raise ValueError(msg)
        return self

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

    # ADR-0118 §4's ceiling on pathology at the embedding seam, and the deadline
    # ADR-0111 §4's check found missing on consolidation's chunk. The composition
    # root wraps whichever embedder is configured above in a bounded one, so this
    # bounds *every* call through the seam — the store's writes, the store's
    # ``search``, and the offline re-embedding migration alike (ADR-0118 §2, §8).
    #
    # **It covers the whole of one ``embed`` call as its caller observes it,
    # including a lazy model load performed inside it.** ``FastEmbedEmbedder``
    # loads its ONNX session on the first embed, and a bound that excluded the
    # operation touching the filesystem would be a bound with a hole exactly where
    # the seam wedges.
    #
    # Thirty seconds is a ceiling on pathology rather than a latency target, the
    # same posture ``model_timeout_seconds`` takes at 60 for a remote call. It has
    # to clear a cold session initialisation on a slow disk plus one inference with
    # headroom — a deadline that fired on an ordinary cold start would convert a
    # startup cost into a recurring fault after every hub restart — and it must not
    # be so large that the bound is nominal. ``allow_inf_nan=False`` matters for
    # the reason stated for the model knobs above: ``gt=0`` rejects NaN but happily
    # accepts infinity, which would silently disable the deadline.
    embedding_timeout_seconds: _RealSetting = Field(
        default=30.0,
        gt=0,
        allow_inf_nan=False,
        description="Deadline for a single embedding call, in seconds (ADR-0118 §4).",
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

    # --- The routed confirmation's lifetime (ADR-0197 §7) -----------------
    # How long a **routed** park stays answerable. Deliberately a
    # ``_DurationSetting`` and not the ``_NullableDuration`` beside it: it takes no
    # part in ``confirmation_ttl``'s disable sentinel, which is exactly the wrong
    # default to inherit here. A routed park is invisible — ``pending_confirmations``
    # does not list it (§7) and no durable store recovers it — so a client that
    # disconnected between the park and its token would otherwise hold a slot at
    # ``max_outstanding_confirmations`` that nothing could ever free, and at a
    # ceiling of one the very next "forget that I ..." would meet backpressure rather
    # than a fresh card. ``None`` is therefore not a value this field accepts, and
    # ``gt=timedelta(0)`` refuses a zero or negative lifetime at load rather than
    # producing a card unusable the instant it is rendered.
    #
    # **It is the whole of this decision's lifetime configuration** (ADR-0197 §7):
    # no second setting scales it, extends it or disables it. Parsed from an
    # ISO-8601 duration or ``HH:MM:SS`` string in the environment
    # (e.g. ``ASSISTANT_ROUTED_CONFIRMATION_TTL=PT5M``).
    routed_confirmation_ttl: _DurationSetting = Field(
        default=timedelta(minutes=15),
        gt=timedelta(0),
        description=(
            "How long a routed operation's confirmation stays answerable before it is "
            "evicted and its ceiling slot released (ADR-0197 §7). Positive and finite, "
            "with no spelling for 'never'."
        ),
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

    # --- The transcript archive (ADR-0225) -------------------------------
    # Whether the archive is written at all, and how long it keeps what it holds.
    # Two settings rather than one, because one field cannot spell both answers
    # (§6): "how long" and "whether at all" are different questions, and the
    # durations here are validated ``gt=timedelta(0)``, so there is no duration that
    # spells "off". Collapsing them would mean either a zero duration — the value
    # ADR-0074 §8 calls out as breaking its own protocol — or reading ``None`` as
    # "off", which is the mirror image of the mistake §7 warns about for
    # ``confirmation_ttl``: the same spelling meaning "keep forever" in one field and
    # "keep nothing" in another.
    #
    # ``transcript_archive_retention`` **defaults to ``None``, and that is the
    # deliberate opposite of ``episode_retention``'s finite default** (§6). §7's
    # argument for a finite episodic default is entirely about the read path: an
    # unbounded one "would ship an ever-growing Tier 1 log of everything the user has
    # ever typed" inside the store the pipeline retrieves from and the observer
    # mines. The archive is in neither — nothing retrieves it, nothing observes it,
    # nothing reads it into a prompt (§4) — and a finite default here would
    # reintroduce exactly the loss the archive exists to remove, at a second number
    # nobody can argue for. The user may set one; the system does not choose one on
    # their behalf.
    #
    # It is read from nowhere else: no implementation derives it from
    # ``episode_retention``, and a change to that setting moves nothing in the
    # archive. Enforcement is **at the read** (§6), so shortening it takes effect on
    # the next read everywhere and lengthening it undertakes nothing in the other
    # direction — what reclamation has already taken is gone.
    #
    # ``transcript_archive_enabled`` defaults to ``True``, because a worst-case net
    # that is off by default catches nothing. Turning it off stops the write and
    # **destroys nothing**: entries already held stay, stay searchable and stay
    # destroyable, so a configuration change is never a silent deletion.
    transcript_archive_enabled: bool = Field(
        default=True,
        description=(
            "Whether a captured turn is also written to the transcript archive "
            "(ADR-0225 §6). Turning it off stops the write and destroys nothing."
        ),
    )
    transcript_archive_retention: _NullableDuration = Field(
        default=None,
        gt=timedelta(0),
        description=(
            "How long the transcript archive keeps an entry, enforced at the read. "
            "Unset means keep forever, which is the default (ADR-0225 §6)."
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
    # and the episodes remain in the store for a later pass — for as long as they
    # remain live, which ADR-0074 §7's horizon bounds).
    #
    # **Forty, and the ground is cost and egress on one pass rather than the intake
    # rule expressed as a number** (ADR-0162 §6). Five *was* ADR-0077 §2's
    # selectivity bar in numbers — "a batch that genuinely yields more durable
    # beliefs than that is a batch worth observing twice" — and ADR-0162 §1 replaces
    # that bar for an episode recording what the user told the assistant, so the
    # figure's ground does not survive with the figure. The probe measured 8.7, 9.1
    # and 9.0 proposals per pass at ``observation_batch_size`` 20 under a cap of 60
    # that never bound; 40 is more than four times that mean, two records per episode
    # in the batch. Held equal to ``learning.observer``'s
    # ``DEFAULT_OBSERVATION_MAX_PROPOSALS``, which is what a direct construction gets
    # and which carries the same reasoning at length; the composition root passes
    # this one, so an operator's value wins over both.
    #
    # **``discarded_over_limit`` above zero is a defect, never the steady state**
    # (§6). A pass in which the bound binds is an *incomplete* pass: it meets the
    # completeness rule up to the bound and no further, the truncation drops records
    # by position in a model's reply rather than by any ranking, and the response is
    # to raise this value, lower ``observation_batch_size``, or both. The two are a
    # pair — raising this one alone relocates the boundary, while halving the batch
    # halves the material each pass must fit — which is why §6 names both.
    observation_batch_size: _IntegerSetting = Field(
        default=20,
        ge=1,
        lt=2**63,
        description=("How many of a conversation's most recent turns one observation pass reads."),
    )
    observation_max_proposals: _IntegerSetting = Field(
        default=40,
        ge=1,
        description="The most beliefs one observation pass may propose; excess is discarded.",
    )

    # --- The conflict reconciler (ADR-0159) -------------------------------
    # Two knobs for the component that labels how a proposal stands to the records
    # a similarity search surfaced beside it — the seam that decides whether a fold
    # destroys a distinct fact.
    #
    # `reconciler_max_conflicts` is how many members of the conflict set, in rank
    # order, one ingest may ask a **model** about; the certain `agrees` rung above it
    # is unconditional and ranges over the whole set (ADR-0159 §3, restated by
    # ADR-0171 §1). It is **not** a second `conflict_limit`: that ceiling is 100 and
    # is a circuit breaker on a runaway store (ADR-0079 §1), nowhere near a cost
    # bound, where this one is exactly that. It is a `Settings` field for the reason
    # `observation_max_proposals` is one (ADR-0077 §2) — a knob an operator tunes
    # against their own corpus.
    #
    # **Fifteen, because fifteen is what was measured** (ADR-0171 §1, partially
    # superseding ADR-0159 §3's default of three). ADR-0159 §3 argued three off a
    # distribution — "a fourth is nearly always a topical neighbour" — and #1302's
    # replay refutes it: 657 of 1,753 crossings offer more than three, and the bound
    # explains 100% of that replay's 2,522 unlabelled relations. The A/B ran the
    # identical proposal stream at 3 and at 15: supersede retirements halve (146 ->
    # 73) while supersede decisions stay flat (56 -> 58) and `contradicts` grows only
    # 66 -> 81, so the raise extends protection rather than inflating supersession,
    # and final store shrinkage is unchanged (-17.6% against -17.8%). Fifteen labels
    # 1,730 of the 1,753 crossings; roughly 25 would zero the residual, which
    # ADR-0171 §7 leaves to a run rather than reading off a distribution.
    #
    # **What it costs is tokens, not calls.** ADR-0159 §3's one-request clause is per
    # ingest and not per member, so a larger bound grows the size of one prompt and
    # never the number of prompts. And since ADR-0171 §2 turning it down costs
    # *recall* rather than records: a member the writer holds no relation for is
    # spared by the supersede widening instead of swept into it, so this is a spend
    # knob that no longer governs destruction.
    #
    # `reconciler_model` is the route the reconciler **names** rather than
    # inheriting, typed as the same validated spec `observer_model` carries so a
    # malformed route is refused where `Settings` is built and not at the first
    # ingest that would have used it. Unset means the route already configured for
    # conversation (`default_model`), which is what makes the setting cost nothing
    # to have: it names no provider the operator did not already configure, so
    # ADR-0004 §2's property cannot be breached by leaving it unset. Like the
    # observer's, the composition root builds it as a route of its own that **never
    # falls back** (ADR-0013 §4, §6) — a reconciler's failure buys nothing by
    # reaching a second provider, because ADR-0159 §3 degrades it to an unlabelled
    # member rather than a failed write, and widening the set of providers shown two
    # stored beliefs is exactly the cost ADR-0004 §7's minimisation rule weighs.
    reconciler_max_conflicts: _IntegerSetting = Field(
        default=15,
        ge=1,
        description=(
            "The most conflict-set members, in rank order, one ingest may ask a model "
            "about when labelling how a proposal stands to them."
        ),
    )
    reconciler_model: _ModelSpec | None = Field(
        default=None,
        description=(
            "Model that labels how a proposed belief stands to the beliefs it conflicts "
            "with, in pydantic-ai 'provider:model' form. Unset means the same route "
            "conversation uses. Never falls back, whichever route it names."
        ),
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

    # --- Proactive notification (ADR-0130 §5, §7, §9) ---------------------
    # Three deployment tunings, and **only** three: §9 is explicit that no
    # standing setting of §6 becomes a `Settings` field. Reach levels, quiet
    # windows and the interruption budget are the *user's* durable state, written
    # through the engine surface and held in the notification store, because the
    # tuning surface has to work on the first day from an empty store — and a
    # value the user edits in a config file is not that.
    #
    # `notification_queue_limit` and `notification_retention` are the pair
    # ADR-0078 §7 already decided for the deferral queue, taking its shapes and
    # its reasons: a cap that "refuses new questions and keeps old ones", strictly
    # positive because "a cap of `0` is at capacity before its first admission",
    # with no "unlimited" spelling because the duration axis is where the
    # deliberate escape lives. `lt=2**63` keeps a configured value inside the
    # domain a store's own count can hold, as `deferral_queue_limit`'s does.
    #
    # **The figures differ from the deferral queue's, and both differences are
    # decisions ADR-0130 §7 argues.** The cap is 100 rather than 50 because it
    # bounds a *reading list* rather than a queue of questions blocking each
    # other. Seven days is shorter than the deferral queue's thirty on purpose: a
    # question keeps its value until it is answered, a notification about a thing
    # that already happened does not, and the whole of this ADR is that proactive
    # contact is about a moment rather than a backlog. `None` is the user's
    # deliberate "keep them", in the same words `deferral_ttl` uses.
    #
    # The cap counts **actionable** records only, so dismissing one frees capacity
    # at once and an expired one holds none; and the retention is stamped onto
    # each record at admission and runs from the instant that record *ceased* to
    # be actionable, never from the live setting and never from admission (§7).
    notification_queue_limit: _IntegerSetting = Field(
        default=100,
        gt=0,
        lt=2**63,
        description=(
            "The most actionable held notifications the store keeps; beyond it a new "
            "candidate is dropped rather than an old one evicted (ADR-0130 §7). Positive, "
            "with no unlimited spelling."
        ),
    )
    notification_retention: _OptionalDuration = Field(
        default=timedelta(days=7),
        gt=timedelta(0),
        description=(
            "How long a notification is kept after it stops being actionable, stamped onto "
            "each record at admission (ADR-0130 §7). Set it to 'none' to keep them, which "
            "also stops them ever being purged."
        ),
    )
    # The reconsideration job's interval, on ADR-0083 §7's convention and in
    # `retention_purge_interval`'s shape: finite and strictly positive, or `None`
    # for disabled and never `0`.
    #
    # **It ships enabled, and at minutes rather than hours.** With no producers it
    # rules nothing, and a held record whose quiet window has passed is the one
    # thing ADR-0130 cannot leave to a later act — a user who raises a class's
    # reach has agreed to be interrupted, and nothing else in the design would
    # reach the record they were agreeing about. It is also the one job on §7's
    # table whose latency is user-visible: a candidate held behind a window
    # closing at 08:00 is contacted at the first run after that, so by 08:05 here.
    # The remedy available to a deployment is a shorter interval rather than a
    # different guarantee, `reconsider_at` being a floor and not a deadline.
    notification_reconsider_interval: _OptionalDuration = Field(
        default=timedelta(minutes=5),
        gt=timedelta(0),
        description=(
            "How often the hub re-rules held notifications whose reconsideration instant "
            "has arrived (ADR-0130 §5). Set it to 'none' to disable the job; never 0."
        ),
    )

    # --- Evaluation traces (ADR-0119 §10) ---------------------------------
    # The one setting the trace store takes, parsed from an ISO-8601 duration or
    # `HH:MM:SS` string (`ASSISTANT_TRACE_RETENTION=P365D`). A trace is deleted
    # only for being older than this; **there is no count cap and no size cap**,
    # and that absence is the decision. A cap evicts the *oldest* rows, and in
    # #829's design the oldest rows are the unarmed baseline — the half of the
    # natural experiment that cannot be re-created, because consolidation writes
    # durably and "unarming later does not restore one". A horizon deletes rows
    # nobody is measuring; a cap deletes the rows the measurement is *about*,
    # silently, at exactly the moment the store has accumulated enough to be
    # interesting. The unbounded-growth worry a cap answers is answered by the
    # arithmetic instead: a trace is a row of numbers and ids, a busy single-user
    # day is on the order of a few hundred events, and a year of them is tens of
    # megabytes on a store whose neighbours hold embeddings.
    #
    # **365 days rather than a figure sized to leg 8** (§10). The horizon must
    # exceed any window a measure will span, and a default sized to the window
    # this lane can foresee is a default that expires the first time somebody
    # wants a year-over-year comparison.
    #
    # `gt=timedelta(0)` refuses a zero or negative horizon at load, as
    # `episode_retention` and `confirmation_ttl` above refuse theirs: a
    # non-positive horizon would sweep every trace at the first purge, which is
    # an instrument switched off by misconfiguration. `None` — reachable only
    # through the disable sentinel — means keep forever, matching
    # `episode_retention`'s convention, and a finite default is chosen for that
    # field's reason: unbounded is the wrong thing to inherit by omission.
    trace_retention: _OptionalDuration = Field(
        default=timedelta(days=365),
        gt=timedelta(0),
        description=(
            "How long an evaluation trace is kept before the retention sweep deletes it "
            "(ADR-0119 §10). Finite by default and longer than any measurement window; "
            "set it to 'none' to keep traces forever. There is no count or size cap."
        ),
    )

    # --- The calendar reader (ADR-0093 §7, §7a; ADR-0095 §1) --------------
    # Leg 6 configures **exactly one source, by explicit fields**. There is no
    # source registry and no list-valued source configuration, on ADR-0083 §7's
    # own precedent — its three job intervals are three flat fields, not a table —
    # because a registry is a schema decision with a validation story and one
    # source does not buy it. §7 revisits at the third source, which is also
    # roughly when §11's grant question stops being deferrable.
    #
    # **The field names carry ADR-0095 §1's substitution.** §7a spells the first
    # two `calendar_sensor_*`; §1 renames the seam and rules that "throughout
    # ADR-0093, 'sensor' denotes a `Reader`". Shipping `calendar_sensor_path`
    # would also collide with the *other* live sense of the word — ADR-0094 §1
    # keeps "sensor" as a **spoke profile name**, so a setting spelled that way
    # would read as configuration for a device across the process boundary, which
    # is precisely the double-booking ADR-0095 exists to end.
    #
    # **It ships disabled by default, and the reason is not that anything
    # technical is missing** (§7): nothing may read a user's personal files
    # because a default said so. Naming the reason is what stops the default
    # flipping the day the technical obstacle clears, and it places the default
    # correctly relative to the grant question — a fresh install that read a
    # calendar unasked would be making that decision by omission, which is the one
    # way it must not be made. **Configuration is not a grant**, and no surface
    # may present it as one: a field here cannot be revoked by the user through
    # the assistant, cannot be scoped, and leaves no audit record (§7, #629).
    #
    # **The two nullable fields interact, so §7a names the four states rather than
    # leaving them to compose**: both unset is fully disabled (the default); a path
    # with no interval is the **facet-only** state, which is *reserved, not
    # enabled* — no adapter may ship before `CurrentContext` grows the calendar
    # field, so today it configures a source nothing reads; both set is the live
    # arrangement, subject to §9's gates; and an interval with no path is
    # incoherent and is refused at load by `_a_reader_interval_needs_a_source`
    # below.
    calendar_reader_path: Path | None = Field(
        default=None,
        description=(
            "Absolute path to the single .ics file the calendar reader reads; None "
            "disables it (ADR-0093 §7a). One regular file — a synced calendar export, "
            "or a co-located fetcher's `singlefile` output — never a directory (#649)."
        ),
    )

    @field_validator("calendar_reader_path")
    @classmethod
    def _calendar_source_is_absolute(cls, value: Path | None) -> Path | None:
        """Refuse a relative source path, and expand ``~`` (ADR-0093 §7).

        **Shape at load, existence at run time**, and the split follows what each
        thing is a property of. Absoluteness is a property of the *configuration*:
        a relative value resolves against each process's working directory, so the
        hub started at boot and a test run from a project directory would read the
        same setting and open different files. A file's existence is a property of
        the *world at an instant* — a hub that refused to start because a calendar
        file was on an unmounted volume would turn an advisory source into a boot
        dependency, which is precisely the coupling ADR-0008 §4 declined for the
        whole context subsystem.

        **Not canonicalised, and that is the one place this departs from
        ``data_dir``.** ``realpath`` resolves symlinks, which is a *filesystem*
        question, and asking it at load would put a fragment of the run-time check
        into the half of the split that must not have one. Nothing here derives a
        second location from this path the way ADR-0084 §9 derives the socket from
        ``data_dir``, so there is no two-readers-disagreeing hazard to close.
        """
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            msg = (
                f"calendar_reader_path must be an absolute path, got {str(value)!r}; a "
                f"relative value resolves against each process's working directory "
                f"(ADR-0093 §7)"
            )
            raise ValueError(msg)
        return expanded

    # ADR-0083 §7's convention exactly, and for its reason: the scheduler re-arms
    # from *completion*, so an interval of zero makes the job due again the instant
    # it finishes, and "off" and "as fast as possible" look identical in a config
    # file. Hence **disabled is `None`, never `0`**.
    #
    # The job this arms is a later lane (ADR-0093 §10's closing paragraph); the
    # field lands here because §7a names it, and because the incoherent-state
    # refusal below cannot be expressed without it.
    calendar_reader_interval: _NullableDuration = Field(
        default=None,
        gt=timedelta(0),
        description=(
            "How often the hub reads the configured calendar; None disables the "
            "scheduled ingestion job (ADR-0093 §7a). Never 0."
        ),
    )
    # The window is **two fields, not one**, because a calendar's usefulness is
    # asymmetric: the future is what the assistant needs to know about, and the
    # past is wanted only so that "this morning" is still in view. One symmetric
    # horizon would have to be sized for the future and would drag a week of
    # history along with it. The defaults are deliberately small, on ADR-0077 §1's
    # posture for `observation_batch_size` — "a handful of exchanges, not a month
    # of transcript" — and for the same reason: this is Tier 1 data being read and
    # proposed, and a bound nobody argued is a payload nobody measured.
    #
    # `calendar_window_past` may be zero and `calendar_window_future` may not. A
    # deployment that wants only what is ahead is coherent; one that wants a window
    # of zero width has configured a reader that reads nothing while reporting
    # health, which is what ADR-0077 §1 refused for a zero batch.
    #
    # **Both are bounded above, and the ceiling is not decoration.** `> 0` alone
    # admits `timedelta.max`, for which `read_at + calendar_window_future` is not a
    # representable instant — so a figure passing a load-time range check would
    # produce an `OverflowError` on the first run, escaping ADR-0093 §8's two
    # outcomes entirely and reaching the scheduler as neither a source failure nor
    # a cancellation.
    calendar_window_past: _DurationSetting = Field(
        default=timedelta(days=1),
        ge=timedelta(0),
        le=_MAX_CALENDAR_WINDOW,
        description=(
            "How far back the clock-relative calendar window reaches (ADR-0093 §7a). "
            "May be zero; at most ten years."
        ),
    )
    calendar_window_future: _DurationSetting = Field(
        default=timedelta(days=7),
        gt=timedelta(0),
        le=_MAX_CALENDAR_WINDOW,
        description=(
            "How far forward the clock-relative calendar window reaches (ADR-0093 §7a). "
            "Strictly positive; at most ten years."
        ),
    )
    calendar_max_entries: _IntegerSetting = Field(
        default=500,
        ge=1,
        lt=2**63,
        description=(
            "The most in-window occurrences one calendar read may return, and so the "
            "most proposals (ADR-0093 §7a). Exceeding it refuses the read; it is never "
            "truncated."
        ),
    )
    # Separate from `calendar_max_entries`, and it is the one that **must** exist:
    # an entry cap can only be applied *after* parsing, so a cap on entries alone
    # lets a 2 GiB .ics be fully parsed before anything refuses it — the bound
    # applied one step too late to bound the work. This is the same ordering
    # ADR-0017 §3 requires of a credential read, applied to a parse.
    calendar_max_bytes: _IntegerSetting = Field(
        default=8 * 1024 * 1024,
        gt=0,
        description=(
            "The most bytes one calendar read consumes, enforced on the read itself "
            "and before any parsing (ADR-0093 §7, §7a)."
        ),
    )
    # Bounds a **different** thing from the other two, and neither substitutes for
    # it: the occurrences a read makes the reader *consider*, which is unbounded by
    # the byte cap (a pathological component is tiny) and by the entry cap (that
    # counts what lands in the window, not what is walked to reach it). Spent
    # across the whole read rather than per component — a budget that resets per
    # component bounds each piece of the work and not the work (ADR-0093 §7b).
    calendar_max_expansion: _IntegerSetting = Field(
        default=100_000,
        ge=1,
        lt=2**63,
        description=(
            "The most recurrence occurrences one calendar read may consider across "
            "every component (ADR-0093 §7a, §7b)."
        ),
    )
    calendar_read_timeout: _DurationSetting = Field(
        default=timedelta(seconds=10),
        gt=timedelta(0),
        description=(
            "The calendar reader's deadline on its own read (ADR-0093 §7, §7a). A path "
            "that is absolute and readable may still be a stalled mount, and every other "
            "bound sits behind an operation that never returns."
        ),
    )
    # Bounds the **output**, which none of the others do. A source can satisfy all
    # three while the proposals blow up: one recurrence carrying a near-8 MiB field
    # with exactly 500 in-window occurrences is inside every other cap and
    # materialises roughly 4 GiB, because an occurrence repeats its component's
    # content and nothing was counting bytes on the way out (ADR-0093 §7a).
    calendar_max_content_bytes: _IntegerSetting = Field(
        default=4 * 1024 * 1024,
        gt=0,
        description=(
            "The most proposal content one calendar read may materialise, checked "
            "before each proposal is built (ADR-0093 §7a)."
        ),
    )

    # --- The upcoming-event producer (ADR-0132 §4) ------------------------
    # **Two fields of its own, and neither is `calendar_reader_interval`.** §4 is
    # explicit that "arming or retuning one of these two changes ingestion's
    # cadence in no way, and arming ingestion arms no producer": the two consumers
    # read the same file at their own cadence (ADR-0093 §3), ingestion's sized for
    # how often beliefs should be refreshed and this one's sized against the lead
    # window by the cross-field rule below. A figure good for one is routinely
    # wrong for the other, and an operator who cannot set one without setting the
    # other has one cadence chosen for two jobs with different needs.
    #
    # **The interval is `None` until an operator sets it**, which is ADR-0093 §7's
    # rule for the same source unchanged — "nothing may read a user's personal
    # files because a default said so". Configuration, consent and reach are then
    # three separate acts and none stands in for another: the operator arms the
    # job here, the user grants `NOTIFY` (ADR-0133 §3, which back-fills nothing),
    # and the user raises the class's reach from `hold` (ADR-0130 §6).
    calendar_upcoming_interval: _NullableDuration = Field(
        default=None,
        gt=timedelta(0),
        description=(
            "How often the hub looks for calendar occurrences about to start; None "
            "disables the upcoming-event producer (ADR-0132 §4). Never 0."
        ),
    )
    # **Thirty minutes is named by the ADR rather than left to this lane** (§4), on
    # ADR-0093 §5's rule that a figure invoked in a decision cannot be satisfied
    # elsewhere and ADR-0074 §9.3's reason: two conforming implementations with
    # different figures notice different things while each believes it conforms.
    #
    # Bounded above for `calendar_window_*`'s reason exactly — `> 0` alone admits
    # `timedelta.max`, and the producer's window is `read_at` plus this figure.
    calendar_upcoming_lead: _DurationSetting = Field(
        default=timedelta(minutes=30),
        gt=timedelta(0),
        le=_MAX_CALENDAR_WINDOW,
        description=(
            "How far ahead of an occurrence's start the producer notices it "
            "(ADR-0132 §4). Strictly positive; at most ten years."
        ),
    )

    @model_validator(mode="after")
    def _an_upcoming_interval_needs_a_source(self) -> Settings:
        """Refuse an armed producer with nothing to read (ADR-0132 §4).

        ``calendar_reader_interval``'s refusal below, for the second job over the
        same source and for its reason unchanged: "An armed producer with no
        source to read is an incoherent state and is refused as one rather than
        discovered at the first tick."

        Raises:
            ValueError: If an interval is set with no path beside it.
        """
        if self.calendar_upcoming_interval is not None and self.calendar_reader_path is None:
            msg = (
                "calendar_upcoming_interval is set but calendar_reader_path is not; an "
                "armed producer needs a source to read (ADR-0132 §4)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_lead_window_outruns_its_own_interval(self) -> Settings:
        """Refuse a lead window that leaves holes between ticks (ADR-0132 §4).

        **The misconfiguration is silent, and silence here is indistinguishable
        from working**, which is the whole reason this is a load-time refusal.
        With ticks at ``t``, ``t+I``, … and a lead ``L``, an occurrence is noticed
        only if some tick sees it inside ``(tick, tick+L)``. Where ``L <= I`` the
        intervals leave holes: an occurrence starting in ``(t+L, t+I]`` is too far
        away at the first tick and already past at the second, so it is never
        noticed at all — while the job runs, logs nothing and reports health.

        **Conditioned on the producer being armed, because the clause names the
        producer's own interval** and there is no interval to outrun when the job
        is off. §4's argument for the refusal is written entirely about a running
        job — "With ticks at t, t+I, …" — so an unarmed deployment carrying a lead
        it does not use is not the incoherent state this refuses.

        **What it does not buy is a guarantee**, and §4 names the gap rather than
        smoothing it over: ADR-0083 §7 schedules a job from its *completion*, so
        the real gap between ticks is the interval plus the run, and a late tick is
        "never a correctness bug". ``L > I`` is necessary and not sufficient, and
        the remedy available to a deployment is a lead comfortably larger than its
        interval.

        Raises:
            ValueError: If an armed producer's lead is not strictly greater than
                its interval.
        """
        interval = self.calendar_upcoming_interval
        if interval is not None and self.calendar_upcoming_lead <= interval:
            msg = (
                f"calendar_upcoming_lead must be strictly greater than "
                f"calendar_upcoming_interval, got {self.calendar_upcoming_lead!r} for "
                f"{interval!r}; a lead no longer than the interval leaves occurrences "
                f"that no tick ever sees, silently (ADR-0132 §4)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_lead_window_stays_inside_the_read(self) -> Settings:
        """Refuse a lead window the read can never fill (ADR-0132 §4).

        The producer's subject is the reading's own proposals, so an occurrence
        beyond ``calendar_window_future`` is not in the reading at all: a lead
        reaching past the reader's forward window selects from a region the read
        never returns, and the job again runs, logs nothing and reports health.

        **Conditioned on the producer being armed, exactly as the two refusals
        above are**, and §4's shared justification is what decides it: both are
        there because "the misconfiguration is silent, and silence here is
        indistinguishable from working", which is a statement about a job that
        runs. An unarmed deployment reads this field nowhere, so a pair that could
        only mislead a running producer is not an incoherent state for it — and
        refusing a hub's startup over a figure nothing consults would be a
        configuration act with no fact behind it.

        Raises:
            ValueError: If an armed producer's lead exceeds the reader's forward
                window.
        """
        if (
            self.calendar_upcoming_interval is not None
            and self.calendar_upcoming_lead > self.calendar_window_future
        ):
            msg = (
                f"calendar_upcoming_lead must not exceed calendar_window_future, got "
                f"{self.calendar_upcoming_lead!r} against {self.calendar_window_future!r}; "
                f"a lead past the read's own forward window selects from occurrences the "
                f"read never returns (ADR-0132 §4)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_reader_interval_needs_a_source(self) -> Settings:
        """Refuse a scheduled read of a source that is not configured (ADR-0093 §7a).

        The fourth state of §7a's matrix, and the only incoherent one. The refusal
        follows this module's own posture — a figure the runtime would refuse must
        fail at load — and the alternative outcomes are all worse and all silently
        different: a scheduler that omits the requested job reports health while
        running nothing, one that arms it re-runs a failing job forever, and one
        that treats it as a source fault turns a configuration mistake into an
        infinite retry.

        Raises:
            ValueError: If an interval is set with no path beside it.
        """
        if self.calendar_reader_interval is not None and self.calendar_reader_path is None:
            msg = (
                "calendar_reader_interval is set but calendar_reader_path is not; a "
                "scheduled read needs a source to read (ADR-0093 §7a)"
            )
            raise ValueError(msg)
        return self

    # --- The email source (ADR-0140 §12) ----------------------------------
    # **Seven fields, derived from this source rather than copied from the
    # calendar's nine** (§12). What is *absent* is as decided as what is here: no
    # `email_window_future`, because a mailbox has no future; and no expansion
    # budget, because a mailbox has no generator — the messages in the store are
    # the messages, so the byte cap bounds the parse and the message cap bounds
    # the output, and a third figure would bound nothing the first two do not.
    #
    # **No field carries the account, and that is a decision rather than an
    # omission** (§12). The reader's identity is the declared constant `"email"`,
    # never the address: ADR-0093 §7 uses exactly this source as its worked
    # counter-example — a reader "names *itself*, never the data it holds" — and
    # here the mistake would be one keystroke away in a free-text setting. Nor is
    # the account **credential** here, or anywhere else in this process: it is the
    # operator's and the fetcher's, and keeping it outside is what makes ADR-0140
    # §1's file boundary a boundary rather than a diagram (§11).
    email_source_path: Path | None = Field(
        default=None,
        description=(
            "Absolute path to the single mbox file the email reader reads; None "
            "disables it (ADR-0140 §2, §12). One regular file, replaced whole by a "
            "co-located fetcher — never a directory and never a maildir (#649)."
        ),
    )

    @field_validator("email_source_path")
    @classmethod
    def _email_source_is_absolute(cls, value: Path | None) -> Path | None:
        """Refuse a relative source path, and expand ``~`` (ADR-0093 §7).

        ``calendar_reader_path``'s validator above, unchanged and for its reasons:
        absoluteness is a property of the *configuration* and is checked here,
        while existence is a property of the world at an instant and is checked at
        run time, where it degrades under ADR-0093 §8 rather than refusing to
        start.
        """
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            msg = (
                f"email_source_path must be an absolute path, got {str(value)!r}; a "
                f"relative value resolves against each process's working directory "
                f"(ADR-0093 §7)"
            )
            raise ValueError(msg)
        return expanded

    email_reader_interval: _NullableDuration = Field(
        default=None,
        gt=timedelta(0),
        description=(
            "How often the hub reads the configured email store; None disables the "
            "scheduled ingestion job (ADR-0140 §12). Never 0."
        ),
    )
    # **One window edge, not two, and it may not be zero.** A calendar is
    # asymmetric because the future is what the assistant needs; a mailbox has no
    # future, so an `email_window_future` would bound nothing. The remaining edge
    # is refused at zero for ADR-0093 §7a's reason applied unchanged — a
    # zero-width window is a reader that reads nothing while reporting health —
    # and this is where `calendar_window_past`'s neighbouring declaration is a
    # trap: that one **may** be zero and its own test asserts so, so a `ge=0`
    # inherited by copying ships exactly that reader.
    #
    # **Seven days rather than the calendar's one**, and the asymmetry is
    # deliberate (§12): a calendar's past is wanted only so "this morning" stays
    # in view, while a mailbox's whole content is its past. A window shorter than
    # the gap between two runs of a hub that is occasionally off loses mail
    # permanently, because ADR-0140 §3 leaves no cursor to notice — seven days is
    # small enough to be a bounded payload of Tier 1 data and large enough that
    # the loss needs a week of downtime to reach.
    email_window_past: _DurationSetting = Field(
        default=timedelta(days=7),
        gt=timedelta(0),
        le=_MAX_EMAIL_WINDOW,
        description=(
            "How far back the clock-relative arrival window reaches (ADR-0140 §3, "
            "§12). Strictly positive — never zero; at most ten years."
        ),
    )
    # **Counts the messages the store's framing yields, before any header is
    # interpreted** (§12). The obvious spelling — "in-window messages" — cannot be
    # enforced, because deciding whether a message is in the window means reading
    # its delivery header, which is the very step ADR-0140 §5's skip rule turns
    # on: a store of 2,001 messages none of which carries a valid
    # `X-Assistant-Delivered-At` would then be skipped message by message and
    # returned as a **successful empty reading** — a busted cap wearing the
    # clothes of a quiet week, which is what ADR-0093 §5's refuse-don't-truncate
    # rule exists to prevent.
    email_max_messages: _IntegerSetting = Field(
        default=2_000,
        ge=1,
        lt=2**63,
        description=(
            "The most framed messages one email read may accept, counted as they "
            "are framed and before any header is interpreted (ADR-0140 §12). "
            "Exceeding it refuses the read; it is never truncated."
        ),
    )
    # Separate from `email_max_messages` and the one that **must** exist, on
    # ADR-0093 §7a's ordering argument unchanged: a message cap can only be
    # applied after parsing, so a cap on messages alone lets a 2 GiB store be
    # fully parsed before anything refuses it.
    email_max_bytes: _IntegerSetting = Field(
        default=8 * 1024 * 1024,
        gt=0,
        description=(
            "The most bytes one email read consumes, enforced on the read itself "
            "and before any parsing (ADR-0093 §7, ADR-0140 §12)."
        ),
    )
    email_read_timeout: _DurationSetting = Field(
        default=timedelta(seconds=10),
        gt=timedelta(0),
        description=(
            "The email reader's deadline on its own read (ADR-0093 §7, ADR-0140 "
            "§12). A path that is absolute and readable may still be a stalled "
            "mount, and every other bound sits behind an operation that never "
            "returns."
        ),
    )
    # Bounds the **output**, which none of the others do: a `Subject` may be
    # folded across many lines, and 2,000 of them inside every other cap can still
    # materialise more content than any consumer wants (§12).
    email_max_content_bytes: _IntegerSetting = Field(
        default=4 * 1024 * 1024,
        gt=0,
        description=(
            "The most proposal content one email read may materialise, checked "
            "before each proposal is built (ADR-0140 §12)."
        ),
    )

    @model_validator(mode="after")
    def _an_email_interval_needs_a_source(self) -> Settings:
        """Refuse a scheduled read of a source that is not configured (ADR-0140 §12).

        ``_a_reader_interval_needs_a_source`` above, for the equivalent pair and
        for ADR-0093 §7a's reason unchanged: every alternative outcome is worse
        and every one is silently different. A scheduler that omits the requested
        job reports health while running nothing, one that arms it re-runs a
        failing job forever, and one that treats it as a source fault turns a
        configuration mistake into an infinite retry.

        **The converse pair is coherent and is deliberately not refused.** A path
        with no interval is the facet-only state — a source a request-path
        assembly may read while nothing ingests from it on a schedule — which is
        one of ADR-0140 §9's three scopes being granted without the other.

        Raises:
            ValueError: If an interval is set with no path beside it.
        """
        if self.email_reader_interval is not None and self.email_source_path is None:
            msg = (
                "email_reader_interval is set but email_source_path is not; a "
                "scheduled read needs a source to read (ADR-0140 §12)"
            )
            raise ValueError(msg)
        return self

    # --- The local-file fetch root and its bounds (ADR-0230 §4, §6) -------
    # **Off until configured, which is what makes the standing cost zero** (§6).
    # The root's named default is *unset*: no root, no listing, no ask, no fetch.
    # A deployment with none pays no listing read, renders no listing block, and
    # cannot service the kind — which is also why ADR-0230 §9's fire rate reads 0%
    # in such a deployment, and why that is a true statement about the
    # configuration rather than a reading of a trigger.
    #
    # **The root's own field carries no domain clause and the four bounds do.**
    # Unset means the mechanism is off, so there is no out-of-range value to
    # refuse here; what *is* refused at construction — and in the concrete
    # fetcher rather than in `core` — is a root whose reads would leave the device
    # (§6's two-stage eligibility). That is a property of storage rather than of
    # configuration, so it cannot be decided from a string.
    fetch_root_path: Path | None = Field(
        default=None,
        description=(
            "Absolute path to the one directory the local-file fetcher lists and "
            "reads; None disables the mechanism entirely (ADR-0230 §6). Its direct "
            "children only — never a tree, and never a second root."
        ),
    )

    @field_validator("fetch_root_path")
    @classmethod
    def _fetch_root_is_absolute(cls, value: Path | None) -> Path | None:
        """Refuse a relative root, and expand ``~`` (ADR-0093 §7's split).

        ``calendar_reader_path``'s validator above, unchanged and for its reasons:
        absoluteness is a property of the *configuration* — a relative value
        resolves against each process's working directory, so the hub started at
        boot and a test run from a project directory would read the same setting
        and open different directories — while what the path *is* on the
        filesystem is a property of the world, decided against an opened handle by
        ADR-0230 §6's two stages and never against this string.

        **Not canonicalised**, for ``calendar_reader_path``'s reason and for a
        second one this seam adds: ``realpath`` resolves symbolic links, and
        ADR-0230 §6 requires that a symbolic link at **any** component of the
        configured path refuse the construction rather than be followed. Resolving
        it here would silently answer the very question the constructor exists to
        refuse.
        """
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            msg = (
                f"fetch_root_path must be an absolute path, got {str(value)!r}; a "
                f"relative value resolves against each process's working directory "
                f"(ADR-0230 §6)"
            )
            raise ValueError(msg)
        return expanded

    # **Every one of the six below has a stated domain, and a value outside it is
    # a load-time configuration error** (ADR-0230 §6, ADR-0232 §2, ADR-0234 §2). Zero
    # and negative values are
    # refused rather than given a meaning, and the refusal is `Settings`'s own — at
    # load, before any fetcher is built and before any filesystem call — for
    # ADR-0093 §5's reason. A zero entry cap is a mechanism that shows nothing
    # while appearing configured, which ADR-0230 §3 rules a listing may not be made
    # to mean; and a negative one is worse than meaningless, because the obvious
    # Python spelling of a cap — `entries[:-1]` — quietly yields all but the *last*
    # entry, so a bound would be defeated by a configuration value rather than
    # enforced by one.
    fetch_listing_ttl: _DurationSetting = Field(
        default=timedelta(minutes=5),
        gt=timedelta(0),
        description=(
            "How long a listing's authority lasts before every fetch against it is "
            "refused (ADR-0230 §4). Strictly positive; bound into the listing's own "
            "token on **both** a monotonic and a wall-clock deadline, either of "
            "which expires it."
        ),
    )
    fetch_listing_max_entries: _IntegerSetting = Field(
        default=40,
        ge=1,
        lt=2**63,
        description=(
            "The most entries one listing shows — the root's most recently modified "
            "supported children (ADR-0230 §6). At least 1: a listing that shows "
            "nothing while appearing configured is not a state this mechanism has."
        ),
    )
    fetch_max_file_bytes: _IntegerSetting = Field(
        default=4 * 1024 * 1024,
        ge=1,
        lt=2**63,
        description=(
            "The most bytes one fetch reads from a file, enforced on the read itself "
            "(ADR-0230 §6). A file beyond it is **refused, never truncated**."
        ),
    )
    fetch_max_content_bytes: _IntegerSetting = Field(
        default=32 * 1024,
        ge=1,
        lt=2**63,
        description=(
            "The most extracted text one fetch may put in a record, counted on the "
            "**quoted rendering** the prompt will carry — `json.dumps` at its "
            "default `ensure_ascii=True`, both delimiters included (ADR-0230 §6). A "
            "file beyond it is refused, never truncated."
        ),
    )
    # **The third quantity, and the third consumer** (ADR-0232 §1, §2). The two
    # fields above are *what is read* and *what reaches the prompt*; this one is
    # what the **parser** is handed, and one number cannot be honest about all
    # three. It is an independent figure and never a derived one: no deployment's
    # change to either field above moves it, and nothing computes it from them.
    #
    # **Bytes parsed, never bytes decoded**, and the two differ by the number of
    # times the extraction reads the same stream. A stream parsed on forty pages is
    # charged forty times — which is the whole content of the bound, because the
    # decoded size of a document's streams is not the quantity its extraction's
    # cost is a function of.
    fetch_max_decoded_bytes: _IntegerSetting = Field(
        default=1024 * 1024,
        ge=1,
        lt=2**63,
        description=(
            "The most decoded bytes one fetch's extraction may **parse**, summed "
            "once per parse and compared before each decoded stream is parsed "
            "(ADR-0232 §2, §3). For PDF that is every content stream the extraction "
            "parses — a page's own and every Form XObject reached from it, once for "
            "each `Do` that invokes it — plus, per parse, the embedded font program "
            "of each font the extraction re-parses per page: no `/ToUnicode`, "
            "`/Subtype` `/Type1`, and a `/FontDescriptor` carrying `/FontFile`. "
            "Plain text and Markdown have no decoding step and count zero. A "
            "document beyond it is refused `TOO_LARGE`, never truncated."
        ),
    )

    # **The fourth quantity, and the fourth consumer** (ADR-0234 §2). Its consumer
    # is the mapping-dictionary build, and it is a second field rather than more of
    # the one above because **neither quantity is a function of the other**:
    # `pypdf`'s `parse_bfrange` builds `b - a + 1` mappings from a single range
    # line, so 65,000 mappings arrive in 927,031 bytes of `bfchar` or in **178** of
    # `bfrange` — a factor of about 5,200. A byte charge on that input is "a number
    # that looks like a bound, is checkable, and is not a function of the cost it
    # claims to bound": a 225-byte CMap declaring 90,000 mappings costs 0.147 s a
    # page, so two thousand pages sharing it is a 568 KB file `extract_text` spends
    # **279 s** on while charging 450,000 bytes — under half the figure above.
    #
    # **Mappings built, never the dictionary that survives.** A CMap whose ranges
    # send two source codes to one key pays for both, because the cost is in the
    # insertions and a count taken after duplicates collapse under-charges exactly
    # the document that declares the most.
    #
    # **Neither field absorbs the other's quantity** (ADR-0234 §2): no
    # implementation converts mappings into notional bytes to charge them above, at
    # an exchange rate no operator chose and no document respects. It is an
    # independent figure and never a derived one.
    fetch_max_character_mappings: _IntegerSetting = Field(
        default=400_000,
        ge=1,
        lt=2**63,
        description=(
            "The most `/ToUnicode` character mappings one fetch's extraction may "
            "**build**, summed once per font-build and compared before the font is "
            "built (ADR-0234 §1, §2, §3). For PDF that is, per parse, every font in "
            "the parse's resource context: the mappings its `/ToUnicode` stream's "
            "own parse builds, or **two** where the `/ToUnicode` is not a stream and "
            "`prepare_cm` synthesises its fixed literal. Plain text and Markdown "
            "build no mapping and count zero. A document beyond it is refused "
            "`TOO_LARGE`, never truncated."
        ),
    )

    # --- The query one search is composed into (ADR-0231 §3, §5) ----------
    # **The bound the composer enforces, and the model never sees.** ADR-0231 §3
    # divides a bound from the value it bounds exactly as ADR-0230 §6 does: the
    # figure is a `Settings` field with a named default, a stated domain and a
    # load-time refusal, `QueryOutcome` carries none of it, and the *configured
    # composer* is what refuses over it. So an outcome validates identically in
    # every deployment, and two composers configured differently in one process
    # produce values one model reads the same way.
    #
    # **A composition over it is refused, never truncated** — `QueryRefusal.TOO_LONG`
    # — because a prefix of a query is a different question, and one no reader of
    # the outcome could tell from the question that was asked.
    #
    # ADR-0231 §5 adds two further fields for the searcher itself —
    # `search_max_results` and `search_max_result_chars`; they land with the lane
    # that enforces them, since a bound nothing reads is a figure an operator can
    # set and watch do nothing.
    search_query_max_chars: _IntegerSetting = Field(
        default=256,
        ge=1,
        lt=2**63,
        description=(
            "The most **Unicode code points** a composed web-search query may carry "
            "(ADR-0231 §3, §5). At least 1. Enforced by the composer, never by the "
            "model: a composition beyond it is refused `TOO_LONG` and never truncated."
        ),
    )
    # **The transport's bound, and it is a different quantity from the two above.**
    # ADR-0231 §5 counts it "over the bytes taken off the channel" — the whole
    # response, its status line and headers included — and enforces it "while the
    # response is read and before any part of it is parsed". So it bounds what the
    # exchange may *buy* from a far end, where `search_max_result_chars` bounds what
    # reaches a prompt; neither is derived from the other and nothing computes one
    # from the other.
    #
    # **A response over it is abandoned and refused, never truncated**: the read
    # stops as soon as one byte past the bound has been taken, the channel is
    # closed, nothing is parsed and no record is minted. A response exactly at it is
    # read whole. An implementation that buffered the whole response and then
    # measured it would satisfy neither half.
    search_max_response_bytes: _IntegerSetting = Field(
        default=1024 * 1024,
        ge=1,
        lt=2**63,
        description=(
            "The most bytes one web-search response may take off the channel — its "
            "status line and headers included — enforced on the read itself and "
            "before any part of it is parsed (ADR-0231 §5). At least 1. A response "
            "beyond it is **abandoned and refused**, never truncated."
        ),
    )

    # --- What one search may bring back (ADR-0231 §5, §10, §17) -----------
    # The last two of ADR-0231 §5's four fields, landing with the searcher that
    # enforces them, "since a bound nothing reads is a figure an operator can set
    # and watch do nothing".
    #
    # **Both are the *searcher's* to enforce and never the model's** (§17).
    # `SearchOutcome` carries neither bound and validates identically in every
    # deployment, which is what makes the type shareable by two searchers
    # configured differently in one process.
    #
    # **Three is a ceiling the setting narrows and never widens** (§5). §10's figure
    # is the maximum, so `le=3` is part of the domain rather than a default: it is
    # what keeps §11's precedence true in *every* configuration, so no deployment
    # can make one search take a third of ADR-0226 §6's budget of ten.
    search_max_results: _IntegerSetting = Field(
        default=3,
        ge=1,
        le=3,
        description=(
            "The most records one web search may mint, one per result the provider "
            "returned and in that order (ADR-0231 §5, §10). From 1 to 3: three is "
            "ADR-0231 §10's ceiling and this setting only narrows it."
        ),
    )
    # **Counted on the quoted rendering, exactly as ADR-0230 §6 counts a fetched
    # document** — `json.dumps` at its default `ensure_ascii=True`, its two
    # delimiters included — and never on the source. A ceiling on source characters
    # would admit a result six or twelve times this long while claiming to admit
    # this much (ADR-0222 §4), because an escaped BMP code point costs six output
    # characters and an astral one twelve.
    #
    # **A result beyond it is dropped, never truncated** (§10): the remaining
    # results are minted, and a response every result of which is dropped yields
    # `SearchRefusal.NO_RESULT` rather than an empty success. Truncating would carry
    # a fragment of a third party's words that no reader could tell from the whole.
    search_max_result_chars: _IntegerSetting = Field(
        default=2048,
        ge=1,
        lt=2**63,
        description=(
            "The most characters one minted search record's content may carry, "
            "counted on its quoted rendering (ADR-0231 §5, §10; ADR-0230 §6's "
            "measure). At least 1. A result beyond it is **dropped**, never "
            "truncated, and its siblings are still minted."
        ),
    )

    # --- The registered search account (ADR-0231 §5, §17) -----------------
    # **Which connected account the web search is registered against, and the one
    # origin it names.** Both, or neither: a deployment that names both gets a
    # searcher registered at the egress seam and bound to that account; a
    # deployment that names neither gets no searcher at all, and
    # `WebSearcher.request` answers `None` — "a configuration fact and never a
    # failure". The composition root derives the searcher and the seam's
    # registration entry from this one pair, so they cannot disagree.
    #
    # **These are the connected account's configuration and not two more of
    # ADR-0231 §5's four bounds.** That section adds exactly four `Settings`
    # fields — `search_query_max_chars`, `search_max_results`,
    # `search_max_result_chars` and `search_max_response_bytes` — each "with the
    # named default, stated domain and load-time refusal ADR-0230 §6 requires of
    # its own", and all four are above. What is here is the same pair every
    # registering lane owes, in `send_email_connection`/`send_email_endpoint`'s
    # own shape and for its own reason: §5 requires the request to be built "from
    # the connected account's configuration alone" and pins the channel to "the
    # one origin the connected account names", and nothing in the tree records
    # either — ADR-0149 §13 rules that "a connection record carries no endpoint and
    # no description". So an operator states both, exactly as they do for the mail
    # integration.
    #
    # **The reference names an existing record; it does not propose one**
    # (ADR-0151 §3), and an unknown or disconnected one is not validated at load:
    # what the store holds is read per call by the binding seam, which refuses an
    # unconnectable reference with the record in hand (ADR-0152 §6). Both are
    # `send_email_connection`'s clauses for its reasons.
    web_search_connection: str | None = Field(
        default=None,
        description=(
            "The connection reference the web search is registered against — a "
            "handle the provisioner minted, read out of the connections listing. "
            "Set it together with web_search_origin, or set neither and no "
            "searcher is built."
        ),
    )
    web_search_origin: str | None = Field(
        default=None,
        description=(
            "The one HTTPS origin the connected search account names, as "
            "https://host[:port] (ADR-0231 §5, §8). The searcher pins the "
            "authorised call to exactly this origin and opens a channel to no "
            "other. Set it together with web_search_connection."
        ),
    )

    # --- What one search costs this deployment (ADR-0236 §1, §2) -----------
    # **The operator's per-call figure, in two fields, and the whole of what
    # ADR-0236 adds to configuration.** ADR-0231 §5's declaration clause already
    # names the field these supply — "a `cost` that is the operator's configured
    # per-call figure where one is configured and `UNKNOWN` where none is" — and
    # left no route to configure one; these are that route.
    #
    # **Two fields rather than one, and neither carries a grammar** (§1). A single
    # setting holding `"USD 0.005"` would invent a parse, a third spelling of a
    # currency alongside `ToolCost.currency`'s and `world_spend_currency`'s. The
    # pair is `web_search_connection`/`web_search_origin`'s shape one field pair
    # along, refused half-set for the same stated reason.
    #
    # **The `web_search_` prefix and not `search_`, deliberately** (§1). The four
    # `search_*` bounds are what the composer, the searcher and the transport
    # enforce; this is the connected account's commercial fact, in the same class
    # as which account and which origin.
    #
    # **They reach a `ToolCost` at exactly one place in production**
    # (`ai_assistant.tools.builtin.build_web_search_integration`, §1): the
    # composition root reads both and passes them through unchanged, applying no
    # default, performing no arithmetic and constructing no `ToolCost`, and
    # nothing in `interfaces/`, `orchestration/` or `permissions/` reads either.
    #
    # **`FREE` is unreachable from here** (§3): the only two states a deployment
    # can put the declaration's `cost` field in are the `PER_CALL` figure the pair
    # builds and the `UNKNOWN` its absence leaves. An operator whose account bills
    # them nothing states `web_search_cost_per_call = 0` with the currency they
    # are denominated in, which is a positive assertion carrying a register.
    web_search_cost_per_call: Decimal | None = Field(
        default=None,
        description=(
            "What one search costs this deployment, as the operator's own figure "
            "(ADR-0236 §1). At least zero — a free tier is a zero figure, not a "
            "FREE basis — finite, and countable under ADR-0194 §1. Set it "
            "together with web_search_cost_currency, and only where a search "
            "account is connected. Unset, the declaration's cost is UNKNOWN: the "
            "cost floor fires alongside the disclosure floor, so no standing "
            "grant is consulted and no search can be ALLOWed, and the ruling is "
            "CONFIRM unless this deployment's own deny thresholds reach a LOW, "
            "REVERSIBLE declaration."
        ),
    )
    web_search_cost_currency: str | None = Field(
        default=None,
        description=(
            "ISO-4217 alphabetic code web_search_cost_per_call is denominated in "
            "(ADR-0236 §1, §2). Shape only, neither normalised nor checked "
            "against the live register. It is not required to equal "
            "world_spend_currency (§6); where the two differ the gate treats the "
            "declared cost exactly as it treats an UNKNOWN basis. Set it together "
            "with web_search_cost_per_call: unset, the declaration's cost is "
            "UNKNOWN, so no standing grant is consulted and no search can be "
            "ALLOWed."
        ),
    )

    # --- The registered egress integration (ADR-0152 §10, ADR-0154 §6) ----
    # **Which connected account `send_email` is registered against, and where it
    # submits.** Both, or neither: a deployment that names both gets the tool
    # registered *and* bound to that account; a deployment that names neither does
    # not get the tool at all. The composition root derives the registry's contents
    # and the seam's registration table from this one pair, so they cannot disagree
    # (`ai_assistant.tools.builtin.build_send_email_integration`).
    #
    # **Why this is configuration rather than something derived from what is
    # connected.** Nothing in the tree records which service a connected account is
    # on. ADR-0151 §18 scopes that out by name — "what an integration *is*: an
    # endpoint, a service identity, a scope list, an account chooser" — and
    # ADR-0149 §13 states the consequence: "a connection record carries no endpoint
    # and no description". So neither the reference nor the endpoint is derivable
    # from a connection record, and until the ADR §18 says fires with the first
    # integration lands, an operator states both. That ADR supersedes these two
    # fields when it does (issue filed alongside this change).
    #
    # **The reference names an existing record; it does not propose one.** ADR-0151
    # §3 is emphatic that "no client, no ``Settings`` value, no configuration file
    # and no model-authored value supplies, proposes, constrains or predicts" a
    # connection reference — and that clause governs the **minting** of one at
    # ``connect_account``, which still mints from its own draw and still takes no
    # reference argument. Nothing here mints, proposes or predicts: the operator
    # reads a reference the provisioner already minted out of the connections
    # listing and states which of them a registration binds. That is selection
    # among what exists, which ADR-0149 §4's "nothing may create a connection from
    # configuration" also leaves untouched — a registration creates no connection.
    #
    # An unknown or disconnected reference is **not** validated here: what the
    # store holds is read per call by the binding seam, which refuses an
    # unconnectable reference at bind time (ADR-0152 §6) rather than at load. A
    # startup check would be a second, staler answer to a question the seam already
    # asks with the record in hand.
    send_email_connection: str | None = Field(
        default=None,
        description=(
            "The connection reference `send_email` is registered against — a handle "
            "the provisioner minted, read out of the connections listing. Set it "
            "together with send_email_endpoint, or set neither and the tool is not "
            "registered."
        ),
    )
    send_email_endpoint: str | None = Field(
        default=None,
        description=(
            "The SMTP submission endpoint `send_email` is configured to use, as "
            "smtps://host[:port] or smtp+starttls://host[:port] (ADR-0148 §6). The "
            "transport pins the connection to exactly this text and opens no other "
            "(#83). Set it together with send_email_connection."
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

    # --- The standing recipient grant (ADR-0193 §1) -----------------------
    # The one figure the recipient-grant store takes, supplied to the concrete
    # store at construction. It bounds how many **outstanding granting records**
    # the store holds, and ``record`` refuses a granting record that would take
    # the count above it rather than truncating, evicting or expiring anything to
    # make room.
    #
    # **Counted over *outstanding* rather than over *live*, and the substitution
    # is in the tighter direction** (§1). Live is outstanding plus the clock, and
    # ``record`` reads no clock; outstanding is a fact about two records, so a
    # ceiling counted over it is at least as tight as one counted over live and
    # never looser. What it costs is that an expired grant occupies its slot until
    # it is revoked — the same shape the duplicate rule already has — and the
    # recourse is the revocation §9 gives the user.
    #
    # **Zero is meaningful rather than a misconfiguration**: it is how a deployment
    # declines route (b). It is **admission-only like every other value** and is
    # not a kill switch — a store already holding live grants keeps them,
    # ``covering`` keeps returning them, and the rows they source keep being
    # written. What may not be created by configuration may not be destroyed by it
    # either (ADR-0097 §8 read in the other direction); the way to make an existing
    # grant stop covering is that the user revokes it, or clears the store.
    #
    # ``ge=0`` rather than ``ge=1``, and a negative is refused at load: an
    # implementation special-casing only zero would accept ``-1``, which would
    # refuse every granting write for a reason no message explains.
    #
    # **Sixty-four is ADR-0193 §1's own default** and is not a recommendation to a
    # deployment (§13): high enough that ordinary use never reaches it, low enough
    # that this store's ``standing()`` stays small in practice while #1551 answers
    # the unbounded-read question for this store and ``SourceGrantStore`` together.
    # A ``_IntegerSetting`` without a default would leave a fresh ``Settings()``
    # undefined, and a lane free to pick would be picking whether route (b) is
    # reachable at all.
    recipient_grant_max_outstanding: _IntegerSetting = Field(
        default=64,
        ge=0,
        lt=2**63,
        description=(
            "How many outstanding standing recipient grants the store admits "
            "(ADR-0193 §1). Zero declines route (b) for a deployment that has "
            "never established one; it retracts nothing from a store that has."
        ),
    )

    # --- The source-read trail (ADR-0185 §6) ------------------------------
    # The one figure this store takes, and the **only** bound it has: a row cap,
    # deliberately not a duration. Every other retention figure here is a duration,
    # and each governs a store whose inflow is bounded by something else — a user
    # act, a conversation, a measurement window. This store's inflow is a *timer*,
    # so a duration bound would leave its size a function of read cadence, which is
    # precisely the quantity ADR-0139 §6's arithmetic is about: "A calendar read on
    # a five-minute interval is on the order of a hundred thousand rows a year, for
    # a deployment with one source." A row cap bounds the store no matter how fast
    # the timer runs. ADR-0185 §14 defers an age bound *beside* it, with the
    # condition that fires one.
    #
    # **There is no unlimited spelling, and the absence is the mechanism** (§6). No
    # sentinel, no ``none``, no zero, no negative — so no deployment can configure
    # the unbounded Tier 1 store ADR-0097 §12 objected to. `notification_queue_limit`
    # already carries the property in its own description and is the right precedent;
    # `trace_retention` and `notification_retention` both accept ``'none'``, and a
    # figure this store accepted ``'none'`` for would be "append and see" with a
    # config key. It is refused **at load** rather than at the first prune, which is
    # ADR-0077 §1's rule as ADR-0093 §5 quotes it: "A setting the store read would
    # refuse must fail at load, not at the first observation."
    #
    # **The figures are ADR-0185 §6's own**, named there rather than left to the
    # lane: 200,000 rows by default, and every strictly positive integer below
    # ``2**63`` admissible — `notification_queue_limit`'s form, which keeps a
    # configured value inside the domain a store's own count can hold. At ADR-0139
    # §6's five-minute figure that is about 1.9 years of one ``(source, use)``
    # stream, or about 7 months if four such streams ran at that cadence: long
    # enough that a revocation made last year is still answerable, and bounded
    # whatever happens.
    #
    # The store evicts the **earliest-recorded** rows when an append would exceed
    # this, which is the opposite of `notification_queue_limit`'s choice and right
    # for the opposite reason (§6): a notification queue holds candidates that have
    # not happened yet, so dropping the newest loses least, while an audit trail
    # holds acts that already happened — and a store that refused new rows when full
    # would, under §5's fail-closed rule, stop the assistant reading sources at all
    # because a log filled up.
    source_read_trail_max_rows: _IntegerSetting = Field(
        default=200_000,
        gt=0,
        lt=2**63,
        description=(
            "The most source-read records the trail holds; beyond it the earliest "
            "recorded are pruned rather than a new one refused (ADR-0185 §6). Positive, "
            "with no unlimited spelling."
        ),
    )

    # --- The routing trail's horizon (ADR-0197 §9) ------------------------
    # The shape and the number ``source_read_trail_max_rows`` already carries, and
    # ADR-0197 §9 chooses them for a stated reason rather than by imitation: a
    # routing row is smaller than a read row, and the two trails are read by the
    # same kind of operator. **No spelling for "unlimited"** (ADR-0185 §6 applied
    # here), and pruning is earliest-recorded-first inside ``record``'s critical
    # section and blind to what the row says — an unanswered park's ``OWED`` row is
    # pruned at the bound like any other, and pruning it neither evicts the park nor
    # releases its slot nor makes its token unresolvable. The park is in memory and
    # the trail is the record rather than the state.
    routing_trail_max_rows: _IntegerSetting = Field(
        default=200_000,
        gt=0,
        lt=2**63,
        description=(
            "The most routed-operation records the trail holds; beyond it the earliest "
            "recorded are pruned rather than a new one refused (ADR-0197 §9). Positive, "
            "with no unlimited spelling."
        ),
    )

    # --- The ceiling on what the world may cost (ADR-0194 §1) -------------
    # **Exactly four fields and no others.** They are the whole of what the spend
    # mechanism adds to configuration: no lane adds a fifth, and these four are the
    # only settings that turn it on or change what it refuses given a period. The
    # mechanism reads one *existing* setting besides them — :attr:`timezone`, whose
    # influence is period selection and nothing else: it fixes the ``[start, end)``
    # bounds, so which period a row falls in and therefore which total an admission
    # is compared against. ``app/composition.py`` is the sole reader of all five
    # (ADR-0194 §5) and hands the holder explicit values.
    #
    # **Unset means unbounded, and that is a decision rather than optimism**
    # (ADR-0194 §1). Nothing reaches the world today without the user answering
    # about that specific call — ADR-0021 §5's disclosure floor and ADR-0148 §3's
    # per-call route — so an unconfigured ceiling declines to add a second lock to a
    # door already answered one call at a time. A defaulted number would be worse in
    # both directions: too low and it refuses work the user authorised, in a currency
    # ``core`` chose for a user it does not know; too high and it is decoration.
    #
    # **The four land here, in the same change as the invoker's consultation of the
    # gate** (ADR-0194 §11). Landed apart, a merged tree would exist in which
    # ``world_spend_day_ceiling=0`` loads without error, no surface reports anything
    # wrong, and a confirmed send executes anyway — a user who read a configured
    # ceiling as a ceiling would be wrong for the length of that window, which is the
    # one failure the whole mechanism exists to prevent.
    world_spend_currency: str | None = Field(
        default=None,
        description=(
            "ISO-4217 alphabetic code the spend ceiling and its totals are denominated "
            "in (ADR-0194 §1). Set alone it configures a reporting currency: totals are "
            "computed and readable and nothing is ever refused."
        ),
    )
    world_spend_month_ceiling: Decimal | None = Field(
        default=None,
        description=(
            "Most the world may cost across a calendar month in the configured zone "
            "(ADR-0194 §1); unset means unbounded. Needs world_spend_currency."
        ),
    )
    world_spend_day_ceiling: Decimal | None = Field(
        default=None,
        description=(
            "Most the world may cost across a calendar day in the configured zone "
            "(ADR-0194 §1); unset means unbounded. Needs world_spend_currency. Both "
            "ceilings bind independently, and a day ceiling above the month ceiling is "
            "accepted — it is simply never the binding one."
        ),
    )
    world_spend_unknown_allowance: Decimal | None = Field(
        default=None,
        description=(
            "What one UNKNOWN-priced call is accounted at (ADR-0194 §2); unset, such a "
            "call is refused rather than counted as zero. Strictly greater than zero, "
            "and needs world_spend_currency. It is the user supplying the fact the "
            "tool's author could not, never an escape hatch: nothing in a turn can "
            "read, set or raise it."
        ),
    )

    @field_validator("world_spend_currency", "web_search_cost_currency")
    @classmethod
    def _spend_currency_is_iso_4217_alphabetic(cls, value: str | None) -> str | None:
        """Require ADR-0194 §1's shape, or nothing at all.

        **Shape only** — exactly three uppercase ASCII letters, neither normalised
        nor checked against the live register. That is ``ToolCost.currency``'s rule
        (ADR-0016 §4) and not a second one, so the two sides of a comparison are
        spelled the same way. ``ASSISTANT_WORLD_SPEND_CURRENCY=`` sets the variable
        to the empty string rather than to nothing, which is why the blank is
        refused here rather than read as unconfigured.

        **``web_search_cost_currency`` is validated by this same validator and not
        by a copy of it** (ADR-0236 §2): that section states the code's rule as
        *"``ToolCost.currency``'s rule (ADR-0016 §4) and ``world_spend_currency``'s,
        and not a third one"*, and one decorator naming both fields is what makes
        that a property of the code rather than of two functions staying in step.
        The two settings are still **independent** (§6): nothing here compares
        them, and a deployment may denominate its search in one currency and meter
        its spend in another.
        """
        if value is None:
            return value
        if len(value) != _SPEND_CURRENCY_LENGTH or not (
            value.isascii() and value.isupper() and value.isalpha()
        ):
            msg = f"must be three uppercase ASCII letters (ISO-4217), got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("world_spend_month_ceiling", "world_spend_day_ceiling")
    @classmethod
    def _spend_ceiling_is_countable_and_not_negative(
        cls, value: Decimal | None, info: ValidationInfo
    ) -> Decimal | None:
        """Require a finite, non-negative, countable ceiling (ADR-0194 §1).

        Non-finite is refused as ``ToolCost.amount`` refuses one and for the same
        reason: ``Decimal`` admits ``Infinity`` and ``NaN``, neither survives
        arithmetic in a running total, and ``NaN`` makes every comparison false
        rather than answering. **Zero is a valid ceiling** and binds hardest of all,
        so nothing here reads falsiness.
        """
        return _checked_spend_amount(value, info.field_name, floor="zero")

    @field_validator("world_spend_unknown_allowance")
    @classmethod
    def _spend_allowance_is_countable_and_positive(
        cls, value: Decimal | None, info: ValidationInfo
    ) -> Decimal | None:
        """Require a finite, countable allowance strictly greater than zero.

        Zero is refused in every spelling ``Decimal`` admits for it —
        ``Decimal("0")``, ``Decimal("-0")``, ``Decimal("0.00")``, ``Decimal("0E-9")``
        — which ``> 0`` decides for all four at once. A **negative** allowance is the
        one this refusal is load-bearing for: it would let an ``UNKNOWN`` estimate
        *lower* a projection and admit a call already at its ceiling, which is the
        one direction the mechanism must never move in.
        """
        return _checked_spend_amount(value, info.field_name, floor="positive")

    @field_validator("web_search_cost_per_call")
    @classmethod
    def _search_cost_is_countable_and_not_negative(
        cls, value: Decimal | None, info: ValidationInfo
    ) -> Decimal | None:
        """Require ADR-0236 §2's domain for the operator's per-call figure.

        Finite, at least zero, and countable under ADR-0194 §1 — **reusing**
        :func:`_checked_spend_amount` at the ceilings' own floor rather than
        restating §1's predicate a third time in this module, which is what
        ADR-0236 §7's first clause asks for.

        **Countability is not a bound this decision invents.** ADR-0194 §1's
        predicate *"governs every amount this mechanism reads: a configured
        ceiling, the allowance, a declared ``ToolCost.amount`` and a reported
        one"*, and this figure becomes a declared ``ToolCost.amount`` the moment
        the builder runs. Admitting an uncountable one would mean a declaration
        that loads, registers, rules ``ALLOW`` and is then refused at the gate with
        ``SpendUndeterminedError`` on every call.

        **Zero is admissible**, which is the floor ``ToolCost.amount`` itself
        carries and a ceiling's rather than the allowance's: ADR-0194 §1 refuses a
        zero *allowance* because an allowance stands in for an unknown, and nothing
        in that argument reaches a price an operator states about a call they are
        paying for (ADR-0236 §2, §3).
        """
        return _checked_spend_amount(value, info.field_name, floor="zero")

    @model_validator(mode="after")
    def _spend_amounts_need_a_currency(self) -> Settings:
        """Refuse a ceiling or an allowance with no currency to state it in.

        ADR-0194 §1: a ceiling and the allowance may each be set only where
        ``world_spend_currency`` is. The currency **may** be set alone. Without this,
        ``world_spend_day_ceiling=10`` loads beside no currency and silently caps
        nothing, which is a configured ceiling that does not bind — the failure §11
        puts these four fields in this change to prevent.

        No ordering is imposed between the two ceilings: §1 accepts a day ceiling
        above the month ceiling and says the month is simply the binding one, so a
        validator quietly requiring ``day <= month`` would reject a configuration
        this ADR calls valid.
        """
        if self.world_spend_currency is not None:
            return self
        for name in (
            "world_spend_month_ceiling",
            "world_spend_day_ceiling",
            "world_spend_unknown_allowance",
        ):
            if getattr(self, name) is not None:
                msg = f"{name} needs world_spend_currency, which is not set"
                raise ValueError(msg)
        return self

    @field_validator(
        "send_email_connection", "send_email_endpoint", "web_search_connection", "web_search_origin"
    )
    @classmethod
    def _is_not_blank(cls, value: str | None) -> str | None:
        """Refuse a blank value, which the environment makes easy to produce.

        ``ASSISTANT_SEND_EMAIL_ENDPOINT=`` sets the variable to the empty string,
        not to nothing, so without this a cleared variable reads as *configured*
        and only fails much later — at a bind, or at a parse inside the transport.
        The value is taken **verbatim** otherwise: a reference is compared against
        the store byte-for-byte and an endpoint is compared as text before it is
        parsed (ADR-0154's condition 5), so stripping or case-folding here would
        make two spellings of one endpoint into one and defeat that comparison.

        Raises:
            ValueError: If the value is present and holds no non-whitespace text.
        """
        if value is not None and not value.strip():
            msg = "must hold text, or be unset entirely"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _the_egress_registration_is_whole_or_absent(self) -> Settings:
        """Refuse half a registration for ``send_email``.

        The two fields are one fact stated in two variables, and either alone
        describes a state the system cannot be in: an account with nowhere to
        submit, or a submission endpoint with no account to submit as. Neither is a
        thing to fail *later* over, because "later" is a user's send — the operator
        would learn that half their configuration never took effect at the moment a
        message did not go out.

        Refused rather than treated as "not configured", because the two readings
        of a half-set pair are opposite and the safe one is not the quiet one: an
        operator who set one variable believes the tool is registered, and a
        deployment that silently registered nothing would leave them believing it
        while every send failed to select a tool at all. This is ADR-0062 §3's
        posture for a well-formed but useless configuration, applied one field pair
        along.

        Raises:
            ValueError: If exactly one of the two is set.
        """
        connection, endpoint = self.send_email_connection, self.send_email_endpoint
        if (connection is None) == (endpoint is None):
            return self
        set_one = "send_email_connection" if endpoint is None else "send_email_endpoint"
        missing = "send_email_endpoint" if endpoint is None else "send_email_connection"
        msg = (
            f"{set_one} is set and {missing} is not; registering send_email needs both "
            f"the connected account it sends as and the endpoint it submits to "
            f"(ADR-0148 §6), so set {missing} as well or unset {set_one} to leave the "
            f"tool unregistered"
        )
        raise ValueError(msg)

    @model_validator(mode="after")
    def _the_search_registration_is_whole_or_absent(self) -> Settings:
        """Refuse half a registration for the web search (ADR-0231 §5, §17).

        The clause above, one field pair along and for exactly its reasons: an
        account with no origin to ask, or an origin with no account to ask it as,
        is a state the system cannot be in, and the quiet reading is the unsafe
        one. "Later" here is a turn whose planner asked for a search and whose
        searcher was never built, which an operator would read as the mechanism
        being inert rather than as their configuration having half-landed.

        Raises:
            ValueError: If exactly one of the two is set.
        """
        connection, origin = self.web_search_connection, self.web_search_origin
        if (connection is None) == (origin is None):
            return self
        set_one = "web_search_connection" if origin is None else "web_search_origin"
        missing = "web_search_origin" if origin is None else "web_search_connection"
        msg = (
            f"{set_one} is set and {missing} is not; registering the web search needs "
            f"both the connected account it asks as and the one origin it asks "
            f"(ADR-0231 §5), so set {missing} as well or unset {set_one} to leave no "
            f"searcher built"
        )
        raise ValueError(msg)

    @model_validator(mode="after")
    def _the_search_cost_is_whole_and_only_where_a_search_is(self) -> Settings:
        """Refuse half a per-call figure, and a figure nothing would read (ADR-0236 §2).

        Two refusals, in the shape
        :meth:`_the_search_registration_is_whole_or_absent` already gives this kind
        and for its reasons.

        **Both or neither.** ``ToolCost`` needs an amount *and* an ISO-4217 code
        for a ``PER_CALL`` basis, so a lone amount is a figure denominated in
        nothing and a lone code is a register for no figure. Neither can become a
        declaration, and the quiet reading — silently falling back to ``UNKNOWN`` —
        is the unsafe one: an operator who set one variable believes their searches
        are priced, and would meet the cost floor on every one of them with no
        indication that their configuration had half-landed.

        **And only where a search is registered.** A per-call figure for a searcher
        no deployment builds is a value nothing reads: ``app/composition.py``
        constructs no ``WebSearchIntegration`` at all unless both
        ``web_search_connection`` and ``web_search_origin`` are set, so the pair
        would reach no builder and no declaration.

        Raises:
            ValueError: If exactly one of the two is set, or if either is set while
                the search registration is not whole.
        """
        amount, currency = self.web_search_cost_per_call, self.web_search_cost_currency
        if (amount is None) != (currency is None):
            set_one = "web_search_cost_per_call" if currency is None else "web_search_cost_currency"
            missing = "web_search_cost_currency" if currency is None else "web_search_cost_per_call"
            msg = (
                f"{set_one} is set and {missing} is not; a declared per-call cost needs "
                f"both the figure and the ISO-4217 code it is denominated in "
                f"(ADR-0236 §1), so set {missing} as well or unset {set_one} to leave the "
                f"search declaring an UNKNOWN cost"
            )
            raise ValueError(msg)
        if amount is None:
            return self
        if self.web_search_connection is not None and self.web_search_origin is not None:
            return self
        msg = (
            "web_search_cost_per_call and web_search_cost_currency are set and no search "
            "account is connected; a per-call figure for a searcher no deployment builds "
            "is a value nothing reads (ADR-0236 §2), so set web_search_connection and "
            "web_search_origin as well or unset both cost fields"
        )
        raise ValueError(msg)

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
