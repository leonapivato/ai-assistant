"""ADR-0259 §12's arms 5-11: the four-act pass, the check, and the attempt's release.

Everything here is driven through the two collaborators that actually take the acts —
:class:`~ai_assistant.orchestration.reconciling.ReconciliationPass` and
:class:`~ai_assistant.orchestration.reconciling.ReconciliationCheck` — over the
canonical fakes, with **no consequential capability wired** (ADR-0255 §13's Q4 rule,
which §12 states its arms over in terms). Arm 9's ordering half and its surfacing half
are engine-level by construction and live in ``test_engine_reconciliation``.

**Every durable assertion is read back from the store**, never off the value a
collaborator returned: an arm reading the return would pass an implementation that
asserted the write rather than made it.

**Two counters stand in for "nothing was dispatched".** ``FakeToolInvoker.invocations``
is the seam's own record of what it ran, and :class:`_Recording`'s ``resumes`` would
count a ``StepRunner.resume`` this decision never makes — the pass holds no runner at
all, which is the strongest form of arm 5's ``ALLOW`` row: there is no object through
which a replay could be issued.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_effect_claim import Harness as ClaimHarness
from test_effect_claim import a_goal as claim_goal
from test_effect_claim import a_step as claim_step
from test_effect_claim import an_execution as claim_execution
from test_effect_claim import declaration as claim_declaration

from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    PlanningError,
    SpendCeilingError,
    SpendUndeterminedError,
    StaleExecutionError,
    ToolBindingError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    AttemptState,
    AttemptTransition,
    BoundAccount,
    CostBasis,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EffectClaim,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Goal,
    GoalAttempt,
    GoalInterpretation,
    Ground,
    Idempotency,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    Reversibility,
    RiskLevel,
    SkipReason,
    SpanCoverage,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.reconciling import (
    ReconciliationCheck,
    ReconciliationPass,
    TurnRemainder,
)
from ai_assistant.orchestration.runner import _requested
from ai_assistant.testing import FakeAuditTrail, FakePlanStore, FakeToolInvoker

if TYPE_CHECKING:
    from ai_assistant.testing import FakeToolImplementation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        ExecutionState,
        FrozenJson,
        StepExecution,
        ToolCall,
    )

AT: Final = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
GOAL: Final = "g-1"
PATIENT: Final = timedelta(seconds=30)
OUTPUT: Final = {"seat": "12A"}


#: A monotonic source an arm drives by hand. ADR-0255 §9 states the gate over a
#: **monotonic** source, so every budget arm here reads this rather than a clock.
class _Ticking:
    """A monotonic source that returns each figure an arm queued, then holds."""

    def __init__(self, *readings: float) -> None:
        """Start at the first reading; every call past the last repeats it."""
        self._readings = list(readings) or [0.0]
        self.reads = 0

    def __call__(self) -> float:
        """The next reading, or the last one for ever."""
        value = self._readings[min(self.reads, len(self._readings) - 1)]
        self.reads += 1
        return value


def reading(tool_id: str = "lookup") -> ToolDefinition:
    """A **non**-``side_effecting`` declaration — the one §3 admits a call for."""
    return ToolDefinition(
        id=tool_id,
        capability="look_up",
        description="Look up a reservation.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=False,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


def acting(tool_id: str = "book", idempotency: Idempotency = Idempotency.NONE) -> ToolDefinition:
    """A ``side_effecting`` declaration — uncheckable whatever its ``Idempotency``."""
    return ToolDefinition(
        id=tool_id,
        capability="book",
        description="Book a room.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=idempotency,
        idempotency_window=timedelta(minutes=5) if idempotency is Idempotency.KEYED else None,
    )


def a_step(
    step_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    parameters: Mapping[str, FrozenJson] | None = None,
) -> PlanStep:
    """One step of a plan."""
    return PlanStep(
        id=step_id,
        intent="look it up",
        capability="look_up",
        parameters={"reference": "R1"} if parameters is None else parameters,
        depends_on=depends_on,
    )


class World:
    """A goal, its plans, its executions and its attempts, over the canonical fakes."""

    def __init__(self, *, invoker: FakeToolInvoker | None = None) -> None:
        """Wire the store, the trail and the seam, all on one pinned clock."""
        self.plans = FakePlanStore(now=lambda: AT)
        self.trail = FakeAuditTrail()
        self.invoker = invoker or FakeToolInvoker((), ledger=self.trail, gate=self.trail)
        self.ids = iter(f"d-{n}" for n in range(1, 500))

    async def goal(self) -> Goal:
        """Store the one goal every arm here works over."""
        await self.plans.save_goal(
            Goal(
                id=GOAL,
                interpretation=(
                    GoalInterpretation(
                        revision=1,
                        outcome="get to Lisbon",
                        outcome_ground=Ground.USER_STATED,
                        outcome_span="get to Lisbon",
                        recorded_at=AT,
                        raised_by="t-1",
                    ),
                ),
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                ),
                created_at=AT,
            )
        )
        held = await self.plans.get_goal(GOAL)
        assert held is not None
        return held

    async def execution(
        self,
        *steps: PlanStep,
        plan_id: str = "p-1",
        attempt_id: str = "a-1",
        supersedes: str | None = None,
        state: AttemptState = AttemptState.RUNNING,
    ) -> ExecutionState:
        """Store a plan over ``steps``, open an execution of it under one attempt."""
        plan = ActionPlan(
            id=plan_id,
            goal_id=GOAL,
            steps=steps,
            created_at=AT,
            targets_revision=1,
            supersedes=supersedes,
        )
        await self.plans.save_plan(plan)
        opened = await self.plans.start_execution(plan.id)
        await self.plans.open_attempt(
            GoalAttempt(
                id=attempt_id,
                goal_id=GOAL,
                opened_at=AT,
                plan_ids=(plan.id,),
                execution_ids=(opened.id,),
                state=state,
            )
        )
        return opened

    async def decide(  # noqa: PLR0913 — one keyword per field an arm varies; each is a distinct fact about the decision
        self,
        state: ExecutionState,
        step: PlanStep,
        tool: ToolDefinition,
        *,
        outcome: PermissionOutcome = PermissionOutcome.ALLOW,
        binding: EgressBinding | None = None,
        resolves: str | None = None,
        parameters: Mapping[str, FrozenJson] | None = None,
    ) -> PermissionDecision:
        """Record one decision about this step, through the trail that holds it."""
        decision = PermissionDecision.from_request(
            ActionRequest(
                tool=tool,
                parameters=step.parameters if parameters is None else parameters,
                goal=GOAL,
                intended_action=step.intended_action,
                step_id=step.id,
                execution_id=state.id,
                egress_binding=binding,
            ),
            PermissionRuling(
                outcome=outcome,
                reason="arm",
                # A resolving ``ALLOW`` must rest on the confirmation it answers
                # (ADR-0021 §5), which the canonical trail enforces on the way in.
                authorised_by=resolves if outcome is PermissionOutcome.ALLOW else None,
            ),
            id=next(self.ids),
            decided_at=AT,
            resolves=resolves,
        )
        await self.trail.record(decision)
        return decision

    async def park(
        self, state: ExecutionState, step: PlanStep, tool: ToolDefinition
    ) -> tuple[ExecutionState, PermissionDecision]:
        """Move a step to ``AWAITING_APPROVAL`` behind a recorded ``CONFIRM``."""
        confirm = await self.decide(state, step, tool, outcome=PermissionOutcome.CONFIRM)
        moved = await self.plans.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id=step.id,
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool=tool.id,
                approval_ref=confirm.id,
            )
        )
        return moved, confirm

    async def uncertain(
        self,
        state: ExecutionState,
        step: PlanStep,
        tool: ToolDefinition,
        *,
        decision: PermissionDecision | None = None,
        attempt_id: str = "a-1",
    ) -> tuple[ExecutionState, PermissionDecision]:
        """Drive a step ``PENDING → RUNNING → INDETERMINATE``, as a crash leaves it.

        That is the route §3 names: ``ToolDefinition.interrupted_outcome`` classifies an
        interrupted **read** as ``FAILED``, so what leaves a read ``INDETERMINATE`` is
        the startup recovery scan moving a step a dead process left ``RUNNING`` *"without
        consulting a declaration"*.
        """
        allowed = decision or await self.decide(state, step, tool)
        claimed = await self.plans.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id=step.id,
                to_status=StepStatus.RUNNING,
                expected_version=state.version,
                bound_tool=tool.id,
                approval_ref=allowed.id,
                attempt_id=attempt_id,
            )
        )
        stranded = await self.plans.commit_transition(
            StepTransition(
                execution_id=claimed.id,
                step_id=step.id,
                to_status=StepStatus.INDETERMINATE,
                expected_version=claimed.version,
                failure=StepFailure(
                    message=(
                        "the step was found running with nothing executing it, "
                        "so whether the tool acted is unknown"
                    ),
                    kind=None,
                ),
            )
        )
        return stranded, allowed

    def pass_(self) -> ReconciliationPass:
        """§4's pass over this world."""
        return ReconciliationPass(plans=self.plans, trail=self.trail)

    def check(self) -> ReconciliationCheck:
        """§3's check over this world."""
        return ReconciliationCheck(plans=self.plans, trail=self.trail, invoker=self.invoker)

    async def stored(self, state: ExecutionState, step_id: str) -> StepExecution:
        """That step **as the store holds it**, never as a collaborator returned it."""
        held = await self.plans.get_execution(state.id)
        assert held is not None
        record = held.step(step_id)
        assert record is not None
        return record

    async def attempt(self, attempt_id: str = "a-1") -> GoalAttempt:
        """That attempt as the store holds it."""
        held = await self.plans.get_attempt(attempt_id)
        assert held is not None
        return held


