"""Every injected-clock seam is guarded, and each refuses a bad reading its own way.

ADR-0026 §7 is uniformity with **no advisory exemption**: a seam that produces a
float, a seam that only stamps an export, and a seam whose instant is advisory
all guard alike, because a seam cannot know the provenance of the reading it was
handed and so cannot know whether attributing UTC restores a fact or invents one.

This module is deliberately cross-subsystem, which no per-package test file can
be. Its subject is the *set*: a new seam that forgets the guard, or an existing
one whose translation drifts to the wrong ``AssistantError``, fails here rather
than being noticed in review. ``tests/core/test_clock.py`` pins what the guard
does; this pins that every seam has it.

**The set is discovered, not declared.** That sentence was untrue of about three
quarters of the tree until #781: twelve rows stood against fifty-one seams, and
the table stopped growing without a single test failing. So ``src/`` is now
parsed for every ``checked_clock(owner=…)`` and the tables below are asserted to
partition the result — a seam added tomorrow fails
:func:`test_the_seam_table_is_the_whole_set` on the day it is added, naming
itself.

**Three postures, because the tree takes three**, and they are stated rather than
silently mixed. :data:`SEAMS` drives a seam that *raises* — the subsystem's own
``AssistantError`` where ADR-0026 §4 assigns one, or ``ClockReadingError`` itself
where the subsystem deliberately lets `core`'s rejection through, with the reason
recorded per seam in :data:`PROPAGATED`. :data:`SWALLOWING_SEAMS` drives the Tier
2 instruments, whose clock fault ADR-0119 §5 makes cost the trace and never the
work. :data:`UNTABLED` records what neither can drive, each entry naming the
finding behind it rather than leaving a hole nothing can see.

The `testing/` fakes are in scope for the reason they exist (ADR-0026 §7): they
are the canonical doubles consumers certify against, and a fake looser than the
contract certifies consumers the real implementation will reject.
"""

from __future__ import annotations

import ast
import tempfile
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
import structlog.testing
from structured_support import structured

import ai_assistant
from ai_assistant.core import clock
from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    ConversationStoreError,
    MemoryStoreError,
    NotificationOutboxError,
    NotificationStoreError,
    PersonModelStoreError,
    PlanningError,
    StoryStoreError,
    TraceStoreError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    CostBasis,
    DataTier,
    EpisodicMemory,
    Idempotency,
    LabelBounds,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PersonActHow,
    PersonModelAct,
    PlanningRound,
    ProfileField,
    ProposedCall,
    Provenance,
    Reversibility,
    RiskLevel,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    TextChannelPayload,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.memory import (
    InMemoryMemoryStore,
    MemoryIngestor,
    SqliteMemoryStore,
    SqliteNotificationOutbox,
    SqliteNotificationStore,
    SqliteStoryStore,
)
from ai_assistant.memory import traces as memory_traces
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.health import StoreHealthReader
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.orchestration import (
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    UpcomingEventStage,
)
from ai_assistant.orchestration import traces as operation_traces
from ai_assistant.orchestration.acting import ActingStage, AuthorizedCall, AuthorizedRound
from ai_assistant.orchestration.activation_coordinator import ActivationCoordinator
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundAuthorization,
    RoundToAuthorize,
    WorkingRecord,
)
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT, ActivationLabels, DigestingStage
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.held_results import HeldResult, HeldResults
from ai_assistant.orchestration.observer import Observer, ObserverLimits
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.phase_path import PhasePath, PhaseTools, PhaseWorking
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    PlaceWindow,
    PlannedRound,
    PlanningInputs,
    PlanningStage,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.story_tidy_up import (
    STORY_TIDY_UP_PROMPT,
    ScheduledTidyUp,
    StoryTidyUp,
)
from ai_assistant.orchestration.traces import OperationTraces
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.orchestration.writes import MemoryWriteStage
from ai_assistant.permissions import (
    SqliteAuditTrail,
)
from ai_assistant.planning import (
    InMemoryPlanStore,
    SqlitePlanStore,
)
from ai_assistant.readers._locality import DeviceBacking, MountClaim
from ai_assistant.readers.files import LocalFileFetcher
from ai_assistant.service import configuration
from ai_assistant.service.configuration import ConfigurationStamp
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeConversationStore,
    FakeEmbedder,
    FakeFetcher,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeNotificationWriter,
    FakePersonModelStore,
    FakePlanStore,
    FakeReader,
    FakeSourceGrants,
    FakeSourceGrantStore,
    FakeSourceReadRecorder,
    FakeSourceReadTrail,
    FakeStoryStore,
    FakeToolCallingCompleter,
    FakeToolRegistry,
    FakeTraceRetention,
    FakeTraceSink,
    default_prompt,
    source_grant,
)
from ai_assistant.testing.memories import HELD_EPISODE, memory
from ai_assistant.tools.builtin import CurrentTime

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Coroutine

    from ai_assistant.core.clock import Clock


def _goal_ids(prefix: str) -> Callable[[], str]:
    """Distinct identifiers, ``<prefix>-1`` first: an id per call, as ``uuid4`` gives."""
    count = 0

    def factory() -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return factory


#: A naive reading: the one every seam used to accept and now must refuse.
_NAIVE = datetime(2026, 7, 21, 12)  # noqa: DTZ001 — the naive reading is the subject
_AWARE = datetime(2026, 7, 21, 12, tzinfo=UTC)


def _naive_clock() -> datetime:
    return _NAIVE


def _failing_clock() -> datetime:
    """A clock that fails on its own account, with the type seams must not steal."""
    msg = "the clock provider is down"
    raise ValueError(msg)


def _record(*, expires_at: datetime | None = None, record_id: str = "m1") -> Memory:
    """A memory carrying an expiry, since that is what makes a store read its clock."""
    return memory(record_id, "the user drinks coffee", expires_at=expires_at)


