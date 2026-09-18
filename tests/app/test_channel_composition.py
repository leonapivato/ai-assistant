"""Reach the production receiver through composition, CLI, and a real hub socket."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from itertools import count
from typing import TYPE_CHECKING, Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    GoalAssociation,
    InformationalEventResult,
    Modality,
    NewConversation,
    PlannerOutput,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.interfaces import cli
from ai_assistant.models import PydanticAIProvider
from ai_assistant.service.transport import Listener
from ai_assistant.testing import (
    FakeGoalAssociator,
    FakeModelProvider,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    StreamAttempt,
)
from ai_assistant.wire import HubEngineClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import GoalBrief, Message, TurnOutcome
    from ai_assistant.orchestration import Engine
    from ai_assistant.orchestration.channels import ResolvedChannelInput

pytestmark = pytest.mark.integration
_BUDGET = timedelta(seconds=10)
_AT = datetime(2026, 9, 18, tzinfo=UTC)


@dataclass
class RunningChannels:
    """The real composition and transport, with controlled model and speech seams."""

    engine: Engine
    client: HubEngineClient
    model: FakeModelProvider
    resolved: list[ResolvedChannelInput]


@pytest.fixture
async def running_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[RunningChannels]:
    """Wire production stores and receiver, then substitute only test collaborators."""
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)
    model = FakeModelProvider("The thermostat entered eco mode at 18:00.")

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    engine = build_engine(settings, data_dir=tmp_path)
    assert engine._informational_events is not None
    assert engine._informational_events._model is engine._composing._model
    # Contract fakes control planning and speech; receiver, stores, composition,
    # lifecycle, CLI and transport all execute their production implementations.
    engine._associator = FakeGoalAssociator(
        answer=GoalAssociation(verdict=AssociationVerdict.FRESH)
    )
    engine._routing = None
    engine._transcriber = FakeSpeechTranscriber(transcripts=["  spoken words  ", ""])
    engine._synthesizer = FakeSpeechSynthesizer()
    engine._composing._streaming = FakeStreamingCompleter(
        script=(StreamAttempt(deltas=("Channel reply.",)),)
    )

    plan_ids = count(1)

    async def plan(goal: GoalBrief, **_kwargs: object) -> PlannerOutput:
        return PlannerOutput(
            plan=ActionPlan(
                id=f"channel-plan-{next(plan_ids)}", goal_id=goal.goal_id, steps=(), created_at=_AT
            )
        )

    monkeypatch.setattr(engine._loop._planner, "plan", plan)
    resolved: list[ResolvedChannelInput] = []
    original = engine._run_turn

    async def process(supplied: ResolvedChannelInput, **kwargs: Any) -> TurnOutcome:
        resolved.append(supplied)
        return await original(supplied, **kwargs)

    monkeypatch.setattr(engine, "_run_turn", process)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    listener = Listener(engine, settings, data_dir=tmp_path)
    await engine.start()
    await listener.start(build="channel-acceptance-test")
    client = HubEngineClient(listener.path, read_timeout=_BUDGET)
    try:
        yield RunningChannels(engine, client, model, resolved)
    finally:
        await listener.aclose()
        await engine.aclose()


async def test_real_cli_text_crosses_hub_and_common_receiver(
    running_channels: RunningChannels,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=rendered, force_terminal=False))
    result = await asyncio.to_thread(CliRunner().invoke, cli.app, ["ask", "Hello channel"])
    assert result.exit_code == 0, result.output
    assert "Channel reply." in rendered.getvalue()
    assert len(running_channels.resolved) == 1
    supplied = running_channels.resolved[0]
    assert supplied.text == "Hello channel"
    assert supplied.modality is Modality.TEXT
    assert supplied.context == ChannelContext()
    assert supplied.channel.channel_type == "conversation"


async def test_hub_context_arrives_intact_and_separately_from_stored_history(
    running_channels: RunningChannels,
) -> None:
    context = ChannelContext(
        history=(
            ChannelContextItem(
                text="Untrusted source history", source="speaker", item_id="local-1"
            ),
        ),
        reply_to=ChannelContextItem(text="Earlier text", item_id="local-2"),
    )
    result = await running_channels.client.receive(
        ChannelInput(
            target=NewConversation(),
            payload=TextChannelPayload(text="  Exact text  "),
            context=context,
        ),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )
    assert running_channels.resolved[0].context == context
    assert running_channels.resolved[0].text == "  Exact text  "
    assert running_channels.resolved[0].channel == result.channel
    assert result.channel is not None
    digest = await running_channels.client.conversation(result.channel.instance_id)
    assert digest is not None
    # The supplied history is carried into processing, never appended as a turn.
    assert digest.recorded_turns == 1


async def test_hub_spoken_path_preserves_modality_and_records_playback(
    running_channels: RunningChannels,
) -> None:
    client = running_channels.client
    spoken = await client.converse_spoken(
        SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4),
        plays=(SpokenAudioFormat.MP4,),
        timeout=_BUDGET,
    )
    assert spoken.heard == "  spoken words  "
    assert spoken.spoken is not None
    assert spoken.outcome is not None
    assert spoken.outcome.conversation_id is not None
    assert spoken.episode_id is not None
    assert running_channels.resolved[0].modality is Modality.SPEECH
    report = SpokenDelivery(
        state=SpokenDeliveryState.COMPLETE,
        played=timedelta(seconds=1),
        rendered=timedelta(seconds=1),
    )
    blank = await client.converse_spoken(
        SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4),
        plays=(SpokenAudioFormat.MP4,),
        timeout=_BUDGET,
        conversation_id=spoken.outcome.conversation_id,
        delivery=SpokenDeliveryReport(episode_id=spoken.episode_id, delivery=report),
    )
    assert blank.heard is None
    assert len(running_channels.resolved) == 1
    digest = await client.conversation(spoken.outcome.conversation_id)
    assert digest is not None
    history = await running_channels.engine._conversations.history(spoken.outcome.conversation_id)
    assert history.deliveries[spoken.episode_id] == report


async def test_input_only_adapter_reaches_real_stage_without_durable_work(
    running_channels: RunningChannels,
) -> None:
    client = running_channels.client
    identity = ChannelIdentity(channel_type="informational_event", instance_id="thermostat-1")
    context = ChannelContext(reply_to=ChannelContextItem(item_id="source-local"))
    before = await client.recent_conversations()
    goals = await client.goals()
    result = await client.receive(
        ChannelInput(
            target=identity,
            payload=TextChannelPayload(text="The thermostat entered eco mode at 18:00."),
            context=context,
        ),
        reply=None,
        timeout=_BUDGET,
    )
    assert result.channel == identity
    assert isinstance(result.result, InformationalEventResult)
    assert result.result.summary == "The thermostat entered eco mode at 18:00."
    assert len(running_channels.model.calls) == 1
    sent = json.loads(running_channels.model.calls[0].messages[1].content)
    assert sent["context"] == context.model_dump(mode="json")
    assert await client.recent_conversations() == before
    assert await client.goals() == goals
    assert running_channels.resolved == []
