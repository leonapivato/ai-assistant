"""The engine driving ADR-0282's windows stage, and understanding reading what it holds.

The windows are assembled by their own stage before recall; the working episode holds
the episode window as ids, and the understanding phase fetches the records it renders,
current versions, recording what came back missing (ADR-0282 §2, §3, §5). The stage
record's placement of the entry for each activation kind is in
``test_engine_stage_record.py``.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from structlog.testing import capture_logs
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import EPISODE_LIMIT, STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ModelTimeoutError
from ai_assistant.core.types import ControllerRule, ControllerStage, EpisodicMemory, StageOutcome
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.understanding import RecentEpisodes, Windows, WindowsStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import ChannelWindow

_BUDGET: Final = timedelta(seconds=10)
_DONE: Final = StageOutcome.DONE


class _ForgetsWhatItChose(WindowsStage):
    """A windows stage whose chosen episodes are deleted before understanding fetches them."""

    def __init__(self, memory: FakeMemoryStore) -> None:
        super().__init__(episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT))
        self._memory = memory
        self.chosen: list[tuple[str, ...] | None] = []

    async def assemble(
        self, channel: ChannelWindow, *, audience: TurnSupply, episodes: bool
    ) -> Windows:
        windows = await super().assemble(channel, audience=audience, episodes=episodes)
        self.chosen.append(windows.episode_ids)
        for episode_id in windows.episode_ids or ():
            await self._memory.delete(episode_id)
        return windows


def _harness(model: FakeModelProvider, memory: FakeMemoryStore, **knobs: Any) -> Harness:
    return Harness(
        memory=memory,
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()
        ),
        understanding=understanding_stage(model=model),
        **knobs,
    )


def _episode_window(model: FakeModelProvider, call: int) -> Any:
    return json.loads(model.calls[call].messages[1].content)["episode_window"]


async def test_understanding_renders_the_episodes_the_windows_stage_chose() -> None:
    memory = FakeMemoryStore(now=lambda: AT)
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(model, memory)
    await harness.engine.converse("My dentist is Dr Rao.", timeout=_BUDGET)
    await harness.engine.converse("Who is my dentist?", timeout=_BUDGET)
    (shown,) = _episode_window(model, 1)
    assert shown["label"] == "P1"
    assert shown["input"] == "My dentist is Dr Rao."


async def test_a_window_episode_forgotten_before_understanding_is_not_rendered() -> None:
    """ADR-0282 §2, §5: a fetch returns current versions; a missing id is recorded and
    left out, and is not an error."""
    memory = FakeMemoryStore(now=lambda: AT)
    model = FakeModelProvider(STATED_PROPOSAL)
    await _harness(model, memory).engine.converse("My dentist is Dr Rao.", timeout=_BUDGET)
    windows = _ForgetsWhatItChose(memory)
    harness = _harness(model, memory, windows=windows)
    with capture_logs() as logs:
        await harness.engine.converse("Who is my dentist?", timeout=_BUDGET)
    (chosen,) = windows.chosen
    assert chosen is not None
    assert len(chosen) == 1
    assert _episode_window(model, 1) == "missing: there are no other recent episodes to show"
    (fetch,) = [log for log in logs if log["event"] == "stage_fetch"]
    assert (fetch["stage"], fetch["fetched"], fetch["missing"]) == ("understanding", 1, 1)


class _Unyielding(WindowsStage):
    """A windows stage that holds the loop past a short deadline, then returns."""

    async def assemble(
        self, channel: ChannelWindow, *, audience: TurnSupply, episodes: bool
    ) -> Windows:
        time.sleep(0.05)  # noqa: ASYNC251 — the point: no timer can fire while it runs
        return await super().assemble(channel, audience=audience, episodes=episodes)


async def test_windows_that_cross_the_deadline_without_yielding_are_the_expiry() -> None:
    """ADR-0280 §5, ADR-0282 §3: assembly that returned past the deadline is the windows
    stage's timeout, and its decision is not made."""
    memory = FakeMemoryStore(now=lambda: AT)
    windows = _Unyielding(episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT))
    harness = _harness(FakeModelProvider(STATED_PROPOSAL), memory, windows=windows)
    with pytest.raises(ModelTimeoutError, match="assembling the windows"):
        await harness.engine.converse("Who is my dentist?", timeout=timedelta(milliseconds=20))
    (episode,) = [r for r in await memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.processing_record is not None
    assert [(e.stage, e.due, e.outcome) for e in episode.processing_record.stages] == [
        (ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED, _DONE),
        (ControllerStage.WINDOWS, ControllerRule.WINDOWS_UNASSEMBLED, StageOutcome.TIMED_OUT),
        (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT, _DONE),
    ]