def _proposal() -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=_record(), rationale="the user said so")


async def _held_episode(store: InMemoryMemoryStore | FakeMemoryStore) -> None:
    """The episode a proposal's support points into (ADR-0328 §4:7)."""
    await store.add(
        EpisodicMemory(
            id=HELD_EPISODE,
            content="the user said they drink coffee",
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AWARE
            ),
            occurred_at=_AWARE,
        )
    )


async def _held(store: InMemoryMemoryStore | FakeMemoryStore) -> None:
    """The episode the proposal's support points into, and a memory it reinforces.

    A ``REINFORCE`` is the ruling whose added support's ``added_at`` the writer stamps
    from its clock (ADR-0328 §5), through ``model_copy(update=...)``, past every
    validator; the writer refuses a proposal whose support's episode it does not hold
    (ADR-0328 §4:7), so the episode is seeded too.
    """
    await _held_episode(store)
    await store.add(_record(record_id="m0"))


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
    store = InMemoryMemoryStore(now=lambda: _AWARE)
    await _held(store)
    await MemoryIngestor(
        traces_sink=FakeTraceSink(),
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
        now=now,
    ).ingest(_proposal())


async def _fake_store(now: Clock) -> None:
    store = FakeMemoryStore(now=now)
    await store.add(_record(expires_at=_AWARE))
    await store.get("m1")


async def _fake_writer(now: Clock) -> None:
    store = FakeMemoryStore(now=lambda: _AWARE)
    await _held(store)
    await FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
        now=now,
    ).ingest(_proposal())


async def _acting_stage(now: Clock) -> None:
    """ADR-0306 §6's ``claimed_at``, read where acting builds the record it claims.

    Driven through ``act`` on a round with one call in the world, which is claimed
    before it runs, so the reading is taken before anything is invoked.
    """
    tool = ToolDefinition(
        id="book",
        capability="book",
        description="Book a stay.",
        risk_level=RiskLevel.HIGH,
        reversibility=Reversibility.IRREVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(DataTier.PERSONAL,),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NONE,
        effect=CapabilityEffect.WORLD,
        leaves_hub=True,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=True,
        safe_to_repeat=False,
    )
    request = ActionRequest(tool=tool)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="d-1",
        decided_at=_AWARE,
        effect="e-1",
    )

    class _Unreached:
        async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
            raise AssertionError

        async def run(self, call: ToolCall) -> ToolResult:
            raise AssertionError

    await ActingStage(
        plans=FakePlanStore(),
        invoker=_Unreached(),
        own_records=_Unreached(),
        timeout=timedelta(seconds=5),
        now=now,
    ).act(
        held=HeldResults(),
        authorized=AuthorizedRound(
            activation_id="act-1",
            round_id="r-1",
            calls=(AuthorizedCall(ToolCall(request=request, decision=decision)),),
        ),
    )


async def _authorizing_stage(now: Clock) -> None:
    """ADR-0037 §2's ``decided_at``, read where a ruling is bound to its request.

    Driven through ``authorize``: selection, the activation's record and the policy all
    run first, and the reading is the last thing before the trail is written.
    """
    planned = ProposedCall(
        call_id="c-1",
        name="remember",
        arguments={"fact": "The user likes tea.", "why": "a taste", "rests_on_input": True},
    )
    await AuthorizingStage(
        registry=FakeToolRegistry([REMEMBER_CANDIDATE]),
        policy=FakeActionPolicy(),
        trail=FakeAuditTrail(),
        stories=FakeStoryStore(),
        memory=FakeMemoryStore(),
        now=now,
    ).authorize(
        RoundToAuthorize(
            activation_id="act-1",
            round=PlanningRound(id="r-1", recorded_at=_AWARE, calls=(planned,)),
            working=WorkingRecord(),
            calls=(CallToAuthorize(planned),),
        )
    )


async def _digesting_stage(now: Clock) -> None:
    """ADR-0308 §4:11's deadline, read as a digest starts, and §7's ``recorded_at``.

    Driven through ``digest_result``: the deadline is read first, before any part's call
    is made or anything is recorded.
    """

    class _Unreached:
        async def record(self, digest: object, labels: object) -> None:
            raise AssertionError

    await DigestingStage(
        provider=structured(FakeModelProvider()),
        recorder=_Unreached(),
        part_chars=50,
        now=now,
        prompt=default_prompt(DIGESTING_PROMPT),
    ).digest_result(
        HeldResult(result_id="result:1", round_id="r-1", decision_id="d-1", content="a page"),
        question="hours",
        labels=ActivationLabels(),
        deadline=_AWARE,
    )


async def _planning_stage(now: Clock) -> None:
    """ADR-0307 §6's current time, read as planning renders its round's request.

    Driven through ``plan``: the reading is the first thing the round takes, before the
    model is asked or anything is recorded.
    """

    class _Unreached:
        async def record(self, planning_round: object, labels: object) -> None:
            raise AssertionError

    await PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=FakeToolCallingCompleter(),
        recorder=_Unreached(),
        excerpt_chars=50,
        now=now,
    ).plan(PlanningInputs(activation_id="act-1", place=PlaceWindow(takes_message=True)))


_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())


@dataclass
class _PhasePass:
    """A pass the phases plan, as a phase stage reads it: its deadline far off."""

    phases: PhaseWorking
    deadline: float = 1e18
    understanding: None = None
    understanding_fetch: None = None
    supply: BoundedAudienceSupply = field(default_factory=lambda: _BOUNDED)
    windows: None = None
    recalled: None = None
    story_candidates: None = None


