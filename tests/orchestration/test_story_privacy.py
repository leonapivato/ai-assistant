"""ADR-0300 §11:1's privacy default, decided from identities alone."""

from __future__ import annotations

from typing import Any, Final

from story_support import AT, episode

from ai_assistant.core.types import StoryNote, StoryNoteAuthor, StoryPageLine
from ai_assistant.orchestration.story_privacy import PageVisibility, activation_of


def _note(note_id: int, **fields: Any) -> StoryNote:
    values: dict[str, Any] = {
        "note_id": note_id,
        "text": "a note",
        "author": StoryNoteAuthor.PLANNING,
        "rests_on": "a-1",
        "outside": False,
        "written_at": AT,
    }
    return StoryNote.model_validate(values | fields)


_SHOWN: Final = _note(1)
_HIDDEN: Final = _note(2, rests_on="a-2")
_OWNER: Final = _note(3, author=StoryNoteAuthor.OWNER, rests_on=None)
_NOTES: Final = {note.note_id: note for note in (_SHOWN, _HIDDEN, _OWNER)}


def _line(*cites: int) -> StoryPageLine:
    return StoryPageLine(text="a line", cites=cites, outside=False)


def test_a_note_is_shown_where_its_episode_may_be() -> None:
    visibility = PageVisibility.of([episode("a-1")], owner_notes=False)

    assert visibility.note(_SHOWN)
    assert not visibility.note(_HIDDEN)


def test_a_note_the_user_wrote_is_shown_where_an_owner_record_may_be() -> None:
    assert PageVisibility.of([], owner_notes=True).note(_OWNER)
    assert not PageVisibility.of([], owner_notes=False).note(_OWNER)


def test_a_line_is_shown_only_where_every_note_it_cites_may_be() -> None:
    visibility = PageVisibility.of([episode("a-1")], owner_notes=True)

    assert visibility.line(_line(1, 3), _NOTES)
    assert not visibility.line(_line(1, 2), _NOTES)
    # A citation nobody handed in is undecidable, and withheld.
    assert not visibility.line(_line(1, 9), _NOTES)


def test_an_episode_recording_no_activation_contributes_nothing() -> None:
    legacy = episode("a-1").model_copy(update={"processing_record": None})

    assert activation_of(legacy) is None
    assert PageVisibility.of([legacy], owner_notes=False).activations == frozenset()
    assert activation_of(episode("a-1")) == "a-1"
