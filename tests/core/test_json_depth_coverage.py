"""Every `FrozenJson` field in `core` carries the depth ceiling (ADR-0196 §5(b)).

ADR-0196 §3 states the ceiling over "every `FrozenJson` value alike", and §1 puts
it on the *type* rather than on a holder because the property being enforced — this
value can be walked, encoded, stored, dumped and revalidated — is intrinsic to the
value and not to who holds it (ADR-0016 §2). A per-holder bound would be the same
rule written nine times, free to disagree, with nothing that fails when it does.

So the check below is **enumerated rather than listed**, in the shape
`test_text_encodability_coverage.py` uses for `EncodableText` and `#1287`'s roster
guard uses for the duration fields. Nine fields declare the type as this is
written; the roster is what makes a tenth arrive already pinned rather than
silently outside the contract. A hand-written list is a list that goes stale.

**Two paths, because either can regress alone.** The first walks the declarations
and reports a field that reaches `FrozenJson` without one of the two guarding
aliases — a hole in the gate rather than in the tree, since no such field exists
today. The second validates an over-deep payload against each discovered field's
own annotation and requires the ceiling's refusal, which is what "refuses the same
over-deep input the same way" means.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAliasType, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.types import (
    _MAX_JSON_DEPTH,
    FrozenJson,
    FrozenJsonMapping,
    FrozenJsonValue,
)

#: The aliases that carry the depth ceiling, by identity.
#:
#: Both are ``Annotated`` forms of :data:`FrozenJson` wearing the same
#: ``BeforeValidator``; reaching :data:`FrozenJson` by any other route reaches it
#: without the ceiling, which is what :func:`unguarded_frozen_json_fields` reports.
GUARDING_ALIASES = (FrozenJsonValue, FrozenJsonMapping)


def _frozen_json_leaves(annotation: object, *, guarded: bool, seen: frozenset[int]) -> list[bool]:
    """For every route to :data:`FrozenJson` in ``annotation``, whether an alias guards it.

    Walks unions, ``Annotated``, generic parameters and type aliases, so
    ``FrozenJsonValue | None`` and ``tuple[FrozenJsonValue, ...]`` are recognised
    while a bare ``FrozenJson`` is not. ``seen`` breaks the cycle in
    :data:`FrozenJson`, which refers to itself.
    """
    if id(annotation) in seen:
        return []
    if isinstance(annotation, TypeAliasType):
        if annotation is FrozenJson:
            return [guarded]
        return _frozen_json_leaves(
            annotation.__value__,
            guarded=guarded or any(annotation is alias for alias in GUARDING_ALIASES),
            seen=seen | {id(annotation)},
        )
    origin = get_origin(annotation)
    if origin is Annotated:
        return _frozen_json_leaves(get_args(annotation)[0], guarded=guarded, seen=seen)
    if origin is not None:
        return [
            leaf
            for arg in get_args(annotation)
            for leaf in _frozen_json_leaves(arg, guarded=guarded, seen=seen | {id(annotation)})
        ]
    return []


def frozen_json_fields(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s fields that reach :data:`FrozenJson` at all."""
    hints = get_type_hints(model, include_extras=True)
    return [
        name
        for name in model.model_fields
        if _frozen_json_leaves(hints.get(name), guarded=False, seen=frozenset())
    ]


