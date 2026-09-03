"""Tests for the planning domain types (ADR-0014).

The validators here exist to make illegal execution states unrepresentable, so
these tests are mostly about what the types *refuse*.
"""

from __future__ import annotations

import copy
import pickle
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from _int_str_digits import pinned_int_str_digits
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    MAX_HOP_LABELS,
    ActionPlan,
    ExecutionState,
    FrozenDict,
    Goal,
    GoalDeletion,
    GoalStatus,
    MemorySource,
    PlanExport,
    PlanStep,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SkipReason,
    StepExecution,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolFailureKind,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_PROV = Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)


def _goal(**overrides: object) -> Goal:
    fields: dict[str, object] = {
        "id": "g1",
        "statement": "relocate to Lisbon in September",
        "provenance": _PROV,
        "created_at": _WHEN,
    }
    return Goal(**(fields | overrides))  # type: ignore[arg-type]


def _step(**overrides: object) -> StepExecution:
    fields: dict[str, object] = {"step_id": "s1"}
    return StepExecution(**(fields | overrides))  # type: ignore[arg-type]


_FINISHED = (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE)
_FAILURE = (StepStatus.FAILED, StepStatus.INDETERMINATE)


def _claimed(status: StepStatus, **overrides: object) -> StepExecution:
    """A step carrying the full set of marks a claimed step requires.

    Supplies ``finished_at`` for the statuses that require one, and a
    ``failure`` for ``FAILED``/``INDETERMINATE`` (ADR-0039 §2), so a test that
    is about something else does not have to. Pass ``finished_at=None`` or
    ``failure=None`` to opt out and exercise the invariant itself.
    """
    fields: dict[str, object] = {
        "step_id": "s1",
        "status": status,
        "attempts": 1,
        "bound_tool": "smtp",
        "approval_ref": "perm-1",
        "started_at": _WHEN,
    }
    if status in _FINISHED:
        fields["finished_at"] = _WHEN
    if status in _FAILURE:
        fields["failure"] = StepFailure(message="boom")
    return StepExecution(**(fields | overrides))  # type: ignore[arg-type]


# --- Goal ---------------------------------------------------------------


def test_goal_defaults_to_active() -> None:
    assert _goal().status is GoalStatus.ACTIVE


def test_goal_rejects_a_blank_statement() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        _goal(statement="   ")


def test_goal_refuses_naive_timestamps() -> None:
    """ADR-0023 §3: ``core`` never attributes an offset it was not given."""
    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        _goal(created_at=datetime(2026, 1, 1))  # noqa: DTZ001 — a naive value is the subject
    with pytest.raises(ValidationError, match="deadline must be timezone-aware"):
        _goal(deadline=datetime(2026, 9, 1))  # noqa: DTZ001 — a naive value is the subject


def test_goal_converts_aware_timestamps_to_utc() -> None:
    goal = _goal(
        created_at=datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))),
        deadline=datetime(2026, 9, 1, 2, tzinfo=timezone(timedelta(hours=2))),
    )
    assert goal.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert goal.created_at.tzinfo is UTC
    assert goal.deadline is not None
    assert goal.deadline.tzinfo is UTC


def test_the_clock_fed_planning_fields_refuse_a_naive_reading() -> None:
    """ADR-0026 §5's second half: the producer led, so these five followed.

    They were the last fields in ``core`` still attributing UTC to a naive
    value, held back by ADR-0023 §6 only until every producer
    (``PlanExecution``, ``InMemoryPlanStore``, ``FakePlanner``,
    ``FakePlanStore``) stored a guarded clock. They all do now, so a naive
    reading is refused at the seam by its named owner — and refused here too,
    which is what makes the deferral closed rather than merely unenforced.
    """
    naive = datetime(2026, 1, 1)  # noqa: DTZ001 — the refusal is the subject

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        ActionPlan(id="p1", goal_id="g1", steps=(), created_at=naive)
    with pytest.raises(ValidationError, match="started_at must be timezone-aware"):
        _claimed(StepStatus.RUNNING, started_at=naive)
    with pytest.raises(ValidationError, match="finished_at must be timezone-aware"):
        _claimed(StepStatus.SUCCEEDED, finished_at=naive)
    with pytest.raises(ValidationError, match="updated_at must be timezone-aware"):
        ExecutionState(id="e1", plan_id="p1", steps=(), updated_at=naive)
    with pytest.raises(ValidationError, match="exported_at must be timezone-aware"):
        PlanExport(exported_at=naive)


def test_the_clock_fed_planning_fields_convert_an_aware_reading_to_utc() -> None:
    """The other half of the type: an offset it *was* given is honoured, not kept.

    Every field carries the ``.tzinfo is UTC`` assertion as well as the instant
    one, because the instant alone does not distinguish the two behaviours:
    aware datetimes compare by instant, so a regression storing the supplied
    ``UTC+02:00`` reading verbatim satisfies ``== _WHEN`` while the conversion
    this test is named for never happened (issue #236).
    """
    berlin = datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))

    plan = ActionPlan(id="p1", goal_id="g1", steps=(), created_at=berlin)
    assert plan.created_at == _WHEN
    assert plan.created_at.tzinfo is UTC

    finished = _claimed(StepStatus.SUCCEEDED, started_at=berlin, finished_at=berlin)
    assert finished.started_at == _WHEN
    assert finished.started_at is not None
    assert finished.started_at.tzinfo is UTC
    assert finished.finished_at == _WHEN
    assert finished.finished_at is not None
    assert finished.finished_at.tzinfo is UTC

    state = ExecutionState(id="e1", plan_id="p1", steps=(), updated_at=berlin)
    assert state.updated_at == _WHEN
    assert state.updated_at.tzinfo is UTC

    exported = PlanExport(exported_at=berlin).exported_at
    assert exported == _WHEN
    assert exported.tzinfo is UTC


