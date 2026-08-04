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
import inspect
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    ConfigurationError,
    MemoryStoreError,
    PlanningError,
    ReaderError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    ActionPlan,
    AnswerKind,
    Attestation,
    BeliefBand,
    BeliefSummary,
    ContinuationToken,
    CostBasis,
    DataTier,
    Disposition,
    EpisodicMemory,
    Evidence,
    FeedbackEvent,
    FeedbackKind,
    Idempotency,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    ObservationReport,
    ObservedProposal,
    PlanStep,
    Provenance,
    QuestionState,
    QueueOutcome,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    StepStatus,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
    Validity,
    band_of,
)
from ai_assistant.orchestration import (
    ConversationLifecycle,
    Engine,
    IngestionStage,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
    WriteOutcome,
    belief_from_record,
    learn_outcome,
    presented_confidence,
)
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, DrainPhase
from ai_assistant.orchestration.loop import LearningLoop
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
    FakeReader,
    FakeSourceGrants,
    FakeToolInvoker,
    ObservationGate,
    source_grant,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.types import (
        CurrentContext,
        Goal,
        MemoryRecord,
        MemoryWrite,
    )

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)

#: The episodic horizon the harness's capture stage stamps with (ADR-0074 §7).
RETENTION = timedelta(days=30)

#: The observation bounds and route the harness wires (ADR-0077 §1, §3). Both are
#: the composition root's job in production; here they are fixed so a test can
#: assert the route the report names.
OBSERVATION_BATCH = 20
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"

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


class RecordingBeliefStore(FakeMemoryStore):
    """A store that records the arguments each ``list_beliefs`` call reached it with.

    Lets a test assert the *relay* — that the façade passes the filters and the page
    through untouched, and that what arrives is a snapshot rather than the caller's
    own sequence — without inferring it from which records came back.
    """

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        super().__init__(now=now)
        self.calls: list[
            tuple[Sequence[BeliefBand] | None, Sequence[MemoryKind] | None, int, int]
        ] = []

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        self.calls.append((bands, kinds, limit, offset))
        return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


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
        feedback: object | None = None,
        observer: object | None = None,
        reader: object | None = None,
        queue_limit: int = 50,
        drain_timeout: timedelta | None = None,
    ) -> None:
        self.plans = FakePlanStore(now=lambda: AT)
        self.trail = FakeAuditTrail()
        # One object as both registry and invoker, as ADR-0029 §8 requires.
        self.invoker = FakeToolInvoker([(definition, _succeeds) for definition in tools])
        self.policy = policy if policy is not None else FakeActionPolicy()
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
        # The capture/lifecycle stage over the *same* memory store, as the
        # composition root wires it (ADR-0074 §9). Kept on the harness so a test can
        # read what capture actually recorded, and so a second façade over the same
        # durable state shares one stage.
        self.conversation_store = FakeConversationStore(now=lambda: AT)
        self.conversations = ConversationLifecycle(
            conversations=self.conversation_store,
            memory=self.memory,
            retention=RETENTION,
            now=lambda: AT,
        )
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.handles = iter(f"tok-{n}" for n in range(1, 100))
        # Kept on the harness so a learn test can read what reached the loop.
        self.feedback = feedback if feedback is not None else FakeFeedbackProcessor()
        self.policy_for_writer = FakeMemoryPolicy()

        writer = FakeMemoryWriter(store=self.memory, policy=self.policy_for_writer, now=lambda: AT)
        # **One** write stage over that writer and one deferral queue, shared by both
        # producers' stages, as the composition root wires it (ADR-0078 §3). Both are
        # kept on the harness: a learn test reads back what was parked, and the
        # question surface answers it.
        self.deferrals = FakeDeferralStore(now=lambda: AT, queue_limit=queue_limit)
        self.writes = MemoryWriteStage(writer=writer, deferrals=self.deferrals)
        self.questions = QuestionStage(
            writer=writer, deferrals=self.deferrals, memory=self.memory, now=lambda: AT
        )
        # The observation stage over the *same* store and write stage, as the
        # composition root wires it (ADR-0077 §8). Kept on the harness so a test can
        # read what batch reached the producer.
        self.observer = observer if observer is not None else FakeObserver()
        self.observation = ObservationStage(
            observer=self.observer,  # type: ignore[arg-type]  # a duck-typed fake stands in for the Protocol
            conversations=self.conversation_store,
            memory=self.memory,
            writes=self.writes,
            batch_size=OBSERVATION_BATCH,
            route=OBSERVER_ROUTE,
        )
        # Leg 6's ingestion stage over the *same* write stage (ADR-0093 §6,
        # ADR-0078 §3), and **only when a reader is given**: a reader ships disabled
        # by default, so the ordinary engine — and therefore almost every case in
        # this module — is built without one.
        self.reader = reader
        # Granted for `INGEST`, because this module is about the *engine* rather
        # than about ADR-0097 §5's gate: an ungranted default would make every
        # ingestion case here refuse before reaching the code under test. The
        # gate's own five cases live in `test_ingestion.py`, against the stage.
        self.grants = FakeSourceGrants(
            []
            if reader is None
            # `reader` is deliberately `object` here — the duck-typed fakes this
            # module wires are not all `Reader`s — so the identity the grant has to
            # cover is read the same way the stage reads it.
            else [source_grant(str(reader.name))]  # type: ignore[attr-defined]
        )
        self.ingestion = (
            None
            if reader is None
            else IngestionStage(
                reader=reader,  # type: ignore[arg-type]  # a duck-typed fake stands in for the Protocol
                writes=self.writes,
                grants=self.grants,
            )
        )
        loop = LearningLoop(
            context=FakeContextProvider(),
            memory=self.memory,
            writes=self.writes,
            planner=planner if planner is not None else OneStepPlanner(),  # type: ignore[arg-type]
            feedback=self.feedback,  # type: ignore[arg-type]
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
            memory=self.memory,
            deferrals=self.deferrals,
            conversations=self.conversations,
            observation=self.observation,
            questions=self.questions,
            ingestion=self.ingestion,
            closers=tuple(closers),  # type: ignore[arg-type]
            id_factory=lambda: next(self.handles),
            drain_timeout=drain_timeout,
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
        await harness.engine.resume(
            ContinuationToken(handle="fabricated"), approved=True, timeout=PATIENT
        )


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
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        id_factory=lambda: next(harness.handles),
    )


async def test_pending_confirmations_is_empty_when_nothing_is_parked() -> None:
    """A turn that executed outright leaves nothing awaiting an answer (ADR-0052 §1)."""
    harness = Harness(tools=(tool(),))
    executed = await harness.engine.converse("send it", timeout=PATIENT)
    assert executed.step is not None
    assert executed.step.disposition is Disposition.EXECUTED
    assert await harness.engine.pending_confirmations() == ()


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
    assert await fresh.pending_confirmations() == ()


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
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
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
    assert await facade_a.pending_confirmations() == ()
    assert facade_a._parked == {}


async def test_an_in_process_park_resolved_elsewhere_is_reconciled_and_frees_the_ceiling() -> None:
    """A converse park resolved by another engine is reconciled, not pinned forever (round 5).

    In-process (turn-carrying) parks count toward the confirmation ceiling. If one is
    resolved by another engine over the same durable stores, its ``_parked`` entry
    would otherwise linger and refuse every later turn as "awaiting an answer". The
    next recovery reconciles it against the trail and evicts it, freeing the ceiling.
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    harness = Harness(tools=(confirmable(),), loop_id_factory=lambda: next(goals))
    facade_a = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        id_factory=lambda: next(harness.handles),
        max_outstanding_confirmations=1,
    )
    parked = await facade_a.converse("send it", timeout=PATIENT)  # A parks in-process (g-1)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    assert len(facade_a._parked) == 1  # a turn-carrying entry, counting toward the ceiling

    # Another engine over the same durable stores resolves A's binding.
    facade_b = _fresh_facade(harness)
    b_pending = await facade_b.pending_confirmations()
    await facade_b.resume(b_pending[0].token, approved=True, timeout=PATIENT)

    # A is now at its ceiling of one with a *stale* in-process entry, so a new turn is
    # refused even though nothing is truly outstanding.
    with pytest.raises(RuntimeError, match="awaiting an answer"):
        await facade_a.converse("send another", timeout=PATIENT)  # consumes g-2

    # Recovery reconciles the stale entry away — it is no longer pending in the trail.
    assert await facade_a.pending_confirmations() == ()
    assert facade_a._parked == {}

    # The ceiling is freed: A drives a fresh turn again.
    outcome = await facade_a.converse("send a third", timeout=PATIENT)  # g-3
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION


async def test_reconcile_keeps_a_concurrent_same_engine_converse_park() -> None:
    """Reconciliation re-checks the trail per binding, so it never strands a fresh park.

    A same-engine ``converse`` that parks *after* recovery read ``active_executions``
    lands in ``_parked`` but is absent from recovery's enumeration snapshot. Evicting
    on that snapshot difference would strand it; the authoritative per-binding
    re-check keeps it, because its binding is genuinely pending (round 5).
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    harness = Harness(tools=(confirmable(),), loop_id_factory=lambda: next(goals))
    facade = Engine(
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        id_factory=lambda: next(harness.handles),
    )
    first = await facade.converse("send it", timeout=PATIENT)  # park g-1 in facade._parked
    assert first.step is not None
    assert len(facade._parked) == 1

    # Gate active_executions so recovery snapshots the store (just g-1), then suspends.
    entered = asyncio.Event()
    release = asyncio.Event()

    class _GateActiveExecutions:
        def __init__(self, inner: object) -> None:
            self._inner = inner
            self._gated = False

        async def active_executions(self) -> object:
            snapshot = await self._inner.active_executions()  # type: ignore[attr-defined]
            if not self._gated:
                self._gated = True
                entered.set()
                await release.wait()
            return snapshot

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    facade._plans = _GateActiveExecutions(harness.plans)  # type: ignore[assignment]  # test double

    recovering = asyncio.ensure_future(facade.pending_confirmations())
    await entered.wait()  # recovery holds the lock, its snapshot is [g-1]

    # A concurrent same-engine converse parks g-2 into facade._parked while recovery is
    # suspended — after its snapshot, so recovery never enumerates it. (converse does
    # not take the recovery lock, so it completes.)
    second = await facade.converse("send another", timeout=PATIENT)  # g-2
    assert second.step is not None
    assert second.step.confirmation is not None
    assert len(facade._parked) == 2  # g-1 and the fresh g-2

    release.set()
    await recovering
    # Reconcile re-checked g-2's binding, found it still pending, and kept it.
    assert len(facade._parked) == 2
    resumed = await facade.resume(second.step.confirmation.token, approved=True, timeout=PATIENT)
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED


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
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
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


