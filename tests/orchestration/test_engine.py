"""The engine façade an adapter drives (ADR-0042 §1, §3, §4).

What is exercised here is only what the façade *composes*: that one call runs a
turn and drives its step, that a parked confirmation comes back as
engine-assembled content plus an opaque token, that relaying the token resumes the
exact step, and that shutdown drains in-flight work before closing owned
resources. Every collaborator is a canonical fake from ``ai_assistant.testing`` or
one of this package's own stage objects, so nothing here imports a subsystem
concrete (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import (
    ContinuationToken,
    Disposition,
    Engine,
    StepExecutor,
    StepRunner,
    TurnOutcome,
)
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeContextProvider,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryKind, MemoryRecord

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)

CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright (mirrors test_runner)."""
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


class OneStepPlanner:
    """A ``Planner`` that plans exactly one step **for the goal it is given**.

    Building the plan from the passed goal is what keeps ``plan.goal_id`` equal to
    the id the loop minted, so the façade's ``save_plan`` finds its goal. Structurally
    implements :class:`~ai_assistant.core.protocols.Planner`.
    """

    def __init__(self, *, capability: str = CAPABILITY) -> None:
        self._capability = capability

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        step = PlanStep(
            id="step-1", intent="send the note", capability=self._capability, parameters=PARAMETERS
        )
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)


class NoStepPlanner:
    """A ``Planner`` that ends a turn at an empty plan."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)


class RaisingMemoryStore(FakeMemoryStore):
    """A store whose ``search`` fails, so the loop degrades retrieval."""

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        msg = "retrieval is down"
        raise MemoryStoreError(msg)


class Harness:
    """A wired :class:`Engine` and the fakes behind it, for assertions."""

    def __init__(  # noqa: PLR0913 — one knob per fake; that is what a harness is
        self,
        *,
        planner: object | None = None,
        tools: tuple[ToolDefinition, ...] = (),
        policy: FakeActionPolicy | None = None,
        memory: FakeMemoryStore | None = None,
        closers: Sequence[object] = (),
        loop_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.plans = FakePlanStore(now=lambda: AT)
        self.trail = FakeAuditTrail()
        # One object as both registry and invoker, as ADR-0029 §8 requires.
        self.invoker = FakeToolInvoker([(definition, _succeeds) for definition in tools])
        self.policy = policy if policy is not None else FakeActionPolicy()
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.handles = iter(f"tok-{n}" for n in range(1, 100))

        writer = FakeMemoryWriter(store=self.memory, policy=FakeMemoryPolicy(), now=lambda: AT)
        loop = LearningLoop(
            context=FakeContextProvider(),
            memory=self.memory,
            writer=writer,
            planner=planner if planner is not None else OneStepPlanner(),  # type: ignore[arg-type]
            feedback=FakeFeedbackProcessor(),
            now=lambda: AT,
            id_factory=loop_id_factory if loop_id_factory is not None else lambda: "g-1",
        )
        runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            now=lambda: AT,
            id_factory=lambda: next(self.ids),
        )
        self.engine = Engine(
            loop=loop,
            runner=runner,
            plans=self.plans,
            trail=self.trail,
            closers=tuple(closers),  # type: ignore[arg-type]
            id_factory=lambda: next(self.handles),
        )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


# --- one call in, one result out (ADR-0042 §3) --------------------------


async def test_converse_with_no_step_ends_at_the_plan() -> None:
    """A turn whose plan has no step returns the plan and drives nothing."""
    harness = Harness(planner=NoStepPlanner())
    outcome = await harness.engine.converse("hello", timeout=PATIENT)
    assert isinstance(outcome, TurnOutcome)
    assert outcome.step is None
    assert outcome.turn is not None  # a converse always carries its turn
    assert outcome.turn.plan.steps == ()
    assert outcome.turn.memory_degraded is False
    # A no-action decision is still a decision: its goal and plan are persisted as
    # an auditable record even though there is nothing to drive.
    assert await harness.plans.get_goal(outcome.turn.goal.id) is not None
    assert await harness.plans.get_plan(outcome.turn.plan.id) is not None


async def test_converse_refuses_a_plan_built_for_another_goal() -> None:
    """A plan whose goal_id is not the turn's goal is refused before it is driven."""

    class MismatchPlanner:
        """Returns a plan pointing at a different goal than the one it was given."""

        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            step = PlanStep(id="step-1", intent="x", capability=CAPABILITY, parameters=PARAMETERS)
            return ActionPlan(
                id="rogue-plan", goal_id="some-other-goal", steps=(step,), created_at=AT
            )

    harness = Harness(planner=MismatchPlanner(), tools=(tool(),))
    with pytest.raises(PlanningError, match="different objective"):
        await harness.engine.converse("send it", timeout=PATIENT)
    # Nothing was persisted or driven for the mismatched plan.
    assert await harness.plans.get_plan("rogue-plan") is None


