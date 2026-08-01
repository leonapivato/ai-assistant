"""What the client does when there is no hub, or the wrong one, or a rude one.

The conformance suite (``test_client_contract.py``) holds the client to the
*engine* contract. These are the conditions ADR-0085 §9 puts outside it — "ADR-0084
§3's undecodable-frame close, version mismatch, credential refusal and
second-concurrent-request close are all transport conditions… They are not
``AssistantEngine`` failures and no Protocol method declares them" — and each is
driven against a real socket with a deliberately misbehaving peer on the other end.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import OversizedValueError, UnresolvedEvidenceError
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import ENVELOPE_RESERVE_BYTES, HubEngineClient, serve_connection
from ai_assistant.wire import envelope as env
from ai_assistant.wire.errors import HubUnavailableError, ProtocolError
from ai_assistant.wire.framing import PREFIX_BYTES, read_frame, write_frame
from ai_assistant.wire.peer import check_peer_is_self, peer_uid
from ai_assistant.wire.server import ConnectionLimits

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

_PATIENT = timedelta(seconds=5)
_FRAME = 1 << 20


@contextlib.asynccontextmanager
async def _listening(
    path: Path, handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]
) -> AsyncIterator[HubEngineClient]:
    """Run an arbitrary handler on a socket, and hand back a client of it."""
    server = await asyncio.start_unix_server(handler, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        _unlink(path)


def _unlink(path: Path) -> None:
    """Remove the socket, off the async path so the checkers stay happy."""
    path.unlink(missing_ok=True)


async def _read_one(reader: asyncio.StreamReader) -> env.Envelope:
    """Read one frame from a client, as a rogue hub would."""
    body = await read_frame(reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT)
    return env.decode_envelope(body)


async def _send(writer: asyncio.StreamWriter, envelope: env.Envelope) -> None:
    """Write one frame back."""
    await write_frame(writer, env.encode_envelope(envelope), max_frame_bytes=_FRAME)


# --- a closed door (ADR-0084 §9) -------------------------------------------


async def test_no_hub_is_an_instruction_naming_the_socket_and_the_command(
    tmp_path: Path,
) -> None:
    """§9: "the client fails with a message naming the socket path it tried and how
    to start the hub, and **exits non-zero**".

    The two halves are asserted separately because a message with only one of them
    is the failure: a path with no command leaves the user guessing, and a command
    with no path leaves them unable to tell which deployment is down.
    """
    client = HubEngineClient(tmp_path / "hub.sock", read_timeout=_PATIENT)
    with pytest.raises(HubUnavailableError) as caught:
        await client.probe()
    assert str(tmp_path / "hub.sock") in str(caught.value)
    assert "ai-assistant-hub" in str(caught.value)


async def test_a_closed_door_is_never_a_fallback(tmp_path: Path) -> None:
    """Ruling 3 and ruling 5, asserted as an absence.

    Nothing is spawned and nothing is built in-process, so **every** method fails
    the same way rather than some of them quietly working. Walking the surface is
    what makes that a property rather than a spot check: a fallback added to one
    method would pass a test that only drove ``converse``.
    """
    client = HubEngineClient(tmp_path / "hub.sock", read_timeout=_PATIENT)
    with pytest.raises(HubUnavailableError):
        await client.beliefs()
    with pytest.raises(HubUnavailableError):
        await client.pending_confirmations()
    with pytest.raises(HubUnavailableError):
        await client.forget("rec-1")
    assert not (tmp_path / "hub.sock").exists()


# --- the handshake's two refusals (ADR-0084 §2, §3) ------------------------


async def test_a_version_mismatch_is_reported_before_it_closes(tmp_path: Path) -> None:
    """§3: a mismatch "**refuses the connection** with a message naming both
    versions and the operator action".

    "Ruling 4 would be poorly served by a silent close on a version mismatch, and it
    does not get one" — so the hub answers with an error frame and only then closes,
    which is what makes the message reachable at all.
    """

    async def _future_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        frame = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=frame.id,
                payload={
                    env.ACK_VERSION: env.PROTOCOL_VERSION + 1,
                    env.ACK_BUILD: "next",
                    env.ACK_READY: True,
                    env.ACK_MAX_FRAME_BYTES: _FRAME,
                },
            ),
        )

    async with _listening(tmp_path / "hub.sock", _future_hub) as client:
        with pytest.raises(ProtocolError) as caught:
            await client.probe()
    assert str(env.PROTOCOL_VERSION) in str(caught.value)
    assert str(env.PROTOCOL_VERSION + 1) in str(caught.value)


async def test_the_hub_refuses_a_credentialled_connect_and_says_why(tmp_path: Path) -> None:
    """§2, from the server's side, with a client that presents one.

    The refusal has to be legible rather than a close, because "it would do so
    silently on the day someone points a future authenticating client at an old
    hub". Driven by writing the connect frame by hand, since a conforming client
    cannot produce this.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT,
                id="c-1",
                payload={
                    env.CONNECT_VERSION: env.PROTOCOL_VERSION,
                    env.CONNECT_CLIENT: "rogue",
                    env.CONNECT_CREDENTIAL: "hunter2",
                },
            ),
        )
        reply = await _read_one(reader)
        writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert reply.kind is env.FrameKind.ERROR
    assert reply.payload["code"] == env.CREDENTIAL_NOT_SUPPORTED
    assert "credential" in reply.payload["message"]


