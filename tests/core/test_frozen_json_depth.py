"""A frozen JSON value is refused past a fixed depth ceiling (ADR-0196).

What `FrozenJson` accepted used to be decided between pydantic-core's own cycle
detector — an unpinned upstream constant, documented in no file here and asserted
by no test here — and `_deep_freeze`'s Python recursion, which moves with
`sys.getrecursionlimit()`. ADR-0196 makes the bound ours: one constant in `core`,
measured twice, refusing with a message that names depth rather than reporting a
depth failure as a cycle or as an encoding failure.

Every test below is one of ADR-0196 §5's pins or the discrimination check that keeps
one honest, and each was verified to fail when the code it covers is reverted. The
two positions are pinned separately because they fail separately: the **front**
measurement is what makes the refusal independent of the recursion limit, and the
**second** is defence in depth against the front's canonical set falling behind.

`sys.setrecursionlimit` appears here deliberately, and only below the ceiling. At the
default limit an implementation that counted depth recursively, or that ran the check
*after* the recursive alias, passes every other pin in this file — the depth
`ValueError` still arrives and nothing distinguishes it from a conforming one. Lower
the limit under the ceiling and both non-conforming placements fail (§5(d)): the
recursive counter exhausts the stack, and so does `_deep_freeze` behind an
after-the-fact check.

**One measurement here differs from ADR-0196's account of it**, and the pins are
written to what was measured. Pydantic-core's recursive-alias walk gives up at 256
containers *whatever* `sys.getrecursionlimit()` is — it is Rust and costs no Python
frame per level — so it is not the alias that made acceptance vary with a
process-global. `_deep_freeze` is: it survives 997 containers at the default limit
and 197 at `setrecursionlimit(200)`, which is where the ADR's own "194 at 200"
figure comes from. That leaves §1's decision untouched and its ground (b) intact —
acceptance did vary with a process-global, and the front measurement is what stops
it — but it means a value past the ceiling is refused by *this* module's front
check where an after-the-fact one would meet `_deep_freeze`'s recursion instead of
the alias's. Filed as an amendment note against the ADR's prose (#1620).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    _MAX_JSON_DEPTH,
    FrozenDict,
    FrozenJson,
    PlanStep,
    ToolOutcome,
    ToolResult,
    _faithful_json_depth,
    _freeze_json,
    _json_depth,
)

#: What §1's over-depth refusal says, matched rather than quoted whole.
TOO_DEEP = "nests containers deeper than 128"

#: What §1's third clause says when it will not guess at a value's contents.
UNREADABLE = "cannot be read the way they are validated"

#: How deep ADR-0196's two hostile cases nest what they under-report.
#:
#: Above the ceiling, and above the 256 containers at which pydantic-core's own
#: recursive-alias walk gives up — which is what makes the pins below
#: discriminate. A front measurement that believed the value's own account would
#: let it through, and what arrives then is the alias's thousand-error refusal
#: naming neither depth nor the ceiling, rather than the single refusal that
#: names both.
HOSTILE_DEPTH = 300

#: A recursion limit below the ceiling, which is what §5(d), (f) and (g) require.
#:
#: Under pytest the interpreter sits about 32 frames deep, so this leaves ample
#: room for the test itself, for building a ``ValidationError`` and for pytest's
#: own reporting — while being far too little for any walk proportional to the
#: depth of the values below. A conforming implementation never needs the
#: headroom; a recursive one exhausts it.
LOW_LIMIT = 120


@contextmanager
def recursion_limit(limit: int) -> Iterator[None]:
    """Run the block with ``sys.setrecursionlimit(limit)``, restoring it after."""
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        yield
    finally:
        sys.setrecursionlimit(original)


def nested(levels: int) -> Any:
    """A mapping nesting exactly ``levels`` containers, built without recursing.

    Built iteratively on purpose: a helper that recursed would fail under
    :data:`LOW_LIMIT` for a reason that has nothing to do with what is being
    pinned.
    """
    value: Any = 1
    for _ in range(levels):
        value = {"k": value}
    return value


def step(parameters: object) -> PlanStep:
    """A minimal :class:`PlanStep` holding ``parameters``, the first of nine holders."""
    return PlanStep(id="s1", intent="i", capability="cap", parameters=parameters)  # type: ignore[arg-type]  # the hostile inputs below are the point


class UnderReportingDict(dict[str, Any]):
    """A ``dict`` subclass whose ``values()`` reports nothing it holds.

    The second of ADR-0196's two hostile cases, and the reason the front
    measurement reads ``dict.values`` rather than the instance's own method.
    Measured against pre-ADR ``main``: an instance of this holding 201 containers
    measured as **depth 1** through the protocol walk and froze to depth 201 — a
    ceiling the input talked its way past. The pin below nests
    :data:`HOSTILE_DEPTH` rather than 201, for the reason that constant gives.
    """

    def values(self) -> Any:
        """Report an empty mapping, whatever is actually held."""
        return iter(())


class RaisingDict(dict[str, Any]):
    """A ``dict`` subclass whose ``values()`` raises.

    The first hostile case. This one validates **today** — pydantic-core
    enumerates any dict instance through the concrete ``dict`` and never calls the
    override — so a front check written over the protocol walk would leak a
    ``RuntimeError`` out of a validator for a value the type accepts.
    """

    def values(self) -> Any:
        """Raise, as a ``dict`` subclass is free to."""
        msg = "values() is not available"
        raise RuntimeError(msg)


class LyingFrozenDict(FrozenDict):
    """A :class:`FrozenDict` subclass whose mapping protocol contradicts its slot.

    Its concrete ``_items`` holds one shallow pair; its ``items()``, ``keys()``
    and ``__getitem__`` report a deep mapping. Pydantic reads it through the
    mapping protocol — the half a subclass can rewrite — so it validates to the
    deep form. Reading the concrete slot does not rescue the measurement, which
    is why §1 admits only the *exact* type and refuses every subclass.
    """

    __slots__ = ()

    _deep: ClassVar[Any] = {"x": nested(HOSTILE_DEPTH)}

    def __getitem__(self, key: str) -> Any:
        """Report the deep mapping, whatever the slot holds."""
        return self._deep[key]

    def __iter__(self) -> Iterator[str]:
        """Report the deep mapping's keys."""
        return iter(self._deep)

    def __len__(self) -> int:
        """Report the deep mapping's size."""
        return len(self._deep)