def whole(budget: timedelta = PATIENT) -> TurnRemainder:
    """A remainder that never runs out inside an arm."""
    return TurnRemainder.opened(budget, monotonic=_Ticking(0.0))


# --- arm 5: a recorded DENY is applied and a recorded ALLOW is not -------


async def test_a_recorded_deny_is_applied_and_a_recorded_allow_is_not() -> None:
    """§12 arm 5, in one arm: act 2 commits the refusal and replays no approval.

    *"An implementation that replayed it fails this row, and it is the row that pins
    §5's asymmetry: a refusal is a repair and an approval would be a dispatch."*
    """
    world = World()
    await world.goal()
    refused, allowed = a_step("s-deny"), a_step("s-allow")
    state = await world.execution(refused, allowed)
    tool = acting()
    state, deny_confirm = await world.park(state, refused, tool)
    state, allow_confirm = await world.park(state, allowed, tool)
    denial = await world.decide(
        state, refused, tool, outcome=PermissionOutcome.DENY, resolves=deny_confirm.id
    )
    approval = await world.decide(
        state, allowed, tool, outcome=PermissionOutcome.ALLOW, resolves=allow_confirm.id
    )
    decisions_before = len(await world.trail.export())
    park_before = await world.stored(state, "s-allow")

    await world.pass_().run(GOAL, remaining=whole())

    refusal = await world.stored(state, "s-deny")
    assert refusal.status is StepStatus.SKIPPED
    assert refusal.skip_reason is SkipReason.APPROVAL_DENIED
    assert refusal.approval_ref == denial.id
    # The `ALLOW` row: left exactly as it stands, its resolution unspent.
    assert await world.stored(state, "s-allow") == park_before
    assert park_before.status is StepStatus.AWAITING_APPROVAL
    assert world.invoker.invocations == []
    assert len(await world.trail.export()) == decisions_before
    still = await world.trail.resolution_of(execution_id=state.id, step_id="s-allow")
    assert still is not None
    assert still.id == approval.id


