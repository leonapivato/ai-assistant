"""The owner's linked devices, followed into the identity store (ADR-0373 §6:2, §6:3).

Every device one of the owner's acts at the hub links — a hub device by its live
enrolment, a browser device by the roster role the owner gave it while it has a live
registration (ADR-0378 §5:2) — is linked to the owner's identity as the hub chat's
account by the owner's ``device`` act, when the act takes effect and again at every
start; an act that leaves no such act standing ends that link. No naming or
registration links anything (§5:1). Admission itself is the record's and is untouched:
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
    DeviceRole,
    LinkAct,
    LinkActHow,
    LinkWriteKind,
    Sureness,
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
_MOMENT: Final = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)  # before any link the fake dates now
_LATER: Final = _MOMENT + timedelta(minutes=5)
_DEVICE: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
_CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


def _account(device: str) -> Account:
    return Account(kind=HUB_CHAT, identifier=device)


def _given_a_role(
    registry: DeviceRegistry, device: str, *, gateway: str = HUB_DEVICE, now: datetime = _MOMENT
) -> None:
    """A gateway names a browser device, and the owner gives it a role: what links it."""
    registry.accept_naming(gateway, device, now=now)
    registry.assign(device, DeviceRole.COMMANDS)


def _marked(registry: DeviceRegistry, gateway: str = _LAPTOP) -> DeviceRegistry:
    """Enrol a gateway machine and mark it, so its namings are accepted (ADR-0378 §2:1)."""
    registry.enrol(gateway, now=_MOMENT)
    registry.mark_gateway(gateway, now=_MOMENT)
    return registry


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


@pytest.mark.parametrize("gateway", [HUB_DEVICE, _LAPTOP])
async def test_a_naming_links_nothing_and_the_role_the_owner_gives_links_the_device(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore, gateway: str
) -> None:
    """ADR-0378 §5:1: "No naming or registration makes, restores or keeps a link"; §5:2:
    the act that links a browser device is the owner's act at the hub "that gives it a
    roster role". A marked gateway's naming and the hub's own are alike; later namings
    add nothing."""
    if gateway != HUB_DEVICE:
        _marked(registry, gateway)
    registry.accept_naming(gateway, _PHONE, now=_MOMENT)
    await links.settled()
    assert _PHONE not in await _standing(identities)

    registry.assign(_PHONE, DeviceRole.COMMANDS)
    registry.accept_naming(gateway, _PHONE, now=_LATER)
    await links.settled()

    (held,) = await _links_of(identities, _PHONE)
    assert held.standing
    assert held.act == _DEVICE


async def test_a_link_stands_only_while_the_device_holds_a_role(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """ADR-0378 §5:2: the link "stands only while the device has a live registration and
    holds a roster role". Taking the last role ends it; giving one again is a new act and
    a new link (ADR-0366 §3)."""
    _given_a_role(registry, _PHONE)
    registry.assign(_PHONE, DeviceRole.SPOKES)
    await links.settled()

    registry.withdraw(_PHONE, DeviceRole.SPOKES)
    await links.settled()
    assert _PHONE in await _standing(identities)

    registry.withdraw(_PHONE, DeviceRole.COMMANDS)
    await links.settled()
    assert _PHONE not in await _standing(identities)

    registry.assign(_PHONE, DeviceRole.COMMANDS)
    await links.settled()
    first, second = await _links_of(identities, _PHONE)
    assert (first.standing, second.standing) == (False, True)


async def test_a_machine_enrolled_after_it_was_named_is_linked_by_its_enrolment_alone(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """ADR-0378 §3:3: once enrolled, no naming reaches it, its earlier registrations
    included, so revoking its enrolment ends its link though a registration and a role
    still stand on the record."""
    _given_a_role(registry, _PHONE)
    registry.enrol(_PHONE, now=_LATER)
    await links.settled()
    assert _PHONE in await _standing(identities)

    registry.revoke(_PHONE, now=_LATER)
    await links.settled()

    assert registry.roles_of(_PHONE) == frozenset({DeviceRole.COMMANDS})
    assert _PHONE not in await _standing(identities)


async def test_a_link_stands_while_anything_still_admits_the_device(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Revoking one registration of two leaves it registered and holding its role, so its
    link stands; the last revocation ends it."""
    _marked(registry)
    _given_a_role(registry, _PHONE, gateway=_LAPTOP)
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
    registry.accept_naming(HUB_DEVICE, _LAPTOP, now=_MOMENT)
    registry.enrol(_LAPTOP, now=_MOMENT)
    await links.settled()
    registry.revoke_device(_LAPTOP, now=_LATER)
    await links.settled()

    assert _LAPTOP not in await _standing(identities)


