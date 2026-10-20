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

**Through the sign-in door the sentence is a person's, not an operator's** (ADR-0327
§10). The person there holds no machine of the hub's and can run none of its
commands; the roles of the hosted browser device are given at the hub "as a setup act
performed only at the person's request" (§10:6). So the sentence says what is not set
up yet and who can set it up, and the command stays on the listeners whose reader can
run it.
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


#: What a person through the sign-in door reads for each reason (ADR-0327 §10). The
#: device is the hosted browser device, which is "the web" rather than a machine, so no
#: sentence names it; and the remedy is the setup's, which is an act at the person's
#: request by whoever set their assistant up (§10:6), so each sentence names them.
_HOSTED_DETAILS: Final[Mapping[DeviceRefusal, str]] = MappingProxyType(
    {
        DeviceRefusal.NO_ROLE: (
            "Your assistant isn't set up to take requests from this page yet. "
            "The person who set it up for you can turn that on."
        ),
        DeviceRefusal.NOT_ALLOWED: (
            "Your assistant isn't set up to let this page do that yet. "
            "The person who set it up for you can turn that on."
        ),
        DeviceRefusal.NOT_ACCEPTED: (
            "Your assistant isn't accepting requests from this page at the moment. "
            "The person who set it up for you can let this page back in."
        ),
    }
)


def refusal_detail(
    reason: DeviceRefusal, *, device: str | None, gateway: str | None, hosted: bool = False
) -> str:
    """The plain sentence the page shows for one refusal, with the remedy in it.

    **Who reads it decides how it is said.** On the loopback and remote browser
    listeners the reader is the owner at a machine of their own, who can run the
    command that changes the answer, so the sentence names the device and the
    command. Through the sign-in door (ADR-0327) the reader is a person on their
    phone, who holds no machine of the hub's and has never heard of a device id: the
    sentence says what is not set up and who can set it up, and names no command, no
    device and no machine. The three reasons stay three sentences on both, so the
    person can still pass on which of them it was (ADR-0298 §6:2).

    Args:
        reason: Why the hub refused the request (ADR-0298 §6:2).
        device: The device the request was made for, as the hub knew it: the browser
            device the gateway named, or the gateway's own device where it named none.
            ``None`` where the gateway could not name it.
        gateway: The gateway's own device as the hub knows it: ``hub`` for a gateway
            on the hub's own machine, and otherwise that machine's overlay identity.
            ``None`` where the gateway could not name it.
        hosted: Whether the request came through the hosted listener, behind the
            sign-in edge (ADR-0327 §10).

    Returns:
        The sentence.
    """
    if hosted:
        return _HOSTED_DETAILS[reason]
    named = _UNNAMED_DEVICE if device is None else device
    if reason is DeviceRefusal.NO_ROLE:
        return (
            f"This browser is device {named}, which has no role yet. On the hub's "
            f"machine, 'ai-assistant-device assign {named} commands' lets it ask and "
            f"manage, and 'assistant my-devices --add {named}' lets it take part in "
            f"conversations."
        )
    if reason is DeviceRefusal.NOT_ALLOWED:
        return (
            f"This browser is device {named}, and its roles do not allow this. Asking "
            f"and managing need the commands role: on the hub's machine, "
            f"'ai-assistant-device assign {named} commands' gives it. A conversation is "
            f"read and written only by its own devices, and starting one needs this "
            f"device in your devices: 'assistant my-devices --add {named}' adds it."
        )
    via = _UNNAMED_GATEWAY if gateway is None else gateway
    return (
        f"This browser is device {named}, which the hub does not accept through this "
        f"gateway. That is so when the owner revoked it here, when it is the hub's own "
        f"machine (open the gateway's loopback address on that machine instead), or "
        f"when this gateway has named as many devices as the hub allows. On the hub's "
        f"machine, 'ai-assistant-device list' shows which, and 'ai-assistant-device "
        f"restore {named} --gateway {via}' restores a revoked one."
    )


__all__ = ["REFUSAL_FAULTS", "refusal_detail"]
