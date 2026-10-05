"""The change stream at the wire: frames, roles, heartbeat and the idle deadline (ADR-0298 §7).

``follow_chat`` is a streaming method on the existing wire (ADR-0296 §4:1-§4:2): chunk
frames answering one request, every one carrying its correlation id, until a terminal
frame or the connection's end. The hub's session layer writes the device's roles when
the stream opens and whenever they change, and a heartbeat whenever the heartbeat
interval passes with no chunk (§7:9-§7:12); the client reads with the dead-peer timeout
as its idle deadline and reopens a quiet stream from its cursor (§7:13).

The cases run over a real ``AF_UNIX`` socket, as the reply stream's did, and carry the
coverage issue #2728 asks of the streaming machinery: the frame sequence, the overlap
rule, a declared failure as the terminal frame, and the client's per-frame correlation
check. The two protocol constants are shortened for a case by patching the module
attribute each end reads.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.device_context import acting_for
from ai_assistant.core.errors import (
    DeviceRefusal,
    DeviceRefusedError,
    UnknownConversationError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    DeviceAccess,
    DeviceChange,
    DeviceRole,
    MessageAddedChange,
    MessageAuthor,
    RequestingDevice,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import envelope as env
from ai_assistant.wire import server as wire_server
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.errors import ConnectionClosedError, ProtocolError, error_payload
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.server import ConnectionLimits, serve_connection
from ai_assistant.wire.surface import chunk_adapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_LIMITS: Final = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")
_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_SETTLE: Final = 5.0
_QUICK: Final = timedelta(milliseconds=100)
_AT: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _said(message_id: str) -> UserMessage:
    return UserMessage(device_id="phone", message_id=message_id, text="hello")


class _Peer:
    """The client half of one served connection, driven frame by frame."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, frame: env.Envelope) -> None:
        """Write one frame."""
        await write_frame(self.writer, env.encode_envelope(frame), max_frame_bytes=_FRAME)

    async def receive(self) -> env.Envelope:
        """Read one frame."""
        body = await read_frame(
            self.reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        return env.decode_envelope(body)

    async def handshake(self) -> None:
        """Complete the connect exchange."""
        payload: dict[str, Any] = {
            env.CONNECT_VERSION: env.PROTOCOL_VERSION,
            env.CONNECT_CLIENT: "assistant-cli",
        }
        await self.send(env.Envelope(kind=env.FrameKind.CONNECT, id="c-0", payload=payload))
        assert (await self.receive()).kind is env.FrameKind.CONNECT_ACK


def _follow(correlation: str = "r-1", after: int = 0) -> env.Envelope:
    return env.Envelope(
        kind=env.FrameKind.REQUEST, id=correlation, method="follow_chat", payload={"after": after}
    )


def _chunk(frame: env.Envelope) -> ChatStreamChunk:
    value = chunk_adapter("follow_chat").validate_python(frame.payload)
    assert isinstance(value, ChatStreamChunk)
    return value


@contextlib.asynccontextmanager
async def _raw(engine: FakeAssistantEngine, tmp_path: Path) -> AsyncIterator[_Peer]:
    """Serve one connection over a real socket and hand back its peer, handshaken."""
    path = tmp_path / "s.sock"
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_unix_server(_accept, path=str(path))
    reader, writer = await asyncio.open_unix_connection(str(path))
    hub_reader, hub_writer = await accepted
    served = asyncio.ensure_future(serve_connection(engine, hub_reader, hub_writer, limits=_LIMITS))
    try:
        peer = _Peer(reader, writer)
        await peer.handshake()
        yield peer
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


@dataclass
class _Roster:
    """A device roster a case scripts, and may change while a stream is open."""

    devices: dict[str | None, RequestingDevice] = field(default_factory=dict)

    def requesting_device(self, *, connecting: str, acting_for: str | None) -> RequestingDevice:
        """Answer as scripted; a name absent is refused as not accepted."""
        del connecting
        if acting_for not in self.devices:
            msg = "that device is not accepted under this gateway"
            raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ACCEPTED)
        return self.devices[acting_for]

    def knows(self, device_id: str) -> bool:
        """Every scripted device is known."""
        return any(one.device_id == device_id for one in self.devices.values())


@contextlib.asynccontextmanager
async def _client(
    engine: FakeAssistantEngine, tmp_path: Path, roster: _Roster | None = None
) -> AsyncIterator[HubEngineClient]:
    """Serve on a socket, each connection as the hub serves it, and hand back a client."""
    path = tmp_path / "hub.sock"

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=_LIMITS, roster=roster)

    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


