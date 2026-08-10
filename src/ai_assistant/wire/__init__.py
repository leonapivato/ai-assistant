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

The remote leg was one bind away on the wire and one ratified decision away in
fact; ADR-0124 is that decision, and both halves of it now exist. The envelope
carried a version, the handshake had a credential slot, and the client was
stateless — those three retrofits, bought in advance by ADR-0084, are what let the
hop add no member, change no encoding and move no version (ADR-0124 §9). What the
hop does **not** authorise is named where it is decided rather than here: no second
hub, no dialled spoke, and no delivery seam for proactivity (ADR-0124 §10).
"""

from __future__ import annotations

from ai_assistant.wire.address import (
    SOCKET_FILENAME,
    SOCKET_MODE,
    HubDestination,
    LoopbackDestination,
    RemoteDestination,
    check_remote_address,
    check_socket_path,
    destination,
    socket_path,
    sun_path_limit,
)
from ai_assistant.wire.client import HubClient, HubEngineClient
from ai_assistant.wire.codec import ENVELOPE_RESERVE_BYTES, canonical_payload
from ai_assistant.wire.enrolment import (
    Enrolment,
    read_enrolment,
    remove_enrolment,
    store_enrolment,
)
from ai_assistant.wire.envelope import PROTOCOL_VERSION, Envelope, FrameKind
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    CredentialNotSupportedError,
    HubIdentityMismatchError,
    HubUnavailableError,
    IncompleteEnrolmentError,
    NotEnrolledError,
    OverlayIdentityUnavailableError,
    ProtocolError,
    TransportError,
    UndecodableFrameError,
)
from ai_assistant.wire.overlay import OverlayAgent, local_agent
from ai_assistant.wire.remote import RemoteHubEngineClient
from ai_assistant.wire.server import ConnectionLimits, serve_connection

__all__ = [
    "ENVELOPE_RESERVE_BYTES",
    "PROTOCOL_VERSION",
    "SOCKET_FILENAME",
    "SOCKET_MODE",
    "ConnectionClosedError",
    "ConnectionLimits",
    "CredentialNotSupportedError",
    "Enrolment",
    "Envelope",
    "FrameKind",
    "HubClient",
    "HubDestination",
    "HubEngineClient",
    "HubIdentityMismatchError",
    "HubUnavailableError",
    "IncompleteEnrolmentError",
    "LoopbackDestination",
    "NotEnrolledError",
    "OverlayAgent",
    "OverlayIdentityUnavailableError",
    "ProtocolError",
    "RemoteDestination",
    "RemoteHubEngineClient",
    "TransportError",
    "UndecodableFrameError",
    "canonical_payload",
    "check_remote_address",
    "check_socket_path",
    "destination",
    "local_agent",
    "read_enrolment",
    "remove_enrolment",
    "serve_connection",
    "socket_path",
    "store_enrolment",
    "sun_path_limit",
]
