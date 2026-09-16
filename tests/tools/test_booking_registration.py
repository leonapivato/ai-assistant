"""What a deployment gets, and what a default one does not (ADR-0273 §10 arms 1, 3, 4, 18).

Four of §10's arms, each over the **production** component: the registry and the seam's
table a composition root actually builds, and the declarations it actually registers.

- **arm 1** — a default ``Settings`` builds no provider and registers neither
  declaration, in the registry or at the seam;
- **arm 3** — enabled with no provisioned connection, it registers nothing and
  fabricates nothing;
- **arm 4** — each declaration's shape, **every field named**, and the registered set
  asserted to be **exactly those two**, compared as whole sets against a default
  ``Settings`` rather than searched for the two members expected; and
- **arm 18** — the transport-confinement contract covers the new module.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from booking_harness import (
    BOOKING_ACT,
    BOOKING_ACT_ID,
    BOOKING_AVAILABILITY,
    BOOKING_AVAILABILITY_ID,
    ENDPOINT,
    IN_WINDOW,
    REFERENCE,
    Records,
    arguments,
    configured,
    provenance,
    registry_for,
    seam_for,
)

from ai_assistant.core.errors import EgressBindingError
from ai_assistant.core.types import (
    ChargedOutput,
    CostBasis,
    DataTier,
    Idempotency,
    QuotedOutput,
    Reversibility,
    RiskLevel,
    ToolCost,
    VerificationKind,
)
from ai_assistant.tools.builtin import egress_registrations

if TYPE_CHECKING:
    from ai_assistant.tools.builtin import SimulatedBookingIntegration

#: This repository's root, for the contract arm.
_ROOT: Final = Path(__file__).resolve().parents[2]

#: The contract ADR-0273 §3 requires the new module to be named in.
_CONTRACT: Final = "network transports are confined to the tools egress seam"


def _registered_ids(booking: SimulatedBookingIntegration | None) -> set[str]:
    """Every tool id the seam's table holds, as a whole set.

    ``RegistrationTable`` exposes a **lookup** and no enumeration, because that is all
    the binding seam needs (ADR-0152 §10). Arm 4 needs the whole set, though — *"compared
    as whole sets … and not merely searched for the two members expected"* — because a
    third registration nothing looked up is exactly what it is written to catch. So the
    table's own mapping is read here, in the test and nowhere else.

    Args:
        booking: The configured provider, or ``None``.

    Returns:
        The ids the table holds.
    """
    table = egress_registrations(None, None, None, booking)
    return set(table._bound)


# --------------------------------------------------------------------------- #
# arm 1: absent by default
# --------------------------------------------------------------------------- #


async def test_a_default_deployment_registers_neither_declaration() -> None:
    """Arm 1 (ADR-0273 §1).

    *"A deployment supplying **none** of them builds **no provider object at all**,
    registers nothing in any registry and adds no entry to the seam's registration
    table."* Both halves in one case on purpose: separately they are two facts that
    happen to agree, and what §1's design buys is that they **cannot** disagree, because
    the registry's half and the seam's half come from one value.
    """
    registry = registry_for(None)

    assert await registry.get(BOOKING_AVAILABILITY_ID) is None
    assert await registry.get(BOOKING_ACT_ID) is None
    assert BOOKING_AVAILABILITY.capability not in await registry.capabilities()
    assert BOOKING_ACT.capability not in await registry.capabilities()
    assert _registered_ids(None) == set()


# --------------------------------------------------------------------------- #
# arm 4: the two declarations, every field, and exactly those two
# --------------------------------------------------------------------------- #


async def test_the_availability_reads_declaration_is_exactly_what_the_adr_fixes() -> None:
    """Arm 4, the read's half — every field ADR-0273 §2 names, over the *registered*
    definition rather than over the module constant.

    ``reads`` names ``SECRET`` because the callable reads the credential the bound
    connection names on every call — *"including for the reference provider, which
    accepts a credential and does not use it"* — and ``()`` there would be the silent
    no-reach claim ADR-0016 §1 makes the field required to prevent.
    """
    booking = await configured()
    registered = await registry_for(booking).get(BOOKING_AVAILABILITY_ID)

    assert registered is not None
    assert registered.side_effecting is False
    assert registered.idempotency is Idempotency.NATURAL
    assert registered.reversibility is Reversibility.REVERSIBLE
    assert registered.risk_level is RiskLevel.LOW
    assert registered.reads == (DataTier.SECRET, DataTier.OPERATIONAL)
    assert registered.writes == ()
    assert registered.discloses == ()
    assert registered.cost == ToolCost(basis=CostBasis.FREE)
    assert registered.quoted_output == QuotedOutput(
        amount="price_amount", currency="price_currency"
    )
    assert registered.charged_output is None
    assert registered.bounded_arguments == ()
    assert registered.postconditions == ()


async def test_the_booking_acts_declaration_is_exactly_what_the_adr_fixes() -> None:
    """Arm 4, the act's half — every field ADR-0273 §2 names, including its postcondition.

    ``IRREVERSIBLE`` and ``HIGH`` are **not lowered because the provider is simulated**
    (§2): a declaration tuned to make a walkthrough quieter would demonstrate a
    confirmation path no real booking takes. ``NONE`` is declared and no ``KEYED``
    window is, because ADR-0016 §4 admits ``KEYED`` only on a real deduplication
    guarantee and this provider offers none.
    """
    booking = await configured()
    registered = await registry_for(booking).get(BOOKING_ACT_ID)

    assert registered is not None
    assert registered.side_effecting is True
    assert registered.idempotency is Idempotency.NONE
    assert registered.idempotency_window is None
    assert registered.reversibility is Reversibility.IRREVERSIBLE
    assert registered.risk_level is RiskLevel.HIGH
    assert registered.reads == (DataTier.SECRET, DataTier.OPERATIONAL)
    assert registered.writes == (DataTier.PERSONAL, DataTier.OPERATIONAL)
    assert registered.discloses == ()
    assert registered.cost == ToolCost(basis=CostBasis.FREE)
    assert registered.quoted_output is None
    assert registered.charged_output == ChargedOutput(
        amount="charged_amount", currency="charged_currency"
    )
    assert registered.bounded_arguments == ()
    assert len(registered.postconditions) == 1
    assert registered.postconditions[0].kind is VerificationKind.FIELD_EQUALS
    assert registered.postconditions[0].field == "booked"
    assert registered.postconditions[0].equals is True


async def test_the_act_classifies_at_adr_0262_s_rung_two() -> None:
    """§7 requires the booking to classify at ADR-0262 §3's **rung 2**.

    That section's rung 2 is a step whose definition is ``side_effecting`` and whose
    ``reversibility`` is more severe than ``REVERSIBLE``, or whose ``discloses`` is
    non-empty, or whose decision carries an ``egress_binding``. This declaration
    satisfies the first limb outright and the third by being registered at the seam, and
    §7 **requires** that it does: *"a reference provider classifying at rung 1 would
    demonstrate the wrong rung of the ladder M33 exists to exercise"*.
    """
    booking = await configured()
    registered = await registry_for(booking).get(BOOKING_ACT_ID)

    assert registered is not None
    assert registered.side_effecting
    assert registered.reversibility is not Reversibility.REVERSIBLE
    assert egress_registrations(None, None, None, booking).registration(BOOKING_ACT_ID) is not None


async def test_exactly_two_declarations_are_registered_and_no_third() -> None:
    """Arm 4's set comparison, **as whole sets** (ADR-0273 §1, §10 arm 4).

    *"So that a third definition the enabled integration registers, a cancellation the
    likeliest, fails this arm instead of standing unremarked beside them."* The
    comparison is against a **default** ``Settings``' registry and table, so what is
    asserted is what the *integration* contributed rather than what the tree happens to
    hold.
    """
    booking = await configured()
    enabled = registry_for(booking)
    absent = registry_for(None)

    enabled_ids = {tool.id for tool in await enabled.all_tools()}
    absent_ids = {tool.id for tool in await absent.all_tools()}
    assert enabled_ids - absent_ids == {BOOKING_AVAILABILITY_ID, BOOKING_ACT_ID}

    enabled_table = _registered_ids(booking)
    absent_table = _registered_ids(None)
    assert enabled_table - absent_table == {BOOKING_AVAILABILITY_ID, BOOKING_ACT_ID}


async def test_both_declarations_are_in_the_registry_as_well_as_at_the_seam() -> None:
    """§1's *"both … in the ``ToolRegistry`` **as well as** the seam's table"*.

    The email integration's shape and **deliberately not the forecast read's**. ADR-0260
    §1 keeps that read out of every registry because *"a registry entry would put its
    capability in front of the planner"*; here the opposite is the requirement, because
    M33 **is** the planner proposing a booking, the user confirming it and the driver
    dispatching it — *"a capability no planner can name has no walkthrough at all"*.
    """
    booking = await configured()
    registry = registry_for(booking)
    table = egress_registrations(None, None, None, booking)

    capabilities = await registry.capabilities()
    for tool_id, definition in (
        (BOOKING_AVAILABILITY_ID, BOOKING_AVAILABILITY),
        (BOOKING_ACT_ID, BOOKING_ACT),
    ):
        assert await registry.get(tool_id) == definition
        assert definition.capability in capabilities
        registration = table.registration(tool_id)
        assert registration is not None
        assert registration.reference == REFERENCE
        assert registration.transport_endpoint == ENDPOINT


async def test_the_registration_the_table_holds_is_the_one_the_callable_holds() -> None:
    """One object, not two equal ones (ADR-0148 §6).

    The reference a record is read by and the endpoint a binding is compared against
    cannot come apart, because the callable's :class:`BoundConnection` and the seam's
    table were handed the **same** ``EgressRegistration``.
    """
    booking = await configured()
    table = egress_registrations(None, None, None, booking)

    assert table.registration(BOOKING_ACT_ID) is booking.booking.registration
    assert table.registration(BOOKING_AVAILABILITY_ID) is booking.availability.registration


# --------------------------------------------------------------------------- #
# arm 3: enabled, and nothing provisioned
# --------------------------------------------------------------------------- #


async def test_a_call_against_an_unprovisioned_connection_is_refused_and_nothing_is_made() -> None:
    """Arm 3 (ADR-0273 §1, ADR-0149 §4).

    *"No connection, credential, identity, reference or endpoint is fabricated,
    defaulted or inferred to make registration succeed."* Where the store holds no
    record for the configured reference, the seam refuses at bind time and **writes
    nothing**: the only thing that happened is a read.
    """
    empty = Records()  # a store with no record for the reference at all
    booking = await configured(records=empty)
    registry = registry_for(booking)
    seam = seam_for(booking, registry, records=empty)

    with pytest.raises(EgressBindingError, match="not connectable"):
        await seam.bind(BOOKING_ACT, parameters=arguments(IN_WINDOW), provenance=provenance())

    assert empty.reads == [REFERENCE]
    assert await booking.store.commit_count() == 0
    assert await booking.store.records() == ()


# --------------------------------------------------------------------------- #
# arm 18: the transport-confinement contract covers the module
# --------------------------------------------------------------------------- #


def test_the_transport_contract_names_the_booking_module() -> None:
    """Arm 18 (ADR-0273 §3).

    *"Its module is added to the transport-confinement contract's enumerated
    ``source_modules`` in ``pyproject.toml`` **in the same change** … so that a later
    edit giving it a transport **fails ``lint-imports``** rather than passing review."*

    ``tests/tools/test_egress_seam.py`` already holds the contract's enumeration equal
    to the modules on disk, so removing this entry fails there as well; this case names
    the obligation where the decision states it, so a reader of ADR-0273 finds its arm.
    """
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = pyproject["tool"]["importlinter"]["contracts"]
    confinement = next(one for one in contracts if one["name"] == _CONTRACT)

    assert "ai_assistant.tools.booking" in confinement["source_modules"]


def test_the_factory_takes_no_transport_parameter() -> None:
    """§3's *"it takes **no** ``OutboundTransport`` parameter"*.

    The injection route by which the real and the fake transport both reach production
    code does not reach this provider at all — asserted over the signature, so that a
    lane adding one fails this rather than merely contradicting a docstring.
    """
    import inspect  # noqa: PLC0415 — one case, one import

    from ai_assistant.tools.builtin import build_simulated_booking_integration  # noqa: PLC0415

    signature = inspect.signature(build_simulated_booking_integration)
    assert "transport" not in signature.parameters
    annotations = {str(one.annotation) for one in signature.parameters.values()}
    assert not any("Transport" in one for one in annotations)