async def test_a_resume_cannot_resolve_a_binding_mid_recovery() -> None:
    """Recovery and same-engine resolution are mutually exclusive (round 3 review).

    Recovery reads a binding's live ``CONFIRM`` and then mints its token; a resume
    records the resolving decision and evicts the binding's ``_parked`` entry. Both
    touch the trail and ``_parked``, so were they able to interleave, a resume could
    resolve a binding *after* recovery read it live but *before* recovery minted —
    handing back a stale, unanswerable token. The shared ``_recovery_lock`` makes
    that impossible: a resume launched while recovery holds the lock cannot make
    progress until recovery releases it.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token

    # Gate the trail so recovery suspends *after* it has read the pending decision,
    # exactly the window the review describes.
    entered = asyncio.Event()
    release = asyncio.Event()

    class _GateAfterRead:
        """Wraps the trail, suspending the first ``pending_confirmation`` after it reads."""

        def __init__(self, inner: object) -> None:
            self._inner = inner
            self._gated = False

        async def pending_confirmation(self, **kwargs: object) -> object:
            result = await self._inner.pending_confirmation(**kwargs)  # type: ignore[attr-defined]
            if not self._gated:
                self._gated = True
                entered.set()
                await release.wait()
            return result

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    harness.engine._trail = _GateAfterRead(harness.trail)  # type: ignore[assignment]  # test double

    recovering = asyncio.ensure_future(harness.engine.pending_confirmations())
    await entered.wait()  # recovery has read the live CONFIRM and now holds the lock

    # A same-engine resume of the very binding recovery is looking at. It must not
    # resolve while recovery holds the lock — without the shared lock it would run to
    # completion here and strand recovery's about-to-be-minted token.
    resuming = asyncio.ensure_future(harness.engine.resume(token, approved=True, timeout=PATIENT))
    # Give a lock-free resume ample opportunity to run to completion over the fakes
    # (all its awaits resolve immediately); with the shared lock it stays blocked.
    for _ in range(10):
        await asyncio.sleep(0)
    assert not resuming.done()  # blocked on the shared recovery lock — the fix

    release.set()
    recovered = await recovering
    # Recovery saw the binding live (the resume was blocked), so it reused the one
    # existing token rather than fabricating a second entry for it.
    assert len(recovered) == 1
    assert recovered[0].token == token
    assert len(harness.engine._parked) == 1

    resumed = await resuming  # only now does the resume proceed and resolve
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    # The binding is resolved exactly once and the table is clean — no stale token.
    assert harness.engine._parked == {}


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


# --- the two-phase drain (ADR-0083 §4) ---------------------------------


class _NeverFinishing:
    """A planner whose call runs until it is cancelled.

    Deliberately *not* a suppressor of cancellation: ADR-0083 §4's argument rests
    on every in-flight party honouring cancellation, and ADR-0054 making a
    cancelled store call release its connection only after its worker physically
    finishes. A fake that ignored cancellation would be testing the shape the ADR
    considered and **declined** (ADR-0033's bounded-and-abandon).
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError  # pragma: no cover - the wait above never returns


async def test_the_drain_is_unbounded_when_no_budget_is_given() -> None:
    """The pre-ADR-0083 shape, kept as the default (``drain_timeout=None``).

    Production gets the budget through the composition root, which is where
    deployment values belong. Defaulting the class to thirty seconds would change
    the shutdown of every caller that never asked for one — including every test
    that builds an ``Engine`` directly — so the absence of a budget has to keep
    meaning "wait".
    """
    planner = _NeverFinishing()
    harness = Harness(planner=planner)
    call = asyncio.ensure_future(harness.engine.converse("hello", timeout=PATIENT))
    await planner.entered.wait()

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0.05)

    assert not closing.done()
    assert not planner.cancelled.is_set()

    call.cancel()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing


async def test_phase_a_ends_and_phase_b_cancels_the_remainder() -> None:
    """The budget is what keeps the graceful path reachable at all (§4).

    Under a supervisor with a stop timeout an unbounded wait ends in ``SIGKILL``,
    which destroys exactly the ADR-0029 §4 bookkeeping the drain exists to
    preserve — the record of *why* a step ended, committed under a shield so that
    "a shutdown that stops waiting politely" cannot leave it unwritten. Phase A's
    budget exists so the process reaches phase B instead.
    """
    planner = _NeverFinishing()
    harness = Harness(planner=planner, drain_timeout=timedelta(milliseconds=20))
    call = asyncio.ensure_future(harness.engine.converse("hello", timeout=PATIENT))
    await planner.entered.wait()

    await harness.engine.aclose()

    assert planner.cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await call


async def test_nothing_is_closed_until_the_cancelled_work_has_completed() -> None:
    """Phase B awaits what it cancelled, and that is ADR-0042 §2 satisfied literally.

    Cancelling is not abandoning. ADR-0054 makes a cancelled store call keep its
    connection until its worker thread physically finishes and re-raise only then,
    so the ``CancelledError`` arrives *after* the connection is free. Closing
    before that await completed would be the failure ADR-0042 §2 exists to
    prevent — and bounding the await instead would re-create ADR-0054's own bug, a
    worker thread still holding a connection the next statement closes.
    """
    closed = asyncio.Event()
    unwound = asyncio.Event()

    class _SlowToUnwind:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Stands in for ADR-0054's worker thread finishing after the
                # cancellation and before the error surfaces.
                assert not closed.is_set(), "a resource was closed while work was unwinding"
                unwound.set()
                raise
            raise AssertionError  # pragma: no cover

    async def close() -> None:
        closed.set()

    harness = Harness(
        planner=_SlowToUnwind(),
        closers=(close,),
        drain_timeout=timedelta(milliseconds=20),
    )
    call = asyncio.ensure_future(harness.engine.converse("hello", timeout=PATIENT))
    await asyncio.sleep(0.01)

    await harness.engine.aclose()

    assert unwound.is_set()
    assert closed.is_set()
    with pytest.raises(asyncio.CancelledError):
        await call


async def test_work_that_finishes_inside_the_budget_is_never_cancelled() -> None:
    """Phase A is a *wait*, not a deadline the drain enforces on healthy work.

    The budget elapsing is what moves the drain to phase B; work that quiesces
    before it must complete normally, or every ordinary shutdown would start
    cancelling turns that were about to finish.
    """
    release = asyncio.Event()
    finished = asyncio.Event()

    class _Gated:
        async def plan(
            self,
            goal: Goal,
            *,
            context: CurrentContext,
            memories: Sequence[MemoryRecord] = (),
        ) -> ActionPlan:
            await release.wait()
            finished.set()
            return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)

    harness = Harness(planner=_Gated(), drain_timeout=timedelta(seconds=30))
    call = asyncio.ensure_future(harness.engine.converse("hello", timeout=PATIENT))
    await asyncio.sleep(0)

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    release.set()
    await call
    await closing

    assert finished.is_set()


async def test_a_drain_with_nothing_in_flight_closes_at_once() -> None:
    """The ordinary case: an idle hub does not wait out its budget to stop."""
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = Harness(closers=(close,), drain_timeout=timedelta(seconds=30))

    await asyncio.wait_for(harness.engine.aclose(), timeout=5)

    assert closed.is_set()


async def test_the_drain_records_which_phase_it_ended_in() -> None:
    """The engine says how it shut down, so the hub can report it (#559).

    ADR-0083 §4 leaves phase B's await **unbounded**, which is why "which phase" is
    the field an operator reads first: it is also "was this bounded at all". The
    engine is the only layer that can answer — the hub sees one ``aclose()`` — so it
    records the answer as it goes.

    Its companion below asserts the other direction, because a property that only
    ever reports the happy value is indistinguishable from a constant. A drain that
    quiesced must **not** claim work was cancelled, and vice versa. They are two
    tests rather than one only because narrowing a property across two ``is``
    assertions makes the second unreachable to the type checker.
    """
    harness = Harness(drain_timeout=timedelta(seconds=30))
    # Read into locals rather than asserted on the property twice: narrowing the
    # member expression would make the second comparison unreachable to mypy while
    # leaving the test just as true.
    before = harness.engine.drain_phase

    await harness.engine.aclose()
    after = harness.engine.drain_phase

    assert before is DrainPhase.NOT_RUN
    assert after is DrainPhase.QUIESCED


