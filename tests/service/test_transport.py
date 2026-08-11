"""The listener: the ordering that keeps the lock the instance guard, and the ceilings.

The protocol is tested in ``tests/wire``. What is here is everything that is a fact
about *this deployment* — when the door opens, when it closes, what mode it carries,
and what happens beyond a ceiling — because those are the parts ADR-0083 owns and
the parts a resident process lives or dies by.
"""

from __future__ import annotations

import asyncio
import contextlib
import stat
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.service.transport import Listener
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import HubEngineClient
from ai_assistant.wire.address import SOCKET_FILENAME, socket_path
from ai_assistant.wire.envelope import (
    Envelope,
    FrameKind,
    connect_payload,
    decode_envelope,
    encode_envelope,
)
from ai_assistant.wire.errors import HubUnavailableError
from ai_assistant.wire.framing import read_frame, write_frame

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_PATIENT = timedelta(seconds=5)
_FRAME = 1 << 20


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """Settings pointed at a temporary data directory."""
    return Settings(data_dir=tmp_path, hub_read_timeout=_PATIENT, **overrides)  # type: ignore[arg-type]


@contextlib.asynccontextmanager
async def _listening(tmp_path: Path, **overrides: object) -> AsyncIterator[Listener]:
    """One listener, started and stopped around the body."""
    listener = Listener(FakeAssistantEngine(), _settings(tmp_path, **overrides), data_dir=tmp_path)
    await listener.start(build="test")
    try:
        yield listener
    finally:
        await listener.stop_accepting()
        await listener.aclose()


async def test_the_socket_is_created_owner_only(tmp_path: Path) -> None:
    """ADR-0084 §1: ``0600``, which is what makes a Unix socket reuse a ratified
    access control where a TCP loopback port has none.

    The mode is asserted on the *file* the listener actually bound, not on the
    constant: a bind that ran under a permissive umask and forgot the ``chmod``
    would satisfy the constant and leave the socket connectable by any local user.
    """
    async with _listening(tmp_path):
        mode = stat.S_IMODE((tmp_path / SOCKET_FILENAME).stat().st_mode)
    assert mode == 0o600


async def test_a_stale_socket_is_replaced_rather_than_refused(tmp_path: Path) -> None:
    """ADR-0084 §1: "a stale ``hub.sock`` survives a ``SIGKILL``".

    Binding over it requires unlinking first, "which is only safe because ADR-0083
    §1's exclusive ``flock`` is already held by then, and a held lock always means a
    live holder". The ordering is the hub's (``_start_and_run`` takes the lock at
    step 2 and starts the listener at step 6); what this asserts is that the
    listener does the unlink at all, since a hub that refused to start after a crash
    would need a human to delete a file.
    """
    stale = socket_path(tmp_path)
    stale.write_bytes(b"")
    async with _listening(tmp_path) as listener:
        assert listener.path.exists()
        client = HubEngineClient(listener.path, read_timeout=_PATIENT)
        await client.probe()


async def test_the_socket_is_unlinked_at_the_start_of_the_drain(tmp_path: Path) -> None:
    """ADR-0084 §1: unlinked "at the **start of phase A**", not at the end.

    "It makes 'draining' indistinguishable from 'not running' to a *new* client,
    which is the correct answer — a new request cannot be served either way, and
    ruling 4's legibility is served by one clear message rather than by a connection
    that hangs for the length of an unbounded phase B."

    So the assertion is not merely that the file goes: it is that a client arriving
    afterwards gets the *instruction*, which is what a hanging connection would not
    give it.
    """
    listener = Listener(FakeAssistantEngine(), _settings(tmp_path), data_dir=tmp_path)
    await listener.start(build="test")
    client = HubEngineClient(listener.path, read_timeout=_PATIENT)
    await client.probe()

    await listener.stop_accepting()
    assert not listener.path.exists()
    with pytest.raises(HubUnavailableError, match="ai-assistant-hub"):
        await client.probe()
    await listener.aclose()


