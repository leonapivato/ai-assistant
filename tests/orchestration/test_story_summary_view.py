"""The owner's summary view (ADR-0303 §10:2): its bound, its privacy, and one consistent read.

The story surface contract holds what every engine answers; this holds what it cannot
reach under its payload limit — the view lists the newest notes up to its bound and
counts the rest — what the owner is shown of a summary under ADR-0304 §4's minimum,
whatever stands behind it, and what only an interleaving shows: a note's pending status
is the one it had as the notes were read.
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
    StorySummaryDraft,
    StorySummaryLine,
    StorySummaryVersionName,
)
from ai_assistant.orchestration.stories import DEFAULT_STORY_SUMMARY_VIEW_NOTES, owner_summary
from ai_assistant.testing import FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.types import StoryNoteList, StorySummaryState


async def _story(stories: FakeStoryStore) -> str:
    created = await stories.create([activation("a-1")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    return created.story_id


async def test_the_view_lists_the_newest_notes_up_to_its_bound_and_counts_the_rest() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    written = []
    for index in range(4):
        outcome = await stories.append_note(story_id, f"note {index}", author=StoryNoteAuthor.OWNER)
        assert outcome.note is not None
        written.append(outcome.note)
    view = await owner_summary(stories, story_id, notes=2)
    assert view is not None
    assert [shown.note for shown in view.notes] == [written[3], written[2]]
    assert all(shown.pending for shown in view.notes)
    assert view.more_notes == 2


def test_the_default_bound_is_a_positive_constant() -> None:
    assert DEFAULT_STORY_SUMMARY_VIEW_NOTES > 0


# --- what the owner is shown of the summary (ADR-0303 §3:9, ADR-0304 §4) ------------


async def _written(
    stories: FakeStoryStore,
    story_id: str,
    *,
    episodes: tuple[str, ...] = (),
    read: tuple[StorySummaryVersionName, ...] = (),
    outside: bool = False,
) -> int:
    """Write a summary of one line taking in the pending notes and ``episodes``."""
    state = await stories.current_summary(story_id)
    assert state is not None
    written = await stories.write_summary(
        story_id,
        StorySummaryDraft(
            lines=(StorySummaryLine(text="A camping trip to Riverside."),),
            took_in_notes=tuple(note.note_id for note in state.pending_notes),
            took_in_episodes=episodes,
            read_pages=read,
            outside=outside,
        ),
        as_of=state.as_of,
    )
    assert written.version is not None, written
    return written.version.version


async def test_the_owner_is_shown_the_summary_and_every_note() -> None:
    """The owner may be shown every note (§3:9) and the summary (ADR-0304 §4:1)."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    await stories.append_note(story_id, "No Fridays", author=StoryNoteAuthor.OWNER)
    await _written(stories, story_id, episodes=("a-1",), outside=True)

    view = await owner_summary(stories, story_id)

    assert view is not None
    assert [line.text for line in view.lines] == ["A camping trip to Riverside."]
    assert (view.outside, view.withheld) == (True, False)


async def test_a_summary_an_earlier_version_took_in_a_forgotten_episode_is_shown() -> None:
    """ADR-0304 §4:3, §5: no episode a version took in withholds it, forgotten or not."""
    stories = FakeStoryStore(now=lambda: AT)
    created = await stories.create([activation("a-1"), activation("a-2")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    story_id = created.story_id
    await _written(stories, story_id, episodes=("a-1",))
    await stories.append_note(story_id, "No Fridays", author=StoryNoteAuthor.OWNER)
    version = await _written(stories, story_id, episodes=("a-2",), outside=True)

    # Neither episode is held anywhere: no memory store is read at all.
    view = await owner_summary(stories, story_id)

    assert view is not None
    assert (view.withheld, view.outside, view.version) == (False, True, version)
    assert [line.text for line in view.lines] == ["A camping trip to Riverside."]
    assert [shown.note.text for shown in view.notes] == ["No Fridays"]


async def test_a_summary_recorded_as_having_read_another_s_is_shown_whatever_that_rests_on() -> (
    None
):
    """ADR-0304 §3:4: a version written before keeps ``read_pages`` as history no rule reads."""
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    other = await stories.create([activation("b-1")], actor=StoryActor.OWNER)
    assert other.story_id is not None
    shown_for_a_flag = await _written(stories, other.story_id, episodes=("b-1",))
    await _written(
        stories,
        story_id,
        episodes=("a-1",),
        read=(StorySummaryVersionName(story=other.story_id, version=shown_for_a_flag),),
    )

    view = await owner_summary(stories, story_id)

    assert view is not None
    assert not view.withheld
    assert [line.text for line in view.lines] == ["A camping trip to Riverside."]


async def test_the_owner_s_view_reads_no_version_log() -> None:
    """ADR-0304 §4:3: whether the summary is shown is answered without reading any log.

    Nor is any episode looked up: the read takes no memory store to look one up in.
    """
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    await _written(stories, story_id, episodes=("a-1",))
    read: list[str] = []

    async def versions(*_: object, **__: object) -> None:
        read.append("summary_versions")

    stories.summary_versions = versions  # type: ignore[method-assign]  # recording the reads

    view = await owner_summary(stories, story_id)

    assert view is not None
    assert not view.withheld
    assert read == []


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

    view = await owner_summary(stories, story_id)

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
    state = await stories.current_summary(story_id)
    assert state is not None
    taken = await stories.write_summary(
        story_id,
        StorySummaryDraft(took_in_episodes=("a-1",), outside=False),
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

    view = await owner_summary(stories, story_id)

    assert view is not None
    assert view.notes == ()
    there = await owner_summary(stories, elsewhere)
    assert there is not None
    assert [(shown.note.note_id, shown.pending) for shown in there.notes] == [(moved[0], True)]


async def test_a_write_to_another_story_costs_a_read_again_and_no_wrong_answer() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    other = await _story(stories)
    _writing_while_notes_are_read(stories, other, times=1)
    reads = stories.current_summary
    count = 0

    async def counted(story_id: str) -> StorySummaryState | None:
        nonlocal count
        count += 1
        return await reads(story_id)

    stories.current_summary = counted  # type: ignore[method-assign]  # counting the reads

    view = await owner_summary(stories, story_id)

    assert view is not None
    assert view.notes == ()
    assert count == 4


async def test_a_story_written_through_every_read_is_a_store_error() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    story_id = await _story(stories)
    _writing_while_notes_are_read(stories, story_id, times=100)

    with pytest.raises(StoryStoreError, match="every time it was read"):
        await owner_summary(stories, story_id)
