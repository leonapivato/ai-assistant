"""Writing and settling the path-(i) row through a whole turn (ADR-0254 §1, §15).

``test_authorizing.py`` pins *which* `CONFIRM` proposes a row. This pins what the
stage then does with the answer: the row is written before the question is put,
and the answer settles it — ADR-0244's shape, which ADR-0254 §1 adopts rather than
re-derives.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing
here imports ``permissions/`` or ``planning/`` (CLAUDE.md golden rule 1).

**No row here carries a coverage member** (#2373, ruled into ADR-0266); see
``test_authorizing.py``'s own docstring and the pull request.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from authorizing_builders import AT, GOAL, RETENTION, a_goal, a_tool

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    ActionPlan,
    AttemptTransition,
    AuthorizationDisposition,
    DataTier,
    Disposition,
    GoalAttempt,
    PlanStep,
    StepStatus,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import Authorization, ExecutionState, Goal, ToolDefinition

#: The one step every test here disposes of. It carries **no argument**, which is
#: the request ADR-0254 §20's arm 54 is stated over and the only shape this lane
#: can found an authority on (#2373).
STEP = "step-1"
ATTEMPT = "a-1"
CAPABILITY = "send_email"
CONNECTION = "conn-1"
IDENTITY = "work@example.com"

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def a_confirmable_tool() -> ToolDefinition:
    """An egress declaration ``FakeActionPolicy`` confirms: it discloses off-device."""
    return a_tool(discloses=(DataTier.PERSONAL,))


class Harness:
    """A wired ``StepRunner`` with a binder and a goal-authorization store."""

    def __init__(
        self,
        *,
        tool: ToolDefinition | None = None,
        retention: timedelta | None = RETENTION,
        authorizations: FakeGoalAuthorizationStore | None = None,
        wired: bool = True,
        now: datetime = AT,
    ) -> None:
        """Wire the stage over canonical fakes.

        ``wired=False`` builds the stage with **no** store, which is ADR-0254
        §15's fail-closed default: it proposes nothing and settles nothing.
        """
        self.tool = a_confirmable_tool() if tool is None else tool
        self.plans = FakePlanStore(now=lambda: now)
        self.policy = FakeActionPolicy()
        self.trail = FakeAuditTrail()
        self.invoker = FakeToolInvoker([(self.tool, _succeeds)], ledger=self.trail, gate=self.trail)
        self.binder = FakeEgressBinder()
        self.binder.register_egress(self.tool, reference=CONNECTION, identity=IDENTITY)
        self.authorizations = (
            FakeGoalAuthorizationStore() if authorizations is None else authorizations
        )
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: now
            ),
            binder=self.binder,
            authorizations=self.authorizations if wired else None,
            episode_retention=retention,
            now=lambda: now,
            id_factory=lambda: next(self.ids),
        )

    async def an_execution(self, goal: Goal) -> ExecutionState:
        """Store ``goal``, a one-step argument-free plan, and open an execution."""
        await self.plans.save_goal(goal)
        step = PlanStep(id=STEP, intent="send the note", capability=CAPABILITY)
        plan = ActionPlan(
            id="p-1", goal_id=goal.id, steps=(step,), created_at=AT, targets_revision=1
        )
        await self.plans.save_plan(plan)
        state = await self.plans.start_execution(plan.id)
        await self.plans.open_attempt(_an_attempt(goal.id))
        await self.plans.commit_attempt(_appends_execution(state.id))
        return state

    async def rows(self) -> tuple[Authorization, ...]:
        """Every row the store holds, whatever its disposition."""
        return await self.authorizations.export()


def _an_attempt(goal_id: str) -> GoalAttempt:
    """The attempt every execution here is opened under (ADR-0255 §3)."""
    return GoalAttempt(id=ATTEMPT, goal_id=goal_id, opened_at=AT)


def _appends_execution(execution_id: str) -> AttemptTransition:
    """ADR-0249 §12's own ordering: the execution is appended before it is driven."""
    return AttemptTransition(attempt_id=ATTEMPT, expected_version=0, add_execution_id=execution_id)


async def _parked(harness: Harness, goal: Goal) -> ExecutionState:
    """Drive the step to its `CONFIRM` park and return the execution."""
    state = await harness.an_execution(goal)
    result = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )
    assert result.disposition is Disposition.AWAITING_CONFIRMATION
    return result.state


# --- the proposal (ADR-0254 §1's path (i)) -------------------------------


async def test_a_confirm_proposes_the_row_before_the_question_is_put() -> None:
    """ADR-0254 §1: written `PROPOSED`, against the recorded `CONFIRM`'s own id."""
    harness = Harness()
    goal = a_goal(deadline=AT + timedelta(hours=12))

    await _parked(harness, goal)

    (row,) = await harness.rows()
    (decision,) = await harness.trail.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.confirmation == decision.id
    assert row.proposed_at == decision.decided_at
    assert row.expires_at == AT + timedelta(hours=12)
    assert row.goal == GOAL
    assert row.coverage == ()
    assert row.settled_at is None


async def test_the_row_takes_the_retention_window_where_the_goal_carries_no_deadline() -> None:
    """ADR-0256 §9's ordinary case, driven end to end."""
    harness = Harness()

    await _parked(harness, a_goal(deadline=None))

    (row,) = await harness.rows()
    assert row.expires_at == AT + RETENTION


async def test_a_deployment_keeping_turns_forever_proposes_nothing() -> None:
    """ADR-0256 §9: `episode_retention = None`, no deadline → no row, route (a)."""
    harness = Harness(retention=None)

    await _parked(harness, a_goal(deadline=None))

    assert await harness.rows() == ()


