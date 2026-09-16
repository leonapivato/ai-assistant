"""ADR-0259 §12's arms 1-3 and 12-13: the effect claim at dispatch, driven.

Everything here is driven through the stage that actually takes the claim —
:class:`~ai_assistant.orchestration.runner.StepRunner`, whose executor takes it
between ADR-0037 §2's read-back and the ``→ RUNNING`` commit — over the canonical
fakes, with **no consequential capability wired** (ADR-0255 §13's Q4 rule, which §12
states its arms over in terms).

**Every durable assertion is read back from the store**, never off the value the stage
returned: §9 has the store write a satisfied step's ``output`` and ``finished_at``
itself, and an arm reading the stage's own return would pass an implementation that
asserted them.

**Two counters stand in for "nothing was dispatched".** ``FakeToolInvoker.invocations``
is the seam's own record of what it ran, and :class:`_CountingTrail` counts the
invocation claims ADR-0192 §1 appends before a callable is entered — so an arm can say
both *the tool was not called* and *no authorisation was spent* rather than only the
first. :class:`_CountingPlanStore` counts ``claim_effect`` itself, which is what arm
13's second half is about: an unscoped step reaches that member **not at all**.

**What this tree cannot reach, said once here rather than implied per arm.** ADR-0255's
own L2 lands the walk; until it does, ``Engine`` drives ``turn.plan.steps[0]`` and no
other step, so no turn can satisfy two steps and no dependent of a satisfied step is
driven by a walk. Arm 1's continuation is asserted as the two facts this tree does
carry — the step is committed ``SUCCEEDED`` with the holder's output, so a dependant
reading it under ADR-0253 §2 finds what it needs, and the walk is not stopped, which is
what ``Disposition.EXECUTED`` beside ``EFFECT_ALREADY_CLAIMED`` says — and its
aggregation half is asserted over
:func:`~ai_assistant.orchestration.effects.told_once`, the accumulator the walk fills.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Disposition,
    EffectClaim,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    Goal,
    GoalAttempt,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    Ground,
    Idempotency,
    IntendedAction,
    IntendedActionMinting,
    MemorySource,
    PlanStep,
    Provenance,
    QuotedOutput,
    ReadKind,
    ReadOutcomeKind,
    Reversibility,
    RiskLevel,
    StepCondition,
    StepStatus,
    StepVerification,
    ToolCost,
    ToolDefinition,
    VerificationKind,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.effects import told_once
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.testing import FakeActionPolicy, FakeAuditTrail, FakePlanStore, FakeToolInvoker

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        ActionQuote,
        EffectKey,
        EffectOutcome,
        EffectRecord,
        ExecutionState,
        FrozenJson,
        PermissionDecision,
        StepExecution,
        ToolInvocation,
    )
    from ai_assistant.orchestration.runner import StepDisposition
    from ai_assistant.testing.invoker import FakeToolImplementation

#: The store's clock. Every durable instant here is this one.
AT: Final = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
PATIENT: Final = timedelta(seconds=30)

#: A deadline the blocking callable of arm 3 cannot meet.
BRIEF: Final = timedelta(microseconds=1)

GOAL: Final = "g-1"
ATTEMPT: Final = "a-1"
CAPABILITY: Final = "book_room"

#: The act the goal intends, and a second one beside it for arm 12.
ACT: Final = "act-1"
OTHER_ACT: Final = "act-2"

#: The condition element arm 2's refusal table is stated over, and the two regions that
#: make one row cover it and another not.
CONDITION: Final = "e-1"
SUNDAY: Final = EvidenceApplicability(topics=("sunday",))
SATURDAY: Final = EvidenceApplicability(topics=("saturday",))

#: What the tool returns, and what a satisfied step therefore carries.
OUTPUT: Final[dict[str, FrozenJson]] = {"booking": "bk-9", "price": "120", "currency": "EUR"}


# --- builders -----------------------------------------------------------


def declaration(tool_id: str = "rooms", **overrides: object) -> ToolDefinition:
    """A **side-effecting** declaration ``FakeActionPolicy`` allows outright."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": CAPABILITY,
        "description": "Book a room.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_step(  # noqa: PLR0913 — one keyword per field an arm varies; each is a distinct declaration
    step_id: str,
    *,
    action: str | None = ACT,
    parameters: Mapping[str, FrozenJson] | None = None,
    when: tuple[StepCondition, ...] = (),
    verifies: StepVerification | None = None,
    capability: str = CAPABILITY,
) -> PlanStep:
    """One step of a plan, naming ``action`` unless an arm asks for none."""
    return PlanStep(
        id=step_id,
        intent="book it",
        capability=capability,
        parameters={"nights": 2} if parameters is None else parameters,
        intended_action=action,
        when=when,
        verifies=verifies,
    )


