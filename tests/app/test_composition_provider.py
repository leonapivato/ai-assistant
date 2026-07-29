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

from ai_assistant.app import build_engine, composition
from ai_assistant.app.composition import _build_model_provider, _model_specs, _observer_spec
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError, ModelError, ModelUnavailableError
from ai_assistant.core.types import Message, Role
from ai_assistant.learning import ModelBackedObserver
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
    settings = Settings(default_model="anthropic:claude-x", fallback_models=("openai:gpt-5",))

    assert _model_specs(settings)[0] == "anthropic:claude-x"


def test_an_unconfigured_deployment_still_expresses_exactly_one_route() -> None:
    """No fallbacks configured means one route, exactly as before ADR-0062.

    The fallback list is opt-in, so adding it must not change what an existing
    deployment routes over. A reader who sees ``RoutingProvider`` at the
    composition root should still not assume *this* configuration can fall back —
    with one route it cannot.
    """
    settings = Settings()

    assert _model_specs(settings) == (settings.default_model,)


def test_configured_fallbacks_become_the_routes_behind_the_default() -> None:
    """The whole of #353: configuration can now express more than one route.

    Before this, ``_model_specs`` could only ever return one spec, so the router
    ADR-0061 §2 put on the production path was structurally unable to fall back
    *in production*, however it was configured. It no longer is.
    """
    settings = Settings(
        default_model="anthropic:claude-x",
        fallback_models=("openai:gpt-5", "openai:gpt-4o"),
    )

    assert _model_specs(settings) == ("anthropic:claude-x", "openai:gpt-5", "openai:gpt-4o")


async def test_a_configured_fallback_reaches_the_router_build_engine_hands_over(
    tmp_path: Path,
) -> None:
    """The specs are not merely returned — they become the built router's routes.

    ``_model_specs`` and ``_build_model_provider`` are tested separately, so this
    pins the join between them: what ``build_engine`` gives the planner has one
    route per configured spec. Without it, a wiring change that dropped the
    fallbacks in between would pass every other test in this file.
    """
    settings = Settings(default_model="anthropic:claude-x", fallback_models=("openai:gpt-5",))
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        model = _planner_model(engine)
        assert isinstance(model, RoutingProvider)
        assert len(model._routes) == 2
    finally:
        await engine.aclose()


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


def test_an_uninstalled_vendor_stops_the_build_rather_than_the_first_request(
    tmp_path: Path,
) -> None:
    """ADR-0062 §2's deferred half: the check runs before an engine exists.

    Reproduced before it was fixed: ``build_engine`` returned a perfectly healthy
    two-route ``Engine``, and the first completion raised ``ModelError`` wrapping
    ``ImportError: Please install the 'groq' package`` — with ``retryable`` and
    ``routable`` both false, so ``RoutingProvider`` re-raised it without ever
    trying the working ``anthropic`` route behind it (ADR-0013 §5). One
    misconfigured spec truncated the whole order, on every request. Now the
    operator is told at startup, which is the only moment they can act on it.

    ``groq`` stands in for "a vendor whose extra was never installed" — see
    ``tests/models/test_vendor_availability.py``, which guards that precondition.
    """
    settings = Settings(default_model="groq:llama-3", fallback_models=("anthropic:claude-x",))

    with pytest.raises(ConfigurationError, match="not installed"):
        build_engine(settings, data_dir=tmp_path)


def test_an_uninstalled_fallback_vendor_also_stops_the_build(tmp_path: Path) -> None:
    """The check covers the fallbacks, not only ``default_model``.

    A fallback is the case the check was argued for: it is exercised only once
    the primary has already failed, so an unusable one converts a degraded state
    into an outage at the exact moment it was being relied on, and nothing about
    a healthy primary would ever reveal it.
    """
    settings = Settings(default_model="anthropic:claude-x", fallback_models=("groq:llama-3",))

    with pytest.raises(ConfigurationError, match="groq:llama-3"):
        build_engine(settings, data_dir=tmp_path)


def test_every_spec_is_checked_not_merely_the_first() -> None:
    """A bad spec anywhere in the order stops the build, and names itself.

    The failure mode this rules out is a check written as a guard on the primary:
    it would pass a router whose *second* route is unusable, which is the very
    configuration ADR-0062 §2 argues is worst — a fallback that only fails once
    something else already has. An unknown vendor is used rather than an
    uninstalled one so the two error paths are both exercised from here.
    """
    with pytest.raises(ConfigurationError, match="nosuchvendor"):
        _build_model_provider(Settings(), ("anthropic:claude-x", "nosuchvendor:whatever"))


