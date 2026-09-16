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

from ai_assistant.core.clock import ClockReadingError, checked_clock
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
    StepFailure,
    StepStatus,
    StepTransition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ActionPlan
    from ai_assistant.planning.effects import BorrowedAct

#: The transition graph from ADR-0014 §4. Anything not listed here is rejected.
#:
#: **ADR-0259 §7 adds exactly three rows and no other.** ``INDETERMINATE →
#: SUCCEEDED``, triggered by a reconciliation that established the effect; and
#: ``PENDING → SUCCEEDED`` and ``AWAITING_APPROVAL → SUCCEEDED``, triggered by a step
#: being satisfied by an effect its goal already completed (§2). Each also sets
#: ``output`` and ``finished_at``, and **none increments** ``attempts``.
#:
#: **Two rows rather than one for the satisfaction**, because §2 takes the claim on
#: both entries — ``StepRunner.run``'s and ``StepRunner.resume``'s — and a resumed step
#: is ``AWAITING_APPROVAL`` in the store, so a single ``PENDING`` row would leave the
#: resumed case with no legal move and the walk stalled at exactly the step that route
#: exists to unstall. **No row is added for a parked step** beyond that: ADR-0259
#: replays nothing, and the ordinary ``AWAITING_APPROVAL → RUNNING`` a user's own
#: answer drives is untouched.
#:
#: **One row out of ``INDETERMINATE`` rather than two** is a consequence of ADR-0259
#: §3's mechanism and not a gap in it: the one reconciliation route it admits is a
#: **read**, which has no effect to have failed to happen, so the transition that
#: would record a proven non-effect has no producer and adding a row nothing writes
#: would be the vocabulary-with-no-producer problem ADR-0249 §5 names.
#: ``INDETERMINATE → FAILED``, ``INDETERMINATE → RUNNING``, ``INDETERMINATE →
#: SKIPPED`` and every other move stay **illegal**.
_LEGAL_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {
            StepStatus.RUNNING,
            StepStatus.AWAITING_APPROVAL,
            StepStatus.SKIPPED,
            StepStatus.SUCCEEDED,
        }
    ),
    StepStatus.AWAITING_APPROVAL: frozenset(
        {StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.SUCCEEDED}
    ),
    StepStatus.RUNNING: frozenset(
        {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE}
    ),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING}),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.INDETERMINATE: frozenset({StepStatus.SUCCEEDED}),
}

#: The two statuses a step is **entered at** when ADR-0259 §2 takes its effect claim,
#: and therefore the only two a satisfaction may move it from (§9's fifth limb).
_SATISFIABLE_STATUSES = frozenset({StepStatus.PENDING, StepStatus.AWAITING_APPROVAL})

