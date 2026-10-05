"""The owner's device acts, at the hub's own machine (ADR-0124 §6, §8; ADR-0298 §4).

Its own console script, for the reason every tool in this package has one:
:mod:`ai_assistant.service.admin`'s socket path and the data directory's
preparation live in ``service``, and ADR-0083 §8's "nothing may import
``service``" means anything reaching them has to *be* here — the same rule that
gave the hub and the re-embedding migration their own entry points (ADR-0084 §6,
ADR-0104 §5).

**It requires the hub to be running, where the re-embedding migration requires it
to be stopped**, and the difference is ADR-0124 §8 rather than taste: "revoking a
device closes any connection that device currently holds", and there are no
connections to close in a stopped hub. The act therefore happens inside the hub
process and this command is what asks for it.

**The credential is printed once and never stored** (ADR-0124 §6). It is not
logged here, it is not written to the record, and re-running the enrolment does
not reprint it — it mints a new one and revokes the old, which is §6's single
rotating act.

**Roles are given here and nowhere else in the first build** (ADR-0298 §4:12):
``assign`` and ``withdraw`` take one role at a time, so no act can clear a role the
owner did not name. ``revoke`` without ``--gateway`` revokes the whole device — its
enrolment, every registration of it and its roles (§4:10); with one it revokes that
registration alone, and ``restore`` is the only way a revoked registration comes
back (§4:9).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import stat
import sys
from typing import TYPE_CHECKING, Any

from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.admin import (
    ADMIN_FRAME_BYTES,
    ADMIN_TIMEOUT,
    ASSIGN,
    ENROL,
    LIST,
    RESTORE,
    REVOKE,
    WITHDRAW,
)
from ai_assistant.service.enrolment import HUB_DEVICE, Role
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.wire.address import admin_socket_path, socket_path
from ai_assistant.wire.errors import ProtocolError, TransportError
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.peer import check_peer_is_self

if TYPE_CHECKING:
    import socket
    from collections.abc import Sequence
    from pathlib import Path

_DESCRIPTION = f"""
Enrol, revoke and list the devices this hub admits, give them roles, and see
which machines each gateway has named.

Run it on the hub's own machine, with the hub running: these are acts the hub
performs on its own record, and a revocation closes the connections the device
currently holds.

A device is a machine: a hub device is enrolled here and reaches the hub over
its remote listener; a browser device is a machine a gateway lists, registered
the first time that gateway names it. A gateway on the hub's own machine is
named '{HUB_DEVICE}'. Each device does nothing until it is given a role:
'{Role.COMMANDS.value}' (commands and queries) or '{Role.SPOKES.value}' (host of spokes).

An enrolment prints its credential once. The hub keeps only a verifier, so a
credential that is lost cannot be recovered — enrol the device again, which mints
a new one and leaves the old verifying against nothing.
"""


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: The arguments, or ``None`` to read the process's.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-device",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    acts = parser.add_subparsers(dest="act", required=True)
    enrol = acts.add_parser(ENROL, help="enrol a device, or rotate its credential")
    enrol.add_argument("identity", help="the device's overlay identity, as your agent reports it")
    revoke = acts.add_parser(
        REVOKE, help="revoke a whole device, or with --gateway one registration of it"
    )
    revoke.add_argument("identity", help="the device's overlay identity")
    revoke.add_argument(
        "--gateway", help="revoke only the registration under this gateway's device"
    )
    restore = acts.add_parser(RESTORE, help="restore a registration that was revoked")
    restore.add_argument("identity", help="the device's overlay identity")
    restore.add_argument("--gateway", required=True, help="the gateway's device")
    roles = [role.value for role in Role]
    for act, verb in ((ASSIGN, "give a device"), (WITHDRAW, "take from a device")):
        one = acts.add_parser(act, help=f"{verb} one role")
        one.add_argument("identity", help="the device's overlay identity")
        one.add_argument("role", choices=roles, help="the role")
    acts.add_parser(LIST, help="show the devices, enrolments and registrations recorded")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Perform one device act against the running hub.

    Args:
        argv: The arguments, or ``None`` to read the process's.

    Returns:
        The process exit code.
    """
    arguments = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"device: {exc}", file=sys.stderr)
        return EXIT_DEPLOYMENT
    request: dict[str, Any] = {"act": arguments.act}
    if arguments.act != LIST:
        request["identity"] = arguments.identity
    if getattr(arguments, "gateway", None) is not None:
        request["gateway"] = arguments.gateway
    if arguments.act in (ASSIGN, WITHDRAW):
        request["role"] = arguments.role
    data_dir = settings.data_dir
    return asyncio.run(
        _perform(
            admin_socket_path(data_dir),
            request,
            loopback=socket_path(data_dir),
        )
    )