# --- PlanStep parameters are frozen all the way down --------------------


def test_step_parameters_are_frozen_at_the_top_level() -> None:
    step = PlanStep(id="s1", intent="mail", capability="send_email", parameters={"to": "a@b.c"})
    with pytest.raises(TypeError):
        step.parameters["to"] = "evil@example.com"  # type: ignore[index]


def test_step_parameters_are_frozen_when_nested() -> None:
    """The point of deep-freezing: shallow ``frozen=True`` would miss this."""
    step = PlanStep(
        id="s1",
        intent="mail",
        capability="send_email",
        parameters={"headers": {"reply_to": "a@b.c"}, "cc": ["x@y.z"]},
    )
    nested = step.parameters["headers"]
    with pytest.raises(TypeError):
        nested["reply_to"] = "evil@example.com"  # type: ignore[index]
    assert isinstance(step.parameters["cc"], tuple)


def test_step_parameters_do_not_alias_the_callers_dict() -> None:
    """Mutating the source dict afterwards must not edit the frozen plan."""
    source = {"to": "a@b.c"}
    step = PlanStep(id="s1", intent="mail", capability="send_email", parameters=source)
    source["to"] = "evil@example.com"
    assert step.parameters["to"] == "a@b.c"


def test_frozen_parameters_round_trip_through_json() -> None:
    step = PlanStep(
        id="s1",
        intent="mail",
        capability="send_email",
        parameters={"to": "a@b.c", "tags": ["x"], "meta": {"n": 1}},
    )
    restored = TypeAdapter(PlanStep).validate_json(step.model_dump_json())
    assert restored == step
    assert isinstance(restored.parameters["meta"], FrozenDict)


def test_frozen_parameters_survive_a_deep_copy() -> None:
    """``MappingProxyType`` cannot do this, which is why ``FrozenDict`` exists."""
    step = PlanStep(id="s1", intent="mail", capability="send_email", parameters={"meta": {"n": 1}})
    assert copy.deepcopy(step) == step
    assert step.model_copy(deep=True) == step


def test_frozen_parameters_survive_pickling() -> None:
    step = PlanStep(id="s1", intent="mail", capability="send_email", parameters={"meta": {"n": 1}})
    assert pickle.loads(pickle.dumps(step)) == step  # noqa: S301  # our own round-trip.


def test_frozen_dict_compares_equal_to_a_plain_mapping() -> None:
    assert FrozenDict({"a": 1}) == {"a": 1}


def test_frozen_dict_has_no_mutable_backing_to_reach_for() -> None:
    """A private dict would still be a real bypass, not merely a rude one."""
    step = PlanStep(id="s1", intent="i", capability="c", parameters={"recipient": "a@b.c"})

    with pytest.raises(AttributeError):
        step.parameters._items = ()  # type: ignore[attr-defined]
    assert not hasattr(step.parameters, "_data")
    assert step.parameters["recipient"] == "a@b.c"


def test_nested_frozen_dicts_are_equally_sealed() -> None:
    step = PlanStep(
        id="s1", intent="i", capability="c", parameters={"headers": {"reply_to": "a@b.c"}}
    )
    nested = step.parameters["headers"]

    with pytest.raises(AttributeError):
        nested._items = ()  # type: ignore[union-attr]


def test_frozen_dict_is_hashable_because_its_values_are_frozen() -> None:
    step = PlanStep(id="s1", intent="mail", capability="send_email", parameters={"meta": {"n": 1}})
    assert hash(step.parameters) == hash(step.parameters)


def test_plan_rejects_duplicate_step_ids() -> None:
    dup = PlanStep(id="s1", intent="a", capability="c")
    with pytest.raises(ValidationError, match="unique"):
        ActionPlan(id="p1", goal_id="g1", steps=(dup, dup), created_at=_WHEN)


# --- A claimed step must be correlatable with its authorisation ---------


@pytest.mark.parametrize(
    "status",
    [StepStatus.RUNNING, StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE],
)
def test_claimed_step_requires_an_approval_ref(status: StepStatus) -> None:
    """ADR-0004 §7: a step that may have acted must name the decision that let it."""
    with pytest.raises(ValidationError, match="approval_ref"):
        _claimed(status, approval_ref=None)


def test_claimed_step_requires_a_bound_tool() -> None:
    with pytest.raises(ValidationError, match="bound_tool"):
        _claimed(StepStatus.RUNNING, bound_tool=None)


def test_claimed_step_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValidationError, match="at least one attempt"):
        _claimed(StepStatus.RUNNING, attempts=0)


