"""ADR-0298 §5's route table, and the half of it the wire server checks.

**Every method on the promoted surface is in exactly one row**, except ``receive``,
which the kind of the input's target places in one of two (ADR-0298 §5:1).
:data:`ROWS` is the table as the ADR states it, and ``tests/wire/test_routes.py``
fails while any member of :data:`~ai_assistant.wire.surface.METHODS` is in no row,
or in more rows than the table allows it (§5:4), and while a row names a method the
surface no longer has.

**Enumerated rather than derived**, as :data:`~ai_assistant.wire.server.
CONNECTION_METHODS` is and for its reason: which row a method sits in is ADR-0298
§5's decision, not a property of its signature, so there is nothing on the Protocol
to read it off. The closure test is what keeps the transcription honest.

**The wire server checks the rows that need only the roster** (§5:6) — the command
role, the role of host of spokes, a known device, and the notification poll's
connecting device — before dispatch, and :func:`check_request` is that check. The
rows that depend on membership of "my devices" or of a conversation are the
engine's, reading the requesting device (§2), so this module passes them through.

**The hub's own machine passes every check that is about the requesting device**
(§3:2): it holds every role. The known-device condition is not one of those — it
is about the devices a request *names*, and ADR-0298 §4:12 lets a device id be
added to a set only if the hub knows it, whoever adds it — so it binds the hub's
own machine too.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, NoReturn

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChannelIdentity, ChannelInput, DeviceRole, NewConversation

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ai_assistant.core.types import RequestingDevice


class Route(StrEnum):
    """One row of ADR-0298 §5's table: what a request needs of its requesting device.

    Attributes:
        COMMAND: Hold the role of source of commands and queries.
        SETTING_DEVICES: Hold the command role, and name only devices the hub knows.
        FORGETTING: Hold the command role and, while the method still deletes the
            conversation, be its end for writing.
        STARTING: Be in "my devices".
        WRITING: Be the named conversation's end for writing.
        READING_ONE: Be the named conversation's end for reading.
        READING_MANY: Hold a role; the answer holds only conversations the device
            reads.
        LEGACY_TURN: Be the named conversation's end for writing and for reading, or
            where none is named, be in "my devices" for both.
        SPOKE_TRAFFIC: Hold the role of host of spokes.
        NOTIFICATION_POLL: Be in "my devices" for reading, as the connecting device.
    """

    COMMAND = "command"
    SETTING_DEVICES = "setting_devices"
    FORGETTING = "forgetting"
    STARTING = "starting"
    WRITING = "writing"
    READING_ONE = "reading_one"
    READING_MANY = "reading_many"
    LEGACY_TURN = "legacy_turn"
    SPOKE_TRAFFIC = "spoke_traffic"
    NOTIFICATION_POLL = "notification_poll"


#: The method whose row the input's target decides (ADR-0298 §5:1, §5:2).
#: ``receive_streaming`` was the other until ADR-0293 §11 took it off the surface.
TARGETED: Final[frozenset[str]] = frozenset({"receive"})

#: ADR-0298 §5's table, row by row, with ``receive`` in both rows its target may place
#: it in. ``converse_streaming``, ``learn`` and ``receive_streaming`` left the surface
#: under ADR-0293 §11, and their names left this table with them, which the closure
#: test asks of a removal. ``receive`` keeps the legacy-turn row for a spoken input to
#: a conversation, the text combination being refused before any row is read.
ROWS: Final[Mapping[Route, frozenset[str]]] = {
    Route.COMMAND: frozenset(
        {
            "abandon_goal",
            "activation_stories",
            "belief",
            "beliefs",
            "cancel_read",
            "connect_account",
            "connected_accounts",
            "create_story",
            "disconnect_account",
            "dismiss_notification",
            "episode_chunk",
            "episodes",
            "establish_destination_trust",
            "establish_recipient_grant",
            "export_decisions",
            "export_invocations",
            "export_reads",
            "forget",
            "forget_notification",
            "forget_question",
            "goals",
            "grant",
            "grantable_decisions",
            "grantable_sources",
            "guard",
            "interrupted_questions",
            "link_story",
            "merge_stories",
            "my_devices",
            "notification_preferences",
            "notifications",
            "pending_confirmations",
            "questions",
            "recent_connection_acts",
            "recent_decisions",
            "recent_grants",
            "recent_invocations",
            "recent_reads",
            "recent_recipient_grants",
            "reprovision_account",
            "resume",
            "revoke",
            "revoke_authorization",
            "revoke_destination_trust",
            "revoke_recipient_grant",
            "set_notification_preferences",
            "spend_totals",
            "split_story",
            "standing_authorizations",
            "standing_destination_trust",
            "standing_grants",
            "standing_recipient_grants",
            "stop_activation",
            "stories",
            "story",
            "story_log",
            "unguard",
            "unlink_story",
            "withdraw_clarification",
        }
    ),
    Route.SETTING_DEVICES: frozenset({"set_my_devices", "set_conversation_devices"}),
    Route.FORGETTING: frozenset({"forget_conversation"}),
    Route.STARTING: frozenset({"start_conversation"}),
    Route.WRITING: frozenset({"write_message", "delete_message", "delete_conversation"}),
    Route.READING_ONE: frozenset({"transcript", "conversation"}),
    Route.READING_MANY: frozenset({"recent_conversations", "chat_changes"}),
    Route.LEGACY_TURN: frozenset({"converse", "converse_spoken", "answer", *TARGETED}),
    Route.SPOKE_TRAFFIC: TARGETED,
    Route.NOTIFICATION_POLL: frozenset({"next_notification"}),
}

#: The ``channel_type`` of a channel whose input is a conversation's, which places a
#: targeted method in the legacy-turn row (ADR-0298 §5:1's table).
CONVERSATION_CHANNEL: Final = "conversation"

#: The role each roster-checked row needs (ADR-0298 §5:6). A row absent here needs no
#: role of the wire server: its check, where it has one, is the engine's.
_ROLE_NEEDED: Final[Mapping[Route, DeviceRole]] = {
    Route.COMMAND: DeviceRole.COMMANDS,
    Route.SETTING_DEVICES: DeviceRole.COMMANDS,
    Route.FORGETTING: DeviceRole.COMMANDS,
    Route.SPOKE_TRAFFIC: DeviceRole.SPOKES,
}


def route_of(method: str, arguments: Mapping[str, Any]) -> Route | None:
    """The row a request is in, by its method and, for ``receive``, its target.

    ADR-0298 §5:2: a request's kind is its envelope ``method``, and for ``receive``
    also the input's target — its ``kind``, and a channel's
    ``channel_type`` — as validated; no row is chosen by any other part of a request.

    Args:
        method: The envelope's ``method``.
        arguments: The request's arguments, decoded and validated.

    Returns:
        The row, or ``None`` for a method in no row.
    """
    if method in TARGETED:
        target = _target(arguments)
        if isinstance(target, NewConversation):
            return Route.LEGACY_TURN
        if isinstance(target, ChannelIdentity) and target.channel_type == CONVERSATION_CHANNEL:
            return Route.LEGACY_TURN
        return Route.SPOKE_TRAFFIC
    for route, methods in ROWS.items():
        if method in methods:
            return route
    return None


def _target(arguments: Mapping[str, Any]) -> object:
    """The validated input's target, or ``None`` where the request carried no input."""
    held = arguments.get("input")
    return held.target if isinstance(held, ChannelInput) else None


