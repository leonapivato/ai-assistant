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

import functools
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

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
    SETTLED_SINGLE_SLOT,
    SPEAKABLE_NOTIFICATION,
    SPEND_ZERO_CEILING,
    UNSPEAKABLE_NOTIFICATION,
    AssistantEngineContract,
    ConnectionSubject,
    DecisionSubject,
    DerivedPlacementSubject,
    InvocationSubject,
    ReadSubject,
    RoutedParkSubject,
    SettledParkSubject,
    SingleSlotParkSubject,
    SpendSubject,
    TranscriptSubject,
    backwards_clock,
    near_ceiling_limit,
    overfull_invocation_rows,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_spend_ledger,
    seeded_trail,
    seeded_transcript_archive,
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
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Message,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanStep,
    Provenance,
    Reversibility,
    RiskLevel,
    Role,
    RoutableOperation,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    Validity,
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
    RoutingStage,
    StepExecutor,
    StepRunner,
)

# The engine's own default confirmation ceiling, read from where it is declared so
# this helper cannot drift from it. Every fixture below wires at the default; the
# one that does not says which value it wants and why (ADR-0198 §4).
from ai_assistant.orchestration.engine import _DEFAULT_MAX_OUTSTANDING
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
    FakeNotificationOutbox,
    FakeObserver,
    FakePlanStore,
    FakeRoutingRecorder,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
    FakeTranscriptArchive,
    FakeTranscriptArchiveWriter,
)
from ai_assistant.testing.grants import source_grant
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import AssistantEngine, SourceReadTrail
    from ai_assistant.core.types import (
        CurrentContext,
        EgressBinding,
        FrozenJson,
        Goal,
        MemoryRecord,
        ShownFile,
        SourceGrant,
    )
    from ai_assistant.tools.invocation import BoundImplementation

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


#: Either invoker ``_wire`` may bind — the canonical fake, or `tools/`'s own
#: registry. Both satisfy ``ToolRegistry`` and ``ToolInvoker``, which is the whole
#: of what the wiring below needs of one.
type InvocableSeam = FakeToolInvoker | InMemoryToolRegistry


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
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
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
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
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


class _SucceedsBound:
    """An **egress-shaped** registration that does nothing and succeeds.

    ``_succeeds`` above satisfies the ordinary callable shape, which is all the
    canonical fake binds. `tools/`'s own registry performs a fourth check the fake
    has no equivalent of — the callable-shape pairing ADR-0148 §4 requires, which
    refuses an egress-authorised call bound to a callable that takes no binding
    (ADR-0152 §10). So a subject wired with the **real** invoker over the parking
    fixture's egress tool needs this shape rather than that one.
    """

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> None:
        """Accept the binding the ruling fixed, and succeed with no output."""