def test_pending_step_needs_none_of_the_claim_marks() -> None:
    assert _step().status is StepStatus.PENDING


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_approval_ref_is_not_an_approval(blank: str) -> None:
    """An empty reference satisfies "is present" while identifying nothing."""
    with pytest.raises(ValidationError, match="must not be blank"):
        _claimed(StepStatus.RUNNING, approval_ref=blank)


def test_a_blank_bound_tool_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        _claimed(StepStatus.RUNNING, bound_tool="  ")


def test_identifiers_are_stored_stripped() -> None:
    step = _claimed(StepStatus.RUNNING, approval_ref="  perm-1  ")
    assert step.approval_ref == "perm-1"


# --- A step that has not run must not look like it has -------------------


def test_a_pending_step_cannot_carry_fabricated_attempts() -> None:
    """The ceiling is only consulted from FAILED, so this would slip past it."""
    with pytest.raises(ValidationError, match="cannot have attempts"):
        _step(attempts=1000)


def test_a_pending_step_cannot_claim_to_have_started() -> None:
    with pytest.raises(ValidationError, match="cannot have started_at"):
        _step(started_at=_WHEN)


def test_a_pending_step_predates_selection_and_approval() -> None:
    with pytest.raises(ValidationError, match="predates tool selection"):
        _step(bound_tool="smtp")


def test_an_awaiting_step_must_name_what_is_being_approved() -> None:
    with pytest.raises(ValidationError, match="requires the bound_tool"):
        _step(status=StepStatus.AWAITING_APPROVAL)


def test_an_awaiting_step_has_no_decision_yet() -> None:
    with pytest.raises(ValidationError, match="undecided"):
        _step(status=StepStatus.AWAITING_APPROVAL, bound_tool="smtp", approval_ref="perm-1")


def test_awaiting_approval_is_not_a_claim() -> None:
    """A step queued for approval has not run, so it needs no approval_ref yet."""
    step = _step(status=StepStatus.AWAITING_APPROVAL, bound_tool="smtp")
    assert step.approval_ref is None


# --- Outcome fields must match the status -------------------------------


def test_skipped_step_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires a skip_reason"):
        _step(status=StepStatus.SKIPPED)


def test_skip_reason_is_rejected_on_a_step_that_was_not_skipped() -> None:
    with pytest.raises(ValidationError, match="only valid for a SKIPPED"):
        _step(skip_reason=SkipReason.SUPERSEDED)


@pytest.mark.parametrize("status", _FAILURE)
def test_a_failure_status_requires_a_failure(status: StepStatus) -> None:
    """Required on FAILED *and* INDETERMINATE (ADR-0039 §2), both asserted.

    INDETERMINATE is the half #208 is about: the state ADR-0014 §4 makes durable
    because it must be resolved explicitly was the one finished status with no
    durable account of itself.
    """
    with pytest.raises(ValidationError, match="requires a failure"):
        _claimed(status, failure=None)


def _with_failure(status: StepStatus) -> StepExecution:
    """A step of ``status`` that is valid except for carrying a failure.

    Each non-failure status has its own other requirements, so the scaffolding
    differs; the failure is the single thing every one of them must reject.
    """
    failure = StepFailure(message="boom")
    if status is StepStatus.PENDING:
        return _step(failure=failure)
    if status is StepStatus.AWAITING_APPROVAL:
        return _step(status=status, bound_tool="smtp", failure=failure)
    if status is StepStatus.SKIPPED:
        return _step(status=status, skip_reason=SkipReason.SUPERSEDED, failure=failure)
    return _claimed(status, failure=failure)


@pytest.mark.parametrize(
    "status",
    [
        StepStatus.PENDING,
        StepStatus.AWAITING_APPROVAL,
        StepStatus.RUNNING,
        StepStatus.SUCCEEDED,
        StepStatus.SKIPPED,
    ],
)
def test_failure_is_forbidden_off_the_failure_statuses(status: StepStatus) -> None:
    """Forbidden on each of the other five (ADR-0039 §2).

    The redrawn rule is too-coarse-made-right, not lifted: a step carrying a
    diagnostic stays readable as a step that did not succeed. A suite that
    checked only the required half would certify one widened to "anything
    finished".
    """
    with pytest.raises(ValidationError, match="only valid for a FAILED or INDETERMINATE"):
        _with_failure(status)


def test_output_is_rejected_on_a_step_that_did_not_succeed() -> None:
    with pytest.raises(ValidationError, match="only valid for a SUCCEEDED"):
        _claimed(StepStatus.RUNNING, output={"ref": "ABC"})


def test_succeeded_step_carries_a_frozen_output() -> None:
    step = _claimed(StepStatus.SUCCEEDED, output={"ref": "ABC"})
    assert step.output is not None
    with pytest.raises(TypeError):
        step.output["ref"] = "XYZ"  # type: ignore[index]


# --- StepFailure --------------------------------------------------------


def test_step_failure_defaults_to_no_kind() -> None:
    """``message`` required, ``kind`` optional — the whole asymmetry (ADR-0039 §1)."""
    failure = StepFailure(message="the upstream is down")
    assert failure.message == "the upstream is down"
    assert failure.kind is None


