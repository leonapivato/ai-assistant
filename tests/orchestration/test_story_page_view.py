"""The owner's page view's bound on its notes (ADR-0303 §10:2).

The story surface contract holds what every engine answers; this holds the one thing
it cannot reach under its payload limit: the view lists the newest notes up to its
bound and counts the rest.
"""

from __future__ import annotations

from story_support import AT, activation

from ai_assistant.core.types import StoryActor, StoryNoteAuthor
from ai_assistant.orchestration.stories import STORY_PAGE_VIEW_NOTES, owner_page
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore


async def test_the_view_lists_the_newest_notes_up_to_its_bound_and_counts_the_rest() -> None:
    stories = FakeStoryStore(now=lambda: AT)
    created = await stories.create([activation("a-1")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    written = []
    for index in range(4):
        outcome = await stories.append_note(
            created.story_id, f"note {index}", author=StoryNoteAuthor.OWNER
        )
        assert outcome.note is not None
        written.append(outcome.note)
    view = await owner_page(stories, FakeMemoryStore(now=lambda: AT), created.story_id, notes=2)
    assert view is not None
    assert [shown.note for shown in view.notes] == [written[3], written[2]]
    assert all(shown.pending for shown in view.notes)
    assert view.more_notes == 2


def test_the_bound_is_a_positive_constant() -> None:
    assert STORY_PAGE_VIEW_NOTES > 0
