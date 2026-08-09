"""No string reachable from an ``EvaluationTrace`` is unconstrained (ADR-0119 §2, §13d).

§2 states the tier discipline as clauses about *strings* precisely so that it is
checkable: "Do not put Tier 1 in a trace" is a rule a reviewer applies to intent;
"every string-typed value reachable from an ``EvaluationTrace`` falls in exactly
one of four categories" is a rule a **type-graph walk** can approximate, in the
spirit of ADR-0085 §5's closure walk. §13d makes that walk an obligation of this
lane.

The four categories, and how each is recognised here:

* an **identifier** — :data:`Identifier`, recognised by its ``_non_blank``
  validator;
* a **member of an enumeration defined in ``core/types.py``** — a ``StrEnum``
  subclass, which cannot hold a value outside its members;
* a **literal constant written in the emitting module** — a
  :data:`TraceLabel`, whose pattern bounds it to a lowercase identifier of at
  most 64 characters, which is what makes an accidentally data-derived key loud;
* an **exception class's ``__name__``** — :data:`FaultClassName`, same shape.

Plus :data:`TraceId`, which is stricter than all four: 32 lowercase hex
characters, minted by the type.

**What this walk can and cannot show.** It shows that no field, at any depth,
admits an *arbitrary* string — that a bare ``str``, an unvalidated
:data:`EncodableText`, or a ``Mapping[str, str]`` cannot appear without this test
failing. It cannot show that an emitter passed a literal rather than a value it
derived from a row: §2's third clause is an obligation review enforces, and
ADR-0119 §2 says so in as many words ("the residue is named rather than hidden").
The pattern is what makes an accidental breach loud rather than silent.

**The walk starts at ``EvaluationTrace`` and nowhere else**, because that is the
type §2's clauses are about. :class:`TracePosition`'s token is deliberately
outside it: it is the store's own order key, never derived from a trace, and it
is the one string in the family a caller is forbidden to read.
"""

from __future__ import annotations

import enum
import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final

import pytest
from pydantic import BaseModel, ConfigDict, create_model
from pydantic.functional_validators import AfterValidator

from ai_assistant.core.types import (
    EncodableText,
    EvaluationTrace,
    FaultClassName,
    Identifier,
    TraceId,
    TraceKind,
    TraceLabel,
    TraceRecords,
    _fault_class_name,
    _non_blank,
    _trace_id,
    _trace_label,
)

#: The validators that put a string in one of §2's four categories. Recognised by
#: identity rather than by name: a same-named function defined elsewhere is a
#: different constraint, and this test exists to catch exactly the string that
#: slipped in without one.
_CONSTRAINING: Final = frozenset({_non_blank, _trace_id, _trace_label, _fault_class_name})


@dataclass(frozen=True)
class _Leaf:
    """One string-typed position in the graph, and how it got there."""

    path: str
    constrained: bool


def _unwrap_alias(annotation: object) -> object:
    """Expand a PEP 695 ``type`` alias to what it stands for."""
    value = annotation
    while isinstance(value, typing.TypeAliasType):
        value = value.__value__
    return value


def _walk(
    annotation: object, path: str, seen: set[type], validators: frozenset[Any]
) -> list[_Leaf]:
    """Report every string-typed leaf reachable from ``annotation``.

    Args:
        annotation: The type to walk.
        path: How this position was reached, for the failure message.
        seen: Models already walked, so a self-referential type terminates.
        validators: The ``AfterValidator`` functions collected on the way in.

    Returns:
        One :class:`_Leaf` per string-typed position.
    """
    annotation = _unwrap_alias(annotation)

    if typing.get_origin(annotation) is Annotated:
        inner, *metadata = typing.get_args(annotation)
        gathered = validators | {item.func for item in metadata if isinstance(item, AfterValidator)}
        return _walk(inner, path, seen, frozenset(gathered))

    origin = typing.get_origin(annotation)
    if origin is not None:
        # A union, or any parameterised container: tuple, Sequence, Mapping, ...
        separator = "|" if origin in (types.UnionType, typing.Union) else "["
        closer = "" if separator == "|" else "]"
        return [
            leaf
            for index, arg in enumerate(typing.get_args(annotation))
            if arg is not Ellipsis and arg is not type(None)
            for leaf in _walk(arg, f"{path}{separator}{index}{closer}", seen, validators)
        ]
    return _walk_leaf(annotation, path, seen, validators)


