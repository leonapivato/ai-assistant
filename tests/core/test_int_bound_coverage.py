"""No `core` integer field may be silently unbounded below (issue #755).

ADR-0107 §3 makes ``ge=0`` part of the binding DTO contract — ``BeliefSummary``
and ``Belief`` "each gain a field ``evidence_elided: int = 0`` with ``ge=0``" —
and both types carry it today. What nothing asserted is that they *enforce* it:
the only negative-value case in the tree was ``Provenance``'s, so dropping the
constraint from either belief DTO in a refactor left the gate green.

**A negative elision is a floor failing open**, which is the direction ADR-0073
§4 forgives least. ``interfaces/cli.py``'s ``_elision_ceiling`` guards with
``if elided <= 0: return ""``, deliberately defensive rather than ``== 0``; with
the constraint in force that branch is unreachable for a negative value, and
without it a negative ``evidence_elided`` silently suppresses the disclosure
ADR-0107 §2 owes a ``DERIVED`` belief.

**Pinning the one field would rot, so this pins the rule instead.** ADR-0085 §4c
records what happened to the one field list that ADR carried — falsified in a
single review round, having missed two fields — and draws the conclusion "a rule
over 'every string' survives, and a list of fields rots". ``evidence_elided`` is
the *second* count added to these two types and ADR-0085 §4's table declares
``ge=0`` on several more, so a per-field pin loses the same race one field at a
time. This module takes the shape ``test_instant_coverage.py`` and
``test_text_encodability_coverage.py` use, for the same reason: it discovers
every ``int`` field on every model in ``core`` and fails on one that declares no
lower bound, so the omission fails the gate rather than depending on a reviewer
noticing.

**Coverage rather than enforcement, and the distinction is the whole point.** A
sweep that took every field *declaring* a bound and checked the bound bites
would be vacuous against exactly the regression #755 names: drop ``ge=0`` and
the field stops declaring a bound, so it drops out of the swept set and the
sweep stays green. The claim has to be that the bound is *there*.

**A lower bound, not ``ge=0`` specifically.** ``ConversationTurn.ordinal`` is
``ge=1`` and ``Settings.hub_max_frame_bytes`` is ``ge=1024``; requiring zero
everywhere would be a rule the surface does not hold. The zero itself is pinned
where ADR-0107 §3 fixes it, by the behavioural anchors at the foot of this
module.

**Scoped to ``int``, and the exclusion of ``float`` is a decision.**
:attr:`~ai_assistant.core.types.MemoryBase.score` is a relevance score populated
by retrieval on the store's own scale (ADR-0005 §1) and has no contract range,
so a rule over every ``float`` would need an exemption list — and an exemption
list is the thing ADR-0085 §4c and ``test_instant_coverage.py``'s deleted
deferral both warn about. Every ``int`` this surface carries is a cardinal
quantity: a count, a version, an ordinal or a limit. The bounded floats
(``confidence``, ``importance``, ``strength``) keep their ``ge``/``le`` and are
simply not this module's subject.

**There is no exemption list**, and the one thing the walk declines to enter is
not one. :data:`~ai_assistant.core.types.FrozenJson` reaches ``int`` because a
client's JSON may contain a number; that ``int`` is a value in an audit record's
payload rather than a field of this surface, and there is no quantity to bound.
The walk stops at the alias, which covers both
:data:`~ai_assistant.core.types.FrozenJsonValue` and
:data:`~ai_assistant.core.types.FrozenJsonMapping` by one rule rather than two.
"""

from __future__ import annotations

import pkgutil
from datetime import UTC, datetime
from importlib import import_module
from typing import (
    TYPE_CHECKING,
    Annotated,
    TypeAliasType,
    get_args,
    get_origin,
    get_type_hints,
)

import pytest
from pydantic import BaseModel, Field, ValidationError

import ai_assistant.core
from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    BeliefSummary,
    FrozenJson,
    FrozenJsonMapping,
    MemoryKind,
    MemorySource,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

