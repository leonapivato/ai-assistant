"""ADR-0283 §14:2: a channel's history is its episodes, through production composition.

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a
fresh data directory, so the stores are the shipped ``sqlite`` ones, the
lifecycle and the activation writer are the ones the root wires, and the only
substitutes are the model-facing seams: the provider's ``complete``, the planner,
the associator and the streaming completer. Nothing here reaches past the engine
into a store it does not hold, and the assertions read the stores the engine
itself reads.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    CostBasis,
    EpisodicMemory,
    GoalAssociation,
    Idempotency,
    NewConversation,
    PlannerOutput,
    PlanStep,
    ProcessingReason,
    ProcessingStatus,
    ProposedAction,
    Reversibility,
    RiskLevel,
    TextChannelPayload,
    TextChannelResult,
    ToolCost,
    ToolDefinition,
    Validity,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.conversations import HISTORY_REPLAY_BOUND, conversation_channel
from ai_assistant.testing import (
    FakeGoalAssociator,
    FakeModelProvider,
    FakeStreamingCompleter,
    StreamAttempt,
)
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import FrozenJson, GoalBrief, MemoryWrite, Message
    from ai_assistant.orchestration import Engine

pytestmark = pytest.mark.integration
_BUDGET = timedelta(seconds=10)
_AT = datetime(2026, 9, 18, tzinfo=UTC)
_UNDERSTANDING_PROMPT = "You read one incoming input and state what it means."
_UNDERSTOOD = json.dumps({"meaning": "The input means what it says.", "meaning_ground": "stated"})
#: The text a case's planner fails on, so a pass ends before capture (ADR-0275 §6).
_FAILS = "this pass fails"
#: The text a case's planner answers with one step the root's own policy confirms.
_PARKS = "book it"
#: A side-effecting declaration at a risk the root's ``confirm_at_risk`` default
#: confirms, disclosing nothing, so the root's policy parks it with no egress binding.
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


async def _book(parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None) -> FrozenJson:
    """The booking's implementation: it does nothing and says so."""
    del parameters, idempotency_key
    return {"booked": True}


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if _UNDERSTANDING_PROMPT in messages[0].content else "Noted."


@dataclass
class Composed:
    """The engine the root built, and the handles its own stages hold."""

    engine: Engine

    @property
    def memory(self) -> MemoryStore:
        """The memory store the lifecycle and the writer were handed."""
        return self.engine._conversations._memory

    @property
    def conversations(self) -> ConversationStore:
        """The conversation store the lifecycle was handed."""
        return self.engine._conversations._conversations

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

    async def fail(self, conversation_id: str) -> str:
        """One activation whose pass raises before capture; the episode it left."""
        before = await self.held(conversation_id)
        with pytest.raises(RuntimeError, match="the planner is down"):
            await self.say(_FAILS, conversation_id)
        after = await self.held(conversation_id)
        assert after[: len(before)] == before
        (recorded,) = after[len(before) :]
        return recorded

    async def held(self, conversation_id: str) -> list[str]:
        """Every id the store physically holds on the conversation's channel."""
        page = await self.memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1000
        )
        return [entry.episode_id for entry in page]


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Composed]:
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
    engine._composing._streaming = FakeStreamingCompleter(
        script=tuple(StreamAttempt(deltas=("Channel reply.",)) for _ in range(64))
    )
    plan_ids = count(1)

    async def plan(goal: GoalBrief, *, utterance: str, **_kwargs: object) -> PlannerOutput:
        if utterance == _FAILS:
            msg = "the planner is down"
            raise RuntimeError(msg)
        if utterance == _PARKS:
            step = PlanStep(
                id="step-1",
                intent="book the table",
                capability=_BOOKING.capability,
                parameters={},
                intended_action=f"A{len(goal.actions) + 1}",
            )
            return PlannerOutput(
                actions=(ProposedAction(intent="book the table"),),
                plan=ActionPlan(
                    id=f"history-plan-{next(plan_ids)}",
                    goal_id=goal.goal_id,
                    steps=(step,),
                    created_at=_AT,
                ),
            )
        return PlannerOutput(
            plan=ActionPlan(
                id=f"history-plan-{next(plan_ids)}", goal_id=goal.goal_id, steps=(), created_at=_AT
            )
        )

    monkeypatch.setattr(engine._loop._planner, "plan", plan)
    registry = engine._runner._registry
    assert isinstance(registry, InMemoryToolRegistry)
    registry.register(_BOOKING, _book)
    await engine.start()
    try:
        yield Composed(engine)
    finally:
        await engine.aclose()


