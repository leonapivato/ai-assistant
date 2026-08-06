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
    NewType,
    TypeAliasType,
    get_args,
    get_origin,
    get_type_hints,
)

import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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

    from pydantic.fields import FieldInfo

AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

#: The ``ge=0`` constraint object itself, as pydantic normalises it onto a field.
#:
#: Taken from a throwaway ``Field`` rather than imported from ``annotated_types``
#: for the reason :func:`_declares_a_lower_bound` gives, and it is the same object
#: the corpus's own declarations carry.
GE_ZERO = Field(ge=0).metadata[0]

#: A count spelled as a distinct static type over ``int``, for the walk's fixture.
#:
#: Module level rather than inside the test: under postponed annotations a model's
#: field types are resolved against its module's namespace, so a locally-bound name
#: is not there to be found.
Count = NewType("Count", int)


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

    Only presence is asked, never the bound's value: ``core`` floors things that
    are not integers at all — ``Settings`` carries ``timedelta`` bounds — and a
    check that read the number would have to decide what to do with them.
    """
    return any(
        getattr(item, "ge", None) is not None or getattr(item, "gt", None) is not None
        for item in metadata
    )


def _the_field_would_accept(field: FieldInfo, value: object) -> bool:
    """Whether ``value`` survives the validation ``field`` declares for itself.

    Pydantic's own machinery rather than a reimplementation of it: the question
    is exactly "would this field have taken this value", and hand-comparing a
    literal against a bound answers a narrower one. It reads the *effective*
    constraint — pydantic hoists ``Annotated[int, Ge(0)]`` metadata onto the
    ``FieldInfo``, so an annotation-level floor is already here — and it refuses
    a default of the wrong type rather than only one of the wrong magnitude.

    **Strict**, because the lax mode that serves a wire boundary is the wrong
    reading here: it coerces ``"0"`` to ``0`` and would pass a default that
    leaves the constructed model holding a ``str`` where its annotation promises
    an ``int``. Nothing in ``core`` declares a default this refuses.

    Validating the *whole* annotation is also what reaches a floor declared on an
    element rather than on the field — ``tuple[Annotated[int, Ge(0)], ...]`` keeps
    its constraint inside the annotation, where ``field.metadata`` is empty and
    pydantic has nothing to hoist. The adapter descends; a reader of
    ``field.metadata`` alone would not.
    """
    declared = (
        Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
    )
    adapter: TypeAdapter[object] = TypeAdapter(declared, config=ConfigDict(strict=True))
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


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
    if isinstance(annotation, NewType | TypeAliasType):
        # Both wrap another type and pydantic validates them as what they wrap, so
        # a floor is owed exactly as it would be on the wrapped ``int`` and the walk
        # has to reach through. They are spelled differently and that is all:
        # ``NewType("Count", int)`` keeps its target on ``__supertype__``, a
        # ``type X = …`` alias on ``__value__``.
        inner = (
            annotation.__supertype__ if isinstance(annotation, NewType) else annotation.__value__
        )
        return _int_leaves(inner, bounded=bounded, seen=seen | {id(annotation)})
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


def int_defaults_their_field_would_refuse(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s bounded int fields whose *default* the field itself would reject.

    **Pydantic does not validate a field default** unless ``validate_default`` is
    set, so a bound is enforced on every value a caller supplies and on nothing
    the caller omits. ``evidence_elided: int = Field(default=-1, ge=0)`` would
    construct, keep its ``ge=0``, refuse an explicit ``-1``, and still hand every
    default-constructed belief the ``-1`` that ``_elision_ceiling`` reads as
    nothing to disclose — the ADR-0107 §2 disclosure suppressed by the field that
    was supposed to guarantee it.

    This is the second of the two independent paths, and it is
    ``test_instant_coverage.py``'s ``unvalidated_datetime_defaults`` applied to a
    different kind of constraint: ADR-0023 §2's three naive instants got in
    through exactly this gap. Either path can regress while the other stays
    green, which is why they are separate functions rather than one verdict.

    The verdict is :func:`_the_field_would_accept`'s, so the check asks whether
    the field would have taken its own default rather than comparing a literal
    against a number. That is what makes it total over the ways a default can be
    inadmissible: below the floor, ``None`` on a non-optional field, or a value of
    the wrong type entirely. Each of those constructs today and leaves the model
    holding it.

    A ``default_factory`` is flagged outright rather than called: its value is
    not readable without running it, and running arbitrary project code is not
    this check's business. ``core`` declares none on an int today, so the strict
    reading costs nothing and fails closed if one appears.

    **Which fields are in scope is decided by the same walk path one uses**, not
    by ``field.metadata``. A floor declared on an element —
    ``tuple[Annotated[int, Ge(0)], ...]`` — leaves ``field.metadata`` empty, so a
    check gated on it would skip the field silently and a default of ``(-1,)``
    would stand. A field path one *fails* is skipped here instead: it has no floor
    for a default to be inadmissible against, and reporting it twice would blur
    which of the two checks regressed.
    """
    hints = get_type_hints(model, include_extras=True)
    # ``validate_default`` is settable per field *and* for a whole model, and the
    # field's own setting is ``None`` rather than ``False`` when it defers. Reading
    # only the field would report every default on a model that validates all of
    # them — a false failure, and the one direction this check must not invent.
    by_default = bool(model.model_config.get("validate_default", False))
    flagged = []
    for name, field in model.model_fields.items():
        bounded_leaves = _int_leaves(
            hints.get(name), bounded=_declares_a_lower_bound(field.metadata)
        )
        if not bounded_leaves or not all(bounded_leaves):
            continue  # not an int field, or path one's subject rather than this one
        validated = by_default if field.validate_default is None else field.validate_default
        if field.is_required() or validated:
            continue  # nothing to omit, or pydantic checks the default itself
        if field.default_factory is not None or not _the_field_would_accept(field, field.default):
            flagged.append(name)
    return flagged


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