class RaisingMapping(Mapping[str, Any]):
    """A mapping that is not a ``dict`` and raises the moment it is enumerated."""

    def __getitem__(self, key: str) -> Any:
        """Raise rather than answer."""
        raise RuntimeError(key)

    def __iter__(self) -> Iterator[str]:
        """Raise rather than enumerate."""
        msg = "iteration is not available"
        raise RuntimeError(msg)

    def __len__(self) -> int:
        """Raise rather than answer."""
        msg = "length is not available"
        raise RuntimeError(msg)


class InterruptingMapping(Mapping[str, Any]):
    """A mapping whose enumeration raises a ``BaseException`` rather than an error.

    It enumerates far enough to be read and then raises on the value, which is
    where a shutdown lands if one arrives mid-measurement.
    """

    def __getitem__(self, key: str) -> Any:
        """Raise the exception a shutdown raises."""
        raise KeyboardInterrupt

    def __iter__(self) -> Iterator[str]:
        """Report one key, so the value is actually reached."""
        return iter(("x",))

    def __len__(self) -> int:
        """Report one key, as :meth:`__iter__` does."""
        return 1


# --- §5(a): the ceiling holds where it says it does --------------------------


def test_a_value_at_the_ceiling_freezes_and_one_container_deeper_is_refused() -> None:
    """The bound is enforced, and enforced at the level it claims (§5(a))."""
    at_ceiling = nested(_MAX_JSON_DEPTH)
    assert _faithful_json_depth(at_ceiling, _MAX_JSON_DEPTH * 2) == _MAX_JSON_DEPTH
    assert step(at_ceiling).parameters

    past = nested(_MAX_JSON_DEPTH + 1)
    with pytest.raises(ValidationError, match=TOO_DEEP) as refusal:
        step(past)
    assert refusal.value.error_count() == 1


