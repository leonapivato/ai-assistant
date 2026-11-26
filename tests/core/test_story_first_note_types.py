"""ADR-0388 §3:3: a story's first note, the value ``StoryStore.create`` takes for each.

``StoryFirstNote`` carries exactly what ``append_note`` takes beside the story, with its
defaults, each field as ``StoryNote`` holds it; it is frozen. That nothing writes a note
as ``tidy_up`` is the store's admission rule, and the shared ``StoryStore`` suite holds it.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from ai_assistant.core.protocols import StoryStore
from ai_assistant.core.types import STORY_NOTE_MAX_CHARS, StoryFirstNote, StoryNoteAuthor


def test_it_carries_exactly_what_append_note_takes_beside_the_story() -> None:
    """The fields are ``append_note``'s parameters but the story, with its defaults."""
    parameters = dict(inspect.signature(StoryStore.append_note).parameters)
    del parameters["self"], parameters["story_id"]
    assert list(StoryFirstNote.model_fields) == list(parameters)
    for name, parameter in parameters.items():
        field = StoryFirstNote.model_fields[name]
        if parameter.default is inspect.Parameter.empty:
            assert field.is_required(), name
        else:
            assert field.default == parameter.default, name


def test_its_defaults_are_append_notes_so_a_planning_note_names_its_activation() -> None:
    note = StoryFirstNote(text="Booked.", author=StoryNoteAuthor.OWNER)
    assert note.written_during is None
    assert note.outside is False
    with pytest.raises(ValidationError):
        StoryFirstNote(text="Booked.", author=StoryNoteAuthor.PLANNING)


@pytest.mark.parametrize(
    "fields",
    [
        {"text": "", "author": "planning", "written_during": "a1"},
        {"text": "   ", "author": "planning", "written_during": "a1"},
        {"text": "x" * (STORY_NOTE_MAX_CHARS + 1), "author": "planning", "written_during": "a1"},
        {"text": "Note.", "author": "owner", "written_during": "a1"},
        {"text": "Note.", "author": "owner", "outside": True},
        {"text": "Note.", "author": "planning", "written_during": "a1", "outside": 1},
        {"text": "Note.", "author": "someone", "written_during": "a1"},
        {"text": "Note.", "author": "planning", "written_during": "a1", "extra": 1},
    ],
    ids=[
        "empty",
        "blank",
        "over-the-cap",
        "owner-with-an-activation",
        "owner-marked-outside",
        "a-mark-that-is-no-bool",
        "an-author-no-one-is",
        "an-unknown-field",
    ],
)
def test_a_note_its_fields_or_its_author_do_not_admit_is_refused(fields: dict[str, object]) -> None:
    """Each field as ``StoryNote`` holds it (ADR-0303 §2:5, §3:1)."""
    with pytest.raises(ValidationError):
        StoryFirstNote.model_validate(fields)


def test_it_is_frozen_and_round_trips_through_its_json() -> None:
    note = StoryFirstNote(
        text="Asked about the trip.",
        author=StoryNoteAuthor.PLANNING,
        written_during="a1",
        outside=True,
    )
    with pytest.raises(ValidationError):
        note.text = "Changed."
    assert StoryFirstNote.model_validate_json(note.model_dump_json()) == note


def test_a_tidy_up_note_is_a_value_the_store_refuses_and_not_the_model() -> None:
    """The model admits the author; ``create`` refuses it, as ``append_note`` does."""
    note = StoryFirstNote(text="Note.", author=StoryNoteAuthor.TIDY_UP, written_during="a1")
    assert note.author is StoryNoteAuthor.TIDY_UP
