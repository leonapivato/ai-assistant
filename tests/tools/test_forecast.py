"""ADR-0260's forecast seam, over the production forecaster reading Open-Meteo (ADR-0344).

§13's arms marked L1, less the two its preamble puts elsewhere: arm (a) was at the
``ReadAsk`` model, which retired with the old path (ADR-0309 §5), and arm (j) is at
``ForecastOutcome`` in ``tests/core/``, because what they assert is a *type*'s refusal.
Everything here has a production
:class:`~ai_assistant.tools.forecast.ForecastEgress` as its subject, which is what §13's
preamble requires — "the subject is the production type or component", with exactly one
assertion admitted over the canonical fake, and that one is in
``tests/tools/test_fake_forecaster.py``.

**The arms run over Open-Meteo's format** (ADR-0344 §2:5, §8:4), and beside them each
row of ADR-0344 §5's table, the number tokens transcribed as spelled, the request target
asserted whole, the transport built with no ``Secrets`` face, and a record naming a slot
refused with no channel opened. Arm (b)'s omitted-field limb is asserted as §5:8 says —
a variable absent for every day, and a column of another length — and arm (c)'s
credential limbs as ADR-0344 §9 restates them.

**The far end is a scripted channel and never a network**, which is the harness's
property rather than this file's: the exchange takes the outbound-transport capability
as a required argument, so an arrangement that forgot to pass one would not construct.
No case sends a request to Open-Meteo; every response is one the harness wrote in its
documented format.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from egress_transport_harness import REFERENCE, SLOT, Records, entry
from forecast_harness import (
    DECIDED_AT,
    KEYLESS,
    LATITUDE,
    LOCATING,
    LONGITUDE,
    MAX_DAYS,
    ORIGIN,
    REPORTED_AT,
    UNITS,
    VARIABLES,
    AbsorbingTransport,
    Built,
    GatedTransport,
    RaisingTransport,
    ReprovisioningRecords,
    StallingTransport,
    answering,
    authorised_read,
    body,
    built,
    day,
    elsewhere_account,
    far_end,
    request,
    response,
)
from forecaster_contract import (
    CannotDescribeItself,
    ConfiguredProvider,
    ForecasterContract,
    GatedRead,
    ScriptedRead,
    ScriptedRefusal,
)

from ai_assistant.core.errors import (
    ToolBindingError,
    ToolError,
    TransportError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.protocols import Forecaster
from ai_assistant.core.types import (
    CostBasis,
    ForecastOutcome,
    ForecastRefusal,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    ProvisioningState,
    SemanticMemory,
    ToolCall,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.testing import FakeOutboundTransport
from ai_assistant.testing.cancellation import settle
from ai_assistant.tools import build_forecast_integration
from ai_assistant.tools.egress import TransportPinError
from ai_assistant.tools.forecast import (
    FORECAST_READ,
    FORECAST_READ_ID,
    FORECAST_SOURCE_NAME,
    ForecastEgress,
    _result_of,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


#: The bound every case passes unless it is about the bound.
_BOUND: Final = timedelta(seconds=30)

#: A bound small enough that a real wait past it is a fraction of a second.
_SHORT: Final = timedelta(milliseconds=50)

#: How long a case waits for a held call to answer once released.
_WAIT: Final = 5.0

#: A content bound the conformance suite's contents fit inside. Nothing in the contract
#: is a function of it; an Open-Meteo transcription is a few hundred characters.
_SMALL_CONTENT_BOUND: Final = 512

#: The bound a case sets when it wants the deadline to fire (ADR-0241 §1). Small
#: enough that the wait is a fraction of a second and large enough that a loaded
#: machine still reaches the stage under test before it expires.
_EXPIRING: Final = timedelta(milliseconds=200)

#: A clock no minted value may equal (§13's arm (b)): "In none of them does any minted
#: value equal a clock the test controls." Deliberately far from
#: :data:`~forecast_harness.REPORTED_AT`, so an implementation reading a clock of its own
#: would have to hit this value by coincidence to pass.
_OUR_CLOCK: Final = datetime(2031, 1, 1, 6, 30, tzinfo=UTC)

#: The whole request ADR-0344 §4 says one read sends, for the harness's configured place
#: and ``forecast_max_days``: the path, exactly five parameters in this order, and no
#: field beyond the exchange's own two and ``Accept``. Written out as text rather than
#: built from the module's constants, so a parameter added, dropped or reordered fails.
_REQUEST: Final = (
    b"GET /v1/forecast?latitude=41.1579&longitude=-8.6291"
    b"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    b"precipitation_probability_max,wind_speed_10m_max"
    b"&timezone=auto&forecast_days=3 HTTP/1.1\r\n"
    b"Host: forecast.example.invalid\r\n"
    b"Connection: close\r\n"
    b"Accept: application/json\r\n"
    b"\r\n"
)


async def _read(subject: Built, *, timeout: timedelta = _BOUND) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this helper only forwards the caller's bound to it
    """Drive one authorised read against ``subject``.

    Args:
        subject: The configured integration.
        timeout: The caller's bound.

    Returns:
        The outcome.
    """
    call = await authorised_read(subject.trail, await request(subject))
    outcome: ForecastOutcome = await subject.forecaster.read(call, timeout=timeout)
    return outcome


def _extents(outcome: ForecastOutcome) -> list[tuple[datetime, datetime]]:
    """The half-open bounds each minted record declares, in order.

    Args:
        outcome: The outcome to read.

    Returns:
        One pair per record. ``ForecastOutcome`` refuses a record with an unbounded
        extent, so neither end can be ``None`` here.
    """
    pairs: list[tuple[datetime, datetime]] = []
    for record in outcome.records:
        attestation = record.provenance.attestation
        assert attestation is not None
        extent = attestation.extent
        assert extent is not None
        assert extent.extends_from is not None
        assert extent.extends_until is not None
        pairs.append((extent.extends_from, extent.extends_until))
    return pairs


def _days(outcome: ForecastOutcome) -> list[str]:
    """The day each minted record's content names, in order.

    Args:
        outcome: The outcome to read.

    Returns:
        One ``YYYY-MM-DD`` per record, read off the first transcribed line — which is
        this adapter's own pinned form and not a cross-implementation one.
    """
    return [record.content.split("\n", 1)[0].removeprefix("time: ") for record in outcome.records]


def _content(**values: str) -> str:
    """The transcription this adapter pins for one day, with :data:`UNITS`' units.

    Args:
        values: ``time`` and each variable's token, as the response spelled them.
            Unnamed ones take :func:`~forecast_harness.day`'s defaults.

    Returns:
        The content a minted record carries.
    """
    tokens = {name: value for name, value in day().items() if name != "time"}
    tokens.update({name: value for name, value in values.items() if name != "time"})
    date = values.get("time", "2026-09-05")
    lines = [f"time: {date}", *(f"{name}: {tokens[name]} {UNITS[name]}" for name in VARIABLES)]
    return "\n".join(lines)


def _sent(subject: Built) -> bytes:
    """Every octet the one channel ``subject`` opened was written.

    Args:
        subject: The configured integration, built over the canonical transport.

    Returns:
        The request, as the far end received it.
    """
    assert isinstance(subject.transport, FakeOutboundTransport)
    (channel,) = subject.transport.channels
    return channel.written


# --- ADR-0344 §4: the request, whole ----------------------------------------


async def test_one_read_sends_exactly_the_request_adr_0344_states() -> None:
    """§4:1 to §4:6, over the octets the far end received.

    "``GET /v1/forecast`` at the configured origin, whose query carries exactly the
    parameters ``latitude``, ``longitude``, ``daily``, ``timezone`` and
    ``forecast_days``, and no credential", and "the adapter adds no request field beyond
    ``Accept: application/json``". **Asserted whole**, so an added parameter, a unit
    setting, an ``apikey``, ``Settings.timezone`` or a field of the adapter's own fails
    (§8:4) — the two fields before ``Accept`` are the exchange's, for every integration.
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.refusal is None
    assert _sent(subject) == _REQUEST


@pytest.mark.parametrize("max_days", [1, 2, 3])
async def test_forecast_days_is_the_forecaster_s_own_bound(max_days: int) -> None:
    """§4:5: ``forecast_days`` is ``Settings.forecast_max_days``, held from construction.

    Asked for what will be minted rather than Open-Meteo's default seven days, which is
    what keeps ``forecast_max_response_bytes`` a backstop rather than the ordinary
    outcome.
    """
    subject = await built(channels=[answering(day())], max_days=max_days)

    await _read(subject)

    assert f"&timezone=auto&forecast_days={max_days} HTTP/1.1".encode() in _sent(subject)


@pytest.mark.parametrize(
    ("latitude", "spelled"),
    [
        pytest.param(0.00001, "0.00001", id="small-enough-for-repr-to-use-an-exponent"),
        pytest.param(-90.0, "-90.0", id="a-whole-number-of-degrees"),
        pytest.param(41.1579, "41.1579", id="the-configured-place"),
    ],
)
async def test_the_coordinate_is_written_in_plain_decimal(latitude: float, spelled: str) -> None:
    """§4:2: the ruled coordinate, spelled as the same float and without an exponent.

    ``repr(0.00001)`` is ``1e-05``; the target carries ``0.00001``, which is the same
    value in the positional notation Open-Meteo's documentation shows.
    """
    subject = await built(channels=[answering(day())], latitude=latitude)

    call = await authorised_read(subject.trail, await request(subject, latitude=latitude))
    await subject.forecaster.read(call, timeout=_BOUND)

    assert f"/v1/forecast?latitude={spelled}&longitude=".encode() in _sent(subject)


def test_the_daily_set_is_pinned() -> None:
    """§4:3: the set is "a constant of the adapter's code, pinned by a test".

    "Its first members are ``weather_code``, ``temperature_2m_max``,
    ``temperature_2m_min``, ``precipitation_sum``, ``precipitation_probability_max`` and
    ``wind_speed_10m_max``, in that order."
    """
    from ai_assistant.tools.forecast import _DAILY_VARIABLES  # noqa: PLC0415 — the pin

    assert _DAILY_VARIABLES == VARIABLES