async def _next(
    chunks: AsyncIterator[ChatStreamChunk | ChatStreamEnd], *, wanted: str
) -> ChatStreamChunk:
    """The next chunk holding ``wanted`` — a change, roles or a heartbeat."""
    async with asyncio.timeout(_SETTLE):
        async for chunk in chunks:
            assert isinstance(chunk, ChatStreamChunk)
            if wanted == "heartbeat" and chunk.heartbeat:
                return chunk
            if wanted != "heartbeat" and getattr(chunk, wanted) is not None:
                return chunk
    msg = f"the stream ended before a chunk holding {wanted}"
    raise AssertionError(msg)


async def _engine_with_a_conversation() -> tuple[FakeAssistantEngine, str]:
    engine = FakeAssistantEngine(chat_reader=False)
    await engine.set_my_devices([_PHONE])
    return engine, (await engine.start_conversation()).id


# --- the frame sequence -----------------------------------------------------


async def test_every_frame_is_a_chunk_of_the_one_request_and_opens_with_the_roles(
    tmp_path: Path,
) -> None:
    """ADR-0173 §1:1 kept: chunks carrying the request's id and no method; roles first.

    Then the engine's: the conversation's state as the stream opens (#2740), and its
    changes.
    """
    engine, conversation = await _engine_with_a_conversation()
    async with _raw(engine, tmp_path) as peer:
        await peer.send(_follow("r-1"))
        frames = [await peer.receive() for _ in range(4)]
        await engine.write_message(conversation, message=_said("m-1"))
        frames.append(await peer.receive())

    assert all(one.kind is env.FrameKind.CHUNK for one in frames)
    assert all(one.id == "r-1" and one.method is None for one in frames)
    chunks = [_chunk(one) for one in frames]
    assert chunks[0] == ChatStreamChunk(roles=(DeviceRole.COMMANDS, DeviceRole.SPOKES))
    assert chunks[1].state is not None
    assert chunks[1].state.conversation_id == conversation
    changes = [one.change for one in chunks[2:]]
    assert all(one is not None for one in changes)
    live = chunks[-1].change
    assert live is not None
    assert isinstance(live.change, MessageAddedChange)


async def test_a_second_request_mid_stream_closes_with_nothing_more_written(
    tmp_path: Path,
) -> None:
    """ADR-0084 §3 on a stream: the hub stops writing and closes, replying to neither."""
    engine, conversation = await _engine_with_a_conversation()
    async with _raw(engine, tmp_path) as peer:
        await peer.send(_follow("r-1"))
        for _ in range(3):
            await peer.receive()
        await peer.send(_follow("r-2"))
        await engine.write_message(conversation, message=_said("m-1"))
        with pytest.raises(ConnectionClosedError):
            await peer.receive()


