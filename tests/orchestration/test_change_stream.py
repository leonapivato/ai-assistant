"""The change stream's engine half, one device at a time (ADR-0298 §7).

:class:`~ai_assistant.orchestration.change_stream.ChangeStream` over the canonical
conversation store, so each case states the chat space it follows and the device it
follows it as. What every ``AssistantEngine`` owes through ``follow_chat`` is the shared
contract's (``chat_surface_contract.py``); this module holds what a device other than
the hub's own machine is sent, which only a requesting device set by the wire server
reaches: the as-of membership, the filter at sending (§7:5), the snapshot in the chunk
of the change that adds the device (§7:6-§7:8), the state only where the device reads,
and the stream's end.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    HUB_REQUESTING_DEVICE,
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    ConversationDeletedChange,
    ConversationStartedChange,
    ConversationState,
    DeletedMessage,
    DeviceAccess,
    DeviceChange,
    DevicesChangedChange,
    MessageAddedChange,
    MessageAuthor,
    NewMessage,
    RequestingDevice,
    TranscriptMessage,
)
from ai_assistant.orchestration.change_stream import Activity, ChangeStream
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing import FakeConversationStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Sequence

    from ai_assistant.core.types import CurrentState

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH: Final = ChatDevice(device_id="watch", access=DeviceAccess.READ)
_PEN: Final = ChatDevice(device_id="pen", access=DeviceAccess.WRITE)
PHONE: Final = RequestingDevice(device_id="phone")
WATCH: Final = RequestingDevice(device_id="watch")
PEN: Final = RequestingDevice(device_id="pen")

#: A payload limit roomy enough for every case but the one that fits a snapshot.
_ROOMY: Final = 1_000_000
_SETTLE: Final = 5.0


class _Engine:
    """What the stream reads of an engine: what runs, and the state it shows."""

    def __init__(self) -> None:
        self.activity: dict[str, Activity] = {}
        self.closing = False
        self.states: dict[str, ConversationState] = {}

    async def state_of(self, conversation_id: str, running: Sequence[str | None]) -> object:
        del running
        return self.states.get(conversation_id, ConversationState())


async def _tracked[T](work: Awaitable[T]) -> T:
    return await work


def _stream(
    chat: FakeConversationStore, engine: _Engine | None = None, *, limit: int = _ROOMY
) -> ChangeStream:
    held = engine or _Engine()
    return ChangeStream(
        chat=chat,
        running=lambda: held.activity,
        state_of=held.state_of,  # type: ignore[arg-type]
        closing=lambda: held.closing,
        tracked=_tracked,
        max_payload_bytes=limit,
        poll_seconds=0.01,
    )


def _said(text: str, message_id: str, device: str = "phone") -> NewMessage:
    return NewMessage(author=MessageAuthor.USER, text=text, device_id=device, message_id=message_id)


class _Following:
    """One open stream, read without ever cancelling its step.

    Cancelling an async generator's pending step ends the generator, so a reader
    that waits with a deadline keeps the step pending across the wait instead, as the
    wire server does; it is cancelled once, when the stream is closed.
    """

    def __init__(self, chunks: AsyncIterator[ChatStreamChunk | ChatStreamEnd]) -> None:
        self._chunks = chunks
        self._step: asyncio.Future[ChatStreamChunk | ChatStreamEnd] | None = None

    async def __aenter__(self) -> _Following:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._step is not None:
            self._step.cancel()
            await asyncio.gather(self._step, return_exceptions=True)
        await self._chunks.aclose()  # type: ignore[attr-defined]

    async def next(self, wait: float) -> ChatStreamChunk | ChatStreamEnd | None:
        """The next chunk, or ``None`` where none came within ``wait`` seconds."""
        if self._step is None:
            self._step = asyncio.ensure_future(anext(self._chunks))
        done, _ = await asyncio.wait({self._step}, timeout=wait)
        if not done:
            return None
        step, self._step = self._step, None
        return step.result()

    async def drain(self) -> list[DeviceChange]:
        """Every change the stream sends until it has been quiet for a while."""
        seen: list[DeviceChange] = []
        while (chunk := await self.next(0.2)) is not None:
            if isinstance(chunk, ChatStreamChunk) and chunk.change is not None:
                seen.append(chunk.change)
        return seen


async def _sent(
    chat: FakeConversationStore, device: RequestingDevice, *, after: int = 0
) -> list[DeviceChange]:
    """What a stream opened from ``after`` sends ``device`` before it goes quiet."""
    async with _Following(_stream(chat).follow(device, after=after)) as following:
        return await following.drain()


async def _chat(chat: FakeConversationStore, *devices: ChatDevice) -> str:
    await chat.set_my_devices(devices)
    return (await chat.start()).id


async def test_the_hubs_machine_is_sent_every_change_and_no_snapshot() -> None:
    """ADR-0298 §3:2: an end of every conversation, so it joins none."""
    chat = FakeConversationStore()
    mine = await _chat(chat, _PHONE)
    theirs = await _chat(chat, _PEN)
    await chat.append_message(mine, _said("hello", "m-1"))

    sent = await _sent(chat, HUB_REQUESTING_DEVICE)

    assert [one.change for one in sent] == list((await chat.changes(after=0)).changes)
    assert {one.conversation_id for one in sent} == {None, mine, theirs}
    assert all(one.snapshot is None for one in sent)


async def test_the_change_that_adds_a_device_brings_its_snapshot_in_one_chunk() -> None:
    """§7:6-§7:7: the conversation as of the change, in the chunk that carries it."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE)
    await chat.append_message(conversation, _said("before", "m-1"))
    await chat.set_conversation_devices(conversation, [_PHONE, _WATCH])
    await chat.append_message(conversation, _said("after", "m-2"))

    sent = await _sent(chat, WATCH)

    joined = next(one for one in sent if isinstance(one.change, DevicesChangedChange))
    assert joined.conversation_id == conversation
    assert joined.snapshot is not None
    assert [one.position for one in joined.snapshot.entries] == [1]
    added = [one.change for one in sent if isinstance(one.change, MessageAddedChange)]
    assert [one.message.position for one in added] == [2], "only what came after it"


