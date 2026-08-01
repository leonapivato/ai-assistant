"""The server half: one connection, driven against an ``AssistantEngine``.

The *listener* is the hub's (:mod:`ai_assistant.service.transport`) — where to
bind, when to start accepting, how many connections to hold — because those are
deployment facts and ADR-0083 §8 owns them. What lives here is the protocol
itself, which is the same on both sides of the socket and depends on ``core``
alone: the handshake, the frame loop, the dispatch onto the fifteen methods, and
the mapping from a declared failure to an error frame.

**Two classes of failure, and the boundary is the envelope** (ADR-0084 §3):

* **If no envelope decodes, the connection is closed without a response.** There
  is no correlation id to quote and "**no agreed encoding to reply in** — a peer
  that has already violated the framing is not one to write more framed bytes at".
* **A frame that decodes gets a typed error** — the handshake's own refusals, and
  the ordinary correlated failures of a call.

**The one exception is a second request arriving while one is outstanding**, which
closes. A correlated error would carry the *second* request's id, "which the
mismatch rule separately obliges the client to reject — so the refusal could never
be consumed. A rule whose own response violates the adjacent rule is not a rule."
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.errors import AssistantError
from ai_assistant.wire import envelope as env
from ai_assistant.wire.codec import ENVELOPE_RESERVE_BYTES
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    ProtocolError,
    UndecodableFrameError,
    error_payload,
)
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.surface import METHODS, argument_adapter, parameters

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from ai_assistant.core.protocols import AssistantEngine

_log = structlog.get_logger(__name__)

#: How many turns of the event loop the overlap watcher is given to observe a frame
#: that is already buffered (:func:`_settle`). **One is enough today** — measured:
#: with zero the refusal is missed, with one it fires — and three is headroom for a
#: watcher path that grows a suspension point, which is free because the loop stops
#: the moment the watcher settles. Zero is the case the tests pin, so a change that
#: removed the yielding would fail rather than become intermittent.
_SETTLE_TURNS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ConnectionLimits:
    """What a served connection is held to (ADR-0084 §3).

    Grouped rather than passed one by one because they travel together everywhere:
    the listener reads all three from ``Settings``, and every function below needs
    the frame ceiling and the deadline in the same breath. It also keeps
    :attr:`payload_limit` derived in one place, so no caller can subtract the
    envelope reserve differently.

    Attributes:
        max_frame_bytes: The hub's effective frame ceiling — what the length prefix
            counts, envelope and payload together.
        read_timeout: How long a peer may stall, mid-frame or between frames.
        build: This build's identifier, published in the connect reply.
    """

    max_frame_bytes: int
    read_timeout: timedelta
    build: str

    @property
    def payload_limit(self) -> int:
        """The contract limit: the frame ceiling less ADR-0085 §8b's reserve."""
        return self.max_frame_bytes - ENVELOPE_RESERVE_BYTES


async def serve_connection(
    engine: AssistantEngine,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    limits: ConnectionLimits,
    on_handshake: Callable[[], None] | None = None,
) -> None:
    """Drive one accepted connection to its end.

    Returns normally on every ordinary ending — a client that hung up, a peer that
    broke the protocol, a deadline that expired — because none of those is the
    *hub's* failure and a resident process must not treat a misbehaving spoke as a
    fault of its own (ADR-0084 §3's "the reason is robustness, not secrecy").

    Args:
        engine: The in-process engine this hub owns.
        reader: The connection's reader.
        writer: The connection's writer.
        limits: The frame ceiling, the deadline and the build identifier.
        on_handshake: Called once the handshake completes, so a listener can move
            this connection off its *pending* ceiling and onto its total. The
            listener owns both figures (ADR-0084 §3) and the handshake happens
            here, so one of the two has to tell the other.
    """
    try:
        if not await _handshake(reader, writer, limits=limits):
            return
        if on_handshake is not None:
            on_handshake()
        await _serve_requests(engine, reader, writer, limits=limits)
    except (ConnectionClosedError, UndecodableFrameError, ProtocolError) as exc:
        _log.info("hub_connection_closed", reason=str(exc), error_class=type(exc).__name__)
    except asyncio.CancelledError:
        raise
    except Exception:
        # One connection's fault must never be the resident process's. The engine
        # declares its failures and they are answered above as error frames; what
        # reaches here is an undeclared one — including the ``RuntimeError`` a
        # shutting-down engine raises, which a client is not meant to observe
        # (ADR-0085 §1) and which ADR-0084 §1 answers by having already unlinked
        # the socket.
        _log.exception("hub_connection_failed")
    finally:
        await _hang_up(writer)


