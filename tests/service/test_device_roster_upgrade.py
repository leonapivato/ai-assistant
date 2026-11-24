"""ADR-0326 §4:2's test, for ADR-0378 §8:2: the device roster before the gateway mark.

``tests/service/legacy/devices-before-adr-0378.db`` was written by the previous release's
own ``EnrolmentStore`` (the build at ``42e073874``), through its public ``enrol``,
``revoke``, ``register``, ``revoke_registration`` and ``assign_role`` alone, never by
hand-built SQL. It holds:

- ``nLAPTOP1CNTRL``, an enrolled hub device with the command role, a gateway under which
  three browser devices were registered: ``nPHONE22CNTRL`` (the command role),
  ``nTABLET3CNTRL`` (no role) and ``nOLDBRW4CNTRL`` (its registration revoked);
- ``nKITCHN5CNTRL``, a browser device the hub's own machine registered, with the command
  role;
- ``nDESKPC6CNTRL``, registered under ``hub`` as a browser device, then enrolled, with
  the spokes role;
- ``nWATCH7CNTRL``, enrolled and revoked; ``nSPARE8CNTRL``, enrolled and rotated.

The roster from before the mark had no gateway mark, so the upgrade is the empty one
ADR-0326 §4's note names: the mark's table is created empty on the first open, and
"a roster from before marks no device" (ADR-0378 §8:2). The head opens a copy, reads
every record back as the previous release wrote it, and then refuses every naming from
the laptop until the owner marks it, accepts the hub's own, and refuses a naming of
the enrolled desk machine (§2:1, §3:1, §3:3).
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
import structlog

from ai_assistant.core.types import HUB_DEVICE_ID, DeviceRole
from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    DeviceKind,
    DeviceRegistry,
    EnrolmentStore,
    NamingRefusal,
)

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "devices-before-adr-0378.db"

#: When the previous release wrote its first row, and the instants after it, by hour.
_T0: Final = datetime(2026, 11, 20, 9, tzinfo=UTC)
_NOW: Final = _T0 + timedelta(days=4)
_HUB: Final = "nHUBAAAACNTRL"

_LAPTOP: Final = "nLAPTOP1CNTRL"
_PHONE: Final = "nPHONE22CNTRL"
_TABLET: Final = "nTABLET3CNTRL"
_OLD: Final = "nOLDBRW4CNTRL"
_KITCHEN: Final = "nKITCHN5CNTRL"
_DESK: Final = "nDESKPC6CNTRL"
_WATCH: Final = "nWATCH7CNTRL"
_SPARE: Final = "nSPARE8CNTRL"


def _at(hours: int) -> datetime:
    return _T0 + timedelta(hours=hours)


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / ENROLMENTS_FILENAME
    shutil.copyfile(_FIXTURE, target)
    return target


def _tables(path: Path, *, kept: bool = False) -> set[str]:
    """The tables a file holds; ``kept`` for the fixture itself, read immutable so the
    read leaves no WAL sidecar beside it."""
    uri = f"file:{path}?mode=ro&immutable=1" if kept else f"file:{path}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_the_fixture_is_the_previous_releases_file() -> None:
    """No mark table: the file is from before ADR-0378."""
    assert "gateway_marks" not in _tables(_FIXTURE, kept=True)
    assert {"enrolments", "devices", "device_roles", "registrations"} <= _tables(
        _FIXTURE, kept=True
    )


def test_every_record_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2: the head "upgrades it, and reads back every record it holds"."""
    store = EnrolmentStore(legacy)
    try:
        enrolments, total = store.recent_enrolments(limit=50)
        assert total == 5
        assert [(one.overlay_identity, one.enrolled_at, one.revoked_at) for one in enrolments] == [
            (_SPARE, _at(11), None),
            (_SPARE, _at(10), _at(11)),
            (_WATCH, _at(8), _at(9)),
            (_DESK, _at(7), None),
            (_LAPTOP, _T0, None),
        ]
        assert store.device_kinds() == {
            _LAPTOP: DeviceKind.HUB,
            _PHONE: DeviceKind.BROWSER,
            _TABLET: DeviceKind.BROWSER,
            _OLD: DeviceKind.BROWSER,
            _KITCHEN: DeviceKind.BROWSER,
            _DESK: DeviceKind.HUB,
            _WATCH: DeviceKind.HUB,
            _SPARE: DeviceKind.HUB,
        }
        assert store.device_roles() == {
            _LAPTOP: frozenset({DeviceRole.COMMANDS}),
            _PHONE: frozenset({DeviceRole.COMMANDS}),
            _KITCHEN: frozenset({DeviceRole.COMMANDS}),
            _DESK: frozenset({DeviceRole.SPOKES}),
        }
        registrations, held = store.recent_registrations(limit=50)
        assert held == 5
        assert [
            (one.device_id, one.gateway, one.registered_at, one.revoked_at)
            for one in reversed(registrations)
        ] == [
            (_PHONE, _LAPTOP, _at(1), None),
            (_TABLET, _LAPTOP, _at(2), None),
            (_OLD, _LAPTOP, _at(3), _at(4)),
            (_KITCHEN, HUB_DEVICE_ID, _at(5), None),
            (_DESK, HUB_DEVICE_ID, _at(6), None),
        ]
        assert set(store.live_verifiers()) == {_LAPTOP, _DESK, _SPARE}
    finally:
        store.close()