async def test_converse_drives_the_first_step_and_executes_it() -> None:
    """An allowed step is run; the outcome carries its executed disposition."""
    harness = Harness(tools=(tool(),))
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    assert outcome.step.tool_id == "smtp"
    assert outcome.step.confirmation is None
    assert outcome.step.state.step("step-1") is not None
    assert outcome.step.state.step("step-1").status is StepStatus.SUCCEEDED  # type: ignore[union-attr]


async def test_converse_surfaces_degraded_memory() -> None:
    """A retrieval failure is reported on the outcome, not swallowed (§3)."""
    harness = Harness(tools=(tool(),), memory=RaisingMemoryStore(now=lambda: AT))
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.turn is not None
    assert outcome.turn.memory_degraded is True


async def test_converse_with_no_capable_tool_reports_it() -> None:
    """Nothing advertises the capability: the step is skipped, not an error."""
    harness = Harness(tools=())
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.NO_CAPABLE_TOOL
    assert outcome.step.confirmation is None


async def test_converse_with_a_denying_policy_reports_denied() -> None:
    """A policy refusal comes back as DENIED with no confirmation."""
    harness = Harness(tools=(tool(),), policy=FakeActionPolicy(deny_at=RiskLevel.LOW))
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.DENIED
    assert outcome.step.confirmation is None


# --- the confirmation round trip (ADR-0042 §4) --------------------------


async def test_a_parked_step_returns_engine_assembled_confirmation_content() -> None:
    """The façade assembles tool content and the ruling reason (§4)."""
    harness = Harness(tools=(confirmable(),))
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    confirmation = outcome.step.confirmation
    assert confirmation is not None
    assert confirmation.tool_id == "smtp"
    assert confirmation.tool_description == "Send an email."
    # Parameters are carried as data, verbatim, for the adapter to escape.
    assert dict(confirmation.parameters) == PARAMETERS
    # The reason is the recorded CONFIRM ruling's own reason, not invented here.
    recorded = await harness.trail.get("d-1")
    assert recorded is not None
    assert confirmation.reason == recorded.ruling.reason
    assert isinstance(confirmation.token, ContinuationToken)


async def test_resume_approved_executes_the_parked_step() -> None:
    """Relaying the token with approval runs the step (§4)."""
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    token = parked.step.confirmation.token  # type: ignore[union-attr]

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.step.state.step("step-1").status is StepStatus.SUCCEEDED  # type: ignore[union-attr]
    # The resumed turn carries the parked turn's own plan (in-process resume).
    assert resumed.turn is not None
    assert parked.turn is not None
    assert resumed.turn.plan == parked.turn.plan


