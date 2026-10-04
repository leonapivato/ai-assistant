"""ADR-0287 §6's lane 3 tests, through production composition.

Episodes are kept until they are forgotten (ADR-0287 §1): ``episode_retention``
defaults to ``None``, so an episode written under the default ``Settings`` carries no
``expires_at``. The setting itself is unmoved, so a deployment that sets a finite
window still gets an ``expires_at`` of ``occurred_at`` advanced by it.

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a fresh
data directory, so the activation writer and the episodic store are the ones the root
wires from the ``Settings`` it is handed. Only the model-facing seams are substituted:
the provider's ``complete``, the planner, the associator and the streaming completer.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    ChannelInput,
    EpisodicMemory,
    GoalAssociation,
    NewConversation,
    PlannerOutput,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.testing import (
    FakeGoalAssociator,
    FakeModelProvider,
    FakeStreamingCompleter,
    StreamAttempt,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from ai_assistant.core.types import GoalBrief, Message
    from ai_assistant.orchestration import Engine

pytestmark = pytest.mark.integration

_BUDGET: Final = timedelta(seconds=10)
_AT: Final = datetime(2026, 10, 4, tzinfo=UTC)
_WINDOW: Final = timedelta(days=7)
_UNDERSTANDING_PROMPT: Final = "You read one incoming input and state what it means."
_UNDERSTOOD: Final = json.dumps(
    {"meaning": "The input means what it says.", "meaning_ground": "stated"}
)


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if _UNDERSTANDING_PROMPT in messages[0].content else "Noted."


@pytest.fixture
def composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[Settings], AbstractAsyncContextManager[Engine]]:
    """Wire the production root over the given ``Settings``, substituting only models."""

    model = FakeModelProvider(_reply)

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)

    @asynccontextmanager
    async def build(settings: Settings) -> AsyncIterator[Engine]:
        built = build_engine(settings, data_dir=tmp_path)
        built._associator = FakeGoalAssociator(
            answer=GoalAssociation(verdict=AssociationVerdict.FRESH)
        )
        built._routing = None
        built._composing._streaming = FakeStreamingCompleter(
            script=tuple(StreamAttempt(deltas=("Channel reply.",)) for _ in range(8))
        )
        plan_ids = count(1)

        async def plan(goal: GoalBrief, **_kwargs: object) -> PlannerOutput:
            return PlannerOutput(
                plan=ActionPlan(
                    id=f"retention-plan-{next(plan_ids)}",
                    goal_id=goal.goal_id,
                    steps=(),
                    created_at=_AT,
                )
            )

        monkeypatch.setattr(built._loop._planner, "plan", plan)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    return build


async def _captured_episode(engine: Engine) -> EpisodicMemory:
    """One text activation on a new conversation, and the episode it recorded."""
    result = await engine.receive(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello")),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )
    assert result.capture.state == "recorded"
    address = result.capture.episode_id
    assert address is not None
    episode = await engine._conversations._memory.get(address)
    assert isinstance(episode, EpisodicMemory), episode
    return episode


async def test_an_episode_written_under_the_default_settings_carries_no_expires_at(
    composed: Callable[[Settings], AbstractAsyncContextManager[Engine]], tmp_path: Path
) -> None:
    """§1, §6: the default keeps an episode until it is forgotten."""
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)
    assert "episode_retention" not in settings.model_fields_set, "the default, not a choice"

    async with composed(settings) as engine:
        episode = await _captured_episode(engine)

    assert episode.expires_at is None


async def test_an_episode_written_under_a_finite_window_expires_that_far_after_it_occurred(
    composed: Callable[[Settings], AbstractAsyncContextManager[Engine]], tmp_path: Path
) -> None:
    """§1, §6: a finite ``episode_retention`` still stamps ``occurred_at`` advanced by it."""
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING, episode_retention=_WINDOW)

    async with composed(settings) as engine:
        episode = await _captured_episode(engine)

    assert episode.expires_at == episode.occurred_at + _WINDOW
