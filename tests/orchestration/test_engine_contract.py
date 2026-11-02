"""The concrete Engine passes the shared AssistantEngine suite.

The other half of the pair ADR-0084 §4's substitutability clause needs: the
in-process engine and the canonical fake are held to *one* suite, so a clause
either binds both or binds neither.

The wiring below is the composition root's, in miniature — the same instances
shared where ADR-0028 §4 says they must be (one memory store behind the writer,
the lifecycle stage and the observation stage). It is written out here rather than
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
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from approvals_panel_contract import APPROVALS_AT, APPROVALS_LIMIT, ApprovalsPanelSubject
from assistant_engine_contract import (
    _BELIEF_LIMIT,
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
    SPEAKABLE_NOTIFICATION,
    SPEND_ZERO_CEILING,
    UNSPEAKABLE_NOTIFICATION,
    AssistantEngineContract,
    BeliefHolder,
    BeliefSubject,
    ConnectionSubject,
    DecisionSubject,
    DerivedPlacementSubject,
    InvocationSubject,
    ReadSubject,
    SpendSubject,
    backwards_clock,
    held_placement,
    near_ceiling_limit,
    overfull_invocation_rows,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_spend_ledger,
    seeded_trail,
)
from chat_surface_contract import (
    CHAT_LIMIT,
    CHAT_SURFACE_AT,
    ChatReaderSubject,
    ChatSurfaceSubject,
)
from episode_inspection_contract import (
    INSPECTION_AT,
    INSPECTION_LIMIT,
    EpisodeInspectionSubject,
)
from pending_candidates_contract import PENDING_AT, PENDING_LIMIT, PendingCandidatesSubject
from person_model_contract import (
    PERSON_BUDGET,
    PERSON_LIMIT,
    PersonModelSubject,
    person_model_stores,
)
from phases_support import phase_path
from story_surface_contract import STORY_LIMIT, STORY_SURFACE_AT, StorySurfaceSubject
from understanding_support import VERSION_LIMIT, understanding_stage, windows_stage

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import ConfigurationError, DeviceRefusal, DeviceRefusedError
from ai_assistant.core.protocols import (
    AuditTrail,
    InvocationLedger,
    SpendGate,
    SpendLedger,
    StoryStore,
)
from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    ChatDevice,
    CostBasis,
    DataTier,
    DeviceAccess,
    GrantScope,
    Idempotency,
    MemoryWrite,
    MemoryWriteMode,
    Placement,
    PlacementReach,
    PlacementSetter,
    RequestingDevice,
    Reversibility,
    RiskLevel,
    StoryMember,
    StoryMemberKind,
    ToolCost,
    ToolDefinition,
    Validity,
)
from ai_assistant.orchestration import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeConversationStore,
    FakeEgressBinder,
    FakeMemoryStore,
    FakeNotificationOutbox,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStoryStore,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
)
from ai_assistant.testing.grants import source_grant

# The engine's own default confirmation ceiling, read from where it is declared so
# this helper cannot drift from it. Every fixture below wires at the default; the
# one that does not says which value it wants and why (ADR-0198 §4).
from ai_assistant.testing.memories import memory as memory_record
from ai_assistant.testing.memories import said_support
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import AssistantEngine, SourceReadTrail
    from ai_assistant.core.types import (
        EgressBinding,
        FrozenJson,
        SourceGrant,
    )
    from ai_assistant.tools.invocation import BoundImplementation

AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)

#: The one grantable identity the ``granting_engine`` fixture holds. It must equal
#: the suite's own ``_SOURCE``: the suite names the source it grants, and a fixture
#: holding a different one would make every clause below vacuously pass on an
#: ungrantable name. Imported rather than repeated for that reason.
_GRANTABLE = _SOURCE


#: The confirmable egress tool's capability. Not ``send_email``: that name is the email
#: tool's, which authorizing checks by its own rules before any ruling (ADR-0364 §9:7).
CAPABILITY = "send_letter"
PARAMETERS = {"to": "someone@example.com"}


#: Either invoker ``_wire`` may bind — the canonical fake, or `tools/`'s own
#: registry. Both satisfy ``ToolRegistry`` and ``ToolInvoker``, which is the whole
#: of what the wiring below needs of one.
type InvocableSeam = FakeToolInvoker | InMemoryToolRegistry


class ConsumingTrail(AuditTrail, InvocationLedger, SpendGate, SpendLedger, Protocol):
    """Both faces of the **one** audit object (ADR-0192 §2).

    The composition root wires a single store as ``AuditTrail``,
    ``InvocationLedger`` and ``InvocationCompleter``, handing each consumer the
    face its job needs. A harness that wires authorizing and the seam has to name
    both at once — authorizing records rulings through the trail, the seam claims
    through the ledger, the seam is **admitted** through the gate, and they must
    be the same object or every claim is refused and the ceiling is decided over
    rows a second holder cannot see (ADR-0194 §5).
    Declared here for the reason ``InvocableToolRegistry`` is declared in the
    invoker suite: a variable annotated with one Protocol does not statically
    satisfy the other, and a cast would hide the very identity being asserted.
    """


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
        effect=CapabilityEffect.WORLD,
        leaves_hub=True,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=True,
        safe_to_repeat=False,
        reads=(),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        parameters_schema=_EGRESS_SCHEMA,
    )


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


def _store_belief_holder(memory: FakeMemoryStore) -> BeliefHolder:
    """Hold beliefs in the store the engine reads, as the owner's own word.

    Written **into the store** for :meth:`TestEngineContract.derived_placement`'s
    reason: no call on this engine writes a belief since ADR-0293 §11 retired ``learn``.
    """
    ids = count(1)

    async def hold(content: str, *, guarded: bool = False) -> str:
        record_id = f"rec-held-{next(ids)}"
        placement = held_placement(guarded=guarded)
        await memory.write_atomic(
            [
                MemoryWrite(
                    record=memory_record(
                        record_id,
                        content,
                        said_support(when=AT, added_at=AT),
                        validity=Validity(),
                        placement=Placement() if placement is None else placement,
                    ),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            ]
        )
        return record_id

    return hold


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
    memory: FakeMemoryStore | None = None,
    notification_outbox: FakeNotificationOutbox | None = None,
    stories: StoryStore | None = None,
    chat_reader: bool = True,
    conversation_store: FakeConversationStore | None = None,
    phases: Mapping[str, Any] | None = None,
    plans: FakePlanStore | None = None,
    person_blocks: PersonBlocks | None = None,
    now: Callable[[], datetime] | None = None,
) -> Engine:
    """Build one engine over in-memory fakes, wired as the composition root would.

    ``parks`` binds an egress tool the policy confirms, with its egress registration,
    so a case driving a call through the phases' acting has a tool to invoke.

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

    ``memory`` is the record store, a knob so a case can seed what the engine reads.

    ``notification_outbox`` is ADR-0131 §3's delivery seam, a knob because nothing on
    this surface enqueues a notification — ADR-0130 §3 puts the offer on the
    ``NotificationWriter`` seam — so a subject with an entry waiting has to be built
    holding one. Left ``None`` for every other case, which is the deployment the suite
    had before ADR-0206 and is why none of them is affected by it.

    ``chat_reader`` is ADR-0293 §6's reader, switched off for the chat-space suite's
    medium obligations alone: they hold exact positions and change lists, so on that
    subject a written message is recorded and waits, as it does on the other two
    implementations built the same way. The reader obligations run with it on, as the
    canonical fake and the wire client answer too; the reader is held to its own
    decision in ``test_chat_reader.py``.

    ``conversation_store`` is the chat space, a knob so the reader obligations can hold
    the reader's marking on the store the engine's chat space is.

    ``phases`` are the keyword knobs ``phases_support.phase_path`` takes — its planning
    double, policy and offered capabilities — for a case that drives a call through the
    phases' acting over this subject's invoker. Given, the path also holds this
    subject's egress binder, as the composition root's does; ``None`` builds the path
    every shared case runs on, unchanged.

    ``plans`` is the plan store, a knob so a case can seed the effect records and
    observation records the pending candidates' read joins; ``candidates`` is the
    composition root's switch that read honours (ADR-0329 §19:3), off as it is there.

    ``person_blocks`` is the person block's assembly over a person-model store and
    ``memory``, as the composition root wires it where ``Settings.person_model`` is on
    (ADR-0338 §7:1); ``None``, the default, is the switch off (§11:2).

    ``now`` is the engine's clock, a knob so the approvals panel's suite reads its requests
    and stamps its taps at the instant its stores are clocked at; ``None`` is the system's.
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
    # The seam claims through the **same** trail authorizing records rulings into
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
    # The egress binding seam, wired only beside the egress tool ``parks`` binds.
    binder = FakeEgressBinder() if parks else None
    if binder is not None:
        binder.register_egress(
            confirmable,
            reference="conn-0001",
            identity="work@example.com",
            transport_endpoint="test://endpoint/one",
        )
    records = FakeMemoryStore(now=lambda: AT) if memory is None else memory
    if conversation_store is None:
        conversation_store = FakeConversationStore(now=conversation_clock)
    conversations = ConversationLifecycle(
        conversations=conversation_store,
        memory=records,
        retention=RETENTION,
        now=conversation_clock,
    )
    return Engine(
        closers=closers,
        plans=store,
        trail=audit,
        spend=audit,
        reads=read_trail,
        memory=records,
        # The narrow deletion seam (ADR-0119 §7), with the horizon the composition
        # root would pass. The contract suite exercises the request surface rather
        # than the maintenance one, so nothing here sweeps; the engine still cannot
        # be built without them, which is the point of their being required.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=conversations,
        # ADR-0276's understanding stage, as the composition root wires it: the shared
        # channel contract asserts the version-1 record every pass it captures carries.
        understanding=understanding_stage(),
        understanding_version_limit=VERSION_LIMIT,
        windows=windows_stage(records),
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
        max_payload_bytes=max_payload_bytes,
        stories=stories,
        chat_reader=chat_reader,
        person_blocks=person_blocks,
        now=(lambda: datetime.now(UTC)) if now is None else now,
        # ADR-0309 §2:6: the phases plan what the chat's reader takes in and every event,
        # as they will on every deployment once the switch lane lands; they are wired
        # only beside the reader, so a subject with it off has none. Over the same
        # invoker, stores, trail and chat space the engine holds, as the root's are.
        phases=(
            phase_path(
                invoker=invoker,
                memory=records,
                plans=store,
                trail=audit,
                conversations=conversation_store,
                **({} if phases is None else {"binder": binder, **phases}),
            )
            if chat_reader
            else None
        ),
    )


