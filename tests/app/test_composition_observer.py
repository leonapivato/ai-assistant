"""The composition root's observer (ADR-0329 §9:9, §12:1, §15:1-§15:3, §16).

What the root hands the observer, and what it hands it as: the window's own selector,
the one memory, plan and story stores, a write stage over the writer persisting to that
memory store, two routes named by their settings that never fall back, and every bound
as a constant of the root but the daily budget, which is a setting. That a request is
kept through all of it is ``test_observer_end_to_end.py``'s.

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine, composition
from ai_assistant.app.composition import (
    _observer_commit_spec,
    _observer_scout_spec,
    ensure_model_credentials,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError, ModelError, ModelUnavailableError
from ai_assistant.core.types import Message, Role
from ai_assistant.memory import MemoryIngestor
from ai_assistant.models import RetryingProvider, RoutingProvider
from ai_assistant.orchestration.observer import Observer

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.orchestration.engine import Engine

_PROMPT = [Message(role=Role.USER, content="hi")]


def _observer(engine: Engine) -> Observer:
    """The observer the root built into ``engine``: a deliberate reach-in."""
    observer = engine._observer
    assert isinstance(observer, Observer), "the root wires the observer on every deployment"
    return observer


async def test_the_observer_is_wired_over_the_roots_own_stores_and_the_windows_selector(
    tmp_path: Path,
) -> None:
    """§15:1, §15:3, §12:1, ADR-0028 §4: one of each, and the selector understanding uses."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        observer = _observer(engine)
        windows = engine._windows
        assert windows is not None
        assert observer._episodes is windows._episodes, "the window it tests is the one shown"
        assert observer._memory is engine._memory
        assert observer._plans is engine._plans
        assert observer._reader._stories is engine._stories
        writer = observer._writer._writes._writer
        assert isinstance(writer, MemoryIngestor)
        assert writer._store is engine._memory, "what it writes is what it reads"
    finally:
        await engine.aclose()


async def test_the_observer_holds_the_person_model_store_only_where_the_switch_is_on(
    tmp_path: Path,
) -> None:
    """ADR-0338 §9:8, §11:2: the one store the person block reads, or none at all."""
    off = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path / "off")
    try:
        observer = _observer(off)
        assert (observer._people, observer._pins, observer._writer._pins) == (None, None, None)
    finally:
        await off.aclose()
    on = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True), data_dir=tmp_path / "on"
    )
    try:
        observer = _observer(on)
        blocks = on._person_blocks
        assert blocks is not None
        assert observer._people is blocks._store, "the one store, read and written"
        assert observer._pins is not None
        assert observer._writer._pins is observer._pins, "the guard runs the run's own pass"
        assert observer._pins._memory is on._memory
    finally:
        await on.aclose()