#: The ``ge=0`` constraint object itself, as pydantic normalises it onto a field.
#:
#: Taken from a throwaway ``Field`` rather than imported from ``annotated_types``
#: for the reason :func:`_declares_a_lower_bound` gives, and it is the same object
#: the corpus's own declarations carry.
GE_ZERO = Field(ge=0).metadata[0]


def _declares_a_lower_bound(metadata: Iterable[object]) -> bool:
    """Whether any entry in ``metadata`` is a ``ge``/``gt`` constraint.

    Duck-typed on the attribute rather than isinstance-checked against
    ``annotated_types``: that package reaches the environment only as a
    transitive dependency of pydantic and is not declared in ``pyproject.toml``,
    so importing it here would be a test depending on something the project does
    not ask for.

    The comparison is ``is not None`` and **not** truthiness, because the bound
    this module exists for is ``ge=0`` — the one value a truthiness test would
    read as absent.
    """
    return any(
        getattr(item, "ge", None) is not None or getattr(item, "gt", None) is not None
        for item in metadata
    )


def _int_leaves(
    annotation: object, *, bounded: bool, seen: frozenset[int] = frozenset()
) -> list[bool]:
    """For every ``int`` in ``annotation``, whether a lower bound is in scope for it.

    Walks unions, ``Annotated``, generic parameters and type aliases, so
    ``int | None`` and ``tuple[int, ...]`` are reached while
    ``Annotated[int, Ge(0)]`` is recognised as bounded. ``seen`` breaks the cycle
    in a recursive alias, and is what stops :data:`FrozenJson` recursing forever
    on the branches it takes before the stop below.

    The walk **stops at** :data:`FrozenJson` and reports nothing for it: its
    ``int`` is a number inside a client's JSON payload, not a field of this
    surface.

    ``bool`` is a subclass of ``int`` at runtime, but a field *annotated* ``bool``
    is the type ``bool`` and not the type ``int``, so the identity test below
    does not reach it — which is correct, since a flag has no magnitude to bound.
    A ``Literal[1]`` argument is likewise the *value* ``1`` rather than the type.
    """
    if annotation is FrozenJson or id(annotation) in seen:
        return []
    if isinstance(annotation, TypeAliasType):
        return _int_leaves(annotation.__value__, bounded=bounded, seen=seen | {id(annotation)})
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return _int_leaves(args[0], bounded=bounded or _declares_a_lower_bound(args[1:]), seen=seen)
    if origin is not None:
        return [
            leaf
            for arg in get_args(annotation)
            if arg is not Ellipsis
            for leaf in _int_leaves(arg, bounded=bounded, seen=seen | {id(annotation)})
        ]
    if annotation is int:
        return [bounded]
    return []