# --- ADR-0344 §2:3: keyless, fixed where the transport is built --------------


async def test_the_transport_is_built_with_no_secrets_face() -> None:
    """§2:3, §8:4: "the transport constructed with no ``Secrets`` face".

    Asserted over the object the builder built and over the builder's own signature:
    there is no parameter through which a face could reach it, so the shape is the
    code's and no caller's (ADR-0325 §2:2).
    """
    subject = await built(channels=[answering(day())])

    assert subject.seam._secrets is None
    assert "secrets" not in inspect.signature(build_forecast_integration).parameters


async def test_a_record_naming_a_slot_is_refused_with_no_channel_opened() -> None:
    """§8:4, ADR-0325 §2:3: "a record naming a slot returning ``PROVIDER_REFUSED`` with
    no channel opened".

    A keyless callable refuses a record that names a credential, because ignoring it
    would leave a credential in the keyring that no call reads while the user believes
    it is in use. The record is read **once** (ADR-0325 §2:5).
    """
    subject = await built(channels=[answering(day())], records=Records(entry(slot=SLOT)))

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()
    assert subject.records.reads == [REFERENCE]


async def test_a_record_re_provisioned_to_name_a_slot_before_the_one_read_is_refused() -> None:
    """ADR-0344 §9, on ADR-0260 §13:3's arm (c): the interleaving limb, replaced.

    "A record re-provisioned to name a slot before the one read, which returns
    ``PROVIDER_REFUSED`` with no channel opened while the three checks still raise."
    The binding was derived over the keyless record at revision 1; the record the one
    read finds is revision 2 and names a slot. **Returned**, where the three checks
    raise — asserted beside them below.
    """
    subject = await built(
        channels=[answering(day())], records=Records(entry(slot=SLOT, revision=2))
    )

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()
    assert subject.records.reads == [REFERENCE]


async def test_a_provisioning_act_landing_after_the_one_read_stops_nothing() -> None:
    """ADR-0344 §3:6, ADR-0325 §2:6: the re-read limb has no subject.

    An act landing after the one read is ADR-0148 §6:21's case and stops nothing
    already begun: the read proceeds, mints, and reads the record exactly once — there
    is no credential read for a second read to bracket.
    """
    records = ReprovisioningRecords(KEYLESS, entry(slot=SLOT, revision=2))
    transport = GatedTransport(answering(day()))
    subject = await built(transport=transport, records=records)
    call = await authorised_read(subject.trail, await request(subject))

    # Held at the channel's open, which is after the one read: the reprovisioning the
    # read queued lands there, while the request is under way.
    gate = transport.suspend_next()
    running = asyncio.ensure_future(subject.forecaster.read(call, timeout=_BOUND))
    await gate.reached()
    assert records.reprovisioned is True
    gate.release()
    outcome = await asyncio.wait_for(running, _WAIT)

    assert _days(outcome) == ["2026-09-05"]
    assert records.reads == [REFERENCE]


# --- ADR-0344 §5's table, rows 1 to 6: the first that holds decides ----------


