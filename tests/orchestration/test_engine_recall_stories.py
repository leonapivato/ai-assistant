"""Recall's stories wired into the engine: recorded, and joining the candidates (ADR-0300 §7).

Each case builds the engine as the composition root does — the windows, recall,
understanding and the story pieces over one memory store and one story store — with an
episode window of one, so the earlier episode recall keeps is past it (ADR-0282 §4).
It asserts what the captured episode's recall result carries, which candidates
understanding was shown and in what order (§6:1), and where the activation was linked.
The stage alone is in ``test_recall_stories.py``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

from story_support import activation, address, episode, failing, memory_of, story
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, recall_stage, understanding_stage

from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    RecallOutcome,
    StageOutcome,
    StoryActor,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.understanding import RecentEpisodes, WindowsStage
from ai_assistant.testing import FakeModelProvider, FakeStoryStore, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodeProcessingRecord
    from ai_assistant.testing import FakeMemoryStore

_BUDGET: Final = timedelta(seconds=10)
_TURN: Final = "The canoe is booked for Sunday."
#: The episode window's one episode: recent, and sharing no word recall would keep it by.
_WINDOWED: Final = "Plan the drive to Riverside."
_SEEDED: Final = (address("a-old"), address("a-new"))


def _proposal(**fields: Any) -> str:
    return json.dumps(json.loads(STATED_PROPOSAL) | fields)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


async def _story(stories: FakeStoryStore, activation_id: str) -> str:
    story_id = (await stories.create([activation(activation_id)], actor=StoryActor.OWNER)).story_id
    assert story_id is not None
    return story_id


async def _seeded() -> FakeMemoryStore:
    """``a-old``, which recall keeps by the turn's words, and ``a-new``, the window's one."""
    return await memory_of(
        episode("a-old", at=AT - timedelta(days=3), text=_TURN),
        episode("a-new", at=AT - timedelta(hours=1), text=_WINDOWED),
        now=AT,
    )


def _harness(
    memory: FakeMemoryStore,
    stories: FakeStoryStore,
    *,
    model: Any,
    recall_stories: FakeStoryStore | None = None,
) -> Harness:
    """The engine over one memory store and one story store, recall's unless named."""
    return Harness(
        memory=memory,
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider("Noted."), streaming=FakeStreamingCompleter()
        ),
        understanding=understanding_stage(model=model),
        windows=WindowsStage(episodes=RecentEpisodes(memory=memory, limit=1)),
        recall=recall_stage(memory, stories=stories if recall_stories is None else recall_stories),
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        ),
        story_links=StoryLinksStage(stories=stories),
    )


async def _captured(harness: Harness) -> EpisodeProcessingRecord:
    (record,) = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record and r.id not in _SEEDED
    ]
    return record


def _shown(model: FakeModelProvider) -> Any:
    return json.loads(model.calls[0].messages[1].content)


def _texts(view: dict[str, Any]) -> str:
    return json.dumps(view["latest_episodes"])


async def test_recalls_story_is_recorded_and_joins_the_candidates_after_the_windows() -> None:
    stories = _stories()
    windowed = await _story(stories, "a-new")
    recalled = await _story(stories, "a-old")
    model = FakeModelProvider(_proposal(story_labels=["S2"]))
    harness = _harness(await _seeded(), stories, model=model)

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FOUND
    kept = {item.id: item.stories for item in record.recall.items}
    # §7:2: the kept episode carries its story; the window's episode is not recalled.
    assert kept[address("a-old")] == (recalled,)
    assert address("a-new") not in kept
    # §6:1: the window's story first, then recall's.
    first, second = _shown(model)["stories"]
    assert (first["label"], second["label"]) == ("S1", "S2")
    assert _WINDOWED in _texts(first)
    assert _TURN in _texts(second)
    # The S2 label resolves to recall's story, and the stage links the activation there.
    assert record.understanding[-1].story_links == (story(recalled),)
    view = await stories.view(recalled)
    assert view is not None
    assert activation(record.activation_id) in [entry.member for entry in view.entries]
    assert windowed != recalled


async def test_a_story_already_a_candidate_through_the_window_is_not_repeated() -> None:
    stories = _stories()
    both = (
        await stories.create([activation("a-new"), activation("a-old")], actor=StoryActor.OWNER)
    ).story_id
    assert both is not None
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _seeded(), stories, model=model)

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness)
    assert record.recall is not None
    assert {item.id: item.stories for item in record.recall.items}[address("a-old")] == (both,)
    (only,) = _shown(model)["stories"]
    assert only["label"] == "S1"


async def test_a_story_store_failure_in_recall_is_tolerated_and_the_turn_goes_on() -> None:
    stories = _stories()
    await _story(stories, "a-old")
    model = FakeModelProvider(STATED_PROPOSAL)
    # Recall's own reads of the story store fail; the candidates' still answer.
    harness = _harness(
        await _seeded(), stories, model=model, recall_stories=failing(_stories(), "stories_of")
    )

    outcome = await harness.engine.converse(_TURN, timeout=_BUDGET)

    assert outcome.reply == "Noted."
    record = await _captured(harness)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FAILED
    stages = [(entry.stage, entry.due, entry.outcome) for entry in record.stages]
    assert (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, StageOutcome.FAILED) in stages
    assert (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, StageOutcome.DONE) in (
        stages
    )
    # Recall's failure brings no candidate, and the window's episode is in no story.
    assert _shown(model)["stories"] == (
        "missing: none of the earlier episodes shown belongs to a story"
    )
