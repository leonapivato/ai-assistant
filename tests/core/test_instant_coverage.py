"""The gate check ADR-0023 §2 requires: no `core` instant may opt out.

ADR-0023 §2 rejects per-field validators as the carrier of the instant rule,
because a per-field validator is *opt-in* — and the three fields that had none
(``Provenance.last_updated``, ``EpisodicMemory.occurred_at``,
``SemanticMemory.valid_until``) are exactly how naive values got in. Typing every
field with :data:`~ai_assistant.core.types.UtcInstant` is the fix, and this
module is what makes the fix stick: it discovers every ``datetime`` field in
``core`` and fails on a bare annotation or an unvalidated datetime default, so
the omission fails the gate rather than depending on a reviewer noticing.

Its two paths are checked by *independent* negative fixtures, as §2 requires:
either check can regress while the other stays green, and a combined fixture
would not say which one failed.
"""

from __future__ import annotations

import pkgutil
from datetime import UTC, datetime
from importlib import import_module
from typing import Annotated, TypeAliasType, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, Field

import ai_assistant.core
from ai_assistant.core.types import _ORDERING_DEFERRED, UtcInstant


def _instant_leaves(
    annotation: object, *, guarded: bool, seen: frozenset[int] = frozenset()
) -> list[bool]:
    """For every ``datetime`` in ``annotation``, whether ``UtcInstant`` wraps it.

    Walks unions, ``Annotated`` and type aliases, so ``UtcInstant | None`` is
    recognised while a bare ``datetime | None`` is not. ``seen`` breaks the cycle
    in a recursive alias such as ``FrozenJson``, which refers to itself.
    """
    if id(annotation) in seen:
        return []
    if isinstance(annotation, TypeAliasType):
        return _instant_leaves(
            annotation.__value__,
            guarded=guarded or annotation is UtcInstant,
            seen=seen | {id(annotation)},
        )
    origin = get_origin(annotation)
    if origin is Annotated:
        return _instant_leaves(get_args(annotation)[0], guarded=guarded, seen=seen)
    if origin is not None:
        return [
            leaf
            for arg in get_args(annotation)
            for leaf in _instant_leaves(arg, guarded=guarded, seen=seen | {id(annotation)})
        ]
    if annotation is datetime:
        return [guarded]
    return []


def bare_datetime_fields(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s fields holding a ``datetime`` not typed ``UtcInstant``."""
    hints = get_type_hints(model, include_extras=True)
    return [
        name
        for name in model.model_fields
        if not all(_instant_leaves(hints.get(name), guarded=False))
    ]


def unvalidated_datetime_defaults(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s instant fields whose default escapes validation.

    Pydantic does not validate a field *default* unless ``validate_default`` is
    set, so a ``default_factory`` reading a naive clock — or a naive literal
    default — would slip past :data:`UtcInstant` entirely. ``None`` is exempt:
    it is not an instant, and it is the only default the optional instants use.
    """
    hints = get_type_hints(model, include_extras=True)
    flagged = []
    for name, field in model.model_fields.items():
        if not _instant_leaves(hints.get(name), guarded=False):
            continue  # not an instant field at all
        has_literal_default = field.default is not None and not field.is_required()
        if (
            has_literal_default or field.default_factory is not None
        ) and not field.validate_default:
            flagged.append(name)
    return flagged


def _core_models() -> list[type[BaseModel]]:
    """Every pydantic model reachable in the ``ai_assistant.core`` package."""
    found: dict[str, type[BaseModel]] = {}
    for info in pkgutil.walk_packages(ai_assistant.core.__path__, f"{ai_assistant.core.__name__}."):
        module = import_module(info.name)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
                found[f"{value.__module__}.{value.__qualname__}"] = value
    return list(found.values())


def test_the_scan_actually_finds_the_core_models() -> None:
    """A discovery check that silently found nothing would pass forever."""
    names = {model.__name__ for model in _core_models()}
    assert {"Provenance", "MemoryBase", "CurrentContext", "Goal", "PermissionDecision"} <= names


@pytest.mark.parametrize("model", _core_models(), ids=lambda model: model.__name__)
def test_every_core_datetime_field_uses_the_instant_type(model: type[BaseModel]) -> None:
    """A bare ``datetime`` on a ``core`` field fails the gate (ADR-0023 §2).

    The one exemption is ``_ORDERING_DEFERRED``: five clock-fed ``planning``
    fields ADR-0023 §6 holds back until ADR-0026's producer guard exists. It is
    an explicit, enumerated set precisely so the debt shrinks to empty rather
    than dissolving into "the check has always been advisory".
    """
    offenders = {
        name
        for name in bare_datetime_fields(model)
        if (model.__name__, name) not in _ORDERING_DEFERRED
    }
    assert not offenders, f"{model.__name__} has bare datetime field(s) {sorted(offenders)}"


@pytest.mark.parametrize("model", _core_models(), ids=lambda model: model.__name__)
def test_no_core_instant_field_has_an_unvalidated_default(model: type[BaseModel]) -> None:
    assert not unvalidated_datetime_defaults(model)


def test_the_ordering_exemption_lists_exactly_what_is_still_bare() -> None:
    """The exemption may not outlive the deferral it records.

    Asserted as equality, not containment: a stale entry would silently
    re-open the opt-out for a field that had since been migrated, which is the
    failure mode that turns an enumerated exemption back into a blanket one.
    """
    bare = {
        (model.__name__, name) for model in _core_models() for name in bare_datetime_fields(model)
    }
    assert bare == set(_ORDERING_DEFERRED)


# --- negative fixtures: the check must catch each omission independently ----


def test_the_bare_annotation_check_catches_an_omission() -> None:
    """Path one, on its own: a field typed ``datetime`` rather than ``UtcInstant``."""

    class _Omission(BaseModel):
        guarded: UtcInstant
        forgotten: datetime
        optional_forgotten: datetime | None = None

    assert bare_datetime_fields(_Omission) == ["forgotten", "optional_forgotten"]


def test_the_default_check_catches_a_naive_literal_default() -> None:
    """Path two, on its own: pydantic skips validating a default."""

    class _LiteralDefault(BaseModel):
        when: UtcInstant = datetime(2026, 1, 1)  # noqa: DTZ001 — the unvalidated default is the subject

    assert unvalidated_datetime_defaults(_LiteralDefault) == ["when"]
    assert bare_datetime_fields(_LiteralDefault) == []  # the other path stays green
    assert _LiteralDefault().when.tzinfo is None  # the naive value really does slip through


def test_the_default_check_catches_a_default_factory() -> None:
    """Path two again, by the other default policy — ``default_factory``."""

    class _FactoryDefault(BaseModel):
        when: UtcInstant = Field(default_factory=lambda: datetime(2026, 1, 1))  # noqa: DTZ001

    assert unvalidated_datetime_defaults(_FactoryDefault) == ["when"]
    assert bare_datetime_fields(_FactoryDefault) == []


def test_a_validated_default_passes_both_checks() -> None:
    """The escape hatch works, and it really does validate."""

    class _Validated(BaseModel):
        when: UtcInstant = Field(
            default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC), validate_default=True
        )

    assert unvalidated_datetime_defaults(_Validated) == []
    assert bare_datetime_fields(_Validated) == []
    assert _Validated().when.tzinfo is UTC


def test_a_none_default_is_not_treated_as_an_unvalidated_instant() -> None:
    """``expires_at: UtcInstant | None = None`` is the shape `core` actually uses."""

    class _Optional(BaseModel):
        when: UtcInstant | None = None

    assert unvalidated_datetime_defaults(_Optional) == []
    assert bare_datetime_fields(_Optional) == []