async def _handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, limits: ConnectionLimits
) -> bool:
    """Run ADR-0084 §2's one-frame-each connect exchange.

    Returns:
        Whether the connection may go on to carry requests.

    Raises:
        UndecodableFrameError: If the connect frame does not decode, which closes.
    """
    body = await read_frame(
        reader,
        max_frame_bytes=limits.max_frame_bytes,
        timeout=limits.read_timeout,
        idle_timeout=limits.read_timeout,
    )
    frame = env.decode_envelope(body)
    if frame.kind is not env.FrameKind.CONNECT:
        msg = f"a connection opened with a {frame.kind.value} frame rather than a connect"
        raise UndecodableFrameError(msg)

    try:
        version, client = env.read_connect(frame.payload)
    except ProtocolError as exc:
        # §2's credential refusal: "a version mismatch and a non-empty credential
        # are members of an envelope that parsed, so they are reported properly and
        # only then does the connection close."
        await _refuse(
            writer,
            frame.id,
            code=env.CREDENTIAL_NOT_SUPPORTED,
            message=str(exc),
            limits=limits,
        )
        return False

    if version != env.PROTOCOL_VERSION:
        await _refuse(
            writer,
            frame.id,
            code=env.VERSION_MISMATCH,
            message=(
                f"this hub speaks protocol version {env.PROTOCOL_VERSION} and the client "
                f"speaks version {version}; the two halves are installed and upgraded "
                f"together, so finish the upgrade and restart both"
            ),
            limits=limits,
        )
        return False

    await write_frame(
        writer,
        env.encode_envelope(
            env.Envelope(
                kind=env.FrameKind.CONNECT_ACK,
                id=frame.id,
                payload=env.connect_ack_payload(
                    build=limits.build, max_frame_bytes=limits.max_frame_bytes
                ),
            )
        ),
        max_frame_bytes=limits.max_frame_bytes,
    )
    _log.debug("hub_client_connected", client=client, protocol_version=version)
    return True


async def _serve_requests(
    engine: AssistantEngine,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    limits: ConnectionLimits,
) -> None:
    """Read requests one at a time, and refuse a second one that overlaps.

    **The overlap check is why the next frame is read concurrently rather than
    after the reply.** Serving sequentially would *queue* a second request, which
    ADR-0084 §3 forbids in as many words — "not queued, not run concurrently" — and
    a server that queued would look conforming while giving a buggy client a
    concurrency the engine does not offer.

    The watcher runs with **no idle deadline**, because the hub is not idle while a
    request is in flight: a ``converse`` may legitimately take longer than
    ``hub_read_timeout``, and closing a working connection because the reply was
    slow would be the deadline defeating the purpose it was added for. The idle
    deadline applies where the hub genuinely is idle — waiting for the *first*
    frame of the next request.
    """
    while True:
        try:
            frame = await _read_request(reader, limits=limits, idle=limits.read_timeout)
        except ConnectionClosedError:
            return

        watcher = asyncio.ensure_future(_read_request(reader, limits=limits, idle=None))
        try:
            reply = await _dispatch(engine, frame, limit=limits.payload_limit)
        finally:
            overlapped = await _settle(watcher)
        if overlapped:
            msg = (
                "a second request arrived while one was outstanding; this connection is "
                "serial, and a correlated error would carry an id the client must itself "
                "reject, so the connection is closed instead"
            )
            raise ProtocolError(msg)
        await write_frame(
            writer, env.encode_envelope(reply), max_frame_bytes=limits.max_frame_bytes
        )


async def _settle(watcher: asyncio.Future[env.Envelope]) -> bool:
    """Stop watching for an overlapping request, and say whether one arrived.

    A watcher that is still running has seen nothing, and cancelling it can only
    discard bytes a conforming client could not have sent — it may write again only
    after the reply, and the reply has not been written yet.

    **The loop of bare yields is what makes the observation deterministic**, and it
    is not a sleep in disguise. A client that pipelined two requests writes both
    before the first reply, so by the time the dispatch returns the second frame is
    already in the reader's buffer — but the watcher only *sees* it once the event
    loop has given it a turn, and a dispatched call that never suspends (a
    ``forget`` that misses, say) returns without the loop ever running. Without
    these turns the refusal would fire or not depending on whether the method
    happened to await, which is a property of the method rather than of the
    protocol. Yielding until the watcher settles is the same idiom the conformance
    suite uses to put a mutation inside the window ADR-0065 protects.

    Returns:
        Whether a second request frame arrived while one was outstanding.
    """
    for _ in range(_SETTLE_TURNS):
        if watcher.done():
            break
        await asyncio.sleep(0)
    if not watcher.done():
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher
        return False
    if watcher.cancelled():  # pragma: no cover — nothing else cancels this future
        return False
    # A peer that hung up, or sent something undecodable, while a request was in
    # flight is not an *overlap*; the next loop iteration reports it as itself.
    return watcher.exception() is None


