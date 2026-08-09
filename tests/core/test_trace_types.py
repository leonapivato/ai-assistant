"""The ``EvaluationTrace`` family's own invariants (ADR-0119 §3, §13a).

The closure walk next door proves that no string reachable from a trace is
*unconstrained*; this module proves that each constraint is the one §3 ratified,
and that the total conversion §3 depends on is actually total.

The two are complementary and neither subsumes the other: a family whose every
string carried a validator that accepted everything would pass the walk and fail
here, and a family whose validators were all correct but whose new field was a
bare ``str`` would pass here and fail the walk.
"""

from __future__ import annotations

import asyncio
import copy
import pickle
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_assistant.core.types import (
    TRACE_RECORD_SET_CAP,
    UNREPRESENTABLE_FAULT_CLASS,
    EvaluationTrace,
    FrozenMapping,
    RecordIdSet,
    TraceChunk,
    TraceKind,
    TraceOutcome,
    TracePosition,
    TraceRecordSet,
    TraceRef,
    WalkPosition,
    fault_class_of,
)

_WHEN = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

#: Positions built by hand, so ``token=`` appears once rather than at every use:
#: it is an order key, and flake8-bandit reads the keyword as a credential.
_BLANK_POSITION = {"token": "   "}
_SEVENTH = TracePosition(token="7")  # noqa: S106 — an order key, not a secret
_EIGHTH = TracePosition(token="8")  # noqa: S106 — same


def _trace(**fields: Any) -> EvaluationTrace:
    """A minimal valid trace, with ``fields`` overriding the defaults."""
    return EvaluationTrace(
        **{
            "kind": TraceKind.OPERATION,
            "seam": "converse",
            "occurred_at": _WHEN,
            "outcome": TraceOutcome.OK,
            **fields,
        }
    )


# --- the closed vocabularies (§3, §13e) --------------------------------------


@pytest.mark.parametrize(
    ("vocabulary", "members"),
    [
        (TraceKind, {"operation", "retrieval", "memory_write", "configuration"}),
        (TraceOutcome, {"ok", "refused", "fault", "incomplete"}),
        (TraceRef, {"correlation", "conversation", "turn", "execution"}),
        (
            TraceRecordSet,
            {"returned", "written", "reinforced", "superseded", "retired"},
        ),
    ],
    ids=lambda value: getattr(value, "__name__", "members"),
)
def test_each_vocabulary_holds_exactly_the_ratified_members(
    vocabulary: type[Any], members: set[str]
) -> None:
    """§13e: a member added to any of the four takes its own ratified ADR.

    Pinned as an equality rather than a subset, because the clause is about
    *membership* in both directions: these are ``core/types.py`` types exchanged
    across the ``TraceSink``/``TraceStore`` boundary, so an emitter writing a
    member a store's schema does not know is a break, and every consumer
    switching on the vocabulary silently acquires an unhandled case. Removing one
    is a break the other way.
    """
    assert {member.value for member in vocabulary} == members


def test_the_record_set_cap_is_the_ratified_figure() -> None:
    """256, and in the type rather than in ``Settings`` (§3).

    "The cap belongs to the type, so every implementation agrees without
    configuration" — a deployment able to move it would make a truncation flag
    mean different things in two stores.
    """
    assert TRACE_RECORD_SET_CAP == 256


# --- the total fault-class conversion (§3) -----------------------------------


def test_an_ordinary_exception_yields_its_class_name() -> None:
    """The base case: the class, never the message."""
    assert fault_class_of(ValueError("a message that names a row")) == "ValueError"