async def test_a_drain_that_spent_its_budget_says_work_was_cancelled() -> None:
    """The other direction of the phase report (#559), and the one that matters.

    Phase B is the only case where in-flight work was actively cancelled and the only
    one whose tail ADR-0083 §4 leaves unbounded, so an operator watching a hub that
    has not exited yet is asking precisely this question.
    """
    planner = _NeverFinishing()
    harness = Harness(planner=planner, drain_timeout=timedelta(milliseconds=20))
    call = asyncio.ensure_future(harness.engine.converse("hello", timeout=PATIENT))
    await planner.entered.wait()

    await harness.engine.aclose()

    assert harness.engine.drain_phase is DrainPhase.CANCELLED
    with pytest.raises(asyncio.CancelledError):
        await call


# --- the maintenance surface (ADR-0083 §8) -----------------------------


def _counting_purges(harness: Harness, *, records: int, questions: int) -> dict[str, int]:
    """Replace both stores' sweeps with counters, on the very instances wired in.

    The *semantics* of each sweep — which rows are past their deadline, and the two
    anchors ADR-0078 §2 gives the deferral queue — belong to the stores and are held
    to their Protocols by the shared conformance suites. What is unproven anywhere
    else, and is the whole of ADR-0078 §10 item 8, is that **one** façade operation
    reaches **both** of them and reports each count as its own. Distinct return
    values are what make the second half checkable: equal ones would pass for an
    implementation that swept one store twice.
    """
    calls = {"records": 0, "questions": 0}

    async def purge_memory() -> int:
        calls["records"] += 1
        return records

    async def purge_questions() -> int:
        calls["questions"] += 1
        return questions

    harness.memory.purge_expired = purge_memory  # type: ignore[method-assign]
    harness.deferrals.purge = purge_questions  # type: ignore[method-assign]
    return calls


async def test_the_purge_sweeps_both_tier_one_stores_and_reports_each_count() -> None:
    """ADR-0083 §8's maintenance surface, and ADR-0078 §10 item 8 taken literally.

    One façade operation over **two** stores, because the deferral queue's purge "is
    wired wherever ``purge_expired`` is wired and inherits the same fate", and
    "inventing a second sweeping mechanism for one store would be the thing that has
    to be undone at leg 5". A version that swept only memory would satisfy the name
    and leave ADR-0078 §1's exposure cap unkept for exactly the rows that hold the
    user's own words.
    """
    harness = Harness()
    calls = _counting_purges(harness, records=3, questions=2)

    report = await harness.engine.purge_expired()

    assert (report.records, report.questions) == (3, 2)
    assert calls == {"records": 1, "questions": 1}


async def test_the_purge_reaches_the_same_deferral_queue_the_question_surface_answers() -> None:
    """One queue, or the sweep reclaims rows nobody can see (ADR-0078 §1, §3).

    A composition-root single-instance obligation no type can state, of the same
    shape as ``plans`` and ``trail``. Wired to a second queue, ``purge_expired``
    would report a cap kept while the rows the user's own questions live in kept
    growing.
    """
    harness = Harness()

    assert harness.engine._deferrals is harness.deferrals
    assert harness.engine._deferrals is harness.questions._deferrals
    assert harness.engine._deferrals is harness.writes._deferrals


async def test_the_purge_is_drained_before_shutdown_closes_resources() -> None:
    """It is a public method, so it is tracked — which is what closes §8's race.

    ADR-0083 §8's whole argument for a scheduler living *above* the composition root
    rests on this: "``Engine._tracked`` wraps every public method, so a job whose
    body is ``engine.<operation>()`` has its underlying store work in ``_inflight``
    already, and the drain waits for it exactly as it waits for a ``converse``."
    Untracked, the sweep would be a store call racing the ``close()`` that follows.

    **The closer records what it saw**, rather than the test merely looking at a
    moment: a bare "not closed yet" assertion after one loop turn passes for an
    untracked sweep too, because the drain task has not been scheduled by then. The
    only claim that holds regardless of how many turns elapse is the closer's own —
    *was the sweep still gated when I ran?*
    """
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    closed_while_sweeping = False

    async def close() -> None:
        nonlocal closed_while_sweeping
        closed_while_sweeping = not release.is_set()
        closed.set()

    async def gated_purge() -> int:
        entered.set()
        await release.wait()
        return 0

    harness = Harness(closers=(close,))
    harness.memory.purge_expired = gated_purge  # type: ignore[method-assign]

    sweeping = asyncio.ensure_future(harness.engine.purge_expired())
    await entered.wait()
    closing = asyncio.ensure_future(harness.engine.aclose())
    # Several turns, so the drain task is scheduled and runs as far as it can. An
    # untracked sweep would let it reach the closers here.
    for _ in range(5):
        await asyncio.sleep(0)

    assert not closed.is_set(), "a resource was closed while a sweep was still running"
    release.set()
    await sweeping
    await closing
    assert closed.is_set()
    assert closed_while_sweeping is False


async def test_the_purge_is_refused_once_shutdown_has_begun() -> None:
    """The refusal the scheduler reads as *stop* rather than as a job failure (§8).

    Its message is the shared constant, so the scheduler's recognition of it cannot
    drift from what is raised here — two spellings of one message is a seam that
    fails silently, leaving the scheduler retrying against an engine that will never
    accept work again.
    """
    harness = Harness()
    await harness.engine.aclose()

    with pytest.raises(RuntimeError) as raised:
        await harness.engine.purge_expired()

    assert str(raised.value) == ENGINE_SHUTTING_DOWN


async def test_a_failing_memory_sweep_does_not_reach_the_deferral_sweep() -> None:
    """Nothing sequences the two, so a half-done sweep must not report success.

    The next tick simply re-runs both — a missed sweep is never a correctness bug
    (ADR-0007 §2) — and swallowing the first failure to reach the second would claim
    a sweep that half happened. The scheduler logs the failure and retries (§7).
    """
    harness = Harness()
    calls = _counting_purges(harness, records=0, questions=0)

    async def refuses() -> int:
        msg = "the memory store is unreadable"
        raise MemoryStoreError(msg)

    harness.memory.purge_expired = refuses  # type: ignore[method-assign]

    with pytest.raises(MemoryStoreError):
        await harness.engine.purge_expired()

    assert calls["questions"] == 0


# --- the ingestion operation (ADR-0093 §6) ------------------------------


async def test_ingest_reads_the_configured_source_and_reports_what_it_proposed() -> None:
    """The operation ADR-0093 §6 says this façade grows, and its one caller's shape.

    "``Engine`` grows an ingestion operation for the job to call: new concrete
    surface in ``orchestration``, not ``core`` contract surface." The engine rules
    on nothing and writes nothing itself; it relays to the stage, which puts every
    proposal through the same gate ``learn`` and ``observe`` use.
    """
    reader = FakeReader()
    harness = Harness(reader=reader)

    report = await harness.engine.ingest()

    # The producer's own declared identity, relayed unchanged (ADR-0093 §7, §10).
    assert report.source == reader.name
    assert report.proposed == 1
    assert report.stored == 1
    assert len(await harness.memory.search("reported one thing", limit=10)) == 1


async def test_ingest_takes_no_argument_so_the_scheduler_can_bind_it() -> None:
    """A caller cannot widen the read, and the bound method is a legal ``JobBody``.

    Both fall out of the same signature: ADR-0093 §10 gives ``read()`` no arguments
    because "a caller able to widen the read is a caller able to defeat the bound",
    and ADR-0083 §8's job table holds bound no-argument engine methods. A version
    taking even an optional argument would still bind, so what is asserted is the
    contract's half — the call site the scheduler uses takes nothing at all.
    """
    harness = Harness(reader=FakeReader())

    assert inspect.signature(harness.engine.ingest).parameters == {}


async def test_ingest_refuses_when_no_reader_is_configured() -> None:
    """A wiring fault is refused, never reported as a source with nothing to say.

    An empty report is a **successful** pass over an empty source (ADR-0093 §8), so
    returning one here would make a deployment whose reader failed to wire look
    healthy forever while ingesting nothing — the failure ADR-0022 §4a refuses, and
    the same reason §8 makes a failed *read* raise rather than return an empty
    reading. Unreachable from the scheduler, which arms the job only on a
    configured interval and whose ``Settings`` refuse an interval with no source
    (§7a); this guards the second caller and the mis-wired composition root.
    """
    harness = Harness()

    with pytest.raises(ConfigurationError):
        await harness.engine.ingest()


async def test_a_source_failure_reaches_the_scheduler_as_the_readers_own_error() -> None:
    """``ReaderError`` propagates, and the façade adds nothing to it.

    The scheduler logs a failed job "with its class" and retries at the next due
    instant (ADR-0083 §7), which is only useful while the class survives the trip —
    and the message stays payload-free by the reader's contract, which is what
    keeps the source's path out of an operational log (ADR-0093 §8, ADR-0004 §5).
    """
    harness = Harness(reader=FakeReader(failure=FileNotFoundError("no such file")))

    with pytest.raises(ReaderError) as raised:
        await harness.engine.ingest()

    assert isinstance(raised.value.__cause__, FileNotFoundError)


async def test_ingest_is_tracked_so_shutdown_drains_its_write() -> None:
    """It writes through two durable stores, so the drain must wait for it (ADR-0042 §2).

    Untracked, a shutdown would close the connections underneath a write that is
    still in flight — which is exactly what ``_tracked`` exists to prevent, and why
    every operation that touches a store goes through it.
    """
    release = asyncio.Event()
    closed = asyncio.Event()
    closed_while_reading = False

    async def close() -> None:
        nonlocal closed_while_reading
        closed_while_reading = not release.is_set()
        closed.set()

    reader = FakeReader()
    harness = Harness(reader=reader, closers=(close,))
    gate = reader.suspend_next()

    ingesting = asyncio.ensure_future(harness.engine.ingest())
    await gate.reached()
    closing = asyncio.ensure_future(harness.engine.aclose())
    # Several turns, so the drain task is scheduled and runs as far as it can. An
    # untracked pass would let it reach the closers here.
    for _ in range(5):
        await asyncio.sleep(0)

    assert not closed.is_set(), "a resource was closed while an ingestion was still running"
    release.set()
    gate.release()
    await ingesting
    await closing
    assert closed.is_set()
    assert closed_while_reading is False


