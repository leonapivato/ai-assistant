"""Tests for Settings validation of the context configuration (ADR-0008)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, get_args

import numpy
import pytest
from pydantic import ValidationError
from pydantic_ai.models import known_model_names

from ai_assistant.core.config import (
    _MODEL_SPEC_PATTERN,
    EmbedderKind,
    Settings,
    load_settings,
)
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import Reversibility, RiskLevel

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import SupportsIndex


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


def test_embedder_defaults_to_on_device() -> None:
    # ADR-0006 §2's firm decision: on-device embedding is the default, so an unset
    # deployment gets semantic (and privacy-preserving) recall, not the non-semantic
    # hashing stand-in (roadmap leg 2).
    assert Settings().embedder is EmbedderKind.ON_DEVICE


def test_embedder_accepts_the_hashing_mode() -> None:
    assert Settings(embedder=EmbedderKind.HASHING).embedder is EmbedderKind.HASHING


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("on-device", EmbedderKind.ON_DEVICE),
        ("hashing", EmbedderKind.HASHING),
    ],
)
def test_embedder_round_trips_from_the_environment(
    value: str, expected: EmbedderKind, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The operator-facing channel: the ASSISTANT_-prefixed variable is parsed from
    # the enum's member value, so a deployment can drop to the hashing embedder
    # (offline/CI) without touching code.
    monkeypatch.setenv("ASSISTANT_EMBEDDER", value)
    assert load_settings().embedder is expected


@pytest.mark.parametrize("value", ["fastembed", "ON-DEVICE", "cloud", ""])
def test_off_mode_embedder_is_rejected(value: str) -> None:
    # A mode selector, not a free-form spec (ADR-0024 vendors one model): anything
    # off the two members — including a wrong-case member — fails at load.
    with pytest.raises(ValidationError):
        Settings(embedder=value)  # type: ignore[arg-type]  # invalid input under test


def test_load_settings_rejects_an_off_mode_embedder_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_EMBEDDER", "cloud")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_embedding_timeout_defaults_to_thirty_seconds() -> None:
    # ADR-0118 §4 fixes the figure. It is a ceiling on pathology rather than a
    # latency target: it has to clear a cold ONNX session initialisation on a slow
    # disk plus one inference with headroom, because the on-device embedder loads
    # lazily inside ``embed`` and a deadline that fired on an ordinary cold start
    # would break the first write after every hub restart.
    assert Settings().embedding_timeout_seconds == 30.0


@pytest.mark.parametrize("value", [0, -1.0, float("inf"), float("nan")])
def test_an_unusable_embedding_timeout_is_rejected(value: float) -> None:
    # ``gt=0`` and ``allow_inf_nan=False`` together, and both arms matter: zero or
    # negative expires every call before it starts, and infinity silently disables
    # the deadline — the one outcome ADR-0118 exists to prevent, arriving as a
    # configuration value rather than as a missing bound.
    with pytest.raises(ValidationError):
        Settings(embedding_timeout_seconds=value)


def test_embedding_timeout_round_trips_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The operator's channel: ADR-0118 §8 makes the field, not a code change, the
    # remedy for a deployment whose hardware genuinely needs longer.
    monkeypatch.setenv("ASSISTANT_EMBEDDING_TIMEOUT_SECONDS", "90.5")
    assert load_settings().embedding_timeout_seconds == 90.5


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


# --- conversations: the two ADR-0074 durations (#449) --------------------


def test_episode_retention_defaults_to_a_finite_horizon() -> None:
    # ADR-0074 §7's load-bearing default, and the one an implementation copying
    # `confirmation_ttl`'s shape gets wrong: `None` there means "a parked
    # confirmation never goes stale" and here would mean unbounded episodic
    # retention — an ever-growing Tier 1 log of everything the user has ever
    # typed, which is exactly what §7 rejects.
    horizon = Settings().episode_retention
    assert horizon is not None
    assert horizon > timedelta(0)


def test_episode_retention_accepts_an_explicit_none_as_keep_forever() -> None:
    # The pair with the case above. `None` is the user's deliberate choice, and it
    # also switches conversation reclaim off entirely (ADR-0074 §7).
    assert Settings(episode_retention=None).episode_retention is None


def test_episode_retention_is_disabled_from_the_environment_by_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default is finite, so omitting the variable can never reach `None` and
    # no duration literal spells it: without the sentinel "keep forever" would be
    # unreachable from a deployment, which §7 says it must not be.
    monkeypatch.setenv("ASSISTANT_EPISODE_RETENTION", "none")
    assert load_settings().episode_retention is None


def test_episode_retention_parses_an_iso_duration_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_EPISODE_RETENTION", "P7D")
    assert load_settings().episode_retention == timedelta(days=7)


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_a_non_positive_episode_retention_is_rejected(value: timedelta) -> None:
    # Zero is not a spelling for "keep forever"; `None` is.
    with pytest.raises(ValidationError):
        Settings(episode_retention=value)


def test_conversation_tombstone_grace_defaults_to_something_positive_and_finite() -> None:
    # ADR-0074 §8: the two values that break the deletion protocol do so in
    # opposite directions — a zero grace drops the index immediately, orphaning
    # the late write the tombstone exists to catch, and an unbounded one keeps
    # every deleted conversation's index forever.
    grace = Settings().conversation_tombstone_grace
    assert grace > timedelta(0)


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_a_non_positive_conversation_tombstone_grace_is_rejected(value: timedelta) -> None:
    with pytest.raises(ValidationError):
        Settings(conversation_tombstone_grace=value)


def test_the_tombstone_grace_has_no_none_spelling() -> None:
    # §8 declines to offer one at all, because "no grace" and "infinite grace" are
    # precisely the two values that break the protocol and a nullable field spells
    # one of them.
    with pytest.raises(ValidationError):
        Settings(conversation_tombstone_grace=None)  # type: ignore[arg-type]  # the point


def test_the_tombstone_grace_is_not_disabled_by_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sentinel is per-field and this field does not opt in, so "none" is judged
    # as a duration and refused rather than quietly becoming an unbounded grace.
    monkeypatch.setenv("ASSISTANT_CONVERSATION_TOMBSTONE_GRACE", "none")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_load_settings_rejects_a_non_positive_tombstone_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_CONVERSATION_TOMBSTONE_GRACE", "PT0S")
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


# --- Model specs: the default and its fallbacks (ADR-0062, #353) -------------


def test_no_fallback_models_are_configured_by_default() -> None:
    # An unset deployment must keep the single-route behaviour ADR-0061 §2
    # described: the fallback list is opt-in, and adding the setting changes
    # nothing for anyone who does not set it.
    assert Settings().fallback_models == ()


def test_fallback_models_parse_as_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole of decision 1: an operator writes specs the way they write a
    # model name, not as a JSON array. pydantic-settings would otherwise parse
    # this field's environment value as JSON, because its type is complex.
    monkeypatch.setenv("ASSISTANT_FALLBACK_MODELS", "openai:gpt-5,anthropic:claude-x")
    assert load_settings().fallback_models == ("openai:gpt-5", "anthropic:claude-x")


def test_fallback_models_tolerate_spacing_and_a_trailing_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_FALLBACK_MODELS", " openai:gpt-5 , anthropic:claude-x , ")
    assert load_settings().fallback_models == ("openai:gpt-5", "anthropic:claude-x")


@pytest.mark.parametrize("value", ["", "   ", " , "])
def test_an_empty_fallback_list_means_no_fallbacks(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setting the variable to nothing must mean the same as not setting it, so an
    # operator can switch fallbacks off without editing the deployment's shape.
    monkeypatch.setenv("ASSISTANT_FALLBACK_MODELS", value)
    assert load_settings().fallback_models == ()


def test_fallback_models_keep_the_order_they_were_written_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Preference order is the operator's statement, so it is preserved verbatim —
    # never sorted, never deduplicated into a set.
    monkeypatch.setenv("ASSISTANT_FALLBACK_MODELS", "openai:z,openai:a,anthropic:m")
    assert load_settings().fallback_models == ("openai:z", "openai:a", "anthropic:m")


def test_a_tuple_passed_directly_is_not_run_through_the_string_splitter() -> None:
    # Non-string input falls through untouched, so a caller constructing Settings
    # in Python (a test, a harness) is not forced through the environment's
    # encoding — and a spec that happens to contain a comma is not re-split.
    assert Settings(fallback_models=("openai:gpt-5",)).fallback_models == ("openai:gpt-5",)


def test_a_list_passed_directly_keeps_its_order() -> None:
    # A list is ordered, so it is an acceptable statement of preference. mypy sees
    # only the declared ``tuple[str, ...]`` and rejects a list statically; the
    # runtime accepts and coerces it, which is what this pins.
    assert Settings(fallback_models=["openai:a", "openai:b"]).fallback_models == (  # type: ignore[arg-type]
        "openai:a",
        "openai:b",
    )


@pytest.mark.parametrize(
    "collection",
    [
        pytest.param({"openai:gpt-5", "anthropic:claude-x"}, id="set"),
        pytest.param(frozenset({"openai:gpt-5", "anthropic:claude-x"}), id="frozenset"),
    ],
)
def test_an_unordered_fallback_collection_is_rejected(collection: object) -> None:
    # ADR-0062 §1 makes the written order the operator's preference, so pydantic's
    # lax coercion of a set to a tuple in hash order would silently discard it and
    # let the router's primary fallback differ between processes (issue #359). The
    # message names *order* as the reason, so the fix is discoverable.
    with pytest.raises(ValidationError, match="ordered sequence"):
        Settings(fallback_models=collection)  # type: ignore[arg-type]  # the wrong type is the subject


def test_a_one_shot_iterator_of_fallbacks_is_rejected() -> None:
    # A generator's order is defined only by a traversal that also consumes it, so
    # it cannot be trusted to carry a preference; refused rather than coerced.
    def specs() -> Iterator[str]:
        yield "openai:gpt-5"
        yield "anthropic:claude-x"

    with pytest.raises(ValidationError, match="one-shot iterator"):
        Settings(fallback_models=specs())  # type: ignore[arg-type]  # the wrong type is the subject


def test_a_custom_unordered_iterable_is_rejected() -> None:
    # An allowlist, not a denylist of set/iterator: an object that is neither an
    # AbstractSet nor an Iterator but iterates a set in hash order would sail past
    # a denylist and be coerced to a tuple in an unstable order. Only str/list/
    # tuple are accepted, so this is refused with the rest.
    class OrderlessIterable:
        def __iter__(self) -> Iterator[str]:
            return iter({"openai:gpt-5", "anthropic:claude-x"})

    with pytest.raises(ValidationError, match="ordered sequence"):
        Settings(fallback_models=OrderlessIterable())  # type: ignore[arg-type]  # the wrong type is the subject


def test_a_list_subclass_that_lies_about_its_order_is_rejected() -> None:
    # The allowlist is by *exact* type, not isinstance: a list subclass can
    # override __iter__ to yield a set's order, which would readmit the very
    # nondeterminism the guard refuses. Only the built-in list/tuple, whose
    # iteration is the uninterceptable C one, is accepted.
    class SetBackedList(list[str]):
        def __iter__(self) -> Iterator[str]:
            return iter({"openai:gpt-5", "anthropic:claude-x"})

    with pytest.raises(ValidationError, match="ordered sequence"):
        Settings(fallback_models=SetBackedList())  # type: ignore[arg-type]  # the wrong type is the subject


def test_a_str_subclass_that_lies_about_split_is_rejected() -> None:
    # The str branch is exact-typed for the same reason as list/tuple: a str
    # subclass can override split() to return set-ordered parts, which the guard
    # must not trust. Only the built-in str, whose split is the C one, is parsed.
    class SetBackedStr(str):
        def split(self, sep: str | None = None, maxsplit: SupportsIndex = -1) -> list[str]:
            return list({"openai:gpt-5", "anthropic:claude-x"})

    with pytest.raises(ValidationError, match="ordered sequence"):
        Settings(fallback_models=SetBackedStr("openai:gpt-5,anthropic:claude-x"))  # type: ignore[arg-type]  # the wrong type is the subject


@pytest.mark.parametrize(
    "spec",
    [
        "openai-gpt-5",  # the separator omitted — the typo this exists to catch
        "openai:",  # no model
        ":gpt-5",  # no provider
        "openai: gpt-5",  # a space inside the spec, not around it
        "none",  # the threshold sentinel, which is not a model
        '["openai:gpt-5"]',  # a JSON array, written by habit
        "test",  # pydantic-ai's in-memory dummy: the one name it ships that we
        # deliberately refuse, since the test path takes a `Model` instance
        # instead (ADR-0062 §2)
    ],
)
def test_a_malformed_model_spec_is_rejected_at_load(spec: str) -> None:
    # Both fields, because the rule is about what a model spec is, not about
    # which of the two it happens to be: a primary that fails to resolve leaves
    # the router unable to fall back at all (a bare ModelError is not routable),
    # so the primary needs this as much as a fallback does.
    with pytest.raises(ValidationError, match="malformed model spec"):
        Settings(default_model=spec)
    with pytest.raises(ValidationError, match="malformed model spec"):
        Settings(fallback_models=(spec,))


@pytest.mark.parametrize(
    "spec",
    [
        "anthropic:claude-opus-4-8",
        "openai:gpt-5",
        "bedrock:us.anthropic.claude-3-5-sonnet-20240620-v1:0",  # colons in the model half
        "gateway/openai:gpt-5",  # a slash in the provider half
        "huggingface:Qwen/Qwen3-235B-A22B",  # a slash in the model half
    ],
)
def test_a_well_formed_model_spec_is_accepted(spec: str) -> None:
    # The shapes that would most plausibly be over-rejected, spelled out so a
    # reader can see what the pattern must tolerate. Exhaustiveness against
    # pydantic-ai's real vocabulary is the test below; this one is the
    # documentation.
    assert Settings(default_model=spec).default_model == spec


def test_a_fallback_repeating_the_default_model_is_rejected() -> None:
    with pytest.raises(ValidationError, match="repeats default_model"):
        Settings(default_model="anthropic:claude-x", fallback_models=("anthropic:claude-x",))


def test_a_fallback_repeating_an_earlier_fallback_is_rejected() -> None:
    with pytest.raises(ValidationError, match=r"repeats fallback_models\[0\]"):
        Settings(fallback_models=("openai:gpt-5", "openai:gpt-5"))


def test_the_same_provider_at_a_different_model_is_a_legitimate_fallback() -> None:
    # The duplicate rule is about the *spec*, not the vendor: a cheaper or older
    # model at the same provider is a real alternative and must stay expressible.
    settings = Settings(default_model="openai:gpt-5", fallback_models=("openai:gpt-4o",))
    assert settings.fallback_models == ("openai:gpt-4o",)


def test_load_settings_reports_a_bad_fallback_list_as_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The operator-facing path: a mistake in this variable surfaces through the
    # same ConfigurationError boundary as every other setting, at load.
    monkeypatch.setenv("ASSISTANT_FALLBACK_MODELS", "openai-gpt-5")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_the_spec_pattern_accepts_every_model_name_pydantic_ai_ships() -> None:
    """Refuse to over-reject: the pattern is checked against the real vocabulary.

    ADR-0062 §Consequences promises that a pydantic-ai release adopting a
    character this pattern does not permit is *a gate failure, not a production
    surprise*. Five hand-picked examples do not deliver that promise — an upgrade
    could add a legitimate name the pattern rejects, and a deployment naming it
    would fail to start while the suite stayed green. So the check is exhaustive
    over ``known_model_names()``, which is the set an operator can legitimately
    draw from.

    The one permitted exclusion is ``test``, pydantic-ai's in-memory dummy and the
    only colon-less name it ships (ADR-0062 §2). It is subtracted rather than
    asserted present, so this test fails only for the reason it exists — a *new*
    name being rejected — and not if pydantic-ai stops shipping the dummy.
    """
    names = tuple(known_model_names())
    accepted = {name for name in names if _MODEL_SPEC_PATTERN.match(name) is not None}
    rejected = set(names) - accepted - {"test"}

    # Guard against the vacuous pass: an empty or unreadable vocabulary would
    # otherwise satisfy the assertion below while checking nothing at all.
    assert accepted, "no pydantic-ai model name matched, so this test proved nothing"
    assert not rejected, (
        "the model-spec pattern rejects names pydantic-ai ships, so a deployment "
        f"naming one could not start: {sorted(rejected)}"
    )


# --- the observer's route and its two per-call bounds (ADR-0077 §§1, 2, 3) ---


def test_observer_model_is_unset_by_default() -> None:
    """Unset means "read through the route conversation already uses" (ADR-0077 §3).

    The default that **widens nothing**: ADR-0004 §2's property is that user data
    reaches only providers the operator explicitly configured, and a default naming
    no new provider cannot breach it. Which route unset resolves to is the
    composition root's to apply — this only pins that the field says nothing.
    """
    assert Settings().observer_model is None


def test_observer_model_accepts_a_route_of_its_own() -> None:
    """Set, it names the route that reads episodes — separably from the answers'."""
    settings = Settings(observer_model="openai:gpt-5", default_model="anthropic:claude-opus-4-8")
    assert settings.observer_model == "openai:gpt-5"
    assert settings.default_model == "anthropic:claude-opus-4-8"