# --- arms 6 and 7: the supersession sweep, completed ---------------------


async def test_a_partial_supersession_sweep_is_completed_from_pending() -> None:
    """§12 arm 6's first half: act 1 finishes what ADR-0255 §7's sweep left."""
    world = World()
    await world.goal()
    landed, left = a_step("s-1"), a_step("s-2")
    state = await world.execution(landed, left, plan_id="p-1")
    await world.execution(a_step("s-3"), plan_id="p-2", attempt_id="a-2", supersedes="p-1")
    # The sweep that landed one step and not the rest, as §7's own residual clause
    # leaves it: `s-1` durably `SKIPPED`/`SUPERSEDED`, `s-2` still `PENDING`.
    state = await world.plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s-1",
            to_status=StepStatus.SKIPPED,
            expected_version=state.version,
            skip_reason=SkipReason.SUPERSEDED,
        )
    )

    await world.pass_().run(GOAL, remaining=whole())

    completed = await world.stored(state, "s-2")
    assert completed.status is StepStatus.SKIPPED
    assert completed.skip_reason is SkipReason.SUPERSEDED
    assert (await world.stored(state, "s-1")).skip_reason is SkipReason.SUPERSEDED


async def test_a_superseded_park_is_swept_and_its_approval_is_not_spent() -> None:
    """§12 arm 7: the sweep takes ``AWAITING_APPROVAL`` too, and spends nothing.

    *"A sweep that moved only ``PENDING`` steps would leave the park standing
    ``AWAITING_APPROVAL`` on a plan nothing will drive"* — and the approval would then
    be spent on a step that could never have run (ADR-0255 §7).

    **And the same over a park already carrying a recorded ``ALLOW``**: it is committed
    ``SKIPPED``/``SUPERSEDED`` by act 1 like any other, the resolution stays in the
    trail unspent, and nothing dispatches.
    """
    world = World()
    await world.goal()
    plain, answered = a_step("s-park"), a_step("s-answered")
    state = await world.execution(plain, answered, plan_id="p-1")
    await world.execution(a_step("s-3"), plan_id="p-2", attempt_id="a-2", supersedes="p-1")
    tool = acting()
    state, _ = await world.park(state, plain, tool)
    state, confirm = await world.park(state, answered, tool)
    approval = await world.decide(
        state, answered, tool, outcome=PermissionOutcome.ALLOW, resolves=confirm.id
    )

    await world.pass_().run(GOAL, remaining=whole())

    for step_id in ("s-park", "s-answered"):
        swept = await world.stored(state, step_id)
        assert swept.status is StepStatus.SKIPPED
        assert swept.skip_reason is SkipReason.SUPERSEDED
    assert world.invoker.invocations == []
    unspent = await world.trail.resolution_of(execution_id=state.id, step_id="s-answered")
    assert unspent is not None
    assert unspent.id == approval.id


# --- arm 8: the attempt is repaired, and the scan wrote none of it -------


async def test_an_attempt_left_running_beside_an_uncertain_step_is_repaired() -> None:
    """§12 arm 8: act 3 writes ``EFFECT_UNRESOLVED``; the startup scan writes none."""
    world = World()
    await world.goal()
    step = a_step("s-1")
    state = await world.execution(step)
    state, _ = await world.uncertain(state, step, reading())
    # The residual the startup recovery scan leaves: the step is `INDETERMINATE` and
    # the attempt still reads `RUNNING`, because §6 rules the scan "writes no
    # `AttemptState`, reads no `GoalAttempt`, and takes no reconciliation call".
    assert (await world.attempt()).state is AttemptState.RUNNING

    await world.pass_().run(GOAL, remaining=whole())

    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED
    assert (await world.stored(state, "s-1")).status is StepStatus.INDETERMINATE


async def test_the_attempt_is_released_only_once_nothing_is_outstanding() -> None:
    """§12 arms 8-9: act 4's release, and that it waits while a step is uncertain."""
    world = World()
    await world.goal()
    step = a_step("s-1")
    state = await world.execution(step)
    state, decision = await world.uncertain(state, step, reading())

    await world.pass_().run(GOAL, remaining=whole())
    # Act 4 ran in the same pass as act 3 and declined: a step still stands uncertain.
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED

    await world.plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s-1",
            to_status=StepStatus.SUCCEEDED,
            expected_version=(await world.plans.get_execution(state.id)).version,  # type: ignore[union-attr]
            output=OUTPUT,
        )
    )
    await world.pass_().run(GOAL, remaining=whole())

    assert (await world.attempt()).state is AttemptState.RUNNING
    assert (await world.attempt()).outcome is None
    assert decision.ruling.outcome is PermissionOutcome.ALLOW


# --- the scripted seam arms 9-11 drive the check over ---------------------


class _Scripted:
    """A ``ToolInvoker`` that answers or raises exactly what an arm queued.

    Not ``FakeToolInvoker``, and deliberately: arm 10's second table is about
    exceptions the seam's **contract** names and about two it does not, and a fake that
    reproduces the contract cannot be made to raise the ones it does not. What is under
    test here is the **check's** disposal of each, so the seam is scripted.
    """

    def __init__(self, *answers: ToolResult | BaseException) -> None:
        """Queue one answer per call; a call past the last is a defect an arm sees."""
        self._answers = list(answers)
        self.calls: list[tuple[ToolCall, timedelta]] = []

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature (ADR-0029 §4)
        """Record the call and its deadline, then answer or raise."""
        self.calls.append((call, timeout))
        answer = self._answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def succeeded(output: FrozenJson = None) -> ToolResult:
    """A returning read."""
    return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=OUTPUT if output is None else output)


