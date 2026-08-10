"""Where the door is, and whether the path can hold it (ADR-0084 §1, §9).

**One setting locates both the data and the door.** The socket path derives from
:attr:`~ai_assistant.core.config.Settings.data_dir` as ``<data_dir>/hub.sock``, and
ADR-0084 §9 makes that deliberate: "a client that can find the data directory can
find the hub", and "a hub and a client that disagree about the data directory would
otherwise fail with a missing socket rather than with the misconfiguration they
actually have". ``Settings`` refuses a relative value and canonicalises the rest,
which is what makes "the same field" mean the same directory.

**The path is length-checked at startup, and this closes #554.** A pathname
``AF_UNIX`` socket is bounded by ``sun_path``, and a perfectly writable, perfectly
valid data directory can have a path no socket can be bound inside. Left unchecked
that failure lands at ADR-0083 §3's **step 6** — after the lock is held, the seven
stores are open and the start-up sweeps have run — "the latest and least legible
moment available, and a hub that is down for a reason buried in a ``bind`` errno is
ruling 4's failure".

**And where the door is when it is on another machine** (ADR-0124 §1). The client
"obtains its destination from configuration and never from a discovery mechanism, a
redirect, or anything a peer tells it", so :func:`destination` reads two settings
and nothing else — no probe, no fallback from one transport to the other, and no
value a peer supplied. Which of the two transports a command uses is therefore a
deployment fact, decided before anything is opened.
"""

from __future__ import annotations

import ipaddress
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

#: The socket's name inside the data directory (ADR-0084 §1).
SOCKET_FILENAME: Final[str] = "hub.sock"

#: The hub-local control socket's name (ADR-0124 §6). It is bound only where the
#: remote listener is configured, because it exists for one purpose: the enrolment
#: and revocation acts, which ADR-0124 §6 requires to be performed "at the hub —
#: on the hub's own machine, over ADR-0084 §1's loopback transport or a hub-local
#: entry point". Its own name rather than a second use of ``hub.sock`` so that the
#: promoted engine surface and the owner's device acts cannot be reached through
#: one door by accident.
ADMIN_SOCKET_FILENAME: Final[str] = "admin.sock"

#: Owner-only, which is ADR-0004 §4's existing posture applied to a new object of
#: the same kind rather than a control invented here — and on Linux the kernel
#: enforces it at ``connect()``, so ``0600`` on ``hub.sock`` is what makes a Unix
#: socket "reuse a ratified access control" where a TCP loopback port has none.
SOCKET_MODE: Final[int] = 0o600

#: ``sun_path``'s size, **by platform**, terminator included. ADR-0084 §1 requires
#: "the running platform's own limit rather than a constant": hardcoding 108 "would
#: let a 104-byte path pass validation on macOS and then fail at ``bind()``, which
#: is precisely the late, opaque failure this rule exists to prevent, reintroduced
#: by the check itself".
_SUN_PATH_BYTES: Final[dict[str, int]] = {
    "linux": 108,
    "darwin": 104,
    "freebsd": 104,
    "openbsd": 104,
    "netbsd": 104,
}

#: What an unrecognised platform gets. The **smaller** of the two figures, because
#: the direction of a wrong guess matters: too small refuses a path that would have
#: worked and says exactly why, while too large passes validation and fails inside
#: ``bind()`` with an errno — the failure this check exists to replace.
_SMALLEST_SUN_PATH: Final[int] = 104


def sun_path_limit() -> int:
    """The running platform's ``sun_path`` budget, terminator included.

    Returns:
        The number of bytes a pathname socket's address may occupy here.
    """
    return _SUN_PATH_BYTES.get(sys.platform, _SMALLEST_SUN_PATH)


def socket_path(data_dir: Path) -> Path:
    """Where the hub listens, given the directory it owns.

    Args:
        data_dir: The absolute, canonical data directory ``Settings`` guarantees.

    Returns:
        ``<data_dir>/hub.sock``.
    """
    return data_dir / SOCKET_FILENAME


