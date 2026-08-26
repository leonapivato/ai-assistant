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
from decimal import Decimal
from itertools import count
from typing import TYPE_CHECKING, Protocol

import pytest
from assistant_engine_contract import (
    _DECISION_LIMIT,
    _INVOCATION_LIMIT,
    _NOT_CANONICAL,
    _OVERFULL_DECISIONS,
    _OVERFULL_GRANTS,
    _OVERFULL_READS,
    _SOURCE,
    _SPEND_LIMIT,
    _TINY_LIMIT,
    _UNHELD_SOURCE,
    _UNWRITABLE_LOCATION,
    _UNWRITABLE_SOURCE,
    SPEND_ZERO_CEILING,
    AssistantEngineContract,
    ConnectionSubject,
    DecisionSubject,
    InvocationSubject,
    ReadSubject,
    SpendSubject,
    backwards_clock,
    overfull_invocation_rows,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_spend_ledger,
    seeded_trail,
)

from ai_assistant.core.protocols import (
    AuditTrail,
    InvocationLedger,
    SpendGate,
    SpendLedger,
)
from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Disposition,
    GrantScope,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    ComposingStage,
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
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
    FakeConnectionProvisioner,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeEgressBinder,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeObserver,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
)
from ai_assistant.testing.grants import source_grant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import AssistantEngine, SourceReadTrail
    from ai_assistant.core.types import (
        CurrentContext,
        FrozenJson,
        Goal,
        MemoryRecord,
        SourceGrant,
    )

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)
OBSERVATION_BATCH = 20
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"

#: The one grantable identity the ``granting_engine`` fixture holds. It must equal
#: the suite's own ``_SOURCE``: the suite names the source it grants, and a fixture
#: holding a different one would make every clause below vacuously pass on an
#: ungrantable name. Imported rather than repeated for that reason.
_GRANTABLE = _SOURCE


CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


class ConsumingTrail(AuditTrail, InvocationLedger, SpendGate, SpendLedger, Protocol):
    """Both faces of the **one** audit object (ADR-0192 §2).

    The composition root wires a single store as ``AuditTrail``,
    ``InvocationLedger`` and ``InvocationCompleter``, handing each consumer the
    face its job needs. A harness that wires the runner and the seam has to name
    both at once — the runner records rulings through the trail, the seam claims
    through the ledger, the seam is **admitted** through the gate, and they must
    be the same object or every claim is refused and the ceiling is decided over
    rows a second holder cannot see (ADR-0194 §5).
    Declared here for the reason ``InvocableToolRegistry`` is declared in the
    invoker suite: a variable annotated with one Protocol does not statically
    satisfy the other, and a cast would hide the very identity being asserted.
    """


def _composing() -> ComposingStage:
    """The terminal composing stage every engine now takes (ADR-0170 §2).

    Wired to a cooperating fake provider, which is all these tests need: what the
    composed answer *says*, and what the engine does when composing it fails, are
    pinned in ``tests/orchestration/test_composing.py`` and
    ``tests/orchestration/test_engine_composing.py``.
    """
    return ComposingStage(model=FakeModelProvider(), streaming=FakeStreamingCompleter())


#: A schema declaring ``to`` a destination-bearing argument, in ADR-0152 §3's two
#: keywords. It is what makes :class:`FakeEgressBinder` derive a real binding for
#: :data:`PARAMETERS` rather than answer ``None``, so the parked confirmation the
#: suite reads is the seam's own output — which is what ADR-0178 §3's clause needs
#: this subject to be in a position to answer.
_EGRESS_SCHEMA: Mapping[str, FrozenJson] = {
    "type": "object",
    "properties": {
        "to": {
            "type": "string",
            "x-egress-destination": "smtp",
            "x-egress-tier": "personal",
        }
    },
    "additionalProperties": False,
}


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
        parameters_schema=_EGRESS_SCHEMA,
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


