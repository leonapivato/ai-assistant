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
from itertools import count
from typing import TYPE_CHECKING

import pytest
from assistant_engine_contract import _TINY_LIMIT, AssistantEngineContract

from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Disposition,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
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
    from collections.abc import AsyncIterator, Callable, Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)
OBSERVATION_BATCH = 20
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"


CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


def _confirmable() -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` rules ``CONFIRM`` on.

    It discloses personal data off-device, which is ADR-0021 §5's floor: a
    disclosure is confirmed whatever the risk level says. Using the policy's own
    rule rather than a scripted ruling is what makes the parked subject a *real*
    park — the disposition comes from the permission stage, not from the fixture.
    """
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
    """A ``Planner`` that plans exactly one step **for the goal it is given**.

    Building the plan from the passed goal is what keeps ``plan.goal_id`` equal to
    the id the loop minted, so the façade's ``save_plan`` finds its goal.
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Return a one-step plan for the goal."""
        step = PlanStep(
            id="step-1", intent="send the note", capability=CAPABILITY, parameters=PARAMETERS
        )
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)


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


def _counter(prefix: str) -> Callable[[], str]:
    """Ids that differ per call.

    A fixed factory would make a second turn reuse the first turn's goal id with a
    different statement, which the plan store refuses on purpose: rewriting a goal's
    identity would make every plan already recorded against it describe an objective
    the user never set.
    """
    numbers = count(1)
    return lambda: f"{prefix}-{next(numbers)}"


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def _wire(*, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES, parks: bool = False) -> Engine:
    """Build one engine over in-memory fakes, wired as the composition root would.

    ``parks`` swaps in a one-step plan over a tool the policy confirms, which is
    the only way to reach the resume path: parking is the permission stage's
    ruling and no call on the surface asks for it.
    """
    # **The conversation store's clock advances**, because ADR-0074 §2's sort key
    # is activity and a frozen clock cannot express "more recently active" at all —
    # every conversation would stamp the same instant and the id tie-break would
    # decide the listing. The other stores keep the fixed instant: nothing else here
    # is about ordering in time.
    ticks = count(1)
    conversation_clock = lambda: AT + timedelta(seconds=next(ticks))  # noqa: E731
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    invoker = FakeToolInvoker([(_confirmable(), _succeeds)] if parks else [])
    memory = FakeMemoryStore(now=lambda: AT)
    conversation_store = FakeConversationStore(now=conversation_clock)
    conversations = ConversationLifecycle(
        conversations=conversation_store,
        memory=memory,
        retention=RETENTION,
        now=conversation_clock,
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
        planner=_OneStepPlanner() if parks else _NoStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=_counter("g"),
    )
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=_counter("d"),
    )
    return Engine(
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        memory=memory,
        deferrals=deferrals,
        conversations=conversations,
        observation=observation,
        questions=questions,
        id_factory=_counter("tok"),
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

    @pytest.fixture
    async def parked_engine(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine holding a single answerable park.

        Reached by driving a real turn over a tool the policy confirms, so the
        confirmation the suite then renders and relays is the one the permission
        stage actually recorded — not a fixture's idea of one.
        """
        built = _wire(parks=True)
        await built.start()
        try:
            outcome = await built.converse("send the note", timeout=timedelta(seconds=30))
            assert outcome.step is not None
            assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
            yield built
        finally:
            await built.aclose()
