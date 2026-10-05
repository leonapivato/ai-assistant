"""The hub's side of the wire's device seam (ADR-0298 §2:1, §3, §4, §6; issue #2726).

:class:`~ai_assistant.service.roster.HubRoster` is what the listeners pass the wire
server, and passing it is the cutover (§9:3). What is here is the decision it makes
for each request — which device the request is for, with which roles — and the
refusals it gives; the route table's checks over that device are pinned in
``tests/wire``, and the listeners' wiring in ``test_transport.py``,
``test_remote_listener.py`` and ``test_hub.py``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import AssistantError, DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import HUB_DEVICE_ID, HUB_REQUESTING_DEVICE, DeviceRole
from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    DeviceKind,
    DeviceRegistry,
    EnrolmentStore,
)
from ai_assistant.service.roster import HubRoster

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.wire.server import DeviceRoster

_HUB: Final = "nHUBAAAACNTRL"
_GATEWAY: Final = "nLAPTOP1CNTRL"
_PHONE: Final = "nPHONE22CNTRL"
_MOMENT: Final = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[EnrolmentStore]:
    """One record inside a temporary data directory."""
    opened = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def registry(store: EnrolmentStore) -> DeviceRegistry:
    """The live view over it, on a hub with a remote listener."""
    return DeviceRegistry(store, hub_identity=_HUB)


@pytest.fixture
def roster(registry: DeviceRegistry) -> HubRoster:
    """The seam over that view."""
    return HubRoster(registry)


def _refused(roster: HubRoster, *, connecting: str, acting_for: str | None) -> DeviceRefusedError:
    """The refusal a request on that connection naming that device receives."""
    with pytest.raises(DeviceRefusedError) as raised:
        roster.requesting_device(connecting=connecting, acting_for=acting_for)
    return raised.value


def test_the_hub_roster_is_the_wires_device_seam(roster: HubRoster) -> None:
    """ADR-0298 §10:7: the seam is a local ``Protocol`` in ``wire``, implemented here."""
    seam: DeviceRoster = roster
    assert seam is roster


# --- the loopback socket: the hub's own machine and the browsers it relays ----------


def test_a_request_on_the_local_socket_naming_no_one_is_the_hubs_own(
    roster: HubRoster,
) -> None:
    """ADR-0298 §3:2: the hub's own machine holds every role "as the requesting device
    of a request on the local socket with no ``acting_for``"."""
    device = roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=None)

    assert device == HUB_REQUESTING_DEVICE


def test_a_browser_a_gateway_on_the_hubs_machine_names_is_registered_under_hub(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §4:2, §4:4, §8:1: the first naming registers the machine under the
    connecting device — ``hub`` for a gateway on the local socket — and the request
    acts with *that* device's roles, which for a new browser device are none.

    The discriminating half of the case above: a roster that answered the local
    socket with every role whatever the frame named would hand every listed browser
    the hub's own authority.
    """
    device = roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    assert device.device_id == _PHONE
    assert device.roles == frozenset()
    assert registry.kind_of(_PHONE) is DeviceKind.BROWSER
    ((registration,), _) = registry.registrations()
    assert (registration.device_id, registration.gateway) == (_PHONE, HUB_DEVICE_ID)


def test_a_named_device_acts_with_the_roles_the_owner_gave_it(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §2:3: the roles "§4 records for it at dispatch" — read on every
    request, so an assignment takes effect on the next one."""
    roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)
    registry.assign(_PHONE, DeviceRole.COMMANDS)

    device = roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    assert device.roles == frozenset({DeviceRole.COMMANDS})


# --- the remote listener: an enrolled device, and a gateway on it ----------------------