def _wire(  # noqa: PLR0913 — one knob per state the shared suite needs a subject in
    *,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    parks: bool = False,
    sources: Sequence[HeldSource] = (),
    grants: Sequence[SourceGrant] = (),
    grant_clock: Callable[[], datetime] | None = None,
    provisioner: FakeConnectionProvisioner | None = None,
    trail: ConsumingTrail | None = None,
    reads: SourceReadTrail | None = None,
) -> Engine:
    """Build one engine over in-memory fakes, wired as the composition root would.

    ``parks`` swaps in a one-step plan over a tool the policy confirms, which is
    the only way to reach the resume path: parking is the permission stage's
    ruling and no call on the surface asks for it.

    ``sources`` is what the composition root would have read off the readers it
    built (ADR-0102 §7). Empty by default, which is the ordinary deployment: a
    reader ships disabled, so nothing is grantable until one is configured.

    ``trail`` is the audit trail the two ADR-0186 §1 reads relay. A knob because
    nothing on this surface writes a decision — ADR-0186 §4 refuses a promoted
    ``record`` — so a subject with rulings in it has to be *built* with them, and
    because the case separating an engine that sorts from one that relays needs a
    conforming trail whose ``export`` exercises the freedom ADR-0021 §4 leaves it.

    ``reads`` is the source-read trail the two ADR-0186 §10 reads relay, a knob for
    the same reason one turn over: a read is authored on the seam that gated it
    (ADR-0185 §5), so nothing on this surface appends one either.
    """
    # **The conversation store's clock advances**, because ADR-0074 §2's sort key
    # is activity and a frozen clock cannot express "more recently active" at all —
    # every conversation would stamp the same instant and the id tie-break would
    # decide the listing. The other stores keep the fixed instant: nothing else here
    # is about ordering in time.
    ticks = count(1)
    conversation_clock = lambda: AT + timedelta(seconds=next(ticks))  # noqa: E731
    plans = FakePlanStore(now=lambda: AT)
    audit: ConsumingTrail = FakeAuditTrail() if trail is None else trail
    read_trail: SourceReadTrail = FakeSourceReadTrail() if reads is None else reads
    confirmable = _confirmable()
    # The seam claims through the **same** trail the runner records rulings into
    # (ADR-0192 §9's wiring clause); a second one would refuse every claim.
    invoker = FakeToolInvoker([(confirmable, _succeeds)] if parks else [], ledger=audit, gate=audit)
    # The egress binding seam, wired only where the suite needs a park: ADR-0178
    # §3's clause binds every producer of a ``ConfirmationEgress``, and a subject
    # parking a non-egress call would leave it vacuous here.
    binder = FakeEgressBinder() if parks else None
    if binder is not None:
        binder.register_egress(
            confirmable,
            reference="conn-0001",
            identity="work@example.com",
            transport_endpoint="test://endpoint/one",
        )
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
        trail=audit,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=_counter("d"),
        binder=binder,
    )
    return Engine(
        composing=_composing(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=audit,
        spend=audit,
        reads=read_trail,
        memory=memory,
        deferrals=deferrals,
        # The narrow deletion seam (ADR-0119 §7), with the horizon the composition
        # root would pass. The contract suite exercises the request surface rather
        # than the maintenance one, so nothing here sweeps; the engine still cannot
        # be built without them, which is the point of their being required.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=conversations,
        observation=observation,
        questions=questions,
        # The **same** store object the drivers would be given, and the only holder
        # of the wide seam (ADR-0097 §3). A second store here would let a grant land
        # somewhere the gate never reads.
        grant_operations=GrantOperations(
            # ``grants`` seeds the store the way a *previous run* of the hub would
            # have left it — which is the only way a grant on a source this build
            # holds no reader for can exist (ADR-0139 §1). Nothing on the surface
            # can put one there, because ``grant`` admits held readers only.
            store=FakeSourceGrantStore(records=grants),
            sources=sources,
            id_factory=_counter("grant"),
            clock=grant_clock if grant_clock is not None else (lambda: AT),
        ),
        # The canonical provisioner fake, which performs ADR-0148 §6's three writes
        # rather than short-cutting them — so the suite's provisioning clauses are
        # exercised against real orderings on this subject too (ADR-0151 §16).
        connection_operations=ConnectionOperations(
            provisioner=provisioner if provisioner is not None else FakeConnectionProvisioner()
        ),
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
    async def connections(self) -> AsyncIterator[ConnectionSubject]:
        """One wired engine and the provisioner its operations delegate to.

        The provisioner is built here and handed to both, which is the only way the
        suite's negative controls are expressible: ``ConnectionOperations`` holds
        the seam and exposes nothing, deliberately (ADR-0151 §10), so a case that
        must prove nothing was written reads the subject the composition root wired
        rather than reaching through the engine for it.
        """
        provisioner = FakeConnectionProvisioner()
        built = _wire(provisioner=provisioner)
        await built.start()
        try:
            yield ConnectionSubject(engine=built, provisioner=provisioner)
        finally:
            await built.aclose()

    @pytest.fixture
    async def tiny_connections(self) -> AsyncIterator[ConnectionSubject]:
        """The same wiring at the limit the suite can reach."""
        provisioner = FakeConnectionProvisioner()
        built = _wire(provisioner=provisioner, max_payload_bytes=_TINY_LIMIT)
        await built.start()
        try:
            yield ConnectionSubject(engine=built, provisioner=provisioner)
        finally:
            await built.aclose()

    @pytest.fixture
    async def granting_engine(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine holding a single grantable source with a location.

        The source is handed in the way ADR-0102 §7 says a real one arrives — read
        off a reader the composition root built — rather than registered through the
        surface, which has no such operation and must not grow one: what may be
        granted is a property of what was built, and a surface that could add to it
        would be a free-text route into the store by another name.
        """
        built = _wire(sources=[HeldSource(_GRANTABLE, location="/srv/calendar.ics")])
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def defective_source_engine(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine holding a grantable source and two that are not.

        Supplied the way a real one arrives — read off the readers a composition
        root built (ADR-0102 §7) — because that is the only way such a source can
        exist at all: nothing on the surface adds to the held set, and nothing may.
        """
        built = _wire(
            sources=[
                HeldSource(_GRANTABLE, location="/srv/calendar.ics"),
                HeldSource(_UNWRITABLE_SOURCE, location=_UNWRITABLE_LOCATION),
                HeldSource(_NOT_CANONICAL, location="/srv/mail"),
            ]
        )
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def back_dated_engine(self) -> AsyncIterator[AssistantEngine]:
        """The same engine, with a clock that steps **backwards** on every reading.

        Injected at the composition seam ADR-0102 §5 puts it at, which is the point:
        the clock is the *implementation's* and no client supplies one, so this is
        the only place the state ADR-0097 §4 permits can be arranged.
        """
        built = _wire(
            sources=[HeldSource(_GRANTABLE, location="/srv/calendar.ics")],
            grant_clock=backwards_clock(),
        )
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def disagreeing_engine(self) -> AsyncIterator[AssistantEngine]:
        """One held-and-ungranted source, one live grant on a source not held.

        The grant is seeded into the store rather than granted through the surface,
        because ``grant`` admits only a held reader's declared name (ADR-0102 §4)
        and nothing unholds one. That is not a test contrivance: it is exactly the
        shape a deployment reaches when an operator unsets a configured path, which
        ADR-0097 §9 records is "not a defect" and ADR-0102 §14 named as the
        condition that would fire this operation.
        """
        built = _wire(
            sources=[HeldSource(_GRANTABLE, location="/srv/calendar.ics")],
            grants=[source_grant(_UNHELD_SOURCE, scope=(GrantScope.INGEST,))],
        )
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def overfull_granting_engine(self) -> AsyncIterator[AssistantEngine]:
        """A wired engine at the tiny limit whose live set does not fit it."""
        built = _wire(
            max_payload_bytes=_TINY_LIMIT,
            grants=[
                source_grant(f"source-{index}", scope=(GrantScope.FACET,))
                for index in range(_OVERFULL_GRANTS)
            ],
        )
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

    @pytest.fixture
    async def decisions(self) -> AsyncIterator[DecisionSubject]:
        """One wired engine over a seeded trail, and that trail.

        The trail is built here and handed to the engine, which is the only way the
        suite's negative controls are expressible: the engine holds its
        ``AuditTrail`` privately, so a case that must prove no read happened reads
        the subject the composition root wired rather than reaching through the
        engine for it — ``connections``' pattern, one store over.
        """
        trail = await seeded_trail()
        built = _wire(trail=trail)
        await built.start()
        try:
            yield DecisionSubject(engine=built, trail=trail)
        finally:
            await built.aclose()

    @pytest.fixture
    async def unordered_decisions(self) -> AsyncIterator[DecisionSubject]:
        """The same wiring over a trail whose ``export`` is deliberately unordered.

        ``AuditTrail.export`` states no order, so this trail is **conforming** and
        the engine still owes ADR-0186 §2's sort over what it hands back. It is the
        binding that would catch a ``tuple(await trail.export())`` here.
        """
        trail = await seeded_trail(ordered_export=False)
        built = _wire(trail=trail)
        await built.start()
        try:
            yield DecisionSubject(engine=built, trail=trail)
        finally:
            await built.aclose()

    @pytest.fixture
    async def overfull_decisions(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine at the decision limit, over a trail too large for it."""
        trail = await seeded_trail(
            rows=tuple((f"d-{index}", index) for index in range(_OVERFULL_DECISIONS))
        )
        built = _wire(trail=trail, max_payload_bytes=_DECISION_LIMIT)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def reads(self) -> AsyncIterator[ReadSubject]:
        """One wired engine over a seeded read trail, and that trail.

        Built and handed over on :attr:`decisions`' terms exactly: the engine holds
        its ``SourceReadTrail`` privately, so the suite's negative controls are only
        expressible if the case can read the store the composition root wired.
        """
        trail = await seeded_read_trail()
        built = _wire(reads=trail)
        await built.start()
        try:
            yield ReadSubject(engine=built, trail=trail)
        finally:
            await built.aclose()

    @pytest.fixture
    async def invocations(self) -> AsyncIterator[InvocationSubject]:
        """One wired engine over a seeded invocation trail, and that trail.

        Built and handed over on :attr:`decisions`' terms exactly — the engine holds
        its ``AuditTrail`` privately, so the suite's negative controls are only
        expressible if the case can read the store the composition root wired — and
        over the **same** wiring parameter, because ADR-0192 §2 puts the invocation
        rows and the decision rows in one store and one object satisfies both faces.
        """
        trail = await seeded_invocation_trail()
        built = _wire(trail=trail)
        await built.start()
        try:
            yield InvocationSubject(engine=built, trail=trail)
        finally:
            await built.aclose()

    @pytest.fixture
    async def spending(self) -> AsyncIterator[SpendSubject]:
        """One wired engine over a ledger carrying a zero ceiling on both periods.

        The **same** wiring parameter as the invocation subject and one more beside
        it, because ADR-0194 §5 wires one object as the trail, the ledger and the
        gate: two holders keyed by the same rows could disagree about a total.
        """
        ledger = await seeded_spend_ledger(
            day_ceiling=SPEND_ZERO_CEILING, month_ceiling=SPEND_ZERO_CEILING
        )
        built = _wire(trail=ledger)
        await built.start()
        try:
            yield SpendSubject(engine=built, ledger=ledger)
        finally:
            await built.aclose()

    @pytest.fixture
    async def unconfigured_spending(self) -> AsyncIterator[SpendSubject]:
        """One wired engine over a ledger with no currency configured."""
        ledger = await seeded_spend_ledger(currency=None)
        built = _wire(trail=ledger)
        await built.start()
        try:
            yield SpendSubject(engine=built, ledger=ledger)
        finally:
            await built.aclose()

    @pytest.fixture
    async def indeterminate_spending(self) -> AsyncIterator[SpendSubject]:
        """One wired engine over a ledger holding an open claim, day ceiling only."""
        ledger = await seeded_spend_ledger(day_ceiling=Decimal("10"), open_claim=True)
        built = _wire(trail=ledger)
        await built.start()
        try:
            yield SpendSubject(engine=built, ledger=ledger)
        finally:
            await built.aclose()

    @pytest.fixture
    async def overfull_spending(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine at a limit the pair of totals cannot fit inside."""
        ledger = await seeded_spend_ledger()
        built = _wire(trail=ledger, max_payload_bytes=_SPEND_LIMIT)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def overfull_invocations(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine at the invocation limit, over a trail too large for it."""
        trail = await seeded_invocation_trail(rows=overfull_invocation_rows())
        built = _wire(trail=trail, max_payload_bytes=_INVOCATION_LIMIT)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def overfull_reads(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine at the tiny limit, over a read trail too large for it."""
        trail = await seeded_read_trail(
            rows=tuple((f"r-{index}", index) for index in range(_OVERFULL_READS))
        )
        built = _wire(reads=trail, max_payload_bytes=_TINY_LIMIT)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()