async def test_row_1_a_response_at_the_read_bound_is_read_and_one_past_it_is_abandoned() -> None:
    """Row 1, ADR-0260 §11:3: "A response **at** the bound is read and minted; a response
    **beyond** it is **abandoned and refused**, never truncated".

    The bound counts "the most octets one response may take off the channel — its status
    line and headers included — enforced *on the read itself* and before any part of it is
    parsed". **No parse is attempted on the over-large one**, which the assertion catches
    by construction: the body is well-formed, so an implementation that buffered and then
    measured would answer with records rather than with the refusal.
    """
    octets = response(payload=body(day()))

    at_the_bound = await built(channels=[far_end(octets)], max_response_bytes=len(octets))
    past_it = await built(channels=[far_end(octets)], max_response_bytes=len(octets) - 1)

    admitted = await _read(at_the_bound)
    refused = await _read(past_it)

    assert admitted.refusal is None
    assert len(admitted.records) == 1
    assert refused.refusal is ForecastRefusal.RESPONSE_TOO_LARGE
    assert refused.records == ()


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        pytest.param("HTTP/1.1 204 No Content", b"", id="no-representation"),
        pytest.param(
            "HTTP/1.1 400 Bad Request",
            b'{"error": true, "reason": "Cannot initialize WeatherVariable from invalid String"}',
            id="open-meteo-s-error-object",
        ),
        pytest.param("HTTP/1.1 429 Too Many Requests", b"", id="rate-limited"),
        pytest.param("HTTP/1.1 500 Internal Server Error", b"", id="server-error"),
        pytest.param("HTTP/1.1 201 Created", body(day()), id="a-2xx-that-is-not-200"),
    ],
)
async def test_row_2_a_status_other_than_200_is_refused(status: str, payload: bytes) -> None:
    """Row 2: "a status other than ``200``, a ``400`` error object and a ``429``
    included" is ``PROVIDER_REFUSED``.

    A ``2xx`` that is not ``200`` is a response no day is read from rather than a
    successful read of zero days — and one carrying a well-formed table is refused all
    the same, because the status is judged first.
    """
    subject = await built(channels=[far_end(response(status=status, payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param(b"not json at all", id="not-json"),
        pytest.param(b'["a list"]', id="not-an-object"),
        pytest.param(b"\xff\xfe", id="not-utf-8"),
        pytest.param(b"", id="empty"),
        # RFC 8259 has no such token. Python's decoder takes all three as an extension
        # unless told otherwise, and a body carrying one **anywhere** — including in a
        # member nothing reads — is a body outside the documented format.
        pytest.param(b'{"daily": {"time": []}, "elevation": NaN}', id="a-nan-nobody-reads"),
        pytest.param(b'{"utc_offset_seconds": Infinity}', id="an-infinity"),
        pytest.param(b'{"utc_offset_seconds": -Infinity}', id="a-negative-infinity"),
        pytest.param(b"[" * 200 + b"]" * 200, id="nested-past-the-decoder-s-bound"),
    ],
)
async def test_row_3_a_body_that_is_not_a_json_object_is_refused(malformed: bytes) -> None:
    """Row 3: "a body that is not a UTF-8 JSON object, as ``decoded_object`` reads one".

    The provider answered — octets arrived — and what it answered is not something this
    system will read, which is a different operator fact from a channel that could not be
    opened.
    """
    subject = await built(channels=[far_end(response(payload=malformed))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "arrangement",
    [
        pytest.param({"daily": "[]"}, id="daily-an-array"),
        pytest.param({"daily": "null"}, id="daily-null"),
        pytest.param({"daily": '"a table"'}, id="daily-a-string"),
        pytest.param({"columns": {"time": "null"}}, id="time-null"),
        pytest.param({"columns": {"time": '{"0": "2026-09-05"}'}}, id="time-an-object"),
        pytest.param({"columns": {"time": '"2026-09-05"'}}, id="time-a-string"),
        pytest.param({"columns": {"temperature_2m_max": "null"}}, id="a-variable-null"),
        pytest.param({"columns": {"temperature_2m_max": "19.2"}}, id="a-variable-a-number"),
        pytest.param({"columns": {"precipitation_sum": "{}"}}, id="a-variable-an-object"),
        pytest.param({"columns": {"weather_code": "[3]"}}, id="a-column-one-short"),
        pytest.param({"columns": {"weather_code": "[3, 3, 3]"}}, id="a-column-one-long"),
        pytest.param({"columns": {"wind_speed_10m_max": "[]"}}, id="a-column-empty"),
    ],
)
async def test_row_4_a_table_that_does_not_say_which_value_is_which_day_s_is_refused(
    arrangement: dict[str, Any],
) -> None:
    """Row 4, and §13:3's arm (b) in the column-of-another-length limb ADR-0344 §5:8 gives.

    "``daily`` present and not an object, ``daily.time`` present and not an array, or a
    requested variable's member present and not an array or not of ``daily.time``'s
    length" is ``PROVIDER_REFUSED``: "the response does not say which value belongs to
    which day", and pairing them by position would be this system deciding what the
    provider said. A refusal of the whole response, not a drop of the short day.
    """
    payload = body(day(date="2026-09-05"), day(date="2026-09-06"), **arrangement)
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


async def test_row_4_outranks_row_5() -> None:
    """§5:1: rows 1 to 6 are taken in order. A malformed table with no ``Date`` is row 4's.

    An implementation reading the instant first would answer ``UNATTESTED`` about a
    response whose shape it could not read at all.
    """
    payload = body(day(), columns={"weather_code": "[]"})
    subject = await built(channels=[far_end(response(date=None, payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"date": None}, id="no-date-field"),
        pytest.param({"date": "Fri, 04 Sep 2026 12:00:00 UTC"}, id="not-gmt"),
        pytest.param({"date": "Friday, 04-Sep-26 12:00:00 GMT"}, id="rfc-850"),
        pytest.param({"date": "Fri Sep  4 12:00:00 2026"}, id="asctime"),
        pytest.param({"date": "not a date at all"}, id="malformed"),
        pytest.param({"headers": ["Date: Fri, 04 Sep 2026 12:00:01 GMT"]}, id="two-date-fields"),
    ],
)
async def test_row_5_a_response_with_no_single_readable_date_mints_nothing(
    headers: dict[str, Any],
) -> None:
    """Row 5, ADR-0260 §5:7: "No single readable ``Date`` field" is ``UNATTESTED``.

    ADR-0092 §3 binds as written and there is **no substitute** (ADR-0344 §5:7): not the
    instant we sent, not the instant we received, not a clock this system read. Two
    ``Date`` fields declare two instants, so the response declares none this seam will
    pick between.
    """
    subject = await built(channels=[far_end(response(payload=body(day()), **headers))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.UNATTESTED
    assert outcome.records == ()


async def test_row_5_outranks_row_6() -> None:
    """§5:1: a response naming no day and declaring no instant is row 5's, not row 6's."""
    subject = await built(channels=[far_end(response(date=None, payload=body(group=False)))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.UNATTESTED


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(body(group=False), id="no-daily"),
        pytest.param(body(day(), columns={"time": None}), id="no-time"),
        pytest.param(body(daily="{}"), id="an-empty-table"),
    ],
)
async def test_row_6_a_response_naming_no_day_yields_no_result(payload: bytes) -> None:
    """Row 6: "``daily`` absent, or ``daily.time`` absent" is ``NO_RESULT``.

    A provider with nothing to say for the coordinate is not a malformed shape — reading
    it as one would report a provider that answered perfectly well as one that answered
    something else. With ``time`` absent no column has a length to disagree with, so the
    variables beside it are not row 4's.
    """
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


# --- rows 7 to 14: what drops days, and what is minted ----------------------


async def test_a_day_mints_its_own_half_open_interval_at_the_declared_offset() -> None:
    """§13:3's arm (b), ADR-0344 §5:4: the extent is the day at ``utc_offset_seconds``.

    "A day's extent is the half-open interval from that day's midnight at that offset to
    24 hours later, computed from the date and the offset alone." The offset here is
    ``+05:30``, so the day begins five and a half hours *before* UTC midnight; a reader
    that ignored the offset, or rounded it to hours, produces another interval and
    passes every assertion about the record's shape — which is why the ends are asserted
    by value.
    """
    subject = await built(channels=[far_end(response(payload=body(day(), offset="19800")))])

    outcome = await _read(subject)

    assert _extents(outcome) == [
        (datetime(2026, 9, 4, 18, 30, tzinfo=UTC), datetime(2026, 9, 5, 18, 30, tzinfo=UTC))
    ]


@pytest.mark.parametrize(
    ("offset", "starts"),
    [
        pytest.param("0", datetime(2026, 9, 5, 0, 0, tzinfo=UTC), id="utc"),
        pytest.param("-0", datetime(2026, 9, 5, 0, 0, tzinfo=UTC), id="negative-zero"),
        pytest.param("-14400", datetime(2026, 9, 5, 4, 0, tzinfo=UTC), id="behind-utc"),
        pytest.param("86399", datetime(2026, 9, 4, 0, 0, 1, tzinfo=UTC), id="just-inside-a-day"),
        pytest.param("-86399", datetime(2026, 9, 5, 23, 59, 59, tzinfo=UTC), id="just-inside-west"),
    ],
)
async def test_row_7_an_integer_offset_inside_a_day_is_read(offset: str, starts: datetime) -> None:
    """Row 7's positive arm, so its refusals below are not vacuous.

    Every integer token of magnitude less than 86 400 is an offset a day can be in, and
    the extent is a fixed 24 hours at it (ADR-0344 §5, "Why the extent is a fixed 24
    hours, across a DST change too").
    """
    subject = await built(channels=[far_end(response(payload=body(day(), offset=offset)))])

    outcome = await _read(subject)

    assert _extents(outcome) == [(starts, starts + timedelta(days=1))]


@pytest.mark.parametrize(
    "offset",
    [
        pytest.param(None, id="absent"),
        pytest.param("null", id="null"),
        pytest.param('"3600"', id="a-string"),
        pytest.param("3600.0", id="a-fraction-token"),
        pytest.param("36e2", id="an-exponent-token"),
        pytest.param("86400", id="a-whole-day"),
        pytest.param("-86400", id="a-whole-day-west"),
        # Inside the interpreter's own integer-string limit, so the body passes row 3 and
        # what refuses it is this row's magnitude — read off the token's length, since
        # `int` of a long token is the work the length check exists to avoid.
        pytest.param("9" * 1000, id="a-thousand-digits"),
    ],
)
async def test_row_7_an_offset_that_is_not_one_drops_every_day(offset: str | None) -> None:
    """Row 7, ADR-0260 §5:8: every day declares no offset and is dropped.

    "``utc_offset_seconds`` absent, not an integer token, or of magnitude 86 400 or
    more." **Dropped rather than minted with an extent this system computed**, which is
    the fail-closed direction: an extent from our own timezone database would be this
    system stating where the provider's entry lies. ``3600.0`` names the same number of
    seconds as ``3600`` and is still not an integer token, which is what the row says.
    """
    payload = body(day(date="2026-09-05"), day(date="2026-09-06"), offset=offset)
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


@pytest.mark.parametrize("variable", VARIABLES)
async def test_row_8_a_requested_variable_absent_drops_every_day(variable: str) -> None:
    """Row 8, and §13:3's arm (b) in the omitted-field limb ADR-0344 §5:8 restates.

    "A column of Open-Meteo's table cannot be absent for one day alone, so that limb is
    asserted as row 8, a requested variable's member absent dropping every day and
    yielding ``NO_RESULT``." Over every variable, so none is optional by omission.
    """
    payload = body(day(date="2026-09-05"), day(date="2026-09-06"), columns={variable: None})
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


@pytest.mark.parametrize(
    "units",
    [
        pytest.param("null", id="daily-units-null"),
        pytest.param("[]", id="daily-units-an-array"),
        pytest.param({**UNITS, "temperature_2m_min": None}, id="a-unit-null"),
        pytest.param({**UNITS, "precipitation_sum": 0}, id="a-unit-a-number"),
        pytest.param(
            {name: unit for name, unit in UNITS.items() if name != "wind_speed_10m_max"},
            id="a-unit-absent",
        ),
        pytest.param({**UNITS, "weather_code": "wmo\ncode"}, id="a-unit-carrying-a-line-break"),
        # `json.dumps` writes the lone surrogate as `\ud800`, which the response then
        # carries and the decoder hands back as a `str` no UTF-8 encoder accepts.
        pytest.param({**UNITS, "weather_code": "\ud800"}, id="a-unit-with-a-lone-surrogate"),
        pytest.param({**UNITS, "precipitation_sum": "m\udfffm"}, id="a-low-surrogate-inside"),
    ],
)
async def test_row_8_a_unit_daily_units_does_not_give_as_a_string_drops_every_day(
    units: Any,
) -> None:
    """Row 8: "a requested variable … whose unit ``daily_units`` does not give as a
    string" drops every day (ADR-0260 §5:3).

    No day's transcription can carry what §5:5 says it carries — its unit "as
    ``daily_units`` spells it". A unit carrying a line break is in every day's
    transcription and breaks the line structure that keeps its spans apart, and one
    carrying a lone surrogate has no UTF-8 encoding no record can hold: each drops every
    day by the same rule one step on, **returned** as ``NO_RESULT`` and never raised
    (ADR-0260 §4).
    """
    payload = body(day(date="2026-09-05"), day(date="2026-09-06"), units=units)
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


async def test_row_8_daily_units_absent_drops_every_day() -> None:
    """Row 8 with no ``daily_units`` member at all: no variable's unit is given."""
    payload = body(day()).replace(f'"daily_units": {json.dumps(UNITS)}, '.encode(), b"")
    assert b"daily_units" not in payload, "the case is about a response with no units"
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


@pytest.mark.parametrize(
    "date",
    [
        pytest.param(None, id="null"),
        pytest.param(20260905, id="a-number"),
        pytest.param("2026-9-5", id="unpadded"),
        pytest.param("20260905", id="basic-format"),
        pytest.param("2026-W36-6", id="a-week-date"),
        pytest.param("2026-02-30", id="no-such-day"),
        pytest.param("2026-09-05T00:00", id="a-date-time"),
        pytest.param("2026-09-0\N{FULLWIDTH DIGIT FIVE}", id="a-non-ascii-digit"),
    ],
)
async def test_row_9_a_time_element_naming_no_calendar_day_drops_its_position(date: Any) -> None:
    """Row 9: "a ``time`` element that is not a ``YYYY-MM-DD`` string naming a calendar
    day" — "that position names no day and is dropped", and its siblings are minted.

    **One spelling and no other.** ``date.fromisoformat`` admits the basic format and a
    week date since 3.11, and two spellings of one day would let row 11 compare unequal
    values naming the same day. The non-ASCII digit is the case a parser checking
    ``isdigit`` without ``isascii`` would read as a number.
    """
    subject = await built(channels=[answering(day(date=date), day(date="2026-09-06"))])

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    ("date", "offset"),
    [
        pytest.param("9999-12-31", "-3600", id="ends-past-the-representable-range"),
        pytest.param("0001-01-01", "3600", id="starts-before-it"),
    ],
)
async def test_row_10_a_day_with_no_constructible_extent_is_dropped(date: str, offset: str) -> None:
    """Row 10, ADR-0260 §5:9: "a day whose date and offset make no constructible extent".

    ``9999-12-31`` at ``-01:00`` ends past the last instant ``datetime`` holds, and
    ``0001-01-01`` at ``+01:00`` begins before the first. Either is dropped rather than
    given an extent trimmed to fit, and the siblings are minted.
    """
    payload = body(day(date=date), day(date="2026-09-06"), offset=offset)
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    "second",
    [
        pytest.param({}, id="positions-that-agree"),
        pytest.param({"weather_code": "61"}, id="positions-that-conflict"),
    ],
)
async def test_row_11_a_day_named_twice_drops_every_one_of_its_positions(
    second: dict[str, str],
) -> None:
    """Row 11, ADR-0260 §5:3: "every one of its positions is dropped".

    "Whether they agree or conflict: the response has not described that day once, and
    preferring one row over another would be this system deciding what the provider
    said." The agreeing case is the one an implementation would be tempted to keep.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05"),
                day(date="2026-09-06"),
                day(date="2026-09-05", **second),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(("complete", "incomplete"), id="the-complete-position-first"),
        pytest.param(("incomplete", "complete"), id="the-incomplete-position-first"),
    ],
)
async def test_row_11_counts_every_position_that_names_a_day(order: tuple[str, str]) -> None:
    """Row 11 is over the day the response **names**, not over the survivors of rows 12-13.

    **An incomplete position still names its day**, so a count taken over the positions
    that survived the *other* drops sees the day once and mints the complete one — the
    preference the clause forbids. Both encounter orders, because an implementation that
    dropped the position it met second would pass one of them.
    """
    complete = day(date="2026-09-05")
    incomplete = day(date="2026-09-05", temperature_2m_min="null")
    positions = [complete if name == "complete" else incomplete for name in order]
    subject = await built(channels=[answering(*positions, day(date="2026-09-06"))])

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_row_11_meeting_row_13_is_two_drops_and_one_day() -> None:
    """The over-long position is dropped on its own account and still **named** the day."""
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05"),
                day(date="2026-09-05", weather_code="1" + "0" * 600),
                day(date="2026-09-06"),
            )
        ],
        max_day_chars=_SMALL_CONTENT_BOUND,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_row_11_positions_naming_no_day_are_counted_toward_none() -> None:
    """Two positions naming no day name one *absence*, and that is not a duplicate."""
    subject = await built(
        channels=[answering(day(date=None), day(date="not a date"), day(date="2026-09-06"))]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_row_11_a_duplicate_beyond_the_cap_still_drops_both_positions() -> None:
    """§13:3's arm (b), as the arm states it: the second occurrence beyond the cap.

    "Because an implementation capping before it looks for duplicates mints the first
    row and passes every arm that keeps the duplicate inside the cap."
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05"),
                day(date="2026-09-06"),
                day(date="2026-09-07"),
                day(date="2026-09-05", weather_code="61"),
            )
        ],
        max_days=3,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06", "2026-09-07"]


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"weather_code": "null"}, id="null"),
        pytest.param({"temperature_2m_max": "true"}, id="a-boolean"),
        pytest.param({"temperature_2m_min": '"11.4"'}, id="a-string"),
        pytest.param({"precipitation_sum": "[0.0]"}, id="an-array"),
        pytest.param({"wind_speed_10m_max": '{"value": 14.4}'}, id="an-object"),
    ],
)
async def test_row_12_a_value_the_format_does_not_admit_drops_that_day_only(
    broken: dict[str, str],
) -> None:
    """Row 12, and §13:3's arm (b) in its ``null`` and ill-typed limbs, which stand.

    "A day whose element for a requested variable is ``null``, a boolean, a string, an
    array or an object" is dropped, "and the remaining days are minted" — the half an
    implementation refusing the whole response would get wrong. A number written as a
    string is the sharpest: reading ``"11.4"`` as ``11.4`` would be this system deciding
    what the provider meant.
    """
    subject = await built(
        channels=[answering(day(date="2026-09-05", **broken), day(date="2026-09-06"))]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_row_13_a_day_at_the_content_bound_is_minted_and_one_past_it_is_dropped() -> None:
    """Row 13, ADR-0260 §5:3, §11: over ``forecast_max_day_chars`` is **dropped**.

    "Measured as ADR-0230 §6 measures a fetched document" — on the ``json.dumps``
    rendering at its default ``ensure_ascii=True``, its two delimiters included. The
    degree sign is six characters there and one in the source, which is what makes the
    measure the rendering's and not the source's.
    """
    exactly = len(json.dumps(_content()))

    minted = await built(channels=[answering(day())], max_day_chars=exactly)
    dropped = await built(
        channels=[answering(day(), day(date="2026-09-06"))], max_day_chars=exactly - 1
    )

    kept = await _read(minted)
    thinned = await _read(dropped)

    assert _days(kept) == ["2026-09-05"]
    assert thinned.refusal is ForecastRefusal.NO_RESULT


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        pytest.param(2, ["2026-09-05", "2026-09-06"], id="fewer-than-the-figure"),
        pytest.param(3, ["2026-09-05", "2026-09-06", "2026-09-07"], id="exactly-the-figure"),
        pytest.param(5, ["2026-09-05", "2026-09-06", "2026-09-07"], id="more-than-the-figure"),
    ],
)
async def test_row_14_the_first_survivors_are_minted_in_time_s_order(
    offered: int, expected: Sequence[str]
) -> None:
    """Row 14, ADR-0260 §5:1, §13's arm (b-prime): "the records minted are the **first**
    that many".

    "The last asserted over **which** days those are and over their extents rather than
    over the count alone — taking the first and taking the last both satisfy a count
    while minting different evidence."
    """
    positions = [day(date=f"2026-09-{5 + index:02d}") for index in range(offered)]
    subject = await built(channels=[answering(*positions)], max_days=MAX_DAYS)

    outcome = await _read(subject)

    assert _days(outcome) == list(expected)
    assert [start for start, _ in _extents(outcome)] == [
        datetime(2026, 9, 4 + index, 23, 0, tzinfo=UTC) for index in range(len(expected))
    ]


