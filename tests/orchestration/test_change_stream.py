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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import (
    DeviceRefusal,
    DeviceRefusedError,
    MemoryStoreError,
    OversizedValueError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    CHAT_DEVICES_MAX,
    HUB_REQUESTING_DEVICE,
    ActivationEnding,
    ChatChanges,
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
    MemorySource,
    MessageAddedChange,
    MessageAuthor,
    NewMessage,
    Provenance,
    RequestingDevice,
    SemanticMemory,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.change_stream import Activity, ChangeStream
from ai_assistant.orchestration.conversations import (
    check_devices_fit,
    check_message_fits,
    fit_stream_chunk,
    fitted_message,
)
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.server import ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Sequence
    from pathlib import Path

    from ai_assistant.core.types import CurrentState, MemoryRecord

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH: Final = ChatDevice(device_id="watch", access=DeviceAccess.READ)
_PEN: Final = ChatDevice(device_id="pen", access=DeviceAccess.WRITE)
PHONE: Final = RequestingDevice(device_id="phone")
WATCH: Final = RequestingDevice(device_id="watch")
PEN: Final = RequestingDevice(device_id="pen")

#: A payload limit roomy enough for every case but the one that fits a snapshot.
_ROOMY: Final = 1_000_000
_AT: Final = datetime(2026, 1, 1, 12, tzinfo=UTC)
_SETTLE: Final = 5.0


class _Engine:
    """What the stream reads of an engine: what runs, and the state it shows."""

    def __init__(self) -> None:
        self.activity: dict[str, Activity] = {}
        self.closing = False
        self.states: dict[str, ConversationState] = {}
        #: Where set, a state read waits on it, having set ``reading``.
        self.gate: asyncio.Event | None = None
        self.reading = asyncio.Event()

    async def state_of(self, conversation_id: str, running: Sequence[str | None]) -> object:
        del running
        if self.gate is not None:
            self.reading.set()
            await self.gate.wait()
        return self.states.get(conversation_id, ConversationState())


async def _tracked[T](work: Awaitable[T]) -> T:
    return await work


def _stream(
    chat: FakeConversationStore,
    engine: _Engine | None = None,
    *,
    limit: int = _ROOMY,
    poll: float = 0.01,
    sweep: float = 60.0,
) -> ChangeStream:
    held = engine or _Engine()
    return ChangeStream(
        chat=chat,
        running=lambda: held.activity,
        state_of=held.state_of,  # type: ignore[arg-type]
        closing=lambda: held.closing,
        tracked=_tracked,
        max_payload_bytes=limit,
        poll_seconds=poll,
        sweep_seconds=sweep,
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
    assert [one.position for one in joined.snapshot] == [1]
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


async def test_a_device_removed_part_way_through_a_page_is_sent_nothing_more_of_it() -> None:
    """§7:5 at the moment of sending: read again after each chunk, not once a page."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE, _WATCH)
    for index in range(3):
        await chat.append_message(conversation, _said("held back", f"m-{index}"))

    async with _Following(_stream(chat).follow(WATCH, after=0)) as following:
        first = await following.next(_SETTLE)
        await chat.set_conversation_devices(conversation, [_PHONE])
        rest = await following.drain()

    assert isinstance(first, ChatStreamChunk)
    assert first.change is not None
    assert first.change.conversation_id is None, "my devices, before the removal"
    assert [type(one.change) for one in rest] == [DevicesChangedChange], "its removal alone"


async def test_a_device_removed_while_its_state_is_read_is_not_sent_it() -> None:
    """§7:5 again after the state's own read: the episodes take a read of their own."""
    chat = FakeConversationStore()
    conversation = await _chat(chat, _PHONE, _WATCH)
    engine = _Engine()
    async with _Following(_stream(chat, engine).follow(WATCH, after=0)) as following:
        await following.drain()
        engine.gate = asyncio.Event()
        engine.activity = {conversation: Activity(turns=1, running=("a-1",))}
        async with asyncio.timeout(_SETTLE):
            await engine.reading.wait()
        await chat.set_conversation_devices(conversation, [_PHONE])
        engine.gate.set()
        sent = []
        while (chunk := await following.next(0.2)) is not None:
            assert isinstance(chunk, ChatStreamChunk)
            sent.append(chunk)

    assert [one.state for one in sent if one.state is not None] == []
    assert [type(one.change.change) for one in sent if one.change is not None] == [
        DevicesChangedChange
    ], "its removal alone"


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
    positions = [one.position for one in joined.change.snapshot]
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
                    assert chunk.change.snapshot == ()
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


async def test_closing_wakes_a_waiting_stream_to_its_end_and_waits_for_it() -> None:
    """A stream waiting out its interval ends at once when its engine shuts down."""
    chat = FakeConversationStore()
    await _chat(chat, _PHONE)
    engine = _Engine()
    stream = _stream(chat, engine, poll=60.0)
    async with _Following(stream.follow(PHONE, after=0)) as following:
        await following.drain()
        engine.closing = True
        closing = asyncio.ensure_future(stream.close(within=_SETTLE))
        last = await following.next(1.0)
        await asyncio.sleep(0)
        assert not closing.done(), "the stream is not closed until its reader closes it"
    async with asyncio.timeout(1.0):
        await closing

    assert isinstance(last, ChatStreamEnd)


async def test_a_state_no_act_changed_is_sent_by_the_sweep() -> None:
    """Round 5's case: an episode leaving its window changes a state with nothing run.

    The sweep reads every read conversation's state again and sends each that differs
    from the last the stream knew, and none to a device that does not read it.
    """
    chat = FakeConversationStore()
    shown = await _chat(chat, _PHONE)
    hidden = await _chat(chat, _PEN)
    engine = _Engine()
    engine.states[shown] = ConversationState(last_ended=ActivationEnding.DONE)
    engine.states[hidden] = ConversationState(last_ended=ActivationEnding.DONE)
    async with _Following(_stream(chat, engine, sweep=0.05).follow(PHONE, after=0)) as following:
        await following.drain()
        engine.states[shown] = ConversationState()  # its episode expired
        engine.states[hidden] = ConversationState()
        sent: list[CurrentState] = []
        while (chunk := await following.next(0.3)) is not None:
            if isinstance(chunk, ChatStreamChunk) and chunk.state is not None:
                sent.append(chunk.state)

    assert [(one.conversation_id, one.state) for one in sent] == [(shown, ConversationState())]


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


async def test_the_hub_writes_each_streams_end_before_its_listener_closes(
    tmp_path: Path,
) -> None:
    """Round 3's case: the hub closes its engine, then cancels the connections it serves.

    An idle stream sleeps out its interval with no engine work in flight, so a drain
    alone would let the hub cancel its connection before it wrote its end. The engine
    wakes its streams and waits for each to be closed, so the end is on the wire first.
    """
    engine = Harness(planner=NoStepPlanner(), chat_reader=False).engine
    await engine.set_my_devices([_PHONE])
    served: set[asyncio.Task[None]] = set()
    limits = ConnectionLimits(
        max_frame_bytes=1 << 20, read_timeout=timedelta(seconds=5), build="test"
    )

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        served.add(task)
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    client = HubEngineClient(path, read_timeout=timedelta(seconds=5))
    received: list[ChatStreamChunk | ChatStreamEnd] = []
    changed = asyncio.Event()

    async def follow() -> None:
        async with closing_stream(client.follow_chat(after=0)) as chunks:
            async for chunk in chunks:
                received.append(chunk)
                if isinstance(chunk, ChatStreamChunk) and chunk.change is not None:
                    changed.set()

    following = asyncio.ensure_future(follow())
    try:
        async with asyncio.timeout(_SETTLE):
            await changed.wait()
        await engine.aclose()
        # The hub's own order: the engine closed, then every served connection.
        server.close()
        for task in served:
            task.cancel()
        await asyncio.gather(*served, return_exceptions=True)
        await asyncio.gather(following, return_exceptions=True)
    finally:
        following.cancel()
        await server.wait_closed()

    assert isinstance(received[-1], ChatStreamEnd)


class _Unreadable(FakeMemoryStore):
    """A memory store whose one record cannot be read, though it can be destroyed."""

    def __init__(self, unreadable: str) -> None:
        super().__init__()
        self.unreadable = unreadable

    async def get(self, record_id: str) -> MemoryRecord | None:
        if record_id == self.unreadable:
            msg = "a stored record could not be decoded"
            raise MemoryStoreError(msg)
        return await super().get(record_id)


async def test_a_record_that_cannot_be_read_is_still_forgotten() -> None:
    """ADR-0073 §5: the read a forget makes for the stream never stands in its way."""
    memory = _Unreadable("note-1")
    await memory.add(
        SemanticMemory(
            id="note-1",
            content="unreadable",
            fact="unreadable",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT
            ),
        )
    )
    engine = Harness(planner=NoStepPlanner(), chat_reader=False, memory=memory).engine
    try:
        assert await engine.forget("note-1") is True
        assert await memory.delete("note-1") is False, "already destroyed"
    finally:
        await engine.aclose()


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
    assert joined.snapshot == (DeletedMessage(conversation_id=conversation, position=1),)
    assert not any(isinstance(one, TranscriptMessage) for one in joined.snapshot), "no text of it"


# --- every change the chat space admits fits one chunk (§7:3, §7:8) ----------

_WIDEST: Final = 2**63 - 1
_WIDEST_AT: Final = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
_UUID_WIDE: Final = "0" * 36


def _widest_chunk(conversation_id: str, message: NewMessage) -> ChatStreamChunk:
    """The chunk carrying ``message`` recorded at the widest values it could take."""
    recorded = TranscriptMessage(
        conversation_id=conversation_id,
        position=_WIDEST,
        written_at=_WIDEST_AT,
        **message.model_dump(),
    )
    return ChatStreamChunk(
        change=DeviceChange(change=MessageAddedChange(seq=_WIDEST, message=recorded))
    )


def _longest_admitted(limit: int) -> int:
    """The longest text ``check_message_fits`` admits at ``limit``, by bisection."""
    low, high = 1, limit
    while high - low > 1:
        middle = (low + high) // 2
        message = UserMessage(device_id="phone", message_id="m", text="x" * middle)
        try:
            check_message_fits(_UUID_WIDE, message, max_bytes=limit)
        except OversizedValueError:
            high = middle
        else:
            low = middle
    return low


@pytest.mark.parametrize("limit", [1024, 2048, 4096])
def test_a_message_admitted_is_one_its_chunk_can_carry(limit: int) -> None:
    """A message the conversation records is never one the stream cannot send.

    The adversarial round's case: a message whose transcript page and change page fit
    the limit while the chunk carrying it, one wrapper wider, did not, so every stream
    reaching it failed at it for good. The chunk is measured at admission too.
    """
    longest = _longest_admitted(limit)
    admitted = UserMessage(device_id="phone", message_id="m", text="x" * longest)
    chunk = _widest_chunk(_UUID_WIDE, admitted.as_new_message())

    assert len(canonical_payload(chunk)) <= limit
    assert fit_stream_chunk(chunk, max_bytes=limit) == chunk


def test_an_assistant_message_is_cut_to_what_its_chunk_can_carry() -> None:
    """The writer's fitting measures the chunk too, so a reply never stops a stream."""
    limit = 2048
    reply = NewMessage(author=MessageAuthor.ASSISTANT, text="y" * 4000)

    fitted = fitted_message(_UUID_WIDE, reply, max_bytes=limit)

    assert fitted.cut_off
    assert len(canonical_payload(_widest_chunk(_UUID_WIDE, fitted))) <= limit


def test_a_set_of_devices_admitted_is_one_its_chunk_can_carry() -> None:
    """A set the chat space records travels in one chunk, its snapshot cut to none."""
    limit = 2048
    admitted: list[ChatDevice] = []
    for index in range(CHAT_DEVICES_MAX):
        candidate = [
            *admitted,
            ChatDevice(device_id=f"device-{index:04d}-" + "d" * 40, access=DeviceAccess.READ),
        ]
        try:
            check_devices_fit(candidate, conversation_id=_UUID_WIDE, max_bytes=limit)
        except OversizedValueError:
            break
        admitted = candidate
    assert admitted, "some set fits"
    change = DevicesChangedChange(seq=_WIDEST, conversation_id=_UUID_WIDE, devices=tuple(admitted))
    chunk = ChatStreamChunk(change=DeviceChange(change=change, snapshot=()))

    assert len(canonical_payload(chunk)) <= limit


def test_a_message_recorded_before_the_stream_existed_fits_its_chunk() -> None:
    """A record admitted when only the two pages were measured still fits one chunk.

    The second round's case: ``check_message_fits`` measured the transcript page and
    the change page before this stream was built, and a record it admitted then at the
    boundary is still in the chat space. A chunk leaves its absent members out, so it
    is no wider than that change page, and the stream carries it.
    """
    for limit in (1024, 2048, 4096):
        low, high = 1, limit
        while high - low > 1:
            middle = (low + high) // 2
            said = UserMessage(device_id="phone", message_id="m", text="x" * middle)
            chunk = _widest_chunk(_UUID_WIDE, said.as_new_message())
            assert chunk.change is not None
            page = ChatChanges(changes=(chunk.change.change,), next_after=_WIDEST)
            if len(canonical_payload(page)) <= limit:
                low = middle
            else:
                high = middle
        said = UserMessage(device_id="phone", message_id="m", text="x" * low)
        chunk = _widest_chunk(_UUID_WIDE, said.as_new_message())
        assert len(canonical_payload(chunk)) <= limit


def test_a_set_of_devices_recorded_before_the_stream_existed_fits_its_chunk() -> None:
    """Round 3's case: a set change admitted when only its page was measured travels.

    A conversation id need not be a store's UUID — one joined from before the chat
    space is any identifier — so the boundary is taken with a long one. A chunk carries
    its snapshot cut to none as an empty list, with the conversation and the instant
    the change's own, so it is no wider than the change's one-change page.
    """
    conversation = "c" * 128
    for limit in (1024, 2048):
        devices: list[ChatDevice] = []
        for index in range(CHAT_DEVICES_MAX):
            candidate = [
                *devices,
                ChatDevice(device_id=f"{index:04d}" + "d" * 88, access=DeviceAccess.READ),
            ]
            change = DevicesChangedChange(
                seq=_WIDEST, conversation_id=conversation, devices=tuple(candidate)
            )
            if len(canonical_payload(ChatChanges(changes=(change,), next_after=_WIDEST))) > limit:
                break
            devices = candidate
        change = DevicesChangedChange(
            seq=_WIDEST, conversation_id=conversation, devices=tuple(devices)
        )
        chunk = ChatStreamChunk(change=DeviceChange(change=change, snapshot=()))
        assert len(canonical_payload(chunk)) <= limit
        assert fit_stream_chunk(chunk, max_bytes=limit) == chunk
