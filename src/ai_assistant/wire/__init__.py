"""The local API: the envelope, the framing, the codec, the errors, the client.

A top-level package rather than a corner of an existing one, and ADR-0084 §6
derives that from a clause of ADR-0083 that is easy to miss. ADR-0083 §8 rules
that "``service`` may import ``app``… and ``core``; **nothing may import
``service``**", so the client cannot live beside the server — ``interfaces`` would
then have to import ``service``.

    **A new top-level package — ``ai_assistant/wire/`` — holds the envelope, the
    framing, the codec, the error mapping, and the client that implements the
    promoted Protocol.** It depends on ``core`` and nothing else. ``service``
    imports it for the server half; ``interfaces`` imports it for the client half;
    nothing imports ``service``, so ADR-0083 §8 stands unamended.

**"Depends on ``core`` and nothing else" is enforced mechanically**, by a
``lint-imports`` contract in ``pyproject.toml`` rather than by this docstring — and
it is what decides #571: the canonical encoder cannot be shared with
``orchestration``'s copy in either direction, so :mod:`ai_assistant.wire.codec` is
a second encoder held to ADR-0087 §5's vectors, which §7 licenses in as many words.

The remote leg is one bind away on the wire and one ratified decision away in
fact. The envelope carries a version, the handshake has a credential slot, and the
client is stateless — the three expensive retrofits are bought. What is **not**
bought, and is named here so nobody assumes it, is authorisation to move user data
off the device: a non-loopback hop engages ADR-0017 §1 and owes its own ratified
egress decision (ADR-0084 §1, §11).
"""

from __future__ import annotations

from ai_assistant.wire.address import (
    SOCKET_FILENAME,
    SOCKET_MODE,
    check_socket_path,
    socket_path,
    sun_path_limit,
)
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.codec import ENVELOPE_RESERVE_BYTES, canonical_payload
from ai_assistant.wire.envelope import PROTOCOL_VERSION, Envelope, FrameKind
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    HubUnavailableError,
    ProtocolError,
    TransportError,
    UndecodableFrameError,
)
from ai_assistant.wire.server import ConnectionLimits, serve_connection

__all__ = [
    "ENVELOPE_RESERVE_BYTES",
    "PROTOCOL_VERSION",
    "SOCKET_FILENAME",
    "SOCKET_MODE",
    "ConnectionClosedError",
    "ConnectionLimits",
    "Envelope",
    "FrameKind",
    "HubEngineClient",
    "HubUnavailableError",
    "ProtocolError",
    "TransportError",
    "UndecodableFrameError",
    "canonical_payload",
    "check_socket_path",
    "serve_connection",
    "socket_path",
    "sun_path_limit",
]
