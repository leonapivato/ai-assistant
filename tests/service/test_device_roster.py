"""The device roster beside the enrolments (ADR-0298 §3, §4; ADR-0296 §1, §2).

The enrolment record's own promises are in ``test_enrolment.py`` and the door the
owner's acts arrive through in ``test_admin.py``. What is here is what the roster
promises: a gateway's first naming registers a machine, a revoked registration stays
revoked until the owner restores it, ``hub`` is never a row, the per-gateway bound,
a whole device's revocation, and the invariant that a device holds a role only while
something admits it.

Nothing here refuses a request: the roster records and answers (ADR-0298 §9).
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
import structlog

from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    EVERY_ROLE,
    HUB_DEVICE,
    MAX_REGISTRATIONS_PER_GATEWAY,
    DeviceKind,
    DeviceRegistry,
    EnrolmentStore,
    NamingRefusal,
    Role,
    RosterActError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_HUB: Final = "nHUBAAAACNTRL"
_GATEWAY: Final = "nLAPTOP1CNTRL"
_OTHER_GATEWAY: Final = "nDESKTOPCNTRL"
_PHONE: Final = "nPHONE22CNTRL"
_WATCH: Final = "nWATCH33CNTRL"
_MOMENT: Final = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_LATER: Final = _MOMENT + timedelta(minutes=5)


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


# --- registration: a gateway's first naming is the listing reaching the hub --------


def test_a_first_naming_registers_a_browser_device_with_no_role(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:2 and §4:3: "the first request on which a gateway names a machine
    registers it under that gateway", and "a registration of a machine that is not
    yet a device makes it a browser device with no role".

    ADR-0296 §2:6, the owner's ruling: "a newly admitted browser can do nothing until
    it is given roles".
    """
    verdict = registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)

    assert verdict.accepted
    assert verdict.registered
    assert registry.kind_of(_PHONE) is DeviceKind.BROWSER
    assert registry.roles_of(_PHONE) == frozenset()
    assert registry.is_known(_PHONE)


def test_a_later_naming_finds_the_registration_and_records_nothing_more(
    registry: DeviceRegistry,
) -> None:
    """One registration per machine and gateway, however many requests name it."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)

    again = registry.accept_naming(_GATEWAY, _PHONE, now=_LATER)

    assert again.accepted
    assert not again.registered
    rows, total = registry.registrations()
    assert total == 1
    assert rows[0].registered_at == _MOMENT


def test_a_registration_is_recorded_with_its_gateway_and_when_and_is_logged(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:6: "the hub records each registration with its gateway and when it
    was made, logs it, and ``ai-assistant-device`` lists the registrations, so the
    owner can see every machine each gateway has named"."""
    with structlog.testing.capture_logs() as captured:
        registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)

    ((registration,), _) = registry.registrations()
    assert registration.device_id == _PHONE
    assert registration.gateway == _GATEWAY
    assert registration.registered_at == _MOMENT
    assert registration.is_live
    (logged,) = [entry for entry in captured if entry["event"] == "device_registered"]
    assert logged["device"] == _PHONE
    assert logged["gateway"] == _GATEWAY


def test_a_gateway_on_the_local_socket_registers_under_hub(registry: DeviceRegistry) -> None:
    """ADR-0298 §4:4: the gateway of a registration is "``hub`` for a gateway on the
    local socket" — the hub's own machine may *be* a gateway, it may only never be
    *named* by one."""
    assert registry.accept_naming(HUB_DEVICE, _PHONE, now=_MOMENT).registered
    ((registration,), _) = registry.registrations()
    assert registration.gateway == HUB_DEVICE


