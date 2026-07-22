"""The join between planning and execution (ADR-0037).

What is here is everything that can only be observed by running the three
stages together: which tool selection picks and when it declines to, what
reaches the audit trail and in what order relative to the claim, and that the
authority a tool runs under is the one the trail holds.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing
here imports `tools/`, `permissions/` or `planning/` — which is exactly what the
subject under test is required to do (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    AuditError,
    InvalidResolutionError,
    PermissionDeniedError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    CostBasis,
    DataTier,
    Goal,
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
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import Disposition, StepExecutor, StepRunner
from ai_assistant.testing import FakeActionPolicy, FakeAuditTrail, FakePlanStore, FakeToolInvoker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ExecutionState, StepExecution

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)

STEP = "step-1"
CAPABILITY = "send_email"


# --- builders -----------------------------------------------------------


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright.

    Low risk, reversible, disclosing nothing, at a known cost: every floor in
    ADR-0021 §5 is clear of it, so a test wanting ``CONFIRM`` or ``DENY`` has to
    ask for it rather than getting it by accident.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": CAPABILITY,
        "description": "Send an email.",
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


def confirmable(tool_id: str = "smtp") -> ToolDefinition:
    """A declaration the fake policy confirms: it discloses off-device."""
    return tool(tool_id, discloses=(DataTier.PERSONAL,))


def plan_step(capability: str = CAPABILITY) -> PlanStep:
    """The one step every test here disposes of."""
    return PlanStep(
        id=STEP,
        intent="send the note",
        capability=capability,
        parameters={"to": "someone@example.com"},
    )


def clock(*, at: datetime = AT) -> Iterator[datetime]:
    """A clock that never moves, so recorded decisions are deterministic."""
    while True:
        yield at


async def an_execution(store: FakePlanStore, step: PlanStep) -> ExecutionState:
    """Store a goal, a one-step plan, and open an execution for it."""
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await store.save_goal(goal)
    plan = ActionPlan(id="p-1", goal_id=goal.id, steps=(step,), created_at=AT)
    await store.save_plan(plan)
    return await store.start_execution(plan.id)


async def stored_step(store: FakePlanStore, state: ExecutionState) -> StepExecution:
    """Read the one step back out of durable state."""
    reloaded = await store.get_execution(state.id)
    assert reloaded is not None
    found = reloaded.step(STEP)
    assert found is not None
    return found


# --- fault-injecting trails ---------------------------------------------


class LosingTrail(FakeAuditTrail):
    """A trail that accepts a write and then does not hold it.

    ADR-0036 §2 built the real trail so that "never recorded" is distinguishable
    from "corrupted"; this is the first of those, which no exception announces.
    """

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer ``None`` for everything, as a trail that lost the write does."""
        return None