async def test_resume_refused_denies_the_parked_step() -> None:
    """approved=False is a decision that yields DENY (§4)."""
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    token = parked.step.confirmation.token  # type: ignore[union-attr]

    resumed = await harness.engine.resume(token, approved=False, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.DENIED


async def test_a_token_resolves_once_then_is_unknown() -> None:
    """A resolved token is evicted; replaying it is a clean refusal (§4)."""
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    token = parked.step.confirmation.token  # type: ignore[union-attr]

    await harness.engine.resume(token, approved=True, timeout=PATIENT)
    with pytest.raises(PlanningError, match="no step awaiting confirmation"):
        await harness.engine.resume(token, approved=True, timeout=PATIENT)


async def test_resume_with_an_unrecognised_token_is_refused() -> None:
    """A token this engine never minted names no parked step (§4 lifetime)."""
    harness = Harness(tools=(confirmable(),))
    with pytest.raises(PlanningError, match="no step awaiting confirmation"):
        await harness.engine.resume(ContinuationToken("fabricated"), approved=True, timeout=PATIENT)


async def test_the_token_is_opaque_process_scoped_state() -> None:
    """A fresh engine does not honour another engine's token (process-scoped)."""
    first = Harness(tools=(confirmable(),))
    parked = await first.engine.converse("send it", timeout=PATIENT)
    token = parked.step.confirmation.token  # type: ignore[union-attr]

    second = Harness(tools=(confirmable(),))
    with pytest.raises(PlanningError):
        await second.engine.resume(token, approved=True, timeout=PATIENT)


# --- durable recovery of a parked confirmation (ADR-0052) ---------------


def _fresh_facade(harness: Harness) -> Engine:
    """A new ``Engine`` over ``harness``'s durable state, with an empty in-process table.

    The fakes are the same instances, so plan/execution state and the audit trail
    persist — this stands in for a restarted process whose ``_parked`` table starts
    empty (ADR-0052 §1). It reuses the harness's stage objects, which already hold
    the same ``plans`` and ``trail``.
    """
    return Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        id_factory=lambda: next(harness.handles),
    )


async def test_pending_confirmations_is_empty_when_nothing_is_parked() -> None:
    """A turn that executed outright leaves nothing awaiting an answer (ADR-0052 §1)."""
    harness = Harness(tools=(tool(),))
    executed = await harness.engine.converse("send it", timeout=PATIENT)
    assert executed.step is not None
    assert executed.step.disposition is Disposition.EXECUTED
    assert await harness.engine.pending_confirmations() == []


