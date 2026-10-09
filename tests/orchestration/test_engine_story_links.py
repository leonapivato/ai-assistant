"""Story links wired into the engine: the candidates, the stage and its row (ADR-0300 §6).

Each case builds the engine as the composition root does — understanding, the windows
and the story pieces wired over one memory store and one story store — and asserts what
the captured episode's processing record carries and what the story store recorded.
The candidates and the stage alone are in ``test_story_links.py``, the prompt in
``test_understanding_stories.py``, and the rule in ``test_controller.py``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from story_support import activation, address, episode, failing, memory_of, story
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    StageOutcome,
    StoryActor,
    StoryChange,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodeProcessingRecord, StoryMember

_BUDGET: Final = timedelta(seconds=10)
_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE
_TURN: Final = "The canoe is booked for Sunday."


def _proposal(**fields: Any) -> str:
    return json.dumps(json.loads(STATED_PROPOSAL) | fields)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


async def _seeded() -> FakeMemoryStore:
    """A store holding one earlier activation's episode, ``a-1``, at the harness's instant."""
    return await memory_of(episode("a-1", at=AT), now=AT)


def _harness(
    memory: FakeMemoryStore,
    stories: FakeStoryStore,
    *,
    model: FakeModelProvider,
    wired: bool = True,
) -> Harness:
    return Harness(
        memory=memory,
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider("Noted."), streaming=FakeStreamingCompleter()
        ),
        informational_events=InformationalEventStage(FakeModelProvider("Summarized.")),
        understanding=understanding_stage(model=model),
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        )
        if wired
        else None,
        story_links=StoryLinksStage(stories=stories) if wired else None,
    )


async def _captured(harness: Harness, *seeded: str) -> EpisodeProcessingRecord:
    """The one activation this case ran: the episode no case seeded."""
    (record,) = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record and r.id not in seeded
    ]
    return record


def _entries(record: EpisodeProcessingRecord) -> list[tuple[ControllerStage, ControllerRule, Any]]:
    return [(entry.stage, entry.due, entry.outcome) for entry in record.stages]


async def _members(stories: FakeStoryStore, story_id: str) -> list[tuple[StoryMember, StoryActor]]:
    view = await stories.view(story_id)
    assert view is not None
    return [(entry.member, entry.actor) for entry in view.entries]


# --- a turn ------------------------------------------------------------------------------


async def test_a_turn_links_its_activation_into_the_story_it_named() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    memory = await _seeded()
    model = FakeModelProvider(_proposal(story_labels=["S1"]))
    harness = _harness(memory, stories, model=model)

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness, address("a-1"))
    assert _entries(record)[2:4] == [
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE),
    ]
    assert record.understanding[-1].story_links == (story(trip),)
    now = activation(record.activation_id)
    assert (now, StoryActor.UNDERSTANDING) in await _members(stories, trip)
    log = await stories.log(trip)
    assert log is not None
    assert (log.lines[-1].change, log.lines[-1].trigger) == (
        StoryChange.ADDED,
        record.activation_id,
    )
    # §6:5: the candidate was shown under its label.
    (shown,) = json.loads(model.calls[0].messages[1].content)["stories"]
    assert shown["label"] == "S1"


async def test_an_earlier_episode_in_no_story_starts_one_with_the_activation() -> None:
    stories = _stories()
    memory = await _seeded()
    harness = _harness(memory, stories, model=FakeModelProvider(_proposal(story_labels=["P1"])))

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness, address("a-1"))
    assert record.understanding[-1].story_links == (activation("a-1"),)
    (started,) = (await stories.stories()).stories
    assert await _members(stories, started.story_id) == [
        (activation("a-1"), StoryActor.UNDERSTANDING),
        (activation(record.activation_id), StoryActor.UNDERSTANDING),
    ]


async def test_a_follow_up_links_the_conversation_s_earlier_turn_through_its_h_label() -> None:
    """ADR-0301 §1: the earlier turn reaches the call only as H1, and still starts a story."""
    stories = _stories()
    model = FakeModelProvider.scripted(STATED_PROPOSAL, _proposal(story_labels=["H1"]))
    harness = _harness(FakeMemoryStore(now=lambda: AT), stories, model=model)
    first = await harness.engine.converse("Plan the camping trip.", timeout=_BUDGET)
    assert first.conversation_id is not None
    (earlier,) = [
        r.processing_record.activation_id
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record
    ]

    await harness.engine.converse(_TURN, timeout=_BUDGET, conversation_id=first.conversation_id)

    (item,) = json.loads(model.calls[1].messages[1].content)["channel_window"]
    assert item["label"] == "H1"
    record = await _captured(harness, address(earlier))
    assert record.understanding[-1].story_links == (activation(earlier),)
    (started,) = (await stories.stories()).stories
    assert await _members(stories, started.story_id) == [
        (activation(earlier), StoryActor.UNDERSTANDING),
        (activation(record.activation_id), StoryActor.UNDERSTANDING),
    ]


async def test_an_input_linked_to_nothing_still_records_the_decision() -> None:
    stories = _stories()
    harness = _harness(
        FakeMemoryStore(now=lambda: AT), stories, model=FakeModelProvider(STATED_PROPOSAL)
    )

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness)
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE) in _entries(record)
    assert record.understanding[-1].story_links == ()
    assert (await stories.stories()).stories == ()


async def test_a_deployment_without_the_story_pieces_runs_as_before() -> None:
    stories = _stories()
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(FakeMemoryStore(now=lambda: AT), stories, model=model, wired=False)

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    record = await _captured(harness)
    assert _S.STORY_LINKS not in [entry.stage for entry in record.stages]
    assert "stories" not in json.loads(model.calls[0].messages[1].content)


# --- an informational event ----------------------------------------------------------------


async def test_an_event_s_links_are_recorded_before_its_summary() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    memory = await _seeded()
    harness = _harness(memory, stories, model=FakeModelProvider(_proposal(story_labels=["S1"])))

    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)

    record = await _captured(harness, address("a-1"))
    assert _entries(record) == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE),
        (_S.EVENT_SUMMARY, _R.EVENT_UNSUMMARIZED, _DONE),
        (_S.END, _R.NOTHING_DUE, _DONE),
    ]
    assert (activation(record.activation_id), StoryActor.UNDERSTANDING) in await _members(
        stories, trip
    )


# --- §6:4 and §6:13: a story store that fails --------------------------------------------


async def test_a_story_store_failure_in_the_stage_is_tolerated_and_the_turn_goes_on() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    stories = failing(stories, "link")
    memory = await _seeded()
    harness = _harness(memory, stories, model=FakeModelProvider(_proposal(story_labels=["S1"])))

    outcome = await harness.engine.converse(_TURN, timeout=_BUDGET)

    assert outcome.reply == "Noted."
    record = await _captured(harness, address("a-1"))
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, StageOutcome.FAILED) in _entries(record)
    assert _entries(record)[-1] == (_S.END, _R.NOTHING_DUE, _DONE)


async def test_unreadable_candidates_say_so_and_understanding_proceeds() -> None:
    stories = failing(_stories(), "stories_of")
    memory = await _seeded()
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(memory, stories, model=model)

    await harness.engine.converse(_TURN, timeout=_BUDGET)

    section = json.loads(model.calls[0].messages[1].content)["stories"]
    assert section == "missing: the stories could not be read, so none is shown"
    record = await _captured(harness, address("a-1"))
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE) in _entries(record)


# --- construction --------------------------------------------------------------------------


def test_the_two_story_pieces_are_wired_together_and_beside_understanding() -> None:
    memory = FakeMemoryStore(now=lambda: AT)
    stories = _stories()
    candidates = StoryCandidates(
        stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
    )
    with pytest.raises(ConfigurationError, match="together"):
        Harness(
            memory=memory,
            understanding=understanding_stage(),
            stories=stories,
            story_candidates=candidates,
        )
    with pytest.raises(ConfigurationError, match="needs it"):
        Harness(
            memory=memory,
            stories=stories,
            story_candidates=candidates,
            story_links=StoryLinksStage(stories=stories),
        )


def test_the_story_summary_view_lists_at_least_one_note() -> None:
    """ADR-0303 §10:2's bound is the composition root's, and a bound of none is refused."""
    memory = FakeMemoryStore(now=lambda: AT)
    with pytest.raises(ConfigurationError, match="ADR-0303 §10:2"):
        Harness(memory=memory, stories=_stories(), story_summary_notes=0)
