"""A hub chat message's device it came through, end to end through the engine (ADR-0378).

The engine records, on every message, the device it came through: the requesting device's
connecting device, which the wire server set, never a value the request carries (§4:2).
The chat's reader reads the sender of a message that came through another device from both
links (§4:3), the episode fixes each message's two devices on its trigger beside its
senders (§7:1), and inspecting the work shows them (§7:2). What the models are shown does
not change: a hub chat input through a gateway renders byte for byte as the same input
through the device it is written from.
"""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from phases_support import (
    PHONE,
    answered,
    frozen,
    open_conversation,
    phases_harness,
    replying,
    said,
    until,
)
from pydantic import ValidationError
from rich.console import Console
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    DeviceRole,
    EpisodicMemory,
    InputSender,
    MessageAuthor,
    RecordedMessageDevices,
    RequestingDevice,
    Sureness,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.interfaces.episode_inspection import render_detail
from ai_assistant.orchestration.work_facts import NO_LINK, chat_account
from ai_assistant.testing import FakeIdentityStore, FakeModelProvider

if TYPE_CHECKING:
    from test_engine import Harness

_GATEWAY: Final = "gateway-1"
_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)

#: The phone, as a gateway names it in ``acting_for``: its own roles, through the gateway.
_NAMED_PHONE: Final = RequestingDevice(
    device_id=PHONE.device_id,
    roles=frozenset({DeviceRole.COMMANDS}),
    connecting_device_id=_GATEWAY,
)
#: The phone, connecting as itself.
_PHONE_ITSELF: Final = RequestingDevice(
    device_id=PHONE.device_id, roles=frozenset({DeviceRole.COMMANDS})
)


def render_episode_detail(episode: EpisodicMemory) -> str:
    """What inspecting the work prints, at a width that wraps no line."""
    buffer = StringIO()
    render_detail(Console(file=buffer, force_terminal=False, width=200), episode, stories=())
    return buffer.getvalue()


def _linked(*devices: str) -> FakeIdentityStore:
    return FakeIdentityStore(
        configured=[Account(kind="conversation", identifier=one) for one in devices]
    )


async def _one_frozen(harness: Harness) -> EpisodicMemory:
    found: list[EpisodicMemory] = []

    async def done() -> bool:
        found[:] = await frozen(harness)
        return len(found) == 1

    await until(done, what="the activation's episode to freeze")
    return found[0]


async def _write(
    harness: Harness, device: RequestingDevice | None, text: str = "hi"
) -> tuple[list[TranscriptMessage], EpisodicMemory]:
    conversation = await open_conversation(harness)
    if device is None:
        await harness.engine.write_message(conversation, message=said("m-1", text))
    else:
        with serving_device(device):
            await harness.engine.write_message(conversation, message=said("m-1", text))
    messages = await answered(harness, conversation, 1)
    episode = await _one_frozen(harness)
    await harness.engine.aclose()
    return messages, episode


def test_a_client_cannot_say_what_device_a_message_came_through() -> None:
    """ADR-0378 §4:2: the wire input names no such member, so a value is refused."""
    with pytest.raises(ValidationError, match="came_through"):
        UserMessage.model_validate(
            {"device_id": "phone", "message_id": "m-1", "text": "hi", "came_through": "hub"}
        )


async def test_a_message_through_a_gateway_records_it_and_reads_both_links() -> None:
    """ADR-0378 §4:2, §4:3, §7:1, §7:2: the engine records the connecting device, the
    gateway no link ties makes the sender no one's, and the episode and inspection keep
    both devices."""
    harness = phases_harness(identities=_linked(PHONE.device_id))
    messages, episode = await _write(harness, _NAMED_PHONE)

    user = messages[0]
    assert (user.author, user.device_id, user.came_through) == (
        MessageAuthor.USER,
        PHONE.device_id,
        _GATEWAY,
    )
    record = episode.processing_record
    assert record is not None
    assert record.trigger.senders == (NO_LINK,)
    assert record.trigger.messages == ()
    assert record.trigger.message_devices == (
        RecordedMessageDevices(position=1, device_id=PHONE.device_id, came_through=_GATEWAY),
    )
    detail = render_episode_detail(episode)
    assert '    Message 1 came through "gateway-1", written from "phone"' in detail


async def test_a_message_through_a_linked_gateway_is_the_owners_at_the_lower_level() -> None:
    """ADR-0378 §4:3: both links tie the owner; the gateway lowered to weak binds it."""
    store = _linked(PHONE.device_id, _GATEWAY)
    gateway = chat_account(_GATEWAY)
    assert gateway is not None
    link = await store.find_link(gateway)
    assert link is not None
    await store.lower(link.id, Sureness.WEAK, by=OWNER_PERSON_ID)
    harness = phases_harness(identities=store)
    _, episode = await _write(harness, _NAMED_PHONE)

    record = episode.processing_record
    assert record is not None
    assert record.trigger.senders == (InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK),)


@pytest.mark.parametrize(
    ("device", "through"),
    [(None, HUB_DEVICE_ID), (_PHONE_ITSELF, PHONE.device_id)],
    ids=["local-socket-label", "enrolled-machine-itself"],
)
async def test_the_owners_own_use_reads_as_before(
    device: RequestingDevice | None, through: str
) -> None:
    """What must not change: written on the hub's own machine under the phone's name
    (ADR-0298 §2:8, ADR-0378 §6:1), where both links stand at one level, and the phone
    writing as itself, are the owner's at normal, and inspection shows no device line
    where it came through its own."""
    harness = phases_harness(identities=_linked(HUB_DEVICE_ID, PHONE.device_id))
    messages, episode = await _write(harness, device)

    assert messages[0].came_through == through
    record = episode.processing_record
    assert record is not None
    assert record.trigger.senders == (_OWNER,)
    assert record.trigger.message_devices == (
        RecordedMessageDevices(position=1, device_id=PHONE.device_id, came_through=through),
    )
    shows = "came through" in render_episode_detail(episode)
    assert shows is (through != PHONE.device_id)


async def test_what_the_models_are_shown_does_not_change() -> None:
    """ADR-0375 §4:1, §4:2 stand: the hub chat's trigger still records no messages, and
    understanding's and planning's inputs for a message through a gateway are byte for byte
    those for the same message through the device it is written from."""
    shown: list[tuple[list[str], list[str]]] = []
    for device in (_PHONE_ITSELF, _NAMED_PHONE):
        model = FakeModelProvider(reply=STATED_PROPOSAL)
        completer = replying()
        harness = phases_harness(
            completer,
            identities=_linked(PHONE.device_id, _GATEWAY),
            understanding=understanding_stage(model=model),
        )
        _, episode = await _write(harness, device)
        record = episode.processing_record
        assert record is not None
        assert record.trigger.messages == ()
        understood = [repr(one.messages) for one in model.calls]
        planned = [one.exchange.model_dump_json() for one in completer.calls]
        assert understood
        assert planned
        shown.append((understood, planned))
    assert shown[0] == shown[1]