def test_a_roster_from_before_marks_no_device(legacy: Path) -> None:
    """ADR-0378 §8:2: "a roster from before marks no device" — so after the upgrade the
    laptop's gateway names no one until the owner marks it at the hub (§2:1, §2:2), and
    nothing it named before is revoked (§2:4)."""
    store = EnrolmentStore(legacy)
    try:
        assert "gateway_marks" in _tables(legacy)
        assert store.live_marks() == {}
        registry = DeviceRegistry(store, hub_identity=_HUB)
        assert registry.gateways() == []
        assert not registry.is_gateway(_LAPTOP)

        refused = registry.accept_naming(_LAPTOP, _PHONE, now=_NOW)
        assert refused.refusal is NamingRefusal.NOT_GATEWAY
        assert registry.registrations()[1] == 5
        assert registry.accept_naming(HUB_DEVICE_ID, _KITCHEN, now=_NOW).accepted

        assert registry.mark_gateway(_LAPTOP, now=_NOW)
        assert registry.accept_naming(_LAPTOP, _PHONE, now=_NOW).accepted
        assert registry.roles_of(_PHONE) == frozenset({DeviceRole.COMMANDS})
    finally:
        store.close()


def test_each_start_names_the_unmarked_gateway_holding_registrations(legacy: Path) -> None:
    """The upgrade marks nothing on the owner's behalf (ADR-0378 §2:2), so every start
    says which enrolled device holds live registrations and names none of them, and what
    to run — and stops saying so once the owner marks it."""
    store = EnrolmentStore(legacy)
    try:
        with structlog.testing.capture_logs() as captured:
            registry = DeviceRegistry(store, hub_identity=_HUB)
        told = [entry for entry in captured if entry["event"] == "device_gateway_unmarked"]
        assert [(one["device"], one["registrations"]) for one in told] == [(_LAPTOP, 2)]
        assert "ai-assistant-device mark-gateway" in told[0]["detail"]

        registry.mark_gateway(_LAPTOP, now=_NOW)
        with structlog.testing.capture_logs() as captured:
            DeviceRegistry(store, hub_identity=_HUB)
        assert "device_gateway_unmarked" not in [entry["event"] for entry in captured]
    finally:
        store.close()


def test_an_enrolled_machine_from_before_is_reached_by_no_naming(legacy: Path) -> None:
    """ADR-0378 §3:3: the desk machine, registered as a browser device and then enrolled,
    is reached by no naming — its registration under ``hub`` stays on the record — and a
    revoked hub device is refused as well (§3:1)."""
    store = EnrolmentStore(legacy)
    try:
        registry = DeviceRegistry(store, hub_identity=_HUB)
        for name in (_DESK, _WATCH):
            verdict = registry.accept_naming(HUB_DEVICE_ID, name, now=_NOW)
            assert verdict.refusal is NamingRefusal.HUB_DEVICE
        assert registry.registrations()[1] == 5
    finally:
        store.close()


def test_the_devices_the_upgrade_leaves_linked(legacy: Path) -> None:
    """ADR-0378 §5:3: at the upgrade a browser device's link stands where §5:2 holds — a
    live registration and a roster role — and every enrolled device stands on its
    enrolment. The tablet, registered with no role, is no longer linkable."""
    store = EnrolmentStore(legacy)
    try:
        registry = DeviceRegistry(store, hub_identity=_HUB)
        assert registry.linkable_devices() == frozenset({_LAPTOP, _DESK, _SPARE, _PHONE, _KITCHEN})
        assert registry.linkable_since(_DESK) == _at(7)
        assert registry.linkable_since(_SPARE) == _at(10)
        assert registry.linkable_since(_PHONE) == _at(1)
    finally:
        store.close()


def test_opening_the_upgraded_file_again_changes_nothing(legacy: Path) -> None:
    """The upgrade runs on every open, so it is idempotent."""
    EnrolmentStore(legacy).close()
    with contextlib.closing(sqlite3.connect(legacy)) as conn:
        before = conn.execute("SELECT count(*) FROM gateway_marks").fetchone()
    EnrolmentStore(legacy).close()
    with contextlib.closing(sqlite3.connect(legacy)) as conn:
        assert conn.execute("SELECT count(*) FROM gateway_marks").fetchone() == before == (0,)