async def test_a_stage_holding_no_store_proposes_nothing() -> None:
    """ADR-0254 §15's fail-closed default, and the shape §6 gives a sourceless policy."""
    harness = Harness(wired=False)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.authorizations.export() == ()


async def test_an_allowed_call_proposes_nothing() -> None:
    """Only a question proposes a row: a ruling that asks nothing establishes nothing."""
    harness = Harness(tool=a_tool())
    state = await harness.an_execution(a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )

    assert result.disposition is Disposition.EXECUTED
    assert await harness.rows() == ()


async def test_a_store_that_refuses_the_write_still_puts_the_question() -> None:
    """ADR-0254 §1's own outcome for proposing none, reached by a fault instead.

    "the `CONFIRM` is resolved and the one call is authorised by ADR-0148 §3's
    route (a)". The cost of a store that could not be written is an authority the
    user has to grant again, never one granted without them — so the dispatch is
    not failed on the strength of a second store.
    """
    store = FakeGoalAuthorizationStore()
    store.fail_writes()
    harness = Harness(authorizations=store)

    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.rows() == ()
    assert len(await harness.trail.export()) == 1
    assert parked.step(STEP) is not None
    assert parked.step(STEP).status is StepStatus.AWAITING_APPROVAL  # type: ignore[union-attr]


# --- the settlement (ADR-0254 §1's five edges) ---------------------------


async def test_an_approval_settles_the_row_established() -> None:
    """ADR-0254 §1: "An approval settles `ESTABLISHED`"."""
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.ESTABLISHED
    assert row.settled_at == AT
    # The row still carries the confirmation it was proposed against, which is
    # ADR-0254 §1's write-path rule and not a validator (§20 arm 38).
    assert row.confirmation is not None
    assert await harness.authorizations.standing(GOAL) == (row,)


async def test_a_refusal_settles_the_row_declined_and_establishes_nothing() -> None:
    """ADR-0254 §1: "a refusal settles `DECLINED`", and `standing` returns it not."""
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=False, timeout=PATIENT
    )

    assert result.disposition is Disposition.DENIED
    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.DECLINED
    assert await harness.authorizations.standing(GOAL) == ()


async def test_the_settlement_instant_is_the_resolving_decisions_own() -> None:
    """ADR-0254 §7 refuses a row whose `settled_at` is after the ruling's instant.

    Equality at the lower end is live (§1), so taking the resolving decision's own
    reading is the one value that cannot put the row and the trail out of step.
    """
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await harness.rows()
    resolving = next(one for one in await harness.trail.export() if one.resolves is not None)
    assert row.settled_at == resolving.decided_at


async def test_an_answer_at_or_after_the_expiry_establishes_nothing() -> None:
    """ADR-0254 §12: the row settles `EXPIRED` and no standing authority comes to be.

    The `CONFIRM` is answered under a stage whose clock has passed the instant the
    row carries; the store settles the lapsed proposal first, so the approval finds
    a disposition the `ESTABLISHED` edge does not leave.
    """
    store = FakeGoalAuthorizationStore()
    parking = Harness(authorizations=store, retention=timedelta(minutes=5))
    parked = await _parked(parking, a_goal(deadline=None))
    (proposal,) = await parking.rows()
    assert proposal.expires_at == AT + timedelta(minutes=5)

    # A second stage over the same stores, reading a clock past that instant --
    # the restart ADR-0254 §11 promises recovers the row, with the instant read off
    # the row rather than recomputed.
    later = StepRunner(
        plans=parking.plans,
        registry=parking.invoker,
        policy=parking.policy,
        trail=parking.trail,
        executor=StepExecutor(
            plans=parking.plans,
            registry=parking.invoker,
            invoker=parking.invoker,
            now=lambda: AT + timedelta(hours=1),
        ),
        binder=parking.binder,
        authorizations=store,
        episode_retention=RETENTION,
        now=lambda: AT + timedelta(hours=1),
        id_factory=lambda: "d-late",
    )

    await later.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.EXPIRED
    assert await store.standing(GOAL) == ()


async def test_a_settlement_the_store_refuses_leaves_the_answer_standing() -> None:
    """A fault at the settlement loses the authority and retracts nothing."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    store.fail_writes()

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    store.fail_writes(None)
    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED


async def test_a_stage_holding_no_store_settles_nothing() -> None:
    """The fail-closed default again, on the answering side."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    unwired = StepRunner(
        plans=harness.plans,
        registry=harness.invoker,
        policy=harness.policy,
        trail=harness.trail,
        executor=StepExecutor(
            plans=harness.plans, registry=harness.invoker, invoker=harness.invoker, now=lambda: AT
        ),
        binder=harness.binder,
        episode_retention=RETENTION,
        now=lambda: AT,
        id_factory=lambda: "d-unwired",
    )

    await unwired.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED


# --- the resolving decision is not itself a question ---------------------


async def test_the_answer_proposes_no_second_row() -> None:
    """A `CONFIRM` recorded with `resolves` set is a resolution, not a question.

    A second row against a decision that was itself an answer would be a proposal
    nobody was ever shown.
    """
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=False, timeout=PATIENT)

    assert len(await harness.rows()) == 1


@pytest.mark.parametrize("approved", [True, False], ids=["approved", "declined"])
async def test_the_store_is_read_and_written_and_never_raises_into_the_turn(
    *, approved: bool
) -> None:
    """A read fault is as survivable as a write fault, on both answers."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    store.fail_reads(AuthorizationError("the store could not be read"))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=approved, timeout=PATIENT
    )

    assert result.disposition is (Disposition.EXECUTED if approved else Disposition.DENIED)