async def test_a_conversation_no_longer_read_is_sent_only_its_removal() -> None:
    """§7:5: catching up, no content from when the device read it — only the removal."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE, _WATCH)
    await chat.append_message(conversation, _said("while it read", "m-1"))
    await chat.set_conversation_devices(conversation, [_PHONE])
    await chat.append_message(conversation, _said("after it left", "m-2"))

    sent = await _sent(chat, WATCH)

    held = [one for one in sent if one.conversation_id == conversation]
    assert [type(one.change) for one in held] == [DevicesChangedChange]
    assert held[0].change == DevicesChangedChange(
        seq=held[0].seq, conversation_id=conversation, devices=(_PHONE,)
    )
    assert held[0].snapshot is None


async def test_a_deletion_reaches_a_former_reader_and_nothing_before_it() -> None:
    """§7:5: a deletion reaches every device that ever read the conversation."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE, _WATCH)
    await chat.append_message(conversation, _said("gone with it", "m-1"))
    await chat.set_conversation_devices(conversation, [_PHONE])
    await chat.stamp_deleted(conversation)

    sent = await _sent(chat, WATCH)

    held = [one.change for one in sent if one.conversation_id == conversation]
    assert held == [ConversationDeletedChange(seq=held[-1].seq, conversation_id=conversation)]


async def test_a_writer_is_sent_no_content_of_a_conversation_it_only_writes_in() -> None:
    """ADR-0296 §4:5: an end for writing alone is not shown the conversation."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE, _PEN)
    await chat.append_message(conversation, _said("hello", "m-1"))

    sent = await _sent(chat, PEN)

    assert [one.conversation_id for one in sent] == [None], "my devices alone"


async def test_a_change_after_the_stream_opened_is_sent_as_it_happens() -> None:
    """ADR-0296 §4:1: the answer stays open, and each change is sent in sequence order."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE)
    async with _Following(_stream(chat).follow(PHONE, after=0)) as following:
        caught = await following.drain()
        await chat.append_message(conversation, _said("live", "m-1"))
        live = await following.drain()

    assert [type(one.change) for one in caught] == [DevicesChangedChange, ConversationStartedChange]
    assert caught[1].snapshot is not None, "the start adds the phone as a reader"
    (added,) = live
    assert isinstance(added.change, MessageAddedChange)
    assert added.seq > caught[-1].seq


async def test_a_snapshot_too_large_is_shortened_from_its_oldest_end() -> None:
    """§7:8: the newest messages that fit with the change, so the chunk always fits."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE)
    for index in range(12):
        await chat.append_message(conversation, _said("x" * 400, f"m-{index}"))
    await chat.set_conversation_devices(conversation, [_PHONE, _WATCH])
    limit = 2048

    async with closing_stream(_stream(chat, limit=limit).follow(WATCH, after=0)) as chunks:
        sent: list[ChatStreamChunk] = []
        async with asyncio.timeout(_SETTLE):
            async for chunk in chunks:
                assert isinstance(chunk, ChatStreamChunk)
                sent.append(chunk)
                if chunk.change is not None and chunk.change.snapshot is not None:
                    break

    joined = sent[-1]
    assert len(canonical_payload(joined)) <= limit
    assert joined.change is not None
    assert joined.change.snapshot is not None
    positions = [one.position for one in joined.change.snapshot.entries]
    assert positions, "some of it fits"
    assert positions == list(range(13 - len(positions), 13)), "the newest, ascending"
    assert len(positions) < 12


async def test_a_snapshot_that_fits_nothing_is_sent_empty() -> None:
    """§7:8: shortened to none if need be, so a cursor never stops on it."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE)
    await chat.append_message(conversation, _said("x" * 3000, "m-1"))
    await chat.set_conversation_devices(conversation, [_PHONE, _WATCH])

    async with closing_stream(_stream(chat, limit=1024).follow(WATCH, after=0)) as chunks:
        async with asyncio.timeout(_SETTLE):
            async for chunk in chunks:
                assert isinstance(chunk, ChatStreamChunk)
                if chunk.change is not None and chunk.change.snapshot is not None:
                    assert chunk.change.snapshot.entries == ()
                    break


