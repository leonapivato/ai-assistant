"""Every injected-clock seam is guarded, and each raises its subsystem's error.

ADR-0026 §7 is uniformity with **no advisory exemption**: a seam that produces a
float, a seam that only stamps an export, and a seam whose instant is advisory
all guard alike, because a seam cannot know the provenance of the reading it was
handed and so cannot know whether attributing UTC restores a fact or invents one.

This module is deliberately cross-subsystem, which no per-package test file can
be. Its subject is the *set*: a new seam that forgets the guard, or an existing
one whose translation drifts to the wrong ``AssistantError``, fails here rather
than being noticed in review. ``tests/core/test_clock.py`` pins what the guard
does; this pins that every seam has it.

The `testing/` fakes are in scope for the reason they exist (ADR-0026 §7): they
are the canonical doubles consumers certify against, and a fake looser than the
contract certifies consumers the real implementation will reject.
"""

from __future__ import annotations

import ast
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import ai_assistant
from ai_assistant.archive import SqliteTranscriptArchive
from ai_assistant.context.sources import (
    CalendarContextSource,
    ClockContextSource,
    EmailContextSource,
)
from ai_assistant.core import clock
from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    ContextError,
    ConversationStoreError,
    DeferralStoreError,
    MemoryStoreError,
    NotificationOutboxError,
    NotificationStoreError,
    PlanningError,
    TraceStoreError,
    TranscriptArchiveError,
)
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    CostBasis,
    CurrentContext,
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    Goal,
    Idempotency,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    TimeOfDay,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
)
from ai_assistant.learning import ModelBackedObserver, RuleBasedFeedbackProcessor
from ai_assistant.memory import (
    InMemoryMemoryStore,
    MemoryIngestor,
    SqliteDeferralStore,
    SqliteMemoryStore,
    SqliteNotificationOutbox,
    SqliteNotificationStore,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.health import StoreHealthReader
from ai_assistant.orchestration import (
    ComposingStage,
    ConnectionOperations,
    ConsolidationStage,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    IngestionStage,
    LearningLoop,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
    UpcomingEventStage,
)
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.orchestration.traces import OperationTraces
from ai_assistant.permissions import SqliteAuditTrail, SqliteRecipientGrantStore
from ai_assistant.planning import (
    InMemoryPlanStore,
    ModelBackedPlanner,
    PlanExecution,
    SqlitePlanStore,
)
from ai_assistant.service.configuration import ConfigurationStamp
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeEmbedder,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeNotificationWriter,
    FakeObserver,
    FakePlanner,
    FakePlanStore,
    FakeReader,
    FakeRecipientGrants,
    FakeRecipientGrantStore,
    FakeSourceGrants,
    FakeSourceGrantStore,
    FakeSourceReadRecorder,
    FakeSourceReadTrail,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeToolRegistry,
    FakeTraceRetention,
    FakeTraceSink,
    FakeTranscriptArchive,
    FakeTranscriptArchiveWriter,
    invoker_over,
    source_grant,
    succeeds,
)
from ai_assistant.tools.builtin import CurrentTime

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ai_assistant.core.clock import Clock

#: A naive reading: the one every seam used to accept and now must refuse.
_NAIVE = datetime(2026, 7, 21, 12)  # noqa: DTZ001 — the naive reading is the subject
_AWARE = datetime(2026, 7, 21, 12, tzinfo=UTC)


def _composing() -> ComposingStage:
    """The terminal composing stage every engine now takes (ADR-0170 §2).

    Wired to a cooperating fake provider, which is all these tests need: what the
    composed answer *says*, and what the engine does when composing it fails, are
    pinned in ``tests/orchestration/test_composing.py`` and
    ``tests/orchestration/test_engine_composing.py``.
    """
    return ComposingStage(model=FakeModelProvider(), streaming=FakeStreamingCompleter())


#: A model reply the plan extractor can parse, so ``ModelBackedPlanner``'s seam is
#: the clock and not the output: a bare ``FakeModelProvider()`` raises
#: ``PlanningError('no JSON object found in the model reply')`` before the clock is
#: reached, which would pass this table's assertion for the wrong reason.
_PLAN_REPLY: Final = (
    '{"rationale": "one step", "steps": [{"intent": "find a place", '
    '"capability": "search_housing", "parameters": {}}]}'
)


def _naive_clock() -> datetime:
    return _NAIVE


def _failing_clock() -> datetime:
    """A clock that fails on its own account, with the type seams must not steal."""
    msg = "the clock provider is down"
    raise ValueError(msg)


def _record(*, expires_at: datetime | None = None) -> SemanticMemory:
    """A record carrying an expiry, since that is what makes a store read its clock."""
    return SemanticMemory(
        id="m1",
        content="the user drinks coffee",
        fact="the user drinks coffee",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AWARE
        ),
        expires_at=expires_at,
    )


def _goal() -> Goal:
    return Goal(
        id="g1",
        statement="book the flight",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AWARE
        ),
        created_at=_AWARE,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_AWARE,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
    )


def _plan() -> ActionPlan:
    return ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_AWARE, rationale="because")


def _proposal() -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=_record(), rationale="the user said so")