def test_step_failure_carries_a_tool_kind_when_one_produced_it() -> None:
    failure = StepFailure(kind=ToolFailureKind.UNAVAILABLE, message="the upstream is down")
    assert failure.kind is ToolFailureKind.UNAVAILABLE


def test_step_failure_refuses_a_blank_message() -> None:
    """ADR-0029 §3's ``_has_visible_text`` case, one layer up (ADR-0039 §1)."""
    with pytest.raises(ValidationError, match="must contain visible text"):
        StepFailure(message="   ")


def test_step_failure_strips_its_message() -> None:
    assert StepFailure(message="  boom  ").message == "boom"


def test_step_failure_is_frozen() -> None:
    """An account of what already happened must not be editable after the fact."""
    failure = StepFailure(message="boom")
    with pytest.raises(ValidationError):
        failure.message = "rewritten"


def test_step_failure_round_trips_through_json() -> None:
    failure = StepFailure(kind=ToolFailureKind.RATE_LIMITED, message="throttled")
    assert TypeAdapter(StepFailure).validate_json(failure.model_dump_json()) == failure


# --- ExecutionState -----------------------------------------------------


def _execution(*steps: StepExecution, version: int = 0) -> ExecutionState:
    return ExecutionState(
        id="e1", plan_id="p1", steps=steps or (_step(),), version=version, updated_at=_WHEN
    )


def test_execution_is_active_while_any_step_is_non_terminal() -> None:
    assert _execution(_step()).is_active


def test_execution_is_inactive_once_every_step_is_terminal() -> None:
    done = _claimed(StepStatus.SUCCEEDED)
    skipped = _step(step_id="s2", status=StepStatus.SKIPPED, skip_reason=SkipReason.SUPERSEDED)
    assert not _execution(done, skipped).is_active


def test_failed_step_leaves_the_execution_active() -> None:
    """FAILED is terminal only if nobody retries, so it must not read as done."""
    assert _execution(_claimed(StepStatus.FAILED)).is_active


def test_indeterminate_step_leaves_the_execution_active() -> None:
    """An ambiguous step needs resolving, so it cannot count as finished."""
    assert _execution(_claimed(StepStatus.INDETERMINATE)).is_active


def test_only_a_running_step_counts_as_live() -> None:
    assert _execution(_claimed(StepStatus.RUNNING)).has_live_step


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        (StepStatus.FAILED, {}),
        (StepStatus.INDETERMINATE, {}),
    ],
)
def test_unfinished_but_not_running_steps_are_not_live(
    status: StepStatus, extra: dict[str, object]
) -> None:
    """The bug this guards: blocking deletion on ``is_active`` voids erasure forever.

    A step that failed with retries exhausted, or one left INDETERMINATE, never
    becomes terminal on its own. If deletion keyed on ``is_active`` the goal
    could never be erased — so the two predicates must stay distinct.
    """
    execution = _execution(_claimed(status, **extra))
    assert execution.is_active
    assert not execution.has_live_step


# --- finished_at must match the status ----------------------------------


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        (StepStatus.SUCCEEDED, {}),
        (StepStatus.FAILED, {}),
        (StepStatus.INDETERMINATE, {}),
    ],
)
def test_finished_status_requires_finished_at(status: StepStatus, extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="requires finished_at"):
        _claimed(status, finished_at=None, **extra)


def test_running_step_cannot_claim_to_have_finished() -> None:
    with pytest.raises(ValidationError, match="cannot have finished_at"):
        _claimed(StepStatus.RUNNING, finished_at=_WHEN)


def test_pending_step_cannot_claim_to_have_finished() -> None:
    with pytest.raises(ValidationError, match="cannot have finished_at"):
        _step(finished_at=_WHEN)


# --- Non-finite floats have no JSON representation ----------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_parameters_are_rejected(bad: float) -> None:
    """These satisfy ``float`` but would change value on the way through JSON."""
    with pytest.raises(ValidationError, match="no JSON representation"):
        PlanStep(id="s1", intent="i", capability="c", parameters={"x": bad})


def test_non_finite_values_are_rejected_when_nested() -> None:
    with pytest.raises(ValidationError, match="no JSON representation"):
        PlanStep(id="s1", intent="i", capability="c", parameters={"a": {"b": [1.0, float("inf")]}})


def test_non_finite_output_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no JSON representation"):
        _claimed(StepStatus.SUCCEEDED, output={"score": float("nan")})


def test_ordinary_floats_still_round_trip() -> None:
    step = PlanStep(id="s1", intent="i", capability="c", parameters={"x": 1.5})
    assert TypeAdapter(PlanStep).validate_json(step.model_dump_json()) == step