@pytest.mark.parametrize("model", _core_models(), ids=lambda model: model.__name__)
def test_no_core_int_default_is_one_its_own_field_would_refuse(model: type[BaseModel]) -> None:
    """Path two: a declared floor the field's own default is not held to."""
    offenders = sorted(int_defaults_their_field_would_refuse(model))
    assert not offenders, f"{model.__name__} has inadmissible int default(s) {offenders}"


def test_no_core_int_field_is_exempt_from_the_default_rule() -> None:
    """The same statement over the whole package, for the same reason as above."""
    escaping = {
        (model.__name__, name)
        for model in _core_models()
        for name in int_defaults_their_field_would_refuse(model)
    }
    assert escaping == set()


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


def test_the_walk_reaches_through_a_newtype() -> None:
    """A ``NewType`` is a static distinction over the same runtime type.

    Pydantic validates it as the supertype, so an unbounded one accepts ``-1``
    exactly as a bare ``int`` would while looking, to a walk that stops at the
    wrapper, like no int field at all.
    """

    class _Wrapped(BaseModel):
        forgotten: Count = Count(0)
        floored: Count = Field(default=Count(0), ge=0)

    assert unbounded_int_fields(_Wrapped) == ["forgotten"]
    assert _Wrapped(forgotten=Count(-1)).forgotten == -1  # really does accept one


def test_a_model_that_validates_every_default_is_not_reported() -> None:
    """``validate_default`` is a model-level setting too, and the field defers to it.

    Reading only ``field.validate_default`` — which is ``None`` rather than
    ``False`` when unset — would report every default on such a model, inventing
    a failure for the one configuration that makes the check unnecessary.
    """

    class _ValidatesAll(BaseModel):
        model_config = ConfigDict(validate_default=True)

        elided: int = Field(default=-1, ge=0)

    assert _ValidatesAll.model_fields["elided"].validate_default is None
    assert int_defaults_their_field_would_refuse(_ValidatesAll) == []
    with pytest.raises(ValidationError):
        _ValidatesAll()  # pydantic itself refuses the default, so nothing is owed


def test_a_bool_field_is_not_treated_as_an_int() -> None:
    """``issubclass(bool, int)`` is true at runtime; the annotation is still ``bool``."""

    class _Flagged(BaseModel):
        degraded: bool = False

    assert unbounded_int_fields(_Flagged) == []


def test_the_default_check_catches_a_literal_default_below_the_floor() -> None:
    """Path two, on its own: the shape pydantic constructs happily and never checks."""

    class _Escaping(BaseModel):
        elided: int = Field(default=-1, ge=0)

    assert int_defaults_their_field_would_refuse(_Escaping) == ["elided"]
    assert unbounded_int_fields(_Escaping) == []  # path one stays green
    assert _Escaping().elided == -1  # the default really does slip through
    with pytest.raises(ValidationError):
        _Escaping(elided=-1)  # while an explicit one is still refused


def test_the_default_check_catches_a_default_factory() -> None:
    """Flagged unread, because reading it means running it."""

    class _Factory(BaseModel):
        elided: int = Field(default_factory=lambda: -1, ge=0)

    assert int_defaults_their_field_would_refuse(_Factory) == ["elided"]
    assert unbounded_int_fields(_Factory) == []