@pytest.mark.parametrize(
    "name",
    ["X" * 65, "Ünïcodé", "has a space", "", "9leading_digit"],
    ids=["over-long", "non-ascii", "not-an-identifier", "empty", "leading-digit"],
)
def test_a_name_that_will_not_fit_the_pattern_becomes_the_reserved_literal(name: str) -> None:
    """§3's totality clause: no exception a provider can raise stops a trace.

    "A name is not a licence to carry a payload" — a class built at runtime can
    have a name of any length and any content, so the pattern refuses it and the
    *conversion* is made total rather than the pattern lax. Failing construction
    here would be the worst available outcome: the record of the fault destroyed
    by the fault's own name.
    """
    built = type(name, (Exception,), {})

    assert fault_class_of(built()) == UNREPRESENTABLE_FAULT_CLASS


def test_a_metaclass_that_raises_on_the_name_read_is_survived() -> None:
    """ "Total" has to mean it, so reading the name is itself guarded.

    A guarantee with an exotic hole in it is not the guarantee §3 states.
    """

    class _Hostile(type):
        def __getattribute__(cls, name: str) -> Any:
            if name == "__name__":
                msg = "the name read itself raises"
                raise RuntimeError(msg)
            return super().__getattribute__(name)

    hostile = _Hostile("Hostile", (Exception,), {})

    assert fault_class_of(hostile()) == UNREPRESENTABLE_FAULT_CLASS


def test_a_name_that_is_not_a_string_is_survived() -> None:
    """``__name__`` can be overridden to return something that is not a ``str``."""

    class _Numeric(type):
        @property
        def __name__(cls) -> Any:  # type: ignore[override]  # the hostile case, on purpose
            return 42

    numeric = _Numeric("Numeric", (Exception,), {})

    assert fault_class_of(numeric()) == UNREPRESENTABLE_FAULT_CLASS


def test_a_cancellation_raised_by_the_name_read_is_delivered_onward() -> None:
    """The guard catches ``Exception`` and not ``BaseException`` (ADR-0060 §1).

    A cancellation absorbed here would be absorbed inside the one function whose
    job is to never fail — which is exactly the shape §5's subordination must not
    be allowed to become.
    """

    class _Cancelling(type):
        def __getattribute__(cls, name: str) -> Any:
            if name == "__name__":
                raise asyncio.CancelledError
            return super().__getattribute__(name)

    cancelling = _Cancelling("Cancelling", (Exception,), {})

    with pytest.raises(asyncio.CancelledError):
        fault_class_of(cancelling())


def test_the_reserved_literal_is_itself_a_valid_fault_class() -> None:
    """Otherwise the totality clause would be a lie one level up.

    A conversion that always returns a value, whose value the model then refuses,
    destroys the trace just as surely as raising would have.
    """
    trace = _trace(outcome=TraceOutcome.FAULT, fault_class=UNREPRESENTABLE_FAULT_CLASS)

    assert trace.fault_class == UNREPRESENTABLE_FAULT_CLASS


# --- the patterns (§13a) -----------------------------------------------------


@pytest.mark.parametrize("seam", ["seam\n", "Seam", "1seam", "s" * 65, "", "sea m", "seam\u200b"])
def test_a_seam_label_outside_the_pattern_is_refused(seam: str) -> None:
    """``fullmatch``, never ``match``.

    ``$`` also matches *before* a trailing newline, so ``match(r"^[a-z]+$",
    "seam\\n")`` succeeds and the bound the pattern exists to impose would not
    hold — which is the case listed first here.
    """
    with pytest.raises(ValidationError):
        _trace(seam=seam)


@pytest.mark.parametrize("value", ["not-hex", "A" * 32, "0" * 31, "0" * 33, "0123456789abcdef"])
def test_an_id_that_is_not_a_minted_uuid_is_refused(value: str) -> None:
    """32 lowercase hex characters, and nothing else (§3).

    ``Identifier`` alone would have let any emitter satisfy the type with a
    user's sentence, putting Tier 1 content in a Tier 2 store through the one
    field nobody inspects.
    """
    with pytest.raises(ValidationError):
        _trace(id=value)


def test_a_trace_mints_its_own_id() -> None:
    """The default is what keeps ``id=`` out of every emitter's reach (§13a)."""
    first, second = _trace(), _trace()

    assert first.id != second.id
    assert len(first.id) == 32
    assert int(first.id, 16) >= 0  # hex, and nothing else