async def test_row_14_the_cap_counts_what_survived_and_not_what_the_provider_sent() -> None:
    """§13's arm (b-prime): "a response whose days exceed the figure only once an
    incomplete one has been dropped mints the **first** ``forecast_max_days`` of what
    survived"."""
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-04", weather_code="null"),
                day(date="2026-09-05"),
                day(date="2026-09-06"),
                day(date="2026-09-07"),
            )
        ],
        max_days=3,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-05", "2026-09-06", "2026-09-07"]


async def test_row_14_the_cap_counts_what_the_content_bound_left_too() -> None:
    """The cap is over every drop's survivors, row 13's as well as row 12's."""
    subject = await built(
        channels=[
            answering(day(date="2026-09-05", weather_code="1" + "0" * 600), day(date="2026-09-06"))
        ],
        max_days=1,
        max_day_chars=_SMALL_CONTENT_BOUND,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_row_14_none_surviving_is_no_result() -> None:
    """ADR-0260 §5:3: "Where every day is dropped the read yields nothing" — ``NO_RESULT``.

    Not an empty success: ``ForecastOutcome`` refuses an outcome carrying neither.
    """
    subject = await built(
        channels=[answering(day(date="2026-02-30"), day(temperature_2m_max="null"))]
    )

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT
    assert outcome.records == ()


async def test_a_response_of_many_days_is_read_in_one_pass_over_them() -> None:
    """§4's deadline covers the transcription and the minting, so the work under it is
    linear.

    A response well inside ``forecast_max_response_bytes`` can name thousands of days —
    this one does — and **no ``await`` occurs between the octets arriving and the records
    being minted**, so a duplicate pass taken per position rather than over the days
    would be quadratic with the bound unable to fire. Row 11 still holds across the whole
    response rather than within a window.
    """
    positions = [
        day(date=f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}") for index in range(2000)
    ]
    # One day named twice, at the two ends of the response: a pass that only compared
    # neighbours, or only looked inside the cap, would keep both.
    positions.append(day(date="2026-01-01", weather_code="61"))
    subject = await built(channels=[answering(*positions)], max_response_bytes=4 * 1024 * 1024)

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-01-02", "2026-01-03", "2026-01-04"]


async def test_a_long_shared_unit_is_measured_once_and_not_once_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 13 over a unit every day shares, at a size the response bound admits.

    A unit appears in every day's transcription, so a reader that built and encoded each
    day before measuring it would copy a hundred-thousand-character unit once per day —
    quadratic work on the event loop's own thread, where ADR-0260 §4's deadline cannot be
    delivered (adversarial review of PR #3352, round 1). **Asserted over the work and not
    over a clock**: every string the read hands ``json.dumps`` is counted, and the total
    is bounded by a small multiple of the response's own size.
    """
    unit = "x" * 100_000
    positions = [
        day(date=(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)).date().isoformat())
        for index in range(3000)
    ]
    payload = body(*positions, units={**UNITS, "weather_code": unit})
    subject = await built(
        channels=[far_end(response(payload=payload))], max_response_bytes=4 * 1024 * 1024
    )
    call = await authorised_read(subject.trail, await request(subject))
    encoded: list[int] = []
    real = json.dumps

    def counting(value: Any, *arguments: Any, **keywords: Any) -> str:
        if isinstance(value, str):
            encoded.append(len(value))
        return real(value, *arguments, **keywords)

    monkeypatch.setattr(json, "dumps", counting)
    outcome = await subject.forecaster.read(call, timeout=_BOUND)
    monkeypatch.undo()

    assert outcome.refusal is ForecastRefusal.NO_RESULT
    assert sum(encoded) <= 2 * len(payload)


# --- the transcription (ADR-0344 §5:2, §5:5, §5:6) --------------------------


async def test_the_transcription_form_is_pinned() -> None:
    """§5:5: "the ``time`` value and then each requested variable in the ``daily`` order,
    each with the provider's field name, its token as the response spelled it and, for a
    variable, its unit as ``daily_units`` spells it. The separators are fixed by the
    adapter and pinned by a test" — this one.
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    minted = outcome.records[0]
    assert isinstance(minted, SemanticMemory)
    assert minted.content == (
        "time: 2026-09-05\n"
        "weather_code: 3 wmo code\n"
        "temperature_2m_max: 19.2 \N{DEGREE SIGN}C\n"
        "temperature_2m_min: 11.4 \N{DEGREE SIGN}C\n"
        "precipitation_sum: 0.0 mm\n"
        "precipitation_probability_max: 10 %\n"
        "wind_speed_10m_max: 14.4 km/h"
    )
    assert minted.fact == minted.content


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("17.20", id="a-trailing-zero"),
        pytest.param("1e1", id="an-exponent"),
        pytest.param("1E+05", id="an-upper-case-signed-exponent"),
        pytest.param("-0", id="negative-zero"),
        pytest.param("-0.0", id="negative-zero-with-a-fraction"),
        pytest.param("0.10000000000000000555", id="more-digits-than-a-float-holds"),
        pytest.param("123456789012345678901234567890", id="a-huge-integer"),
    ],
)
async def test_a_number_token_is_transcribed_as_the_response_spelled_it(token: str) -> None:
    """ADR-0344 §5:2, §8:4: "a number token transcribed as it was spelled, ``17.20`` and
    ``1e1`` included".

    "The body is decoded with each number token kept as the text the response carried,
    and no transcribed value is parsed to a number or re-rendered on the way to a
    record." Each of these is a spelling a ``float`` or ``int`` round trip would change.
    """
    subject = await built(channels=[answering(day(temperature_2m_max=token))])

    outcome = await _read(subject)

    assert outcome.records[0].content == _content(temperature_2m_max=token)


