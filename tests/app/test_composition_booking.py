"""What configuring the simulated booking provider wires (ADR-0273 §1, §3, §10).

ADR-0273 §1 wires this provider *"from ``app/composition.py`` alone"*, and §10's arms 1
and 4 are about what a deployment **gets**: nothing by default, and exactly two
declarations — in the ``ToolRegistry`` **and** at the egress seam — where it configured
the provider whole. `tests/tools/` asserts those over the factories; this file asserts
them over the engine a composition root actually builds, which is the only place a
wiring mistake can live.

**Nothing here opens a socket, and the provider could not.** Every case builds the
engine over a hashing embedder and closes it; the provider takes no
``OutboundTransport`` parameter at all (§3), and the configured endpoint names an
``.invalid`` host (RFC 6761 §6.4).

**No deployment is configured by this lane.** §10: *"no lane of this decision configures
the provider in any deployment"* — that is the operator act §1 reserves. What these
cases configure is a ``Settings`` object in a temporary directory, which is the arms
being run rather than a deployment being enabled.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final, cast

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.tools.booking import (
    BOOKING_ACT,
    BOOKING_ACT_ID,
    BOOKING_AVAILABILITY,
    BOOKING_AVAILABILITY_ID,
    BoundConnection,
    SimulatedBookingAct,
    SqliteBookingStore,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.orchestration import Engine
    from ai_assistant.tools.egress_binder import EgressBindingSeam, RegistrationTable
    from ai_assistant.tools.registry import InMemoryToolRegistry


def _wired_registry(engine: Engine) -> InMemoryToolRegistry:
    """The registry this root wired, as the concrete object it built.

    The runner holds it behind ``ToolRegistry``, which is the narrowing ADR-0029 §8
    wants in production; a case about **what was wired** has to look at the object.
    """
    return cast("InMemoryToolRegistry", engine._runner._registry)


def _wired_table(engine: Engine) -> RegistrationTable:
    """The registration table this root wired, likewise.

    The runner holds the seam behind the ``EgressBinder`` Protocol, which carries
    ``bind`` and ``rebind`` and nothing else; the table is the concrete seam's.
    """
    binder = engine._runner._binder
    assert binder is not None, "the composition root wires a binding seam"
    seam = cast("EgressBindingSeam", binder)
    return cast("RegistrationTable", seam._registrations)


pytestmark = pytest.mark.anyio

#: The connection a configured deployment names, and the endpoint nothing is transmitted
#: to. ``.invalid`` (RFC 6761 §6.4), so a case that somehow did reach a resolver would
#: fail rather than connect.
CONNECTION: Final = "conn-booking-0001"
ENDPOINT: Final = "https://bookings.example.invalid"

#: The configured window, price, charge and bound. The charge deliberately **disagrees**
#: with the price in amount, so that a case asserting the wiring is asserting that the
#: root forwarded two independent figures rather than one value twice (ADR-0273 §5).
FROM: Final = date(2026, 10, 1)
TO: Final = date(2026, 10, 7)
PRICE: Final = "120.00"
CHARGE: Final = "140.00"
CURRENCY: Final = "EUR"
RETAINED: Final = 3
UNCERTAIN: Final = date(2026, 10, 5)


def _settings(*, configured: bool, uncertain: bool = False) -> Settings:
    """Settings for a deployment that has, or has not, configured the provider.

    Args:
        configured: Whether to name the nine ``booking_*`` fields.
        uncertain: Whether to name the tenth as well. It is settable only beside the
            nine, which ``Settings`` refuses otherwise.

    Returns:
        The settings.
    """
    if not configured:
        return Settings(embedder=EmbedderKind.HASHING)
    return Settings(
        embedder=EmbedderKind.HASHING,
        booking_connection=CONNECTION,
        booking_endpoint=ENDPOINT,
        booking_available_from=FROM,
        booking_available_to=TO,
        booking_price_amount=Decimal(PRICE),
        booking_price_currency=CURRENCY,
        booking_billed_amount=Decimal(CHARGE),
        booking_billed_currency=CURRENCY,
        booking_retained_records=RETAINED,
        booking_indeterminate_date=UNCERTAIN if uncertain else None,
    )


async def test_a_default_deployment_wires_no_booking_provider(tmp_path: Path) -> None:
    """Arm 1, over the engine a composition root builds (ADR-0273 §1).

    *"A deployment supplying **none** of them builds **no provider object at all**,
    registers nothing in any registry and adds no entry to the seam's registration
    table."* Both halves here, and the store's file too: a default deployment leaves no
    ``bookings.db`` behind, because the branch never constructs one.
    """
    engine = build_engine(_settings(configured=False), data_dir=tmp_path)
    try:
        registry = _wired_registry(engine)
        table = _wired_table(engine)

        assert await registry.get(BOOKING_AVAILABILITY_ID) is None
        assert await registry.get(BOOKING_ACT_ID) is None
        assert BOOKING_ACT.capability not in await registry.capabilities()
        assert table.registration(BOOKING_ACT_ID) is None
        assert table.registration(BOOKING_AVAILABILITY_ID) is None
    finally:
        await engine.aclose()
    assert not (tmp_path / "bookings.db").exists()


async def test_a_configured_deployment_wires_both_declarations_in_both_places(
    tmp_path: Path,
) -> None:
    """Arm 4's wiring half (ADR-0273 §1).

    *"Both declarations go in the ``ToolRegistry`` as well as the seam's registration
    table, which is the email integration's shape and deliberately not the forecast
    read's."* The root derives the registry's half and the seam's half from **one**
    value, so they cannot disagree — asserted together for that reason.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        registry = _wired_registry(engine)
        table = _wired_table(engine)
        capabilities = await registry.capabilities()

        for tool_id, definition in (
            (BOOKING_AVAILABILITY_ID, BOOKING_AVAILABILITY),
            (BOOKING_ACT_ID, BOOKING_ACT),
        ):
            assert await registry.get(tool_id) == definition
            assert definition.capability in capabilities
            registration = table.registration(tool_id)
            assert registration is not None
            assert registration.reference == CONNECTION
            assert registration.transport_endpoint == ENDPOINT
    finally:
        await engine.aclose()