class _RoutingProvider:
    """A ``ModelProvider`` that always answers the routing stage the same way.

    ADR-0197 §4 gives the router's envelope two legal shapes; this yields the route one
    for a scripted query and the decline one otherwise, which is what lets one ``_wire``
    knob produce either a deployment that routes a ``forget`` or the ordinary deployment
    that routes nothing at all.

    It is the routing stage's **only** collaborator (§2), so a double this small is the
    whole of what a subject holding a routed park needs — no planner, no tool and no
    policy is reached on a routed pass.
    """

    def __init__(self, query: str | None) -> None:
        """Answer with a ``forget`` on ``query``, or decline where it is ``None``."""
        self._query = query

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Return one envelope, ignoring what was asked."""
        del messages, model
        envelope = (
            {"no_operation": True}
            if self._query is None
            else {"operation": RoutableOperation.FORGET.value, "query": self._query}
        )
        return Message(role=Role.ASSISTANT, content=json.dumps(envelope))


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
    real_invoker: bool = False,
    closers: Sequence[Callable[[], Awaitable[None]]] = (),
    routes: str | None = None,
    memory: FakeMemoryStore | None = None,
    plans: FakePlanStore | None = None,
    max_outstanding_confirmations: int = _DEFAULT_MAX_OUTSTANDING,
    notification_outbox: FakeNotificationOutbox | None = None,
    archive: FakeTranscriptArchive | None = None,
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

    ``routes`` scripts the operation-routing stage to route every utterance to a
    ``forget`` on that query (ADR-0197 §1), which is the only way to reach the routed
    resume path: a routed park is minted inside a turn and, unlike a tool park, is not
    enumerable afterwards (§7). ``None`` — the default — wires the stage and its recorder
    as a deployment that never routes anything, so every other case in the shared suite
    is driven over a pipeline that behaves exactly as it did before ADR-0197.

    ``memory`` is the record store, a knob so a routed ``forget``'s subject can be seeded:
    §5 resolves the argument by reading the store the operation itself reads, so a
    resolvable park needs a belief in it before the turn runs.

    ``plans`` is the plan store, a knob for one clause only: ADR-0198 §2 rules that a
    restatement re-reads ``StepOutcome.state`` from the store rather than answering from
    a snapshot, and the case that separates the two needs the store emptied *behind* an
    engine that has already settled a park. Nothing on the promoted surface reaches plan
    state, so a fixture that could not hold the store could not arrange it.

    ``notification_outbox`` is ADR-0131 §3's delivery seam, a knob because nothing on
    this surface enqueues a notification — ADR-0130 §3 puts the offer on the
    ``NotificationWriter`` seam — so a subject with an entry waiting has to be built
    holding one. Left ``None`` for every other case, which is the deployment the suite
    had before ADR-0206 and is why none of them is affected by it.

    ``max_outstanding_confirmations`` is the ceiling ADR-0198 §4 reuses as the bound on
    the retained settled records. A knob for :attr:`AssistantEngineContract.tiny_engine`'s
    reason — it is a construction-time property of a deployment — and at
    :data:`SETTLED_SINGLE_SLOT` it is what makes §4's discard reachable in two
    settlements.
    """
    # **The conversation store's clock advances**, because ADR-0074 §2's sort key
    # is activity and a frozen clock cannot express "more recently active" at all —
    # every conversation would stamp the same instant and the id tie-break would
    # decide the listing. The other stores keep the fixed instant: nothing else here
    # is about ordering in time.
    ticks = count(1)
    conversation_clock = lambda: AT + timedelta(seconds=next(ticks))  # noqa: E731
    store = FakePlanStore(now=lambda: AT) if plans is None else plans
    audit: ConsumingTrail = FakeAuditTrail() if trail is None else trail
    read_trail: SourceReadTrail = FakeSourceReadTrail() if reads is None else reads
    confirmable = _confirmable()
    # The seam claims through the **same** trail the runner records rulings into
    # (ADR-0192 §9's wiring clause); a second one would refuse every claim.
    bound = [(confirmable, _succeeds)] if parks else []
    egress_bound: list[tuple[ToolDefinition, BoundImplementation]] = (
        [(confirmable, _SucceedsBound())] if parks else []
    )
    # ``real_invoker`` binds `tools/`'s own registry instead of the canonical fake.
    # The two are contract-equivalent by the shared suite, so no case needs it to
    # exercise ``invoke``'s rules — what it buys is the composition ADR-0194 §11's
    # shutdown clause is about, where the object that admits and the object the
    # façade closes have to be one and the same all the way down.
    invoker: InvocableSeam = (
        InMemoryToolRegistry(egress_bound, ledger=audit, gate=audit)
        if real_invoker
        else FakeToolInvoker(bound, ledger=audit, gate=audit)
    )
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
    records = FakeMemoryStore(now=lambda: AT) if memory is None else memory
    conversation_store = FakeConversationStore(now=conversation_clock)
    conversations = ConversationLifecycle(
        conversations=conversation_store,
        memory=records,
        retention=RETENTION,
        now=conversation_clock,
        archive=FakeTranscriptArchiveWriter(),
        archive_enabled=True,
    )
    writer = FakeMemoryWriter(store=records, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    questions = QuestionStage(writer=writer, deferrals=deferrals, memory=records, now=lambda: AT)
    observation = ObservationStage(
        observer=FakeObserver(),
        conversations=conversation_store,
        memory=records,
        writes=writes,
        batch_size=OBSERVATION_BATCH,
        route=OBSERVER_ROUTE,
    )
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=records,
        writes=writes,
        planner=_OneStepPlanner() if parks else _NoStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=_counter("g"),
        # The same object the runner below resolves against (ADR-0211 §3): a
        # loop told one vocabulary while selection resolved against another
        # could plan a step the selecting registry never advertised.
        registry=invoker,
    )
    runner = StepRunner(
        plans=store,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=audit,
        executor=StepExecutor(plans=store, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=_counter("d"),
        binder=binder,
    )
    return Engine(
        composing=_composing(),
        closers=closers,
        loop=loop,
        runner=runner,
        plans=store,
        trail=audit,
        spend=audit,
        reads=read_trail,
        memory=records,
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
        # ADR-0197's routing stage, holding the write-only half of §9's trail (§9 puts
        # the capability on the stage, so the façade holds no trail seam of any width). A
        # provider that always names one operation is what makes a routed park reachable
        # at all: §7 rules that `pending_confirmations` does not list one and that no
        # durable store recovers it.
        routing=RoutingStage(model=_RoutingProvider(routes), recorder=FakeRoutingRecorder()),
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
        # ADR-0200's two seams, the canonical fakes, wired **together** as the engine
        # requires. The contract suite drives the promoted member rather than either
        # seam, so what these supply is a subject for it to drive at all.
        transcriber=FakeSpeechTranscriber(),
        synthesizer=FakeSpeechSynthesizer(),
        notification_outbox=notification_outbox,
        id_factory=_counter("tok"),
        max_payload_bytes=max_payload_bytes,
        max_outstanding_confirmations=max_outstanding_confirmations,
        archive=FakeTranscriptArchive() if archive is None else archive,
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
    async def speaking_engine(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine holding a placed candidate in its delivery outbox.

        The entry is offered through the outbox itself, which is how a real one
        arrives — ADR-0130 §3's writer hands it over and nothing on the promoted
        surface can — and the synthesizer ``_wire`` already supplies declares every
        format, which is what this subject owes the suite.
        """
        outbox = FakeNotificationOutbox()
        await outbox.offer(SPEAKABLE_NOTIFICATION)
        built = _wire(notification_outbox=outbox)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def withholding_engine(self) -> AsyncIterator[AssistantEngine]:
        """The same, holding a candidate ADR-0206 §3 does not place."""
        outbox = FakeNotificationOutbox()
        await outbox.offer(UNSPEAKABLE_NOTIFICATION)
        built = _wire(notification_outbox=outbox)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def near_ceiling_engine(self) -> AsyncIterator[AssistantEngine]:
        """The same at the limit only a rendering bursts, computed by the suite."""
        outbox = FakeNotificationOutbox()
        await outbox.offer(SPEAKABLE_NOTIFICATION)
        built = _wire(
            notification_outbox=outbox,
            max_payload_bytes=near_ceiling_limit(SPEAKABLE_NOTIFICATION),
        )
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
    async def derived_placement(self) -> AsyncIterator[DerivedPlacementSubject]:
        """One wired engine over a store holding a belief the derivation placed.

        The record is written **into the store** rather than reached through the
        surface, for :attr:`routed_park`'s reason with no turn to drive: ADR-0204 §2's
        evaluation runs between retrieval and planning and writes what a producer
        writes, and ADR-0217 §4's proposal is a producer's too, so no call on this
        engine produces setter ``DERIVED``.

        The placement carries an **instant**, because ADR-0217 §1 admits an untimed
        ``DERIVED`` placement for §9's decode alone: a producer that narrowed stamps
        one, and a fixture that omitted it would be handing the suite a record only the
        legacy decode can produce.
        """
        records = FakeMemoryStore(now=lambda: AT)
        await records.write_atomic(
            [
                MemoryWrite(
                    record=SemanticMemory(
                        id="rec-derived",
                        content="the user's consultant said the merger is off",
                        fact="the user's consultant said the merger is off",
                        validity=Validity(),
                        provenance=Provenance(
                            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                        ),
                        placement=Placement(
                            reach=PlacementReach.OWNER,
                            set_by=PlacementSetter.DERIVED,
                            set_at=AT,
                        ),
                    ),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            ]
        )
        built = _wire(memory=records)
        await built.start()
        try:
            yield DerivedPlacementSubject(engine=built, record_id="rec-derived")
        finally:
            await built.aclose()

    @pytest.fixture
    async def routed_park(self) -> AsyncIterator[RoutedParkSubject]:
        """One wired engine holding a single answerable routed park.

        Reached by driving a **real** turn through the routing stage, so the card the
        suite then answers is the one ADR-0197 §5 resolved and §7 registered — not a
        fixture's idea of one. That is the only way to reach it: §7 rules that a routed
        park is not listed by ``pending_confirmations`` and not recovered across a
        restart, so nothing on the surface can produce or re-mint its token afterwards.

        The belief is seeded before the turn because §5's lookup reads the store the
        operation itself reads; without it the route would resolve to nothing and end in
        ``NOT_FOUND`` rather than parking.
        """
        records = FakeMemoryStore(now=lambda: AT)
        await records.write_atomic(
            [
                MemoryWrite(
                    record=SemanticMemory(
                        id="rec-routed",
                        content="the user likes jazz",
                        fact="the user likes jazz",
                        validity=Validity(),
                        provenance=Provenance(
                            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                        ),
                    ),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            ]
        )
        built = _wire(routes="jazz", memory=records)
        await built.start()
        try:
            outcome = await built.converse("forget that I like jazz", timeout=timedelta(seconds=30))
            assert outcome.routed is not None
            assert outcome.routed.confirmation is not None
            yield RoutedParkSubject(
                engine=built,
                token=outcome.routed.confirmation.token,
                belief_id="rec-routed",
            )
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
    async def spoken_step_park(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine whose spoken turn parks the step it drove (ADR-0207 §1).

        Reached by driving a **real** spoken pass over a tool the policy confirms, so
        the park the suite then reads is the one the permission stage recorded and the
        rendering is the one the engine's own synthesis stage produced — not a
        fixture's idea of either. It is the same wiring :attr:`parked_engine` uses,
        because what makes a turn park is a property of the deployment rather than of
        the call.
        """
        built = _wire(parks=True)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def spoken_routed_park(self) -> AsyncIterator[AssistantEngine]:
        """One wired engine whose spoken turn parks a confirm-owed route (ADR-0207 §1).

        The belief is seeded before the pass for :attr:`routed_park`'s reason: ADR-0197
        §5's lookup reads the store the operation itself reads, so without it the route
        resolves to nothing and ends in ``NOT_FOUND`` rather than parking.
        """
        records = FakeMemoryStore(now=lambda: AT)
        await records.write_atomic(
            [
                MemoryWrite(
                    record=SemanticMemory(
                        id="rec-routed-spoken",
                        content="the user likes jazz",
                        fact="the user likes jazz",
                        validity=Validity(),
                        provenance=Provenance(
                            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                        ),
                    ),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            ]
        )
        built = _wire(routes="jazz", memory=records)
        await built.start()
        try:
            yield built
        finally:
            await built.aclose()

    @pytest.fixture
    async def settled_park(self) -> AsyncIterator[SettledParkSubject]:
        """One wired engine that has answered its park, and the token that named it.

        Settled by driving the **real** resolution — a real turn parks over a tool the
        policy confirms, and a real ``resume`` records the answer through the runner —
        so the retained record under test is the one ADR-0198 §1 installs inside the
        resolution's own critical section, not a fixture's idea of one.
        """
        built = _wire(parks=True)
        await built.start()
        try:
            outcome = await built.converse("send the note", timeout=timedelta(seconds=30))
            assert outcome.step is not None
            assert outcome.step.confirmation is not None
            token = outcome.step.confirmation.token
            resolved = await built.resume(token, approved=True, timeout=timedelta(seconds=30))
            assert resolved.step is not None
            assert resolved.step.disposition is Disposition.EXECUTED
            yield SettledParkSubject(engine=built, token=token)
        finally:
            await built.aclose()

    @pytest.fixture
    async def settled_park_without_its_execution(self) -> AsyncIterator[SettledParkSubject]:
        """:attr:`settled_park`'s subject whose plan store has been emptied behind it.

        Emptied through the store's **own** data-rights operation rather than by
        reaching into its dict, because that is how the state arises: a user erases
        their history, or a store is rebuilt beneath a process still running. ``clear``
        refuses while any execution has a live step, so it also witnesses that the
        settlement really completed before the execution went away.
        """
        plans = FakePlanStore(now=lambda: AT)
        built = _wire(parks=True, plans=plans)
        await built.start()
        try:
            outcome = await built.converse("send the note", timeout=timedelta(seconds=30))
            assert outcome.step is not None
            assert outcome.step.confirmation is not None
            token = outcome.step.confirmation.token
            await built.resume(token, approved=True, timeout=timedelta(seconds=30))
            assert await plans.clear() > 0
            yield SettledParkSubject(engine=built, token=token)
        finally:
            await built.aclose()

    @pytest.fixture
    async def single_slot_parks(self) -> AsyncIterator[SingleSlotParkSubject]:
        """One wired engine at a ceiling of one, holding a settled record and a park.

        **The second turn is admitted only because retention holds no ceiling slot.**
        This engine's ceiling is one, and ``_admit_and_reserve`` refuses a turn that
        would exceed it — so an implementation that counted the settled record with
        the parks would raise inside this fixture rather than fail an assertion, which
        is the loudest place for it to happen.
        """
        built = _wire(parks=True, max_outstanding_confirmations=SETTLED_SINGLE_SLOT)
        await built.start()
        try:
            first = await built.converse("send the note", timeout=timedelta(seconds=30))
            assert first.step is not None
            assert first.step.confirmation is not None
            settled = first.step.confirmation.token
            await built.resume(settled, approved=True, timeout=timedelta(seconds=30))

            second = await built.converse("send another note", timeout=timedelta(seconds=30))
            assert second.step is not None
            assert second.step.confirmation is not None
            yield SingleSlotParkSubject(
                engine=built, settled=settled, parked=second.step.confirmation.token
            )
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
    async def transcripts(self) -> AsyncIterator[TranscriptSubject]:
        """One wired engine over a seeded transcript archive, and that archive.

        Built and handed over on :attr:`reads`' terms exactly: the engine holds its
        ``TranscriptArchive`` privately, so the suite's negative controls — a refusal
        that must leave the archive untouched, a scripted fault that must not be
        reached — are only expressible if the case can hold the object the
        composition wired.
        """
        archive = seeded_transcript_archive()
        built = _wire(archive=archive)
        await built.start()
        try:
            yield TranscriptSubject(engine=built, archive=archive)
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


#: ADR-0233 §15 leaves ``StepRunner._bound`` passing the fail-closed constant, and §6
#: refuses that value at construction — so every egress call in this tree is
#: unconstructable until the lane that follows computes it. The ADR names the state in
#: terms: "a field that lands with nothing writing it leaves a seam answering
#: ``PATH_WITHOUT_MODEL`` and refusing every send, which is the fail-closed direction
#: working and an unfinished job". **Strict**, so the marker is an obligation rather
#: than a licence: #2051's first act is deleting this block, any case that still fails
#: then is a real defect, and any that passes while still marked fails the suite. Not
#: one assertion in this file or in the shared suite is changed by the marking.
_REFUSED_UNTIL_THE_COMPOSER_LANDS: Final = (
    "ADR-0233 §15: the seam refuses every send until the composer lane (#2051) computes coverage"
)

#: The inherited contract cases the **real engine** cannot pass while the seam refuses
#: every send. The canonical fake and the hub client inherit the same cases and pass
#: them, because neither drives ``StepRunner._bound``.
_REFUSED_CASES: Final = (
    "test_a_park_is_recovered_with_a_token_that_resolves",
    "test_a_parked_confirmations_destination_set_is_the_bindings_own",
    "test_a_parked_egress_confirmation_carries_what_the_ruling_was_taken_over",
    "test_a_refusal_is_a_result_and_not_an_exception",
    "test_a_restatement_is_returned_whatever_the_replay_s_approved_carries",
    "test_a_restatement_performs_nothing_however_often_it_is_asked",
    "test_a_restatement_reads_the_execution_and_refuses_to_state_what_it_cannot",
    "test_a_resume_always_carries_its_resolved_step",
    "test_a_settled_binding_is_not_listed_among_pending_confirmations",
    "test_a_settled_denial_restates_the_disposition_it_reached",
    "test_a_settled_token_restates_its_answer_rather_than_being_refused",
    "test_a_spoken_pass_that_parks_a_step_is_spoken_not_silent",
    "test_an_ordinary_parked_step_is_ruled_exactly_as_before",
    "test_retention_holds_no_ceiling_slot_and_discards_the_least_recently_settled",
    "test_two_concurrent_resumes_of_one_token_both_get_the_settled_answer",
)


def _marked_for_this_subclass(case: str) -> Callable[..., Awaitable[None]]:
    """The shared suite's case, marked ``xfail`` **on this subclass alone**.

    A delegating copy rather than a decorator on the inherited function, and the
    indirection is load-bearing rather than clever. ``pytest.mark.xfail(...)(func)``
    stores the mark on the *function object*, and
    :class:`AssistantEngineContract`'s cases are declared once and inherited by
    **three** subclasses — the real engine here, the canonical fake in
    ``test_fake_engine.py`` and the hub client in ``tests/wire/test_client_contract.py``.
    Only this one drives ``StepRunner._bound``, so decorating the shared function would
    mark cases nothing is wrong with, and **strict** ``xfail`` would then fail the suite
    on their ``XPASS`` — turning a marker meant to keep an unfinished job honest into a
    reason two conforming implementations look broken.

    Overriding each case by hand would work and is worse: fifteen stub bodies restating
    a signature the shared suite owns, in a lane whose instruction is to change no
    assertion. This delegates with ``*args``/``**kwargs`` and lets
    ``functools.wraps`` carry ``__wrapped__``, which is what pytest reads the fixture
    names off — so a signature the shared suite changes is followed rather than
    duplicated here.

    Args:
        case: The inherited method's name.

    Returns:
        A fresh coroutine function delegating to it, carrying the strict marker.
    """
    inherited = getattr(AssistantEngineContract, case)

    @functools.wraps(inherited)
    async def marked(*args: object, **kwargs: object) -> None:
        await inherited(*args, **kwargs)

    return pytest.mark.xfail(  # type: ignore[no-any-return]  # the decorator is untyped
        strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS
    )(marked)


for _case in _REFUSED_CASES:
    setattr(TestEngineContract, _case, _marked_for_this_subclass(_case))
