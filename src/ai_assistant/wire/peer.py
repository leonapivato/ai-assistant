"""The client authenticates the hub from the kernel, not from the filesystem.

ADR-0084 §1 spends most of its length on the data directory's modes and then says
what actually closes the hole:

    Filesystem checks are a walk over topology the operator controls, and a walk
    can be wrong — a bind mount, an ACL, a symlinked ancestor. So the client does
    not rely on them alone: **after ``connect()`` and before sending anything, the
    client reads the peer's credentials from the kernel and refuses unless the
    server's uid is its own.**

That is "a direct check on *who is actually on the other end*, not an inference
from who could have written where, and it is free of the time-of-check
time-of-use gap a pre-connect ``stat`` of the socket would have". A replaced socket
belonging to another user is refused at that point whatever the directory modes
were.

**The rule is the check, not the syscall, because the syscall is not portable.**
Linux exposes it as ``SO_PEERCRED``; macOS and the BSDs expose the same fact as
``getpeereid()``, which CPython does not surface. ADR-0084 §1 fixes the direction
of that gap: "**A platform offering neither cannot host this client**, and that is
the fail-closed direction on purpose — silently skipping the check where the call
is missing would leave exactly the deployments with the weakest filesystem
guarantees running with no server authentication at all."

**This does not contradict §2's declining of ``SO_PEERCRED``**, because it runs in
the other direction. §2 declines it as the *server* authorising the *client*, where
it would re-derive what the socket mode already guarantees. Here it is the *client*
authenticating the *server*, which nothing else establishes.
"""

from __future__ import annotations

import os
import socket
import struct
from typing import Final

from ai_assistant.wire.errors import ProtocolError

#: ``struct ucred`` — ``{ pid_t pid; uid_t uid; gid_t gid; }``, three native 32-bit
#: integers, but not three of the same kind: ``pid_t`` is signed while ``uid_t`` and
#: ``gid_t`` are **unsigned**. Reading all three as ``i`` costs nothing until a uid
#: reaches 2\ :sup:`31` — directory-service id mapping and some container uid
#: remappings do — and then it decodes as a negative number that equals neither
#: ``0`` nor any real euid, so the checks below refuse the user's own hub or agent.
#: ``struct.calcsize`` is 12 either way, so only the value would have been wrong.
_UCRED: Final[str] = "iII"


def peer_uid(sock: socket.socket) -> int:
    """Read the uid on the other end of a connected Unix socket.

    Args:
        sock: The connected socket.

    Returns:
        The peer process's effective uid.

    Raises:
        ProtocolError: If this platform exposes no peer-credential mechanism
            CPython surfaces. Fail closed: a client that cannot authenticate the
            server must not proceed as though it had.
    """
    if not hasattr(socket, "SO_PEERCRED"):
        msg = (
            "this platform exposes no peer-credential call CPython surfaces, so a client "
            "cannot verify that the hub on the other end of the socket runs as this user; "
            "refusing rather than connecting unauthenticated (ADR-0084 §1)"
        )
        raise ProtocolError(msg)
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize(_UCRED))
    _pid, uid, _gid = struct.unpack(_UCRED, raw)
    return int(uid)


def check_peer_is_self(sock: socket.socket) -> None:
    """Refuse a hub that is not running as this user (ADR-0084 §1).

    Args:
        sock: The connected socket, before anything has been sent on it.

    Raises:
        ProtocolError: If the peer's uid is not this process's, or the platform
            cannot say. The first case is the one the check exists for: a socket
            another local user unlinked and rebound in place, which the CLI would
            otherwise hand the user's utterance to — Tier 0/1 content going to
            another user's process (ADR-0004 §1).
    """
    mine = os.geteuid()
    theirs = peer_uid(sock)
    if theirs != mine:
        msg = (
            f"the process listening on this socket runs as uid {theirs}, not as uid {mine}; "
            f"refusing to send anything to it — another user may have replaced the hub's "
            f"socket, and nothing about the directory's mode would prevent that"
        )
        raise ProtocolError(msg)