@dataclass(frozen=True)
class Seam:
    """One injected-clock seam and the error its subsystem owes on a bad reading.

    Attributes:
        label: The seam, as named in ADR-0026's table. Also its ``owner`` string,
            so a label that drifts from the constructor fails the assertion.
        drive: Builds the object with the given clock and drives it to *read*
            that clock, through the seam's real entry point rather than by
            reaching into a private method. Taking the clock as a parameter is
            what lets one table assert both halves of ADR-0026 §2's
            reading/invocation boundary. Async uniformly, so the one synchronous
            seam needs no separate branch.
        error: What a caller of ``drive`` sees when the reading is refused — the
            ``AssistantError`` subclass ADR-0026 §4 assigns the seam, or
            ``ClockReadingError`` itself where the subsystem deliberately lets
            `core`'s rejection through untranslated. The second case is not a
            gap in the table: it is a posture the tree takes on purpose and
            states in the seam's own docstring, and :data:`PROPAGATED` is where
            the reason is recorded, so a seam that quietly changed posture fails
            :func:`test_the_untranslated_seams_are_the_declared_ones`.
    """

    label: str
    drive: Callable[[Clock], Coroutine[None, None, None]]
    error: type[Exception]


async def _in_memory_store(now: Clock) -> None:
    store = InMemoryMemoryStore(now=now)
    await store.add(_record(expires_at=_AWARE))
    await store.get("m1")


async def _sqlite_store(now: Clock) -> None:
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(), path=":memory:", embedder=FakeEmbedder(), now=now
    )
    await store.get("m1")


async def _ingestor(now: Clock) -> None:
    # STORE_TEMPORARY is the ruling whose expiry stamp reads the clock, and it
    # reaches the store through `model_copy(update=...)`, past every validator.
    await MemoryIngestor(
        traces_sink=FakeTraceSink(),
        store=InMemoryMemoryStore(now=lambda: _AWARE),
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY),
        now=now,
    ).ingest(_proposal())


async def _fake_store(now: Clock) -> None:
    store = FakeMemoryStore(now=now)
    await store.add(_record(expires_at=_AWARE))
    await store.get("m1")


async def _fake_writer(now: Clock) -> None:
    await FakeMemoryWriter(
        store=FakeMemoryStore(now=lambda: _AWARE),
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY),
        now=now,
    ).ingest(_proposal())


async def _learning_loop(now: Clock) -> None:
    memory = FakeMemoryStore(now=lambda: _AWARE)
    await LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AWARE),
            deferrals=FakeDeferralStore(now=lambda: _AWARE),
        ),
        planner=FakePlanner(now=lambda: _AWARE),
        feedback=FakeFeedbackProcessor(),
        now=now,
        registry=FakeToolRegistry(),
    ).respond("book the flight")


async def _clock_source(now: Clock) -> None:
    await ClockContextSource(now=now).contribute()


async def _calendar_context_source(now: Clock) -> None:
    """The granted facet adapter's clock, read whether or not a grant answers.

    Driven with **no** grant, which is the shortest path to the reading: ADR-0185
    §12 has the clock read the instant ``live()`` resolves, "by answering or by
    raising", so a refusal reaches the seam exactly as a grant does.
    """
    await CalendarContextSource(
        reader=FakeReader(), grants=FakeSourceGrants([]), reads=FakeSourceReadRecorder(), now=now
    ).contribute()


async def _email_context_source(now: Clock) -> None:
    """The second adapter of the same class, on :func:`_calendar_context_source`'s rule.

    Both are driven rather than one taken as representative of the pair: the
    ``owner`` is ``type(self).__name__``, so the two labels are produced by one
    line of source and only driving both proves that line yields both.
    """
    await EmailContextSource(
        reader=FakeReader(), grants=FakeSourceGrants([]), reads=FakeSourceReadRecorder(), now=now
    ).contribute()


async def _fake_planner(now: Clock) -> None:
    await FakePlanner(now=now).plan(_goal(), context=_context(), capabilities=())


async def _fake_plan_store(now: Clock) -> None:
    await FakePlanStore(now=now).export()


async def _in_memory_plan_store(now: Clock) -> None:
    await InMemoryPlanStore(now=now).export()


async def _plan_execution(now: Clock) -> None:
    PlanExecution(now=now).start(_plan(), execution_id="e1")


async def _engine(now: Clock) -> None:
    """The façade's own clock, read only to place the trace horizon (ADR-0119 §10).

    Every *other* collaborator is given a conforming clock, so the reading under
    test is the engine's and not one borrowed from a stage it drives. Driven
    through ``purge_expired``, the one operation that reads it: the maintenance
    surface's retention sweep, where a horizon that is a duration has to become an
    instant.
    """
    memory = FakeMemoryStore(now=lambda: _AWARE)
    conversations = FakeConversationStore(now=lambda: _AWARE)
    deferrals = FakeDeferralStore(now=lambda: _AWARE)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AWARE)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    plans = FakePlanStore(now=lambda: _AWARE)
    # No call in this arm reaches the seam; the ledger is the collaborator
    # ADR-0192 §1 makes unconditional, and nothing here reads it.
    invoker = FakeToolInvoker([], ledger=FakeAuditTrail(), gate=FakeAuditTrail())
    await Engine(
        composing=_composing(),
        loop=LearningLoop(
            context=FakeContextProvider(),
            memory=memory,
            writes=writes,
            planner=FakePlanner(now=lambda: _AWARE),
            feedback=FakeFeedbackProcessor(),
            now=lambda: _AWARE,
            # The same object the runner below resolves against (ADR-0211 §3):
            # a loop told one vocabulary while selection resolved against another
            # could plan a step the selecting registry never advertised.
            registry=invoker,
        ),
        runner=StepRunner(
            plans=plans,
            registry=invoker,
            policy=FakeActionPolicy(),
            trail=FakeAuditTrail(),
            executor=StepExecutor(
                plans=plans, registry=invoker, invoker=invoker, now=lambda: _AWARE
            ),
            now=lambda: _AWARE,
        ),
        plans=plans,
        trail=FakeAuditTrail(),
        spend=FakeAuditTrail(),
        reads=FakeSourceReadTrail(),
        memory=memory,
        deferrals=deferrals,
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: _AWARE,
            archive=FakeTranscriptArchiveWriter(),
            archive_enabled=True,
        ),
        observation=ObservationStage(
            observer=FakeObserver(),
            conversations=conversations,
            memory=memory,
            writes=writes,
            batch_size=20,
            route="anthropic:claude-opus-4-8",
        ),
        questions=QuestionStage(
            writer=writer, deferrals=deferrals, memory=memory, now=lambda: _AWARE
        ),
        grant_operations=GrantOperations(
            store=FakeSourceGrantStore(),
            sources=(),
            id_factory=lambda: "grant-1",
            clock=lambda: _AWARE,
        ),
        # No clock seam of its own: a connection record carries no instant at all
        # (ADR-0149 §3, ADR-0151 §4), which is why this module has nothing to assert
        # about one and why ``recent_connection_acts`` answers in the store's own
        # order rather than by time.
        connection_operations=ConnectionOperations(provisioner=FakeConnectionProvisioner()),
        now=now,
        archive=FakeTranscriptArchive(),
    ).purge_expired()


