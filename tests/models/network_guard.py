"""Deny the network inside a block, so "offline" is asserted rather than assumed.

ADR-0024's whole claim is that no runtime path fetches a model artifact and that
a build from an sdist finds one already present. Both are claims about something
*not* happening, and a test that merely observes the right answer cannot tell a
cached fetch from no fetch at all. This guard turns the absence into an
assertion: any attempt to connect a socket, or to resolve a name, fails loudly
and is attributed to the code under test.

Connection is denied rather than socket *construction*, deliberately: the running
event loop and the standard library create sockets for their own reasons, and
refusing those would fail tests for something other than egress. Nothing reaches
a remote host without ``connect``, ``connect_ex`` or a name lookup.
"""

from __future__ import annotations

import contextlib
import socket
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Iterator


class NetworkUsedError(AssertionError):
    """Raised in place of an outbound connection while the network is denied."""


def _deny(*args: Any, **kwargs: Any) -> NoReturn:
    msg = "the network was used inside a block that denies it"
    raise NetworkUsedError(msg)


@contextlib.contextmanager
def network_denied() -> Iterator[None]:
    """Deny outbound connections and name resolution for the duration of the block.

    Yields:
        None.
    """
    saved = {
        (socket.socket, "connect"): socket.socket.connect,
        (socket.socket, "connect_ex"): socket.socket.connect_ex,
        (socket, "create_connection"): socket.create_connection,
        (socket, "getaddrinfo"): socket.getaddrinfo,
    }
    for (target, name), _ in saved.items():
        setattr(target, name, _deny)
    try:
        yield
    finally:
        for (target, name), original in saved.items():
            setattr(target, name, original)
