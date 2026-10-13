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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ChannelProcessingTimeoutError
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ControllerRule,
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
    ProcessingStatus,
    ProposedAction,
    Reversibility,
    RiskLevel,
    TextChannelPayload,
    ToolCost,
    ToolDefinition,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.channels import ChannelProjection
from ai_assistant.orchestration.conversations import conversation_channel
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
        # ADR-0293 §11 takes the text conversational combination off ``receive``, and
        # ``converse`` — which still runs it, for the turn carrying a reference — returns
        # the bare outcome. These cases are about how that turn's episode is captured,
        # so they drive the same admission ``converse`` does and read its receipt.
        return await self.engine._receive(
            ChannelInput(target=target, payload=TextChannelPayload(text=text)),
            reply=WholeTextReply(),
            timeout=_BUDGET,
            projection=ChannelProjection("converse"),
            typed_turn=True,
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