def unguarded_frozen_json_fields(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s fields reaching :data:`FrozenJson` past both aliases."""
    hints = get_type_hints(model, include_extras=True)
    return [
        name
        for name in model.model_fields
        if not all(_frozen_json_leaves(hints.get(name), guarded=False, seen=frozenset()))
    ]


def _core_type_models() -> list[type[BaseModel]]:
    """Every pydantic model declared in ``ai_assistant.core.types``."""
    found: dict[str, type[BaseModel]] = {}
    for value in vars(core_types).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
            found[value.__qualname__] = value
    return list(found.values())


def _roster() -> list[tuple[type[BaseModel], str]]:
    """Every ``(model, field)`` in ``core.types`` that declares a frozen JSON value."""
    return [(model, name) for model in _core_type_models() for name in frozen_json_fields(model)]


def _over_deep() -> Any:
    """A mapping one container past the ceiling, built without recursing."""
    value: Any = 1
    for _ in range(_MAX_JSON_DEPTH + 1):
        value = {"k": value}
    return value


def test_the_roster_finds_the_fields_adr_0196_names() -> None:
    """A roster that silently found nothing would pass forever.

    Named as a **subset**, deliberately: a tenth field must not have to be added
    here to be covered, and the nine below are what ADR-0196's Context enumerates,
    so their disappearance from the roster is a change worth failing on.
    """
    found = {(model.__name__, name) for model, name in _roster()}
    assert {
        ("PlanStep", "parameters"),
        ("StepExecution", "output"),
        ("StepTransition", "output"),
        ("ActionRequest", "parameters"),
        ("BoundEgressCall", "parameters"),
        ("Confirmation", "parameters"),
        ("ToolResult", "output"),
        ("ToolDefinition", "parameters_schema"),
        ("ParameterViolation", "schema_value"),
    } <= found


def test_the_walk_discriminates_between_a_guarded_and_a_bare_declaration() -> None:
    """Without this the walk could return ``[]`` for everything and pass enforcing nothing."""
    bare: frozenset[int] = frozenset()
    assert _frozen_json_leaves(FrozenJson, guarded=False, seen=bare) == [False]
    assert _frozen_json_leaves(FrozenJsonValue, guarded=False, seen=bare) == [True]
    assert _frozen_json_leaves(FrozenJsonMapping, guarded=False, seen=bare) == [True]
    assert _frozen_json_leaves(FrozenJsonValue | None, guarded=False, seen=bare) == [True]
    assert _frozen_json_leaves(tuple[FrozenJsonValue, ...], guarded=False, seen=bare) == [True]
    assert _frozen_json_leaves(str, guarded=False, seen=bare) == []


def test_the_unguarded_check_catches_an_omission() -> None:
    """Path one, on its own: a field typed ``FrozenJson`` rather than an alias."""

    class _Omission(BaseModel):
        guarded: FrozenJsonValue
        forgotten: FrozenJson
        in_a_tuple: tuple[FrozenJson, ...] = ()

    assert unguarded_frozen_json_fields(_Omission) == ["forgotten", "in_a_tuple"]


@pytest.mark.parametrize("model", _core_type_models(), ids=lambda model: model.__name__)
def test_no_core_field_reaches_frozen_json_past_the_guarding_aliases(
    model: type[BaseModel],
) -> None:
    """A bare ``FrozenJson`` on a ``core.types`` field fails the gate.

    Such a field would hold a value the ceiling never measured, which is the one
    way ADR-0196 §3's "every ``FrozenJson`` value alike" can quietly stop being
    true without any file that states it changing.
    """
    offenders = set(unguarded_frozen_json_fields(model))
    assert not offenders, f"{model.__name__} has unguarded FrozenJson field(s) {sorted(offenders)}"


@pytest.mark.parametrize(
    ("model", "field"), _roster(), ids=lambda item: getattr(item, "__name__", item)
)
def test_every_frozen_json_field_refuses_an_over_deep_value(
    model: type[BaseModel], field: str
) -> None:
    """§5(b): the same input, the same refusal, at every holder.

    Validated through a ``TypeAdapter`` built from the field's **own** annotation
    rather than by constructing nine models, because the annotation is exactly
    what pydantic compiles into the field's validator, and a per-model constructor
    would need a hand-maintained set of sibling values — the staleness this roster
    exists to avoid.

    A future field that wraps the alias in a container (``tuple[FrozenJsonValue,
    ...]``) will fail here rather than pass vacuously: the payload would be
    refused for its *shape* and the assertion below requires the ceiling's own
    reason.
    """
    annotation = get_type_hints(model, include_extras=True)[field]
    with pytest.raises(ValidationError, match="nests containers deeper than") as refusal:
        TypeAdapter(annotation).validate_python(_over_deep())
    assert refusal.value.error_count() == 1


@pytest.mark.parametrize(
    ("model", "field"), _roster(), ids=lambda item: getattr(item, "__name__", item)
)
def test_every_frozen_json_field_accepts_a_value_at_the_ceiling(
    model: type[BaseModel], field: str
) -> None:
    """The other direction: without it the pin above passes on a field refusing everything."""
    annotation = get_type_hints(model, include_extras=True)[field]
    at_ceiling: Any = 1
    for _ in range(_MAX_JSON_DEPTH):
        at_ceiling = {"k": at_ceiling}
    assert TypeAdapter(annotation).validate_python(at_ceiling)
