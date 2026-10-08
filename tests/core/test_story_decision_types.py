"""The story types ADR-0302 adds or changes hold their own shapes (§§2-4, §7).

What names a flag (:class:`StoryFlagName`), the ``decided`` line's two fields on
:class:`StoryLogLine`, the ``flag`` a membership refusal names, and the activation or
note a ``not_held`` page refusal names. Each rule is a model validator, so a value
breaking it never reaches a store, a peer or the CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    StoryActor,
    StoryChange,
    StoryDecision,
    StoryFlag,
    StoryFlagKind,
    StoryFlagName,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryPageRefusal,
    StoryPageRefusalReason,
    StoryRefusal,
    StoryRefusalReason,
)

_AT = datetime(2026, 10, 8, tzinfo=UTC)
_TWO = StoryFlag(kind=StoryFlagKind.TWO_MATTERS)
_TIDY_UP = StoryFlagName(story="story:a", version=3, flag=_TWO)
_UNDERSTANDING = StoryFlagName(activation="a1")


def test_a_flag_is_named_by_its_version_or_by_its_activation() -> None:
    assert (_TIDY_UP.story, _TIDY_UP.version, _TIDY_UP.flag) == ("story:a", 3, _TWO)
    assert _TIDY_UP.activation is None
    assert _UNDERSTANDING.activation == "a1"
    assert (_UNDERSTANDING.story, _UNDERSTANDING.version, _UNDERSTANDING.flag) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"story": "story:a", "version": 3},
        {"story": "story:a", "flag": _TWO},
        {"version": 3, "flag": _TWO},
        {"activation": "a1", "story": "story:a"},
        {"activation": "a1", "version": 3},
        {"activation": "a1", "flag": _TWO},
        {"story": "story:a", "version": 0, "flag": _TWO},
        {"story": "story:a", "version": True, "flag": _TWO},
        {"activation": " "},
    ],
)
def test_a_flag_name_of_neither_shape_or_of_both_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StoryFlagName(**fields)


def test_flags_named_alike_are_one_and_a_later_version_is_another() -> None:
    assert StoryFlagName(story="story:a", version=3, flag=_TWO) == _TIDY_UP
    assert StoryFlagName(story="story:a", version=4, flag=_TWO) != _TIDY_UP


def _line(change: StoryChange, **fields: Any) -> StoryLogLine:
    base: dict[str, Any] = {
        "sequence": 1,
        "story_id": "story:a",
        "member": None,
        "other_story": None,
        "actor": StoryActor.MATTERS_PASS,
        "trigger": None,
        "at": _AT,
    }
    return StoryLogLine(change=change, **(base | fields))


def test_a_decided_line_names_the_flag_and_the_outcome() -> None:
    line = _line(StoryChange.DECIDED, answers=_TIDY_UP, outcome=StoryDecision.LEFT)
    assert (line.answers, line.outcome) == (_TIDY_UP, StoryDecision.LEFT)


@pytest.mark.parametrize(
    ("change", "fields"),
    [
        (StoryChange.DECIDED, {}),
        (StoryChange.DECIDED, {"answers": _TIDY_UP}),
        (StoryChange.DECIDED, {"outcome": StoryDecision.MERGED}),
        (
            StoryChange.DECIDED,
            {"answers": _TIDY_UP, "outcome": StoryDecision.LEFT, "trigger": "a1"},
        ),
        (
            StoryChange.DECIDED,
            {
                "answers": _TIDY_UP,
                "outcome": StoryDecision.LEFT,
                "member": StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1"),
            },
        ),
        (
            StoryChange.DECIDED,
            {"answers": _TIDY_UP, "outcome": StoryDecision.LEFT, "other_story": "story:b"},
        ),
        (StoryChange.CREATED, {"answers": _TIDY_UP, "outcome": StoryDecision.LEFT}),
        (StoryChange.CREATED, {"outcome": StoryDecision.LEFT}),
    ],
)
def test_a_line_names_a_flag_and_an_outcome_exactly_when_it_records_a_decision(
    change: StoryChange, fields: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        _line(change, **fields)


def test_a_line_from_before_the_decisions_still_validates() -> None:
    """The two fields default to absent, so no line written before them changes."""
    line = StoryLogLine.model_validate(
        {
            "sequence": 1,
            "story_id": "story:a",
            "change": "created",
            "member": None,
            "other_story": None,
            "actor": "owner",
            "trigger": None,
            "at": _AT,
        }
    )
    assert (line.answers, line.outcome) == (None, None)


@pytest.mark.parametrize(
    "reason", [StoryRefusalReason.UNKNOWN_FLAG, StoryRefusalReason.ALREADY_DECIDED]
)
def test_a_flag_refusal_names_the_flag_and_no_other_refusal_does(
    reason: StoryRefusalReason,
) -> None:
    assert StoryRefusal(reason=reason, flag=_UNDERSTANDING).flag == _UNDERSTANDING
    with pytest.raises(ValidationError):
        StoryRefusal(reason=reason)
    with pytest.raises(ValidationError):
        StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS, flag=_UNDERSTANDING)


def test_a_not_held_refusal_names_the_activation_or_the_note() -> None:
    by_activation = StoryPageRefusal(
        reason=StoryPageRefusalReason.NOT_HELD, story_id="story:a", activation="a1"
    )
    assert (by_activation.activation, by_activation.note) == ("a1", None)
    by_note = StoryPageRefusal(reason=StoryPageRefusalReason.NOT_HELD, story_id="story:a", note=4)
    assert (by_note.activation, by_note.note) == (None, 4)


@pytest.mark.parametrize(
    ("reason", "fields"),
    [
        (StoryPageRefusalReason.NOT_HELD, {}),
        (StoryPageRefusalReason.NOT_HELD, {"activation": "a1", "note": 4}),
        (StoryPageRefusalReason.UNKNOWN_NOTE, {"note": 4, "activation": "a1"}),
        (StoryPageRefusalReason.OVER_CAP, {"activation": "a1"}),
        (StoryPageRefusalReason.OVER_CAP, {"note": 4}),
    ],
)
def test_a_page_refusal_names_an_activation_only_on_not_held(
    reason: StoryPageRefusalReason, fields: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        StoryPageRefusal(reason=reason, story_id="story:a", **fields)
