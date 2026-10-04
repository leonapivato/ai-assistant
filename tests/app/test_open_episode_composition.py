"""ADR-0286 §15:3: the open episode, through production composition.

An episode is written open at admission, extended as each stage ends, and frozen by
its end entry; a restart closes what a dead process left open (ADR-0286).

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a fresh
data directory, so the stores are the shipped ``sqlite`` ones and the lifecycle, the
coordinator and the activation writer are the ones the root wires. The substitutes
are the model-facing seams — the provider's ``complete``, the planner, the
associator, the streaming completer and the speech fakes — and, where a case needs a
pass to stop at a known point, a wrapper around one of the engine's own stages that
waits there. A process that dies mid-pass is a writer whose freeze never runs.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.errors import ChannelProcessingTimeoutError, TranscriptionFailedError
from ai_assistant.core.types import (
    ActionPlan,
    ActivationLinks,
    AssociationVerdict,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ControllerRule,
    ControllerStage,
    CostBasis,
    EpisodeProcessingRecord,
    EpisodicMemory,
    GoalAssociation,
    Idempotency,
    MemoryWrite,
    MemoryWriteMode,
    NewConversation,
    PlacementReach,
    PlacementSetter,
    PlannerOutput,
    PlanStep,
    ProcessingReason,
    ProcessingStatus,
    ProposedAction,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    Reversibility,
    RiskLevel,
    SpeechChannelPayload,
    SpeechFailure,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    StageOutcome,
    TextChannelPayload,
    TextChannelResult,
    ToolCost,
    ToolDefinition,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.conversations import HISTORY_REPLAY_BOUND, conversation_channel
from ai_assistant.testing import (
    FakeGoalAssociator,
    FakeModelProvider,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    StreamAttempt,
)
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import FrozenJson, GoalBrief, Message
    from ai_assistant.orchestration import Engine
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.activation_writer import ActivationWriter

pytestmark = pytest.mark.integration
_BUDGET = timedelta(seconds=10)
_AT = datetime(2026, 10, 3, tzinfo=UTC)
_UNDERSTANDING_PROMPT = "You read one incoming input and state what it means."
_UNDERSTOOD = json.dumps({"meaning": "The input means what it says.", "meaning_ground": "stated"})
#: The text a case's planner fails on, so the pass ends in its turn loop.
_FAILS = "this pass fails"
#: The text a case's planner answers with one step the root's own policy confirms.
_PARKS = "book it"
#: A side-effecting declaration the root's ``confirm_at_risk`` default confirms.
_BOOKING = ToolDefinition(
    id="book_table",
    capability="book_table",
    description="Book a table.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
)
_SENSOR = ChannelIdentity(channel_type="informational_event", instance_id="sensor")
#: Numbers each engine a case builds, so their plan ids never collide in one store.
_ENGINES = count()


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if _UNDERSTANDING_PROMPT in messages[0].content else "Noted."


@dataclass
class Composed:
    """The engine the root built, and what its booking tool saw stored when it ran."""

    engine: Engine
    #: What the store held at the running resume's address when the booking ran.
    booked: list[EpisodicMemory | None] = field(default_factory=list)

    @property
    def memory(self) -> MemoryStore:
        """The memory store the lifecycle and the writer were handed."""
        return self.engine._conversations._memory

    @property
    def writer(self) -> ActivationWriter:
        """The activation writer the lifecycle built."""
        return self.engine._conversations.activation_writer

    async def say(self, text: str, conversation_id: str | None = None) -> ChannelResult:
        """One text activation on a new conversation, or on the one named."""
        target = (
            NewConversation()
            if conversation_id is None
            else ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
        )
        return await self.engine.receive(
            ChannelInput(target=target, payload=TextChannelPayload(text=text)),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )

    async def stored(self, address: str) -> EpisodicMemory | None:
        """The episode the store holds at ``address``, open or frozen."""
        record = await self.memory.get(address)
        assert record is None or isinstance(record, EpisodicMemory)
        return record

    async def held(self, conversation_id: str) -> list[str]:
        """Every id the store physically holds on the conversation's channel."""
        page = await self.memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1000
        )
        return [entry.episode_id for entry in page]

    def cut_off(self) -> None:
        """Make every later freeze not happen, as a process dying mid-pass leaves it."""

        async def died(state: ActivationState, *_args: object, **_kwargs: object) -> object:
            return state.degraded_report()

        # A test double standing in for the bound method, its signature loosened.
        self.writer.write = died  # type: ignore[method-assign,assignment]


