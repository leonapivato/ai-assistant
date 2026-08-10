"""The overlay agent: who is at the other end, and which address is ours.

ADR-0124 §4 restates ADR-0084 §1's obligation in terms of the *fact* rather than
the syscall, because ``SO_PEERCRED`` "has no analogue across a network":

> Before admitting a connection on the remote listener, the hub obtains the
> connecting device's overlay identity from the overlay agent running on the hub's
> own machine, over a local interface. It may not take that identity from anything
> the peer asserts, and it may not obtain it by a call that leaves the device. A
> connection whose overlay identity cannot be obtained is refused.

**The agent is queried, never linked.** ADR-0124 §3 is categorical: "the overlay
agent is not imported by, embedded in, linked into or launched by
``ai_assistant``. The hub binds an address the agent provides and the client dials
one; neither speaks to the agent's operator." So this module speaks a few bytes of
HTTP/1.1 to a Unix socket the agent already listens on, and adds no dependency —
the request is a fixed ``GET``, and refusing to grow a client library for it is
also what keeps the "not linked into" clause mechanically true.

**Querying it is not egress**, and §4 says why: "It is a call to a daemon on the
same machine over a local interface, in the class ADR-0084 §1 already reasoned
about: 'a loopback listener moves bytes between two processes on one machine; it
engages neither clause.'"

**The seam is a Protocol here and not in ``core``.** ADR-0124 §10 decides no
``core/protocols.py`` surface, and an overlay agent is a deployment fact the hub
holds — the shape :mod:`ai_assistant.service.scheduler` already uses for a
collaborator that is not a contract between subsystems.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import structlog

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.custody import first_ancestor_fault
from ai_assistant.wire.address import sun_path_limit

_log = structlog.get_logger(__name__)

#: Where ``tailscaled`` listens for its local API, in the order the two
#: filesystem layouts occur. Both are the daemon's own socket, protected by the
#: operating system's own access control — which is the custody ADR-0004 §3 leans
#: on everywhere else, applied to a socket rather than a keyring.
TAILSCALE_SOCKETS: Final[tuple[str, ...]] = (
    "/var/run/tailscale/tailscaled.sock",
    "/run/tailscale/tailscaled.sock",
)

#: What an overlay identity may occupy, encoded. Every overlay §2 could accept
#: names a node with a short stable identifier — Tailscale's are a dozen or so
#: characters — so this is generous by an order of magnitude and exists to make the
#: identity a *bounded* value rather than to fit any real one.
#:
#: **Bounding it is load-bearing rather than defensive**, and two things rest on
#: it. The enrolment reply repeats the identity beside the credential ADR-0124 §6
#: discloses "once at enrolment and never again", so an identity large enough to
#: overflow that reply would leave an enrolment committed whose credential nobody
#: ever read — the clause defeated by a value nothing bounded. And a listing
#: carries one identity per row, so a bound on rows is a bound on the answer only
#: if a row is bounded too.
MAX_OVERLAY_IDENTITY_BYTES: Final[int] = 128

#: The ``Host`` header the local API requires. It is not a name that resolves and
#: is never looked up; the connection is already open to the Unix socket by the
#: time it is written.
_LOCAL_API_HOST: Final = "local-tailscaled.sock"

#: How long one local query may take. A daemon on the same machine answers in
#: milliseconds, and a hung one must not hold a pending-handshake slot open: the
#: refusal §4 requires is the correct answer to an agent that will not say.
_QUERY_TIMEOUT_SECONDS: Final = 5.0

#: How many space-separated parts a status line must have before its code can be
#: read: ``HTTP/1.1`` and the code itself.
_STATUS_LINE_PARTS: Final = 2

#: What one response may occupy. The local API's ``status`` grows with the number
#: of overlay members, so the bound is generous; it exists so that a daemon
#: answering without end cannot be a memory fault in the hub.
_MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024


class OverlayIdentityUnavailableError(Exception):
    """The overlay agent did not say who a peer is, so the peer is refused.

    ADR-0124 §4's last sentence, as a type: "A connection whose overlay identity
    cannot be obtained is refused." Every way of not knowing is one condition — an
    agent that is not running, a socket the hub may not open, a peer the agent has
    never heard of, an answer that does not parse — because the hub's response to
    all of them is identical and a taxonomy would only invite one branch to become
    "admit anyway".
    """


@dataclass(frozen=True, slots=True)
class HubOverlayIdentity:
    """What the agent reports about *this* machine.

    Attributes:
        identity: The hub's own overlay identity — the value ADR-0124 §6 discloses
            beside a minted credential, because §4 makes it "the thing a
            destination has to match". It is not a secret.
        addresses: Every address this machine holds on the overlay, which is what
            ADR-0124 §2's bind restriction is checked against.
    """

    identity: str
    addresses: frozenset[str]


class OverlayAgent(Protocol):
    """The local daemon, as the hub uses it.

    Two questions, and both are answered from this machine: which addresses and
    identity are ours, and who is at a given remote address.
    """

    async def hub_identity(self) -> HubOverlayIdentity:
        """Ask the agent what this machine is on the overlay.

        Returns:
            This machine's overlay identity and addresses.

        Raises:
            OverlayIdentityUnavailableError: If the agent will not say.
        """

    async def identify(self, host: str, port: int) -> str:
        """Ask the agent whose device holds a remote address.

        Args:
            host: The peer's address, as the accepted socket reports it.
            port: The peer's source port, which the agent needs to disambiguate.

        Returns:
            The peer's overlay identity.

        Raises:
            OverlayIdentityUnavailableError: If the agent does not know the peer.
        """


class TailscaleAgent:
    """Tailscale's local API, over the daemon's own Unix socket.

    ADR-0124 §2 accepts Tailscale "as the first implementation, in writing, and the
    acceptance is of an overlay rather than of a vendor" — so this class is one
    implementation of the Protocol above, and "moving to another overlay that
    satisfies the clause… is a configuration and operating change".

    **The identity is the node's stable identifier, not its name or its address.**
    A name is renameable and an address is reassignable, and ADR-0124 §6 records an
    enrolment against an identity that has to survive both — an enrolment that
    quietly followed a renamed node, or worse a reused name, would be admitting a
    device the owner never enrolled.

    Attributes:
        socket_path: The daemon socket this instance talks to.
    """

    def __init__(self, socket_path: Path | str) -> None:
        """Point the hub at a local overlay daemon.

        Args:
            socket_path: The daemon's Unix socket.
        """
        self.socket_path = str(socket_path)

    async def hub_identity(self) -> HubOverlayIdentity:
        """Read this machine's identity and overlay addresses from the daemon.

        Returns:
            This machine's overlay identity and addresses.

        Raises:
            OverlayIdentityUnavailableError: If the agent will not say.
        """
        status = await self._get("/localapi/v0/status")
        this = status.get("Self")
        if not isinstance(this, dict):
            msg = "the overlay agent's status names no node for this machine"
            raise OverlayIdentityUnavailableError(msg)
        identity = _stable_id(this)
        addresses = this.get("TailscaleIPs")
        if not isinstance(addresses, list) or not all(isinstance(one, str) for one in addresses):
            msg = "the overlay agent reported no usable addresses for this machine"
            raise OverlayIdentityUnavailableError(msg)
        return HubOverlayIdentity(identity=identity, addresses=frozenset(addresses))

    async def identify(self, host: str, port: int) -> str:
        """Ask the daemon whose device holds ``host``.

        Args:
            host: The peer's address, as the accepted socket reports it.
            port: The peer's source port.

        Returns:
            The peer's overlay identity.

        Raises:
            OverlayIdentityUnavailableError: If the agent does not know the peer.
        """
        # Bracketed for IPv6, which is the form the local API's `addr` expects and
        # the form a hub on an overlay's IPv6 range will actually meet.
        literal = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        whois = await self._get(f"/localapi/v0/whois?addr={literal}")
        node = whois.get("Node")
        if not isinstance(node, dict):
            msg = f"the overlay agent knows no node at the address a peer connected from ({port})"
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
                f"the overlay agent at {self.socket_path} did not answer ({exc}); a device "
                f"whose overlay identity cannot be obtained is refused (ADR-0124 §4)"
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
            The response body, or empty bytes on a non-200 status.

        Raises:
            OSError: If the socket cannot be opened or the daemon goes away.
            OverlayIdentityUnavailableError: If the status line is not a success.
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
    single call is not "the body" — it is whatever one packet happened to carry,
    which for a status listing several overlay members is a fragment that then
    fails to parse as JSON. Reading to EOF is what makes the answer whole, and the
    ceiling is what stops a daemon answering without end from being a memory fault
    in a resident process.

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
            **There is deliberately no fallback to a name or an address**: an
            enrolment recorded against a renameable value would follow a rename, and
            one recorded against an address would follow a reassignment — both of
            which admit a device the owner never enrolled.
    """
    identity = node.get("StableID")
    if not isinstance(identity, str) or not identity:
        msg = (
            "the overlay agent reported a node with no stable identity; an enrolment "
            "recorded against a name or an address would follow a rename or a reassignment"
        )
        raise OverlayIdentityUnavailableError(msg)
    try:
        size = len(identity.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # **A string JSON decoded is not always a string that can be sent.** A lone
        # surrogate survives ``json.loads`` and has no UTF-8 form at all, which is
        # the category :func:`ai_assistant.wire.envelope._finite` handles for a
        # non-finite number — "it has no form on this wire". An identity that cannot
        # be encoded cannot be recorded, compared or reported, so not knowing it is
        # the same condition as not being told it, and takes §4's same answer.
        msg = (
            "the overlay agent reported a stable identity with no UTF-8 form, so it "
            "cannot be recorded or compared; the peer is refused"
        )
        raise OverlayIdentityUnavailableError(msg) from exc
    if size > MAX_OVERLAY_IDENTITY_BYTES:
        # Refused at the seam that *produces* an identity, so nothing downstream has
        # to re-derive the bound. §4's answer to an identity it cannot use is the
        # same as its answer to one it cannot obtain: the connection is refused.
        msg = (
            f"the overlay agent reported a stable identity over "
            f"{MAX_OVERLAY_IDENTITY_BYTES} bytes, which no overlay this hub accepts "
            f"produces; the peer is refused rather than recorded under it"
        )
        raise OverlayIdentityUnavailableError(msg)
    return identity


def check_configured_socket(socket_path: Path) -> None:
    """A configured agent socket keeps the custody the two defaults have.

    **This is what makes the setting safe to expose, and without it the setting
    would be a different decision.** The comment on :data:`TAILSCALE_SOCKETS` gives
    the reason the two packaged paths can be trusted at all: they are "the daemon's
    own socket, protected by the operating system's own access control — which is
    the custody ADR-0004 §3 leans on everywhere else, applied to a socket rather
    than a keyring". ADR-0124 §4 then makes that socket's answer the identity of
    every device that connects, and forbids taking that identity "from anything the
    peer asserts". A path an operator can name is not in itself a breach of that
    clause — a Unix socket is a local interface, and §4's third clause governs the
    client's *enrolled hub identity*, not the agent's location. But a path with no
    conditions on it would let a socket any local user owns answer for the overlay,
    which reaches the same end by another route.

    So the conditions are the ones ADR-0084 §1 already imposes on the data
    directory, and for the same reason: nothing here is authenticated at the moment
    it is opened, so the filesystem has to carry the trust. The ancestry walk is
    literally shared (:mod:`ai_assistant.service.custody`) rather than restated.

    **The leaf takes root-or-us, not exactly-us**, which is where this departs from
    the data directory. The daemon runs as root in the ordinary deployment, so its
    socket is root-owned and a hub demanding its own uid would reject every real
    installation. What both cases exclude is the same: a *third* user owning the
    thing the hub is about to trust.

    Args:
        socket_path: The path an operator configured.

    **It asks who could answer, never whether anybody currently does.** An absent
    socket is accepted, because refusing one would both contradict
    :func:`local_agent`'s contract and turn "the hub started a moment before its
    agent" into a stay-down fault. What bounds who may place a socket there later
    is the ancestry walk, which is the same thing that bounds it for a path that
    exists.

    Raises:
        ConfigurationError: If the path is too long to connect to, if any ancestor
            lets an untrusted user replace what sits beneath it, or if a socket is
            present and is not a socket or belongs to a third user. Every one is a
            stay-down deployment fault in ADR-0083 §5's sense — none is fixed by
            restarting.
    """
    setting = "ASSISTANT_HUB_OVERLAY_AGENT_SOCKET"
    limit = sun_path_limit()
    encoded = len(str(socket_path).encode("utf-8")) + 1  # the NUL terminator counts
    if encoded > limit:
        msg = (
            f"the overlay agent socket {socket_path} encodes to {encoded} bytes including "
            f"its terminator, over this platform's {limit}-byte sun_path budget, so no "
            f"connection can be made to it; set {setting} to a shorter path"
        )
        raise ConfigurationError(msg)

    try:
        fault = first_ancestor_fault(socket_path)
    except OSError as exc:
        # A directory that is missing or cannot be traversed is the ordinary typo,
        # and it has to arrive as a `ConfigurationError` like every other startup
        # misconfiguration — ADR-0083 §5 maps this class to a stay-down exit, and a
        # raw `FileNotFoundError` out of the composition root would instead be an
        # unexpected fault, reported as though the hub had a defect.
        msg = (
            f"the path to the overlay agent socket {socket_path}, which {setting} names, "
            f"cannot be read ({exc.strerror} at {exc.filename}), so whether an untrusted "
            f"user could answer for the overlay there cannot be established; correct "
            f"{setting}, or unset it to look at the two paths the daemon is packaged to "
            f"use ({', '.join(TAILSCALE_SOCKETS)})"
        )
        raise ConfigurationError(msg) from exc
    if fault is not None and fault.kind == "replaceable":
        msg = (
            f"{fault.ancestor} is mode {fault.mode:04o}, writable by other users and not "
            f"sticky, so another user could replace the overlay agent socket beneath it "
            f"and answer for the overlay — which is the identity ADR-0124 §4 admits every "
            f"device by; chmod it, set its sticky bit, or set {setting} to a path under a "
            f"directory you own"
        )
        raise ConfigurationError(msg)
    if fault is not None:
        msg = (
            f"{fault.ancestor} is owned by uid {fault.uid}, neither root nor the "
            f"uid {os.geteuid()} the hub runs as, so that user controls the path to the "
            f"overlay agent socket and could answer for the overlay; set {setting} to a "
            f"path under a directory you own"
        )
        raise ConfigurationError(msg)

    try:
        info = socket_path.stat()
    except FileNotFoundError:
        # **Absence is not refused here, and that is deliberate.** `local_agent`'s
        # contract is that "whether the daemon is actually there is answered by the
        # first query, which is where a refusal belongs", and ADR-0124 §3 forbids
        # launching one — so a hub that started a moment before its agent gets the
        # same answer for a configured path as for a packaged one. Nothing is
        # given up by allowing it: an absent socket answers for nobody, and the
        # ancestry walk above is what bounds who can place one here later.
        return
    if not stat.S_ISSOCK(info.st_mode):
        msg = (
            f"{socket_path}, which {setting} names, is not a socket; the overlay agent's "
            f"local API is a Unix socket, so nothing can be asked of this path"
        )
        raise ConfigurationError(msg)
    if info.st_uid not in (0, os.geteuid()):
        msg = (
            f"the overlay agent socket {socket_path} is owned by uid {info.st_uid}, "
            f"neither root nor the uid {os.geteuid()} the hub runs as, so that user "
            f"answers for the overlay and decides which device the hub admits "
            f"(ADR-0124 §4); point {setting} at your own overlay agent's socket"
        )
        raise ConfigurationError(msg)


def local_agent(socket_path: str | None = None) -> TailscaleAgent:
    """The agent this machine runs, at whichever path it listens on.

    Args:
        socket_path: An explicit socket path, or ``None`` to look at the two
            places the daemon is packaged to use. An explicit path is held to
            :func:`check_configured_socket`'s custody conditions first; the two
            packaged defaults are used exactly as before.

    Returns:
        An agent pointed at a socket. Whether the daemon is actually there is
        answered by the first query, which is where a refusal belongs — a
        constructor that probed would ask the question at a moment nothing chose.
        That holds for a configured path too: the custody check asks who *could*
        answer, never whether anybody currently does.

    Raises:
        ConfigurationError: If an explicit ``socket_path`` fails the custody
            conditions the two defaults hold by construction.
    """
    if socket_path is not None:
        check_configured_socket(Path(socket_path))
        return TailscaleAgent(socket_path)
    for candidate in TAILSCALE_SOCKETS:
        if Path(candidate).exists():
            return TailscaleAgent(candidate)
    _log.info(
        "overlay_agent_socket_not_found",
        looked_at=list(TAILSCALE_SOCKETS),
        detail="the first query will refuse, which is the answer ADR-0124 §4 requires",
    )
    return TailscaleAgent(TAILSCALE_SOCKETS[0])
