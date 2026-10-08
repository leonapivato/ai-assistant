"""The composition root wires ADR-0300 §6's candidates and story-links stage, and its values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    STORY_SHORT_VIEW_EPISODES,
    STORY_SHORT_VIEW_LINES,
    STORY_SHORT_VIEW_NOTES,
    UNDERSTANDING_STORY_CANDIDATES,
)
from ai_assistant.core.config import Settings
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage

if TYPE_CHECKING:
    from pathlib import Path


def test_the_roots_story_values_are_the_decisions_and_this_lanes() -> None:
    """§6:1's initial value, and §6:2's numbers within its ceiling of two."""
    assert UNDERSTANDING_STORY_CANDIDATES == 5
    assert STORY_SHORT_VIEW_LINES == 3
    assert (STORY_SHORT_VIEW_NOTES, STORY_SHORT_VIEW_EPISODES) == (2, 2)


async def test_the_engine_is_built_with_both_story_pieces_over_its_one_story_store(
    tmp_path: Path,
) -> None:
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        candidates = engine._story_candidates
        links = engine._story_links
        assert isinstance(candidates, StoryCandidates)
        assert isinstance(links, StoryLinksStage)
        # One story store: the engine surface's, the candidates' and the stage's.
        assert candidates._stories is engine._stories
        assert links._stories is engine._stories
        assert candidates._memory is engine._loop._memory
        assert (candidates._limit, candidates._lines, candidates._notes, candidates._episodes) == (
            UNDERSTANDING_STORY_CANDIDATES,
            STORY_SHORT_VIEW_LINES,
            STORY_SHORT_VIEW_NOTES,
            STORY_SHORT_VIEW_EPISODES,
        )
    finally:
        await engine.aclose()