async def test_ingest_is_refused_once_shutdown_has_begun() -> None:
    """The refusal the scheduler reads as *stop* rather than as a job failure (§8).

    The shared constant, for :meth:`purge_expired`'s reason: two spellings of one
    message is a seam that fails silently, leaving the scheduler retrying against
    an engine that will never accept work again.
    """
    harness = Harness(reader=FakeReader())
    await harness.engine.aclose()

    with pytest.raises(RuntimeError) as raised:
        await harness.engine.ingest()

    assert str(raised.value) == ENGINE_SHUTTING_DOWN


async def test_a_shutting_down_engine_refuses_before_it_reads_the_source() -> None:
    """The refusal precedes the read, so a stopping hub opens no file.

    ``_reject_if_closing`` runs first, which is what makes the ``RuntimeError``
    above a *stop* rather than a fault reported after the work was already done —
    and for this operation the work is I/O against the user's own data.
    """
    reader = FakeReader()
    harness = Harness(reader=reader)
    await harness.engine.aclose()

    with pytest.raises(RuntimeError):
        await harness.engine.ingest()

    assert reader.call_count == 0


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
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
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
        memory=harness.memory,
        deferrals=harness.deferrals,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
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
            memory=harness.memory,
            deferrals=harness.deferrals,
            conversations=harness.conversations,
            observation=harness.observation,
            questions=harness.questions,
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
            memory=harness.memory,
            deferrals=harness.deferrals,
            conversations=harness.conversations,
            observation=harness.observation,
            questions=harness.questions,
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


# --- learn: the correction leg (ADR-0042 §3; roadmap leg 1) --------------


def feedback(
    *,
    kind: FeedbackKind = FeedbackKind.CORRECTION,
    memory_kind: MemoryKind = MemoryKind.SEMANTIC,
    content: str = "the office is in Boston",
    subject: str | None = None,
) -> FeedbackEvent:
    """A ``FeedbackEvent`` the fakes fold into memory."""
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        created_at=AT,
    )


async def test_learn_delegates_to_the_loop_and_summarises_the_result() -> None:
    """``learn`` hands the event to the loop and returns an orchestration summary (§3)."""
    harness = Harness()
    event = feedback()

    outcome = await harness.engine.learn(event)

    assert isinstance(outcome, LearnOutcome)
    # The event reached the loop's feedback processor unchanged.
    assert harness.feedback.events == [event]  # type: ignore[attr-defined]
    # The default fake policy accepts, storing one new record.
    assert len(outcome.results) == 1
    summary = outcome.results[0]
    assert isinstance(summary, IngestSummary)
    assert summary.decision is LearnDecision.STORED
    assert summary.stored is True
    assert summary.record_id is not None
    assert outcome.stored == 1


async def test_learn_summary_carries_the_policy_reason() -> None:
    """The summary surfaces the policy's own justification, per result (§1)."""
    harness = Harness()
    outcome = await harness.engine.learn(feedback())
    # FakeMemoryPolicy stamps a reason on every decision; the summary carries it
    # verbatim, the transparency a confirmation's reason gives (ADR-0042 §4).
    assert harness.policy_for_writer.call_count == 1
    assert outcome.results[0].reason == "fake: configured decision"


async def test_learn_with_no_proposals_returns_an_empty_summary() -> None:
    """Feedback that proposes no update yields an empty, non-error outcome (§3)."""
    harness = Harness(feedback=FakeFeedbackProcessor([]))
    outcome = await harness.engine.learn(feedback())
    assert outcome.results == ()
    assert outcome.stored == 0


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (MemoryDecisionKind.ACCEPT, LearnDecision.STORED),
        (MemoryDecisionKind.REJECT, LearnDecision.REJECTED),
        (MemoryDecisionKind.REINFORCE, LearnDecision.REINFORCED),
        (MemoryDecisionKind.SUPERSEDE, LearnDecision.SUPERSEDED),
        (MemoryDecisionKind.ASK_USER, LearnDecision.DEFERRED),
        (MemoryDecisionKind.STORE_TEMPORARY, LearnDecision.STORED_TEMPORARILY),
    ],
)
def test_from_results_maps_every_decision_kind(
    kind: MemoryDecisionKind, expected: LearnDecision
) -> None:
    """Every ``core`` ruling has a faithful orchestration echo (§1, exhaustive)."""
    decision = _decision(kind)
    stored = None if kind in {MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER} else "rec-1"
    outcome = learn_outcome(
        (_write_outcome(MemoryIngestResult(decision=decision, record_id=stored)),)
    )
    summary = outcome.results[0]
    assert summary.decision is expected
    assert summary.record_id == stored
    assert summary.stored is (stored is not None)
    assert summary.reason == decision.reason


def test_from_results_preserves_order_across_multiple_results() -> None:
    """One summary per result, in the order the loop applied them (§1)."""
    results = (
        _write_outcome(
            MemoryIngestResult(decision=_decision(MemoryDecisionKind.ACCEPT), record_id="rec-1")
        ),
        _write_outcome(
            MemoryIngestResult(decision=_decision(MemoryDecisionKind.REJECT), record_id=None)
        ),
    )
    outcome = learn_outcome(results)
    assert [s.decision for s in outcome.results] == [LearnDecision.STORED, LearnDecision.REJECTED]
    assert outcome.stored == 1


def _write_outcome(result: MemoryIngestResult) -> WriteOutcome:
    """A write outcome carrying ``result`` and no admission.

    ``admission=None`` is what a ruling that raised no question produces — and, for
    an ``ASK_USER``, what secret-tier data produces, which is the case these mapping
    tests happen to drive (ADR-0078 §1). The admission's *own* translation is pinned
    separately, on ``QueuedQuestion.from_admission``.
    """
    return WriteOutcome(result=result)


def _decision(kind: MemoryDecisionKind) -> MemoryDecision:
    """A valid ``MemoryDecision`` of ``kind`` (target/ttl supplied where required)."""
    if kind in {MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE}:
        return MemoryDecision(kind=kind, reason=f"{kind.value} reason", target_id="target-1")
    if kind is MemoryDecisionKind.STORE_TEMPORARY:
        return MemoryDecision(kind=kind, reason="temporary", ttl=timedelta(hours=1))
    return MemoryDecision(kind=kind, reason=f"{kind.value} reason")


async def test_learn_is_refused_once_shutdown_has_begun() -> None:
    """After aclose, learn accepts no new work (§2 stops accepting)."""
    harness = Harness()
    await harness.engine.aclose()
    with pytest.raises(RuntimeError, match="shutting down"):
        await harness.engine.learn(feedback())


async def test_learn_is_drained_before_shutdown_closes_resources() -> None:
    """The write path touches the store, so aclose waits for it before closing (§2)."""
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    closed_while_inflight = False

    class GatedFeedbackProcessor(FakeFeedbackProcessor):
        async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
            entered.set()
            await release.wait()
            return await super().process(event)

    async def close() -> None:
        nonlocal closed_while_inflight
        closed_while_inflight = not release.is_set()
        closed.set()

    harness = Harness(feedback=GatedFeedbackProcessor(), closers=(close,))
    call = asyncio.ensure_future(harness.engine.learn(feedback()))
    await entered.wait()

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)  # let aclose reach its drain
    assert not closed.is_set()  # the resource is not closed while the write is in flight

    release.set()
    await call
    await closing
    assert closed.is_set()
    assert closed_while_inflight is False


# --- the belief inspection surface (ADR-0073 §4, §5, §7) ----------------


def _record(  # noqa: PLR0913 — one knob per field a Belief carries; that is the point
    record_id: str,
    *,
    source: MemorySource = MemorySource.USER_ASSERTED,
    confidence: float = 1.0,
    evidence: tuple[str, ...] = (),
    last_updated: datetime = AT,
    valid_until: datetime | None = None,
    content: str = "the office is in Boston",
    score: float | None = None,
) -> SemanticMemory:
    """A stored semantic record, with every field the projection reads addressable.

    The attestation is *not* a knob: the `ATTESTED` band is unconstructable without
    one since ADR-0092 §1, and no projection case here reads it, so it is supplied
    from the band rather than from a keyword nobody would vary. Keyed on `band_of`
    so a `MemorySource` added into that band later needs no edit here.
    """
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        score=score,
        validity=Validity(valid_until=valid_until),
        provenance=Provenance(
            source=source,
            confidence=confidence,
            evidence=evidence,
            last_updated=last_updated,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=AT)
                if band_of(source) is BeliefBand.ATTESTED
                else None
            ),
        ),
    )


@pytest.mark.parametrize(
    ("source", "band"),
    [
        (MemorySource.USER_ASSERTED, BeliefBand.ASSERTED),
        (MemorySource.OBSERVED, BeliefBand.DERIVED),
        (MemorySource.INFERRED, BeliefBand.DERIVED),
        (MemorySource.EXTERNAL, BeliefBand.ATTESTED),
    ],
)
def test_from_record_applies_the_band_projection_in_the_engine(
    source: MemorySource, band: BeliefBand
) -> None:
    """Every source is classified here, once, so no adapter ever has to (ADR-0073 §7)."""
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.4
    belief = belief_from_record(_record("rec-1", source=source, confidence=confidence))
    assert belief.band is band
    assert belief.confidence == confidence


