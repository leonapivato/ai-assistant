"""ADR-0259 §12's arm 9 at the engine: the ordering, and the surfacing.

*"A step left ``INDETERMINATE`` by the recovery scan is left standing by the pass and
checked nowhere in it … **surfaced to the user in that turn's investigation phase and
reconciled there, both before that turn's first ``Planner.plan`` call**."*

Both halves are engine-level by construction and neither can be seen one level down.
The **ordering** is a fact about the sequence a turn takes — the association, then §4's
pass, then §3's check, then the planner — and no collaborator can observe it from
inside. The **surfacing** is a fact about what reaches the composing stage, which is
the engine's to hand over.

**Where the two halves sit on this tree, stated once rather than per case.**
``LearningLoop`` stamps ``AttemptPhase.INVESTIGATE`` **after** its first planner call
(``loop.py``), holds no ``PlanStore`` (ADR-0249 §11) and holds no ``ToolInvoker``. The
clause that is mechanically checkable is the **ordering** one, so both halves run
between ADR-0250 §3's association — which is where a turn resolves the goal it is
about, before it plans — and ``LearningLoop.respond``. A case here asserts that
ordering directly, against a recorder both the seam and the planner write to.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from test_engine import AT, PATIENT, Harness, NoStepPlanner, confirmable, tool

from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    AssociationVerdict,
    AttemptState,
    Goal,
    GoalAssociation,
    GoalAttempt,
    GoalInterpretation,
    Ground,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    Role,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reconciling import ReconciliationStage
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeGoalAssociator,
    FakeModelProvider,
    FakePlanStore,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import (
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        MemoryRecord,
        PlannerOutput,
        ReadAskOutcome,
        ShownFile,
        ToolCall,
        ToolDefinition,
    )

GOAL: Final = "goal-booked"
ASKED: Final = "did that go through?"
OUTPUT: Final = {"reservation": "R-9"}


class _Ordering:
    """What the turn did, in the order it did it — the arm's whole subject."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.events: list[str] = []


class _RecordingPlanner(NoStepPlanner):
    """A planner that records when it was called, and plans nothing."""

    def __init__(self, ordering: _Ordering) -> None:
        """Hold the recorder; the plan itself is ``NoStepPlanner``'s."""
        self._ordering = ordering

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        """Record the call, then plan as ``NoStepPlanner`` does."""
        self._ordering.events.append("plan")
        return await super().plan(
            goal,
            utterance=utterance,
            context=context,
            memories=memories,
            capabilities=capabilities,
            files=files,
            read_outcomes=read_outcomes,
            evidence=evidence,
        )


class _RecordingInvoker:
    """A ``ToolInvoker`` that records the reconciliation call and answers it."""

    def __init__(self, ordering: _Ordering) -> None:
        """Hold the recorder; every call succeeds with :data:`OUTPUT`."""
        self._ordering = ordering
        self.calls: list[ToolCall] = []

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature (ADR-0029 §4)
        """Record the call, then answer it."""
        self._ordering.events.append("reconcile")
        self.calls.append(call)
        assert timeout > timedelta(0)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=OUTPUT)


def _reading() -> ToolDefinition:
    """The one declaration ADR-0259 §3 admits a reconciliation call for."""
    return tool(tool_id="lookup", side_effecting=False, capability="look_up")