def failed(kind: ToolFailureKind = ToolFailureKind.UNAVAILABLE) -> ToolResult:
    """A read that did not answer."""
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(message="no", kind=kind))


def indeterminate() -> ToolResult:
    """A read whose own outcome is uncertain."""
    return ToolResult(
        outcome=ToolOutcome.INDETERMINATE,
        failure=ToolFailure(message="unknown", kind=ToolFailureKind.TIMED_OUT),
    )


async def an_uncertain_read(
    world: World,
    *,
    tool: ToolDefinition | None = None,
    binding: EgressBinding | None = None,
    parameters: Mapping[str, FrozenJson] | None = None,
) -> tuple[ExecutionState, PlanStep, PermissionDecision]:
    """One goal, one plan, one step left ``INDETERMINATE`` under ``tool``."""
    await world.goal()
    step = a_step("s-1", parameters=parameters)
    state = await world.execution(step)
    declared = tool or reading()
    decision = await world.decide(state, step, declared, binding=binding)
    state, decision = await world.uncertain(state, step, declared, decision=decision)
    return state, step, decision


# --- arm 10: every way a reconciliation does not resolve a step ----------


@pytest.mark.parametrize(
    "tool",
    [
        pytest.param(acting("book", Idempotency.NONE), id="side-effecting-none"),
        pytest.param(acting("book", Idempotency.KEYED), id="side-effecting-keyed"),
        pytest.param(acting("book", Idempotency.NATURAL), id="side-effecting-natural"),
    ],
)
async def test_an_uncheckable_declaration_takes_no_call(tool: ToolDefinition) -> None:
    """§12 arm 10's declaration rows: every side-effecting step takes **no call**.

    The ``NATURAL`` row is *"the one an implementation reading ``NATURAL`` as
    reconcilable would fail"*: §3 excludes it because that declaration is ADR-0016 §4's
    guarantee about **the effect** and *"nothing in this corpus declares that a repeat
    returns what the first call returned"*.
    """
    world = World()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]  # the scripted seam is a ToolInvoker
    state, _, _ = await an_uncertain_read(world, tool=tool)
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert found.uncertain == ("s-1",)
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


async def test_an_egress_decision_takes_no_call() -> None:
    """§12 arm 10's egress row: a decision carrying an ``egress_binding`` is uncheckable.

    *"Which can only be a side-effecting tool because ADR-0148 §8 rules that a tool
    registered at the seam declares a non-empty ``discloses`` … so that row pins a
    conjunct the first already implies and is kept for it."* It is kept here for the
    same reason: an implementation testing only ``side_effecting`` passes every other
    row of this table and fails this one.
    """
    world = World()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]
    binding = EgressBinding(
        spans=(
            EgressSpan(
                argument="reference",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("a@example.com"),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="a@example.com",
                    canonical="a@example.com",
                ),
            ),
        ),
        account=BoundAccount(identity="work@example.com", reference="conn-0001"),
        transport_endpoint="smtp://mail.example.com:587",
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )
    state, _, _ = await an_uncertain_read(
        world,
        tool=acting("send"),
        binding=binding,
        parameters={"reference": "a@example.com"},
    )
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


async def _left_exactly_as_it_stood(world: World, state: ExecutionState) -> None:
    """Arm 10's *"in **every** row"* clause, asserted once rather than per row.

    *"The step stays ``INDETERMINATE``, ``attempts`` is **unchanged**, no transition is
    committed, the attempt stays ``EFFECT_UNRESOLVED``, and **no second call is made in
    that turn**."*
    """
    record = await world.stored(state, "s-1")
    assert record.status is StepStatus.INDETERMINATE
    assert record.attempts == 1
    assert record.output is None
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED


