"""Counting the keys a reply carried that its shape does not name (#3246)."""

from __future__ import annotations

import json
from typing import Annotated, Literal

import pytest
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, TypeAdapter

from ai_assistant.orchestration.reply_keys import stray_keys


class _Item(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    text: str
    source: str = Field(default="", alias="from")


class _Reply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    items: tuple[_Item, ...] = ()
    lead: _Item | None = None
    words: tuple[str, ...] = ()


class _Left(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    kind: Literal["left"]
    side: str


class _Right(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    kind: Literal["right"]
    reach: int


_EITHER: TypeAdapter[_Left | _Right] = TypeAdapter(
    Annotated[_Left | _Right, Field(discriminator="kind")]
)


def _counted(value: object) -> int:
    text = json.dumps(value)
    return stray_keys(text, _Reply.model_validate_json(text))


@pytest.mark.parametrize(
    ("value", "stray"),
    [
        ({}, 0),
        ({"items": [{"text": "a", "from": "D1"}], "words": ["x"]}, 0),
        ({"note": "x"}, 1),
        ({"note": "x", "command": None}, 2),
        ({"items": [{"text": "a", "why": "x"}, {"text": "b", "why": "y", "how": 1}]}, 3),
        ({"lead": {"text": "a", "why": "x"}}, 1),
        ({"lead": None, "note": "x"}, 1),
        # A dropped key is one, whatever it holds.
        ({"note": {"why": "x", "how": [{"a": 1}]}}, 1),
        # A field read under its alias is not read by its name.
        ({"items": [{"text": "a", "source": "D1"}]}, 1),
        # Strings in a sequence are not shapes: nothing in them is a key.
        ({"words": ["note", "why"]}, 0),
    ],
)
def test_the_keys_a_shape_does_not_name_are_counted(value: object, stray: int) -> None:
    assert _counted(value) == stray


def test_a_union_is_walked_by_the_member_validation_chose() -> None:
    text = json.dumps({"kind": "right", "reach": 3, "side": "x", "why": "y"})
    # ``side`` is a field of the other member, not of the one chosen: it is stray here.
    assert stray_keys(text, _EITHER.validate_json(text)) == 2


def test_a_shape_reading_fields_by_name_counts_neither_spelling() -> None:
    class _ByName(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore", validate_by_name=True)
        source: str = Field(alias="from")

    for value in ({"from": "x"}, {"source": "x"}):
        text = json.dumps(value)
        assert stray_keys(text, _ByName.model_validate_json(text)) == 0


def test_a_choice_of_aliases_is_refused_rather_than_walked_wrongly() -> None:
    class _Choice(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")
        source: str = Field(validation_alias=AliasChoices("from", "source"))

    text = json.dumps({"from": "x"})
    with pytest.raises(TypeError, match="does not follow"):
        stray_keys(text, _Choice.model_validate_json(text))