# --- Values with no JSON encoding (issue #121) --------------------------
# Plan parameters and step outputs are ``FrozenJson`` holders, so they inherit
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
def test_step_parameters_with_a_lone_surrogate_are_rejected(
    parameters: dict[str, Any],
) -> None:
    """A lone surrogate is a ``str`` with no UTF-8 encoding (ADR-0021 §1)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        PlanStep(id="s1", intent="i", capability="c", parameters=parameters)


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param({"n": 10**5000}, id="a value"),
        pytest.param({"nested": {"n": -(10**5000)}}, id="nested in a mapping"),
        pytest.param({"items": [10**5000]}, id="inside a sequence"),
    ],
)
def test_step_parameters_with_an_unrenderable_integer_are_rejected(
    parameters: dict[str, Any],
) -> None:
    """``json.dumps`` renders an int through ``str()``; CPython refuses one past
    its integer-string conversion limit, so the value has no JSON encoding.

    ``pinned_int_str_digits`` holds the limit at the default so ``10**5000``
    stays unrenderable under a raised or disabled ``PYTHONINTMAXSTRDIGITS``
    (#406)."""
    with pinned_int_str_digits(), pytest.raises(ValidationError, match="no JSON encoding"):
        PlanStep(id="s1", intent="i", capability="c", parameters=parameters)


def test_a_step_output_with_a_lone_surrogate_is_rejected() -> None:
    """The other ``FrozenJson`` holder inherits the same refusal (issue #121)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _claimed(StepStatus.SUCCEEDED, output={"body": "\ud800"})


def test_a_large_but_renderable_value_still_round_trips() -> None:
    """The bound is "can it be encoded", not "is it big" or "is it astral"."""
    step = PlanStep(
        id="s1",
        intent="i",
        capability="c",
        parameters={"n": 10**100, "emoji": "\U0001f389 done"},
    )
    assert TypeAdapter(PlanStep).validate_json(step.model_dump_json()) == step


def test_execution_looks_up_a_step_by_id() -> None:
    execution = _execution(_step(step_id="s1"), _step(step_id="s2"))
    found = execution.step("s2")
    assert found is not None
    assert found.step_id == "s2"
    assert execution.step("nope") is None


def test_execution_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _execution(_step(step_id="s1"), _step(step_id="s1"))


def test_execution_rejects_a_negative_version() -> None:
    with pytest.raises(ValidationError):
        _execution(version=-1)


# --- StepTransition -----------------------------------------------------


def _transition(to_status: StepStatus, **overrides: object) -> StepTransition:
    fields: dict[str, object] = {
        "execution_id": "e1",
        "step_id": "s1",
        "to_status": to_status,
        "expected_version": 0,
    }
    return StepTransition(**(fields | overrides))  # type: ignore[arg-type]


def test_transition_to_skipped_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires a skip_reason"):
        _transition(StepStatus.SKIPPED)


@pytest.mark.parametrize("to_status", _FAILURE)
def test_transition_to_a_failure_status_requires_a_failure(to_status: StepStatus) -> None:
    """The same rule as ``StepExecution``, over ``to_status`` (ADR-0039 §2).

    Both directions on both statuses: ``StepTransition`` and ``StepExecution``
    are two validators expressing one rule, and are exactly the pair that can
    drift.
    """
    with pytest.raises(ValidationError, match="requires a failure"):
        _transition(to_status)


@pytest.mark.parametrize(
    "to_status",
    [StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SUCCEEDED],
)
def test_transition_forbids_a_failure_off_the_failure_statuses(to_status: StepStatus) -> None:
    with pytest.raises(
        ValidationError, match="only valid for a transition to FAILED or INDETERMINATE"
    ):
        _transition(to_status, failure=StepFailure(message="boom"))


def test_transition_rejects_an_output_unless_succeeding() -> None:
    with pytest.raises(ValidationError, match="only valid for a transition to SUCCEEDED"):
        _transition(StepStatus.RUNNING, output={"ref": "ABC"})


def test_transition_is_frozen() -> None:
    transition = _transition(StepStatus.RUNNING)
    with pytest.raises(ValidationError):
        transition.to_status = StepStatus.SUCCEEDED


def test_transition_carries_no_approval_ref_requirement_of_its_own() -> None:
    """A retry inherits the step's existing approval_ref, so the command may omit it.

    Legality against the *current* status is the tracker's job, not the type's.
    """
    assert _transition(StepStatus.RUNNING).approval_ref is None


# --- StepTransition output with no JSON encoding (issue #121, #409) ------
# StepTransition.output is a FrozenJsonValue holder, exactly like
# StepExecution.output, so it inherits _freeze_json's refusal of a value that
# satisfies its Python type but has no portable encoding. #401 pinned that for
# PlanStep.parameters and StepExecution.output; this carrier carries the same
# guarantee and had no field-specific regression until #409.


def test_a_transition_output_with_a_lone_surrogate_is_rejected() -> None:
    """A lone surrogate is a ``str`` with no UTF-8 encoding (ADR-0021 §1)."""
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _transition(StepStatus.SUCCEEDED, output={"body": "\ud800"})


def test_a_transition_output_with_an_unrenderable_integer_is_rejected() -> None:
    """``json.dumps`` renders an int through ``str()``; CPython refuses one past
    its integer-string conversion limit, so the value has no JSON encoding.

    ``pinned_int_str_digits`` holds the limit at the default so ``10**5000``
    stays unrenderable under a raised or disabled ``PYTHONINTMAXSTRDIGITS``
    (#406)."""
    with pinned_int_str_digits(), pytest.raises(ValidationError, match="no JSON encoding"):
        _transition(StepStatus.SUCCEEDED, output={"n": 10**5000})


def test_an_ordinary_transition_output_still_round_trips() -> None:
    """The bound is "can it be encoded", not "is it big" or "is it astral"."""
    transition = _transition(
        StepStatus.SUCCEEDED, output={"n": 10**100, "emoji": "\U0001f389 done"}
    )
    assert TypeAdapter(StepTransition).validate_json(transition.model_dump_json()) == transition


def test_a_scalar_transition_output_is_accepted() -> None:
    """output is a single ``FrozenJsonValue``, not a mapping: a bare scalar is a
    valid output, so a regression narrowing the field to a mapping is caught.
    """
    transition = _transition(StepStatus.SUCCEEDED, output="done")
    assert transition.output == "done"
    assert TypeAdapter(StepTransition).validate_json(transition.model_dump_json()) == transition


def test_a_scalar_transition_output_with_a_lone_surrogate_is_rejected() -> None:
    """A bare scalar runs through ``_freeze_json`` too, so an unencodable scalar
    is refused — not only an unencodable value nested inside a mapping. Guards a
    regression that checks mapping values but admits a bare unencodable string.
    """
    with pytest.raises(ValidationError, match="no JSON encoding"):
        _transition(StepStatus.SUCCEEDED, output="\ud800")


# --- GoalDeletion -------------------------------------------------------


def test_refused_deletion_must_name_what_blocked_it() -> None:
    with pytest.raises(ValidationError, match="must name the executions"):
        GoalDeletion(deleted=False)


def test_successful_deletion_cannot_be_blocked() -> None:
    with pytest.raises(ValidationError, match="cannot be blocked_by"):
        GoalDeletion(deleted=True, blocked_by=("e1",))


def test_deletion_reports_erased_indeterminate_steps() -> None:
    """The warning the contract promises the user has to survive in the result."""
    result = GoalDeletion(deleted=True, plans_removed=1, indeterminate_steps=("s1",))
    assert result.indeterminate_steps == ("s1",)


# --- ADR-0226: the read request the planner may name beside its plan -----
# §11 item 11: "Every condition §4 puts on the models is refused by the models,
# arm for arm, and none of them is left to a caller." Each arm below is one of the
# nine that section enumerates.


def _hop(*labels: str) -> ReadAsk:
    return ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels)


def _query(text: str = "which lender did you recommend?") -> ReadAsk:
    return ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text)