async def test_a_unit_carries_what_its_escape_encodes_and_not_the_escape() -> None:
    """ADR-0260 §5:2 is ADR-0230 §5's **decoding**-not-rendering rule.

    JSON's ``\\u00b0`` is that format's encoding of the degree sign, so the unit the
    response *carried* is ``°C`` and the record carries those two characters — "no word
    of this system's is added", and the transport's escaping is not a word of the
    provider's either.
    """
    payload = body(day()).replace(b'"\\u00b0C"', b'"\\u00B0C"')
    assert b"\\u00B0C" in payload, "the case is about an escape that reached the wire"
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.records[0].content == _content()


async def test_a_duplicate_json_member_is_resolved_by_the_decoder_and_not_by_this_seam() -> None:
    """The container format's own ambiguity is resolved by the decoding (ADR-0230 §5).

    RFC 8259 admits a repeated member name and fixes no meaning for it; Python's decoder
    resolves one deterministically, last occurrence winning. Row 11 is stated over a
    *day* named twice in ``daily.time``, not over the transport's object members, and
    reading it onto them would put a duplicate-detecting decoder into the reader
    ``tools/http_reading.py`` shares with the ``WEB_SEARCH`` seam. Pinned so the reading
    is decided rather than undecided.
    """
    payload = body(day(weather_code="61")).replace(
        b'"weather_code": [61]', b'"weather_code": [3], "weather_code": [61]'
    )
    assert payload.count(b'"weather_code": [') == 2, "the case is about a repeated member"
    subject = await built(channels=[far_end(response(payload=payload))])

    outcome = await _read(subject)

    assert outcome.records[0].content == _content(weather_code="61")


async def test_no_other_member_of_the_response_reaches_a_record() -> None:
    """§5:6: not ``latitude``, ``longitude``, ``elevation``, ``timezone`` or
    ``timezone_abbreviation``, "each of which locates or names a place", and not
    ``generationtime_ms`` or ``utc_offset_seconds``.

    The response the harness writes carries each with a distinctive value, and none of
    them — nor the members' names — appears in what was minted.
    """
    subject = await built(channels=[answering(day(), day(date="2026-09-06"))])

    outcome = await _read(subject)

    assert len(outcome.records) == 2
    for record in outcome.records:
        for name, value in LOCATING.items():
            assert name not in record.content
            assert value.strip('"') not in record.content
        assert "utc_offset_seconds" not in record.content
        assert "3600" not in record.content


# --- ADR-0260 §13's arm (b) and (b-prime): what the producer owes -------------


async def test_a_minted_record_carries_a_fully_open_validity() -> None:
    """ADR-0260 §5: "``validity`` is fully open and no lane sets it to the day the record is
    about".

    ADR-0045 §2 makes the envelope window "a lifecycle property of the record's life in
    the store, set operationally by the applier", and ADR-0252 §3 forbids reading it as
    coverage "on any kind, under any fallback".
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.records
    for record in outcome.records:
        assert record.validity.valid_from is None
        assert record.validity.valid_until is None


async def test_no_minted_value_equals_a_clock_this_test_controls() -> None:
    """§13's arm (b)'s closing clause, asserted over every instant a record carries.

    "In none of them does any minted value equal a clock the test controls." The
    assertion is over the *record* rather than over the outcome, because
    ``Provenance.last_updated`` and ``last_confirmed_at`` are two more places a producer
    could reach for a local clock while still satisfying ``ForecastOutcome``'s
    attestation equality.
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.reported_at == REPORTED_AT
    assert outcome.records
    for record in outcome.records:
        attestation = record.provenance.attestation
        assert attestation is not None
        assert attestation.reported_at == REPORTED_AT
        assert record.provenance.last_updated == REPORTED_AT
        assert record.provenance.last_confirmed_at == REPORTED_AT
        assert REPORTED_AT != _OUR_CLOCK


async def test_a_minted_record_carries_the_facts_the_producer_owes() -> None:
    """§13's arm (b-prime): the §5 facts ``ForecastOutcome`` cannot decide.

    "Over the **production** forecaster's own output, a minted record's ``confidence`` is
    ``0.9``, its ``derived_from_external`` is ``False``, its ``placement`` is the default
    that narrows nothing, and its ``Attestation.reported_by`` **equals that forecaster's
    own ``name``**" — which is never a vendor (ADR-0344 §7, ADR-0260 §5:6).
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.records
    for record in outcome.records:
        assert record.provenance.confidence == pytest.approx(0.9)
        assert record.provenance.derived_from_external is False
        assert record.placement == Placement()
        assert record.provenance.source is MemorySource.EXTERNAL
        attestation = record.provenance.attestation
        assert attestation is not None
        assert attestation.reported_by == subject.forecaster.name
        assert attestation.reported_by == FORECAST_SOURCE_NAME


async def test_a_channel_that_could_not_be_opened_is_a_transport_failure() -> None:
    """ADR-0260 §4: ``TRANSPORT_FAILED`` is a statement about this system's own reach.

    "A refused connection, a TLS failure, a channel closed mid-response — and never about
    what the provider said, which is ``PROVIDER_REFUSED``."
    """
    subject = await built(transport=RaisingTransport(TransportError("refused")))

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.TRANSPORT_FAILED


async def test_a_redirect_is_refused_and_is_never_a_second_request() -> None:
    """ADR-0260 §3: "One ask is one read … no implementation follows a link out of a
    response".
    """
    subject = await built(
        channels=[far_end(response(status="HTTP/1.1 302 Found", headers=["Location: /elsewhere"]))]
    )

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.TRANSPORT_FAILED
    assert len(subject.transport.attempts) == 1


# --- ADR-0260 §13's arm (c): the bound, the checks and the cancellation ------


async def test_the_timeout_keyword_is_required() -> None:
    """§13's arm (c): "``read``'s ``timeout`` is **required with no default**, so
    omitting it is a ``TypeError``".

    There is no spelling here for an unbounded call, which is ADR-0241 §1's whole claim
    about this seam.
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject))

    with pytest.raises(TypeError):
        await subject.forecaster.read(call)


@pytest.mark.parametrize(
    "bound",
    [
        pytest.param(30, id="not-a-timedelta"),
        pytest.param(None, id="none"),
        pytest.param(timedelta(0), id="zero"),
        pytest.param(timedelta(seconds=-1), id="negative"),
    ],
)
async def test_a_bound_outside_its_domain_reaches_nothing(bound: object) -> None:
    """§13's arm (c): refused "**before** the call is revalidated, before any credential
    is read and before any channel is opened, asserted over those three orderings".

    The forecaster reads no credential, so the second ordering is asserted as ADR-0344
    §9 restates it: before the connection record is read. **Zero cannot pass as an
    instant expiry**, which is the clause the three orderings exist for: an
    implementation reading "expired" as "do not call" would be promising something the
    event loop does not keep, and one that accepted the value and then expired would have
    read the record for a call it never made.
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject))

    with pytest.raises(ValueError, match=r"timeout|deadline"):
        await subject.forecaster.read(call, timeout=bound)

    assert subject.records.reads == []
    assert subject.transport.attempts == ()


async def test_a_call_mutated_after_construction_does_not_survive_revalidation() -> None:
    """§6's first check: "The ``ToolCall`` is **revalidated and detached**".

    "So a mutation landed after construction cannot survive into the read."
    ``ToolCall``'s own validator runs at construction and ``object.__setattr__`` defeats
    ``frozen=True``, so a call whose arguments were rewritten afterwards is exactly the
    shape this check exists for — and an implementation trusting the construction-time
    validator fails here.
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject))
    rewritten = call.request.model_copy(update={"parameters": {"origin": "https://elsewhere"}})
    call.__dict__["request"] = rewritten

    with pytest.raises(ToolBindingError):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.records.reads == []
    assert subject.transport.attempts == ()


async def test_a_call_naming_another_declaration_is_refused() -> None:
    """§6's second check, and §13's arm (c) says what makes it load-bearing.

    "One whose definition is not the forecaster's own registered declaration, **which
    ``authorises`` would otherwise pass**": the decision is recorded *for* that
    declaration, so the third check answers ``True`` and only the comparison against the
    forecaster's own registered original refuses it. ADR-0029 §2 puts the registry's
    original here; this integration has an egress registration and no registry entry, so
    the forecaster's own held copy stands in that place.
    """
    subject = await built(channels=[answering(day())])
    # **A valid but different definition**, and the id is deliberately unchanged: a
    # different id would be refused by the binding seam as mis-registered, which is a
    # different check in a different place. What this reaches is a declaration tampered
    # into a still-valid state — ADR-0018 §4's case — whose `discloses`, `cost` or
    # `risk_level` the policy never ruled on.
    weakened = FORECAST_READ.model_copy(update={"description": "a description nobody registered"})
    call = await authorised_read(subject.trail, await request(subject, tool=weakened))

    with pytest.raises(ToolBindingError, match="not the one this forecaster registered"):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.records.reads == []
    assert subject.transport.attempts == ()