def test_the_refusal_names_depth_and_the_ceiling_rather_than_a_cycle() -> None:
    """§1 requires the reason, not merely the refusal.

    What refused a deep payload before this decision was a *cycle* detector
    reporting "Recursion error - cyclic reference detected" about a value with no
    cycle in it, or the encoder refusal saying the value "has no JSON encoding"
    about a value that encodes fine. Neither told a caller what was wrong.
    """
    with pytest.raises(ValidationError) as refusal:
        step(nested(_MAX_JSON_DEPTH + 1))
    message = str(refusal.value)
    assert str(_MAX_JSON_DEPTH) in message
    assert "cyclic reference" not in message
    assert "no JSON encoding" not in message


def test_a_value_at_the_ceiling_can_be_dumped_and_revalidated() -> None:
    """The ceiling sits below the band where a holder accepts what it cannot write.

    Measured before this decision: a ``PlanStep`` was constructible at 256
    containers and ``model_dump_json()`` on the result then raised — "accepted,
    then unusable", the shape ADR-0014 §2 exists to close (#1610). The ceiling is
    half of the tightest mechanism that walks the value, so a value the type
    accepts survives the whole round trip.
    """
    original = step(nested(_MAX_JSON_DEPTH))
    assert PlanStep.model_validate_json(original.model_dump_json()) == original


# --- §5(d): the refusal does not depend on a process-global ------------------


def test_a_value_past_the_ceiling_is_refused_under_a_low_recursion_limit() -> None:
    """§5(d): the pin that tests §1's ordering and §2's iterativeness at once.

    With the limit set beneath the ceiling, a check placed after the recursive
    ``FrozenJson`` alias never gets to answer: below the alias's own 256 the value
    reaches ``_deep_freeze``, which recurses a frame per level and raises
    ``RecursionError``, and above it the alias refuses first with a thousand errors
    naming neither depth nor the ceiling. A recursive depth counter exhausts the
    stack in its own right. Both non-conforming placements fail here and nowhere
    else — verified by reverting each in turn.
    """
    for levels in (_MAX_JSON_DEPTH + 1, 300, 5000):
        with recursion_limit(LOW_LIMIT), pytest.raises(ValidationError, match=TOO_DEEP) as refusal:
            step(nested(levels))
        assert refusal.value.error_count() == 1


def test_what_the_unguarded_alias_says_instead_is_the_refusal_being_replaced() -> None:
    """Why the pins above insist on a *single* error, measured rather than asserted.

    The recursive alias with no front check on it — which is what both aliases
    were before this decision — gives, on the same value, over a thousand errors
    headed "Input should be a valid string", of which exactly one is the recursion
    diagnostic: a refusal naming neither depth nor the ceiling, about a value
    whose only defect is its depth. Every pin above therefore asserts that the
    ceiling's refusal is the *only* error, because "a matching message somewhere
    among 1276" is exactly what a non-conforming implementation also produces.
    """
    unguarded: TypeAdapter[Mapping[str, FrozenJson]] = TypeAdapter(Mapping[str, FrozenJson])
    with pytest.raises(ValidationError) as refusal:
        unguarded.validate_python(nested(HOSTILE_DEPTH))
    assert TOO_DEEP not in str(refusal.value)
    assert refusal.value.error_count() > 1


# --- §5(e): an enumeration that raises leaks nothing --------------------------


def test_a_mapping_whose_enumeration_raises_is_an_ordinary_construction_refusal() -> None:
    """§5(e): the caller sees a ``ValidationError``, not a ``RuntimeError``."""
    with pytest.raises(ValidationError, match=UNREADABLE) as refusal:
        step({"a": RaisingMapping()})
    assert refusal.value.error_count() == 1


def test_the_second_measurement_refuses_an_over_deep_validated_value() -> None:
    """§1's second clause, pinned where only it can answer.

    ``_freeze_json`` is the ``AfterValidator``, and the ceiling holds there too —
    for the structure that is actually frozen, whatever the raw input presented to
    the front measurement. Called directly, as the validator calls it, this is the
    half of the pair that survives the front's canonical set falling behind a
    pydantic version that built a container form the front measured as a leaf.
    """
    with pytest.raises(ValueError, match=TOO_DEEP):
        _freeze_json(nested(_MAX_JSON_DEPTH + 1))
    assert _freeze_json(nested(_MAX_JSON_DEPTH))


