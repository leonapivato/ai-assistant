"""The concrete Engine passes the shared AssistantEngine suite.

The other half of the pair ADR-0084 §4's substitutability clause needs: the
in-process engine and the canonical fake are held to *one* suite, so a clause
either binds both or binds neither.

The wiring below is the composition root's, in miniature — the same instances
shared where ADR-0028 §4 and ADR-0078 §3 say they must be (one memory store behind
the writer, the lifecycle stage and the observation stage; one deferral queue
behind the write stage and the question stage). It is written out here rather than
imported from ``test_engine``'s harness because that harness carries knobs for
that module's own cases; what a conformance binding needs is the smallest engine
that is really wired.

**The engine's lifecycle is driven here and never by the suite.** ``start`` and
``aclose`` are not on the Protocol (ADR-0083 §8), so the suite must not reach for
them; the fixture does, because *this* implementation owns durable connections and
the composition root would.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from assistant_engine_contract import _TINY_LIMIT, AssistantEngineContract

from ai_assistant.core.types import ActionPlan
from ai_assistant.orchestration import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    ConversationLifecycle,
    Engine,
    LearningLoop,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
)
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeObserver,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)
OBSERVATION_BATCH = 20
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"


class _NoStepPlanner:
    """A ``Planner`` that ends a turn at an empty plan.

    The conformance suite is about the *surface*, not about driving a tool: a turn
    with no step is a ratified shape (``TurnOutcome(step=None)``) and it keeps the
    binding free of a permission fixture it would otherwise have to carry.
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Return an empty plan for the goal."""
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)


def _wire(*, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> Engine:
    """Build one engine over in-memory fakes, wired as the composition root would."""
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    invoker = FakeToolInvoker([])
    memory = FakeMemoryStore(now=lambda: AT)
    conversation_store = FakeConversationStore(now=lambda: AT)
    conversations = ConversationLifecycle(
        conversations=conversation_store, memory=memory, retention=RETENTION, now=lambda: AT
    )
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    questions = QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT)
    observation = ObservationStage(
        observer=FakeObserver(),
        conversations=conversation_store,
        memory=memory,
        writes=writes,
        batch_size=OBSERVATION_BATCH,
        route=OBSERVER_ROUTE,
    )
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=writes,
        planner=_NoStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=lambda: "g-1",
    )
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=lambda: "d-1",
    )
    return Engine(
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        memory=memory,
        conversations=conversations,
        observation=observation,
        questions=questions,
        id_factory=lambda: "tok-1",
        max_payload_bytes=max_payload_bytes,
    )


class TestEngineContract(AssistantEngineContract):
    """The concrete engine, held to the shared contract."""

    @pytest.fixture
    async def engine(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine at the ordinary contract limit."""
        built = _wire()
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def tiny_engine(self) -> AsyncIterator[AssistantEngine]:
        """The same implementation, with the limit small enough to reach."""
        built = _wire(max_payload_bytes=_TINY_LIMIT)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()
