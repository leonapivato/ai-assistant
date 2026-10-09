"""The engine's run of the matters pass (ADR-0300 §9:3, ADR-0302 §5).

``Engine.decide_story_flags`` is concrete maintenance surface, the body of the
scheduler's ``matters_pass`` row: each case builds the engine with the pass wired, or
not, and asserts what the operation does. The pass itself is in
``test_matters_pass.py``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from typing import Final

import pytest
from story_support import AT, activation, episode, memory_of
from test_engine import Harness

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    StoryActor,
    StoryChange,
    StoryDecision,
    StoryFlag,
    StoryFlagKind,
    StoryNoteAuthor,
    StoryPageDraft,
    StoryPageLine,
)
from ai_assistant.orchestration.matters_pass import MattersPass, MattersPassReport
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStoryStore

_BUDGET: Final = timedelta(seconds=10)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


def _pass(
    model: FakeModelProvider, stories: FakeStoryStore, memory: FakeMemoryStore
) -> MattersPass:
    return MattersPass(
        model=model,
        stories=stories,
        memory=memory,
        excerpt_chars=1000,
        flags_per_run=10,
        decisions=5,
        episodes=6,
        notes=5,
        budget=_BUDGET,
    )


async def test_it_runs_the_pass_and_answers_its_report() -> None:
    stories = _stories()
    memory = await memory_of(episode("a-1"))
    created = await stories.create([activation("a-1")], actor=StoryActor.OWNER)
    trip = created.story_id
    assert trip is not None
    note = await stories.append_note(trip, "Riverside.", author=StoryNoteAuthor.OWNER)
    assert note.note is not None
    state = await stories.current_page(trip)
    assert state is not None
    written = await stories.write_page(
        trip,
        StoryPageDraft(
            lines=(StoryPageLine(text="Riverside."),),
            took_in_notes=(note.note.note_id,),
            flags=(StoryFlag(kind=StoryFlagKind.TWO_MATTERS),),
            outside=False,
        ),
        as_of=state.as_of,
    )
    assert written.version is not None
    model = FakeModelProvider(json.dumps({"decision": "leave"}))
    harness = Harness(memory=memory, stories=stories, matters_pass=_pass(model, stories, memory))

    report = await harness.engine.decide_story_flags()

    assert isinstance(report, MattersPassReport)
    assert (report.flags, report.decided) == (1, 1)
    log = await stories.log(trip, limit=100)
    assert log is not None
    (decided,) = [line for line in log.lines if line.change is StoryChange.DECIDED]
    assert (decided.outcome, decided.actor) == (StoryDecision.LEFT, StoryActor.MATTERS_PASS)


async def test_it_refuses_where_no_pass_is_wired() -> None:
    harness = Harness(memory=await memory_of(), stories=_stories())

    with pytest.raises(ConfigurationError, match="no matters pass is wired"):
        await harness.engine.decide_story_flags()


async def test_the_pass_is_wired_only_beside_the_story_store() -> None:
    stories = _stories()
    memory = await memory_of()

    with pytest.raises(ConfigurationError, match="only beside that store"):
        Harness(memory=memory, matters_pass=_pass(FakeModelProvider(), stories, memory))