async def _a_goal_with_an_uncertain_read(plans: PlanStore, trail: Any, *, conversation: str) -> str:
    """Seed the residual a crash leaves: one ``INDETERMINATE`` read, attempt ``RUNNING``.

    That is §3's own route to an uncertain **read**: ``interrupted_outcome`` classifies
    an interrupted read as ``FAILED``, so what leaves one ``INDETERMINATE`` is the
    startup recovery scan moving a step a dead process left ``RUNNING`` *"without
    consulting a declaration"* (§6).
    """
    await plans.save_goal(
        Goal(
            id=GOAL,
            conversation_id=conversation,
            interpretation=(
                GoalInterpretation(
                    revision=1,
                    outcome="book a room in Lisbon",
                    outcome_ground=Ground.USER_STATED,
                    outcome_span="book a room in Lisbon",
                    recorded_at=AT,
                    raised_by="turn-1",
                ),
            ),
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
            created_at=AT,
        )
    )
    await plans.engage_goal(GOAL, at=AT, conversation_id=conversation, expected_version=0)
    step = PlanStep(
        id="s-1",
        intent="look the reservation up",
        capability="look_up",
        parameters={"reference": "R-9"},
    )
    plan = ActionPlan(id="p-1", goal_id=GOAL, steps=(step,), created_at=AT, targets_revision=1)
    await plans.save_plan(plan)
    state = await plans.start_execution(plan.id)
    await plans.open_attempt(
        GoalAttempt(
            id="a-1",
            goal_id=GOAL,
            opened_at=AT,
            plan_ids=(plan.id,),
            execution_ids=(state.id,),
        )
    )
    request: ActionRequest = _request(step, state.id)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="arm"),
        id="d-reconcile",
        decided_at=AT,
    )
    await trail.record(decision)
    claimed = await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s-1",
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool="lookup",
            approval_ref=decision.id,
            attempt_id="a-1",
        )
    )
    await plans.commit_transition(
        StepTransition(
            execution_id=claimed.id,
            step_id="s-1",
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
    return state.id


def _request(step: PlanStep, execution_id: str) -> ActionRequest:
    """The request the claim was made under, rebuilt here as the runner builds one."""
    return ActionRequest(
        tool=_reading(),
        parameters=step.parameters,
        goal=GOAL,
        intended_action=step.intended_action,
        step_id=step.id,
        execution_id=execution_id,
    )


async def test_the_pass_and_the_check_both_run_before_the_turns_first_plan_call() -> None:
    """§12 arm 9's ordering half, and its surfacing half, in one turn.

    The recorder is written to by the seam and by the planner, so the assertion is over
    the **sequence** rather than over two independent facts: an implementation that
    reconciled after planning, or inside the pass, fails it.
    """
    ordering = _Ordering()
    seam = _RecordingInvoker(ordering)
    provider = FakeModelProvider()
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = Harness(
        planner=_RecordingPlanner(ordering),
        composing=ComposingStage(model=provider, streaming=FakeStreamingCompleter()),
        tools=(_reading(),),
        associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.CONTINUES)),
        plans=plans,
        trail=trail,
        reconciliation=ReconciliationStage(plans=plans, trail=trail, invoker=seam),
        now=lambda: AT,
    )
    conversation = (await harness.conversations.begin(None)).id
    execution_id = await _a_goal_with_an_uncertain_read(plans, trail, conversation=conversation)

    outcome = await harness.engine.converse(ASKED, timeout=PATIENT, conversation_id=conversation)

    assert ordering.events == ["reconcile", "plan"], "both halves run before the planner"
    assert len(seam.calls) == 1
    held = await harness.plans.get_execution(execution_id)
    assert held is not None
    record = held.step("s-1")
    assert record is not None
    assert record.status is StepStatus.SUCCEEDED
    assert record.output == OUTPUT
    assert record.attempts == 1, "§3: the call established what happened, and was not an attempt"
    # **The attempt this turn leaves is ADR-0262 §4's and not this decision's.** Act 3
    # repaired it to `EFFECT_UNRESOLVED` before the check ran; the check then
    # established the one step that was outstanding, so §4's three ending conditions
    # held at the end of the turn and this engine ended it. Act 4's release is what
    # happens where the turn does **not** end the attempt, and is asserted at the unit
    # level (``test_reconciliation``) where nothing else is writing to the row.
    (attempt,) = await harness.plans.attempts_of(GOAL)
    assert attempt.state is AttemptState.ENDED
    # The surfacing: the turn says it is unsure whether the action went through. §10
    # books *what* the user is told to A9 and fixes "no reply, no phrasing and no
    # channel", so what is asserted is that the fact reached the answer at all — an
    # implementation that resolved the step silently fails this.
    system = next(message for message in provider.last_messages if message.role is Role.SYSTEM)
    assert "whether it went through" in system.content
    assert outcome.reply is not None