def _writes(memory: FakeMemoryStore) -> MemoryWriteStage:
    """The write stage every memory-writing stage takes, on a conforming clock."""
    return MemoryWriteStage(
        writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AWARE),
        deferrals=FakeDeferralStore(now=lambda: _AWARE),
    )


def _feedback() -> FeedbackEvent:
    """A correction carrying the resolved kind a ``FeedbackProcessor`` requires."""
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        content="that is wrong",
        created_at=_AWARE,
        memory_kind=MemoryKind.SEMANTIC,
    )


def _episode() -> EpisodicMemory:
    """One episode for the observer to read."""
    return EpisodicMemory(
        id="e1",
        content="we talked about coffee",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AWARE
        ),
        occurred_at=_AWARE,
    )


def _tool() -> ToolDefinition:
    """The one side-effecting tool the execution seams run a step over."""
    return ToolDefinition(
        id="smtp",
        capability="send_email",
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


def _request(*, execution_id: str | None = None) -> ActionRequest:
    """The one request the permission and execution seams are driven over."""
    return ActionRequest(tool=_tool(), parameters={}, step_id="s1", execution_id=execution_id)


def _decision(request: ActionRequest) -> PermissionDecision:
    """The ``ALLOW`` a runner records before executing ``request``."""
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because the user said so"),
        id="d1",
        decided_at=_AWARE,
    )


async def _claimed(store: FakePlanStore) -> str:
    """Store a goal and a one-step plan, open an execution, and answer its id."""
    await store.save_goal(_goal())
    await store.save_plan(
        ActionPlan(
            id="p1",
            goal_id="g1",
            steps=(PlanStep(id="s1", intent="send the note", capability="send_email"),),
            created_at=_AWARE,
            rationale="because",
        )
    )
    state = await store.start_execution("p1")
    return state.id


def _ask() -> MemoryDecision:
    """The ruling that puts a proposal on the deferral queue as a question."""
    return MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="the user decides")


# ---- drivers -------------------------------------------------------------


async def _consolidation(now: Clock) -> None:
    """Consolidation reads its clock to fix the run budget before the first chunk."""
    memory = FakeMemoryStore(now=lambda: _AWARE)
    await memory.add(_record())
    await ConsolidationStage(
        memory=memory, writes=_writes(memory), model=FakeModelProvider(), now=now
    ).run()


async def _conversation_lifecycle(now: Clock) -> None:
    """The retention reclaim reads the clock to place the episodic horizon."""
    await ConversationLifecycle(
        conversations=FakeConversationStore(now=lambda: _AWARE),
        memory=FakeMemoryStore(now=lambda: _AWARE),
        archive=FakeTranscriptArchiveWriter(),
        archive_enabled=True,
        retention=timedelta(days=30),
        now=now,
    ).reclaim()


async def _current_time(now: Clock) -> None:
    """The tool's whole output is the reading, so invoking it is the seam."""
    await CurrentTime(now=now)({}, idempotency_key=None)


async def _fake_audit_trail(now: Clock) -> None:
    """A completion stamps ``recorded_at``, which is the trail's guarded reading."""
    trail = FakeAuditTrail(now=now)
    authorisation = _decision(_request())
    await trail.record(authorisation)
    claim = await trail.claim_invocation(decision=authorisation)
    await trail.complete_invocation(
        claim_id=claim.id,
        outcome=ToolOutcome.FAILED,
        incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
    )


async def _fake_conversation_store(now: Clock) -> None:
    """Starting a conversation stamps it from the store's own clock."""
    await FakeConversationStore(now=now).start()


async def _fake_deferral_store(now: Clock) -> None:
    """The retention purge reads the clock to place its horizon."""
    await FakeDeferralStore(now=now).purge()


async def _fake_feedback_processor(now: Clock) -> None:
    """Every proposal the fake synthesises carries a provenance it stamps."""
    await FakeFeedbackProcessor(now=now).process(_feedback())


async def _fake_notification_outbox(now: Clock) -> None:
    """A claim reads the clock to settle leases before it answers."""
    await FakeNotificationOutbox(now=now).claim()


async def _fake_recipient_grant_store(now: Clock) -> None:
    """The standing listing reads the clock to judge which grants are still live."""
    await FakeRecipientGrantStore(now=now).standing()


