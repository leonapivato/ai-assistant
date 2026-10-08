"""ADR-0300 §8:1: the shape of where a matter stands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    STORY_STANDING_RECENT,
    StoryEffectState,
    StoryHeader,
    StoryRelated,
    StoryRelation,
    StoryStanding,
    StoryStandingEarlier,
    StoryStandingEffect,
    StoryStandingEpisode,
)

_AT: Final = datetime(2026, 10, 1, tzinfo=UTC)
_STORY: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into=None)
_MERGED: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into="story:b")


def _moment(activation_id: str, at: datetime) -> StoryStandingEpisode:
    return StoryStandingEpisode(
        activation_id=activation_id, occurred_at=at, meaning=None, in_progress=False, outside=False
    )


def _full(newest: datetime) -> tuple[StoryStandingEpisode, ...]:
    return tuple(
        _moment(f"e{index}", newest - timedelta(hours=index))
        for index in range(STORY_STANDING_RECENT)
    )


def _effect(state: StoryEffectState) -> StoryStandingEffect:
    return StoryStandingEffect(activation_id="act", state=state, at=_AT)


def _related(relation: StoryRelation, story_id: str) -> StoryRelated:
    return StoryRelated(relation=relation, story_id=story_id, member_count=1)


def test_story_standing_empty_is_valid() -> None:
    standing = StoryStanding(story=_STORY)

    assert standing.done == ()
    assert standing.recent == ()
    assert standing.earlier is None
    assert standing.related == ()


def test_story_standing_merged_story_carries_nothing_else() -> None:
    assert StoryStanding(story=_MERGED).story.merged_into == "story:b"
    with pytest.raises(ValidationError, match="merged story's standing"):
        StoryStanding(story=_MERGED, recent=(_moment("e", _AT),))


def test_story_standing_done_is_listed_unknown_then_not_done_then_done() -> None:
    ordered = tuple(
        _effect(state)
        for state in (StoryEffectState.UNKNOWN, StoryEffectState.NOT_DONE, StoryEffectState.DONE)
    )
    assert StoryStanding(story=_STORY, done=ordered).done == ordered
    with pytest.raises(ValidationError, match="unknown first"):
        StoryStanding(story=_STORY, done=ordered[::-1])


def test_story_standing_recent_runs_most_recent_first() -> None:
    newer, older = _moment("b", _AT + timedelta(days=1)), _moment("a", _AT)
    assert StoryStanding(story=_STORY, recent=(newer, older)).recent == (newer, older)
    with pytest.raises(ValidationError, match="most recent first"):
        StoryStanding(story=_STORY, recent=(older, newer))


def test_story_standing_recent_is_bounded() -> None:
    recent = (*_full(_AT + timedelta(days=1)), _moment("extra", _AT - timedelta(days=1)))

    with pytest.raises(ValidationError):
        StoryStanding(story=_STORY, recent=recent)


def test_story_standing_earlier_only_once_recent_is_full_and_no_newer() -> None:
    newest = _AT + timedelta(days=5)
    recent = _full(newest)
    oldest_shown = recent[-1].occurred_at
    earlier = StoryStandingEarlier(episodes=2, first_at=_AT, last_at=oldest_shown)

    assert StoryStanding(story=_STORY, recent=recent, earlier=earlier).earlier == earlier
    with pytest.raises(ValidationError, match="only once the recent ones are full"):
        StoryStanding(story=_STORY, recent=recent[:-1], earlier=earlier)
    too_new = StoryStandingEarlier(episodes=1, first_at=_AT, last_at=newest)
    with pytest.raises(ValidationError, match="no newer than the oldest one shown"):
        StoryStanding(story=_STORY, recent=recent, earlier=too_new)


def test_story_standing_earlier_spans_forward() -> None:
    with pytest.raises(ValidationError, match="first instant is not after"):
        StoryStandingEarlier(episodes=2, first_at=_AT + timedelta(days=1), last_at=_AT)
    with pytest.raises(ValidationError):
        StoryStandingEarlier(episodes=0, first_at=_AT, last_at=_AT)


def test_story_standing_related_part_of_before_contains_each_once() -> None:
    part_of = _related(StoryRelation.PART_OF, "story:p")
    contains = _related(StoryRelation.CONTAINS, "story:c")

    assert StoryStanding(story=_STORY, related=(part_of, contains)).related == (part_of, contains)
    with pytest.raises(ValidationError, match="part of come before"):
        StoryStanding(story=_STORY, related=(contains, part_of))
    with pytest.raises(ValidationError, match="named once"):
        StoryStanding(story=_STORY, related=(part_of, part_of))
    with pytest.raises(ValidationError, match="named once"):
        StoryStanding(story=_STORY, related=(_related(StoryRelation.PART_OF, "story:a"),))


def test_story_standing_episode_marks_are_strict_booleans() -> None:
    with pytest.raises(ValidationError):
        StoryStandingEpisode.model_validate(
            {
                "activation_id": "a",
                "occurred_at": _AT,
                "meaning": None,
                "in_progress": 0,
                "outside": False,
            }
        )