async def test_pending_confirmations_recovers_a_park_for_a_fresh_facade() -> None:
    """A durably-parked step is recoverable via a fresh façade — the #287 fix (ADR-0052)."""
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    original = parked.step.confirmation
    assert original is not None

    # A fresh façade over the same durable state has no in-process token at all.
    fresh = _fresh_facade(harness)
    assert fresh._parked == {}

    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    recovered = pending[0]
    # The content is reconstructed from durable state: tool and reason from the
    # recorded CONFIRM, parameters from the plan step.
    assert recovered.tool_id == "smtp"
    assert recovered.tool_description == "Send an email."
    assert dict(recovered.parameters) == PARAMETERS
    assert recovered.reason == original.reason

    resumed = await fresh.resume(recovered.token, approved=True, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    # A recovered resume has no live turn — context and memories were never persisted.
    assert resumed.turn is None
    assert resumed.step.state.step("step-1").status is StepStatus.SUCCEEDED  # type: ignore[union-attr]


async def test_pending_confirmations_is_idempotent_and_bounded() -> None:
    """Repeated recovery yields stable tokens and mints no duplicate entry (ADR-0052 §2)."""
    harness = Harness(tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)
    fresh = _fresh_facade(harness)

    first = await fresh.pending_confirmations()
    second = await fresh.pending_confirmations()
    assert [c.token for c in first] == [c.token for c in second]  # stable tokens
    assert len(fresh._parked) == 1  # the same binding is reused, not re-minted


async def test_a_recovered_confirmation_resolved_is_no_longer_presented() -> None:
    """Once answered, a recovered park is not re-presented (ADR-0044 §2b via ADR-0052)."""
    harness = Harness(tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)
    fresh = _fresh_facade(harness)

    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    denied = await fresh.resume(pending[0].token, approved=False, timeout=PATIENT)
    assert denied.step is not None
    assert denied.step.disposition is Disposition.DENIED

    # The binding is decided; recovery presents nothing further.
    assert await fresh.pending_confirmations() == []


async def test_pending_confirmations_recovers_a_dropped_in_process_token() -> None:
    """A park whose token was dropped in the *same* process is still recoverable (#287)."""
    harness = Harness(tools=(confirmable(),))
    outcome = await harness.engine.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    # Simulate the token being lost/dropped before it reached the adapter: clear the
    # engine's own table. The step is still durably parked in the plan store.
    harness.engine._parked.clear()

    pending = await harness.engine.pending_confirmations()
    assert len(pending) == 1
    resumed = await harness.engine.resume(pending[0].token, approved=True, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED


async def test_a_recovered_entry_does_not_count_toward_the_confirmation_ceiling() -> None:
    """A recovered park applies no backpressure: only turn-carrying parks count (§2).

    Were recovered entries counted, a durably-parked step — or one resolved by
    another engine that left a stale entry — would block new turns forever. With a
    ceiling of one, a recovered entry present, a fresh turn is still admitted; the
    ceiling bites only once a *turn-carrying* park exists.
    """
    harness = Harness(tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)  # park one durably (g-1)

    goals = iter(f"g-{n}" for n in range(2, 100))
    harness.engine._loop._id_factory = lambda: next(goals)  # fresh goal ids for new turns
    facade = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        id_factory=lambda: next(harness.handles),
        max_outstanding_confirmations=1,
    )
    pending = await facade.pending_confirmations()
    assert len(pending) == 1
    assert len(facade._parked) == 1  # a recovered entry (turn is None) is registered

    # The recovered entry does not count: a fresh turn is admitted under the ceiling.
    outcome = await facade.converse("send it", timeout=PATIENT)
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION

    # Now a turn-carrying park exists, so the ceiling of one bites.
    with pytest.raises(RuntimeError, match="awaiting an answer"):
        await facade.converse("send it", timeout=PATIENT)


async def test_a_recovered_entry_resolved_elsewhere_is_pruned() -> None:
    """A recovered park resolved by another façade is pruned on the next recovery (§2)."""
    harness = Harness(tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)

    facade_a = _fresh_facade(harness)
    await facade_a.pending_confirmations()
    assert len(facade_a._parked) == 1  # A holds a recovered entry

    # Façade B, over the same durable stores, resolves the binding out from under A.
    facade_b = _fresh_facade(harness)
    b_pending = await facade_b.pending_confirmations()
    await facade_b.resume(b_pending[0].token, approved=True, timeout=PATIENT)

    # A recovers again: nothing pending now, and A's stale entry is pruned.
    assert await facade_a.pending_confirmations() == []
    assert facade_a._parked == {}


async def test_pending_confirmations_is_drained_before_shutdown_closes_resources() -> None:
    """Recovery is a tracked operation, so ``aclose`` awaits it before closing (§2).

    Recovery reads the plan store and the audit trail; were it untracked, ``aclose``
    could close those connections while it was still mid-read. Gating the store read
    lets us start ``aclose`` while recovery is suspended and observe that shutdown
    waits for the tracked recovery to finish.
    """
    harness = Harness(tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)
    fresh = _fresh_facade(harness)

    entered = asyncio.Event()
    release = asyncio.Event()

    class _GatedPlans:
        """Wraps the real store, suspending the first ``active_executions`` read."""

        def __init__(self, inner: object) -> None:
            self._inner = inner

        async def active_executions(self) -> object:
            entered.set()
            await release.wait()
            return await self._inner.active_executions()  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    fresh._plans = _GatedPlans(harness.plans)  # type: ignore[assignment]  # test double

    recovering = asyncio.ensure_future(fresh.pending_confirmations())
    await entered.wait()  # recovery is now suspended mid-read

    closing = asyncio.ensure_future(fresh.aclose())
    await asyncio.sleep(0)  # give aclose a chance to (wrongly) proceed
    assert not closing.done()  # it must be waiting for the tracked recovery to drain

    release.set()
    recovered = await recovering
    assert len(recovered) == 1  # the still-parked confirmation was recovered
    await closing  # shutdown completes only after the drain


async def test_concurrent_recovery_does_not_prune_another_calls_returned_token() -> None:
    """Overlapping recoveries are serialized, so one's prune cannot strand another's token.

    Without serialization, a recovery that enumerated a stale snapshot could prune a
    binding a concurrent recovery had just registered and returned, making that token
    unresumable (round 2 review). One engine, two overlapping ``pending_confirmations``
    calls, with a second execution parked in between: both returned tokens must remain
    resumable (ADR-0052 §2).
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    harness = Harness(tools=(confirmable(),), loop_id_factory=lambda: next(goals))
    await harness.engine.converse("send it", timeout=PATIENT)  # park execution 1 (g-1)

    # Façade A's plan store gates its first get_plan so call A suspends mid-enumeration,
    # after it has snapshotted active_executions but before it reconciles.
    entered = asyncio.Event()
    release = asyncio.Event()

    class _GateFirstGetPlan:
        def __init__(self, inner: object) -> None:
            self._inner = inner
            self._gated = False

        async def get_plan(self, plan_id: str) -> object:
            if not self._gated:
                self._gated = True
                entered.set()
                await release.wait()
            return await self._inner.get_plan(plan_id)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    facade = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        id_factory=lambda: next(harness.handles),
    )
    facade._plans = _GateFirstGetPlan(harness.plans)  # type: ignore[assignment]  # test double

    call_a = asyncio.ensure_future(facade.pending_confirmations())
    await entered.wait()  # A holds the recovery lock, suspended in get_plan

    # A second execution is parked durably while A is suspended (another façade, same stores).
    parker = _fresh_facade(harness)
    await parker.converse("send it", timeout=PATIENT)  # park execution 2 (g-2)

    # Call B on the *same* façade. It must wait for A's critical section, not interleave.
    call_b = asyncio.ensure_future(facade.pending_confirmations())
    await asyncio.sleep(0)
    assert not call_b.done()  # serialized behind A's held recovery lock

    release.set()
    a_result = await call_a
    b_result = await call_b
    # B ran after A and saw both parked executions; A saw only the first.
    assert len(a_result) == 1
    assert len(b_result) == 2

    # Every token B returned is still resumable — none was pruned by A's older snapshot.
    for confirmation in b_result:
        resumed = await facade.resume(confirmation.token, approved=True, timeout=PATIENT)
        assert resumed.step is not None
        assert resumed.step.disposition is Disposition.EXECUTED


async def test_aclose_closes_owned_resources_in_order() -> None:
    """The façade releases every resource, in the order it was handed them."""
    order: list[str] = []

    async def close_a() -> None:
        order.append("a")

    async def close_b() -> None:
        order.append("b")

    harness = Harness(tools=(tool(),), closers=(close_a, close_b))
    await harness.engine.converse("send it", timeout=PATIENT)
    await harness.engine.aclose()
    assert order == ["a", "b"]


async def test_aclose_is_idempotent() -> None:
    """A second close drains nothing and closes nothing again."""
    calls: list[str] = []

    async def close() -> None:
        calls.append("closed")

    harness = Harness(closers=(close,))
    await harness.engine.aclose()
    await harness.engine.aclose()
    assert calls == ["closed"]


async def test_calls_are_refused_once_shutdown_has_begun() -> None:
    """After aclose no new work is accepted (§2 stops accepting)."""
    harness = Harness(tools=(tool(),))
    await harness.engine.aclose()
    with pytest.raises(RuntimeError, match="shutting down"):
        await harness.engine.converse("send it", timeout=PATIENT)


async def test_shutdown_drains_in_flight_work_before_closing() -> None:
    """Closing waits for a running call to quiesce before it closes resources."""
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    closed_while_inflight = False

    class GatedPlanner:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            entered.set()
            await release.wait()
            step = PlanStep(id="step-1", intent="x", capability=CAPABILITY, parameters=PARAMETERS)
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)

    async def close() -> None:
        nonlocal closed_while_inflight
        closed_while_inflight = not release.is_set()
        closed.set()

    harness = Harness(tools=(tool(),), planner=GatedPlanner(), closers=(close,))
    call = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    await entered.wait()

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)  # let aclose reach its drain
    assert not closed.is_set()  # the resource is not closed while work is in flight

    release.set()
    await call
    await closing
    assert closed.is_set()
    assert closed_while_inflight is False


async def test_a_cancelled_call_does_not_abandon_its_underlying_work() -> None:
    """Cancelling converse leaves the tracked work running for the drain (§2)."""
    entered = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    class GatedPlanner:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            entered.set()
            await release.wait()
            finished.set()
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)

    harness = Harness(planner=GatedPlanner())
    call = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    await entered.wait()

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert not finished.is_set()  # the underlying work is not cancelled with the caller

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    release.set()
    await closing
    assert finished.is_set()  # the drain waited for the orphaned work to quiesce


async def test_cancelling_aclose_still_closes_the_resources() -> None:
    """A cancelled aclose does not leave connections open (§2 ownership).

    The drain-and-close is one memoised task every caller awaits shielded, so
    cancelling *this* caller cannot abandon the closures: the task runs on, and a
    later aclose awaits the same task rather than returning over unclosed
    resources.
    """
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()

    class GatedPlanner:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            entered.set()
            await release.wait()
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)

    async def close() -> None:
        closed.set()

    harness = Harness(planner=GatedPlanner(), closers=(close,))
    call = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    await entered.wait()

    # First aclose blocks on the drain; cancel it while it waits.
    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert not closed.is_set()  # nothing closed yet — the drain is still waiting

    # The shutdown task survives the cancellation; letting work finish and awaiting
    # aclose again completes the closures exactly once.
    release.set()
    await call
    await harness.engine.aclose()
    assert closed.is_set()


async def test_a_colliding_handle_factory_still_yields_distinct_tokens() -> None:
    """Handle uniqueness is the engine's invariant, so consent never rebinds (§4).

    A factory that repeats a handle must not overwrite one parked step with
    another (which would resume the wrong action), nor strand the second step by
    refusing it — the engine disambiguates to a unique handle instead.
    """

    class CollidingFactory:
        """Always mints the same handle."""

        def __call__(self) -> str:
            return "same"

    harness = Harness(tools=(confirmable(),))
    harness.engine._id_factory = CollidingFactory()

    # Same utterance both turns, so the fixed-id goal/plan re-save idempotently and
    # each turn parks its own execution.
    first = await harness.engine.converse("send it", timeout=PATIENT)
    second = await harness.engine.converse("send it", timeout=PATIENT)
    token_one = first.step.confirmation.token  # type: ignore[union-attr]
    token_two = second.step.confirmation.token  # type: ignore[union-attr]
    assert token_one != token_two  # distinct despite the colliding factory

    # The first token resolves the first execution, not the second — no rebind.
    first_execution = first.step.state.id  # type: ignore[union-attr]
    resumed = await harness.engine.resume(token_one, approved=True, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.state.id == first_execution
    # The second token is still answerable on its own execution.
    resumed_two = await harness.engine.resume(token_two, approved=True, timeout=PATIENT)
    assert resumed_two.step is not None
    assert resumed_two.step.state.id == second.step.state.id  # type: ignore[union-attr]


async def test_a_raising_handle_factory_fails_before_any_step_is_parked() -> None:
    """The handle is minted before the runner parks, so no step is stranded (§4, #287)."""

    def boom() -> str:
        msg = "the id factory is broken"
        raise RuntimeError(msg)

    harness = Harness(tools=(confirmable(),))
    harness.engine._id_factory = boom

    with pytest.raises(RuntimeError, match="id factory is broken"):
        await harness.engine.converse("send it", timeout=PATIENT)
    # No step was left durably parked: the mint failed before `run` could commit
    # AWAITING_APPROVAL, so nothing awaits an answer that can never be supplied.
    # (The execution exists with its step still PENDING, which is undriven work,
    # not a parked confirmation.)
    executions = await harness.plans.active_executions()
    assert all(
        step.status is not StepStatus.AWAITING_APPROVAL
        for execution in executions
        for step in execution.steps
    )


async def test_concurrent_parks_get_distinct_tokens_despite_a_colliding_factory() -> None:
    """Two turns parking at once never share a handle (atomic reservation, §4).

    Same utterance both turns, so the fixed-id goal/plan re-save idempotently, but
    each ``start_execution`` opens a *distinct* execution — so the two parks are
    genuinely different steps that must not collide onto one token.
    """

    class CollidingFactory:
        def __call__(self) -> str:
            return "same"

    entered = asyncio.Event()
    release = asyncio.Event()
    seen = 0

    class GatedConfirmPlanner:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            nonlocal seen
            seen += 1
            if seen == 2:  # both turns are now in flight together
                entered.set()
            await release.wait()
            step = PlanStep(id="step-1", intent="x", capability=CAPABILITY, parameters=PARAMETERS)
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)

    harness = Harness(tools=(confirmable(),), planner=GatedConfirmPlanner())
    harness.engine._id_factory = CollidingFactory()

    first = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    second = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    await entered.wait()
    release.set()
    out_one, out_two = await first, await second

    token_one = out_one.step.confirmation.token  # type: ignore[union-attr]
    token_two = out_two.step.confirmation.token  # type: ignore[union-attr]
    assert token_one != token_two  # atomic reservation kept them apart
    # Each token still resolves its own execution, not the other's.
    r1 = await harness.engine.resume(token_one, approved=True, timeout=PATIENT)
    r2 = await harness.engine.resume(token_two, approved=True, timeout=PATIENT)
    assert r1.step.state.id != r2.step.state.id  # type: ignore[union-attr]


async def test_outstanding_confirmations_apply_backpressure_without_stranding() -> None:
    """At the ceiling the engine refuses new work rather than dropping a live token (§4)."""
    goals = iter(f"g-{n}" for n in range(1, 100))
    harness = Harness(tools=(confirmable(),), loop_id_factory=lambda: next(goals))
    engine = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        id_factory=lambda: next(harness.handles),
        max_outstanding_confirmations=2,  # tighten for the test
    )

    first = await engine.converse("send it", timeout=PATIENT)
    second = await engine.converse("send it", timeout=PATIENT)
    assert len(engine._parked) == 2  # at the ceiling

    # A third action is refused — backpressure — and nothing new is parked, and no
    # durable goal/plan is written for the refused turn (round 8: admission precedes
    # persistence). The refused turn's goal would have been "g-3".
    with pytest.raises(RuntimeError, match="awaiting an answer"):
        await engine.converse("send it", timeout=PATIENT)
    assert len(engine._parked) == 2
    assert await harness.plans.get_goal("g-3") is None
    assert await harness.plans.get_plan("g-3-plan") is None

    # Both outstanding confirmations are still answerable — nothing was stranded.
    a = await engine.resume(first.step.confirmation.token, approved=True, timeout=PATIENT)  # type: ignore[union-attr]
    assert a.step is not None
    # With one resolved, there is room to start another action again.
    third = await engine.converse("send it", timeout=PATIENT)
    assert third.step is not None
    assert third.step.disposition is Disposition.AWAITING_CONFIRMATION
    b = await engine.resume(second.step.confirmation.token, approved=True, timeout=PATIENT)  # type: ignore[union-attr]
    assert b.step is not None


