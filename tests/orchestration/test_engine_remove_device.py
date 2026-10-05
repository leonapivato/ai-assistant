"""``Engine.remove_device``: a revoked device leaves every set (ADR-0298 §4:10).

The hub's owner act calls it once the device roster has revoked a device, so the
device stops being an end of any conversation, and of "my devices", with each
removal a change the other devices see (ADR-0296 §3:6). It is maintenance surface on
the concrete engine, as :meth:`~ai_assistant.orchestration.engine.Engine.
purge_expired` is, and never contract or wire surface: no device may revoke another
over the wire.
"""

from __future__ import annotations

from typing import Final

import pytest
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import ChatDevice, DeviceAccess, DevicesChangedChange
from ai_assistant.wire.surface import METHODS

_PHONE: Final = ChatDevice(device_id="nPHONE22CNTRL", access=DeviceAccess.READ_WRITE)
_LAPTOP: Final = ChatDevice(device_id="nLAPTOP1CNTRL", access=DeviceAccess.READ)


def _harness() -> Harness:
    """An engine whose chat reader is off, so nothing answers in the background."""
    return Harness(planner=NoStepPlanner(), chat_reader=False)


async def test_a_removed_device_leaves_my_devices_and_every_conversation() -> None:
    """ADR-0298 §4:10, through the engine: the device leaves "my devices" and each
    conversation's devices, the other devices stay, and each removal is recorded as a
    change, so every other device sees it."""
    harness = _harness()
    engine = harness.engine
    await engine.set_my_devices([_PHONE, _LAPTOP])
    first = (await engine.start_conversation()).id
    second = (await engine.start_conversation()).id
    before = (await engine.chat_changes(after=0)).next_after

    removed = await engine.remove_device(_PHONE.device_id)

    assert removed is True
    assert await engine.my_devices() == (_LAPTOP,)
    for conversation_id in (first, second):
        digest = await engine.conversation(conversation_id)
        assert digest is not None
        assert digest.devices == (_LAPTOP,)
    recorded = (await engine.chat_changes(after=before)).changes
    assert [type(change) for change in recorded] == [DevicesChangedChange] * 3
    await engine.aclose()


async def test_removing_a_device_no_set_names_records_nothing() -> None:
    """Safe to repeat, which is what lets an unfinished revocation be run again."""
    harness = _harness()
    engine = harness.engine
    await engine.set_my_devices([_LAPTOP])
    before = (await engine.chat_changes(after=0)).next_after

    assert await engine.remove_device(_PHONE.device_id) is False
    assert (await engine.chat_changes(after=before)).changes == ()
    await engine.aclose()


async def test_a_closing_engine_refuses_the_removal() -> None:
    """Tracked work, refused once the engine is closing, as every operation is."""
    harness = _harness()
    await harness.engine.aclose()

    with pytest.raises(RuntimeError):
        await harness.engine.remove_device(_PHONE.device_id)


def test_removal_is_not_on_the_contract_or_the_wire() -> None:
    """Roles are given, and devices revoked, only at the hub (ADR-0298 §4:12)."""
    assert not hasattr(AssistantEngine, "remove_device")
    assert "remove_device" not in METHODS