async def test_beyond_the_connection_ceiling_the_listener_refuses(tmp_path: Path) -> None:
    """ADR-0084 §3: "the listener **refuses rather than queueing without bound**".

    "So the client reads a refusal instead of waiting on something it cannot tell
    apart from a hung hub (ruling 4, again)." The ceiling is set to one and two
    clients are driven concurrently: the first is served, and the second reads a
    closed connection rather than blocking until the first finishes.

    Without a ceiling "a client in a crash loop — or a script that forgot to close —
    exhausts descriptors and reader tasks while every individual connection is still
    inside its deadline".
    """
    # **A ceiling of one is no longer expressible**, and that is ADR-0131 §5a's
    # consequence rather than this case drifting: `hub_max_delivery_connections`
    # is refused at load unless it is at least 1 *and* strictly below
    # `hub_max_connections`, so a hub serving delivery needs at least two slots —
    # which is the sub-bound's whole point, a slot for a poller and a slot for the
    # owner's CLI. The ceiling is therefore two here and two connections are held.
    async with _listening(
        tmp_path,
        hub_max_connections=2,
        hub_max_pending_handshakes=2,
        hub_max_delivery_connections=1,
    ) as hub:
        first_reader, first_writer = await asyncio.open_unix_connection(str(hub.path))
        second_reader, second_writer = await asyncio.open_unix_connection(str(hub.path))
        try:
            # Neither held connection has handshaken, so both occupy slots.
            await asyncio.sleep(0)
            third = HubEngineClient(hub.path, read_timeout=_PATIENT)
            with pytest.raises(HubUnavailableError):
                await third.probe()
        finally:
            for writer in (first_writer, second_writer):
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            del first_reader, second_reader


async def test_inside_the_ceiling_a_client_is_served(tmp_path: Path) -> None:
    """The discriminating half: a ceiling that refused everything would pass above.

    Driven at the ceiling rather than well inside it, so an off-by-one that refused
    the last permitted connection would fail here.
    """
    async with _listening(
        tmp_path,
        hub_max_connections=2,
        hub_max_pending_handshakes=2,
        hub_max_delivery_connections=1,
    ) as hub:
        # One slot held, so the client below takes the *last* one — which is what
        # keeps this "at the ceiling" now that ADR-0131 §5a makes a ceiling of one
        # unexpressible for a hub that serves delivery.
        held_reader, held_writer = await asyncio.open_unix_connection(str(hub.path))
        try:
            await asyncio.sleep(0)
            client = HubEngineClient(hub.path, read_timeout=_PATIENT)
            assert await client.beliefs() == ()
            assert await client.forget("nothing") is False
        finally:
            held_writer.close()
            with contextlib.suppress(Exception):
                await held_writer.wait_closed()
            del held_reader


async def test_a_handshaken_connection_frees_the_pending_slot(tmp_path: Path) -> None:
    """ADR-0084 §3's two ceilings are two, and the lower one is about the handshake.

    "A connection that has not completed the handshake has cost the hub a descriptor
    and a task while telling it nothing, which is the cheapest state for a
    misbehaving peer to accumulate." A connection that *has* handshaken is an
    identified client and must stop counting against the tighter budget — otherwise
    the pending ceiling would silently become the connection ceiling, and a hub
    configured with 64 connections and 8 pending would serve 8.

    The pair with the ceiling test above is what makes this a property rather than a
    coincidence: there, one **un**-handshaken connection at ``pending=1`` refuses the
    next client; here, one **handshaken** connection at the same ceiling does not.
    Same ceiling, same held connection, opposite answers, and the handshake is the
    only difference.
    """
    async with _listening(
        tmp_path,
        hub_max_connections=8,
        hub_max_pending_handshakes=1,
        hub_max_delivery_connections=4,
    ) as hub:
        reader, writer = await asyncio.open_unix_connection(str(hub.path))
        try:
            await write_frame(
                writer,
                encode_envelope(
                    Envelope(
                        kind=FrameKind.CONNECT, id="c-0", payload=connect_payload(client="held")
                    )
                ),
                max_frame_bytes=_FRAME,
            )
            body = await read_frame(
                reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
            )
            assert decode_envelope(body).kind is FrameKind.CONNECT_ACK
            # The reply is written inside the handshake, so the listener's own
            # bookkeeping runs on the next turn of the loop rather than before the
            # client can observe the ack.
            await asyncio.sleep(0)

            client = HubEngineClient(hub.path, read_timeout=_PATIENT)
            assert await client.beliefs() == ()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            del reader


async def test_the_listener_lets_go_of_a_connection_nobody_closed(tmp_path: Path) -> None:
    """A hub that has drained must not stay alive for a spoke that forgot to hang up.

    The *engine* calls a connection made are tracked work ADR-0083 §4's phases own;
    what is left after the drain is a connection whose peer has neither hung up nor
    sent anything. Cancelling those is the difference between a clean exit and a
    process that looks wedged.
    """
    listener = Listener(FakeAssistantEngine(), _settings(tmp_path), data_dir=tmp_path)
    await listener.start(build="test")
    reader, writer = await asyncio.open_unix_connection(str(listener.path))
    await asyncio.sleep(0)
    await listener.stop_accepting()
    await asyncio.wait_for(listener.aclose(), timeout=_PATIENT.total_seconds())
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    del reader