async def _pending() -> AsyncIterator[PendingCandidatesSubject]:
    """An engine at the pending candidates' bound, its stores injected and clocked there."""
    memory = FakeMemoryStore(now=lambda: PENDING_AT)
    plans = FakePlanStore(now=lambda: PENDING_AT)
    built = _wire(memory=memory, plans=plans, max_payload_bytes=PENDING_LIMIT)
    await built.start()
    try:
        yield PendingCandidatesSubject(engine=built, memory=memory, plans=plans)
    finally:
        await built.aclose()


async def _approvals() -> AsyncIterator[ApprovalsPanelSubject]:
    """An engine at the approvals panel's bound, its stores injected, clocked there."""
    memory = FakeMemoryStore(now=lambda: APPROVALS_AT)
    plans = FakePlanStore(now=lambda: APPROVALS_AT)
    built = _wire(
        memory=memory, plans=plans, max_payload_bytes=APPROVALS_LIMIT, now=lambda: APPROVALS_AT
    )
    await built.start()
    try:
        yield ApprovalsPanelSubject(engine=built, plans=plans, memory=memory)
    finally:
        await built.aclose()


async def _person_model(*, wired: bool) -> AsyncIterator[PersonModelSubject]:
    """An engine at the person model's bound, its two stores injected; wired or not."""
    people, memory = person_model_stores()
    blocks = (
        PersonBlocks(store=people, memory=memory, budget_chars=PERSON_BUDGET) if wired else None
    )
    built = _wire(memory=memory, max_payload_bytes=PERSON_LIMIT, person_blocks=blocks)
    await built.start()
    try:
        yield PersonModelSubject(engine=built, people=people, memory=memory)
    finally:
        await built.aclose()