# --- authenticating the hub from the kernel (ADR-0084 §1) ------------------


async def test_the_peer_credential_of_our_own_socket_is_our_own_uid() -> None:
    """The mechanism, before the rule that uses it.

    ADR-0084 §1 states the obligation "in terms of the *credential* so that it binds
    on both" Linux and the BSDs; this asserts that the Linux mechanism reports what
    it is supposed to, which is what the refusal below rests on.
    """
    left, right = socket.socketpair()
    try:
        assert peer_uid(left) == os.geteuid()
        check_peer_is_self(left)
    finally:
        left.close()
        right.close()


async def test_a_hub_running_as_another_user_is_refused_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1's actual close, and the reason a filesystem walk is not it.

    "A replaced socket belonging to another user is refused at that point whatever
    the directory modes were" — and the check runs **after ``connect()`` and before
    sending anything**, so the utterance never leaves this process. The foreign uid
    is injected because a test cannot bind a socket as another user, but the *rule*
    under test is the comparison, not the syscall.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    monkeypatch.setattr("ai_assistant.wire.peer.peer_uid", lambda _sock: os.geteuid() + 1)
    async with _listening(tmp_path / "hub.sock", _hub) as client:
        with pytest.raises(ProtocolError, match="another user"):
            await client.converse("something private", timeout=_PATIENT)


# --- the serial connection's two rules (ADR-0084 §3) -----------------------


async def test_a_response_whose_correlation_id_does_not_match_closes(tmp_path: Path) -> None:
    """§3: "A stream that has desynchronised cannot be repaired by guessing."

    The client's own rule, kept separate from the server's so that "the one
    exception" stays true: this is "the client's obligation about a response, not
    the server's about a request, and the two never apply to the same frame".
    """

    async def _confused_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=connect.id,
                payload=env.connect_ack_payload(build="t", max_frame_bytes=_FRAME),
            ),
        )
        await _read_one(reader)
        await _send(
            writer, env.Envelope(kind=env.FrameKind.RESULT, id="some-other-id", payload=False)
        )

    async with _listening(tmp_path / "hub.sock", _confused_hub) as client:
        with pytest.raises(ProtocolError, match="outstanding"):
            await client.forget("rec-1")


