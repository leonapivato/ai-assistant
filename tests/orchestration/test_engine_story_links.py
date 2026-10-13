"""Story links wired into the engine: the candidates, the stage and its row (ADR-0300 §6).

Each case builds the engine as the composition root does — understanding, the windows
and the story pieces wired over one memory store and one story store — and asserts what
the captured episode's processing record carries and what the story store recorded.
The candidates and the stage alone are in ``test_story_links.py``, the prompt in
``test_understanding_stories.py``, and the rule in ``test_controller.py``.
"""

from __future__ import annotations

from itertools import count

import pytest
from test_engine import AT, Harness
from understanding_support import understanding_stage

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


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
