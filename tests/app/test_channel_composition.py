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
    ChannelResult,
    EpisodicMemory,
    GoalAssociation,
    InformationalEventResult,
    Modality,
    NewConversation,
    PlannerOutput,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenChannelResult,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    SpokenReply,
    TextChannelPayload,
    TextChannelResult,
    WholeTextReply,
)
from ai_assistant.interfaces import cli
from ai_assistant.models import PydanticAIProvider
from ai_assistant.service import backup, restore
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
    listener: Listener
    settings: Settings


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
        yield RunningChannels(engine, client, model, resolved, listener, settings)
    finally:
        await listener.stop_accepting()
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


async def _canonical(client: HubEngineClient, address: str) -> str:
    chunk = await client.episode_chunk(address, max_bytes=379)
    assert chunk is not None
    first = chunk
    parts = [chunk.text]
    while chunk.next_offset is not None:
        chunk = await client.episode_chunk(
            address, version=first.version, offset=chunk.next_offset, max_bytes=379
        )
        assert chunk is not None
        assert chunk.text
        parts.append(chunk.text)
    return "".join(parts)


async def _reopened_records(settings: Settings, expected: dict[str, str]) -> None:
    engine = build_engine(settings, data_dir=settings.data_dir)
    listener = Listener(engine, settings, data_dir=settings.data_dir)
    await engine.start()
    await listener.start(build="m36-restart-acceptance")
    client = HubEngineClient(listener.path, read_timeout=_BUDGET)
    try:
        page = await client.episodes()
        assert {row.position.episode_id for row in page.items} == set(expected)
        for address, encoded in expected.items():
            assert await _canonical(client, address) == encoded
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        await engine.aclose()


def _assert_captured_result(result: ChannelResult, encoded: str, context: ChannelContext) -> None:
    episode = EpisodicMemory.model_validate_json(encoded)
    processing = episode.processing_record
    assert processing is not None
    assert processing.activation_id == result.capture.activation_id
    assert processing.status is ProcessingStatus.COMPLETED
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    assert processing.trigger.channel == result.channel
    if isinstance(result.result, TextChannelResult):
        assert episode.outcome == result.result.outcome.reply
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert processing.trigger.payload.text == "  exact text\n"
        assert processing.trigger.context == context
    elif isinstance(result.result, SpokenChannelResult):
        spoken = result.result.outcome
        assert spoken.outcome is not None
        assert spoken.spoken is not None
        assert episode.outcome == spoken.outcome.reply
        assert isinstance(processing.trigger.payload, RecordedSpeechInput)
        assert processing.trigger.payload.transcript == spoken.heard == "  spoken words  "
        assert "YXVkaW8=" not in encoded
        assert spoken.spoken.content not in encoded
    else:
        assert episode.outcome == result.result.summary
        assert not processing.model_eligible
        assert processing.trigger.context == context


