"""The engine's interim tidy-up run (ADR-0300 §5, "before the phases").

Test-hub scaffolding, removed at the cutover with
``orchestration.story_tidy_up_interim``; so is this suite. Each case builds the engine
as the composition root does, with the story pieces and the interim run wired, drives
one turn, and asserts that the turn did not wait for the tidy-up it started, and what
the tidy-up then wrote. The operation alone is in ``test_story_tidy_up.py``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import AT, activation, episode, memory_of
from test_engine import Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import Message, Role, StageOutcome, StoryActor, StoryNoteAuthor
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.orchestration.story_links import (
    StoryCandidates,
    StoryLinksDecision,
    StoryLinksStage,
)
from ai_assistant.orchestration.story_tidy_up import StoryTidyUp
from ai_assistant.orchestration.story_tidy_up_interim import InterimTidyUp
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_BUDGET: Final = timedelta(seconds=10)
_TURN: Final = "The canoe is booked for Sunday."
_PAGE: Final = json.dumps({"lines": [{"text": "A camping trip to Riverside.", "cites": ["N1"]}]})


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


class _Gated:
    """The tidy-up's provider: it records whether it ran in an activation, then waits."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.gate = asyncio.Event()
        self.calls = 0
        self.entered = asyncio.Event()
        self.in_activation: list[bool] = []

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.calls += 1
        self.in_activation.append(active_state() is not None)
        self.entered.set()
        await self.gate.wait()
        return Message(role=Role.ASSISTANT, content=self.reply)


def _tidy_up(model: Any, stories: FakeStoryStore, memory: FakeMemoryStore) -> StoryTidyUp:
    return StoryTidyUp(
        model=model,
        stories=stories,
        memory=memory,
        excerpt_chars=2000,
        other_stories=5,
        budget=_BUDGET,
    )


def _harness(
    memory: FakeMemoryStore, stories: FakeStoryStore, tidy_up: StoryTidyUp, *, labels: list[str]
) -> Harness:
    proposal = json.dumps(json.loads(STATED_PROPOSAL) | {"story_labels": labels})
    return Harness(
        memory=memory,
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider("Noted."), streaming=FakeStreamingCompleter()
        ),
        informational_events=InformationalEventStage(FakeModelProvider("Summarized.")),
        understanding=understanding_stage(model=FakeModelProvider(proposal)),
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        ),
        story_links=StoryLinksStage(stories=stories),
        interim_tidy_up=InterimTidyUp(tidy_up=tidy_up),
    )


async def _drained(harness: Harness) -> None:
    """Every task the engine started, the tidy-ups included, run to its end."""
    await asyncio.gather(*harness.engine._inflight)


async def test_a_turn_linking_into_a_story_with_a_pending_note_starts_a_tidy_up_unawaited() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    await stories.append_note(
        trip, "Camping at Riverside.", author=StoryNoteAuthor.PLANNING, rests_on="a-1"
    )
    memory = await memory_of(episode("a-1", at=AT), now=AT)
    model = _Gated(_PAGE)
    harness = _harness(memory, stories, _tidy_up(model, stories, memory), labels=["S1"])

    # The turn returns while the tidy-up's completion is still held: nobody waits.
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    await model.entered.wait()
    state = await stories.current_page(trip)
    assert state is not None
    assert state.page is None

    model.gate.set()
    await _drained(harness)

    state = await stories.current_page(trip)
    assert state is not None
    assert state.page is not None
    assert [line.text for line in state.page.lines] == ["A camping trip to Riverside."]
    assert state.pending_notes == ()
    assert "a-1" not in state.pending_episodes
    # Its own task, in a context of its own: not the activation's.
    assert (model.calls, model.in_activation) == (1, [False])


async def test_a_turn_linking_into_no_story_starts_no_tidy_up() -> None:
    stories = _stories()
    memory = await memory_of(episode("a-1", at=AT), now=AT)
    model = FakeModelProvider.scripted()
    harness = _harness(memory, stories, _tidy_up(model, stories, memory), labels=[])

    await harness.engine.converse(_TURN, timeout=_BUDGET)
    await _drained(harness)

    assert model.calls == []


async def test_a_story_the_rule_starts_is_tidied_from_the_earlier_episode_it_holds() -> None:
    stories = _stories()
    memory = await memory_of(episode("a-1", at=AT), now=AT)
    reply = json.dumps(
        {
            "safety_net": [{"episode": "E1", "text": "A camping trip to Riverside."}],
            "lines": [{"text": "A camping trip to Riverside.", "cites": ["T1"]}],
        }
    )
    model = FakeModelProvider(reply)
    harness = _harness(memory, stories, _tidy_up(model, stories, memory), labels=["P1"])

    await harness.engine.converse(_TURN, timeout=_BUDGET)
    await _drained(harness)

    (started,) = (await stories.stories()).stories
    state = await stories.current_page(started.story_id)
    assert state is not None
    assert state.page is not None
    versions = await stories.page_versions(started.story_id)
    assert versions is not None
    (version,) = versions.versions
    assert version.took_in_episodes[0] == "a-1"


async def test_the_runs_are_one_per_story_linked_or_started() -> None:
    model = FakeModelProvider.scripted()
    memory = await memory_of()
    stories = _stories()
    interim = InterimTidyUp(tidy_up=_tidy_up(model, stories, memory))
    decision = StoryLinksDecision(
        outcome=StageOutcome.FAILED, linked=("story:1", "story:2"), started="story:1"
    )

    runs = interim.runs(decision)
    try:
        assert len(runs) == 2
    finally:
        for run in runs:
            await run
    assert interim.runs(StoryLinksDecision(outcome=StageOutcome.DONE)) == ()


async def test_a_crashing_run_is_logged_and_never_raised() -> None:
    class _Crashing(StoryTidyUp):
        async def run(self, story_id: str) -> Any:
            msg = "a defect"
            raise RuntimeError(msg)

    memory = await memory_of()
    stories = _stories()
    crashing = _Crashing(
        model=FakeModelProvider(),
        stories=stories,
        memory=memory,
        excerpt_chars=1,
        other_stories=0,
        budget=_BUDGET,
    )
    (run,) = InterimTidyUp(tidy_up=crashing).runs(
        StoryLinksDecision(outcome=StageOutcome.DONE, linked=("story:1",))
    )
    await run


async def test_the_interim_run_is_wired_only_beside_the_story_links_stage() -> None:
    memory = await memory_of()
    stories = _stories()
    interim = InterimTidyUp(tidy_up=_tidy_up(FakeModelProvider(), stories, memory))
    with pytest.raises(ConfigurationError, match="ADR-0300 §5"):
        Harness(memory=memory, stories=stories, interim_tidy_up=interim)
