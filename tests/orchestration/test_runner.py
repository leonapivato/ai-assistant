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
    from collections.abc import Callable, Iterator

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ExecutionState, StepExecution

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)

STEP = "step-1"
NEIGHBOUR = "step-2"
CAPABILITY = "send_email"

#: The id ``Harness`` mints for the first decision of a test.
FIRST_DECISION = "d-1"


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


async def a_two_step_execution(store: FakePlanStore) -> ExecutionState:
    """Store a goal, a two-step plan, and open an execution for it."""
    goal = Goal(
        id="g-1",
        statement="send the notes",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await store.save_goal(goal)
    neighbour = PlanStep(id=NEIGHBOUR, intent="send another", capability=CAPABILITY)
    plan = ActionPlan(id="p-1", goal_id=goal.id, steps=(plan_step(), neighbour), created_at=AT)
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


class MislabelledTrail(FakeAuditTrail):
    """A trail whose row is keyed as one id and stores another.

    The shape ADR-0036 §2's storage admits: the key and the serialised record are
    written separately, so a corrupted row round-trips and validates while
    calling itself something else. Everything downstream reads ``decision.id``.
    """

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer with the right decision under the wrong name."""
        stored = await super().get(decision_id)
        if stored is None:
            return None
        return stored.model_copy(update={"id": f"{stored.id}-relabelled"})


# --- fault-injecting plan stores ----------------------------------------


class LeakyPlanStore(FakePlanStore):
    """A store that hands back the plan it holds, rather than a snapshot.

    ``PlanStore`` contracts no detached snapshot — unlike ``MemoryStore``,
    ``ToolRegistry`` and ``AuditTrail`` — so this is a *conforming* store, and
    the caller is the one that has to hold its own copy.
    """

    def __init__(self, **kwargs: object) -> None:
        """Record the plan most recently handed out, so a test can mutate it."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.handed_out: ActionPlan | None = None

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the stored plan itself, attached."""
        detached = await super().get_plan(plan_id)
        self.handed_out = detached
        return detached


class TurncoatPolicy(FakeActionPolicy):
    """A policy that rewrites the ruling it already returned.

    It hands back an `ALLOW`, keeps the object, and flips it to `DENY` through
    ``__dict__`` — the bypass ADR-0018 §3 puts inside the threat model — at the
    first opportunity, which is the ``await`` on ``AuditTrail.record``.
    """

    def __init__(self) -> None:
        """Allow everything, then think better of it."""
        super().__init__(confirm_at=None)
        self.issued: PermissionRuling | None = None

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Return an ``ALLOW`` this policy intends to take back."""
        ruling = await super().decide(request)
        self.issued = ruling
        return ruling

    def defect(self) -> None:
        """Rewrite the returned ruling to a ``DENY``."""
        assert self.issued is not None
        self.issued.__dict__["outcome"] = PermissionOutcome.DENY


class RetentivePolicy(FakeActionPolicy):
    """A policy that keeps the request it was handed and rewrites it later.

    ``decide`` receives the caller's ``ActionRequest``; nothing stops a policy
    holding on to it, and ``frozen=True`` does not stop ``__dict__``
    (ADR-0018 §3).
    """

    def __init__(self) -> None:
        """Allow everything, and remember what was asked."""
        super().__init__(confirm_at=None)
        self.held: ActionRequest | None = None

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule as the fake does, keeping the request."""
        self.held = request
        return await super().decide(request)

    def rewrite(self, definition: ToolDefinition) -> None:
        """Point the retained request at another declaration."""
        assert self.held is not None
        self.held.__dict__["tool"] = definition


class SwappingPolicy(FakeActionPolicy):
    """A policy that rules on one action and swaps in another before returning.

    The capability ADR-0021 §3 removed from `PermissionRuling` by giving it no
    subject field, reintroduced through the *request* if the object it is handed
    is the one that then gets bound and executed.
    """

    def __init__(self, substitute: ToolDefinition) -> None:
        """Allow everything, then point the request at ``substitute``."""
        super().__init__(confirm_at=None)
        self.substitute = substitute

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule, then rewrite the request it ruled on."""
        ruling = await super().decide(request)
        request.__dict__["tool"] = self.substitute
        return ruling


class TurncoatTrail(FakeAuditTrail):
    """A trail that lets the policy defect while the write is in flight."""

    def __init__(self, defect: Callable[[], None]) -> None:
        """Run ``defect`` mid-``record``, as an interleaving would."""
        super().__init__()
        self._defect = defect

    async def record(self, decision: PermissionDecision) -> str:
        """Append, giving the policy the await it needs to change its mind."""
        recorded = await super().record(decision)
        self._defect()
        return recorded


class RedirectingTrail(FakeAuditTrail):
    """A trail that lets a caller repoint its own ``state`` while a write is in flight.

    The interleaving that defeats a stage which authenticates the stored
    execution and then reads ``state.id``/``state.version`` again after an await:
    the ``record`` this stage does before any transition is that await.
    """

    def __init__(self, redirect: Callable[[], None]) -> None:
        """Run ``redirect`` mid-``record``, as a concurrent mutation would."""
        super().__init__()
        self._redirect = redirect

    async def record(self, decision: PermissionDecision) -> str:
        """Append, giving the caller the await it needs to move its state."""
        recorded = await super().record(decision)
        self._redirect()
        return recorded


class ForgetfulPlanStore(FakePlanStore):
    """A store whose execution outlives the plan it names.

    ``delete_goal`` cascades, so the combination is not reachable through the
    contract — which is exactly why the branch that refuses it needs a double.
    """

    def __init__(self, **kwargs: object) -> None:
        """Start out holding plans normally."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.forget_plans = False

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Answer ``None`` once the store has been told to forget."""
        if self.forget_plans:
            return None
        return await super().get_plan(plan_id)


class RewritingPolicy(FakeActionPolicy):
    """A policy that rewrites the store's step id while ruling on it.

    The mutation ADR-0018 §3 puts inside the threat model: ``frozen=True``
    refuses ``step.id = ...`` and does nothing about ``step.__dict__``. A stage
    reading the store's object after this would rule on one step and commit
    against another.
    """

    def __init__(self, store: LeakyPlanStore, *, becomes: str) -> None:
        """Deny everything, and rewrite the handed-out step on the way."""
        super().__init__(deny_at=RiskLevel.LOW)
        self._store = store
        self._becomes = becomes

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rewrite the step the store handed out, then rule as the fake does."""
        plan = self._store.handed_out
        assert plan is not None
        plan.steps[0].__dict__["id"] = self._becomes
        return await super().decide(request)


# --- the harness --------------------------------------------------------


class Harness:
    """A wired ``StepRunner`` and the fakes behind it, for assertions."""

    def __init__(  # one knob per fake; that is what a harness is
        self,
        *,
        tools: tuple[ToolDefinition, ...] = (),
        plans: FakePlanStore | None = None,
        policy: FakeActionPolicy | None = None,
        trail: FakeAuditTrail | None = None,
        now: Clock | None = None,
    ) -> None:
        """Wire the stage over canonical fakes."""
        self.plans = plans if plans is not None else FakePlanStore(now=lambda: AT)
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

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

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

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.AMBIGUOUS_CAPABILITY
    # Value-equal to the input: nothing was committed. It is the private snapshot
    # `run` detaches on entry, not the caller's object by identity.
    assert result.state == state
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

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    assert result.tool_id == "smtp"
    assert [request.tool.id for request in harness.policy.requests] == ["smtp"]
    assert [call.request.tool.id for call in harness.invoker.invocations] == ["smtp"]


async def test_the_step_parameters_are_what_the_policy_rules_on() -> None:
    """The gate rules on the arguments the plan actually proposes."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    await harness.runner.run(state, STEP, timeout=PATIENT)

    assert dict(harness.policy.requests[0].parameters) == {"to": "someone@example.com"}
    assert harness.policy.requests[0].step_id == STEP


# --- ALLOW: recording, then the claim (ADR-0037 §2, §3) -----------------


async def test_an_allowed_step_runs_and_names_a_decision_the_trail_holds() -> None:
    """Issue #107: the ``approval_ref`` on a run step resolves to a record."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

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

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    invoked = harness.invoker.invocations[0]
    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert invoked.decision == recorded


async def test_a_trail_that_lost_the_write_stops_the_turn_before_the_claim() -> None:
    """Nothing runs, and nothing is left ``RUNNING`` over a record nobody has."""
    harness = Harness(tools=(tool(),), trail=LosingTrail())
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="does not hold decision"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert harness.invoker.invocations == []


async def test_a_trail_answering_about_another_action_is_refused() -> None:
    """A copy describing another action is refused, ``ALLOW`` included.

    It carries the id that was asked for, so the identity check passes and the
    subject comparison is what refuses it — the two guards are separable, and
    the subject one runs on every outcome rather than only where a ``ToolCall``
    would have caught it.
    """
    elsewhere = ActionRequest(
        tool=tool("other"), parameters={"to": "elsewhere@example.com"}, step_id=STEP
    )
    about_something_else = PermissionDecision.from_request(
        elsewhere,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="about something else"),
        id=FIRST_DECISION,
        decided_at=AT,
    )
    harness = Harness(tools=(tool(),), trail=SubstitutingTrail(about_something_else))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="is not the decision that was recorded"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


async def test_a_denial_read_back_as_an_approval_runs_nothing() -> None:
    """A flipped outcome is a reversed policy, and the subject would not show it."""
    request = ActionRequest(tool=tool(), parameters={"to": "someone@example.com"}, step_id=STEP)
    flipped = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the trail says otherwise"),
        id=FIRST_DECISION,
        decided_at=AT,
    )
    harness = Harness(
        tools=(tool(),),
        policy=FakeActionPolicy(deny_at=RiskLevel.LOW),
        trail=SubstitutingTrail(flipped),
    )
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="is not the decision that was recorded"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


async def test_an_approval_read_back_as_a_denial_skips_nothing() -> None:
    """The inverse writes a durable refusal that never happened."""
    request = ActionRequest(tool=tool(), parameters={"to": "someone@example.com"}, step_id=STEP)
    flipped = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.DENY, reason="the trail says otherwise"),
        id=FIRST_DECISION,
        decided_at=AT,
    )
    harness = Harness(tools=(tool(),), trail=SubstitutingTrail(flipped))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="is not the decision that was recorded"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert stored.skip_reason is None


# --- DENY (ADR-0037 §5) --------------------------------------------------


async def test_a_denied_step_is_skipped_as_denied_and_points_at_the_decision() -> None:
    """A `PENDING` `DENY` skips in one commit, over ADR-0041's direct edge."""
    harness = Harness(tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.DENIED
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SKIPPED
    assert stored.skip_reason is SkipReason.APPROVAL_DENIED
    assert stored.approval_ref == result.decision_id
    # No `bound_tool`: the step went straight from `PENDING` and never queued
    # for an approval; the `approval_ref` names the decision that refused it.
    assert stored.bound_tool is None
    assert harness.invoker.invocations == []


async def test_a_denial_is_recorded_in_the_trail() -> None:
    """ADR-0004 §7's reviewability covers what the assistant declined to do."""
    harness = Harness(tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.DENY


# --- CONFIRM (ADR-0037 §4) ----------------------------------------------


async def test_a_confirm_parks_the_step_durably_and_asks_nobody() -> None:
    """The turn stops; it does not invent an answer or block."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

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
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)

    result = await harness.runner.resume(
        parked.state,
        STEP,
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
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)

    result = await harness.runner.resume(
        parked.state,
        STEP,
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
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    shown = await harness.trail.get(str(parked.decision_id))
    assert shown is not None

    await harness.runner.resume(
        parked.state,
        STEP,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert harness.invoker.invocations[0].decision.tool == shown.tool


async def test_resuming_a_confirmation_for_another_step_is_refused() -> None:
    """One step's prompt must not release another step's action (ADR-0021 §1)."""
    harness = Harness(tools=(confirmable(),))
    state = await a_two_step_execution(harness.plans)
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)

    with pytest.raises(PermissionDeniedError, match="different plan step"):
        await harness.runner.resume(
            parked.state,
            NEIGHBOUR,
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
    allowed = await harness.runner.run(state, STEP, timeout=PATIENT)

    with pytest.raises(PermissionDeniedError, match="never shown as a question"):
        await harness.runner.resume(
            allowed.state,
            STEP,
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

    with pytest.raises(AuditError, match="does not hold decision"):
        await harness.runner.resume(
            state, STEP, confirmation_id="never-recorded", approved=True, timeout=PATIENT
        )


async def test_the_answered_action_cannot_drift_from_the_one_confirmed() -> None:
    """The prompt and the answer read the same immutable plan step.

    ADR-0014 §2 makes a plan an intact audit record — re-planning takes a new id
    — so the parameters cannot be rewritten under a live execution, and
    ``resume`` rebuilds the request from that same step. ``AuditTrail.record``'s
    subject check stays the backstop for a store that let it happen.
    """
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    rewritten = step.model_copy(update={"parameters": {"to": "somebody-else@example.com"}})

    with pytest.raises(PlanningError, match="already exists and differs"):
        await harness.plans.save_plan(
            ActionPlan(id="p-1", goal_id="g-1", steps=(rewritten,), created_at=AT)
        )

    result = await harness.runner.resume(
        parked.state,
        STEP,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert result.disposition is Disposition.EXECUTED
    confirmed = await harness.trail.get(str(parked.decision_id))
    resolution = await harness.trail.get(str(result.decision_id))
    assert confirmed is not None
    assert resolution is not None
    assert resolution.parameters_digest == confirmed.parameters_digest


async def test_a_confirmation_cannot_release_the_same_step_of_another_execution() -> None:
    """A plan may have several executions, and an approval names no execution."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    first = await an_execution(harness.plans, step)
    parked = await harness.runner.run(first, STEP, timeout=PATIENT)
    # A second execution of the same plan: the same step id, still `PENDING`,
    # for which `PENDING → RUNNING` would be a perfectly legal claim.
    second = await harness.plans.start_execution("p-1")

    with pytest.raises(PermissionDeniedError, match="not awaiting approval"):
        await harness.runner.resume(
            second,
            STEP,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []
    assert harness.invoker.invocations == []
    reloaded = await harness.plans.get_execution(second.id)
    assert reloaded is not None
    assert reloaded.step(STEP) is not None
    assert reloaded.step(STEP).status is StepStatus.PENDING  # type: ignore[union-attr]  # asserted above


async def test_a_confirmation_for_another_tool_does_not_release_a_parked_step() -> None:
    """The parked step must await approval for the declaration being resolved."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    # A real, recorded confirmation about the same step and a *different*
    # declaration — the shape a rebound id produces (ADR-0016 §5, issue #54).
    about_another_tool = PermissionDecision.from_request(
        ActionRequest(
            tool=confirmable("somebody-else"),
            parameters=step.parameters,
            step_id=STEP,
        ),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="a different declaration"),
        id="d-elsewhere",
        decided_at=AT,
    )
    await harness.trail.record(about_another_tool)

    with pytest.raises(PermissionDeniedError, match="awaits approval for"):
        await harness.runner.resume(
            parked.state,
            STEP,
            confirmation_id="d-elsewhere",
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []
    assert harness.invoker.invocations == []


async def test_a_forged_parked_state_does_not_release_a_pending_step() -> None:
    """The parked check reads the store, because the graph cannot cover it.

    A stored ``PENDING`` step is claimable as ``PENDING → RUNNING`` (ADR-0014
    §4), so a ``state`` forged to read ``AWAITING_APPROVAL`` would be accepted by
    the transition it is heading for. Only the store settles it.
    """
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    first = await an_execution(harness.plans, step)
    parked = await harness.runner.run(first, STEP, timeout=PATIENT)
    second = await harness.plans.start_execution("p-1")
    forged = second.model_copy(
        update={
            "steps": (
                second.steps[0].model_copy(
                    update={"status": StepStatus.AWAITING_APPROVAL, "bound_tool": "smtp"}
                ),
            )
        }
    )

    with pytest.raises(PermissionDeniedError, match="not awaiting approval"):
        await harness.runner.resume(
            forged,
            STEP,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []
    assert harness.invoker.invocations == []
    reloaded = await harness.plans.get_execution(second.id)
    assert reloaded is not None
    assert reloaded.step(STEP) is not None
    assert reloaded.step(STEP).status is StepStatus.PENDING  # type: ignore[union-attr]  # asserted above


async def test_a_step_rewritten_mid_ruling_does_not_move_its_neighbour() -> None:
    """The stage reads its own snapshot, not the store's mutable object.

    ``PlanStore`` contracts no detached snapshot, so a conforming store may hand
    back the object it holds — and ``frozen=True`` does not stop
    ``__dict__`` (ADR-0018 §3).
    """
    leaky = LeakyPlanStore(now=lambda: AT)
    harness = Harness(
        tools=(tool(),), plans=leaky, policy=RewritingPolicy(leaky, becomes=NEIGHBOUR)
    )
    state = await a_two_step_execution(leaky)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.DENIED
    reloaded = await harness.plans.get_execution(state.id)
    assert reloaded is not None
    ruled_on = reloaded.step(STEP)
    untouched = reloaded.step(NEIGHBOUR)
    assert ruled_on is not None
    assert untouched is not None
    assert ruled_on.status is StepStatus.SKIPPED
    assert ruled_on.skip_reason is SkipReason.APPROVAL_DENIED
    assert untouched.status is StepStatus.PENDING
    assert untouched.approval_ref is None


async def test_a_state_repointed_mid_ruling_claims_the_execution_it_authenticated() -> None:
    """`run` claims the execution it read history from, not one `state` is moved to.

    `run` authenticates the stored execution through `_opened`, then — after the
    registry, the policy and the trail have awaited — commits and hands the
    executor a claim. `ExecutionState` is mutable (`frozen=True` is not set), so a
    caller sharing the object could repoint `state.id`/`state.version` to a
    *second* execution of the same plan, whose matching step is still `PENDING`
    and claimable at its own version, while a write is suspended. The private
    snapshot `run` takes on entry (`_detached_state`) is what keeps the claim on
    the authenticated execution.
    """
    plans = FakePlanStore(now=lambda: AT)
    step = plan_step()
    first = await an_execution(plans, step)  # execution A, authenticated below
    second = await plans.start_execution("p-1")  # execution B, same plan
    a_id = first.id

    def repoint() -> None:
        first.id = second.id
        first.version = second.version

    harness = Harness(tools=(tool(),), plans=plans, trail=RedirectingTrail(repoint))

    result = await harness.runner.run(first, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    ran = await plans.get_execution(a_id)
    other = await plans.get_execution(second.id)
    assert ran is not None
    assert other is not None
    ran_step = ran.step(STEP)
    other_step = other.step(STEP)
    assert ran_step is not None
    assert other_step is not None
    # A ran under the authority that authenticated it; B was never claimed.
    assert ran_step.status is StepStatus.SUCCEEDED
    assert other_step.status is StepStatus.PENDING
    assert len(harness.invoker.invocations) == 1


# --- the step comes from the plan (ADR-0037 §2) --------------------------


async def test_a_step_the_plan_does_not_hold_is_refused() -> None:
    """The runner disposes of planned steps, and of nothing else."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(PlanningError, match="has no step"):
        await harness.runner.run(state, "step-invented", timeout=PATIENT)

    assert harness.policy.requests == []
    assert harness.invoker.invocations == []
    assert await harness.trail.export() == []


async def test_a_state_naming_another_execution_s_plan_does_not_redirect_the_step() -> None:
    """The plan comes from the stored execution, not from the argument."""
    harness = Harness(tools=(tool(),))
    state = await a_two_step_execution(harness.plans)
    # A second plan, whose `step-1` does something else entirely, and a state
    # carrying this execution's id and version with that plan's id.
    await harness.plans.save_plan(
        ActionPlan(
            id="p-2",
            goal_id="g-1",
            steps=(plan_step(capability="delete_everything"),),
            created_at=AT,
        )
    )
    forged = state.model_copy(update={"plan_id": "p-2"})

    result = await harness.runner.run(forged, STEP, timeout=PATIENT)

    # Selection asked about the *stored* execution's capability, not "p-2"'s.
    assert result.disposition is Disposition.EXECUTED
    assert [request.tool.capability for request in harness.policy.requests] == [CAPABILITY]


async def test_an_execution_the_store_does_not_hold_runs_nothing() -> None:
    """A state naming no stored execution says nothing about any plan."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    invented = state.model_copy(update={"id": "execution-invented"})

    with pytest.raises(PlanningError, match="holds no execution"):
        await harness.runner.run(invented, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []


async def test_an_execution_whose_plan_is_gone_runs_nothing() -> None:
    """With no plan there is nothing that says what the step should do."""
    forgetful = ForgetfulPlanStore(now=lambda: AT)
    harness = Harness(tools=(tool(),), plans=forgetful)
    step = plan_step()
    state = await an_execution(forgetful, step)
    forgetful.forget_plans = True

    with pytest.raises(PlanningError, match="which the store does not hold"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []


# --- the read-back is of the decision that was asked for -----------------


async def test_a_trail_answering_under_the_wrong_id_is_refused() -> None:
    """A record that calls itself something else is not the one recorded."""
    harness = Harness(tools=(tool(),), trail=MislabelledTrail())
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="calls itself"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert harness.invoker.invocations == []
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


# --- every branch reads its decision back --------------------------------


async def test_a_lost_denial_is_refused_before_the_step_is_skipped() -> None:
    """A skipped step's ``approval_ref`` must point at something (ADR-0014 §4)."""
    harness = Harness(
        tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW), trail=LosingTrail()
    )
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="does not hold decision"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert stored.approval_ref is None


async def test_a_lost_confirmation_is_refused_before_the_step_is_parked() -> None:
    """Parking on an id nobody can resolve is a step that can never continue."""
    harness = Harness(tools=(confirmable(),), trail=LosingTrail())
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="does not hold decision"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


async def test_a_ruling_mutated_while_it_is_recorded_does_not_steer_the_outcome() -> None:
    """The branch reads the recorded ruling, not the policy's own object.

    ``frozen=True`` does not stop ``__dict__`` (ADR-0018 §3), and ``record`` is
    an await — so a policy that rewrote its answer mid-write would have an
    ``ALLOW`` recorded and a ``DENY`` committed against it.
    """
    policy = TurncoatPolicy()
    harness = Harness(tools=(tool(),), policy=policy, trail=TurncoatTrail(policy.defect))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.ALLOW
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SUCCEEDED
    assert stored.approval_ref == result.decision_id


async def test_a_denial_recorded_about_another_action_is_refused() -> None:
    """A skip's ``approval_ref`` must describe the step it is written on."""
    about_something_else = PermissionDecision.from_request(
        ActionRequest(tool=tool("other"), parameters={"to": "elsewhere@example.com"}, step_id=STEP),
        PermissionRuling(outcome=PermissionOutcome.DENY, reason="about something else"),
        id=FIRST_DECISION,
        decided_at=AT,
    )
    harness = Harness(
        tools=(tool(),),
        policy=FakeActionPolicy(deny_at=RiskLevel.LOW),
        trail=SubstitutingTrail(about_something_else),
    )
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="is not the decision that was recorded"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING
    assert stored.approval_ref is None


async def test_a_confirmation_recorded_about_another_action_is_refused() -> None:
    """Parking on a confirmation about another tool is a step nobody can answer."""
    about_something_else = PermissionDecision.from_request(
        ActionRequest(tool=tool("other"), parameters={"to": "elsewhere@example.com"}, step_id=STEP),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="about something else"),
        id=FIRST_DECISION,
        decided_at=AT,
    )
    harness = Harness(tools=(confirmable(),), trail=SubstitutingTrail(about_something_else))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(AuditError, match="is not the decision that was recorded"):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.PENDING


async def test_a_policy_cannot_swap_the_action_it_ruled_on() -> None:
    """A ruling carries no subject, and the request it saw is not the one bound.

    ADR-0021 §3 gave `PermissionRuling` no tool field so a policy could not
    substitute the subject. Handing `decide` the object that is then bound and
    executed would give that capability back through the request.
    """
    # Registered and invocable, but advertising a different capability, so
    # selection is unambiguous and the swap is the policy's own doing.
    swapped = tool("high-risk", capability="delete_everything", risk_level=RiskLevel.CRITICAL)
    harness = Harness(tools=(tool(), swapped), policy=SwappingPolicy(swapped))
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    assert result.tool_id == "smtp"
    assert [call.request.tool.id for call in harness.invoker.invocations] == ["smtp"]
    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert recorded.tool.id == "smtp"


async def test_a_request_rewritten_while_it_is_recorded_does_not_fail_the_turn() -> None:
    """The comparison is against what was written, over a private copy.

    A policy may keep the ``ActionRequest`` it was handed and rewrite it through
    ``__dict__`` during the trail's await. Nothing unsafe follows — the decision
    transcribed its subject first, so a mismatch fails closed — but failing here
    would refuse a good action *after* its decision is durable, leaving an
    un-erasable orphan in an append-only store (ADR-0021 §4).
    """
    policy = RetentivePolicy()
    harness = Harness(
        tools=(tool(),),
        policy=policy,
        trail=TurncoatTrail(lambda: policy.rewrite(tool("somebody-else"))),
    )
    step = plan_step()
    state = await an_execution(harness.plans, step)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EXECUTED
    assert result.tool_id == "smtp"
    recorded = await harness.trail.get(str(result.decision_id))
    assert recorded is not None
    assert recorded.tool.id == "smtp"
    stored = await stored_step(harness.plans, state)
    assert stored.status is StepStatus.SUCCEEDED


# --- run() only enters at PENDING (ADR-0037 §6) --------------------------


async def test_running_an_already_parked_step_records_no_orphan_decision() -> None:
    """Answering a parked step is ``resume``'s; ruling again is not an answer."""
    harness = Harness(tools=(confirmable(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    before = await harness.trail.export()

    with pytest.raises(PlanningError, match="already awaiting approval"):
        await harness.runner.run(parked.state, STEP, timeout=PATIENT)

    assert await harness.trail.export() == before
    assert len(harness.policy.requests) == 1


async def test_running_a_finished_step_is_refused() -> None:
    """A disposed step has nothing left for this stage to do."""
    harness = Harness(tools=(tool(),))
    step = plan_step()
    state = await an_execution(harness.plans, step)
    done = await harness.runner.run(state, STEP, timeout=PATIENT)
    before = await harness.trail.export()

    with pytest.raises(PlanningError, match="nothing here left to dispose of"):
        await harness.runner.run(done.state, STEP, timeout=PATIENT)

    assert await harness.trail.export() == before
    assert len(harness.invoker.invocations) == 1


# --- the clock -----------------------------------------------------------


async def test_a_naive_clock_reading_fails_the_stage_that_read_it() -> None:
    """ADR-0026 §4: `orchestration` has no error of its own, so the stage's stands."""
    harness = Harness(tools=(tool(),), now=lambda: datetime(2026, 7, 22, 9, 0))  # noqa: DTZ001
    step = plan_step()
    state = await an_execution(harness.plans, step)

    with pytest.raises(PlanningError):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert await harness.trail.export() == []
    assert harness.invoker.invocations == []