def test_an_enrolled_device_acts_with_its_own_roles(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §2:1 and §9:4: the connecting device on the remote listener is the
    enrolled device, which holds no role until the owner gives it one."""
    registry.enrol(_GATEWAY, now=_MOMENT)

    before = roster.requesting_device(connecting=_GATEWAY, acting_for=None)
    registry.assign(_GATEWAY, DeviceRole.SPOKES)
    after = roster.requesting_device(connecting=_GATEWAY, acting_for=None)

    assert before.device_id == _GATEWAY
    assert before.roles == frozenset()
    assert after.roles == frozenset({DeviceRole.SPOKES})


def test_a_remote_gateways_naming_registers_the_browser_under_that_gateway(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §4:4: the gateway of a registration is the connecting device — here an
    enrolled hub device — and the request acts as the browser, not as the gateway (§8:1).
    """
    registry.enrol(_GATEWAY, now=_MOMENT)
    registry.assign(_GATEWAY, DeviceRole.COMMANDS)

    device = roster.requesting_device(connecting=_GATEWAY, acting_for=_PHONE)

    assert device.device_id == _PHONE
    assert device.roles == frozenset()
    ((registration,), _) = registry.registrations()
    assert registration.gateway == _GATEWAY


# --- refusals: §6:2's first reason ------------------------------------------------------


def test_a_revoked_registration_is_refused_and_registers_nothing(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §4:9: "a gateway naming it again is refused (§6) and does not register
    it again", with §6:2's first reason."""
    roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)
    registry.revoke_registration(_PHONE, gateway=HUB_DEVICE_ID, now=_MOMENT)

    refusal = _refused(roster, connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    assert refusal.reason is DeviceRefusal.NOT_ACCEPTED
    assert "revoked" in str(refusal)
    assert not registry.is_known(_PHONE)


def test_a_naming_beyond_the_gateways_bound_is_refused(store: EnrolmentStore) -> None:
    """ADR-0298 §4:7: "refuses a naming beyond it (§6)"."""
    registry = DeviceRegistry(store, hub_identity=_HUB, max_registrations_per_gateway=1)
    roster = HubRoster(registry)
    roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    refusal = _refused(roster, connecting=HUB_DEVICE_ID, acting_for="nTABLETXCNTRL")

    assert refusal.reason is DeviceRefusal.NOT_ACCEPTED
    assert not registry.is_known("nTABLETXCNTRL")


def test_no_gateway_may_name_the_hubs_own_overlay_identity(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §3:3: "nor the hub's own overlay identity where the hub has one"."""
    refusal = _refused(roster, connecting=HUB_DEVICE_ID, acting_for=_HUB)

    assert refusal.reason is DeviceRefusal.NOT_ACCEPTED
    assert registry.registrations()[1] == 0


def test_a_live_enrolment_of_the_hubs_own_identity_is_refused_every_request(
    store: EnrolmentStore,
) -> None:
    """Issue #2726: a record written before ADR-0298 can hold a live enrolment of the
    hub's own overlay identity, and ADR-0124's two facts still admit its connection.

    §3:3 has the hub's own machine reach the hub "through the local socket … and
    through nothing else", and §6:2 names "the hub's own overlay identity" among the
    devices not accepted, so every request on that connection is refused — its own and
    any it relays — and the identity is no device a set may name (§4:11). The record
    is written directly, because the registry no longer enrols it (§3:4).
    """
    store.enrol(_HUB, verifier="unused", now=_MOMENT)
    registry = DeviceRegistry(store, hub_identity=_HUB)
    roster = HubRoster(registry)

    own = _refused(roster, connecting=_HUB, acting_for=None)
    relayed = _refused(roster, connecting=_HUB, acting_for=_PHONE)

    assert own.reason is DeviceRefusal.NOT_ACCEPTED
    assert relayed.reason is DeviceRefusal.NOT_ACCEPTED
    assert "revoke" in str(own)
    assert registry.registrations()[1] == 0
    assert not roster.knows(_HUB)


# --- §4:11: the devices a set may name ---------------------------------------------------


def test_the_roster_knows_the_hub_and_admitted_devices_only(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """ADR-0298 §4:11: "``hub``, an enrolled hub device whose enrolment is live, or a
    browser device with a live registration"."""
    registry.enrol(_GATEWAY, now=_MOMENT)
    roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    assert roster.knows(HUB_DEVICE_ID)
    assert roster.knows(_GATEWAY)
    assert roster.knows(_PHONE)
    assert not roster.knows("nNEVERSEENCNTRL")
    assert not roster.knows(_HUB)

    registry.revoke_device(_PHONE, now=_MOMENT)
    assert not roster.knows(_PHONE)


def test_a_device_being_revoked_is_refused_and_known_as_no_device(
    roster: HubRoster, registry: DeviceRegistry
) -> None:
    """While the owner's revocation removes a device from every set it is refused every
    request — its own, and any relayed for it — and no set may name it, so it cannot
    put itself back before the record moves (review of PR #2727)."""
    registry.enrol(_GATEWAY, now=_MOMENT)
    roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    with registry.withheld(_PHONE), registry.withheld(_GATEWAY):
        relayed = _refused(roster, connecting=HUB_DEVICE_ID, acting_for=_PHONE)
        own = _refused(roster, connecting=_GATEWAY, acting_for=None)
        known = (roster.knows(_PHONE), roster.knows(_GATEWAY))

    assert relayed.reason is DeviceRefusal.NOT_ACCEPTED
    assert own.reason is DeviceRefusal.NOT_ACCEPTED
    assert known == (False, False)
    assert roster.knows(_PHONE), "released once the block ends"


def test_a_registration_the_record_cannot_write_is_a_declared_failure(
    roster: HubRoster,
    registry: DeviceRegistry,
    store: EnrolmentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first naming writes one row; a storage fault there is answered as a declared
    failure the wire turns into an error frame, never an undeclared exception that
    would close the gateway's connection, and nothing is registered."""

    def _unwritable(*args: object, **kwargs: object) -> int:
        msg = "attempt to write a readonly database"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(store, "register", _unwritable)

    with pytest.raises(AssistantError) as failed:
        roster.requesting_device(connecting=HUB_DEVICE_ID, acting_for=_PHONE)

    assert not isinstance(failed.value, DeviceRefusedError)
    assert isinstance(failed.value.__cause__, sqlite3.OperationalError)
    assert not registry.is_known(_PHONE)
