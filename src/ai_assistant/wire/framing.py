"""Length-prefixed framing, with the ceilings and deadlines a resident hub needs.

ADR-0084 §3 fixes the framing as **a 4-byte big-endian unsigned length prefix
followed by that many bytes**. The prefix counts envelope and payload together,
"which also settles what ``hub_max_frame_bytes`` bounds: that same number, so the
cap is checked against the prefix before anything is read and there is one answer
to 'does the limit include the envelope'."

**A declared length is a claim, and the reader must be free to disbelieve it.**
The three rules that follow from that are all here:

* a declared length above the ceiling is **refused before a byte of payload is
  read** — a pre-envelope failure, so it takes the connection-level close rather
  than a typed error there is no correlation id to carry;
* the reader **never allocates the declared length up front**; it reads
  incrementally against the cap;
* the deadline runs **while waiting for the next frame's prefix as well as
  mid-frame**, so a peer that completes the handshake and then sends nothing is
  closed rather than holding a slot against the connection ceiling.

**The reason is robustness, not secrecy**, and ADR-0084 §3 insists on saying so:
the ``0600`` bit already scopes a peer to the owning user, so this is not a defence
against a hostile stranger. It is a defence against the thing ADR-0083 is entirely
about — a *resident* process. "A one-shot CLI could shrug this off; a process that
runs for weeks cannot."
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from ai_assistant.wire.errors import (
    ConnectionClosedError,
    ProtocolError,
    UndecodableFrameError,
)

if TYPE_CHECKING:
    from datetime import timedelta

#: ADR-0084 §3's prefix: four bytes, big-endian, unsigned.
PREFIX_BYTES: Final[int] = 4

#: How much of a frame is read at once. The declared length is **not** allocated
#: up front; this is the step the reader takes towards it, so the memory a peer can
#: cause to be reserved before its claim has been believed is this and not its
#: claim. A frame at the 16 MiB default is 256 of these.
_CHUNK_BYTES: Final[int] = 64 * 1024


async def read_frame(
    reader: asyncio.StreamReader,
    *,
    max_frame_bytes: int,
    timeout: timedelta,  # noqa: ASYNC109 - a transport read deadline, not a caller's budget
    idle_timeout: timedelta | None,
) -> bytes:
    """Read one frame's bytes, without the prefix.

    **The two deadlines are separate, and the split is what makes the rule usable
    on both sides.** ADR-0084 §3 requires the deadline to run "while **waiting for
    the next frame's prefix**, not only mid-frame, so a peer that completes the
    handshake and then sends nothing is closed rather than holding a slot against
    the connection ceiling" — that is ``idle_timeout``, and the hub sets it.

    A *client* waiting for a response is a different situation and must not take
    the same bound: the reply's latency is the call's own — ``converse`` and
    ``resume`` carry a ``timeout`` argument that may exceed any transport figure,
    and a page over a large store takes what it takes. A client that gave up while
    the hub was still working would report a transport failure for a turn that is
    running, and would then be unable to say what became of it. So the client
    passes ``idle_timeout=None`` for a response and keeps ``timeout`` for the
    frame's own body, which is where a genuine stall shows.

    Args:
        reader: The connection to read from.
        max_frame_bytes: The ceiling a declared length is judged against.
        timeout: How long the frame's body may take once its prefix has arrived.
        idle_timeout: How long to wait for that prefix, or ``None`` to wait as long
            as the caller is willing to.

    Returns:
        The frame's bytes.

    Raises:
        ConnectionClosedError: If the peer closed cleanly between frames. Not a
            violation — it is how a stateless client finishes.
        UndecodableFrameError: If the declared length exceeds the ceiling, the
            frame is truncated, or a deadline expires. All three are members of
            ADR-0084 §3's closed undecodable class, whose answer is a close with no
            response.
    """
    idle = None if idle_timeout is None else idle_timeout.total_seconds()
    try:
        async with asyncio.timeout(idle):
            prefix = await _read_exactly(reader, PREFIX_BYTES, at_start=True)
    except TimeoutError as exc:
        msg = (
            f"a peer sent nothing for {idle:g}s while a frame was expected; the connection "
            f"is closed rather than held open against the connection ceiling"
        )
        raise UndecodableFrameError(msg) from exc

    length = int.from_bytes(prefix, "big")
    if length > max_frame_bytes:
        msg = (
            f"a frame declares {length} bytes, over the {max_frame_bytes}-byte "
            f"ceiling; refused before a byte of it was read"
        )
        raise UndecodableFrameError(msg)
    try:
        async with asyncio.timeout(timeout.total_seconds()):
            return await _read_exactly(reader, length, at_start=False)
    except TimeoutError as exc:
        msg = (
            f"a peer stopped sending part-way through a {length}-byte frame and did not "
            f"resume within {timeout.total_seconds():g}s"
        )
        raise UndecodableFrameError(msg) from exc


async def _read_exactly(reader: asyncio.StreamReader, count: int, *, at_start: bool) -> bytes:
    """Read exactly ``count`` bytes, in bounded steps.

    Args:
        reader: The connection to read from.
        count: How many bytes the frame declares.
        at_start: Whether nothing of this frame has been read yet, which is what
            distinguishes a clean close from a truncation.

    Returns:
        The bytes.

    **A reset is treated exactly as an end of file**, and that is a decision rather
    than laziness. A peer that closed with unread bytes still queued reaches this as
    ``ConnectionResetError`` rather than as an empty read — the same event from the
    kernel's point of view and a different exception from Python's — and the
    listener's own ceiling refusal is one of the paths that produces it. Letting the
    raw ``OSError`` escape would hand a caller an exception outside this package's
    vocabulary for the ordinary case of a peer hanging up.

    Raises:
        ConnectionClosedError: On a clean close before any of the frame arrived.
        UndecodableFrameError: On a close part-way through one.
    """
    buffer = bytearray()
    while len(buffer) < count:
        try:
            chunk = await reader.read(min(_CHUNK_BYTES, count - len(buffer)))
        except OSError:
            chunk = b""
        if not chunk:
            if at_start and not buffer:
                msg = "the peer closed the connection"
                raise ConnectionClosedError(msg)
            msg = f"a frame declared {count} bytes and the connection carried {len(buffer)}"
            raise UndecodableFrameError(msg)
        buffer.extend(chunk)
    return bytes(buffer)


async def write_frame(writer: asyncio.StreamWriter, body: bytes, *, max_frame_bytes: int) -> None:
    """Write one frame, prefix and body.

    Args:
        writer: The connection to write to.
        body: The frame's bytes, without the prefix.
        max_frame_bytes: The ceiling the frame must fit inside.

    Raises:
        ProtocolError: If the frame exceeds the ceiling. Reaching this is a bug on
            *this* side rather than a peer's fault — the contract limit is the
            frame size less ADR-0085 §8b's 512-byte envelope reserve, so a payload
            the contract admitted cannot overflow a frame — and writing it anyway
            would put a length on the wire the peer must refuse.
        ConnectionClosedError: If the peer has gone away.
    """
    if len(body) > max_frame_bytes:
        msg = (
            f"refusing to write a {len(body)}-byte frame, over the {max_frame_bytes}-byte "
            f"ceiling; the envelope reserve is meant to make this unreachable"
        )
        raise ProtocolError(msg)
    try:
        writer.write(len(body).to_bytes(PREFIX_BYTES, "big") + body)
        await writer.drain()
    except (ConnectionError, BrokenPipeError) as exc:
        msg = "the connection went away before the frame could be written"
        raise ConnectionClosedError(msg) from exc
