"""The framing's three refusals, and the two deadlines that are not one.

ADR-0084 §3: "A declared length is a claim, and the reader must be free to
disbelieve it." Each clause it states is asserted here against a real
:class:`asyncio.StreamReader` fed real bytes, because every one of them is about
what happens when a peer lies or stops — which a fake reader would have to be told
to do rather than being able to do.
"""

from __future__ import annotations

import asyncio
import socket
from datetime import timedelta

import pytest

from ai_assistant.wire.errors import (
    ConnectionClosedError,
    ProtocolError,
    UndecodableFrameError,
)
from ai_assistant.wire.framing import PREFIX_BYTES, read_frame, write_frame

_PATIENT = timedelta(seconds=5)
_BRIEF = timedelta(milliseconds=50)


def _reader(*chunks: bytes, close: bool = True) -> asyncio.StreamReader:
    """A reader holding exactly these bytes, optionally at EOF afterwards."""
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if close:
        reader.feed_eof()
    return reader


def _framed(body: bytes) -> bytes:
    """One well-formed frame."""
    return len(body).to_bytes(PREFIX_BYTES, "big") + body


async def test_a_frame_round_trips_through_its_own_prefix() -> None:
    """The ordinary case, which every refusal below is a departure from."""
    body = b'{"kind":"request"}'
    read = await read_frame(
        _reader(_framed(body)), max_frame_bytes=1024, timeout=_PATIENT, idle_timeout=_PATIENT
    )
    assert read == body


async def test_a_frame_arriving_in_pieces_is_still_one_frame() -> None:
    """The reader is incremental, so a body split across writes reassembles.

    Worth asserting rather than assuming: a socket splits wherever it likes, and a
    reader that assumed one ``read`` returned a whole frame would work on every
    small payload and fail on the large ones ADR-0084 §4 is entirely about.
    """
    body = b"x" * 5000
    read = await read_frame(
        _reader(_framed(body)[:3], _framed(body)[3:2000], _framed(body)[2000:]),
        max_frame_bytes=1 << 20,
        timeout=_PATIENT,
        idle_timeout=_PATIENT,
    )
    assert read == body


async def test_a_declared_length_over_the_ceiling_is_refused_before_the_body() -> None:
    """§3: "refused **before a byte of payload is read**".

    The reader is given a prefix claiming 4 GiB and **no body at all**. If the
    ceiling were checked after reading, this would hang or fail on truncation; it
    fails on the claim, which is the property that keeps a resident hub from
    allocating against a lie.
    """
    with pytest.raises(UndecodableFrameError, match="ceiling"):
        await read_frame(
            _reader((2**32 - 1).to_bytes(PREFIX_BYTES, "big"), close=False),
            max_frame_bytes=1024,
            timeout=_PATIENT,
            idle_timeout=_PATIENT,
        )


async def test_a_clean_close_between_frames_is_not_a_violation() -> None:
    """A stateless client finishing is the commonest thing the hub sees.

    Distinguished from a truncation because the two mean opposite things: one is
    the protocol working, the other is a peer that stopped mid-claim.
    """
    with pytest.raises(ConnectionClosedError):
        await read_frame(_reader(), max_frame_bytes=1024, timeout=_PATIENT, idle_timeout=_PATIENT)


async def test_a_frame_that_stops_part_way_is_a_violation_rather_than_a_close() -> None:
    """The other side of the same distinction."""
    with pytest.raises(UndecodableFrameError, match="declared"):
        await read_frame(
            _reader((100).to_bytes(PREFIX_BYTES, "big"), b"only ten b"),
            max_frame_bytes=1024,
            timeout=_PATIENT,
            idle_timeout=_PATIENT,
        )


async def test_a_peer_that_sends_nothing_is_closed_on_the_idle_deadline() -> None:
    """§3: the deadline runs "while **waiting for the next frame's prefix**".

    Without it "a peer that completes the handshake and then sends nothing" holds a
    slot against the connection ceiling indefinitely — the cheapest state for a
    misbehaving peer to accumulate against a process that runs for weeks.
    """
    with pytest.raises(UndecodableFrameError, match="sent nothing"):
        await read_frame(
            _reader(close=False), max_frame_bytes=1024, timeout=_PATIENT, idle_timeout=_BRIEF
        )


async def test_a_peer_that_stalls_mid_frame_is_closed_on_the_body_deadline() -> None:
    """§3: "a frame that stalls part-way is abandoned on a read deadline"."""
    with pytest.raises(UndecodableFrameError, match="part-way"):
        await read_frame(
            _reader((100).to_bytes(PREFIX_BYTES, "big"), b"half", close=False),
            max_frame_bytes=1024,
            timeout=_BRIEF,
            idle_timeout=_PATIENT,
        )


async def test_no_idle_deadline_means_a_reader_waits_for_a_slow_reply() -> None:
    """The client's side of the split, and the reason the two deadlines are two.

    A ``converse`` may legitimately take longer than ``hub_read_timeout``; a client
    that applied the transport's idle bound to the *reply* would report a transport
    failure for a turn that is still running and then be unable to say what became
    of it. Driven with a reply that arrives after the brief deadline would have
    expired, so a single-deadline implementation fails here.
    """
    reader = asyncio.StreamReader()

    async def _late() -> None:
        await asyncio.sleep(_BRIEF.total_seconds() * 3)
        reader.feed_data(_framed(b"late"))

    task = asyncio.ensure_future(_late())
    read = await read_frame(reader, max_frame_bytes=1024, timeout=_PATIENT, idle_timeout=None)
    await task
    assert read == b"late"


async def test_writing_a_frame_over_the_ceiling_is_refused_on_this_side() -> None:
    """The envelope reserve is meant to make this unreachable, so it is a bug here.

    Refusing rather than writing is what stops one side putting a length on the wire
    the other must refuse — which would turn a local mistake into a closed
    connection the peer has to diagnose.
    """
    _, writer = await _pair()
    with pytest.raises(ProtocolError, match="refusing to write"):
        await write_frame(writer, b"x" * 100, max_frame_bytes=10)
    writer.close()


async def _pair() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A connected reader/writer pair over a real socket."""
    left, right = socket.socketpair()
    reader, writer = await asyncio.open_connection(sock=left)
    right.close()
    return reader, writer