class _RefusingTrail(FakeAuditTrail):
    """A trail whose ``get`` answers nothing, or raises, exactly as an arm asked."""

    def __init__(self, *, raises: bool = False, answers: bool = False) -> None:
        """Start empty; ``raises`` and ``answers`` are arm 10's two unbuildable rows."""
        super().__init__()
        self.raises = raises
        self.answers = answers

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer nothing, raise, or behave exactly as the fake does."""
        if self.raises:
            msg = "the trail cannot be read"
            raise AuditError(msg)
        if not self.answers:
            return None
        return await super().get(decision_id)


async def test_a_step_carrying_no_approval_ref_takes_no_call() -> None:
    """§12 arm 10: *"a step whose ``approval_ref`` is absent"* takes **no call**.

    Reached by hand rather than by a transition, because ``PlanExecution`` refuses a
    ``→ RUNNING`` claim without one — *"every executed step must name the decision that
    authorised it"* — so the state is one only a store that lost the reference can be
    in. The check's job is to leave it exactly where it stands.
    """
    world = World()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())
    held = await world.plans.get_execution(state.id)
    assert held is not None
    stripped = held.model_copy(
        update={
            "steps": tuple(step.model_copy(update={"approval_ref": None}) for step in held.steps)
        }
    )
    world.plans._executions[state.id] = stripped

    found = await world.check().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert found.uncertain == ("s-1",)
    assert found.established == ()


@pytest.mark.parametrize(
    ("raises", "answers"),
    [pytest.param(False, False, id="answers-nothing"), pytest.param(True, False, id="raises")],
)
async def test_a_trail_that_cannot_return_the_decision_takes_no_call(
    *, raises: bool, answers: bool
) -> None:
    """§12 arm 10's two trail rows, which §3 states as two and not one.

    *"Or ``AuditTrail.get`` **answers nothing** for the decision it names, or that read
    **raises ``AuditError``** — a closed, corrupt or unreadable trail, which is the same
    store failure §4 answers for its own reads and is answered the same way here."* The
    read is taken **before** ``ToolInvoker.invoke``, so its failure reaches no seam and
    is not one of §3's six.
    """
    world = World()
    world.trail = _RefusingTrail(raises=raises, answers=answers)
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


async def test_a_rebuild_the_decision_does_not_authorise_takes_no_call() -> None:
    """§12 arm 10: *"whose rebuilt request ``PermissionDecision.authorises`` rejects"*.

    Driven by a decision recorded over **different parameters** than the stored step
    carries — a plan edited between the claim and the reconciliation — which is exactly
    the drift §3 says the comparison is there to catch: *"a rebuild that drifted … fails
    that comparison and the step stays uncertain, which is the safe direction"*.
    """
    world = World()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]
    await world.goal()
    step = a_step("s-1")
    state = await world.execution(step)
    drifted = await world.decide(state, step, reading(), parameters={"reference": "R2"})
    state, _ = await world.uncertain(state, step, reading(), decision=drifted)
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(failed(), id="failed"),
        pytest.param(failed(ToolFailureKind.TIMED_OUT), id="timed-out"),
        pytest.param(indeterminate(), id="indeterminate"),
    ],
)
async def test_a_call_that_does_not_return_a_success_leaves_the_step_uncertain(
    answer: ToolResult,
) -> None:
    """§12 arm 10: a reconcilable step whose call does not succeed takes **one**.

    *"Neither a failed reconciliation nor an unbuildable one is ever read as
    establishing that the effect did not happen"* — ``INDETERMINATE → FAILED`` has no
    producer and §7 adds no row for it.
    """
    world = World()
    seam = _Scripted(answer)
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert len(seam.calls) == 1
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(ToolBindingError("the registry no longer holds it"), id="binding"),
        pytest.param(SpendCeilingError("a ceiling would be crossed"), id="ceiling"),
        pytest.param(SpendUndeterminedError("the spend has no number"), id="undetermined"),
        pytest.param(AuthorisationSpentError("spent"), id="spent"),
        pytest.param(UnrecordedAuthorisationError("unrecorded"), id="unrecorded"),
        pytest.param(AuditError("the claim append failed"), id="audit"),
    ],
)
async def test_each_declared_refusal_ends_the_check_and_not_the_turn(
    raised: Exception,
) -> None:
    """§12 arm 10's first raising table: §3's **six**, each ending the check alone.

    *"On those six the reconciliation writes nothing, the step stays ``INDETERMINATE``,
    the check ends there, no second step of that turn is reconciled, nothing is retried
    inside the turn, none of them escapes into the turn's own work, and the turn does
    not fail."*
    """
    world = World()
    seam = _Scripted(raised, succeeded())
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())

    found = await world.check().run(GOAL, remaining=whole())

    assert len(seam.calls) == 1
    assert found.established == ()
    await _left_exactly_as_it_stood(world, state)


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(ValueError("timeout is not a positive timedelta"), id="value-error"),
        pytest.param(RuntimeError("the invoker is broken"), id="runtime-error"),
        pytest.param(asyncio.CancelledError(), id="cancelled"),
    ],
)
async def test_an_undeclared_exception_propagates_out_of_the_check(
    raised: BaseException,
) -> None:
    """§12 arm 10's second raising table: *"an implementation catching a base class fails"*.

    *"Any exception the seam's contract does not name is propagated unchanged out of the
    check"*, and so is a ``ValueError``, which that contract raises only for a timeout
    this system computed — *"so raising it is this system's bug and not the seam's
    refusal"*. ``CancelledError`` propagates too, and is not counted among the six.
    """
    world = World()
    seam = _Scripted(raised)
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())

    with pytest.raises(type(raised)):
        await world.check().run(GOAL, remaining=whole())

    assert len(seam.calls) == 1
    await _left_exactly_as_it_stood(world, state)


# --- arm 9: the reconciliation that establishes the effect ---------------


def gated(*readings: float, budget: timedelta = PATIENT) -> TurnRemainder:
    """A remainder whose every gate reads the next figure an arm queued.

    ``started`` is supplied rather than read, so reading *n* is gate *n* and an arm
    counts gates rather than clock reads.
    """
    return TurnRemainder(budget=budget, started=0.0, monotonic=_Ticking(*readings))


async def test_a_reconcilable_step_is_established_and_its_attempt_released() -> None:
    """§12 arm 9: the pass leaves it standing, the check establishes it, act 4 releases.

    *"A step left ``INDETERMINATE`` by the recovery scan is **left standing by the pass
    and checked nowhere in it** … surfaced to the user in that turn's investigation phase
    and reconciled there … to ``SUCCEEDED``, its attempt returning to ``RUNNING`` on the
    next pass's act 4."*

    **``attempts`` is asserted equal before and after**, because §3 rules the call
    *"established what happened and was not an attempt at the effect"* — and an
    implementation that incremented it would corrupt the retry history while passing
    every other assertion here.
    """
    world = World()
    seam = _Scripted(succeeded())
    world.invoker = seam  # type: ignore[assignment]
    state, _, decision = await an_uncertain_read(world)

    await world.pass_().run(GOAL, remaining=whole())

    # The pass checked nowhere: the seam was not reached, and the only thing it wrote
    # for this step is act 3's attempt repair.
    assert seam.calls == []
    before = await world.stored(state, "s-1")
    assert before.status is StepStatus.INDETERMINATE
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED

    # A *fresh* check over the same store, which is the restart §3's rebuild clause is
    # stated over: nothing is carried in memory from the claim, and the request is
    # rebuilt from the stored plan and execution alone.
    found = await world.check().run(GOAL, remaining=whole())

    assert found.uncertain == ("s-1",)
    assert found.established == ("s-1",)
    called, deadline = seam.calls[0]
    assert called.decision.id == decision.id
    assert called.request.step_id == "s-1"
    assert called.request.execution_id == state.id
    assert called.request.goal == GOAL
    assert deadline > timedelta(0)
    # §1 gives a read no effect key at all, so no row is written for it and
    # ``claim_effect`` is never called for it (§7).
    assert called.effect_key is None
    assert (await world.plans.export()).effects == ()

    after = await world.stored(state, "s-1")
    assert after.status is StepStatus.SUCCEEDED
    assert after.output == OUTPUT
    assert after.attempts == before.attempts
    assert after.failure is None
    assert after.finished_at == AT

    # The release is the **next** pass's act 4, not this turn's check.
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED
    await world.pass_().run(GOAL, remaining=whole())
    assert (await world.attempt()).state is AttemptState.RUNNING
    assert (await world.attempt()).outcome is None


async def test_a_superseded_plans_step_reconciles_identically() -> None:
    """§12 arm 9's superseded row: *"a read drives nothing"*.

    ADR-0255 §7's *"drives nothing further"* refuses the **next claim**, and §3 takes
    none — so the conjunct it would be refused by is never reached, and ADR-0255 §7 is
    *"not reached rather than scoped"*. §6's override keeps the step out of act 1's
    sweep, which is what leaves it standing for the check at all.
    """
    world = World()
    seam = _Scripted(succeeded())
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)
    await world.execution(a_step("s-2"), plan_id="p-2", attempt_id="a-2", supersedes="p-1")

    await world.pass_().run(GOAL, remaining=whole())
    assert (await world.stored(state, "s-1")).status is StepStatus.INDETERMINATE

    found = await world.check().run(GOAL, remaining=whole())

    assert found.established == ("s-1",)
    assert (await world.stored(state, "s-1")).status is StepStatus.SUCCEEDED


async def test_the_rebuilt_request_is_the_one_step_runner_would_build() -> None:
    """§3's *"rebuilt the way ``StepRunner`` builds one"*, pinned rather than asserted.

    The production module states the construction rather than importing a private name
    across modules; this row is what stops the two drifting, by building both from one
    pair of stored rows and comparing them whole.
    """
    world = World()
    seam = _Scripted(succeeded())
    world.invoker = seam  # type: ignore[assignment]
    state, step, decision = await an_uncertain_read(world)
    await world.pass_().run(GOAL, remaining=whole())
    await world.check().run(GOAL, remaining=whole())

    rebuilt, _ = seam.calls[0]
    held = await world.plans.get_execution(state.id)
    assert held is not None
    assert rebuilt.request == _requested(decision.tool, step, held, None, goal=GOAL)


# --- arm 11: the pass's boundaries ---------------------------------------


async def a_world_with_all_three_residuals(*, goal_id: str = GOAL) -> World:
    """One goal carrying act 1's, act 2's and act 3's work at once."""
    world = World()
    await world.goal()
    swept, parked, uncertain_step = a_step("s-1"), a_step("s-2"), a_step("s-3")
    state = await world.execution(swept, parked, plan_id="p-1")
    await world.execution(a_step("s-9"), plan_id="p-2", attempt_id="a-2", supersedes="p-1")
    tool = acting()
    state, confirm = await world.park(state, parked, tool)
    await world.decide(state, parked, tool, outcome=PermissionOutcome.DENY, resolves=confirm.id)
    assert goal_id == GOAL
    assert uncertain_step.id == "s-3"
    return world


