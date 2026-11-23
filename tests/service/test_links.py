"""The owner's admitted devices, followed into the identity store (ADR-0373 §6:2, §6:3).

Every device the record admits — enrolled at the hub, or registered by a gateway — is
linked to the owner's identity as the hub chat's account by the owner's ``device`` act,
when the act takes effect and again at every start; a revocation that leaves the device
admitted by nothing ends that link. Admission itself is the record's and is untouched:
each case drives the real record and its registry over a temporary data directory, and
the canonical fake identity store, whose contract the store under the hub keeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
import structlog

from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    LinkAct,
    LinkActHow,
    LinkWriteKind,
)
from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    HUB_DEVICE,
    DeviceRegistry,
    EnrolmentStore,
    Refusal,
)
from ai_assistant.service.links import HUB_CHAT, DeviceLinks
from ai_assistant.testing import FakeIdentityStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.types import Link

_HUB: Final = "nHUBAAAACNTRL"
_LAPTOP: Final = "nLAPTOP1CNTRL"
_PHONE: Final = "nPHONE22CNTRL"
_WATCH: Final = "nWATCH33CNTRL"
_HOSTED: Final = "browser-hosted"
_MOMENT: Final = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_LATER: Final = _MOMENT + timedelta(minutes=5)
_DEVICE: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
_CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


def _account(device: str) -> Account:
    return Account(kind=HUB_CHAT, identifier=device)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[EnrolmentStore]:
    """One device record inside a temporary data directory."""
    opened = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def registry(store: EnrolmentStore) -> DeviceRegistry:
    """Its live view, on a hub with a remote listener."""
    return DeviceRegistry(store, hub_identity=_HUB)


@pytest.fixture
def identities() -> FakeIdentityStore:
    """The identity store as the hub opens it: the owner, with ``hub`` configured."""
    return FakeIdentityStore(configured=(_account(HUB_DEVICE_ID),))


@pytest.fixture
async def links(
    identities: FakeIdentityStore, registry: DeviceRegistry
) -> AsyncIterator[DeviceLinks]:
    """The record's acts, followed into the store from now on."""
    following = DeviceLinks(identities, registry)
    try:
        yield following
    finally:
        await following.aclose()


async def _standing(identities: FakeIdentityStore) -> dict[str, LinkAct]:
    """Each standing link of the hub chat's, by device, with its act."""
    owner = await identities.identity(OWNER_PERSON_ID)
    assert owner is not None
    return {
        one.account.identifier: one.act
        for one in owner.standing_links
        if one.account.kind == HUB_CHAT
    }


async def _links_of(identities: FakeIdentityStore, device: str) -> list[Link]:
    """Every link the device's account was ever tied by, in the order made."""
    owner = await identities.identity(OWNER_PERSON_ID)
    assert owner is not None
    return [one for one in owner.links if one.account == _account(device)]


# --- at the act -----------------------------------------------------------------------


