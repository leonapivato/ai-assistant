"""How many keys a model's reply carried that the shape it was read as does not name (#3246).

The digesting stage, the story tidy-up and the matters pass read their model's JSON reply
into a local shape that drops a key it does not name, as the observer's shapes have since
#3220: a stray key beside the fields a reply was asked for is no reason to lose the reply.
Every field a shape does name is validated as before, so a reply missing a required field,
or carrying a value of the wrong kind, is still refused whole.

What is dropped is counted here so that each stage can log it, **by count alone**. A key
is text the model wrote, and each of these stages logs code-owned text only, never the
reply's own (ADR-0275 §8), so no key's name is ever logged. The count is logged as
``stray``, never under a field whose name holds ``key``, which the hub's log redaction
masks (``core/logging.py``).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, TypeAdapter, ValidationError

__all__ = ["shape_keys", "stray_keys"]

#: Any JSON value, decoded by the parser the shapes themselves are validated with.
_JSON: Final[TypeAdapter[object]] = TypeAdapter(object)


def stray_keys(text: str, reply: BaseModel) -> int:
    """How many keys ``text`` carries that ``reply``'s shape, or one nested in it, does not name.

    ``reply`` is what ``text`` was validated as, so the walk follows the fields that
    validation kept: the member of a union it chose, and each element of a sequence of
    shapes in order. A key under a dropped key is not counted again: the dropped key is
    one stray key, whatever it holds.

    Args:
        text: The JSON text ``reply`` was validated from.
        reply: The shape validated from ``text``.

    Returns:
        The number of keys dropped, ``0`` where none were.
    """
    try:
        value = _JSON.validate_json(text)
    except ValidationError, RecursionError:  # pragma: no cover — ``text`` validated as ``reply``
        return 0
    return _count(value, reply)


def _count(value: object, shape: object) -> int:
    """The stray keys of the JSON ``value`` that validated as ``shape``, nested ones included."""
    if isinstance(shape, BaseModel):
        if not isinstance(value, dict):  # pragma: no cover — a shape validates from an object
            return 0
        named = _named(type(shape))
        count = sum(1 for key in value if key not in named)
        for key, field in named.items():
            if key in value:
                count += _count(value[key], getattr(shape, field))
        return count
    if isinstance(shape, tuple | list) and isinstance(value, list):
        return sum(_count(one, kept) for one, kept in zip(value, shape, strict=False))
    return 0


def shape_keys(shape: type[BaseModel]) -> frozenset[str]:
    """Every key ``shape`` reads at its own level, each field's alias in place of its name.

    Raises:
        TypeError: If a field is read under a choice of aliases or a path.
    """
    return frozenset(_named(shape))


def _named(shape: type[BaseModel]) -> dict[str, str]:
    """Each key ``shape`` reads, and the field it reads it into.

    A field read under an alias is read under the alias alone, unless the shape also
    reads fields by name.

    Raises:
        TypeError: If a field is read under a choice of aliases or a path, which this
            walk does not follow.
    """
    by_name = bool(shape.model_config.get("validate_by_name")) or bool(
        shape.model_config.get("populate_by_name")
    )
    named: dict[str, str] = {}
    for name, field in shape.model_fields.items():
        alias = field.validation_alias if field.validation_alias is not None else field.alias
        if alias is not None and not isinstance(alias, str):
            msg = f"{shape.__name__}.{name} is read under an alias this walk does not follow"
            raise TypeError(msg)
        if alias is None or by_name:
            named[name] = name
        if alias is not None:
            named[alias] = name
    return named