def test_the_second_measurement_leaks_no_exception_either() -> None:
    """§1's fourth clause holds at *both* measurements, not only the front one.

    The front refuses a non-``dict`` mapping without enumerating it, so this is
    pinned where the enumeration is actually reached: :func:`_freeze_json` called
    directly on a value that lies, which is the position the second measurement
    occupies.
    """
    with pytest.raises(ValueError, match="could not be measured") as refusal:
        _freeze_json(RaisingMapping())
    assert isinstance(refusal.value.__cause__, RuntimeError)


class UnprintableError(ValueError):
    """A ``ValueError`` that cannot be rendered.

    Pydantic renders whatever a validator raises, so an error whose ``__str__``
    raises escapes as *that* exception — which is how a ``RuntimeError`` gets out
    of a validator even when everything raised is nominally a ``ValueError``.
    """

    def __str__(self) -> str:
        """Raise rather than render."""
        msg = "str() is not available"
        raise RuntimeError(msg)


class HostileClass:
    """A value whose very ``isinstance`` check raises an unrenderable error.

    ``isinstance`` against a concrete type reads ``__class__`` when the instance's
    real type does not match, and against an ABC it reads it unconditionally, so
    this is the one point in a measurement where caller-controlled code runs.
    """

    @property  # type: ignore[misc]  # a read-only, raising __class__ is the point
    def __class__(self) -> Any:
        """Raise an error that cannot be printed."""
        raise UnprintableError("boom")


def test_a_value_whose_isinstance_check_raises_is_still_an_ordinary_refusal() -> None:
    """§1's fourth clause, at the one point a measurement runs caller code.

    Re-raising every ``ValueError`` a measurement meets is not enough, because
    an unrenderable one escapes as its own ``__str__``'s exception when pydantic
    formats the error — a ``RuntimeError`` arriving out of construction for a
    value the ceiling was supposed to refuse politely. The refusal therefore
    carries a constant message and keeps the original only as ``__cause__``,
    where nothing renders it.
    """
    with pytest.raises(ValidationError, match="could not be measured") as refusal:
        step({"a": HostileClass()})
    assert refusal.value.error_count() == 1


def test_a_base_exception_propagates_unchanged() -> None:
    """ADR-0029 §3, restated by §1: a ``BaseException`` is never converted."""
    with pytest.raises(KeyboardInterrupt):
        _freeze_json(InterruptingMapping())


def test_a_dict_subclass_with_a_raising_values_still_validates() -> None:
    """The trap §5(e) exists for, in the direction that is easy to miss.

    This value is *accepted* — before this decision and after it. An
    implementation whose front measurement went through the protocol walk would
    refuse it with a leaked ``RuntimeError``, so a pin that only checked the
    refusals would call that conforming.
    """
    assert step({"a": RaisingDict({"x": 1})}).parameters == FrozenDict({"a": FrozenDict({"x": 1})})


# --- §5(f): a dict subclass is measured on what it holds ---------------------


@pytest.mark.parametrize("limit", [sys.getrecursionlimit(), LOW_LIMIT])
def test_a_dict_subclass_is_measured_on_its_concrete_contents(limit: int) -> None:
    """§5(f): ``dict.values`` and not the instance's own ``values()``.

    Pinned under the low limit as well as the default because that is where the
    difference shows: at the default limit an unfaithful front measurement is
    rescued by the second one and the pin passes for the wrong reason. Beneath the
    ceiling the rescue costs stack it does not have, and what arrives is either a
    ``RecursionError`` or the alias's own thousand-error refusal — which is why
    the refusal here has to be the **only** error rather than one among them.
    """
    under_reporting = UnderReportingDict({"x": nested(HOSTILE_DEPTH)})
    with recursion_limit(limit), pytest.raises(ValidationError, match=TOO_DEEP) as refusal:
        step({"a": under_reporting})
    assert refusal.value.error_count() == 1


def test_a_dict_subclass_within_the_ceiling_is_still_accepted() -> None:
    """Measuring a subclass faithfully is not the same as refusing every subclass."""
    assert step(UnderReportingDict({"x": {"y": 1}})).parameters == FrozenDict({"x": {"y": 1}})


# --- §5(g): a frozen or sequence subclass is refused, not measured -----------