async def _fake_recipient_grants(now: Clock) -> None:
    """A cover query reads the clock to judge the grant's expiry."""
    await FakeRecipientGrants(now=now).covering(_request())


async def _fake_transcript_archive(now: Clock) -> None:
    """A retention floor is evaluated at the read, which is what reads the clock."""
    await FakeTranscriptArchive(retention=timedelta(days=7), now=now).size()


async def _ingestion(now: Clock) -> None:
    """The stage stamps the read it records from its own clock."""
    memory = FakeMemoryStore(now=lambda: _AWARE)
    await IngestionStage(
        reader=FakeReader(),
        writes=_writes(memory),
        grants=FakeSourceGrants([source_grant()]),
        reads=FakeSourceReadRecorder(),
        now=now,
    ).ingest()


async def _observer(now: Clock) -> None:
    """The observer stamps each proposal it draws from the batch."""
    await ModelBackedObserver(FakeModelProvider(), now=now).observe([_episode()])


async def _planner(now: Clock) -> None:
    """The plan the model's reply becomes is stamped ``created_at`` from the clock."""
    await ModelBackedPlanner(FakeModelProvider(_PLAN_REPLY), now=now).plan(
        _goal(), context=_context(), capabilities=("search_housing",)
    )


async def _observation(now: Clock) -> None:
    """The pass reads the clock to decide which conversation is due."""
    memory = FakeMemoryStore(now=lambda: _AWARE)
    conversations = FakeConversationStore(now=lambda: _AWARE)
    await conversations.start()
    await ObservationStage(
        observer=FakeObserver(),
        conversations=conversations,
        memory=memory,
        writes=_writes(memory),
        batch_size=20,
        route="anthropic:claude-opus-4-8",
        now=now,
    ).run()


async def _questions(now: Clock) -> None:
    """Accepting a question reads the clock for the proposal's staleness check."""
    memory = FakeMemoryStore(now=lambda: _AWARE)
    deferrals = FakeDeferralStore(now=lambda: _AWARE)
    await deferrals.defer(deferral_id="q1", proposal=_proposal(), decision=_ask())
    await QuestionStage(
        writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AWARE),
        deferrals=deferrals,
        memory=memory,
        now=now,
    ).answer("q1", accept=True)


async def _rule_based_processor(now: Clock) -> None:
    """Every proposal the rules produce carries a provenance stamped from the clock."""
    await RuleBasedFeedbackProcessor(now=now).process(_feedback())


async def _sqlite_audit_trail(now: Clock) -> None:
    """A completion stamps ``recorded_at``, which is the trail's guarded reading."""
    with tempfile.TemporaryDirectory() as directory:
        trail = SqliteAuditTrail(path=Path(directory) / "audit.db", now=now)
        try:
            authorisation = _decision(_request())
            await trail.record(authorisation)
            claim = await trail.claim_invocation(decision=authorisation)
            await trail.complete_invocation(
                claim_id=claim.id,
                outcome=ToolOutcome.FAILED,
                incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
            )
        finally:
            trail.close()


async def _sqlite_conversation_store(now: Clock) -> None:
    """Starting a conversation stamps it from the store's own clock."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqliteConversationStore(path=Path(directory) / "conversations.db", now=now)
        try:
            await store.start()
        finally:
            store.close()


async def _sqlite_deferral_store(now: Clock) -> None:
    """The retention purge reads the clock to place its horizon."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqliteDeferralStore(path=Path(directory) / "deferrals.db", now=now)
        try:
            await store.purge()
        finally:
            store.close()


async def _sqlite_notification_outbox(now: Clock) -> None:
    """A claim reads the clock to settle leases before it answers."""
    with tempfile.TemporaryDirectory() as directory:
        outbox = SqliteNotificationOutbox(
            path=Path(directory) / "outbox.db",
            records=FakeNotificationStore(now=lambda: _AWARE),
            lease=timedelta(minutes=2),
            max_entries=256,
            max_bytes=1 << 20,
            candidate_ceiling=64,
            now=now,
        )
        try:
            await outbox.claim()
        finally:
            outbox.close()


async def _sqlite_notification_store(now: Clock) -> None:
    """The retention purge reads the clock to place its horizon."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqliteNotificationStore(
            path=Path(directory) / "notifications.db", traces_sink=FakeTraceSink(), now=now
        )
        try:
            await store.purge()
        finally:
            store.close()


async def _sqlite_plan_store(now: Clock) -> None:
    """The export stamps ``exported_at`` from the store's own clock."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqlitePlanStore(path=Path(directory) / "plans.db", now=now)
        try:
            await store.export()
        finally:
            store.close()