def test_a_plan_asks_for_no_read_by_default() -> None:
    """ADR-0226 §4's default, which is what makes the field additive.

    ``None`` is the semantically correct answer for a planner that knows nothing of
    this envelope, and no implementation reads it as an error, a degradation, or an
    instruction to service a default read — so the *positive* fact asserted here is
    that constructing a plan exactly as every existing caller does still produces
    one that asked for nothing.
    """
    plan = ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_WHEN)

    assert plan.read_request is None


def test_a_request_carries_the_two_kinds_it_was_given() -> None:
    """The positive case, so the refusals below cannot be satisfied by a model that
    refuses everything."""
    request = ReadRequest(asks=(_hop("M1", "M2"), _query()))

    assert [ask.kind for ask in request.asks] == [ReadKind.CITATION_HOP, ReadKind.SIGHTED_QUERY]
    assert request.asks[0].labels == ("M1", "M2")
    assert request.asks[1].query == "which lender did you recommend?"


def test_an_empty_request_is_refused() -> None:
    """§11 item 11 names this arm as the one worth stating.

    "A ``ReadRequest`` that admitted no ask would be a non-``None``
    ``read_request``, which §8 defines as a turn the trigger fired on, servicing
    nothing — a fire-rate numerator with no read under it." The instrument's
    numerator is what this refusal protects, which is why the condition is the
    model's and not a servicer's.
    """
    with pytest.raises(ValidationError, match="at least one ask"):
        ReadRequest(asks=())


def test_two_asks_of_one_kind_are_refused() -> None:
    """ADR-0226 §2: "one emission may carry at most one ask of each kind".

    Everything downstream is stated over one ask per kind — §6's budget and
    cross-kind precedence, §7's deduplication, §9's per-kind counts — so a second
    ask of a kind is not an emission with a defined servicing at all.
    """
    with pytest.raises(ValidationError, match="at most one ask of each kind"):
        ReadRequest(asks=(_query("first"), _query("second")))


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "], ids=["empty", "spaces", "whitespace"])
def test_a_sighted_query_ask_refuses_a_blank_query(blank: str) -> None:
    """§4: "a non-blank query for ``SIGHTED_QUERY``".

    A blank query is a fired trigger with nothing to search for: it would reach
    ``assemble_by_band`` as an empty relevance selection, spend the budget's
    ordering and the audit's counts on a read that asked for nothing, and register
    in the fire rate as a judged insufficiency.
    """
    with pytest.raises(ValidationError):
        ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=blank)


def test_a_sighted_query_ask_refuses_labels() -> None:
    """§4: a ``SIGHTED_QUERY`` ask carries a query "and no labels".

    An ask carrying both is two asks wearing one kind's name, and §6's precedence —
    the hop first, the query second — has no answer for which half of it runs when.
    """
    with pytest.raises(ValidationError, match="must not carry labels"):
        ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="where?", labels=("M1",))