def admin_socket_path(data_dir: Path) -> Path:
    """Where the hub takes the owner's device acts (ADR-0124 §6).

    Args:
        data_dir: The absolute, canonical data directory ``Settings`` guarantees.

    Returns:
        ``<data_dir>/admin.sock``.
    """
    return data_dir / ADMIN_SOCKET_FILENAME


def check_admin_socket_path(data_dir: Path) -> None:
    """Refuse a data directory whose path cannot hold the control socket.

    The same ``sun_path`` argument as :func:`check_socket_path`, applied where it
    is owed. It is **not** folded into ADR-0083 §3's step 2 with the other one,
    deliberately: this socket is bound only where the remote listener is configured
    (ADR-0124 §2), and a deployment that never binds it must not be refused at
    startup for a path length that could never bind anything.

    Args:
        data_dir: The data directory the socket would live in.

    Raises:
        ConfigurationError: If the encoded path plus its terminator exceeds the
            platform's budget.
    """
    _check_path(admin_socket_path(data_dir), what="the hub's control socket")


def check_socket_path(data_dir: Path) -> None:
    """Refuse a data directory whose path cannot hold the socket (ADR-0084 §1).

    ADR-0083 §5's test applies without strain: restarting unchanged never succeeds,
    and a human must move the data directory — so it is a stay-down deployment
    fault, which :func:`~ai_assistant.service.exits.classify` reaches through
    :class:`~ai_assistant.core.errors.ConfigurationError`.

    **The check is on the encoded byte length** rather than the character count,
    because ``sun_path`` bounds bytes: "a directory named in a non-ASCII script
    spends more of the budget than it looks like it does."

    Args:
        data_dir: The data directory the socket would live in.

    Raises:
        ConfigurationError: If the encoded path plus its terminator exceeds the
            platform's budget. The message names the limit, the encoded length and
            the directory, which is what ADR-0084 §1 asks of it.
    """
    _check_path(socket_path(data_dir), what="the hub's socket")


@dataclass(frozen=True, slots=True)
class LoopbackDestination:
    """The hub on this machine, over ADR-0084 §1's Unix socket.

    Attributes:
        socket_path: ``<data_dir>/hub.sock``.
    """

    socket_path: Path


@dataclass(frozen=True, slots=True)
class RemoteDestination:
    """A hub on another machine, over ADR-0124's overlay transport.

    **The address is here and the identity is not**, which is ADR-0124 §4's third
    clause and the thing that stops its second from being circular. An edit that
    redirects this client changes what it dials and leaves untouched the check that
    destination has to pass, because the enrolled hub identity lives in the keyring
    beside the credential (:mod:`ai_assistant.wire.enrolment`) and "no configuration
    setting may override that identity".

    Attributes:
        host: The hub's address on the overlay, as a literal.
        port: The port its remote listener binds.
    """

    host: str
    port: int


#: Where a command's hub is. Two cases and no third: ADR-0084 §9's "a closed door is
#: an instruction, never a fallback" applies to the choice as well as to the
#: outcome, so a remote destination never silently becomes the loopback one.
type HubDestination = LoopbackDestination | RemoteDestination


def destination(*, data_dir: Path, remote_address: str | None, remote_port: int) -> HubDestination:
    """Decide which hub this command talks to, from configuration alone.

    ADR-0124 §1: the client "obtains its destination from configuration and never
    from a discovery mechanism, a redirect, or anything a peer tells it". The
    address is the switch, in the shape ADR-0124 §2 already gave the hub's own
    listener — unset means the loopback socket, and there is no separate boolean,
    because two settings that can disagree about which transport is in use is one
    more state than a deployment has.

    Args:
        data_dir: The resolved data directory, which locates the loopback socket.
        remote_address: The hub's overlay address, or ``None`` for this machine's.
        remote_port: The port the hub's remote listener binds.

    Returns:
        The destination.

    Raises:
        ConfigurationError: If ``remote_address`` is not one a hub's remote listener
            could be bound to.
    """
    if remote_address is None:
        return LoopbackDestination(socket_path(data_dir))
    return RemoteDestination(host=check_remote_address(remote_address), port=remote_port)