def test_a_machine_already_a_device_keeps_its_kind_and_roles_when_named(
    registry: DeviceRegistry,
) -> None:
    """ADR-0296 §1:4, the owner's ruling: "a listing leaves the roles of a machine that
    is already a device as they are" — a laptop enrolled as a hub device and listed at
    another machine's gateway "is that one device, with the roles the user gave the
    laptop"."""
    registry.enrol(_WATCH, now=_MOMENT)
    registry.assign(_WATCH, Role.COMMANDS)

    verdict = registry.accept_naming(_GATEWAY, _WATCH, now=_LATER)

    assert verdict.registered
    assert registry.kind_of(_WATCH) is DeviceKind.HUB
    assert registry.roles_of(_WATCH) == frozenset({Role.COMMANDS})


def test_a_browser_device_later_enrolled_is_one_hub_device(registry: DeviceRegistry) -> None:
    """A machine is one device however it is admitted (ADR-0296 §1:4): enrolling a
    registered browser device makes it a hub device, keeping its roles."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)

    registry.enrol(_PHONE, now=_LATER)

    assert registry.kind_of(_PHONE) is DeviceKind.HUB
    assert registry.roles_of(_PHONE) == frozenset({Role.COMMANDS})
    (device,) = [one for one in registry.roster()[0] if one.device_id == _PHONE]
    assert device.kind is DeviceKind.HUB


# --- what no gateway may name ------------------------------------------------------


@pytest.mark.parametrize("name", [HUB_DEVICE, _HUB])
def test_no_gateway_may_name_the_hubs_own_machine(registry: DeviceRegistry, name: str) -> None:
    """ADR-0298 §3:3: "No gateway may name ``hub``, nor the hub's own overlay identity
    where the hub has one: such a name is refused", and §3:4: ``hub`` "is never
    enrolled, registered or revoked". A refusal registers nothing."""
    verdict = registry.accept_naming(_GATEWAY, name, now=_MOMENT)

    assert verdict.refusal is NamingRefusal.RESERVED
    assert not verdict.registered
    assert registry.registrations() == ([], 0)
    assert registry.kind_of(name) is None


def test_a_hub_with_no_overlay_identity_still_refuses_hub(store: EnrolmentStore) -> None:
    """``hub`` is the hub's machine "in every configuration" (§3:1)."""
    registry = DeviceRegistry(store, hub_identity=None)
    assert registry.accept_naming(_GATEWAY, HUB_DEVICE, now=_MOMENT).refusal is (
        NamingRefusal.RESERVED
    )
    assert registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT).accepted


def test_the_hub_holds_every_role_by_rule_and_is_always_known(registry: DeviceRegistry) -> None:
    """ADR-0298 §3:2 and §4:11: the hub's own machine holds every role, and "a device
    id may be added to 'my devices' … only if the hub knows it as a device: ``hub``,
    …" — by rule, with no row."""
    assert registry.roles_of(HUB_DEVICE) == EVERY_ROLE
    assert registry.is_known(HUB_DEVICE)
    assert registry.roster() == ([], 0)


@pytest.mark.parametrize("name", [HUB_DEVICE, _HUB])
def test_the_hubs_own_machine_is_never_enrolled(registry: DeviceRegistry, name: str) -> None:
    """ADR-0298 §3:4: "the hub refuses it, and its own overlay identity where it has
    one, as the identity of an enrolment" — before anything is minted."""
    with pytest.raises(RosterActError, match="hub's own machine"):
        registry.enrol(name, now=_MOMENT)
    assert registry.enrolments() == ([], 0)


@pytest.mark.parametrize(
    "act",
    [
        lambda registry: registry.revoke_device(HUB_DEVICE, now=_MOMENT),
        lambda registry: registry.revoke_registration(HUB_DEVICE, gateway=_GATEWAY, now=_MOMENT),
        lambda registry: registry.restore_registration(HUB_DEVICE, gateway=_GATEWAY, now=_MOMENT),
        lambda registry: registry.assign(HUB_DEVICE, Role.COMMANDS),
        lambda registry: registry.withdraw(HUB_DEVICE, Role.COMMANDS),
    ],
)
def test_no_roster_act_reaches_the_hubs_own_machine(
    registry: DeviceRegistry, act: Callable[[DeviceRegistry], object]
) -> None:
    """``hub`` is never registered or revoked, and its roles are not a row (§3:2,
    §3:4), so every act on it is refused in a sentence rather than performed."""
    with pytest.raises(RosterActError, match="hub's own machine"):
        act(registry)
    assert registry.roles_of(HUB_DEVICE) == EVERY_ROLE