async def test_a_second_request_while_one_is_outstanding_closes_the_connection(
    tmp_path: Path,
) -> None:
    """§3's one exception, and the reason it is an exception.

    "A correlated error would carry the *second* request's id, which the mismatch
    rule separately obliges the client to reject — so the refusal could never be
    consumed. A rule whose own response violates the adjacent rule is not a rule."

    Driven by writing two request frames back to back, which a conforming client
    cannot do. The assertion is that **no reply to either arrives**: a server that
    queued would answer both, and one that answered with a correlated error would
    send a frame. The connection closing with nothing on it is the ratified
    behaviour, and it is the one a queueing implementation cannot fake.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT, id="c-0", payload=env.connect_payload(client="rogue")
            ),
        )
        assert (await _read_one(reader)).kind is env.FrameKind.CONNECT_ACK
        for correlation in ("c-1", "c-2"):
            await _send(
                writer,
                env.Envelope(
                    kind=env.FrameKind.REQUEST,
                    id=correlation,
                    payload={"record_id": "rec-1"},
                    method="forget",
                ),
            )
        rest = await asyncio.wait_for(reader.read(), timeout=_PATIENT.total_seconds())
        writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert rest == b"", "the connection must close with no reply to either request"


async def test_one_request_at_a_time_on_one_connection_is_answered_normally(
    tmp_path: Path,
) -> None:
    """The discriminating half: the overlap rule refuses only an overlap.

    Two requests **in sequence** on one connection are ordinary, and a server that
    closed on the second would break every client that reused a connection. Written
    by hand for the same reason the case above is: the shipped client opens a
    connection per call, so nothing else in the suite reaches this path.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT, id="c-0", payload=env.connect_payload(client="rogue")
            ),
        )
        await _read_one(reader)
        answers = []
        for correlation in ("c-1", "c-2"):
            await _send(
                writer,
                env.Envelope(
                    kind=env.FrameKind.REQUEST,
                    id=correlation,
                    payload={"record_id": "rec-1"},
                    method="forget",
                ),
            )
            answers.append(await _read_one(reader))
        writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert [answer.id for answer in answers] == ["c-1", "c-2"]
    assert all(answer.kind is env.FrameKind.RESULT for answer in answers)


