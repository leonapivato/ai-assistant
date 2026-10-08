"""ADR-0300 §8:3: the page as a reader is shown it, and the story commands' argument checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    STORY_NOTE_MAX_CHARS,
    StoryHeader,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StoryPageLine,
    StoryPageView,
    story_move_members,
    story_note_text,
)

_AT: Final = datetime(2026, 10, 8, tzinfo=UTC)
_STORY: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into=None)
_MERGED: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into="story:b")
_LINE: Final = StoryPageLine(text="A camping trip in October", cites=(1,), outside=False)
_NOTE: Final = StoryNote(
    note_id=2,
    text="Leaning against Saturday",
    author=StoryNoteAuthor.OWNER,
    rests_on=None,
    outside=False,
    written_at=_AT,
)


def _activation(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def test_a_page_never_tidied_carries_what_is_pending_and_no_line() -> None:
    view = StoryPageView(story=_STORY, pending_notes=(_NOTE,), pending_episodes=("a1",))
    assert view.version is None
    assert view.tidied_at is None
    assert view.lines == ()
    with pytest.raises(ValidationError, match="never written shows no line"):
        StoryPageView(story=_STORY, lines=(_LINE,))
    with pytest.raises(ValidationError, match="never written shows no line"):
        StoryPageView(story=_STORY, withheld_lines=1)


def test_a_tidied_page_names_its_version_and_when_together() -> None:
    view = StoryPageView(story=_STORY, version=3, tidied_at=_AT, lines=(_LINE,), withheld_lines=1)
    assert view.version == 3
    with pytest.raises(ValidationError, match="exactly when it says when"):
        StoryPageView(story=_STORY, version=3)
    with pytest.raises(ValidationError, match="exactly when it says when"):
        StoryPageView(story=_STORY, tidied_at=_AT)


@pytest.mark.parametrize(
    "extra",
    [
        {"version": 1, "tidied_at": _AT},
        {"pending_notes": (_NOTE,)},
        {"pending_episodes": ("a1",)},
        {"withheld_notes": 1},
    ],
)
def test_a_merged_story_page_carries_its_header_alone(extra: dict[str, object]) -> None:
    assert StoryPageView(story=_MERGED).story.merged_into == "story:b"
    with pytest.raises(ValidationError, match="merged story's page view"):
        StoryPageView.model_validate({"story": _MERGED, **extra})


def test_the_withheld_counts_are_never_negative() -> None:
    with pytest.raises(ValidationError):
        StoryPageView(story=_STORY, withheld_notes=-1)


def test_a_note_text_is_checked_as_the_store_checks_it() -> None:
    assert story_note_text("  Waiting on the campground  ") == "  Waiting on the campground  "
    assert story_note_text("x" * STORY_NOTE_MAX_CHARS) == "x" * STORY_NOTE_MAX_CHARS
    for bad in ("", "   ", "x" * (STORY_NOTE_MAX_CHARS + 1), "lone \ud800 surrogate"):
        with pytest.raises(ValueError, match="note's text must be non-blank"):
            story_note_text(bad)
    with pytest.raises(ValueError, match="must be a string"):
        story_note_text(7)


def test_a_move_is_between_two_stories_and_carries_activations_only() -> None:
    members = [_activation("a1"), _activation("a2")]
    assert story_move_members("story:a", "story:b", members) == tuple(members)
    assert story_move_members("story:a", "story:b", []) == ()
    with pytest.raises(ValueError, match="from one story to another"):
        story_move_members("story:a", "story:a", members)
    with pytest.raises(ValueError, match="activation members only"):
        story_move_members(
            "story:a", "story:b", [StoryMember(kind=StoryMemberKind.STORY, id="story:c")]
        )
    with pytest.raises(ValueError, match="StoryMember"):
        story_move_members("story:a", "story:b", ["a1"])