def test_a_well_formed_id_supplied_by_a_caller_is_accepted() -> None:
    """The residue ADR-0119 §13a **accepts by name**, pinned so it reads as decided.

    "A caller can still pass 32 hex characters it computed from content — a
    digest, a hex-encoded string — and the type will take it. No constructor
    discipline closes that: the model must be reconstructible from a stored row,
    every hydration path is callable, and the caller in question is first-party
    code inside this repository." The corpus has ruled this class of residue
    accepted twice over — ADR-0021 §1 ("a caller falsifying its own audit trail,
    not a policy subverting a gate… no producer can prevent it") and ADR-0058.

    §13a also names, and refuses, the fix that looks obvious: "a required ``id``
    plus a separate minting factory… was weighed and refused, because it puts
    ``id=`` back in every emitter's reach and reopens exactly the accidental route
    the default closes."

    What the shape *does* buy is asserted beside it: nothing that looks like
    content survives the pattern, so every **accidental** route is gone and the
    remaining one is a deliberate act by first-party code that review governs
    (§2's third clause).
    """
    supplied = "0" * 32

    assert _trace(id=supplied).id == supplied

    for content in ("the user's address", "0" * 31, "not hex at all", "A" * 32):
        with pytest.raises(ValidationError):
            _trace(id=content)


# --- the model's invariants (§13a) -------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "fault_class"),
    [
        (TraceOutcome.OK, "ValueError"),
        (TraceOutcome.INCOMPLETE, "ValueError"),
        (TraceOutcome.REFUSED, None),
        (TraceOutcome.FAULT, None),
    ],
)
def test_an_outcome_and_a_fault_class_that_disagree_are_refused(
    outcome: TraceOutcome, fault_class: str | None
) -> None:
    """Present exactly when an exception decided the outcome (§13a).

    Both directions, because each is a different lie: a failure with no class
    names no discriminator, and a success with one reports a failure that did not
    happen.
    """
    with pytest.raises(ValidationError, match="disagree"):
        _trace(outcome=outcome, fault_class=fault_class)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_metric_is_refused_at_construction(value: float) -> None:
    """§3's finiteness clause, and the corpus has paid for the alternative twice.

    ``json.dumps`` renders these to a non-JSON token instead of raising, so the
    encoder does not catch them — and a single ``NaN`` score from a provider
    poisons every average and every threshold computed over the walk, silently,
    long after the trace was written. §5 already accepts that the stream can be
    *incomplete*; it must not also be able to be *wrong*.
    """
    with pytest.raises(ValidationError):
        _trace(metrics={"score": value})


def test_a_negative_elapsed_is_refused_and_zero_is_not() -> None:
    """A duration that runs backwards is not a measurement."""
    assert _trace(elapsed=timedelta(0)).elapsed == timedelta(0)

    with pytest.raises(ValidationError):
        _trace(elapsed=timedelta(microseconds=-1))


def test_the_defaulted_mappings_are_validated_and_frozen() -> None:
    """``validate_default=True``, and it is the one pydantic default this family cannot take.

    Pydantic does not run a field's validators over its default, so a plain
    ``{}`` would reach every trace constructed without refs — most
    ``CONFIGURATION`` traces and every faulting one — as a *mutable* dict that
    ``frozen=True`` does not protect. The injection path §13a closes would be open
    on exactly the traces least likely to be examined.
    """
    trace = _trace()

    for mapping in (trace.refs, trace.records, trace.metrics):
        assert isinstance(mapping, FrozenMapping)


def test_a_mapping_cannot_be_mutated_in_place() -> None:
    """``frozen=True`` refuses ``trace.metrics = …`` and not ``trace.metrics["k"] = …``.

    The second is the one that matters: a caller mutating a validated trace's
    metrics could put a free-form string past §2's containment rule *after*
    validation ran.
    """
    trace = _trace(metrics={"limit": 10})

    with pytest.raises(TypeError):
        trace.metrics["injected"] = "a sentence the user typed"  # type: ignore[index]

    with pytest.raises(ValidationError):
        trace.metrics = {}