async def test_a_call_whose_decision_authorises_another_request_is_refused() -> None:
    """§6's third check: ``authorises`` is **re-evaluated** against the detached copy.

    Rather than trusted from construction. The decision here was recorded over one
    request and the call carries another — the substitution ADR-0029 §2's third check
    exists for, where every record still reads as consistent and the thing about to run
    is not the thing that was authorised.

    **Which of the three catches it is the seam's stated order and not this case's
    choice.** ``revalidated_call`` rebuilds the call through ``ToolCall``'s own
    validator, which runs ``authorises`` itself, so a ``__dict__`` write reaching this
    shape is refused at check one and the explicit re-evaluation stands behind it —
    ADR-0029 §2's ordering, and the reason ``revalidated_call`` gives for it: a mutated
    ``parameters`` can hold a value whose digest would raise, so checking authorisation
    first would raise a serialisation error out of a method whose contract is to answer
    a question. What the arm asserts is the outcome the ordering exists for: refused, and
    **the connection record unread and no channel opened** (ADR-0344 §9).
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject))
    call.__dict__["request"] = await request(subject, latitude=0.0, longitude=0.0)

    with pytest.raises(ToolBindingError, match="not the call that was authorised"):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.records.reads == []
    assert subject.transport.attempts == ()


async def test_a_separately_authorised_call_naming_another_place_reads_that_place() -> None:
    """ADR-0364 §12:2-§12:3: the coordinates are planning's, and what the call sends.

    **The call here is entirely valid**: a fresh request carrying this forecaster's own
    declaration and origin with other coordinates, with its **own** recorded ``ALLOW``.
    The coordinates are no longer pinned to the configured place (§12:2 replaces ADR-0260
    §3:2's *none is accepted from one*), so the read asks about the place the call names,
    and still of the one configured provider alone (§12:3).
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject, latitude=0.0, longitude=0.0))

    await subject.forecaster.read(call, timeout=_BOUND)

    assert b"/v1/forecast?latitude=0.0&longitude=0.0" in _sent(subject)
    assert len(subject.transport.attempts) == 1