async def _read_request(
    reader: asyncio.StreamReader, *, limits: ConnectionLimits, idle: timedelta | None
) -> env.Envelope:
    """Read one frame and require it to be a request."""
    body = await read_frame(
        reader,
        max_frame_bytes=limits.max_frame_bytes,
        timeout=limits.read_timeout,
        idle_timeout=idle,
    )
    frame = env.decode_envelope(body)
    if frame.kind is not env.FrameKind.REQUEST:
        msg = f"a served connection carried a {frame.kind.value} frame where a request belongs"
        raise UndecodableFrameError(msg)
    return frame


async def _dispatch(engine: AssistantEngine, frame: env.Envelope, *, limit: int) -> env.Envelope:
    """Run one request against the engine and render its answer as a frame.

    Args:
        engine: The engine to call.
        frame: The request.
        limit: The contract limit an error payload must fit inside.

    Returns:
        The result or error frame to write back.

    Raises:
        UndecodableFrameError: If the request names no known method or carries
            arguments the surface does not declare. **Closing rather than replying
            is deliberate**: ADR-0085 §10a fixes the wire's error vocabulary as
            "exactly the ``AssistantError`` subtree", so there is no ratified code
            for "no such method", and inventing one would be this lane authoring
            contract surface it may not author. The two halves ship together
            (ADR-0084 §3), so a request naming a method this build does not have is
            a bug rather than a version to tolerate.
    """
    method = frame.method
    if method is None or method not in METHODS:
        msg = f"a request names {method!r}, which this build's engine surface does not declare"
        raise UndecodableFrameError(msg)
    arguments = _decode_arguments(method, frame.payload)
    try:
        result = await getattr(engine, method)(**arguments)
    except AssistantError as exc:
        return env.Envelope(
            kind=env.FrameKind.ERROR,
            id=frame.id,
            payload=error_payload(exc, max_bytes=limit),
        )
    return env.Envelope(kind=env.FrameKind.RESULT, id=frame.id, payload=result)


def _decode_arguments(method: str, payload: object) -> dict[str, Any]:
    """Validate a request's argument object into the method's declared types.

    ADR-0087 §7's order, on the receiving side: **decode, then validate, then
    measure**. The engine measures — it enforces the contract limit itself, in both
    directions (ADR-0084 §4) — so what this owes is the validation that must
    precede it, "because a value with no canonical form must not reach the
    measurement step".

    **An argument the client did not send is absent, not ``null``** (ADR-0085 §10),
    so it simply does not appear here and the engine applies its own declared
    default — which is why the page-size default is a contract clause rather than a
    signature detail.

    Args:
        method: The method being called.
        payload: The request payload, as decoded.

    Returns:
        The keyword arguments to call the engine with.

    Raises:
        UndecodableFrameError: If the payload is not an object, names an argument
            the method does not declare, or carries a value its declared type
            refuses. The last of those is a client that failed to refuse locally
            what ADR-0085 §9 obliges it to refuse locally, which is a bug on that
            side rather than a request to answer.
    """
    if not isinstance(payload, dict):
        msg = f"a request payload must be an object, got {type(payload).__name__}"
        raise UndecodableFrameError(msg)
    declared = set(parameters(method))
    unknown = sorted(set(payload) - declared)
    if unknown:
        msg = f"a request to {method}() names arguments it does not declare: {unknown}"
        raise UndecodableFrameError(msg)
    decoded: dict[str, Any] = {}
    for name, value in payload.items():
        try:
            decoded[name] = argument_adapter(method, name).validate_python(value)
        except Exception as exc:
            msg = f"a request to {method}() carries a {name!r} its declared type refuses: {exc}"
            raise UndecodableFrameError(msg) from exc
    return decoded


async def _refuse(
    writer: asyncio.StreamWriter,
    correlation: str,
    *,
    code: str,
    message: str,
    limits: ConnectionLimits,
) -> None:
    """Report a handshake refusal properly, and only then close.

    "Ruling 4 would be poorly served by a silent close on a version mismatch, and
    it does not get one."
    """
    await write_frame(
        writer,
        env.encode_envelope(
            env.Envelope(
                kind=env.FrameKind.ERROR,
                id=correlation,
                payload={"code": code, "message": message, "details": None, "reduced": False},
            )
        ),
        max_frame_bytes=limits.max_frame_bytes,
    )
    _log.info("hub_connection_refused", reason=code)


async def _hang_up(writer: asyncio.StreamWriter) -> None:
    """Close one connection, tolerating a peer that has already gone."""
    writer.close()
    with contextlib.suppress(ConnectionError, OSError, asyncio.CancelledError):
        await writer.wait_closed()
