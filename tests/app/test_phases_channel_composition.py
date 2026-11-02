"""Reach the production receiver and the chat's reader through the root and a real hub
socket, on the phases.

``test_channel_composition`` drove these cases through ``ask``, ``converse``'s
admission, a spoken turn and the old event stage, which the cutover retired (ADR-0309
§2:6, §5:1, ADR-0313). Each case here is one of them with the root's phases wired: a
message written over the hub socket is taken in by the reader and answered there; an
event over the socket runs the phases and starts no conversation; a message's and an
event's records survive a restart and an encrypted backup and restore; and two
activations on two conversations finishing in reverse keep their records apart.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from phases_composition_support import (
    BUDGET,
    PHONE,
    REPLY,
    SETTLE,
    UNDERSTANDING_INSTRUCTIONS,
    Phased,
    Turn,
    answering,
    build_phased,
    phased,
    reply_to,
    until,
)

from ai_assistant.core.types import (
    ActivationEnding,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    EpisodicMemory,
    InformationalEventResult,
    MessageAuthor,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    TextChannelPayload,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.service import backup, restore
from ai_assistant.service.transport import Listener
from ai_assistant.wire import HubEngineClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.config import Settings

pytestmark = pytest.mark.integration


@dataclass
class Hub:
    """The root with the phases, served on a real socket, and a client on it."""

    phased: Phased
    client: HubEngineClient
    listener: Listener
    settings: Settings


@pytest.fixture
async def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Hub]:
    """Wire production stores, receiver and reader, then serve them on a hub socket."""
    phased_root = build_phased(tmp_path, monkeypatch, completer=answering())
    served = phased_root.settings
    listener = Listener(phased_root.engine, served, data_dir=tmp_path)
    await phased_root.engine.start()
    await listener.start(build="phases-channel-acceptance-test")
    client = HubEngineClient(listener.path, read_timeout=BUDGET)
    try:
        yield Hub(phased_root, client, listener, served)
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        await phased_root.engine.aclose()


async def _written_over_the_socket(hub: Hub, text: str, conversation_id: str) -> Turn:
    """A message written through the hub client; the activation the reader ran on it."""
    receipt = await hub.client.write_message(
        conversation_id,
        message=UserMessage(device_id=PHONE.device_id, message_id=f"hub-{text}", text=text),
    )
    assert receipt.position is not None
    activation = await hub.phased.taken_by(conversation_id, receipt.position)
    await hub.phased.idle(conversation_id)
    return Turn(conversation_id=conversation_id, activation_id=activation)


async def test_a_message_written_over_the_hub_socket_is_answered_in_its_conversation(
    hub: Hub,
) -> None:
    """ADR-0293 §6, §10: the medium's write crosses the socket; the reader answers it."""
    await hub.client.set_my_devices([PHONE])
    conversation_id = (await hub.client.start_conversation()).id

    turn = await _written_over_the_socket(hub, "Hello channel", conversation_id)

    page = await hub.client.transcript(conversation_id)
    assert page is not None
    said = [(one.author, one.text) for one in page.entries if isinstance(one, TranscriptMessage)]
    assert said == [(MessageAuthor.USER, "Hello channel"), (MessageAuthor.ASSISTANT, REPLY)]
    episode = phased(await hub.phased.stored(turn.address))
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    assert isinstance(trigger.payload, RecordedTextInput)
    assert trigger.payload.text == "Hello channel"


async def test_an_event_over_the_hub_socket_runs_the_phases_and_starts_no_conversation(
    hub: Hub,
) -> None:
    """ADR-0313 §4: one activation whose place takes no message, its context carried."""
    identity = ChannelIdentity(channel_type="informational_event", instance_id="thermostat-1")
    context = ChannelContext(reply_to=ChannelContextItem(item_id="source-local"))
    before = await hub.client.recent_conversations()

    result = await hub.client.receive(
        ChannelInput(
            target=identity,
            payload=TextChannelPayload(text="The thermostat entered eco mode at 18:00."),
            context=context,
        ),
        reply=None,
        timeout=BUDGET,
    )

    assert result.channel == identity
    assert isinstance(result.result, InformationalEventResult)
    assert result.result.ended is ActivationEnding.DONE
    # The understanding stage ran once, over the supplied context; planning followed.
    (understanding,) = [
        call
        for call in hub.phased.model.calls
        if call.messages[0].content in UNDERSTANDING_INSTRUCTIONS
    ]
    assert understanding
    assert hub.phased.completer.calls, "planning ran"
    asked = hub.phased.completer.calls[0].exchange.briefing
    # ADR-0364 §3:9: an event's origin is no connection, so nothing could be sent to it.
    assert reply_to(asked) is None
    assert await hub.client.recent_conversations() == before
    assert result.capture.episode_id is not None
    episode = phased(await hub.phased.stored(result.capture.episode_id))
    assert episode.processing_record is not None
    received = episode.processing_record.trigger
    assert isinstance(received, RecordedChannelTrigger)
    assert received.context == context


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


