"""The owner's page view (ADR-0303 §10:2): its bound, its privacy, and one consistent read.

The story surface contract holds what every engine answers; this holds what it cannot
reach under its payload limit — the view lists the newest notes up to its bound and
counts the rest — what the owner is shown of a page under §3's default, walked over
everything behind it, and what only an interleaving shows: a note's pending status is
the one it had as the notes were read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from story_support import AT, activation, episode, memory_of

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    StoryActor,
    StoryNoteAuthor,
    StoryPageDraft,
    StoryPageLine,
    StoryPageVersionName,
)
from ai_assistant.orchestration.stories import DEFAULT_STORY_PAGE_VIEW_NOTES, owner_page
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


def test_the_default_bound_is_a_positive_constant() -> None:
    assert DEFAULT_STORY_PAGE_VIEW_NOTES > 0


# --- what the owner is shown of the page (ADR-0303 §3:9-§3:12) ----------------------


async def _written(
    stories: FakeStoryStore,
    story_id: str,
    *,
    episodes: tuple[str, ...] = (),
    read: tuple[StoryPageVersionName, ...] = (),
    outside: bool = False,
) -> int:
    """Write a page of one line taking in the pending notes and ``episodes``."""
    state = await stories.current_page(story_id)
    assert state is not None
    written = await stories.write_page(
        story_id,
        StoryPageDraft(
            lines=(StoryPageLine(text="A camping trip to Riverside."),),
            took_in_notes=tuple(note.note_id for note in state.pending_notes),
            took_in_episodes=episodes,
            read_pages=read,
            outside=outside,
        ),
        as_of=state.as_of,
    )
    assert written.version is not None, written
    return written.version.version


async def test_the_owner_is_shown_a_page_whose_episodes_and_notes_are_all_held() -> None:
    """The owner may be shown every note (§3:9) and every record the store holds."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    await stories.append_note(story_id, "No Fridays", author=StoryNoteAuthor.OWNER)
    await _written(stories, story_id, episodes=("a-1",), outside=True)

    view = await owner_page(stories, await memory_of(episode("a-1")), story_id)

    assert view is not None
    assert [line.text for line in view.lines] == ["A camping trip to Riverside."]
    assert (view.outside, view.withheld) == (True, False)


async def test_a_page_an_earlier_version_took_in_a_forgotten_episode_is_withheld() -> None:
    """§3:12: forgotten, it cannot be established, and the walk is cumulative (§3:10)."""
    stories = FakeStoryStore(now=lambda: AT)
    created = await stories.create([activation("a-1"), activation("a-2")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    story_id = created.story_id
    await _written(stories, story_id, episodes=("a-1",))
    await stories.append_note(story_id, "No Fridays", author=StoryNoteAuthor.OWNER)
    version = await _written(stories, story_id, episodes=("a-2",), outside=True)

    view = await owner_page(stories, await memory_of(episode("a-2")), story_id)

    assert view is not None
    # What a withheld page carries: that it was withheld, when it was tidied, its
    # version, and the notes, which §3:9 decides on their own; never a line or the mark.
    assert (view.withheld, view.lines, view.outside) == (True, (), False)
    assert view.version == version
    assert [shown.note.text for shown in view.notes] == ["No Fridays"]


async def test_a_page_that_read_a_page_resting_on_a_forgotten_episode_is_withheld() -> None:
    """§3:10: through each other story's page a run was shown, everything behind it."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    other = await stories.create([activation("b-1")], actor=StoryActor.OWNER)
    assert other.story_id is not None
    shown_for_a_flag = await _written(stories, other.story_id, episodes=("b-1",))
    await _written(
        stories,
        story_id,
        episodes=("a-1",),
        read=(StoryPageVersionName(story=other.story_id, version=shown_for_a_flag),),
    )

    kept = await owner_page(stories, await memory_of(episode("a-1"), episode("b-1")), story_id)
    forgotten = await owner_page(stories, await memory_of(episode("a-1")), story_id)

    assert kept is not None
    assert not kept.withheld
    assert forgotten is not None
    assert forgotten.withheld


async def test_the_owner_may_be_shown_a_page_behind_which_an_episode_is_still_open() -> None:
    """The owner's direct inspection reads every record, an open one included."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    await _written(stories, story_id, episodes=("a-1",))

    view = await owner_page(stories, await memory_of(episode("a-1", open_=True)), story_id)

    assert view is not None
    assert not view.withheld


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