def check_remote_address(value: str) -> str:
    """Refuse a destination no conforming hub could be listening on (ADR-0124 §1, §2).

    **The same five refusals the hub applies to its own bind**, from the other end
    of the hop, and that symmetry is the argument: ADR-0124 §2 forbids the listener
    to bind a wildcard, a loopback, a multicast, a link-local or a globally-routable
    address, so a client pointed at one is pointed at something that is not a
    conforming hub's remote listener. Saying so here costs a message; discovering it
    costs a connection attempt to whatever *is* there.

    **A name is refused rather than resolved**, which is the client half of a rule
    ``Settings`` already applies to the hub: resolving one is a lookup whose answer
    another party supplies, so the address dialled would be a fact about a resolver
    rather than about this deployment — and §1's "never from a discovery mechanism"
    is exactly that. It is defence in depth rather than the defence: §4's identity
    check is what makes a wrong destination harmless, and this is what makes a wrong
    destination *legible*.

    Args:
        value: The configured address.

    Returns:
        The address, stripped and unchanged otherwise.

    Raises:
        ConfigurationError: If it is not a literal IP address, or is one no
            conforming remote listener holds.
    """
    text = value.strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        msg = (
            f"the hub's remote address {value!r} is not an IP address. A client takes its "
            f"destination from configuration and never from a discovery mechanism "
            f"(ADR-0124 §1), so a name is refused rather than resolved — the address "
            f"dialled would otherwise be a fact about a resolver. Run your overlay agent's "
            f"status command and use the address it reports for the hub's machine "
            f"(ASSISTANT_REMOTE_HUB_ADDRESS)"
        )
        raise ConfigurationError(msg) from exc
    forbidden = (
        (address.is_unspecified, "a wildcard, which names no host to dial"),
        (
            address.is_loopback,
            "a loopback address, which is this machine; the hub on this machine is "
            "reached over ADR-0084 §1's Unix socket, by leaving this setting unset",
        ),
        (address.is_multicast, "a multicast address, which no listener holds"),
        (address.is_link_local, "a link-local address, which is not on the overlay"),
        (
            address.is_global,
            "reachable from the public internet, where ADR-0124 §2 forbids a hub to bind "
            "its remote listener — so whatever answers there is not your hub",
        ),
    )
    for holds, reason in forbidden:
        if holds:
            msg = (
                f"the hub's remote address {value!r} is {reason}. Configure the address "
                f"your overlay agent reports for the hub's machine, or unset "
                f"ASSISTANT_REMOTE_HUB_ADDRESS to use the hub on this one"
            )
            raise ConfigurationError(msg)
    return text


def _check_path(path: Path, *, what: str) -> None:
    """Hold one socket path to this platform's ``sun_path`` budget.

    Args:
        path: The path a socket would be bound at.
        what: How the path reads in the message.

    Raises:
        ConfigurationError: If the encoded path plus its terminator exceeds the
            budget. The message names the limit, the encoded length and the path,
            which is what ADR-0084 §1 asks of it.
    """
    limit = sun_path_limit()
    encoded = len(str(path).encode("utf-8")) + 1  # the NUL terminator counts
    if encoded > limit:
        msg = (
            f"{what} path {path} encodes to {encoded} bytes including its "
            f"terminator, over this platform's {limit}-byte sun_path budget, so no socket "
            f"can be bound there; move the data directory somewhere shorter "
            f"(ASSISTANT_DATA_DIR)"
        )
        raise ConfigurationError(msg)