async def test_the_confirmation_ceiling_is_a_hard_bound_under_concurrency() -> None:
    """Concurrent admissions cannot exceed the ceiling: reserved slots count (§4)."""
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = 0

    class GatedConfirmPlanner:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            nonlocal seen
            seen += 1
            if seen == 3:  # all three turns are in flight together
                entered.set()
            await release.wait()
            step = PlanStep(id="step-1", intent="x", capability=CAPABILITY, parameters=PARAMETERS)
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)

    goals = iter(f"g-{n}" for n in range(1, 100))
    harness = Harness(
        tools=(confirmable(),), planner=GatedConfirmPlanner(), loop_id_factory=lambda: next(goals)
    )
    engine = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        id_factory=lambda: next(harness.handles),
        max_outstanding_confirmations=2,  # ceiling of two, three concurrent turns
    )

    calls = [asyncio.ensure_future(engine.converse("send it", timeout=PATIENT)) for _ in range(3)]
    await entered.wait()
    release.set()
    results = await asyncio.gather(*calls, return_exceptions=True)

    parked = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, RuntimeError)]
    assert len(parked) == 2  # exactly the ceiling parked
    assert len(refused) == 1  # the third was refused, not admitted
    assert len(engine._parked) == 2  # never exceeded the hard bound


async def test_a_non_positive_confirmation_ceiling_is_refused() -> None:
    """The ceiling must be positive — zero would refuse to drive any step at all."""
    harness = Harness()
    with pytest.raises(ValueError, match="must be positive"):
        Engine(
            loop=harness.engine._loop,
            runner=harness.engine._runner,
            plans=harness.plans,
            trail=harness.trail,
            max_outstanding_confirmations=0,
        )


