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
from ai_assistant.wire.routes import ROWS, TARGETED, Route, check_request, route_of
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

    Two methods are the table's own exception (§5:1): ``receive`` and
    ``receive_streaming`` sit in exactly two rows, the legacy turn and spoke traffic,
    and the input's target decides which.
    """
    held = Counter(name for methods in ROWS.values() for name in methods)
    unplaced = sorted(METHODS - set(held))
    assert not unplaced, f"methods in no row of ADR-0298 §5's table: {unplaced}"
    for name in METHODS:
        rows = {route for route, methods in ROWS.items() if name in methods}
        if name in TARGETED:
            assert rows == {Route.LEGACY_TURN, Route.SPOKE_TRAFFIC}, name
        else:
            assert len(rows) == 1, f"{name} is in {sorted(rows)}"


def test_no_row_names_a_method_the_surface_does_not_have() -> None:
    """A stale name would answer for a method nobody can call, and hide a rename."""
    named = {name for methods in ROWS.values() for name in methods}
    assert named <= METHODS, sorted(named - METHODS)


def test_stop_activation_is_a_command() -> None:
    """§5's commentary: ADR-0295 §1:4 accepts a stop only from a device that commands."""
    assert route_of("stop_activation", {}) is Route.COMMAND


@pytest.mark.parametrize(
    ("arguments", "route"),
    [
        (_CONVERSATION_INPUT, Route.LEGACY_TURN),
        (_NEW_CONVERSATION_INPUT, Route.LEGACY_TURN),
        (_EVENT_INPUT, Route.SPOKE_TRAFFIC),
    ],
)
@pytest.mark.parametrize("method", sorted(TARGETED))
def test_a_targeted_methods_row_is_its_inputs_target(
    method: str, arguments: dict[str, Any], route: Route
) -> None:
    """§5:2: for ``receive`` the kind is the target's ``kind`` and ``channel_type``.

    An informational event carries the same text payload a conversation does
    (ADR-0274), so only the target can tell them apart, and it does.
    """
    assert route_of(method, arguments) is route


def test_a_method_in_no_row_has_no_route() -> None:
    """§5:3's subject, which the closure test keeps hypothetical on this surface."""
    assert route_of("not_a_method", {}) is None


# --- the wire server's checks (§5:6) ------------------------------------------


@pytest.mark.parametrize("method", sorted(METHODS - TARGETED))
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
        | (ROWS[Route.LEGACY_TURN] - TARGETED)
    ),
)
def test_a_membership_row_is_left_to_the_engine(method: str) -> None:
    """§5:6: rows that depend on membership are the engine's; the wire refuses none."""
    check_request(method, {}, device=_NOBODY, acting_for="new-phone", knows=_nothing_known)


@pytest.mark.parametrize("method", sorted(TARGETED))
def test_spoke_traffic_needs_the_spoke_role_and_a_conversation_does_not(method: str) -> None:
    """§5's spoke-traffic row, which the command role does not satisfy."""
    with pytest.raises(DeviceRefusedError) as refused:
        check_request(
            method, _EVENT_INPUT, device=_COMMANDER, acting_for=None, knows=_everything_known
        )
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    check_request(
        method, _EVENT_INPUT, device=_SPOKE_HOST, acting_for=None, knows=_everything_known
    )
    check_request(
        method, _CONVERSATION_INPUT, device=_NOBODY, acting_for=None, knows=_everything_known
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