def test_a_sighted_query_ask_refuses_a_missing_query() -> None:
    """The other half of the same clause: the kind's own argument is required."""
    with pytest.raises(ValidationError, match="must carry a query"):
        ReadAsk(kind=ReadKind.SIGHTED_QUERY)


def test_a_citation_hop_ask_refuses_naming_no_label() -> None:
    """§4: "at least one label for ``CITATION_HOP``"."""
    with pytest.raises(ValidationError, match="at least one label"):
        ReadAsk(kind=ReadKind.CITATION_HOP)


def test_a_citation_hop_ask_refuses_a_query() -> None:
    """§4: a ``CITATION_HOP`` ask carries labels "and no query"."""
    with pytest.raises(ValidationError, match="must not carry a query"):
        ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",), query="where?")


def test_a_citation_hop_ask_refuses_a_third_label() -> None:
    """ADR-0226 §6's cap, which is a measurement and not a round number.

    Two is "the figure the replay's own real arm used", so the 47.6% conversion it
    measured is the conversion of this bound rather than of a looser one. Uncapped,
    two labels at ``MAX_EVIDENCE_CITATIONS`` would be 128 records against a
    ``get_many`` that is contractually uncapped.
    """
    assert MAX_HOP_LABELS == 2
    with pytest.raises(ValidationError, match="at most 2 labels"):
        _hop("M1", "M2", "M3")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        pytest.param(ReadAsk, {"kind": "citation_hop", "labels": ["M1"], "extra": "x"}, id="ask"),
        pytest.param(
            ReadRequest,
            {"asks": [{"kind": "citation_hop", "labels": ["M1"]}], "extra": "x"},
            id="request",
        ),
    ],
)
def test_both_models_refuse_an_unknown_field(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    """``extra="forbid"`` on both, for the reason every boundary model here has it.

    A member the contract does not name is a member no reader can be relied on to
    carry, and on a document that outlives the code that wrote it — an
    ``ActionPlan`` reaches ``PlanExport`` — a tolerated extra is a shape change
    nothing announced.
    """
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        pytest.param("ask", "labels", ("M9",), id="ask-labels"),
        pytest.param("ask", "kind", ReadKind.SIGHTED_QUERY, id="ask-kind"),
        pytest.param("request", "asks", (), id="request-asks"),
    ],
)
def test_both_models_refuse_mutation_after_construction(
    target: str, field: str, value: object
) -> None:
    """A plan is an audit record all the way down (ADR-0014 §2, ADR-0068).

    ``frozen=True`` is why the emission cannot be edited after the plan records it:
    a frozen plan holding a mutable request would let a later stage rewrite what the
    planner asked for, after the decision the plan is a record of.
    """
    ask = _hop("M1")
    subject: object = ask if target == "ask" else ReadRequest(asks=(ask,))

    with pytest.raises(ValidationError):
        setattr(subject, field, value)


def test_a_label_that_resolves_to_nothing_is_still_constructible() -> None:
    """ADR-0226 §3's discard is the loop's, so the models must admit its inputs.

    "A string that does not match the form, an *n* below 1 or beyond the sequence's
    length, and a label whose record is no longer live all resolve to nothing … each
    is discarded silently — **not an error**, not a park, not a degradation of the
    turn — and recorded in §9's audit as dropped." A form check here would turn
    exactly that population into a construction failure at the emitting seam, and
    would empty the audit field that exists to count it.
    """
    for label in ("M0", "M999", "banana", "9d2f7a10-8c44-4f2b-9a1e-1c0b5d6e7f80"):
        assert _hop(label).labels == (label,)


def test_the_kind_vocabulary_is_the_two_the_decision_admits() -> None:
    """§1: a closed enumeration, and §4: added to and never renamed.

    Pinned by value as well as by name, because the serialised spelling is what a
    ``PlanExport`` carries and what a later reader matches on — renaming a member
    would silently invalidate every document already written.
    """
    assert {member.value for member in ReadKind} == {"sighted_query", "citation_hop"}
    assert ReadKind.SIGHTED_QUERY.value == "sighted_query"
    assert ReadKind.CITATION_HOP.value == "citation_hop"


# --- PlanExport ---------------------------------------------------------


def test_export_is_versioned_and_defaults_to_empty() -> None:
    export = PlanExport(exported_at=_WHEN)
    assert export.schema_version == 4
    assert export.goals == ()


def test_export_pins_the_schema_version_to_exactly_four() -> None:
    """The label is a fact about the document, not a producer's claim (ADR-0039 §10).

    ``Literal[4]`` refuses an explicit ``3`` — a document of the shape this export
    had before ``ActionPlan`` gained ``supersedes`` does not validate against this
    contract at all (ADR-0228 §5, §6), exactly as a ``2`` stopped validating when it
    gained ``read_request`` — and any other value, so the advertised version cannot
    be mislabelled. The positive default is what a producer gets for free; only the
    rejections pin it.
    """
    assert PlanExport(exported_at=_WHEN, schema_version=4).schema_version == 4
    for stale in (1, 2, 3, 5):
        with pytest.raises(ValidationError):
            PlanExport(exported_at=_WHEN, schema_version=stale)  # type: ignore[arg-type]


