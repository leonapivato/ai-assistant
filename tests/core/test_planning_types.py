"""Tests for ``PlanExport``'s own members and the frozen-JSON annotations.

The frozen-JSON arms go through a local holder that declares each annotation exactly
as the planning steps declared it, so each arm pins the annotation and nothing else.
These tests are mostly about what the types *refuse*.
"""

from __future__ import annotations

import copy
import pickle
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from _int_str_digits import pinned_int_str_digits
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    FrozenDict,
    FrozenJsonMapping,
    FrozenJsonValue,
    PlanExport,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


class _FrozenJsonHolder(BaseModel):
    """One field of each frozen-JSON annotation, declared as the planning steps declared them.

    ``FrozenJsonMapping`` and ``FrozenJsonValue`` are carried by live types —
    ``ProposedCall.arguments`` and ``ToolDefinition.parameters_schema`` among them — and
    the arms below pinned them through ``PlanStep.parameters`` and a step's ``output``,
    which left ``core`` with the old path (ADR-0309 §5). A holder with nothing else on
    it keeps each arm about the annotation and nothing besides.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameters: FrozenJsonMapping = Field(default_factory=FrozenDict)
    output: FrozenJsonValue = None


def test_the_export_instant_refuses_a_naive_reading() -> None:
    """ADR-0026 §5's second half: the producer led, so ``exported_at`` followed.

    It was among the last fields in ``core`` still attributing UTC to a naive value,
    held back by ADR-0023 §6 only until every producer stored a guarded clock. They all
    do now, so a naive reading is refused at the seam by its named owner — and refused
    here too, which is what makes the deferral closed rather than merely unenforced.
    """
    naive = datetime(2026, 1, 1)  # noqa: DTZ001 — the refusal is the subject

    with pytest.raises(ValidationError, match="exported_at must be timezone-aware"):
        PlanExport(exported_at=naive)


def test_the_export_instant_converts_an_aware_reading_to_utc() -> None:
    """The other half of the type: an offset it *was* given is honoured, not kept.

    The ``.tzinfo is UTC`` assertion is made as well as the instant one, because the
    instant alone does not distinguish the two behaviours: aware datetimes compare by
    instant, so a regression storing the supplied ``UTC+02:00`` reading verbatim
    satisfies ``== _WHEN`` while the conversion this test is named for never happened
    (issue #236).
    """
    berlin = datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))

    exported = PlanExport(exported_at=berlin).exported_at
    assert exported == _WHEN
    assert exported.tzinfo is UTC


# --- Frozen JSON parameters are frozen all the way down -------------------


def test_frozen_parameters_are_frozen_at_the_top_level() -> None:
    holder = _FrozenJsonHolder(parameters={"to": "a@b.c"})
    with pytest.raises(TypeError):
        holder.parameters["to"] = "evil@example.com"  # type: ignore[index]


def test_frozen_parameters_are_frozen_when_nested() -> None:
    """The point of deep-freezing: shallow ``frozen=True`` would miss this."""
    holder = _FrozenJsonHolder(parameters={"headers": {"reply_to": "a@b.c"}, "cc": ["x@y.z"]})
    nested = holder.parameters["headers"]
    with pytest.raises(TypeError):
        nested["reply_to"] = "evil@example.com"  # type: ignore[index]
    assert isinstance(holder.parameters["cc"], tuple)


def test_frozen_parameters_do_not_alias_the_callers_dict() -> None:
    """Mutating the source dict afterwards must not edit the frozen value."""
    source = {"to": "a@b.c"}
    holder = _FrozenJsonHolder(parameters=source)
    source["to"] = "evil@example.com"
    assert holder.parameters["to"] == "a@b.c"


def test_frozen_parameters_round_trip_through_json() -> None:
    holder = _FrozenJsonHolder(parameters={"to": "a@b.c", "tags": ["x"], "meta": {"n": 1}})
    restored = TypeAdapter(_FrozenJsonHolder).validate_json(holder.model_dump_json())
    assert restored == holder
    assert isinstance(restored.parameters["meta"], FrozenDict)


def test_frozen_parameters_survive_a_deep_copy() -> None:
    """``MappingProxyType`` cannot do this, which is why ``FrozenDict`` exists."""
    holder = _FrozenJsonHolder(parameters={"meta": {"n": 1}})
    assert copy.deepcopy(holder) == holder
    assert holder.model_copy(deep=True) == holder


def test_frozen_parameters_survive_pickling() -> None:
    parameters = _FrozenJsonHolder(parameters={"meta": {"n": 1}}).parameters
    assert pickle.loads(pickle.dumps(parameters)) == parameters  # noqa: S301  # our own round-trip.


def test_frozen_dict_compares_equal_to_a_plain_mapping() -> None:
    assert FrozenDict({"a": 1}) == {"a": 1}


def test_frozen_dict_has_no_mutable_backing_to_reach_for() -> None:
    """A private dict would still be a real bypass, not merely a rude one."""
    holder = _FrozenJsonHolder(parameters={"recipient": "a@b.c"})

    with pytest.raises(AttributeError):
        holder.parameters._items = ()  # type: ignore[attr-defined]
    assert not hasattr(holder.parameters, "_data")
    assert holder.parameters["recipient"] == "a@b.c"


def test_nested_frozen_dicts_are_equally_sealed() -> None:
    holder = _FrozenJsonHolder(parameters={"headers": {"reply_to": "a@b.c"}})
    nested = holder.parameters["headers"]

    with pytest.raises(AttributeError):
        nested._items = ()  # type: ignore[union-attr]


def test_frozen_dict_is_hashable_because_its_values_are_frozen() -> None:
    holder = _FrozenJsonHolder(parameters={"meta": {"n": 1}})
    assert hash(holder.parameters) == hash(holder.parameters)


def test_a_mapping_output_is_frozen() -> None:
    holder = _FrozenJsonHolder(output={"ref": "ABC"})
    assert holder.output is not None
    with pytest.raises(TypeError):
        holder.output["ref"] = "XYZ"  # type: ignore[index]


# --- Non-finite floats have no JSON representation ----------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_parameters_are_rejected(bad: float) -> None:
    """These satisfy ``float`` but would change value on the way through JSON."""
    with pytest.raises(ValidationError, match="no JSON representation"):
        _FrozenJsonHolder(parameters={"x": bad})


def test_non_finite_values_are_rejected_when_nested() -> None:
    with pytest.raises(ValidationError, match="no JSON representation"):
        _FrozenJsonHolder(parameters={"a": {"b": [1.0, float("inf")]}})


def test_non_finite_output_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no JSON representation"):
        _FrozenJsonHolder(output={"score": float("nan")})


def test_ordinary_floats_still_round_trip() -> None:
    holder = _FrozenJsonHolder(parameters={"x": 1.5})
    assert TypeAdapter(_FrozenJsonHolder).validate_json(holder.model_dump_json()) == holder


# --- Values with no JSON encoding (issue #121) --------------------------
# Frozen-JSON parameters and outputs are ``FrozenJson`` holders, so they inherit
# ``_freeze_json``'s refusal of a value that satisfies its Python type but has no
# portable encoding — a lone surrogate ``str`` or an integer past CPython's
# integer-string conversion limit. Checked by running the real encoder, so a key
# and a deeply nested value are refused too, not only a top-level value.


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param({"body": "\ud800"}, id="a value"),
        pytest.param({"\ud800": "body"}, id="a key"),
        pytest.param({"nested": {"body": "\udfff"}}, id="nested in a mapping"),
        pytest.param({"items": ["fine", "\ud800"]}, id="inside a sequence"),
    ],
)
def test_parameters_with_a_lone_surrogate_are_rejected(
    parameters: dict[str, Any],
) -> None:
    """A lone surrogate is a ``str`` with no UTF-8 encoding (ADR-0021 §1)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _FrozenJsonHolder(parameters=parameters)


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param({"n": 10**5000}, id="a value"),
        pytest.param({"nested": {"n": -(10**5000)}}, id="nested in a mapping"),
        pytest.param({"items": [10**5000]}, id="inside a sequence"),
    ],
)
def test_parameters_with_an_unrenderable_integer_are_rejected(
    parameters: dict[str, Any],
) -> None:
    """``json.dumps`` renders an int through ``str()``; CPython refuses one past
    its integer-string conversion limit, so the value has no JSON encoding.

    ``pinned_int_str_digits`` holds the limit at the default so ``10**5000``
    stays unrenderable under a raised or disabled ``PYTHONINTMAXSTRDIGITS``
    (#406)."""
    with pinned_int_str_digits(), pytest.raises(ValidationError, match="no JSON encoding"):
        _FrozenJsonHolder(parameters=parameters)