def check_request(
    method: str,
    arguments: Mapping[str, Any],
    *,
    device: RequestingDevice,
    acting_for: str | None,
    knows: Callable[[str], bool],
) -> None:
    """Refuse a request the roster-only rows of ADR-0298 §5 do not allow (§5:6).

    Every refusal is a :class:`~ai_assistant.core.errors.DeviceRefusedError` raised
    before dispatch, so the operation has changed nothing (§6:1).

    **A role refusal says the device's roles do not allow the request, never that it
    holds none.** The wire server sees the roster's roles and no membership, and a
    device holding no roster role may still be in "my devices" — a watch is added
    read-only — so "holds no role" is a claim this check cannot make true. That
    reason is the engine's to give, from the rows it checks (§5:6).

    Args:
        method: The envelope's ``method``.
        arguments: The request's arguments, decoded and validated.
        device: The requesting device (§2:1).
        acting_for: The frame's ``acting_for``, or ``None`` where it carried none.
        knows: Whether the hub knows a device id as a device (§4:12).

    Raises:
        DeviceRefusedError: If the request's row needs a role the device does not
            hold, names a device the hub does not know, is a poll relayed for
            another device (§5:5), or is in no row and not the hub's (§5:3).
    """
    route = route_of(method, arguments)
    if route is None:
        if not device.is_hub:
            _refuse(f"{method} is in no row of the route table", DeviceRefusal.NOT_ALLOWED)
        return
    needed = _ROLE_NEEDED.get(route)
    if needed is not None and needed not in device.roles:
        _refuse(
            f"{method} needs the {needed.value} role, which this device does not hold",
            DeviceRefusal.NOT_ALLOWED,
        )
    if route is Route.NOTIFICATION_POLL and acting_for is not None and not device.is_hub:
        _refuse(
            "next_notification is the connecting device's own and is never relayed",
            DeviceRefusal.NOT_ALLOWED,
        )
    if route is Route.SETTING_DEVICES:
        for named in _named_devices(arguments):
            if not knows(named):
                _refuse(
                    f"{method} names a device the hub does not know as a device",
                    DeviceRefusal.NOT_ALLOWED,
                )


def _named_devices(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    """The device ids a setting-devices request names, in the order it names them."""
    return tuple(device.device_id for device in arguments.get("devices", ()))


def _refuse(message: str, reason: DeviceRefusal) -> NoReturn:
    """Raise the one refusal ADR-0298 §6 gives every check."""
    raise DeviceRefusedError(message, reason=reason)


__all__ = [
    "CONVERSATION_CHANNEL",
    "ROWS",
    "TARGETED",
    "Route",
    "check_request",
    "route_of",
]
