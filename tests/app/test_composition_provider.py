"""The composition root's model seam: retry inside routing (ADR-0061 §2, ADR-0013 §3).

A sibling of ``test_composition.py`` rather than part of it: this file's subject
is only how the provider stack is composed, and keeping it separate keeps that
question readable next to the store-sharing obligations the other file pins.

None of these calls a model. ``PydanticAIProvider`` defers model resolution to
the first completion, so construction needs neither a credential nor a network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app.composition import _build_model_provider, _model_specs
from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, ModelError, ModelUnavailableError
from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIProvider, RetryingProvider, RoutingProvider
from ai_assistant.planning import ModelBackedPlanner

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.orchestration import Engine

PROMPT = [Message(role=Role.USER, content="hi")]


async def _no_sleep(delay: float) -> None:
    """Stand in for backoff, so a composition test never waits in real time."""
    del delay


def _planner_model(engine: Engine) -> ModelProvider:
    """The provider the composed engine's planner will actually call.

    The reach-in is deliberate and matches ``test_composition.py``'s existing
    idiom: the composition root's obligations are about *which object ends up
    where*, and no public surface exposes that — asserting it any other way would
    mean widening the API to make a wiring rule observable.
    """
    planner = engine._loop._planner
    assert isinstance(planner, ModelBackedPlanner)
    return planner._model


class _FailingProvider:
    """A ``ModelProvider`` that always raises, counting its calls."""

    def __init__(self, error: ModelError) -> None:
        self._error = error
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del messages, model
        self.calls += 1
        raise self._error


class _AnsweringProvider:
    """A ``ModelProvider`` that always answers, counting its calls."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del messages, model
        self.calls += 1
        return Message(role=Role.ASSISTANT, content=self._content)


async def test_build_engine_gives_the_planner_a_routing_provider(tmp_path: Path) -> None:
    """The production model seam is the router, not a bare retrying provider.

    Before this, ``RoutingProvider`` was constructed nowhere outside its own
    tests: the fallback mechanism ADR-0013 built existed in ``models/`` and was
    unreachable from any running assistant. The seam the planner is handed is now
    the shape ADR-0013 §3 recommends.
    """
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        assert isinstance(_planner_model(engine), RoutingProvider)
    finally:
        await engine.aclose()


async def test_the_routers_routes_retry_before_routing_gives_up_on_them(tmp_path: Path) -> None:
    """Each route is a ``RetryingProvider``, so retry happens *inside* routing.

    The order is the whole decision (ADR-0013 §3): the opposite nesting re-routes
    on the first transient blip, transmitting the prompt to a second vendor and
    billing it for a failure the first would have absorbed. Nothing in ``models/``
    can enforce the order — a wrapper cannot know what wraps it — so it is pinned
    here, at the one place that chooses it.
    """
    settings = Settings(model_max_attempts=5, model_timeout_seconds=12.5)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        model = _planner_model(engine)
        assert isinstance(model, RoutingProvider)
        routes = model._routes
        assert routes, "the router must have at least one route"
        for route in routes:
            retrying = route.provider
            assert isinstance(retrying, RetryingProvider)
            # The configured resilience knobs reached the wrapper, and did not
            # get lost when routing was layered over it.
            assert retrying._policy.max_attempts == 5
            assert retrying._policy.timeout_seconds == 12.5
            assert isinstance(retrying._inner, PydanticAIProvider)
    finally:
        await engine.aclose()


def test_the_default_model_is_the_first_route() -> None:
    """Whatever else is configured, the operator's ``default_model`` is preferred first."""
    settings = Settings(default_model="anthropic:claude-x")

    assert _model_specs(settings)[0] == "anthropic:claude-x"


def test_todays_configuration_expresses_exactly_one_route() -> None:
    """One route today, and the test says so rather than leaving it implicit.

    ``Settings`` carries a single model spec, so the router it builds cannot fall
    back — a fact worth asserting, because a reader who sees ``RoutingProvider``
    at the composition root would otherwise reasonably assume it can. What is now
    true is that the mechanism is *on the production path* and correct for as many
    routes as it is given (below); what it still needs is a second spec for an
    operator to name.
    """
    assert len(_model_specs(Settings())) == 1


async def test_the_composed_router_falls_back_when_given_more_than_one_spec() -> None:
    """Given two specs, the composition root builds a router that actually falls back.

    This is what makes the fallback mechanism *reachable* rather than merely
    constructed: the router the production path builds is exercised end to end,
    with the routes' inner providers swapped for doubles so no model is called.
    """
    settings = Settings()
    provider = _build_model_provider(settings, ("anthropic:a", "openai:b"))
    down = _FailingProvider(ModelUnavailableError("primary is down"))
    up = _AnsweringProvider("from the fallback")
    doubles: tuple[ModelProvider, ...] = (down, up)
    for route, inner in zip(provider._routes, doubles, strict=True):
        retrying = route.provider
        assert isinstance(retrying, RetryingProvider)
        # Replace each route's *inner* provider, keeping the real
        # RetryingProvider and the real RoutingProvider — the composed structure
        # is the thing on test, and the production `RetryPolicy` with it.
        retrying._inner = inner
        # Backoff is the one part that must not be real: `RetryingProvider`
        # takes `sleep` and `jitter` precisely so a test need not wait on
        # `asyncio.sleep` or depend on `random.random`. Injecting both keeps
        # this deterministic and instant while leaving the *policy* — how many
        # attempts, in what order — exactly as the composition root built it.
        retrying._sleep = _no_sleep
        retrying._jitter = lambda: 0.0

    reply = await provider.complete(PROMPT)

    assert reply.content == "from the fallback"
    # The primary was retried within its own route before routing moved on: retry
    # inside routing, not the other way round.
    assert down.calls == settings.model_max_attempts
    assert up.calls == 1


def test_building_a_provider_with_no_specs_is_a_configuration_error() -> None:
    """An empty route list fails at wiring time, not at the first completion."""
    with pytest.raises(ConfigurationError, match="at least one route"):
        _build_model_provider(Settings(), ())
