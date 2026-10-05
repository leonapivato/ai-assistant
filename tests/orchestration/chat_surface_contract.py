"""Shared chat-space obligations from ADR-0293 §2-§6, §8, §10 and §11.

Run through the engine, the canonical fake engine and the wire client, each over an
injected memory store the suite seeds episodes into, so the acts in the medium, their
reads, the current state and forgetting are held to one answer on every
implementation. What the conversation store itself owes is
``tests/memory/conversation_store_contract.py``'s; this suite asserts what the engine
surface adds: a conversation started empty on "my devices", a written message answered
*received* and safe to repeat, deleting that forgets nothing, forgetting that deletes
nothing, the current state read from the episodes, the pages fitted to the payload
limit, and every argument refused locally.

**Two subjects per implementation.** :class:`ChatSurfaceContract` holds the medium on a
subject whose reader is off, so a written message is recorded and waits and every
position and change list is the case's own. :class:`ChatReaderContract` holds the
reader (§6), the adapter (§10) and the current state they drive (§8) on a subject whose
reader is on, over a conversation store the suite can hold at the reader's marking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import OversizedValueError, UnknownConversationError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    ChatDevice,
    ChatStreamChunk,
    ControllerRule,
    ConversationDeletedChange,
    ConversationStartedChange,
    ConversationState,
    DeletedMessage,
    DeviceAccess,
    DevicesChangedChange,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    MessageAddedChange,
    MessageAuthor,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    SendOutcome,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    TranscriptMessage,
    UnderstandingOmission,
    UserMessage,
)
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import ChatStreamEnd, CurrentState, DeviceChange, MemoryWrite
    from ai_assistant.testing import FakeConversationStore, FakeMemoryStore

#: The payload limit every subject is built at: small enough that a page of a few
#: long messages does not fit, so the fitting is exercised rather than assumed.
CHAT_LIMIT = 4096

#: The instant the injected memory store reads.
CHAT_SURFACE_AT = datetime(2026, 10, 5, 12, tzinfo=UTC)

_PHONE = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_LAPTOP = ChatDevice(device_id="laptop", access=DeviceAccess.READ_WRITE)
_WATCH = ChatDevice(device_id="watch", access=DeviceAccess.READ)

#: Long enough that a few of them overflow :data:`CHAT_LIMIT`, short enough that one
#: fits with room to spare.
_LONG = "x" * 900

#: A spoken turn on a conversation, which is how these cases hold an activation running:
#: ADR-0293 §11 takes the typed one off ``receive``, and a message written into the
#: conversation starts the reader's activation rather than the caller's.
_RECORDING = SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
_PLAYS = SpokenReply(plays=(SpokenAudioFormat.MP4,))


@dataclass(frozen=True)
class ChatSurfaceSubject:
    """An engine and the memory store its current state and forgetting read."""

    engine: AssistantEngine
    memory: FakeMemoryStore


@dataclass(frozen=True)
class ChatReaderSubject:
    """An engine whose chat reader is on, with the stores behind it.

    ``chat`` is the conversation store the engine's chat space is, which the suite
    holds at the reader's ``take_in`` — the activation's first step once it is
    admitted (ADR-0293 §6:8), on every implementation — so an activation is running,
    and reachable by a stop, while the case acts.
    """

    engine: AssistantEngine
    memory: FakeMemoryStore
    chat: FakeConversationStore


_STATUS_REASON: dict[ProcessingStatus, tuple[ProcessingReason, ControllerRule]] = {
    ProcessingStatus.COMPLETED: (ProcessingReason.RETURNED, ControllerRule.NOTHING_DUE),
    ProcessingStatus.WAITING: (ProcessingReason.CLARIFICATION, ControllerRule.NOTHING_DUE),
    ProcessingStatus.FAILED: (ProcessingReason.PROCESSING_FAILED, ControllerRule.STAGE_FAILED),
    ProcessingStatus.INTERRUPTED: (ProcessingReason.HUB_STOPPED, ControllerRule.HUB_STOPPED),
}


def conversation_episode(
    conversation_id: str,
    activation_id: str,
    *,
    status: ProcessingStatus | None,
    resolved: bool = True,
) -> EpisodicMemory:
    """An episode on ``conversation_id``'s place: open where ``status`` is ``None``.

    ``resolved=False`` is an open pass that has not yet named the conversation its
    episode is written for, so only its trigger's target names it.
    """
    at = CHAT_SURFACE_AT
    channel = ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
    running = status is None
    reason, rule = (None, None) if status is None else _STATUS_REASON[status]
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="",
        occurred_at=at,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=at),
        processing_record=EpisodeProcessingRecord(
            activation_id=activation_id,
            started_at=at,
            ended_at=None if running else at,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel if resolved else None,
                payload=RecordedTextInput(text="input"),
                context=ChannelContext(),
                reply=None,
                origin=InputOrigin.USER,
            ),
            status=status,
            reason=reason,
            understanding_omitted=None if running else UnderstandingOmission.NOT_REACHED,
            stages=() if running or rule is None else ended_pass(at, rule),
        ),
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=at)
        if running
        else Placement(),
    )


def said(device: ChatDevice, message_id: str, text: str, **more: int) -> UserMessage:
    """The user's message ``text`` from ``device``, carrying ``message_id``."""
    return UserMessage(device_id=device.device_id, message_id=message_id, text=text, **more)