def test_a_mapping_is_detached_from_what_the_caller_passed() -> None:
    """The model owns a copy no caller can reach (§13a)."""
    supplied = {"limit": 10}
    trace = _trace(metrics=supplied)

    supplied["limit"] = 999

    assert dict(trace.metrics) == {"limit": 10}


def test_a_trace_is_hashable_and_deep_copyable() -> None:
    """Both, and the second is what ``MappingProxyType`` would have cost.

    ``FrozenDict``'s docstring names the edge: a proxy "can be neither pickled nor
    deep-copied, which would make any model holding one fail
    ``model_copy(deep=True)``" — and a trace that failed a deep copy would fail
    exactly the detached-snapshot obligation §13b is built on.
    """
    trace = _trace(metrics={"limit": 10}, refs={TraceRef.TURN: "turn-1"})

    assert copy.deepcopy(trace) == trace
    assert trace.model_copy(deep=True) == trace
    assert pickle.loads(pickle.dumps(trace)) == trace  # noqa: S301 — our own object
    assert hash(trace.metrics) == hash(FrozenMapping({"limit": 10}))


def test_a_bool_metric_stays_a_bool() -> None:
    """``int | float | bool`` must not quietly coerce a flag to ``1``.

    A measure counting "how many reads hit the cache" reads a different column
    from one summing a count, and a union that collapsed the two would make the
    distinction invisible after storage.
    """
    trace = _trace(metrics={"was_cached": True, "returned": 1})

    assert trace.metrics["was_cached"] is True
    assert trace.metrics["returned"] == 1
    assert not isinstance(trace.metrics["returned"], bool)


# --- the record id set (§3, §13a) --------------------------------------------


def test_a_record_id_set_refuses_a_repeated_id() -> None:
    """Checked **first**, because the length invariant cannot see it.

    ``ids=("a", "a"), total=2`` satisfies the count while double-counting one
    record in a measure's numerator and crowding a real one out at the cap.
    """
    with pytest.raises(ValidationError, match="at most once"):
        RecordIdSet(ids=("a", "a"), total=2)


@pytest.mark.parametrize(
    ("ids", "total"),
    [((), 1), (("a",), 0), (("a",), 2), (("a", "b"), 1)],
)
def test_a_record_id_set_refuses_a_count_that_does_not_match(
    ids: tuple[str, ...], total: int
) -> None:
    """``len(ids) == min(total, CAP)`` — an equality, not a bound (§13a).

    ``total >= len(ids)`` admits ``ids=(), total=1``: an emitter dropping ids it
    was under no pressure to drop, which reports a truncation §3 reserves for cap
    overflow and costs a trace its place in a measure's population for nothing.
    """
    with pytest.raises(ValidationError):
        RecordIdSet(ids=ids, total=total)


def test_a_set_at_the_cap_is_not_truncated_and_one_past_it_is() -> None:
    """Truncation is *derived* from the two numbers rather than flagged beside them.

    So the count survives the truncation the ids do not, and the two cannot
    disagree (§3).
    """
    ids = tuple(str(index) for index in range(TRACE_RECORD_SET_CAP))

    exact = RecordIdSet(ids=ids, total=TRACE_RECORD_SET_CAP)
    over = RecordIdSet(ids=ids, total=TRACE_RECORD_SET_CAP + 1)

    assert len(exact.ids) == exact.total
    assert over.total > len(over.ids)


def test_a_set_carrying_more_ids_than_the_cap_is_refused() -> None:
    """No trace is dropped because an operation was large — but nor is the cap advisory."""
    with pytest.raises(ValidationError):
        RecordIdSet(
            ids=tuple(str(index) for index in range(TRACE_RECORD_SET_CAP + 1)),
            total=TRACE_RECORD_SET_CAP + 1,
        )


