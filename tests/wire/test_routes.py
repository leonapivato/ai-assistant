"""ADR-0298 §5's route table: its closure, and the half the wire server checks.

The closure test is §5:4's, and it is the reason the table can be transcribed at
all: a method the surface gains fails here until it is given a row, and a method it
loses fails here until its row is deleted.

The check is :func:`~ai_assistant.wire.routes.check_request` taken directly, with
the requesting device under each case's control; ``tests/wire/test_device_gate.py``
drives the same check through a served connection.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

import pytest

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    HUB_REQUESTING_DEVICE,
    ChannelIdentity,
    ChannelInput,
    ChatDevice,
    DeviceAccess,
    DeviceRole,
    NewConversation,
    RequestingDevice,
    TextChannelPayload,
)
from ai_assistant.wire.errors import UndecodableFrameError
from ai_assistant.wire.routes import ROWS, Route, check_request, route_of
from ai_assistant.wire.server import _decode_arguments
from ai_assistant.wire.surface import METHODS

_NOBODY: Final = RequestingDevice(device_id="new-phone")
_COMMANDER: Final = RequestingDevice(device_id="laptop", roles=frozenset({DeviceRole.COMMANDS}))
_SPOKE_HOST: Final = RequestingDevice(device_id="sensor-box", roles=frozenset({DeviceRole.SPOKES}))


def _everything_known(_: str) -> bool:
    return True


def _nothing_known(_: str) -> bool:
    return False


def _input(target: ChannelIdentity | NewConversation) -> dict[str, Any]:
    return {"input": ChannelInput(target=target, payload=TextChannelPayload(text="hello"))}


_CONVERSATION_INPUT: Final = _input(ChannelIdentity(channel_type="conversation", instance_id="c-1"))
_NEW_CONVERSATION_INPUT: Final = _input(NewConversation())
_EVENT_INPUT: Final = _input(ChannelIdentity(channel_type="informational_event", instance_id="e"))


# --- the closure (§5:1, §5:4) -------------------------------------------------


def test_every_method_on_the_surface_is_in_exactly_the_rows_the_table_allows() -> None:
    """§5:4: a test fails while any member of ``METHODS`` is in no row, or in more.

    ``receive`` was the table's own exception (§5:1), in the legacy-turn row and the
    spoke-traffic row by its input's target; the legacy-turn row left with its last
    member (ADR-0309 §5:1), so every method now sits in exactly one row.
    """
    held = Counter(name for methods in ROWS.values() for name in methods)
    unplaced = sorted(METHODS - set(held))
    assert not unplaced, f"methods in no row of ADR-0298 §5's table: {unplaced}"
    for name in METHODS:
        rows = {route for route, methods in ROWS.items() if name in methods}
        assert len(rows) == 1, f"{name} is in {sorted(rows)}"


def test_no_row_names_a_method_the_surface_does_not_have() -> None:
    """A stale name would answer for a method nobody can call, and hide a rename."""
    named = {name for methods in ROWS.values() for name in methods}
    assert named <= METHODS, sorted(named - METHODS)


def test_stop_activation_is_a_command() -> None:
    """§5's commentary: ADR-0295 §1:4 accepts a stop only from a device that commands."""
    assert route_of("stop_activation") is Route.COMMAND


#: ADR-0338 §8:1's eight person-model members.
_PERSON_MODEL_MEMBERS: Final = frozenset(
    {
        "person_model",
        "profile_changes",
        "set_profile_field",
        "pin_memory",
        "unpin_memory",
        "remove_style_mark",
        "accept_person_suggestion",
        "dismiss_person_suggestion",
    }
)


@pytest.mark.parametrize("method", sorted(_PERSON_MODEL_MEMBERS))
def test_a_persons_model_is_a_command_shown_only_to_the_owner(method: str) -> None:
    """ADR-0338 §8:3: shown only to that person and to the owner, held by the command row.

    The command role is the owner's devices' (ADR-0329 §18:1's placement of the
    panel's read), and today's hub holds one person, the owner (ADR-0338 §2:1), so a
    device without it is refused before dispatch and one holding it is let through.
    """
    assert route_of(method) is Route.COMMAND
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(method, {}, device=_NOBODY, acting_for=None, knows=_everything_known)
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(method, {}, device=_COMMANDER, acting_for=None, knows=_everything_known)


def test_the_person_model_members_are_the_surfaces_own() -> None:
    """The eight are on the surface, so the row above names no stale method."""
    assert _PERSON_MODEL_MEMBERS <= METHODS


@pytest.mark.parametrize("method", ["approvals", "tap_approval"])
def test_the_approvals_panels_members_are_commands_for_an_admitted_device(method: str) -> None:
    """ADR-0361 §4:8: a tap from the hub page is carried out only from a device admitted
    under ADR-0124, whose command role is the owner's; one without it is refused before
    dispatch, and the panel's read with it."""
    assert method in METHODS
    assert route_of(method) is Route.COMMAND
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(method, {}, device=_NOBODY, acting_for=None, knows=_everything_known)
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(method, {}, device=_COMMANDER, acting_for=None, knows=_everything_known)


