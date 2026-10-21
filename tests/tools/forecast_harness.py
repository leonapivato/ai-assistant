"""Arranging one authorised forecast read, and a far end that is not a network.

Shared by :mod:`test_forecast` and the composition case that asserts the forecast
declaration reaches no registry. What varies between those is what the provider answered
and what the connection store held at the one record read; none of it is a property of
the forecaster, so the arrangement lives here and the cases stay about ADR-0260's and
ADR-0344's clauses.

**The far end speaks Open-Meteo's documented format** (ADR-0344 §2:5): :func:`body`
writes a ``/v1/forecast`` response — the daily table, its units, the one offset and the
members that locate the place — as JSON text, so a number token reaches the forecaster
spelled exactly as a case wrote it. **Nothing here sends a request to Open-Meteo.**

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
one: a connection reference and an identity are what a provisioning act writes for *any*
integration, and a transport that stalls, raises or absorbs a cancellation is a double
for the **seam** rather than for either kind. Two spellings of them would be two
harnesses that could disagree about what ADR-0148 §6 and ADR-0060 §1 are over — and the
seam under both is now literally one class
(:class:`~ai_assistant.tools.egress.HttpsEgressTransport`). The record defaults to the
keyless one ADR-0325's act writes — ``ACTIVE``, naming no slot — because the forecast
is keyless (ADR-0344 §2:3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, final

from egress_transport_harness import REFERENCE, Records, entry
from web_search_harness import (
    AbsorbingTransport,
    GatedTransport,
    InterruptingTransport,
    RaisingTransport,
    ReprovisioningRecords,
    StallingTransport,
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

    from ai_assistant.core.errors import TransportError
    from ai_assistant.core.protocols import OutboundTransport
    from ai_assistant.core.types import BoundEgressCall, FrozenJson, ToolDefinition
    from ai_assistant.tools.builtin import ForecastIntegration
    from ai_assistant.tools.egress import HttpsEgressTransport

__all__ = [
    "DATE_FIELD",
    "DECIDED_AT",
    "KEYLESS",
    "LATITUDE",
    "LOCATING",
    "LONGITUDE",
    "MAX_DAYS",
    "MAX_DAY_CHARS",
    "MAX_RESPONSE_BYTES",
    "OFFSET",
    "ORIGIN",
    "REPORTED_AT",
    "UNITS",
    "VARIABLES",
    "AbsorbingTransport",
    "Built",
    "GatedTransport",
    "InterruptingTransport",
    "RaisingTransport",
    "ReprovisioningRecords",
    "StallingTransport",
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

#: The record ADR-0325's keyless act writes: ``ACTIVE`` at revision 1, naming no slot.
KEYLESS: Final = entry(slot=None)


#: The daily variables ADR-0344 §4:3 asks for, in its order, restated here rather than
#: imported so that a case asserting the request target is asserting the decision and
#: not the module's own constant back at it.
VARIABLES: Final = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)

#: What Open-Meteo's ``daily_units`` documents for each of them in its default units.
UNITS: Final = {
    "time": "iso8601",
    "weather_code": "wmo code",
    "temperature_2m_max": "\N{DEGREE SIGN}C",
    "temperature_2m_min": "\N{DEGREE SIGN}C",
    "precipitation_sum": "mm",
    "precipitation_probability_max": "%",
    "wind_speed_10m_max": "km/h",
}

#: ``+01:00``, the offset every day of a response here is in unless a case names its
#: own, as ``utc_offset_seconds`` spells it.
OFFSET: Final = "3600"

#: The members a response carries that §5:6 says reach no record, each with a value
#: distinctive enough that a case can look for it in a minted content.
LOCATING: Final = {
    "latitude": "41.16",
    "longitude": "-8.62",
    "generationtime_ms": "0.0731",
    "timezone": '"Europe/Lisbon"',
    "timezone_abbreviation": '"WEST"',
    "elevation": "93.0",
}


def day(  # noqa: PLR0913 — one parameter per daily variable ADR-0344 §4:3 names, so a case can make any one of them null or ill-typed
    *,
    date: Any = "2026-09-05",
    weather_code: str = "3",
    temperature_2m_max: str = "19.2",
    temperature_2m_min: str = "11.4",
    precipitation_sum: str = "0.0",
    precipitation_probability_max: str = "10",
    wind_speed_10m_max: str = "14.4",
) -> dict[str, str]:
    """One position of Open-Meteo's daily table, as the JSON text each column carries.

    **Every variable is raw JSON text**, so a case writes ``"17.20"``, ``"1e1"``,
    ``"null"``, ``"true"``, ``'"19.2"'``, ``"[1]"`` or ``"{}"`` and the body carries
    exactly that — which is what makes a transcription case about the token the response
    spelled rather than about a float this harness rendered.

    Args:
        date: The ``time`` element. A ``str`` is sent as that JSON string; any other
            value is sent as ``json.dumps`` writes it, ``None`` as ``null``.
        weather_code: That column's element, as JSON text.
        temperature_2m_max: Likewise.
        temperature_2m_min: Likewise.
        precipitation_sum: Likewise.
        precipitation_probability_max: Likewise.
        wind_speed_10m_max: Likewise.

    Returns:
        The position, by member name, ready for :func:`body`.
    """
    return {
        "time": json.dumps(date),
        "weather_code": weather_code,
        "temperature_2m_max": temperature_2m_max,
        "temperature_2m_min": temperature_2m_min,
        "precipitation_sum": precipitation_sum,
        "precipitation_probability_max": precipitation_probability_max,
        "wind_speed_10m_max": wind_speed_10m_max,
    }


def body(
    *days: Mapping[str, str],
    offset: str | None = OFFSET,
    units: Mapping[str, str] | str | None = None,
    columns: Mapping[str, str | None] | None = None,
    daily: str | None = None,
    group: bool = True,
) -> bytes:
    """An Open-Meteo ``/v1/forecast`` body carrying ``days``, written as JSON text.

    Written by hand rather than through ``json.dumps`` of a payload, because a number
    token's spelling is the subject of half the cases and a decoder-encoder round trip
    would re-render every one of them.

    Args:
        days: The positions of the daily table, in ``time``'s order.
        offset: ``utc_offset_seconds`` as JSON text, or ``None`` to send no such member.
        units: ``daily_units`` — a mapping of member to unit string, raw JSON text for
            the whole member, or ``None`` for :data:`UNITS`.
        columns: Members of ``daily`` to replace with this raw JSON text, or to leave
            out where the value is ``None`` — for a column of another length, another
            type, or absent.
        daily: Raw JSON text for the whole ``daily`` member, in place of the table.
        group: Whether to carry ``daily`` and ``daily_units`` at all. ``False`` is a
            response naming no day, which §5's row 6 reads as ``NO_RESULT``.

    Returns:
        The body's octets.
    """
    members = [f'"{name}": {value}' for name, value in LOCATING.items()]
    if offset is not None:
        members.append(f'"utc_offset_seconds": {offset}')
    if group:
        if isinstance(units, str):
            members.append(f'"daily_units": {units}')
        else:
            members.append(f'"daily_units": {json.dumps(UNITS if units is None else units)}')
        if daily is None:
            table: dict[str, str | None] = {
                name: "[" + ", ".join(position[name] for position in days) + "]"
                for name in ("time", *VARIABLES)
            }
            table.update(columns or {})
            daily = "{" + ", ".join(f'"{n}": {v}' for n, v in table.items() if v is not None) + "}"
        members.append(f'"daily": {daily}')
    return ("{" + ", ".join(members) + "}").encode("utf-8")


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


def answering(*days: Mapping[str, str], date: str | None = DATE_FIELD) -> FakeByteChannel:
    """A far end answering ``200`` with ``days``, in one call.

    Args:
        days: The positions of the daily table.
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
        records: The connection store, whose answers a case scripts read by read, and
            whose ``reads`` say whether the one record read happened at all.
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
        records: The connection store's scripted answers; defaults to one active,
            keyless record that never moves.
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
    capability = transport
    if capability is None:
        served = FakeOutboundTransport().serve(*channels)
        if refusal is not None:
            served.refuse_with(refusal)
        capability = served
    store = Records(KEYLESS) if records is None else records
    integration = build_forecast_integration(
        connection=REFERENCE,
        origin=origin,
        latitude=latitude,
        longitude=longitude,
        records=store,
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
        records=Records(KEYLESS),
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
