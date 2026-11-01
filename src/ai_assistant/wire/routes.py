"""ADR-0298 §5's route table, and the half of it the wire server checks.

**Every method on the promoted surface is in exactly one row** (ADR-0298 §5:1).
``receive`` was the exception, placed by its input's target in the legacy-turn row
or the spoke-traffic row; the legacy-turn row left with its last member (ADR-0309
§5:1), and a conversational input is refused at decode before any row is read
(ADR-0313 §4:1), so ``receive`` is spoke traffic alone.
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
from ai_assistant.core.types import DeviceRole

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
    SPOKE_TRAFFIC = "spoke_traffic"
    NOTIFICATION_POLL = "notification_poll"


#: ADR-0298 §5's table, row by row. ``converse_streaming``, ``learn`` and
#: ``receive_streaming`` left the surface under ADR-0293 §11, and their names left this
#: table with them, which the closure test asks of a removal; ``converse_spoken`` left
#: with spoken conversation (ADR-0313 §3:1); ``converse``, ``resume``, ``cancel_read``,
#: ``pending_confirmations``, ``goals``, ``withdraw_clarification``, ``abandon_goal``,
#: ``standing_authorizations``, ``revoke_authorization``, ``answer``, ``questions``,
#: ``interrupted_questions`` and ``forget_question`` with the old path (ADR-0309 §5:1);
#: ``grantable_decisions`` and ``establish_recipient_grant`` with the establishing
#: act (ADR-0313 §5:1); and ``standing_recipient_grants``, ``recent_recipient_grants``,
#: ``revoke_recipient_grant``, ``establish_destination_trust``,
#: ``standing_destination_trust`` and ``revoke_destination_trust`` with recipient
#: grants and destination trust (ADR-0321 §7:1, §7:2). The legacy-turn row left with
#: ``answer``, its last member, and ``receive`` is spoke traffic alone: a
#: conversational input is refused at decode, before any row is read (ADR-0313 §4:1).
#:
#: ADR-0300 §8's four story commands, ``story_summary``, ``story_standing``,
#: ``add_story_note`` and ``move_story_members``, postdate the table and are placed
#: in the command-or-query row by their class, beside ADR-0289's nine story methods:
#: each is a command or a query on the assistant's own records, and none is input to
#: the assistant or traffic of a conversation's or a spoke's. ADR-0329 §18:2's
#: ``pending_candidates`` is placed there by the same class, beside ``beliefs``: a
#: query on the assistant's own records, which the command role scopes to the owner
#: (§18:1). ADR-0325 §5:1's ``connect_keyless_account`` is placed there beside
#: ``connect_account``, by the same class: a command on the hub's own connection
#: records, which ADR-0151's connection surface already puts in this row. ADR-0332
#: §5:11 places ``composing`` in the Writing row beside ``write_message``: the requesting
#: device must be the named conversation's end for writing, which the engine checks.
#: ADR-0338 §8:1's eight person-model members, ``person_model``, ``profile_changes``,
#: ``set_profile_field``, ``pin_memory``, ``unpin_memory``, ``remove_style_mark``,
#: ``accept_person_suggestion`` and ``dismiss_person_suggestion``, are placed in the
#: command-or-query row by the same class, beside ``beliefs`` and
#: ``pending_candidates``: commands and queries on the
#: assistant's own records, which the command role scopes to the owner. That is how
#: §8:3's rule holds on the wire: a person's model is shown only to that person and to
#: the owner, and on a hub whose one person is the owner (§2:1) a device without the
#: command role is refused before dispatch.
#:
#: ADR-0361 §8:4's ``approvals`` and ``tap_approval``, the hub page's approvals panel's
#: query and its tap command, are placed in the command-or-query row by the same class: a
#: query and a command on the assistant's own records, beside ``stop_activation``, the
#: other act a page makes that is never perceived. That is how §4:8 holds on the wire: a
#: tap from the hub page is carried out only from a device admitted under ADR-0124,
#: whose command role is the owner's, and a device without it is refused before
#: dispatch, changing nothing.
ROWS: Final[Mapping[Route, frozenset[str]]] = {
    Route.COMMAND: frozenset(
        {
            "activation_stories",
            "add_story_note",
            "approvals",
            "belief",
            "beliefs",
            "connect_account",
            "connect_keyless_account",
            "connected_accounts",
            "accept_person_suggestion",
            "create_story",
            "dismiss_person_suggestion",
            "disconnect_account",
            "dismiss_notification",
            "episode_chunk",
            "episodes",
            "export_decisions",
            "export_invocations",
            "export_reads",
            "forget",
            "forget_notification",
            "grant",
            "grantable_sources",
            "guard",
            "link_story",
            "merge_stories",
            "move_story_members",
            "my_devices",
            "notification_preferences",
            "notifications",
            "pending_candidates",
            "person_model",
            "pin_memory",
            "profile_changes",
            "recent_connection_acts",
            "recent_decisions",
            "recent_grants",
            "recent_invocations",
            "recent_reads",
            "remove_style_mark",
            "reprovision_account",
            "revoke",
            "set_notification_preferences",
            "set_profile_field",
            "spend_totals",
            "split_story",
            "standing_grants",
            "stop_activation",
            "stories",
            "story",
            "story_log",
            "story_summary",
            "story_standing",
            "tap_approval",
            "unguard",
            "unlink_story",
            "unpin_memory",
        }
    ),
    Route.SETTING_DEVICES: frozenset({"set_my_devices", "set_conversation_devices"}),
    Route.FORGETTING: frozenset({"forget_conversation"}),
    Route.STARTING: frozenset({"start_conversation"}),
    Route.WRITING: frozenset(
        {"write_message", "composing", "delete_message", "delete_conversation"}
    ),
    Route.READING_ONE: frozenset({"transcript", "conversation"}),
    # ADR-0298 §5 names "the change stream" in this row; `follow_chat` is its name.
    Route.READING_MANY: frozenset({"recent_conversations", "chat_changes", "follow_chat"}),
    Route.SPOKE_TRAFFIC: frozenset({"receive"}),
    Route.NOTIFICATION_POLL: frozenset({"next_notification"}),
}

#: The role each roster-checked row needs (ADR-0298 §5:6). A row absent here needs no
#: role of the wire server: its check, where it has one, is the engine's.
_ROLE_NEEDED: Final[Mapping[Route, DeviceRole]] = {
    Route.COMMAND: DeviceRole.COMMANDS,
    Route.SETTING_DEVICES: DeviceRole.COMMANDS,
    Route.FORGETTING: DeviceRole.COMMANDS,
    Route.SPOKE_TRAFFIC: DeviceRole.SPOKES,
}


def route_of(method: str) -> Route | None:
    """The row a request is in, by its method (ADR-0298 §5:2).

    A request's kind is its envelope ``method``, and no row is chosen by any other
    part of a request. ``receive``'s target once chose between two rows; with the
    legacy-turn row gone (ADR-0309 §5:1) and a conversational input refused at
    decode (ADR-0313 §4:1), every ``receive`` that reaches a row is spoke traffic.

    Args:
        method: The envelope's ``method``.

    Returns:
        The row, or ``None`` for a method in no row.
    """
    for route, methods in ROWS.items():
        if method in methods:
            return route
    return None


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
    route = route_of(method)
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
    "ROWS",
    "Route",
    "check_request",
    "route_of",
]
