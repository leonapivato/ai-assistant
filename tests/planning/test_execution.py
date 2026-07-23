"""Tests for the PlanExecution transition tracker (ADR-0014 §4).

The store's conformance suite covers the transitions reachable through the
contract. This module covers what only the tracker exposes: cancellation, crash
recovery, and the ceiling being configurable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_assistant.core.errors import (
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
)
from ai_assistant.core.types import (
    ActionPlan,
    PlanStep,
    SkipReason,
    StepFailure,
    StepStatus,
    StepTransition,
)
from ai_assistant.planning import PlanExecution

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _now() -> datetime:
    return _WHEN


def _plan(steps: int = 2) -> ActionPlan:
    return ActionPlan(
        id="p1",
        goal_id="g1",
        steps=tuple(
            PlanStep(id=f"s{index}", intent=f"step {index}", capability="send_email")
            for index in range(1, steps + 1)
        ),
        created_at=_WHEN,
    )


def _tracker(**kwargs: object) -> PlanExecution:
    return PlanExecution(now=_now, **kwargs)  # type: ignore[arg-type]


def _claim(execution_id: str, step_id: str, version: int) -> StepTransition:
    return StepTransition(
        execution_id=execution_id,
        step_id=step_id,
        to_status=StepStatus.RUNNING,
        expected_version=version,
        bound_tool="smtp",
        approval_ref="perm-1",
    )


def test_a_naive_clock_is_refused_at_the_producer() -> None:
    """Inverted by ADR-0026: ``_revalidated_state`` used to normalise this.

    ``model_copy`` skips validators, and the validator that caught a naive
    ``updated_at`` on the re-validation path is exactly what ADR-0023 removes —
    so the guard is at the producer, and the reading is refused rather than
    attributed.
    """
    naive = PlanExecution(now=lambda: datetime(2026, 1, 1))  # noqa: DTZ001

    with pytest.raises(PlanningError, match="PlanExecution"):
        naive.start(_plan(1), execution_id="e1")


def test_a_conforming_clock_still_stamps_every_transition_in_utc() -> None:
    """The other half: nothing about the ordinary path changed."""
    tracker = PlanExecution(now=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    state = tracker.start(_plan(1), execution_id="e1")
    assert state.updated_at.tzinfo is UTC

    claimed = tracker.apply(state, _claim("e1", "s1", state.version))
    assert claimed.updated_at.tzinfo is UTC

    recovered = tracker.abandon_running(claimed)
    assert recovered.updated_at.tzinfo is UTC

    cancelled = tracker.cancel(tracker.start(_plan(1), execution_id="e2"))
    assert cancelled.updated_at.tzinfo is UTC


def test_a_pending_step_is_denied_in_a_single_commit() -> None:
    """A policy `DENY` disposes of the step in one version (ADR-0041).

    The version count is the point of the widening, not a detail. The
    two-commit path this makes unnecessary can be interrupted between the
    commits, leaving the step durably `AWAITING_APPROVAL` for a decision that
    was never a question and that neither `run` nor `resume` will touch
    (#257). Only a caller that takes this edge escapes that.
    """
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    before = state.version

    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.SKIPPED,
            expected_version=state.version,
            skip_reason=SkipReason.APPROVAL_DENIED,
            approval_ref="perm-1",
        ),
    )

    assert state.version == before + 1
    step = state.step("s1")
    assert step is not None
    assert step.status is StepStatus.SKIPPED
    assert step.skip_reason is SkipReason.APPROVAL_DENIED
    assert step.approval_ref == "perm-1"


def test_a_pending_denial_without_an_approval_ref_is_refused() -> None:
    """The reference, not the queueing, is what the rule protects (ADR-0041 §2)."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    with pytest.raises(IllegalTransitionError, match="without an approval_ref"):
        tracker.apply(
            state,
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
            ),
        )


@pytest.mark.parametrize(
    "reason",
    [SkipReason.UNMET_DEPENDENCY, SkipReason.NO_CAPABLE_TOOL, SkipReason.SUPERSEDED],
)
def test_the_other_pending_skip_reasons_are_unchanged(reason: SkipReason) -> None:
    """ADR-0041 widens `PENDING` by one reason and leaves the rest alone.

    Each still skips without an `approval_ref`, which the denial now requires:
    the new rule is scoped to `APPROVAL_DENIED` and did not become a general
    obligation on skipping.
    """
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")

    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.SKIPPED,
            expected_version=state.version,
            skip_reason=reason,
        ),
    )

    step = state.step("s1")
    assert step is not None
    assert step.status is StepStatus.SKIPPED
    assert step.skip_reason is reason
    assert step.approval_ref is None