async def a_goal(
    store: FakePlanStore,
    *,
    actions: tuple[str, ...] = (ACT,),
    conditions: tuple[GoalElement, ...] = (),
) -> Goal:
    """Store a goal holding ``actions``, through the writer that owns each field."""
    await store.save_goal(
        Goal(
            id=GOAL,
            interpretation=(
                GoalInterpretation(
                    revision=1,
                    outcome="book a room in Lisbon",
                    outcome_ground=Ground.USER_STATED,
                    outcome_span="book a room in Lisbon",
                    conditions=conditions,
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
    return await store.record_intended_actions(
        IntendedActionMinting(
            goal_id=GOAL,
            actions=tuple(IntendedAction(id=one, intent=f"perform {one}") for one in actions),
            expected_version=0,
        )
    )


async def an_execution(
    store: FakePlanStore,
    *steps: PlanStep,
    plan_id: str = "p-1",
    supersedes: str | None = None,
) -> ExecutionState:
    """Store a plan over ``steps`` and open an execution of it under an attempt."""
    plan = ActionPlan(
        id=plan_id,
        goal_id=GOAL,
        steps=steps,
        created_at=AT,
        targets_revision=1,
        supersedes=supersedes,
    )
    await store.save_plan(plan)
    state = await store.start_execution(plan.id)
    await store.open_attempt(
        GoalAttempt(
            id=f"{ATTEMPT}-{plan_id}",
            goal_id=GOAL,
            opened_at=AT,
            plan_ids=(plan.id,),
            execution_ids=(state.id,),
        )
    )
    return state


def a_row(row_id: str, *, supported: EvidenceApplicability) -> GoalEvidence:
    """A ``READ_OUTCOME`` row that answers, stands, and supports ``supported``."""
    return GoalEvidence(
        id=row_id,
        goal_id=GOAL,
        attempt_id=f"{ATTEMPT}-p-1",
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=ReadKind.FORECAST_READ,
        # **A forecast row names no record and its count stands alone** (ADR-0260 §9,
        # which §15 records as an amendment to ADR-0252 §1's ephemeral-kind list): its
        # records are minted for one turn and resolve in no store, so `returned` and
        # `admitted` below carry the figure on their own.
        records=(),
        supported=(supported,),
        supported_elided=0,
        read_at=AT,
        returned=1,
        admitted=1,
        verdict=ReadOutcomeKind.RETURNED_RECORDS.value,
        standing=EvidenceStanding.STANDING,
    )


def _never_returns() -> FakeToolImplementation:
    """A callable that outlives any deadline — arm 3's route to ``INDETERMINATE``."""

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        await asyncio.sleep(3600)
        return None

    return implementation


def returning(output: FrozenJson) -> FakeToolImplementation:
    """A tool that succeeds with ``output``."""

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        return output

    return implementation


# --- the two counters, and the store that counts the claim ---------------


class _CountingTrail(FakeAuditTrail):
    """A trail that counts the invocation claims ADR-0192 §1 appends."""

    def __init__(self) -> None:
        """Start with nothing claimed."""
        super().__init__()
        self.claims = 0

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Count the claim, then append it exactly as the fake does."""
        self.claims += 1
        return await super().claim_invocation(decision=decision)


class _CountingPlanStore(FakePlanStore):
    """A store that records every ``claim_effect`` and what it answered."""

    def __init__(self) -> None:
        """Start with nothing claimed, on the store clock every arm here reads."""
        super().__init__(now=lambda: AT)
        self.claims: list[tuple[str, str]] = []
        self.answers: list[EffectClaim] = []

    async def claim_effect(
        self, *, execution_id: str, step_id: str, effect_key: EffectKey
    ) -> EffectOutcome:
        """Record the call and the answer, then behave exactly as the fake does."""
        self.claims.append((execution_id, step_id))
        outcome = await super().claim_effect(
            execution_id=execution_id, step_id=step_id, effect_key=effect_key
        )
        self.answers.append(outcome.claim)
        return outcome


class Harness:
    """A wired ``StepRunner`` over the counting fakes."""

    def __init__(self, *tools: tuple[ToolDefinition, FakeToolImplementation]) -> None:
        """Wire the stage; the store stamps :data:`AT` and so does the executor."""
        self.plans = _CountingPlanStore()
        self.policy = FakeActionPolicy()
        self.trail = _CountingTrail()
        self.invoker = FakeToolInvoker(tools, ledger=self.trail, gate=self.trail)
        ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            now=lambda: AT,
            id_factory=lambda: next(ids),
        )

    async def drive(
        self,
        state: ExecutionState,
        step_id: str,
        *,
        timeout: timedelta = PATIENT,  # noqa: ASYNC109 — threaded to the seam, which owns the deadline
    ) -> StepDisposition:
        """Run one step under the attempt its execution was opened with."""
        return await self.runner.run(
            state,
            step_id,
            attempt_id=f"{ATTEMPT}-{state.plan_id}",
            timeout=timeout,
            origin=NOTHING_EXTERNAL,
        )

    async def quotes(self) -> tuple[ActionQuote, ...]:
        """The goal's quotes as the store holds them (ADR-0267 §2)."""
        goal = await self.plans.get_goal(GOAL)
        assert goal is not None
        return goal.quotes

    async def stored(self, state: ExecutionState, step_id: str) -> StepExecution:
        """That step's record **as the store holds it**, never as a stage returned it."""
        held = await self.plans.get_execution(state.id)
        assert held is not None
        record = held.step(step_id)
        assert record is not None
        return record

    async def rows(self) -> tuple[EffectRecord, ...]:
        """The effect rows the store holds, through the one document that carries them."""
        return (await self.plans.export()).effects


async def a_completed_effect(
    harness: Harness, *, step_id: str = "s-1", output: FrozenJson = None
) -> ExecutionState:
    """Drive one plan to a ``SUCCEEDED`` step, which is what every arm borrows from."""
    state = await an_execution(harness.plans, a_step(step_id))
    assert (await harness.drive(state, step_id)).disposition is Disposition.EXECUTED
    record = await harness.stored(state, step_id)
    assert record.status is StepStatus.SUCCEEDED
    assert record.output == (OUTPUT if output is None else output)
    return state


# --- arm 1: a modifying plan's step is satisfied (§12 arm 1) -------------


async def test_a_modifying_plans_step_is_satisfied_from_the_completed_effect() -> None:
    """Arm 1: not dispatched, ``COMPLETED``, satisfied from the holder's own output.

    Every durable value is read back from the store: §9 has the store write ``output``
    and ``finished_at`` itself, so an arm reading the stage's return would pass an
    implementation that asserted them instead of borrowing them.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans)
    first = await a_completed_effect(harness)
    later = await an_execution(harness.plans, a_step("s-2"), plan_id="p-2", supersedes="p-1")

    result = await harness.drive(later, "s-2")

    assert result.disposition is Disposition.EXECUTED, "the walk is not stopped"
    assert result.satisfied == "s-2", "the turn is told about the step it satisfied"
    assert harness.plans.answers == [EffectClaim.CLAIMED, EffectClaim.COMPLETED]
    assert len(harness.invoker.invocations) == 1, "ToolInvoker.invoke was not reached again"
    assert harness.trail.claims == 1, "no second invocation was claimed"
    record = await harness.stored(later, "s-2")
    assert record.status is StepStatus.SUCCEEDED
    assert record.output == OUTPUT, "the holder's own output, copied by the store"
    assert record.finished_at == AT
    assert record.attempts == 0, "nothing ran under it, so no attempt was spent"
    assert record.approval_ref is None, "a satisfied step carries no approval mark"
    assert record.started_at is None, "and no started_at: nothing ran under it"
    assert record.satisfied_by_execution == first.id
    assert record.satisfied_by_step == "s-1"
    holder = await harness.stored(first, "s-1")
    assert holder.attempts == 1, "the holder's own record is untouched"
    assert holder.satisfied_by_execution is None


def test_the_told_once_tuple_is_the_walk_order_undeduplicated() -> None:
    """Arm 1's aggregation half, over the accumulator ADR-0255's own L2 will fill.

    The three mistakes arm 1 names — overwriting at each satisfaction, deduplicating
    through a set, returning the sequence reversed — are each a property of this
    function and of nothing else on this tree, because ``Engine`` drives one step per
    turn until that walk lands. ``()`` never leaves it: ``TurnOutcome``'s own validator
    refuses an empty non-``None`` tuple, so ``None`` is the one spelling of *nothing*.
    """
    assert told_once(()) is None
    assert told_once(("s-2", "s-5")) == ("s-2", "s-5")
    assert told_once(("s-5", "s-2")) == ("s-5", "s-2"), "walk order, never sorted"
    assert told_once(("s-2", "s-2")) == ("s-2", "s-2"), "never deduplicated through a set"
    assert told_once(["s-9"]) == ("s-9",), "one satisfaction is a one-element tuple, not a scalar"


# --- arm 2: a fresh plan, a resumed step, and the refusal table ----------


async def test_a_freshly_planned_step_is_satisfied_the_same_way() -> None:
    """Arm 2's first half: a plan produced afresh rather than by modification.

    The later plan names no ``supersedes``, so nothing about the answer rests on the
    supersession branch of §2's table — the row is read at the ``(goal, intended
    action)`` pair, and the holder is ``SUCCEEDED`` under this call's own key.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans)
    first = await a_completed_effect(harness)
    later = await an_execution(harness.plans, a_step("s-2"), plan_id="p-2")

    result = await harness.drive(later, "s-2")

    assert result.disposition is Disposition.EXECUTED
    assert result.satisfied == "s-2"
    assert len(harness.invoker.invocations) == 1
    record = await harness.stored(later, "s-2")
    assert record.status is StepStatus.SUCCEEDED
    assert record.output == OUTPUT
    assert record.satisfied_by_execution == first.id
    assert record.satisfied_by_step == "s-1"


async def test_a_resumed_step_is_satisfied_from_awaiting_approval() -> None:
    """Arm 2's second half: the ``AWAITING_APPROVAL → SUCCEEDED`` commit §2 admits.

    Both steps are parked and answered, because the two have to carry the **same**
    ``EffectKey`` for the later one to meet ``COMPLETED`` at all — a different
    declaration would be a different key and therefore ``COMPLETED_OTHERWISE``.

    **"No second permission record authored" is read as what it can be checked as**:
    the resolving ``ALLOW`` ``resume`` records is the last decision the trail gains, and
    it stays **unspent** — no invocation is claimed against it (§5) — so nothing about
    the satisfaction authored or consumed an authority of its own.
    """
    confirmable = declaration(discloses=(DataTier.PERSONAL,))
    harness = Harness((confirmable, returning(OUTPUT)))
    await a_goal(harness.plans)
    first = await an_execution(harness.plans, a_step("s-1"))
    parked = await harness.drive(first, "s-1")
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    await harness.runner.resume(
        parked.state,
        "s-1",
        attempt_id=f"{ATTEMPT}-p-1",
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )
    later = await an_execution(harness.plans, a_step("s-2"), plan_id="p-2")
    second_park = await harness.drive(later, "s-2")
    assert second_park.disposition is Disposition.AWAITING_CONFIRMATION
    claimed_before = harness.trail.claims

    result = await harness.runner.resume(
        second_park.state,
        "s-2",
        attempt_id=f"{ATTEMPT}-p-2",
        confirmation_id=str(second_park.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert result.disposition is Disposition.EXECUTED
    assert result.satisfied == "s-2"
    assert len(harness.invoker.invocations) == 1, "the second answer dispatched nothing"
    assert harness.trail.claims == claimed_before, "the resolving ALLOW stays unspent"
    record = await harness.stored(later, "s-2")
    assert record.status is StepStatus.SUCCEEDED
    assert record.output == OUTPUT
    assert record.attempts == 0
    assert record.approval_ref is None, "a satisfied step carries no execution mark"
    assert record.bound_tool == "rooms", "an AWAITING_APPROVAL source keeps the tool it parked on"
    assert record.satisfied_by_step == "s-1"


@pytest.mark.parametrize(
    ("supported", "verifies", "holds"),
    [
        pytest.param(SUNDAY, None, True, id="when-holds"),
        pytest.param(SATURDAY, None, False, id="when-no-longer-holds"),
        pytest.param(
            SUNDAY,
            StepVerification(kind=VerificationKind.FIELD_EQUALS, field="booking", equals="bk-9"),
            True,
            id="verifies-holds",
        ),
        pytest.param(
            SUNDAY,
            StepVerification(
                kind=VerificationKind.FIELD_EQUALS, field="booking", equals="bk-other"
            ),
            False,
            id="verifies-rejects-the-borrowed-output",
        ),
    ],
)
async def test_each_reuse_condition_is_a_row_of_arm_twos_table(
    supported: EvidenceApplicability,
    verifies: StepVerification | None,
    *,
    holds: bool,
) -> None:
    """Arm 2's refusal table: one row per reuse condition, each paired with its positive.

    The pairing is what makes it a table rather than two assertions: the **same** step
    is satisfied where the condition holds and refused where it does not, so an
    implementation that marked every ``COMPLETED`` answer ``SUCCEEDED`` fails the
    refusing rows while an implementation that refused every one fails the holding rows.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(
        harness.plans,
        conditions=(
            GoalElement(
                id=CONDITION,
                text="the trip is on Sunday",
                ground=Ground.USER_STATED,
                span="on Sunday",
                applicability=SUNDAY,
            ),
        ),
    )
    await harness.plans.record_evidence(a_row("ev-1", supported=supported))
    first = await a_completed_effect(harness)
    conditioned = a_step(
        "s-2",
        when=(StepCondition(about=CONDITION, basis=EvidenceBasis.READ_OUTCOME),),
        verifies=verifies,
    )
    later = await an_execution(harness.plans, conditioned, plan_id="p-2")
    rows_before = await harness.rows()

    result = await harness.drive(later, "s-2")

    record = await harness.stored(later, "s-2")
    if holds:
        assert result.disposition is Disposition.EXECUTED
        assert result.satisfied == "s-2"
        assert record.status is StepStatus.SUCCEEDED
        assert record.satisfied_by_step == "s-1"
        return
    assert result.disposition is Disposition.EFFECT_ALREADY_CLAIMED
    assert result.satisfied is None, "nothing is announced for a step that was not satisfied"
    assert result.tool_id is None, "no tool id rides a refusal: nothing was dispatched"
    assert result.decision_id is None, "and no decision id either"
    assert record.status is StepStatus.PENDING, "the step keeps the status it was entered at"
    assert record.satisfied_by_execution is None
    assert len(harness.invoker.invocations) == 1, "no second invocation"
    assert await harness.rows() == rows_before, "the row did not move"
    holder = await harness.stored(first, "s-1")
    assert holder.status is StepStatus.SUCCEEDED, "the holder's own record is untouched"
    assert holder.attempts == 1


# --- arm 3: an INDETERMINATE holder, over both plan shapes ---------------


@pytest.mark.parametrize("supersedes", [None, "p-1"], ids=["fresh", "modifying"])
async def test_an_indeterminate_holder_answers_uncertain_and_stops_the_walk(
    supersedes: str | None,
) -> None:
    """Arm 3: the paired case over an ``INDETERMINATE`` first step, both plan shapes.

    What is uncertain is whether the act happened at all, so §2 answers ``UNCERTAIN``
    *"whether or not the keys are equal"* — and a differently-argued call under an
    action that may already have been performed is the one thing a modify-before-replace
    investigation must not be started from.

    The holder reaches ``INDETERMINATE`` the way ADR-0029 §4 says it does: a
    side-effecting, non-``NATURAL`` declaration whose callable outlives the deadline.
    """
    harness = Harness((declaration(idempotency=Idempotency.NONE), _never_returns()))
    await a_goal(harness.plans)
    first = await an_execution(harness.plans, a_step("s-1"))
    await harness.drive(first, "s-1", timeout=BRIEF)
    assert (await harness.stored(first, "s-1")).status is StepStatus.INDETERMINATE
    later = await an_execution(harness.plans, a_step("s-2"), plan_id="p-2", supersedes=supersedes)
    rows_before = await harness.rows()
    claimed_before = harness.trail.claims

    result = await harness.drive(later, "s-2")

    assert harness.plans.answers[-1] is EffectClaim.UNCERTAIN
    assert result.disposition is Disposition.EFFECT_ALREADY_CLAIMED
    assert result.satisfied is None
    assert harness.trail.claims == claimed_before, "the later step claimed no invocation"
    assert (await harness.stored(later, "s-2")).status is StepStatus.PENDING
    assert await harness.rows() == rows_before, "nothing was written"


# --- arm 12: two intended actions, one goal, two dispatches -------------


async def test_two_intended_actions_of_one_goal_both_dispatch() -> None:
    """Arm 12: the owner's *"book two identical rooms"*, which the scoping buys.

    The two steps' bound tool, resolved arguments and binding are identical, so their
    ``EffectKey``\\ s are **equal** — and they are still two rows, because the row is
    keyed on the goal **and the intended action**. An implementation that keyed it on
    ``(goal_id, effect_key)`` books one room and reports two.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans, actions=(ACT, OTHER_ACT))
    state = await an_execution(
        harness.plans, a_step("s-1", action=ACT), a_step("s-2", action=OTHER_ACT)
    )

    first = await harness.drive(state, "s-1")
    second = await harness.drive(first.state, "s-2")

    assert harness.plans.answers == [EffectClaim.CLAIMED, EffectClaim.CLAIMED]
    assert first.disposition is Disposition.EXECUTED
    assert second.disposition is Disposition.EXECUTED
    assert first.satisfied is None, "the first step acted rather than borrowing"
    assert second.satisfied is None, "and so did the second"
    assert len(harness.invoker.invocations) == 2, "ToolInvoker.invoke was reached twice"
    rows = await harness.rows()
    assert {row.intended_action_id for row in rows} == {ACT, OTHER_ACT}
    assert len({row.key for row in rows}) == 1, "one key, two rows — the scoping, not the key"


async def test_two_steps_under_one_intended_action_dispatch_once() -> None:
    """Arm 12's negative: one action, and the second step performs nothing.

    **The answer the second step meets depends on where the first one got to, and both
    halves are asserted.** Driven after the first has *succeeded*, §2's table answers
    ``COMPLETED`` — the same key under the same action — so the second step is
    **satisfied** rather than dispatched, which is one dispatch and not two. Driven
    while the first stands at its **entry** status, it answers ``HELD``, and that is §2's
    own stated residual of the effect-claim-then-step-claim ordering: *"A failure
    between the two leaves a row naming a step still at its entry status … every other
    step of that goal under the same intended action is ``HELD``"*. It is reached here
    the way §2 says it is reached — a ``→ RUNNING`` claim the store refuses after the
    row is written — rather than by contriving a concurrency the walk does not have.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans)
    state = await an_execution(harness.plans, a_step("s-1", action=ACT), a_step("s-2", action=ACT))

    first = await harness.drive(state, "s-1")
    second = await harness.drive(first.state, "s-2")

    assert first.disposition is Disposition.EXECUTED
    assert second.disposition is Disposition.EXECUTED
    assert second.satisfied == "s-2", "the second step performed nothing of its own"
    assert len(harness.invoker.invocations) == 1, "one dispatch, not two"
    assert len(await harness.rows()) == 1, "one row per (goal, intended action)"

    held = Harness((declaration(), returning(OUTPUT)))
    await a_goal(held.plans)
    unclaimed = await an_execution(held.plans, a_step("s-1", action=ACT), a_step("s-2", action=ACT))
    with pytest.raises(PlanningError):
        await held.runner.run(
            unclaimed,
            "s-1",
            attempt_id="a-no-such-attempt",
            timeout=PATIENT,
            origin=NOTHING_EXTERNAL,
        )
    assert (await held.stored(unclaimed, "s-1")).status is StepStatus.PENDING

    stalled = await held.drive(unclaimed, "s-2")

    assert held.plans.answers == [EffectClaim.CLAIMED, EffectClaim.HELD]
    assert stalled.disposition is Disposition.EFFECT_ALREADY_CLAIMED
    assert held.invoker.invocations == [], "nothing dispatched under a held act"


# --- arm 13: one action, different arguments — and the unscoped step -----


async def test_a_revised_argument_under_one_action_is_completed_otherwise() -> None:
    """Arm 13: the Sunday case end to end — not dispatched, and the row does not move.

    An implementation that answered ``CLAIMED`` to the revised step double-books; one
    that answered ``COMPLETED`` satisfies a changed request from an unchanged act.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans)
    first = await a_completed_effect(harness)
    revised = a_step("s-2", parameters={"nights": 3})
    later = await an_execution(harness.plans, revised, plan_id="p-2", supersedes="p-1")
    rows_before = await harness.rows()

    result = await harness.drive(later, "s-2")

    assert harness.plans.answers[-1] is EffectClaim.COMPLETED_OTHERWISE
    assert result.disposition is Disposition.EFFECT_ALREADY_CLAIMED
    assert result.satisfied is None
    assert len(harness.invoker.invocations) == 1, "ToolInvoker.invoke was not reached"
    assert harness.trail.claims == 1, "no invocation was claimed"
    record = await harness.stored(later, "s-2")
    assert record.status is StepStatus.PENDING, "the step keeps its entry status"
    assert record.satisfied_by_execution is None
    assert await harness.rows() == rows_before, "the row did not move and was not re-keyed"
    assert (await harness.stored(first, "s-1")).status is StepStatus.SUCCEEDED


async def test_a_side_effecting_step_naming_no_intended_action_is_unscoped() -> None:
    """Arm 13's second half: ``EFFECT_UNSCOPED``, and ``claim_effect`` is not called.

    Dispatching there would perform an effect **no row could ever recognise**, so every
    later plan of the goal would answer ``CLAIMED`` and repeat it.
    """
    harness = Harness((declaration(), returning(OUTPUT)))
    await a_goal(harness.plans)
    state = await an_execution(harness.plans, a_step("s-1", action=None))

    result = await harness.drive(state, "s-1")

    assert result.disposition is Disposition.EFFECT_UNSCOPED
    assert harness.plans.claims == [], "claim_effect was not called at all"
    assert harness.invoker.invocations == []
    assert harness.trail.claims == 0
    assert (await harness.stored(state, "s-1")).status is StepStatus.PENDING
    assert await harness.rows() == ()


async def test_a_step_that_is_not_side_effecting_is_driven_exactly_as_before() -> None:
    """Arm 13's control: no key, so the claim is never reached and ``None`` costs nothing."""
    reading = declaration(tool_id="inbox", capability="read_email", side_effecting=False)
    harness = Harness((reading, returning(OUTPUT)))
    await a_goal(harness.plans)
    state = await an_execution(harness.plans, a_step("s-1", action=None, capability="read_email"))

    result = await harness.drive(state, "s-1")

    assert result.disposition is Disposition.EXECUTED
    assert harness.plans.claims == [], "a call with no effect key reaches claim_effect never"
    assert len(harness.invoker.invocations) == 1
    assert (await harness.stored(state, "s-1")).status is StepStatus.SUCCEEDED


# --- ADR-0267 §4: a satisfied step mints nothing ------------------------


async def test_a_satisfied_step_mints_no_quote_from_the_borrowed_output() -> None:
    """A reading nobody took, at an instant nobody observed (ADR-0267 §4).

    The satisfied step is ``SUCCEEDED``, names an intended action and carries both an
    ``output`` and a ``finished_at``, so §4's four conditions all hold on it — and the
    facts they stand for do not: the price was read once, by the act this step borrowed
    from, and the instant on this record is when the **satisfaction** was committed.
    """
    priced = declaration(quoted_output=QuotedOutput(amount="price", currency="currency"))
    harness = Harness((priced, returning(OUTPUT)))
    await a_goal(harness.plans)
    await a_completed_effect(harness)
    minted = await harness.quotes()
    assert len(minted) == 1, "the act that ran read the price once"
    later = await an_execution(harness.plans, a_step("s-2"), plan_id="p-2")

    result = await harness.drive(later, "s-2")

    assert result.satisfied == "s-2"
    assert await harness.quotes() == minted, "the satisfaction appended no second reading"