@pytest.mark.parametrize(
    "elsewhere",
    [
        pytest.param(elsewhere_account(reference="another-account"), id="another-connection"),
        pytest.param({"transport_endpoint": "https://elsewhere.invalid"}, id="another-endpoint"),
    ],
)
async def test_a_call_bound_elsewhere_reaches_no_record(elsewhere: dict[str, Any]) -> None:
    """ADR-0148 §6 at the seam: a call this integration is not the registration for.

    Refused **before** the record is read, because the record is read *by the
    registration's* reference: without the comparison, a binding for account B's
    connection is checked against account A's record, both record checks pass where the
    two share an identity, and the request goes out under A's connection although the
    approval named B.
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject, elsewhere=elsewhere))

    with pytest.raises(TransportPinError):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.records.reads == []
    assert subject.transport.attempts == ()


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        # A keyless entry is `ACTIVE` by construction (ADR-0325 §3), so the pending record
        # an unconnectable reference carries is a credentialed act's that never finished
        # — refused for its state, which the keyless read judges first.
        pytest.param(entry(state=ProvisioningState.PENDING), "pending", id="not-connectable"),
        pytest.param(
            entry(identity="someone.else@example.invalid", slot=None),
            "identity",
            id="other-identity",
        ),
        pytest.param(None, "absent", id="no-record"),
    ],
)
async def test_adr_0148_s_conditions_refuse_before_a_byte_is_transmitted(
    record: Any, reason: str
) -> None:
    """ADR-0344 §3:5: the keyless refusals against the one read are ``PROVIDER_REFUSED``.

    "A reference that is not connectable, a recorded identity other than the bound one,
    and a record that names a credential slot. Each is returned as ``PROVIDER_REFUSED``
    before any byte is transmitted." The slot is
    :func:`test_a_record_naming_a_slot_is_refused_with_no_channel_opened`'s; the other
    two are here, each over the record read exactly once.

    **They are returned where §6's three checks raise**, which is the discrimination
    §13's arm (c) insists on: those raise because *the thing about to run is not the
    thing that was authorised*, where these fire on a call that was and stayed exactly
    that and whose **connection record moved beneath it**.
    """
    del reason
    subject = await built(channels=[answering(day())], records=Records(record))

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()
    assert subject.records.reads == [REFERENCE]


async def test_a_cancelled_read_re_raises_and_yields_no_outcome() -> None:
    """§13's arm (c): "cancelled from outside while suspended, re-raises
    ``CancelledError``".

    "It yields no ``ForecastOutcome``, no ``ForecastRefusal``, and in particular no
    ``DEADLINE_EXPIRED``, which is ``read``'s **own** expiry and never an outer one"
    (ADR-0241 §4). This is the place a conforming-looking implementation could satisfy
    every other clause and still get it wrong — by catching broadly around its provider
    call and returning ``TRANSPORT_FAILED`` for a shutdown that was working correctly.
    """
    transport = GatedTransport(answering(day()))
    subject = await built(transport=transport)
    call = await authorised_read(subject.trail, await request(subject))
    gate = transport.suspend_next()
    running = asyncio.ensure_future(subject.forecaster.read(call, timeout=_BOUND))
    await gate.reached()

    running.cancel()
    gate.release()

    with pytest.raises(asyncio.CancelledError):
        await running


async def test_a_transport_that_absorbs_the_cancellation_still_delivers_it() -> None:
    """ADR-0060 §1: "a method never absorbs one", however the collaborator behaves.

    A transport that catches the task's own cancellation and answers anyway leaves the
    frame holding a value and no exception — and returning it would answer a cancelled
    turn with a result. The count ADR-0031 §2 keeps is the only surviving record that the
    cancellation was delivered, and it is read as a delta from a baseline taken on entry
    so that a caller's earlier, unrelated cancellation does not fail this call.
    """
    transport = AbsorbingTransport(3600.0, answering(day()))
    subject = await built(transport=transport)
    call = await authorised_read(subject.trail, await request(subject))
    running = asyncio.ensure_future(subject.forecaster.read(call, timeout=_BOUND))
    # Cancelled once the open has demonstrably been reached: the ledger claim is awaited
    # first (ADR-0324 §5:8), so a fixed count of yields would cancel ahead of the
    # transport. `settle` yields in turns rather than for a duration.
    await settle()
    assert transport.attempts, "the open was reached before the cancellation"

    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running
    assert transport.absorbed == 1
    # The claim was completed on the way past, with the declaration's interrupted
    # outcome (ADR-0192 §3).
    completions = [
        row.invocation
        for row in await subject.trail.export_invocations()
        if row.invocation.completes is not None
    ]
    assert [row.outcome for row in completions] == [FORECAST_READ.interrupted_outcome]


async def test_a_transport_that_invents_a_cancellation_raises_a_fault() -> None:
    """ADR-0031 §2 through ADR-0241 §7: a cancellation with nothing cancelled is a fault.

    "Not a teardown that ends the turn, and not an outcome." It leaves as an
    ``AssistantError``, which is what reaches ADR-0226 §5's degradation — where letting
    the ``CancelledError`` out would tear down a turn nobody cancelled.
    """
    subject = await built(transport=RaisingTransport(asyncio.CancelledError()))
    call = await authorised_read(subject.trail, await request(subject))

    with pytest.raises(ToolError, match="nothing cancelled"):
        await subject.forecaster.read(call, timeout=_BOUND)


# --- ADR-0260 §13's arm (i): the deadline, and one ask is one read -----------


async def test_a_read_held_past_a_positive_bound_returns_an_expiry() -> None:
    """§13's arm (i): the case that separates a seam enforcing its own deadline from one
    that merely accepts the keyword.

    "A production forecaster whose exchange is suspended past a **positive** ``timeout``
    **returns** ``DEADLINE_EXPIRED``, raises no ``CancelledError`` outward, opens no
    second channel, and does not report ``TRANSPORT_FAILED``." Arm (c) asserts what an
    *invalid* timeout refuses; this asserts what a valid one does.
    """
    transport = StallingTransport()
    subject = await built(transport=transport)

    outcome = await _read(subject, timeout=_SHORT)

    assert outcome.refusal is ForecastRefusal.DEADLINE_EXPIRED
    assert outcome.records == ()
    assert len(transport.attempts) == 1


@pytest.mark.parametrize("member", list(ForecastRefusal))
async def test_one_ask_issues_at_most_one_request_on_every_terminal_outcome(
    member: ForecastRefusal,
) -> None:
    """§13's arm (i): §3's *one ask is one read*, "**enumerated exhaustively** over
    ``ForecastRefusal``".

    "Each issuing **at most one** provider request and opening **at most one** channel
    before returning: **exactly one** wherever the outcome was read off the wire, and
    **none** for §6's ADR-0148 §6 refusal, which reaches ``PROVIDER_REFUSED`` before any
    byte is transmitted."

    Without it an implementation may retry after any of them, return the same outcome
    from the second exchange, and satisfy every disposition, contact and statement arm
    while contacting the provider twice against a clause §3 states absolutely. The
    enumeration is exhaustive rather than a chosen few, so a seventh member added without
    this assertion fails the arm.
    """
    subject, opens = await _arranged_for(member)

    outcome = await _read(
        subject, timeout=_SHORT if member is ForecastRefusal.DEADLINE_EXPIRED else _BOUND
    )

    assert outcome.refusal is member
    assert opens() <= 1
    if member is ForecastRefusal.PROVIDER_REFUSED:
        # This arrangement is ADR-0148 §6's pre-transmit refusal, which §13's arm (i)
        # singles out as the one that opens **none**.
        assert opens() == 0
    else:
        assert opens() == 1


async def _arranged_for(member: ForecastRefusal) -> tuple[Built, Any]:
    """A subject that answers ``member``, and a reader of how many channels it opened.

    One arrangement per member, chosen so that each reaches its class the way a provider
    would rather than by being scripted into it — which is what makes the count an
    assertion about the seam rather than about a double.

    Args:
        member: The class to reach.

    Returns:
        The subject and a callable answering how many opens it performed.
    """
    if member is ForecastRefusal.DEADLINE_EXPIRED:
        stalling = StallingTransport()
        return await built(transport=stalling), lambda: len(stalling.attempts)
    if member is ForecastRefusal.TRANSPORT_FAILED:
        raising = RaisingTransport(TransportError("refused"))
        return await built(transport=raising), lambda: len(raising.attempts)
    if member is ForecastRefusal.PROVIDER_REFUSED:
        # The keyless read's own limb: an unconnectable record, refused before the send.
        subject = await built(channels=[answering(day())], records=Records(None))
        return subject, lambda: len(subject.transport.attempts)
    channels = {
        ForecastRefusal.RESPONSE_TOO_LARGE: far_end(response(payload=body(day()))),
        ForecastRefusal.UNATTESTED: answering(day(), date=None),
        ForecastRefusal.NO_RESULT: far_end(response(payload=body(group=False))),
    }[member]
    bytes_bound = 1 if member is ForecastRefusal.RESPONSE_TOO_LARGE else 64 * 1024
    subject = await built(channels=[channels], max_response_bytes=bytes_bound)
    return subject, lambda: len(subject.transport.attempts)


# --- the declaration, and what it is registered in --------------------------


def test_the_declaration_declares_what_one_read_does() -> None:
    """ADR-0016 §1: "Every field that a permission decision depends on is required".

    Pinned by value, because each of these is a claim the policy rules on: a
    ``discloses`` narrowed, a ``risk_level`` or ``reversibility`` restated to make a read
    reachable, or a ``cost`` declared ``FREE`` where the figure is not known are each the
    mis-declaration ADR-0016 §1 and ADR-0148 §2 refuse.
    """
    assert FORECAST_READ.id == FORECAST_READ_ID
    assert FORECAST_READ.side_effecting is True
    assert FORECAST_READ.cost.basis.value == "unknown"
    assert [tier.value for tier in FORECAST_READ.discloses] == ["personal"]
    assert FORECAST_READ.reads == ()
    assert FORECAST_READ.writes == ()


def test_the_declaration_names_the_origin_and_the_coordinate_and_nothing_else() -> None:
    """ADR-0152 §3, ADR-0148 §8: the origin bears the destination keyword.

    Without it the binding seam derives no canonical destination set and ADR-0148 §8's
    third floor refuses an ``ALLOW`` — so this is the declaration clause the whole ruling
    path depends on. The coordinate arguments bear **no** destination keyword and the
    ``personal`` tier: they select no recipient, and ADR-0146 §5 gives the tier to a field
    every value of which carries one.
    """
    properties = FORECAST_READ.parameters_schema["properties"]
    assert isinstance(properties, Mapping)
    assert set(properties) == {"origin", "latitude", "longitude"}
    origin = properties["origin"]
    assert isinstance(origin, Mapping)
    assert origin["x-egress-destination"] == "https"
    assert origin["x-egress-tier"] == "operational"
    for name in ("latitude", "longitude"):
        coordinate = properties[name]
        assert isinstance(coordinate, Mapping)
        assert "x-egress-destination" not in coordinate
        assert coordinate["x-egress-tier"] == "personal"
    assert FORECAST_READ.parameters_schema["additionalProperties"] is False


async def test_a_request_carries_the_declaration_and_the_configured_place() -> None:
    """§4: the proposal, carrying "the arguments its own registered schema declares".

    And ``None`` for ``egress_binding``: the binding is derived by ``EgressBinder``
    and accepted from nobody.
    """
    subject = await built(channels=[answering(day())])

    proposal = await subject.forecaster.request()

    assert proposal is not None
    assert proposal.tool == FORECAST_READ
    assert dict(proposal.parameters) == {
        "origin": ORIGIN,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
    }
    assert proposal.egress_binding is None


async def test_a_configured_per_call_figure_reaches_the_registered_declaration() -> None:
    """ADR-0236 §1 through ADR-0260 §11: the pair becomes a ``PER_CALL`` cost here.

    **On a declaration built per registration rather than by editing the module
    constant**: a permission decision is recorded against the definition that was in
    force, so a shared constant whose ``cost`` was rewritten at start-up would be the back
    door ADR-0016 §1's ``frozen=True`` argument names.
    """
    subject = await built(
        channels=[answering(day())], cost_per_call=Decimal("0.002"), cost_currency="EUR"
    )

    assert subject.declaration.cost.basis.value == "per_call"
    assert subject.declaration.cost.amount == Decimal("0.002")
    assert subject.declaration.cost.currency == "EUR"
    assert FORECAST_READ.cost.basis.value == "unknown"


# --- the constructor's own domain (ADR-0260 §11) ----------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("max_days", 0, id="days-zero"),
        pytest.param("max_days", 4, id="days-above-the-ceiling"),
        pytest.param("max_days", True, id="days-a-flag"),
        pytest.param("max_day_chars", 0, id="chars-zero"),
        pytest.param("latitude", 90.1, id="latitude-out-of-range"),
        pytest.param("latitude", float("nan"), id="latitude-nan"),
        pytest.param("longitude", -180.1, id="longitude-out-of-range"),
        pytest.param("longitude", float("inf"), id="longitude-infinite"),
        # The type is refused first, so the value reaching the message is anything at
        # all: a bound that will not describe itself must still earn the `ValueError`
        # this constructor documents, and not whatever its `__repr__` threw.
        pytest.param("max_days", CannotDescribeItself(), id="days-a-value-whose-repr-raises"),
    ],
)
async def test_a_forecaster_is_refused_where_it_is_configured(field: str, value: Any) -> None:
    """§11's domain restated at the one place a forecaster is built without ``Settings``.

    Which is ADR-0236 §2's posture one field pair over: "the domain is enforced twice,
    deliberately, and the two statements are of one rule". A state this forecaster could
    not act from is refused where it is configured rather than at an arbitrary later
    call, which is the one thing ADR-0260 §4 says never leaves either member.
    """
    subject = await built(channels=[answering(day())])
    fields: dict[str, Any] = {
        "transport": subject.seam,
        "ledger": subject.trail,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "max_days": MAX_DAYS,
        "max_day_chars": 2048,
        field: value,
    }

    with pytest.raises(ValueError, match=field):
        ForecastEgress(**fields)


@pytest.mark.parametrize(
    "enormous",
    [
        pytest.param(10**10000, id="too-large-to-be-a-float"),
        pytest.param(-(10**10000), id="too-small-to-be-a-float"),
    ],
)
async def test_a_coordinate_too_large_to_be_a_float_is_refused_as_a_value_error(
    enormous: int,
) -> None:
    """The class a caller is told to catch is the class it gets.

    ``float(10**10000)`` raises ``OverflowError``, which is **not** a ``ValueError`` —
    so a caller catching the configuration error this constructor documents would meet
    an exception it never declared, and the same value arriving in a call's parameters
    would reach :meth:`ForecastEgress.read` as a fault where a refusal belongs. A JSON
    body can carry an integer of any size, so this is a value a *provider* can produce
    and not only a mis-wired composition root.
    """
    subject = await built(channels=[answering(day())])

    with pytest.raises(ValueError, match="latitude"):
        ForecastEgress(
            transport=subject.seam,
            ledger=subject.trail,
            latitude=enormous,
            longitude=LONGITUDE,
            max_days=MAX_DAYS,
            max_day_chars=2048,
        )


@pytest.mark.parametrize("name", ["", "   ", " forecast ", "forecast "])
async def test_a_forecaster_named_something_identifier_would_strip_is_refused(
    name: str,
) -> None:
    """§4: ``name`` is "a value ``Identifier`` accepts unchanged".

    §5 requires this value and a minted record's ``reported_by`` to be **equal**, and
    ``reported_by`` is typed ``Identifier``, which refuses a blank value *and strips the
    one it accepts* — so a forecaster named ``" forecast "`` would be conforming by every
    other clause and would mint a record no equality this ADR asserts could hold. The
    refusal is at construction, far from that mint.
    """
    subject = await built(channels=[answering(day())])

    with pytest.raises(ValueError, match="name"):
        ForecastEgress(
            transport=subject.seam,
            ledger=subject.trail,
            latitude=LATITUDE,
            longitude=LONGITUDE,
            max_days=MAX_DAYS,
            max_day_chars=2048,
            name=name,
        )


async def test_the_production_forecaster_conforms_to_the_protocol() -> None:
    """Golden rule 1: what ``orchestration`` will hold is the Protocol, not this class.

    Asserted over an *instance*, because ``Forecaster`` carries a non-method member —
    ``name`` is a property — and a runtime-checkable Protocol with one supports
    ``isinstance`` and not ``issubclass``.
    """
    subject = await built(channels=[answering(day())])

    assert isinstance(subject.forecaster, Forecaster)


# --------------------------------------------------------------------------- #
# the shared conformance suite, over the production forecaster (ADR-0260 §12)
# --------------------------------------------------------------------------- #


class TestForecastEgressContract(ForecasterContract):
    """``ForecastEgress`` against the shared suite (ADR-0260 §12).

    Every subject below is the *real* forecaster over a scripted far end, so what the
    suite drives is the production order — the bound, ADR-0029 §2's three checks and the
    keyless connection's one record read (ADR-0325 §2:5) — and not a stand-in for it.
    """

    #: ADR-0260 §12: ``app/composition.py`` constructs a forecaster only where a
    #: provider is configured, so this implementation has no unconfigured state to
    #: exhibit. See the suite's own note for why the two §4 clauses agree.
    constructed_only_with_a_provider = True

    @pytest.fixture
    async def forecaster(self) -> Any:
        subject = await built(channels=[answering(day())])
        return subject.forecaster

    def days_bound(self) -> int:
        return MAX_DAYS

    def content_bound(self) -> int:
        return _SMALL_CONTENT_BOUND

    async def reading(self, days: int) -> ScriptedRead:
        # Distinct, short contents: distinct so an implementation minting one record per
        # day and one minting the same record twice are told apart, and short so that
        # none of them meets the small content bound this harness configures.
        rows = [
            day(
                date=f"2026-09-{5 + index:02d}",
                weather_code=f"{index}",
                temperature_2m_min=f"{index}.0",
                temperature_2m_max=f"1{index}.0",
            )
            for index in range(days)
        ]
        forecaster, call = await self._prepared(channels=[answering(*rows)])
        return ScriptedRead(forecaster=forecaster, call=call)

    async def naming_one_day_twice(self) -> ScriptedRead:
        # Two well-formed positions of the documented table naming one day between
        # them, and nothing else: each would be minted alone — distinct contents, both
        # inside the small content bound — so what drops them is only that the response
        # named their day twice.
        rows = [
            day(date="2026-09-05", weather_code="0"),
            day(date="2026-09-05", weather_code="1"),
        ]
        forecaster, call = await self._prepared(channels=[answering(*rows)])
        return ScriptedRead(forecaster=forecaster, call=call)

    async def refusing(self, refusal: ForecastRefusal) -> ScriptedRefusal:
        forecaster, call = await self._refusing(refusal)
        # ADR-0241 §4's member is the one a *bound* reaches rather than a script, so the
        # arrangement below stalls the transport and this hook names the bound that
        # expires against it. Every other member fits inside the suite's own.
        timeout = _EXPIRING if refusal is ForecastRefusal.DEADLINE_EXPIRED else _BOUND
        return ScriptedRefusal(forecaster=forecaster, call=call, timeout=timeout)

    async def gated(self) -> GatedRead:
        transport = GatedTransport(answering(day()))
        forecaster, call = await self._prepared(transport=transport)
        return GatedRead(forecaster=forecaster, call=call, arm=transport.suspend_next)

    async def another_declaration(self) -> ScriptedRead:
        # **Bound by the real seam**, which the shared id makes possible: the
        # registration is found, the binding is derived for the same origin, and only
        # the declaration's own text differs — so every check but the second passes.
        subject = await built(max_day_chars=_SMALL_CONTENT_BOUND, channels=[answering(day())])
        weakened = FORECAST_READ.model_copy(update={"description": "nobody registered this"})
        proposal = await request(subject, tool=weakened)
        return ScriptedRead(
            forecaster=subject.forecaster, call=await authorised_read(subject.trail, proposal)
        )

    async def configured(self) -> ConfiguredProvider:
        forecaster, _ = await self._prepared(channels=[answering(day())])
        return ConfiguredProvider(
            forecaster=forecaster,
            origin=ORIGIN,
            latitude=LATITUDE,
            longitude=LONGITUDE,
            declaration=FORECAST_READ,
        )

    async def unconfigured(self) -> Any:  # pragma: no cover — see the flag
        raise NotImplementedError

    async def _prepared(self, **arrangement: Any) -> tuple[Any, ToolCall]:
        """A subject and the authorised call that reaches its scripted answer.

        Args:
            arrangement: Passed straight to ``forecast_harness.built``.

        Returns:
            The forecaster and the call.
        """
        subject = await built(max_day_chars=_SMALL_CONTENT_BOUND, **arrangement)
        return subject.forecaster, await authorised_read(subject.trail, await request(subject))

    async def _refusing(self, refusal: ForecastRefusal) -> tuple[Any, ToolCall]:
        """A subject whose read refuses with ``refusal``, and the call that reaches it.

        Every one is driven from a *real* cause rather than from a switch: a transport
        that will not connect, a stall against a real bound, a record the store no longer
        holds, a bound of one octet, a response with no ``Date``, and a response
        describing no day. That is what makes ADR-0260 §4's "raises for no source reason"
        an assertion about this forecaster rather than about a stub.

        Args:
            refusal: The class to reach.

        Returns:
            The forecaster and the call.
        """
        arrangements: dict[ForecastRefusal, dict[str, Any]] = {
            ForecastRefusal.TRANSPORT_FAILED: {
                "refusal": TransportError("this file connects to nothing")
            },
            # A **real** stall and a real bound, not a scripted class: §13's arm (i)
            # asks for an exchange suspended past a positive timeout, so the member the
            # suite parametrises over is reached the way a deployment reaches it.
            ForecastRefusal.DEADLINE_EXPIRED: {"transport": StallingTransport()},
            # ADR-0148 §6's own limb, which §13's arm (i) singles out as the one that
            # opens no channel at all.
            ForecastRefusal.PROVIDER_REFUSED: {
                "channels": [answering(day())],
                "records": Records(None),
            },
            ForecastRefusal.RESPONSE_TOO_LARGE: {
                "channels": [answering(day())],
                "max_response_bytes": 1,
            },
            ForecastRefusal.UNATTESTED: {"channels": [answering(day(), date=None)]},
            ForecastRefusal.NO_RESULT: {"channels": [far_end(response(payload=body(group=False)))]},
        }
        return await self._prepared(**arrangements[refusal])


# --- ADR-0324 §5:8: the weather pull's ledger claim and completion ---------------------


async def _rows(subject: Built) -> tuple[list[ToolInvocation], list[ToolInvocation]]:
    """The ledger's claims and its completions, in order."""
    rows = [row.invocation for row in await subject.trail.export_invocations()]
    return (
        [row for row in rows if row.completes is None],
        [row for row in rows if row.completes is not None],
    )