def test_from_record_carries_exactly_what_the_surface_must_convey() -> None:
    """The DTO carries ADR-0073 §4's fields: id, band, kind, content, confidence, times."""
    until = datetime(2026, 8, 1, tzinfo=UTC)
    belief = belief_from_record(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=0.62,
            evidence=("episode-1", "episode-2"),
            valid_until=until,
        )
    )
    assert belief.id == "rec-1"
    assert belief.kind is MemoryKind.SEMANTIC
    assert belief.content == "the office is in Boston"
    assert belief.last_updated == AT
    assert belief.valid_until == until


def test_from_record_carries_resolved_evidence_and_never_ids() -> None:
    """ADR-0073 §4's derived floor, made structural: the citations do not leave here.

    A citation the surface cannot render as evidence is never rendered *as* evidence
    — "not as a reassuring id, not silently dropped". ADR-0077 §6 discharged the gate
    on *resolving* them, so what the DTO now carries is readable content or an
    explicit tombstone; what it still never carries is an id, which is what stops an
    adapter passing one off as the warrant.
    """
    belief = belief_from_record(
        _record("rec-1", source=MemorySource.INFERRED, confidence=0.5, evidence=("ep-1", "ep-2")),
        (Evidence(content="they said so"), Evidence()),
    )
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 1
    assert "ep-1" not in str(belief)  # no citation id is reachable from the DTO at all


def test_from_record_drops_the_relevance_score() -> None:
    """Nothing was ranked on this path, so no score is carried (ADR-0073 §2, §7)."""
    belief = belief_from_record(_record("rec-1", score=0.93))
    assert not hasattr(belief, "score")


async def test_beliefs_lists_what_memory_holds_in_the_store_s_own_order() -> None:
    """The façade relays the enumeration and projects each record (ADR-0073 §1, §7)."""
    harness = Harness()
    await harness.memory.add(_record("older", last_updated=AT - timedelta(days=1)))
    await harness.memory.add(_record("newer", last_updated=AT))

    page = await harness.engine.beliefs()
    assert [summary.id for summary in page] == ["newer", "older"]  # the store's order, unchanged
    # The listing ships summaries, not beliefs (ADR-0085 §4a): a `BeliefSummary` has
    # no field a citation's content could occupy, so no page can carry the corpus.
    assert all(isinstance(summary, BeliefSummary) for summary in page)
    assert all(not hasattr(summary, "evidence") for summary in page)
    assert page[0].band is BeliefBand.ASSERTED


async def test_beliefs_returns_an_empty_page_when_nothing_matches() -> None:
    """An empty store is an empty tuple, not an error."""
    harness = Harness()
    assert await harness.engine.beliefs() == ()


async def test_beliefs_relays_every_filter_and_the_bounded_default_page() -> None:
    """Filters and paging reach the store verbatim; the default limit is stated (§2)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)

    await harness.engine.beliefs()
    await harness.engine.beliefs(
        bands=[BeliefBand.DERIVED], kinds=[MemoryKind.SEMANTIC], limit=2, offset=7
    )
    assert store.calls == [
        # No filters, and the bounded default page starting from the beginning (§2).
        (None, None, 50, 0),
        # Every filter and both paging arguments, relayed exactly as given.
        ((BeliefBand.DERIVED,), (MemoryKind.SEMANTIC,), 2, 7),
    ]


async def test_beliefs_selects_nothing_for_an_explicitly_empty_filter() -> None:
    """An empty sequence is relayed as itself — it selects nothing, unlike None (§1)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)
    await harness.engine.beliefs(bands=[], kinds=[])
    assert store.calls[-1] == ((), (), 50, 0)


async def test_beliefs_snapshots_its_filters_so_a_caller_cannot_change_the_page() -> None:
    """The filters are materialised before the awaiting task reads them (ADR-0065).

    The mutation lands **mid-flight** — while the store is suspended inside
    ``list_beliefs``, before it has read the sequence it was handed — and not after
    the call returned. That is the difference between proving snapshot *isolation*
    and proving *when* the snapshot was taken, which is what ADR-0065 §3's discharge
    is about.

    Mutating afterwards instead does catch a façade that relays the caller's list
    verbatim — but only by accident of this seam: the recorder happens to keep the
    raw object, and a ``list`` never equals a ``tuple``. Let the recorder normalise
    its capture on entry, an unremarkable thing for a recorder to do, and the
    after-the-fact form goes green against a façade that materialises nothing, while
    this form still fails. A property that rests on the recorder's choice of
    representation is not the property the docstring claims, so it is asserted where
    no later copy can rescue it: after the store already holds the argument.

    The gated-collaborator idiom is the one
    ``test_learn_is_drained_before_shutdown_closes_resources`` uses.
    ``RecordingBeliefStore`` is the seam, subclassed so it reads its own ``bands``
    argument *after* the release — standing in for a store that observes its input
    late, which is the only kind of store that can tell the two façades apart.
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    class GatedBeliefStore(RecordingBeliefStore):
        """Holds ``list_beliefs`` open, then reads ``bands`` only once released."""

        #: ``bands`` as it read after resuming, or ``None`` if it was given none.
        observed_on_resume: tuple[BeliefBand, ...] | None = None

        async def list_beliefs(
            self,
            *,
            bands: Sequence[BeliefBand] | None = None,
            kinds: Sequence[MemoryKind] | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> list[MemoryRecord]:
            entered.set()
            await release.wait()
            self.observed_on_resume = None if bands is None else tuple(bands)
            return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)

    store = GatedBeliefStore(now=lambda: AT)
    harness = Harness(memory=store)

    bands = [BeliefBand.ASSERTED]
    call = asyncio.ensure_future(harness.engine.beliefs(bands=bands))
    await entered.wait()

    bands.append(BeliefBand.DERIVED)  # the caller mutates while the read is in flight
    release.set()
    await call

    # One coherent snapshot: what the store was handed and what it read on resuming
    # are both the filter as it stood when the call was made, not as the caller left
    # it. The second assertion is the original after-the-fact property, kept — it is
    # implied here but costs nothing and names the weaker half explicitly.
    assert store.observed_on_resume == (BeliefBand.ASSERTED,)
    assert store.calls[-1][0] == (BeliefBand.ASSERTED,)


async def test_beliefs_relays_an_out_of_range_page_refusal() -> None:
    """The store refuses rather than clamps, and the façade does not swallow it (§2)."""
    harness = Harness()
    with pytest.raises(ValueError, match="limit"):
        await harness.engine.beliefs(limit=-1)


async def test_belief_reads_the_one_a_deletion_is_about_to_destroy() -> None:
    """The single read show-then-confirm needs, projected like any other (§5, §7)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1", source=MemorySource.EXTERNAL, confidence=0.8))
    belief = await harness.engine.belief("rec-1")
    assert belief is not None
    assert belief.id == "rec-1"
    assert belief.band is BeliefBand.ATTESTED


async def test_belief_is_none_for_an_id_no_live_record_has() -> None:
    """Unknown, and — because ``get`` is live-only — retired, both read as None (§5)."""
    harness = Harness()
    assert await harness.engine.belief("nothing") is None
    retired = _record("retired", valid_until=AT - timedelta(days=1))
    await harness.memory.add(retired)
    assert await harness.engine.belief("retired") is None


async def test_forget_destroys_the_record_and_reports_that_it_did() -> None:
    """``forget`` is ``MemoryStore.delete``, relayed (ADR-0073 §5)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1"))
    assert await harness.engine.forget("rec-1") is True
    assert await harness.engine.belief("rec-1") is None
    assert await harness.engine.beliefs() == ()


async def test_forget_reports_false_for_an_id_no_record_has() -> None:
    """ "No such belief" is a return value the adapter renders, not an error (§7)."""
    harness = Harness()
    assert await harness.engine.forget("nothing") is False


@pytest.mark.parametrize("band", list(BeliefBand))
async def test_forget_refuses_no_band(band: BeliefBand) -> None:
    """The store grows no band-conditional refusal: a data right is unconditional (§5).

    ADR-0004 §6 gives the user an unconditional right to delete their data, so a
    belief is destroyed whatever band the system itself put it in. The asymmetry
    between the bands lives in what the user is told before answering, not in what
    the deletion will do.
    """
    source = {
        BeliefBand.ASSERTED: MemorySource.USER_ASSERTED,
        BeliefBand.DERIVED: MemorySource.INFERRED,
        BeliefBand.ATTESTED: MemorySource.EXTERNAL,
    }[band]
    confidence = 1.0 if band is BeliefBand.ASSERTED else 0.5
    harness = Harness()
    await harness.memory.add(_record("rec-1", source=source, confidence=confidence))
    shown = await harness.engine.belief("rec-1")
    assert shown is not None
    assert shown.band is band
    assert await harness.engine.forget("rec-1") is True


async def test_forget_leaves_nothing_behind_not_even_in_an_export() -> None:
    """Forgetting destroys; a correction would have retired and kept it (ADR-0073 §6)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1"))
    await harness.engine.forget("rec-1")
    assert await harness.memory.export() == []


@pytest.mark.parametrize("call", ["beliefs", "belief", "forget"])
async def test_the_inspection_surface_is_refused_once_shutdown_has_begun(call: str) -> None:
    """After aclose, no inspection call is accepted either (ADR-0042 §2)."""
    harness = Harness()
    await harness.engine.aclose()
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "beliefs": harness.engine.beliefs,
        "belief": lambda: harness.engine.belief("rec-1"),
        "forget": lambda: harness.engine.forget("rec-1"),
    }
    with pytest.raises(RuntimeError, match="shutting down"):
        await calls[call]()


