"""What the page is told when the hub refuses a request for its device (ADR-0298 §6).

The hub refuses a request it checks against a device's roles with one error,
:class:`~ai_assistant.core.errors.DeviceRefusedError`, carrying one of three reasons
(§6:2), so that the owner can tell "this phone was revoked" from "this phone has no
role yet" from "this phone has no role for that". A gateway that flattened all three
into ``assistant-declined`` would leave the owner reading the hub's terse message and
guessing what to do on which machine. So each reason is its own fault name, and the
detail is a plain sentence of this gateway's own that names the device and the act
that would change the answer.

**One fault name per reason, rather than one name and a member.** The page already
reads a condition off the ``fault`` member and nothing else, and its ``FAULTS`` table
gives each name its headline. A distinct name keeps the reason machine-readable to the
page without widening the body a fault may carry.

**The detail is this gateway's own text, never the hub's message.** The hub's message
is accurate, but it is written for a log; and on the spoken path ADR-0200 §8 bars a
handler from surfacing an exception message it did not author. A sentence per reason,
with the device filled in, is both what the owner can act on and what every path may
write.

**The status is ``422``.** The hub received the request and declined it, and it
declined it before changing anything (§6:1), which is ADR-0168 §9's "a request the
hub received and declined" exactly. So the page's classification of a relay failure
by status, which reads ``422`` as that and nothing else, is unchanged.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import DeviceRefusal

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Mapping

#: The fault name the page reads for each reason (ADR-0298 §6:2).
REFUSAL_FAULTS: Final[Mapping[DeviceRefusal, str]] = MappingProxyType(
    {
        DeviceRefusal.NOT_ACCEPTED: "device-not-accepted",
        DeviceRefusal.NO_ROLE: "device-without-role",
        DeviceRefusal.NOT_ALLOWED: "device-not-allowed",
    }
)

#: What a sentence calls a device the gateway could not name.
_UNNAMED_DEVICE: Final = "<this machine's overlay identity>"

#: What a sentence calls a gateway whose own device it could not name.
_UNNAMED_GATEWAY: Final = "<the gateway machine's overlay identity>"


def refusal_detail(reason: DeviceRefusal, *, device: str | None, gateway: str | None) -> str:
    """The plain sentence the page shows for one refusal, with the remedy in it.

    Args:
        reason: Why the hub refused the request (ADR-0298 §6:2).
        device: The device the request was made for, as the hub knew it: the browser
            device the gateway named, or the gateway's own device where it named none.
            ``None`` where the gateway could not name it.
        gateway: The gateway's own device as the hub knows it: ``hub`` for a gateway
            on the hub's own machine, and otherwise that machine's overlay identity.
            ``None`` where the gateway could not name it.

    Returns:
        The sentence.
    """
    named = _UNNAMED_DEVICE if device is None else device
    if reason is DeviceRefusal.NO_ROLE:
        return (
            f"This browser is device {named}, which holds no role. On the hub's machine, "
            f"'ai-assistant-device assign {named} commands' lets it ask and manage, and "
            f"'assistant my-devices --add {named}' lets it take part in conversations."
        )
    if reason is DeviceRefusal.NOT_ALLOWED:
        return (
            f"This browser is device {named}, whose roles do not allow this. Asking and "
            f"managing need the commands role, which 'ai-assistant-device assign {named} "
            f"commands' gives on the hub's machine; a conversation is read and written "
            f"only by its own devices, and starting one needs this device in my devices."
        )
    via = _UNNAMED_GATEWAY if gateway is None else gateway
    return (
        f"This browser is device {named}. The hub refuses it from this gateway when the "
        f"owner revoked it here, when it is the hub's own machine (open the gateway's "
        f"loopback address on that machine instead), or when this gateway has named as "
        f"many devices as the hub allows. On the hub's machine, 'ai-assistant-device "
        f"list' shows which, and 'ai-assistant-device restore {named} --gateway {via}' "
        f"restores a revoked one."
    )


__all__ = ["REFUSAL_FAULTS", "refusal_detail"]