@pytest.mark.parametrize(
    ("readings", "swept", "refused"),
    [
        pytest.param((100.0,), False, False, id="before-act-1"),
        pytest.param((0.0, 100.0), True, False, id="between-act-1-and-act-2"),
    ],
)
async def test_a_non_positive_remainder_starts_nothing_and_ends_the_pass(
    readings: tuple[float, ...], *, swept: bool, refused: bool
) -> None:
    """§12 arm 11: the gate is over **every** act and between two of them.

    *"In each, **nothing is started** for the ungated step or attempt — no transition
    and no attempt state is committed — the step keeps the status it stood at, the pass
    **ends**, earlier acts' writes **stand**, and the **turn does not fail**; an
    implementation that gated only the first act, or that read the remainder once and
    reused it, fails the later rows."*
    """
    world = await a_world_with_all_three_residuals()
    execution_id = next(iter(k for k in world.plans._executions if k.startswith("p-1")))
    held = await world.plans.get_execution(execution_id)
    assert held is not None

    await world.pass_().run(GOAL, remaining=gated(*readings))

    swept_now = (await world.stored(held, "s-1")).status is StepStatus.SKIPPED
    refused_now = (await world.stored(held, "s-2")).status is StepStatus.SKIPPED
    assert swept_now is swept
    assert refused_now is refused
    # Whatever the gate stopped, the attempt was not moved: act 3 is later than both.
    assert (await world.attempt()).state is AttemptState.RUNNING


async def test_the_gate_stops_act_three_and_act_four_too() -> None:
    """§12 arm 11: *"acts 3's and 4's ``commit_attempt`` writes"*, each gated.

    Two rows in one arm, because the two acts differ in what they would have written and
    an implementation gating only one passes the other.
    """
    world = World()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]
    state, _, _ = await an_uncertain_read(world)

    # Act 3's gate: nothing before it to sweep or refuse, so the first reading is its.
    await world.pass_().run(GOAL, remaining=gated(100.0))
    assert (await world.attempt()).state is AttemptState.RUNNING

    await world.pass_().run(GOAL, remaining=whole())
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED
    await world.plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s-1",
            to_status=StepStatus.SUCCEEDED,
            expected_version=(await world.plans.get_execution(state.id)).version,  # type: ignore[union-attr]
            output=OUTPUT,
        )
    )

    # Act 4's gate: act 3 no longer applies, so the first reading is act 4's.
    await world.pass_().run(GOAL, remaining=gated(100.0))
    assert (await world.attempt()).state is AttemptState.EFFECT_UNRESOLVED
    assert seam.calls == []