class SubstitutingTrail(FakeAuditTrail):
    """A trail that hands back a record of a *different* action."""

    def __init__(self, substitute: PermissionDecision) -> None:
        """Return ``substitute`` from every lookup."""
        super().__init__()
        self._substitute = substitute

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer with the substituted decision."""
        return self._substitute


# --- the harness --------------------------------------------------------


class Harness:
    """A wired ``StepRunner`` and the fakes behind it, for assertions."""

    def __init__(
        self,
        *,
        tools: tuple[ToolDefinition, ...] = (),
        policy: FakeActionPolicy | None = None,
        trail: FakeAuditTrail | None = None,
        now: Clock | None = None,
    ) -> None:
        """Wire the stage over canonical fakes."""
        self.plans = FakePlanStore(now=lambda: AT)
        # One object as both registry and invoker, as ADR-0029 §8 requires of
        # the wiring — the same binding selects and acts.
        self.invoker = FakeToolInvoker([(definition, _succeeds) for definition in tools])
        self.policy = policy if policy is not None else FakeActionPolicy()
        self.trail = trail if trail is not None else FakeAuditTrail()
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        ticks = clock()
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            now=(lambda: next(ticks)) if now is None else now,
            id_factory=lambda: next(self.ids),
        )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


# --- selection (ADR-0037 §1) --------------------------------------------


async def test_no_capable_tool_skips_the_step_with_the_reserved_reason() -> None:
    """An unsatisfied capability is a detectable outcome, not an error."""
    harness = Harness()
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.NO_CAPABLE_TOOL
    assert result.decision_id is None
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SKIPPED
    assert stored.skip_reason is SkipReason.NO_CAPABLE_TOOL
    # Nothing was ruled on, so nothing is in the trail.
    assert await harness.trail.export() == []


async def test_several_candidates_commit_nothing_and_leave_the_step_pending() -> None:
    """No rule chooses, so no rule is invented and no falsehood is written."""
    harness = Harness(tools=(tool("a-sender"), tool("b-sender")))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.AMBIGUOUS_CAPABILITY
    assert result.state is state
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert stored.skip_reason is None
    assert harness.policy.requests == []
    assert harness.invoker.invocations == []


async def test_the_single_candidate_is_the_tool_ruled_on_and_run() -> None:
    """Selection hands the policy and the seam the same declaration."""
    harness = Harness(tools=(tool("smtp"),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    assert result.tool_id == "smtp"
    assert [request.tool.id for request in harness.policy.requests] == ["smtp"]
    assert [call.request.tool.id for call in harness.invoker.invocations] == ["smtp"]


async def test_the_step_parameters_are_what_the_policy_rules_on() -> None:
    """The gate rules on the arguments the plan actually proposes."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    await harness.runner.run(state, step, timeout=PATIENT)

    assert dict(harness.policy.requests[0].parameters) == {"to": "someone@example.com"}
    assert harness.policy.requests[0].step_id == STEP


# --- ALLOW: recording, then the claim (ADR-0037 §2, §3) -----------------


async def test_an_allowed_step_runs_and_names_a_decision_the_trail_holds() -> None:
    """Issue #107: the ``approval_ref`` on a run step resolves to a record."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SUCCEEDED
    assert stored.approval_ref is not None
    recorded = await harness.trail.get(stored.approval_ref)
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.ALLOW
    assert recorded.step_id == STEP


async def test_the_call_carries_the_trails_copy_of_the_decision() -> None:
    """The authority is read back, not remembered (ADR-0037 §3)."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    invoked = harness.invoker.invocations[0]
    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert invoked.decision == recorded


async def test_a_trail_that_lost_the_write_stops_the_turn_before_the_claim() -> None:
    """Nothing runs, and nothing is left ``RUNNING`` over a record nobody has."""
    harness = Harness(tools=(tool(),), trail=LosingTrail())
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="does not hold it"):
        await harness.runner.run(state, step, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert harness.invoker.invocations == []


async def test_a_trail_answering_about_another_action_is_refused() -> None:
    """A copy that does not authorise the request cannot become a call."""
    elsewhere = ActionRequest(
        tool=tool("other"), parameters={"to": "elsewhere@example.com"}, step_id=STEP
    )
    about_something_else = PermissionDecision.from_request(
        elsewhere,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="about something else"),
        id="d-substitute",
        decided_at=AT,
    )
    harness = Harness(tools=(tool(),), trail=SubstitutingTrail(about_something_else))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="does not authorise this request"):
        await harness.runner.run(state, step, timeout=PATIENT)

    assert harness.invoker.invocations == []
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


# --- DENY (ADR-0037 §5) --------------------------------------------------