async def test_a_restored_registration_links_the_device_again_by_a_new_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """An ended link is kept and ties nothing; a later act naming the account again is a
    new link, with an id of its own (ADR-0366 §3). A restored registration holds no role
    (ADR-0298 §4:11), so the link comes back with the role the owner gives it again."""
    _given_a_role(registry, _PHONE)
    await links.settled()
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    await links.settled()
    registry.restore_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    await links.settled()
    assert _PHONE not in await _standing(identities)
    registry.assign(_PHONE, DeviceRole.COMMANDS)
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
    _given_a_role(registry, _PHONE)
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
        _given_a_role(registry, _HOSTED)
        await links.settled()
        (held,) = await _links_of(identities, _HOSTED)
        assert held.standing
        assert held.act == _CONFIGURED

        registry.revoke_registration(_HOSTED, gateway=HUB_DEVICE, now=_LATER)
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
    """Devices linkable before this change, or while a link write failed, are linked; a
    ``device`` link whose device is no longer linkable is ended; other links stand.

    ADR-0378 §5:3, the upgrade: "a browser device's standing ``device`` link stands where
    §5:2 holds and is ended where it does not, with no act of the owner's" — a browser
    device a naming linked under ADR-0373, and the owner never gave a role, is unlinked
    at the first start."""
    store.enrol(_LAPTOP, verifier="v", now=_MOMENT)
    store.register(_PHONE, gateway=_LAPTOP, now=_MOMENT)
    store.assign_role(_PHONE, DeviceRole.COMMANDS)
    store.register("nTABLETXCNTRL", gateway=_LAPTOP, now=_MOMENT)
    named = await identities.link(OWNER_PERSON_ID, _account("nTABLETXCNTRL"), act=_DEVICE)
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
    (unlinked,) = await _links_of(identities, "nTABLETXCNTRL")
    assert (unlinked.id, unlinked.standing) == (named.record_id, False)
    (logged,) = [entry for entry in captured if entry["event"] == "device_links_followed"]
    assert (logged["linked"], logged["ended"]) == (2, 2)


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
    store.assign_role(_PHONE, DeviceRole.COMMANDS)
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


async def test_a_revocation_and_a_restore_back_to_back_end_the_old_link_and_make_a_new_one(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """Two acts, however close: the link the revoked registration stood on ends with it,
    lowerings and all, and the restore with the role given again makes a new link
    (ADR-0366 §3, ADR-0373 §6:3)."""
    _given_a_role(registry, _PHONE)
    await links.settled()
    (first,) = await _links_of(identities, _PHONE)
    await identities.lower(first.id, Sureness.WEAK, by=OWNER_PERSON_ID)

    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    registry.restore_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    registry.assign(_PHONE, DeviceRole.COMMANDS)
    await links.settled()

    ended, made = await _links_of(identities, _PHONE)
    assert ended.id == first.id
    assert not ended.standing
    assert made.standing
    assert made.lowerings == ()


async def test_ending_a_device_link_hands_a_configured_account_back_to_the_configuration(
    registry: DeviceRegistry,
) -> None:
    """The hosted device set to a device its admission already linked: L1's opening finds
    the account held and links nothing, so when the admission ends, the account is
    linked again by the ``configured`` act it still stands on, never left unlinked."""
    identities = FakeIdentityStore(configured=(_account(HUB_DEVICE_ID),))
    _given_a_role(registry, _HOSTED)
    await identities.link(OWNER_PERSON_ID, _account(_HOSTED), act=_DEVICE)
    links = DeviceLinks(
        identities, registry, configured=(_account(HUB_DEVICE_ID), _account(_HOSTED))
    )
    try:
        registry.revoke_registration(_HOSTED, gateway=HUB_DEVICE, now=_LATER)
        await links.settled()
    finally:
        await links.aclose()

    ended, configured = await _links_of(identities, _HOSTED)
    assert (ended.act, ended.standing) == (_DEVICE, False)
    assert (configured.act, configured.standing) == (_CONFIGURED, True)


async def test_following_at_start_hands_a_configured_account_back_to_the_configuration(
    store: EnrolmentStore,
) -> None:
    """A revoked device whose link write failed, then named as the hosted device: the
    start ends its ``device`` link and links the account by the ``configured`` act."""
    identities = FakeIdentityStore(configured=(_account(HUB_DEVICE_ID),))
    await identities.link(OWNER_PERSON_ID, _account(_HOSTED), act=_DEVICE)
    links = DeviceLinks(
        identities,
        DeviceRegistry(store, hub_identity=_HUB),
        configured=(_account(HUB_DEVICE_ID), _account(_HOSTED)),
    )
    try:
        await links.follow()
    finally:
        await links.aclose()

    assert await _standing(identities) == {HUB_DEVICE_ID: _CONFIGURED, _HOSTED: _CONFIGURED}


async def test_a_failed_end_then_a_restore_does_not_keep_the_revoked_admissions_link(
    registry: DeviceRegistry, links: DeviceLinks, identities: FakeIdentityStore
) -> None:
    """The revocation's write failed, so its link still stood when the restore came: the
    restore and the role given again end it, lowering and all, and make a new one
    (ADR-0373 §6:3)."""
    _given_a_role(registry, _PHONE)
    await links.settled()
    (first,) = await _links_of(identities, _PHONE)
    await identities.lower(first.id, Sureness.WEAK, by=OWNER_PERSON_ID)

    identities.fail_next()
    # After the link was written, which the fake dates by the wall clock.
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=datetime.now(UTC))
    await links.settled()
    registry.restore_registration(
        _PHONE, gateway=HUB_DEVICE, now=datetime.now(UTC) + timedelta(seconds=1)
    )
    registry.assign(_PHONE, DeviceRole.COMMANDS)
    await links.settled()

    ended, made = await _links_of(identities, _PHONE)
    assert ended.id == first.id
    assert not ended.standing
    assert (made.standing, made.lowerings) == (True, ())