def _walk_leaf(
    annotation: object, path: str, seen: set[type], validators: frozenset[Any]
) -> list[_Leaf]:
    """Classify an unparameterised annotation.

    Args:
        annotation: The type at this position.
        path: How it was reached.
        seen: Models already walked.
        validators: The validators collected on the way in.

    Returns:
        One :class:`_Leaf` if this position is a string, the nested model's
        leaves if it is a model, and nothing otherwise — an enum member is a
        category of its own (§2's second bullet) and a number carries no content.
    """
    if not isinstance(annotation, type):
        return []
    if issubclass(annotation, enum.Enum):
        return []
    if issubclass(annotation, BaseModel):
        return [] if annotation in seen else _walk_model(annotation, path, seen | {annotation})
    if issubclass(annotation, str):
        return [_Leaf(path, bool(validators & _CONSTRAINING))]
    return []


def _walk_model(model: type[BaseModel], path: str, seen: set[type]) -> list[_Leaf]:
    """Report every string-typed leaf reachable from ``model``'s declared fields."""
    hints = typing.get_type_hints(model, include_extras=True)
    return [
        leaf
        for name in model.model_fields
        for leaf in _walk(hints[name], f"{path}.{name}", seen, frozenset())
    ]


def _positions(
    annotation: object, path: str = "", seen: frozenset[type] = frozenset()
) -> list[tuple[object, str]]:
    """Every annotation position reachable from ``annotation``, unwrapped.

    A second, coarser walk than :func:`_walk`: it reports *every* leaf rather than
    only the string ones, which is what an "is any position open-valued?" question
    needs. Kept separate rather than folded in, because the two ask different
    questions and a single walk answering both would have to return everything and
    let each caller filter.

    Args:
        annotation: The type to walk.
        path: How this position was reached.
        seen: Models already walked.

    Returns:
        ``(annotation, path)`` for every unparameterised position.
    """
    annotation = _unwrap_alias(annotation)
    if typing.get_origin(annotation) is Annotated:
        return _positions(typing.get_args(annotation)[0], path, seen)
    if typing.get_origin(annotation) is not None:
        return [
            position
            for index, arg in enumerate(typing.get_args(annotation))
            if arg is not Ellipsis
            for position in _positions(arg, f"{path}[{index}]", seen)
        ]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return []
        hints = typing.get_type_hints(annotation, include_extras=True)
        return [
            position
            for name in annotation.model_fields
            for position in _positions(hints[name], f"{path}.{name}", seen | {annotation})
        ]
    return [(annotation, path)]


def _leaves_of(model: type[BaseModel]) -> list[_Leaf]:
    """Every string-typed leaf reachable from ``model``."""
    return _walk_model(model, model.__name__, {model})


def test_every_string_reachable_from_a_trace_is_constrained() -> None:
    """ADR-0119 §13d's type-graph walk, over the whole family.

    A new field admitting a bare ``str`` — an "attributes bag", a free-text note,
    a serialised payload — fails here, which is the point: §2's containment is a
    property of the type, and a property nothing checks is a promise.
    """
    unconstrained = [leaf.path for leaf in _leaves_of(EvaluationTrace) if not leaf.constrained]

    assert not unconstrained, (
        f"these string-typed positions admit an arbitrary string: {unconstrained}. "
        f"Every string reachable from an EvaluationTrace must be an identifier, an "
        f"enum member, a bounded label, or an exception class name (ADR-0119 §2)."
    )


def test_the_walk_reaches_the_positions_it_is_meant_to_guard() -> None:
    """Guard the walk itself: one that finds nothing passes vacuously.

    Named rather than counted, so a field *removed* from the family fails here
    instead of quietly shrinking the walk's coverage.
    """
    paths = {leaf.path for leaf in _leaves_of(EvaluationTrace)}

    assert "EvaluationTrace.id" in paths
    assert "EvaluationTrace.seam" in paths
    assert "EvaluationTrace.fault_class|0" in paths
    assert "EvaluationTrace.refs[1]" in paths  # the mapping's *value*: an Identifier
    assert "EvaluationTrace.metrics[0]" in paths  # the mapping's *key*: a TraceLabel
    assert "EvaluationTrace.records[1].ids[0]" in paths  # through a nested model


