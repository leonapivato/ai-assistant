"""The two device context values and the types they carry (ADR-0298 §1:5-6, §2, §10).

The requesting device is what the engine reads to know whom a request is for; the
outbound name is what a gateway sets for the wire client to write. These are the
properties a reader of either depends on: the default when nothing is set, the reset
on the way out of a block, isolation between concurrent tasks, and that neither value
is ever read for the other.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from ai_assistant.core.device_context import (
    acting_for,
    current_acting_for,
    current_requesting_device,
    serving_device,
    without_requesting_device,
)
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    HUB_REQUESTING_DEVICE,
    DeviceRole,
    RequestingDevice,
)

_PHONE = RequestingDevice(device_id="phone.tailnet", roles=frozenset({DeviceRole.COMMANDS}))
_WATCH = RequestingDevice(device_id="watch.tailnet")


def test_an_unset_requesting_device_is_the_hubs_own_machine() -> None:
    """§2:5: a caller inside the hub's own process runs as the hub's own machine."""
    assert current_requesting_device() == HUB_REQUESTING_DEVICE
    assert current_requesting_device().is_hub


def test_the_hubs_own_machine_holds_every_role_and_is_named_hub() -> None:
    """§3:1-2: its id is ``hub`` in every configuration, and it holds every role."""
    assert HUB_REQUESTING_DEVICE.device_id == HUB_DEVICE_ID == "hub"
    assert HUB_REQUESTING_DEVICE.roles == frozenset(DeviceRole)


def test_the_requesting_device_lasts_for_the_block_and_no_longer() -> None:
    """§2:2: it lasts for the request; a nested block leaves the outer value intact."""
    with serving_device(_PHONE):
        assert current_requesting_device() == _PHONE
        with serving_device(_WATCH):
            assert current_requesting_device() == _WATCH
        assert current_requesting_device() == _PHONE
    assert current_requesting_device() == HUB_REQUESTING_DEVICE


async def test_two_concurrent_requests_never_see_each_others_device() -> None:
    """A context value set in one task is that task's own (the module's premise)."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def served(device: RequestingDevice) -> RequestingDevice:
        with serving_device(device):
            if device == _PHONE:
                entered.set()
                await release.wait()
            else:
                await entered.wait()
                release.set()
            return current_requesting_device()

    seen = await asyncio.gather(served(_PHONE), served(_WATCH))
    assert list(seen) == [_PHONE, _WATCH]


async def test_work_that_outlives_a_request_runs_with_the_device_unset() -> None:
    """§2:6: a task started in the copy reads the hub's own machine; others stay."""
    seen: list[tuple[RequestingDevice, str | None]] = []

    async def outliving() -> None:
        seen.append((current_requesting_device(), current_acting_for()))

    with acting_for("browser.one"), serving_device(_WATCH):
        await asyncio.get_running_loop().create_task(
            outliving(), context=without_requesting_device()
        )
        assert current_requesting_device() == _WATCH, "the request's own value stands"
    assert seen == [(HUB_REQUESTING_DEVICE, "browser.one")]


def test_the_outbound_name_is_absent_unless_a_gateway_sets_it() -> None:
    """§1:2: a call that is the connecting device's own carries no ``acting_for``."""
    assert current_acting_for() is None
    with acting_for("phone.tailnet"):
        assert current_acting_for() == "phone.tailnet"
    assert current_acting_for() is None


def test_neither_value_is_ever_read_for_the_other() -> None:
    """§1:6: the outbound name and the requesting device are distinct values.

    Setting one leaves the other where it was, so a device set inside the hub can
    never reach an outbound frame, nor a gateway's name the engine's checks.
    """
    with serving_device(_PHONE):
        assert current_acting_for() is None
    with acting_for("phone.tailnet"):
        assert current_requesting_device() == HUB_REQUESTING_DEVICE


def test_a_requesting_device_is_frozen_and_its_id_is_an_identifier() -> None:
    """§2:3: a frozen ``RequestingDevice``; a blank id names no device."""
    with pytest.raises(ValidationError):
        _PHONE.device_id = "other"
    with pytest.raises(ValidationError):
        RequestingDevice(device_id="   ")


def test_a_device_refusal_carries_one_of_three_reasons() -> None:
    """§6:2: the reason is a public attribute, coerced from its string value."""
    assert {member.value for member in DeviceRefusal} == {
        "not_accepted",
        "no_role",
        "not_allowed",
    }
    refused = DeviceRefusedError("no", reason="no_role")  # type: ignore[arg-type]  # as a reconstruction passes it
    assert refused.reason is DeviceRefusal.NO_ROLE
    with pytest.raises(ValueError, match="DeviceRefusal"):
        DeviceRefusedError("no", reason="revoked")  # type: ignore[arg-type]  # the refused value
