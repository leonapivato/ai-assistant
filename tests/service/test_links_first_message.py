"""A device's first hub chat message, and the link the owner's act made (#3656, ADR-0373 §6).

**ADR-0378 §5 has no naming make a link.** A browser device a gateway registers is
linked by the owner's act that gives it a roster role, while it holds one (§5:2), so a
browser device that is only an end of a conversation writes as an unidentified sender
until the owner gives it a role, and the cases below give the role where they read the
owner's message.

#3656 asked whether a browser device a gateway names for the first time, on a request
that is itself a hub chat message, has its message's sender read before the link its
registration schedules (:class:`~ai_assistant.service.links.DeviceLinks`) is written.
Every case here drives the hub's own pieces over one temporary data directory — the
device record and its registry, the roster the wire server decides each request's
device by, the links following the record, and the real engine over the canonical
fakes — and reads back what the hub recorded.

**Such a request records no message.** A message is written only by an end for writing
of its conversation (ADR-0298 §5, "Writing"), a device id joins a conversation's devices
only once the hub knows it (§4:12), and the hub knows a browser device only once a
gateway has named it (§4:2, §4:11). So the request that registers a device finds it an
end of no conversation, is refused before anything is recorded (§6:1), and no sender is
read for it. The device's first message the hub can record follows a later act of the
owner's naming it in a conversation's devices, which the registration had to precede.
An enrolment (ADR-0124 §6) and a restored registration (ADR-0298 §4:9) are the same:
each is an owner's act at the hub, and a device it admits is an end of no conversation
until the owner names it in one — a revocation that left it admitted by nothing removed
it from every set first (§4:10).

**What reaches a recorded first message.** Only a conversation's devices that name a
device the record does not admit, which the wire's check of §4:12 never writes: a set
written before that check bound (ADR-0298 §9:2), or a conversation store restored apart
from the device record. The last case drives one; what orders its read after the link
is said there.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import frozen, phases_harness, processing, until, written

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.device_context import acting_for, serving_device
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    ChatDevice,
    DeviceAccess,
    DeviceRole,
    InputSender,
    LinkAct,
    LinkActHow,
    MessageAuthor,
    UserMessage,
)
from ai_assistant.orchestration.work_facts import NO_LINK
from ai_assistant.service.admin import AdminListener
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, DeviceRegistry, EnrolmentStore
from ai_assistant.service.links import HUB_CHAT, DeviceLinks
from ai_assistant.service.roster import HubRoster
from ai_assistant.testing import FakeIdentityStore
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.server import ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from test_engine import Harness

    from ai_assistant.core.types import EpisodicMemory, Link

#: The hub's own overlay identity, so the record can enrol a device (ADR-0124 §6).
_HUB_IDENTITY: Final = "nHUBAAAACNTRL"
#: A browser device a gateway on the hub's own machine names (ADR-0298 §4:4).
_BROWSER: Final = "nPHONE22CNTRL"
#: A hub device the owner enrols, which connects as itself (ADR-0298 §2:1).
_ENROLLED: Final = "nLAPTOP1CNTRL"
_PATIENT: Final = timedelta(seconds=5)
_LIMITS: Final = ConnectionLimits(max_frame_bytes=1 << 20, read_timeout=_PATIENT, build="test")
_DEVICE_ACT: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
#: The owner, at the most the hub chat's kind declares (ADR-0366 §5:2, §5:6).
_OWNER_AT_MOST: Final = InputSender(person=OWNER_PERSON_ID, level=most_sureness(HUB_CHAT))


@dataclass
class _Hub:
    """The hub's pieces a message from a device passes through, over one data directory.

    Attributes:
        harness: The real engine over the canonical fakes.
        identities: The identity store the engine reads senders from, and the links
            are written into.
        registry: The device record's live view.
        links: The links following it.
        admin: The owner's acts at the hub, as the control socket performs them.
        client: A client of the hub's local socket, served with the roster.
    """

    harness: Harness
    identities: FakeIdentityStore
    registry: DeviceRegistry
    links: DeviceLinks
    admin: AdminListener
    client: HubEngineClient

    async def act(self, act: str, **request: Any) -> dict[str, Any]:
        """One owner's act at the hub, as the control socket performs it."""
        return await self.admin._act(act, {"act": act, **request})

    async def link_of(self, device: str) -> Link | None:
        """The standing link of ``device``'s hub chat account, once every write has run."""
        await self.links.settled()
        return await self.identities.find_link(Account(kind=HUB_CHAT, identifier=device))

    async def name_in(self, conversation: str, *devices: str) -> None:
        """The owner names ``devices`` as the conversation's ends, from the hub's own machine."""
        await self.client.set_conversation_devices(
            conversation,
            devices=[ChatDevice(device_id=one, access=DeviceAccess.READ_WRITE) for one in devices],
        )

    async def recorded(self, conversation: str) -> list[str | None]:
        """The device each of the user's messages was written from, oldest first."""
        return [
            one.device_id
            for one in await written(self.harness, conversation)
            if one.author is MessageAuthor.USER
        ]

    async def work_of(self, write: Any) -> EpisodicMemory:
        """Run ``write`` and wait for the one work it starts to end."""
        before = {one.id for one in await frozen(self.harness)}
        await write()
        found: list[EpisodicMemory] = []

        async def ended() -> bool:
            found[:] = [one for one in await frozen(self.harness) if one.id not in before]
            return bool(found)

        await until(ended, what="the message's work to end")
        (episode,) = found
        return episode