def test_an_awaiting_step_cannot_be_skipped_for_a_planning_reason() -> None:
    """NO_CAPABLE_TOOL is decided before approval is sought, not after."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.AWAITING_APPROVAL,
            expected_version=state.version,
            bound_tool="smtp",
        ),
    )
    with pytest.raises(IllegalTransitionError, match="cannot be skipped"):
        tracker.apply(
            state,
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.NO_CAPABLE_TOOL,
            ),
        )


def test_start_derives_one_pending_step_per_plan_step() -> None:
    state = _tracker().start(_plan(3), execution_id="e1")
    assert [step.step_id for step in state.steps] == ["s1", "s2", "s3"]
    assert all(step.status is StepStatus.PENDING for step in state.steps)


def test_a_transition_for_another_execution_is_rejected() -> None:
    tracker = _tracker()
    state = tracker.start(_plan(), execution_id="e1")
    with pytest.raises(PlanningError, match="targets execution"):
        tracker.apply(state, _claim("other", "s1", state.version))


def test_cancel_supersedes_steps_that_never_started() -> None:
    tracker = _tracker()
    state = tracker.start(_plan(2), execution_id="e1")
    cancelled = tracker.cancel(state)

    assert all(step.status is StepStatus.SKIPPED for step in cancelled.steps)
    assert all(step.skip_reason is SkipReason.SUPERSEDED for step in cancelled.steps)
    assert not cancelled.is_active


def test_cancel_leaves_a_running_step_alone() -> None:
    """Only the executor owning the live tool call can stop it."""
    tracker = _tracker()
    state = tracker.start(_plan(2), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))

    cancelled = tracker.cancel(state)

    running = cancelled.step("s1")
    assert running is not None
    assert running.status is StepStatus.RUNNING
    assert cancelled.has_live_step


def test_cancel_is_a_no_op_when_nothing_is_cancellable() -> None:
    """A no-op must not burn a version, or it would break a concurrent writer's CAS."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))

    assert tracker.cancel(state) is state


def test_abandon_running_marks_indeterminate_not_failed() -> None:
    """A crash mid-effect is ambiguous; guessing either way would be wrong."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))

    recovered = tracker.abandon_running(state)

    step = recovered.step("s1")
    assert step is not None
    assert step.status is StepStatus.INDETERMINATE
    assert step.finished_at is not None
    assert not recovered.has_live_step
    assert recovered.is_active  # still needs resolving


def test_abandon_running_records_a_failure_with_no_kind() -> None:
    """The transition #208 is really about now writes a diagnostic (ADR-0039 §7).

    Every recovered ``RUNNING`` step carries a ``StepFailure`` with visible text
    and ``kind=None`` — recovery has no ``ToolResult`` and never had one, so a
    fabricated kind would be wrong, not merely absent.
    """
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))

    recovered = tracker.abandon_running(state)

    step = recovered.step("s1")
    assert step is not None
    assert step.failure is not None
    assert step.failure.kind is None
    assert step.failure.message.strip()


def test_an_indeterminate_step_cannot_be_retried() -> None:
    """It is never auto-retried — that is the whole point of the state."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))
    state = tracker.abandon_running(state)

    with pytest.raises(IllegalTransitionError):
        tracker.apply(state, _claim("e1", "s1", state.version))


def test_the_retry_ceiling_is_configurable() -> None:
    tracker = _tracker(max_attempts=1)
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.FAILED,
            expected_version=state.version,
            failure=StepFailure(message="boom"),
        ),
    )

    with pytest.raises(RetriesExhaustedError):
        tracker.apply(state, _claim("e1", "s1", state.version))


def test_a_zero_retry_ceiling_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        PlanExecution(now=_now, max_attempts=0)


def test_a_retry_clears_the_previous_attempts_outcome() -> None:
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.FAILED,
            expected_version=state.version,
            failure=StepFailure(message="boom"),
        ),
    )
    state = tracker.apply(state, _claim("e1", "s1", state.version))

    step = state.step("s1")
    assert step is not None
    assert step.failure is None
    assert step.finished_at is None
    assert step.attempts == 2


def test_a_retry_inherits_the_original_authorisation() -> None:
    """The claim carries no approval_ref, so it must come from the step."""
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(state, _claim("e1", "s1", state.version))
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.FAILED,
            expected_version=state.version,
            failure=StepFailure(message="boom"),
        ),
    )
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
        ),
    )

    step = state.step("s1")
    assert step is not None
    assert step.approval_ref == "perm-1"


def test_approval_denied_skips_the_step() -> None:
    tracker = _tracker()
    state = tracker.start(_plan(1), execution_id="e1")
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.AWAITING_APPROVAL,
            expected_version=state.version,
            bound_tool="smtp",
        ),
    )
    state = tracker.apply(
        state,
        StepTransition(
            execution_id="e1",
            step_id="s1",
            to_status=StepStatus.SKIPPED,
            expected_version=state.version,
            skip_reason=SkipReason.APPROVAL_DENIED,
            approval_ref="perm-denied",
        ),
    )

    step = state.step("s1")
    assert step is not None
    assert step.status is StepStatus.SKIPPED
    assert step.skip_reason is SkipReason.APPROVAL_DENIED
    assert step.approval_ref == "perm-denied"