def test_a_validated_default_passes_the_default_check() -> None:
    """The escape hatch works, and it really does validate."""

    class _Validated(BaseModel):
        elided: int = Field(default=0, ge=0, validate_default=True)

    assert int_defaults_their_field_would_refuse(_Validated) == []
    assert _Validated().elided == 0


def test_a_required_int_has_no_default_to_escape() -> None:
    """``ConversationTurn.ordinal`` is the shape: a floor and nothing to omit."""

    class _Required(BaseModel):
        ordinal: int = Field(ge=1)

    assert int_defaults_their_field_would_refuse(_Required) == []
    assert unbounded_int_fields(_Required) == []


def test_a_default_on_the_floor_is_not_flagged() -> None:
    """``ge=0`` with ``default=0`` is the corpus's own shape, and admissible."""

    class _OnTheFloor(BaseModel):
        elided: int = Field(default=0, ge=0)
        limit: int = Field(default=1, gt=0)

    assert int_defaults_their_field_would_refuse(_OnTheFloor) == []


def test_the_default_check_catches_a_none_on_a_non_optional_int() -> None:
    """Not every inadmissible default is merely the wrong magnitude.

    ``None`` is what a field acquires when a ``| None`` is dropped from its
    annotation and the default is left behind, and pydantic will not look at it:
    the model constructs, holds ``None`` where an ``int`` was promised, and every
    arithmetic reader of the count raises instead of disclosing.
    """

    class _NoneDefault(BaseModel):
        elided: int = Field(default=None, ge=0)  # type: ignore[assignment]

    assert int_defaults_their_field_would_refuse(_NoneDefault) == ["elided"]
    assert _NoneDefault().elided is None  # the default really does slip through


def test_the_default_check_catches_a_default_of_the_wrong_type() -> None:
    """The strict reading, on its own: ``"0"`` satisfies ``ge=0`` only after coercion.

    Lax validation would take it, and the model would then hold the *string*
    ``"0"`` — which compares to nothing and serialises as a JSON string on a wire
    surface whose contract says integer.
    """

    class _StringDefault(BaseModel):
        elided: int = Field(default="0", ge=0)  # type: ignore[assignment]

    assert int_defaults_their_field_would_refuse(_StringDefault) == ["elided"]
    # mypy reads the annotation and calls this non-overlapping, which is the
    # defect stated in type-checker terms: the runtime value is not what the
    # field promises, and only the unvalidated default can make that true.
    assert _StringDefault().elided == "0"  # type: ignore[comparison-overlap]


def test_an_annotation_level_floor_is_read_for_the_default_too() -> None:
    """Pydantic hoists ``Annotated`` metadata onto the ``FieldInfo``, so there is no
    second place to look — asserted rather than assumed, since the check would be
    silently one-sided if that ever stopped being true.
    """

    class _AnnotatedFloor(BaseModel):
        elided: Annotated[int, GE_ZERO] = -1

    assert _AnnotatedFloor.model_fields["elided"].metadata == [GE_ZERO]
    assert int_defaults_their_field_would_refuse(_AnnotatedFloor) == ["elided"]


def test_the_default_check_reaches_a_floor_declared_on_a_collections_element() -> None:
    """The one place the hoisting above does *not* happen, and the escape it opens.

    A constraint on the element of a ``tuple`` stays inside the annotation:
    ``field.metadata`` is empty, because there is nothing declared *on the field*
    to lift. A default-check gated on ``field.metadata`` would skip this field
    without reporting anything, and the model would construct holding ``(-1,)``.
    """

    class _NestedFloor(BaseModel):
        counts: tuple[Annotated[int, GE_ZERO], ...] = (-1,)

    assert _NestedFloor.model_fields["counts"].metadata == []  # nothing to hoist
    assert unbounded_int_fields(_NestedFloor) == []  # path one sees the element floor
    assert int_defaults_their_field_would_refuse(_NestedFloor) == ["counts"]
    assert _NestedFloor().counts == (-1,)  # the default really does slip through
    with pytest.raises(ValidationError):
        _NestedFloor(counts=(-1,))  # while an explicit one is still refused


def test_an_admissible_nested_default_is_not_flagged() -> None:
    """The discriminating half of the case above: the empty tuple ``core`` would use."""

    class _NestedOk(BaseModel):
        counts: tuple[Annotated[int, GE_ZERO], ...] = ()

    assert int_defaults_their_field_would_refuse(_NestedOk) == []