@pytest.fixture
async def hub(tmp_path: Path) -> AsyncIterator[_Hub]:
    """The hub's pieces, wired as :func:`ai_assistant.service.hub._build_devices` wires them."""
    identities = FakeIdentityStore(configured=(Account(kind=HUB_CHAT, identifier=HUB_DEVICE_ID),))
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    registry = DeviceRegistry(store, hub_identity=_HUB_IDENTITY)
    links = DeviceLinks(identities, registry)
    roster = HubRoster(registry)
    harness = phases_harness(identities=identities)
    engine = harness.engine
    await engine.start()
    admin = AdminListener(registry, data_dir=tmp_path, remove_device=engine.remove_device)
    path = tmp_path / "hub.sock"

    async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=_LIMITS, roster=roster)

    server = await asyncio.start_unix_server(_serve, path=str(path))
    try:
        yield _Hub(
            harness=harness,
            identities=identities,
            registry=registry,
            links=links,
            admin=admin,
            client=HubEngineClient(path, read_timeout=_PATIENT),
        )
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        await engine.aclose()
        await links.aclose()
        store.close()


def _message(device: str, number: int) -> UserMessage:
    return UserMessage(device_id=device, message_id=f"m-{number}", text="What's on today?")


async def test_a_first_naming_that_is_a_message_records_nothing_and_reads_no_sender(
    hub: _Hub,
) -> None:
    """#3656's scenario: a gateway names a browser device for the first time on a
    ``write_message``. The naming registers the device (ADR-0298 §4:2) and links nothing
    (ADR-0378 §5:1), and the device is an end of no conversation, so the message
    is refused before anything is recorded (§5 "Writing", §6:1) — as a device holding no
    role, which it does not until the owner gives it one (§6:2) — with no message, no work,
    and no sender read for it. The hub could not have made it an end first: a set naming a
    device it does not know is refused (§4:12)."""
    conversation = (await hub.client.start_conversation()).id
    with pytest.raises(DeviceRefusedError) as unknown:
        await hub.name_in(conversation, HUB_DEVICE_ID, _BROWSER)

    with acting_for(_BROWSER), pytest.raises(DeviceRefusedError) as refused:
        await hub.client.write_message(conversation, message=_message(_BROWSER, 1))

    assert unknown.value.reason is DeviceRefusal.NOT_ALLOWED
    assert refused.value.reason is DeviceRefusal.NO_ROLE
    assert await hub.recorded(conversation) == []
    assert await frozen(hub.harness) == []
    registrations, _ = hub.registry.registrations()
    assert [(one.device_id, one.gateway) for one in registrations] == [(_BROWSER, HUB_DEVICE_ID)]
    assert await hub.link_of(_BROWSER) is None
    await hub.act("assign", identity=_BROWSER, role=DeviceRole.COMMANDS.value)
    link = await hub.link_of(_BROWSER)
    assert link is not None
    assert (link.person_id, link.act) == (OWNER_PERSON_ID, _DEVICE_ACT)


async def test_a_newly_named_devices_first_recorded_message_is_the_owners_at_the_kinds_most(
    hub: _Hub,
) -> None:
    """The first message a newly named browser device can write follows the owner's act
    naming it in the conversation, which its registration preceded. Its sender is no one
    until the owner gives it a role (ADR-0378 §5:2, "a browser device that is only such
    an end writes as an unidentified sender"); then the owner's, at the most the hub
    chat's kind declares (ADR-0366 §4:1, §5:6)."""
    conversation = (await hub.client.start_conversation()).id
    with acting_for(_BROWSER), pytest.raises(DeviceRefusedError):
        await hub.client.write_message(conversation, message=_message(_BROWSER, 1))
    await hub.name_in(conversation, HUB_DEVICE_ID, _BROWSER)

    def write(number: int) -> Any:
        async def written_by_the_browser() -> None:
            with acting_for(_BROWSER):
                await hub.client.write_message(conversation, message=_message(_BROWSER, number))

        return written_by_the_browser

    unlinked = await hub.work_of(write(2))
    await hub.act("assign", identity=_BROWSER, role=DeviceRole.COMMANDS.value)
    await hub.links.settled()
    linked = await hub.work_of(write(3))

    assert await hub.recorded(conversation) == [_BROWSER, _BROWSER]
    assert processing(unlinked).trigger.senders == (NO_LINK,)
    assert processing(linked).trigger.senders == (_OWNER_AT_MOST,)


