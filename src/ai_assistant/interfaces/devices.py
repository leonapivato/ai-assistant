"""Which device an interface adapter is, as ADR-0296 §1 counts devices: the machine.

Shared by the command line and the browser gateway, so the two name the hub's own
machine by one rule (ADR-0293 §4:1's message is "from one of the conversation's
devices", and a device is the machine, not the adapter). Lifted from the command
line's chat (ADR-0293 lane D1) when the gateway came to need the same rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire import (
    LoopbackDestination,
    OverlayIdentityUnavailableError,
    RemoteDestination,
    destination,
)

if TYPE_CHECKING:
    from ai_assistant.core.config import Settings
    from ai_assistant.wire import OverlayAgent

#: The device the hub's own machine is (ADR-0296 §1:7): a command line on the local
#: socket is the user at that machine, and so is a browser on a gateway's loopback
#: listener there. The id itself is ADR-0298 §3's, which is still a proposal (#2698)
#: and is followed here ahead of it — a stable name that does not change when the
#: remote listener is turned on or off.
HUB_DEVICE: Final = "hub"


async def this_device(settings: Settings, *, named: str | None, agent: OverlayAgent | None) -> str:
    """The device this machine is, toward the hub ``settings`` reaches.

    On the hub's own machine it is :data:`HUB_DEVICE`, whatever ``named`` says
    otherwise, since an adapter there cannot be another machine. On another machine it
    is that machine's overlay identity: ``named`` where the caller was told it, and
    otherwise read from this machine's own overlay agent — the stable identifier the
    hub's enrolment recorded for this machine, since the hub asked the overlay who
    this machine is and the agent here answers that question about itself with the
    same value (:meth:`~ai_assistant.wire.overlay.OverlayAgent.own_identity`).

    **A ``named`` device wins, and the agent is not asked.** Naming is the fallback for
    an agent that cannot answer, so consulting the agent to check a name would make
    the fallback depend on what it falls back from. The name is not this adapter's to
    authenticate either way: the hub decides which device a message may be written
    from, by the conversation's devices and the device's roles (ADR-0296 §2).

    Args:
        settings: The configuration that says where the hub is.
        named: The device the caller was told this machine is, or ``None``.
        agent: This machine's overlay agent, asked only where the hub is on another
            machine and nothing is ``named``; ``None`` where the caller has none.

    Returns:
        The device's id.

    Raises:
        ConfigurationError: If the destination cannot be read from configuration, if
            ``named`` names another machine on the hub's own, or if the hub is on
            another machine, nothing is ``named`` and the agent is absent or will not
            say which node this machine is.
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
            if named is not None:
                return named
            return await _own_identity(agent)
        case _:  # pragma: no cover — the union is closed
            assert_never(where)


async def _own_identity(agent: OverlayAgent | None) -> str:
    """This machine's overlay identity, or a refusal that names the fallback.

    Raises:
        ConfigurationError: If there is no agent to ask, or it will not say.
    """
    fallback = (
        "name this device with --device: this machine's overlay identity, as the hub's "
        "enrolment of it shows"
    )
    if agent is None:
        msg = f"the hub is on another machine and no overlay agent is at hand, so {fallback}"
        raise ConfigurationError(msg)
    try:
        return await agent.own_identity()
    except OverlayIdentityUnavailableError as exc:
        msg = (
            f"the hub is on another machine, and this machine's overlay agent would not "
            f"say which node this machine is ({exc}); {fallback}"
        )
        raise ConfigurationError(msg) from exc