async def test_text_voice_event_records_survive_hub_restart_and_encrypted_backup_restore(
    running_channels: RunningChannels,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = running_channels
    client = running.client
    context = ChannelContext(history=(ChannelContextItem(text="quoted café", source="untrusted"),))
    text = await client.receive(
        ChannelInput(
            target=NewConversation(),
            payload=TextChannelPayload(text="  exact text\n"),
            context=context,
        ),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )
    assert text.channel is not None
    voice = await client.receive(
        ChannelInput(
            target=text.channel,
            payload=SpeechChannelPayload(
                audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
            ),
        ),
        reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        timeout=_BUDGET,
    )
    event = await client.receive(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="sensor"),
            payload=TextChannelPayload(text="  exact event\n"),
            context=context,
        ),
        reply=None,
        timeout=_BUDGET,
    )
    expected: dict[str, str] = {}
    for result in (text, voice, event):
        assert result.capture.state == "recorded"
        assert result.capture.episode_id is not None
        encoded = await _canonical(client, result.capture.episode_id)
        expected[result.capture.episode_id] = encoded
        _assert_captured_result(result, encoded, context)
    # Owner CLI reads the same complete canonical record over the live socket.
    rendered = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=rendered, force_terminal=False))
    address = next(iter(expected))
    command = await asyncio.to_thread(CliRunner().invoke, cli.app, ["episode", address, "--json"])
    assert command.exit_code == 0, command.output
    assert json.loads(rendered.getvalue()) == json.loads(expected[address])
    await running.listener.stop_accepting()
    await running.listener.aclose()
    await running.engine.aclose()
    await _reopened_records(running.settings, expected)

    # The production encrypted whole-directory backup/restore path carries the
    # enriched records without a producer-specific export or reconstruction.
    artifact_dir = tmp_path.parent / f"{tmp_path.name}-acceptance-backups"
    artifact_dir.mkdir(mode=0o700)
    phrase = artifact_dir / "phrase"
    phrase.write_text("acceptance-only passphrase\n")
    artifact = artifact_dir / "m36.age"
    monkeypatch.setattr(backup, "load_settings", lambda: running.settings)
    monkeypatch.setattr(restore, "load_settings", lambda: running.settings)
    monkeypatch.setattr(backup, "DEFAULT_WORK_FACTOR", 8)
    assert (
        await asyncio.to_thread(backup.main, [str(artifact), "--passphrase-file", str(phrase)]) == 0
    )
    restored = artifact_dir / "restored"
    assert (
        await asyncio.to_thread(
            restore.main, [str(artifact), str(restored), "--passphrase-file", str(phrase)]
        )
        == 0
    )
    await _reopened_records(running.settings.model_copy(update={"data_dir": restored}), expected)


@pytest.mark.parametrize("same_conversation", [False, True])
async def test_composed_concurrent_activations_keep_records_isolated_when_finishing_in_reverse(
    running_channels: RunningChannels,
    monkeypatch: pytest.MonkeyPatch,
    same_conversation: bool,
) -> None:
    running = running_channels
    initial = await running.client.converse("start", timeout=_BUDGET)
    assert initial.conversation_id is not None
    channel = ChannelIdentity(channel_type="conversation", instance_id=initial.conversation_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = running.engine._run_turn

    async def controlled(supplied: ResolvedChannelInput, **kwargs: Any) -> TurnOutcome:
        if supplied.text == "slow":
            entered.set()
            await release.wait()
        return await original(supplied, **kwargs)

    monkeypatch.setattr(running.engine, "_run_turn", controlled)
    slow_input = ChannelInput(
        target=channel,
        payload=TextChannelPayload(text="slow"),
        context=ChannelContext(reply_to=ChannelContextItem(text="slow context")),
    )
    fast_input = ChannelInput(
        target=channel if same_conversation else NewConversation(),
        payload=TextChannelPayload(text="fast"),
        context=ChannelContext(reply_to=ChannelContextItem(text="fast context")),
    )
    task = asyncio.create_task(
        running.client.receive(slow_input, reply=WholeTextReply(), timeout=_BUDGET)
    )
    await entered.wait()
    try:
        fast = await running.client.receive(fast_input, reply=WholeTextReply(), timeout=_BUDGET)
        assert not task.done()
    finally:
        release.set()
    slow = await task
    assert fast.capture.activation_id != slow.capture.activation_id
    assert fast.capture.episode_id != slow.capture.episode_id
    for result, supplied in ((slow, slow_input), (fast, fast_input)):
        assert result.capture.state == "recorded"
        assert result.capture.episode_id is not None
        episode = EpisodicMemory.model_validate_json(
            await _canonical(running.client, result.capture.episode_id)
        )
        processing = episode.processing_record
        assert processing is not None
        assert processing.model_eligible
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert isinstance(supplied.payload, TextChannelPayload)
        assert processing.trigger.payload.text == supplied.payload.text
        assert processing.trigger.context == supplied.context
        assert processing.trigger.channel == result.channel
        assert processing.links.predecessor_episode_id is None
        assert isinstance(result.result, TextChannelResult)
        assert episode.outcome == result.result.outcome.reply