def test_an_output_with_a_lone_surrogate_is_rejected() -> None:
    """The other ``FrozenJson`` holder inherits the same refusal (issue #121)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _FrozenJsonHolder(output={"body": "\ud800"})


def test_a_large_but_renderable_value_still_round_trips() -> None:
    """The bound is "can it be encoded", not "is it big" or "is it astral"."""
    holder = _FrozenJsonHolder(parameters={"n": 10**100, "emoji": "\U0001f389 done"})
    assert TypeAdapter(_FrozenJsonHolder).validate_json(holder.model_dump_json()) == holder


# --- A single frozen-JSON value with no JSON encoding (issue #121, #409) ---
# ``FrozenJsonValue`` is a single value rather than a mapping, so it inherits
# _freeze_json's refusal of a value that satisfies its Python type but has no
# portable encoding at the top level as well as nested.


def test_an_output_with_an_unrenderable_integer_is_rejected() -> None:
    """``json.dumps`` renders an int through ``str()``; CPython refuses one past
    its integer-string conversion limit, so the value has no JSON encoding.

    ``pinned_int_str_digits`` holds the limit at the default so ``10**5000``
    stays unrenderable under a raised or disabled ``PYTHONINTMAXSTRDIGITS``
    (#406)."""
    with pinned_int_str_digits(), pytest.raises(ValidationError, match="no JSON encoding"):
        _FrozenJsonHolder(output={"n": 10**5000})


def test_an_ordinary_output_still_round_trips() -> None:
    """The bound is "can it be encoded", not "is it big" or "is it astral"."""
    holder = _FrozenJsonHolder(output={"n": 10**100, "emoji": "\U0001f389 done"})
    assert TypeAdapter(_FrozenJsonHolder).validate_json(holder.model_dump_json()) == holder


def test_a_scalar_output_is_accepted() -> None:
    """The value is a single ``FrozenJsonValue``, not a mapping: a bare scalar is
    valid, so a regression narrowing the annotation to a mapping is caught.
    """
    holder = _FrozenJsonHolder(output="done")
    assert holder.output == "done"
    assert TypeAdapter(_FrozenJsonHolder).validate_json(holder.model_dump_json()) == holder


def test_a_scalar_output_with_a_lone_surrogate_is_rejected() -> None:
    """A bare scalar runs through ``_freeze_json`` too, so an unencodable scalar
    is refused — not only an unencodable value nested inside a mapping. Guards a
    regression that checks mapping values but admits a bare unencodable string.
    """
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _FrozenJsonHolder(output="\ud800")


# --- PlanExport ---------------------------------------------------------


def test_export_is_versioned_and_defaults_to_empty() -> None:
    export = PlanExport(exported_at=_WHEN)
    assert export.schema_version == 28
    assert export.activation_effects == ()
    assert export.observations == ()
    assert export.scheduled_tasks == ()
    assert export.approval_requests == ()


def test_export_pins_the_schema_version_to_exactly_twenty_eight() -> None:
    """The label is a fact about the document, not a producer's claim (ADR-0039 §10).

    ``Literal[28]`` refuses an explicit ``27`` — a document whose requests' calls carry
    no recorded wording (ADR-0338 §8:6) — and any other value, so the advertised version
    cannot be mislabelled. The positive default is what a producer gets for free; only
    the rejections pin it.

    **The neighbour on each side is asserted and not only the far ones**: ``27`` is
    the shape this contract had one decision ago and ``29`` is the shape nobody has
    decided, and a ``Literal`` that admitted either would be a document announcing a
    shape it does not have.
    """
    assert PlanExport(exported_at=_WHEN, schema_version=28).schema_version == 28
    for stale in (*range(1, 28), 29):
        with pytest.raises(ValidationError):
            PlanExport(exported_at=_WHEN, schema_version=stale)


@pytest.mark.parametrize(
    "retired", ["goals", "plans", "executions", "attempts", "questions", "evidence", "effects"]
)
def test_export_refuses_a_section_the_old_path_carried(retired: str) -> None:
    """ADR-0309 §5: the old path's sections left the document, and ``extra="forbid"``
    refuses a document that still carries one rather than dropping it silently."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlanExport.model_validate({"exported_at": _WHEN, retired: []})


def test_export_carries_stopped_activations_once_each() -> None:
    """ADR-0297 §1: the stop records travel as a tuple of ids, and none twice.

    A record names an activation and nothing the document otherwise carries, so it
    closes over nothing; the one constraint is that the store holds at most one record
    per activation, which a duplicate would contradict.
    """
    export = PlanExport(exported_at=_WHEN, stopped_activations=("act-1", "act-2"))
    assert export.stopped_activations == ("act-1", "act-2")
    assert PlanExport(exported_at=_WHEN).stopped_activations == ()
    restored = PlanExport.model_validate_json(export.model_dump_json())
    assert restored == export

    with pytest.raises(ValidationError, match="duplicate stopped activation"):
        PlanExport(exported_at=_WHEN, stopped_activations=("act-1", "act-1"))
    with pytest.raises(ValidationError):
        PlanExport(exported_at=_WHEN, stopped_activations=("  ",))