def test_a_hub_with_no_remote_listener_enrols_nothing(store: EnrolmentStore) -> None:
    """ADR-0124 §6 discloses the hub's overlay identity beside every credential, and a
    hub with no remote listener asked no agent for one — nor has it a door for an
    enrolled device to arrive at. Refused before anything is minted or recorded."""
    registry = DeviceRegistry(store, hub_identity=None)

    with pytest.raises(RosterActError, match="ASSISTANT_HUB_REMOTE_ADDRESS"):
        registry.enrol(_GATEWAY, now=_MOMENT)

    assert registry.enrolments() == ([], 0)
    assert registry.roster() == ([], 0)


# --- revocation and restoring ------------------------------------------------------


def test_a_revoked_registration_stays_revoked_and_is_not_registered_again(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:9: "a gateway naming it again is refused (§6) and does not register
    it again, and only the owner's act at the hub restores it"."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    assert registry.revoke_registration(_PHONE, gateway=_GATEWAY, now=_LATER)

    again = registry.accept_naming(_GATEWAY, _PHONE, now=_LATER)

    assert again.refusal is NamingRefusal.REVOKED
    assert not again.registered
    assert registry.registrations()[1] == 1
    assert not registry.is_known(_PHONE)


def test_restoring_is_the_only_way_back_and_the_device_comes_back_with_no_role(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:9 and §4:11: restored by the owner's act, and "a device re-admitted
    after revocation, by re-enrolment or by a restored registration, holds no role
    until the user gives it one". The revocation is kept, beside a new live row."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)
    registry.revoke_registration(_PHONE, gateway=_GATEWAY, now=_LATER)

    assert registry.restore_registration(_PHONE, gateway=_GATEWAY, now=_LATER)

    assert registry.accept_naming(_GATEWAY, _PHONE, now=_LATER).accepted
    assert registry.roles_of(_PHONE) == frozenset()
    rows, total = registry.registrations()
    assert total == 2
    assert [row.is_live for row in rows] == [True, False]


def test_restoring_a_live_registration_changes_nothing(registry: DeviceRegistry) -> None:
    """Reported rather than refused: the owner asked for a state that already holds."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    assert not registry.restore_registration(_PHONE, gateway=_GATEWAY, now=_LATER)
    assert registry.registrations()[1] == 1


def test_restoring_registers_nothing_a_gateway_never_named(registry: DeviceRegistry) -> None:
    """A machine is registered by its gateway naming it (§4:2); restoring is not a
    second way in."""
    with pytest.raises(RosterActError, match="no revoked registration"):
        registry.restore_registration(_PHONE, gateway=_GATEWAY, now=_MOMENT)
    assert registry.registrations() == ([], 0)


def test_a_revoked_registration_under_one_gateway_leaves_another_live(
    registry: DeviceRegistry,
) -> None:
    """The refusal is "a registration the owner revoked *under it*" (ADR-0298's header
    record on ADR-0296 §1:5): one registration, not the machine."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.accept_naming(_OTHER_GATEWAY, _PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)

    registry.revoke_registration(_PHONE, gateway=_GATEWAY, now=_LATER)

    assert registry.accept_naming(_GATEWAY, _PHONE, now=_LATER).refusal is NamingRefusal.REVOKED
    assert registry.accept_naming(_OTHER_GATEWAY, _PHONE, now=_LATER).accepted
    # Still admitted under the other gateway, so it keeps its roles.
    assert registry.roles_of(_PHONE) == frozenset({Role.COMMANDS})


def test_revoking_a_device_revokes_everything_that_admits_it_and_clears_its_roles(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:10: "Revoking a device revokes its enrolment, if it has one, and
    every registration of it; clears its roles". The enrolment's connections are
    closed (ADR-0124 §8), and every gateway's naming of it is refused afterwards."""
    expelled: list[tuple[str, str]] = []
    registry.when_expelled(lambda identity, reason: expelled.append((identity, reason)))
    registry.enrol(_PHONE, now=_MOMENT)
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.accept_naming(_OTHER_GATEWAY, _PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)
    registry.assign(_PHONE, Role.SPOKES)

    revocation = registry.revoke_device(_PHONE, now=_LATER)

    assert revocation.enrolment
    assert revocation.registrations == 2
    assert revocation.roles == EVERY_ROLE
    assert expelled == [(_PHONE, "revoked")]
    assert registry.roles_of(_PHONE) == frozenset()
    assert not registry.is_known(_PHONE)
    for gateway in (_GATEWAY, _OTHER_GATEWAY):
        assert registry.accept_naming(gateway, _PHONE, now=_LATER).refusal is (
            NamingRefusal.REVOKED
        )


def test_a_device_re_enrolled_after_revocation_holds_no_role(registry: DeviceRegistry) -> None:
    """ADR-0298 §4:11, the re-enrolment half."""
    registry.enrol(_PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)
    registry.revoke_device(_PHONE, now=_LATER)

    registry.enrol(_PHONE, now=_LATER)

    assert registry.roles_of(_PHONE) == frozenset()


def test_rotating_an_enrolment_keeps_the_devices_roles(registry: DeviceRegistry) -> None:
    """A rotation is one act that leaves the device admitted throughout (ADR-0124 §6's
    "no intermediate state … has … none"), so nothing re-admits it and its roles
    stand."""
    registry.enrol(_PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)

    assert registry.enrol(_PHONE, now=_LATER).rotated

    assert registry.roles_of(_PHONE) == frozenset({Role.COMMANDS})


def test_revoking_the_last_admission_clears_roles_and_revoking_one_of_two_does_not(
    registry: DeviceRegistry, store: EnrolmentStore
) -> None:
    """The roster's invariant: a device holds a role only while something admits it.

    Asserted on the record as well as the view, because the record is what a restart
    reads and the two must not disagree."""
    registry.enrol(_PHONE, now=_MOMENT)
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.assign(_PHONE, Role.COMMANDS)

    registry.revoke(_PHONE, now=_LATER)  # the enrolment alone; the registration admits it
    assert registry.roles_of(_PHONE) == frozenset({Role.COMMANDS})
    assert store.device_roles() == {_PHONE: frozenset({Role.COMMANDS})}

    registry.revoke_registration(_PHONE, gateway=_GATEWAY, now=_LATER)
    assert registry.roles_of(_PHONE) == frozenset()
    assert store.device_roles() == {}


def test_revoking_a_gateways_device_leaves_the_registrations_under_it(
    registry: DeviceRegistry,
) -> None:
    """ADR-0298 §4:13: "Revoking a gateway's device does not revoke the registrations
    of other devices under it; no connection can use them while the gateway is
    revoked." """
    registry.enrol(_GATEWAY, now=_MOMENT)
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)

    registry.revoke_device(_GATEWAY, now=_LATER)

    assert registry.is_known(_PHONE)
    assert registry.accept_naming(_GATEWAY, _PHONE, now=_LATER).accepted


# --- the bound -----------------------------------------------------------------------


def test_the_bound_is_a_named_figure() -> None:
    """ADR-0298 §4:7: "a figure the implementing change names"."""
    assert MAX_REGISTRATIONS_PER_GATEWAY == 32


def test_a_naming_beyond_the_bound_is_refused_and_registers_nothing(
    store: EnrolmentStore,
) -> None:
    """ADR-0298 §4:7: "The hub bounds the live registrations under one gateway … and
    refuses a naming beyond it". A machine already registered is still accepted, the
    bound is per gateway, and a revoked registration frees its place."""
    registry = DeviceRegistry(store, hub_identity=_HUB, max_registrations_per_gateway=2)
    registry.accept_naming(_GATEWAY, "nONE", now=_MOMENT)
    registry.accept_naming(_GATEWAY, "nTWO", now=_MOMENT)

    beyond = registry.accept_naming(_GATEWAY, "nTHREE", now=_MOMENT)

    assert beyond.refusal is NamingRefusal.BOUND
    assert not registry.is_known("nTHREE")
    assert registry.kind_of("nTHREE") is None
    assert registry.accept_naming(_GATEWAY, "nONE", now=_MOMENT).accepted
    assert registry.accept_naming(_OTHER_GATEWAY, "nTHREE", now=_MOMENT).registered
    registry.revoke_registration("nONE", gateway=_GATEWAY, now=_LATER)
    assert registry.accept_naming(_GATEWAY, "nFOUR", now=_LATER).registered


def test_a_restore_is_held_to_the_bound_too(store: EnrolmentStore) -> None:
    """ADR-0298 §4:7 bounds the *live* registrations under one gateway, so the owner's
    restore cannot take a gateway past it either: refused in a sentence, with nothing
    changed."""
    registry = DeviceRegistry(store, hub_identity=_HUB, max_registrations_per_gateway=1)
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    registry.revoke_registration(_PHONE, gateway=_GATEWAY, now=_MOMENT)
    registry.accept_naming(_GATEWAY, _WATCH, now=_MOMENT)

    with pytest.raises(RosterActError, match="live registrations"):
        registry.restore_registration(_PHONE, gateway=_GATEWAY, now=_LATER)

    assert registry.accept_naming(_GATEWAY, _PHONE, now=_LATER).refusal is NamingRefusal.REVOKED
    assert [row.is_live for row in registry.registrations()[0]] == [True, False]


def test_the_bound_counts_what_the_record_already_holds(tmp_path: Path) -> None:
    """The count is rebuilt from the record at start, so a restart is not a way past
    the bound."""
    first = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    DeviceRegistry(first, hub_identity=_HUB, max_registrations_per_gateway=1).accept_naming(
        _GATEWAY, _PHONE, now=_MOMENT
    )
    first.close()

    second = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        reopened = DeviceRegistry(second, hub_identity=_HUB, max_registrations_per_gateway=1)
        assert reopened.accept_naming(_GATEWAY, _WATCH, now=_LATER).refusal is (NamingRefusal.BOUND)
    finally:
        second.close()


# --- roles -------------------------------------------------------------------------


def test_roles_are_given_and_taken_one_at_a_time(registry: DeviceRegistry) -> None:
    """ADR-0298 §4:12: roles are assigned "only by ``ai-assistant-device`` on the hub's
    own machine"; each act reports whether it changed anything."""
    registry.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)

    assert registry.assign(_PHONE, Role.COMMANDS)
    assert not registry.assign(_PHONE, Role.COMMANDS)
    assert registry.assign(_PHONE, Role.SPOKES)
    assert registry.roles_of(_PHONE) == EVERY_ROLE
    assert registry.withdraw(_PHONE, Role.SPOKES)
    assert not registry.withdraw(_PHONE, Role.SPOKES)
    assert registry.roles_of(_PHONE) == frozenset({Role.COMMANDS})


