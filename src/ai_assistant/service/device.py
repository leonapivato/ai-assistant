"""The owner's device acts, at the hub's own machine (ADR-0124 §6, §8).

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
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from typing import TYPE_CHECKING, Any

from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.admin import ADMIN_FRAME_BYTES, ADMIN_TIMEOUT, ENROL, LIST, REVOKE
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.wire.address import admin_socket_path
from ai_assistant.wire.errors import TransportError
from ai_assistant.wire.framing import read_frame, write_frame

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_DESCRIPTION = """
Enrol, revoke and list the devices this hub admits over its remote listener.

Run it on the hub's own machine, with the hub running: enrolment and revocation
are acts the hub performs on its own record, and a revocation closes the
connections the device currently holds.

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
    revoke = acts.add_parser(REVOKE, help="revoke a device's enrolment")
    revoke.add_argument("identity", help="the device's overlay identity")
    acts.add_parser(LIST, help="show every enrolment this hub has recorded")
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
    if arguments.act in (ENROL, REVOKE):
        request["identity"] = arguments.identity
    return asyncio.run(_perform(admin_socket_path(settings.data_dir), request))


async def _perform(socket: Path, request: dict[str, Any]) -> int:
    """Send one act to the hub and render its answer.

    Args:
        socket: The hub's control socket.
        request: The act.

    Returns:
        The process exit code.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket))
    except FileNotFoundError, ConnectionRefusedError:
        print(
            f"device: no hub is listening at {socket}. Device acts are performed by the "
            f"running hub, because revoking a device closes the connections it holds; "
            f"start it with 'ai-assistant-hub' and try again.",
            file=sys.stderr,
        )
        return EXIT_RESTART
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
        if reply.get("revoked"):
            print("Revoked. Its credential now verifies against nothing and its connections")
            print("are closed. What it already received, it keeps — revocation is prospective.")
        else:
            print("That device had no live enrolment; nothing changed.")
        return EXIT_OK
    print(f"Hub: {reply['hub_identity']}")
    devices = reply.get("devices", [])
    if not devices:
        print("No device has ever been enrolled at this hub.")
        return EXIT_OK
    for device in devices:
        state = "live" if device["live"] else f"revoked {device['revoked_at']}"
        print(f"  {device['overlay_identity']}  enrolled {device['enrolled_at']}  {state}")
    # Said rather than left to be inferred: the record keeps every revocation, so a
    # long-lived hub has more history than one listing carries, and a listing that
    # stopped silently would read as a complete record that it is not.
    omitted = reply.get("omitted", 0)
    if omitted:
        print(f"  ({omitted} older enrolment(s) not shown; the newest are listed above.)")
    return EXIT_OK
