"""Arranging the simulated booking provider, its seam and its store (ADR-0273 §10).

Shared by :mod:`test_simulated_booking` and :mod:`test_booking_registration`, which ask
different questions of one integration: the first what it *does*, the second what a
deployment *gets*.

**Every arm is deterministic and offline**, which ADR-0260 §13 makes a standing
requirement rather than a new one — and here it is a property of the component rather
than of the arrangement. The provider takes **no** ``OutboundTransport`` parameter (§3),
so an arrangement that forgot to displace one would not construct; hosts are
``.invalid`` (RFC 6761 §6.4) throughout, so a case that somehow did reach a resolver
would fail rather than connect.

**The connection-store and keyring doubles are
:mod:`egress_transport_harness`'s**, not second ones. ADR-0148 §6's four conditions are
what this provider performs, the cases about them are about *two reads differing across
a credential read*, and that scripting is exactly what ``Records`` already does. A second
copy would be a second reading of one clause.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

from egress_transport_harness import (  # the store and keyring doubles, reused
    CREDENTIAL,
    IDENTITY,
    REFERENCE,
    SLOT,
    Keyring,
    Records,
    entry,
    keyring,
)

from ai_assistant.core.types import (
    ActionRequest,
    CarriedProvenance,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    SpanCoverage,
    ToolCall,
)
from ai_assistant.testing import FakeAuditTrail
from ai_assistant.tools.booking import (
    BOOKING_ACT,
    BOOKING_ACT_ID,
    BOOKING_AVAILABILITY,
    BOOKING_AVAILABILITY_ID,
    DATE_ARGUMENT,
    ORIGIN_ARGUMENT,
)
from ai_assistant.tools.builtin import (
    SimulatedBookingIntegration,
    build_default_registry,
    build_simulated_booking_integration,
    egress_registrations,
)
from ai_assistant.tools.egress_binder import EgressBindingSeam

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal
    from pathlib import Path

    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolDefinition, ToolResult
    from ai_assistant.tools.registry import InMemoryToolRegistry

__all__ = [
    "AVAILABLE_FROM",
    "AVAILABLE_TO",
    "BOOKING_ACT",
    "BOOKING_ACT_ID",
    "BOOKING_AVAILABILITY",
    "BOOKING_AVAILABILITY_ID",
    "CHARGE",
    "CREDENTIAL",
    "CURRENCY",
    "DECIDED_AT",
    "ENDPOINT",
    "IDENTITY",
    "IN_WINDOW",
    "PRICE",
    "REFERENCE",
    "RETAINED",
    "SLOT",
    "TIMEOUT",
    "UNAVAILABLE",
    "UNCERTAIN",
    "Keyring",
    "Records",
    "arguments",
    "authorised",
    "bound",
    "configured",
    "drive",
    "entry",
    "keyring",
    "provenance",
    "registry_for",
    "seam_for",
    "settings_kwargs",
]

#: The origin the registration configures. **Nothing is transmitted to it** (ADR-0273
#: §3); it is what the binding is pinned to and what the four conditions compare.
ENDPOINT: Final = "https://bookings.example.invalid"

#: The window the deployment configured, a day inside it, a day outside it, and the
#: day whose booking commits and then reports that it may have (§4).
AVAILABLE_FROM: Final = date(2026, 10, 1)
AVAILABLE_TO: Final = date(2026, 10, 7)
IN_WINDOW: Final = date(2026, 10, 2)
UNAVAILABLE: Final = date(2026, 11, 1)
UNCERTAIN: Final = date(2026, 10, 5)

#: The price quoted and the charge made. Equal by default, which is ADR-0273 §5's
#: *"a booking whose charge equals the quote it was pinned to"*; a case that wants the
#: disagreeing configuration passes its own.
PRICE: Final = "120.00"
CHARGE: Final = "120.00"
CURRENCY: Final = "EUR"

#: How many records the store retains by default. Small, so §10 arm 10's pruning is
#: reached in three bookings rather than in a thousand.
RETAINED: Final = 2

#: When the arranged decision was taken. Fixed, because nothing here reads a clock.
DECIDED_AT: Final = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

#: The deadline every arranged invocation is given. Generous, because no case here is
#: about the seam's own deadline (ADR-0029 §4) and a tight one would make an arm flaky
#: on a loaded machine rather than more exact.
TIMEOUT: Final = timedelta(seconds=30)


def settings_kwargs(**overrides: object) -> dict[str, object]:
    """The nine ``booking_*`` settings a whole configuration carries, plus the tenth.

    Args:
        **overrides: Fields to replace or, with ``None``, to leave unset — which is how
            a case arranges the half-configured refusal ADR-0273 §1 requires.

    Returns:
        The keyword arguments for ``Settings``.
    """
    whole: dict[str, object] = {
        "booking_connection": REFERENCE,
        "booking_endpoint": ENDPOINT,
        "booking_available_from": AVAILABLE_FROM,
        "booking_available_to": AVAILABLE_TO,
        "booking_price_amount": PRICE,
        "booking_price_currency": CURRENCY,
        "booking_billed_amount": CHARGE,
        "booking_billed_currency": CURRENCY,
        "booking_retained_records": RETAINED,
    }
    return whole | overrides


async def configured(  # noqa: PLR0913 — one keyword per configured fact a case varies
    *,
    store_path: Path | str = ":memory:",
    records: Records | None = None,
    available_from: date | str = AVAILABLE_FROM,
    available_to: date | str = AVAILABLE_TO,
    secrets: Keyring | None = None,
    price_amount: Decimal | int | str = PRICE,
    price_currency: str = CURRENCY,
    charge_amount: Decimal | int | str = CHARGE,
    charge_currency: str = CURRENCY,
    retained_records: int = RETAINED,
    indeterminate_date: date | str | None = None,
    connection: str = REFERENCE,
    endpoint: str = ENDPOINT,
) -> SimulatedBookingIntegration:
    """One deployment that configured the provider, through the production factory.

    Args:
        store_path: Where the durable state lives; ``":memory:"`` for a case that does
            not restart, a real path for one that does.
        records: The connection store's scripted answers; defaults to one active record
            that never moves.
        available_from: The first available day, as a ``date`` or its ISO spelling.
        available_to: The last.
        secrets: The keyring; defaults to one holding the credential under the slot.
        price_amount: The quoted price.
        price_currency: Its ISO-4217 code.
        charge_amount: The amount a booking charges.
        charge_currency: Its ISO-4217 code.
        retained_records: ADR-0273 §2's record bound.
        indeterminate_date: The day whose booking reports an uncertain effect.
        connection: The connection reference both tools register against.
        endpoint: The origin the binding is pinned to.

    Returns:
        The integration, exactly as ``app/composition.py`` builds one.
    """
    return build_simulated_booking_integration(
        connection=connection,
        endpoint=endpoint,
        records=Records(entry()) if records is None else records,
        secrets=await keyring() if secrets is None else secrets,
        store_path=store_path,
        available_from=available_from,
        available_to=available_to,
        price_amount=price_amount,
        price_currency=price_currency,
        charge_amount=charge_amount,
        charge_currency=charge_currency,
        retained_records=retained_records,
        indeterminate_date=indeterminate_date,
    )


def registry_for(booking: SimulatedBookingIntegration | None) -> InMemoryToolRegistry:
    """The registry a composition root would build for that configuration.

    Args:
        booking: The configured provider, or ``None``.

    Returns:
        The one object injected as both ``ToolRegistry`` and ``ToolInvoker``.
    """
    trail = FakeAuditTrail()
    return build_default_registry(booking=booking, ledger=trail, gate=trail)


def seam_for(
    booking: SimulatedBookingIntegration | None,
    registry: InMemoryToolRegistry,
    *,
    records: Records | None = None,
) -> EgressBindingSeam:
    """The binding seam over the same registry and the same registration table.

    Args:
        booking: The configured provider, or ``None``.
        registry: The registry, injected as its own ``RegisteredDefinitions`` face.
        records: The store the seam reads its one record from.

    Returns:
        The seam a composition root would build for that pair.
    """
    return EgressBindingSeam(
        definitions=registry,
        registrations=egress_registrations(None, None, None, booking),
        records=Records(entry()) if records is None else records,
    )


def arguments(day: date | str = IN_WINDOW, **extra: FrozenJson) -> dict[str, FrozenJson]:
    """One call's arguments, as ``invoke`` would hand them to a callable.

    Args:
        day: The day being asked about or booked.
        **extra: Further keys, for the cases about arguments the declaration's own
            schema does not name.

    Returns:
        The mapping.
    """
    built: dict[str, FrozenJson] = {
        ORIGIN_ARGUMENT: ENDPOINT,
        DATE_ARGUMENT: day if isinstance(day, str) else day.isoformat(),
    }
    return built | dict(extra)


def provenance() -> CarriedProvenance:
    """What a runner carries into the seam for one of these calls.

    Nothing here is covered content and nothing was planned over external material: the
    day is the user's own and the origin is the registration's. Every member is stated
    rather than defaulted, because :class:`CarriedProvenance` gives ``spans``,
    ``planned_with_external_content`` and ``coverage`` no defaults — a caller holding no
    provenance has to say so.

    Returns:
        The carrier.
    """
    return CarriedProvenance(
        spans={},
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


async def bound(
    seam: EgressBindingSeam,
    definition: ToolDefinition,
    parameters: Mapping[str, FrozenJson],
) -> EgressBinding:
    """The binding the **real** seam derives for this call (ADR-0273 §3).

    Derived rather than hand-built, because §3's requirement is that both declarations
    are *"bound at the designated egress seam"* — a binding assembled in a test would
    assert the provider against a shape nothing produced.

    Args:
        seam: The binding seam.
        definition: The declaration being bound.
        parameters: The call's arguments.

    Returns:
        The derived binding.

    Raises:
        AssertionError: If the seam answered that this is not an egress call, which
            would mean the registration and the schema had come apart.
    """
    call = await seam.bind(definition, parameters=parameters, provenance=provenance())
    assert call is not None, "the seam answered that this is not an egress call"
    assert call.binding is not None
    return call.binding


def authorised(  # noqa: PLR0913 — one keyword per fact a ruling fixes; a case varies one at a time
    definition: ToolDefinition,
    parameters: Mapping[str, FrozenJson],
    binding: EgressBinding | None,
    *,
    decision_id: str = "d-1",
    step_id: str = "step-1",
    decided_at: datetime | None = None,
) -> ToolCall:
    """One authorised call, as the runner would have built it.

    Args:
        definition: The declaration being invoked.
        parameters: The call's arguments.
        binding: The binding the seam derived.
        decision_id: The decision's id, which a case varies to make two dispatches.
        step_id: The step the request serves.
        decided_at: When the ruling was taken.

    Returns:
        The call, which is unconstructable unless the decision authorises it.
    """
    request = ActionRequest(
        tool=definition,
        parameters=parameters,
        step_id=step_id,
        egress_binding=binding,
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user confirmed the booking"),
        id=decision_id,
        decided_at=decided_at or DECIDED_AT,
    )
    return ToolCall(request=request, decision=decision)


async def recorded(registry: InMemoryToolRegistry, call: ToolCall) -> ToolResult:
    """Record the call's ruling in the registry's own trail, then invoke it.

    ADR-0192 §1 makes the claim the consume: the ledger requires the decision it is
    handed to **equal the decision the store holds under that id**, so a call whose
    ruling the trail never saw is refused before the callable is reached. That is the
    runner's job in production and the arrangement's here — the registry is handed the
    one object a composition root wires as ``AuditTrail``, ``InvocationLedger`` and
    ``InvocationCompleter``, so recording through ``registry.ledger`` is recording
    through exactly that object.

    Args:
        registry: The registry, which is also the invoker.
        call: The authorised call.

    Returns:
        The seam's own ``ToolResult``.
    """
    ledger = registry.ledger
    assert isinstance(ledger, FakeAuditTrail), "this harness claims through the trail it wired"
    await ledger.record(call.decision)
    return await registry.invoke(call, timeout=TIMEOUT)


async def drive(
    registry: InMemoryToolRegistry,
    seam: EgressBindingSeam,
    definition: ToolDefinition,
    parameters: Mapping[str, FrozenJson] | None = None,
    *,
    decision_id: str = "d-1",
) -> ToolResult:
    """Bind the call at the real seam and invoke it through the real registry.

    The whole production path, end to end: the seam derives the binding from the
    declaration's own schema and the registration's connection record, and the registry
    revalidates, checks and invokes. What a case asserts is therefore what a deployment
    would see.

    Args:
        registry: The registry, which is also the invoker.
        seam: The binding seam.
        definition: The declaration to invoke.
        parameters: The call's arguments; defaults to a day inside the window.
        decision_id: The decision's id.

    Returns:
        The seam's own ``ToolResult``.
    """
    call_parameters = arguments() if parameters is None else parameters
    binding = await bound(seam, definition, call_parameters)
    call = authorised(definition, call_parameters, binding, decision_id=decision_id)
    return await recorded(registry, call)