async def test_a_denied_step_is_skipped_as_denied_and_points_at_the_decision() -> None:
    """``APPROVAL_DENIED`` is reachable only from ``AWAITING_APPROVAL``."""
    harness = Harness(tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.DENIED
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SKIPPED
    assert stored.skip_reason is SkipReason.APPROVAL_DENIED
    assert stored.approval_ref == result.decision_id
    assert stored.bound_tool == "smtp"
    assert harness.invoker.invocations == []


async def test_a_denial_is_recorded_in_the_trail() -> None:
    """ADR-0004 §7's reviewability covers what the assistant declined to do."""
    harness = Harness(tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.DENY


# --- CONFIRM (ADR-0037 §4) ----------------------------------------------


async def test_a_confirm_parks_the_step_durably_and_asks_nobody() -> None:
    """The turn stops; it does not invent an answer or block."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, step, timeout=PATIENT)

    assert result.disposition is Disposition.AWAITING_CONFIRMATION
    assert result.decision_id is not None
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.AWAITING_APPROVAL
    assert stored.bound_tool == "smtp"
    assert harness.invoker.invocations == []
    parked = await harness.trail.get(result.decision_id)
    assert parked is not None
    assert parked.ruling.outcome is PermissionOutcome.CONFIRM


async def test_an_approved_confirmation_runs_the_step_it_was_about() -> None:
    """Resuming turns the parked step into an execution under a resolving ALLOW."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, step, timeout=PATIENT)

    result = await harness.runner.resume(
        parked.state,
        step,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert result.disposition is Disposition.EXECUTED
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SUCCEEDED
    assert stored.approval_ref == result.decision_id
    resolution = await harness.trail.get(str(result.decision_id))
    assert resolution is not None
    assert resolution.resolves == parked.decision_id
    assert resolution.ruling.authorised_by == parked.decision_id


async def test_a_declined_confirmation_skips_the_step_as_denied() -> None:
    """Only ``True`` is consent, and a refusal is honoured (ADR-0021 §3)."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, step, timeout=PATIENT)

    result = await harness.runner.resume(
        parked.state,
        step,
        confirmation_id=str(parked.decision_id),
        approved=False,
        timeout=PATIENT,
    )

    assert result.disposition is Disposition.DENIED
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SKIPPED
    assert stored.skip_reason is SkipReason.APPROVAL_DENIED
    assert harness.invoker.invocations == []


async def test_the_resumed_tool_is_the_declaration_the_user_was_shown() -> None:
    """The definition comes from the record, never re-resolved through the registry."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, step, timeout=PATIENT)
    shown = await harness.trail.get(str(parked.decision_id))
    assert shown is not None

    await harness.runner.resume(
        parked.state,
        step,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert harness.invoker.invocations[0].decision.tool == shown.tool


async def test_resuming_a_confirmation_for_another_step_is_refused() -> None:
    """One step's prompt must not release another step's action (ADR-0021 §1)."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, step, timeout=PATIENT)
    elsewhere = PlanStep(id="step-2", intent="send another", capability=CAPABILITY)

    with pytest.raises(PermissionDeniedError, match="different plan step"):
        await harness.runner.resume(
            parked.state,
            elsewhere,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []
    assert harness.invoker.invocations == []


async def test_resuming_something_that_was_never_a_question_is_refused() -> None:
    """An answer to a decision nobody was shown authorises nothing."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    allowed = await harness.runner.run(state, step, timeout=PATIENT)

    with pytest.raises(PermissionDeniedError, match="never shown as a question"):
        await harness.runner.resume(
            allowed.state,
            step,
            confirmation_id=str(allowed.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []


async def test_resuming_an_unknown_confirmation_is_refused() -> None:
    """A pointer the trail cannot resolve is not an answer to anything."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="holds no decision"):
        await harness.runner.resume(
            state, step, confirmation_id="never-recorded", approved=True, timeout=PATIENT
        )


async def test_parameters_changed_since_the_prompt_are_refused_by_the_trail() -> None:
    """The confirmation must answer the question that was asked (ADR-0021 §4)."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, step, timeout=PATIENT)
    rewritten = step.model_copy(update={"parameters": {"to": "somebody-else@example.com"}})

    with pytest.raises(InvalidResolutionError):
        await harness.runner.resume(
            parked.state,
            rewritten,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.invoker.invocations == []


# --- the clock -----------------------------------------------------------


async def test_a_naive_clock_reading_fails_the_stage_that_read_it() -> None:
    """ADR-0026 §4: `orchestration` has no error of its own, so the stage's stands."""
    harness = Harness(tools=(tool(),), now=lambda: datetime(2026, 7, 22, 9, 0))  # noqa: DTZ001
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(PlanningError):
        await harness.runner.run(state, step, timeout=PATIENT)

    assert await harness.trail.export() == []
    assert harness.invoker.invocations == []
