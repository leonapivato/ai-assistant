"""ADR-0303 §3's privacy default, decided from identities alone."""

from __future__ import annotations

from typing import Any, Final

from story_support import AT, episode

from ai_assistant.core.types import StoryNote, StoryNoteAuthor
from ai_assistant.orchestration.story_privacy import PageVisibility, activation_of


def _note(note_id: int, **fields: Any) -> StoryNote:
    values: dict[str, Any] = {
        "note_id": note_id,
        "text": "a note",
        "author": StoryNoteAuthor.PLANNING,
        "written_during": "a-1",
        "outside": False,
        "written_at": AT,
    }
    return StoryNote.model_validate(values | fields)


_PLANNED: Final = _note(1)
_OWNER: Final = _note(3, author=StoryNoteAuthor.OWNER, written_during=None)


def test_a_note_is_shown_where_an_owner_record_may_be_whoever_wrote_it() -> None:
    """§3:6: the activation it was written during decides nothing (§2:4)."""
    episodes = [episode("a-1")]
    for note in (_PLANNED, _OWNER):
        assert PageVisibility.of(episodes, owner_notes=True).note(note)
        assert not PageVisibility.of(episodes, owner_notes=False).note(note)


def test_the_page_is_shown_where_an_owner_record_may_be_until_its_lane() -> None:
    """The interim rule ADR-0303 §12:3's lane replaces with §3:7's walk."""
    assert PageVisibility.of([], owner_notes=True).page()
    assert not PageVisibility.of([episode("a-1")], owner_notes=False).page()


def test_an_episode_recording_no_activation_contributes_nothing() -> None:
    legacy = episode("a-1").model_copy(update={"processing_record": None})

    assert activation_of(legacy) is None
    assert PageVisibility.of([legacy], owner_notes=False).activations == frozenset()
    assert activation_of(episode("a-1")) == "a-1"