def test_export_rejects_a_plan_whose_goal_is_missing() -> None:
    """A dangling reference is a plan whose purpose was lost in transit."""
    orphan = ActionPlan(id="p1", goal_id="gone", steps=(), created_at=_WHEN)
    with pytest.raises(ValidationError, match="goal is missing"):
        PlanExport(exported_at=_WHEN, plans=(orphan,))


def test_export_rejects_an_execution_whose_plan_is_missing() -> None:
    execution = ExecutionState(id="e1", plan_id="gone", steps=(), updated_at=_WHEN)
    with pytest.raises(ValidationError, match="plan is missing"):
        PlanExport(exported_at=_WHEN, executions=(execution,))


def test_export_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate goal ids"):
        PlanExport(exported_at=_WHEN, goals=(_goal(), _goal()))


def test_export_rejects_an_execution_that_does_not_match_its_plan() -> None:
    """A misaligned export is unsafe to resume — steps are positional."""
    plan = ActionPlan(
        id="p1",
        goal_id="g1",
        steps=(
            PlanStep(id="s1", intent="a", capability="c"),
            PlanStep(id="s2", intent="b", capability="c"),
        ),
        created_at=_WHEN,
    )
    execution = ExecutionState(
        id="e1",
        plan_id="p1",
        steps=(_step(step_id="s2"), _step(step_id="ghost")),
        updated_at=_WHEN,
    )
    with pytest.raises(ValidationError, match="does not line up"):
        PlanExport(exported_at=_WHEN, goals=(_goal(),), plans=(plan,), executions=(execution,))


def test_a_step_cannot_finish_before_it_started() -> None:
    """A clock that steps backwards would otherwise write an impossible history."""
    with pytest.raises(ValidationError, match="cannot finish before it started"):
        _claimed(
            StepStatus.FAILED,
            started_at=datetime(2026, 2, 1, tzinfo=UTC),
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_export_round_trips_through_json() -> None:
    """A v3 export with a failed step and a read request survives a round-trip.

    Carrying both is the point, because each is why a version moved: ``StepFailure``
    was new to the exported shape at 2 (ADR-0039 §10), and ``ActionPlan``'s
    ``read_request`` is new to it at 3 (ADR-0226 §4). A document carrying either but
    labelled with the other version does not validate at all, which is the whole of
    what the label is for.
    """
    plan = ActionPlan(
        id="p1",
        goal_id="g1",
        steps=(PlanStep(id="s1", intent="mail", capability="send_email"),),
        created_at=_WHEN,
        read_request=ReadRequest(
            asks=(
                ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="which lender did you recommend?"),
                ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M2", "M5")),
            )
        ),
    )
    execution = ExecutionState(
        id="e1",
        plan_id="p1",
        steps=(
            _claimed(
                StepStatus.FAILED,
                failure=StepFailure(kind=ToolFailureKind.UNAVAILABLE, message="down"),
            ),
        ),
        updated_at=_WHEN,
    )
    export = PlanExport(exported_at=_WHEN, goals=(_goal(),), plans=(plan,), executions=(execution,))
    restored = TypeAdapter(PlanExport).validate_json(export.model_dump_json())
    assert restored == export
    assert restored.schema_version == 4
    request = restored.plans[0].read_request
    assert request is not None
    assert {ask.kind for ask in request.asks} == {ReadKind.SIGHTED_QUERY, ReadKind.CITATION_HOP}
    step = restored.executions[0].steps[0]
    assert step.failure is not None
    assert step.failure.kind is ToolFailureKind.UNAVAILABLE
    assert step.failure.message == "down"


# --- ADR-0068: the planning record graph is frozen all the way down -----


def test_goal_is_frozen_including_its_provenance() -> None:
    """A ``Goal`` and the ``Provenance`` it carries reject post-construction edits."""
    goal = _goal()
    with pytest.raises(ValidationError):
        goal.statement = "tampered"
    with pytest.raises(ValidationError):
        goal.provenance.confidence = 0.1  # the nested model is frozen too


def test_step_execution_is_frozen() -> None:
    step = _step()
    with pytest.raises(ValidationError):
        step.status = StepStatus.SUCCEEDED


def test_execution_state_is_frozen_including_its_step_elements() -> None:
    execution = _execution(_step())
    with pytest.raises(ValidationError):
        execution.version = 99
    with pytest.raises(ValidationError):
        execution.steps[0].status = StepStatus.SUCCEEDED  # the nested element is frozen


def test_plan_export_is_deeply_immutable() -> None:
    """Issue #41's cited scenario: a caller cannot rewrite a goal inside an export.

    ``PlanExport`` was already ``frozen=True`` around a mutable ``Goal``, so
    ``export.goals[0].statement = ...`` used to succeed and silently break the
    export's referential integrity. ADR-0068 freezes ``Goal``, so it now raises —
    the wrapper needed no change of its own.
    """
    export = PlanExport(exported_at=_WHEN, goals=(_goal(),))
    with pytest.raises(ValidationError):
        export.goals[0].statement = "tampered"