@pytest.mark.parametrize(
    "arguments", [_CONVERSATION_INPUT, _NEW_CONVERSATION_INPUT], ids=["channel", "new"]
)
def test_a_conversational_receive_routes_as_any_receive_and_is_refused_first(
    arguments: dict[str, Any],
) -> None:
    """The legacy-turn row is gone, so every ``receive`` is spoke traffic (ADR-0309 §5:1).

    That a conversational one now routes there too is moot, and this pins why: the
    hub refuses the conversational combination at decode (ADR-0313 §4:1), before
    :func:`~ai_assistant.wire.routes.check_request` reads any row, so no such request
    ever reaches the table. Were it to, it would meet the spoke-traffic row's role
    check like an event, not pass as a conversation's turn.
    """
    assert route_of("receive") is Route.SPOKE_TRAFFIC
    held = arguments["input"]
    payload = {
        "input": held.model_dump(mode="json"),
        "reply": None,
        "timeout": "PT10S",
    }
    with pytest.raises(UndecodableFrameError):
        _decode_arguments("receive", payload)
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            "receive", arguments, device=_NOBODY, acting_for=None, knows=_everything_known
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED


def test_a_method_in_no_row_has_no_route() -> None:
    """§5:3's subject, which the closure test keeps hypothetical on this surface."""
    assert route_of("not_a_method") is None


# --- the wire server's checks (§5:6) ------------------------------------------


@pytest.mark.parametrize("method", sorted(METHODS))
def test_the_hubs_own_machine_passes_every_check(method: str) -> None:
    """§3:2: on its own socket, or before the cutover (§9:2), nothing is refused."""
    check_request(
        method, {}, device=HUB_REQUESTING_DEVICE, acting_for=None, knows=_everything_known
    )


def test_a_relayed_poll_from_the_hub_is_not_refused() -> None:
    """§9:2: before the cutover every request is the hub's, so the poll rule is inert."""
    check_request(
        "next_notification",
        {},
        device=HUB_REQUESTING_DEVICE,
        acting_for="phone",
        knows=_everything_known,
    )


@pytest.mark.parametrize(
    "method", sorted(ROWS[Route.COMMAND] | ROWS[Route.SETTING_DEVICES] | ROWS[Route.FORGETTING])
)
def test_a_command_row_needs_the_command_role(method: str) -> None:
    """§5's three command rows: without the role the device's roles do not allow it."""
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(method, {}, device=_NOBODY, acting_for=None, knows=_everything_known)
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(method, {}, device=_COMMANDER, acting_for=None, knows=_everything_known)


@pytest.mark.parametrize(
    "method",
    sorted(
        ROWS[Route.STARTING]
        | ROWS[Route.WRITING]
        | ROWS[Route.READING_ONE]
        | ROWS[Route.READING_MANY]
    ),
)
def test_a_membership_row_is_left_to_the_engine(method: str) -> None:
    """§5:6: rows that depend on membership are the engine's; the wire refuses none."""
    check_request(method, {}, device=_NOBODY, acting_for="new-phone", knows=_nothing_known)


def test_spoke_traffic_needs_the_spoke_role() -> None:
    """§5's spoke-traffic row, which the command role does not satisfy."""
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            "receive", _EVENT_INPUT, device=_COMMANDER, acting_for=None, knows=_everything_known
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(
        "receive", _EVENT_INPUT, device=_SPOKE_HOST, acting_for=None, knows=_everything_known
    )


def test_a_poll_is_never_relayed() -> None:
    """§5:5: a poll carrying ``acting_for`` is refused; one without it is the engine's."""
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            "next_notification", {}, device=_NOBODY, acting_for="phone", knows=_everything_known
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request("next_notification", {}, device=_NOBODY, acting_for=None, knows=_nothing_known)


@pytest.mark.parametrize("device", [HUB_REQUESTING_DEVICE, _COMMANDER])
@pytest.mark.parametrize("method", sorted(ROWS[Route.SETTING_DEVICES]))
def test_setting_devices_names_only_devices_the_hub_knows(
    method: str, device: RequestingDevice
) -> None:
    """§5's setting-devices row with §4:12: an unknown id is refused, whoever adds it.

    The hub's own machine holds every role (§3:2), and that is about who asks; §4:12
    is about what is named, so it binds the hub's own machine too.
    """
    arguments = {
        "devices": (
            ChatDevice(device_id="laptop", access=DeviceAccess.READ_WRITE),
            ChatDevice(device_id="stranger", access=DeviceAccess.READ),
        )
    }
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            method,
            arguments,
            device=device,
            acting_for=None,
            knows=lambda named: named != "stranger",
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    assert "stranger" not in str(refused.value)
    check_request(method, arguments, device=device, acting_for=None, knows=_everything_known)


def test_a_method_in_no_row_is_refused_for_every_device_but_the_hub() -> None:
    """§5:3."""
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            "not_a_method", {}, device=_COMMANDER, acting_for=None, knows=_everything_known
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(
        "not_a_method", {}, device=HUB_REQUESTING_DEVICE, acting_for=None, knows=_everything_known
    )
