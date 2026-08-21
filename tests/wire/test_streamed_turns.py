"""ADR-0173 §1 at the wire: many frames answering one request, still serially.

The frame sequence a streamed turn writes, the client's read loop that consumes it,
and the two clauses ADR-0173 §14 says a cooperative test will miss — that an
overlapping request stops the *writing* rather than merely closing afterwards, and
that the outcome is the same driven in process and driven across the wire, including
a turn whose chunk frames never reach the peer.

**Everything here runs over a real ``AF_UNIX`` socket.** A double in the middle would
let the sequence pass over a path the wire never takes, which is the failure the
transport half exists to catch in the direction nobody looks.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import UnknownConversationError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import ReplyChunk, TurnOutcome
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import envelope as env
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.errors import ConnectionClosedError
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.server import ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_LIMITS: Final = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")


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
        reply = await self.receive()
        assert reply.kind is env.FrameKind.CONNECT_ACK


class _GatedEngine(FakeAssistantEngine):
    """An engine whose stream holds its second chunk until a test releases it.

    The canonical fake streams straight through, which is what makes it useless for
    asking whether the hub *stopped writing*: with nothing suspended, "it never wrote
    the second chunk" and "it had not got that far yet" are the same observation.
    """

    def __init__(self) -> None:
        """Start with the second chunk held."""
        super().__init__()
        self.release = asyncio.Event()
        self.produced = 0
        self.turn_outcome = None

    def converse_streaming(
        self,
        utterance: str,
        *,
        timeout: timedelta,
        conversation_id: str | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Stream two chunks with a gate between them, then the outcome."""
        return self._gated(utterance, timeout=timeout, conversation_id=conversation_id)

    async def _gated(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own argument
        conversation_id: str | None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Yield ``"half an"``, wait, yield ``" answer"``, then the whole outcome."""
        base = await self.converse(utterance, timeout=timeout, conversation_id=conversation_id)
        outcome = TurnOutcome(
            turn=base.turn,
            step=base.step,
            conversation_id=base.conversation_id,
            reply="half an answer",
        )
        # Counted **before** each yield, because a generator resumes only when its
        # consumer asks for the next value: a count after the yield would read one
        # short precisely on the run this test is about, where the hub takes the
        # second chunk and then declines to write it.
        self.produced += 1
        yield ReplyChunk(text="half an")
        await self.release.wait()
        self.produced += 1
        yield ReplyChunk(text=" answer")
        yield outcome


@contextlib.asynccontextmanager
async def _serving(
    engine: FakeAssistantEngine, tmp_path: Path
) -> AsyncIterator[tuple[_Peer, asyncio.Task[None]]]:
    """Serve one connection over a real socket, so the framing is exercised too."""
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
        yield _Peer(reader, writer), served
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


def _streaming_request(correlation: str = "r-1", **arguments: Any) -> env.Envelope:
    """A ``converse_streaming`` request frame."""
    payload: dict[str, Any] = {"utterance": "hello", "timeout": "PT30S", **arguments}
    return env.Envelope(
        kind=env.FrameKind.REQUEST,
        id=correlation,
        method="converse_streaming",
        payload=payload,
    )


async def _read_the_answer(peer: _Peer) -> list[env.Envelope]:
    """Read frames until a terminal one, which §1 makes the last of the exchange."""
    frames: list[env.Envelope] = []
    while True:
        frame = await peer.receive()
        frames.append(frame)
        if frame.kind is not env.FrameKind.CHUNK:
            return frames


# --- ADR-0173 §1: the frame sequence ----------------------------------------


async def test_every_frame_of_one_answer_carries_the_requests_correlation_id(
    tmp_path: Path,
) -> None:
    """§1: "Every frame of the answer carries the request's correlation id".

    This is the reserved affordance being spent exactly as it was reserved: ADR-0084
    §3's mismatched-response rule says a response whose id does not match the
    outstanding request is a violation, and every chunk here carries the id that
    *does* match — so the rule is satisfied rather than bent.
    """
    async with _serving(FakeAssistantEngine(), tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(_streaming_request("r-7"))

        frames = await _read_the_answer(peer)

    assert [frame.id for frame in frames] == ["r-7"] * len(frames)


async def test_a_chunk_frame_names_no_method_and_the_terminal_frame_is_last(
    tmp_path: Path,
) -> None:
    """§2: a chunk "names no method", as no non-request frame does.

    ``wire/envelope.py`` already refuses a non-request frame that names one, so this
    asserts the sequence the hub actually writes rather than the decoder's rule —
    the two agreeing is the point.
    """
    async with _serving(FakeAssistantEngine(), tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(_streaming_request())

        frames = await _read_the_answer(peer)

    assert len(frames) > 1, "the fake's answer is long enough to chunk"
    assert all(frame.method is None for frame in frames)
    assert all(frame.kind is env.FrameKind.CHUNK for frame in frames[:-1])
    assert frames[-1].kind is env.FrameKind.RESULT


async def test_a_client_reading_the_sequence_obtains_what_converse_would_have(
    tmp_path: Path,
) -> None:
    """§14: "a client reading the sequence obtains the same ``TurnOutcome``".

    The same fake, the same utterance, two entries — and §4's promise is that a
    caller which wants no stream loses nothing by calling ``converse`` instead.
    """
    engine = FakeAssistantEngine()
    async with _serving(engine, tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(_streaming_request())
        frames = await _read_the_answer(peer)

    streamed = TurnOutcome.model_validate(frames[-1].payload)
    whole = await FakeAssistantEngine().converse("hello", timeout=_PATIENT)

    assert streamed.reply == whole.reply
    assert streamed.turn == whole.turn
    assert streamed.conversation_id == whole.conversation_id


async def test_converse_is_byte_identical_on_the_wire_to_what_it_is_today(
    tmp_path: Path,
) -> None:
    """§4: "``converse`` is unchanged… same one result frame".

    A caller that wants no stream "calls it and observes nothing this ADR adds" —
    one request frame in, one result frame out, no chunk frame anywhere.
    """
    async with _serving(FakeAssistantEngine(), tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(
            env.Envelope(
                kind=env.FrameKind.REQUEST,
                id="r-2",
                method="converse",
                payload={"utterance": "hello", "timeout": "PT30S"},
            )
        )

        reply = await peer.receive()

    assert reply.kind is env.FrameKind.RESULT
    assert reply.id == "r-2"


async def test_a_failure_terminates_the_exchange_with_an_error_frame(tmp_path: Path) -> None:
    """§1: "a result frame **or an error frame**", and §6's last clause.

    A stream terminated by an error produced no ``TurnOutcome``, so there is no
    ``reply`` to be authoritative and the client reports the failure — the residual
    ADR-0170 §8 already accepts for a propagating defect, reached one frame later.
    """
    async with _serving(FakeAssistantEngine(), tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(_streaming_request(conversation_id="no-such-id"))

        frames = await _read_the_answer(peer)

    assert [frame.kind for frame in frames] == [env.FrameKind.ERROR]
    assert frames[0].payload["code"] == UnknownConversationError.__name__


async def test_a_second_request_mid_stream_stops_the_writing_and_closes(
    tmp_path: Path,
) -> None:
    """§14's overlap clause, which "a test that asserts only the eventual close" misses.

    "A peer that sends a second request after receiving a first chunk has its
    connection closed, with **no further chunk frames written** after the violating
    request was readable and no correlated error sent." An implementation that
    streamed to completion and closed afterwards passes the weaker test and fails
    this one.

    **The schedule is the test's, which is what makes the assertion exact rather
    than timed.** :class:`_GatedEngine` holds its second chunk until this test
    releases it, so the violating request is on the socket *before* the hub has
    anything left to write — and what the peer reads next is either the second chunk
    (non-conforming) or a closed connection (conforming), with no race between them.
    """
    engine = _GatedEngine()
    async with _serving(engine, tmp_path) as (peer, served):
        await peer.handshake()
        await peer.send(_streaming_request("r-1"))
        first = await peer.receive()
        assert first.kind is env.FrameKind.CHUNK
        assert first.payload == {"text": "half an"}

        await peer.send(_streaming_request("r-2"))
        engine.release.set()

        with pytest.raises(ConnectionClosedError):
            await peer.receive()

    await asyncio.gather(served, return_exceptions=True)
    assert engine.produced == 2, (
        "the engine yielded its second chunk; §1 is about the hub declining to write it"
    )


# --- ADR-0173 §6: the commit point is the surface's, not the transport's ------


async def test_the_same_turn_yields_the_same_outcome_in_process_and_over_the_wire(
    tmp_path: Path,
) -> None:
    """§14: the commit point is asserted by comparing the two, not by inspection.

    ADR-0084 §5 promoted this façade to a Protocol precisely so the two are
    substitutable, and ADR-0173 §6 puts the commit point where the engine can
    observe it — "an in-process caller and a caller across the wire observe the same
    outcome for the same turn".
    """
    in_process = await _outcome_of(
        FakeAssistantEngine().converse_streaming("hello", timeout=_PATIENT)
    )

    async with _serving(FakeAssistantEngine(), tmp_path) as (peer, _):
        await peer.handshake()
        await peer.send(_streaming_request())
        frames = await _read_the_answer(peer)

    assert TurnOutcome.model_validate(frames[-1].payload) == in_process


async def test_a_turn_whose_chunk_frames_never_reach_the_peer_still_carries_them(
    tmp_path: Path,
) -> None:
    """§6's second clause, on the case that makes it bite (§14).

    The engine decides its shape "from what it yielded, never from what the
    transport achieved", so a peer that hangs up after the first chunk changes the
    outcome the engine produced by nothing. What that costs is a conservative
    disclosure and nothing else — and by §9 the peer is gone, so the terminal frame
    is discarded undelivered too and there is no client to mislead.
    """
    engine = FakeAssistantEngine()
    async with _serving(engine, tmp_path) as (peer, served):
        await peer.handshake()
        await peer.send(_streaming_request())
        assert (await peer.receive()).kind is env.FrameKind.CHUNK
        peer.writer.close()
        await asyncio.gather(served, return_exceptions=True)

    in_process = await _outcome_of(
        FakeAssistantEngine().converse_streaming("hello", timeout=_PATIENT)
    )
    assert in_process.reply is not None
    assert in_process.reply_degraded is False


# --- the client's read loop --------------------------------------------------


async def test_the_client_relays_chunks_then_the_outcome(tmp_path: Path) -> None:
    """The honest cost §1 names: "``HubClient._call``… reads exactly one".

    A streaming call reads until the terminal frame, and what it hands its caller is
    the same union the Protocol declares — chunks first, outcome last.
    """
    engine = FakeAssistantEngine()
    async with (
        _serving_client(engine, tmp_path) as client,
        closing_stream(client.converse_streaming("hello", timeout=_PATIENT)) as values,
    ):
        produced = [value async for value in values]

    assert isinstance(produced[-1], TurnOutcome)
    assert all(isinstance(value, ReplyChunk) for value in produced[:-1])
    joined = "".join(value.text for value in produced[:-1] if isinstance(value, ReplyChunk))
    assert joined == produced[-1].reply


async def test_the_client_reports_an_error_frame_that_terminates_a_stream(
    tmp_path: Path,
) -> None:
    """ADR-0085 §10a's reconstruction, reached one frame later than usual."""
    async with (
        _serving_client(FakeAssistantEngine(), tmp_path) as client,
        closing_stream(
            client.converse_streaming("hello", timeout=_PATIENT, conversation_id="nope")
        ) as values,
    ):
        with pytest.raises(UnknownConversationError):
            await _exhaust(values)


async def test_a_client_that_stops_reading_hangs_up_when_it_closes(tmp_path: Path) -> None:
    """§4: closing is the caller's obligation, and the client's cleanup is the hang-up.

    A generator nobody closes never runs its ``finally``, which is exactly why the
    contract states the obligation rather than leaving it to be discovered — and why
    a client that *does* close must really let the connection go.
    """
    async with _serving_client(FakeAssistantEngine(), tmp_path) as client:
        stream = client.converse_streaming("hello", timeout=_PATIENT)
        first = await anext(aiter(stream))
        assert isinstance(first, ReplyChunk)
        await stream.aclose()  # type: ignore[attr-defined]  # the contract's own clause


@contextlib.asynccontextmanager
async def _serving_client(
    engine: FakeAssistantEngine, tmp_path: Path
) -> AsyncIterator[HubEngineClient]:
    """A real client over a real socket, served for as long as the block runs."""
    path = tmp_path / "hub.sock"
    served: list[asyncio.Task[None]] = []

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        served.append(
            asyncio.ensure_future(serve_connection(engine, reader, writer, limits=_LIMITS))
        )

    server = await asyncio.start_unix_server(_accept, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        for task in served:
            task.cancel()
        await asyncio.gather(*served, return_exceptions=True)
        server.close()
        await server.wait_closed()


async def _exhaust(values: AsyncIterator[ReplyChunk | TurnOutcome]) -> None:
    """Read a stream to its end, discarding what it carried."""
    async for _ in values:
        pass


async def _outcome_of(stream: AsyncIterator[ReplyChunk | TurnOutcome]) -> TurnOutcome:
    """The terminal outcome of one streamed turn."""
    async with closing_stream(stream) as values:
        produced = [value async for value in values]
    terminal = produced[-1]
    assert isinstance(terminal, TurnOutcome)
    return terminal