async def test_a_read_leaves_one_claim_taken_from_its_decision_and_completed_succeeded() -> None:
    """ADR-0324 §5:8, ADR-0306 §5:7: the attempt and its outcome are the ledger's rows.

    One claim, taken from the recorded decision, and one completion of it, as the
    searcher's are; the call's ``SUCCEEDED`` is what the read did, and the records are
    what it brought back.
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.records
    claims, completions = await _rows(subject)
    assert [row.decision_id for row in claims] == ["d-forecast-1"]
    assert [row.completes for row in completions] == [claims[0].id]
    assert completions[0].outcome is ToolOutcome.SUCCEEDED


@pytest.mark.parametrize(
    ("arrangement", "expected"),
    [
        pytest.param(
            {"refusal": TransportError("this file connects to nothing")},
            ToolOutcome.FAILED,
            id="a-transport-failure-completes-failed",
        ),
        pytest.param(
            {"channels": [far_end(response(status="HTTP/1.1 400 Bad Request"))]},
            ToolOutcome.FAILED,
            id="a-provider-refusal-completes-failed",
        ),
        pytest.param(
            {"channels": [far_end(response(payload=body(group=False)))]},
            ToolOutcome.SUCCEEDED,
            id="an-answer-describing-no-day-completes-succeeded",
        ),
        pytest.param(
            {"channels": [answering(day(), date=None)]},
            ToolOutcome.SUCCEEDED,
            id="an-unattested-answer-completes-succeeded",
        ),
    ],
)
async def test_the_completion_says_what_happened_to_the_call_and_not_to_the_forecast(
    arrangement: dict[str, Any], expected: ToolOutcome
) -> None:
    """The split ``_result_of`` states: an answer the provider *gave* completed the call.

    ``NO_RESULT`` and ``UNATTESTED`` are the provider answering, so the row says
    ``SUCCEEDED`` while the read yields nothing; a call that did not complete as a call
    says ``FAILED``. The searcher's split, one integration along.
    """
    subject = await built(**arrangement)

    await _read(subject)

    claims, completions = await _rows(subject)
    assert len(claims) == 1
    assert [row.outcome for row in completions] == [expected]


async def test_a_read_cut_short_by_its_deadline_completes_unknown_at_an_unknown_cost() -> None:
    """ADR-0324 §8:1 and ADR-0241 §5: the outcome is the declaration's ``interrupted_outcome``.

    A read cut short may have reached the provider, so its completion says unknown, and
    its cost is what nothing measured, never the declared figure.
    """
    subject = await built(transport=StallingTransport())

    outcome = await _read(subject, timeout=_SHORT)

    assert outcome.refusal is ForecastRefusal.DEADLINE_EXPIRED
    claims, completions = await _rows(subject)
    assert len(claims) == 1
    assert [row.outcome for row in completions] == [ToolOutcome.INDETERMINATE]
    assert FORECAST_READ.interrupted_outcome is ToolOutcome.INDETERMINATE
    assert completions[0].incurred_cost is not None
    assert completions[0].incurred_cost.basis is CostBasis.UNKNOWN


async def test_a_call_that_is_not_the_one_authorised_appends_no_claim() -> None:
    """ADR-0192 §1's placement: the three checks come before the claim.

    So a call refused at them leaves no row at all, as it opens no channel.
    """
    subject = await built(channels=[answering(day())])
    call = await authorised_read(subject.trail, await request(subject))
    # Another request than the one authorised: revalidation refuses it.
    call.__dict__["request"] = await request(subject, latitude=0.0, longitude=0.0)

    with pytest.raises(ToolBindingError, match="not the call that was authorised"):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert await subject.trail.export_invocations() == []
    assert subject.transport.attempts == ()


async def test_a_call_whose_decision_was_never_recorded_is_refused_before_the_send() -> None:
    """ADR-0192 §1: the ledger requires the decision the trail holds under its id.

    A forecast read is the recorded decision's to claim (ADR-0306 §5:7), so one carrying
    a decision the trail never recorded is refused at the claim and nothing is sent.
    """
    subject = await built(channels=[answering(day())])
    proposal = await request(subject)
    decision = PermissionDecision.from_request(
        proposal,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="never recorded"),
        id="d-unrecorded",
        decided_at=DECIDED_AT,
    )
    call = ToolCall(request=proposal, decision=decision)

    with pytest.raises(UnrecordedAuthorisationError):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.transport.attempts == ()


@pytest.mark.parametrize(
    ("refusal", "outcome", "kind"),
    [
        (ForecastRefusal.NO_RESULT, ToolOutcome.SUCCEEDED, None),
        (ForecastRefusal.UNATTESTED, ToolOutcome.SUCCEEDED, None),
        (ForecastRefusal.DEADLINE_EXPIRED, ToolOutcome.INDETERMINATE, ToolFailureKind.TIMED_OUT),
        (ForecastRefusal.TRANSPORT_FAILED, ToolOutcome.FAILED, ToolFailureKind.UNAVAILABLE),
        (ForecastRefusal.PROVIDER_REFUSED, ToolOutcome.FAILED, ToolFailureKind.REFUSED),
        (ForecastRefusal.RESPONSE_TOO_LARGE, ToolOutcome.FAILED, ToolFailureKind.REFUSED),
    ],
)
def test_every_refusal_completes_with_the_outcome_the_pull_reports(
    refusal: ForecastRefusal, outcome: ToolOutcome, kind: ToolFailureKind | None
) -> None:
    """ADR-0306 §5:8: the completion's outcome, over every ``ForecastRefusal`` member.

    The same table ``orchestration``'s tests pin for the result acting writes an
    approved call's effect record from, so the ledger row and the effect record give
    one answer (ADR-0321 §4:10).
    """
    result = _result_of(ForecastOutcome(refusal=refusal), FORECAST_READ, _BOUND)

    assert result.outcome is outcome
    assert (None if result.failure is None else result.failure.kind) is kind
