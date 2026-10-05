"""The hub's side of the wire's device seam: who each request is for (ADR-0298 §2, §4).

:class:`~ai_assistant.wire.server.DeviceRoster` is a local ``Protocol`` in ``wire``,
implemented here over the roster DS1 keeps (ADR-0298 §10:7), as
:class:`~ai_assistant.wire.server.Admission` is implemented over the enrolments.
**Passing it to a listener is the cutover** (§9:3): without one the wire server
serves every request as the hub's own machine, and with one it decides each
request's device from the connection and the frame's ``acting_for``, so the route
table's checks and the engine's start to refuse.

**What decides the requesting device** (§2:1, §3, §4):

* **No ``acting_for``:** the connecting device. On the loopback socket that is
  ``hub``, which holds every role (§3:2); on the remote listener it is the enrolled
  device the overlay agent named, with the roles the owner gave it (§4:1).
* **``acting_for``:** the machine the gateway named, accepted and — the first time —
  registered under that gateway (§4:2), with that machine's own roles (§8:1). The
  gateway is the connecting device: an enrolled hub device on the remote listener,
  and ``hub`` for a gateway on the hub's own machine (§4:4).

**A connection admitted under the hub's own overlay identity is refused every
request** (issue #2726). A record written before ADR-0298 can hold a live
enrolment of that identity, and an upgrade revokes nothing on the owner's behalf
(ADR-0124 §6, §8), so ADR-0124's two facts still admit the connection. But §3:3
has the hub's own machine reach the hub "through the local socket … and through
nothing else", and §6:2's first reason names "the hub's own overlay identity", so
each request on such a connection is refused with that reason, and the identity is
no device a set may name (§4:11). The hub logs ``device_hub_identity_enrolled`` at
every start until the owner revokes it, which the cutover's procedure does first.

**Synchronous, for the seam's reason**: the decision, the wire server's check and
the dispatch they allow have no suspension point between them, so no revocation
lands between a role read and the request it allowed. Every answer here is read
from :class:`~ai_assistant.service.enrolment.DeviceRegistry`'s live view; a first
naming writes one row, inside the same step.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import HUB_DEVICE_ID, HUB_REQUESTING_DEVICE, RequestingDevice
from ai_assistant.service.enrolment import NamingRefusal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.service.enrolment import DeviceRegistry


#: What a refused naming tells the device, by the roster's reason. Every one is
#: §6:2's first reason, ``NOT_ACCEPTED``; the sentence says which, so the owner can
#: tell a revoked registration from a full gateway. No name is quoted, so each fits
#: :data:`~ai_assistant.core.errors.DEVICE_REFUSAL_MESSAGE_BYTES` by construction.
_NAMING_REFUSED: Final[Mapping[NamingRefusal, str]] = {
    NamingRefusal.REVOKED: (
        "the owner revoked this device's registration under this gateway; only the "
        "owner's act at the hub restores it"
    ),
    NamingRefusal.RESERVED: (
        "no gateway may name the hub's own machine; it reaches the hub on its own socket"
    ),
    NamingRefusal.BOUND: (
        "this gateway already holds as many registrations as the hub accepts under one "
        "gateway; the owner can revoke one it no longer needs"
    ),
}

#: What a connection admitted under the hub's own overlay identity is told.
_HUB_IDENTITY_REFUSED: Final = (
    "this connection is the hub's own overlay identity, which reaches the hub only "
    "through its local socket; the owner should revoke this enrolment at the hub"
)


class HubRoster:
    """The roster as the wire server reads it (ADR-0298 §10:7).

    Implements :class:`~ai_assistant.wire.server.DeviceRoster`. One per hub, shared
    by both listeners, because both read the one roster (§4:1).
    """

    def __init__(self, registry: DeviceRegistry) -> None:
        """Read the roster through the registry's live view.

        A first naming's registration is dated by the wall clock, in UTC, read here:
        the instant is a record for the owner to read (§4:6) and decides nothing, so
        there is no injected clock to guard.

        Args:
            registry: The enrolments and the roster, and where an act takes effect.
        """
        self._registry = registry

    def requesting_device(self, *, connecting: str, acting_for: str | None) -> RequestingDevice:
        """Decide a request's requesting device (ADR-0298 §2:1).

        Args:
            connecting: The connecting device: the admitted overlay identity on the
                remote listener, ``hub`` on the loopback socket.
            acting_for: The frame's ``acting_for``, already held to §1:3 and never
                ``hub`` (the wire server refuses that first), or ``None``.

        Returns:
            The requesting device, with the roles the roster records for it now.

        Raises:
            DeviceRefusedError: With ``NOT_ACCEPTED`` where the connection is the
                hub's own overlay identity (#2726), or the hub does not accept the
                name under that gateway (§6:2). A registration a first naming made
                stands either way (§6:1).
        """
        if self._is_hub_identity(connecting):
            raise DeviceRefusedError(_HUB_IDENTITY_REFUSED, reason=DeviceRefusal.NOT_ACCEPTED)
        if acting_for is None:
            if connecting == HUB_DEVICE_ID:
                return HUB_REQUESTING_DEVICE
            return self._device(connecting)
        verdict = self._registry.accept_naming(connecting, acting_for, now=datetime.now(UTC))
        if verdict.refusal is not None:
            raise DeviceRefusedError(
                _NAMING_REFUSED[verdict.refusal], reason=DeviceRefusal.NOT_ACCEPTED
            )
        return self._device(acting_for)

    def knows(self, device_id: str) -> bool:
        """Whether the hub knows an id as a device (ADR-0298 §4:11).

        Args:
            device_id: An id a request names.

        Returns:
            Whether it is ``hub``, an enrolled hub device whose enrolment is live, or
            a browser device with a live registration — never the hub's own overlay
            identity, which is the hub's own machine and is named ``hub`` (§3:1).
        """
        return not self._is_hub_identity(device_id) and self._registry.is_known(device_id)

    def _device(self, device_id: str) -> RequestingDevice:
        """One device other than the hub's own machine, with its roles as recorded."""
        return RequestingDevice(device_id=device_id, roles=self._registry.roles_of(device_id))

    def _is_hub_identity(self, device_id: str) -> bool:
        """Whether an id is the hub's own overlay identity, where the hub has one."""
        hub_identity = self._registry.hub_identity
        return hub_identity is not None and device_id == hub_identity


__all__ = ["HubRoster"]