async def _perform(socket: Path, request: dict[str, Any], *, loopback: Path) -> int:
    """Send one act to the hub and render its answer.

    Args:
        socket: The hub's control socket.
        request: The act.
        loopback: ADR-0084 §1's socket, which an absent control socket is
            diagnosed against — see :func:`_report_no_control_socket`.

    Returns:
        The process exit code.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        # The errno is the third state's evidence, so it is carried rather than
        # collapsed — see :func:`_report_no_control_socket`.
        return await _report_no_control_socket(
            socket, loopback, bound=isinstance(exc, ConnectionRefusedError)
        )
    except OSError as exc:
        print(f"device: cannot reach the hub at {socket}: {exc}", file=sys.stderr)
        return EXIT_RESTART
    # **The decode is inside the guarded block, and so is ``TransportError``.**
    # ``read_frame`` reports a hub that went away mid-exchange as
    # ``ConnectionClosedError`` — the project's own hierarchy, which is neither an
    # ``OSError`` nor a ``ValueError`` — and a reply that does not decode is the
    # same class of failure as one that never arrived. Either escaping would leave
    # a device command printing a traceback where ADR-0083's ruling 4 asks for a
    # sentence and an exit code.
    try:
        async with asyncio.timeout(ADMIN_TIMEOUT.total_seconds()):
            await write_frame(
                writer, json.dumps(request).encode("utf-8"), max_frame_bytes=ADMIN_FRAME_BYTES
            )
            body = await read_frame(
                reader,
                max_frame_bytes=ADMIN_FRAME_BYTES,
                timeout=ADMIN_TIMEOUT,
                idle_timeout=ADMIN_TIMEOUT,
            )
            reply = json.loads(body)
    except (TimeoutError, OSError, ValueError, TransportError) as exc:
        print(f"device: the hub did not answer: {exc}", file=sys.stderr)
        return EXIT_RESTART
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return _render(reply, request["act"])


async def _report_no_control_socket(socket: Path, loopback: Path, *, bound: bool) -> int:
    """Say which of three states an unanswering control socket is, rather than assuming.

    **The socket not answering is ambiguous, and the states want opposite acts**
    (#1441). Every hub binds the control socket (ADR-0298 §4:13), so a silent
    ``admin.sock`` means one of: no hub is running; a hub is running and has not
    opened this door yet; or a hub is running and the socket it bound is gone from
    under it. Reporting the first for all three would send an owner to start a hub
    that was already serving, where the advice either contended for the instance
    lock or did nothing and produced the identical message on the next try.

    **Two facts separate them, and each is read rather than guessed at.**

    The first is the loopback socket. ADR-0124 §2 binds it "whether or not the
    remote listener is", so a hub answering there decides *hub or no hub* outright. The
    instance lock would have been the weaker probe: it is held by the offline tools
    too (``ai-assistant-reembed`` and the rest), so contention names a directory in
    use rather than a hub that is serving.

    The second is ``bound`` — which failure the connect raised. A hub binds this
    socket **before** it opens ADR-0084 §1's door and begins serving it just
    *after* (``hub.py``, ADR-0083 §14.2's "every door binds before any door
    accepts"), and a bound-but-not-yet-serving Unix socket refuses rather than
    accepting. So there is a startup instant in which the loopback door answers and
    this one refuses, and a report that read the loopback probe alone would tell an
    owner whose hub is merely starting that its socket had gone.
    ``ConnectionRefusedError`` means the socket file is there, which that state has
    and a removed socket does not; so the state is named by the errno, at no cost,
    rather than by retrying the connect for a startup window — which would put
    latency on every genuine failure to cover an instant that is already legible.
    The errno is only this sharp because a starting hub unlinks whatever stale file
    is at the path before it binds
    (:meth:`~ai_assistant.service.admin.AdminListener.start`), so a running hub's
    refusing socket is the one it bound.

    Args:
        socket: The control socket that did not answer.
        loopback: ADR-0084 §1's socket, in the same data directory.
        bound: Whether the connect was *refused* rather than finding nothing at the
            path — that is, whether the socket file exists.

    Returns:
        The process exit code.
    """
    if not await _hub_is_serving(loopback):
        print(
            f"device: no hub is listening at {socket}. Device acts are performed by the "
            f"running hub, because revoking a device closes the connections it holds; "
            f"start it with 'ai-assistant-hub' and try again.",
            file=sys.stderr,
        )
        return EXIT_RESTART
    if bound:
        if not _is_socket(socket):
            # A refusal does not mean "a socket that is not serving": connecting to
            # a *regular file* — or a directory — at that path refuses with the same
            # errno. Nothing about that resolves by waiting, so it must not be
            # dressed as the startup instant below.
            print(
                f"device: a hub is running here — it answers at {loopback} — but {socket} "
                f"is not a socket, so nothing can be reached through it. Remove whatever "
                f"is at that path and restart the hub, which binds its control socket "
                f"there.",
                file=sys.stderr,
            )
            return EXIT_DEPLOYMENT
        # Restartable, and by the same question as everything else here: the hub is
        # opening its doors and the next attempt succeeds. It stays true because a
        # starting hub unlinks a stale file at the path before it binds, so this path
        # cannot be reached by a stale file that no retry would clear.
        print(
            f"device: a hub is running here — it answers at {loopback} — but {socket} "
            f"exists and is not answering yet. The hub binds that socket before it opens "
            f"its own door and serves it just afterwards, so this is the instant between "
            f"the two; try again.",
            file=sys.stderr,
        )
        return EXIT_RESTART
    # A deployment fault rather than a restartable one, by
    # :func:`~ai_assistant.service.exits.classify`'s own question: running this
    # again, unchanged, never succeeds. Every hub binds its control socket before it
    # opens its own door, so a serving hub with none has had it removed from under
    # it — or is a build from before ADR-0298, which bound it only with a remote
    # listener — and only restarting that hub moves it.
    print(
        f"device: a hub is running here — it answers at {loopback} — but there is no "
        f"control socket at {socket}. A hub binds it before it opens its own door, so "
        f"it was removed while the hub ran, or the hub predates this command; restart "
        f"the hub and try again.",
        file=sys.stderr,
    )
    return EXIT_DEPLOYMENT


def _is_socket(path: Path) -> bool:
    """Whether what is literally at ``path`` is a socket.

    ``lstat`` rather than :meth:`~pathlib.Path.is_socket`, on both counts: the
    question is what occupies this path, so a symbolic link is answered as a link
    and not as its target; and a failure to read it must not answer "no".

    Args:
        path: The control socket's path.

    Returns:
        ``True`` if a socket is there, and ``True`` when the path cannot be read at
        all — which is the restartable direction, and the honest one: something that
        vanished between the connect and this call is answered by the next attempt,
        not by an operator being told to go and remove it.
    """
    try:
        return stat.S_ISSOCK(path.lstat().st_mode)
    except OSError:
        return True


async def _hub_is_serving(loopback: Path) -> bool:
    """Whether *this user's* hub is accepting on ADR-0084 §1's socket.

    The connection carries no frame and is closed immediately: this is a liveness
    probe on the door, not a request, and the hub treats a peer that hangs up
    before the handshake as the ordinary ending rather than a fault
    (``service/transport.py``). It is bounded by :data:`ADMIN_TIMEOUT` for the same
    reason every other local exchange here is — a wedged hub must not turn a
    diagnostic into a hang.

    **The peer is authenticated from the kernel before the probe counts as
    evidence** (``wire/peer.py``, ADR-0084 §1). Nothing is sent either way, so the
    clause's own "before sending anything" is not what compels it here; the reason
    is that the answer this function's name promises is a claim about *the hub*, and
    a filesystem path is not proof of who is behind it — §1 names bind mounts, ACLs
    and symlinked ancestors as the topology a path check walks wrong. Left
    unauthenticated, another user's process bound at that path would be enough to
    tell an owner their hub's control socket was gone, and to say it with the fatal
    exit code.

    Args:
        loopback: Where the hub listens, given the directory it owns.

    Returns:
        ``True`` only if something accepted *and* runs as this user; ``False`` on a
        refusal, an absence, a stall, a foreign peer, or a platform that cannot say
        whose peer it is. Every one of those failing to ``False`` is the fail-closed
        direction ADR-0084 §1 fixes, and it costs nothing here: ``False`` selects
        the message that names the socket and says to start the hub, which is
        correct advice in each case — a hub that starts takes the instance lock and
        rebinds this socket over whatever was squatting on it.
    """
    try:
        async with asyncio.timeout(ADMIN_TIMEOUT.total_seconds()):
            _, writer = await asyncio.open_unix_connection(str(loopback))
    except TimeoutError, OSError:
        return False
    try:
        raw: socket.socket | None = writer.get_extra_info("socket")
        if raw is None:  # pragma: no cover — asyncio always supplies one here
            return False
        check_peer_is_self(raw)
    except ProtocolError, OSError:
        # ``OSError`` as well as ``ProtocolError``: the uid is read with
        # ``getsockopt``, which can fail on a connection the peer has already torn
        # down, and it is read *after* the connect — outside the handler above. The
        # docstring's promise is ``False`` whenever peer identity cannot be
        # established, and a traceback out of a diagnostic is what ADR-0083's ruling
        # 4 asks a sentence and an exit code in place of.
        return False
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return True


def _render(reply: Any, act: str) -> int:
    """Print what the hub did, and say what the owner must do next.

    Args:
        reply: The hub's answer, decoded.
        act: Which act was asked for.

    Returns:
        The process exit code.
    """
    if not isinstance(reply, dict) or not reply.get("ok"):
        reason = reply.get("error") if isinstance(reply, dict) else "an answer it cannot read"
        print(f"device: the hub refused the act: {reason}", file=sys.stderr)
        return EXIT_DEPLOYMENT
    if act == ENROL:
        if reply.get("rotated"):
            print("The previous enrolment was revoked and its connections were closed.")
        print(f"Device:     {reply['overlay_identity']}")
        print(f"Hub:        {reply['hub_identity']}")
        print(f"Credential: {reply['credential']}")
        print()
        print("Give the device both values. The credential is shown once and never again:")
        print("the hub keeps only a verifier it cannot be recovered from.")
        return EXIT_OK
    if act == REVOKE:
        _render_revocation(reply)
        return EXIT_OK
    held = ", ".join(reply.get("roles", [])) or "none"
    if act == RESTORE:
        if reply.get("restored"):
            print("Restored. The gateway's next naming of it is accepted.")
        else:
            print("That registration is already live; nothing changed.")
        print(f"Roles: {held}")
        return EXIT_OK
    if act in (ASSIGN, WITHDRAW):
        if not reply.get("changed"):
            print("Nothing changed.")
        print(f"Roles: {held}")
        return EXIT_OK
    _render_listing(reply)
    return EXIT_OK


def _render_revocation(reply: dict[str, Any]) -> None:
    """Print what a revocation did, of a whole device or of one registration."""
    if "revoked" in reply:
        if reply["revoked"]:
            print("Revoked. That gateway's naming of it is refused until you restore it.")
        else:
            print("That device had no live registration under that gateway; nothing changed.")
        return
    registrations = int(reply.get("registrations", 0))
    roles = ", ".join(reply.get("roles", []))
    if not reply.get("enrolment") and not registrations and not roles:
        print("That device had no live enrolment, registration or role; nothing changed.")
        return
    if reply.get("enrolment"):
        print("Its enrolment is revoked: its credential now verifies against nothing and its")
        print("connections are closed.")
    if registrations:
        print(f"{registrations} registration(s) under a gateway revoked.")
    if roles:
        print(f"Roles cleared: {roles}.")
    print("What it already received, it keeps — revocation is prospective.")


def _render_listing(reply: dict[str, Any]) -> None:
    """Print the roster, the enrolments and the registrations, each saying what it omits.

    Each section is bounded and says so rather than leaving it to be inferred: the
    record keeps every revocation, so a long-lived hub has more history than one
    listing carries, and a listing that stopped silently would read as a complete
    record that it is not.
    """
    hub_identity = reply.get("hub_identity")
    print(f"Hub: {hub_identity or 'no overlay identity (no remote listener configured)'}")
    devices = reply.get("devices", [])
    print("Devices:")
    if not devices:
        print("  None yet.")
    for device in devices:
        roles = ", ".join(device["roles"]) or "no role"
        state = "" if device["admitted"] else "  (not admitted)"
        print(f"  {device['device']}  {device['kind']}  {roles}{state}")
    _omitted(reply.get("devices_omitted", 0), "device")
    enrolments = reply.get("enrolments", [])
    print("Enrolments:")
    if not enrolments:
        print("  No device has ever been enrolled at this hub.")
    for one in enrolments:
        state = "live" if one["live"] else f"revoked {one['revoked_at']}"
        print(f"  {one['overlay_identity']}  enrolled {one['enrolled_at']}  {state}")
    _omitted(reply.get("enrolments_omitted", 0), "enrolment")
    registrations = reply.get("registrations", [])
    print("Registrations:")
    if not registrations:
        print("  No gateway has named a machine yet.")
    for one in registrations:
        state = "live" if one["live"] else f"revoked {one['revoked_at']}"
        print(
            f"  {one['device']}  under {one['gateway']}  registered {one['registered_at']}  {state}"
        )
    _omitted(reply.get("registrations_omitted", 0), "registration")


def _omitted(count: int, what: str) -> None:
    """Say how many older rows a bounded section did not show."""
    if count:
        print(f"  ({count} older {what}(s) not shown; the newest are listed above.)")
