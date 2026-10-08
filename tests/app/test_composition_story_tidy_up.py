"""The composition root wires ADR-0300 §5's interim tidy-up run, and its values.

The interim run is test-hub scaffolding removed at the cutover, and with it the
assertions here about the engine's ``interim_tidy_up``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    STORY_TIDY_UP_BUDGET,
    STORY_TIDY_UP_EXCERPT_CHARS,
    STORY_TIDY_UP_OTHER_STORIES,
    UNDERSTANDING_EXCERPT_CHARS,
    UNDERSTANDING_STORY_CANDIDATES,
)
from ai_assistant.core.config import Settings
from ai_assistant.orchestration.story_tidy_up import StoryTidyUp
from ai_assistant.orchestration.story_tidy_up_interim import InterimTidyUp

if TYPE_CHECKING:
    from pathlib import Path


def test_the_tidy_ups_values_are_this_lanes() -> None:
    assert STORY_TIDY_UP_EXCERPT_CHARS == UNDERSTANDING_EXCERPT_CHARS
    assert STORY_TIDY_UP_OTHER_STORIES == UNDERSTANDING_STORY_CANDIDATES
    assert timedelta(minutes=2) == STORY_TIDY_UP_BUDGET


async def test_the_interim_run_tidies_over_the_one_story_store_on_consolidations_route(
    tmp_path: Path,
) -> None:
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        interim = engine._interim_tidy_up
        assert isinstance(interim, InterimTidyUp)
        tidy_up = interim._tidy_up
        assert isinstance(tidy_up, StoryTidyUp)
        # One story store and one memory store: the engine surface's and the loop's.
        assert tidy_up._stories is engine._stories
        assert tidy_up._memory is engine._loop._memory
        # The route the deployment names for background work over its own records.
        assert engine._consolidation is not None
        assert tidy_up._model is engine._consolidation._model
        assert (tidy_up._excerpt_chars, tidy_up._other_stories, tidy_up._budget) == (
            STORY_TIDY_UP_EXCERPT_CHARS,
            STORY_TIDY_UP_OTHER_STORIES,
            STORY_TIDY_UP_BUDGET,
        )
    finally:
        await engine.aclose()