def test_an_observed_empty_set_is_representable() -> None:
    """ "It was observed and it was empty" is a fact, distinct from "not observed" (§3)."""
    trace = _trace(records={TraceRecordSet.RETURNED: RecordIdSet(ids=(), total=0)})

    assert trace.records[TraceRecordSet.RETURNED].total == 0
    assert TraceRecordSet.WRITTEN not in trace.records


# --- the generic frozen mapping (§13a) ---------------------------------------


def test_the_frozen_mapping_refuses_every_mutation_route() -> None:
    """Including the one a private ``dict`` would leave open.

    ``FrozenDict``'s reason, inherited: "a private ``dict`` would still be a
    mutable object reachable as ``parameters._data``, which is a real bypass".
    """
    mapping: FrozenMapping[str, int] = FrozenMapping({"a": 1})

    with pytest.raises(AttributeError):
        mapping.anything = 1
    with pytest.raises(AttributeError):
        del mapping._items
    with pytest.raises(TypeError):
        mapping["b"] = 2  # type: ignore[index]


def test_the_frozen_mapping_compares_equal_to_a_plain_mapping() -> None:
    """So a test can assert against a ``dict`` without a conversion step."""
    assert FrozenMapping({"a": 1}) == {"a": 1}
    assert FrozenMapping({"a": 1}) != {"a": 2}
    assert FrozenMapping({"a": 1}) != "not a mapping"


def test_the_frozen_mapping_survives_a_round_trip() -> None:
    """Hashable, pickleable and deep-copyable — the three ``MappingProxyType`` is not."""
    mapping: FrozenMapping[str, int] = FrozenMapping({"a": 1, "b": 2})

    assert hash(mapping) == hash(FrozenMapping({"b": 2, "a": 1}))
    assert copy.deepcopy(mapping) == mapping
    assert pickle.loads(pickle.dumps(mapping)) == mapping  # noqa: S301 — our own object
    assert list(mapping) == ["a", "b"]
    assert repr(mapping).startswith("FrozenMapping(")


def test_the_frozen_mapping_raises_on_a_missing_key() -> None:
    """A ``Mapping`` that answered ``None`` would make an absent metric a zero."""
    with pytest.raises(KeyError):
        FrozenMapping({"a": 1})["b"]


def test_an_empty_frozen_mapping_is_falsy_and_empty() -> None:
    """The default's shape, since every trace without refs carries one."""
    empty: FrozenMapping[str, int] = FrozenMapping()

    assert len(empty) == 0
    assert dict(empty) == {}


# --- the walk's position and chunk (§7a, §13b) -------------------------------


def test_a_position_refuses_a_blank_token() -> None:
    """A position with no value is not a position, and a store cannot resume from one."""
    with pytest.raises(ValidationError):
        TracePosition(**_BLANK_POSITION)


def test_a_chunk_is_frozen_and_always_carries_a_position() -> None:
    """§7a: there is no exhausted state in which a caller is handed no position."""
    chunk = TraceChunk(traces=(), position=_SEVENTH)

    assert chunk.position == _SEVENTH
    with pytest.raises(ValidationError):
        chunk.position = _EIGHTH


def test_a_chunk_requires_its_position() -> None:
    """No default, so an implementation cannot omit one by accident."""
    with pytest.raises(ValidationError):
        TraceChunk(traces=())  # type: ignore[call-arg]


def test_a_trace_position_is_not_interchangeable_with_another_stores_position() -> None:
    """A *separate* type from ``WalkPosition`` rather than a reuse (§13b).

    "A key issued by one store is meaningless in another, and a shared type is an
    invitation to hand a memory walk's position to the trace store and be answered
    rather than refused."
    """

    class _Holder(BaseModel):
        model_config = ConfigDict(frozen=True)

        position: TracePosition

    assert not isinstance(WalkPosition(token="1"), TracePosition)  # noqa: S106 — an order key
    assert _Holder(position=_SEVENTH).position == _SEVENTH