async def test_every_bound_is_the_roots_constant_and_the_budget_is_the_setting(
    tmp_path: Path,
) -> None:
    """ADR-0329 §7:5, §16:4-§16:9, ADR-0346 §6:1-§6:7, ADR-0345 §7:3."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, observer_daily_calls=40), data_dir=tmp_path
    )
    try:
        limits = _observer(engine)._limits
        assert limits.since == datetime(2026, 10, 16, tzinfo=UTC)
        assert limits.since == composition.OBSERVER_SINCE
        assert limits.relevance == composition.RECALL_THRESHOLDS[EmbedderKind.HASHING]
        assert limits.retrieved == composition.OBSERVER_RETRIEVED
        assert limits.recent_supports == composition.OBSERVER_RECENT_SUPPORTS
        assert limits.stale_retries == composition.OBSERVER_STALE_RETRIES
        assert limits.labels == composition.LABEL_BOUNDS
        assert limits.retry_base == composition.OBSERVER_RETRY_BASE
        assert limits.retry_cap == composition.OBSERVER_RETRY_CAP
        assert limits.stuck_after == composition.OBSERVER_STUCK_AFTER
        assert limits.per_run == composition.OBSERVER_PER_RUN
        assert limits.daily_calls == 40
    finally:
        await engine.aclose()


def test_the_daily_budget_starts_at_three_hundred_and_the_timer_is_armed() -> None:
    """§16:9's initial value, and §7:6's row armed by default."""
    settings = Settings()
    assert settings.observer_daily_calls == 300
    assert settings.observer_interval is not None
    assert settings.observer_interval > timedelta(0)


def test_a_stuck_episode_outlasts_a_weekends_outage() -> None:
    """§16:5: no surface re-runs a stuck episode yet, so the count outlasts an outage.

    The backoff doubles from the base to the cap (§16:4); the stuck count's last failure
    comes no sooner than two days after the first.
    """
    waited = timedelta(0)
    backoff = composition.OBSERVER_RETRY_BASE
    for _ in range(composition.OBSERVER_STUCK_AFTER - 1):
        waited += backoff
        backoff = min(composition.OBSERVER_RETRY_CAP, backoff * 2)
    assert waited >= timedelta(days=2)


def test_each_route_is_its_setting_or_else_the_conversational_route() -> None:
    """§9:9, ADR-0285 §5:3: named where set, ``default_model`` where not."""
    unset = Settings(default_model="anthropic:claude-x", fallback_models=("openai:gpt-5",))
    assert _observer_scout_spec(unset) == "anthropic:claude-x"
    assert _observer_commit_spec(unset) == "anthropic:claude-x"
    named = Settings(
        default_model="anthropic:claude-x",
        observer_scout_model="openai:gpt-5",
        observer_commit_model="anthropic:claude-small",
    )
    assert _observer_scout_spec(named) == "openai:gpt-5"
    assert _observer_commit_spec(named) == "anthropic:claude-small"


async def test_neither_route_can_fall_back(tmp_path: Path) -> None:
    """§9:9: each a ``RetryingProvider``, never a router, with fallbacks configured."""
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-x",
        fallback_models=("openai:gpt-5",),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        observer = _observer(engine)
        for route in (observer._scout, observer._commit):
            assert isinstance(route, RetryingProvider)
            assert not isinstance(route, RoutingProvider)
    finally:
        await engine.aclose()


class _Failing:
    """A ``ModelProvider`` that always raises, counting its calls."""

    def __init__(self, spec: str) -> None:
        self.spec = spec
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del messages, model
        self.calls += 1
        msg = f"{self.spec} is down"
        raise ModelUnavailableError(msg)


@pytest.mark.parametrize("step", ["scout", "commit"])
async def test_only_the_named_route_is_reached_once_when_a_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """§9:9, §16:9: the named spec fails, once, and nothing is called in its place.

    Once although the deployment retries three times elsewhere: the observer records
    each call against its daily budget before making it, so a retry inside the call
    would send requests the budget never counted. Its own retry is the attempt's
    recorded backoff (§16:4).
    """
    built: dict[str, _Failing] = {}
    monkeypatch.setattr(
        composition,
        "PydanticAIProvider",
        lambda spec, *, thinking_summaries: built.setdefault(spec, _Failing(spec)),
    )
    monkeypatch.setattr(composition, "ensure_vendor_available", lambda spec: None)
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-x",
        fallback_models=("openai:gpt-5",),
        observer_scout_model="anthropic:scout",
        observer_commit_model="anthropic:commit",
    )
    assert settings.model_max_attempts > 1
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        observer = _observer(engine)
        route = observer._scout if step == "scout" else observer._commit
        assert isinstance(route, RetryingProvider)
        assert route._policy.max_attempts == 1
        assert route._policy.timeout_seconds == settings.model_timeout_seconds
        with pytest.raises(ModelError):
            await route.complete(_PROMPT)
    finally:
        await engine.aclose()

    assert {spec: one.calls for spec, one in built.items() if one.calls} == {f"anthropic:{step}": 1}


def test_an_uninstalled_observer_vendor_stops_the_build(tmp_path: Path) -> None:
    """ADR-0062 §2: checked at startup, not at the first run."""
    settings = Settings(default_model="anthropic:claude-x", observer_commit_model="groq:llama-3")

    with pytest.raises(ConfigurationError, match="groq:llama-3"):
        build_engine(settings, data_dir=tmp_path)


def test_the_credential_preflight_covers_the_observers_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#530: a route that never falls back is checked at the hub's start, each once."""
    asked: list[str] = []
    monkeypatch.setattr(composition, "ensure_vendor_available", lambda spec: None)
    monkeypatch.setattr(composition, "ensure_credential_available", asked.append)

    ensure_model_credentials(
        Settings(
            default_model="anthropic:one",
            observer_scout_model="openai:two",
            observer_commit_model="anthropic:one",
        )
    )

    assert asked == ["anthropic:one", "openai:two"]