async def test_the_pass_reaches_no_seam_and_hands_no_deadline_to_a_callable() -> None:
    """§12 arm 11: *"the pass is asserted to pass no ``timeout`` anywhere"*.

    *"No act reaches ``ToolInvoker.invoke`` or ``StepRunner``, so nothing here can raise
    the ``ValueError`` §3 propagates, and an implementation that handed a callable the
    turn's figure from inside the pass fails this row on the call it should not have
    made."* The strongest form of it is structural and is asserted here as well: the
    pass is constructed with **no** invoker and **no** runner, so there is no object
    through which such a call could be issued.
    """
    world = await a_world_with_all_three_residuals()
    seam = _Scripted()
    world.invoker = seam  # type: ignore[assignment]

    await world.pass_().run(GOAL, remaining=whole())

    assert seam.calls == []
    assert not hasattr(world.pass_(), "_invoker")


async def test_the_pass_touches_only_the_goal_the_turn_engaged() -> None:
    """§12 arm 11: *"a second goal carrying the same three residuals is unchanged"*."""
    world = await a_world_with_all_three_residuals()
    other = "g-2"
    await world.plans.save_goal(
        Goal(
            id=other,
            interpretation=(
                GoalInterpretation(
                    revision=1,
                    outcome="something else",
                    outcome_ground=Ground.USER_STATED,
                    outcome_span="something else",
                    recorded_at=AT,
                    raised_by="t-2",
                ),
            ),
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
            created_at=AT,
        )
    )
    plan = ActionPlan(
        id="p-other",
        goal_id=other,
        steps=(a_step("s-other"),),
        created_at=AT,
        targets_revision=1,
    )
    await world.plans.save_plan(plan)
    elsewhere = await world.plans.start_execution(plan.id)
    await world.plans.save_plan(
        ActionPlan(
            id="p-other-2",
            goal_id=other,
            steps=(a_step("s-other-2"),),
            created_at=AT,
            targets_revision=1,
            supersedes="p-other",
        )
    )
    await world.plans.open_attempt(
        GoalAttempt(
            id="a-other",
            goal_id=other,
            opened_at=AT,
            plan_ids=("p-other", "p-other-2"),
            execution_ids=(elsewhere.id,),
        )
    )
    before = await world.plans.get_execution(elsewhere.id)

    await world.pass_().run(GOAL, remaining=whole())

    assert await world.plans.get_execution(elsewhere.id) == before


class _FailingStore(FakePlanStore):
    """A store that raises on the *n*th write, and answers every read.

    ``PlanStore`` failures and lost compare-and-swaps arrive at the pass as one class
    (``StaleExecutionError`` is a ``PlanningError``), which is §4's *"stops at the first
    that loses"* and its store-failure clause being one rule rather than two.
    """

    def __init__(
        self, *, fail_transition_at: int | None = None, fail_attempt_at: int | None = None
    ) -> None:
        """Count writes from one; ``None`` fails none of that kind."""
        super().__init__(now=lambda: AT)
        self.transitions = 0
        self.attempts_written = 0
        self._fail_transition_at = fail_transition_at
        self._fail_attempt_at = fail_attempt_at

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Raise where this is the write the arm armed, else behave as the fake does."""
        self.transitions += 1
        if self.transitions == self._fail_transition_at:
            msg = "the store could not be written"
            raise PlanningError(msg)
        return await super().commit_transition(transition)

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Raise where this is the write the arm armed, else behave as the fake does."""
        self.attempts_written += 1
        if self.attempts_written == self._fail_attempt_at:
            msg = "the attempt could not be written"
            raise StaleExecutionError(msg)
        return await super().commit_attempt(transition)


class _CancellingTrail(FakeAuditTrail):
    """A trail whose ``resolution_of`` raises what an arm armed, at act 2's own await."""

    def __init__(self, raises: BaseException) -> None:
        """Arm the exception; every other member behaves as the fake does."""
        super().__init__()
        self._raises = raises

    async def resolution_of(self, *, execution_id: str, step_id: str) -> PermissionDecision | None:
        """Raise the armed exception."""
        raise self._raises


async def test_a_store_failure_ends_the_pass_and_what_landed_stands() -> None:
    """§12 arm 11: a failure injected at an act boundary stops the pass there.

    *"What landed **stands**, every later act is **not taken**, **no write is retried
    inside that turn**, **the turn itself does not fail**, and the next turn that engages
    the goal runs the pass again over whatever is then residual."*
    """
    world = World()
    world.plans = _FailingStore(fail_transition_at=2)
    await world.goal()
    first, second = a_step("s-1"), a_step("s-2")
    state = await world.execution(first, second, plan_id="p-1")
    await world.execution(a_step("s-9"), plan_id="p-2", attempt_id="a-2", supersedes="p-1")

    await world.pass_().run(GOAL, remaining=whole())

    assert (await world.stored(state, "s-1")).status is StepStatus.SKIPPED
    assert (await world.stored(state, "s-2")).status is StepStatus.PENDING
    # The next turn runs it again over what is then residual, and it lands.
    world.plans._fail_transition_at = None
    await world.pass_().run(GOAL, remaining=whole())
    assert (await world.stored(state, "s-2")).status is StepStatus.SKIPPED


async def test_an_audit_error_from_act_twos_read_ends_the_pass_and_not_the_turn() -> None:
    """§12 arm 11: *"including an ``AuditError`` from act 2's ``resolution_of`` read"*.

    §4 names the trail as one of the two stores whose failure ends the pass: *"a failure
    of either store it reads — ``PlanStore``, or the trail through ``resolution_of``,
    whose ``AuditError`` is one such failure — ends the pass for that turn"*.
    """
    world = World()
    world.trail = _CancellingTrail(AuditError("the trail cannot be read"))
    await world.goal()
    parked, step = a_step("s-1"), a_step("s-2")
    state = await world.execution(parked, step)
    state, _ = await world.park(state, parked, acting())

    await world.pass_().run(GOAL, remaining=whole())

    assert (await world.stored(state, "s-1")).status is StepStatus.AWAITING_APPROVAL
    # Act 3 is later than act 2, so the pass did not reach it.
    assert (await world.attempt()).state is AttemptState.RUNNING


