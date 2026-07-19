"""Tests for the planning domain types (ADR-0014).

The validators here exist to make illegal execution states unrepresentable, so
these tests are mostly about what the types *refuse*.
"""

from __future__ import annotations

import copy
import pickle
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
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
    SkipReason,
    StepExecution,
    StepStatus,
    StepTransition,
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


def _claimed(status: StepStatus, **overrides: object) -> StepExecution:
    """A step carrying the full set of marks a claimed step requires."""
    fields: dict[str, object] = {
        "step_id": "s1",
        "status": status,
        "attempts": 1,
        "bound_tool": "smtp",
        "approval_ref": "perm-1",
        "started_at": _WHEN,
    }
    return StepExecution(**(fields | overrides))  # type: ignore[arg-type]


# --- Goal ---------------------------------------------------------------


def test_goal_defaults_to_active() -> None:
    assert _goal().status is GoalStatus.ACTIVE


def test_goal_rejects_a_blank_statement() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        _goal(statement="   ")


def test_goal_normalises_naive_timestamps_to_utc() -> None:
    goal = _goal(created_at=datetime(2026, 1, 1), deadline=datetime(2026, 9, 1))  # noqa: DTZ001
    assert goal.created_at.tzinfo is UTC
    assert goal.deadline is not None
    assert goal.deadline.tzinfo is UTC


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
    extra: dict[str, object] = {"approval_ref": None}
    if status is StepStatus.FAILED:
        extra["error"] = "boom"
    with pytest.raises(ValidationError, match="approval_ref"):
        _claimed(status, **extra)


def test_claimed_step_requires_a_bound_tool() -> None:
    with pytest.raises(ValidationError, match="bound_tool"):
        _claimed(StepStatus.RUNNING, bound_tool=None)


def test_claimed_step_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValidationError, match="at least one attempt"):
        _claimed(StepStatus.RUNNING, attempts=0)


def test_pending_step_needs_none_of_the_claim_marks() -> None:
    assert _step().status is StepStatus.PENDING


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


def test_failed_step_requires_an_error() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        _claimed(StepStatus.FAILED)


def test_error_is_rejected_on_a_step_that_did_not_fail() -> None:
    with pytest.raises(ValidationError, match="only valid for a FAILED"):
        _claimed(StepStatus.RUNNING, error="boom")


def test_output_is_rejected_on_a_step_that_did_not_succeed() -> None:
    with pytest.raises(ValidationError, match="only valid for a SUCCEEDED"):
        _claimed(StepStatus.RUNNING, output={"ref": "ABC"})


def test_succeeded_step_carries_a_frozen_output() -> None:
    step = _claimed(StepStatus.SUCCEEDED, output={"ref": "ABC"})
    assert step.output is not None
    with pytest.raises(TypeError):
        step.output["ref"] = "XYZ"  # type: ignore[index]


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
    assert _execution(_claimed(StepStatus.FAILED, error="boom")).is_active


def test_indeterminate_step_leaves_the_execution_active() -> None:
    """An ambiguous step needs resolving, so it cannot count as finished."""
    assert _execution(_claimed(StepStatus.INDETERMINATE)).is_active


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


def test_transition_to_failed_requires_an_error() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        _transition(StepStatus.FAILED)


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


# --- PlanExport ---------------------------------------------------------


def test_export_is_versioned_and_defaults_to_empty() -> None:
    export = PlanExport(exported_at=_WHEN)
    assert export.schema_version == 1
    assert export.goals == ()


def test_export_round_trips_through_json() -> None:
    plan = ActionPlan(
        id="p1",
        goal_id="g1",
        steps=(PlanStep(id="s1", intent="mail", capability="send_email"),),
        created_at=_WHEN,
    )
    export = PlanExport(exported_at=_WHEN, goals=(_goal(),), plans=(plan,))
    assert TypeAdapter(PlanExport).validate_json(export.model_dump_json()) == export