@pytest.mark.parametrize("limit", [sys.getrecursionlimit(), LOW_LIMIT])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(LyingFrozenDict({"x": 1}), id="frozendict-subclass"),
        pytest.param(type("ListSubclass", (list,), {})([1]), id="list-subclass"),
        pytest.param(type("TupleSubclass", (tuple,), {})((1,)), id="tuple-subclass"),
    ],
)
def test_a_frozen_or_sequence_subclass_is_refused_at_the_front(value: Any, limit: int) -> None:
    """§5(g): the exact type, because a subclass can rewrite the half pydantic reads.

    ``LyingFrozenDict`` is ADR-0196's own case: one pair in the concrete slot,
    :data:`HOSTILE_DEPTH` containers through the mapping protocol, and it validates
    to the deep form. Nothing concrete makes the two agree, so the only faithful
    answer for a non-``dict`` mapping is to refuse — which is why this pin holds
    for the *shallow* subclasses beside it too.
    """
    with recursion_limit(limit), pytest.raises(ValidationError, match=UNREADABLE) as refusal:
        step({"a": value})
    assert refusal.value.error_count() == 1


def test_the_lying_frozen_dict_really_does_lie() -> None:
    """A fixture that had stopped lying would make the pin above pass for nothing."""
    lying = LyingFrozenDict({"x": 1})
    assert _json_depth(lying, _MAX_JSON_DEPTH * 2) > _MAX_JSON_DEPTH
    assert len(lying._items) == 1


def test_the_exact_frozen_and_sequence_types_are_still_accepted() -> None:
    """What ``_deep_freeze`` and ``_thaw_json`` produce stays inside the set."""
    frozen = step({"a": FrozenDict({"b": 1}), "c": [1, 2], "d": (3, 4)}).parameters
    assert frozen == FrozenDict({"a": FrozenDict({"b": 1}), "c": (1, 2), "d": (3, 4)})


# --- the measurement itself, and what it counts ------------------------------


def test_the_faithful_measurement_counts_containers_the_way_the_ceiling_does() -> None:
    """A scalar is 0 and ``{}`` is 1, matching :func:`_json_depth`'s vocabulary."""
    assert _faithful_json_depth("x", 10) == 0
    assert _faithful_json_depth({}, 10) == 1
    assert _faithful_json_depth({"a": 1}, 10) == 1
    assert _faithful_json_depth({"a": {"b": [1]}}, 10) == 3
    assert _faithful_json_depth([[[1]]], 10) == 3


def test_the_measurement_stops_once_past_its_limit() -> None:
    """It answers "is this past the ceiling", not "how deep is this" (§2)."""
    assert _faithful_json_depth(nested(5000), _MAX_JSON_DEPTH) == _MAX_JSON_DEPTH + 1


def test_bytes_are_measured_as_a_leaf_because_that_is_how_they_validate() -> None:
    """Faithful cuts both ways: a container the validator never sees is not one.

    Pydantic validates ``bytes`` and ``bytearray`` against the ``str`` member of
    ``FrozenJson`` and never enumerates either as a sequence, so reading them as
    containers would refuse values the type accepts.
    """
    assert _faithful_json_depth(b"xy", 10) == 0
    assert step({"a": b"xy"}).parameters == FrozenDict({"a": "xy"})


def test_the_other_refusals_on_this_ingress_still_say_their_own_reason() -> None:
    """The depth check runs first and must not steal another refusal's message."""
    with pytest.raises(ValidationError, match="no JSON representation"):
        step({"a": float("nan")})
    with pytest.raises(ValidationError, match="no JSON encoding"):
        step({"a": "\ud800"})


# --- the ceiling reaches holders other than the first one --------------------


def test_the_ceiling_reaches_a_value_holder_as_well_as_a_mapping_holder() -> None:
    """``FrozenJsonValue`` and ``FrozenJsonMapping`` carry the same bound.

    The roster in ``test_json_depth_coverage.py`` states this over every field
    that declares either alias; these two are the end-to-end construction of it.
    """
    with pytest.raises(ValidationError, match=TOO_DEEP):
        ToolResult(outcome=ToolOutcome.SUCCEEDED, output=nested(_MAX_JSON_DEPTH + 1))
    assert ToolResult(outcome=ToolOutcome.SUCCEEDED, output=nested(_MAX_JSON_DEPTH)).output