async def _phase_path(now: Clock) -> None:
    """ADR-0309 §3:3's step start, read as a round's acting stage begins.

    Driven through the acting stage the path hands the controller: the step's start is
    its first reading, before any call runs or any message is claimed. A stage
    classifies what it raised, so the driver raises the error its result carries.
    """

    class _Unreached:
        async def send(self, *args: object) -> object:
            raise AssertionError

    path = PhasePath(
        planning_prompt=default_prompt(PLANNING_PROMPT),
        completer=FakeToolCallingCompleter(),
        provider=structured(FakeModelProvider()),
        authorizing=_Unreached(),  # type: ignore[arg-type]  # never reached
        acting=_Unreached(),  # type: ignore[arg-type]  # never reached
        tools=PhaseTools(registry=FakeToolRegistry([]), invoker=_Unreached()),  # type: ignore[arg-type]  # never reached
        plans=FakePlanStore(),
        writer=_Unreached(),  # type: ignore[arg-type]  # never reached
        capabilities=(),
        round_limit=1,
        round_wait=timedelta(seconds=5),
        excerpt_chars=50,
        part_chars=50,
        memory=FakeMemoryStore(),
        recall_cap=1,
        recall_digest_wait=timedelta(seconds=5),
        now=now,
        digesting_prompt=default_prompt(DIGESTING_PROMPT),
    )
    working = PhaseWorking(
        activation_id="act-1",
        place=PlaceWindow(takes_message=True),
        conversation_id="c-1",
        trigger=None,
        owner_records=True,
        round_limit=1,
    )
    working.planned(
        PlannedRound(round=PlanningRound(id="r-1", recorded_at=_AWARE), labels=(), recorded=True)
    )
    working.latest.authorization = RoundAuthorization(activation_id="act-1", round_id="r-1")
    result = await path.stages()[2].run(_PhasePass(working))
    if result.error is not None:
        raise result.error


@dataclass(frozen=True)
class _VouchingTables:
    """A platform view that vouches for one real directory, truthfully about its device.

    ADR-0230 §6 decides eligibility in two stages, and stage 2 checks the opened mount
    root's device identity against what stage 1 claimed — so a view that names the
    directory itself, with the device the kernel reports for it, passes the check while
    saying nothing this test has not verified.
    """

    root: Path

    def claim_for(self, path: Path) -> MountClaim:
        """What the tables say about the mount the fetch root falls under."""
        return MountClaim(
            mount_point=self.root,
            filesystem_type="tmpfs",
            device=self.root.stat().st_dev,
            backing=DeviceBacking.LOCAL,
        )


async def _fake_fetcher(now: Clock) -> None:
    """The canonical ``Fetcher`` double's clock, guarded like the seam it stands in for.

    ADR-0026 §7 is uniformity with no advisory exemption, and this module's own opening
    says why the fakes are in scope: "they are the canonical doubles consumers certify
    against, and a fake looser than the contract certifies consumers the real
    implementation will reject."
    """
    await FakeFetcher({"note.md": "text"}, now=now).listing()


async def _local_file_fetcher(now: Clock) -> None:
    """The fetch seam's wall clock: read at acquisition, on the loop (ADR-0230 §4).

    Driven through ``listing()``, which is where the clock is read — for the listing's
    ``read_at`` and for one of the two expiry deadlines — and read **before** anything
    is dispatched off the loop, so a bad reading is the caller's fault rather than a
    worker thread's.

    **The platform view is supplied**, for the reason
    ``tests/readers/fetch_fixtures.py`` states: ``ProcPlatformTables`` is fail-closed
    by decision (ADR-0230 §6), so a container's ``overlay`` root or a CI runner's
    device chain may legitimately refuse to establish locality — and a clock test has
    no business being decided by the machine it runs on.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fetcher = LocalFileFetcher(root, now=now, tables=_VouchingTables(root))
        try:
            await fetcher.listing()
        finally:
            fetcher.close()


async def _observer(now: Clock) -> None:
    """ADR-0329 §16's clock, read as a run takes its queue (§16:2).

    Driven through ``run``, over the canonical fakes on a conforming clock, so the reading
    under test is the stage's own: the queue's instant is the first thing a run reads.
    """

    def conforming() -> datetime:
        return _AWARE

    memory = FakeMemoryStore(now=conforming)
    writer = FakeMemoryWriter(
        store=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT), now=conforming
    )
    await Observer(
        scout=structured(FakeModelProvider()),
        commit=structured(FakeModelProvider()),
        memory=memory,
        writes=MemoryWriteStage(writer=writer),
        plans=FakePlanStore(now=conforming),
        stories=FakeStoryStore(now=conforming),
        episodes=RecentEpisodes(memory=memory, limit=2),
        limits=ObserverLimits(
            since=_AWARE,
            relevance=0.5,
            retrieved=1,
            recent_supports=1,
            stale_retries=1,
            labels=LabelBounds(max_labels=1, max_chars=10, min_distance=0.1),
            retry_base=timedelta(minutes=1),
            retry_cap=timedelta(hours=1),
            stuck_after=1,
            per_run=1,
            daily_calls=1,
        ),
        now=now,
        scout_prompt=default_prompt(OBSERVER_SCOUT_PROMPT),
        framing_prompt=default_prompt(OBSERVER_FRAMING_PROMPT),
        placement_prompt=default_prompt(OBSERVER_PLACEMENT_PROMPT),
    ).run()


async def _scheduled_tidy_up(now: Clock) -> None:
    """ADR-0358 §4:2's quiet period, measured from the clock as a run finds what is due.

    Driven through ``run``, over the canonical fakes on a conforming clock, so the reading
    under test is the run's own: it is the first thing a run reads, store or no story.
    """

    def conforming() -> datetime:
        return _AWARE

    stories = FakeStoryStore(now=conforming)
    memory = FakeMemoryStore(now=conforming)
    await ScheduledTidyUp(
        tidy_up=StoryTidyUp(
            model=structured(FakeModelProvider()),
            stories=stories,
            memory=memory,
            excerpt_chars=10,
            other_stories=0,
            decisions=0,
            budget=timedelta(minutes=1),
            threshold=0.0,
            prompt=default_prompt(STORY_TIDY_UP_PROMPT),
        ),
        stories=stories,
        threshold=1,
        quiet=timedelta(hours=1),
        per_run=1,
        budget=timedelta(minutes=1),
        now=now,
    ).run()


async def _fake_plan_store(now: Clock) -> None:
    await FakePlanStore(now=now).export()


async def _in_memory_plan_store(now: Clock) -> None:
    await InMemoryPlanStore(now=now).export()


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
    plans = FakePlanStore(now=lambda: _AWARE)
    await Engine(
        chat_reader=False,
        plans=plans,
        trail=FakeAuditTrail(),
        spend=FakeAuditTrail(),
        reads=FakeSourceReadTrail(),
        memory=memory,
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: _AWARE,
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
    ).purge_expired()


def _tool() -> ToolDefinition:
    """The one side-effecting tool the permission seams are driven over."""
    return ToolDefinition(
        id="smtp",
        capability="send_email",
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
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


def _request() -> ActionRequest:
    """The one request the permission seams are driven over."""
    return ActionRequest(tool=_tool(), parameters={})


def _decision(request: ActionRequest) -> PermissionDecision:
    """The ``ALLOW`` recorded for ``request``."""
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because the user said so"),
        id="d1",
        decided_at=_AWARE,
    )


# ---- drivers -------------------------------------------------------------


async def _conversation_lifecycle(now: Clock) -> None:
    """The retention reclaim reads the clock to place the episodic horizon."""
    await ConversationLifecycle(
        conversations=FakeConversationStore(now=lambda: _AWARE),
        memory=FakeMemoryStore(now=lambda: _AWARE),
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


async def _fake_notification_outbox(now: Clock) -> None:
    """A claim reads the clock to settle leases before it answers."""
    await FakeNotificationOutbox(now=now).claim()


async def _fake_notification_store(now: Clock) -> None:
    """The retention purge reads the clock, as the durable store's does (#1964)."""
    await FakeNotificationStore(now=now).purge()


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