# --- the anchors: ADR-0107 §3's zero, on every type that carries it ----------
#
# Each builder goes through ``model_validate`` rather than the constructor, so
# that omitting ``evidence_elided`` is expressible: a keyword-splat into a typed
# constructor is not, and the omission is exactly what the default anchor tests.
# It is the same validation path — ADR-0085 §4b's invariants and ``extra="forbid"``
# both still run.

#: The fields both belief DTOs need beyond ``evidence_elided``, which are the same
#: six: ADR-0085 §4a's "same three names read identically on both types" extends to
#: everything the listing and the detail view share.
_BELIEF_FIELDS: dict[str, object] = {
    "id": "rec-1",
    "band": BeliefBand.DERIVED,
    "kind": MemoryKind.SEMANTIC,
    "content": "the office is in Boston",
    "confidence": 0.5,
    "last_updated": AT,
}


def _provenance(**overrides: int) -> Provenance:
    """The record's own copy of the count (ADR-0086 §4)."""
    return Provenance.model_validate(
        {
            "source": MemorySource.OBSERVED,
            "confidence": 0.6,
            "last_updated": AT,
            **overrides,
        }
    )


def _belief(**overrides: int) -> Belief:
    """The single-belief view — the fuller answer, per ADR-0077 §6."""
    return Belief.model_validate(_BELIEF_FIELDS | overrides)


def _summary(**overrides: int) -> BeliefSummary:
    """The listing row, which has no evidence to derive a count from (ADR-0085 §4a)."""
    return BeliefSummary.model_validate(_BELIEF_FIELDS | overrides)


#: What one of the anchor builders returns: a type carrying ``evidence_elided``.
ElisionCarrier = Provenance | Belief | BeliefSummary

#: Every type in ``core`` carrying ``evidence_elided``, by name.
#:
#: ``Provenance`` is here despite ``test_types.py`` already refusing a negative
#: value on it: the overlap is what buys the completeness assertion below, which
#: is the part that cannot rot. Its case there is one clause of a *defaults*
#: test and reads as part of that narrative; this set is the claim that the three
#: carriers are three.
ELISION_CARRIERS: dict[str, Callable[..., ElisionCarrier]] = {
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
def test_a_negative_elision_is_refused(build: Callable[..., ElisionCarrier]) -> None:
    """ADR-0107 §3's ``ge=0``, as behaviour rather than as a declaration.

    The sweep above asserts the floor is declared; this asserts the declared
    floor is the *right* one and that the whole model applies it. A count of
    citations that are no longer carried cannot be negative, and a value that
    was would be read by ``_elision_ceiling`` as nothing to disclose.
    """
    with pytest.raises(ValidationError):
        build(evidence_elided=-1)


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_a_non_default_elision_is_carried_exactly(
    build: Callable[..., ElisionCarrier],
) -> None:
    """ADR-0107 §8's rule for every case that touches this field.

    "Every case below constructs a non-zero, non-default ``evidence_elided`` and
    asserts the exact number" — a fixture left at the default passes whether the
    field is carried or silently dropped, which is a test that cannot fail.
    """
    assert build(evidence_elided=3).evidence_elided == 3


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_the_bound_is_inclusive_of_zero(build: Callable[..., ElisionCarrier]) -> None:
    """The discriminating half: ``ge=0`` and not ``gt=0``.

    Zero is the overwhelmingly common value — every record that has never had a
    citation displaced — so a floor tightened by one would refuse almost the
    whole corpus. This is one of the two cases ADR-0107 §8's non-default rule
    does not govern, because the default *is* its subject.
    """
    assert build(evidence_elided=0).evidence_elided == 0


@pytest.mark.parametrize("build", ELISION_CARRIERS.values(), ids=list(ELISION_CARRIERS))
def test_the_declared_default_is_zero(build: Callable[..., ElisionCarrier]) -> None:
    """ADR-0107 §3 fixes the default as well as the floor: ``evidence_elided: int = 0``.

    The generic path-two sweep asserts no ``core`` int default escapes its own
    bound, which would already catch a default of ``-1``. This is narrower and
    checks what that rule cannot: a default of ``4`` satisfies ``ge=0`` and would
    still make every record claim four citations it never elided, inventing a
    disclosure rather than suppressing one.

    The second case ADR-0107 §8's non-default rule does not govern, and for the
    same reason as the one above — this test's subject *is* what happens when the
    field is omitted, so supplying a value would test something else.
    """
    assert build().evidence_elided == 0
