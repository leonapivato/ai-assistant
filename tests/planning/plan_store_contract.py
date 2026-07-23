"""Shared conformance suite for the PlanStore Protocol (ADR-0014).

Every ``PlanStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlanStoreContract` and
overrides the ``store`` fixture.

This suite matters more than most: `InMemoryPlanStore` and `FakePlanStore`
re-implement the ADR-0014 §4 transition graph independently — the fake cannot
import the subsystem it stands in for — so this is what stops the two drifting.
It asserts only behaviour the *contract* guarantees, never how a given store
keys its ids.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    ActionPlan,
    Goal,
    GoalStatus,
    MemorySource,
    PlanStep,
    Provenance,
    SkipReason,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolFailureKind,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ExecutionState

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _plan(plan_id: str = "p1", goal_id: str = "g1", *, steps: int = 1) -> ActionPlan:
    return ActionPlan(
        id=plan_id,
        goal_id=goal_id,
        steps=tuple(
            PlanStep(id=f"s{index}", intent=f"step {index}", capability="send_email")
            for index in range(1, steps + 1)
        ),
        created_at=_WHEN,
    )


def _claim(state: ExecutionState, step_id: str = "s1") -> StepTransition:
    """The transition that claims a step — bound tool plus authorisation."""
    return StepTransition(
        execution_id=state.id,
        step_id=step_id,
        to_status=StepStatus.RUNNING,
        expected_version=state.version,
        bound_tool="smtp",
        approval_ref="perm-1",
    )


class PlanStoreContract:
    """Behaviour every ``PlanStore`` implementation must exhibit."""

    @pytest.fixture
    def store(self) -> PlanStore:
        """Return an empty store under test."""
        raise NotImplementedError

    async def _started(self, store: PlanStore, *, steps: int = 1) -> ExecutionState:
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=steps))
        return await store.start_execution("p1")

    # --- goals and plans ------------------------------------------------

    async def test_saves_and_reads_back_a_goal(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_missing_goal_reads_as_none(self, store: PlanStore) -> None:
        assert await store.get_goal("nope") is None

    async def test_saving_a_goal_twice_upserts(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.save_goal(_goal())
        export = await store.export()
        assert len(export.goals) == 1

    async def test_a_plan_needs_its_goal_to_exist(self, store: PlanStore) -> None:
        """Refusing the orphan here is what lets export promise integrity."""
        with pytest.raises(PlanningError):
            await store.save_plan(_plan(goal_id="ghost"))

    async def test_execution_needs_its_plan_to_exist(self, store: PlanStore) -> None:
        with pytest.raises(PlanningError):
            await store.start_execution("ghost")

    async def test_a_plan_id_cannot_be_reused_for_a_different_plan(self, store: PlanStore) -> None:
        """Replacing a plan would rewrite the record of what was decided.

        Worse, an execution already under way refers to its plan by id, so the
        swap would pair real step history with steps that were never planned.
        Re-planning takes a new id (ADR-0014 §2).
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=1))
        await store.start_execution("p1")

        with pytest.raises(PlanningError):
            await store.save_plan(_plan(steps=2))

        stored = await store.get_plan("p1")
        assert stored is not None
        assert [step.id for step in stored.steps] == ["s1"]

    async def test_a_goals_objective_cannot_be_rewritten(self, store: PlanStore) -> None:
        """Otherwise plans already recorded would come to describe a new objective."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        rewritten = _goal().model_copy(update={"statement": "delete all mail"})
        with pytest.raises(PlanningError):
            await store.save_goal(rewritten)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_a_goals_status_may_still_change(self, store: PlanStore) -> None:
        """Identity is fixed; a goal's progress is exactly what should move."""
        await store.save_goal(_goal())
        await store.save_goal(_goal().model_copy(update={"status": GoalStatus.ACHIEVED}))

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.status is GoalStatus.ACHIEVED

    async def test_saving_an_identical_plan_again_is_idempotent(self, store: PlanStore) -> None:
        """A retry must not be punished — only a *differing* plan is a conflict."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan())

        export = await store.export()
        assert len(export.plans) == 1

    # --- starting an execution ------------------------------------------

    async def test_execution_starts_derived_from_the_plan(self, store: PlanStore) -> None:
        state = await self._started(store, steps=2)
        assert state.plan_id == "p1"
        assert [step.step_id for step in state.steps] == ["s1", "s2"]
        assert all(step.status is StepStatus.PENDING for step in state.steps)
        assert state.version == 0

    # --- the transition graph -------------------------------------------

    async def test_claiming_a_step_advances_it(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        step = updated.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 1
        assert step.started_at is not None

    async def test_a_write_bumps_the_version(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        assert updated.version == state.version + 1

    async def test_illegal_transition_is_rejected(self, store: PlanStore) -> None:
        """PENDING to SUCCEEDED skips the claim, so it must not be persistable."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=state.version,
                )
            )

    async def test_running_without_authorisation_is_rejected(self, store: PlanStore) -> None:
        """ADR-0004 §7: nothing executes without a decision to point at."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="smtp",
                )
            )

    async def test_approval_cannot_be_sought_without_a_tool_to_approve(
        self, store: PlanStore
    ) -> None:
        """Consent is to a specific action, not to an unspecified one."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_never_queued_step_can_be_denied_in_one_transition(
        self, store: PlanStore
    ) -> None:
        """A policy refusing outright is a denial, though nobody was asked.

        ADR-0041 §1: the record is truthful because it names the decision that
        refused it, not because a confirmation was put to anyone.

        The version count is asserted, not incidental. A store that satisfied
        this request by durably writing `AWAITING_APPROVAL` and then `SKIPPED`
        would return an indistinguishable final state while reopening the very
        window ADR-0041 closes — a failure between the two writes strands the
        step (#257). One commit is the obligation; the disposition is not.
        """
        state = await self._started(store)
        before = state.version
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-1",
            )
        )

        assert state.version == before + 1

        # Read back rather than trust the return value: a denial that is only
        # in the returned object is exactly the stranding this edge exists to
        # prevent, since a restart would resurrect the step as PENDING.
        stored = await store.get_execution(state.id)
        assert stored is not None
        assert stored.version == before + 1
        step = stored.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-1"

    async def test_a_queued_step_is_still_denied_by_a_human(self, store: PlanStore) -> None:
        """ADR-0041 widens the denial rule; it does not move it (§3).

        This is the genuine human-denied path — a confirmation was shown and
        answered no — and it stays legal. Without it the suite would admit a
        store that implements only the direct edge, leaving a real user denial
        with nowhere to go and the step awaiting approval forever.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-denied",
            )
        )

        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-denied"

    async def test_a_pending_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        """The `approval_ref` is the whole guard on the direct edge (ADR-0041 §2).

        Without it, `APPROVAL_DENIED` would be assertable from the status every
        step starts in, with nothing behind it — the fabricated record the
        narrower rule was protecting against.
        """
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_a_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_an_approved_step_cannot_run_a_different_tool(self, store: PlanStore) -> None:
        """Approving "smtp" must not become permission to run something else.

        This is the authorisation-laundering path: without the check, a caller
        approves a benign tool and then claims the step with a destructive one,
        carrying the benign approval along as its justification.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                    approval_ref="perm-for-smtp",
                )
            )

    async def test_a_retry_cannot_swap_the_tool(self, store: PlanStore) -> None:
        """The same laundering, taken through the retry path instead."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                )
            )

    async def test_unknown_step_is_rejected(self, store: PlanStore) -> None:
        state = await self._started(store)
        with pytest.raises(PlanningError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="ghost",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_full_run_reaches_succeeded_with_its_output(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SUCCEEDED,
                expected_version=state.version,
                output={"ref": "ABC"},
            )
        )
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SUCCEEDED
        assert step.output == {"ref": "ABC"}
        assert step.finished_at is not None
        assert not state.is_active

    # --- compare-and-swap -----------------------------------------------

    async def test_a_stale_write_is_refused(self, store: PlanStore) -> None:
        """The race that would otherwise run a non-idempotent tool twice."""
        state = await self._started(store)
        first = _claim(state)
        second = _claim(state)  # computed against the same version

        await store.commit_transition(first)
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(second)

    async def test_the_loser_of_a_race_did_not_change_anything(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(state))

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.attempts == 1

    # --- retries ---------------------------------------------------------

    async def test_a_failed_step_can_be_retried(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        state = await store.commit_transition(_claim(state))
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 2
        assert step.failure is None, "a retry re-opens the step, clearing the last failure"

    async def test_retries_are_bounded(self, store: PlanStore) -> None:
        """The ceiling is deterministic code's to enforce (VISION §7)."""
        state = await self._started(store)
        for _ in range(3):
            state = await store.commit_transition(_claim(state))
            state = await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.FAILED,
                    expected_version=state.version,
                    failure=StepFailure(message="boom"),
                )
            )
        with pytest.raises(RetriesExhaustedError):
            await store.commit_transition(_claim(state))

    # --- failure records survive the store (ADR-0039) ---------------------

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_failure_status_transition_requires_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Required on both FAILED and INDETERMINATE (ADR-0039 §2), not just FAILED.

        A suite that pinned only ``FAILED`` would certify a store fed by a
        command shape that left ``INDETERMINATE`` — the #208 half — with no
        durable account of itself.
        """
        with pytest.raises(ValidationError, match="requires a failure"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
            )

    @pytest.mark.parametrize(
        "to_status",
        [StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SUCCEEDED],
    )
    async def test_a_non_failure_transition_forbids_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        with pytest.raises(ValidationError, match="only valid for a transition to FAILED"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
                failure=StepFailure(message="boom"),
            )

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_tool_failure_round_trips_verbatim(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Kind and message are unchanged after ``commit_transition`` (ADR-0039 §6).

        On ``FAILED`` *and* ``INDETERMINATE`` — the latter is the regression test
        for #208 and for ADR-0032 §5's by-value rule surviving one frame past the
        seam. Read back from the store, not the return value, so a store that
        only echoed the command would not pass.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        failure = StepFailure(
            kind=ToolFailureKind.RATE_LIMITED, message="the upstream throttled us"
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=to_status,
                expected_version=state.version,
                failure=failure,
            )
        )

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.status is to_status
        assert step.failure == failure
        assert step.failure is not None
        assert step.failure.kind is ToolFailureKind.RATE_LIMITED
        assert step.failure.message == "the upstream throttled us"

    async def test_an_indeterminate_step_with_a_retryable_kind_is_not_run_again(
        self, store: PlanStore
    ) -> None:
        """A durable kind on an INDETERMINATE step is diagnostic, never permission.

        The graph has no ``INDETERMINATE → RUNNING`` edge (ADR-0014 §4), so a
        ``TIMED_OUT`` whose ``retryable`` is ``True`` still cannot be re-claimed
        (ADR-0039 §4). This is the case a reader of the new field is most likely
        to get wrong.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(kind=ToolFailureKind.TIMED_OUT, message="deadline passed"),
            )
        )
        assert ToolFailureKind.TIMED_OUT.retryable  # the field says "retryable"...
        with pytest.raises(IllegalTransitionError):  # ...and the graph still refuses it
            await store.commit_transition(_claim(state))

    # --- resumption -------------------------------------------------------

    async def test_active_executions_finds_outstanding_work(self, store: PlanStore) -> None:
        state = await self._started(store)
        assert [found.id for found in await store.active_executions()] == [state.id]

    async def test_a_finished_execution_is_not_active(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.SUPERSEDED,
            )
        )
        assert await store.active_executions() == []

    # --- stored state is the store's own ----------------------------------

    async def test_a_retained_goal_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """Otherwise a caller could rewrite a goal after the fact, unrecorded."""
        goal = _goal()
        await store.save_goal(goal)
        goal.statement = "tampered"

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_goal_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        got = await store.get_goal("g1")
        assert got is not None
        got.statement = "tampered"

        fresh = await store.get_goal("g1")
        assert fresh is not None
        assert fresh.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_plan_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """``frozen=True`` stops attribute assignment, not ``__dict__`` writes.

        Sharing the stored instance would therefore let a caller rewrite the
        audit record in place — including a nested step's ``capability``, which
        is what the executor later binds a tool to.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        got = await store.get_plan("p1")
        assert got is not None
        got.__dict__["goal_id"] = "tampered"
        got.steps[0].__dict__["capability"] = "payments.delete_account"

        fresh = await store.get_plan("p1")
        assert fresh is not None
        assert fresh.goal_id == "g1"
        assert fresh.steps[0].capability == "send_email"

    async def test_a_retained_plan_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        plan = _plan()
        await store.save_plan(plan)
        plan.__dict__["goal_id"] = "tampered"

        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.goal_id == "g1"

    async def test_an_exported_plan_cannot_edit_stored_state(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        export = await store.export()
        export.plans[0].__dict__["goal_id"] = "tampered"

        again = await store.export()
        assert again.plans[0].goal_id == "g1"

    async def test_mutating_a_returned_execution_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """Execution state is the audit record; only commit_transition may move it."""
        state = await self._started(store)
        state.steps[0].status = StepStatus.SUCCEEDED
        state.version = 99

        fresh = await store.get_execution(state.id)
        assert fresh is not None
        assert fresh.steps[0].status is StepStatus.PENDING
        assert fresh.version == 0

    async def test_active_executions_come_back_oldest_first(self, store: PlanStore) -> None:
        """Sorting ids would interleave plans and put exec-10 before exec-2."""
        await store.save_goal(_goal())
        expected = []
        for index in range(1, 13):
            await store.save_plan(_plan(plan_id=f"p{index}"))
            expected.append((await store.start_execution(f"p{index}")).id)

        assert [state.id for state in await store.active_executions()] == expected

    # --- data rights (ADR-0004) -------------------------------------------

    async def test_export_carries_the_stored_state(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert [goal.id for goal in export.goals] == ["g1"]
        assert [plan.id for plan in export.plans] == ["p1"]
        assert len(export.executions) == 1

    async def test_export_round_trips_through_json(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert type(export).model_validate_json(export.model_dump_json()) == export

    async def test_deleting_a_goal_cascades(self, store: PlanStore) -> None:
        state = await self._started(store)
        result = await store.delete_goal("g1")

        assert result.deleted
        assert result.plans_removed == 1
        assert result.executions_removed == 1
        assert await store.get_goal("g1") is None
        assert await store.get_plan("p1") is None
        assert await store.get_execution(state.id) is None

    async def test_deletion_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))

        result = await store.delete_goal("g1")
        assert not result.deleted
        assert result.blocked_by == (state.id,)
        assert await store.get_goal("g1") is not None

    async def test_deletion_succeeds_once_the_live_step_resolves(self, store: PlanStore) -> None:
        """Cancel-then-delete: the round-trip the refusal above asks for."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deletion_reports_erased_indeterminate_steps(self, store: PlanStore) -> None:
        """The user must learn an action may have completed before its record went."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.indeterminate_steps == ("s1",)

    async def test_a_permanently_failed_step_does_not_block_deletion(
        self, store: PlanStore
    ) -> None:
        """Otherwise one failure would void the erasure right for good."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        assert state.is_active
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deleting_an_unknown_goal_reports_refusal(self, store: PlanStore) -> None:
        result = await store.delete_goal("ghost")
        assert not result.deleted

    async def test_clear_empties_the_store(self, store: PlanStore) -> None:
        await self._started(store)
        assert await store.clear() > 0
        assert await store.get_goal("g1") is None

    async def test_clear_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(ActiveExecutionError):
            await store.clear()
