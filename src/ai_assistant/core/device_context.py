"""The two device context values ADR-0298 carries outside every signature.

**The requesting device** (ADR-0298 §2) is the device a request is served for. The
wire server decides it before dispatching a request and sets it here for the
request's duration — for a streamed request, the whole stream (§2:2) — and the
engine reads it here, so no ``AssistantEngine`` method gains a device argument.
Where nothing has set it, as for a caller inside the hub's own process, the
requesting device is the hub's own machine (§2:5).

**The outbound name** (ADR-0298 §1:5) is the browser device a gateway relays a call
for. The gateway sets it around one ``AssistantEngine`` call — for a streamed call,
around the whole iteration — and the wire client writes the value it holds into the
``request`` frame's ``acting_for`` member when it writes that frame.

**The two are distinct values and never read for each other** (§1:6): the wire
client reads the outbound name and never the requesting device, and the wire server
reads ``acting_for`` off the frame and never the outbound name. So a value set
inside the hub can never leak onto an outbound frame, nor the reverse.

**It lives in `core`, in a module of its own** (§2:4, §10:2), because the wire server
sets one value, the wire client reads the other, and the engine and a gateway each
read or set one of them: golden rules 1 and 2 leave exactly one place all of them can
import from. The shape is :mod:`ai_assistant.core.correlation`'s, for its reason: a
``ContextVar`` set inside a task changes that task's own copy of the context, so two
concurrent requests never see each other's device.

**Only the wire server sets the requesting device** (§2:4). Nothing in Python can
make that structural, so ``tests/wire/test_device_gate.py`` pins that no other
module under ``src/`` calls :func:`serving_device`.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import HUB_REQUESTING_DEVICE, RequestingDevice

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The requesting device, or ``None`` where nothing has set it. ``None`` rather than
#: the hub's device as the default, so that "unset" stays a state of its own: ADR-0298
#: §2:6 starts work that outlives a request with the value *unset*, which is a
#: different fact from a request the hub's own machine made, even though both read
#: as the hub's own machine.
_REQUESTING: Final[ContextVar[RequestingDevice | None]] = ContextVar(
    "ai_assistant_requesting_device", default=None
)

#: The outbound name a gateway sets, or ``None`` where the call is the connecting
#: device's own (ADR-0298 §1:2).
_ACTING_FOR: Final[ContextVar[str | None]] = ContextVar("ai_assistant_acting_for", default=None)


def current_requesting_device() -> RequestingDevice:
    """The device the request being served here is for (ADR-0298 §2).

    Returns:
        The requesting device the wire server set, or the hub's own machine where
        nothing set one — a caller inside the hub's own process (§2:5).
    """
    held = _REQUESTING.get()
    return HUB_REQUESTING_DEVICE if held is None else held


@contextmanager
def serving_device(device: RequestingDevice) -> Iterator[RequestingDevice]:
    """Set the requesting device for the duration of the block (ADR-0298 §2:2).

    The wire server's setter, and only the wire server calls it (§2:4). The reset is
    in a ``finally`` and uses the token, so a nested block leaves the outer value
    intact on the way out.

    Args:
        device: The requesting device the wire server decided (§2:1).

    Yields:
        ``device``.
    """
    token = _REQUESTING.set(device)
    try:
        yield device
    finally:
        _REQUESTING.reset(token)


def without_requesting_device() -> Context:
    """A copy of the current context with the requesting device unset (ADR-0298 §2:6).

    For work a request starts that outlives the request: a task started in the
    returned context keeps every other context value — the correlation scope among
    them — but does not run as the requesting device, so the assistant's own work is
    never checked as the device whose request started it. It reads as the hub's own
    machine (§2:5). Unsetting is not setting: :func:`serving_device` stays the wire
    server's alone (§2:4).

    Returns:
        The copy, for ``asyncio.create_task(..., context=...)``.
    """
    context = copy_context()
    context.run(_REQUESTING.set, None)
    return context


def current_acting_for() -> str | None:
    """The browser device a call made here is relayed for (ADR-0298 §1:5).

    Returns:
        The outbound name a gateway set, or ``None`` where the call is the
        connecting device's own and its frame carries no ``acting_for`` (§1:2).
    """
    return _ACTING_FOR.get()


@contextmanager
def acting_for(name: str) -> Iterator[str]:
    """Name the browser device the calls made in the block are relayed for (§1:5).

    A gateway's setter, around one ``AssistantEngine`` call or, for a streamed call,
    around the whole iteration. The name is not checked here: the wire client holds
    it to ADR-0298 §1:3 before it writes any frame, where the bound it is checked
    against lives.

    Args:
        name: The browser device's name.

    Yields:
        ``name``.
    """
    token = _ACTING_FOR.set(name)
    try:
        yield name
    finally:
        _ACTING_FOR.reset(token)


__all__ = [
    "acting_for",
    "current_acting_for",
    "current_requesting_device",
    "serving_device",
    "without_requesting_device",
]
