"""A shape's schema, its version and the reading rule (ADR-0354 §3:2 to §3:4)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from ai_assistant.core.errors import ModelError
from ai_assistant.core.reply_shapes import (
    read_reply,
    reply_schema,
    reply_shape_version,
    schema_version,
    unfenced,
)
from ai_assistant.core.types import ReplyFailure


class _Leaf(BaseModel):
    """A leaf. Its docstring is text the schema never carries."""

    name: str = Field(description="Its name.", examples=["oak"])


class _Tree(BaseModel):
    """A tree, with text and objects at every depth."""

    model_config = ConfigDict(title="A titled tree")

    root: _Leaf = Field(description="Where it starts.")
    leaves: list[_Leaf] = Field(description="What hangs off it.")
    crown: _Leaf | None = Field(default=None, title="The top")
    tags: tuple[str, ...] = ()


class _Named(BaseModel):
    """Properties named after the text keywords keep their names."""

    title: str
    description: str
    examples: list[str]


class _Simple(BaseModel):
    answer: str
    confidence: int


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")

    answer: str


class _Forbidding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class _A(BaseModel):
    kind: Literal["a"]
    a: int


class _B(BaseModel):
    kind: Literal["b"]
    b: str


class _Decision(BaseModel):
    """One of several kinds, as a discriminated union at an object's top level (§9:3)."""

    decision: Annotated[_A | _B, Field(discriminator="kind")]


class _Node(BaseModel):
    label: str
    child: _Node | None = None


def _positions(schema: object) -> list[dict[str, Any]]:
    """Every schema position, descending through every keyword's value."""
    found: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        found.append(schema)
        for keyword, value in schema.items():
            if keyword in {"properties", "$defs"} and isinstance(value, dict):
                for item in value.values():
                    found.extend(_positions(item))
            elif keyword not in {"default", "const", "enum", "discriminator"}:
                found.extend(_positions(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_positions(item))
    return found


# --- the schema (§3:2) ---------------------------------------------------------


def test_every_object_is_closed_at_every_depth() -> None:
    schema = reply_schema(_Tree)
    objects = [p for p in _positions(schema) if p.get("type") == "object"]
    assert len(objects) == 2
    assert all(p["additionalProperties"] is False for p in objects)


def test_no_title_description_or_examples_survives_anywhere() -> None:
    generated = json.dumps(_Tree.model_json_schema())
    assert "A titled tree" in generated
    assert "Where it starts." in generated
    for position in _positions(reply_schema(_Tree)):
        assert not {"title", "description", "examples"} & position.keys()
    sent = json.dumps(reply_schema(_Tree))
    for text in ("A titled tree", "Where it starts.", "oak", "The top", "A leaf."):
        assert text not in sent


def test_nothing_else_changes() -> None:
    assert reply_schema(_Simple) == {
        "properties": {"answer": {"type": "string"}, "confidence": {"type": "integer"}},
        "required": ["answer", "confidence"],
        "type": "object",
        "additionalProperties": False,
    }


def test_a_property_keeps_its_name_whatever_it_is() -> None:
    schema = reply_schema(_Named)
    assert set(schema["properties"]) == {"title", "description", "examples"}  # type: ignore[call-overload]


def test_a_shape_allowing_further_keys_is_closed_rather_than_refused() -> None:
    """§10:2: a shape keeps its own ``extra``, and its schema is closed either way."""
    assert reply_schema(_Open)["additionalProperties"] is False
    assert reply_schema(_Forbidding)["additionalProperties"] is False


def test_a_discriminated_union_keeps_its_discriminator() -> None:
    schema = reply_schema(_Decision)
    decision = schema["properties"]["decision"]  # type: ignore[index]
    assert decision["discriminator"]["propertyName"] == "kind"
    assert reply_schema(_Decision)["$defs"]["_A"]["additionalProperties"] is False  # type: ignore[index]


def test_a_recursive_shape_is_closed() -> None:
    schema = reply_schema(_Node)
    assert schema["$defs"]["_Node"]["additionalProperties"] is False  # type: ignore[index]


def test_each_call_gives_a_fresh_schema() -> None:
    first = reply_schema(_Tree)
    first["properties"] = {}
    assert reply_schema(_Tree)["properties"] != {}


class _Mapping(BaseModel):
    scores: dict[str, int]


class _FurtherKeys(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, int]
    name: str


class _JsonValue(BaseModel):
    payload: JsonValue


class _Anything(BaseModel):
    anything: Any = None


class _ListOfAnything(BaseModel):
    items: list[Any]


class _Object(BaseModel):
    thing: object


class _DeepOpen(BaseModel):
    trees: list[_Anything]


class _Unschemable(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    handle: _Opaque


class _Opaque:
    pass


_Unschemable.model_rebuild()


class _NotAnObject(RootModel[int]):
    pass


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param(_Mapping, id="a-mapping"),
        pytest.param(_FurtherKeys, id="a-schema-for-further-keys"),
        pytest.param(_JsonValue, id="an-open-json-value"),
        pytest.param(_Anything, id="any"),
        pytest.param(_ListOfAnything, id="a-list-of-anything"),
        pytest.param(_Object, id="object"),
        pytest.param(_DeepOpen, id="an-open-value-deep-inside"),
        pytest.param(_Unschemable, id="no-json-schema"),
        pytest.param(_NotAnObject, id="not-an-object"),
        pytest.param(dict, id="not-a-model-class"),
        pytest.param(_Simple(answer="a", confidence=1), id="an-instance"),
    ],
)
def test_a_shape_that_cannot_be_closed_is_refused_with_no_disposition(shape: object) -> None:
    with pytest.raises(ModelError) as caught:
        reply_schema(shape)  # type: ignore[arg-type]
    assert type(caught.value) is ModelError
    assert caught.value.retryable is False
    assert caught.value.routable is False


