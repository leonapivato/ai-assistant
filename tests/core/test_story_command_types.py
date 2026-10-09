"""ADR-0303 §10:2: the page as a reader is shown it, and the story commands' argument checks."""

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
    StoryPageViewNote,
    story_move_members,
    story_note_text,
)

_AT: Final = datetime(2026, 10, 8, tzinfo=UTC)
_STORY: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into=None)
_MERGED: Final = StoryHeader(story_id="story:a", created_at=_AT, merged_into="story:b")
_LINE: Final = StoryPageLine(text="A camping trip in October")
_NOTE: Final = StoryNote(
    note_id=2,
    text="Leaning against Saturday",
    author=StoryNoteAuthor.OWNER,
    written_during=None,
    outside=False,
    written_at=_AT,
)
_PLANNED: Final = StoryNote(
    note_id=5,
    text="The lower loop closes on the 15th",
    author=StoryNoteAuthor.PLANNING,
    written_during="a1",
    outside=True,
    written_at=_AT,
)


def _activation(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def test_a_page_never_tidied_carries_its_notes_and_no_page() -> None:
    """ADR-0303 §10:2: the notes, newest first, and the count beyond them."""
    view = StoryPageView(
        story=_STORY,
        notes=(StoryPageViewNote(note=_NOTE, pending=True),),
        more_notes=1,
    )
    assert view.version is None
    assert view.tidied_at is None
    assert (view.lines, view.outside, view.withheld) == ((), False, False)
    for page in ({"lines": (_LINE,)}, {"outside": True}, {"withheld": True}):
        with pytest.raises(ValidationError, match="never written shows no page"):
            StoryPageView.model_validate({"story": _STORY, **page})


def test_a_tidied_page_names_its_version_and_when_together() -> None:
    view = StoryPageView(story=_STORY, version=3, tidied_at=_AT, lines=(_LINE,), outside=True)
    assert (view.version, view.outside) == (3, True)
    assert StoryPageView(story=_STORY, version=3, tidied_at=_AT).lines == ()
    with pytest.raises(ValidationError, match="exactly when it says when"):
        StoryPageView(story=_STORY, version=3)
    with pytest.raises(ValidationError, match="exactly when it says when"):
        StoryPageView(story=_STORY, tidied_at=_AT)


@pytest.mark.parametrize("page", [{"lines": (_LINE,)}, {"outside": True}])
def test_a_withheld_page_carries_neither_its_lines_nor_its_mark(page: dict[str, object]) -> None:
    """ADR-0303 §3:7: none of it is shown, and the reader is told it was withheld."""
    assert StoryPageView(story=_STORY, version=3, tidied_at=_AT, withheld=True).withheld
    with pytest.raises(ValidationError, match="withheld page carries neither"):
        StoryPageView.model_validate(
            {"story": _STORY, "version": 3, "tidied_at": _AT, "withheld": True, **page}
        )


def test_the_notes_are_listed_newest_first_each_once() -> None:
    newer = StoryPageViewNote(note=_PLANNED, pending=False)
    older = StoryPageViewNote(note=_NOTE, pending=True)
    assert StoryPageView(story=_STORY, notes=(newer, older)).notes == (newer, older)
    for notes in ((older, newer), (older, older)):
        with pytest.raises(ValidationError, match="newest first"):
            StoryPageView(story=_STORY, notes=notes)


@pytest.mark.parametrize(
    "extra",
    [
        {"version": 1, "tidied_at": _AT},
        {"notes": (StoryPageViewNote(note=_NOTE, pending=True),)},
        {"more_notes": 1},
    ],
)
def test_a_merged_story_page_carries_its_header_alone(extra: dict[str, object]) -> None:
    assert StoryPageView(story=_MERGED).story.merged_into == "story:b"
    with pytest.raises(ValidationError, match="merged story's page view"):
        StoryPageView.model_validate({"story": _MERGED, **extra})


def test_the_count_beyond_the_notes_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        StoryPageView(story=_STORY, more_notes=-1)


def test_a_note_records_an_activation_exactly_when_the_user_did_not_write_it() -> None:
    """ADR-0303 §2:5, §3:1: and a note the user wrote is never marked."""
    for author, during, outside in (
        (StoryNoteAuthor.OWNER, "a1", False),
        (StoryNoteAuthor.PLANNING, None, False),
        (StoryNoteAuthor.OWNER, None, True),
    ):
        with pytest.raises(ValidationError):
            StoryNote(
                note_id=1,
                text="n",
                author=author,
                written_during=during,
                outside=outside,
                written_at=_AT,
            )


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