async def test_the_store_lives_in_the_data_directory_and_closes_with_the_engine(
    tmp_path: Path,
) -> None:
    """ADR-0273 §2's *"ordinary store of this deployment"*, and ADR-0042 §2's shutdown.

    It sits **in the data directory**, so ``ai-assistant-purge`` (ADR-0126, ADR-0153)
    destroys it with every other store; and its ``close`` is in the root's ordered
    shutdown path, so the engine's ``aclose`` releases it. The second half is asserted by
    reopening the same file afterwards — a connection the root had left open would make
    that the second handle on one store rather than the only one.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    await engine.aclose()

    assert (tmp_path / "bookings.db").exists()
    reopened = SqliteBookingStore(path=tmp_path / "bookings.db", retained=RETAINED)
    try:
        assert await reopened.records() == ()
        assert await reopened.commit_count() == 0
    finally:
        reopened.close()


async def test_the_root_forwards_the_configured_price_charge_and_bound(
    tmp_path: Path,
) -> None:
    """The root passes each configured value through unchanged (ADR-0273 §5).

    *"Passing a value is not interpreting it"*: the price and the charge reach the
    provider as two **independent** figures — this deployment's charge disagrees with
    its quote on purpose, which is ADR-0271 §3's case — and the record bound reaches the
    store. Asserted through the built objects rather than through the settings, because
    what could be wrong is the forwarding.
    """
    engine = build_engine(_settings(configured=True, uncertain=True), data_dir=tmp_path)
    try:
        registry = _wired_registry(engine)
        implementation = cast("SimulatedBookingAct", registry._live[BOOKING_ACT_ID].implementation)
        catalogue = implementation._catalogue

        assert str(catalogue.price_amount) == PRICE
        assert str(catalogue.charge_amount) == CHARGE
        assert catalogue.price_currency == CURRENCY
        assert catalogue.charge_currency == CURRENCY
        assert catalogue.available_from == FROM
        assert catalogue.available_to == TO
        assert catalogue.retained_records == RETAINED
        assert catalogue.indeterminate_date == UNCERTAIN
        assert implementation._store.retained == RETAINED
    finally:
        await engine.aclose()


async def test_no_transport_is_constructed_for_the_booking_provider(
    tmp_path: Path,
) -> None:
    """§3: the injection route does not reach this provider at all.

    The callable holds a connection check and a store, and **nothing** that could open a
    channel: no ``OutboundTransport``, no exchange, no endpoint parser. Asserted over
    the wired object's own attributes, so a lane that handed it one fails here as well as
    at ``lint-imports``.
    """
    engine = build_engine(_settings(configured=True), data_dir=tmp_path)
    try:
        registry = _wired_registry(engine)
        held = cast("SimulatedBookingAct", registry._live[BOOKING_ACT_ID].implementation)
        names = set(SimulatedBookingAct.__slots__)

        assert names == {"_catalogue", "_connection", "_store"}
        assert set(BoundConnection.__slots__) == {"_records", "_registration", "_secrets"}
        assert isinstance(held._connection, BoundConnection)
    finally:
        await engine.aclose()