async def test_forget_is_drained_before_shutdown_closes_resources() -> None:
    """A deletion touches the connection-owning store, so aclose waits for it (§2)."""
    release = asyncio.Event()
    entered = asyncio.Event()
    closed = asyncio.Event()
    closed_while_inflight = False

    class GatedDeleteStore(FakeMemoryStore):
        async def delete(self, record_id: str) -> bool:
            entered.set()
            await release.wait()
            return await super().delete(record_id)

    async def close() -> None:
        nonlocal closed_while_inflight
        closed_while_inflight = not release.is_set()
        closed.set()

    harness = Harness(memory=GatedDeleteStore(now=lambda: AT), closers=(close,))
    call = asyncio.ensure_future(harness.engine.forget("rec-1"))
    await entered.wait()

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)  # let aclose reach its drain
    assert not closed.is_set()  # the store is not closed while the deletion is in flight

    release.set()
    await call
    await closing
    assert closed.is_set()
    assert closed_while_inflight is False


# --- conversations: capture, continuity and the façade (ADR-0074 §2, §3, §5) --


class RecordingPlanner(OneStepPlanner):
    """A planner that keeps the ``memories`` it was handed, in order.

    §5 widens what that parameter means — the conversation's recent turns first,
    then the relevance-retrieved beliefs — and the widening is only observable at
    the seam that receives it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        self.seen.append(tuple(memories))
        return await super().plan(goal, context=context, memories=memories)


class RecordingSearchStore(FakeMemoryStore):
    """A store that records the ``kinds`` filter each ``search`` reached it with."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.kinds: list[Sequence[MemoryKind] | None] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        self.kinds.append(kinds)
        return await super().search(query, limit=limit, kinds=kinds)


async def test_converse_runs_under_a_conversation_and_reports_the_one_it_ran_under() -> None:
    """§2: no id starts one, and the outcome names it so a client can continue.

    The id is what a stateless client holds; without it on the outcome, continuing
    would require the *interface* to have kept state VISION §Principle 8 forbids it
    to own.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse("hello", timeout=PATIENT)

    assert outcome.conversation_id is not None
    assert outcome.capture_degraded is False
    assert await harness.conversation_store.get(outcome.conversation_id) is not None
    # One episode per outcome (§3), recorded in the conversation's index.
    turns = await harness.conversation_store.turns(outcome.conversation_id)
    assert [turn.ordinal for turn in turns] == [1]
    assert await harness.memory.get(turns[0].episode_id) is not None


async def test_converse_continues_the_conversation_it_is_given() -> None:
    """§2: a turn carrying an id appends to that conversation; there is no "open"."""
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = Harness(planner=NoStepPlanner(), loop_id_factory=lambda: next(goals))
    first = await harness.engine.converse("hello", timeout=PATIENT)
    assert first.conversation_id is not None

    second = await harness.engine.converse(
        "and again", timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.conversation_id == first.conversation_id
    turns = await harness.conversation_store.turns(first.conversation_id)
    assert [turn.ordinal for turn in turns] == [1, 2]


async def test_converse_refuses_an_id_the_store_does_not_know() -> None:
    """§1: silently starting one turns a typo into "my conversation vanished"."""
    harness = Harness(planner=NoStepPlanner())

    with pytest.raises(UnknownConversationError):
        await harness.engine.converse("hello", timeout=PATIENT, conversation_id="nobody")

    assert await harness.conversation_store.recent() == [], "no conversation was created"


async def test_the_conversation_tail_reaches_the_planner_ahead_of_the_retrieved_beliefs() -> None:
    """§5: continuity reaches the model through the seam it already has.

    ``memories`` carries the conversation's recent turns **first**, then the
    relevance-retrieved records. The order is the whole of the widening: a planner
    may rely on the grouping and must not read a global ranking into it.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    planner = RecordingPlanner()
    harness = Harness(planner=planner, tools=(tool(),), loop_id_factory=lambda: next(goals))
    await harness.memory.add(
        SemanticMemory(
            id="belief-1",
            content="the user prefers metric units",
            fact="metric units",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
        )
    )
    first = await harness.engine.converse("send it", timeout=PATIENT)
    assert first.conversation_id is not None

    await harness.engine.converse("send it", timeout=PATIENT, conversation_id=first.conversation_id)

    handed = planner.seen[-1]
    assert handed, "the second turn should have been handed something"
    assert handed[0].kind == MemoryKind.EPISODIC.value, "the conversation tail comes first"
    assert all(record.kind != MemoryKind.EPISODIC.value for record in handed[1:]), (
        "the relevance-retrieved half is beliefs, because retrieval excludes episodes"
    )


async def test_relevance_retrieval_asks_for_the_belief_kinds_and_never_episodes() -> None:
    """§6: a captured turn must not compete with beliefs for the retrieval budget.

    ``MemoryStore.search`` itself stays band-neutral and kind-filtered only by its
    caller's argument; this asserts the *caller's* argument.
    """
    memory = RecordingSearchStore()
    harness = Harness(planner=NoStepPlanner(), memory=memory)

    await harness.engine.converse("hello", timeout=PATIENT)

    assert memory.kinds, "retrieval ran"
    for asked in memory.kinds:
        assert asked is not None
        assert MemoryKind.EPISODIC not in asked


async def test_a_resumption_is_captured_into_the_conversation_that_parked() -> None:
    """§3: recovered through the binding, never passed — and no conversation invented.

    Two records, both true: the park is an answer the user saw, and so is the
    resolution. The resumption must land in the conversation that parked, which is
    the whole reason the parking turn writes its ``(execution_id, step_id)`` down.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    assert parked.conversation_id is not None
    assert parked.capture_degraded is False

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.conversation_id == parked.conversation_id
    assert resumed.capture_degraded is False
    turns = await harness.conversation_store.turns(parked.conversation_id)
    assert [turn.ordinal for turn in turns] == [1, 2], "the resolution is its own episode"
    assert turns[0].parked is not None, "the parking turn recorded its binding"
    assert turns[1].parked is None
    assert len(await harness.conversation_store.recent()) == 1, "no conversation was invented"


async def test_a_resumption_whose_park_no_longer_resolves_is_not_captured() -> None:
    """§3: a park whose conversation the user deleted — nothing is recorded, and said so.

    Recording it under a conversation invented for the purpose would be worse than
    not recording it: it would assert a conversation the user never had.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    assert parked.conversation_id is not None
    await harness.conversation_store.stamp_deleted(parked.conversation_id)

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED, "the answer is still the answer"
    assert resumed.conversation_id is None
    assert resumed.capture_degraded is True


async def test_a_capture_failure_degrades_the_turn_and_is_reported_on_the_outcome() -> None:
    """§9 item 6: the answer is still the answer, and the user is told it went unrecorded.

    Beside ``memory_degraded``, because a user whose turns are silently not being
    recorded will not find out until they try to continue.
    """

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the embedder is down"
            raise MemoryStoreError(msg)

    harness = Harness(planner=NoStepPlanner(), memory=Faulting(now=lambda: AT))

    outcome = await harness.engine.converse("hello", timeout=PATIENT)

    assert outcome.turn is not None, "the turn still produced its answer"
    assert outcome.capture_degraded is True
    assert outcome.conversation_id is not None


async def test_engine_start_consumes_the_stamped_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0076 §3: every conformance clause can pass against a method **nothing calls**.

    So this asserts the wiring rather than the store: engine start-up reaches the
    enumeration ADR-0076 added, which is the only way a deletion a previous run left
    unfinished is ever rediscovered.
    """
    harness = Harness(planner=NoStepPlanner())
    calls: list[str | None] = []
    original = harness.conversation_store.stamped_conversation_ids

    async def _spy(*, limit: int | None = None, after_id: str | None = None) -> list[str]:
        calls.append(after_id)
        return await original(limit=limit, after_id=after_id)

    monkeypatch.setattr(harness.conversation_store, "stamped_conversation_ids", _spy)

    await harness.engine.start()

    assert calls == [None], "start-up walked the tombstones exactly once, from the beginning"


async def test_engine_start_finishes_a_deletion_a_previous_run_left_unfinished() -> None:
    """ADR-0074 §8: the reclaim runs "by the deleting call, **at engine start**"."""
    harness = Harness(planner=NoStepPlanner())
    outcome = await harness.engine.converse("hello", timeout=PATIENT)
    assert outcome.conversation_id is not None
    turns = await harness.conversation_store.turns(outcome.conversation_id)
    # An interrupted §8 sequence: the stamp landed, nothing else did.
    assert await harness.conversation_store.stamp_deleted(outcome.conversation_id) is True
    assert await harness.memory.get(turns[0].episode_id) is not None

    await harness.engine.start()

    assert await harness.memory.get(turns[0].episode_id) is None, "the leak was swept"


async def test_recent_conversations_projects_what_a_person_chooses_from() -> None:
    """§2: activity descending, and never ``last_turn_at`` as the key."""
    harness = Harness(planner=NoStepPlanner())
    first = await harness.engine.converse("hello", timeout=PATIENT)
    assert first.conversation_id is not None

    listed = await harness.engine.recent_conversations()

    assert [one.id for one in listed] == [first.conversation_id]
    assert listed[0].last_turn_at is not None
    assert listed[0].last_active_at == listed[0].started_at


async def test_forget_conversation_shows_the_span_then_destroys_everything() -> None:
    """§8: show-then-confirm at the unit the user thinks in, then the ordered deletion."""
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = Harness(planner=NoStepPlanner(), loop_id_factory=lambda: next(goals))
    first = await harness.engine.converse("hello", timeout=PATIENT)
    assert first.conversation_id is not None
    await harness.engine.converse("again", timeout=PATIENT, conversation_id=first.conversation_id)

    digest = await harness.engine.conversation(first.conversation_id)
    assert digest is not None
    assert digest.recorded_turns == 2
    assert digest.last_turn_at is not None

    assert await harness.engine.forget_conversation(first.conversation_id) is True

    assert await harness.engine.conversation(first.conversation_id) is None
    assert await harness.engine.recent_conversations() == ()
    assert await harness.memory.export() == [], "every episode it recorded is gone"


# --- the observation leg (ADR-0077 §8) -----------------------------------


async def _one_captured_turn(harness: Harness) -> str:
    """Record one turn through the capture stage, so an episode exists to observe."""
    conversation = await harness.conversations.begin(None)
    await harness.conversations.capture(conversation.id, content="the user said something")
    return conversation.id


async def test_observe_delegates_to_the_stage_and_reports_what_happened() -> None:
    """One call in, one report out — and it names the route that read the episodes.

    The route is ADR-0013 §6's owed reporting, made on the one call where it matters
    most: a model reading back the transcript.
    """
    harness = Harness()
    conversation = await _one_captured_turn(harness)

    report = await harness.engine.observe(conversation_id=conversation)

    assert isinstance(report, ObservationReport)
    assert report.conversation_id == conversation
    assert report.episodes_read == 1
    assert report.route == OBSERVER_ROUTE
    assert report.proposals  # the default fake observer proposes from the batch
    assert all(isinstance(entry, ObservedProposal) for entry in report.proposals)


async def test_observe_with_no_id_selects_the_most_recently_active_conversation() -> None:
    """The façade relays "no id" as ADR-0077 §8's selector, not as "everything"."""
    harness = Harness()
    conversation = await _one_captured_turn(harness)

    report = await harness.engine.observe()

    assert report.conversation_id == conversation


