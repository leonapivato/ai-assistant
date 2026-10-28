"""The observer's reply shapes: closed, restated, and today's types (ADR-0354 §9:1, §9:7).

Each step's shape passes the seam's check (§2:3), its six open values restated as the named
properties its prompt describes, and each is a subclass of the type its reader reads, so a
value goes to that reader as it is and the reader runs the checks it runs today.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from observer_support import read_as

from ai_assistant.core.reply_shapes import reply_schema
from ai_assistant.core.types import ProfileField
from ai_assistant.orchestration.observer import replies
from ai_assistant.orchestration.observer.framing import FramingReply
from ai_assistant.orchestration.observer.placement import PlacementReply
from ai_assistant.orchestration.observer.replies import (
    FramingReplyShape,
    PersonScoutReplyShape,
    PlacementReplyShape,
    ScoutReplyShape,
)
from ai_assistant.orchestration.observer.scout import PersonScoutReply, ScoutReply

_SHAPES = (
    (ScoutReplyShape, ScoutReply),
    (PersonScoutReplyShape, PersonScoutReply),
    (FramingReplyShape, FramingReply),
    (PlacementReplyShape, PlacementReply),
)


def _property(shape: type[Any], *path: str) -> dict[str, Any]:
    """The schema at ``path``: a definition's name, then a property's, each in turn."""
    schema = reply_schema(shape)
    held: dict[str, Any] = schema
    for step in path:
        if step.startswith("#"):
            held = cast("dict[str, Any]", schema["$defs"])[step[1:]]
        else:
            held = cast("dict[str, Any]", held["properties"])[step]
    return held


def _object(names: set[str]) -> dict[str, Any]:
    """What a restated object is matched by: its type, its closure and its names."""
    return {"type": "object", "additionalProperties": False, "names": names}


def _shape_of(schema: dict[str, Any]) -> Any:
    """``schema`` as a comparable outline: objects by their names, the rest as written."""
    if schema.get("type") == "object":
        return {
            "type": "object",
            "additionalProperties": schema["additionalProperties"],
            "names": set(schema["properties"]),
        }
    if "anyOf" in schema:
        return [_shape_of(one) for one in schema["anyOf"]]
    if schema.get("type") == "array":
        return ["array", _shape_of(schema["items"])]
    return {key: value for key, value in schema.items() if key != "default"}


@pytest.mark.parametrize(("shape", "today"), _SHAPES)
def test_each_shape_passes_the_seams_check_and_is_todays_type(
    shape: type[Any], today: type[Any]
) -> None:
    """ADR-0354 §2:3, §9:7: closed at every depth, and read by today's reader."""
    reply_schema(shape)  # raises where any position is open

    assert issubclass(shape, today)
    assert set(shape.model_fields) == set(today.model_fields)


def test_the_scouts_narrowing_restates_the_prompts_object() -> None:
    """``{"reach", "note"}`` or null (ADR-0346 §4:2)."""
    narrowing = _property(ScoutReplyShape, "#_ScoutFinding", "narrowing")

    assert _shape_of(narrowing) == [_object({"reach", "note"}), {"type": "null"}]


def test_the_person_scouts_restates_and_suggestions_restate_the_prompts_objects() -> None:
    """ADR-0338 §9:2-§9:3: a setting or null, and a list of suggestions or null."""
    finding = "#_PersonScoutFinding"
    restates = _property(PersonScoutReplyShape, finding, "restates")
    suggestions = _property(PersonScoutReplyShape, "suggestions")

    assert _shape_of(restates) == [_object({"field", "value"}), {"type": "null"}]
    assert _shape_of(suggestions) == [
        ["array", _object({"field", "value", "part"})],
        {"type": "null"},
    ]
    assert _shape_of(_property(PersonScoutReplyShape, finding, "narrowing")) == [
        _object({"reach", "note"}),
        {"type": "null"},
    ]
    (setting, _null) = restates["anyOf"]
    assert setting["properties"]["field"]["enum"] == [one.value for one in ProfileField]


def test_framings_style_and_pin_restate_the_prompts_booleans() -> None:
    """ADR-0338 §9:4-§9:5: true, false or null."""
    for name in ("style", "pin"):
        held = _property(FramingReplyShape, "#_FramedMemoryShape", name)
        assert _shape_of(held) == [{"type": "boolean"}, {"type": "null"}]


def test_placements_answers_restate_the_prompts_object() -> None:
    """ADR-0346 §6:2: one memory and its question, or null."""
    answers = _property(PlacementReplyShape, "answers")

    assert _shape_of(answers) == [_object({"memory", "question"}), {"type": "null"}]


def test_a_restated_field_holds_what_the_reply_wrote_for_todays_reader() -> None:
    """ADR-0354 §9:7: the readers read what they read today, malformed entries included.

    A model writing outside the schema, as one in prompted mode may, is read as before:
    a narrowing that is no object still narrows, failing closed (ADR-0217 §4); a list of
    answers is set aside entry by entry by placement's reader (#3398); a malformed
    suggestion is dropped alone by the scout's.
    """
    scout = read_as(json.dumps({"findings": [{"claim": "x", "narrowing": True}]}), ScoutReplyShape)
    person = read_as(
        json.dumps({"findings": [], "suggestions": [{"field": "name"}, 7]}),
        PersonScoutReplyShape,
    )
    placement = read_as(
        json.dumps(
            {
                "relations": [{"memory": "M1", "relation": "independent"}],
                "answers": [{"memory": "M1", "question": "Q1"}, "Q2"],
            }
        ),
        PlacementReplyShape,
    )
    framing = read_as(
        json.dumps({"memories": [{"wording": "x", "style": "yes", "pin": True}]}),
        FramingReplyShape,
    )

    assert scout is not None
    assert scout.findings[0].narrowing is True
    assert person is not None
    assert person.suggestions == [{"field": "name"}, 7]
    assert placement is not None
    assert placement.answers == [{"memory": "M1", "question": "Q1"}, "Q2"]
    assert framing is not None
    assert (framing.memories[0].style, framing.memories[0].pin) == ("yes", True)


def test_the_text_json_reader_is_gone() -> None:
    """ADR-0354 §10:1: ``replies.parsed`` and its candidate walk are removed."""
    for name in ("parsed", "_candidates", "_names_a_field", "_balanced_end", "_past_string"):
        assert not hasattr(replies, name)