def test_a_machine_nothing_admits_is_given_no_role(registry: DeviceRegistry) -> None:
    """A role is never inferred (ADR-0296 §2:5), and neither is a device: a machine
    never enrolled nor named is no device yet, so it cannot be pre-authorised."""
    with pytest.raises(RosterActError, match="not a device this hub admits"):
        registry.assign(_PHONE, Role.COMMANDS)
    assert registry.roles_of(_PHONE) == frozenset()
    assert registry.roster() == ([], 0)


# --- the record ----------------------------------------------------------------------


def test_the_roster_survives_a_restart(tmp_path: Path) -> None:
    """The roster is durable state the hub owns, read back whole into the live view."""
    first = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    live = DeviceRegistry(first, hub_identity=_HUB)
    live.accept_naming(_GATEWAY, _PHONE, now=_MOMENT)
    live.accept_naming(_GATEWAY, _WATCH, now=_MOMENT)
    live.assign(_PHONE, Role.COMMANDS)
    live.revoke_registration(_WATCH, gateway=_GATEWAY, now=_LATER)
    first.close()

    second = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        reopened = DeviceRegistry(second, hub_identity=_HUB)
        assert reopened.roles_of(_PHONE) == frozenset({Role.COMMANDS})
        assert reopened.kind_of(_PHONE) is DeviceKind.BROWSER
        assert reopened.accept_naming(_GATEWAY, _PHONE, now=_LATER).accepted
        assert reopened.accept_naming(_GATEWAY, _WATCH, now=_LATER).refusal is (
            NamingRefusal.REVOKED
        )
    finally:
        second.close()


