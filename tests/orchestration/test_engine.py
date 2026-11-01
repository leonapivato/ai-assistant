"""The engine façade an adapter drives (ADR-0042 §1, §3, §4).

What is exercised here is only what the façade *composes*: the maintenance
surface, the belief inspection surface, the trace emitter at its one wiring point,
and that shutdown drains in-flight work before closing owned resources. Every
collaborator is a canonical fake from ``ai_assistant.testing`` or
one of this package's own stage objects, so nothing here imports a subsystem
concrete (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from pydantic import SecretStr
from story_support import episode as story_episode

from ai_assistant.core.errors import (
    MemoryStoreError,
    OversizedValueError,
    TraceStoreError,
)
from ai_assistant.core.protocols import (
    AuditTrail,
    InvocationLedger,
    SpeechSynthesizer,
    SpeechTranscriber,
    SpendGate,
    SpendLedger,
)
from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    CostBasis,
    DataTier,
    EpisodicMemory,
    Idempotency,
    Memory,
    MemoryKind,
    MemorySource,
    MemoryStanding,
    MemoryStatus,
    MemorySupport,
    PlanningRound,
    Provenance,
    ProvisioningState,
    ReportedExtent,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    TraceOutcome,
    Validity,
    belief_summary,
    belief_view,
    secret_value,
)
from ai_assistant.orchestration import (
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
)
from ai_assistant.orchestration import engine as engine_module
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, DrainPhase
from ai_assistant.orchestration.matters import (
    DEFAULT_HELD_INPUT_LIMIT,
    DEFAULT_IN_PROGRESS_LIMIT,
)
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.speech import DEFAULT_MAX_SPOKEN_AUDIO_BYTES
from ai_assistant.orchestration.stories import DEFAULT_STORY_SUMMARY_VIEW_NOTES
from ai_assistant.orchestration.understanding import RecentEpisodes, WindowsStage
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeConversationStore,
    FakeMemoryStore,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
    evaluation_trace,
    with_phase_declaration,
)
from ai_assistant.testing.memories import (
    legacy_support,
    memory,
    message_support,
    remembered_support,
    said_support,
    sourced_support,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        DiagnosticSink,
        SourceReadTrail,
        StoryStore,
    )
    from ai_assistant.core.types import (
        EvaluationTrace,
        MemoryRecord,
    )
    from ai_assistant.orchestration.approval_calls import ApprovalsSeams
    from ai_assistant.orchestration.delivery import DeliveryOutbox
    from ai_assistant.orchestration.matters_pass import MattersPass
    from ai_assistant.orchestration.person_block import PersonBlocks
    from ai_assistant.orchestration.phase_path import PhasePath
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
    from ai_assistant.orchestration.story_tidy_up import ScheduledTidyUp
    from ai_assistant.orchestration.task_manager import TaskSchedulerSeams
    from ai_assistant.orchestration.telegram import TelegramLineSeams
    from ai_assistant.orchestration.understanding import UnderstandingStage
    from ai_assistant.testing.invoker import FakeToolImplementation


AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


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


def _grant_ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _grant_operations(sources: Sequence[HeldSource] = ()) -> GrantOperations:
    """The grant collaborator every ``Engine`` needs (ADR-0102 §7).

    Required rather than optional on the façade: the four grant
    methods are on the Protocol, so an engine that could be built without them is one
    whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


def _connection_operations() -> ConnectionOperations:
    """The connection collaborator every ``Engine`` needs (ADR-0151 §10).

    Required rather than optional on the façade, on ``_grant_operations``' reason
    exactly: the five connection methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. The
    canonical fake is the subject, so a case that wants a live record, a pending
    one, or a keyring that raises scripts it through the provisioner's own switches
    rather than through a second double.
    """
    return ConnectionOperations(provisioner=FakeConnectionProvisioner())


#: The episodic horizon the harness's capture stage stamps with (ADR-0074 §7).
RETENTION = timedelta(days=30)

#: The trace horizon the harness's maintenance operation sweeps against
#: (ADR-0119 §10). Deliberately *not* ``RETENTION``: the two are different
#: settings over different tiers, and a shared value would let a sweep against
#: the wrong one pass.
TRACE_RETENTION = timedelta(days=365)

#: The hub chat's start wait a harness runs at unless a case varies it (ADR-0332 §5:1):
#: short enough that a message is taken in at once, as every case before the wait wrote.
CASE_START_WAIT = timedelta(milliseconds=1)


