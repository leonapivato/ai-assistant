"""Which device an interface adapter is, as ADR-0296 §1 counts devices: the machine.

Shared by the command line and the browser gateway, so the two name the hub's own
machine by one rule (ADR-0293 §4:1's message is "from one of the conversation's
devices", and a device is the machine, not the adapter). Lifted from the command
line's chat (ADR-0293 lane D1) when the gateway came to need the same rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire import LoopbackDestination, RemoteDestination, destination

if TYPE_CHECKING:
    from ai_assistant.core.config import Settings

#: The device the hub's own machine is (ADR-0296 §1:7): a command line on the local
#: socket is the user at that machine, and so is a browser on a gateway's loopback
#: listener there. The id itself is ADR-0298 §3's, which is still a proposal (#2698)
#: and is followed here ahead of it — a stable name that does not change when the
#: remote listener is turned on or off.
HUB_DEVICE: Final = "hub"


def this_device(settings: Settings, *, named: str | None) -> str:
    """The device this machine is, toward the hub ``settings`` reaches.

    On the hub's own machine it is :data:`HUB_DEVICE`, whatever ``named`` says
    otherwise, since an adapter there cannot be another machine. On another machine it
    is that machine's overlay identity, which no adapter has a way to read for itself
    yet, so it must be ``named``.

    Args:
        settings: The configuration that says where the hub is.
        named: The device the caller was told this machine is, or ``None``.

    Returns:
        The device's id.

    Raises:
        ConfigurationError: If the destination cannot be read from configuration, if
            ``named`` names another machine on the hub's own, or if it is missing for a
            hub on another machine.
    """
    where = destination(
        data_dir=settings.data_dir,
        remote_address=settings.remote_hub_address,
        remote_port=settings.remote_hub_port,
    )
    match where:
        case LoopbackDestination():
            if named is not None and named != HUB_DEVICE:
                msg = (
                    f"on the hub's own machine this device is '{HUB_DEVICE}', so --device "
                    "cannot name another"
                )
                raise ConfigurationError(msg)
            return HUB_DEVICE
        case RemoteDestination():
            if named is None:
                msg = (
                    "the hub is on another machine, so name this device with --device: "
                    "this machine's overlay identity, as the hub's enrolment of it shows"
                )
                raise ConfigurationError(msg)
            return named
        case _:  # pragma: no cover — the union is closed
            assert_never(where)