def test_a_malformed_observer_model_is_rejected_at_load() -> None:
    """Validated for form like every other spec (ADR-0062 §2)."""
    with pytest.raises(ValidationError, match="malformed model spec"):
        Settings(observer_model="not-a-spec")


def test_observer_model_may_repeat_the_default_model() -> None:
    """Naming the conversational route explicitly is not a useless duplicate route.

    ``_fallbacks_are_alternatives`` refuses a fallback repeating an earlier route,
    because routing would re-send the same prompt to the same place. The observer is
    not in that order at all — it is one route that never falls back — so naming
    ``default_model`` there is simply saying out loud what unset already means.
    """
    settings = Settings(default_model="openai:gpt-5", observer_model="openai:gpt-5")
    assert settings.observer_model == settings.default_model


def test_observer_model_parses_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator sets one variable to move the episodic read to another model."""
    monkeypatch.setenv("ASSISTANT_OBSERVER_MODEL", "openai:gpt-5")
    assert load_settings().observer_model == "openai:gpt-5"


def test_the_observation_bounds_have_the_defaults_the_adr_names() -> None:
    """20 episodes and 5 proposals — named here, not left to the implementation.

    ADR-0074 §9.3's rule applied by ADR-0077 §1: two conforming stages picking 20
    and 2,000 would send categorically different amounts of Tier 1 data to a model
    while each believed it conformed.
    """
    settings = Settings()
    assert settings.observation_batch_size == 20
    assert settings.observation_max_proposals == 5


@pytest.mark.parametrize("value", [0, -1])
def test_a_non_positive_observation_batch_size_is_rejected(value: int) -> None:
    """A zero batch observes nothing while reporting health (ADR-0077 §1)."""
    with pytest.raises(ValidationError):
        Settings(observation_batch_size=value)


def test_an_observation_batch_size_at_the_stores_range_bound_is_rejected() -> None:
    """``2**63`` would load cleanly and make every observation raise (ADR-0077 §1).

    The batch is read through ``ConversationStore.turns``, whose ``limit`` outside
    ``[0, 2**63)`` is a ``ValueError`` by its own contract. A setting the store would
    refuse must fail at load, not at the first observation — which is what
    ``load_settings`` promises for every other value here.
    """
    with pytest.raises(ValidationError):
        Settings(observation_batch_size=2**63)


@pytest.mark.parametrize("value", [0, -1])
def test_a_non_positive_observation_max_proposals_is_rejected(value: int) -> None:
    """A zero proposal bound could never propose anything (ADR-0077 §2)."""
    with pytest.raises(ValidationError):
        Settings(observation_max_proposals=value)


def test_load_settings_rejects_an_invalid_observation_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It fails at load as a ``ConfigurationError``, like every other bad tuning."""
    monkeypatch.setenv("ASSISTANT_OBSERVATION_BATCH_SIZE", "0")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_the_observation_bounds_parse_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both are ordinary integers in the environment, with the ``ASSISTANT_`` prefix."""
    monkeypatch.setenv("ASSISTANT_OBSERVATION_BATCH_SIZE", "4")
    monkeypatch.setenv("ASSISTANT_OBSERVATION_MAX_PROPOSALS", "2")
    settings = load_settings()
    assert settings.observation_batch_size == 4
    assert settings.observation_max_proposals == 2


# --- deferred questions: the lifetime and the cap (ADR-0078 §6, §7) ---------


def test_deferral_ttl_defaults_to_thirty_days() -> None:
    # The value ADR-0078 §6 argues for, and the one no invalid-value test can
    # assert. "Finite" alone admits a one-microsecond default that expires every
    # question before a user can list it and a decades-long one that keeps
    # unanswered Tier 1 content for a working lifetime — both conforming, neither
    # intended. Thirty days is `episode_retention`'s own horizon, deliberately: a
    # deferred question is about a belief, and for an observed one the evidence is
    # episodes on that clock, so a question outliving them would ask the user to
    # adjudicate something the system can no longer explain.
    assert Settings().deferral_ttl == timedelta(days=30)


def test_deferral_ttl_accepts_an_explicit_none_as_ask_me_forever() -> None:
    # `None` is a real value with stated behaviour, not a gap: the question never
    # lapses and its record is never purged (ADR-0078 §6). It is the user's
    # deliberate choice, in the same words `episode_retention` already uses.
    assert Settings(deferral_ttl=None).deferral_ttl is None


def test_deferral_ttl_is_disabled_from_the_environment_by_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default is finite, so omitting the variable can never reach `None` and no
    # duration literal spells it: without the sentinel "ask me forever" would be
    # unreachable from a deployment.
    monkeypatch.setenv("ASSISTANT_DEFERRAL_TTL", "none")
    assert load_settings().deferral_ttl is None


def test_deferral_ttl_parses_an_iso_duration_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_DEFERRAL_TTL", "P7D")
    assert load_settings().deferral_ttl == timedelta(days=7)


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_a_non_positive_deferral_ttl_is_rejected(value: timedelta) -> None:
    # A zero or negative lifetime lapses every question the instant it is admitted:
    # never answerable, immediately purgeable, its content dropped in silence.
    with pytest.raises(ValidationError):
        Settings(deferral_ttl=value)


@pytest.mark.parametrize("value", ["PT0S", "-PT1H"])
def test_load_settings_rejects_a_non_positive_deferral_ttl(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ASSISTANT_DEFERRAL_TTL", value)
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_the_deferral_queue_limit_defaults_to_a_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # It matches `DeferralStore.pending`'s bounded default, so the whole answerable
    # queue fits one page and ADR-0078 §7's "the cap is legible from the first page"
    # is true in the strongest sense.
    monkeypatch.delenv("ASSISTANT_DEFERRAL_QUEUE_LIMIT", raising=False)
    assert Settings().deferral_queue_limit == 50


@pytest.mark.parametrize("value", [0, -1])
def test_a_non_positive_deferral_queue_limit_is_rejected(value: int) -> None:
    # A cap of 0 is at capacity before its first admission, so every `ASK_USER`
    # proposal is refused and the drop ADR-0078 exists to end returns in full, by
    # configuration, while the system reports health. Exactly the class of value
    # ADR-0022 §4a refuses at construction. There is no "unlimited" spelling either:
    # an uncapped queue is what §7 exists to prevent.
    with pytest.raises(ValidationError):
        Settings(deferral_queue_limit=value)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_load_settings_rejects_a_non_positive_deferral_queue_limit(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ASSISTANT_DEFERRAL_QUEUE_LIMIT", value)
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


# --- a flag is not a count: every integer setting refuses a non-integer (#471) ---
#
# Discovered from the model rather than listed, so a new `int` field is covered
# the day it is added instead of the day someone remembers this file. A field
# annotated `int` appears here whether or not it carries `_IntegerSetting` —
# pydantic reports the annotation as `int` either way and files the
# `BeforeValidator` under `metadata` — so an unguarded new field fails these
# tests rather than slipping past them.
_INTEGER_FIELDS: Final = tuple(
    name for name, field in Settings.model_fields.items() if field.annotation is int
)


#: Fields a field-generic case must supply **beside** the one it is exercising,
#: because some settings are only coherent together. ``calendar_reader_interval``
#: and ``calendar_upcoming_interval`` are why: ADR-0093 §7a and ADR-0132 §4 each
#: refuse an interval with no source at load, so a case that set one alone would be
#: exercising that cross-field refusal rather than the per-field guard it means to.
#: ``calendar_upcoming_lead`` joins them for ADR-0132 §4's other refusal — a lead
#: must be strictly greater than the producer's interval, and the shipped
#: thirty-minute default is *below* the one-hour value these cases use, so without a
#: companion every duration case over that interval would refuse.
#:
#: Supplying all three for every case is harmless — each is a valid value in its own
#: right, a case exercising one of them overrides the companion, and no assertion
#: below reads any of them — and it keeps the parametrisation field-agnostic, which
#: is what makes a new setting covered without anyone editing the cases.
_COMPANIONS: Final[dict[str, Any]] = {
    "calendar_reader_path": Path("/srv/calendars/personal.ics"),
    "calendar_upcoming_lead": timedelta(hours=2),
}


def _settings_with(name: str, value: object) -> Settings:
    """Construct ``Settings`` with the one field ``name`` set to ``value``.

    The dynamic keyword is the point of the tests below — they parametrise over
    the *real* field names so a new integer setting is covered without anyone
    editing this file — and it is the one thing mypy cannot check, since it sees
    a single ``**dict`` offered against every field's own type at once. Confining
    the ``Any`` to this helper keeps that gap one line wide.
    """
    kwargs: dict[str, Any] = {**_COMPANIONS, name: value}
    return Settings(**kwargs)


def test_every_integer_setting_is_discovered() -> None:
    """Pin the discovery, so the parametrised tests below cannot pass vacuously.

    A helper that quietly returned nothing would turn every ``parametrize`` over
    it into zero cases and a green run. This is also the tripwire #471 asks for:
    a new integer setting fails here until it is acknowledged, which is the
    moment to give it the alias too.
    """
    assert set(_INTEGER_FIELDS) == {
        "model_max_attempts",
        "working_hours_start",
        "working_hours_end",
        "observation_batch_size",
        "observation_max_proposals",
        "deferral_queue_limit",
        # ADR-0130 §7's cap on actionable held notifications, acknowledged here
        # for `deferral_queue_limit`'s reason and with the same `bool` argument:
        # `notification_queue_limit=True` is a store at capacity after its first
        # admission, which drops every later candidate while the system reports
        # health.
        "notification_queue_limit",
        # ADR-0084 §3's transport figures. Acknowledged here rather than exempted:
        # each is refused at load unless strictly positive, and joining this tuple
        # is what subjects them to the parametrised guards below. The ``bool`` one
        # earns its place twice over — ``hub_max_connections=True`` would be a hub
        # that serves exactly one client at a time while reporting health, and
        # ``hub_max_frame_bytes=True`` a one-byte frame ceiling, which is ADR-0084
        # §3's own worked example of a value that "would pass every startup step in
        # ADR-0083 §3 and then refuse every client, including the CLI".
        "hub_max_frame_bytes",
        "hub_max_connections",
        "hub_max_pending_handshakes",
        # ADR-0131 §5a's three integer figures. Acknowledged here for the reason
        # every hub ceiling is: none of them is nullable, because "a hub serving
        # delivery with no lease, no outbox bound, no budget bound or no connection
        # sub-bound has the failure the clause naming it exists to prevent".
        "hub_notification_outbox_entries",
        "hub_notification_outbox_bytes",
        "hub_max_delivery_connections",
        # ADR-0124 §2's remote listener port. Acknowledged here for the same reason
        # and with the same ``bool`` argument: ``hub_remote_port=True`` would have
        # the hub bind port 1 — privileged, and not the port the owner configured —
        # so an unprivileged run would fail at bind with an errno rather than at
        # load with the value it was given.
        "hub_remote_port",
        # ADR-0124 §1's client-side port, the mirror of the one above and
        # acknowledged for the same reason. ``remote_hub_port=True`` would have a
        # client dial port 1 rather than the port the owner configured, so the two
        # halves of one hop would disagree about where the door is — and the
        # failure would arrive as a connection refused, which is exactly what a
        # hub that is down looks like.
        "remote_hub_port",
        # ADR-0093 §7a's four counting caps. Acknowledged here for the reason the
        # transport figures are: each is refused at load outside its range, and
        # joining this tuple is what subjects it to the guards below. The ``bool``
        # one is not decoration for any of them — ``calendar_max_entries=True`` is
        # a calendar read that proposes exactly one entry while reporting health,
        # which is the shape §5 refuses when it says a bound is enforced by
        # refusing and never by truncating.
        "calendar_max_entries",
        "calendar_max_bytes",
        # ADR-0111 §4's chunk bound. Acknowledged here for the reason every figure
        # above is, and the ``bool`` guard is load-bearing in its own way: the ADR
        # pins the field to "exactly an ``int``" precisely because ``True`` would
        # otherwise load as a chunk size of one, and a walk taking one record per
        # chunk spends a model call per record while reporting health. The range is
        # ``MemoryStore.walk_records``' own, so a configured chunk size is always an
        # admissible limit and the two figures cannot disagree at run time.
        "scheduler_chunk_size",
        "calendar_max_expansion",
        "calendar_max_content_bytes",
    }


@pytest.mark.parametrize("name", _INTEGER_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_every_integer_setting_refuses_a_bool(name: str, value: bool) -> None:
    """``Settings(observation_batch_size=True)`` is a mistake, not a one-item batch.

    Pydantic's non-strict ``int`` coercion accepts ``True`` as ``1`` because
    ``bool`` is an ``int`` subclass, and ``1`` satisfies every bound these fields
    carry — so without this the flag loads as a plausible value and nothing
    downstream can tell. The guards *below* settings already refuse it
    (``_check_batch_size`` in ``orchestration/observation.py``, ``_check_tuning``
    in ``orchestration/loop.py``, ``Engine.__init__``, and ``_check_bound`` in
    ``learning/observer.py``), but ``Settings`` hands them an already-coerced
    integer, so on the settings path they can never fire. This is the
    configuration layer stating the rule the four layers under it already state
    (#471).

    The message is asserted, not just the refusal: ``False`` and ``True`` land on
    ``0`` and ``1``, which some of these fields' range bounds would reject anyway,
    so a test that only asserted "raises" would pass for the wrong reason on those
    fields and prove nothing about the ones where ``1`` is in range.
    """
    with pytest.raises(ValidationError, match="a flag is not a count"):
        _settings_with(name, value)


@pytest.mark.parametrize("name", _INTEGER_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        # A flag that is not a `bool`. `numpy.bool_` is a direct dependency here
        # (ADR-0024's embedder) and is *not* a `bool` subclass, so a guard written
        # as a denylist of `bool` would let it through to the same coerced `1` —
        # the very failure #471 is about, one type name away. This case is why the
        # guard is an allowlist of what an integer setting may be.
        numpy.bool_(True),
        numpy.bool_(False),
        # Numerics that convert without being integers. The layers below already
        # refuse these — `RetryPolicy` checks `type(...) is not int`, and
        # `_check_batch_size` refuses a float rather than comparing it — so
        # accepting them here would leave the same one-layer inconsistency #471
        # exists to end, just on a different axis.
        1.0,
        Decimal(1),
        numpy.int64(1),
    ],
)
def test_every_integer_setting_refuses_a_convertible_non_integer(name: str, value: object) -> None:
    """Only an exact ``int`` or a ``str`` is an integer setting; nothing else is coerced.

    The companion to the ``bool`` case above, and the reason the guard names what
    it accepts rather than what it refuses: ``bool`` is not the only type pydantic
    would turn into a plausible ``1``, so a denylist would have to grow a case for
    every foreign scalar and would be wrong until it did.
    """
    with pytest.raises(ValidationError, match="expected an integer"):
        _settings_with(name, value)


def test_a_value_that_cannot_describe_itself_is_still_a_validation_error() -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    The refusal above builds its message from the offered value, and this branch
    is reached by *arbitrary* objects. A ``__repr__`` that raises would replace
    the ``ValueError`` pydantic converts into a ``ValidationError`` with whatever
    it threw — escaping the seam ``load_settings`` promises to report as a
    ``ConfigurationError``. Pydantic renders such an input as
    ``<unprintable ... object>`` unaided, so the guard must not be the one link in
    the chain that cannot survive being told about it. ``describe_untrusted``
    (``core.types``) is the shared helper written for exactly this, and this is
    the test that it is actually used.

    One field, not all six: the message is built once in a field-independent
    helper, and the parametrised cases above already prove every field reaches it.
    """

    class Unprintable:
        def __repr__(self) -> str:
            msg = "this value refuses to describe itself"
            raise RuntimeError(msg)

    with pytest.raises(ValidationError, match="expected an integer"):
        _settings_with("observation_batch_size", Unprintable())


@pytest.mark.parametrize("name", _INTEGER_FIELDS)
def test_every_integer_setting_still_accepts_its_own_default(name: str) -> None:
    """The refusal narrows nothing legitimate: a real integer is still a real integer."""
    default = Settings.model_fields[name].default
    assert type(default) is int
    assert getattr(_settings_with(name, default), name) == default


@pytest.mark.parametrize("name", _INTEGER_FIELDS)
def test_every_integer_setting_still_parses_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The operator-facing path is untouched, and this is what keeps it so.

    #471 is reachable only from untyped code constructing ``Settings`` directly —
    ``ASSISTANT_OBSERVATION_BATCH_SIZE=True`` already fails int parsing at load.
    So the guard accepts a ``str`` alongside an exact ``int``: an environment
    variable and a ``.env`` entry both arrive as one, and a guard that demanded an
    exact ``int`` and nothing else would break *every* integer setting in every
    deployment while fixing a seam no deployment can reach.
    """
    default = Settings.model_fields[name].default
    monkeypatch.setenv(f"ASSISTANT_{name.upper()}", str(default))
    assert getattr(load_settings(), name) == default


# --- a flag is not a measurement or a duration: the float and timedelta half (#500) ---
#
# The sibling of the integer block above, split from it in #471/#499 because a
# duration is not a count and needed its own reasoning. Discovered from the model
# for the same reason, and through a helper rather than `field.annotation is ...`
# because three of the four duration settings are nullable, so their annotation is
# `timedelta | None` rather than `timedelta`.


def _admitted_types(annotation: object) -> frozenset[object]:
    """The non-``None`` types a field's annotation admits.

    ``float`` for a real-valued setting; ``timedelta`` for a duration whether or
    not it spells ``None``. A field carrying a ``BeforeValidator`` reports the same
    annotation as one without — pydantic files the validator under ``metadata`` —
    so an unguarded new field is discovered here and fails the tests below rather
    than slipping past them.
    """
    args = get_args(annotation)
    if not args:
        return frozenset({annotation})
    return frozenset(args) - {type(None)}


_REAL_FIELDS: Final = tuple(
    name
    for name, field in Settings.model_fields.items()
    if _admitted_types(field.annotation) == frozenset({float})
)

_DURATION_FIELDS: Final = tuple(
    name
    for name, field in Settings.model_fields.items()
    if _admitted_types(field.annotation) == frozenset({timedelta})
)

#: Values that are neither a real number nor a duration but that pydantic's lax
#: mode coerces into a plausible one anyway. ``numpy.bool_`` is the case the
#: allowlist exists for: a flag that is not a ``bool`` subclass — so a denylist
#: named after ``bool`` would miss it — from a direct dependency (ADR-0024's
#: embedder). The rest are numerics that convert without being the type asked for.
_CONVERTIBLE_NON_NUMBERS: Final = (
    numpy.bool_(True),
    numpy.bool_(False),
    Decimal(1),
    numpy.int64(1),
)


def test_every_real_setting_is_discovered() -> None:
    """Pin the discovery, so the parametrised tests below cannot pass vacuously.

    A helper that quietly returned nothing would turn every ``parametrize`` over
    it into zero cases and a green run. It is also the tripwire: a new ``float``
    setting fails here until it is acknowledged, which is the moment to give it
    ``_RealSetting`` too.
    """
    assert set(_REAL_FIELDS) == {
        "model_timeout_seconds",
        "model_backoff_base_seconds",
        "model_backoff_max_seconds",
        # ADR-0118 §4's embedding deadline. Acknowledged here rather than
        # exempted: §4 requires it to be refused at load unless it is exactly a
        # real number that is finite and strictly positive, and joining this tuple
        # is what subjects it to the parametrised guards below. For this field the
        # ``bool`` guard is the difference between "thirty seconds" and "one
        # second" — and one second fails every cold ONNX load, turning the whole
        # seam into a deadline that never clears.
        "embedding_timeout_seconds",
    }


def test_every_duration_setting_is_discovered() -> None:
    """The same tripwire for the durations, nullable and not alike."""
    assert set(_DURATION_FIELDS) == {
        "confirmation_ttl",
        # ADR-0131 §5a's two durations, on the same argument as its integers.
        "hub_notification_lease",
        "hub_max_notification_budget",
        "episode_retention",
        "conversation_tombstone_grace",
        "deferral_ttl",
        # ADR-0083 §4's phase-A budget. Acknowledged here rather than exempted:
        # §7 requires *every* duration the hub adds to be refused at load unless
        # finite and strictly positive, and joining this tuple is what subjects
        # it to the parametrised guards below — including the ``bool`` one, which
        # for this field is the difference between "wait thirty seconds" and
        # "delete phase A".
        "shutdown_drain_seconds",
        # ADR-0083 §7's three scheduler intervals, acknowledged here for the same
        # reason ``shutdown_drain_seconds`` is: §7 requires *every* duration the hub
        # adds to be refused at load unless finite and strictly positive, and
        # joining this tuple is what subjects each to the parametrised guards below.
        # For an interval the ``bool`` guard is the difference between "sweep every
        # hour" and "sweep every second"; the positive bound is the difference
        # between an interval and a hot loop, because the loop re-arms a job from
        # its *completion* and a zero interval makes it due again the instant it
        # finishes.
        "retention_purge_interval",
        "conversation_sweep_interval",
        "observation_interval",
        # ADR-0130 §5's reconsideration interval, a fourth row on ADR-0083 §7's
        # table and subject to its convention unchanged — finite and strictly
        # positive, or `None` for disabled and never `0`. It is the one job on
        # that table whose latency is user-visible, which is why its default is
        # minutes rather than hours and why a `bool` here is the difference
        # between "re-rule every five minutes" and "re-rule every second".
        "notification_reconsider_interval",
        # ADR-0130 §7's retention for a held notification, on `deferral_ttl`'s
        # convention: finite by default, with `None` the user's deliberate "keep
        # them" and the one escape the cap axis does not offer.
        "notification_retention",
        # ADR-0111 §4's run budget. It does **not** follow §7's nullable convention,
        # for ``hub_read_timeout``'s reason one clause on: a chunked run with no
        # budget is the unbounded walk ADR-0083 §7 accepted the absence of a bound
        # on, so "off" is not an available value here either.
        "scheduler_run_budget",
        # ADR-0084 §3's read deadline. It is **not** nullable, and that is the one
        # place ADR-0084 departs from ADR-0083 §7's convention: "a hub with no frame
        # cap or no read deadline has exactly the failure §3 exists to prevent, so
        # 'off' is not an available value".
        "hub_read_timeout",
        # ADR-0093 §7a's four durations. The interval follows ADR-0083 §7's
        # convention exactly — disabled is ``None``, never ``0`` — and the two
        # window arms are the only durations in the model bounded *above*, because
        # ``> 0`` alone admits ``timedelta.max``, for which
        # ``read_at + calendar_window_future`` is not a representable instant.
        # ``calendar_reader_interval`` is also the one field with a cross-field
        # precondition; see :data:`_COMPANIONS`.
        "calendar_reader_interval",
        "calendar_window_past",
        "calendar_window_future",
        "calendar_read_timeout",
        # ADR-0132 §4's two, for the producer reading the same source on its own
        # cadence. The interval follows ADR-0083 §7's convention — disabled is
        # ``None``, never ``0`` — and the lead is bounded above for
        # ``calendar_window_future``'s reason exactly. Both carry cross-field
        # preconditions, which is why the lead joins :data:`_COMPANIONS`; the
        # parametrised guards below still hold each one's own range.
        "calendar_upcoming_interval",
        "calendar_upcoming_lead",
        # ADR-0119 §10's trace horizon. Acknowledged here rather than exempted,
        # for the reason every duration above is: joining this tuple is what
        # subjects it to the parametrised guards below. It follows
        # ``episode_retention``'s convention exactly — finite by default, ``None``
        # reachable only through the disable sentinel and meaning "keep forever" —
        # and the positive bound matters here in the direction a retention setting
        # fails worst: a zero or negative horizon sweeps *every* trace at the first
        # purge, which is the instrument switched off by misconfiguration rather
        # than by a decision.
        "trace_retention",
    }


@pytest.mark.parametrize("name", _REAL_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_every_real_setting_refuses_a_bool(name: str, value: bool) -> None:
    """``Settings(model_timeout_seconds=True)`` is a mistake, not a one-second deadline.

    ``bool`` is an ``int`` subclass and an integer converts to a float, so lax mode
    reads ``True`` as ``1.0`` — which clears ``gt=0`` and ``allow_inf_nan=False``
    alike, so the flag loads as a plausible deadline and nothing downstream can
    tell. ``RetryPolicy.__post_init__`` already refuses it for exactly these three
    knobs ("a boolean timeout is a mistake worth naming rather than coercing to
    1.0"), but is handed an already-coerced float by ``RetryPolicy.from_settings``,
    so on the settings path that exclusion can never fire (#500).

    The message is asserted rather than the bare refusal, for the reason the
    integer block gives: ``False`` lands on ``0.0``, which ``gt=0`` would reject
    anyway, so a test that only asserted "raises" would pass for the wrong reason
    on half its cases and prove nothing about ``True``.
    """
    with pytest.raises(ValidationError, match="a flag is not a measurement"):
        _settings_with(name, value)


@pytest.mark.parametrize("name", _DURATION_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_every_duration_setting_refuses_a_bool(name: str, value: bool) -> None:
    """``Settings(conversation_tombstone_grace=True)`` is a mistake, not one second.

    Lax mode reads a bare number as *seconds*, and ``True`` is a number by
    inheritance, so the flag arrives as a one-second horizon — past the
    ``gt=timedelta(0)`` every one of these fields carries, exactly as ``1``
    cleared every integer bound in #471.

    The message is asserted for the same reason as above: ``False`` becomes
    ``timedelta(0)``, which the positive bound rejects on its own.
    """
    with pytest.raises(ValidationError, match="a flag is not a duration"):
        _settings_with(name, value)


@pytest.mark.parametrize("name", _REAL_FIELDS)
@pytest.mark.parametrize("value", _CONVERTIBLE_NON_NUMBERS)
def test_every_real_setting_refuses_a_convertible_non_number(name: str, value: object) -> None:
    """Only a float, an exact int, or a str is a real-valued setting.

    The companion to the ``bool`` case, and the reason the guard names what it
    accepts rather than what it refuses: ``bool`` is not the only type pydantic
    would turn into a plausible ``1.0``, so a denylist would have to grow a case
    for every foreign scalar and would be wrong until it did.
    """
    with pytest.raises(ValidationError, match="expected a real number"):
        _settings_with(name, value)


@pytest.mark.parametrize("name", _DURATION_FIELDS)
@pytest.mark.parametrize("value", _CONVERTIBLE_NON_NUMBERS)
def test_every_duration_setting_refuses_a_convertible_non_duration(
    name: str, value: object
) -> None:
    """The same allowlist on the duration axis: ``numpy.bool_`` also reads as one second."""
    with pytest.raises(ValidationError, match="expected a duration"):
        _settings_with(name, value)


@pytest.mark.parametrize("name", _REAL_FIELDS)
@pytest.mark.parametrize(("value", "expected"), [(2.5, 2.5), (2, 2.0), ("2.5", 2.5)])
def test_every_real_setting_still_accepts_the_forms_it_is_written_in(
    name: str, value: object, expected: float
) -> None:
    """The refusal narrows nothing legitimate.

    A ``float`` is the obvious one; an **exact** ``int`` is accepted because a whole
    number of seconds is how a caller writes one and ``RetryPolicy`` accepts one
    itself (``isinstance(value, (int, float))``) — refusing it would make
    configuration stricter than the layer it configures; a ``str`` is what the
    environment supplies. ``2.5`` and ``2`` are inside every one of these fields'
    bounds *and* inside the backoff window the model validator cross-checks, so a
    refusal here would be about the guard rather than about the value.
    """
    assert getattr(_settings_with(name, value), name) == expected


@pytest.mark.parametrize("name", _DURATION_FIELDS)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (timedelta(hours=1), timedelta(hours=1)),
        # A bare number of seconds: a form pydantic has always accepted from a
        # direct caller, kept working deliberately. The guard refuses the *flag*
        # by requiring an exact `int`/`float`, not by refusing numbers — a
        # refusal of "anything that is not a timedelta" would have closed one
        # defect by breaking two legitimate inputs (#500). The value each number
        # lands on is asserted, not merely that it is accepted: seconds is
        # pydantic's reading of a bare number, and it is the reading this keeps.
        (3600, timedelta(hours=1)),
        (3600.5, timedelta(seconds=3600, microseconds=500_000)),
        # The operator's own spellings, ISO-8601 and `HH:MM:SS`.
        ("PT1H", timedelta(hours=1)),
        ("01:00:00", timedelta(hours=1)),
    ],
)
def test_every_duration_setting_still_accepts_the_forms_it_is_written_in(
    name: str, value: object, expected: timedelta
) -> None:
    """A duration setting still takes a timedelta, a number of seconds, or a string."""
    assert getattr(_settings_with(name, value), name) == expected


@pytest.mark.parametrize("name", _REAL_FIELDS)
def test_every_real_setting_still_parses_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The operator-facing path is untouched, and this is what keeps it so.

    #500 is reachable only from untyped code constructing ``Settings`` directly —
    ``ASSISTANT_MODEL_TIMEOUT_SECONDS=True`` already fails float parsing at load.
    So the guard accepts a ``str``: an environment variable and a ``.env`` entry
    both arrive as one, and a guard that demanded a ``float`` and nothing else
    would break every real-valued setting in every deployment while fixing a seam
    no deployment can reach.
    """
    default = Settings.model_fields[name].default
    assert type(default) is float
    monkeypatch.setenv(f"ASSISTANT_{name.upper()}", str(default))
    assert getattr(load_settings(), name) == default


@pytest.mark.parametrize("name", _DURATION_FIELDS)
def test_every_duration_setting_still_parses_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The same for the durations, spelled as ISO-8601 the way each field documents.

    Not the field's own default, which is ``None`` for ``confirmation_ttl`` and has
    no environment spelling other than the sentinel: one literal that every one of
    the four accepts proves the string path just as well.
    """
    for companion, value in _COMPANIONS.items():
        monkeypatch.setenv(f"ASSISTANT_{companion.upper()}", str(value))
    monkeypatch.setenv(f"ASSISTANT_{name.upper()}", "PT1H")
    assert getattr(load_settings(), name) == timedelta(hours=1)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("model_timeout_seconds", "expected a real number"),
        ("confirmation_ttl", "expected a duration"),
    ],
)
def test_an_undescribable_value_is_still_a_validation_error(name: str, expected: str) -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    The integer guard learned this the hard way (#499, round 2): a refusal that
    builds its message with ``{value!r}`` is reached by *arbitrary* objects, and a
    ``__repr__`` that raises replaces the ``ValueError`` pydantic converts into a
    ``ValidationError`` with whatever it threw — escaping the seam
    ``load_settings`` promises to report as a ``ConfigurationError``. Both new
    guards use ``describe_untrusted`` (``core.types``) for the same reason, and
    this is the test that they actually do.

    One field per guard, not all seven: the message is built once in a
    field-independent helper, and the parametrised cases above already prove every
    field reaches it.
    """

    class Unprintable:
        def __repr__(self) -> str:
            msg = "this value refuses to describe itself"
            raise RuntimeError(msg)

    with pytest.raises(ValidationError, match=expected):
        _settings_with(name, Unprintable())


@pytest.mark.parametrize("name", _DURATION_FIELDS)
def test_every_duration_setting_refuses_a_timedelta_that_lies_about_its_length(
    name: str,
) -> None:
    """The exact-``timedelta`` check is load-bearing, and this is what makes it so.

    Without this case the guard could be relaxed to ``isinstance(value, timedelta)``
    and the rest of the suite would stay green, because nothing else offers a
    subclass — so the one difference between the duration guard and the real-number
    one would be untested (raised as a ``major`` by the adversarial review).

    What the exactness buys, in the two steps the assertions below pin. pydantic
    **preserves** a ``timedelta`` subclass instance in the model rather than
    normalising it the way it normalises a ``float`` subclass, and it applies
    ``gt=timedelta(0)`` natively, so a subclass whose comparison operators disagree
    with its own length clears the load-time bound intact. It is then handed to the
    subsystems that compare *against* it, where the value sits on the right of the
    comparison and Python's reflected-operand priority gives the subclass the
    decision — ``ConversationStore``'s reclaim sweep,
    ``now - conversation.deleted_at >= self._grace``, is the case pinned below: a
    week-old tombstone reads as ineligible forever, dropping ADR-0074 §8's
    guarantee with every stated setting still looking correct. The same defence,
    for the same reason, as :func:`_split_model_specs`' exact ``list``.
    """

    class Deceitful(timedelta):
        """An hour-long duration that denies being shorter than anything."""

        def __le__(self, other: object) -> bool:
            return False

        def __repr__(self) -> str:
            return "Deceitful(1h)"

    grace = Deceitful(hours=1)
    # The premise, pinned rather than described. The first pair is the sweep's own
    # comparison, `ConversationStore._reclaim`'s `now - deleted_at >= self._grace`,
    # answered by the subclass instead of by its length. The second is the store's
    # constructor guard, which cannot catch it either: `isinstance` admits the
    # subclass and the `<=` it then evaluates is the subclass's own. If Python's
    # reflected-operand rule ever stopped working this way, these are where it
    # would be noticed rather than in a silently weakened guard.
    assert (timedelta(days=7) >= grace) is False
    assert (timedelta(days=7) >= timedelta(hours=1)) is True
    assert isinstance(Deceitful(hours=-1), timedelta)
    assert (Deceitful(hours=-1) <= timedelta(0)) is False

    with pytest.raises(ValidationError, match="expected a duration"):
        _settings_with(name, grace)


@pytest.mark.parametrize("name", _REAL_FIELDS)
def test_every_real_setting_accepts_a_float_subclass_and_stores_a_plain_float(
    name: str,
) -> None:
    """The other side of that asymmetry, pinned so it is a decision rather than a slip.

    The real-number guard admits a ``float`` by ``isinstance`` where the duration
    guard demands the built-in, and this is why that is safe: pydantic
    **normalises** a ``float`` subclass to a built-in ``float`` before storing it,
    so no subclass survives into the model to intercept a later comparison — the
    exact hazard the duration case above exists for. ``numpy.float64`` is the
    subclass this codebase can actually produce (ADR-0024's embedder), and it means
    precisely its own value, so refusing it would buy nothing.
    """
    stored = getattr(_settings_with(name, numpy.float64(2.5)), name)
    assert stored == 2.5
    assert type(stored) is float


# --- the local API's transport (ADR-0084 §3, ADR-0085 §8d) ------------------


def test_the_transport_settings_carry_the_ratified_defaults() -> None:
    """ADR-0084 §3 names all four rather than leaving them to the implementation.

    Following ADR-0083 §7, "which named every scheduler interval for ADR-0074 §9.3's
    reason: 'a "bounded default" with no figure is two conforming stores handing the
    same continuation different history.' The same applies with more force to a
    limit whose whole job is to refuse."
    """
    settings = Settings()
    assert settings.hub_max_frame_bytes == 16 * 1024 * 1024
    assert settings.hub_read_timeout == timedelta(seconds=30)
    assert settings.hub_max_connections == 64
    assert settings.hub_max_pending_handshakes == 8


@pytest.mark.parametrize("value", [0, 1023])
def test_a_frame_size_below_the_floor_is_refused(value: int) -> None:
    """ADR-0085 §8d: 512 for the envelope reserve plus 256 for either connect
    payload is 768, and 1024 leaves room for both handshake frames and a small
    request besides.

    "A value below the floor yields a hub that passes every ADR-0083 §3 startup step
    and then refuses every client including the CLI — indistinguishable from a hub
    that is down, which is ADR-0084's ruling 4 failure produced by a config typo,
    and load time is where it should surface."
    """
    with pytest.raises(ValidationError):
        Settings(hub_max_frame_bytes=value)


def test_a_frame_size_the_prefix_cannot_express_is_refused() -> None:
    """ADR-0084 §3's upper bound: "representable by the framing".

    "Without this, a setting of 5 GiB would be accepted at load and would be a limit
    the contract declares (§4) but the wire cannot encode, so the in-process engine
    would accept a value the client provably cannot send — the very divergence §4
    moved the limit into the contract to prevent."
    """
    with pytest.raises(ValidationError):
        Settings(hub_max_frame_bytes=5 * 1024**3)
    # The outbox bound travels with the frame ceiling, ADR-0131 §5a refusing it
    # below one frame — an outbox that could hold no entry a device could receive
    # would evict every notification the instant it arrived.
    widest = Settings(hub_max_frame_bytes=2**32 - 1, hub_notification_outbox_bytes=2**32 - 1)
    assert widest.hub_max_frame_bytes == 2**32 - 1


def test_the_floor_and_the_ceiling_admit_what_they_must() -> None:
    """The discriminating half of the two bounds above."""
    assert Settings(hub_max_frame_bytes=1024).hub_max_frame_bytes == 1024


@pytest.mark.parametrize("value", [0, -1])
def test_a_non_positive_connection_ceiling_is_refused(value: int) -> None:
    """ADR-0084 §3: "'off' is not an available value and a zero is a
    misconfiguration rather than a way to express it".

    "A ``hub_max_connections`` of 0 would refuse every client, including the CLI, and
    would look from outside exactly like a hub that is down."
    """
    with pytest.raises(ValidationError):
        Settings(hub_max_connections=value)


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_a_non_positive_read_timeout_is_refused(value: timedelta) -> None:
    """The deadline is not nullable and not zero: a hub with no read deadline "has
    exactly the failure §3 exists to prevent"."""
    with pytest.raises(ValidationError):
        Settings(hub_read_timeout=value)


def test_a_pending_ceiling_above_the_total_is_refused() -> None:
    """ADR-0084 §3: "a pending ceiling above the total is a limit that can never bind".

    A limit that cannot bind is not a weaker limit but an absent one, and an operator
    who set it believes they hold a defence against the cheapest state a misbehaving
    peer can accumulate.
    """
    with pytest.raises(ValidationError, match="can never bind"):
        Settings(
            hub_max_connections=4, hub_max_pending_handshakes=5, hub_max_delivery_connections=2
        )
    # The delivery sub-bound travels with them: ADR-0131 §5a refuses it unless it
    # is *strictly* below `hub_max_connections`, so a ceiling of 4 cannot keep the
    # shipped 8 — the same relation this case is about, one clause along.
    coherent = Settings(
        hub_max_connections=4, hub_max_pending_handshakes=4, hub_max_delivery_connections=3
    )
    assert coherent.hub_max_connections == 4


def test_load_settings_reports_a_bad_transport_setting_as_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment fault surfaces at load, as every other setting's does."""
    monkeypatch.setenv("ASSISTANT_HUB_MAX_FRAME_BYTES", "10")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


# --- ADR-0124 §2: where the remote listener may bind, decided at load ---------


def test_the_remote_listener_is_off_unless_it_is_configured_on() -> None:
    """ADR-0124 §2: "the remote listener is off unless it is configured on. A hub
    with no remote-listener configuration binds only ADR-0084 §1's loopback socket."

    The address **is** the switch: there is no separate boolean, because two
    settings that can disagree about whether a listener exists is one more state than
    the hub has.
    """
    assert Settings().hub_remote_address is None


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("0.0.0.0", "wildcard"),  # noqa: S104 — the value being refused is the point
        ("::", "wildcard"),
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("169.254.7.7", "link-local"),
        ("224.0.0.1", "multicast"),
        ("8.8.8.8", "public internet"),
        ("2606:4700:4700::1111", "public internet"),
    ],
)
def test_an_address_adr_0124_forbids_is_refused_at_load(value: str, reason: str) -> None:
    """ADR-0124 §2: "it may not bind a wildcard address, an address of a physical
    interface, or any address reachable from the public internet, and a
    configuration that would have it do so is refused at load time rather than
    bound".

    The wildcard case is the one that matters most and the one an operator reaches
    for first: it "would put the hub on every interface this machine has", which is
    precisely the door §2 refuses to open. Each refusal names its own reason, because
    an operator who is told only "invalid" has to guess which of five rules they met.
    """
    with pytest.raises(ValidationError, match=reason):
        Settings(hub_remote_address=value)


@pytest.mark.parametrize("value", ["hub.example.ts.net", "localhost", "", "100.64.0"])
def test_an_address_that_is_not_an_ip_address_is_refused(value: str) -> None:
    """A name is refused rather than resolved.

    "Resolving one is a lookup whose answer another party supplies, and the address a
    listener binds would then be a fact about a resolver rather than about this
    deployment" — which is ADR-0124 §1's rule that a destination never comes "from a
    discovery mechanism", applied at the other end of the hop.
    """
    with pytest.raises(ValidationError, match="not an IP address"):
        Settings(hub_remote_address=value)


@pytest.mark.parametrize("value", ["100.64.0.9", "fd7a:115c:a1e0::42", "10.1.2.3"])
def test_an_overlay_address_is_admitted(value: str) -> None:
    """The discriminating half: a validator that refused everything would pass above.

    The two overlay ranges an operator will actually meet are here — Tailscale's
    CGNAT range and its IPv6 ULA prefix, which ADR-0124 §2 accepts "as the first
    implementation" — beside a private LAN address, which passes *this* check on
    purpose. Nothing decidable from the string tells a LAN address from an overlay
    one, so §2's physical-interface clause is closed before the bind instead, by the
    overlay agent (``tests/service/test_remote_listener.py``).
    """
    assert Settings(hub_remote_address=value).hub_remote_address == value


def test_the_address_is_trimmed_rather_than_refused_for_surrounding_space() -> None:
    """An environment variable that picked up a trailing newline is a deployment that
    works, not one that fails at load with a message about a value that looks
    correct."""
    assert Settings(hub_remote_address="  100.64.0.9\n").hub_remote_address == "100.64.0.9"


@pytest.mark.parametrize("value", [0, 65536, -1])
def test_a_port_outside_its_range_is_refused(value: int) -> None:
    """A port is not nullable and not zero: zero would bind whatever the kernel
    offered, so the hub would listen somewhere no client was told about."""
    with pytest.raises(ValidationError):
        Settings(hub_remote_address="100.64.0.9", hub_remote_port=value)


# --- reaching a hub on another machine (ADR-0124 §1) ------------------------


def test_a_client_reaches_the_hub_on_this_machine_by_default() -> None:
    """The address is the switch, and its default is "the hub on this machine".

    ADR-0124 §2 gave the hub's own listener the same shape, and for the same reason:
    there is no separate boolean, because "two settings that can disagree about
    whether a listener exists is one more state than the hub has".
    """
    assert Settings().remote_hub_address is None


def test_the_two_ports_default_to_the_same_figure() -> None:
    """The two halves of one hop, so an owner who sets neither still has a hop.

    A default the client and the hub disagreed about would make the ordinary case
    fail with a connection refused — which looks exactly like a hub that is down.
    """
    assert Settings().remote_hub_port == Settings().hub_remote_port


def test_the_client_address_is_held_as_written() -> None:
    """Validated where the destination is composed, not here.

    The refusals are ``wire.address.check_remote_address``'s, and they belong there
    for two reasons: a ``Settings`` validator would make every command on the *hub's*
    machine — where this is unset and irrelevant — answer for a value only a client
    reads, and it would put a ``wire`` rule in ``core``, where ``wire`` cannot be
    named.
    """
    assert Settings(remote_hub_address="100.64.1.7").remote_hub_address == "100.64.1.7"


def test_no_setting_can_supply_or_override_the_enrolled_hub_identity() -> None:
    """ADR-0124 §4's third clause, as an absence — which is its whole content.

    > The enrolled hub identity is held beside the credential, in the same Tier 0
    > place and by the same mechanism (§6), and it is **not an ordinary
    > configuration value**… **no configuration setting may override that
    > identity**.

    It is what stops §4's second clause from being circular: an edit that redirects
    the client changes the destination and leaves the check that destination has to
    pass exactly where it was. A field here would hand an attacker with an editor
    both halves at once, which is the attack §4 exists to close.
    """
    assert not [name for name in Settings.model_fields if "identity" in name]


def test_the_overlay_agent_socket_is_unset_and_means_the_packaged_paths() -> None:
    """#918: the agent's *location* is configurable; its answer is still the agent's.

    Unset is the ordinary deployment, where ``service.overlay.TAILSCALE_SOCKETS``
    is looked at exactly as before — which is what makes the field additive rather
    than a change to how any existing hub finds its agent.
    """
    assert Settings().hub_overlay_agent_socket is None


def test_the_overlay_agent_socket_is_a_location_and_never_an_identity() -> None:
    """ADR-0124 §4's third clause governs the *enrolled hub identity*, not where the
    agent listens, and the distinction is the whole reason this field is permitted.

    So the field that clause forbids stays absent while this one exists: there is
    no setting that says who the hub or its peer *is*, only one that says where to
    ask. Asserted rather than left to the comment beside it, because an added
    identity field would be exactly the regression the clause is about.
    """
    fields = set(Settings.model_fields)

    assert "hub_overlay_agent_socket" in fields
    assert not {name for name in fields if "identity" in name}


def test_the_client_overlay_agent_socket_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#937, and the defect the review of #941 named: a field, not a bare env var.

    ``Settings`` is configured ``extra="ignore"``, so a name the model does not
    declare is dropped in silence rather than refused — an operator who set
    ``ASSISTANT_CLIENT_OVERLAY_AGENT_SOCKET`` against a build without this field
    would get the packaged defaults and no indication that their setting had been
    discarded. Declaring it is what makes the value reachable at all, so it is
    asserted through the environment rather than through the constructor.
    """
    monkeypatch.setenv("ASSISTANT_CLIENT_OVERLAY_AGENT_SOCKET", "/run/qa/tailscaled.sock")

    assert load_settings().client_overlay_agent_socket == "/run/qa/tailscaled.sock"


def test_the_client_overlay_agent_socket_is_unset_and_means_the_packaged_paths() -> None:
    """Unset is the ordinary deployment, and the field is additive because of it.

    The two paths ``wire.overlay.TAILSCALE_SOCKETS`` names are looked at exactly as
    before, so no existing client changes how it finds its agent.
    """
    assert Settings().client_overlay_agent_socket is None


def test_the_two_ends_of_the_hop_configure_their_agents_separately() -> None:
    """ADR-0124 §4 puts an agent on *each* machine, so one field cannot serve both.

    On a single machine the two would name the same socket and a shared field would
    be the obvious economy. On two devices they are two daemons on two hosts, and a
    shared field would make the hub operator's path govern a client that runs no
    hub — which is the deployment ADR-0124 exists for.
    """
    fields = set(Settings.model_fields)

    assert {"hub_overlay_agent_socket", "client_overlay_agent_socket"} <= fields


def test_neither_agent_setting_is_an_identity() -> None:
    """ADR-0124 §4's third clause survives the client field as it did the hub's.

    "No configuration setting may override that identity." Both fields say where to
    *ask*; the answer is still the agent's, and the enrolled identity a client
    compares it against stays in the keyring. Re-asserted here rather than trusted
    to the hub's copy of this test, because this change is the one that adds a
    second overlay setting and so is the one that could have added a third.
    """
    fields = set(Settings.model_fields)

    assert "client_overlay_agent_socket" in fields
    assert not {name for name in fields if "identity" in name}


class TestTheOutboxByteDefaultIsARule:
    """ADR-0134 §1: the greater of 1 MiB and the *configured* frame ceiling."""

    def test_the_shipped_deployment_gets_the_frame_ceiling(self) -> None:
        """The unconfigured hub, which ADR-0131 §5a's own two figures refused.

        §5a gave this field a default of 1 MiB and a range of
        ``>= hub_max_frame_bytes``, and ADR-0084 §3 ships a 16 MiB ceiling — so a
        hub with no configuration at all could not load. ADR-0134 replaces the
        Default column with a rule the range always satisfies.
        """
        assert Settings().hub_notification_outbox_bytes == 16 * 1024 * 1024

    def test_a_lowered_ceiling_gets_the_1_mib_floor(self) -> None:
        """§1's floor half, and the case a *static* default would get wrong.

        This is the whole reason §1 is a rule over the configured value rather than
        a figure: a default computed from ADR-0084 §3's *named* 16 MiB agrees with
        §1 on an unmodified deployment and diverges the moment an operator lowers
        the ceiling — 16 MiB where the rule says 1 MiB, looser than ratified.
        """
        settings = Settings(hub_max_frame_bytes=512 * 1024)

        assert settings.hub_notification_outbox_bytes == 1024 * 1024

    def test_a_raised_ceiling_carries_the_default_up_with_it(self) -> None:
        """§1's other half: above 1 MiB the ceiling is the greater of the two."""
        settings = Settings(hub_max_frame_bytes=32 * 1024 * 1024)

        assert settings.hub_notification_outbox_bytes == 32 * 1024 * 1024

    def test_the_resolved_default_always_satisfies_the_range(self) -> None:
        """§1: "the range for this field is unchanged and is what this default
        satisfies"."""
        for ceiling in (1024, 512 * 1024, 1024 * 1024, 4 * 1024 * 1024, 2**31):
            settings = Settings(hub_max_frame_bytes=ceiling)

            assert settings.hub_notification_outbox_bytes >= settings.hub_max_frame_bytes

    def test_a_configured_value_is_still_refused_below_the_ceiling(self) -> None:
        """§1: refused "whether it came from an operator or from this default"."""
        with pytest.raises(ValidationError, match="ADR-0134 §1"):
            Settings(hub_max_frame_bytes=4 * 1024 * 1024, hub_notification_outbox_bytes=1024 * 1024)

    def test_a_configured_value_is_never_overwritten_by_the_rule(self) -> None:
        """The rule fills an *absent* value and decides nothing an operator set."""
        settings = Settings(
            hub_max_frame_bytes=1024 * 1024, hub_notification_outbox_bytes=8 * 1024 * 1024
        )

        assert settings.hub_notification_outbox_bytes == 8 * 1024 * 1024

    def test_the_field_stays_a_non_nullable_integer(self) -> None:
        """ADR-0134 §2: no sentinel reaches the settings surface.

        "A nullable field, or an out-of-range marker like ``0`` or ``-1`` — would
        each put a value in the settings surface that §5a ruled out." Absence is
        distinguished before validation, so the public field never holds one.
        """
        with pytest.raises(ValidationError):
            Settings(hub_notification_outbox_bytes=None)  # type: ignore[arg-type]  # the refusal is the subject

    def test_an_unparseable_ceiling_is_left_to_the_field_validators(self) -> None:
        """A fault is reported where it happened, not buried under a guess."""
        with pytest.raises(ValidationError, match="hub_max_frame_bytes"):
            Settings(hub_max_frame_bytes="not-a-number")  # type: ignore[arg-type]  # the refusal is the subject


class TestTheUpcomingEventProducerSFigures:
    """ADR-0132 §4's two fields and its three load-time refusals.

    **Every refusal here exists because the misconfiguration is silent**, and §4
    says so in terms: with ticks at ``t``, ``t+I``, … and a lead ``L``, an
    occurrence is noticed only if some tick sees it inside ``(tick, tick+L)``, so a
    lead no longer than the interval leaves occurrences that no tick ever sees —
    while the job runs, logs nothing and reports health. A hub that starts and
    notices nothing is indistinguishable from a hub that starts and has nothing to
    notice, which is the state ADR-0022 §4a keeps refusing.
    """

    _SOURCE: Final = Path("/srv/calendars/personal.ics")

    def test_the_producer_ships_disabled(self) -> None:
        """§4: "The interval defaults to ``None``. The producer does not run until
        an operator sets it."

        ADR-0093 §7's rule for the same source unchanged — "nothing may read a
        user's personal files because a default said so" — and naming the reason is
        what stops the default flipping the day the technical obstacle clears.
        """
        assert Settings().calendar_upcoming_interval is None

    def test_the_lead_window_defaults_to_thirty_minutes(self) -> None:
        """§4 names the figure rather than leaving it to the implementing lane.

        ADR-0093 §5's rule that a figure a decision invokes cannot be satisfied
        elsewhere, and ADR-0074 §9.3's reason: two conforming implementations with
        different figures notice different things while each believes it conforms.
        """
        assert Settings().calendar_upcoming_lead == timedelta(minutes=30)

    def test_the_interval_is_not_the_ingestion_job_s(self) -> None:
        """§4: "Neither field is ``calendar_reader_interval``, and neither is
        derived from it."

        "Arming or retuning one of these two changes ingestion's cadence in no way,
        and arming ingestion arms no producer." A shared interval would make §3's
        independence unbuildable: ingestion's cadence is sized for how often beliefs
        should be refreshed and this one's against the lead window, and a figure
        good for one is routinely wrong for the other.
        """
        armed = Settings(
            calendar_reader_path=self._SOURCE, calendar_reader_interval=timedelta(hours=6)
        )
        assert armed.calendar_upcoming_interval is None

        producing = Settings(
            calendar_reader_path=self._SOURCE, calendar_upcoming_interval=timedelta(minutes=5)
        )
        assert producing.calendar_reader_interval is None

    def test_an_armed_producer_with_no_source_is_refused_at_load(self) -> None:
        """§4: "An armed producer with no source to read is an incoherent state and
        is refused as one rather than discovered at the first tick."

        Exactly as ``calendar_reader_interval`` set without a path already is, and
        for that refusal's reasons: a scheduler that omitted the requested job would
        report health while noticing nothing, and one that armed it would re-run a
        failing job forever.
        """
        with pytest.raises(ValidationError, match="armed producer needs a source"):
            Settings(calendar_upcoming_interval=timedelta(minutes=5))

    def test_a_lead_no_longer_than_the_interval_is_refused(self) -> None:
        """§4's hole, closed at load because it cannot be seen at run time.

        "Where ``L < I`` the intervals leave holes: an occurrence starting in
        ``(t+L, t+I]`` is too far away at the first tick and already past at the
        second, so it is never noticed at all." Equality is refused too — a lead
        exactly equal to the interval leaves the single instant at the seam, and the
        window's upper edge is exclusive.
        """
        with pytest.raises(ValidationError, match="strictly greater than"):
            Settings(
                calendar_reader_path=self._SOURCE,
                calendar_upcoming_interval=timedelta(minutes=30),
                calendar_upcoming_lead=timedelta(minutes=10),
            )

        with pytest.raises(ValidationError, match="strictly greater than"):
            Settings(
                calendar_reader_path=self._SOURCE,
                calendar_upcoming_interval=timedelta(minutes=30),
                calendar_upcoming_lead=timedelta(minutes=30),
            )

    def test_a_lead_past_the_read_s_forward_window_is_refused(self) -> None:
        """§4's other silent hole: "the read never returns the occurrence".

        The producer's subject is the reading's own proposals, so a lead reaching
        past ``calendar_window_future`` selects from a region the read never covers
        — and the job runs, logs nothing, and reports health exactly as in the case
        above.
        """
        with pytest.raises(ValidationError, match="must not exceed calendar_window_future"):
            Settings(
                calendar_reader_path=self._SOURCE,
                calendar_upcoming_interval=timedelta(minutes=5),
                calendar_upcoming_lead=timedelta(days=8),
            )

    def test_the_two_lead_refusals_do_not_fire_on_an_unarmed_producer(self) -> None:
        """Both are conditioned on the producer being armed, and §4's argument is why.

        Each exists because "the misconfiguration is silent, and silence here is
        indistinguishable from working" — a statement about a job that *runs*. An
        unarmed deployment reads the lead nowhere, so refusing a hub's startup over
        a figure nothing consults would be a configuration act with no fact behind
        it. The first clause could not fire in any case: it names "this producer's
        own interval", and there is none.
        """
        settings = Settings(
            calendar_reader_path=self._SOURCE,
            calendar_window_future=timedelta(hours=1),
            calendar_upcoming_lead=timedelta(days=8),
        )

        assert settings.calendar_upcoming_lead == timedelta(days=8)
        assert settings.calendar_upcoming_interval is None

    def test_the_armed_coherent_state_loads(self) -> None:
        """Without this, the four refusals above prove nothing.

        A validator that refused everything would pass every case in this class.
        """
        settings = Settings(
            calendar_reader_path=self._SOURCE,
            calendar_upcoming_interval=timedelta(minutes=5),
            calendar_upcoming_lead=timedelta(minutes=45),
        )

        assert settings.calendar_upcoming_interval == timedelta(minutes=5)
        assert settings.calendar_upcoming_lead == timedelta(minutes=45)

    def test_disabled_is_none_and_never_zero(self) -> None:
        """ADR-0083 §7's convention, inherited by §4 in as many words.

        On a completion-scheduled loop a zero interval turns the producer into a hot
        loop re-reading a file, and "off" and "as fast as possible" look identical
        in a config file — the one confusion a scheduler cannot afford.
        """
        with pytest.raises(ValidationError):
            Settings(calendar_reader_path=self._SOURCE, calendar_upcoming_interval=timedelta(0))