async def test_observe_is_refused_once_shutdown_has_begun() -> None:
    """It writes to the connection-owning store, so it is admission-checked (§2)."""
    harness = Harness()
    await harness.engine.aclose()
    with pytest.raises(RuntimeError, match="shutting down"):
        await harness.engine.observe()


async def test_observe_is_drained_before_shutdown_closes_resources() -> None:
    """An in-flight observation quiesces before the stores close (ADR-0042 §2).

    It reads both durable stores and writes to one, so closing underneath it would
    be closing a connection a live write is using.
    """
    gate = ObservationGate()
    closed: list[str] = []
    harness = Harness(
        observer=FakeObserver(gate=gate),
        closers=(_recording_closer(closed),),
    )
    conversation = await _one_captured_turn(harness)

    running = asyncio.ensure_future(harness.engine.observe(conversation_id=conversation))
    await gate.reached()
    shutdown = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    assert closed == []  # the store is still open while the observation runs
    gate.release()
    await running
    await shutdown
    assert closed == ["closed"]


def _recording_closer(closed: list[str]) -> Callable[[], Awaitable[None]]:
    """A closer that records that it ran, for the drain assertion above."""

    async def _close() -> None:
        closed.append("closed")

    return _close


# --- lost evidence: tombstones and presented confidence (ADR-0077 §6) ----


#: A derived belief's stored confidence, comfortably above the presentation floor.
_STORED = 0.6


async def _derived_with_two_episodes(harness: Harness) -> None:
    """Store a derived belief citing two episodes that both resolve."""
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=_STORED,
            evidence=("ep-1", "ep-2"),
            content="the user prefers metric units",
        )
    )