def _conversation(result: ChannelResult) -> str:
    assert result.channel is not None
    assert result.channel.channel_type == "conversation"
    return result.channel.instance_id


async def test_a_conversational_episode_is_named_for_its_activation_on_its_channel(
    composed: Composed,
) -> None:
    """§2: the id is ``activation:<activation_id>``, and its channel names the conversation."""
    result = await composed.say("hello")

    assert result.capture.state == "recorded"
    assert result.capture.activation_id is not None
    assert result.capture.episode_id == f"activation:{result.capture.activation_id}"
    episode = await composed.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    conversation_id = _conversation(result)
    assert episode.processing_record.trigger.channel == conversation_channel(conversation_id)
    assert await composed.held(conversation_id) == [result.capture.episode_id]


async def test_history_returns_the_channels_eligible_episodes_in_number_order_within_the_bound(
    composed: Composed,
) -> None:
    """§4:1: the newest ``HISTORY_REPLAY_BOUND`` eligible episodes, number ascending.

    The channel is filled past the bound with copies of a real episode, and the
    newest of them is made ineligible: it is on the channel, and it consumes no
    place in the page.
    """
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    assert first.capture.episode_id is not None
    template = await composed.memory.get(first.capture.episode_id)
    assert isinstance(template, EpisodicMemory)
    copies = [
        template.model_copy(update={"id": f"activation:copy-{n:02d}"})
        for n in range(HISTORY_REPLAY_BOUND + 2)
    ]
    for copy in copies:
        await composed.memory.add(copy)
    assert template.processing_record is not None
    ineligible = template.model_copy(
        update={
            "id": "activation:ineligible",
            "processing_record": template.processing_record.model_copy(
                update={
                    "status": ProcessingStatus.FAILED,
                    "reason": ProcessingReason.PROCESSING_FAILED,
                    "model_eligible": False,
                }
            ),
        }
    )
    await composed.memory.add(ineligible)

    history = await composed.engine._conversations.history(conversation_id)

    assert history.degraded is False
    assert [record.id for record in history.records] == [
        copy.id for copy in copies[-HISTORY_REPLAY_BOUND:]
    ]
    assert "activation:ineligible" in await composed.held(conversation_id)


async def test_a_pass_that_ends_before_capture_is_on_the_channel_and_absent_from_history(
    composed: Composed,
) -> None:
    """§4:1 with ADR-0275 §7: the failed pass is recorded, ineligible, and never replayed."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)

    failed = await composed.fail(conversation_id)

    assert failed.startswith("activation:")
    episode = await composed.memory.get(failed)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.model_eligible is False
    assert episode.processing_record.trigger.channel == conversation_channel(conversation_id)
    assert await composed.held(conversation_id) == [first.capture.episode_id, failed]
    history = await composed.engine._conversations.history(conversation_id)
    assert [record.id for record in history.records] == [first.capture.episode_id]


async def _parked(composed: Composed) -> tuple[str, str, Any]:
    """A conversation whose activation parked a confirmation: its id, episode, token."""
    result = await composed.say(_PARKS)
    assert isinstance(result.result, TextChannelResult)
    step = result.result.outcome.step
    assert step is not None
    assert step.confirmation is not None, "the root's policy confirms the booking"
    assert result.capture.state == "recorded"
    assert result.capture.episode_id is not None
    episode = await composed.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.links.parks is not None, "§3:4: the writer set parks"
    return _conversation(result), result.capture.episode_id, step.confirmation.token


async def test_a_resume_finds_its_conversation_through_the_parking_episode(
    composed: Composed,
) -> None:
    """§5: the resumption is recorded on the conversation whose episode parked it."""
    conversation_id, parking, token = await _parked(composed)

    resumed = await composed.engine.resume(token, approved=True, timeout=_BUDGET)

    assert resumed.conversation_id == conversation_id
    assert resumed.capture_degraded is False
    held = await composed.held(conversation_id)
    assert len(held) == 2
    assert held[0] == parking
    resolution = await composed.memory.get(held[1])
    assert isinstance(resolution, EpisodicMemory)
    assert resolution.processing_record is not None
    assert resolution.processing_record.links.predecessor_episode_id == parking
    assert resolution.processing_record.trigger.channel == conversation_channel(conversation_id)


async def test_a_resume_whose_parking_episode_is_gone_degrades(composed: Composed) -> None:
    """§5: no live episode parked the binding, so nothing is recorded and it says so."""
    conversation_id, parking, token = await _parked(composed)
    assert await composed.memory.delete(parking) is True

    resumed = await composed.engine.resume(token, approved=True, timeout=_BUDGET)

    assert resumed.conversation_id is None
    assert resumed.capture_degraded is True
    assert await composed.held(conversation_id) == []
    assert await composed.conversations.get(conversation_id) is not None


async def test_deleting_a_conversation_deletes_every_episode_on_its_channel(
    composed: Composed,
) -> None:
    """§8:1: eligible or not, expired but unpurged, or not yet valid — all of it goes."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    failed = await composed.fail(conversation_id)
    assert first.capture.episode_id is not None
    template = await composed.memory.get(first.capture.episode_id)
    assert isinstance(template, EpisodicMemory)
    now = datetime.now(UTC)
    await composed.memory.add(
        template.model_copy(
            update={"id": "activation:expired", "expires_at": now - timedelta(days=1)}
        )
    )
    await composed.memory.add(
        template.model_copy(
            update={
                "id": "activation:not-yet-valid",
                "validity": Validity(valid_from=now + timedelta(days=1)),
            }
        )
    )
    assert len(await composed.held(conversation_id)) == 4
    other = await composed.say("another conversation")

    assert await composed.engine.forget_conversation(conversation_id) is True

    assert await composed.held(conversation_id) == []
    for gone in (first.capture.episode_id, failed):
        assert gone is not None
        assert await composed.memory.get(gone) is None
    assert await composed.held(_conversation(other)) == [other.capture.episode_id]


