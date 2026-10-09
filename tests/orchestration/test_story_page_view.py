"""The owner's page view (ADR-0303 §10:2): its bound on its notes, and one consistent read.

The story surface contract holds what every engine answers; this holds what it cannot
reach under its payload limit — the view lists the newest notes up to its bound and
counts the rest — and what only an interleaving shows: a note's pending status is the
one it had as the notes were read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from story_support import AT, activation

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    StoryActor,
    StoryNoteAuthor,
    StoryPageDraft,
)
from ai_assistant.orchestration.stories import STORY_PAGE_VIEW_NOTES, owner_page
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.types import StoryNoteList, StoryPageState


async def _story(stories: FakeStoryStore) -> str:
    created = await stories.create([activation("a-1")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    return created.story_id


def _memory() -> FakeMemoryStore:
    return FakeMemoryStore(now=lambda: AT)


async def test_the_view_lists_the_newest_notes_up_to_its_bound_and_counts_the_rest() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    written = []
    for index in range(4):
        outcome = await stories.append_note(story_id, f"note {index}", author=StoryNoteAuthor.OWNER)
        assert outcome.note is not None
        written.append(outcome.note)
    view = await owner_page(stories, _memory(), story_id, notes=2)
    assert view is not None
    assert [shown.note for shown in view.notes] == [written[3], written[2]]
    assert all(shown.pending for shown in view.notes)
    assert view.more_notes == 2


def test_the_bound_is_a_positive_constant() -> None:
    assert STORY_PAGE_VIEW_NOTES > 0


def _writing_while_notes_are_read(
    stories: FakeStoryStore, writing_to: str, *, times: int
) -> list[int]:
    """``stories.notes`` appending a note to ``writing_to`` before each of its first reads."""
    listing = stories.notes
    appended: list[int] = []

    async def appending(
        story_id: str, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryNoteList | None:
        if len(appended) < times:
            outcome = await stories.append_note(
                writing_to, f"late {len(appended)}", author=StoryNoteAuthor.OWNER
            )
            assert outcome.note is not None
            appended.append(outcome.note.note_id)
        return await listing(story_id, cursor=cursor, limit=limit)

    stories.notes = appending  # type: ignore[method-assign]  # an interleaving point
    return appended


async def test_a_note_written_while_the_notes_are_read_is_shown_pending() -> None:
    """The reads that disagree are read again, so no note is shown taken in that is not."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    appended = _writing_while_notes_are_read(stories, story_id, times=1)

    view = await owner_page(stories, _memory(), story_id)

    assert view is not None
    assert [(shown.note.note_id, shown.pending) for shown in view.notes] == [(appended[0], True)]


async def test_a_note_written_and_moved_away_while_the_notes_are_read_is_not_shown() -> None:
    """Appended, listed, then moved with its member before the second read (round 2's case).

    The story's own state is as it was, but the store's counter is not, so the reads are
    made again, and the note, no longer the story's, is not shown taken in.
    """
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    elsewhere = await _story(stories)
    state = await stories.current_page(story_id)
    assert state is not None
    taken = await stories.write_page(
        story_id,
        StoryPageDraft(took_in_episodes=("a-1",), outside=False),
        as_of=state.as_of,
    )
    assert taken.version is not None
    listing = stories.notes
    moved: list[int] = []

    async def appending_then_moving(
        story_id: str, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryNoteList | None:
        if moved:
            return await listing(story_id, cursor=cursor, limit=limit)
        late = await stories.append_note(story_id, "late", author=StoryNoteAuthor.OWNER)
        assert late.note is not None
        moved.append(late.note.note_id)
        listed = await listing(story_id, cursor=cursor, limit=limit)
        away = await stories.move(
            story_id, elsewhere, [activation("a-1")], actor=StoryActor.OWNER, notes=moved
        )
        assert away.refusal is None
        return listed

    stories.notes = appending_then_moving  # type: ignore[method-assign]  # an interleaving point

    view = await owner_page(stories, _memory(), story_id)

    assert view is not None
    assert view.notes == ()
    there = await owner_page(stories, _memory(), elsewhere)
    assert there is not None
    assert [(shown.note.note_id, shown.pending) for shown in there.notes] == [(moved[0], True)]


async def test_a_write_to_another_story_costs_a_read_again_and_no_wrong_answer() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    other = await _story(stories)
    _writing_while_notes_are_read(stories, other, times=1)
    reads = stories.current_page
    count = 0

    async def counted(story_id: str) -> StoryPageState | None:
        nonlocal count
        count += 1
        return await reads(story_id)

    stories.current_page = counted  # type: ignore[method-assign]  # counting the reads

    view = await owner_page(stories, _memory(), story_id)

    assert view is not None
    assert view.notes == ()
    assert count == 4


async def test_a_story_written_through_every_read_is_a_store_error() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    _writing_while_notes_are_read(stories, story_id, times=100)

    with pytest.raises(StoryStoreError, match="every time it was read"):
        await owner_page(stories, _memory(), story_id)