async def test_a_turn_over_a_goal_with_no_residual_says_nothing_and_calls_nothing() -> None:
    """The byte-identity half: a turn with nothing to reconcile is unchanged by this.

    ADR-0242 §6's guarantee, applied to this decision's clause: on a turn the check
    found nothing for, the assembled prompt is what it is without ADR-0259, and the seam
    is not reached.
    """
    ordering = _Ordering()
    seam = _RecordingInvoker(ordering)
    provider = FakeModelProvider()
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = Harness(
        planner=_RecordingPlanner(ordering),
        composing=ComposingStage(model=provider, streaming=FakeStreamingCompleter()),
        plans=plans,
        trail=trail,
        reconciliation=ReconciliationStage(plans=plans, trail=trail, invoker=seam),
        now=lambda: AT,
    )

    await harness.engine.converse(ASKED, timeout=PATIENT)

    assert ordering.events == ["plan"]
    assert seam.calls == []
    system = next(message for message in provider.last_messages if message.role is Role.SYSTEM)
    assert "whether it went through" not in system.content


async def test_a_turn_whose_new_step_parks_still_reconciles_and_composes_no_prose() -> None:
    """A parked turn reconciles and tells nothing, because ADR-0170 §4 says it may not.

    Adversarial review, round 1, ``blocker``, **waived with this row as its record.**
    The finding is true as stated — a turn whose plan parks for confirmation returns the
    confirmation and never says the earlier effect is uncertain — but the rule that
    produces it is not this decision's. ADR-0170 §4 rules that *"a pass whose step parked
    for confirmation"* composes no reply at all, *"because what the user must answer is
    the confirmation"* and *"prose beside it competes with the question"* (ADR-0197 §10
    states it again for a routed park). Every other statement this system composes rides
    the same way and is lost on the same shape — ``outbound_statement`` is documented as
    ``None`` on exactly that pass — so surfacing here would be **this lane** overturning
    ADR-0170 §4 for one clause, which ADR-0259 §10 expressly does not authorise: *"this
    decision fixes no reply, no phrasing and no channel"*, and **A9** owns what the user
    is told about an uncertain effect and whether *told once* survives a park.

    What this row pins is that nothing is **lost but the telling**: the pass and the
    check both ran, the step is established, and the record the A9 report will read is
    exactly the record §3 asks be preserved. Filed for A9 as an issue.
    """
    ordering = _Ordering()
    seam = _RecordingInvoker(ordering)
    provider = FakeModelProvider()
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = Harness(
        composing=ComposingStage(model=provider, streaming=FakeStreamingCompleter()),
        tools=(_reading(), confirmable()),
        associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.CONTINUES)),
        plans=plans,
        trail=trail,
        reconciliation=ReconciliationStage(plans=plans, trail=trail, invoker=seam),
        now=lambda: AT,
    )
    conversation = (await harness.conversations.begin(None)).id
    execution_id = await _a_goal_with_an_uncertain_read(plans, trail, conversation=conversation)

    outcome = await harness.engine.converse(ASKED, timeout=PATIENT, conversation_id=conversation)

    assert outcome.step is not None
    assert outcome.step.confirmation is not None, "the new step parked"
    assert outcome.reply is None, "ADR-0170 §4: a parked pass owes no answer"
    assert len(seam.calls) == 1, "and the reconciliation still happened"
    held = await plans.get_execution(execution_id)
    assert held is not None
    record = held.step("s-1")
    assert record is not None
    assert record.status is StepStatus.SUCCEEDED, "the record §3 asks be preserved is settled"