#: Which skip reasons are truthful from which status (ADR-0014 §4, ADR-0041).
#:
#: ``APPROVAL_DENIED`` is legal from both statuses a refusal can arrive in: a
#: human answering a confirmation from ``AWAITING_APPROVAL``, and a policy
#: refusing the step outright while it is still ``PENDING``, with nobody asked.
#: What keeps either record truthful is not that a question was put but that the
#: denial names the decision that refused it — so the ``approval_ref`` check in
#: :meth:`PlanExecution._to_skipped` is unconditional, and it, not this table,
#: is what stops a denial being manufactured for a decision nobody made.
_LEGAL_SKIP_REASONS: dict[StepStatus, frozenset[SkipReason]] = {
    StepStatus.PENDING: frozenset(
        {
            SkipReason.APPROVAL_DENIED,
            SkipReason.UNMET_DEPENDENCY,
            SkipReason.NO_CAPABLE_TOOL,
            SkipReason.SUPERSEDED,
        }
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({SkipReason.APPROVAL_DENIED, SkipReason.SUPERSEDED}),
}

#: How many times a step may be claimed before its retry budget is spent.
DEFAULT_MAX_ATTEMPTS = 3

#: What :meth:`PlanExecution.abandon_running` records on a step it found
#: ``RUNNING`` with nothing executing it (ADR-0039 §7). ``planning`` authors it
#: because recovery has no ``ToolResult`` and never had one — which is also why
#: the paired ``kind`` is ``None`` rather than a fabricated classification.
_ABANDONED = (
    "the step was found running with nothing executing it, so whether the tool acted is unknown"
)


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


def _revalidated_state(state: ExecutionState) -> ExecutionState:
    """Re-run ``ExecutionState``'s validators over a state built by ``model_copy``.

    Same reasoning as :func:`_revalidated`, and still load-bearing now that
    ``updated_at`` is :data:`~ai_assistant.core.types.UtcInstant`. It never
    carried that field's tz-awareness — the producer does, via
    :meth:`PlanExecution._now` (ADR-0026 §2) — but ``model_copy(update=...)``
    replaces ``steps`` wholesale without validating, so this is what re-runs
    ``ExecutionState``'s own step-id uniqueness check and every nested
    ``StepExecution`` validator over the rebuilt tuple.
    """
    return ExecutionState.model_validate(state.model_dump())


class PlanExecution:
    """Applies step transitions to an execution, enforcing the legal graph.

    Args:
        now: Clock used to stamp transitions; injectable so tests are
            deterministic, matching `memory` and `context`. Guarded by
            :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
            reading is a ``PlanningError`` rather than a silently attributed
            instant (ADR-0026).
        max_attempts: How many times a single step may be claimed before
            :class:`~ai_assistant.core.errors.RetriesExhaustedError`. The
            ceiling lives here, not in a model's judgement (VISION §7).
    """

    def __init__(
        self,
        *,
        now: Clock = _utcnow,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        """Create a tracker with an injectable clock and retry ceiling."""
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._clock = checked_clock(now, owner="PlanExecution")
        self._max_attempts = max_attempts

    def _now(self) -> datetime:
        """The guarded clock's reading, as `planning`'s own error (ADR-0026 §4).

        Every transition timestamp comes through here. ``core`` raises
        ``ValueError`` — the only option open to a layer that cannot know what
        its caller will do with the failure — and this seam translates it into
        the ``AssistantError`` subclass `planning` already owns, the same
        boundary translation the subsystem performs elsewhere.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

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

    def apply(
        self,
        state: ExecutionState,
        transition: StepTransition,
        *,
        satisfaction: Callable[[StepExecution], BorrowedAct] | None = None,
    ) -> ExecutionState:
        """Return ``state`` advanced by ``transition``.

        Args:
            state: The execution as currently stored.
            transition: The move to apply.
            satisfaction: The store's verification of a satisfaction (ADR-0259 §9),
                called with the **stored** source step once this method's own
                preconditions have passed, and returning what the store writes onto
                it. Passing it is how the store's five-limbed claim condition runs
                *after* the version compare and the step lookup, so a stale write is
                a ``StaleExecutionError`` and an unknown step a ``PlanningError``
                rather than whichever the satisfaction check happened to reach first.
                A transition carrying the trio without one is refused: this tracker
                cannot verify a borrowing, and it does not guess.

        Returns:
            A new state with the step updated and ``version`` incremented.

        Raises:
            StaleExecutionError: If ``transition.expected_version`` no longer
                matches — someone else has written since the caller read.
            IllegalTransitionError: If the move is not legal from the step's
                current status, or a ``→ SUCCEEDED`` move from an undispatched step
                carries no satisfaction.
            RetriesExhaustedError: If a retry would exceed the ceiling.
            PlanningError: If the execution or step ids do not match, if a
                satisfaction arrives with no ``satisfaction`` to verify it, or on any
                limb of the store's own claim condition.
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

        updated = _revalidated(self._advance(current, transition, satisfaction))
        return _revalidated_state(
            state.model_copy(
                update={
                    "steps": tuple(
                        updated if step.step_id == updated.step_id else step for step in state.steps
                    ),
                    "version": state.version + 1,
                    "updated_at": self._now(),
                }
            )
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

        It now carries a :class:`StepFailure` too (ADR-0039 §7): the state
        ADR-0014 §4 made durable *because* it must be resolved explicitly is no
        longer the one finished status with no durable diagnostic. ``kind`` is
        ``None`` — recovery has no ``ToolResult`` to classify from and never had
        one — which is correct and not a shortfall.
        """
        stopped = self._now()
        abandoned = StepFailure(kind=None, message=_ABANDONED)
        steps = tuple(
            _revalidated(
                step.model_copy(
                    update={
                        "status": StepStatus.INDETERMINATE,
                        "finished_at": stopped,
                        "failure": abandoned,
                    }
                )
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
        return _revalidated_state(
            state.model_copy(
                update={"steps": steps, "version": state.version + 1, "updated_at": self._now()}
            )
        )

    def _advance(
        self,
        step: StepExecution,
        transition: StepTransition,
        satisfaction: Callable[[StepExecution], BorrowedAct] | None = None,
    ) -> StepExecution:
        """Build the step's next value for a move already known to be legal."""
        if transition.to_status is StepStatus.RUNNING:
            return self._to_running(step, transition)
        if transition.to_status is StepStatus.AWAITING_APPROVAL:
            return self._to_awaiting_approval(step, transition)
        if transition.to_status is StepStatus.SKIPPED:
            return self._to_skipped(step, transition)
        return self._to_finished(step, transition, satisfaction)

    def _to_awaiting_approval(
        self, step: StepExecution, transition: StepTransition
    ) -> StepExecution:
        """Queue the step for approval, which requires knowing what would run.

        Approval is consent to a *specific* action, so asking before selection
        has chosen a tool would seek agreement to something unspecified
        (ADR-0014 §4).
        """
        bound_tool = transition.bound_tool or step.bound_tool
        if bound_tool is None:
            msg = (
                f"step {step.step_id} cannot await approval without a bound_tool: "
                "there would be nothing specific to approve"
            )
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={"status": StepStatus.AWAITING_APPROVAL, "bound_tool": bound_tool}
        )

    def _to_skipped(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Skip the step, checking the reason is one this status could produce.

        A denial must carry an ``approval_ref`` whichever status it comes from
        (ADR-0041 §2), so the check is deliberately not conditioned on the step
        having passed through ``AWAITING_APPROVAL``. What is enforced here is
        that the reference is *present* — that a denial always names something
        to look up in ``permissions/``. Whether it resolves to a stored decision
        is that subsystem's to guarantee and remains open as #107.
        """
        allowed = _LEGAL_SKIP_REASONS.get(step.status, frozenset())
        if transition.skip_reason not in allowed:
            msg = (
                f"step {step.step_id} cannot be skipped as {transition.skip_reason} "
                f"from {step.status}"
            )
            raise IllegalTransitionError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        if transition.skip_reason is SkipReason.APPROVAL_DENIED and approval_ref is None:
            msg = (
                f"step {step.step_id} cannot record a denial without an approval_ref "
                "pointing at the decision"
            )
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.SKIPPED,
                "skip_reason": transition.skip_reason,
                "approval_ref": approval_ref,
            }
        )

    def _to_running(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Claim the step: the move that must be committed *before* a tool runs."""
        if step.status is StepStatus.FAILED and step.attempts >= self._max_attempts:
            msg = (
                f"step {step.step_id} has used its {self._max_attempts} attempts; "
                "it cannot be retried again"
            )
            raise RetriesExhaustedError(msg)

        bound_tool = transition.bound_tool or step.bound_tool
        if bound_tool is None:
            msg = f"step {step.step_id} cannot run without a bound_tool"
            raise IllegalTransitionError(msg)

        if step.bound_tool is not None and bound_tool != step.bound_tool:
            # Authorisation is granted for a specific action. Letting the tool
            # change here would launder an approval for one tool into
            # permission to run another — approve "smtp", then run
            # "payments.delete_account" under the same reference. Re-selecting
            # a tool is a new decision and needs a flow that seeks one.
            msg = (
                f"step {step.step_id} is bound to {step.bound_tool} and cannot switch "
                f"to {bound_tool}: the approval covers the tool it was granted for"
            )
            raise IllegalTransitionError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        if approval_ref is None:
            msg = (
                f"step {step.step_id} cannot run without an approval_ref: "
                "every executed step must name the decision that authorised it"
            )
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
                "failure": None,
                "output": None,
            }
        )

    def _to_finished(
        self,
        step: StepExecution,
        transition: StepTransition,
        satisfaction: Callable[[StepExecution], BorrowedAct] | None = None,
    ) -> StepExecution:
        """Close the step out as SUCCEEDED, FAILED, or INDETERMINATE.

        **A ``→ SUCCEEDED`` move from an undispatched step is a satisfaction and
        nothing else** (ADR-0259 §2). ADR-0014 §4's two new rows are triggered by a
        step being satisfied by an effect its goal already completed, so a transition
        that takes one of them without naming the act it borrows from is refused here
        rather than left to :class:`StepExecution`'s own validator — which would
        refuse it too, for the marks a ``SUCCEEDED`` step needs, but with a message
        about ``approval_ref`` rather than about the move.

        **And a satisfaction is committed only through a store that can verify it.**
        Whether the borrowed act is this goal's, stands ``SUCCEEDED``, is the one the
        effect row names, was taken under the key the transition names, and is being
        applied to a step that has not already run are ADR-0259 §9's five limbs, and
        every one of them is a question about **stored rows** this tracker does not
        hold. So the store's verification is called here — after the version compare,
        the step lookup and the legality check, which is the ordering
        ``PlanStore.commit_transition``'s exception contract needs — and a
        satisfaction arriving without one is refused rather than guessed at.

        **What it returns is what lands**: the ``output`` is the holder's own and the
        ``finished_at`` is the **store's** clock's, not this tracker's, which §9 names
        in terms and which matters because a store may be given an independently
        clocked tracker. ``attempts`` is untouched on every path here, so no row of
        ADR-0259 §7's three increments it.
        """
        satisfied = transition.satisfied_by_execution is not None
        undispatched = step.status in _SATISFIABLE_STATUSES
        if transition.to_status is StepStatus.SUCCEEDED and undispatched and not satisfied:
            msg = (
                f"step {step.step_id} cannot go from {step.status} to SUCCEEDED without "
                "naming the completed effect that satisfies it"
            )
            raise IllegalTransitionError(msg)

        borrowed: BorrowedAct | None = None
        if satisfied:
            if satisfaction is None:
                msg = (
                    f"step {step.step_id} names a completed effect, and a satisfaction is "
                    "committed only through a store that can verify it against its rows"
                )
                raise PlanningError(msg)
            borrowed = satisfaction(step)

        return step.model_copy(
            update={
                "status": transition.to_status,
                "output": transition.output if borrowed is None else borrowed.output,
                "failure": transition.failure,
                "finished_at": self._now() if borrowed is None else borrowed.finished_at,
                "satisfied_by_execution": transition.satisfied_by_execution,
                "satisfied_by_step": transition.satisfied_by_step,
            }
        )