async def _sqlite_recipient_grant_store(now: Clock) -> None:
    """The standing listing reads the clock to judge which grants are still live."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqliteRecipientGrantStore(
            path=Path(directory) / "grants.db", max_outstanding=64, now=now
        )
        try:
            await store.standing()
        finally:
            store.close()


async def _sqlite_transcript_archive(now: Clock) -> None:
    """A retention floor is evaluated at the read, which is what reads the clock."""
    with tempfile.TemporaryDirectory() as directory:
        archive = SqliteTranscriptArchive(
            path=Path(directory) / "archive.db", retention=timedelta(days=7), now=now
        )
        try:
            await archive.size()
        finally:
            archive.close()


async def _executor(now: Clock) -> None:
    """The executor reads the clock between the claim and the callable."""
    plans = FakePlanStore()
    execution_id = await _claimed(plans)
    invoker, trail = invoker_over([(_tool(), succeeds)])
    request = _request(execution_id=execution_id)
    decision = _decision(request)
    await trail.record(decision)
    state = await plans.get_execution(execution_id)
    assert state is not None
    await StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=now).execute(
        state,
        step_id="s1",
        call=ToolCall(request=request, decision=decision),
        timeout=timedelta(seconds=30),
    )


async def _runner(now: Clock) -> None:
    """The runner reads the clock to stamp the decision it records before executing."""
    plans = FakePlanStore()
    execution_id = await _claimed(plans)
    invoker, trail = invoker_over([(_tool(), succeeds)])
    state = await plans.get_execution(execution_id)
    assert state is not None
    await StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: _AWARE),
        now=now,
    ).run(state, "s1", timeout=timedelta(seconds=30), origin=NOTHING_EXTERNAL)


async def _store_health(now: Clock) -> None:
    """The report stamps the instant it was taken; synchronous, as the reader is."""
    with tempfile.TemporaryDirectory() as directory:
        store = Path(directory) / "memory.db"
        store.touch()
        StoreHealthReader(store=store, now=now).report()


async def _upcoming(now: Clock) -> None:
    """The stage reads the clock to place the lead window it notices within."""
    await UpcomingEventStage(
        reader=FakeReader(),
        grants=FakeSourceGrants([source_grant()]),
        writer=FakeNotificationWriter(
            store=FakeNotificationStore(now=lambda: _AWARE), policy=FakeNotificationPolicy()
        ),
        reads=FakeSourceReadRecorder(),
        now=now,
        lead=timedelta(hours=1),
    ).notice()


#: Every seam ADR-0026 §7 covers, verified against the code rather than the table:
#: ``FakeMemoryWriter`` is an eleventh the ADR's table predates (ADR-0028), and it
#: is in scope for §7's reason — it is a canonical double (#186).
SEAMS = [
    Seam("ClockContextSource", _clock_source, ContextError),
    # `context`'s other two seams take the *opposite* posture, and ADR-0026 §4 is
    # why both are right: §4 gives `ClockContextSource` `ContextError` because it is
    # the one **required** source, whose failure may not be degraded away. A granted
    # facet source is optional, so its clock fault is left to reach the assembler as
    # itself and become an absent facet like every other fault there (ADR-0008 §4).
    Seam("CalendarContextSource", _calendar_context_source, ClockReadingError),
    Seam("EmailContextSource", _email_context_source, ClockReadingError),
    Seam("PlanExecution", _plan_execution, PlanningError),
    Seam("InMemoryPlanStore", _in_memory_plan_store, PlanningError),
    Seam("InMemoryMemoryStore", _in_memory_store, MemoryStoreError),
    Seam("SqliteMemoryStore", _sqlite_store, MemoryStoreError),
    Seam("MemoryIngestor", _ingestor, MemoryStoreError),
    Seam("LearningLoop", _learning_loop, PlanningError),
    Seam("FakeMemoryStore", _fake_store, MemoryStoreError),
    Seam("FakeMemoryWriter", _fake_writer, MemoryStoreError),
    Seam("FakePlanner", _fake_planner, PlanningError),
    Seam("FakePlanStore", _fake_plan_store, PlanningError),
    # A twelfth, later than the ADR's table (ADR-0119 §10): the façade reads a
    # clock to place the trace horizon, so its error is the sweep's own.
    Seam("Engine", _engine, TraceStoreError),
    # The rest of the tree, added when the roster below made the omission visible
    # (#781). Nothing here is a new claim about what a seam *should* raise: each
    # row is what driving that seam's real entry point over a naive reading was
    # observed to produce, which is the only thing this table can honestly assert.
    Seam("ConsolidationStage", _consolidation, ClockReadingError),
    Seam("ConversationLifecycle", _conversation_lifecycle, ConversationStoreError),
    Seam("CurrentTime", _current_time, ClockReadingError),
    Seam("FakeAuditTrail", _fake_audit_trail, AuditError),
    Seam("FakeConversationStore", _fake_conversation_store, ConversationStoreError),
    Seam("FakeDeferralStore", _fake_deferral_store, DeferralStoreError),
    Seam("FakeFeedbackProcessor", _fake_feedback_processor, ClockReadingError),
    Seam("FakeNotificationOutbox", _fake_notification_outbox, NotificationOutboxError),
    Seam("FakeRecipientGrantStore", _fake_recipient_grant_store, ClockReadingError),
    Seam("FakeRecipientGrants", _fake_recipient_grants, ClockReadingError),
    Seam("FakeTranscriptArchive", _fake_transcript_archive, TranscriptArchiveError),
    Seam("IngestionStage", _ingestion, ClockReadingError),
    Seam("ModelBackedObserver", _observer, ClockReadingError),
    Seam("ModelBackedPlanner", _planner, PlanningError),
    Seam("ObservationStage", _observation, ClockReadingError),
    Seam("QuestionStage", _questions, DeferralStoreError),
    Seam("RuleBasedFeedbackProcessor", _rule_based_processor, ClockReadingError),
    Seam("SqliteAuditTrail", _sqlite_audit_trail, AuditError),
    Seam("SqliteConversationStore", _sqlite_conversation_store, ConversationStoreError),
    Seam("SqliteDeferralStore", _sqlite_deferral_store, DeferralStoreError),
    Seam("SqliteNotificationOutbox", _sqlite_notification_outbox, NotificationOutboxError),
    Seam("SqliteNotificationStore", _sqlite_notification_store, NotificationStoreError),
    Seam("SqlitePlanStore", _sqlite_plan_store, PlanningError),
    Seam("SqliteRecipientGrantStore", _sqlite_recipient_grant_store, ClockReadingError),
    Seam("SqliteTranscriptArchive", _sqlite_transcript_archive, TranscriptArchiveError),
    Seam("StepExecutor", _executor, PlanningError),
    Seam("StepRunner", _runner, PlanningError),
    Seam("StoreHealthReader", _store_health, ClockReadingError),
    Seam("UpcomingEventStage", _upcoming, ClockReadingError),
]


@pytest.mark.parametrize("seam", SEAMS, ids=[seam.label for seam in SEAMS])
async def test_every_seam_refuses_a_naive_reading_as_its_own_error(seam: Seam) -> None:
    """ADR-0026 §§4, 7: guarded everywhere, translated at each subsystem's boundary.

    ``core`` raises ``ValueError`` and nothing else — it cannot know what its
    caller will do with the failure — so a raw ``ValueError`` reaching a caller
    is the failure this asserts against. `orchestration` has no error of its own,
    so it borrows the reading stage's; a fake raises the error of the
    implementation it doubles, since a fake that leaked ``ValueError`` where the
    real store raises ``MemoryStoreError`` would certify a consumer's error
    handling against behaviour it never meets in production.
    """
    with pytest.raises(seam.error) as caught:
        await seam.drive(_naive_clock)

    assert seam.label in str(caught.value)


@pytest.mark.parametrize("seam", SEAMS, ids=[seam.label for seam in SEAMS])
async def test_no_seam_steals_a_failure_of_the_clock_itself(seam: Seam) -> None:
    """ADR-0026 §2's reading/invocation boundary, asserted where it can be lost.

    ``checked_clock`` keeps the invocation outside its guard, but that only
    survives if the seams can tell a refused *reading* from the clock's own
    failure. A boundary catching bare ``ValueError`` cannot, and would report
    "your clock returned a bad reading" for a clock provider that was simply
    down — destroying the type and cause §2 exists to preserve. Every rejection
    is therefore a ``ClockReadingError``, and every seam catches that.
    """
    with pytest.raises(ValueError, match="the clock provider is down") as caught:
        await seam.drive(_failing_clock)

    assert not isinstance(caught.value, ClockReadingError)
    assert not isinstance(caught.value, seam.error)


@dataclass(frozen=True)
class SwallowedSeam:
    """A seam whose clock fault costs the *observation* and never the work.

    The third posture, and the reason :data:`SEAMS` cannot state the whole set on
    its own: ADR-0119 §5 gives the Tier 2 instrument the opposite failure rule to
    every seam above it — "a clock that raises costs the trace and not the read".
    So a naive reading here raises nothing at all, the crossing returns what it
    was going to return, and the trace is emitted with **no** ``occurred_at``.

    That is not an exemption from ADR-0026 §7, which is about the *guard* and not
    about what a subsystem does with a rejection: the reading is checked, refused
    and labelled exactly as everywhere else, and ``memory/traces.py`` then catches
    it deliberately and logs ``trace_not_recorded``. Omitting these seams because
    they raise nothing is what would make the table's claim untrue — a clock that
    silently stopped being guarded here would look identical.

    Attributes:
        label: The seam, as ``owner`` names it. These two are the seams whose
            ``owner`` is the ``MemoryTraces`` constructor's argument, so they are
            among the labels :data:`COMPUTED_OWNERS` declares.
        drive: Builds the emitting object over the given clock and the given sink
            and drives one crossing of it, through the emitter's real entry point.
    """

    label: str
    drive: Callable[[Clock, FakeTraceSink], Coroutine[None, None, None]]


async def _nothing() -> None:
    """A crossing with no work in it, so the subject is the stamp alone."""


async def _ingestor_write_traces(now: Clock, sink: FakeTraceSink) -> None:
    """The ``MEMORY_WRITE`` emitter's own clock, which is not the ingestor's.

    ``traces_now`` is a second seam on the same object (ADR-0119 §3 stamps the
    instant on the emitter, not on the store), so the ingestor's ``now`` is left
    conforming: the reading under test is the instrument's.
    """
    await MemoryIngestor(
        traces_sink=sink,
        store=InMemoryMemoryStore(now=lambda: _AWARE),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT),
        now=lambda: _AWARE,
        traces_now=now,
    ).ingest(_proposal())


async def _store_retrieval_traces(now: Clock, sink: FakeTraceSink) -> None:
    """The ``RETRIEVAL`` emitter's own clock, on :func:`_ingestor_write_traces`'s rule."""
    store = SqliteMemoryStore(
        traces_sink=sink,
        path=":memory:",
        embedder=FakeEmbedder(),
        now=lambda: _AWARE,
        traces_now=now,
    )
    await store.search("coffee", limit=1)


async def _operation_traces(now: Clock, sink: FakeTraceSink) -> None:
    """The request façade's own emitter, which opens the correlation scope (§4).

    Driven over a crossing that does nothing, because the subject is the stamp and
    not the work: what §5 promises is that ``observing`` returns whatever ``work``
    returned however badly the clock is wired.
    """
    await OperationTraces(sink=sink, now=now).observing("converse", _nothing())


async def _configuration_stamp(now: Clock, sink: FakeTraceSink) -> None:
    """The hub's startup stamp, whose own docstring says it **never raises** (§5).

    The strongest case for the posture and the one most worth pinning: a hub that
    refused to start because the instrument's clock was misconfigured would have
    let Tier 2 tracing become a boot dependency.
    """
    await ConfigurationStamp(
        sink=sink, retrieval_search_limit=10, conflict_search_limit=12, now=now
    ).record(Settings(embedder=EmbedderKind.HASHING))


#: Every seam whose clock fault costs an observation and never the work: both
#: crossings of :class:`~ai_assistant.memory.traces.MemoryTraces` — the one seam
#: whose ``owner`` is a constructor argument — and the two emitters that take the
#: same posture on their own account.
SWALLOWING_SEAMS = [
    SwallowedSeam("MemoryIngestor write traces", _ingestor_write_traces),
    SwallowedSeam("SqliteMemoryStore retrieval traces", _store_retrieval_traces),
    SwallowedSeam("OperationTraces", _operation_traces),
    SwallowedSeam("ConfigurationStamp", _configuration_stamp),
]


@pytest.mark.parametrize(
    "clock", [_naive_clock, _failing_clock], ids=["a naive reading", "a clock that is down"]
)
@pytest.mark.parametrize("seam", SWALLOWING_SEAMS, ids=[seam.label for seam in SWALLOWING_SEAMS])
async def test_an_instruments_clock_fault_costs_the_trace_and_not_the_work(
    seam: SwallowedSeam, clock: Clock
) -> None:
    """ADR-0119 §5: the instrument's clock fault reaches the trace and stops there.

    A trace with no instant is not a trace ADR-0119 §3 can order, so the emitter
    drops the whole record rather than emitting a stamp-less one — the "absence
    travels to ``_record``" its own docstring describes. What §5 protects is the
    other side: the crossing completes and returns what it was going to return.
    An instrument that failed a memory write because its own clock was
    misconfigured would be the tail wagging the dog.

    Both halves are asserted, because the first alone is satisfied by an emitter
    that never emits anything: the same crossing is driven again over a conforming
    clock and has to produce the trace the faulted one did not. Without that, a
    seam whose instrumentation had been disconnected entirely would pass.

    Both clocks, because §5 draws no distinction: a refused *reading* and the
    clock's own failure are the same fact to an instrument that may not fail, and
    a guard that let one of them through would be caught only here.
    """
    faulted = FakeTraceSink()

    await seam.drive(clock, faulted)

    assert faulted.recorded == (), (
        f"{seam.label} emitted a trace from a clock that never produced a conforming "
        f"reading; an unstamped trace is one ADR-0119 §3 cannot order"
    )

    conforming = FakeTraceSink()
    await seam.drive(lambda: _AWARE, conforming)
    assert len(conforming.recorded) == 1, (
        f"{seam.label} emits no trace even over a conforming clock, so the assertion "
        f"above is vacuous and this seam is no longer instrumented at all"
    )


#: The reason shared by every seam that propagates without saying so: ADR-0026 §4
#: maps its subsystem, and nothing in its module mentions ``ClockReadingError`` at
#: all. That is the fact separating these from the six that argue the posture in
#: their own docstrings, and it is what #1966 asks to be settled.
_UNDECLARED: Final = (
    "#1966: undocumented — ADR-0026 §4 maps this seam's subsystem, and its module "
    "mentions ``ClockReadingError`` nowhere"
)

#: Seams that let `core`'s rejection reach their caller untranslated, and why
#: each is entitled to. ADR-0026 §4 enumerates the translation per subsystem; a
#: seam here is one whose subsystem the enumeration does not reach, or one whose
#: caller already has the right posture for a raw wiring bug. It is a
#: ``ValueError`` either way, so a caller holding only the ADR's promise still
#: catches it.
PROPAGATED: Final[dict[str, str]] = {
    "CalendarContextSource": (
        "an optional source, whose fault ADR-0008 §4 degrades to an absent facet; only "
        "the required ClockContextSource owes ContextError (ADR-0026 §4)"
    ),
    "EmailContextSource": "the second adapter of that one class",
    "ConsolidationStage": _UNDECLARED,
    "CurrentTime": ("documented at ``tools/builtin.py:148``, and `tools` is not in §4's list"),
    "FakeFeedbackProcessor": (
        "documented at ``testing/learning.py:207``, doubling a `learning` seam that propagates"
    ),
    "FakeRecipientGrantStore": _UNDECLARED,
    "FakeRecipientGrants": _UNDECLARED,
    "IngestionStage": _UNDECLARED,
    "ModelBackedObserver": (
        "documented at ``learning/observer.py:656``, and `learning` owns no error class"
    ),
    "ObservationStage": _UNDECLARED,
    "RuleBasedFeedbackProcessor": (
        "documented at ``learning/processor.py:146``, on the observer's precedent"
    ),
    "SqliteRecipientGrantStore": _UNDECLARED,
    "StoreHealthReader": _UNDECLARED,
    "UpcomingEventStage": _UNDECLARED,
}


def test_the_untranslated_seams_are_the_declared_ones() -> None:
    """A seam changing posture is a decision, so it may not happen silently.

    ADR-0026 §4's enumeration is per subsystem and does not reach every subsystem
    that now holds a seam, so "raises ``ClockReadingError``" is a real and stated
    answer rather than a hole. What it must not be is an accident: a seam that
    *stopped* translating would otherwise pass every assertion above by having its
    row edited to match, and a subsystem that gained an error class would leave the
    old posture behind with nothing to notice.
    """
    untranslated = {seam.label for seam in SEAMS if seam.error is ClockReadingError}
    assert untranslated == set(PROPAGATED), (
        f"{sorted(untranslated ^ set(PROPAGATED))} propagates or translates differently "
        f"from what ``PROPAGATED`` records; the posture is the decision, not the row"
    )
    translated = [seam for seam in SEAMS if seam.error is not ClockReadingError]
    assert all(issubclass(seam.error, AssistantError) for seam in translated), (
        f"{sorted(s.label for s in translated if not issubclass(s.error, AssistantError))} "
        f"translates into something that is not an ``AssistantError`` at all, which is "
        f"neither of the two postures ADR-0026 §4 admits"
    )


#: Seams whose ``owner=`` is a run-time expression, so no scan of the source can
#: name them: the unparsed expression maps to the labels it actually produces.
#: Each label is driven by a row of :data:`SEAMS` above, and
#: :func:`test_every_seam_refuses_a_naive_reading_as_its_own_error` asserts the
#: label appears in the rejection — which is what keeps this mapping honest
#: rather than a second declaration nothing checks.
COMPUTED_OWNERS: Final[dict[str, tuple[str, ...]]] = {
    "type(self).__name__": ("CalendarContextSource", "EmailContextSource"),
    "owner": ("MemoryIngestor write traces", "SqliteMemoryStore retrieval traces"),
}

#: Seams the roster below finds in ``src/`` that :data:`SEAMS` deliberately does
#: not drive, each with the reason it is not merely an omission. **Empty is the
#: intended state**; an entry here is a debt with an issue behind it, and the
#: partition assertion is what stops the list growing by accident.
UNTABLED: Final[dict[str, str]] = {
    "AdminListener": (
        "#1965: guarded, and its fault is caught by the connection handler's "
        "``except ValueError`` — the act is abandoned, the socket closed and nothing "
        "raised, so neither table above has an observable to assert on"
    ),
    "CalendarReader": (
        "#1963: translates the refused reading into ``ReaderError`` correctly, but "
        "ADR-0093 §8's blanket wrapper collapses the clock's *own* failure into the "
        "same type — so it fails ``test_no_seam_steals_a_failure_of_the_clock_itself``"
    ),
    "EmailReader": "#1963: the second reader, with ``CalendarReader``'s clause verbatim",
    "FakeNotificationStore": (
        "#1964: translates into ``NotificationStoreError`` correctly but replaces the "
        "guard's message with a constant, so the ``owner`` label the seam paid for is "
        "not in the rejection this module asserts on"
    ),
}


def _clock_seam_roster() -> tuple[frozenset[str], frozenset[str]]:
    """Every ``checked_clock`` call in ``src/``, read out of the source itself.

    Parsed rather than imported, because an import-time roster would only see the
    seams whose modules something in this test happened to load — the failure mode
    a roster exists to prevent. ``core/clock.py`` is skipped: the ``checked_clock``
    inside it is the definition, not a seam.

    Returns:
        The ``owner`` labels written as string literals, and the ``owner``
        expressions computed at run time, unparsed.
    """
    literal: set[str] = set()
    computed: set[str] = set()
    definition = Path(clock.__file__)
    for path in sorted(Path(ai_assistant.__file__).parent.rglob("*.py")):
        if path == definition:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
            if name != "checked_clock":
                continue
            owner = next((kw.value for kw in node.keywords if kw.arg == "owner"), None)
            if isinstance(owner, ast.Constant) and isinstance(owner.value, str):
                literal.add(owner.value)
            else:
                computed.add("<positional or absent>" if owner is None else ast.unparse(owner))
    return frozenset(literal), frozenset(computed)


def test_the_seam_table_is_the_whole_set() -> None:
    """A new seam that forgets the guard has to be added here to pass anything.

    The labels are the ``owner`` strings, and a seam whose label drifts from its
    constructor fails the parametrised assertions above. What this adds is the half
    those cannot see: the seams that exist in ``src/`` and are *not* in the table.
    Twelve rows stood against forty-nine seams for long enough that the module's
    stated subject — "the *set*" — was true of a quarter of it (#781), because
    nothing failed on the day the table stopped growing.

    So the roster is **discovered** rather than declared: the source is parsed for
    every ``checked_clock(owner=…)`` and the table is asserted to partition it. A
    seam added tomorrow fails here, naming itself.

    It is still not a proof of the *guard* — nothing can mechanically discover a
    clock that was never wrapped at all — but it is a proof of the *table*, which
    is the half that had gone stale.
    """
    assert len({seam.label for seam in SEAMS}) == len(SEAMS)
    assert len({seam.label for seam in SWALLOWING_SEAMS}) == len(SWALLOWING_SEAMS)

    literal, computed = _clock_seam_roster()
    assert literal, "the roster scan found no seam at all, so nothing below is evidence"
    assert computed == frozenset(COMPUTED_OWNERS), (
        f"the run-time ``owner=`` expressions in ``src/`` are {sorted(computed)}, but "
        f"``COMPUTED_OWNERS`` declares {sorted(COMPUTED_OWNERS)}; a seam whose owner is "
        f"computed has to name the labels it produces here, because no scan can read them"
    )

    tabled = {seam.label for seam in SEAMS} | {seam.label for seam in SWALLOWING_SEAMS}
    roster = literal | {label for labels in COMPUTED_OWNERS.values() for label in labels}
    assert tabled - roster == set(), (
        f"{sorted(tabled - roster)} is tabled here but reads no clock in ``src/``: a "
        f"label that drifted from its constructor, or a seam that has been removed"
    )
    assert roster - tabled == set(UNTABLED), (
        f"{sorted(roster - tabled - set(UNTABLED))} guards a clock in ``src/`` and is "
        f"is driven by no table here and recorded in ``UNTABLED`` with no reason"
    )