async def _reopened_records(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, expected: dict[str, str]
) -> None:
    reopened = build_phased(data_dir, monkeypatch, completer=answering())
    listener = Listener(reopened.engine, reopened.settings, data_dir=data_dir)
    await reopened.engine.start()
    await listener.start(build="phases-restart-acceptance")
    client = HubEngineClient(listener.path, read_timeout=BUDGET)
    try:
        page = await client.episodes()
        assert {row.position.episode_id for row in page.items} == set(expected)
        for address, encoded in expected.items():
            assert await _canonical(client, address) == encoded
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        await reopened.engine.aclose()


async def test_message_and_event_records_survive_hub_restart_and_encrypted_backup_restore(
    hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0286, ADR-0123: the records two activations left are what a restart and a
    restored backup serve back, byte for byte."""
    await hub.client.set_my_devices([PHONE])
    conversation_id = (await hub.client.start_conversation()).id
    turn = await _written_over_the_socket(hub, "  exact text\n", conversation_id)
    context = ChannelContext(history=(ChannelContextItem(text="quoted café", source="untrusted"),))
    event = await hub.client.receive(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="sensor"),
            payload=TextChannelPayload(text="  exact event\n"),
            context=context,
        ),
        reply=None,
        timeout=BUDGET,
    )
    assert event.capture.episode_id is not None
    expected: dict[str, str] = {}
    for address in (turn.address, event.capture.episode_id):
        encoded = await _canonical(hub.client, address)
        expected[address] = encoded
        episode = EpisodicMemory.model_validate_json(encoded)
        processing = episode.processing_record
        assert processing is not None
        assert processing.status is ProcessingStatus.COMPLETED
        assert isinstance(processing.trigger, RecordedChannelTrigger)
    message = EpisodicMemory.model_validate_json(expected[turn.address])
    assert message.processing_record is not None
    written = message.processing_record.trigger
    assert isinstance(written, RecordedChannelTrigger)
    assert isinstance(written.payload, RecordedTextInput)
    assert written.payload.text == "  exact text\n"
    assert message.outcome == REPLY
    report = EpisodicMemory.model_validate_json(expected[event.capture.episode_id])
    assert report.processing_record is not None
    reported = report.processing_record.trigger
    assert isinstance(reported, RecordedChannelTrigger)
    assert reported.context == context
    await hub.listener.stop_accepting()
    await hub.listener.aclose()
    await hub.phased.engine.aclose()
    await _reopened_records(monkeypatch, tmp_path, expected)

    # The production encrypted whole-directory backup and restore carry the records
    # without a producer-specific export or reconstruction.
    artifact_dir = tmp_path.parent / f"{tmp_path.name}-phases-backups"
    artifact_dir.mkdir(mode=0o700)
    phrase = artifact_dir / "phrase"
    phrase.write_text("acceptance-only passphrase\n")
    artifact = artifact_dir / "phases.age"
    monkeypatch.setattr(backup, "load_settings", lambda: hub.settings)
    monkeypatch.setattr(restore, "load_settings", lambda: hub.settings)
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
    await _reopened_records(monkeypatch, restored, expected)


async def test_concurrent_activations_on_two_conversations_keep_records_isolated_in_reverse(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two activations at once, the first held until the second has ended: each record
    carries its own input, channel and outcome, and no predecessor.

    Two messages on **one** conversation are never concurrent on the phases: what waits
    is taken in together when the running activation ends (ADR-0293 §6:2), which
    ``test_phases_chat_reader`` pins.
    """
    phased_root = hub.phased
    engine = phased_root.engine
    slow_conversation = await phased_root.start_conversation()
    fast_conversation = await phased_root.start_conversation()
    entered, release = asyncio.Event(), asyncio.Event()
    original = engine._begin_conversation_stage

    async def controlled(working: Any) -> None:
        await original(working)
        if getattr(working, "utterance", None) == "slow":
            entered.set()
            await release.wait()

    monkeypatch.setattr(engine, "_begin_conversation_stage", controlled)
    position = await phased_root.write(slow_conversation, "slow")
    await asyncio.wait_for(entered.wait(), SETTLE)
    try:
        fast = await phased_root.say("fast", fast_conversation)

        async def still_running() -> bool:
            digest = await engine.conversation(slow_conversation)
            return digest is not None and digest.state.working

        await until(still_running, what="the slow activation to be running")
    finally:
        release.set()
    slow = Turn(
        conversation_id=slow_conversation,
        activation_id=await phased_root.taken_by(slow_conversation, position),
    )
    await phased_root.idle(slow_conversation)
    assert fast.activation_id != slow.activation_id
    for turn, text in ((slow, "slow"), (fast, "fast")):
        episode = EpisodicMemory.model_validate_json(await _canonical(hub.client, turn.address))
        phased(episode)
        processing = episode.processing_record
        assert processing is not None
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert processing.trigger.payload.text == text
        assert processing.trigger.channel == ChannelIdentity(
            channel_type="conversation", instance_id=turn.conversation_id
        )
        assert episode.outcome == REPLY