@pytest.mark.parametrize("bad", [True, 1.5, "2"])
async def test_a_non_integer_confirmation_ceiling_is_refused(bad: object) -> None:
    """A bool, float or string ceiling is a TypeError, not a surprising limit."""
    harness = Harness()
    with pytest.raises(TypeError, match="must be an integer"):
        Engine(
            loop=harness.engine._loop,
            runner=harness.engine._runner,
            plans=harness.plans,
            trail=harness.trail,
            max_outstanding_confirmations=bad,  # type: ignore[arg-type]  # the point of the test
        )


async def test_aclose_attempts_every_closer_even_when_one_fails() -> None:
    """A raising closer must not skip the resources after it (§2 releases every one)."""
    closed: list[str] = []

    async def close_a() -> None:
        closed.append("a")
        msg = "resource a would not close"
        raise RuntimeError(msg)

    async def close_b() -> None:
        closed.append("b")

    harness = Harness(tools=(tool(),), closers=(close_a, close_b))
    await harness.engine.converse("send it", timeout=PATIENT)
    with pytest.raises(ExceptionGroup):
        await harness.engine.aclose()
    assert closed == ["a", "b"]  # b was closed despite a failing first


async def test_aclose_sweeps_remaining_closers_when_one_is_cancelled() -> None:
    """A cancelled closer still lets the rest release, then propagates (§2)."""
    closed: list[str] = []

    async def close_a() -> None:
        closed.append("a")
        raise asyncio.CancelledError

    async def close_b() -> None:
        closed.append("b")

    harness = Harness(closers=(close_a, close_b))
    with pytest.raises(asyncio.CancelledError):
        await harness.engine.aclose()
    assert closed == ["a", "b"]  # b released despite a's cancellation
