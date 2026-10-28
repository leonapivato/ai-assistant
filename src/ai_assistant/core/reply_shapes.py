"""A reply shape's schema, its version, and the rule a reply is read by (ADR-0354 §3).

A **shape** is the pydantic model class a stage wants its reply to be, defined by its
consumer (§3:1). This module is the one place three things about a shape are
computed, so that a stage writing its given entry, the structured-completion seam and
the regression suite agree on all three (§3:5):

- :func:`reply_schema`, the schema sent for it (§3:2): its pydantic JSON schema in
  validation mode, with every object closed (``"additionalProperties": false``) and
  every ``title``, ``description`` and ``examples`` keyword removed, and no other
  change. A property keeps its name whatever it is, so a field named ``title`` stays.
  A shape whose schema cannot be closed is refused (§2:3): one with a mapping, a
  schema for further keys, or a position admitting any JSON value.
- :func:`reply_shape_version`, its version (§3:3): the first twelve hexadecimal digits
  of the SHA-256 of that schema serialised with sorted keys and no insignificant
  whitespace.
- :func:`read_reply`, the reading rule (§3:4): one Markdown code fence enclosing the
  whole reply is removed, and what remains is validated with the shape's own
  ``model_validate_json`` under its own configuration. Nothing else is done to it: no
  prose is cut away, no key is dropped and no value is repaired.

It does no I/O and keeps nothing between calls, so it holds no reference to a shape
once a call returns.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, PydanticUserError, ValidationError

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import ReplyFailure

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The digits of a shape's version, as ADR-0334 §8:1 gives a template's (§3:3).
_VERSION_DIGITS: Final = 12

#: The keywords that carry text, removed wherever a schema stands (§3:2).
_TEXT_KEYWORDS: Final = frozenset({"title", "description", "examples"})

#: The keywords that annotate a schema and assert nothing of a value. A schema of
#: these alone admits any JSON value.
_ANNOTATIONS: Final = frozenset(
    {
        *_TEXT_KEYWORDS,
        "default",
        "deprecated",
        "readOnly",
        "writeOnly",
        "$comment",
        "$schema",
        "$id",
    }
)

#: The keywords whose value is one schema.
_ONE_SCHEMA: Final = frozenset(
    {
        "additionalItems",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
    }
)

#: The keywords whose value is a list of schemas.
_SCHEMA_LISTS: Final = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})

#: The keywords whose value maps names to schemas. A name is never rewritten.
_SCHEMA_MAPS: Final = frozenset({"$defs", "definitions", "dependentSchemas", "properties"})

#: The keywords that give an object's further keys a schema of their own.
_FURTHER_KEYS: Final = frozenset(
    {"additionalProperties", "patternProperties", "unevaluatedProperties"}
)

#: The fence that opens and closes a fenced reply, and the info strings removed with it.
_FENCE: Final = "```"
_INFO_STRINGS: Final = frozenset({"", "json", "JSON"})


def reply_schema(shape: type[BaseModel]) -> dict[str, object]:
    """The schema sent for ``shape``: closed at every depth and carrying no text (§3:2).

    Args:
        shape: A pydantic model class.

    Returns:
        A fresh schema, the caller's to keep or change.

    Raises:
        ModelError: The bare class, neither retryable nor routable (ADR-0066 §3), if
            ``shape`` is not a pydantic model class, pydantic gives it no JSON schema,
            its schema is not a JSON object, or the schema cannot be closed: an object
            names no properties or gives its further keys a schema of their own, or a
            position admits any JSON value (§2:3). The message names the defect and
            where it stands, and nothing of the shape's text.
    """
    if not _is_model_class(shape):
        msg = "a reply shape is a pydantic model class"
        raise ModelError(msg)
    try:
        generated = shape.model_json_schema(mode="validation")
    except PydanticUserError as exc:
        msg = f"pydantic gives the reply shape {shape.__name__} no JSON schema"
        raise ModelError(msg) from exc
    schema = _closed(copy.deepcopy(generated), "#")
    if not isinstance(schema, dict) or not _is_object(_root(schema)):
        msg = f"the reply shape {shape.__name__}'s schema is not a JSON object"
        raise ModelError(msg)
    return schema


def reply_shape_version(shape: type[BaseModel]) -> str:
    """``shape``'s version: twelve hexadecimal digits of its schema's SHA-256 (§3:3).

    Args:
        shape: A pydantic model class.

    Returns:
        The version, stable across runs and changed by any change to the schema.

    Raises:
        ModelError: Where :func:`reply_schema` refuses ``shape``.
    """
    return schema_version(reply_schema(shape))


def schema_version(schema: Mapping[str, object]) -> str:
    """The version of a schema :func:`reply_schema` gave (§3:3).

    Args:
        schema: The schema, as :func:`reply_schema` returned it.

    Returns:
        The first twelve hexadecimal digits of the SHA-256 of ``schema`` serialised as
        JSON with its keys sorted and no insignificant whitespace.
    """
    serialised = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("ascii")).hexdigest()[:_VERSION_DIGITS]


def unfenced(reply: str) -> str:
    """``reply`` with one Markdown code fence enclosing the whole of it removed (§3:4).

    The reply is taken without its surrounding whitespace. Where it opens and closes
    with a fence, both are removed, and so is the opening line's info string where it
    is empty or ``json``. Anything else is left as it stands.

    Args:
        reply: The reply as the model wrote it.

    Returns:
        What the rule validates.
    """
    body = reply.strip()
    if body.startswith(_FENCE) and body.endswith(_FENCE) and len(body) >= 2 * len(_FENCE):
        body = body[len(_FENCE) : -len(_FENCE)]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in _INFO_STRINGS:
            body = body[newline + 1 :]
    return body


def read_reply[T: BaseModel](shape: type[T], reply: str) -> T | ReplyFailure:
    """Read ``reply`` as ``shape`` by the one rule (§3:4).

    Args:
        shape: The shape the reply is read as.
        reply: The reply as the model wrote it.

    Returns:
        The shape's value, or :attr:`ReplyFailure.EMPTY` where nothing but whitespace
        is left once the fence is removed, or :attr:`ReplyFailure.INVALID` where what
        is left does not validate as ``shape``.
    """
    body = unfenced(reply)
    if not body.strip():
        return ReplyFailure.EMPTY
    try:
        return shape.model_validate_json(body)
    except ValidationError, ValueError, RecursionError:
        # A validation failure, JSON the parser refuses, or nesting too deep to walk:
        # each is a reply that does not validate as the shape.
        return ReplyFailure.INVALID


def _is_model_class(candidate: object) -> bool:
    """Whether ``candidate`` is a pydantic model class, whatever its caller's annotation."""
    return isinstance(candidate, type) and issubclass(candidate, BaseModel)