async def _build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, start: bool = True
) -> Composed:
    """Wire the production root, substituting only the model-facing seams."""
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)
    model = FakeModelProvider(_reply)

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    engine = build_engine(settings, data_dir=tmp_path)
    engine._associator = FakeGoalAssociator(
        answer=GoalAssociation(verdict=AssociationVerdict.FRESH)
    )
    engine._routing = None
    engine._transcriber = FakeSpeechTranscriber(transcripts=["  spoken words  "] * 8)
    engine._synthesizer = FakeSpeechSynthesizer()
    engine._composing._streaming = FakeStreamingCompleter(
        script=tuple(StreamAttempt(deltas=("Channel reply.",)) for _ in range(64))
    )
    # A second engine over the same data directory must not reuse a plan id.
    plan_ids = count(1 + 1000 * next(_ENGINES))

    async def plan(goal: GoalBrief, *, utterance: str, **_kwargs: object) -> PlannerOutput:
        if utterance == _FAILS:
            msg = "the planner is down"
            raise RuntimeError(msg)
        steps: tuple[PlanStep, ...] = ()
        actions: tuple[ProposedAction, ...] = ()
        if utterance == _PARKS:
            steps = (
                PlanStep(
                    id="step-1",
                    intent="book the table",
                    capability=_BOOKING.capability,
                    parameters={},
                    intended_action=f"A{len(goal.actions) + 1}",
                ),
            )
            actions = (ProposedAction(intent="book the table"),)
        return PlannerOutput(
            actions=actions,
            plan=ActionPlan(
                id=f"open-plan-{next(plan_ids)}", goal_id=goal.goal_id, steps=steps, created_at=_AT
            ),
        )

    monkeypatch.setattr(engine._loop._planner, "plan", plan)
    composed = Composed(engine)

    async def book(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        del parameters, idempotency_key
        state = active_state()
        assert state is not None
        assert state.episode_address is not None
        composed.booked.append(await composed.stored(state.episode_address))
        return {"booked": True}

    registry = engine._runner._registry
    assert isinstance(registry, InMemoryToolRegistry)
    registry.register(_BOOKING, book)
    if start:
        await engine.start()
    return composed


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Composed]:
    """The production root over a fresh data directory, started."""
    built = await _build(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        await built.engine.aclose()


def _conversation(result: ChannelResult) -> str:
    assert result.channel is not None
    assert result.channel.channel_type == "conversation"
    return result.channel.instance_id


def _address(result: ChannelResult) -> str:
    assert result.capture.activation_id is not None
    return f"activation:{result.capture.activation_id}"


def _open(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted open (ADR-0286 §1)."""
    assert record is not None
    processing = record.processing_record
    assert processing is not None
    assert processing.is_open, "the episode is open"
    assert record.content == ""
    assert record.placement.reach is PlacementReach.OWNER
    assert record.placement.set_by is PlacementSetter.DERIVED
    return processing


def _frozen(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted frozen."""
    assert record is not None
    processing = record.processing_record
    assert processing is not None
    assert not processing.is_open, "the episode is frozen"
    return processing


@dataclass
class Gate:
    """A stage wrapper's stopping point: where a matching pass waits, and what it saw."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    addresses: list[str] = field(default_factory=list)
    working: list[Any] = field(default_factory=list)

    @property
    def address(self) -> str:
        """The address of the pass that waited here."""
        (address,) = self.addresses
        return address


def _hold(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    stage: str,
    matches: Callable[[Any], bool],
) -> Gate:
    """Hold a matching pass once ``stage``'s body returns, before its entry is appended."""
    gate = Gate()
    original: Callable[[Any], Awaitable[None]] = getattr(engine, stage)

    async def held(working: Any) -> None:
        await original(working)
        if matches(working):
            state = active_state()
            assert state is not None
            assert state.episode_address is not None
            gate.addresses.append(state.episode_address)
            gate.working.append(working)
            gate.entered.set()
            await gate.release.wait()

    monkeypatch.setattr(engine, stage, held)
    return gate


def _saying(text: str) -> Callable[[Any], bool]:
    return lambda working: getattr(working, "utterance", None) == text


# --- an episode is stored open before the first stage -------------------------------


def _before_first_stage(
    monkeypatch: pytest.MonkeyPatch, composed: Composed, stage: str
) -> list[EpisodicMemory | None]:
    """What the store holds at the running pass's address as ``stage`` is entered."""
    seen: list[EpisodicMemory | None] = []
    original: Callable[[Any], Awaitable[None]] = getattr(composed.engine, stage)

    async def observed(working: Any) -> None:
        state = active_state()
        assert state is not None
        assert state.episode_address is not None
        if not state.stages.entries:
            seen.append(await composed.stored(state.episode_address))
        await original(working)

    monkeypatch.setattr(composed.engine, stage, observed)
    return seen


async def test_a_typed_turns_episode_is_stored_open_before_its_first_stage(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1: inserted at admission, before any processing, carrying no stage entry."""
    seen = _before_first_stage(monkeypatch, composed, "_begin_conversation_stage")

    result = await composed.say("hello")

    (opened,) = seen
    processing = _open(opened)
    assert opened is not None
    assert opened.id == _address(result)
    assert processing.stages == ()
    assert processing.trigger.channel is None, "a conversational target is not resolved yet"
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    assert result.capture.state == "recorded"
    frozen = await composed.stored(_address(result))
    _frozen(frozen)
    assert frozen is not None
    # §2:2: the admission write's one capture timestamp, reused by the freeze.
    assert frozen.occurred_at == opened.occurred_at


async def test_a_spoken_turns_episode_is_stored_open_before_its_first_stage(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1 for speech: the open record carries the trigger as admitted, no transcript."""
    seen = _before_first_stage(monkeypatch, composed, "_begin_conversation_stage")

    result = await composed.engine.receive(
        ChannelInput(
            target=NewConversation(),
            payload=SpeechChannelPayload(
                audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
            ),
        ),
        reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        timeout=_BUDGET,
    )

    (opened,) = seen
    processing = _open(opened)
    assert processing.stages == ()
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    assert isinstance(processing.trigger.payload, RecordedSpeechInput)
    frozen = _frozen(await composed.stored(_address(result)))
    assert isinstance(frozen.trigger, RecordedChannelTrigger)
    assert isinstance(frozen.trigger.payload, RecordedSpeechInput)
    assert frozen.trigger.payload.transcript == "  spoken words  "


async def test_an_informational_events_episode_is_stored_open_before_its_first_stage(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1 for an event: its channel is set at admission, from the accepted identity."""
    seen = _before_first_stage(monkeypatch, composed, "_windows_stage")

    result = await composed.engine.receive(
        ChannelInput(target=_SENSOR, payload=TextChannelPayload(text="eco mode")),
        reply=None,
        timeout=_BUDGET,
    )

    (opened,) = seen
    processing = _open(opened)
    assert processing.stages == ()
    assert processing.trigger.channel == _SENSOR
    _frozen(await composed.stored(_address(result)))


async def test_an_append_runs_inside_the_pass_deadline(composed: Composed) -> None:
    """§3:8: an append whose store never answers is cut off at the pass's deadline; the
    pass times out as its kind classifies the expiry, and the freeze still records."""
    addresses: list[str] = []

    async def never(state: ActivationState, **_kwargs: object) -> None:
        assert state.episode_address is not None
        addresses.append(state.episode_address)
        await asyncio.Event().wait()

    # A test double for the bound method: the store read it makes never returns.
    composed.writer.append = never  # type: ignore[method-assign]

    with pytest.raises(ChannelProcessingTimeoutError):
        await asyncio.wait_for(
            composed.engine.receive(
                ChannelInput(target=_SENSOR, payload=TextChannelPayload(text="eco mode")),
                reply=None,
                timeout=timedelta(milliseconds=300),
            ),
            timeout=5,
        )

    processing = _frozen(await composed.stored(addresses[0]))
    assert processing.status is not ProcessingStatus.COMPLETED
    assert processing.stages[-1].due is ControllerRule.STAGE_TIMED_OUT


async def test_the_admission_write_runs_inside_the_calls_deadline(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0274 §7, ADR-0286 §2:1: an event's budget starts at receiver admission, so an
    admission insert the store never answers is cut off there; the event times out as
    its kind classifies the expiry, and the insert that never landed leaves nothing."""
    addresses = _admission_never_answers(monkeypatch, composed)

    with pytest.raises(ChannelProcessingTimeoutError):
        await asyncio.wait_for(
            composed.engine.receive(
                ChannelInput(target=_SENSOR, payload=TextChannelPayload(text="eco mode")),
                reply=None,
                timeout=timedelta(milliseconds=300),
            ),
            timeout=5,
        )

    (address,) = addresses
    assert await composed.stored(address) is None
    assert not composed.writer.holds(address)


async def test_a_spoken_turn_is_handed_only_what_its_admission_write_left_of_the_budget(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0274 §6, ADR-0200 §3: the whole speech-call budget starts at receiver
    admission, so an admission write that spends all of it leaves the transcription an
    exhausted budget — its own expiry, with the seam never called."""
    addresses = _admission_never_answers(monkeypatch, composed)
    transcriber = composed.engine._transcriber
    assert isinstance(transcriber, FakeSpeechTranscriber)

    with pytest.raises(TranscriptionFailedError) as refused:
        await asyncio.wait_for(
            composed.engine.receive(
                ChannelInput(
                    target=NewConversation(),
                    payload=SpeechChannelPayload(
                        audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
                    ),
                ),
                reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
                timeout=timedelta(milliseconds=300),
            ),
            timeout=5,
        )

    assert refused.value.failure is SpeechFailure.TIMED_OUT
    assert transcriber.calls == []
    (address,) = addresses
    assert await composed.stored(address) is None


def _admission_never_answers(monkeypatch: pytest.MonkeyPatch, composed: Composed) -> list[str]:
    """Make the store never answer the first admission insert; record its address."""
    addresses: list[str] = []
    original = composed.memory.write_atomic

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        if not addresses and any(
            write.mode is MemoryWriteMode.INSERT_IF_ABSENT for write in writes
        ):
            addresses.append(writes[0].record.id)
            await asyncio.Event().wait()
        return await original(writes)

    monkeypatch.setattr(composed.memory, "write_atomic", write_atomic)
    return addresses


async def _parked(composed: Composed) -> tuple[str, str, Any]:
    """A conversation whose activation parked a confirmation: its id, episode, token."""
    result = await composed.say(_PARKS)
    assert isinstance(result.result, TextChannelResult)
    step = result.result.outcome.step
    assert step is not None
    assert step.confirmation is not None, "the root's policy confirms the booking"
    assert result.capture.state == "recorded"
    return _conversation(result), _address(result), step.confirmation.token


async def test_a_resumes_episode_is_stored_open_before_its_first_stage(
    composed: Composed,
) -> None:
    """§2:3, §9: written once its conversation is resolved, before the resumed step runs.

    The booking runs inside the resume's ``drive`` stage, after its resolution point:
    what the store holds there is the resume's open episode, its parked binding and
    predecessor linked and no stage ended yet.
    """
    conversation_id, parking, token = await _parked(composed)

    resumed = await composed.engine.resume(token, approved=True, timeout=_BUDGET)

    assert resumed.capture_degraded is False
    (opened,) = composed.booked
    processing = _open(opened)
    assert processing.stages == ()
    assert isinstance(processing.trigger, RecordedResumeTrigger)
    assert processing.trigger.channel == conversation_channel(conversation_id)
    assert processing.links.predecessor_episode_id == parking
    assert opened is not None
    frozen = _frozen(await composed.stored(opened.id))
    assert [entry.stage for entry in frozen.stages] == [
        ControllerStage.DRIVE,
        ControllerStage.COMPOSE,
        ControllerStage.END,
    ]


# --- each stage appends, and the frozen record is the one-write record ----------------


def _appends(
    monkeypatch: pytest.MonkeyPatch, composed: Composed
) -> list[EpisodeProcessingRecord | None]:
    """What the store holds after each of the engine's appends."""
    after: list[EpisodeProcessingRecord | None] = []
    coordinator = composed.engine._activation_coordinator
    original = coordinator.append

    async def append(state: ActivationState) -> None:
        await original(state)
        assert state.episode_address is not None
        record = await composed.stored(state.episode_address)
        after.append(None if record is None else record.processing_record)

    monkeypatch.setattr(coordinator, "append", append)
    return after


async def test_each_stage_end_leaves_one_more_entry_on_the_stored_record(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3:1: every stage's end replaces the stored episode with one more entry, open; the
    end entry is the freeze's (§4:1). A resume appends the same way (§9)."""
    after = _appends(monkeypatch, composed)

    result = await composed.say("hello")

    frozen = _frozen(await composed.stored(_address(result)))
    assert len(after) == len(frozen.stages) - 1
    for count_, stored in enumerate(after, start=1):
        assert stored is not None
        assert stored.is_open
        assert len(stored.stages) == count_
        assert stored.stages == frozen.stages[:count_]
    assert frozen.stages[-1].stage is ControllerStage.END

    after.clear()
    _conversation_id, _parking, token = await _parked(composed)
    after.clear()
    await composed.engine.resume(token, approved=True, timeout=_BUDGET)
    assert [len(stored.stages) for stored in after if stored is not None] == [1, 2]


async def test_a_frozen_record_is_the_one_a_single_write_at_the_end_would_store(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3's closing paragraph: both bounds keep a fixed head and a sliding tail, so a
    record frozen through appends equals the one-write record — here with a stage bound
    small enough that the appends cut it, so the elision is exercised on the way."""
    composed.engine._stage_record_limit = 3
    states: list[ActivationState] = []
    original = composed.engine._begin_conversation_stage

    async def keep(working: Any) -> None:
        state = active_state()
        assert state is not None
        states.append(state)
        await original(working)

    monkeypatch.setattr(composed.engine, "_begin_conversation_stage", keep)

    result = await composed.say("hello")

    assert result.capture.state == "recorded"
    frozen = _frozen(await composed.stored(_address(result)))
    (state,) = states
    assert frozen.ended_at is not None
    assert frozen == state.processing(frozen.ended_at, None)
    assert frozen.stages_elided > 0, "the bound cut the record"
    assert len(frozen.stages) == 3


# --- the reads that feed a model pass over open episodes ------------------------------


async def test_history_recall_and_the_episode_window_never_return_an_open_episode(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: neither another activation's open episode nor the running one's own reaches
    history, recall or the episode window, and the running one takes no history slot.

    The conversation holds a full history bound of frozen episodes. One pass is held
    open on it, its channel set; a second pass then runs on the same conversation, and
    what its windows stage assembled and what its history reads are checked while both
    open episodes are on the channel.
    """
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    template = await composed.stored(_address(first))
    assert template is not None
    for n in range(HISTORY_REPLAY_BOUND):
        await composed.memory.add(template.model_copy(update={"id": f"activation:copy-{n:02d}"}))
    gate = _hold(monkeypatch, composed.engine, "_windows_stage", _saying("held open"))
    observed: dict[str, Any] = {}
    original = composed.engine._windows_stage

    async def windows(working: Any) -> None:
        await original(working)
        if getattr(working, "utterance", None) == "while it is open":
            state = active_state()
            assert state is not None
            observed["own"] = state.episode_address
            observed["windows"] = working.windows
            observed["history"] = await composed.engine._conversations.history(conversation_id)
            observed["on_channel"] = await composed.held(conversation_id)

    monkeypatch.setattr(composed.engine, "_windows_stage", windows)
    held = asyncio.create_task(composed.say("held open", conversation_id))
    await gate.entered.wait()
    try:
        second = await composed.say("while it is open", conversation_id)
    finally:
        gate.release.set()
    await held

    own, other = observed["own"], gate.address
    open_ids = {own, other}
    assert open_ids <= set(observed["on_channel"]), "both are open on the channel"
    history = [record.id for record in observed["history"].records]
    assert len(history) == HISTORY_REPLAY_BOUND, "the running episode takes no slot"
    assert not open_ids & set(history)
    window = observed["windows"].episode_ids
    assert window, "the episode window holds the frozen episodes"
    assert not open_ids & set(window)
    recall = _frozen(await composed.stored(_address(second))).recall
    assert recall is not None
    assert not open_ids & {item.id for item in recall.items}


# --- a restart closes what a dead process left open ------------------------------------


async def test_a_start_closes_an_open_episode_a_dead_process_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: closed ``interrupted`` / ``hub_stopped`` by an end entry due ``hub_stopped``,
    owner-only, and its turn recorded on its conversation."""
    dying = await _build(tmp_path, monkeypatch)
    try:
        conversation_id = _conversation(await dying.say("hello"))
        dying.cut_off()
        result = await dying.say("dies mid-pass", conversation_id)
        address = _address(result)
        left = _open(await dying.stored(address))
        assert left.stages, "its stages were appended before it died"
    finally:
        await dying.engine.aclose()

    restarted = await _build(tmp_path, monkeypatch)
    try:
        closed = await restarted.stored(address)
        processing = _frozen(closed)
        assert closed is not None
        assert processing.status is ProcessingStatus.INTERRUPTED
        assert processing.reason is ProcessingReason.HUB_STOPPED
        end = processing.stages[-1]
        assert end.stage is ControllerStage.END
        assert end.due is ControllerRule.HUB_STOPPED
        assert end.outcome is StageOutcome.DONE
        assert end.started_at == end.ended_at == processing.ended_at
        assert processing.stages[:-1] == left.stages
        assert closed.placement.reach is PlacementReach.OWNER
        assert closed.placement.set_by is PlacementSetter.DERIVED
        assert closed.content == episode_content(closed)
        assert address in await restarted.held(conversation_id)
        conversation = await restarted.engine._conversations._conversations.get(conversation_id)
        assert conversation is not None
        assert conversation.last_turn_at == closed.occurred_at, "§7:3: record_turn was called"
    finally:
        await restarted.engine.aclose()


async def test_a_start_closes_no_episode_this_engine_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:2: a second ``start`` closes nothing this engine admitted, and nor does a first
    ``start`` that comes after an admission — the writer holds that episode."""
    started = await _build(tmp_path, monkeypatch)
    try:
        conversation_id = _conversation(await started.say("hello"))
        gate = _hold(monkeypatch, started.engine, "_windows_stage", _saying("still running"))
        running = asyncio.create_task(started.say("still running", conversation_id))
        await gate.entered.wait()
        try:
            await started.engine.start()
            _open(await started.stored(gate.address))
        finally:
            gate.release.set()
        assert (await running).capture.state == "recorded"
        assert _frozen(await started.stored(gate.address)).status is ProcessingStatus.COMPLETED
    finally:
        await started.engine.aclose()

    unstarted = await _build(tmp_path, monkeypatch, start=False)
    try:
        gate = _hold(monkeypatch, unstarted.engine, "_windows_stage", _saying("admitted first"))
        running = asyncio.create_task(unstarted.say("admitted first", conversation_id))
        await gate.entered.wait()
        try:
            await unstarted.engine.start()
            _open(await unstarted.stored(gate.address))
        finally:
            gate.release.set()
        assert (await running).capture.state == "recorded"
    finally:
        await unstarted.engine.aclose()


async def test_a_restart_closes_with_the_externality_the_pass_last_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4:3, §7:3: a resume of a parked turn whose value is true, cut off after it
    composes, is closed carrying it true; a pass cut off before it held a value is
    closed carrying ``False``."""
    dying = await _build(tmp_path, monkeypatch)
    try:
        conversation_id, _parking, token = await _parked(dying)
        parked = dying.engine._parked[token.handle]
        dying.engine._parked[token.handle] = replace(parked, derived_from_external=True)
        dying.cut_off()
        await dying.engine.resume(token, approved=True, timeout=_BUDGET)
        (resumed,) = await dying.memory.open_episodes(limit=10)
        resume_address = resumed.record.id
        assert [entry.stage for entry in _open(resumed.record).stages] == [
            ControllerStage.DRIVE,
            ControllerStage.COMPOSE,
        ]
        with pytest.raises(RuntimeError, match="the planner is down"):
            await dying.say(_FAILS, conversation_id)
        opened = await dying.memory.open_episodes(limit=10)
        (failed,) = [entry.record for entry in opened if entry.record.id != resume_address]
        failed_address = failed.id
        assert failed.provenance.derived_from_external is False
    finally:
        await dying.engine.aclose()

    restarted = await _build(tmp_path, monkeypatch)
    try:
        resume = await restarted.stored(resume_address)
        assert _frozen(resume).reason is ProcessingReason.HUB_STOPPED
        assert resume is not None
        assert resume.provenance.derived_from_external is True
        unvalued = await restarted.stored(failed_address)
        assert _frozen(unvalued).reason is ProcessingReason.HUB_STOPPED
        assert unvalued is not None
        assert unvalued.provenance.derived_from_external is False
        assert await restarted.memory.open_episodes(limit=10) == ()
    finally:
        await restarted.engine.aclose()


# --- a capture failure ends capture and leaves no episode -----------------------------


def _episode_writes(monkeypatch: pytest.MonkeyPatch, memory: MemoryStore) -> list[str]:
    """Every record id the memory store is asked to write, in order."""
    written: list[str] = []
    original = memory.write_atomic

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written.extend(write.record.id for write in writes)
        return await original(writes)

    monkeypatch.setattr(memory, "write_atomic", write_atomic)
    return written


async def test_forget_during_a_pass_leaves_no_episode_and_its_later_stages_write_nothing(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8: ``forget`` deletes the open episode at once; the pass runs on, its next write
    deletes instead, and nothing re-creates the episode."""
    conversation_id = _conversation(await composed.say("hello"))
    gate = _hold(monkeypatch, composed.engine, "_windows_stage", _saying("forget me"))
    written = _episode_writes(monkeypatch, composed.memory)
    running = asyncio.create_task(composed.say("forget me", conversation_id))
    await gate.entered.wait()
    try:
        address = gate.address
        _open(await composed.stored(address))
        assert await composed.engine.forget(address) is True
        mark = len(written)
    finally:
        gate.release.set()
    result = await running

    assert result.capture.state == "degraded"
    assert address not in written[mark:], "no write after the forget names the episode"
    assert await composed.stored(address) is None
    assert address not in await composed.held(conversation_id)


async def test_a_conversation_deleted_during_a_pass_leaves_no_episode(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5, ADR-0283 §8:1: the deletion sweep takes the open episode on its channel, and
    the pass's next write finds no record — a mismatch, so capture ends."""
    conversation_id = _conversation(await composed.say("hello"))
    gate = _hold(monkeypatch, composed.engine, "_windows_stage", _saying("deleted under it"))
    running = asyncio.create_task(composed.say("deleted under it", conversation_id))
    await gate.entered.wait()
    try:
        address = gate.address
        assert address in await composed.held(conversation_id), "its channel was appended"
        assert await composed.engine.forget_conversation(conversation_id) is True
    finally:
        gate.release.set()
    result = await running

    assert result.capture.state == "degraded"
    assert await composed.stored(address) is None
    assert await composed.held(conversation_id) == []


async def test_a_forced_mismatch_reports_the_capture_degraded_and_leaves_no_episode(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3:4, §5: a stored record other than the one last written ends capture without a
    retry, deletes the episode, and the pass's answer stands."""
    conversation_id = _conversation(await composed.say("hello"))
    gate = _hold(monkeypatch, composed.engine, "_windows_stage", _saying("moved under it"))
    running = asyncio.create_task(composed.say("moved under it", conversation_id))
    await gate.entered.wait()
    try:
        address = gate.address
        stored = await composed.stored(address)
        processing = _open(stored)
        assert stored is not None
        moved = stored.model_copy(
            update={
                "processing_record": processing.model_copy(
                    update={"links": ActivationLinks(question_id="someone-else")}
                )
            }
        )
        await composed.memory.write_atomic([MemoryWrite(record=moved)])
    finally:
        gate.release.set()
    result = await running

    assert result.capture.state == "degraded"
    assert isinstance(result.result, TextChannelResult)
    assert result.result.outcome.reply is not None, "processing was not failed by it"
    assert await composed.stored(address) is None


async def test_an_admission_collision_deletes_nothing(composed: Composed) -> None:
    """§2:4: the record at the address is not this activation's, so the collision writes
    nothing there and deletes nothing there."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    template = await composed.stored(_address(first))
    assert template is not None
    minted = "5b7c0f0e-7a43-4d0c-9d3e-0c1f7f3a2b61"
    address = f"activation:{minted}"
    await composed.memory.add(template.model_copy(update={"id": address}))
    before = await composed.stored(address)
    composed.engine._activation_id_factory = lambda: minted

    result = await composed.say("collides", conversation_id)

    assert result.capture.state == "degraded"
    assert result.capture.episode_id is None
    assert await composed.stored(address) == before
