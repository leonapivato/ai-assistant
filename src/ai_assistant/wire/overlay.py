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
mine, and who is at this one), and a client asks one.

**The custody guard, by contrast, is shared and lives here** (#911, #937).
:func:`check_configured_socket` decides whether a socket an operator named can be
trusted to answer for the overlay at all, and that question has one answer on both
ends of the hop — so the wall above, which forbids ``wire`` to import ``service``,
decides *which* module holds it: this one, which ``service`` may import and does.
Only the wording of a refusal is per-caller (:class:`AgentSocketTerms`), because
what an operator should correct differs even where the condition does not.

The HTTP/1.1 transport and ``_stable_id`` below are still duplicated against the
hub's copy; folding those together is #911's remaining half and is deliberately
not taken here, so that a security guard's move and a refactor of the bytes on the
socket are two reviewable changes rather than one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire.address import sun_path_limit
from ai_assistant.wire.custody import displayable, first_ancestor_fault, others_can_create_in
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


@dataclass(frozen=True, slots=True)
class AgentSocketTerms:
    """The words one end of the hop uses about its own overlay agent socket.

    **Nothing here changes what is checked.** The custody conditions are identical
    on both ends of ADR-0124 §4 — the socket answers for the overlay either way, so
    the question "could an untrusted user answer here instead" has one answer and
    one implementation, which is the whole reason this guard is shared rather than
    restated. What differs is only what a refusal should *tell an operator*, and
    that differs in three places: which environment variable to correct, which
    process's uid the socket is being compared against, and what the identity is
    used for once obtained.

    Getting those wrong is not cosmetic. A client refused for a bad path would
    otherwise be told to correct a hub variable that need not be set on its machine
    at all, and to compare a uid against a hub that is not running there — which is
    the defect this parameterisation exists to prevent, and the reason the guard
    could not simply be called with the hub's wording from the client side.

    Attributes:
        setting: The environment variable naming the socket, so a refusal names the
            one the operator can actually edit on this machine.
        runner: How the process holding the socket reads in a refusal — "the hub"
            or "this client" — for the uid comparisons, which are about *this*
            machine's euid rather than about the other end of the hop.
        stakes: What the agent's answer *is* here, as a noun phrase completing
            "…answer for the overlay, which is …". On the hub it is the identity
            every connecting device is admitted by; on a client it is the identity
            its destination has to match.
        decides: What the agent's answer *settles* here, as a noun phrase
            completing "…answers for the overlay and decides …". A separate field
            from ``stakes`` rather than a reuse of it, because the two slots take
            different grammar and a clause that fits one reads as a non-sentence in
            the other — which is how a shared message ends up saying less than
            either of the two it replaced.
    """

    setting: str
    runner: str
    stakes: str
    decides: str


#: What a *client* refusal says (ADR-0124 §4's second clause). The hub's own terms
#: live with the hub's agent, in :mod:`ai_assistant.service.overlay`, because the
#: vocabulary belongs to the caller rather than to the check.
CLIENT_AGENT_SOCKET: Final = AgentSocketTerms(
    setting="ASSISTANT_CLIENT_OVERLAY_AGENT_SOCKET",
    runner="this client",
    stakes=(
        "the identity ADR-0124 §4 makes this client's destination match before it sends anything"
    ),
    decides="which hub this client will talk to",
)


def _refuse_an_unclaimed_name(socket_path: Path, terms: AgentSocketTerms) -> None:
    """A configured socket that does not exist yet must not be anybody's to create.

    Split out because the condition is the opposite way round from the ancestry
    walk's: there the sticky bit *earns* an other-writable directory its place, and
    here it buys nothing at all.
    """
    parent = socket_path.parent
    shown = displayable(socket_path)
    here = displayable(parent)
    try:
        plantable = others_can_create_in(parent)
    except OSError as exc:
        why = displayable(exc.strerror)
        msg = (
            f"the directory {here} holding the overlay agent socket {terms.setting} names "
            f"cannot be read ({why}), so whether an untrusted user could create "
            f"that socket cannot be established; correct {terms.setting}, or unset it"
        )
        raise ConfigurationError(msg) from exc
    if plantable:
        msg = (
            f"no socket exists yet at {shown}, and {here} is mode "
            f"{stat.S_IMODE(parent.stat().st_mode):04o} — writable by other users, so any "
            f"of them could create that socket first and answer for the overlay, which is "
            f"{terms.stakes}. A sticky bit does not help "
            f"here: it stops a user renaming an entry they do not own, and this name is "
            f"not owned by anyone yet. Set {terms.setting} to a path under a directory only you "
            f"can write, or start the overlay agent so its socket exists"
        )
        raise ConfigurationError(msg)


def _check_path_to(socket_path: Path, terms: AgentSocketTerms) -> None:
    """The budget, and the ancestry that decides who could put something here."""
    shown = displayable(socket_path)
    limit = sun_path_limit()
    # `os.fsencode`, not a UTF-8 encode: these are the bytes the kernel is handed,
    # and a filename need not be UTF-8 at all. A non-UTF-8 byte in the environment
    # reaches Python as a surrogate (PEP 383), which `str.encode("utf-8")` refuses
    # — so measuring the budget that way turned a perfectly valid pathname into a
    # `UnicodeEncodeError` no handler catches, which is a crash rather than a
    # verdict. `fsencode` round-trips the surrogates back to the original bytes.
    encoded = len(os.fsencode(socket_path)) + 1  # the NUL terminator counts
    if encoded > limit:
        msg = (
            f"the overlay agent socket {shown} encodes to {encoded} bytes including "
            f"its terminator, over this platform's {limit}-byte sun_path budget, so no "
            f"connection can be made to it; set {terms.setting} to a shorter path"
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
        why = displayable(exc.strerror)
        where = displayable(exc.filename)
        msg = (
            f"the path to the overlay agent socket {shown}, which {terms.setting} names, "
            f"cannot be read ({why} at {where}), so whether an untrusted "
            f"user could answer for the overlay there cannot be established; correct "
            f"{terms.setting}, or unset it to look at the two paths the daemon is packaged to "
            f"use ({', '.join(TAILSCALE_SOCKETS)})"
        )
        raise ConfigurationError(msg) from exc
    if fault is None:
        return
    culprit = displayable(fault.ancestor)
    if fault.kind == "replaceable":
        msg = (
            f"{culprit} is mode {fault.mode:04o}, writable by other users and not "
            f"sticky, so another user could replace the overlay agent socket beneath it "
            f"and answer for the overlay — which is {terms.stakes}; chmod it, set its "
            f"sticky bit, or set {terms.setting} to a path under a "
            f"directory you own"
        )
        raise ConfigurationError(msg)
    msg = (
        f"{culprit} is owned by uid {fault.uid}, neither root nor the "
        f"uid {os.geteuid()} {terms.runner} runs as, so that user controls the path to the "
        f"overlay agent socket and could answer for the overlay; set {terms.setting} to a "
        f"path under a directory you own"
    )
    raise ConfigurationError(msg)


def _check_socket_at(socket_path: Path, terms: AgentSocketTerms) -> None:
    """What occupies the path is the daemon's, and an unclaimed name is nobody's."""
    shown = displayable(socket_path)
    try:
        info = socket_path.stat()
    except FileNotFoundError:
        # **Absence itself is not refused; an unclaimed name others can take is.**
        # `local_agent`'s contract is that "whether the daemon is actually there is
        # answered by the first query", and ADR-0124 §3 forbids launching one, so a
        # hub that started a moment before its agent must still come up. What
        # cannot be allowed is that gap being usable by somebody else: the sticky
        # bit protects entries that *exist* from being renamed away and says
        # nothing about a name nobody has taken, so `/tmp/tailscaled.sock` is a
        # socket any local user may be the first to create — and whoever creates it
        # answers for the overlay, which is the identity §4 turns on.
        _refuse_an_unclaimed_name(socket_path, terms)
        return
    except OSError as exc:
        # The same reasoning as the ancestry walk's own `OSError`: a path that
        # cannot be read is a configuration fault, not a defect. Reached when a
        # parent is owned by this process's uid but not traversable, which the
        # walk's `stat` of the directory itself does not detect.
        why = displayable(exc.strerror)
        msg = (
            f"the overlay agent socket {shown}, which {terms.setting} names, cannot be "
            f"read ({why}), so whether an untrusted user could answer for the "
            f"overlay there cannot be established; correct {terms.setting}, or unset it to look "
            f"at the two paths the daemon is packaged to use ({', '.join(TAILSCALE_SOCKETS)})"
        )
        raise ConfigurationError(msg) from exc
    if not stat.S_ISSOCK(info.st_mode):
        msg = (
            f"{shown}, which {terms.setting} names, is not a socket; the overlay agent's "
            f"local API is a Unix socket, so nothing can be asked of this path"
        )
        raise ConfigurationError(msg)
    if info.st_uid not in (0, os.geteuid()):
        msg = (
            f"the overlay agent socket {shown} is owned by uid {info.st_uid}, "
            f"neither root nor the uid {os.geteuid()} {terms.runner} runs as, so that user "
            f"answers for the overlay and decides {terms.decides} "
            f"(ADR-0124 §4); point {terms.setting} at your own overlay agent's socket"
        )
        raise ConfigurationError(msg)


def check_configured_socket(socket_path: Path, *, terms: AgentSocketTerms) -> Path:
    """A configured agent socket keeps the custody the two defaults have.

    **This is what makes the setting safe to expose, and without it the setting
    would be a different decision.** The comment on :data:`TAILSCALE_SOCKETS` gives
    the reason the two packaged paths can be trusted at all: they are the daemon's
    own socket, protected by the operating system's own access control — which is
    the custody ADR-0004 §3 leans on everywhere else, applied to a socket rather
    than a keyring. ADR-0124 §4 then makes that socket's answer the identity every
    device is admitted by on one end and the identity a destination must match on
    the other, and forbids taking that identity "from anything the peer asserts". A
    path an operator can name is not in itself a breach of that clause — a Unix
    socket is a local interface, and §4's third clause governs the client's
    *enrolled hub identity*, not the agent's location. But a path with no conditions
    on it would let a socket any local user owns answer for the overlay, which
    reaches the same end by another route.

    So the conditions are the ones ADR-0084 §1 already imposes on the data
    directory, and for the same reason: nothing here is authenticated at the moment
    it is opened, so the filesystem has to carry the trust. The ancestry walk is
    literally shared (:mod:`ai_assistant.wire.custody`) rather than restated.

    **Both ends of the hop run this same function** (#911, #937). ADR-0084 §6 puts
    the client's agent in ``wire`` and ADR-0083 §8 forbids anything to import
    ``service``, so a guard living beside the hub's agent was reachable from one end
    only — and the client half could have had this rule only by copying it. What is
    per-caller is the *wording*, in :class:`AgentSocketTerms`, and never the check.

    **The path is canonicalised, and the checks are run against what will actually
    be opened.** This is ``data_dir``'s rule (ADR-0084 §1) for ``data_dir``'s
    reason: two readers that disagree about which file a name means is the whole
    hazard. A symlink whose target is validated but whose *name* is connected to
    leaves a gap between the two, and a dangling symlink under a trusted directory
    would otherwise pass every check while pointing at a name any local user could
    claim. So the ancestry of the name is checked — nobody untrusted may re-point
    the link — and everything else is decided about the resolved path.

    **The leaf takes root-or-us, not exactly-us**, which is where this departs from
    the data directory. The daemon runs as root in the ordinary deployment, so its
    socket is root-owned and a process demanding its own uid would reject every real
    installation. What both cases exclude is the same: a *third* user owning the
    thing that is about to be trusted.

    **It asks who could answer, never whether anybody currently does.** An absent
    socket is accepted, because refusing one would both contradict
    :func:`local_agent`'s contract and turn "the hub started a moment before its
    agent" into a stay-down fault. But an absent socket is held to one condition a
    present one is not: its directory must be one only its owner can write. The
    ancestry walk lets a sticky ``/tmp`` through, correctly, because sticky stops a
    user renaming an entry they do not own — and a name nobody has taken yet is not
    such an entry, so it would leave the socket for whoever creates it first.

    Args:
        socket_path: The path an operator configured.
        terms: Which end of the hop is asking, in the words its refusals use. It
            selects no behaviour — see :class:`AgentSocketTerms`.

    Returns:
        The canonical path, which is the one to connect to.

    Raises:
        ConfigurationError: If the path is not a usable pathname, is too long to
            connect to, has an ancestor that lets an untrusted user replace what
            sits beneath it, names nothing in a directory others can write, or
            holds something that is not a socket or belongs to a third user. Every
            one is a stay-down deployment fault in ADR-0083 §5's sense — none is
            fixed by restarting.
    """
    try:
        resolved = Path(os.path.realpath(socket_path))
    except ValueError as exc:
        # An embedded NUL is the case that reaches here: it survives every string
        # operation and fails inside the first syscall, as a `ValueError` no
        # `OSError` handler catches. A pathname the OS will not accept is a
        # configuration fault like any other, not a defect.
        msg = (
            f"{terms.setting} is not a usable pathname ({exc}); set it to the path of your "
            f"overlay agent's Unix socket, or unset it to look at the two paths the "
            f"daemon is packaged to use ({', '.join(TAILSCALE_SOCKETS)})"
        )
        raise ConfigurationError(msg) from exc

    # The name's own ancestry still matters when it differs from the target's: it is
    # what stops an untrusted user re-pointing the link between this check and the
    # connection. Everything else is decided about the path that will be opened.
    if resolved != socket_path:
        _check_path_to(socket_path, terms)
    _check_path_to(resolved, terms)
    _check_socket_at(resolved, terms)
    return resolved


def local_agent(
    socket_path: str | None = None,
    *,
    candidates: Sequence[str] = TAILSCALE_SOCKETS,
    terms: AgentSocketTerms = CLIENT_AGENT_SOCKET,
) -> TailscaleAgent:
    """The agent this machine runs, at whichever path it listens on.

    Args:
        socket_path: An explicit socket path, or ``None`` to look at the two places
            the daemon is packaged to use. An explicit path is held to
            :func:`check_configured_socket`'s custody conditions first; the
            packaged defaults are used exactly as before, byte for byte.
        candidates: The socket paths to look at when none was configured, in order.
        terms: The words a refusal about a configured path uses. Defaults to the
            client's, because this is the client's agent — the hub's own
            :func:`ai_assistant.service.overlay.local_agent` passes its own.

    Returns:
        An agent pointed at a socket — the *canonical* path when one was
        configured, since that is what the custody check was decided about.
        Whether the daemon is actually there is answered by the first query, which
        is where a refusal belongs — a constructor that probed would ask the
        question at a moment nothing chose
        (:class:`~ai_assistant.wire.client.HubEngineClient` takes the same shape and
        records the same reason). Where none of the paths exists the first is used,
        so the refusal names a path rather than an absence. That holds for a
        configured path too: the custody check asks who *could* answer, never
        whether anybody does.

    Raises:
        ConfigurationError: If an explicit ``socket_path`` fails the custody
            conditions the packaged defaults hold by construction.
    """
    if socket_path is not None:
        # The *canonical* path, not the one written: connecting to the name a
        # symlink carries would reopen the gap between what was checked and what is
        # opened, which is the hazard ADR-0084 §1 canonicalises `data_dir` to close.
        return TailscaleAgent(check_configured_socket(Path(socket_path), terms=terms))
    for candidate in candidates:
        if Path(candidate).exists():
            return TailscaleAgent(candidate)
    return TailscaleAgent(candidates[0])