def _root(schema: dict[str, object]) -> object:
    """The schema the root stands for: itself, or the definition its ``$ref`` names."""
    reference = schema.get("$ref")
    definitions = schema.get("$defs")
    if isinstance(reference, str) and isinstance(definitions, dict):
        name = reference.removeprefix("#/$defs/")
        if name != reference:
            return definitions.get(name)
    return schema


def _is_object(schema: object) -> bool:
    """Whether ``schema`` describes a JSON object."""
    if not isinstance(schema, dict):
        return False
    kind = schema.get("type")
    return (
        kind == "object" or (isinstance(kind, list) and "object" in kind) or "properties" in schema
    )


def _closed(schema: object, where: str) -> object:
    """``schema`` with its text removed and every object closed, refusing what cannot be.

    ``where`` is the schema's JSON pointer, for the refusal's message.

    Raises:
        ModelError: The bare class, if a position admits any JSON value, or an object
            names no properties or gives its further keys a schema.
    """
    if schema is True or (isinstance(schema, dict) and schema.keys() <= _ANNOTATIONS):
        msg = f"the reply shape's schema admits any JSON value at {where}"
        raise ModelError(msg)
    if not isinstance(schema, dict):
        return schema
    closed: dict[str, object] = {}
    for keyword, value in schema.items():
        if keyword in _TEXT_KEYWORDS:
            continue
        closed[keyword] = _subschemas(keyword, value, f"{where}/{keyword}")
    if _is_object(closed):
        _refuse_open_object(closed, where)
        closed["additionalProperties"] = False
    return closed


def _subschemas(keyword: str, value: object, where: str) -> object:
    """``value``, the value of ``keyword``, with every schema it holds closed."""
    if keyword in _ONE_SCHEMA:
        return _closed(value, where)
    if keyword in _SCHEMA_LISTS and isinstance(value, list):
        return [_closed(item, f"{where}/{index}") for index, item in enumerate(value)]
    if keyword in _SCHEMA_MAPS and isinstance(value, dict):
        return {name: _closed(item, f"{where}/{name}") for name, item in value.items()}
    # Any other keyword's value is data, never a schema: a ``default``, an ``enum``, a
    # ``const``, a ``discriminator``. ``additionalProperties`` is judged by the object.
    return value


def _refuse_open_object(schema: dict[str, object], where: str) -> None:
    """Refuse an object that cannot be closed (§2:3).

    Raises:
        ModelError: The bare class, if the object names no properties, or gives its
            further keys a schema of their own. ``additionalProperties: true``, as a
            shape allowing extra keys writes, is closed rather than refused (§10:2).
    """
    if not isinstance(schema.get("properties"), dict):
        msg = f"the reply shape's schema has an object naming no properties at {where}"
        raise ModelError(msg)
    for keyword in _FURTHER_KEYS:
        if keyword in schema and schema[keyword] not in (True, False):
            msg = (
                f"the reply shape's schema gives an object's further keys a schema at "
                f"{where}/{keyword}"
            )
            raise ModelError(msg)
