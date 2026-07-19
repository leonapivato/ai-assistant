"""The deterministic execution-state tracker (ADR-0014 §4).

VISION §7 puts state transitions, retries and execution status in the hands of
deterministic code. This module is that code: it owns which moves are legal,
enforces the retry ceiling, and stamps the timestamps. No model output ever sets
a :class:`~ai_assistant.core.types.StepStatus`.

Every operation returns a *new* :class:`~ai_assistant.core.types.ExecutionState`
rather than mutating one, so a caller cannot half-apply a transition and persist
the result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.errors import (
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    ExecutionState,
    SkipReason,
    StepExecution,
    StepStatus,
    StepTransition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ActionPlan

#: The transition graph from ADR-0014 §4. Anything not listed here is rejected.
_LEGAL_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SKIPPED}
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED}),
    StepStatus.RUNNING: frozenset(
        {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE}
    ),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING}),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.INDETERMINATE: frozenset(),
}

#: How many times a step may be claimed before its retry budget is spent.
DEFAULT_MAX_ATTEMPTS = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _revalidated(step: StepExecution) -> StepExecution:
    """Re-run ``StepExecution``'s validators over a step built by ``model_copy``.

    ``model_copy(update=...)`` deliberately skips validation, so without this a
    transition could persist a state the type is supposed to make impossible —
    a claimed step with no ``approval_ref``, say. Since those invariants are the
    contract's teeth, every transition result is put back through them.
    """
    return StepExecution.model_validate(step.model_dump())


class PlanExecution:
    """Applies step transitions to an execution, enforcing the legal graph.

    Args:
        now: Clock used to stamp transitions; injectable so tests are
            deterministic, matching `memory` and `context`.
        max_attempts: How many times a single step may be claimed before
            :class:`~ai_assistant.core.errors.RetriesExhaustedError`. The
            ceiling lives here, not in a model's judgement (VISION §7).
    """

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utcnow,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        """Create a tracker with an injectable clock and retry ceiling."""
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._now = now
        self._max_attempts = max_attempts

    def start(self, plan: ActionPlan, *, execution_id: str) -> ExecutionState:
        """Open a fresh execution for ``plan``.

        The state is derived from the plan — one ``PENDING`` step each, in order
        — rather than supplied, which is what guarantees the positional
        correspondence the rest of the contract assumes.
        """
        return ExecutionState(
            id=execution_id,
            plan_id=plan.id,
            steps=tuple(StepExecution(step_id=step.id) for step in plan.steps),
            version=0,
            updated_at=self._now(),
        )

    def apply(self, state: ExecutionState, transition: StepTransition) -> ExecutionState:
        """Return ``state`` advanced by ``transition``.

        Args:
            state: The execution as currently stored.
            transition: The move to apply.

        Returns:
            A new state with the step updated and ``version`` incremented.

        Raises:
            StaleExecutionError: If ``transition.expected_version`` no longer
                matches — someone else has written since the caller read.
            IllegalTransitionError: If the move is not legal from the step's
                current status.
            RetriesExhaustedError: If a retry would exceed the ceiling.
            PlanningError: If the execution or step ids do not match.
        """
        if transition.execution_id != state.id:
            msg = f"transition targets execution {transition.execution_id}, not {state.id}"
            raise PlanningError(msg)

        if transition.expected_version != state.version:
            msg = (
                f"execution {state.id} is at version {state.version}, "
                f"but the write was computed against {transition.expected_version}"
            )
            raise StaleExecutionError(msg)

        current = state.step(transition.step_id)
        if current is None:
            msg = f"execution {state.id} has no step {transition.step_id}"
            raise PlanningError(msg)

        if transition.to_status not in _LEGAL_TRANSITIONS[current.status]:
            msg = (
                f"step {current.step_id} cannot go from {current.status} to {transition.to_status}"
            )
            raise IllegalTransitionError(msg)

        updated = _revalidated(self._advance(current, transition))
        return state.model_copy(
            update={
                "steps": tuple(
                    updated if step.step_id == updated.step_id else step for step in state.steps
                ),
                "version": state.version + 1,
                "updated_at": self._now(),
            }
        )

    def cancel(self, state: ExecutionState) -> ExecutionState:
        """Drive every not-yet-started step to a terminal state.

        What an executor runs before a goal can be deleted: `PENDING` and
        `AWAITING_APPROVAL` steps become `SKIPPED`/`SUPERSEDED`. A `RUNNING`
        step is deliberately left alone — only the executor that owns the live
        tool call can stop it, and it resolves the step via
        :meth:`abandon_running` once it has.
        """
        cancellable = {StepStatus.PENDING, StepStatus.AWAITING_APPROVAL}
        steps = tuple(
            _revalidated(
                step.model_copy(
                    update={
                        "status": StepStatus.SKIPPED,
                        "skip_reason": SkipReason.SUPERSEDED,
                    }
                )
            )
            if step.status in cancellable
            else step
            for step in state.steps
        )
        return self._replace_steps(state, steps)

    def abandon_running(self, state: ExecutionState) -> ExecutionState:
        """Mark every `RUNNING` step `INDETERMINATE`, for crash recovery.

        A step still `RUNNING` when nothing is executing it may or may not have
        caused its side effect — planning cannot tell. Rather than guess, it
        becomes `INDETERMINATE`, which is never auto-retried and must be
        resolved explicitly (ADR-0014 §4).
        """
        stopped = self._now()
        steps = tuple(
            _revalidated(
                step.model_copy(update={"status": StepStatus.INDETERMINATE, "finished_at": stopped})
            )
            if step.status is StepStatus.RUNNING
            else step
            for step in state.steps
        )
        return self._replace_steps(state, steps)

    def _replace_steps(
        self, state: ExecutionState, steps: tuple[StepExecution, ...]
    ) -> ExecutionState:
        """Return ``state`` carrying ``steps``, bumped a version, unless unchanged."""
        if steps == state.steps:
            return state
        return state.model_copy(
            update={"steps": steps, "version": state.version + 1, "updated_at": self._now()}
        )

    def _advance(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Build the step's next value for a move already known to be legal."""
        if transition.to_status is StepStatus.RUNNING:
            return self._to_running(step, transition)
        if transition.to_status is StepStatus.AWAITING_APPROVAL:
            return step.model_copy(
                update={
                    "status": StepStatus.AWAITING_APPROVAL,
                    "bound_tool": transition.bound_tool or step.bound_tool,
                }
            )
        if transition.to_status is StepStatus.SKIPPED:
            return step.model_copy(
                update={
                    "status": StepStatus.SKIPPED,
                    "skip_reason": transition.skip_reason,
                    "approval_ref": transition.approval_ref or step.approval_ref,
                }
            )
        return self._to_finished(step, transition)

    def _to_running(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Claim the step: the move that must be committed *before* a tool runs."""
        if step.status is StepStatus.FAILED and step.attempts >= self._max_attempts:
            msg = (
                f"step {step.step_id} has used its {self._max_attempts} attempts; "
                "it cannot be retried again"
            )
            raise RetriesExhaustedError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        if approval_ref is None:
            msg = (
                f"step {step.step_id} cannot run without an approval_ref: "
                "every executed step must name the decision that authorised it"
            )
            raise IllegalTransitionError(msg)

        bound_tool = transition.bound_tool or step.bound_tool
        if bound_tool is None:
            msg = f"step {step.step_id} cannot run without a bound_tool"
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.RUNNING,
                "attempts": step.attempts + 1,
                "bound_tool": bound_tool,
                "approval_ref": approval_ref,
                "started_at": self._now(),
                # A retry re-opens the step, so last attempt's outcome is cleared.
                "finished_at": None,
                "error": None,
                "output": None,
            }
        )

    def _to_finished(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Close the step out as SUCCEEDED, FAILED, or INDETERMINATE."""
        return step.model_copy(
            update={
                "status": transition.to_status,
                "output": transition.output,
                "error": transition.error,
                "finished_at": self._now(),
            }
        )