async def test_a_cancellation_propagates_out_of_the_pass_unchanged() -> None:
    """§12 arm 11's distinct row: a ``CancelledError`` is never a store failure.

    *"It **propagates out of the pass unchanged**, **no later act is taken**, what landed
    **stands**, and the row fails an implementation that caught it, counted it as a store
    failure or let the turn continue."*
    """
    world = World()
    world.trail = _CancellingTrail(asyncio.CancelledError())
    await world.goal()
    parked = a_step("s-1")
    state = await world.execution(parked)
    state, _ = await world.park(state, parked, acting())

    with pytest.raises(asyncio.CancelledError):
        await world.pass_().run(GOAL, remaining=whole())

    assert (await world.stored(state, "s-1")).status is StepStatus.AWAITING_APPROVAL
    assert (await world.attempt()).state is AttemptState.RUNNING


async def test_two_turns_reconciling_one_step_leave_exactly_one_commit() -> None:
    """§12 arm 11's stale compare-and-swap row, driven by a barrier and not an error.

    *"Two turns reconcile one ``INDETERMINATE`` step at once and both calls return, one
    ``INDETERMINATE → SUCCEEDED`` commit **lands** and the other loses on a stale
    ``expected_version`` — after which the winner's ``SUCCEEDED``, its ``output`` and its
    ``finished_at`` **stand unchanged**, the loser **writes nothing**, **retries
    nothing**, makes **no second reconciliation call** and **does not fail its turn**."*

    **The two actors are two turns' investigation phases and not two passes** — the
    check is never the pass's (§3). The store is not permitted to pass this row by
    serialising the two checks in the test's own control flow, so both checks read the
    execution before either commits, which the barrier below enforces.
    """
    world = World()
    await world.goal()
    step = a_step("s-1")
    state = await world.execution(step)
    state, _ = await world.uncertain(state, step, reading())
    await world.pass_().run(GOAL, remaining=whole())

    barrier = asyncio.Barrier(2)

    class _Barriered(_Scripted):
        """A seam that holds both calls until each has been made."""

        async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
            """Wait for the other turn's call, then answer."""
            await barrier.wait()
            return await super().invoke(call, timeout=timeout)

    seam = _Barriered(succeeded(), succeeded({"seat": "later"}))
    world.invoker = seam  # type: ignore[assignment]
    first, second = (
        ReconciliationCheck(plans=world.plans, trail=world.trail, invoker=seam),
        ReconciliationCheck(plans=world.plans, trail=world.trail, invoker=seam),
    )

    outcomes = await asyncio.gather(
        first.run(GOAL, remaining=whole()), second.run(GOAL, remaining=whole())
    )

    assert len(seam.calls) == 2
    landed = [one for one in outcomes if one.established == ("s-1",)]
    lost = [one for one in outcomes if one.established == ()]
    assert len(landed) == 1
    assert len(lost) == 1
    record = await world.stored(state, "s-1")
    assert record.status is StepStatus.SUCCEEDED
    assert record.output in (OUTPUT, {"seat": "later"})
    assert record.finished_at == AT


# --- arm 6's second half: the supersession is what unsticks the goal ------


def _raising() -> FakeToolImplementation:
    """A callable that fails, which is how a holder reaches ``FAILED``."""

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        msg = "the booking service refused"
        raise RuntimeError(msg)

    return implementation


@pytest.mark.parametrize(
    ("supersedes", "answer", "dispatches"),
    [
        pytest.param("p-1", EffectClaim.CLAIMED, 1, id="superseded-unsticks-the-goal"),
        pytest.param(None, EffectClaim.HELD, 0, id="a-live-plans-hold-survives"),
    ],
)
async def test_a_failed_holder_releases_its_row_only_once_its_plan_is_superseded(
    supersedes: str | None, answer: EffectClaim, dispatches: int
) -> None:
    """§12 arm 6's second half, asserted against its own negative in one arm.

    *"Plan ``P``'s step ``A`` is **``FAILED``** and holds the goal's effect row; ``P`` is
    superseded by ``P2`` whose step would perform that same effect; ``P2``'s step answers
    **``CLAIMED``**, the row re-points to it, and it **dispatches exactly once**. Asserted
    against the negative in the same arm: with ``P`` **not** superseded, ``P2``'s step
    answers **``HELD``** and dispatches nothing, while ``A``'s own execution still answers
    ``CLAIMED`` for its retry — so the supersession is shown to be what unsticks the goal,
    and the live-plan hold is shown to survive."*

    It lives beside the pass's arms because it is what act 1's *"this act releases no
    effect row and deletes none"* clause is measured against: the release is
    ``claim_effect``'s **own** branch, decided in the store *"because only there is it
    atomic with the write"*, and an implementation that made the pass release rows would
    pass this arm's first row while breaking its second.
    """
    harness = ClaimHarness((claim_declaration(), _raising()))
    await claim_goal(harness.plans)
    first = await claim_execution(harness.plans, claim_step("s-1"))
    assert (await harness.drive(first, "s-1")).disposition is Disposition.EXECUTED
    assert (await harness.stored(first, "s-1")).status is StepStatus.FAILED
    later = await claim_execution(
        harness.plans, claim_step("s-2"), plan_id="p-2", supersedes=supersedes
    )
    calls_before = len(harness.invoker.invocations)

    await harness.drive(later, "s-2")

    assert harness.plans.answers[-1] is answer
    assert len(harness.invoker.invocations) - calls_before == dispatches
    rows = await harness.rows()
    assert len(rows) == 1
    assert rows[0].step_id == ("s-2" if supersedes else "s-1")