async def test_an_enrolment_links_the_device_to_the_owner_by_the_device_act(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()

    held = await identities.find_link(_account(_LAPTOP))
    assert held is not None
    assert held.person_id == OWNER_PERSON_ID
    assert held.act == _DEVICE
    assert await _standing(identities) == {HUB_DEVICE_ID: _CONFIGURED, _LAPTOP: _DEVICE}


async def test_a_revocation_ends_the_link_and_keeps_it(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """ADR-0373 §6:3: once its device's enrolment is revoked, the link no longer stands."""
    registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()
    registry.revoke(_LAPTOP, now=_LATER)
    await links.settled()

    assert await identities.find_link(_account(_LAPTOP)) is None
    (kept,) = await _links_of(identities, _LAPTOP)
    assert not kept.standing
    assert kept.act == _DEVICE


async def test_a_rotation_keeps_the_one_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Re-enrolling is one act that keeps the device admitted throughout (ADR-0124 §6)."""
    registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()
    registry.enrol(_LAPTOP, now=_LATER)
    await links.settled()

    (held,) = await _links_of(identities, _LAPTOP)
    assert held.standing


async def test_a_gateways_first_naming_links_the_browser_device_and_later_ones_add_nothing(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    registry.accept_naming(_LAPTOP, _PHONE, now=_MOMENT)
    await links.settled()
    registry.accept_naming(_LAPTOP, _PHONE, now=_LATER)
    await links.settled()

    (held,) = await _links_of(identities, _PHONE)
    assert held.standing
    assert held.act == _DEVICE


async def test_a_gateway_on_the_hubs_own_machine_links_what_it_names(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    registry.accept_naming(HUB_DEVICE, _PHONE, now=_MOMENT)
    await links.settled()

    assert (await _standing(identities))[_PHONE] == _DEVICE


async def test_a_link_stands_while_anything_still_admits_the_device(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Revoking one registration of two, or the enrolment of a device still registered,
    leaves it admitted, so its link stands; the last revocation ends it."""
    registry.accept_naming(_LAPTOP, _PHONE, now=_MOMENT)
    registry.accept_naming(HUB_DEVICE, _PHONE, now=_MOMENT)
    await links.settled()

    registry.revoke_registration(_PHONE, gateway=_LAPTOP, now=_LATER)
    await links.settled()
    assert _PHONE in await _standing(identities)

    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    await links.settled()
    assert _PHONE not in await _standing(identities)


async def test_an_enrolled_device_keeps_its_link_when_a_registration_of_it_is_revoked(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    registry.accept_naming(HUB_DEVICE, _LAPTOP, now=_MOMENT)
    registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()
    registry.revoke_registration(_LAPTOP, gateway=HUB_DEVICE, now=_LATER)
    await links.settled()

    (held,) = await _links_of(identities, _LAPTOP)
    assert held.standing


async def test_revoking_a_whole_device_ends_its_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    registry.enrol(_LAPTOP, now=_MOMENT)
    registry.accept_naming(HUB_DEVICE, _LAPTOP, now=_MOMENT)
    await links.settled()
    registry.revoke_device(_LAPTOP, now=_LATER)
    await links.settled()

    assert _LAPTOP not in await _standing(identities)


async def test_a_restored_registration_links_the_device_again_by_a_new_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """An ended link is kept and ties nothing; a later act naming the account again is a
    new link, with an id of its own (ADR-0366 §3)."""
    registry.accept_naming(_LAPTOP, _PHONE, now=_MOMENT)
    await links.settled()
    registry.revoke_registration(_PHONE, gateway=_LAPTOP, now=_LATER)
    await links.settled()
    registry.restore_registration(_PHONE, gateway=_LAPTOP, now=_LATER)
    await links.settled()

    first, second = await _links_of(identities, _PHONE)
    assert not first.standing
    assert second.standing
    assert second.id != first.id


async def test_an_act_and_its_undoing_back_to_back_leave_no_standing_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Each write reads the record when it runs, so an enrolment's write still pending
    when its revocation lands cannot leave a revoked device linked."""
    registry.enrol(_LAPTOP, now=_MOMENT)
    registry.revoke(_LAPTOP, now=_LATER)
    registry.accept_naming(_LAPTOP, _PHONE, now=_MOMENT)
    registry.revoke_device(_PHONE, now=_LATER)
    await links.settled()

    assert await _standing(identities) == {HUB_DEVICE_ID: _CONFIGURED}


async def test_the_act_itself_is_unchanged_and_its_reply_waits_on_no_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Admission is the record's (ADR-0124 §8): it holds the instant the act returns,
    before any link is written."""
    minted = registry.enrol(_LAPTOP, now=_MOMENT)

    assert registry.verify(_LAPTOP, minted.credential).enrolment_id is not None
    assert await identities.find_link(_account(_LAPTOP)) is None
    await links.settled()
    assert await identities.find_link(_account(_LAPTOP)) is not None


# --- one link per account ---------------------------------------------------------------


async def test_the_hosted_device_keeps_its_one_configured_link(
    registry: DeviceRegistry,
) -> None:
    """The web door's hosted device is the configuration's link (L1): a gateway's naming
    of it makes no second, and a revocation of that naming does not end it."""
    identities = FakeIdentityStore(
        configured=(_account(HUB_DEVICE_ID), _account(_HOSTED)),
    )
    links = DeviceLinks(identities, registry)
    try:
        registry.accept_naming(_LAPTOP, _HOSTED, now=_MOMENT)
        await links.settled()
        (held,) = await _links_of(identities, _HOSTED)
        assert held.standing
        assert held.act == _CONFIGURED

        registry.revoke_registration(_HOSTED, gateway=_LAPTOP, now=_LATER)
        await links.settled()
        await links.follow()
        (held,) = await _links_of(identities, _HOSTED)
        assert held.standing
        assert held.act == _CONFIGURED
    finally:
        await links.aclose()


async def test_the_hubs_own_machine_is_never_linked_by_a_device_act(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """``hub`` is the configuration's link (L1), and the hub's own overlay identity, which a
    record written before ADR-0298 may hold enrolled, is the hub's own machine too."""
    store.enrol(_HUB, verifier="v", now=_MOMENT)
    registry = DeviceRegistry(store, hub_identity=_HUB)
    links = DeviceLinks(identities, registry)
    try:
        await links.follow()
        registry.revoke_device(_HUB, now=_LATER)
        await links.settled()
    finally:
        await links.aclose()

    owner = await identities.identity(OWNER_PERSON_ID)
    assert owner is not None
    assert [(one.account, one.act) for one in owner.links] == [
        (_account(HUB_DEVICE_ID), _CONFIGURED)
    ]


# --- at start ---------------------------------------------------------------------------


async def test_following_at_start_links_what_was_admitted_and_ends_what_was_not(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """Devices admitted before this change, or while a link write failed, are linked; a
    ``device`` link whose device is no longer admitted is ended; other links stand."""
    store.enrol(_LAPTOP, verifier="v", now=_MOMENT)
    store.register(_PHONE, gateway=_LAPTOP, now=_MOMENT)
    left = await identities.link(OWNER_PERSON_ID, _account(_WATCH), act=_DEVICE)
    telegram = Account(kind="telegram", identifier="424242")
    await identities.link(OWNER_PERSON_ID, telegram, act=_CONFIGURED)
    links = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        with structlog.testing.capture_logs() as captured:
            await links.follow()
    finally:
        await links.aclose()

    assert await _standing(identities) == {
        HUB_DEVICE_ID: _CONFIGURED,
        _LAPTOP: _DEVICE,
        _PHONE: _DEVICE,
    }
    assert await identities.find_link(telegram) is not None
    (ended,) = await _links_of(identities, _WATCH)
    assert ended.id == left.record_id
    assert not ended.standing
    (logged,) = [entry for entry in captured if entry["event"] == "device_links_followed"]
    assert (logged["linked"], logged["ended"]) == (2, 1)


async def test_following_again_changes_nothing(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    store.enrol(_LAPTOP, verifier="v", now=_MOMENT)
    links = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await links.follow()
        before = await identities.export()
        with structlog.testing.capture_logs() as captured:
            await links.follow()
    finally:
        await links.aclose()

    assert await identities.export() == before
    assert not [entry for entry in captured if entry["event"] == "device_links_followed"]


async def test_a_hub_with_no_remote_listener_follows_its_browser_devices(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """A gateway on the hub's own machine serves listed browsers with no remote listener
    (ADR-0298 §4:13), so those devices are linked on such a hub too."""
    store.register(_PHONE, gateway=HUB_DEVICE, now=_MOMENT)
    links = DeviceLinks(identities, DeviceRegistry(store, hub_identity=None))
    try:
        await links.follow()
    finally:
        await links.aclose()

    assert (await _standing(identities))[_PHONE] == _DEVICE


# --- what a failed link write does ------------------------------------------------------


async def test_a_failed_link_write_leaves_the_act_done_and_the_next_start_repairs_it(
    store: EnrolmentStore,
    registry: DeviceRegistry,
    links: DeviceLinks,
    identities: FakeIdentityStore,
) -> None:
    identities.fail_next()
    with structlog.testing.capture_logs() as captured:
        minted = registry.enrol(_LAPTOP, now=_MOMENT)
        await links.settled()

    assert registry.verify(_LAPTOP, minted.credential).enrolment_id is not None
    assert await identities.find_link(_account(_LAPTOP)) is None
    (logged,) = [entry for entry in captured if entry["event"] == "device_link_unwritten"]
    assert logged["device"] == _LAPTOP
    assert logged["error_class"] == "IdentityStoreError"

    restarted = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await restarted.follow()
    finally:
        await restarted.aclose()
    assert (await _standing(identities))[_LAPTOP] == _DEVICE


async def test_a_failed_end_leaves_the_revocation_done_and_the_next_start_ends_the_link(
    store: EnrolmentStore,
    registry: DeviceRegistry,
    links: DeviceLinks,
    identities: FakeIdentityStore,
) -> None:
    minted = registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()
    identities.fail_next()
    registry.revoke(_LAPTOP, now=_LATER)
    await links.settled()

    assert registry.verify(_LAPTOP, minted.credential).refusal is Refusal.REVOKED
    assert _LAPTOP in await _standing(identities)

    restarted = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await restarted.follow()
    finally:
        await restarted.aclose()
    assert _LAPTOP not in await _standing(identities)


async def test_a_store_fault_at_start_is_logged_and_does_not_refuse_the_start(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    store.enrol(_LAPTOP, verifier="v", now=_MOMENT)
    links = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    identities.fail_next()
    try:
        with structlog.testing.capture_logs() as captured:
            await links.follow()
    finally:
        await links.aclose()

    assert [entry["event"] for entry in captured] == ["device_links_unfollowed"]
    assert _LAPTOP not in await _standing(identities)


async def test_an_act_after_close_writes_nothing_and_says_so(
    registry: DeviceRegistry, identities: FakeIdentityStore
) -> None:
    """The drain closes the identity store, so the hub stops following before it."""
    links = DeviceLinks(identities, registry)
    await links.aclose()
    with structlog.testing.capture_logs() as captured:
        registry.enrol(_LAPTOP, now=_MOMENT)
        await links.settled()

    assert await identities.find_link(_account(_LAPTOP)) is None
    (logged,) = [entry for entry in captured if entry["event"] == "device_link_unwritten"]
    assert logged["device"] == _LAPTOP


async def test_closing_lets_a_pending_write_go(
    registry: DeviceRegistry, identities: FakeIdentityStore
) -> None:
    links = DeviceLinks(identities, registry)
    registry.enrol(_LAPTOP, now=_MOMENT)
    with structlog.testing.capture_logs() as captured:
        await links.aclose()

    assert await identities.find_link(_account(_LAPTOP)) is None
    assert [entry["event"] for entry in captured] == ["device_link_unwritten"]


async def test_a_refused_link_is_logged_and_changes_nothing(
    registry: DeviceRegistry, identities: FakeIdentityStore
) -> None:
    """A standing link ties an account to one identity at most: an account someone else's
    link holds is never taken over by a device act."""
    identities.hold_identity("person:other")
    other = await identities.link(
        "person:other", _account(_LAPTOP), act=LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
    )
    assert other.kind is LinkWriteKind.WRITTEN
    links = DeviceLinks(identities, registry)
    try:
        with structlog.testing.capture_logs() as captured:
            registry.enrol(_LAPTOP, now=_MOMENT)
            await links.settled()
    finally:
        await links.aclose()

    held = await identities.find_link(_account(_LAPTOP))
    assert held is not None
    assert held.person_id == "person:other"
    (logged,) = [entry for entry in captured if entry["event"] == "device_link_refused"]
    assert logged["refusal"] == "already_linked"