def test_the_walk_reports_an_unconstrained_string() -> None:
    """The negative control: the check fails on a type it should reject."""

    class _Bag(BaseModel):
        model_config = ConfigDict(frozen=True)

        note: str
        attributes: Mapping[str, str]

    unconstrained = {leaf.path for leaf in _leaves_of(_Bag) if not leaf.constrained}

    assert unconstrained == {"_Bag.note", "_Bag.attributes[0]", "_Bag.attributes[1]"}


def test_encodable_text_alone_does_not_count_as_constrained() -> None:
    """:data:`EncodableText` is the near miss, and it must not pass.

    ADR-0119 §2 makes the point about :data:`Identifier` and it applies here with
    more force: encodability is a statement about a value's *bytes*, not about its
    origin, so a whole conversation turn satisfies it.
    """

    class _Loose(BaseModel):
        model_config = ConfigDict(frozen=True)

        text: EncodableText

    assert [leaf.constrained for leaf in _leaves_of(_Loose)] == [False]


@pytest.mark.parametrize(
    ("annotation", "label"),
    [
        (Identifier, "an identifier"),
        (TraceLabel, "a bounded label"),
        (FaultClassName, "an exception class name"),
        (TraceId, "a minted trace id"),
    ],
)
def test_each_admitted_category_is_recognised(annotation: Any, label: str) -> None:
    """The positive control for the recogniser, so it is not failing for free.

    Built with ``create_model`` rather than a class body, because a class body
    cannot take a parametrised annotation: the name would be resolved from the
    module at evaluation time and there is nothing there to find.
    """
    model = create_model("_One", value=(annotation, ...))

    assert [leaf.constrained for leaf in _leaves_of(model)] == [True], label


def test_an_enum_member_is_a_category_and_not_a_free_string() -> None:
    """A ``StrEnum`` is a ``str``, so the walk must not treat it as an open one.

    Recognised as a category rather than skipped: the value of a ``StrEnum``
    field cannot be anything but a declared member, which is §2's second bullet
    exactly.
    """

    class _Kinded(BaseModel):
        model_config = ConfigDict(frozen=True)

        kind: TraceKind

    assert _leaves_of(_Kinded) == []


class _Recursive(BaseModel):
    """A cycle in the type graph, so the walk's termination guard has a subject.

    At module scope because a locally defined self-referential model has no name
    ``get_type_hints`` can resolve.
    """

    model_config = ConfigDict(frozen=True)

    child: _Recursive | None = None
    name: Identifier = "x"


def test_the_walk_terminates_on_a_self_referential_model() -> None:
    """A cycle in the graph must not hang the check.

    Nothing in the family is self-referential today, and the guard is what keeps
    that from being a precondition of the check working at all.
    """
    assert [leaf.path for leaf in _leaves_of(_Recursive)] == ["_Recursive.name"]


def test_the_records_mapping_reaches_its_nested_model() -> None:
    """The one place the graph is more than one level deep.

    ``records`` is a mapping whose *values* are models carrying a tuple of ids, so
    a walk that stopped at the mapping would report a closed family while the ids
    inside it were unchecked.
    """
    leaves = _walk(TraceRecords, "records", set(), frozenset())

    assert [leaf.path for leaf in leaves] == ["records[1].ids[0]"]
    assert all(leaf.constrained for leaf in leaves)


def test_no_field_of_the_family_carries_an_open_value_type() -> None:
    """§2's last clause: no serialised payload and no open-value-type mapping.

    Distinct from the string walk above, which would pass on a
    ``Mapping[TraceLabel, Any]``: what is checked here is that every *value* type
    in the family resolves to a number, a boolean, an instant, a duration, an
    enum member, a constrained string or another model of the family.
    """
    offenders = [
        path for annotation, path in _positions(EvaluationTrace) if annotation in (Any, object)
    ]

    assert not offenders, f"these positions admit an arbitrary value: {offenders}"


def test_the_family_holds_no_sequence_of_free_text() -> None:
    """A ``Sequence[str]`` would satisfy every clause above and carry a payload.

    Covered by the main walk — the element type is a string leaf like any other —
    and asserted separately because a list of notes is the shape an author reaches
    for when the metric map will not take what they want to record.
    """

    class _Notes(BaseModel):
        model_config = ConfigDict(frozen=True)

        notes: Sequence[str]

    assert [leaf.constrained for leaf in _leaves_of(_Notes)] == [False]
