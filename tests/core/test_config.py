"""Tests for Settings validation of the context configuration (ADR-0008)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from pydantic_ai.models import known_model_names

from ai_assistant.core.config import _MODEL_SPEC_PATTERN, Settings, load_settings
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