def test_a_refusal_names_where_the_defect_stands() -> None:
    with pytest.raises(ModelError, match="admits any JSON value at #/properties/anything"):
        reply_schema(_Anything)


# --- the version (§3:3) ----------------------------------------------------------


def test_the_version_is_twelve_digits_of_the_sorted_compact_schemas_sha256() -> None:
    serialised = json.dumps(reply_schema(_Simple), sort_keys=True, separators=(",", ":"))
    assert reply_shape_version(_Simple) == hashlib.sha256(serialised.encode()).hexdigest()[:12]
    assert schema_version(reply_schema(_Simple)) == reply_shape_version(_Simple)


def test_the_version_is_stable_across_runs() -> None:
    # Pinned: a run in another process, or after a refactor that changes nothing sent,
    # gives this same version.
    assert reply_shape_version(_Simple) == "803f28709428"


def test_the_version_changes_when_a_field_changes() -> None:
    class Added(BaseModel):
        answer: str
        confidence: int
        why: str

    class Retyped(BaseModel):
        answer: str
        confidence: float

    class Renamed(BaseModel):
        answer: str
        certainty: int

    versions = {reply_shape_version(shape) for shape in (_Simple, Added, Retyped, Renamed)}
    assert len(versions) == 4


def test_the_version_ignores_text_the_schema_does_not_carry() -> None:
    class Described(BaseModel):
        """A docstring."""

        answer: str = Field(description="Said differently.")
        confidence: int = Field(examples=[3])

    assert reply_shape_version(Described) == reply_shape_version(_Simple)


# --- the reading rule (§3:4) -------------------------------------------------------

_VALID = '{"answer": "yes", "confidence": 4}'
_VALUE = _Simple(answer="yes", confidence=4)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_VALID, id="bare"),
        pytest.param(f"  \n{_VALID}\n ", id="surrounded-by-whitespace"),
        pytest.param(f"```json\n{_VALID}\n```", id="json-fence"),
        pytest.param(f"```JSON\n{_VALID}\n```", id="upper-case-json-fence"),
        pytest.param(f"```\n{_VALID}\n```", id="bare-fence"),
        pytest.param(f"```{_VALID}```", id="fence-on-one-line"),
    ],
)
def test_a_reply_is_read_once_one_enclosing_fence_is_removed(reply: str) -> None:
    assert read_reply(_Simple, reply) == _VALUE


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(f"Sure! {_VALID}", id="prose-before"),
        pytest.param(f"{_VALID} Hope that helps.", id="prose-after"),
        pytest.param(f"```json\n```json\n{_VALID}\n```\n```", id="two-fences"),
        pytest.param(f"```python\n{_VALID}\n```", id="another-languages-fence"),
        pytest.param(f"Here:\n```json\n{_VALID}\n```", id="a-fence-not-enclosing-the-reply"),
        pytest.param('{"answer": "yes"}', id="a-missing-field"),
        pytest.param('{"answer": "yes", "confidence": 4,}', id="malformed-json"),
        pytest.param("[" * 10_000 + "]" * 10_000, id="too-deep"),
    ],
)
def test_nothing_else_is_done_to_a_reply(reply: str) -> None:
    assert read_reply(_Simple, reply) is ReplyFailure.INVALID


@pytest.mark.parametrize("reply", ["", "   ", "\n\t", "```\n```", "```json\n  \n```"])
def test_a_reply_of_nothing_but_whitespace_is_empty(reply: str) -> None:
    assert read_reply(_Simple, reply) is ReplyFailure.EMPTY


def test_a_reply_is_validated_under_the_shapes_own_configuration() -> None:
    stray = '{"answer": "yes", "confidence": 4, "why": "x"}'
    assert read_reply(_Forbidding, '{"answer": "yes", "why": "x"}') is ReplyFailure.INVALID
    assert read_reply(_Simple, stray) == _VALUE

    class Strict(BaseModel):
        model_config = ConfigDict(strict=True)
        confidence: int

    assert read_reply(Strict, '{"confidence": "4"}') is ReplyFailure.INVALID
    assert read_reply(_Simple, '{"answer": "yes", "confidence": "4"}') == _VALUE


def test_unfenced_removes_one_fence_and_its_info_string() -> None:
    assert unfenced("```json\n{}\n```") == "{}\n"
    assert unfenced("``` \n{}\n```") == "{}\n"
    assert unfenced("```python\n{}\n```") == "python\n{}\n"
    assert unfenced("``````") == ""
    assert unfenced("```") == "```"
