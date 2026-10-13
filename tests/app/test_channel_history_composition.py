"""ADR-0283 §14:2 and ADR-0284 §11:2, through production composition.

A channel's history is its episodes (ADR-0283), and an episode is the experience of
processing its activation (ADR-0284): where its input came from, the verdict each
stage reached, and the search text one rule derives from the record.

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a
fresh data directory, so the stores are the shipped ``sqlite`` ones, the
lifecycle and the activation writer are the ones the root wires, and the only
substitutes are the model-facing seams: the provider's ``complete``, the planner,
the associator and the streaming completer. Nothing here reaches past the engine
into a store it does not hold, and the assertions read the stores the engine
itself reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    CostBasis,
    EpisodicMemory,
    GoalAssociation,
    Idempotency,
    InputOrigin,
    NewConversation,
    PlannerOutput,
    PlanStep,
    ProposedAction,
    RecordedChannelTrigger,
    Reversibility,
    RiskLevel,
    TextChannelPayload,
    ToolCost,
    ToolDefinition,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.channels import ChannelProjection
from ai_assistant.orchestration.conversations import conversation_channel
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
    from ai_assistant.core.types import FrozenJson, GoalBrief, Message
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
    #: The fake every model-facing call reaches, recording what each was handed.
    model: FakeModelProvider

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
async def composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Composed]:
    """Wire the production root, substituting only the model-facing seams.

    A case that needs a finite ``episode_retention`` passes it as an indirect
    parameter; every other case runs under the default, ``None`` since ADR-0287 §1.
    """
    window: timedelta | None = getattr(request, "param", None)
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING, episode_retention=window)
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
        yield Composed(engine, model)
    finally:
        await engine.aclose()


# --- ADR-0284 §11:2: the experience of processing, through production composition -----

#: An informational event channel, which declares its input ``outside`` (ADR-0284 §2:2).
_SENSOR = ChannelIdentity(channel_type="informational_event", instance_id="sensor")
#: The understanding every pass in this module records, as the fake model states it.
_MEANING = "The input means what it says."
#: An event's raw text, which no episode's search text may carry (§7:1).
_REPORTED = "The thermostat entered eco mode."


async def _episode(composed: Composed, result: ChannelResult) -> EpisodicMemory:
    """The episode a pass recorded, with its processing record."""
    assert result.capture.episode_id is not None
    episode = await composed.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    return episode


def _origin(episode: EpisodicMemory) -> InputOrigin | None:
    """The origin the episode's trigger recorded."""
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    return trigger.origin


async def _event(composed: Composed) -> ChannelResult:
    """One informational event, admitted and processed by the root's own stages."""
    return await composed.engine.receive(
        ChannelInput(target=_SENSOR, payload=TextChannelPayload(text=_REPORTED)),
        reply=None,
        timeout=_BUDGET,
    )


async def test_an_event_episode_is_outside_and_its_content_the_meaning_alone(
    composed: Composed,
) -> None:
    """ADR-0284 §2:2 and §7:1: admission records ``outside``; the words are not content."""
    episode = await _episode(composed, await _event(composed))

    assert _origin(episode) is InputOrigin.OUTSIDE
    assert episode.content == _MEANING
    assert _REPORTED not in episode.content