def _episode_record(
    episode_id: str, content: str, *, expires_at: datetime | None = None
) -> EpisodicMemory:
    """One captured episode, optionally with a retention deadline already passed."""
    return EpisodicMemory(
        id=episode_id,
        content=content,
        occurred_at=AT,
        expires_at=expires_at,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


async def test_a_belief_whose_evidence_all_resolves_shows_the_stored_confidence() -> None:
    """Nothing lost, nothing adjusted — the baseline the degradation is measured from."""
    harness = Harness()
    await _derived_with_two_episodes(harness)

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.confidence == _STORED
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 0
    assert belief.unsupported is False
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_a_deleted_citation_becomes_a_tombstone_without_touching_the_record() -> None:
    """The rendering changes; the stored record does not (ADR-0077 §6).

    The byte-identity assertion is what catches an implementation that "fixed" the
    record instead of the rendering — the record graph is frozen (ADR-0068), and
    losing evidence is not the producer changing its mind.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    before = await harness.memory.get("rec-1")
    assert before is not None

    assert await harness.memory.delete("ep-1") is True
    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 1
    assert belief.evidence[0].lost is True
    assert belief.evidence[0].content is None  # never the id, never a silent gap
    assert belief.evidence[1].content == "they asked again in metric"
    assert belief.confidence < _STORED  # presented, and strictly lower
    # The record is untouched, and an export still carries the citation as written.
    assert await harness.memory.get("rec-1") == before
    exported = {record.id: record for record in await harness.memory.export()}
    assert exported["rec-1"].provenance.evidence == ("ep-1", "ep-2")
    assert exported["rec-1"].provenance.confidence == _STORED


async def test_an_expired_citation_renders_exactly_as_a_deleted_one() -> None:
    """Expiry is the *commoner* loss and has no event to hook (ADR-0077 §6).

    Pinned deliberately: an implementation that hooked deletion only would pass every
    deletion test above and silently leave every expired citation dangling, which is
    §6's decisive argument against eager rewriting.
    """
    harness = Harness()
    await harness.memory.add(
        _episode_record("ep-1", "they asked for metric units", expires_at=AT - timedelta(days=1))
    )
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-2")
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 1
    assert belief.evidence[0].content is None
    assert belief.confidence < _STORED


async def test_a_belief_whose_evidence_is_all_gone_is_held_at_its_effective_floor() -> None:
    """Marked, answerable, still live — **not** retired (ADR-0077 §6).

    Auto-retiring would be the cascade under a softer name: it destroys a belief that
    may be perfectly true, and makes deleting an old conversation silently undo an
    accumulation the user never asked to lose.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    await harness.memory.delete("ep-1")
    await harness.memory.delete("ep-2")

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.unsupported is True
    assert belief.lost_evidence == 2
    assert belief.confidence == pytest.approx(0.1)  # the effective floor, not zero
    # Still live, still listed, and still deletable by the user.
    assert [one.id for one in await harness.engine.beliefs()] == ["rec-1"]
    assert await harness.engine.forget("rec-1") is True


async def test_a_belief_stored_below_the_floor_is_left_where_it_is() -> None:
    """``min(stored, floor)``, not the floor itself — the whole of the edge case (§6).

    ``Provenance.confidence`` permits ``0.0`` and only the observer is bound to a
    positive ladder, so a belief can be stored beneath the floor — where an absolute
    floor and "never above stored" have no value between them at all. The pair with
    the case above is what pins ``min(stored, floor)`` rather than either half of it.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "a thin signal"))
    await harness.memory.add(
        _record("thin", source=MemorySource.INFERRED, confidence=0.05, evidence=("ep-1",))
    )
    await harness.memory.delete("ep-1")

    belief = await harness.engine.belief("thin")

    assert belief is not None
    assert belief.unsupported is True
    assert belief.confidence == 0.05  # unchanged: both bounds collapsed onto the stored value


async def test_the_presented_confidence_falls_strictly_with_each_further_loss() -> None:
    """Monotone above the floor, and bounded by the stored value (ADR-0077 §6).

    Asserted on the function rather than through the store, because the property is
    about the *function*: a pure map from the stored value and how much support
    survives, with no clock and nothing read.
    """
    full = presented_confidence(_STORED, cited=3, resolved=3)
    one_lost = presented_confidence(_STORED, cited=3, resolved=2)
    two_lost = presented_confidence(_STORED, cited=3, resolved=1)
    none_left = presented_confidence(_STORED, cited=3, resolved=0)

    assert full == _STORED
    assert _STORED > one_lost > two_lost > none_left
    assert none_left == pytest.approx(0.1)
    # An assertion cites nothing, and nothing about that is a loss.
    assert presented_confidence(1.0, cited=0, resolved=0) == 1.0


async def test_the_listing_and_the_single_belief_view_agree_on_the_number() -> None:
    """Every surface that states a confidence states the adjusted one (ADR-0077 §6).

    Two surfaces quoting different numbers for one belief would make the disclosure
    rule meaningless, so the adjustment lives in the projection both go through.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    await harness.memory.delete("ep-1")

    listed = await harness.engine.beliefs()
    single = await harness.engine.belief("rec-1")

    assert single is not None
    assert [one.confidence for one in listed if one.id == "rec-1"] == [single.confidence]
    assert single.confidence < _STORED


# --- citations resolve in one batch read (ADR-0086 §6, §8 item 6) --------


class CountingStore(FakeMemoryStore):
    """A store that records which read shape each call took, and with what ids.

    Both counters matter separately. ``_belief`` reads the belief itself through
    ``get`` and §6 is explicit that ``get_many`` "does not replace ``get``", so a
    case that merely counted total reads could not tell the one legitimate single
    from *n* illegitimate ones.
    """

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        super().__init__(now=now)
        self.singles: list[str] = []
        self.batches: list[tuple[str, ...]] = []

    async def get(self, record_id: str) -> MemoryRecord | None:
        self.singles.append(record_id)
        return await super().get(record_id)

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        self.batches.append(tuple(record_ids))
        return await super().get_many(record_ids)


class SteppingClock:
    """A clock that advances on every reading **once armed**, so *when* is visible.

    This is what makes §6's snapshot testable from the consumer's side without
    counting calls: a loop of singles reads the clock once per citation and a batch
    reads it once for the record, so a citation whose expiry falls between two steps
    resolves under one and not the other.

    Arming is what makes the case deterministic rather than merely suggestive. A
    clock that stepped from construction would also step for every ``add`` in the
    fixture, so how far it had moved by the read under test would depend on how many
    setup writes happened to precede it — and the case would pass or fail on that
    accident instead of on the batch.
    """

    def __init__(self, *, step: timedelta) -> None:
        self._now = AT
        self._step = step
        self._armed = False

    def arm(self) -> None:
        """Start advancing, from here on."""
        self._armed = True

    def __call__(self) -> datetime:
        now = self._now
        if self._armed:
            self._now += self._step
        return now


async def test_a_beliefs_citations_are_resolved_in_one_batch_read() -> None:
    """§8 item 6: one ``get_many`` per record, not one ``get`` per citation."""
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.singles.clear()
    store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert store.batches == [("ep-1", "ep-2")], "the citations went in one call, in order"
    assert store.singles == ["rec-1"], (
        "the only single read left is the belief's own id — §6 does not replace `get`"
    )


async def test_a_listing_page_batches_once_per_belief_not_once_per_citation() -> None:
    """The listing is the call site §8 item 6's arithmetic is actually about.

    ADR-0085 §4a removed the listing's evidence *payload* and none of its reads, so
    a lane that migrated the single-belief wrapper alone would leave the 50-by-64 path
    on singles while every single-belief test passed. One batch **per belief**, not
    one per page: the beliefs are independent presentations and §8 item 6 says per
    belief.
    """
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    await harness.memory.add(_episode_record("ep-3", "they wrote 20 °C"))
    await harness.memory.add(
        _record("rec-2", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-3",))
    )
    store.singles.clear()
    store.batches.clear()

    listed = await harness.engine.beliefs()

    assert {"rec-1", "rec-2"} <= {one.id for one in listed}
    assert len(store.batches) == len(listed), "one batch per listed belief, page-wide"
    assert sorted(one for one in store.batches if one) == [("ep-1", "ep-2"), ("ep-3",)]
    assert store.singles == [], "the listing reads through `list_beliefs`, then batches"


async def test_a_belief_citing_nothing_asks_the_store_for_nothing() -> None:
    """§6: an empty argument is a question with an answer, and no round trip.

    Relied on rather than branched around, so this pins that the reliance is real.
    """
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await harness.memory.add(_record("rec-1", evidence=()))
    store.singles.clear()
    store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.evidence == ()
    assert store.batches == [()]


async def test_every_citation_of_a_belief_is_judged_at_one_instant() -> None:
    """§6's snapshot, observed from the consumer: one clock reading for the record.

    Pins the *mechanism* and not the values. Armed, the clock steps an hour per read:
    the belief's own ``get`` takes ``AT``, and the citations are read next. ``ep-2``
    expires 90 minutes in, so a loop of singles reads ``ep-1`` at ``AT + 1h`` and
    ``ep-2`` at ``AT + 2h`` and renders a tombstone the record never lost — the
    "belief's rendered count disagrees with its own tombstones" failure §6 names. One
    batch judges both against the single instant the batch was taken, and nothing is
    lost. No call is counted here, deliberately: this is the case that fails if the
    batch is replaced by a loop that returns identical values.
    """
    clock = SteppingClock(step=timedelta(hours=1))
    store = FakeMemoryStore(now=clock)
    harness = Harness(memory=store)
    await store.add(_episode_record("ep-1", "they asked for metric units"))
    await store.add(
        _episode_record("ep-2", "they asked again in metric", expires_at=AT + timedelta(minutes=90))
    )
    await store.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-2")
        )
    )
    clock.arm()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 0, (
        "both citations were judged against the batch's one instant, not against one "
        "instant each — a citation cannot expire partway through its own presentation"
    )
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_a_repeated_citation_keeps_a_position_of_its_own() -> None:
    """§6: duplicates collapse in the mapping; the rendering must not lose them.

    The answer is assembled by walking ``provenance.evidence``, so a tuple citing an
    id twice renders two positions. An implementation that iterated the mapping would
    render one, and would be silently short for every belief a fold cited twice.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-1")
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked for metric units",
    ]
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 0


async def test_the_batch_renders_tombstones_where_the_singles_did() -> None:
    """§6: ``get_many`` never disagrees with ``get``, on any of the three outcomes.

    Absent, expired and not-yet-live in one record, each in a known position, so a
    batch that honoured only some of the read-time axes — or that returned a ``None``
    value where §6 requires an omission — is caught at the position it broke.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-live", "they asked for metric units"))
    await harness.memory.add(
        _episode_record("ep-expired", "old", expires_at=AT - timedelta(days=1))
    )
    await harness.memory.add(
        EpisodicMemory(
            id="ep-future",
            content="not yet",
            occurred_at=AT,
            validity=Validity(valid_from=AT + timedelta(days=1)),
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        )
    )
    await harness.memory.add(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=_STORED,
            evidence=("ep-live", "ep-expired", "ep-absent", "ep-future"),
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [item.lost for item in belief.evidence] == [False, True, True, True]
    assert belief.evidence[0].content == "they asked for metric units"
    assert belief.lost_evidence == 3


# --- the deferred-question surface, through the façade (ADR-0078 §8, §9) ----


async def test_learn_parks_a_deferred_question_the_facade_can_list_and_answer() -> None:
    """The façade's whole leg 4 reach, in one pass (ADR-0078 §8 reaches 1 and 2).

    ``learn`` says the question was parked **and carries its id**, which is the reach
    that closes issue #423's own scenario; ``questions`` lists it for the case where no
    ``learn`` was in flight to render anything; and ``answer`` commits it. Nothing here
    reaches a store: the façade is the only surface `interfaces` has (ADR-0042 §1).
    """
    harness = Harness()
    harness.policy_for_writer.kind = MemoryDecisionKind.ASK_USER

    learned = await harness.engine.learn(feedback())

    [summary] = learned.results
    assert summary.decision is LearnDecision.DEFERRED
    assert summary.record_id is None
    assert summary.queued is not None
    assert summary.queued.outcome is QueueOutcome.QUEUED
    assert summary.queued.question_id is not None
    assert summary.queued.question_state is QuestionState.OPEN

    [question] = await harness.engine.questions()
    assert question.id == summary.queued.question_id
    assert question.state is QuestionState.OPEN
    assert await harness.engine.interrupted_questions() == (), "the two reads are disjoint"

    harness.policy_for_writer.kind = MemoryDecisionKind.ACCEPT
    answered = await harness.engine.answer(question.id, accept=True)

    assert answered.kind is AnswerKind.APPLIED
    assert answered.record_id is not None
    assert await harness.engine.belief(answered.record_id) is not None
    assert await harness.engine.questions() == (), "and it is no longer waiting"


async def test_learn_against_a_full_queue_tells_the_user_rather_than_going_silent() -> None:
    """§7's refused branch, end to end through the façade (§10 item 3).

    "The refusal is **reported, not swallowed**" — and nothing raises, so this is the
    branch an implementation is most likely to leave as a no-op. A cap of one makes it
    observable without depending on the configured default.
    """
    harness = Harness(queue_limit=1)
    harness.policy_for_writer.kind = MemoryDecisionKind.ASK_USER
    first = await harness.engine.learn(feedback(content="the office is in Boston"))
    assert first.results[0].queued is not None
    assert first.results[0].queued.outcome is QueueOutcome.QUEUED

    second = await harness.engine.learn(feedback(content="the office moved to Lisbon"))

    [summary] = second.results
    assert summary.queued is not None
    assert summary.queued.outcome is QueueOutcome.QUEUE_FULL
    assert summary.queued.question_id is None, "there is no question to name"
    assert len(await harness.engine.questions()) == 1


async def test_a_secret_tier_learn_queues_nothing_and_says_it_is_not_answerable() -> None:
    """§1's residue at the façade (§10 item 3's third half, §10 item 9).

    "Without the third it routes every ``ASK_USER`` through the queued-question line
    and tells the user to go answer something that was never queued — and every other
    listed test still passes, because they all drive the arms that *are* closed."
    """
    harness = Harness(feedback=FakeFeedbackProcessor([_secret_proposal()]))

    learned = await harness.engine.learn(feedback())

    [summary] = learned.results
    assert summary.decision is LearnDecision.DEFERRED
    assert summary.queued is not None
    assert summary.queued.outcome is QueueOutcome.NOT_QUEUABLE
    assert summary.queued.question_id is None
    assert await harness.engine.questions() == (), "nothing was queued"


async def test_forget_question_relays_the_disposal_and_reports_an_unknown_id() -> None:
    """§9's first recovery step, relayed unconditionally (ADR-0007)."""
    harness = Harness()
    harness.policy_for_writer.kind = MemoryDecisionKind.ASK_USER
    learned = await harness.engine.learn(feedback())
    queued = learned.results[0].queued
    assert queued is not None
    assert queued.question_id is not None

    assert await harness.engine.forget_question(queued.question_id) is True
    assert await harness.engine.forget_question(queued.question_id) is False
    assert await harness.engine.questions() == ()


async def test_the_question_surface_is_refused_while_the_engine_is_shutting_down() -> None:
    """Every façade method rejects new work once ``aclose`` has been entered (§2)."""
    harness = Harness()
    await harness.engine.aclose()

    for call in (
        harness.engine.questions(),
        harness.engine.interrupted_questions(),
        harness.engine.answer("q-1", accept=True),
        harness.engine.forget_question("q-1"),
    ):
        with pytest.raises(RuntimeError, match="shutting down"):
            await call


def _secret_proposal() -> MemoryUpdateProposal:
    """A ``DataTier.SECRET`` proposal — the one ``ASK_USER`` nothing may queue."""
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="secret-1",
            content="the api key is hunter2",
            fact="the api key is hunter2",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
        ),
        rationale="the user pasted a credential",
        sensitivity=DataTier.SECRET,
    )