async def _fake_story_store(now: Clock) -> None:
    """A create stamps the story and its log lines from the store's own clock."""
    await FakeStoryStore(now=now).create(
        [StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1")], actor=StoryActor.OWNER
    )


async def _fake_person_model_store(now: Clock) -> None:
    """A field's write stamps its change from the store's own clock (ADR-0338 §3:5)."""
    act = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
    await FakePersonModelStore(now=now).set_field(
        OWNER_PERSON_ID, ProfileField.NAME, "Robin", act=act
    )


async def _sqlite_person_model_store(now: Clock) -> None:
    """Creating the store stamps the owner, and a field's write its change (ADR-0338 §3:5)."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqlitePersonModelStore(
            path=Path(directory) / "person_model.db", field_chars=200, now=now
        )
        try:
            act = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
            await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin", act=act)
        finally:
            store.close()


async def _sqlite_story_store(now: Clock) -> None:
    """A create stamps the story and its log lines from the store's own clock."""
    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStoryStore(path=Path(directory) / "stories.db", now=now)
        try:
            await store.create(
                [StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1")], actor=StoryActor.OWNER
            )
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


#: Every seam that answers a refused reading by *raising*, verified against the
#: code rather than against ADR-0026's own table — which predates most of them.
#: ``FakeMemoryWriter`` was the first of those (ADR-0028), in scope for §7's
#: reason: it is a canonical double (#186).
SEAMS = [
    # ADR-0230 §4's fetch seam, propagating rather than translating for the reason
    # `PROPAGATED` records: that ADR adds **no** error class to `core.errors`, because
    # "there is no failure a caller would handle differently from a refusal it must
    # already handle" — and a clock fault is not a source reason, so it is not one of
    # the refusals either.
    Seam("LocalFileFetcher", _local_file_fetcher, ClockReadingError),
    Seam("FakeFetcher", _fake_fetcher, ClockReadingError),
    Seam("InMemoryPlanStore", _in_memory_plan_store, PlanningError),
    Seam("InMemoryMemoryStore", _in_memory_store, MemoryStoreError),
    Seam("SqliteMemoryStore", _sqlite_store, MemoryStoreError),
    Seam("MemoryIngestor", _ingestor, MemoryStoreError),
    # ADR-0306 §6's record clock, propagating for the reason `PROPAGATED` records.
    Seam("ActingStage", _acting_stage, ClockReadingError),
    # ADR-0037 §2's decision stamp, propagating for `ActingStage`'s reason one phase over.
    Seam("AuthorizingStage", _authorizing_stage, ClockReadingError),
    # ADR-0307 §6's current time, propagating for `ActingStage`'s reason one phase over.
    Seam("PlanningStage", _planning_stage, ClockReadingError),
    # ADR-0308 §4:11's deadline, propagating for `PlanningStage`'s reason one phase over.
    Seam("DigestingStage", _digesting_stage, ClockReadingError),
    # ADR-0309 §3:3's step start, propagating for `ActingStage`'s reason: the glue that
    # runs the phases adds no error class either.
    Seam("PhasePath", _phase_path, ClockReadingError),
    # ADR-0329 §16's queue instant, propagating for `ActingStage`'s reason: the
    # observer's stage adds no error class either.
    Seam("Observer", _observer, ClockReadingError),
    # ADR-0358 §4:2's quiet period, propagating for `Observer`'s reason: the scheduled
    # tidy-up adds no error class either.
    Seam("ScheduledTidyUp", _scheduled_tidy_up, ClockReadingError),
    Seam("FakeMemoryStore", _fake_store, MemoryStoreError),
    Seam("FakeMemoryWriter", _fake_writer, MemoryStoreError),
    Seam("FakePlanStore", _fake_plan_store, PlanningError),
    # A twelfth, later than the ADR's table (ADR-0119 §10): the façade reads a
    # clock to place the trace horizon, so its error is the sweep's own.
    Seam("Engine", _engine, TraceStoreError),
    # The rest of the tree, added when the roster below made the omission visible
    # (#781). Nothing here is a new claim about what a seam *should* raise: each
    # row is what driving that seam's real entry point over a naive reading was
    # observed to produce, which is the only thing this table can honestly assert.
    Seam("ConversationLifecycle", _conversation_lifecycle, ConversationStoreError),
    Seam("CurrentTime", _current_time, ClockReadingError),
    Seam("FakeAuditTrail", _fake_audit_trail, AuditError),
    Seam("FakeConversationStore", _fake_conversation_store, ConversationStoreError),
    Seam("FakeNotificationOutbox", _fake_notification_outbox, NotificationOutboxError),
    Seam("FakeNotificationStore", _fake_notification_store, NotificationStoreError),
    Seam("SqliteAuditTrail", _sqlite_audit_trail, AuditError),
    Seam("SqliteConversationStore", _sqlite_conversation_store, ConversationStoreError),
    Seam("FakeStoryStore", _fake_story_store, StoryStoreError),
    Seam("FakePersonModelStore", _fake_person_model_store, PersonModelStoreError),
    Seam("SqlitePersonModelStore", _sqlite_person_model_store, PersonModelStoreError),
    Seam("SqliteStoryStore", _sqlite_story_store, StoryStoreError),
    Seam("SqliteNotificationOutbox", _sqlite_notification_outbox, NotificationOutboxError),
    Seam("SqliteNotificationStore", _sqlite_notification_store, NotificationStoreError),
    Seam("SqlitePlanStore", _sqlite_plan_store, PlanningError),
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
        label: The seam, as ``owner`` names it.
        drive: Builds the emitting object over the given clock and the given sink
            and drives one crossing of it, through the emitter's real entry point.
        event: The emitter module's own ``trace_not_recorded`` constant. Each of
            the three modules declares the literal separately and says why in its
            own comment, so the row takes the one its emitter will log rather than
            a shared copy this module would have to keep in step.
        kind: The ``kind`` field §5's loss record carries, which is what
            distinguishes the two ``MemoryTraces`` crossings from each other.
        seam: The ``seam`` field of the same record — §5's third named field, and
            the one an emitter can regress on while ``kind`` and ``error_class``
            stay right. Taken from the emitting module's own constant where it has
            one, so a renamed seam fails here rather than being asserted against a
            copy of the old name.
    """

    label: str
    drive: Callable[[Clock, FakeTraceSink], Coroutine[None, None, None]]
    event: str
    kind: str
    seam: str


#: The crossing label ``_operation_traces`` drives, named once so the driver and
#: the row it is asserted against cannot drift apart.
_OPERATION_SEAM: Final = "converse"


async def _nothing() -> None:
    """A crossing with no work in it, so the subject is the stamp alone."""


async def _ingestor_write_traces(now: Clock, sink: FakeTraceSink) -> None:
    """The ``MEMORY_WRITE`` emitter's own clock, which is not the ingestor's.

    ``traces_now`` is a second seam on the same object (ADR-0119 §3 stamps the
    instant on the emitter, not on the store), so the ingestor's ``now`` is left
    conforming: the reading under test is the instrument's.
    """
    store = InMemoryMemoryStore(now=lambda: _AWARE)
    await _held_episode(store)
    await MemoryIngestor(
        traces_sink=sink,
        store=store,
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
    await OperationTraces(sink=sink, now=now).observing(_OPERATION_SEAM, _nothing())


async def _configuration_stamp(now: Clock, sink: FakeTraceSink) -> None:
    """The hub's startup stamp, whose own docstring says it **never raises** (§5).

    The strongest case for the posture and the one most worth pinning: a hub that
    refused to start because the instrument's clock was misconfigured would have
    let Tier 2 tracing become a boot dependency.
    """
    await ConfigurationStamp(sink=sink, conflict_search_limit=12, now=now).record(
        Settings(embedder=EmbedderKind.HASHING)
    )


#: Every seam whose clock fault costs an observation and never the work: both
#: crossings of :class:`~ai_assistant.memory.traces.MemoryTraces` — the one seam
#: whose ``owner`` is a constructor argument — and the two emitters that take the
#: same posture on their own account.
SWALLOWING_SEAMS = [
    SwallowedSeam(
        "MemoryIngestor write traces",
        _ingestor_write_traces,
        memory_traces.TRACE_NOT_RECORDED,
        "memory_write",
        memory_traces.SEAM_INGEST,
    ),
    SwallowedSeam(
        "SqliteMemoryStore retrieval traces",
        _store_retrieval_traces,
        memory_traces.TRACE_NOT_RECORDED,
        "retrieval",
        memory_traces.SEAM_SEARCH,
    ),
    SwallowedSeam(
        "OperationTraces",
        _operation_traces,
        operation_traces.TRACE_NOT_RECORDED,
        "operation",
        _OPERATION_SEAM,
    ),
    SwallowedSeam(
        "ConfigurationStamp",
        _configuration_stamp,
        configuration.TRACE_NOT_RECORDED,
        "configuration",
        configuration.SEAM_STARTUP,
    ),
]


@pytest.mark.parametrize(
    ("clock", "refusal"),
    [(_naive_clock, "ClockReadingError"), (_failing_clock, "ValueError")],
    ids=["a naive reading", "a clock that is down"],
)
@pytest.mark.parametrize("seam", SWALLOWING_SEAMS, ids=[seam.label for seam in SWALLOWING_SEAMS])
async def test_an_instruments_clock_fault_costs_the_trace_and_not_the_work(
    seam: SwallowedSeam, clock: Clock, refusal: str
) -> None:
    """ADR-0119 §5: the instrument's clock fault reaches the trace and stops there.

    A trace with no instant is not a trace ADR-0119 §3 can order, so the emitter
    drops the whole record rather than emitting a stamp-less one — the "absence
    travels to ``_record``" its own docstring describes. What §5 protects is the
    other side: the crossing completes and returns what it was going to return.
    An instrument that failed a memory write because its own clock was
    misconfigured would be the tail wagging the dog.

    **The loss is loud, and that is what proves the guard is still there.** All
    three fields §5 requires are asserted — the kind, the seam and the failure's
    class, because "a measure over a stream with dropped rows reports a
    smaller numerator and does not know it". Asserting only the externally visible
    outcome — no trace, work completed — would be satisfied by an emitter that had
    stopped calling ``checked_clock`` altogether: a naive instant handed straight
    to ``EvaluationTrace.occurred_at`` fails ``UtcInstant``'s validator instead,
    the same broad handler drops the same trace, and the work still completes. The
    two are told apart only by ``error_class``, which is ``ClockReadingError``
    when the guard refused the reading and would be a ``ValidationError`` if
    nothing had.

    Both clocks, because §5 draws no distinction: a refused *reading* and the
    clock's own failure are the same fact to an instrument that may not fail, and
    a guard that let one of them through would be caught only here.
    """
    faulted = FakeTraceSink()

    with structlog.testing.capture_logs() as captured:
        await seam.drive(clock, faulted)

    assert faulted.recorded == (), (
        f"{seam.label} emitted a trace from a clock that never produced a conforming "
        f"reading; an unstamped trace is one ADR-0119 §3 cannot order"
    )
    losses = [record for record in captured if record["event"] == seam.event]
    assert len(losses) == 1, (
        f"{seam.label} dropped its trace without leaving exactly one {seam.event!r} "
        f"record; §5 forbids a silent loss"
    )
    assert losses[0]["kind"] == seam.kind
    assert losses[0]["seam"] == seam.seam, (
        f"{seam.label} named {losses[0]['seam']!r} as the crossing it lost, not "
        f"{seam.seam!r}; §5's record has to name the seam it is a record of"
    )
    assert losses[0]["error_class"] == refusal, (
        f"{seam.label} lost its trace to a {losses[0]['error_class']}, not to the guard "
        f"refusing the reading — which is what an unguarded seam handing a naive instant "
        f"to ``UtcInstant``'s validator would look like from outside"
    )

    conforming = FakeTraceSink()
    await seam.drive(lambda: _AWARE, conforming)
    assert len(conforming.recorded) == 1, (
        f"{seam.label} emits no trace even over a conforming clock, so the assertions "
        f"above are vacuous and this seam is no longer instrumented at all"
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
    "FakeFetcher": "the canonical double of the seam below, with its clause verbatim",
    "LocalFileFetcher": (
        "ADR-0230 §4 adds **no** error class to `core.errors` — a source failure is a "
        "`FetchRefusal` rather than a raise — and a clock fault is not a source reason, "
        "so `core`'s own rejection is what a caller sees"
    ),
    "ActingStage": (
        "ADR-0306 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a refusal of the call: no record was claimed and nothing ran"
    ),
    "AuthorizingStage": (
        "ADR-0306 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a ruling: nothing was recorded and nothing runs"
    ),
    "PlanningStage": (
        "ADR-0307 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a round: no model was asked and nothing was recorded"
    ),
    "DigestingStage": (
        "ADR-0308 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is none of §4:11's three failures — a call that raised, a reply "
        "that did not parse, a deadline passed — so it is not a failed digest: no "
        "model was asked and nothing was recorded"
    ),
    "PhasePath": (
        "ADR-0309 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a round's outcome: no call ran and no message was claimed"
    ),
    "Observer": (
        "ADR-0329 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a failed attempt: no episode was read, no model was asked "
        "and nothing was recorded"
    ),
    "ScheduledTidyUp": (
        "ADR-0358 adds **no** error class to `core.errors`, and a clock this process "
        "cannot read is not a failed tidy-up: no story was read as due, no model was "
        "asked and nothing was written"
    ),
    "CurrentTime": ("documented at ``tools/builtin.py:148``, and `tools` is not in §4's list"),
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


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """The module-level names bound to a string literal.

    A label is as often a named constant as an inline literal — ``_OWNER = "…"``
    beside the emitter, then ``owner=_OWNER`` at the call. Resolving those is what
    keeps :func:`_owners_given_in` reading labels rather than refusing them.

    Args:
        tree: One parsed module.

    Returns:
        Name to string value, for the module-level string assignments only.
    """
    resolved: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                resolved[target.id] = value.value
    return resolved


def _owners_given_in(
    source: str, callee: str, module: str
) -> tuple[frozenset[str], frozenset[str]]:
    """Every ``owner=`` one module passes to ``callee``, resolved where it can be.

    The other half of a computed owner: ``MemoryTraces`` takes its label as a
    constructor argument, so the *seam's* own ``owner=`` is unreadable but every
    caller's is readable one file away — as a literal, or as a module constant
    :func:`_module_constants` resolves.

    **What it cannot read it reports rather than skips.** Returning only the
    labels it understood would let a caller building its label at run time slip
    a seam past the partition assertion in silence, which is the one thing this
    roster exists to stop; the second set is what the assertion refuses on.

    Args:
        source: One module's text.
        callee: The constructor's name, matched under any spelling of its import.
        module: The dotted path of the module defining it.

    Returns:
        The labels this module's calls name, and the ``owner`` expressions that
        could not be resolved to one, unparsed.
    """
    tree = ast.parse(source)
    bound = _modules_bound_in(tree)
    constants = _module_constants(tree)
    labels: set[str] = set()
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _refers_to(node.func, callee, module, bound):
            continue
        for keyword in node.keywords:
            if keyword.arg != "owner":
                continue
            given = keyword.value
            if isinstance(given, ast.Constant) and isinstance(given.value, str):
                labels.add(given.value)
            elif isinstance(given, ast.Name) and given.id in constants:
                labels.add(constants[given.id])
            else:
                unresolved.add(ast.unparse(given))
    return frozenset(labels), frozenset(unresolved)


def _owners_given_to(callee: str, module: str) -> frozenset[str]:
    """:func:`_owners_given_in`, unioned over ``src/`` and refusing what it cannot read.

    Args:
        callee: The constructor's name.
        module: The dotted path of the module defining it.

    Returns:
        The labels its callers name.

    Raises:
        AssertionError: If any caller's ``owner`` could not be resolved to a
            label. Raised here rather than returned, so a seam that becomes
            unreadable fails the roster instead of shrinking it.
    """
    labels: set[str] = set()
    unreadable: set[str] = set()
    for path in sorted(Path(ai_assistant.__file__).parent.rglob("*.py")):
        found, unresolved = _owners_given_in(path.read_text(encoding="utf-8"), callee, module)
        labels |= found
        unreadable |= unresolved
    assert not unreadable, (
        f"{sorted(unreadable)} is passed as {callee}'s ``owner`` and cannot be read "
        f"statically, so the seam it names is outside this roster; give it a literal, "
        f"a module constant, or an explicit derivation in ``COMPUTED_OWNERS``"
    )
    return frozenset(labels)


#: Seams whose ``owner=`` is a run-time expression, so the scan cannot read the
#: label off the seam itself: the unparsed expression maps to a function that
#: **derives** the labels it produces from ``src/``. Derived rather than listed,
#: because a list is exactly what goes stale — a third ``MemoryTraces``
#: construction would produce a new label while the expression at the seam stayed
#: word for word the same, and a declared pair would have gone on passing. What
#: stays declared is the *expression*, so a new computed-owner seam still has to be
#: accounted for here by hand.
COMPUTED_OWNERS: Final[dict[str, Callable[[], frozenset[str]]]] = {
    "owner": lambda: _owners_given_to(_EMITTER, _EMITTER_MODULE),
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
}


#: The guard, and the module that defines it: a call is the seam only when both
#: halves match, which is what keeps an unrelated ``x.checked_clock(…)`` out.
_GUARD: Final = "checked_clock"
_CLOCK: Final = "ai_assistant.core.clock"

#: The emitter whose ``owner`` is a constructor argument, and its module.
_EMITTER: Final = "MemoryTraces"
_EMITTER_MODULE: Final = "ai_assistant.memory.traces"


def _modules_bound_in(tree: ast.Module) -> dict[str, str]:
    """The module each importable name in this module stands for, fully qualified.

    The receiver half of :func:`_refers_to`: ``clock.checked_clock(…)`` is the
    guard only when ``clock`` is *this* project's ``core.clock``.

    Args:
        tree: One parsed module.

    Returns:
        Local name to dotted path, over both import forms. Names imported *from*
        a module are included too; they simply never match a module path.
    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None and not node.level:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def _dotted(expr: ast.expr) -> str | None:
    """The dotted path a pure name-or-attribute chain spells, if it is one.

    Args:
        expr: Any expression; anything else answers ``None``.

    Returns:
        ``"a.b.c"``, or ``None`` for an expression with a call or a subscript in it.
    """
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        prefix = _dotted(expr.value)
        return None if prefix is None else f"{prefix}.{expr.attr}"
    return None


def _refers_to(func: ast.expr, target: str, module: str, bound: dict[str, str]) -> bool:
    """Whether a call's callee is ``module.target``, under any spelling of the import.

    **Both directions matter, and they were found one round apart.** Matching a
    bare name only would miss a seam imported under an alias, and the partition
    assertion would pass with no row driving it. Matching *any* attribute called
    ``target`` would claim an unrelated ``scheduler.checked_clock(…)``, and the
    partition assertion would fail naming a seam that does not exist. So the
    receiver is resolved to the module that defines the target, and a bare name is
    only the target when this module imported it from there.

    Args:
        func: The ``func`` of an :class:`ast.Call`.
        target: The name being looked for.
        module: The dotted path of the module that defines it.
        bound: :func:`_modules_bound_in` for the module the call is in. Passed in
            rather than derived here, because this is asked once per call node and
            re-walking the module for each of them is quadratic.

    Returns:
        ``True`` for a bare name this module imported from ``module``, or an
        attribute access on a receiver bound to ``module``. A bare name that was
        never imported from there — a local ``def checked_clock``, a vendor's — is
        not the guard, whatever it is called.
    """
    if isinstance(func, ast.Name):
        return bound.get(func.id) == f"{module}.{target}"
    if not isinstance(func, ast.Attribute) or func.attr != target:
        return False
    receiver = _dotted(func.value)
    return receiver is not None and bound.get(receiver, receiver) == module


def _owners_in(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """Every ``checked_clock`` call in one module's source, by how its owner is written.

    Args:
        source: One module's text.

    Returns:
        The ``owner`` labels written as string literals, and the ``owner``
        expressions computed at run time, unparsed.
    """
    tree = ast.parse(source)
    bound = _modules_bound_in(tree)
    literal: set[str] = set()
    computed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _refers_to(node.func, _GUARD, _CLOCK, bound):
            continue
        owner = next((kw.value for kw in node.keywords if kw.arg == "owner"), None)
        if isinstance(owner, ast.Constant) and isinstance(owner.value, str):
            literal.add(owner.value)
        else:
            computed.add("<positional or absent>" if owner is None else ast.unparse(owner))
    return frozenset(literal), frozenset(computed)


def _clock_seam_roster() -> tuple[frozenset[str], frozenset[str]]:
    """Every ``checked_clock`` call in ``src/``, read out of the source itself.

    Parsed rather than imported, because an import-time roster would only see the
    seams whose modules something in this test happened to load — the failure mode
    a roster exists to prevent. ``core/clock.py`` is skipped: the ``checked_clock``
    inside it is the definition, not a seam.

    Returns:
        :func:`_owners_in`'s two sets, unioned over every module under ``src/``.
    """
    literal: set[str] = set()
    computed: set[str] = set()
    definition = Path(clock.__file__)
    for path in sorted(Path(ai_assistant.__file__).parent.rglob("*.py")):
        if path == definition:
            continue
        found, expressions = _owners_in(path.read_text(encoding="utf-8"))
        literal |= found
        computed |= expressions
    return frozenset(literal), frozenset(computed)


def test_the_roster_scans_follow_a_name_under_any_spelling_of_its_import() -> None:
    """A seam hidden behind an import alias is a seam this module never sees.

    No module in ``src/`` writes any of these spellings today, so nothing above
    would fail if the scans handled only the plain one — and a scan that silently
    stopped finding seams is worse than no scan, because the partition assertion
    would go on passing. This is the two of them run over source written to break
    each in turn: the guard called under an alias, and a constructor whose owner
    label is a literal or a module constant called under an alias. The last emitter
    builds its label at run time, which nothing static can follow: that one is
    *reported*, so the roster refuses it rather than shortening itself.

    And twice in the other direction, because a roster that invents a seam is as
    unreadable as one that misses one: neither an unrelated object with a method
    of the guard's name nor a same-named function imported from somewhere else is
    the guard, and claiming either would fail the partition naming a seam that
    does not exist.
    """
    source = textwrap.dedent("""
        from ai_assistant.core.clock import checked_clock
        from ai_assistant.core.clock import checked_clock as guard
        from ai_assistant.core import clock as module
        from ai_assistant.memory.traces import MemoryTraces as Emitter
        from vendor.timing import checked_clock as vendored

        a = checked_clock(now, owner="Plain")
        b = guard(now, owner="Aliased")
        c = module.checked_clock(now, owner="Qualified")
        impostor = scheduler.checked_clock(now, owner="NotAnAttributeSeam")
        stranger = vendored(now, owner="NotABareSeam")
        d = guard(now, owner=type(self).__name__)
        _OWNER: Final = "Named constant"

        e = Emitter(kind=kind, sink=sink, now=now, owner="Aliased emitter")
        f = Emitter(kind=kind, sink=sink, now=now, owner=_OWNER)
        g = Emitter(kind=kind, sink=sink, now=now, owner=build_label())
        """)

    literal, computed = _owners_in(source)

    assert literal == {"Plain", "Aliased", "Qualified"}
    assert computed == {"type(self).__name__"}
    assert _owners_given_in(source, _EMITTER, _EMITTER_MODULE) == (
        frozenset({"Aliased emitter", "Named constant"}),
        frozenset({"build_label()"}),
    )


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
        f"computed has to say here how its labels are derived, since no scan can read "
        f"them off the seam"
    )

    tabled = (
        {seam.label for seam in SEAMS}
        | {seam.label for seam in SWALLOWING_SEAMS}
        | set(CAPTURE_SEAMS)
    )
    derived: set[str] = set()
    for expression, produce in COMPUTED_OWNERS.items():
        labels = produce()
        assert labels, (
            f"{expression!r} derived no label at all, so the roster is short by however "
            f"many seams that expression stands for and the partition below is vacuous"
        )
        derived |= labels
    roster = literal | derived
    assert tabled - roster == set(), (
        f"{sorted(tabled - roster)} is tabled here but reads no clock in ``src/``: a "
        f"label that drifted from its constructor, or a seam that has been removed"
    )
    assert roster - tabled == set(UNTABLED), (
        f"{sorted(roster - tabled - set(UNTABLED))} guards a clock in ``src/`` and is "
        f"is driven by no table here and recorded in ``UNTABLED`` with no reason"
    )


CAPTURE_SEAMS = ("ActivationCoordinator", "ActivationWriter")


@pytest.mark.parametrize("label", CAPTURE_SEAMS)
@pytest.mark.parametrize(
    "now", [_naive_clock, _failing_clock, lambda: _AWARE], ids=["naive", "down", "valid"]
)
async def test_capture_clock_fault_degrades_receipt_without_writing_an_invalid_record(
    label: str, now: Clock
) -> None:
    """ADR-0275's clock loss preserves processing and emits only closed telemetry."""
    memory = FakeMemoryStore(now=lambda: _AWARE)
    state = admit_channel(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="event"),
            payload=TextChannelPayload(text="input"),
        ),
        None,
        clock=lambda: _AWARE,
        id_factory=lambda: "1bed03e1-3b38-4e67-a2e4-6f6bf9c97eb1",
    )
    writer = ActivationWriter(
        conversations=FakeConversationStore(now=lambda: _AWARE),
        memory=memory,
        retention=None,
        now=now if label == "ActivationWriter" else lambda: _AWARE,
    )
    children: list[asyncio.Task[None]] = []
    coordinator = ActivationCoordinator(
        writer=writer,
        register=children.append,
        register_safety=children.append,
        now=now if label == "ActivationCoordinator" else lambda: _AWARE,
        payload_limit=10000,
    )
    with structlog.testing.capture_logs() as logs:
        result = await coordinator.finish(state, failure=None, check_output=lambda: None)
    if now in (_naive_clock, _failing_clock):
        assert result.report.state == "degraded"
        assert await memory.export() == []
        losses = [entry for entry in logs if entry["event"] == "activation_capture_degraded"]
        assert len(losses) == 1
        assert set(losses[0]) == {"event", "stage", "reason", "log_level"}
    else:
        assert result.report.state == "recorded"
        assert len(await memory.export()) == 1
    assert all(child.done() for child in children)