def test_a_record_written_before_the_roster_gains_its_devices_with_no_role(
    tmp_path: Path,
) -> None:
    """The migration: every machine an older record enrolled is a hub device, holding
    no role — ADR-0298 §9:4, "at the cutover every enrolled device … holds no role,
    because a role is never inferred from what a device could reach before"."""
    path = tmp_path / ENROLMENTS_FILENAME
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as older:
        older.executescript(
            """
            CREATE TABLE enrolments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, overlay_identity TEXT NOT NULL,
                verifier TEXT NOT NULL, enrolled_at TEXT NOT NULL, revoked_at TEXT
            );
            """
        )
        older.executemany(
            "INSERT INTO enrolments (overlay_identity, verifier, enrolled_at, revoked_at) "
            "VALUES (?, 'v', ?, ?)",
            [
                (_GATEWAY, _MOMENT.isoformat(), None),
                (_PHONE, _MOMENT.isoformat(), _LATER.isoformat()),
            ],
        )

    store = EnrolmentStore(path)
    try:
        registry = DeviceRegistry(store, hub_identity=_HUB)
        devices, total = registry.roster()
        assert total == 2
        assert {one.device_id: one.kind for one in devices} == {
            _GATEWAY: DeviceKind.HUB,
            _PHONE: DeviceKind.HUB,
        }
        assert all(one.roles == frozenset() for one in devices)
        assert registry.is_known(_GATEWAY)
        assert not registry.is_known(_PHONE)
        assert registry.enrolments()[1] == 2
    finally:
        store.close()