# --- the observer's route: named, separable, and never falling back (ADR-0077 §3) ---


def _observer_provider(engine: Engine) -> ModelProvider:
    """The provider the composed engine's observer will actually read episodes with.

    The same deliberate reach-in ``_planner_model`` uses: the composition root's
    obligations are about *which object ends up where*, and no public surface
    exposes that — an ``Observer`` holds its provider and shows nobody.
    """
    observer = engine._observation._observer
    assert isinstance(observer, ModelBackedObserver)
    return observer._model


def test_the_observer_reads_through_the_conversational_route_when_unset() -> None:
    """Unset means ``default_model``, which widens no recipient set (ADR-0077 §3)."""
    settings = Settings(default_model="anthropic:claude-x", fallback_models=("openai:gpt-5",))
    assert _observer_spec(settings) == "anthropic:claude-x"


def test_a_named_observer_model_is_the_route_that_reads_episodes() -> None:
    """Set, it names the route — and the answers' route is untouched."""
    settings = Settings(default_model="anthropic:claude-x", observer_model="openai:gpt-5")
    assert _observer_spec(settings) == "openai:gpt-5"
    assert _model_specs(settings) == ("anthropic:claude-x",)


async def test_build_engine_gives_the_observer_a_route_that_cannot_fall_back(
    tmp_path: Path,
) -> None:
    """The observer's seam is a ``RetryingProvider``, never a ``RoutingProvider``.

    **This is the no-fallback property, structurally**: with two specs configured
    the planner gets a two-route router, and the observer gets a provider that holds
    no route list at all — so there is no second candidate a routable failure could
    advance to. An implementation that reused the router wholesale would pass every
    other test in this file (ADR-0077 §3, ADR-0013 §4).

    Retry is deliberately kept: it re-sends to the *same* provider, so it widens no
    recipient set, and dropping it would make the observer less resilient than every
    other call for no privacy gain.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-x",
        fallback_models=("openai:gpt-5",),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        model = _observer_provider(engine)
        assert isinstance(model, RetryingProvider)
        assert not isinstance(model, RoutingProvider)
        assert isinstance(_planner_model(engine), RoutingProvider)  # the answers still route
    finally:
        await engine.aclose()


@pytest.mark.parametrize(
    ("observer_model", "expected"),
    [(None, "anthropic:claude-x"), ("openai:gpt-5", "openai:gpt-5")],
)
async def test_only_the_named_route_is_reached_when_an_observation_fails(
    tmp_path: Path, observer_model: str | None, expected: str
) -> None:
    """Unset and set, the primary failing reaches **no** second provider (ADR-0077 §3).

    ADR-0077 §9's paired case, run through the real composed engine: every
    ``PydanticAIProvider`` the build constructs is swapped for a counting double, the
    observer's own call is driven, and the assertion is that exactly one spec was
    ever called and it was the observer's. A router behind the observer would call
    the fallback here and be caught.
    """
    built: dict[str, _FailingProvider] = {}

    def _double(spec: str) -> _FailingProvider:
        provider = _FailingProvider(ModelUnavailableError(f"{spec} is down"))
        built[spec] = provider
        return provider

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(composition, "PydanticAIProvider", _double)
    try:
        settings = Settings(
            embedder=EmbedderKind.HASHING,
            default_model="anthropic:claude-x",
            fallback_models=("openai:gpt-5",),
            observer_model=observer_model,
            model_max_attempts=1,  # no backoff to wait on; retry is not what is on test
        )
        engine = build_engine(settings, data_dir=tmp_path)
        try:
            with pytest.raises(ModelError):
                await _observer_provider(engine).complete(PROMPT)
        finally:
            await engine.aclose()
    finally:
        monkeypatch.undo()

    called = {spec: double.calls for spec, double in built.items() if double.calls}
    assert called == {expected: 1}


def test_an_uninstalled_observer_vendor_stops_the_build(tmp_path: Path) -> None:
    """The observer's route is vendor-checked too, at startup (ADR-0062 §2, ADR-0077 §3).

    Without it a deployment whose answers route perfectly well would fail on the
    first observation instead — and an observation is exactly the call an operator is
    least likely to make while they still remember changing the setting.
    """
    settings = Settings(default_model="anthropic:claude-x", observer_model="groq:llama-3")

    with pytest.raises(ConfigurationError, match="groq:llama-3"):
        build_engine(settings, data_dir=tmp_path)
