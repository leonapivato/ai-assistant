"""The story types ADR-0304 §9 adds or changes hold their own shapes.

A line recording a carried note (:class:`StoryLogLine`'s ``note``, on
``note_moved_out`` and ``note_moved_in``) and the ``no_notes`` refusal. Each rule is a
model validator, so a value breaking it never reaches a store, a peer or the CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    StoryActor,
    StoryChange,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryRefusal,
    StoryRefusalReason,
)

_AT = datetime(2026, 10, 9, tzinfo=UTC)
_CARRIED = (StoryChange.NOTE_MOVED_OUT, StoryChange.NOTE_MOVED_IN)


def _line(change: StoryChange, **fields: Any) -> StoryLogLine:
    return StoryLogLine.model_validate(
        {
            "sequence": 4,
            "story_id": "story:a",
            "change": change,
            "member": None,
            "other_story": None,
            "actor": StoryActor.OWNER,
            "trigger": None,
            "at": _AT,
            **fields,
        }
    )


@pytest.mark.parametrize("change", _CARRIED)
def test_a_carried_note_line_names_the_note_and_the_other_story(change: StoryChange) -> None:
    line = _line(change, note=7, other_story="story:b", trigger="a1")
    assert (line.note, line.other_story, line.trigger) == (7, "story:b", "a1")
    assert line.member is None


@pytest.mark.parametrize("change", _CARRIED)
@pytest.mark.parametrize(
    "fields",
    [
        {"other_story": "story:b"},
        {"note": 7},
        {"note": 0, "other_story": "story:b"},
        {"note": True, "other_story": "story:b"},
        {"note": 2**63, "other_story": "story:b"},
        {
            "note": 7,
            "other_story": "story:b",
            "member": StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1"),
        },
    ],
)
def test_a_carried_note_line_without_a_note_or_the_other_story_is_refused(
    change: StoryChange, fields: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        _line(change, **fields)


@pytest.mark.parametrize(
    ("change", "fields"),
    [
        (StoryChange.CREATED, {}),
        (StoryChange.ADDED, {"member": StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1")}),
        (StoryChange.SPLIT_OFF, {"other_story": "story:b"}),
        (StoryChange.MERGED_INTO, {"other_story": "story:b"}),
        (StoryChange.ABSORBED, {"other_story": "story:b"}),
    ],
)
def test_only_a_carried_note_line_names_a_note(change: StoryChange, fields: dict[str, Any]) -> None:
    """§9:7: present exactly on those lines; a line written before has none, unchanged."""
    assert _line(change, **fields).note is None
    with pytest.raises(ValidationError, match="names a note"):
        _line(change, note=7, **fields)


def test_a_no_notes_refusal_names_the_story_moved_from() -> None:
    refusal = StoryRefusal(reason=StoryRefusalReason.NO_NOTES, story_id="story:a")
    assert refusal.story_id == "story:a"
    with pytest.raises(ValidationError, match="no_notes"):
        StoryRefusal(reason=StoryRefusalReason.NO_NOTES)
