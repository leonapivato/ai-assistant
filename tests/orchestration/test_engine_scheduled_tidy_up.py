"""The engine's scheduled tidy-up (ADR-0358 §4).

``Engine.tidy_stories`` is concrete maintenance surface, the body of the scheduler's
``scheduled_tidy_up`` row: each case builds the engine with the run wired, or not, and
asserts what the operation does. The run itself is in ``test_scheduled_tidy_up.py``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from typing import Final

import pytest
from story_support import AT, activation, episode, memory_of
from structured_support import structured
from test_engine import Harness

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import StoryActor, StoryNoteAuthor
from ai_assistant.orchestration.story_tidy_up import (
    STORY_TIDY_UP_PROMPT,
    ScheduledTidyUp,
    ScheduledTidyUpReport,
    StoryTidyUp,
)
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStoryStore, default_prompt

_BUDGET: Final = timedelta(seconds=10)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


def _scheduled(
    model: FakeModelProvider, stories: FakeStoryStore, memory: FakeMemoryStore
) -> ScheduledTidyUp:
    tidy_up = StoryTidyUp(
        model=structured(model),
        stories=stories,
        memory=memory,
        excerpt_chars=2000,
        other_stories=0,
        decisions=0,
        budget=_BUDGET,
        threshold=0.0,
        prompt=default_prompt(STORY_TIDY_UP_PROMPT),
    )
    return ScheduledTidyUp(
        tidy_up=tidy_up,
        stories=stories,
        threshold=1,
        quiet=timedelta(hours=24),
        per_run=10,
        budget=_BUDGET,
        now=lambda: AT,
    )


async def test_it_runs_the_scheduled_tidy_up_and_answers_its_report() -> None:
    stories = _stories()
    memory = await memory_of(episode("a-1"))
    created = await stories.create([activation("a-1")], actor=StoryActor.UNDERSTANDING)
    trip = created.story_id
    assert trip is not None
    await stories.append_note(trip, "Riverside.", author=StoryNoteAuthor.OWNER)
    model = FakeModelProvider(json.dumps({"lines": ["A camping trip."], "flags": []}))
    harness = Harness(
        memory=memory, stories=stories, scheduled_tidy_up=_scheduled(model, stories, memory)
    )

    report = await harness.engine.tidy_stories()

    assert report == ScheduledTidyUpReport(due=1, tidied=1, written=1)
    state = await stories.current_summary(trip)
    assert state is not None
    assert state.summary is not None
    assert [line.text for line in state.summary.lines] == ["A camping trip."]
    # §4:7: it starts no activation and records no episode; its trace is the operation's.
    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "tidy_stories"


async def test_it_refuses_where_no_scheduled_tidy_up_is_wired() -> None:
    harness = Harness(memory=await memory_of(), stories=_stories())

    with pytest.raises(ConfigurationError, match="no scheduled tidy-up is wired"):
        await harness.engine.tidy_stories()


async def test_the_scheduled_tidy_up_is_wired_only_beside_the_story_store() -> None:
    stories = _stories()
    memory = await memory_of()

    with pytest.raises(ConfigurationError, match="only beside that store"):
        Harness(memory=memory, scheduled_tidy_up=_scheduled(FakeModelProvider(), stories, memory))


def test_assistant_engine_gains_nothing() -> None:
    """§4:8: a public method of the concrete engine, and on no Protocol."""
    assert not hasattr(AssistantEngine, "tidy_stories")