async def test_an_episode_write_that_commits_then_cancels_on_a_deleted_conversation_leaves_none(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: the conversation is deleted meanwhile; the drain's compensation removes it."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    memory = composed.memory
    original = memory.write_atomic
    cancelled: list[str] = []

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written = await original(writes)
        episode = [write.record.id for write in writes if write.record.id.startswith("activation:")]
        if episode and episode[0] != first.capture.episode_id and not cancelled:
            cancelled.append(episode[0])
            await composed.engine.forget_conversation(conversation_id)
            raise asyncio.CancelledError
        return written

    monkeypatch.setattr(memory, "write_atomic", write_atomic)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.ensure_future(composed.say("and again", conversation_id))

    assert cancelled, "the second episode's write committed and then cancelled"
    assert await memory.get(cancelled[0]) is None
    assert await composed.held(conversation_id) == []


async def test_a_conversation_deleted_while_a_pass_runs_leaves_neither_episode_nor_archive(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7, §8: the pass's capture degrades and leaves nothing behind it."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    entered, release = asyncio.Event(), asyncio.Event()
    original = composed.engine._begin_conversation_stage

    async def held(working: Any) -> None:
        await original(working)
        if working.input.text == "slow":
            entered.set()
            await release.wait()

    monkeypatch.setattr(composed.engine, "_begin_conversation_stage", held)
    task = asyncio.create_task(composed.say("slow", conversation_id))
    await entered.wait()
    try:
        assert await composed.engine.forget_conversation(conversation_id) is True
    finally:
        release.set()
    result = await task

    assert result.capture.state == "degraded"
    address = f"activation:{result.capture.activation_id}"
    assert await composed.memory.get(address) is None
    assert await composed.engine._archive.entry(address) is None
    assert await composed.held(conversation_id) == []


async def test_reclaim_keeps_a_conversation_whose_channel_holds_a_live_episode(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8:2: past the horizon, the one holding an episode stays and the empty one goes."""
    kept = _conversation(await composed.say("hello"))
    empty = await composed.engine._conversations.begin(None)
    lifecycle = composed.engine._conversations
    assert lifecycle._retention is not None
    later = datetime.now(UTC) + lifecycle._retention + timedelta(days=1)
    monkeypatch.setattr(lifecycle, "_now", lambda: later)
    monkeypatch.setattr(composed.conversations, "_now", lambda: later)

    await lifecycle.reclaim()

    assert await composed.conversations.get(kept) is not None
    assert await composed.engine.conversation(kept) is not None
    assert await composed.conversations.get(empty.id) is None


async def test_the_digest_counts_the_channels_episodes(composed: Composed) -> None:
    """§4:2: every live episode on the channel, eligible or not."""
    first = await composed.say("hello")
    conversation_id = _conversation(first)
    await composed.say("again", conversation_id)
    await composed.fail(conversation_id)

    digest = await composed.engine.conversation(conversation_id)

    assert digest is not None
    assert digest.recorded_turns == 3
    assert digest.last_turn_at is not None