def unbounded_int_fields(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s fields holding an ``int`` that declares no lower bound.

    The walk is seeded with the field's own metadata, which is where the corpus
    puts the constraint — ``evidence_elided: int = Field(default=0, ge=0, …)``
    carries ``Ge`` on the ``FieldInfo`` rather than inside the annotation.
    """
    hints = get_type_hints(model, include_extras=True)
    return [
        name
        for name, field in model.model_fields.items()
        if not all(_int_leaves(hints.get(name), bounded=_declares_a_lower_bound(field.metadata)))
    ]


def _core_models() -> list[type[BaseModel]]:
    """Every pydantic model reachable in the ``ai_assistant.core`` package.

    The same walk ``test_instant_coverage.py`` makes for its own rule, and kept
    separate rather than shared: the two modules assert unrelated properties, and
    a shared discovery helper would let a change made for one silently narrow the
    other's scope.
    """
    found: dict[str, type[BaseModel]] = {}
    for info in pkgutil.walk_packages(ai_assistant.core.__path__, f"{ai_assistant.core.__name__}."):
        module = import_module(info.name)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
                found[f"{value.__module__}.{value.__qualname__}"] = value
    return list(found.values())


def test_the_scan_actually_finds_the_core_int_carriers() -> None:
    """A discovery check that silently found nothing would pass forever.

    ``Settings`` is named alongside the DTOs because this rule covers the whole
    ``core`` package: its thirteen bounded ints are limits read from the
    environment, and an unbounded one there is the same fault in a different
    file.
    """
    names = {model.__name__ for model in _core_models()}
    assert {"Belief", "BeliefSummary", "Provenance", "ObservationReport", "Settings"} <= names


@pytest.mark.parametrize("model", _core_models(), ids=lambda model: model.__name__)
def test_every_core_int_field_declares_a_lower_bound(model: type[BaseModel]) -> None:
    """An ``int`` field with no floor fails the gate, naming itself."""
    offenders = sorted(unbounded_int_fields(model))
    assert not offenders, f"{model.__name__} has unbounded int field(s) {offenders}"


def test_no_core_int_field_is_exempt_from_the_rule() -> None:
    """Stated once over the whole package, not model by model.

    The per-model check above fails on the offending model; this one asserts the
    property an exemption set would erode — that *nothing* in ``core`` opts out.
    Keeping it explicit is what stops a future deferral re-appearing as an
    exemption argument threaded back through the per-model check.
    """
    unbounded = {
        (model.__name__, name) for model in _core_models() for name in unbounded_int_fields(model)
    }
    assert unbounded == set()


# --- negative fixtures: the sweep must discriminate, not just pass -----------
# A check that accepted everything would look identical on the corpus above, so a
# green sweep proves nothing until it has been seen to refuse. Each fixture
# isolates one path, so either can regress while the other stays green.


def test_the_sweep_catches_a_bare_int() -> None:
    """The plain omission: a count declared with no floor at all."""

    class _Omission(BaseModel):
        bounded: int = Field(default=0, ge=0)
        forgotten: int = 0

    assert unbounded_int_fields(_Omission) == ["forgotten"]


def test_the_sweep_reaches_an_int_inside_a_union_or_a_tuple() -> None:
    """A floor is owed wherever the ``int`` is, not only where it is the whole field."""

    class _Nested(BaseModel):
        optional: int | None = None
        collected: tuple[int, ...] = ()

    assert unbounded_int_fields(_Nested) == ["optional", "collected"]


def test_an_annotated_bound_counts_as_declared() -> None:
    """The constraint may sit in the annotation rather than on the ``FieldInfo``.

    Which is the only way to floor an ``int`` *inside* a collection: a ``ge`` on
    the ``FieldInfo`` of a ``tuple[int, ...]`` field would constrain the tuple.

    A bound written as a nested ``Field(ge=0)`` rather than as the constraint
    object is **not** recognised, and deliberately not accommodated: pydantic
    keeps a ``FieldInfo``'s constraints one level further down, and the corpus
    declares none that way. The failure mode of the simpler rule is a *false
    report* of an unbounded field, which fails the gate loudly — never a bound
    silently accepted as present.
    """

    class _Annotated(BaseModel):
        collected: tuple[Annotated[int, GE_ZERO], ...] = ()

    assert unbounded_int_fields(_Annotated) == []


def test_a_gt_bound_counts_and_a_ceiling_alone_does_not() -> None:
    """``Settings`` uses both spellings of a floor; an ``le`` is not one.

    A field bounded only above is the interesting near-miss: it looks
    constrained, and it still admits every negative value.
    """

    class _Bounds(BaseModel):
        floored_by_gt: int = Field(default=1, gt=0)
        ceiling_only: int = Field(default=0, le=10)

    assert unbounded_int_fields(_Bounds) == ["ceiling_only"]


def test_a_zero_lower_bound_is_not_read_as_a_missing_one() -> None:
    """The truthiness trap, pinned: ``ge=0`` is the bound this module exists for."""
    assert _declares_a_lower_bound([GE_ZERO]) is True


def test_the_walk_does_not_descend_into_a_json_holder() -> None:
    """A number in a client's payload is not a field of this surface.

    Without the stop, every ``parameters`` and ``output`` field in ``core`` would
    be reported unbounded and the rule could only be stated with an exemption
    list.
    """

    class _Holder(BaseModel):
        parameters: FrozenJsonMapping = Field(default_factory=dict)
        payload: FrozenJson = None

    assert unbounded_int_fields(_Holder) == []


def test_a_bool_field_is_not_treated_as_an_int() -> None:
    """``issubclass(bool, int)`` is true at runtime; the annotation is still ``bool``."""

    class _Flagged(BaseModel):
        degraded: bool = False

    assert unbounded_int_fields(_Flagged) == []


# --- the anchors: ADR-0107 §3's zero, on every type that carries it ----------


def _provenance(elided: int) -> Provenance:
    """The record's own copy of the count (ADR-0086 §4)."""
    return Provenance(
        source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT, evidence_elided=elided
    )


def _belief(elided: int) -> Belief:
    """The single-belief view — the fuller answer, per ADR-0077 §6."""
    return Belief(
        id="rec-1",
        band=BeliefBand.DERIVED,
        kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        confidence=0.5,
        last_updated=AT,
        evidence_elided=elided,
    )


def _summary(elided: int) -> BeliefSummary:
    """The listing row, which has no evidence to derive a count from (ADR-0085 §4a)."""
    return BeliefSummary(
        id="rec-1",
        band=BeliefBand.DERIVED,
        kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        confidence=0.5,
        last_updated=AT,
        evidence_elided=elided,
    )


#: What one of the anchor builders returns: a type carrying ``evidence_elided``.
ElisionCarrier = Provenance | Belief | BeliefSummary

#: Every type in ``core`` carrying ``evidence_elided``, by name.
#:
#: ``Provenance`` is here despite ``test_types.py`` already refusing a negative
#: value on it: the overlap is what buys the completeness assertion below, which
#: is the part that cannot rot. Its case there is one clause of a *defaults*
#: test and reads as part of that narrative; this set is the claim that the three
#: carriers are three.
ELISION_CARRIERS: dict[str, Callable[[int], ElisionCarrier]] = {
    "Provenance": _provenance,
    "Belief": _belief,
    "BeliefSummary": _summary,
}


def test_every_type_carrying_an_elision_is_anchored_here() -> None:
    """A fourth carrier must join the cases below rather than arrive uncovered.

    ADR-0107 §3 put the field on two types at once, so the shape that leaves a
    carrier untested is not hypothetical — it is what #755 recorded.
    """
    carriers = {
        model.__name__ for model in _core_models() if "evidence_elided" in model.model_fields
    }
    assert carriers == set(ELISION_CARRIERS)


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_a_negative_elision_is_refused(build: Callable[[int], ElisionCarrier]) -> None:
    """ADR-0107 §3's ``ge=0``, as behaviour rather than as a declaration.

    The sweep above asserts the floor is declared; this asserts the declared
    floor is the *right* one and that the whole model applies it. A count of
    citations that are no longer carried cannot be negative, and a value that
    was would be read by ``_elision_ceiling`` as nothing to disclose.
    """
    with pytest.raises(ValidationError):
        build(-1)


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_a_non_default_elision_is_carried_exactly(
    build: Callable[[int], ElisionCarrier],
) -> None:
    """ADR-0107 §8's rule for every case that touches this field.

    "Every case below constructs a non-zero, non-default ``evidence_elided`` and
    asserts the exact number" — a fixture left at the default passes whether the
    field is carried or silently dropped, which is a test that cannot fail.
    """
    assert build(3).evidence_elided == 3


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_the_bound_is_inclusive_of_zero(build: Callable[[int], ElisionCarrier]) -> None:
    """The discriminating half: ``ge=0`` and not ``gt=0``.

    Zero is the overwhelmingly common value — every record that has never had a
    citation displaced — so a floor tightened by one would refuse almost the
    whole corpus. This is the one case ADR-0107 §8's non-default rule does not
    govern, because the default *is* its subject.
    """
    assert build(0).evidence_elided == 0
