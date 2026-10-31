"""The composition root wires ADR-0300 §5's tidy-up, and its values.

The interim run that started one at the freeze is gone with the switch (ADR-0309 §5:8);
planning's tidy-up call is what runs it (ADR-0307 §7, ADR-0300 §10:4), through the
phases' story calls.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    RECALL_THRESHOLDS,
    SCHEDULED_TIDY_UP_PER_RUN,
    SCHEDULED_TIDY_UP_QUIET,
    SCHEDULED_TIDY_UP_THRESHOLD,
    STORY_TIDY_UP_BUDGET,
    STORY_TIDY_UP_EXCERPT_CHARS,
    STORY_TIDY_UP_OTHER_STORIES,
    UNDERSTANDING_EXCERPT_CHARS,
    UNDERSTANDING_STORY_CANDIDATES,
)
from ai_assistant.core.config import Settings
from ai_assistant.orchestration.story_calls import StoryCalls
from ai_assistant.orchestration.story_tidy_up import ScheduledTidyUp, StoryTidyUp

if TYPE_CHECKING:
    from pathlib import Path


def test_the_tidy_ups_values_are_this_lanes() -> None:
    assert STORY_TIDY_UP_EXCERPT_CHARS == UNDERSTANDING_EXCERPT_CHARS
    assert STORY_TIDY_UP_OTHER_STORIES == UNDERSTANDING_STORY_CANDIDATES
    assert timedelta(minutes=2) == STORY_TIDY_UP_BUDGET


async def test_planning_s_tidy_up_tidies_over_the_one_story_store_on_consolidations_route(
    tmp_path: Path,
) -> None:
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        assert not hasattr(engine, "_interim_tidy_up"), "the interim run is gone"
        assert engine._phases is not None
        calls = engine._phases._story_calls
        assert isinstance(calls, StoryCalls)
        tidy_up = calls._tidy_up
        assert isinstance(tidy_up, StoryTidyUp)
        # One story store and one memory store: the engine surface's and the loop's.
        assert tidy_up._stories is engine._stories
        assert tidy_up._memory is engine._memory
        # The route the deployment names for background work over its own records,
        # the one the matters pass rides too (ADR-0328 §14:4).
        assert engine._matters_pass is not None
        assert tidy_up._model is engine._matters_pass._model
        assert (tidy_up._excerpt_chars, tidy_up._other_stories, tidy_up._budget) == (
            STORY_TIDY_UP_EXCERPT_CHARS,
            STORY_TIDY_UP_OTHER_STORIES,
            STORY_TIDY_UP_BUDGET,
        )
        # ADR-0303 §5:7: the lookalike search keeps what recall would, at recall's
        # threshold for the embedder this deployment wires.
        assert tidy_up._threshold == RECALL_THRESHOLDS[Settings().embedder]
    finally:
        await engine.aclose()


def test_the_scheduled_tidy_ups_values_are_adr_0358_s_tunable_defaults() -> None:
    """ADR-0358 §4:3: initially 5 pending, 24 hours quiet and 10 stories a run."""
    assert SCHEDULED_TIDY_UP_THRESHOLD == 5
    assert timedelta(hours=24) == SCHEDULED_TIDY_UP_QUIET
    assert SCHEDULED_TIDY_UP_PER_RUN == 10


async def test_the_scheduled_tidy_up_runs_planning_s_one_tidy_up(tmp_path: Path) -> None:
    """ADR-0358 §4:5: the operation planning's call runs, so one run is on a story at a time.

    And its run is bounded by ``scheduler_run_budget``, as the matters pass's is (§4:3).
    """
    settings = Settings(scheduler_run_budget=timedelta(minutes=3))
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        scheduled = engine._scheduled_tidy_up
        assert isinstance(scheduled, ScheduledTidyUp)
        assert engine._phases is not None
        calls = engine._phases._story_calls
        assert calls is not None
        assert scheduled._tidy_up is calls._tidy_up
        assert scheduled._stories is engine._stories
        assert (scheduled._threshold, scheduled._quiet, scheduled._per_run) == (
            SCHEDULED_TIDY_UP_THRESHOLD,
            SCHEDULED_TIDY_UP_QUIET,
            SCHEDULED_TIDY_UP_PER_RUN,
        )
        assert scheduled._budget == timedelta(minutes=3)
    finally:
        await engine.aclose()