async def test_the_next_start_ends_a_link_its_device_outlived(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """Revoked and admitted again while nothing wrote the links: the start reads the
    record, which keeps the revocation, and replaces the link the revocation ended."""
    registry = DeviceRegistry(store, hub_identity=_HUB)
    links = DeviceLinks(identities, registry)
    _given_a_role(registry, _PHONE)
    await links.settled()
    await links.aclose()
    (first,) = await _links_of(identities, _PHONE)
    # After the link was written, which the fake dates by the wall clock.
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=datetime.now(UTC))
    registry.restore_registration(
        _PHONE, gateway=HUB_DEVICE, now=datetime.now(UTC) + timedelta(seconds=1)
    )
    registry.assign(_PHONE, DeviceRole.COMMANDS)

    restarted = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await restarted.follow()
    finally:
        await restarted.aclose()

    ended, made = await _links_of(identities, _PHONE)
    assert (ended.id, ended.standing) == (first.id, False)
    assert made.standing


async def test_a_device_admitted_without_a_break_keeps_its_link_at_start(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """A rotation, or an enrolment while still registered, breaks nothing: the link made
    under the first admission stands across starts."""
    registry = DeviceRegistry(store, hub_identity=_HUB)
    links = DeviceLinks(identities, registry)
    _given_a_role(registry, _PHONE)
    registry.enrol(_PHONE, now=_LATER)
    await links.settled()
    await links.aclose()
    registry.enrol(_PHONE, now=_LATER + timedelta(minutes=1))
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER + timedelta(minutes=2))

    restarted = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await restarted.follow()
    finally:
        await restarted.aclose()

    (held,) = await _links_of(identities, _PHONE)
    assert held.standing


async def test_a_late_replay_writes_no_link_for_an_admission_already_ended(
    store: EnrolmentStore,
    registry: DeviceRegistry,
    links: DeviceLinks,
    identities: FakeIdentityStore,
) -> None:
    """Named, given a role, revoked, restored and given a role again before any write ran,
    with the store failing once on the way: only the restore's admission is linked, so no
    link stands on the revoked one, and the next start finds nothing to change."""
    _given_a_role(registry, _PHONE)
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER)
    registry.restore_registration(_PHONE, gateway=HUB_DEVICE, now=_LATER + timedelta(minutes=1))
    registry.assign(_PHONE, DeviceRole.COMMANDS)
    identities.fail_next()
    await links.settled()

    (held,) = await _links_of(identities, _PHONE)
    assert held.standing

    restarted = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await restarted.follow()
    finally:
        await restarted.aclose()
    assert await _links_of(identities, _PHONE) == [held]


async def test_tied_admissions_one_revoked_do_not_stop_the_start(
    store: EnrolmentStore, identities: FakeIdentityStore
) -> None:
    """A registration and an enrolment made at one instant, the registration later
    revoked: the admission runs on unbroken, and the start keeps the link."""
    store.register(_PHONE, gateway=_LAPTOP, now=_MOMENT)
    store.enrol(_PHONE, verifier="v", now=_MOMENT)
    linked = await identities.link(OWNER_PERSON_ID, _account(_PHONE), act=_DEVICE)
    store.revoke_registration(_PHONE, gateway=_LAPTOP, now=_LATER)
    links = DeviceLinks(identities, DeviceRegistry(store, hub_identity=_HUB))
    try:
        await links.follow()
    finally:
        await links.aclose()

    (held,) = await _links_of(identities, _PHONE)
    assert (held.id, held.standing) == (linked.record_id, True)