# --- what the hub refuses without answering (ADR-0084 §3) ------------------


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b"\x00\x00\x00\x04not json", "text that is not JSON"),
        ((2**32 - 1).to_bytes(PREFIX_BYTES, "big"), "a length over the ceiling"),
        (b"\x00\x00\x00\x02[]", "JSON that is not an object"),
    ],
)
async def test_an_undecodable_frame_closes_without_a_response(
    tmp_path: Path, raw: bytes, why: str
) -> None:
    """§3: "the server closes the connection without a response".

    "There is no correlation id to quote and **no agreed encoding to reply in** — a
    peer that has already violated the framing is not one to write more framed bytes
    at." The assertion is the *absence* of a reply, which is the only thing that
    distinguishes this from the typed-error path.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=1024, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        writer.write(raw)
        await writer.drain()
        rest = await asyncio.wait_for(reader.read(), timeout=_PATIENT.total_seconds())
        writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert rest == b"", why


# --- the published limit is the one the client enforces (ADR-0084 §3) ------


async def test_the_client_enforces_the_limit_it_was_told_and_not_one_of_its_own(
    tmp_path: Path,
) -> None:
    """§3: "the server's value is authoritative… the client enforces the number it
    was told".

    "A client configured at 32 MiB against a hub at 16 MiB would accept a 20 MiB
    utterance that the hub then refuses on its prefix." The hub here publishes a
    small frame size and the client, which was configured with none at all, refuses
    against exactly ``published - 512``.
    """
    published = 2048
    engine = FakeAssistantEngine(max_payload_bytes=published - ENVELOPE_RESERVE_BYTES)
    limits = ConnectionLimits(max_frame_bytes=published, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    async with _listening(tmp_path / "hub.sock", _hub) as client:
        with pytest.raises(OversizedValueError) as caught:
            await client.converse("x" * 4000, timeout=_PATIENT)
    assert caught.value.limit == published - ENVELOPE_RESERVE_BYTES
    assert caught.value.field == "utterance"


async def test_the_argument_refusal_happens_before_any_request_frame_is_written(
    tmp_path: Path,
) -> None:
    """§4: "An argument that exceeds it then fails in the client, locally… not as a
    connection that closes mid-request."

    The hub records every request it is asked to serve. A client that sent the
    oversized frame and let the hub refuse it would leave a record here; a client
    that refused locally leaves none.
    """
    seen: list[Any] = []

    async def _recording_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=connect.id,
                payload=env.connect_ack_payload(build="t", max_frame_bytes=2048),
            ),
        )
        with contextlib.suppress(Exception):
            seen.append(await _read_one(reader))

    async with _listening(tmp_path / "hub.sock", _recording_hub) as client:
        with pytest.raises(OversizedValueError):
            await client.converse("x" * 4000, timeout=_PATIENT)
    await asyncio.sleep(0)
    assert seen == [], "the request must never have been written"


async def test_an_error_frame_reconstructs_the_hub_s_own_declared_failure(
    tmp_path: Path,
) -> None:
    """The other direction of ADR-0085 §10a, end to end over a socket.

    The hub raises a real failure and the client raises the same *type* with the
    same structured state, which is the substitutability clause biting: an adapter
    that catches ``UnresolvedEvidenceError`` catches it either way.
    """

    async def _failing_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=connect.id,
                payload=env.connect_ack_payload(build="t", max_frame_bytes=_FRAME),
            ),
        )
        request = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.ERROR,
                id=request.id,
                payload={
                    "code": "UnresolvedEvidenceError",
                    "message": "two citations are gone",
                    "details": {"unresolved_ids": ["a", "b"]},
                    "reduced": False,
                },
            ),
        )

    async with _listening(tmp_path / "hub.sock", _failing_hub) as client:
        with pytest.raises(UnresolvedEvidenceError) as caught:
            await client.answer("q-1", accept=True)
    assert caught.value.unresolved_ids == ("a", "b")
    assert caught.value.details_elided is False


async def test_a_hub_that_hangs_up_mid_request_says_what_was_outstanding(
    tmp_path: Path,
) -> None:
    """§3: "A close with no response is reported as what the client was attempting
    when the connection went away."

    The distinction survives to the user because a transport failure and a declined
    request mean different things — one is "the hub said no", the other is "the hub
    stopped talking", and flattening them is what ruling 4 forbids.
    """

    async def _rude_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=connect.id,
                payload=env.connect_ack_payload(build="t", max_frame_bytes=_FRAME),
            ),
        )
        await _read_one(reader)
        writer.close()

    async with _listening(tmp_path / "hub.sock", _rude_hub) as client:
        with pytest.raises(HubUnavailableError, match="beliefs"):
            await client.beliefs()


def test_the_request_frame_carries_the_method_in_the_envelope() -> None:
    """ADR-0085 §8a: "The method name is the envelope's ``method`` member… not a
    payload member."

    Asserted on the bytes rather than through a hub, because it is a statement about
    the frame's shape: a client that put the method in the payload would still work
    against *this* server and would be unable to talk to any other.
    """
    frame = env.encode_envelope(
        env.Envelope(
            kind=env.FrameKind.REQUEST, id="c-1", payload={"record_id": "r-1"}, method="belief"
        )
    )
    decoded = json.loads(frame)
    assert decoded["method"] == "belief"
    assert decoded["payload"] == {"record_id": "r-1"}


async def test_a_value_with_no_wire_form_is_refused_before_the_socket_is_opened(
    tmp_path: Path,
) -> None:
    """ADR-0085 §9's "before any I/O", for the values ADR-0087 §2 gives no form.

    **Driven with no hub at all**, which is what makes it a test of the *ordering*
    rather than of the refusal: if the utterance were validated after ``connect``,
    this would raise ``HubUnavailableError`` instead. So the error a caller sees
    would depend on whether a hub happened to be up — a ``ValueError`` in-process, a
    transport failure over the wire — for one value both implementations must refuse
    the same way.
    """
    client = HubEngineClient(tmp_path / "hub.sock", read_timeout=_PATIENT)
    with pytest.raises(ValueError, match="UTF-8"):
        await client.converse("bad \ud800", timeout=_PATIENT)
    # An *identifier* is refused one step earlier still, by Identifier's own
    # validation (ADR-0085 §3c) rather than by the projection — a different message
    # for the same obligation, and still before anything is opened.
    with pytest.raises(ValueError, match="identifier"):
        await client.belief("bad \ud800")


async def test_a_well_formed_argument_still_reaches_the_socket(tmp_path: Path) -> None:
    """The discriminating half: the local refusal refuses only what has no form.

    Without it, a client that raised on every argument would pass the case above and
    never talk to a hub at all.
    """
    client = HubEngineClient(tmp_path / "hub.sock", read_timeout=_PATIENT)
    with pytest.raises(HubUnavailableError):
        await client.converse("perfectly ordinary", timeout=_PATIENT)


async def test_a_malformed_frame_arriving_mid_request_closes_with_no_reply(
    tmp_path: Path,
) -> None:
    """ADR-0084 §3, on the interleaving that is easy to get half right.

    A peer that writes **anything** before its reply has violated the serial rule,
    and an undecodable second frame is a violation twice over. Treating it as "no
    overlap" is worse than missing it: the malformed bytes have already been
    consumed, so the reply would be written to a peer that has already broken the
    framing — "not one to write more framed bytes at".

    The assertion is that **nothing at all** comes back. A server that answered the
    first request and then waited for another frame — the shape that swallows the
    malformed one — would send a result here.
    """
    engine = FakeAssistantEngine()
    limits = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=limits)

    path = tmp_path / "hub.sock"
    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        reader, writer = await asyncio.open_unix_connection(str(path))
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.CONNECT, id="c-0", payload=env.connect_payload(client="rogue")
            ),
        )
        assert (await _read_one(reader)).kind is env.FrameKind.CONNECT_ACK
        await _send(
            writer,
            env.Envelope(
                kind=env.FrameKind.REQUEST,
                id="c-1",
                payload={"record_id": "rec-1"},
                method="forget",
            ),
        )
        # Not a frame any decoder accepts, written before the reply could arrive.
        writer.write((8).to_bytes(PREFIX_BYTES, "big") + b"not json")
        await writer.drain()
        rest = await asyncio.wait_for(reader.read(), timeout=_PATIENT.total_seconds())
        writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert rest == b"", "the connection must close with no reply to the request either"


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ({env.ACK_VERSION: 1, env.ACK_READY: True, env.ACK_MAX_FRAME_BYTES: 1024}, "no build"),
        (
            {
                env.ACK_VERSION: 1,
                env.ACK_BUILD: "b",
                env.ACK_READY: True,
                env.ACK_MAX_FRAME_BYTES: 0,
            },
            "an impossible frame size",
        ),
        (
            {
                env.ACK_VERSION: 1,
                env.ACK_BUILD: "b",
                env.ACK_READY: True,
                env.ACK_MAX_FRAME_BYTES: 2**40,
            },
            "a frame size the prefix cannot express",
        ),
    ],
)
async def test_a_malformed_connect_reply_is_refused_rather_than_believed(
    tmp_path: Path, reply: dict[str, object], why: str
) -> None:
    """The client enforces the number it was told, so the number has to be legal.

    A reply of ``0`` would make the contract limit negative and every ordinary
    argument would come back as an ``OversizedValueError`` — a malformed handshake
    misreported as the caller's fault, which is the failure mode that makes a
    permissive reader worse than a strict one. The bounds are the ones the setting
    itself carries: ADR-0085 §8d's floor and what the 4-byte prefix can express.
    """

    async def _bad_hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await _read_one(reader)
        await _send(
            writer,
            env.Envelope(kind=env.FrameKind.CONNECT_ACK, id=connect.id, payload=reply),
        )

    async with _listening(tmp_path / "hub.sock", _bad_hub) as client:
        with pytest.raises(ProtocolError):
            await client.probe()