def test_opening_the_record_twice_migrates_nothing_twice(tmp_path: Path) -> None:
    """The migration runs on every open, so it has to be idempotent."""
    first = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    DeviceRegistry(first, hub_identity=_HUB).enrol(_PHONE, now=_MOMENT)
    first.close()
    second = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    third = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        assert second.recent_devices(limit=10)[1] == 1
    finally:
        second.close()
        third.close()


def test_the_database_itself_refuses_two_live_registrations_of_one_pair(
    store: EnrolmentStore,
) -> None:
    """The uniqueness rule is in the schema, as the enrolments' is: a second live row
    for one machine under one gateway would make "its registration" name two."""
    store.register(_PHONE, gateway=_GATEWAY, now=_MOMENT)
    with pytest.raises(sqlite3.IntegrityError):
        store.register(_PHONE, gateway=_GATEWAY, now=_LATER)


def test_the_schema_holds_exactly_the_values_the_enums_name(store: EnrolmentStore) -> None:
    """The record's CHECK constraints and the enums are two statements of one set;
    a value one names and the other refuses fails here rather than at a write."""
    store.register(_PHONE, gateway=_GATEWAY, now=_MOMENT)
    for role in Role:
        store.assign_role(_PHONE, role)
    assert store.device_roles() == {_PHONE: EVERY_ROLE}
    store.enrol(_WATCH, verifier="v", now=_MOMENT)
    assert set(store.device_kinds().values()) == set(DeviceKind)
    with (
        contextlib.closing(sqlite3.connect(store.path)) as other,
        pytest.raises(sqlite3.IntegrityError),
    ):
        other.execute("INSERT INTO device_roles (device_id, role) VALUES (?, 'host')", (_PHONE,))
