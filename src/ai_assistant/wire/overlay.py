"""Whose device holds the address this client is about to dial (ADR-0124 §4).

The client's half of the mutual authentication, and the mirror of the hub's:

> **Normative.** Before sending anything on the remote transport, the client
> obtains the hub's overlay identity from the overlay agent on its own machine and
> refuses unless it equals the **enrolled hub identity** §6 gave it. ADR-0084 §1's
> peer-credential check governs the loopback transport and is unavailable here;
> this clause stands in its place, in the same direction.

**The agent is queried, never linked** (ADR-0124 §3): "the overlay agent is not
imported by, embedded in, linked into or launched by ``ai_assistant``… neither
speaks to the agent's operator". So this speaks a few bytes of HTTP/1.1 to a Unix
socket the agent already listens on and adds no dependency — refusing to grow a
client library for a fixed ``GET`` is also what keeps the "not linked into" clause
mechanically true.

**Querying it is not egress**, and §4 says why: "It is a call to a daemon on the
same machine over a local interface, in the class ADR-0084 §1 already reasoned
about."

**Why this is not :mod:`ai_assistant.service.overlay`.** That module is the hub's
half and lives in ``service``; ADR-0084 §6 rules that ``wire`` "depends on ``core``
and nothing else", so a client in ``wire`` cannot reach it — the same wall that
gave the hub's device tool its own console script. What is here is deliberately
*narrower* than what is there: the hub asks two questions (which addresses are
mine, and who is at this one), and a client asks one. Folding the shared HTTP
transport into this module and having ``service`` import it is the obvious
consolidation and is filed rather than taken, because ``service`` is not this
lane's to edit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from ai_assistant.wire.errors import OverlayIdentityUnavailableError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Where ``tailscaled`` listens for its local API, in the order the two filesystem
#: layouts occur. Both are the daemon's own socket, protected by the operating
#: system's own access control.
TAILSCALE_SOCKETS: Final[tuple[str, ...]] = (
    "/var/run/tailscale/tailscaled.sock",
    "/run/tailscale/tailscaled.sock",
)

#: The ``Host`` header the local API requires. It is not a name that resolves and is
#: never looked up; the connection is already open to the Unix socket by the time it
#: is written.
_LOCAL_API_HOST: Final = "local-tailscaled.sock"

#: How long one local query may take. A daemon on the same machine answers in
#: milliseconds, and a client must not hang before it has sent anything: refusing is
#: the correct answer to an agent that will not say (ADR-0124 §4).
_QUERY_TIMEOUT_SECONDS: Final = 5.0

#: How many space-separated parts a status line must have before its code can be
#: read: ``HTTP/1.1`` and the code itself.
_STATUS_LINE_PARTS: Final = 2

#: What one response may occupy. A ``whois`` answer is one node's record, so this is
#: generous; it exists so that a daemon answering without end cannot be a memory
#: fault in a command.
_MAX_RESPONSE_BYTES: Final = 1024 * 1024

#: What an overlay identity may occupy, encoded. Every overlay ADR-0124 §2 could
#: accept names a node with a short stable identifier — Tailscale's are a dozen or
#: so characters — so this is generous by an order of magnitude and exists to make
#: the identity a *bounded* value rather than to fit any real one.
#:
#: **Bounded where an identity is produced**, which is the same place the hub's own
#: agent seam bounds it, so nothing downstream has to re-derive it: an identity this
#: client cannot compare or report is one it does not know, and §4's answer to not
#: knowing is that the destination is refused.
MAX_OVERLAY_IDENTITY_BYTES: Final[int] = 128


class OverlayAgent(Protocol):
    """The local daemon, as a *client* uses it: one question, asked of this machine.

    Narrower than the hub's seam on purpose. A client never binds an address, so it
    never needs to know which addresses are its own; what it needs is the identity
    of the node at the address it is about to dial, so that it can refuse a
    destination that is not the hub it was enrolled at.
    """

    async def identify(self, host: str, port: int) -> str:
        """Ask the agent whose device holds a remote address.

        Args:
            host: The address this client is about to dial.
            port: The port it is about to dial.

        Returns:
            That node's overlay identity.

        Raises:
            OverlayIdentityUnavailableError: If the agent will not say.
        """


class TailscaleAgent:
    """Tailscale's local API, over the daemon's own Unix socket.

    ADR-0124 §2 accepts Tailscale "as the first implementation, in writing, and the
    acceptance is of an overlay rather than of a vendor", so this is one
    implementation of the Protocol above and "moving to another overlay that
    satisfies the clause… is a configuration and operating change".

    **The identity is the node's stable identifier, not its name or its address.** A
    name is renameable and an address is reassignable, and ADR-0124 §6 records an
    enrolment against an identity that has to survive both. On this side that
    matters twice over: the value compared here is the one the hub disclosed at
    enrolment, so a client that compared names would accept a node that had merely
    taken the hub's name.

    Attributes:
        socket_path: The daemon socket this instance talks to.
    """

    def __init__(self, socket_path: Path | str) -> None:
        """Point a client at its local overlay daemon.

        Args:
            socket_path: The daemon's Unix socket.
        """
        self.socket_path = str(socket_path)

    async def identify(self, host: str, port: int) -> str:
        """Ask the daemon whose device holds ``host``.

        Args:
            host: The address this client is about to dial.
            port: The port it is about to dial.

        Returns:
            That node's overlay identity.

        Raises:
            OverlayIdentityUnavailableError: If the daemon cannot be reached, does
                not know the node, or answers with something unusable.
        """
        # Bracketed for IPv6, which is the form the local API's `addr` expects and
        # the form a hub on an overlay's IPv6 range will actually meet.
        literal = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        whois = await self._get(f"/localapi/v0/whois?addr={literal}")
        node = whois.get("Node")
        if not isinstance(node, dict):
            msg = (
                f"the overlay agent at {self.socket_path} knows no node at {literal}. A "
                f"client refuses a destination it cannot name rather than dialling it "
                f"(ADR-0124 §4); check that the hub's device is on the overlay and up"
            )
            raise OverlayIdentityUnavailableError(msg)
        return _stable_id(node)

    async def _get(self, path: str) -> dict[str, Any]:
        """Perform one local ``GET`` and decode its JSON body.

        Args:
            path: The local API path, query string included.

        Returns:
            The decoded object.

        Raises:
            OverlayIdentityUnavailableError: If the daemon cannot be reached, does
                not answer, or answers with something that is not a JSON object.
        """
        try:
            async with asyncio.timeout(_QUERY_TIMEOUT_SECONDS):
                body = await self._request(path)
        except (TimeoutError, OSError) as exc:
            msg = (
                f"the overlay agent at {self.socket_path} did not answer ({exc}). This "
                f"client asks its own machine who is at the address it is about to dial, "
                f"and sends nothing until it has been told (ADR-0124 §4); start the "
                f"overlay agent and try again"
            )
            raise OverlayIdentityUnavailableError(msg) from exc
        try:
            decoded = json.loads(body)
        except ValueError as exc:
            msg = (
                f"the overlay agent at {self.socket_path} answered with something that is not JSON"
            )
            raise OverlayIdentityUnavailableError(msg) from exc
        if not isinstance(decoded, dict):
            msg = f"the overlay agent answered {type(decoded).__name__} where an object belongs"
            raise OverlayIdentityUnavailableError(msg)
        return decoded

    async def _request(self, path: str) -> bytes:
        """Write one HTTP/1.1 request and read the whole response body.

        Hand-written rather than delegated, for ADR-0124 §3's reason: the agent is
        "not imported by, embedded in, linked into or launched by ``ai_assistant``",
        and a fixed ``GET`` against a local socket is a smaller thing than the
        dependency that would perform it. ``Connection: close`` is what makes the
        body's end unambiguous without reading a chunked encoding.

        Args:
            path: The local API path, query string included.

        Returns:
            The response body.

        Raises:
            OSError: If the socket cannot be opened or the daemon goes away.
            OverlayIdentityUnavailableError: If the status line is not a success, or
                the daemon closed early or ran on.
        """
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        try:
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {_LOCAL_API_HOST}\r\n"
                f"Accept: application/json\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(request.encode("ascii"))
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            status = head.split(b"\r\n", 1)[0].split(b" ")
            if len(status) < _STATUS_LINE_PARTS or status[1] != b"200":
                rendered = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
                msg = f"the overlay agent refused a local query: {rendered}"
                raise OverlayIdentityUnavailableError(msg)
            return await _read_body(reader)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            msg = "the overlay agent closed the connection before answering, or ran on"
            raise OverlayIdentityUnavailableError(msg) from exc
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


async def _read_body(reader: asyncio.StreamReader) -> bytes:
    """Read a ``Connection: close`` response body to its end, under a ceiling.

    ``StreamReader.read(n)`` returns as soon as *any* bytes are available, so a
    single call is not "the body" — it is whatever one packet happened to carry.
    Reading to EOF is what makes the answer whole, and the ceiling is what stops a
    daemon answering without end from being a memory fault in a command.

    Args:
        reader: The connection to the agent.

    Returns:
        The body's bytes.

    Raises:
        OverlayIdentityUnavailableError: If the response exceeds the ceiling.
    """
    body = bytearray()
    while chunk := await reader.read(64 * 1024):
        body += chunk
        if len(body) > _MAX_RESPONSE_BYTES:
            msg = f"the overlay agent's answer exceeded {_MAX_RESPONSE_BYTES} bytes"
            raise OverlayIdentityUnavailableError(msg)
    return bytes(body)


def _stable_id(node: dict[str, Any]) -> str:
    """Read one node's stable overlay identity, or refuse to guess.

    Args:
        node: The agent's record of a node.

    Returns:
        Its stable identifier.

    Raises:
        OverlayIdentityUnavailableError: If the record carries no usable one.
            **There is deliberately no fallback to a name or an address**: the value
            an enrolment recorded is a stable identifier, so comparing against a
            renameable or reassignable one would accept a node that had merely
            acquired the hub's name — which is the substitution ADR-0124 §4's second
            clause exists to refuse.
    """
    identity = node.get("StableID")
    if not isinstance(identity, str) or not identity:
        msg = (
            "the overlay agent reported a node with no stable identity, so this client "
            "cannot tell whether the address it was about to dial is the hub it was "
            "enrolled at; it refuses rather than guessing from a name or an address, "
            "either of which would follow a rename or a reassignment"
        )
        raise OverlayIdentityUnavailableError(msg)
    try:
        size = len(identity.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # **A string JSON decoded is not always a string that can be sent.** A lone
        # surrogate survives ``json.loads`` and has no UTF-8 form at all, so it
        # cannot be compared against an enrolled identity that was bounded on the
        # way in — not knowing it is the same condition as not being told it.
        msg = (
            "the overlay agent reported a stable identity with no UTF-8 form, so it "
            "cannot be compared against the enrolled one; the destination is refused"
        )
        raise OverlayIdentityUnavailableError(msg) from exc
    if size > MAX_OVERLAY_IDENTITY_BYTES:
        msg = (
            f"the overlay agent reported a stable identity over "
            f"{MAX_OVERLAY_IDENTITY_BYTES} bytes, which no overlay this client accepts "
            f"produces; the destination is refused rather than compared against it"
        )
        raise OverlayIdentityUnavailableError(msg)
    return identity


def local_agent(candidates: Sequence[str] = TAILSCALE_SOCKETS) -> TailscaleAgent:
    """The agent this machine runs, at whichever path it listens on.

    Args:
        candidates: The socket paths to look at, in order.

    Returns:
        An agent pointed at a socket. Whether the daemon is actually there is
        answered by the first query, which is where a refusal belongs — a
        constructor that probed would ask the question at a moment nothing chose
        (:class:`~ai_assistant.wire.client.HubEngineClient` takes the same shape and
        records the same reason). Where none of the paths exists the first is used,
        so the refusal names a path rather than an absence.
    """
    for candidate in candidates:
        if Path(candidate).exists():
            return TailscaleAgent(candidate)
    return TailscaleAgent(candidates[0])