async def test_an_enrolled_device_writes_nothing_until_the_owner_names_it(hub: _Hub) -> None:
    """Enrolled and then writing at once (ADR-0124 §6): the enrolment is the owner's act
    and the device is an end of no conversation, so its first request — decided by the
    roster as the wire server decides one, then run as that device (ADR-0298 §2:1, §2:2)
    — is refused and records nothing. Once the owner names it, its message is the
    owner's at the kind's most."""
    conversation = (await hub.client.start_conversation()).id
    reply = await hub.act("enrol", identity=_ENROLLED)
    roster = HubRoster(hub.registry)

    async def write(number: int) -> None:
        device = roster.requesting_device(connecting=_ENROLLED, acting_for=None)
        with serving_device(device):
            await hub.harness.engine.write_message(
                conversation, message=_message(_ENROLLED, number)
            )

    with pytest.raises(DeviceRefusedError) as refused:
        await write(1)
    assert await hub.recorded(conversation) == []
    await hub.name_in(conversation, HUB_DEVICE_ID, _ENROLLED)
    episode = await hub.work_of(lambda: write(2))

    assert reply["ok"] is True
    assert refused.value.reason is DeviceRefusal.NO_ROLE
    assert await hub.recorded(conversation) == [_ENROLLED]
    assert processing(episode).trigger.senders == (_OWNER_AT_MOST,)


async def test_a_restored_registration_writes_nothing_until_the_owner_names_it_again(
    hub: _Hub,
) -> None:
    """A restored registration (ADR-0298 §4:9): the revocation left the device admitted
    by nothing, so it removed the device from every set first (§4:10). The restore
    re-admits it as an end of no conversation, holding no role: its first request after
    the restore is refused, and once the owner names it again and gives it a role again
    its message is the owner's, by a new link made after the restore (ADR-0366 §3,
    ADR-0378 §5:2)."""
    conversation = (await hub.client.start_conversation()).id
    with acting_for(_BROWSER), pytest.raises(DeviceRefusedError):
        await hub.client.beliefs()
    await hub.act("assign", identity=_BROWSER, role=DeviceRole.COMMANDS.value)
    await hub.name_in(conversation, HUB_DEVICE_ID, _BROWSER)
    before = await hub.link_of(_BROWSER)
    revoked = await hub.act("revoke", identity=_BROWSER, gateway=HUB_DEVICE_ID)
    restored = await hub.act("restore", identity=_BROWSER, gateway=HUB_DEVICE_ID)
    with acting_for(_BROWSER), pytest.raises(DeviceRefusedError) as refused:
        await hub.client.write_message(conversation, message=_message(_BROWSER, 1))
    assert await hub.recorded(conversation) == []
    await hub.name_in(conversation, HUB_DEVICE_ID, _BROWSER)
    await hub.act("assign", identity=_BROWSER, role=DeviceRole.COMMANDS.value)

    async def write() -> None:
        with acting_for(_BROWSER):
            await hub.client.write_message(conversation, message=_message(_BROWSER, 2))

    episode = await hub.work_of(write)
    after = await hub.link_of(_BROWSER)

    assert (revoked["memberships"], restored["restored"]) == (True, True)
    assert refused.value.reason is DeviceRefusal.NO_ROLE
    assert processing(episode).trigger.senders == (_OWNER_AT_MOST,)
    assert before is not None
    assert after is not None
    assert after.id != before.id


async def test_a_set_naming_an_unadmitted_device_lets_its_first_naming_be_a_message(
    hub: _Hub,
) -> None:
    """The one way a first naming records a message: a conversation's devices that name a
    device the record does not admit, which the wire's §4:12 check never writes — written
    here past that check, as a set from before it bound (ADR-0298 §9:2) would be.

    The message is an unidentified sender's, at none: the naming links nothing
    (ADR-0378 §5:1), so no write of a link races the chat's read of its sender any
    more, and only the owner's act giving the device a role links it (§5:2)."""
    conversation = (await hub.client.start_conversation()).id
    held = [
        ChatDevice(device_id=one, access=DeviceAccess.READ_WRITE)
        for one in (HUB_DEVICE_ID, _BROWSER)
    ]
    await hub.harness.engine.set_conversation_devices(conversation, devices=held)
    assert not hub.registry.is_known(_BROWSER)

    async def write() -> None:
        with acting_for(_BROWSER):
            await hub.client.write_message(conversation, message=_message(_BROWSER, 1))

    episode = await hub.work_of(write)

    assert await hub.recorded(conversation) == [_BROWSER]
    registrations, _ = hub.registry.registrations()
    assert [(one.device_id, one.gateway) for one in registrations] == [(_BROWSER, HUB_DEVICE_ID)]
    assert processing(episode).trigger.senders == (NO_LINK,)
    assert await hub.link_of(_BROWSER) is None
