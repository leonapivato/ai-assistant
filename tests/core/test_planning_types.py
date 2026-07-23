"""Tests for the planning domain types (ADR-0014).

The validators here exist to make illegal execution states unrepresentable, so
these tests are mostly about what the types *refuse*.
"""

from __future__ import annotations

import copy
import pickle
from datetime import UTC, datetime, timedelta, timezone

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
    assert export.schema_version == 2
    assert export.goals == ()


def test_export_pins_the_schema_version_to_exactly_two() -> None:
    """The label is a fact about the document, not a producer's claim (ADR-0039 §10).

    ``Literal[2]`` refuses an explicit ``1`` — a v1 document does not validate
    against this contract at all — and any other value, so the advertised
    version cannot be mislabelled. The positive default is what a producer gets
    for free; only the rejections pin it.
    """
    assert PlanExport(exported_at=_WHEN, schema_version=2).schema_version == 2
    with pytest.raises(ValidationError):
        PlanExport(exported_at=_WHEN, schema_version=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PlanExport(exported_at=_WHEN, schema_version=3)  # type: ignore[arg-type]


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
    """A v2 export with a failed step's failure survives a JSON round-trip.

    Carrying the failure is the point: ``StepFailure`` is new to the exported
    shape, which is exactly what ``schema_version`` moving to 2 announces.
    """
    plan = ActionPlan(
        id="p1",
        goal_id="g1",
        steps=(PlanStep(id="s1", intent="mail", capability="send_email"),),
        created_at=_WHEN,
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
    assert restored.schema_version == 2
    step = restored.executions[0].steps[0]
    assert step.failure is not None
    assert step.failure.kind is ToolFailureKind.UNAVAILABLE
    assert step.failure.message == "down"