class _Ending(FakeAssistantEngine):
    """An engine whose stream sends one change, then ends as a shutdown or a failure."""

    def __init__(self, *, failing: bool) -> None:
        super().__init__()
        self.failing = failing

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """One change, then the end or a declared failure."""
        return self._ending(after)

    async def _ending(self, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        page = await self.chat.changes(after=after, limit=1)
        yield ChatStreamChunk(change=DeviceChange(change=page.changes[0]))
        if self.failing:
            raise UnknownConversationError("c-gone")
        yield ChatStreamEnd(next_after=page.next_after)


@pytest.mark.parametrize("failing", [False, True])
async def test_the_stream_ends_with_one_terminal_frame(tmp_path: Path, failing: bool) -> None:
    """A result frame carrying the cursor, or the declared failure as an error frame."""
    engine = _Ending(failing=failing)
    await engine.set_my_devices([_PHONE])
    async with _raw(engine, tmp_path) as peer:
        await peer.send(_follow("r-1"))
        roles, change, terminal = [await peer.receive() for _ in range(3)]

    assert (roles.kind, change.kind) == (env.FrameKind.CHUNK, env.FrameKind.CHUNK)
    assert terminal.id == "r-1"
    if failing:
        assert terminal.kind is env.FrameKind.ERROR
        assert terminal.payload == error_payload(
            UnknownConversationError("c-gone"), max_bytes=_LIMITS.payload_limit
        )
    else:
        assert terminal.kind is env.FrameKind.RESULT
        assert terminal.payload == {"next_after": 1}


# --- the session layer's chunks (§7:9-§7:12, §7:16) --------------------------


async def test_a_quiet_stream_carries_a_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:12: written whenever the interval passes with no chunk."""
    monkeypatch.setattr(wire_server, "CHANGE_STREAM_HEARTBEAT", _QUICK)
    engine, _ = await _engine_with_a_conversation()
    async with (
        _client(engine, tmp_path) as client,
        closing_stream(client.follow_chat(after=0)) as chunks,
    ):
        beat = await _next(chunks, wanted="heartbeat")

    assert beat == ChatStreamChunk(heartbeat=True)


async def test_a_change_of_roles_is_sent_and_a_revoked_name_ends_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:9: the roles at opening and on change; §7:16: revocation ends it, refused."""
    monkeypatch.setattr(wire_server, "CHANGE_STREAM_HEARTBEAT", _QUICK)
    engine, _ = await _engine_with_a_conversation()
    phone = RequestingDevice(device_id="phone", roles=frozenset({DeviceRole.COMMANDS}))
    roster = _Roster(devices={"phone": phone})
    async with _client(engine, tmp_path, roster) as client:
        with acting_for("phone"):
            async with closing_stream(client.follow_chat(after=0)) as chunks:
                opened = await _next(chunks, wanted="roles")
                roster.devices["phone"] = RequestingDevice(
                    device_id="phone", roles=frozenset(DeviceRole)
                )
                changed = await _next(chunks, wanted="roles")
                del roster.devices["phone"]
                with pytest.raises(DeviceRefusedError) as refused:
                    await _next(chunks, wanted="roles")

    assert opened.roles == (DeviceRole.COMMANDS,)
    assert changed.roles == (DeviceRole.COMMANDS, DeviceRole.SPOKES)
    assert refused.value.reason is DeviceRefusal.NOT_ACCEPTED


# --- the client's idle deadline (§7:13) --------------------------------------


class _Reopening(FakeAssistantEngine):
    """An engine that says when its stream has been opened a second time."""

    def __init__(self) -> None:
        super().__init__(chat_reader=False)
        self.reopened = asyncio.Event()

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Follow as the fake does, noting a second opening."""
        stream = super().follow_chat(after=after)
        if len([name for name, _ in self.calls if name == "follow_chat"]) >= 2:
            self.reopened.set()
        return stream


async def test_the_client_reopens_a_quiet_stream_from_the_last_change_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:13: no frame within the dead-peer timeout, so close and reopen with the cursor."""
    monkeypatch.setattr(env, "CHANGE_STREAM_DEAD_PEER", _QUICK)
    engine = _Reopening()
    await engine.set_my_devices([_PHONE])
    conversation = (await engine.start_conversation()).id
    async with (
        _client(engine, tmp_path) as client,
        closing_stream(client.follow_chat(after=0)) as chunks,
    ):
        first = (await _next(chunks, wanted="change")).change
        second = (await _next(chunks, wanted="change")).change
        assert first is not None
        assert second is not None
        # Waiting for its next change, the client sees no frame within the deadline
        # and reopens; the change written once it has is read on the reopened stream.
        pending = asyncio.ensure_future(_next(chunks, wanted="change"))
        async with asyncio.timeout(_SETTLE):
            await engine.reopened.wait()
        await engine.write_message(conversation, message=_said("m-1"))
        live = (await pending).change

    assert live is not None
    assert isinstance(live.change, MessageAddedChange)
    cursors = [call["after"] for name, call in engine.calls if name == "follow_chat"]
    assert cursors[0] == 0
    assert len(cursors) >= 2, "the quiet stream was reopened"
    assert cursors[1] == second.seq, "from the last change the caller took"


async def test_the_client_refuses_a_chunk_answering_another_request(tmp_path: Path) -> None:
    """ADR-0084 §3 on every frame of a stream: a mismatched id is unrepairable."""
    path = tmp_path / "hub.sock"

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = _Peer(reader, writer)
        connect = await peer.receive()
        await peer.send(
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=connect.id,
                payload=env.connect_ack_payload(build="test", max_frame_bytes=_FRAME),
            )
        )
        await peer.receive()
        chunk = ChatStreamChunk(heartbeat=True)
        await peer.send(env.Envelope(kind=env.FrameKind.CHUNK, id="not-yours", payload=chunk))
        with contextlib.suppress(Exception):
            await peer.receive()  # until the client hangs up

    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        client = HubEngineClient(path, read_timeout=_PATIENT)
        async with closing_stream(client.follow_chat(after=0)) as chunks:
            with pytest.raises(ProtocolError, match="correlation"):
                await anext(chunks)
    finally:
        server.close()
        await server.wait_closed()


async def test_a_malformed_cursor_is_refused_before_any_connection(tmp_path: Path) -> None:
    """ADR-0085 §9: refused from the call, with nothing listening."""
    client = HubEngineClient(tmp_path / "nothing.sock", read_timeout=_PATIENT)
    with pytest.raises(ValueError, match="after"):
        client.follow_chat(after=-1)