CAPABILITY = "send_email"


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright (as the retired test_runner's did)."""
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
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def confirmable(tool_id: str = "smtp") -> ToolDefinition:
    """A declaration the fake policy confirms: it discloses off-device."""
    return tool(tool_id, discloses=(DataTier.PERSONAL,))


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


class _Default:
    """The sentinel that tells "the harness picks one" from an explicit ``None``.

    ADR-0200 lets an engine be built with **no** speech seams — a deployment with
    no models — and refuses one built with exactly one of the two. A default of
    ``None`` would make both of those shapes unreachable from this harness, so
    ``None`` is passed through literally and this is what "unspecified" looks like.
    """


_DEFAULT: Final = _Default()


class Harness:
    """A wired :class:`Engine` and the fakes behind it, for assertions."""

    def __init__(  # noqa: PLR0913 — one knob per fake; that is what a harness is
        self,
        *,
        tools: tuple[ToolDefinition, ...] = (),
        memory: FakeMemoryStore | None = None,
        conversation_store: FakeConversationStore | None = None,
        closers: Sequence[object] = (),
        drain_timeout: timedelta | None = None,
        traces: FakeTraceRetention | None = None,
        trace_sink: FakeTraceSink | None = None,
        trace_retention: timedelta | None = TRACE_RETENTION,
        plans: FakePlanStore | None = None,
        tool_handler: FakeToolImplementation | None = None,
        trail: ConsumingTrail | None = None,
        reads: SourceReadTrail | None = None,
        # ADR-0276's understanding stage, wired as the composition root wires it with
        # §7's version bound beside it. `None` is every other case's deployment: no
        # stage, so every capture records `not_reached`.
        understanding: UnderstandingStage | None = None,
        understanding_version_limit: int | None = 8,
        # ADR-0282's windows stage. `None` wires one over this harness's store wherever
        # understanding is wired, as the composition root does.
        windows: WindowsStage | None = None,
        # ADR-0281's recall stage. `None` is every other case's deployment: no recall.
        recall: RecallStage | None = None,
        # ADR-0300 §6's story store, candidates and story-links stage. `None` is every
        # other case's deployment: no story is read or written, and no stories section
        # is rendered.
        stories: StoryStore | None = None,
        story_candidates: StoryCandidates | None = None,
        story_links: StoryLinksStage | None = None,
        # ADR-0303 §10:2's bound on the story summary view's notes.
        story_summary_notes: int = DEFAULT_STORY_SUMMARY_VIEW_NOTES,
        # ADR-0300 §9:3's matters pass. `None` is every other case's deployment:
        # `decide_story_flags` refuses, and nothing else reads it.
        matters_pass: MattersPass | None = None,
        # ADR-0358 §4's scheduled tidy-up. `None` is every other case's deployment:
        # `tidy_stories` refuses, and nothing else reads it.
        scheduled_tidy_up: ScheduledTidyUp | None = None,
        transcriber: SpeechTranscriber | None | _Default = _DEFAULT,
        synthesizer: SpeechSynthesizer | None | _Default = _DEFAULT,
        speakable_attested_sources: frozenset[str] = frozenset(),
        max_spoken_audio_bytes: int = DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        notification_outbox: DeliveryOutbox | None = None,
        now: Clock | None = None,
        # ADR-0293 §6's reader, which runs every activation through the phases (ADR-0309
        # §2:6), so it is wired only beside them. `None`, the default, is on wherever
        # `phases` is given and off otherwise: a case holding the medium alone, or a
        # surface no activation reaches, builds no phases.
        chat_reader: bool | None = None,
        # ADR-0309 §2:6's phases, built over this harness's own stores once they exist.
        # `None` builds none: no activation runs, so a case that drives one wires them.
        phases: Callable[[Harness], PhasePath] | None = None,
        # ADR-0314 §4:4's sink, which the controller of every pass writes through.
        # `None` is every other case's deployment: the diagnostic record off.
        diagnostics: DiagnosticSink | None = None,
        # ADR-0323's Telegram line, over its fakes. `None` is every other case's
        # deployment: no line, and nothing of it starts.
        telegram: TelegramLineSeams | None = None,
        # ADR-0349 §9:2-§9:3's `held_input_limit` and `in_progress_limit`, at the
        # settings' own defaults unless a case varies them.
        held_input_limit: int = DEFAULT_HELD_INPUT_LIMIT,
        in_progress_limit: int = DEFAULT_IN_PROGRESS_LIMIT,
        # ADR-0338 §7:1's person block. `None` is every other case's deployment, as
        # every hub's until a person-model store is wired: no block is assembled.
        person_blocks: PersonBlocks | None = None,
        # ADR-0332 §5:1's start wait on the hub chat: a millisecond unless a case
        # varies it, so a message is taken in at once, as before the wait, and a case
        # driving the wait sets its own.
        chat_start_wait: timedelta = CASE_START_WAIT,
        # ADR-0350's Task Scheduler. `None` is every other case's deployment: no sensor,
        # no spawn, and a stop that cascades nothing.
        task_scheduler: TaskSchedulerSeams | None = None,
        # ADR-0361's Approvals channel. `None` is every other case's deployment.
        approvals: ApprovalsSeams | None = None,
    ) -> None:
        # ADR-0200's two seams, wired **together** or not at all — the engine refuses
        # half a pipeline. Defaulted to the canonical fakes, and kept on the harness so
        # a case can read what reached each seam, arm a failure, or narrow a `formats`
        # set.
        self.transcriber: SpeechTranscriber | None = (
            FakeSpeechTranscriber() if isinstance(transcriber, _Default) else transcriber
        )
        self.synthesizer: SpeechSynthesizer | None = (
            FakeSpeechSynthesizer() if isinstance(synthesizer, _Default) else synthesizer
        )
        # The **injected** clock (ADR-0009), settable so a case moves it rather than
        # waits.
        self.clock: Clock = (lambda: AT) if now is None else now
        # A knob because a case about the phases' effect records needs to hold the
        # store that took them. The default stays the canonical fake, which is what
        # every other case here wants.
        self.plans = FakePlanStore(now=lambda: AT) if plans is None else plans
        # ``trail`` is a knob because the audit surface's own reader cases need a
        # store that holds **bytes**: ADR-0184 §10 puts the origin-unrecorded row's
        # read half in each implementation's own tests, "because it is a property of
        # a store that persists a serialised payload and rebuilds it, and a fake
        # holding objects has no bytes for a shared case to seed". The default stays
        # the canonical fake, which is what every other case here wants.
        self.trail: ConsumingTrail = FakeAuditTrail() if trail is None else trail
        # One object as both registry and invoker, as ADR-0029 §8 requires, which the
        # phases a case wires reach. The seam claims through the **same** trail
        # authorizing records rulings into (ADR-0192 §9's wiring clause); a second one
        # would refuse every claim. ``tool_handler`` is a knob so a case can have a
        # tool fail rather than succeed.
        self.invoker = FakeToolInvoker(
            [
                (definition, _succeeds if tool_handler is None else tool_handler)
                for definition in tools
            ],
            ledger=self.trail,
            gate=self.trail,
        )
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
        # The capture/lifecycle stage over the *same* memory store, as the
        # composition root wires it (ADR-0074 §9). Kept on the harness so a test can
        # read what capture actually recorded.
        # A knob for the same reason ``memory`` is one: ADR-0074 §9's store faults and
        # ADR-0205 §3's refusals are properties of what the *store* does, and a case
        # about one needs a store it can arm or count. The default is the canonical
        # fake, which is what every other case here wants.
        self.conversation_store = (
            FakeConversationStore(now=lambda: AT)
            if conversation_store is None
            else conversation_store
        )
        self.conversations = ConversationLifecycle(
            conversations=self.conversation_store,
            memory=self.memory,
            retention=RETENTION,
            now=lambda: AT,
        )
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        # ADR-0185 §5's trail, whole, as the composition root hands it to the façade
        # (ADR-0186 §10). A knob for ``trail``'s reason, one store over: the read
        # surface's own cases need a **durable** trail, because the order
        # ``export_reads`` reverses comes from the store's ``ORDER BY`` rather than
        # from a Python list, and a fake cannot exhibit a wrong one.
        self.reads: SourceReadTrail = FakeSourceReadTrail() if reads is None else reads
        # The trace store's *deletion* seam, and only that: ADR-0119 §7 gives the
        # engine the purge and withholds the walk, so the harness hands it a
        # ``FakeTraceRetention`` rather than the whole store — a fake that could
        # walk would let a test assert a reach the production wiring does not have.
        self.traces = traces if traces is not None else FakeTraceRetention()
        # The trace store's *append* seam, and only that (ADR-0119 §7): the engine
        # emits its own ``OPERATION`` trace through a ``FakeTraceSink``, which can
        # be appended to and cannot be walked. Separate from ``traces`` above
        # because the capabilities are separate — the production wiring narrows one
        # object twice, and a harness handing over one fake for both would let a
        # case assert a reach the engine does not have.
        self.trace_sink = trace_sink if trace_sink is not None else FakeTraceSink()
        self.trace_retention = trace_retention
        self.engine = Engine(
            grant_operations=_grant_operations(),
            connection_operations=_connection_operations(),
            plans=self.plans,
            trail=self.trail,
            spend=self.trail,
            reads=self.reads,
            memory=self.memory,
            traces=self.traces,
            trace_sink=self.trace_sink,
            trace_retention=trace_retention,
            conversations=self.conversations,
            closers=tuple(closers),  # type: ignore[arg-type]
            understanding=understanding,
            understanding_version_limit=understanding_version_limit,
            windows=(
                WindowsStage(episodes=RecentEpisodes(memory=self.memory, limit=10))
                if windows is None and understanding is not None
                else windows
            ),
            recall=recall,
            stories=stories,
            story_summary_notes=story_summary_notes,
            story_candidates=story_candidates,
            story_links=story_links,
            matters_pass=matters_pass,
            scheduled_tidy_up=scheduled_tidy_up,
            transcriber=self.transcriber,
            synthesizer=self.synthesizer,
            speakable_attested_sources=speakable_attested_sources,
            max_spoken_audio_bytes=max_spoken_audio_bytes,
            # ADR-0085 §8c's contract limit, a knob so a case can put a *result* over
            # it cheaply.
            max_payload_bytes=max_payload_bytes,
            # The whole harness runs at one instant unless a case moves it, so the
            # horizon the sweep measures back from is a figure a case can name
            # (ADR-0119 §10).
            now=self.clock,
            drain_timeout=drain_timeout,
            # ADR-0131 §3's durable delivery queue. ``None`` by default, which is the
            # in-process deployment that serves no poll.
            notification_outbox=notification_outbox,
            chat_reader=phases is not None if chat_reader is None else chat_reader,
            phases=None if phases is None else phases(self),
            diagnostics=diagnostics,
            telegram=telegram,
            held_input_limit=held_input_limit,
            in_progress_limit=in_progress_limit,
            person_blocks=person_blocks,
            chat_start_wait=chat_start_wait,
            task_scheduler=task_scheduler,
            approvals=approvals,
        )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


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
        await harness.engine.beliefs()


# --- the two-phase drain (ADR-0083 §4) ---------------------------------


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


# --- the maintenance surface (ADR-0083 §8) -----------------------------


def _counting_purges(harness: Harness, *, records: int) -> dict[str, int]:
    """Replace the memory store's sweep with a counter, on the very instance wired in.

    The *semantics* of the sweep — which rows are past their deadline — belong to the
    store and are held to its Protocol by the shared conformance suite. What is
    unproven anywhere else is that the façade operation reaches it and reports its
    count as its own.
    """
    calls = {"records": 0}

    async def purge_memory() -> int:
        calls["records"] += 1
        return records

    harness.memory.purge_expired = purge_memory  # type: ignore[method-assign]
    return calls


async def test_the_purge_sweeps_the_memory_store_and_reports_its_count() -> None:
    """ADR-0083 §8's maintenance surface reaches the memory store's sweep once.

    The report carries no ``questions`` count: the deferred-question queue retired
    (ADR-0309 §5), so the operation no longer sweeps it.
    """
    harness = Harness()
    calls = _counting_purges(harness, records=3)

    report = await harness.engine.purge_expired()

    assert report.records == 3
    assert calls == {"records": 1}
    assert not hasattr(report, "questions")


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


async def test_a_failing_memory_sweep_does_not_reach_the_trace_sweep() -> None:
    """Nothing sequences the sweeps, so a half-done sweep must not report success.

    The next tick simply re-runs them all — a missed sweep is never a correctness bug
    (ADR-0007 §2) — and swallowing the first failure to reach the next would claim a
    sweep that half happened. The scheduler logs the failure and retries (§7).
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(400))
    harness = Harness(traces=traces)

    async def refuses() -> int:
        msg = "the memory store is unreadable"
        raise MemoryStoreError(msg)

    harness.memory.purge_expired = refuses  # type: ignore[method-assign]

    with pytest.raises(MemoryStoreError):
        await harness.engine.purge_expired()

    assert len(traces.recorded) == 1


# --- the trace horizon, swept by that same operation (ADR-0119 §10) -----


def _aged(days: int) -> EvaluationTrace:
    """A trace stamped ``days`` before the harness's instant."""
    return evaluation_trace("engine", occurred_at=AT - timedelta(days=days))


async def test_the_purge_sweeps_the_trace_store_as_its_third_call() -> None:
    """ADR-0119 §10 taken literally, and ADR-0078 §10 item 8 reaching a third store.

    "ADR-0083 §7's retention-purge row already calls two purges through one
    ``Engine`` maintenance operation; the trace purge becomes the third call behind
    that same operation." So the claim is not merely that traces get swept — it is
    that *this* operation sweeps them, with no new job, no new interval and no new
    store surface on the scheduler.

    The horizon is ``now - trace_retention`` and the bound is **strict**: the
    contract says "a trace whose ``occurred_at`` is strictly before it is deleted;
    one at the instant is kept". Asserted with a trace exactly on the horizon,
    because an off-by-one there is invisible against any other fixture — every
    plausible implementation deletes the 400-day-old one.
    """
    traces = FakeTraceRetention()
    horizon = _aged(365)
    recent = _aged(1)
    traces.hold(_aged(400), horizon, recent)
    harness = Harness(traces=traces)

    report = await harness.engine.purge_expired()

    assert report.traces == 1
    assert traces.recorded == (horizon, recent)


async def test_a_keep_forever_horizon_does_not_call_the_trace_sweep_at_all() -> None:
    """``None`` means keep forever, so the sweep is skipped — not called with a floor.

    ADR-0119 §10: the horizon is "an optional duration… where ``None`` means 'keep
    forever'". A floor passed to ``purge_before`` would delete nothing *today* and
    would be a horizon the moment somebody computed it from a different instant, so
    the distinction has to be that no call is made.

    Proven by scripting the seam to raise on any purge: a test that only inspected
    the count would pass for an implementation that swept against
    ``datetime.min``, since that deletes nothing either.
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(4000))
    traces.fail_purge()
    harness = Harness(traces=traces, trace_retention=None)

    report = await harness.engine.purge_expired()

    assert report.traces is None, "None says 'not swept', where 0 would say 'swept, found nothing'"
    assert len(traces.recorded) == 1


async def test_a_horizon_longer_than_the_calendar_deletes_nothing_instead_of_failing() -> None:
    """Accepted configuration must not break the operation it configures.

    ``Settings`` refuses a trace horizon only for being non-finite or non-positive
    (ADR-0119 §10), so ``P999999998D`` loads — three orders of magnitude past the
    calendar. Subtracting one of those from any real clock reading overflows, and it
    would overflow *inside* the maintenance operation, after both Tier 1 sweeps had
    run, on every tick: a retention job that never completes because a setting asked
    for more history than there are dates.

    Saturating is not a guess about intent. A horizon nothing can predate deletes
    nothing, which is what the setting asked for — and it stays distinguishable from
    "keep forever", which does not call the sweep at all.
    """
    traces = FakeTraceRetention()
    ancient = _aged(4000)
    traces.hold(ancient)
    harness = Harness(traces=traces, trace_retention=timedelta.max)

    report = await harness.engine.purge_expired()

    assert report.traces == 0, "0 says 'swept, deleted nothing', where None would say 'not swept'"
    assert traces.recorded == (ancient,)


async def test_a_clock_at_the_start_of_the_calendar_does_not_break_the_sweep() -> None:
    """The other end of the same arithmetic, and the reason the guard is a comparison.

    ``checked_clock`` accepts any reading a day clear of ``datetime.min``
    (ADR-0026 §3's localization margin), so a clock there is a *conforming* clock —
    and the ordinary 365-day horizon underflows against it. An implementation that
    guarded only the huge-``timedelta`` case would still fail here, which is why the
    guard compares the gap rather than special-casing a value.
    """
    traces = FakeTraceRetention()
    ancient = _aged(4000)
    traces.hold(ancient)
    harness = Harness(traces=traces)
    facade = Engine(
        chat_reader=False,
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        plans=harness.plans,
        trail=harness.trail,
        spend=harness.trail,
        reads=harness.reads,
        memory=harness.memory,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        now=lambda: datetime.min.replace(tzinfo=UTC) + timedelta(days=1),
    )

    report = await facade.purge_expired()

    assert report.traces == 0
    assert traces.recorded == (ancient,)


async def test_a_failing_trace_sweep_reaches_the_caller() -> None:
    """Unlike an emission failure, a purge failure is loud (ADR-0119 §5, §7).

    §5 subordinates the instrument to the work being observed — "no trace-store
    failure reaches the caller" — but a sweep is not the work being observed, and
    the contract says so where it lives: "a purge that silently did nothing would
    let a store grow without bound behind a horizon an operator believes is
    enforced". The scheduler logs the failure and retries on the next tick.
    """
    traces = FakeTraceRetention()
    traces.fail_purge()
    harness = Harness(traces=traces)
    calls = _counting_purges(harness, records=1)

    with pytest.raises(TraceStoreError):
        await harness.engine.purge_expired()

    # The memory sweep ran and is not undone: the next tick re-runs them all.
    assert calls == {"records": 1}


def test_the_engine_never_reads_a_trace_back() -> None:
    """ADR-0119 §7's third clause, at the first component that holds a trace seam.

    "No component of the request pipeline… holds a seam carrying the walk, and none
    reads a trace back." The type is the guarantee — ``TraceRetention`` has no
    ``walk`` — but the type is erased at runtime and the composition root hands over
    an object that *does*, so a call added here would work perfectly and be caught
    by nothing. What the clause protects is the instrument's independence: a
    pipeline that consults its own telemetry is measuring a system that includes the
    instrument, and leg 8's whole question becomes circular.

    Read out of the source rather than exercised, for the sweep guard's reason: a
    runtime test could only show that the operations it happened to call do not
    walk.
    """
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    walks = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "walk"
    ]

    assert walks == [], "the engine reads a trace back, which ADR-0119 §7 forbids"


@pytest.mark.parametrize("unusable", [float("nan"), float("inf"), 1.5, True, 0, -1])
async def test_a_payload_limit_that_could_not_bind_is_refused_at_construction(
    unusable: object,
) -> None:
    """ADR-0085 §8c's limit is guarded where it is injected, like its two siblings.

    ``Settings`` refuses a bad ``hub_max_frame_bytes`` at load and the composition
    root derives this argument from it, so no shipped path reaches here — but this is
    a **constructor** argument on a class tests and future roots build directly, and
    the failure is the silent kind: ``float("nan")`` compares ``False`` against every
    ``>``, so an engine built with one would measure every argument and every result
    against a ceiling nothing can exceed while reporting health. A limit that cannot
    bind is not a laxer limit but an absent one, and this one is absent across the
    *whole* promoted surface rather than one method of it (#1686).

    ``True`` earns its place twice over: it is an ``int`` subclass a flag would slip
    through as, and as a limit it is one byte, which no envelope fits inside.
    """
    with pytest.raises((TypeError, ValueError), match="max_payload_bytes"):
        Harness(max_payload_bytes=unusable)  # type: ignore[arg-type]  # the point of the test


async def test_an_int_subclass_that_answers_its_own_comparisons_is_refused_as_a_limit() -> None:
    """The guard allowlists the exact ``int``, which is what closes the class.

    A denylist naming ``bool`` closes one case of it. This is the case that leaves the
    limit *non-binding* rather than merely wrong, and it is reachable with two dunder
    overrides: ``__lt__`` walks the value through the positivity check on the way in,
    and — because Python gives a **subclass's** reflected comparison priority over the
    left operand's own — ``__gt__`` then answers every ``size > limit`` this engine
    performs. The result is ADR-0085 §8c's limit present in the constructor and absent
    everywhere it is measured against, with the engine reporting health throughout,
    which is exactly the failure this guard exists to prevent.
    """

    class _NonBinding(int):
        def __lt__(self, other: object) -> bool:
            return False

        def __gt__(self, other: object) -> bool:
            return False

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        Harness(max_payload_bytes=_NonBinding(0))


async def test_a_knob_that_cannot_describe_itself_still_gets_the_documented_refusal() -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    The refusal interpolates the offending value, so a value whose ``__repr__`` raises
    would replace the documented ``TypeError`` with whatever that ``__repr__`` threw —
    raised from inside the ``raise`` that reports it, which is the shape
    ``core.types.describe_untrusted`` exists to close and which this guard reaches for
    rather than restating.
    """

    class _Unspeakable:
        def __repr__(self) -> str:
            msg = "this value refuses to describe itself"
            raise RuntimeError(msg)

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        Harness(max_payload_bytes=_Unspeakable())  # type: ignore[arg-type]  # the point of the test


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


# --- the belief inspection surface (ADR-0073 §5, §7; ADR-0328 §15) --------


def _memory(
    record_id: str,
    *supports: MemorySupport,
    content: str = "the office is in Boston",
    valid_until: datetime | None = None,
) -> Memory:
    """A stored memory on ``supports`` (one said support where none is given)."""
    return memory(
        record_id,
        content,
        *(supports or (said_support("ep-1", when=AT, added_at=AT),)),
        validity=Validity(valid_until=valid_until),
    )


def _in_band(record_id: str, band: BeliefBand, *, outside: bool = False) -> Memory:
    """A memory standing in ``band``: said, sourced from the work calendar, or remembered."""
    match band:
        case BeliefBand.ASSERTED:
            support = said_support("ep-1", when=AT, added_at=AT)
        case BeliefBand.ATTESTED:
            support = sourced_support(_CALENDAR, episode="ep-1", when=AT, added_at=AT)
        case BeliefBand.DERIVED:
            support = remembered_support("ep-1", outside=outside, when=AT, added_at=AT)
    return _memory(record_id, support)


#: The source details an attested memory's support carries.
_CALENDAR: Final = Attestation(reported_by="calendar:work", reported_at=AT)


@pytest.mark.parametrize(
    ("band", "standing"),
    [
        (BeliefBand.ASSERTED, MemoryStanding.SAID),
        (BeliefBand.ATTESTED, MemoryStanding.SOURCE),
        (BeliefBand.DERIVED, MemoryStanding.INFERENCE),
    ],
)
def test_both_projections_carry_the_standing_and_its_band(
    band: BeliefBand, standing: MemoryStanding
) -> None:
    """ADR-0328 §6, §15:1: the standing and its band are computed once, in ``core``."""
    record = _in_band("rec-1", band)
    summary = belief_summary(record, now=AT, supports_gone=False)
    belief = belief_view(record, now=AT, contents={})
    assert (summary.standing, summary.band) == (standing, band)
    assert (belief.standing, belief.band) == (standing, band)


def test_a_projection_carries_exactly_what_adr_0328_15_1_names() -> None:
    """The id, the wording, the status, the validity end, as of, learned, the evidence
    summary, and no confidence and no elision count (§15:1, §15:3)."""
    until = datetime(2026, 8, 1, tzinfo=UTC)
    record = _memory(
        "rec-1",
        remembered_support("ep-1", when=AT - timedelta(days=2), added_at=AT),
        remembered_support("ep-2", effect="effect-2", when=AT, added_at=AT),
        valid_until=until,
    )
    summary = belief_summary(record, now=AT, supports_gone=False)
    assert summary.id == "rec-1"
    assert summary.content == "the office is in Boston"
    assert summary.status is MemoryStatus.CURRENT
    assert summary.valid_until == until
    assert summary.learned == AT - timedelta(days=2)
    assert summary.as_of == AT
    assert (summary.evidence.supporting, summary.evidence.episodes) == (2, 2)
    assert summary.kind == "memory"
    for absent in ("confidence", "evidence_elided"):
        assert absent not in BeliefSummary.model_fields
        assert absent not in Belief.model_fields
    # A memory's source details are on its supports (§15:2); the field is an episode's.
    assert summary.attestation is None


def test_the_single_view_resolves_each_support_and_never_carries_an_id() -> None:
    """ADR-0328 §15:2, ADR-0073 §4's floor: content or gone, never an episode id."""
    record = _memory(
        "rec-1",
        remembered_support("ep-1", when=AT, added_at=AT),
        remembered_support("ep-2", effect="effect-2", when=AT, added_at=AT),
    )
    first, second = (support.points_at for support in record.supports)
    belief = belief_view(record, now=AT, contents={first: "they said so", second: None})
    assert [support.content for support in belief.supports] == ["they said so", None]
    assert belief.supports[1].gone is True
    assert "ep-1" not in str(belief)


@pytest.mark.parametrize(
    ("band", "outside", "rests"),
    [
        (BeliefBand.ASSERTED, False, False),
        (BeliefBand.DERIVED, False, False),
        (BeliefBand.DERIVED, True, True),
        (BeliefBand.ATTESTED, False, True),
    ],
)
def test_both_projections_carry_rests_on_outside_content(
    band: BeliefBand, outside: bool, rests: bool
) -> None:
    """ADR-0328 §7:6, §12: the computed value, on both projections, read and not re-derived."""
    record = _in_band("rec-1", band, outside=outside)
    assert record.rests_on_outside_content is rests
    assert belief_view(record, now=AT, contents={}).rests_on_outside_content is rests
    assert belief_summary(record, now=AT, supports_gone=False).rests_on_outside_content is rests


def test_a_user_s_own_word_never_rests_on_outside_content_whatever_else_it_rests_on() -> None:
    """ADR-0328 §7:6: only a memory not in band ``ASSERTED`` rests on outside content."""
    record = _memory(
        "rec-1",
        said_support("ep-1", when=AT, added_at=AT),
        remembered_support("ep-2", outside=True, when=AT, added_at=AT),
    )
    assert record.band is BeliefBand.ASSERTED
    assert belief_view(record, now=AT, contents={}).rests_on_outside_content is False


def test_a_source_support_carries_its_source_details_whole() -> None:
    """ADR-0328 §15:2, ADR-0189 §2: the attestation as stored, on the support it is.

    Whole means its extent too, which nothing renders (ADR-0189 §2) but no projection
    drops: a populated one survives, and is the same object the record holds.
    """
    extended = _CALENDAR.model_copy(
        update={
            "extent": ReportedExtent(
                extends_from=AT - timedelta(days=7), extends_until=AT + timedelta(days=7)
            )
        }
    )
    record = _memory("rec-1", sourced_support(extended, episode="ep-1", when=AT, added_at=AT))
    belief = belief_view(record, now=AT, contents={})
    assert belief.supports[0].source_details == extended
    assert belief.supports[0].source_details is record.supports[0].source_details
    assert belief.attestation == extended
    said = belief_view(_in_band("rec-2", BeliefBand.ASSERTED), now=AT, contents={})
    assert said.supports[0].source_details is None


def test_the_listing_and_the_detail_view_agree_about_every_computed_value() -> None:
    """ADR-0085 §4a's split is about supports alone: every other value is the same."""
    for record in (
        _in_band("rec-1", BeliefBand.ATTESTED),
        _in_band("rec-2", BeliefBand.DERIVED, outside=True),
    ):
        belief = belief_view(record, now=AT, contents={})
        summary = belief_summary(record, now=AT, supports_gone=belief.supports_gone)
        assert summary == BeliefSummary.model_validate(belief.model_dump(exclude={"supports"}))


async def test_beliefs_lists_what_memory_holds_in_the_store_s_own_order() -> None:
    """The façade relays the enumeration and projects each memory (ADR-0073 §1, §7)."""
    harness = Harness()
    await harness.memory.add(
        _memory("older", said_support("ep-1", added_at=AT - timedelta(days=1)))
    )
    await harness.memory.add(_memory("newer", said_support("ep-1", added_at=AT)))

    page = await harness.engine.beliefs()
    assert [summary.id for summary in page] == ["newer", "older"]  # the store's order, unchanged
    # The listing ships summaries, not single views (ADR-0085 §4a): a `BeliefSummary`
    # has no field a support's content could occupy.
    assert all(isinstance(summary, BeliefSummary) for summary in page)
    assert all(not hasattr(summary, "supports") for summary in page)
    assert page[0].band is BeliefBand.ASSERTED


async def test_beliefs_lists_memories_and_never_an_episode() -> None:
    """ADR-0328 §11:2 (#3143): the listing excludes episodes by default."""
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(_memory("rec-1"))
    assert [summary.id for summary in await harness.engine.beliefs()] == ["rec-1"]


async def test_beliefs_returns_an_empty_page_when_nothing_matches() -> None:
    """An empty store is an empty tuple, not an error."""
    harness = Harness()
    assert await harness.engine.beliefs() == ()


async def test_beliefs_relays_the_band_filter_and_the_bounded_default_page() -> None:
    """The filter and paging reach the store verbatim; no kind is asked (§2, ADR-0328 §11:2)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)

    await harness.engine.beliefs()
    await harness.engine.beliefs(bands=[BeliefBand.DERIVED], limit=2, offset=7)
    assert store.calls == [
        # No filter, and the bounded default page starting from the beginning (§2).
        (None, None, 50, 0),
        # The filter and both paging arguments, relayed exactly as given; the kinds
        # are the store's default, which is memories alone.
        ((BeliefBand.DERIVED,), None, 2, 7),
    ]


async def test_beliefs_selects_nothing_for_an_explicitly_empty_filter() -> None:
    """An empty sequence is relayed as itself — it selects nothing, unlike None (§1)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)
    await harness.engine.beliefs(bands=[])
    assert store.calls[-1] == ((), None, 50, 0)


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
    await harness.memory.add(_in_band("rec-1", BeliefBand.ATTESTED))
    belief = await harness.engine.belief("rec-1")
    assert belief is not None
    assert belief.id == "rec-1"
    assert belief.band is BeliefBand.ATTESTED


async def test_belief_is_none_for_an_id_no_live_record_has() -> None:
    """Unknown, and — because ``get`` is live-only — retired, both read as None (§5)."""
    harness = Harness()
    assert await harness.engine.belief("nothing") is None
    retired = _memory("retired", valid_until=AT - timedelta(days=1))
    await harness.memory.add(retired)
    assert await harness.engine.belief("retired") is None


async def test_belief_reads_an_episode_as_its_view_so_forget_can_show_it() -> None:
    """ADR-0074 §6: ``forget <id>`` destroys an episode exactly as it destroys a belief.

    So the single read the ceremony takes (ADR-0073 §5) answers for an episode's id
    with :func:`episode_view`: no standing, no supports, learned when it happened.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    shown = await harness.engine.belief("ep-1")
    assert shown is not None
    assert shown.kind == "episodic"
    assert shown.standing is None
    assert shown.supports == ()
    assert await harness.engine.forget("ep-1") is True
    assert await harness.engine.belief("ep-1") is None


async def test_the_listing_lists_episodes_only_where_the_episodic_kind_is_named() -> None:
    """ADR-0328 §11:2 changes the default alone; ADR-0074 §6's ``--kind episodic`` stands."""
    harness = Harness()
    await harness.memory.add(_memory("rec-1"))
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    assert [one.id for one in await harness.engine.beliefs()] == ["rec-1"]
    episodic = await harness.engine.beliefs(kinds=[MemoryKind.EPISODIC])
    assert [(one.id, one.kind) for one in episodic] == [("ep-1", "episodic")]
    both = await harness.engine.beliefs(kinds=[MemoryKind.EPISODIC, MemoryKind.MEMORY])
    assert {one.id for one in both} == {"rec-1", "ep-1"}
    assert await harness.engine.beliefs(kinds=[]) == ()


async def test_forget_destroys_the_record_and_reports_that_it_did() -> None:
    """``forget`` is ``MemoryStore.delete``, relayed (ADR-0073 §5)."""
    harness = Harness()
    await harness.memory.add(_memory("rec-1"))
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
    harness = Harness()
    await harness.memory.add(_in_band("rec-1", band))
    shown = await harness.engine.belief("rec-1")
    assert shown is not None
    assert shown.band is band
    assert await harness.engine.forget("rec-1") is True


async def test_forget_leaves_nothing_behind_not_even_in_an_export() -> None:
    """Forgetting destroys; a correction would have retired and kept it (ADR-0073 §6)."""
    harness = Harness()
    await harness.memory.add(_memory("rec-1"))
    await harness.engine.forget("rec-1")
    assert await harness.memory.export() == []


@pytest.mark.parametrize("call", ["beliefs", "belief", "forget", "episodes", "episode_chunk"])
async def test_the_inspection_surface_is_refused_once_shutdown_has_begun(call: str) -> None:
    """After aclose, no inspection call is accepted either (ADR-0042 §2)."""
    harness = Harness()
    await harness.engine.aclose()
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "episodes": harness.engine.episodes,
        "episode_chunk": lambda: harness.engine.episode_chunk(""),
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


async def test_engine_start_consumes_the_stamped_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0076 §3: every conformance clause can pass against a method **nothing calls**.

    So this asserts the wiring rather than the store: engine start-up reaches the
    enumeration ADR-0076 added, which is the only way a deletion a previous run left
    unfinished is ever rediscovered.
    """
    harness = Harness()
    calls: list[str | None] = []
    original = harness.conversation_store.stamped_conversation_ids

    async def _spy(*, limit: int | None = None, after_id: str | None = None) -> list[str]:
        calls.append(after_id)
        return await original(limit=limit, after_id=after_id)

    monkeypatch.setattr(harness.conversation_store, "stamped_conversation_ids", _spy)

    await harness.engine.start()

    assert calls == [None], "start-up walked the tombstones exactly once, from the beginning"


# --- supports whose episode is gone (ADR-0328 §15:7, ADR-0077 §6) --------


async def _derived_with_two_episodes(harness: Harness) -> None:
    """Store a memory resting on the inputs of two episodes that both resolve.

    Each support points at its episode's input, which an episode recorded with no
    processing record holds as its content (ADR-0328 §15:2).
    """
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _memory(
            "rec-1",
            said_support("ep-1", when=AT, added_at=AT),
            said_support("ep-2", when=AT, added_at=AT),
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


async def test_a_memory_whose_supports_all_resolve_shows_each_one() -> None:
    """Nothing gone — the baseline the marks are measured from."""
    harness = Harness()
    await _derived_with_two_episodes(harness)

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.supports_gone is False
    assert belief.evidence.supporting == 2
    assert [support.content for support in belief.supports] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_a_deleted_episode_shows_its_support_as_gone_without_touching_the_memory() -> None:
    """The rendering changes; the stored memory does not (ADR-0328 §15:7, ADR-0077 §6).

    The support still counts — it is shown as gone, never as evidence — and the byte
    identity catches an implementation that "fixed" the memory instead of the view.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    before = await harness.memory.get("rec-1")
    assert before is not None

    assert await harness.memory.delete("ep-1") is True
    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.supports[0].gone is True
    assert belief.supports[0].content is None  # never the id, never a silent gap
    assert belief.supports[0].counts is True
    assert belief.supports[1].content == "they asked again in metric"
    assert belief.supports_gone is False
    assert belief.evidence.supporting == 2
    assert await harness.memory.get("rec-1") == before


async def test_an_expired_episode_renders_exactly_as_a_deleted_one() -> None:
    """Expiry is the *commoner* loss and has no event to hook (ADR-0077 §6)."""
    harness = Harness()
    await harness.memory.add(
        _episode_record("ep-1", "they asked for metric units", expires_at=AT - timedelta(days=1))
    )
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _memory(
            "rec-1",
            said_support("ep-1", when=AT, added_at=AT),
            said_support("ep-2", when=AT, added_at=AT),
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.supports[0].content is None
    assert belief.supports[1].content == "they asked again in metric"


async def test_a_memory_none_of_whose_episodes_resolves_is_held_and_marked() -> None:
    """Marked, answerable, still live — **not** retired (ADR-0328 §15:7, ADR-0077 §6)."""
    harness = Harness()
    await _derived_with_two_episodes(harness)
    await harness.memory.delete("ep-1")
    await harness.memory.delete("ep-2")

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.supports_gone is True
    assert belief.unbacked is False  # gone supports still count
    # Still live, still listed with the mark, and still deletable by the user.
    listed = await harness.engine.beliefs()
    assert [(one.id, one.supports_gone) for one in listed] == [("rec-1", True)]
    assert await harness.engine.forget("rec-1") is True


async def test_a_legacy_support_reads_as_the_record_it_carries() -> None:
    """ADR-0328 §16:4: a legacy support points at no episode, and shows its record."""
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    carried = legacy_support(
        {"id": "old-1", "kind": "semantic", "content": "the office is in Boston"}
    )
    await harness.memory.add(_memory("old-1", carried))
    store.batches.clear()

    belief = await harness.engine.belief("old-1")

    assert belief is not None
    assert belief.legacy is True
    assert belief.supports[0].content == "the office is in Boston"
    assert belief.supports_gone is False
    assert store.batches == [], "no episode to read, so no batch"


# --- supports resolve in one batch read (ADR-0086 §6) ---------------------


class CountingStore(FakeMemoryStore):
    """A store that records which read shape each call took, and with what ids.

    Both counters matter separately. ``_belief`` reads the memory itself through
    ``get`` and ADR-0086 §6 is explicit that ``get_many`` "does not replace ``get``",
    so a case that merely counted total reads could not tell the one legitimate single
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

    A loop of singles reads the clock once per episode and a batch reads it once, so
    an episode whose expiry falls between two steps resolves under one and not the
    other. Armed rather than stepping from construction, so the fixture's own writes do
    not move it.
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


async def test_a_memory_s_supports_are_resolved_in_one_batch_read() -> None:
    """One ``get_many`` for the memory's episodes, not one ``get`` per support."""
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.singles.clear()
    store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert store.batches == [("ep-1", "ep-2")], "the episodes went in one call, in order"
    assert store.singles == ["rec-1"], (
        "the only single read left is the memory's own id — §6 does not replace `get`"
    )


async def test_a_listing_page_resolves_every_support_in_one_batch() -> None:
    """The listing reads through ``list_beliefs``, then resolves the page in one read."""
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    await harness.memory.add(_episode_record("ep-3", "they wrote 20 °C"))
    await harness.memory.add(_memory("rec-2", remembered_support("ep-3", added_at=AT)))
    store.singles.clear()
    store.batches.clear()

    listed = await harness.engine.beliefs()

    assert {"rec-1", "rec-2"} <= {one.id for one in listed}
    assert len(store.batches) == 1, "one batch for the page"
    assert sorted(store.batches[0]) == ["ep-1", "ep-2", "ep-3"]
    assert store.singles == []


async def test_two_supports_in_one_episode_ask_for_it_once_and_each_shows_its_part() -> None:
    """Each support reads as its own part of the one episode, which is read once (§15:2).

    The input and a round's message are two texts, never the episode's search text
    twice; a round the episode never recorded is gone though the episode resolves.
    """
    harness_store = CountingStore(now=lambda: AT)
    harness = Harness(memory=harness_store)
    held = story_episode("a", text="they asked for metric units")
    assert held.processing_record is not None
    held = held.model_copy(
        update={
            "processing_record": held.processing_record.model_copy(
                update={"rounds": (PlanningRound(id="r-1", recorded_at=AT, text="Metric it is."),)}
            )
        }
    )
    await harness.memory.add(held)
    await harness.memory.add(
        _memory(
            "rec-1",
            said_support(held.id, when=AT, added_at=AT),
            message_support(held.id, round_id="r-1", when=AT, added_at=AT),
            message_support(held.id, round_id="r-never", when=AT, added_at=AT),
        )
    )
    harness_store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert harness_store.batches == [(held.id,)]
    assert [support.content for support in belief.supports] == [
        "they asked for metric units",
        "Metric it is.",
        None,
    ]
    assert belief.supports_gone is False, "the episode resolves; one part of it is missing"


async def test_a_held_episode_missing_the_only_part_is_not_all_gone_on_either_view() -> None:
    """§15:7 keys the all-gone mark on the episode: the listing and the view agree.

    The memory's one support names a round its held episode never recorded, so the part
    is shown as gone while the episode resolves; neither view marks the memory as having
    lost everything it rested on.
    """
    harness = Harness()
    held = story_episode("a", text="they asked for metric units")
    await harness.memory.add(held)
    await harness.memory.add(
        _memory("rec-1", message_support(held.id, round_id="r-never", when=AT, added_at=AT))
    )

    belief = await harness.engine.belief("rec-1")
    (listed,) = [one for one in await harness.engine.beliefs() if one.id == "rec-1"]

    assert belief is not None
    assert belief.supports[0].content is None
    assert belief.supports_gone is False
    assert listed.supports_gone is False


async def test_every_support_of_a_memory_is_judged_at_one_instant() -> None:
    """ADR-0086 §6's snapshot, observed from the consumer: one clock reading.

    Armed, the clock steps an hour per read: the memory's own ``get`` takes ``AT``,
    and the episodes are read next. ``ep-2`` expires 90 minutes in, so a loop of
    singles would show it gone; one batch judges both against one instant.
    """
    clock = SteppingClock(step=timedelta(hours=1))
    store = FakeMemoryStore(now=clock)
    harness = Harness(memory=store)
    await store.add(_episode_record("ep-1", "they asked for metric units"))
    await store.add(
        _episode_record("ep-2", "they asked again in metric", expires_at=AT + timedelta(minutes=90))
    )
    await store.add(
        _memory(
            "rec-1",
            said_support("ep-1", when=AT, added_at=AT),
            said_support("ep-2", when=AT, added_at=AT),
        )
    )
    clock.arm()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [support.content for support in belief.supports] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_the_batch_shows_gone_where_the_singles_would() -> None:
    """``get_many`` never disagrees with ``get``, on any of the three outcomes.

    Absent, expired and not-yet-live in one memory, each in a known position.
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
        _memory(
            "rec-1",
            *(
                said_support(episode, when=AT, added_at=AT)
                for episode in ("ep-live", "ep-expired", "ep-absent", "ep-future")
            ),
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [support.gone for support in belief.supports] == [False, True, True, True]
    assert belief.supports[0].content == "they asked for metric units"


# --- a refused support read is an error, never "gone" (#585) --------------


class RefusingCitationStore(FakeMemoryStore):
    """A store that answers everything but the support batch, **once armed**."""

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        super().__init__(now=now)
        self._armed = False
        self.batches = 0

    def arm(self) -> None:
        """Start refusing every batch from here on."""
        self._armed = True

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        if not self._armed:
            return await super().get_many(record_ids)
        self.batches += 1
        msg = "the support batch cannot be read"
        raise MemoryStoreError(msg)


async def test_belief_propagates_a_store_that_refuses_the_support_read() -> None:
    """A read that failed asserts nothing about the episodes, so it is never shown as gone."""
    store = RefusingCitationStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.arm()

    with pytest.raises(MemoryStoreError):
        await harness.engine.belief("rec-1")


async def test_beliefs_propagates_rather_than_returning_a_page_it_could_not_resolve() -> None:
    """A page whose supports could not be read is no page, never a partial one."""
    store = RefusingCitationStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.arm()

    with pytest.raises(MemoryStoreError):
        await harness.engine.beliefs()

    assert store.batches == 1


# --- ADR-0119 §8: one OPERATION trace per call, at one wiring point -----


#: Public ``Engine`` methods that are not an operation and emit nothing.
#:
#: ``aclose`` alone, and it is not an oversight. Shutdown is not work the engine
#: was asked to do — it is the engine ceasing to accept work — and it is the one
#: public method that deliberately does *not* run through ``_tracked``: tracing it
#: would put a trace's append inside the drain that exists to wait for appends,
#: and the ``TraceSink`` may already be closed by the time it returned.
_UNTRACED = frozenset({"aclose"})


class _TrackedScan(ast.NodeVisitor):
    """Collect every ``self._tracked(...)`` call and the method it sits in."""

    def __init__(self) -> None:
        self._scope: list[str] = []
        #: ``(enclosing method, the seam literal or None)`` per call found.
        self.found: list[tuple[str, str | None]] = []
        #: Every ``async def`` inside ``class Engine``, by name.
        self.methods: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._scope == ["Engine"]:
            self.methods.append(node.name)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "_tracked",
            "_activation_task",
        }:
            seam = (
                next((item.value for item in node.keywords if item.arg == "seam"), None)
                if node.func.attr == "_activation_task"
                else node.args[1]
                if len(node.args) > 1
                else None
            )
            if self._scope[-1] in {"_receive", "_streamed"}:
                # ADR-0274: compatibility methods delegate one admission. The
                # private dispatcher uses the projection selected at that entry.
                assert isinstance(seam, ast.Attribute)
                assert seam.attr == "method"
                assert isinstance(seam.value, ast.Name)
                assert seam.value.id == "projection"
            elif self._scope[-1] in _READERS:
                # ADR-0293 §6, ADR-0323 §2:2: a channel's reader admits its activation
                # from no public call — it is the channel's own spoke — so the seam it
                # is traced under is the reader's, a literal, and is no public
                # operation's.
                assert isinstance(seam, ast.Constant)
                assert seam.value == _READERS[self._scope[-1]]
            else:
                literal = seam.value if isinstance(seam, ast.Constant) else None
                self.found.append((self._scope[-1], literal if isinstance(literal, str) else None))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_receive":
            projection = next(item.value for item in node.keywords if item.arg == "projection")
            assert isinstance(projection, ast.Call)
            assert isinstance(projection.func, ast.Name)
            assert projection.func.id == "ChannelProjection"
            projected_label = projection.args[0]
            assert isinstance(projected_label, ast.Constant)
            assert isinstance(projected_label.value, str)
            self.found.append((self._scope[-1], projected_label.value))
        self.generic_visit(node)


#: The engine's spokes that admit an activation from no public call, by the method that
#: admits it, and the seam each is traced under (ADR-0293 §6, ADR-0323 §2:2), the Task
#: Scheduler's sensor's and the Approvals channel's among them (ADR-0350 §7, ADR-0361 §3).
_READERS: Final = {
    "_read_in": "chat_reader",
    "_line_read_in": "telegram_reader",
    "_admit_task": "task_scheduler",
    # ADR-0361 §3:4: the Approvals channel's sensor admits an outcome's activation.
    "_admit_approval": "approvals",
}


def _tracked_scan() -> _TrackedScan:
    """Parse ``orchestration/engine.py`` and scan it for the wiring point."""
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    scan = _TrackedScan()
    scan.visit(ast.parse(source, filename=engine_module.__file__))
    return scan


def test_every_public_operation_reaches_the_one_wiring_point_exactly_once() -> None:
    """ADR-0119 §8 and §5's one-crossing rule, held structurally rather than by drill.

    §8 places the envelope at ``_tracked`` precisely because it "already wraps every
    public method" — so the claim that makes the placement sound is that the set of
    public methods and the set of traced ones are the same set. Driving all
    twenty-three through a harness would need twenty-three fixtures and would still
    say nothing about the twenty-fourth somebody adds next month.

    Exactly once, not at least once: "one crossing of a seam produces at most one
    trace" (§5), and a method that reached the wiring point twice would record one
    operation as two — inflating every denominator drawn from the stream.
    """
    scan = _tracked_scan()
    expected = {name for name in scan.methods if not name.startswith("_")} - _UNTRACED
    traced = [method for method, _ in scan.found]

    assert sorted(traced) == sorted(expected), (
        "every public operation is traced once and only public operations are"
    )


def test_each_seam_label_is_the_literal_name_of_its_own_method() -> None:
    """The label a measure filters on is the surface a caller invoked (§2, §3).

    Two properties at once. The label is a **literal constant in the emitting
    module**, which is §2's second clause — anything computed at runtime is a string
    the tier discipline cannot vouch for. And it is the method's own name, so a
    measure grouping by seam is grouping by operation rather than by whatever the
    author of the twenty-fourth method happened to type; a seam that drifted from
    its method would silently merge two operations into one population.
    """
    mislabelled = {method: seam for method, seam in _tracked_scan().found if seam != method}

    assert mislabelled == {}, "each _tracked call passes its own method's name"


async def test_the_maintenance_operation_carries_its_counts() -> None:
    """§5's one-crossing rule: the sweep's detail rides on the sweep's own trace.

    "A job with detail the envelope cannot see returns it in the operation's own
    result type, where it becomes metrics on that operation's one trace, rather than
    emitting a second record for the same run."
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(400), _aged(1))
    harness = Harness(traces=traces)

    await harness.engine.purge_expired()

    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "purge_expired"
    assert dict(trace.metrics) == {"records": 0, "traces": 1}


async def test_a_sweep_that_did_not_run_omits_its_key_rather_than_reporting_zero() -> None:
    """§3's observation rule, on the one metric in this lane that can be unobserved.

    "A metric key appears in a trace only when the quantity it names was
    **observed**. An absent key means *not observed* and never zero." A keep-forever
    horizon does not call the trace sweep at all, so a ``0`` here would report a
    store swept clean by a sweep nobody ran — and would do it on the deployment
    whose whole point is that nothing is deleted.
    """
    harness = Harness(trace_retention=None)

    await harness.engine.purge_expired()

    (trace,) = harness.trace_sink.recorded
    assert "traces" not in trace.metrics
    assert dict(trace.metrics) == {"records": 0}


async def test_a_result_too_large_to_return_records_the_refusal_not_a_success() -> None:
    """The trace and the caller's answer must agree (ADR-0119 §3, §8).

    ``_checked`` measures the *result* against ADR-0084 §4's limit, and it used to
    run one frame outside the traced region — so an operation whose page would not
    fit recorded ``OK`` while its caller received an ``OversizedValueError``. A
    stream in which a refused call is indistinguishable from a served one is the
    lie §5 spends its clauses refusing, arriving through placement instead of
    through I/O.

    The refusal is ``REFUSED`` rather than ``FAULT``: a contract limit answered is
    the system working, and ADR-0084 §4 puts the same limit on the way in.

    Driven through ``standing_grants``, which takes no arguments at all, so a
    one-byte ceiling cannot be tripped by the *argument* check that runs before
    ``_tracked`` — an operation refused there emits nothing at all, which is the
    separate gap #855 carries and not the one this case is about.
    ``pending_confirmations`` drove it until it retired (ADR-0309 §5:1).
    """
    harness = Harness()
    harness.engine._max_payload_bytes = 1

    with pytest.raises(OversizedValueError):
        await harness.engine.standing_grants()

    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "standing_grants"
    assert trace.outcome is TraceOutcome.REFUSED
    assert trace.fault_class == "OversizedValueError"


async def test_a_maintenance_report_is_not_measured_against_the_payload_limit() -> None:
    """``checked`` is per operation, and the four maintenance ones are exempt.

    ADR-0085 §1 fixes the promoted ``AssistantEngine`` surface and none of
    ``start``/``purge_expired``/``decide_story_flags`` is on it: their reports
    go to the hub's scheduler in-process and never cross a wire (ADR-0083 §8). They
    were never measured before this lane and they are not measured now — the flag
    exists so that stays a stated fact rather than an accident of which call site
    happened to be wrapped.
    """
    harness = Harness()
    harness.engine._max_payload_bytes = 1

    report = await harness.engine.purge_expired()

    assert report.traces == 0
    (trace,) = harness.trace_sink.recorded
    assert trace.outcome is TraceOutcome.OK


# --- ADR-0151 §6: the connection surface is not traced -----------------------


async def test_no_connection_operation_is_recorded_in_a_trace() -> None:
    """ADR-0151 §6: "No provisioning act, and no operation on this surface, is
    recorded in a trace (ADR-0141), an ``AuditTrail``, a conversation or a plan."

    **The prohibition is categorical rather than credential-scoped**, and that is
    what makes it easy to get wrong. An ``OPERATION`` trace records the seam, the
    outcome, the elapsed time and the fault class — never an argument — so nothing
    about a credential leaks through one, and an implementation reasoning only
    about disclosure would route these five through ``_tracked``'s default like
    every other method and pass every other test in this lane.

    What §6 forecloses is the **act being recorded at all**, and the reason is
    legible in ADR-0151 §18: a connection record deliberately carries *no instant*
    (ADR-0149 §3), so a trace of ``connect_account`` would reintroduce a
    timestamped record of the owner's act through a different door — which §18
    defers to "the first surface that has to answer 'when did I connect this?'".

    **The control is the load-bearing half.** An engine that emitted no traces at
    all would satisfy the first assertion and break ADR-0119 §8 wholesale, so a
    traced operation runs in the same harness and must still appear.
    """
    harness = Harness()

    record = await harness.engine.connect_account(
        identity="ada@example.com", credential=secret_value(SecretStr("hunter2-secret"))
    )
    await harness.engine.reprovision_account(
        record.reference,
        identity="ada@example.com",
        credential=secret_value(SecretStr("rotated-secret")),
    )
    await harness.engine.disconnect_account(record.reference)
    await harness.engine.connected_accounts()
    await harness.engine.recent_connection_acts()
    # The control: an ordinary read, which ADR-0119 §8 requires to be traced.
    await harness.engine.beliefs()

    seams = [trace.seam for trace in harness.trace_sink.recorded]
    assert seams == ["beliefs"], (
        "ADR-0151 §6 forbids a trace for any operation on the connection surface; "
        f"these were recorded: {seams}"
    )


async def test_the_connection_surface_is_still_drained_though_it_is_not_traced() -> None:
    """ADR-0042 §2 survives ADR-0151 §6, which is the half a suppression can break.

    Suppressing the trace and suppressing the *tracking* are one line apart, and
    only the second is forbidden to be kept: the connection store is
    connection-owning like every other, so an untracked provisioning act would let
    :meth:`~ai_assistant.orchestration.engine.Engine.aclose` close the store out
    from under ADR-0148 §6's three writes.

    Asserted through the drain rather than through an attribute: a call in flight
    when ``aclose`` begins is awaited to completion, so the record it was writing
    is there afterwards.
    """
    harness = Harness()

    running = asyncio.ensure_future(
        harness.engine.connect_account(
            identity="ada@example.com", credential=secret_value(SecretStr("hunter2-secret"))
        )
    )
    await asyncio.sleep(0)
    await harness.engine.aclose()
    record = await running

    assert record.state is ProvisioningState.ACTIVE
    assert [trace.seam for trace in harness.trace_sink.recorded] == []


# --- ADR-0181 §4, §10: the origin the engine computes from its own selection ---
# Kept in one block so a rebase across another lane's edits to this module moves
# it whole rather than through it.


@pytest.mark.parametrize("method", ["episodes", "episode_chunk"])
async def test_episode_inspection_is_drained_before_shutdown(method: str) -> None:
    """The store cannot close while an admitted inspection read still owns it."""
    memory = FakeMemoryStore(now=lambda: AT)
    held = memory.suspend_next_operation()
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = Harness(memory=memory, closers=(close,))
    read = asyncio.ensure_future(
        harness.engine.episodes() if method == "episodes" else harness.engine.episode_chunk("")
    )
    try:
        await held.reached()
        closing = asyncio.ensure_future(harness.engine.aclose())
        await asyncio.sleep(0)
        assert not closed.is_set()
        held.release()
        await read
        await closing
        assert closed.is_set()
    finally:
        held.release()
        await harness.engine.aclose()