class TestEngineContract(AssistantEngineContract):
    """The concrete engine, held to the shared contract."""

    @pytest.fixture
    async def chat_surface(self) -> AsyncIterator[ChatSurfaceSubject]:
        """The production engine over an injected memory store, at the chat bound."""
        memory = FakeMemoryStore(now=lambda: CHAT_SURFACE_AT)
        built = _wire(memory=memory, max_payload_bytes=CHAT_LIMIT, chat_reader=False)
        await built.start()
        try:
            yield ChatSurfaceSubject(engine=built, memory=memory)
        finally:
            await built.aclose()

    @pytest.fixture
    async def chat_reader_surface(self) -> AsyncIterator[ChatReaderSubject]:
        """The production engine with its chat reader on, over injected stores.

        Both read the engine's own instant: the episodes its reader's activations write
        are stamped with it and expire by it, so a store reading another instant would
        hide them. The conversation store's clock advances, as :func:`_wire`'s does.
        """
        memory = FakeMemoryStore(now=lambda: AT)
        ticks = count(1)
        chat = FakeConversationStore(now=lambda: AT + timedelta(seconds=next(ticks)))
        built = _wire(memory=memory, max_payload_bytes=CHAT_LIMIT, conversation_store=chat)
        await built.start()
        try:
            yield ChatReaderSubject(engine=built, memory=memory, chat=chat)
        finally:
            await built.aclose()

    @pytest.fixture
    async def story_surface(self) -> AsyncIterator[StorySurfaceSubject]:
        """The production engine over an injected memory store and story store."""
        memory = FakeMemoryStore(now=lambda: STORY_SURFACE_AT)
        stories = FakeStoryStore(now=lambda: STORY_SURFACE_AT)
        built = _wire(memory=memory, max_payload_bytes=STORY_LIMIT, stories=stories)
        await built.start()
        try:
            yield StorySurfaceSubject(engine=built, memory=memory, stories=stories)
        finally:
            await built.aclose()

    @pytest.fixture
    async def episode_inspection(self) -> AsyncIterator[EpisodeInspectionSubject]:
        """The production engine with an injected inspection store and small payload bound."""
        memory = FakeMemoryStore(now=lambda: INSPECTION_AT)
        built = _wire(memory=memory, max_payload_bytes=INSPECTION_LIMIT)
        await built.start()
        try:
            yield EpisodeInspectionSubject(engine=built, memory=memory)
        finally:
            await built.aclose()

    @pytest.fixture
    async def pending_candidates_subject(self) -> AsyncIterator[PendingCandidatesSubject]:
        """The production engine, over injected stores."""
        async for subject in _pending():
            yield subject

    @pytest.fixture
    async def person_model_subject(self) -> AsyncIterator[PersonModelSubject]:
        """The production engine with a person-model store wired, over injected stores."""
        async for subject in _person_model(wired=True):
            yield subject

    @pytest.fixture
    async def person_model_off(self) -> AsyncIterator[PersonModelSubject]:
        """The production engine as the root builds it with the switch off: no store."""
        async for subject in _person_model(wired=False):
            yield subject

    @pytest.fixture
    async def approvals_subject(self) -> AsyncIterator[ApprovalsPanelSubject]:
        """The production engine over injected stores, clocked at the panel's instant."""
        async for subject in _approvals():
            yield subject

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
    async def beliefs(self) -> AsyncIterator[BeliefSubject]:
        """One wired engine over a store the beliefs are held in."""
        memory = FakeMemoryStore(now=lambda: AT)
        built = _wire(memory=memory)
        await built.start()
        try:
            yield BeliefSubject(engine=built, hold=_store_belief_holder(memory))
        finally:
            await built.aclose()

    @pytest.fixture
    async def tiny_beliefs(self) -> AsyncIterator[BeliefSubject]:
        """:meth:`beliefs`' subject at the limit small enough to reach."""
        memory = FakeMemoryStore(now=lambda: AT)
        built = _wire(memory=memory, max_payload_bytes=_BELIEF_LIMIT)
        await built.start()
        try:
            yield BeliefSubject(engine=built, hold=_store_belief_holder(memory))
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
                source_grant(f"source-{index}", scope=(GrantScope.NOTIFY,))
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
        surface, with no turn to drive: ADR-0204 §2's
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
                    record=memory_record(
                        "rec-derived",
                        "the user's consultant said the merger is off",
                        said_support(when=AT, added_at=AT),
                        validity=Validity(),
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


@pytest.mark.parametrize(
    "call",
    [
        "create_story",
        "link_story",
        "unlink_story",
        "merge_stories",
        "split_story",
        "story",
        "story_log",
        "stories",
        "activation_stories",
    ],
)
async def test_an_engine_with_no_story_store_refuses_the_story_surface(call: str) -> None:
    """An engine built with no story store says so rather than answering empty.

    ADR-0289 §4 puts the nine methods on every engine; a deployment that wired no
    store has no stories, and answering an empty listing would claim it had looked.
    """
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1")
    calls = {
        "create_story": lambda engine: engine.create_story([member]),
        "link_story": lambda engine: engine.link_story("story:s", [member]),
        "unlink_story": lambda engine: engine.unlink_story("story:s", [member]),
        "merge_stories": lambda engine: engine.merge_stories("story:a", "story:b"),
        "split_story": lambda engine: engine.split_story("story:s", [member]),
        "story": lambda engine: engine.story("story:s"),
        "story_log": lambda engine: engine.story_log("story:s"),
        "stories": lambda engine: engine.stories(),
        "activation_stories": lambda engine: engine.activation_stories("a1"),
    }
    built = _wire()
    await built.start()
    try:
        with pytest.raises(ConfigurationError, match="story store"):
            await calls[call](built)
    finally:
        await built.aclose()


async def test_a_composing_signal_needs_the_conversations_end_for_writing() -> None:
    """ADR-0332 §5:11: ``composing`` is in ADR-0298 §5:1's Writing row, which the engine checks.

    A device that is an end for writing is answered with nothing; one that only reads the
    conversation, and one in no set, are refused as a writing call is. The hub's own
    machine passes every row (ADR-0298 §3:2).
    """
    built = _wire(chat_reader=False)
    await built.start()
    try:
        await built.set_my_devices(
            [
                ChatDevice(device_id="pen", access=DeviceAccess.WRITE),
                ChatDevice(device_id="watch", access=DeviceAccess.READ),
            ]
        )
        conversation = (await built.start_conversation()).id
        await built.composing(conversation)
        with serving_device(RequestingDevice(device_id="pen")):
            await built.composing(conversation)
        for device, reason in (
            ("watch", DeviceRefusal.NOT_ALLOWED),
            ("stranger", DeviceRefusal.NO_ROLE),
        ):
            with (
                serving_device(RequestingDevice(device_id=device)),
                pytest.raises(DeviceRefusedError) as refused,
            ):
                await built.composing(conversation)
            assert refused.value.reason is reason
    finally:
        await built.aclose()