# --- the dead-peer timeout on the hub's side (§7:14) -------------------------


class _Socket:
    def __init__(self, family: socket.AddressFamily) -> None:
        self.family = family
        self.set: list[tuple[int, int, int]] = []

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.set.append((level, option, value))


class _Writer:
    def __init__(self, held: _Socket) -> None:
        self.held = held

    def get_extra_info(self, name: str) -> object:
        return self.held if name == "socket" else None


@pytest.mark.skipif(
    not hasattr(socket, "TCP_USER_TIMEOUT"), reason="the platform offers no user timeout"
)
def test_a_tcp_stream_sets_its_user_timeout_to_the_dead_peer_timeout() -> None:
    """§7:14: a silent peer becomes a closed connection within the timeout."""
    tcp, local = _Socket(socket.AF_INET), _Socket(socket.AF_UNIX)
    wire_server._bound_user_timeout(_Writer(tcp))  # type: ignore[arg-type]
    wire_server._bound_user_timeout(_Writer(local))  # type: ignore[arg-type]

    milliseconds = int(env.CHANGE_STREAM_DEAD_PEER.total_seconds() * 1000)
    assert tcp.set == [(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, milliseconds)]
    assert local.set == [], "the local socket reports a closed peer at once"


class _Flooding(FakeAssistantEngine):
    """An engine whose stream sends large chunks for as long as it is read."""

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Large changes, one after another."""
        del after
        return self._flooding()

    async def _flooding(self) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        seq = 0
        while True:
            seq += 1
            message = TranscriptMessage(
                conversation_id="c-1",
                position=seq,
                written_at=_AT,
                author=MessageAuthor.ASSISTANT,
                text="x" * 15_000,
            )
            change = MessageAddedChange(seq=seq, message=message)
            yield ChatStreamChunk(change=DeviceChange(change=change))


async def test_a_peer_that_stops_reading_is_abandoned_at_the_dead_peer_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:14: a write that does not drain ends the connection, and its hang-up with it."""
    monkeypatch.setattr(wire_server, "CHANGE_STREAM_DEAD_PEER", _QUICK)
    path = tmp_path / "s.sock"
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_unix_server(_accept, path=str(path))
    reader, writer = await asyncio.open_unix_connection(str(path))
    hub_reader, hub_writer = await accepted
    served = asyncio.ensure_future(
        serve_connection(_Flooding(), hub_reader, hub_writer, limits=_LIMITS)
    )
    try:
        peer = _Peer(reader, writer)
        await peer.handshake()
        await peer.send(_follow("r-1"))
        # The peer reads nothing more, so the hub's writes fill the socket and stall.
        # Well inside the connection's own read deadline, so it is the stalled write
        # that ends it, and its hang-up does not wait for the bytes to drain.
        # Shielded, so the deadline expiring fails the case rather than cancelling the
        # serving task into an ending of its own.
        async with asyncio.timeout(_PATIENT.total_seconds() / 4):
            await asyncio.shield(served)
        assert hub_writer.transport.is_closing()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


async def test_a_shutdown_cancelling_a_stalled_write_does_not_wait_on_it(
    tmp_path: Path,
) -> None:
    """Round 4's case: the hub cancels a connection whose write is stalled on its peer.

    Cancelled mid-write, the write is abandoned as a timed-out one is, so the hang-up
    after it does not wait for the bytes the peer will never read.
    """
    path = tmp_path / "s.sock"
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_unix_server(_accept, path=str(path))
    reader, writer = await asyncio.open_unix_connection(str(path))
    hub_reader, hub_writer = await accepted
    served = asyncio.ensure_future(
        serve_connection(_Flooding(), hub_reader, hub_writer, limits=_LIMITS)
    )
    try:
        peer = _Peer(reader, writer)
        await peer.handshake()
        await peer.send(_follow("r-1"))
        await asyncio.sleep(0.2)  # long enough for the writes to fill the socket
        assert not served.done()
        served.cancel()
        done, _ = await asyncio.wait({served}, timeout=_PATIENT.total_seconds() / 4)
        assert done, "the cancelled connection ended rather than waiting on its write"
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


def test_the_two_figures_are_the_ones_the_adr_fixed() -> None:
    """§7:11: 15 seconds and 45, protocol constants both ends read."""
    assert timedelta(seconds=15) == env.CHANGE_STREAM_HEARTBEAT
    assert timedelta(seconds=45) == env.CHANGE_STREAM_DEAD_PEER