async def test_a_state_is_pushed_only_to_a_device_that_reads_the_conversation() -> None:
    """ADR-0296 §4:9, ADR-0298 §7:5: a state, where the device reads; never otherwise."""
    chat = FakeConversationStore()
    shown = await _chat(chat, _PHONE, _PEN)
    engine = _Engine()
    engine.states[shown] = ConversationState(working=True, activation_id="a-1")
    states: dict[str, list[CurrentState]] = {"phone": [], "pen": []}

    async def follow(device: RequestingDevice) -> None:
        async with closing_stream(_stream(chat, engine).follow(device, after=0)) as chunks:
            async for chunk in chunks:
                if isinstance(chunk, ChatStreamChunk) and chunk.state is not None:
                    states[device.device_id].append(chunk.state)

    tasks = [asyncio.ensure_future(follow(one)) for one in (PHONE, PEN)]
    await asyncio.sleep(0.05)
    engine.activity = {shown: Activity(turns=1, running=("a-1",))}
    await asyncio.sleep(0.1)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert [one.conversation_id for one in states["phone"]] == [shown]
    assert states["phone"][0].state.working
    assert states["pen"] == []


async def test_the_stream_ends_with_its_cursor_when_the_engine_closes() -> None:
    """The one ``ChatStreamEnd``: the engine is shutting down; reopen from here."""
    chat = FakeConversationStore()
    await _chat(chat, _PHONE)
    engine = _Engine()
    async with _Following(_stream(chat, engine).follow(PHONE, after=0)) as following:
        await following.drain()
        engine.closing = True
        last = await following.next(_SETTLE)
        with pytest.raises(StopAsyncIteration):
            await following.next(_SETTLE)

    head = (await chat.changes(after=0)).next_after
    assert last == ChatStreamEnd(next_after=head)


# --- through the engine -----------------------------------------------------


async def test_a_device_with_no_role_is_refused_the_stream_before_any_chunk() -> None:
    """ADR-0298 §5 "Reading many", §7:17: refused as holding no role, at the first step."""
    engine = Harness(planner=NoStepPlanner(), chat_reader=False).engine
    try:
        await engine.set_my_devices([_PHONE])
        with serving_device(RequestingDevice(device_id="stranger")):
            stream = engine.follow_chat(after=0)
        with serving_device(RequestingDevice(device_id="stranger")):
            async with closing_stream(stream) as chunks:
                with pytest.raises(DeviceRefusedError) as refused:
                    await anext(chunks)
        assert refused.value.reason is DeviceRefusal.NO_ROLE
        with serving_device(PHONE):
            async with closing_stream(engine.follow_chat(after=0)) as chunks:
                first = await anext(chunks)
        assert isinstance(first, ChatStreamChunk)
        assert first.change is not None
    finally:
        await engine.aclose()


async def test_the_engines_stream_ends_when_it_shuts_down() -> None:
    """The engine closing ends every open stream with the cursor to reopen from."""
    engine = Harness(planner=NoStepPlanner(), chat_reader=False).engine
    await engine.set_my_devices([_PHONE])
    head = (await engine.chat_changes(after=0)).next_after
    async with closing_stream(engine.follow_chat(after=0)) as chunks:
        await anext(chunks)
        closing = asyncio.ensure_future(engine.aclose())
        async with asyncio.timeout(_SETTLE):
            rest = [chunk async for chunk in chunks]
        await closing

    assert rest[-1] == ChatStreamEnd(next_after=head)
    with pytest.raises(RuntimeError):
        engine.follow_chat(after=0)


async def test_a_snapshot_shows_a_message_deleted_since_as_its_marker() -> None:
    """§7:7: deleted since the change, so its marker; the text never reaches the device."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE)
    await chat.append_message(conversation, _said("regretted", "m-1"))
    await chat.set_conversation_devices(conversation, [_PHONE, _WATCH])
    await chat.delete_message(conversation, 1)

    sent = await _sent(chat, WATCH)

    joined = next(one for one in sent if one.snapshot is not None)
    assert joined.snapshot is not None
    assert joined.snapshot.entries == (DeletedMessage(conversation_id=conversation, position=1),)
    assert not any(isinstance(one, TranscriptMessage) for one in joined.snapshot.entries), (
        "no text of it"
    )
