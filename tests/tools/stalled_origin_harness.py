"""A real origin that accepts a connection and then never speaks (#2207).

**Nothing here is a double.** ADR-0241 §12's Arm 1 asks for "a stub origin that
connects and never answers", and the in-tree arm met it with a substituted
``OutboundTransport`` — which is how a defect in the one component whose behaviour
decides the property passed every check this project runs. The QA run that found it
drove a few lines of ``asyncio`` bound on the loopback interface, and this is those
lines, so that a case can drive the production
:class:`~ai_assistant.tools.egress.StreamOutboundTransport` against the arrangement
the defect was measured in.

**The stall is in the TLS handshake, and no certificate is needed to arrange one.**
The server accepts the TCP connection and reads nothing and writes nothing, so a
client under implicit TLS sends its ``ClientHello`` and waits for a ``ServerHello``
that never comes — which is exactly what #2207's origin logged ("peer sent 1523
bytes at 0.000s", then silence until the peer gave up at 60.004 s). Completing the
handshake and stalling after it would need a trust anchor the client's default
context would accept, and would exercise the response read, which is a stage no
shield ever covered.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.types import TransportEndpoint

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: The loopback name, so nothing here leaves the machine and no resolver is asked
#: about anything a network could answer.
#:
#: **A name rather than a literal, because the searcher refuses a literal.** The
#: origin a connected account carries is canonicalised at the seam, and "an HTTPS
#: host whose rightmost label is a number is an IP literal and is refused"
#: (ADR-0231 §8, ``tools/destinations``) — which is why #2207's QA origin was
#: ``127-0-0-1.nip.io``. ``localhost`` is the one name that resolves to the
#: loopback interface without a resolver leaving the machine, so the transport
#: arms and the servicing arm can name one place.
HOST: Final = "localhost"


@final
@dataclass(slots=True)
class StalledOrigin:
    """A listening socket that answers nothing, and the ways to name it.

    Attributes:
        endpoint: What ``open_channel`` is handed, under implicit TLS so the stall
            lands in the handshake rather than in a read.
        origin: The same place as the origin string a connected search account is
            configured with, for the arm that drives the whole servicing path.
        accepted: Set the first time the far end accepts a connection, so a case
            can wait until its arrangement has actually reached the handshake
            instead of asserting against an open that never left the resolver.
        connections: How many connections were accepted, so a case can say that
            the origin was reached exactly once.
    """

    endpoint: TransportEndpoint
    origin: str
    accepted: asyncio.Event = field(default_factory=asyncio.Event)
    connections: int = 0


@asynccontextmanager
async def stalled_origin() -> AsyncIterator[StalledOrigin]:
    """Bind a silent origin on the loopback interface for the life of the block.

    Yields:
        The origin, already listening on a port the operating system chose.
    """
    stop = asyncio.Event()
    origin: StalledOrigin | None = None

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Accept, say nothing, and give the socket back when the block ends.

        Args:
            reader: The read half, deliberately never read from — a server that
                consumed the ``ClientHello`` would still not answer it, and not
                reading is the smaller arrangement.
            writer: The write half, closed when the block ends so that
                ``Server.wait_closed`` has a handler to wait on that finishes.
        """
        del reader
        assert origin is not None, "the handler cannot run before the yield below"
        origin.connections += 1
        origin.accepted.set()
        try:
            await stop.wait()
        finally:
            with suppress(OSError):
                writer.close()
            with suppress(OSError):
                writer.transport.abort()

    # **Bound to the first address ``HOST`` resolves to, and to that one only.**
    # ``localhost`` can carry both an IPv6 and an IPv4 address, and
    # ``asyncio.start_server`` given a name and port 0 binds one socket per address
    # with a *different* ephemeral port on each — so there would be no single port
    # to name. Binding the first address ourselves gives one port, and it is the
    # one ``create_connection`` reaches first, since it walks the same
    # ``getaddrinfo`` order this did.
    family, kind, proto, _, address = socket.getaddrinfo(HOST, 0, type=socket.SOCK_STREAM)[0]
    listening = socket.socket(family, kind, proto)
    listening.setblocking(False)
    listening.bind(address)
    port = int(listening.getsockname()[1])
    server = await asyncio.start_server(serve, sock=listening)
    origin = StalledOrigin(
        endpoint=TransportEndpoint(host=HOST, port=port, implicit_tls=True),
        origin=f"https://{HOST}:{port}",
    )
    try:
        yield origin
    finally:
        # Released before the server is closed: ``Server.wait_closed`` waits for
        # every handler task, and a handler still sitting on ``stop`` would hold
        # the teardown for as long as this arrangement holds a client.
        stop.set()
        server.close()
        await server.wait_closed()