async def _started(engine: AssistantEngine, *devices: ChatDevice) -> str:
    await engine.set_my_devices(devices)
    return (await engine.start_conversation()).id


class ChatSurfaceContract:
    """The chat space's acts and reads, through every ``AssistantEngine``."""

    @pytest.fixture
    def chat_surface(self) -> ChatSurfaceSubject:
        """Override: an implementation at ``CHAT_LIMIT`` over a seedable memory store."""
        raise NotImplementedError

    # --- starting, and devices (§2:1, §3) ------------------------------------

    async def test_a_started_conversation_is_empty_and_on_my_devices(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§2:1: an empty conversation, shown on "my devices" as they stood."""
        engine = chat_surface.engine
        assert await engine.set_my_devices([_PHONE, _LAPTOP]) is True
        assert await engine.set_my_devices([_LAPTOP, _PHONE]) is False, "the same set"
        started = await engine.start_conversation()
        assert started.last_turn_at is None
        assert started.id in [one.id for one in await engine.recent_conversations()]
        digest = await engine.conversation(started.id)
        assert digest is not None
        assert digest.devices == (_LAPTOP, _PHONE)
        assert digest.state == ConversationState()
        page = await engine.transcript(started.id)
        assert page is not None
        assert page.entries == ()
        assert await engine.my_devices() == (_LAPTOP, _PHONE)

    async def test_a_conversations_devices_change_apart_from_my_devices(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§3:3: choosing one conversation's devices leaves "my devices" alone."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        assert await engine.set_conversation_devices(conversation, devices=[_PHONE, _WATCH])
        assert not await engine.set_conversation_devices(conversation, devices=[_WATCH, _PHONE])
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.devices == (_PHONE, _WATCH)
        assert await engine.my_devices() == (_PHONE,)
        later = (await engine.start_conversation()).id
        digest = await engine.conversation(later)
        assert digest is not None
        assert digest.devices == (_PHONE,), "a later conversation starts on my devices"

    # --- a message in (§4) --------------------------------------------------

    async def test_a_written_message_is_answered_received_and_repeats_are_one(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§4:2, §4:4: *received* is the position, and a repeat is the same message."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE, _LAPTOP)
        first = await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        assert first.outcome is SendOutcome.RECORDED
        assert first.position == 1
        again = await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        assert again.outcome is SendOutcome.REPEATED
        assert again.position == 1
        other = await engine.write_message(conversation, message=said(_LAPTOP, "m-1", "hi"))
        assert other.position == 2, "another device's id is another message"
        page = await engine.transcript(conversation)
        assert page is not None
        assert [type(one) for one in page.entries] == [TranscriptMessage, TranscriptMessage]
        message = page.entries[0]
        assert isinstance(message, TranscriptMessage)
        assert message.author is MessageAuthor.USER
        assert (message.device_id, message.message_id, message.text) == ("phone", "m-1", "hello")

    async def test_only_a_writing_end_writes_and_a_reply_names_a_message_held(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§7:2 and §4:5: refused writes are answered with no position and record nothing."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE, _WATCH)
        stranger = ChatDevice(device_id="tablet", access=DeviceAccess.READ_WRITE)
        refused = await engine.write_message(conversation, message=said(stranger, "m", "hi"))
        assert (refused.outcome, refused.position) == (SendOutcome.NOT_AN_END, None)
        reader = await engine.write_message(conversation, message=said(_WATCH, "m", "hi"))
        assert reader.outcome is SendOutcome.NOT_AN_END
        dangling = await engine.write_message(
            conversation, message=said(_PHONE, "m-1", "re", replies_to=7)
        )
        assert (dangling.outcome, dangling.position) == (SendOutcome.NO_SUCH_REPLY, None)
        await engine.write_message(conversation, message=said(_PHONE, "m-2", "first"))
        reply = await engine.write_message(
            conversation, message=said(_PHONE, "m-3", "wrong, I meant Pinecrest", replies_to=1)
        )
        assert (reply.outcome, reply.position) == (SendOutcome.RECORDED, 2)

    async def test_a_message_never_creates_a_conversation(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§2:2: an id naming no conversation is refused, not started."""
        engine = chat_surface.engine
        with pytest.raises(UnknownConversationError):
            await engine.write_message("no-such", message=said(_PHONE, "m", "hello"))
        assert await engine.recent_conversations() == ()

    async def test_a_message_no_read_could_return_is_refused_and_not_recorded(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """Clause 5, read forward: a message is accepted only where it can be read back.

        Its arguments fit the limit, but its record — position, instant, author — would
        not fit a one-entry page, so a recorded copy would stop every cursor at it.
        """
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        with pytest.raises(OversizedValueError):
            await engine.write_message(conversation, message=said(_PHONE, "m", "x" * 3950))
        page = await engine.transcript(conversation)
        assert page is not None
        assert page.entries == ()
        fits = await engine.write_message(conversation, message=said(_PHONE, "m", "x" * 3000))
        assert fits.outcome is SendOutcome.RECORDED
        widest = await engine.write_message(
            conversation, message=said(_PHONE, "m-2", "re", replies_to=2**63 - 1)
        )
        assert (widest.outcome, widest.position) == (SendOutcome.NO_SUCH_REPLY, None)

    async def test_a_set_of_devices_no_read_could_return_is_refused_and_not_recorded(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """Clause 5, read forward, for devices: a recorded set is one every read returns.

        The argument fits the limit, but the change recording the set — and, for "my
        devices", every later conversation's start, and the digest carrying it — would
        not, so a recorded copy would stop every cursor at that change.
        """
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        before = await engine.chat_changes(after=0)
        wide = ChatDevice(device_id="d" * 3800, access=DeviceAccess.READ_WRITE)
        with pytest.raises(OversizedValueError):
            await engine.set_my_devices([wide])
        with pytest.raises(OversizedValueError):
            await engine.set_conversation_devices(conversation, devices=[wide])
        assert await engine.my_devices() == (_PHONE,)
        assert await engine.chat_changes(after=0) == before

    # --- deleting, and forgetting (§2, §5) -----------------------------------

    async def test_deleting_a_message_leaves_its_marker_and_its_replies(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§5:8, §5:12: the marker stands, a reply stays, and a repeat is that message."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "first"))
        await engine.write_message(conversation, message=said(_PHONE, "m-2", "re", replies_to=1))
        assert await engine.delete_message(conversation, position=1) is True
        assert await engine.delete_message(conversation, position=1) is False
        assert await engine.delete_message(conversation, position=9) is False
        page = await engine.transcript(conversation)
        assert page is not None
        assert page.entries[0] == DeletedMessage(conversation_id=conversation, position=1)
        reply = page.entries[1]
        assert isinstance(reply, TranscriptMessage)
        assert reply.replies_to == 1
        late = await engine.write_message(conversation, message=said(_PHONE, "m-1", "first"))
        assert (late.outcome, late.position) == (SendOutcome.REPEATED, 1)

    async def test_deleting_a_conversation_forgets_nothing(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§2:3, §2:5: deleted from every read; its episodes stay until forgotten."""
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        episode = conversation_episode(conversation, "a-1", status=ProcessingStatus.COMPLETED)
        await memory.add(episode)
        assert await engine.delete_conversation(conversation) is True
        assert await engine.delete_conversation(conversation) is False
        assert await engine.conversation(conversation) is None
        assert await engine.transcript(conversation) is None
        assert conversation not in [one.id for one in await engine.recent_conversations()]
        with pytest.raises(UnknownConversationError):
            await engine.write_message(conversation, message=said(_PHONE, "m-2", "again"))
        assert await memory.get(episode.id) is not None, "deleting forgets nothing"
        assert await engine.forget_conversation(conversation) is True
        assert await memory.get(episode.id) is None, "forgetting reaches the place still"

    async def test_forgetting_a_conversation_leaves_it_and_its_transcript(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§2:4, §5:6, §11:4: memory-only; the conversation and transcript stand.

        Every episode on the place goes, an open one included (§2:6), and no other
        place is reached (§2:8).
        """
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        ended = conversation_episode(conversation, "a-1", status=ProcessingStatus.COMPLETED)
        running = conversation_episode(conversation, "a-2", status=None, resolved=False)
        elsewhere = conversation_episode("other", "a-3", status=ProcessingStatus.COMPLETED)
        for one in (ended, running, elsewhere):
            await memory.add(one)
        assert await engine.forget_conversation(conversation) is True
        assert await memory.get(ended.id) is None
        assert await memory.get(running.id) is None, "an open episode is forgotten too"
        assert await memory.get(elsewhere.id) is not None, "another place is not reached"
        assert await engine.conversation(conversation) is not None
        page = await engine.transcript(conversation)
        assert page is not None
        assert len(page.entries) == 1
        assert await engine.forget_conversation(conversation) is False

    # --- the current state (§8) ---------------------------------------------

    @pytest.mark.parametrize(
        ("status", "ending"),
        [
            (ProcessingStatus.COMPLETED, ActivationEnding.DONE),
            (ProcessingStatus.WAITING, ActivationEnding.DONE),
            (ProcessingStatus.FAILED, ActivationEnding.COULDNT_FINISH),
            (ProcessingStatus.INTERRUPTED, ActivationEnding.INTERRUPTED),
        ],
    )
    async def test_the_state_shows_how_the_last_activation_ended(
        self,
        chat_surface: ChatSurfaceSubject,
        status: ProcessingStatus,
        ending: ActivationEnding,
    ) -> None:
        """§8:3: the place's newest ended episode says how the last activation ended."""
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        await memory.add(conversation_episode(conversation, "a-1", status=ProcessingStatus.FAILED))
        await memory.add(conversation_episode(conversation, "a-2", status=status))
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.state == ConversationState(last_ended=ending)

    async def test_an_open_episode_alone_is_not_a_running_activation(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§8:2: "working…" is the assistant's account of what runs, not a stored record.

        An open episode can outlive its activation — a failed capture whose
        compensation could not delete it stays open until a restart closes it (ADR-0286
        §5) — so the suite seeds one with no activation running, and the state is idle
        but for how the last one ended.
        """
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        await memory.add(conversation_episode(conversation, "a-1", status=ProcessingStatus.FAILED))
        await memory.add(conversation_episode(conversation, "a-2", status=None, resolved=False))
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.state == ConversationState(last_ended=ActivationEnding.COULDNT_FINISH)

    async def test_the_state_shows_working_while_an_activation_runs_and_not_after(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§8:2, ADR-0295 §1:2: "working…" with the running activation's id, then idle.

        A turn on the conversation is held at its first episode write — the engine's
        admission, the fake's capture — so it is running while the state is read.
        """
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        entered, release = asyncio.Event(), asyncio.Event()
        original = memory.write_atomic

        async def held(writes: Sequence[MemoryWrite]) -> Sequence[str]:
            if not entered.is_set():
                entered.set()
                await release.wait()
            return await original(writes)

        memory.write_atomic = held  # type: ignore[method-assign]
        turn = asyncio.create_task(
            engine.receive(
                ChannelInput(
                    target=ChannelIdentity(channel_type="conversation", instance_id=conversation),
                    payload=SpeechChannelPayload(audio=_RECORDING),
                ),
                reply=_PLAYS,
                timeout=timedelta(seconds=30),
            )
        )
        try:
            async with asyncio.timeout(10):
                await entered.wait()
            during = await engine.conversation(conversation)
            assert during is not None
            assert during.state.working
            assert during.state.activation_id is not None
        finally:
            release.set()
        await turn
        after = await engine.conversation(conversation)
        assert after is not None
        assert not after.state.working
        assert after.state.activation_id is None

    async def test_forgetting_reaches_an_activation_running_on_the_conversation(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§2:6: an activation running when its conversation is forgotten writes nothing back.

        The turn is held at its first episode write — the engine's admission, the
        fake's capture — so no read of the store can see its episode yet; forgetting
        the conversation then must still leave no episode of it once it finishes.
        """
        engine, memory = chat_surface.engine, chat_surface.memory
        conversation = await _started(engine, _PHONE)
        entered, release = asyncio.Event(), asyncio.Event()
        original = memory.write_atomic

        async def held(writes: Sequence[MemoryWrite]) -> Sequence[str]:
            if not entered.is_set():
                entered.set()
                await release.wait()
            return await original(writes)

        memory.write_atomic = held  # type: ignore[method-assign]
        turn = asyncio.create_task(
            engine.receive(
                ChannelInput(
                    target=ChannelIdentity(channel_type="conversation", instance_id=conversation),
                    payload=SpeechChannelPayload(audio=_RECORDING),
                ),
                reply=_PLAYS,
                timeout=timedelta(seconds=30),
            )
        )
        try:
            async with asyncio.timeout(10):
                await entered.wait()
            await engine.forget_conversation(conversation)
        finally:
            release.set()
        result = await turn
        assert result.capture.episode_id is None
        assert await memory.get(f"activation:{result.capture.activation_id}") is None
        assert await engine.conversation(conversation) is not None

    # --- the change stream (§5:10, §5:11) -----------------------------------

    async def test_every_change_after_a_cursor_in_sequence(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§5:10: every change has a number, and one request catches up after a cursor."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        await engine.delete_message(conversation, position=1)
        await engine.delete_conversation(conversation)
        caught = await engine.chat_changes(after=0)
        kinds = [type(one) for one in caught.changes]
        assert kinds == [DevicesChangedChange, ConversationDeletedChange]
        assert caught.next_after == caught.changes[-1].seq
        assert (await engine.chat_changes(after=caught.next_after)).changes == ()

    async def test_changes_page_and_filter_by_conversation(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§5:11: a page resumes from ``next_after``; a filter keeps "my devices"."""
        engine = chat_surface.engine
        first = await _started(engine, _PHONE)
        second = (await engine.start_conversation()).id
        await engine.write_message(first, message=said(_PHONE, "m-1", "one"))
        await engine.write_message(second, message=said(_PHONE, "m-1", "two"))
        whole = await engine.chat_changes(after=0)
        assert [type(one) for one in whole.changes] == [
            DevicesChangedChange,
            ConversationStartedChange,
            ConversationStartedChange,
            MessageAddedChange,
            MessageAddedChange,
        ]
        head = await engine.chat_changes(after=0, limit=2)
        assert head.changes == whole.changes[:2]
        rest = await engine.chat_changes(after=head.next_after)
        assert rest.changes == whole.changes[2:]
        only = await engine.chat_changes(after=0, conversation_ids=[f" {second} "])
        assert [type(one) for one in only.changes] == [
            DevicesChangedChange,
            ConversationStartedChange,
            MessageAddedChange,
        ]
        assert only.next_after == whole.next_after, "a filtered read still moves on"

    async def test_a_changes_page_too_large_is_shortened_from_its_newest_end(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """Clause 5: the page fits, and ``next_after`` resumes after what it held."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        for n in range(8):
            await engine.write_message(conversation, message=said(_PHONE, f"m-{n}", _LONG))
        first = await engine.chat_changes(after=0)
        assert 0 < len(first.changes) < 10, "the limit is small enough to bind"
        assert first.next_after == first.changes[-1].seq
        seen: list[int] = []
        cursor = 0
        while page := (await engine.chat_changes(after=cursor)).changes:
            seen.extend(one.seq for one in page)
            cursor = page[-1].seq
        assert seen == sorted(set(seen))
        assert len(seen) == 10, "the devices and the start, then eight messages"

    # --- the transcript (§5:13) ---------------------------------------------

    # --- the change stream (ADR-0296 §4, ADR-0298 §7) -----------------------

    async def test_following_sends_every_change_after_the_cursor_then_each_as_it_happens(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """ADR-0296 §4:1: catch up from the cursor, then the stream stays open."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))

        async with closing_stream(engine.follow_chat(after=0)) as chunks:
            caught = [await next_change(chunks) for _ in range(3)]
            await engine.write_message(conversation, message=said(_PHONE, "m-2", "again"))
            live = await next_change(chunks)

        assert [type(one.change) for one in caught] == [
            DevicesChangedChange,
            ConversationStartedChange,
            MessageAddedChange,
        ]
        assert all(one.snapshot is None for one in caught), "the hub's machine joins nothing"
        assert isinstance(live.change, MessageAddedChange)
        assert live.change.message.position == 2
        assert [one.seq for one in [*caught, live]] == sorted(one.seq for one in [*caught, live])
        async with closing_stream(engine.follow_chat(after=caught[-1].seq)) as chunks:
            resumed = await next_change(chunks)
        assert resumed == live, "a cursor is the last change applied"

    @pytest.mark.parametrize("bad", [-1, 2**63, 1.5, True, "0", None])
    async def test_a_malformed_cursor_is_refused_by_the_stream_locally(
        self, chat_surface: ChatSurfaceSubject, bad: object
    ) -> None:
        """Refused from the call, before a stream exists (ADR-0085 §9)."""
        with pytest.raises(ValueError, match=r"\w"):
            chat_surface.engine.follow_chat(after=bad)  # type: ignore[arg-type]

    async def test_a_transcript_reads_recent_then_older(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """§5:13: a snapshot of recent messages, and older ones before a position."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        for n in range(5):
            await engine.write_message(conversation, message=said(_PHONE, f"m-{n}", f"m{n}"))
        recent = await engine.transcript(conversation, limit=2)
        assert recent is not None
        assert [one.position for one in recent.entries] == [4, 5]
        older = await engine.transcript(conversation, before=4, limit=2)
        assert older is not None
        assert [one.position for one in older.entries] == [2, 3]
        changes = await engine.chat_changes(after=0)
        assert recent.as_of == changes.next_after

    async def test_a_transcript_too_large_is_shortened_from_its_oldest_end(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """Clause 5: the snapshot keeps its newest entries, and nothing is lost."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        for n in range(8):
            await engine.write_message(conversation, message=said(_PHONE, f"m-{n}", _LONG))
        positions: list[int] = []
        before: int | None = None
        while True:
            page = await engine.transcript(conversation, before=before)
            assert page is not None
            if not page.entries:
                break
            assert len(page.entries) < 8, "the limit is small enough to bind"
            positions[:0] = [one.position for one in page.entries]
            before = page.entries[0].position
        assert positions == list(range(1, 9))

    # --- local refusals (clauses 2 and 4) -----------------------------------

    @pytest.mark.parametrize("bad", [0, -1, True, 1.0, 2**63])
    async def test_a_malformed_position_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject, bad: object
    ) -> None:
        engine = chat_surface.engine
        with pytest.raises(ValueError, match=r"\w"):
            await engine.delete_message("c", position=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match=r"\w"):
            await engine.transcript("c", before=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-1, True, 1.0, 2**63])
    async def test_a_malformed_cursor_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject, bad: object
    ) -> None:
        with pytest.raises(ValueError, match=r"\w"):
            await chat_surface.engine.chat_changes(after=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["c-1", ["c-1", "  "], ["c"] * 1001, [3]])
    async def test_a_malformed_conversation_filter_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject, bad: object
    ) -> None:
        with pytest.raises(ValueError, match=r"\w"):
            await chat_surface.engine.chat_changes(
                after=0,
                conversation_ids=bad,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("bad", ["phone", [_PHONE, _PHONE], ["phone"], [_PHONE] * 65], ids=str)
    async def test_a_malformed_set_of_devices_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject, bad: object
    ) -> None:
        engine = chat_surface.engine
        with pytest.raises(ValueError, match=r"\w"):
            await engine.set_my_devices(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match=r"\w"):
            await engine.set_conversation_devices("c", devices=bad)  # type: ignore[arg-type]

    async def test_a_message_that_is_not_the_users_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """The author is the hub's statement: the surface takes a ``UserMessage`` only."""
        with pytest.raises(ValueError, match=r"\w"):
            await chat_surface.engine.write_message(
                "c",
                message="hello",  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "call",
        ["delete_conversation", "transcript", "set_conversation_devices", "write_message"],
    )
    async def test_a_blank_conversation_is_refused_locally(
        self, chat_surface: ChatSurfaceSubject, call: str
    ) -> None:
        engine = chat_surface.engine
        by_call: dict[str, dict[str, object]] = {
            "delete_conversation": {},
            "transcript": {},
            "set_conversation_devices": {"devices": [_PHONE]},
            "write_message": {"message": said(_PHONE, "m", "hello")},
        }
        arguments = by_call[call]
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(engine, call)("  ", **arguments)

    async def test_a_padded_conversation_id_names_the_conversation(
        self, chat_surface: ChatSurfaceSubject
    ) -> None:
        """Clause 2: a padded id names the conversation it pads."""
        engine = chat_surface.engine
        conversation = await _started(engine, _PHONE)
        receipt = await engine.write_message(f" {conversation} ", message=said(_PHONE, "m", "hi"))
        assert receipt.conversation_id == conversation
        assert receipt.outcome is SendOutcome.RECORDED


# --- the reader and the adapter (§6, §8, §10) --------------------------------------

#: How long a case waits for the reader to settle before it fails rather than hangs.
_SETTLE = 10.0


async def next_change(chunks: AsyncIterator[ChatStreamChunk | ChatStreamEnd]) -> DeviceChange:
    """The next change a change stream sends, passing over its other chunks.

    Roles and heartbeats are the hub's session layer's (ADR-0298 §7:10), so a client
    sends them and an engine followed in-process does not; a state is pushed as it
    changes. Fails rather than hangs.
    """
    async with asyncio.timeout(_SETTLE):
        async for chunk in chunks:
            if isinstance(chunk, ChatStreamChunk) and chunk.change is not None:
                return chunk.change
    msg = "the change stream ended before its next change"
    raise AssertionError(msg)


async def next_state(chunks: AsyncIterator[ChatStreamChunk | ChatStreamEnd]) -> CurrentState:
    """The next current state a change stream pushes, passing over its other chunks."""
    async with asyncio.timeout(_SETTLE):
        async for chunk in chunks:
            if isinstance(chunk, ChatStreamChunk) and chunk.state is not None:
                return chunk.state
    msg = "the change stream ended before its next state"
    raise AssertionError(msg)


async def _until(check: Callable[[], Awaitable[bool]], *, what: str) -> None:
    """Wait for ``check`` to hold, polling the loop; fail rather than hang."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            msg = f"the reader never settled: {what}"
            raise AssertionError(msg)
        await asyncio.sleep(0.005)


async def _messages(engine: AssistantEngine, conversation_id: str) -> list[TranscriptMessage]:
    """The conversation's standing messages, oldest first."""
    page = await engine.transcript(conversation_id)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


async def _answered(
    engine: AssistantEngine, conversation_id: str, count: int
) -> list[TranscriptMessage]:
    """Wait for ``count`` assistant messages and an idle conversation, then read."""

    async def done() -> bool:
        written = await _messages(engine, conversation_id)
        digest = await engine.conversation(conversation_id)
        replies = [one for one in written if one.author is MessageAuthor.ASSISTANT]
        return len(replies) >= count and digest is not None and not digest.state.working

    await _until(done, what=f"{count} assistant message(s)")
    return await _messages(engine, conversation_id)


async def _working(engine: AssistantEngine, conversation_id: str) -> str:
    """Wait for the conversation to show "working…" with an id, and return the id."""
    found: list[str] = []

    async def shown() -> bool:
        digest = await engine.conversation(conversation_id)
        if digest is None or not digest.state.working or digest.state.activation_id is None:
            return False
        found.append(digest.state.activation_id)
        return True

    await _until(shown, what="the running activation's id")
    return found[-1]


def _held_take_in(chat: FakeConversationStore) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold the reader's first marking until released: its activation is then running."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = chat.take_in

    async def held(*args: Any, **kwargs: Any) -> tuple[int, ...]:
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await original(*args, **kwargs)

    chat.take_in = held  # type: ignore[method-assign]
    return entered, release


async def _input_of(memory: FakeMemoryStore, activation_id: str) -> str:
    """The text the activation's episode says it was admitted with."""
    episode = await memory.get(f"activation:{activation_id}")
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    assert isinstance(trigger.payload, RecordedTextInput)
    return trigger.payload.text


class ChatReaderContract:
    """The chat's reader and adapter, through every ``AssistantEngine`` (ADR-0293 §6, §10)."""

    @pytest.fixture
    def chat_reader_surface(self) -> ChatReaderSubject:
        """Override: an implementation at ``CHAT_LIMIT`` with its chat reader on."""
        raise NotImplementedError

    async def test_a_written_message_is_answered_with_one_assistant_message(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """§6:1, §10:1, §8:3: taken in, answered once, and the state shows it ended done.

        The assistant's own message is never taken in (§6:1), so it starts nothing:
        nothing waits once the reply is written.
        """
        engine, chat = chat_reader_surface.engine, chat_reader_surface.chat
        conversation = await _started(engine, _PHONE)
        receipt = await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        assert receipt.outcome is SendOutcome.RECORDED
        written = await _answered(engine, conversation, 1)
        assert [(one.position, one.author) for one in written] == [
            (1, MessageAuthor.USER),
            (2, MessageAuthor.ASSISTANT),
        ]
        assert written[1].text.strip()
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.state == ConversationState(last_ended=ActivationEnding.DONE)
        taken = await chat.taken_in(conversation, positions=[1, 2])
        assert set(taken) == {1}, "the user's message is taken in, the reply is not"
        assert await chat.untaken_messages(conversation) == ()
        assert await _input_of(chat_reader_surface.memory, taken[1]) == "hello"

    async def test_messages_written_while_it_runs_wait_and_are_taken_in_together(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """§6:2, §6:3, §8:2: one activation at a time; what waited is one input after it.

        The first activation is held at its marking, so it is running — "working…",
        with its id — while two more messages are written. Each lands at once, and
        when it ends the two are taken in together by one second activation: two
        replies, not three.
        """
        engine, chat = chat_reader_surface.engine, chat_reader_surface.chat
        conversation = await _started(engine, _PHONE)
        entered, release = _held_take_in(chat)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "first"))
        try:
            async with asyncio.timeout(_SETTLE):
                await entered.wait()
            running = await _working(engine, conversation)
            second = await engine.write_message(conversation, message=said(_PHONE, "m-2", "second"))
            third = await engine.write_message(conversation, message=said(_PHONE, "m-3", "third"))
            assert (second.position, third.position) == (2, 3), "never refused, never held"
            assert await _working(engine, conversation) == running
        finally:
            release.set()
        written = await _answered(engine, conversation, 2)
        assert [one.author for one in written] == [
            MessageAuthor.USER,
            MessageAuthor.USER,
            MessageAuthor.USER,
            MessageAuthor.ASSISTANT,
            MessageAuthor.ASSISTANT,
        ]
        taken = await chat.taken_in(conversation, positions=[1, 2, 3])
        assert taken[1] == running
        assert taken[2] == taken[3] != running, "what waited is one input"
        together = await _input_of(chat_reader_surface.memory, taken[2])
        assert "second" in together
        assert "third" in together
        assert await chat.untaken_messages(conversation) == ()

    async def test_following_pushes_the_current_state_as_it_changes(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0296 §4:9: "working…" while it runs, then how it ended, unsequenced.

        The activation is held at its marking, so it is running when the stream next
        reads; once released, the state it ends in is pushed.
        """
        engine, chat = chat_reader_surface.engine, chat_reader_surface.chat
        conversation = await _started(engine, _PHONE)
        entered, release = _held_take_in(chat)

        async with closing_stream(engine.follow_chat(after=0)) as chunks:
            await next_change(chunks)  # the stream has taken its first reading
            await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
            try:
                async with asyncio.timeout(_SETTLE):
                    await entered.wait()
                running = await next_state(chunks)
            finally:
                release.set()
            ended = await next_state(chunks)
            while ended.state.working:
                ended = await next_state(chunks)

        assert running.conversation_id == conversation
        assert running.state.working
        assert running.state.activation_id is not None
        assert ended.conversation_id == conversation
        assert ended.state == ConversationState(last_ended=ActivationEnding.DONE)

    async def test_an_activation_between_two_readings_still_pushes_how_it_ended(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """A state the stream never saw running is still pushed once it has ended."""
        engine = chat_reader_surface.engine
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        await _answered(engine, conversation, 1)

        async with closing_stream(engine.follow_chat(after=0)) as chunks:
            await next_change(chunks)  # the stream has taken its first reading
            await engine.write_message(conversation, message=said(_PHONE, "m-2", "again"))
            ended = await next_state(chunks)
            while ended.state.working:
                ended = await next_state(chunks)

        assert ended.state == ConversationState(last_ended=ActivationEnding.DONE)

    async def test_forgetting_a_conversation_pushes_the_state_it_leaves(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0296 §4:9: the state is read from the episodes, so forgetting changes it."""
        engine = chat_reader_surface.engine
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        await _answered(engine, conversation, 1)

        async with closing_stream(engine.follow_chat(after=0)) as chunks:
            await next_change(chunks)  # the stream has taken its first reading
            assert await engine.forget_conversation(conversation) is True
            left = await next_state(chunks)

        assert left.conversation_id == conversation
        assert left.state == ConversationState(), "what the assistant forgot it no longer knows"

    async def test_forgetting_the_episode_a_state_was_read_from_pushes_the_state_it_leaves(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0296 §4:9: a forget naming the conversation's episode changes its state."""
        engine, chat = chat_reader_surface.engine, chat_reader_surface.chat
        conversation = await _started(engine, _PHONE)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hello"))
        await _answered(engine, conversation, 1)
        taken = await chat.taken_in(conversation, positions=[1])

        async with closing_stream(engine.follow_chat(after=0)) as chunks:
            await next_change(chunks)  # the stream has taken its first reading
            assert await engine.forget(f"activation:{taken[1]}") is True
            left = await next_state(chunks)

        assert left.conversation_id == conversation
        assert left.state == ConversationState()

    async def test_a_stopped_activation_writes_nothing_and_shows_stopped(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0295 §3:3-§3:4, ADR-0297 §4: no reply, no *couldn't finish*; state *stopped*.

        The stop lands while the input is being taken in, so nothing after it starts.
        What it marked stays taken in (§6:8), so nothing is taken in again after it.
        """
        engine, chat = chat_reader_surface.engine, chat_reader_surface.chat
        conversation = await _started(engine, _PHONE)
        entered, release = _held_take_in(chat)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hi"))
        try:
            async with asyncio.timeout(_SETTLE):
                await entered.wait()
            running = await _working(engine, conversation)
            assert await engine.stop_activation(running) is ActivationStop.STOPPED
        finally:
            release.set()

        async def idle() -> bool:
            digest = await engine.conversation(conversation)
            return digest is not None and not digest.state.working

        await _until(idle, what="the stopped activation to end")
        written = await _messages(engine, conversation)
        assert [(one.author, one.text) for one in written] == [(MessageAuthor.USER, "hi")]
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.state == ConversationState(last_ended=ActivationEnding.STOPPED)
        assert await chat.taken_in(conversation, positions=[1]) == {1: running}
        assert await chat.untaken_messages(conversation) == ()
        # Nothing started after the stop (ADR-0297 §4): no understanding, no outcome.
        episode = await chat_reader_surface.memory.get(f"activation:{running}")
        assert isinstance(episode, EpisodicMemory)
        assert episode.processing_record is not None
        assert episode.processing_record.reason is ProcessingReason.STOPPED
        assert episode.processing_record.understanding == ()
        assert episode.outcome is None
