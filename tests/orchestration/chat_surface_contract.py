"""Shared chat-space obligations from ADR-0293 §2-§5, §8 and §11.

Run through the engine, the canonical fake engine and the wire client, each over an
injected memory store the suite seeds episodes into, so the acts in the medium, their
reads, the current state and forgetting are held to one answer on every
implementation. What the conversation store itself owes is
``tests/memory/conversation_store_contract.py``'s; this suite asserts what the engine
surface adds: a conversation started empty on "my devices", a written message answered
*received* and safe to repeat, deleting that forgets nothing, forgetting that deletes
nothing, the current state read from the episodes, the pages fitted to the payload
limit, and every argument refused locally.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import OversizedValueError, UnknownConversationError
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    ChatDevice,
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
    TextChannelPayload,
    TranscriptMessage,
    UnderstandingOmission,
    UserMessage,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import MemoryWrite
    from ai_assistant.testing import FakeMemoryStore

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


@dataclass(frozen=True)
class ChatSurfaceSubject:
    """An engine and the memory store its current state and forgetting read."""

    engine: AssistantEngine
    memory: FakeMemoryStore


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
                    payload=TextChannelPayload(text="hello"),
                ),
                reply=WholeTextReply(),
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
                    payload=TextChannelPayload(text="hello"),
                ),
                reply=WholeTextReply(),
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
