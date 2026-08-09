"""A durably-parked confirmation survives a process restart, end to end (ADR-0052).

Unlike ``test_engine.py`` — which drives the façade over canonical in-memory fakes
— this module wires the façade over the **real** connection-owning durable stores
(:class:`SqlitePlanStore`, :class:`SqliteAuditTrail`) and reopens them against the
*same database files* to simulate a restart. That is the proof #287/#318 need: a
confirmation parked by one engine, whose process then exits, is recovered and
resolved by a second engine reading the same files, and the resolution is itself
durable.

The model-facing loop is still a fake (no network): what is under test is durable
recovery of a parked step, not planning. Everything below the façade that touches
the databases — the runner, the executor, the audit trail — is real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING
from uuid import uuid4

from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Disposition,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    SkipReason,
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import (
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
)
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.permissions import SqliteAuditTrail
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeObserver,
    FakeSourceGrantStore,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _grant_ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _grant_operations(sources: Sequence[HeldSource] = ()) -> GrantOperations:
    """The grant collaborator every ``Engine`` needs (ADR-0102 §7).

    Required rather than optional on the façade, like ``questions`` and
    ``observation``: the four grant methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


PATIENT = timedelta(seconds=30)
CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


def _confirmable_tool() -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` confirms: it discloses off-device."""
    return ToolDefinition(
        id="smtp",
        capability=CAPABILITY,
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


class _OneStepPlanner:
    """Plans exactly one confirmable step for the goal it is given."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        step = PlanStep(
            id="step-1", intent="send the note", capability=CAPABILITY, parameters=PARAMETERS
        )
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def _aclose(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    async def _run() -> None:
        close()

    return _run


def _make_engine(
    plans: SqlitePlanStore, trail: SqliteAuditTrail, conversations: FakeConversationStore
) -> Engine:
    """Wire a façade over the given *real* durable stores (fake loop, real runner).

    ``conversations`` is passed in rather than built here, because these cases stand
    in for a *restart* over the same durable state: a resumption recovers its
    conversation from the binding the parking turn recorded (ADR-0074 §3), so the
    second process has to be looking at the index the first one wrote.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=writes,
        planner=_OneStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=lambda: "g-1",
    )
    invoker = FakeToolInvoker([(_confirmable_tool(), _succeeds)])
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        # Unique decision ids, as production does (uuid): a second process must not
        # re-mint the id the first recorded, or the durable trail rejects the
        # resolving decision as a duplicate.
        id_factory=lambda: uuid4().hex,
    )
    return Engine(
        grant_operations=_grant_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        memory=memory,
        deferrals=deferrals,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). This module
        # is about a *restarted* façade recovering a durable park, and nothing here
        # sweeps; a fresh fake per engine is therefore right — the trace store is
        # not part of the durable state the second process re-reads.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
        observation=ObservationStage(
            observer=FakeObserver(),
            conversations=conversations,
            memory=memory,
            writes=writes,
            batch_size=20,
            route="anthropic:claude-opus-4-8",
        ),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
        closers=[_aclose(plans.close), _aclose(trail.close)],
    )


async def test_a_parked_confirmation_survives_a_restart_and_resolves_durably(
    tmp_path: Path,
) -> None:
    """ask → park → exit → restart → resume → executed, all against the same files."""
    plans_path = tmp_path / "plans.db"
    audit_path = tmp_path / "audit.db"
    # One conversation index across both "processes": the resumption finds its
    # conversation through the binding the parking turn wrote there (ADR-0074 §3),
    # so a second engine that could not see it would capture nothing.
    conversations = FakeConversationStore(now=lambda: AT)

    # --- first process: park a confirmation, then "exit" (close the connections) ---
    engine1 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    parked = await engine1.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    execution_id = parked.step.state.id
    await engine1.aclose()  # closes both sqlite connections — the process is gone

    # --- restart: a brand-new engine over the same database files ---
    engine2 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    try:
        assert engine2._parked == {}  # nothing carried over in memory
        pending = await engine2.pending_confirmations()
        assert len(pending) == 1
        recovered = pending[0]
        assert recovered.tool_id == "smtp"
        assert dict(recovered.parameters) == PARAMETERS

        resumed = await engine2.resume(recovered.token, approved=True, timeout=PATIENT)
        assert resumed.step is not None
        assert resumed.step.disposition is Disposition.EXECUTED
        assert resumed.turn is None  # recovered resume: no live turn
    finally:
        await engine2.aclose()

    # --- a third reopen proves the resolution was durable, not engine2's memory ---
    plans3 = SqlitePlanStore(path=plans_path)
    try:
        state = await plans3.get_execution(execution_id)
        assert state is not None
        step = state.step("step-1")
        assert step is not None
        assert step.status is StepStatus.SUCCEEDED
        assert await plans3.active_executions() == []  # nothing left parked
    finally:
        plans3.close()


async def test_a_recovered_confirmation_can_be_denied_across_a_restart(tmp_path: Path) -> None:
    """The restart path resolves a refusal too, durably (ADR-0052 §3)."""
    plans_path = tmp_path / "plans.db"
    audit_path = tmp_path / "audit.db"
    # One conversation index across both "processes": the resumption finds its
    # conversation through the binding the parking turn wrote there (ADR-0074 §3),
    # so a second engine that could not see it would capture nothing.
    conversations = FakeConversationStore(now=lambda: AT)

    engine1 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    parked = await engine1.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    execution_id = parked.step.state.id
    await engine1.aclose()

    engine2 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    try:
        pending = await engine2.pending_confirmations()
        assert len(pending) == 1
        denied = await engine2.resume(pending[0].token, approved=False, timeout=PATIENT)
        assert denied.step is not None
        assert denied.step.disposition is Disposition.DENIED
    finally:
        await engine2.aclose()

    plans3 = SqlitePlanStore(path=plans_path)
    try:
        state = await plans3.get_execution(execution_id)
        assert state is not None
        step = state.step("step-1")
        assert step is not None
        # A refused confirmation resolves the step to SKIPPED/APPROVAL_DENIED.
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
    finally:
        plans3.close()
