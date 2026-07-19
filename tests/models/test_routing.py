"""Tests for the routing/fallback wrapper.

Everything here is offline and synchronous in effect: routes are backed by fakes
that either answer or raise a chosen ``ModelError``, so each test states exactly
one routing rule.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest
from model_provider_contract import ModelProviderContract
from structlog.testing import capture_logs

from ai_assistant.core.errors import (
    ConfigurationError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import RetryingProvider, Route, RoutingProvider
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider

PROMPT = [Message(role=Role.USER, content="hi")]


async def _no_sleep(_delay: float) -> None:
    """Stand in for backoff, so composition tests never wait in real time."""


class AlwaysFailsProvider:
    """A ``ModelProvider`` that raises a fixed failure and counts its calls.

    Local rather than :class:`FakeModelProvider`: routing is driven by the
    *class* of the failure, and the canonical fake flattens every reply failure
    into a bare ``ModelError``, which is exactly the classification under test.
    """

    def __init__(self, error: ModelError) -> None:
        self._error = error
        self.calls = 0
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        self.models.append(model)
        raise self._error


class RecordingProvider:
    """A ``ModelProvider`` that always succeeds and records what it was asked."""

    def __init__(self, content: str = "ok") -> None:
        self._content = content
        self.calls = 0
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        self.models.append(model)
        return Message(role=Role.ASSISTANT, content=self._content)


class TestRoutingProviderContract(ModelProviderContract):
    """Runs RoutingProvider through the shared ModelProvider conformance suite.

    A router is substitutable for a single provider, so it owes the contract in
    its own right. Backed by the canonical fake, so the suite exercises the
    ordinary first-route-succeeds path.
    """

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return RoutingProvider([Route(FakeModelProvider())])


def test_an_empty_route_list_is_rejected() -> None:
    # Failing at construction, not on the first call, keeps the error next to
    # the wiring mistake that caused it.
    with pytest.raises(ConfigurationError, match="at least one route"):
        RoutingProvider([])


async def test_the_first_route_wins_when_it_succeeds() -> None:
    primary, secondary = RecordingProvider("primary"), RecordingProvider("secondary")

    reply = await RoutingProvider([Route(primary), Route(secondary)]).complete(PROMPT)

    assert reply.content == "primary"
    # The fallback must not be warmed, called speculatively, or paid for.
    assert secondary.calls == 0


async def test_a_routable_failure_falls_through_to_the_next_route() -> None:
    down = AlwaysFailsProvider(ModelUnavailableError("503"))
    backup = RecordingProvider("backup")

    reply = await RoutingProvider([Route(down), Route(backup)]).complete(PROMPT)

    assert reply.content == "backup"
    assert down.calls == 1
    assert backup.calls == 1


async def test_a_non_routable_failure_stops_routing_immediately() -> None:
    refused = AlwaysFailsProvider(ModelContentFilterError("refused"))
    backup = RecordingProvider()

    with pytest.raises(ModelContentFilterError):
        await RoutingProvider([Route(refused), Route(backup)]).complete(PROMPT)

    # Shopping a refused prompt around until a provider accepts is not
    # resilience, and would widen who sees a prompt already flagged sensitive.
    assert backup.calls == 0


async def test_an_auth_failure_routes_even_though_it_is_not_retryable() -> None:
    # The case that motivates a second flag: retrying the same expired key is
    # pointless, but another provider authenticates with a different credential.
    expired = AlwaysFailsProvider(ModelAuthError("401"))
    backup = RecordingProvider("backup")

    assert ModelAuthError.retryable is False

    reply = await RoutingProvider([Route(expired), Route(backup)]).complete(PROMPT)

    assert reply.content == "backup"


async def test_routes_are_tried_in_order() -> None:
    first = AlwaysFailsProvider(ModelUnavailableError("first down"))
    second = AlwaysFailsProvider(ModelUnavailableError("second down"))
    third = RecordingProvider("third")

    await RoutingProvider([Route(first), Route(second), Route(third)]).complete(PROMPT)

    assert (first.calls, second.calls, third.calls) == (1, 1, 1)


async def test_exhausting_every_route_reports_all_of_them() -> None:
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503")), label="primary"),
        Route(AlwaysFailsProvider(ModelRateLimitError("429")), label="secondary"),
    ]

    with capture_logs() as logs, pytest.raises(ModelError):
        await RoutingProvider(routes).complete(PROMPT)

    # Naming each candidate beats re-reading the wiring, but it is logged rather
    # than attached to the exception, which the router does not own.
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["routes"] == 2
    assert event["failures"] == [
        {"route": "primary", "error": "ModelUnavailableError"},
        {"route": "secondary", "error": "ModelRateLimitError"},
    ]


async def test_exception_messages_never_reach_the_log() -> None:
    # ADR-0004 §5: logs are Tier 2 and must never carry Tier 0/1 data. Provider
    # errors routinely quote the offending request, so str(exc) is vendor- and
    # attacker-controlled text that can carry the prompt. Only the failure's
    # class is logged — fail-closed by construction rather than by redaction,
    # which matters because no redaction processor is configured yet.
    sensitive = "PATIENT SSN 123-45-6789"
    routes = [Route(AlwaysFailsProvider(ModelUnavailableError(sensitive)), label="primary")]

    with capture_logs() as logs, pytest.raises(ModelUnavailableError):
        await RoutingProvider(routes).complete(PROMPT)

    assert sensitive not in repr(logs)
    # ...while the caller still gets the full message on the exception.
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "primary", "error": "ModelUnavailableError"}]


async def test_exhaustion_reraises_the_last_failure_untouched() -> None:
    last = ModelRateLimitError("429")
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(AlwaysFailsProvider(last)),
    ]

    with pytest.raises(ModelRateLimitError) as caught:
        await RoutingProvider(routes).complete(PROMPT)

    # Classification must survive routing: a caller that backs off on a rate
    # limit still sees one, rather than a flattened generic failure. The very
    # object comes back, with its own message and nothing bolted on.
    #
    # Note this does not claim the traceback is untouched — propagating through
    # the router appends frames to it, as it would through any intermediate
    # call. What is guaranteed is the identity, type, message and __cause__.
    assert caught.value is last
    assert str(caught.value) == "429"
    assert getattr(caught.value, "__notes__", []) == []


async def test_exhaustion_survives_a_subclass_with_a_richer_constructor() -> None:
    # Regression (adversarial review): rebuilding the failure as
    # `type(last)(msg)` assumed every ModelError takes one message argument.
    # A route may be any ModelProvider, so a subclass carrying extra state used
    # to raise TypeError here — which `except ModelError` does not even catch,
    # destroying the provider's real failure.
    class ProviderQuotaError(ModelError):
        """A routable failure that carries more than a message."""

        routable = True

        def __init__(self, limit: int, message: str) -> None:
            super().__init__(message)
            self.limit = limit

    routes = [
        Route(AlwaysFailsProvider(ProviderQuotaError(100, "quota exhausted"))),
        Route(AlwaysFailsProvider(ProviderQuotaError(50, "quota exhausted"))),
    ]

    with pytest.raises(ProviderQuotaError) as caught:
        await RoutingProvider(routes).complete(PROMPT)

    assert caught.value.limit == 50


async def test_reusing_one_exception_object_does_not_accumulate_state() -> None:
    # Regression (adversarial review): the first fix attached a PEP 678 note to
    # the caught exception. A provider that raises a cached instance — which
    # AlwaysFailsProvider does — then grew a note per call, and concurrent
    # routers sharing that object would leak each other's route labels into it.
    shared = ModelUnavailableError("503")
    router = RoutingProvider([Route(AlwaysFailsProvider(shared), label="a")])

    for _ in range(3):
        with pytest.raises(ModelUnavailableError) as caught:
            await router.complete(PROMPT)
        assert caught.value is shared

    # The router owns no state on someone else's exception, so repetition is
    # idempotent no matter how many times it is re-raised.
    assert getattr(shared, "__notes__", []) == []
    assert str(shared) == "503"

    # Its traceback *does* grow across calls, but that is Python's behaviour for
    # re-raising one cached exception instance — a plain function re-raising it
    # accumulates frames identically — not something the router adds or can
    # prevent. Caching an exception instance is the anti-pattern; this asserts
    # the router does not make it materially worse.
    baseline = ModelUnavailableError("503")

    def reraise_baseline() -> None:
        try:
            raise baseline
        except ModelUnavailableError:
            raise

    for _ in range(3):
        with pytest.raises(ModelUnavailableError):
            reraise_baseline()

    assert len(traceback.extract_tb(shared.__traceback__)) <= 2 * len(
        traceback.extract_tb(baseline.__traceback__)
    )


async def test_a_route_model_override_is_passed_to_its_provider() -> None:
    # One provider can appear as several routes — a cheap model first, a
    # stronger one behind it — which is what the per-route override is for.
    shared = RecordingProvider()
    routes = [Route(shared, model="anthropic:claude-haiku-4-5"), Route(shared)]

    await RoutingProvider(routes).complete(PROMPT)

    assert shared.models == ["anthropic:claude-haiku-4-5"]


async def test_a_caller_supplied_override_disables_routing() -> None:
    primary = RecordingProvider("primary")
    backup = RecordingProvider("backup")

    reply = await RoutingProvider([Route(primary), Route(backup)]).complete(
        PROMPT, model="anthropic:claude-opus-4-8"
    )

    assert reply.content == "primary"
    assert primary.models == ["anthropic:claude-opus-4-8"]
    assert backup.calls == 0


async def test_a_caller_supplied_override_does_not_fall_back() -> None:
    down = AlwaysFailsProvider(ModelUnavailableError("503"))
    backup = RecordingProvider()

    # The caller named a model. Answering from a different one would be a worse
    # surprise than the failure, so the failure propagates.
    with pytest.raises(ModelUnavailableError):
        await RoutingProvider([Route(down), Route(backup)]).complete(PROMPT, model="prov:model")

    assert backup.calls == 0


async def test_a_single_route_degenerates_to_pass_through() -> None:
    only = RecordingProvider("only")

    assert (await RoutingProvider([Route(only)]).complete(PROMPT)).content == "only"


async def test_routes_are_not_mutated_by_a_later_caller() -> None:
    routes = [Route(RecordingProvider("primary"))]
    provider = RoutingProvider(routes)

    routes.append(Route(AlwaysFailsProvider(ModelUnavailableError("boom"))))

    # The router snapshots its routes, so mutating the caller's list after
    # construction cannot silently re-wire it.
    assert (await provider.complete(PROMPT)).content == "primary"


class FlakyProvider:
    """Fails with a routable+retryable error N times, then succeeds."""

    def __init__(self, failures: int, content: str) -> None:
        self._remaining = failures
        self._content = content
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise ModelUnavailableError("503")
        return Message(role=Role.ASSISTANT, content=self._content)


async def test_retrying_inside_routing_exhausts_a_provider_before_falling_back() -> None:
    # The composition ADR-0011 promised and ADR-0013 recommends. Cheap retries
    # against the primary come first; only a provider that stays down costs a
    # re-send elsewhere.
    primary = FlakyProvider(failures=99, content="primary")
    backup = RecordingProvider("backup")
    policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0.001, backoff_max_seconds=0.001)

    router = RoutingProvider(
        [
            Route(RetryingProvider(primary, policy=policy, sleep=_no_sleep)),
            Route(backup),
        ]
    )

    reply = await router.complete(PROMPT)

    assert reply.content == "backup"
    # Three attempts against the primary, then one fallback — not one attempt
    # each, and not three fallbacks.
    assert primary.calls == 3
    assert backup.calls == 1


async def test_a_route_that_recovers_within_its_retries_never_falls_back() -> None:
    primary = FlakyProvider(failures=1, content="primary")
    backup = RecordingProvider("backup")
    policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0.001, backoff_max_seconds=0.001)

    router = RoutingProvider(
        [
            Route(RetryingProvider(primary, policy=policy, sleep=_no_sleep)),
            Route(backup),
        ]
    )

    assert (await router.complete(PROMPT)).content == "primary"
    assert primary.calls == 2
    assert backup.calls == 0


def test_a_route_describes_itself_for_diagnostics() -> None:
    provider = RecordingProvider()

    assert Route(provider, label="primary").describe() == "primary"
    assert Route(provider, model="anthropic:claude-haiku-4-5").describe() == (
        "anthropic:claude-haiku-4-5"
    )
    assert Route(provider).describe() == "RecordingProvider"
