"""Arranging one authorised forecast read, and a far end that is not a network.

Shared by :mod:`test_forecast` and the composition case that asserts the forecast
declaration reaches no registry. What varies between those is what the provider answered
and what the connection store did under the credential read; none of it is a property of
the forecaster, so the arrangement lives here and the cases stay about ADR-0260's clauses.

**Nothing here opens a socket, and that is a property of the design rather than of the
arrangement.** :class:`~ai_assistant.tools.egress.HttpsExchange` takes the
outbound-transport capability as a **required** argument with no default (ADR-0191 §3),
so an arrangement that forgot to pass one would not construct rather than quietly
reaching the network. Every response and every refusal below is served over
:class:`~ai_assistant.testing.FakeByteChannel`, and hosts are ``.invalid`` (RFC 6761
§6.4) throughout, so a case that somehow did reach a resolver would fail rather than
connect.

**The account facts and the transport doubles are the search harness's**, imported
rather than restated, for exactly the reason that harness gives for importing the mail
one: a connection reference, an identity, a slot and a credential are what a provisioning
act writes for *any* integration, and a transport that stalls, raises or absorbs a
cancellation is a double for the **seam** rather than for either kind. Two spellings of
them would be two harnesses that could disagree about what ADR-0148 §6 and ADR-0060 §1
are over — and the seam under both is now literally one class
(:class:`~ai_assistant.tools.egress.HttpsEgressTransport`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, final

from egress_transport_harness import CREDENTIAL, REFERENCE, Records, entry, keyring
from web_search_harness import (
    AbsorbingTransport,
    GatedTransport,
    InterruptingTransport,
    RaisingTransport,
    ReprovisioningRecords,
    StallingTransport,
    SuspendableKeyring,
    elsewhere_account,
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
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools import build_forecast_integration, egress_registrations
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.forecast import FORECAST_READ

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from decimal import Decimal

    from egress_transport_harness import Keyring

    from ai_assistant.core.errors import TransportError
    from ai_assistant.core.protocols import OutboundTransport
    from ai_assistant.core.types import BoundEgressCall, FrozenJson, ToolDefinition
    from ai_assistant.tools.builtin import ForecastIntegration
    from ai_assistant.tools.egress import HttpsEgressTransport

__all__ = [
    "DATE_FIELD",
    "DECIDED_AT",
    "LATITUDE",
    "LONGITUDE",
    "MAX_DAYS",
    "MAX_DAY_CHARS",
    "MAX_RESPONSE_BYTES",
    "OMITTED",
    "ORIGIN",
    "REPORTED_AT",
    "AbsorbingTransport",
    "Built",
    "GatedTransport",
    "InterruptingTransport",
    "RaisingTransport",
    "ReprovisioningRecords",
    "StallingTransport",
    "SuspendableKeyring",
    "answering",
    "authorised_read",
    "body",
    "bound",
    "built",
    "day",
    "elsewhere_account",
    "far_end",
    "request",
    "response",
]

#: The configured provider's origin. ``.invalid`` (RFC 6761 §6.4), so a case that reached
#: a resolver would fail rather than connect.
ORIGIN: Final = "https://forecast.example.invalid"

#: The place this deployment is configured for (ADR-0260 §3, §11).
LATITUDE: Final = 41.1579
LONGITUDE: Final = -8.6291

#: The instant the provider's response declares, and the record every mint here is
#: attested to (ADR-0260 §5, ADR-0092 §3). Its IMF-fixdate spelling and its value, kept
#: beside each other so a case can assert on either.
DATE_FIELD: Final = "Fri, 04 Sep 2026 12:00:00 GMT"
REPORTED_AT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: When the one decision every call here carries was taken.
DECIDED_AT: Final = datetime(2026, 9, 4, 11, 30, tzinfo=UTC)

#: ADR-0260 §11's named defaults, which every subject here carries unless a case names
#: its own.
MAX_DAYS: Final = 3
MAX_DAY_CHARS: Final = 2048

#: A response bound generous enough that no case reaches it by accident. The bound's own
#: cases supply their own.
MAX_RESPONSE_BYTES: Final = 64 * 1024


@final
class _Omitted:
    """A field the provider did not send at all, as distinct from one it sent null.

    ADR-0260 §5's drop rule is total over four forms and each has to be expressible;
    ``None`` already means ``null``, so omission needs a value of its own.
    """

    __slots__ = ()


#: The one instance of it, passed to :func:`day` for a field to leave out.
OMITTED: Final = _Omitted()


def day(  # noqa: PLR0913 — one parameter per field the documented format names, so a case can make any one of them absent, null or ill-typed
    *,
    date: str | None | _Omitted | Any = "2026-09-05",
    utc_offset: str | None | _Omitted | Any = "+01:00",
    conditions: str | None | _Omitted | Any = "Clear",
    temperature_min: str | None | _Omitted | Any = "11.4",
    temperature_max: str | None | _Omitted | Any = "19.2",
    precipitation: str | None | _Omitted | Any = "0.0",
) -> dict[str, Any]:
    """One day row, in the shape the reference provider's documented format carries.

    **Every value is a JSON string in that format**, which ADR-0260 §5 forces: a content
    is "the octets of the value the response carried, and never a re-rendering of a
    parsed number", so a documented format carrying a number as a JSON number would
    oblige the reader to render a parsed float.

    Args:
        date: The day, as ``YYYY-MM-DD`` — a string, ``None`` for ``null``,
            :data:`OMITTED` for a field the provider did not send, or any other JSON
            value for §5's ill-typed case.
        utc_offset: The offset that day is in, as ``+HH:MM``, likewise.
        conditions: The conditions span, likewise.
        temperature_min: The low, likewise.
        temperature_max: The high, likewise.
        precipitation: The precipitation, likewise.

    Returns:
        The object, ready for :func:`body`.
    """
    fields = {
        "date": date,
        "utc_offset": utc_offset,
        "conditions": conditions,
        "temperature_min": temperature_min,
        "temperature_max": temperature_max,
        "precipitation": precipitation,
    }
    return {name: value for name, value in fields.items() if not isinstance(value, _Omitted)}


def body(*days: Mapping[str, Any], group: bool = True) -> bytes:
    """The documented response's body, carrying ``days``.

    Args:
        days: The day rows, in the order the provider returned them.
        group: Whether to carry the list at all. ``False`` is the response a provider
            with nothing to say for the coordinate sends, which ADR-0260 §5 reads as a
            response describing no day rather than as a shape refusal.

    Returns:
        The body's octets.
    """
    payload = {"days": list(days)} if group else {}
    return json.dumps(payload).encode("utf-8")


def response(
    *,
    status: str = "HTTP/1.1 200 OK",
    date: str | None = DATE_FIELD,
    headers: Sequence[str] = (),
    payload: bytes = b"",
) -> bytes:
    """One response's octets, framed by a content length.

    Args:
        status: The status line, without its terminator.
        date: The ``Date`` field's value, or ``None`` to send none — which is ADR-0260
            §5's "a response declaring no instant".
        headers: Any further field lines, without their terminators.
        payload: The body.

    Returns:
        The octets a far end would send.
    """
    fields = [*([] if date is None else [f"Date: {date}"]), *headers]
    fields.append(f"Content-Length: {len(payload)}")
    head = "\r\n".join([status, *fields]) + "\r\n\r\n"
    # ``latin-1`` and not ``ascii``: RFC 9110 §5.5 admits ``obs-text`` in a field value,
    # and :class:`HttpsResponse` carries one opaquely — which is what lets a case send a
    # ``Date`` carrying a non-ASCII digit.
    return head.encode("latin-1") + payload


def far_end(*octets: bytes) -> FakeByteChannel:
    """A secure channel with ``octets`` already sent by the far end.

    Args:
        octets: What the far end will answer, in order.

    Returns:
        The channel, ready to be served for an implicit-TLS endpoint.
    """
    return FakeByteChannel(secure=True).deliver(*octets)


def answering(*days: Mapping[str, Any], date: str | None = DATE_FIELD) -> FakeByteChannel:
    """A far end answering ``200`` with ``days``, in one call.

    Args:
        days: The day rows.
        date: The ``Date`` field's value, or ``None`` for a response declaring none.

    Returns:
        The channel.
    """
    return far_end(response(date=date, payload=body(*days)))


@dataclass(frozen=True, slots=True)
class Built:
    """One configured forecast integration and every double behind it.

    Attributes:
        integration: What the composition root's builder returned.
        transport: The outbound-transport capability, so a case can read the opens back
            — including the case whose whole assertion is that there were none.
        keyring: The recording ``Secrets`` face, likewise for credential reads.
        records: The connection store, whose answers a case scripts read by read.
    """

    integration: ForecastIntegration
    transport: (
        FakeOutboundTransport
        | GatedTransport
        | InterruptingTransport
        | StallingTransport
        | RaisingTransport
        | AbsorbingTransport
    )
    keyring: Keyring | SuspendableKeyring
    records: Records | ReprovisioningRecords

    @property
    def declaration(self) -> ToolDefinition:
        """The declaration this registration carries (ADR-0236 §1).

        :data:`~ai_assistant.tools.forecast.FORECAST_READ` where the builder was given no
        cost pair, and its ``PER_CALL`` twin where it was — read off the forecaster
        rather than rebuilt, so a case cannot assert against a declaration the seam was
        never registered with.

        Returns:
            The declaration.
        """
        declaration: ToolDefinition = self.integration.forecaster._declaration
        return declaration

    @property
    def forecaster(self) -> Any:
        """The ``Forecaster`` under test.

        Returns:
            The forecaster the builder constructed.
        """
        return self.integration.forecaster

    @property
    def seam(self) -> HttpsEgressTransport:
        """The egress transport the forecaster acts through.

        Returns:
            The transport, for a case that reads the registration off it.
        """
        return self.integration.forecaster._transport


async def built(  # noqa: PLR0913 — one knob per double a case arranges, and each is set on its own
    *,
    channels: Sequence[FakeByteChannel] = (),
    transport: GatedTransport
    | InterruptingTransport
    | StallingTransport
    | RaisingTransport
    | AbsorbingTransport
    | OutboundTransport
    | None = None,
    records: Records | ReprovisioningRecords | None = None,
    secrets: SuspendableKeyring | None = None,
    holds: str | None = CREDENTIAL,
    origin: str = ORIGIN,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    max_days: int = MAX_DAYS,
    max_day_chars: int = MAX_DAY_CHARS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    cost_per_call: Decimal | None = None,
    cost_currency: str | None = None,
    refusal: TransportError | None = None,
) -> Built:
    """One deployment that configured a forecast provider, wired to scripted doubles.

    Args:
        channels: The far ends to serve, in order. Ignored where ``transport`` is
            supplied.
        transport: A transport of the case's own, for the states the canonical fake has
            no arrangement for — one held open, one that stalls, one that raises and one
            that absorbs a cancellation.
        records: The connection store's scripted answers; defaults to one active record
            that never moves.
        secrets: A keyring of the case's own, for the arms that hold a credential read
            open. Defaults to the recording one the mail harness builds.
        holds: What the keyring holds under the record's slot, or ``None`` for a keyring
            with no entry — which is what an interrupted provisioning act leaves behind.
        origin: The origin the configured provider names.
        latitude: ``Settings.forecast_latitude``.
        longitude: ``Settings.forecast_longitude``.
        max_days: ``Settings.forecast_max_days``.
        max_day_chars: ``Settings.forecast_max_day_chars``.
        max_response_bytes: ``Settings.forecast_max_response_bytes``.
        cost_per_call: ``Settings.forecast_cost_per_call`` (ADR-0236 §1, ADR-0260 §11);
            supplied together with ``cost_currency`` or not at all.
        cost_currency: ``Settings.forecast_cost_currency``.
        refusal: Arms the canonical transport to refuse every open with this, after
            recording the attempt.

    Returns:
        The integration and every double behind it.
    """
    ring = await keyring(holds=holds) if secrets is None else secrets
    capability = transport
    if capability is None:
        served = FakeOutboundTransport().serve(*channels)
        if refusal is not None:
            served.refuse_with(refusal)
        capability = served
    store = Records(entry()) if records is None else records
    integration = build_forecast_integration(
        connection=REFERENCE,
        origin=origin,
        latitude=latitude,
        longitude=longitude,
        records=store,
        secrets=ring,
        transport=capability,
        max_days=max_days,
        max_day_chars=max_day_chars,
        max_response_bytes=max_response_bytes,
        cost_per_call=cost_per_call,
        cost_currency=cost_currency,
    )
    return Built(
        integration=integration,
        transport=capability,  # type: ignore[arg-type]  # the union above is the set of doubles this harness serves
        keyring=ring,
        records=store,
    )


@final
class _NoDefinitions:
    """A ``RegisteredDefinitions`` face holding nothing (ADR-0260 §1).

    The state a deployment with a forecast provider configured is actually in: the
    declaration is registered at the egress seam and in **no** ``ToolRegistry``, so the
    seam's registry-original comparison "is not reached, exactly as ADR-0152 §1 states".
    A harness that handed the seam a registry holding the declaration would be arranging
    a state the design forbids.
    """

    __slots__ = ()

    def original(self, tool_id: str, /) -> None:
        """No registry holds a definition for this id.

        Args:
            tool_id: The id being looked up.

        Returns:
            ``None``, always.
        """
        del tool_id


async def bound(  # noqa: PLR0913 — one knob per argument a case varies about the binding it derives, plus the carried fact ADR-0260 §11 puts on the carrier
    subject: Built,
    *,
    origin: str = ORIGIN,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    tool: Any = FORECAST_READ,
    forecast_reach: bool = True,
) -> BoundEgressCall:
    """The binding ``EgressBinder`` derives for one forecast read, over the real seam.

    Derived rather than hand-built, and that is what makes these cases about the
    forecaster: an ``EgressBinding``'s spans have to cover every argument the call carries
    (ADR-0150 §4), so a hand-built one is a second derivation that can be wrong in ways no
    production path can be. This is the sequence ADR-0260 §7 puts in front of the
    forecaster — ``orchestration`` builds the request, ``EgressBinder.bind`` derives the
    binding whole — with the ruling left to the caller.

    Args:
        subject: The configured integration, whose registration the seam reads.
        origin: The origin argument.
        latitude: The latitude argument.
        longitude: The longitude argument.
        tool: The declaration to bind against.
        forecast_reach: The fact ``orchestration`` writes onto the carrier (ADR-0260
            §11). ``True`` here, because that is what a deployment holding a forecast
            registration computes; a case about the restrictive default passes ``False``.

    Returns:
        The binding beside the detached arguments.

    Raises:
        AssertionError: If the seam answered "not an egress call", which would mean the
            declaration lost its destination keyword.
    """
    seam = EgressBindingSeam(
        definitions=_NoDefinitions(),
        registrations=egress_registrations(None, None, subject.integration),
        records=Records(entry()),
    )
    parameters: dict[str, FrozenJson] = {
        "origin": origin,
        "latitude": latitude,
        "longitude": longitude,
    }
    derived = await seam.bind(
        tool,
        parameters=parameters,
        provenance=CarriedProvenance(
            spans={},
            planned_with_external_content=False,
            coverage=SpanCoverage.NOT_COVERED,
            forecast_reach=forecast_reach,
        ),
    )
    assert derived is not None, "the forecast declaration carries a destination keyword"
    return derived


async def request(  # noqa: PLR0913 — one knob per thing a case varies about the request it is refusing
    subject: Built,
    *,
    origin: str = ORIGIN,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
    tool: Any = FORECAST_READ,
    elsewhere: Mapping[str, Any] | None = None,
    unbound: bool = False,
) -> ActionRequest:
    """The request a servicer builds for one forecast read (ADR-0260 §6, §7).

    Args:
        subject: The configured integration.
        origin: The origin argument.
        latitude: The latitude argument.
        longitude: The longitude argument.
        tool: The declaration carried by value.
        elsewhere: Fields to rewrite on the derived binding, for the cases about a call
            bound to another account or another endpoint. Applied to a binding the seam
            derived, so its spans stay the ones ADR-0150 §4 requires.
        unbound: Whether to carry no binding at all — ADR-0148 §8's third floor, restated
            at the one seam that could ignore it.

    Returns:
        The request.
    """
    derived = await bound(subject, origin=origin, latitude=latitude, longitude=longitude, tool=tool)
    carried = (
        derived.binding if elsewhere is None else derived.binding.model_copy(update=dict(elsewhere))
    )
    return ActionRequest(
        tool=tool,
        parameters=dict(derived.parameters),
        egress_binding=None if unbound else carried,
    )


def authorised_read(
    proposal: ActionRequest,
    *,
    decision_id: str = "d-forecast-1",
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
) -> ToolCall:
    """One authorised call for ``proposal``.

    **No trail is recorded and none is needed**, which is the one place this harness is
    simpler than the search's: ADR-0260 §6 enumerates what ``read`` performs and names no
    ledger, so nothing here requires the decision to be findable in a store before the
    send.

    Args:
        proposal: The request to authorise.
        decision_id: The decision's id.
        outcome: The ruling. Only an ``ALLOW`` constructs a ``ToolCall``.

    Returns:
        The call, which is unconstructable unless the decision authorises it.
    """
    decision = PermissionDecision.from_request(
        proposal,
        PermissionRuling(outcome=outcome, reason="the owner configured this provider"),
        id=decision_id,
        decided_at=DECIDED_AT,
    )
    return ToolCall(request=proposal, decision=decision)
