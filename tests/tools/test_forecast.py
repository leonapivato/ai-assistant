"""ADR-0260's forecast seam, over the production forecaster.

§13's arms marked L1, less the two its preamble puts elsewhere: arm (a) is at the
``ReadAsk`` model and arm (j) at ``ForecastOutcome``, both in ``tests/core/``, because
what they assert is a *type*'s refusal. Everything here has a production
:class:`~ai_assistant.tools.forecast.ForecastEgress` as its subject, which is what §13's
preamble requires — "the subject is the production type or component", with exactly one
assertion admitted over the canonical fake, and that one is in
``tests/tools/test_fake_forecaster.py``.

**The far end is a scripted channel and never a network**, which is the harness's
property rather than this file's: the exchange takes the outbound-transport capability
as a required argument, so an arrangement that forgot to pass one would not construct.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from egress_transport_harness import Records, entry
from forecast_harness import (
    LATITUDE,
    LONGITUDE,
    MAX_DAYS,
    ORIGIN,
    REPORTED_AT,
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
    suspendable,
)
from forecaster_contract import (
    ConfiguredProvider,
    ForecasterContract,
    GatedRead,
    ScriptedRead,
    ScriptedRefusal,
)

from ai_assistant.core.errors import ToolBindingError, ToolError, TransportError
from ai_assistant.core.protocols import Forecaster
from ai_assistant.core.types import (
    ForecastRefusal,
    MemorySource,
    Placement,
    ProvisioningState,
    SemanticMemory,
    ToolCall,
)
from ai_assistant.tools.egress import TransportPinError
from ai_assistant.tools.forecast import (
    FORECAST_READ,
    FORECAST_READ_ID,
    FORECAST_SOURCE_NAME,
    ForecastEgress,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ForecastOutcome

#: The bound every case passes unless it is about the bound.
_BOUND: Final = timedelta(seconds=30)

#: A bound small enough that a real wait past it is a fraction of a second.
_SHORT: Final = timedelta(milliseconds=50)

#: How long a case waits for a held call to answer once released.
_WAIT: Final = 5.0

#: A content bound small enough that the boundary cases script a handful of
#: characters rather than a paragraph. Nothing in the contract is a function of it.
_SMALL_CONTENT_BOUND: Final = 64

#: The bound a case sets when it wants the deadline to fire (ADR-0241 §1). Small
#: enough that the wait is a fraction of a second and large enough that a loaded
#: machine still reaches the stage under test before it expires.
_EXPIRING: Final = timedelta(milliseconds=200)

#: A clock no minted value may equal (§13's arm (b)): "In none of them does any minted
#: value equal a clock the test controls." Deliberately far from
#: :data:`~forecast_harness.REPORTED_AT`, so an implementation reading a clock of its own
#: would have to hit this value by coincidence to pass.
_OUR_CLOCK: Final = datetime(2031, 1, 1, 6, 30, tzinfo=UTC)


async def _read(subject: Built, *, timeout: timedelta = _BOUND) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this helper only forwards the caller's bound to it
    """Drive one authorised read against ``subject``.

    Args:
        subject: The configured integration.
        timeout: The caller's bound.

    Returns:
        The outcome.
    """
    call = authorised_read(await request(subject))
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
    return [record.content.split("\n", 1)[0] for record in outcome.records]


# --- ADR-0260 §13's arm (b): what the source owes, and the fallbacks not taken ---


async def test_a_dated_day_with_a_declared_offset_mints_its_own_half_open_interval() -> None:
    """§5: the extent is the day, computed from the provider's own declared values.

    "Its ends are the half-open bounds of that day, computed **from the day the provider
    named and the UTC offset the provider's own response declared for it**, and from
    nothing else — never from a clock of ours, never from a timezone database of ours,
    never from the reader's configuration, and never from the place."

    The offset is ``+01:00``, so the day begins an hour *before* UTC midnight. A reader
    that ignored the offset would produce an interval one hour off and would pass every
    assertion about the record's shape, which is why the ends are asserted by value.
    """
    subject = await built(channels=[answering(day(date="2026-09-05", utc_offset="+01:00"))])

    outcome = await _read(subject)

    assert outcome.refusal is None
    assert _extents(outcome) == [
        (
            datetime(2026, 9, 4, 23, 0, tzinfo=UTC),
            datetime(2026, 9, 5, 23, 0, tzinfo=UTC),
        )
    ]


async def test_a_minted_record_carries_a_fully_open_validity() -> None:
    """§5: "``validity`` is fully open and no lane sets it to the day the record is about".

    ADR-0045 §2 makes the envelope window "a lifecycle property of the record's life in
    the store, set operationally by the applier", and ADR-0252 §3 forbids reading it as
    coverage "on any kind, under any fallback". A producer setting it to the forecast's
    own day would be writing the source's testimony into the operational axis — the
    authorship mixing ADR-0117 §2 refuses — and would hand the prohibited fallback
    exactly the value it was written to refuse.
    """
    subject = await built(channels=[answering(day())])

    outcome = await _read(subject)

    assert outcome.records
    for record in outcome.records:
        assert record.validity.valid_from is None
        assert record.validity.valid_until is None


async def test_a_day_declaring_no_offset_mints_no_record_for_that_day() -> None:
    """§5: "A day the provider named without declaring the offset it is in declares no
    extent", and that day is dropped.

    **Dropped rather than minted with an extent this system computed**, which is the
    fail-closed direction: an extent derived from our own timezone database would be
    this system stating where the provider's entry lies, and ADR-0117 §2 makes an extent
    producer testimony.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05", utc_offset=None),
                day(date="2026-09-06", utc_offset="+01:00"),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    "unreadable",
    [
        pytest.param("Z", id="a-zulu"),
        pytest.param("+01", id="no-minutes"),
        pytest.param("+01:00:00", id="with-seconds"),
        pytest.param("+99:00", id="no-day-is-in-it"),
        pytest.param("=01:00", id="no-sign"),
        pytest.param("+0\N{FULLWIDTH DIGIT ONE}:00", id="a-non-ascii-digit"),
    ],
)
async def test_a_day_whose_offset_cannot_be_read_mints_no_record_for_that_day(
    unreadable: str,
) -> None:
    """§5: an unreadable offset is not a declared one, so the day is dropped.

    **One spelling and no other**, which this adapter pins and §5 authorises it to: "the
    field selection, their order, the separators and the omission rule are fixed by the
    implementation that reads that provider's documented format". A value the format does
    not admit is read under no rule at all rather than under a looser one — the posture
    ADR-0231 §10 takes for the obsolete HTTP date formats, one field over.

    The non-ASCII digit is the case a parser checking ``isdigit`` without ``isascii``
    would read as a number: a fullwidth digit is a digit by Unicode and ``int()``
    accepts it.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05", utc_offset=unreadable),
                day(date="2026-09-06", utc_offset="+01:00"),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    ("hours", "minutes"),
    [
        pytest.param("23", "59", id="the-widest-either-component-admits"),
        pytest.param("00", "00", id="the-narrowest"),
    ],
)
async def test_an_offset_at_its_component_bounds_is_read(hours: str, minutes: str) -> None:
    """The positive arm of the component check, so the refusals below are not vacuous.

    ``+23:59`` and ``+00:00`` are the widest and narrowest this documented format
    spells, and both are offsets a day can be in — so a check that refused either would
    be dropping days the provider described perfectly well.
    """
    subject = await built(
        channels=[answering(day(date="2026-09-05", utc_offset=f"+{hours}:{minutes}"))]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-05"]


@pytest.mark.parametrize(
    "normalising",
    [
        pytest.param("+01:99", id="minutes-past-fifty-nine"),
        pytest.param("-01:60", id="minutes-at-sixty"),
        pytest.param("+24:00", id="hours-at-twenty-four"),
        pytest.param("+99:99", id="both"),
    ],
)
async def test_an_offset_whose_components_normalise_is_not_a_declared_one(
    normalising: str,
) -> None:
    """§5: the day is dropped rather than minted at an offset the provider never stated.

    **``timedelta`` normalises, and that is the whole of this case.** ``+01:99`` becomes
    two hours and thirty-nine minutes — a well-formed, in-range offset — so an
    implementation that built the duration first and range-checked afterwards cannot
    tell it from a provider that declared ``+02:39``, and mints the day at a position
    nothing in the response states. §5 admits an extent computed "from the day the
    provider named and the UTC offset the provider's own response declared for it, and
    from nothing else"; a normalised one is neither.

    ``+24:00`` is the sibling case on the other component, and it is the one a check
    resting on ``timezone``'s own ±24-hour bound would *also* miss — ``timezone`` refuses
    it, but only after the normalisation has already merged the two fields.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05", utc_offset=normalising),
                day(date="2026-09-06", utc_offset="+01:00"),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_a_day_list_present_as_null_is_a_response_of_another_shape() -> None:
    """§5: a member the documented format does not admit is ``PROVIDER_REFUSED``.

    **Absence and ``null`` are two different operator facts**, and ``dict.get`` cannot
    tell them apart: a provider with nothing to say for the coordinate omits the member,
    where one that sent ``null`` sent a value this format does not admit. Reading the
    second as the first would report ``NO_RESULT`` — the provider answered and had
    nothing — about a response this system could not read at all.
    """
    subject = await built(channels=[far_end(response(payload=b'{"days": null}'))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


async def test_a_response_of_many_rows_is_read_in_one_pass_over_them() -> None:
    """§4's deadline covers the transcription and the minting, so the work under it is
    linear.

    A response well inside ``forecast_max_response_bytes`` can carry thousands of
    compact rows — this one does — and **no ``await`` occurs anywhere between the octets
    arriving and the records being minted**, so there is no point at which an expiry
    could be delivered while that work runs. A duplicate pass taken per row rather than
    over the days would be quadratic there: tens of millions of comparisons on the event
    loop's own thread, with the bound §4 states over "the response read and the
    transcription" unable to fire.

    What the case asserts is the outcome at that size — the cap, and §5's duplicate rule
    still holding across the whole response rather than within a window. The linearity is
    what makes the assertion return at all.
    """
    rows = [
        day(date=f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}", utc_offset="+00:00")
        for index in range(2000)
    ]
    # One day named twice, at the two ends of the response: a pass that only compared
    # neighbours, or only looked inside the cap, would keep both.
    rows.append(day(date="2026-01-01", utc_offset="+00:00", conditions="Rain"))
    subject = await built(channels=[answering(*rows)], max_response_bytes=4 * 1024 * 1024)

    outcome = await _read(subject)

    assert len(outcome.records) == MAX_DAYS
    assert _days(outcome) == ["2026-01-02", "2026-01-03", "2026-01-04"]


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"conditions": None}, id="null"),
        pytest.param({"temperature_min": 11.4}, id="a-number-not-a-string"),
        pytest.param({"temperature_max": ["19.2"]}, id="an-array"),
        pytest.param({"precipitation": True}, id="a-boolean"),
    ],
)
async def test_a_day_the_response_did_not_describe_completely_mints_its_siblings_only(
    broken: dict[str, Any],
) -> None:
    """§5: "A day the response does not describe completely is dropped whole".

    "A day for which the provider omitted a documented field, supplied it as ``null``, or
    supplied a value of a type its documented format does not admit" — and the remaining
    days are minted, which is the half an implementation that refused the whole response
    would get wrong.

    A number is the sharpest of the four: rendering ``19.2`` as ``"19.2"`` would be this
    system adding a word of its own, which §5 forbids in terms — "no word of this
    system's is added".
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05", **broken),
                day(date="2026-09-06"),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


async def test_a_day_omitting_a_documented_field_mints_its_siblings_only() -> None:
    """§5's fourth form: omitted, as distinct from supplied ``null``.

    Two states of the same clause and one outcome, which is why the harness has a
    sentinel for absence: ``None`` already means ``null``, so a case that could not
    express omission would leave one of the four forms untested.
    """
    from forecast_harness import OMITTED  # noqa: PLC0415 — one case needs the sentinel

    subject = await built(
        channels=[answering(day(date="2026-09-05", conditions=OMITTED), day(date="2026-09-06"))]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    "second",
    [
        pytest.param({}, id="rows-that-agree"),
        pytest.param({"conditions": "Rain"}, id="rows-that-conflict"),
    ],
)
async def test_a_day_the_response_names_twice_mints_no_record_and_mints_its_siblings(
    second: dict[str, Any],
) -> None:
    """§5: "A day the response names more than once is dropped in **every one of its
    rows**".

    "Whether they agree or conflict: the response has not described that day once, and
    preferring one row over another would be this system deciding what the provider
    said." **That is not a deduplication** — nothing is merged, no row is preferred, and
    ADR-0226 §7's whole-union rule at the supply is untouched.

    The agreeing case is the one an implementation would be tempted to keep: two
    identical rows describe the day consistently, and dropping them anyway is what the
    clause actually says.
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


async def test_a_duplicate_beyond_the_cap_still_drops_both_of_its_rows() -> None:
    """§13's arm (b), stated as the arm states it, with its own reason.

    "Asserted over agreeing rows and conflicting ones alike **and with the second
    occurrence placed beyond ``forecast_max_days``**, because an implementation capping
    before it looks for duplicates mints the first row and passes every arm that keeps
    the duplicate inside the cap."

    Four rows and a cap of three: the duplicate of the first day sits fourth, so an
    implementation that capped first would never see it and would mint the first row of a
    day the response described twice.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05"),
                day(date="2026-09-06"),
                day(date="2026-09-07"),
                day(date="2026-09-05", conditions="Rain"),
            )
        ],
        max_days=3,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06", "2026-09-07"]


async def test_a_response_every_day_of_which_is_dropped_yields_no_result() -> None:
    """§5: "Where every day is dropped the read yields nothing" — ``NO_RESULT``.

    Not an empty success: ``ForecastOutcome`` refuses an outcome carrying neither, and
    §8 maps this member to ``EMPTY`` rather than to a disposition, which is what makes a
    read that reached the provider and was answered a completed servicing.
    """
    subject = await built(
        channels=[answering(day(date="2026-09-05", utc_offset=None), day(conditions=None))]
    )

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT
    assert outcome.records == ()


async def test_a_response_describing_no_day_at_all_yields_no_result() -> None:
    """§5's other route to the same member: the provider answered with nothing usable.

    An absent day list is a provider with nothing to say for the coordinate, not a
    malformed shape — reading it as one would report a provider that answered perfectly
    well as one that answered something else, and the two are different operator facts.
    """
    subject = await built(channels=[far_end(response(payload=body(group=False)))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.NO_RESULT


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param(None, id="no-date-field"),
        pytest.param("Fri, 04 Sep 2026 12:00:00 UTC", id="not-gmt"),
        pytest.param("Friday, 04-Sep-26 12:00:00 GMT", id="rfc-850"),
        pytest.param("Fri Sep  4 12:00:00 2026", id="asctime"),
        pytest.param("not a date at all", id="malformed"),
    ],
)
async def test_a_response_declaring_no_readable_instant_mints_nothing(
    declared: str | None,
) -> None:
    """§5: "A response declaring **no** instant … mints **no record**" — ``UNATTESTED``.

    ADR-0092 §3 binds as written and there is **no substitute**: not the instant we sent,
    not the instant we received, not a clock this system read. "No implementation reads
    an unparseable field as licence to fall back to a clock it read", and the obsolete
    HTTP date formats land with the malformed one because RFC 9110 §5.6.7 forbids a
    sender generating them.
    """
    subject = await built(channels=[answering(day(), date=declared)])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.UNATTESTED
    assert outcome.records == ()


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


# --- ADR-0260 §13's arm (b-prime), the producer's half ----------------------


async def test_a_minted_record_carries_the_facts_the_producer_owes() -> None:
    """§13's arm (b-prime): the §5 facts ``ForecastOutcome`` cannot decide.

    "Over the **production** forecaster's own output, a minted record's ``confidence`` is
    ``0.9``, its ``derived_from_external`` is ``False``, its ``placement`` is the default
    that narrows nothing, and its ``Attestation.reported_by`` **equals that forecaster's
    own ``name``** — asserted against the configured instance's ``name`` and not merely
    against its siblings', which §4's model already enforces and which a vendor string
    stamped consistently would satisfy."
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


async def test_a_response_at_the_read_bound_is_read_and_one_past_it_is_abandoned() -> None:
    """§11: "A response **at** the bound is read and minted; a response **beyond** it is
    **abandoned and refused**, never truncated".

    The bound counts "the most octets one response may take off the channel — its status
    line and headers included — enforced *on the read itself* and before any part of it is
    parsed", which is ``search_max_response_bytes``' population word for word so that the
    two bounds mean the same thing at two seams.

    **No parse is attempted on the over-large one**, which the assertion catches by
    construction: the body is well-formed, so an implementation that buffered and then
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


async def test_a_day_at_the_content_bound_is_minted_and_one_past_it_is_dropped() -> None:
    """§5, §11: a day over ``forecast_max_day_chars`` is **dropped**, never truncated.

    "Measured as ADR-0230 §6 measures a fetched document" — on the ``json.dumps``
    rendering at its default ``ensure_ascii=True``, its two delimiters included, which is
    the rendering the prompt will carry. A ceiling on source characters would admit a day
    six or twelve times this long while claiming to admit this much (ADR-0222 §4).
    """
    row = day(date="2026-09-05")
    content = "\n".join(
        str(row[field])
        for field in ("date", "conditions", "temperature_min", "temperature_max", "precipitation")
    )
    exactly = len(json.dumps(content))

    minted = await built(channels=[answering(row)], max_day_chars=exactly)
    dropped = await built(
        channels=[answering(row, day(date="2026-09-06"))], max_day_chars=exactly - 1
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
async def test_the_cap_is_taken_over_the_survivors_and_taken_from_the_front(
    offered: int, expected: Sequence[str]
) -> None:
    """§5, §13's arm (b-prime): "the records minted are the **first** that many".

    "The last asserted over **which** days those are and over their extents rather than
    over the count alone — taking the first and taking the last both satisfy a count
    while minting different evidence." A cap that did not say which days it kept would
    let two implementations mint different evidence, and different goal outcomes, from
    one response.
    """
    rows = [day(date=f"2026-09-{5 + index:02d}") for index in range(offered)]
    subject = await built(channels=[answering(*rows)], max_days=MAX_DAYS)

    outcome = await _read(subject)

    assert _days(outcome) == list(expected)
    assert _extents(outcome)[0][0] == datetime(2026, 9, 4, 23, 0, tzinfo=UTC)


async def test_the_cap_counts_what_survived_and_not_what_the_provider_sent() -> None:
    """§13's arm (b-prime): "a response whose days exceed the figure only once an
    incomplete one has been dropped mints the **first** ``forecast_max_days`` of what
    survived".

    Four rows, one of them incomplete and first, a cap of three: an implementation that
    capped the *rows* before dropping would consider three rows, drop one, and mint two.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-04", conditions=None),
                day(date="2026-09-05"),
                day(date="2026-09-06"),
                day(date="2026-09-07"),
            )
        ],
        max_days=3,
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_the_transcription_form_is_pinned() -> None:
    """§5: "What this clause fixes is that the form is *fixed somewhere a test asserts*".

    This is that test. The field selection, their order and the separator are **this
    adapter's** and no other's — "there is no cross-implementation form, and no
    implementation conforms by matching another's output" — so what is pinned here is
    that the form does not move, not that any other provider's reader produces it.

    ``utc_offset`` is a documented field and is deliberately **not** transcribed: the
    extent already carries the position, and a raw offset in prose is noise a model would
    have to read past.
    """
    from ai_assistant.tools.forecast import _TRANSCRIBED_FIELDS  # noqa: PLC0415 — the pin

    assert _TRANSCRIBED_FIELDS == (
        "date",
        "conditions",
        "temperature_min",
        "temperature_max",
        "precipitation",
    )


async def test_a_content_is_the_provider_s_own_octets_joined_in_that_order() -> None:
    """§5: a transcription, "each rendered **as the provider's own response spelled it**".

    "The octets of the value the response carried, and never a re-rendering of a parsed
    number." The values here carry trailing zeros and a leading zero a float round-trip
    would eat, which is what makes the assertion about *transcription* rather than about
    equality of meaning.
    """
    subject = await built(
        channels=[
            answering(
                day(
                    date="2026-09-05",
                    conditions="Light rain",
                    temperature_min="09.0",
                    temperature_max="19.20",
                    precipitation="0.00",
                )
            )
        ]
    )

    outcome = await _read(subject)

    minted = outcome.records[0]
    assert isinstance(minted, SemanticMemory)
    assert minted.content == "2026-09-05\nLight rain\n09.0\n19.20\n0.00"
    assert minted.fact == minted.content


async def test_a_day_whose_transcribed_span_carries_a_line_break_is_dropped() -> None:
    """§5's verbatim rule meeting this adapter's own separator.

    The line structure is the only thing keeping the spans apart, so a break inside a
    present span would have to be altered — which would stop it being verbatim — or would
    produce a record whose lines no reader can assign to a span. Dropping is the one
    answer that keeps both properties, and it is ADR-0231 §10's rule at a second producer.
    """
    subject = await built(
        channels=[
            answering(
                day(date="2026-09-05", conditions="Clear\nthen rain"),
                day(date="2026-09-06"),
            )
        ]
    )

    outcome = await _read(subject)

    assert _days(outcome) == ["2026-09-06"]


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param(b"not json at all", id="not-json"),
        pytest.param(b'["a list"]', id="not-an-object"),
        pytest.param(b'{"days": {"not": "a list"}}', id="days-is-an-object"),
        pytest.param(b'{"days": ["not an object"]}', id="a-row-is-not-an-object"),
        pytest.param(b"\xff\xfe", id="not-utf-8"),
    ],
)
async def test_a_response_of_another_shape_is_refused_by_the_provider(malformed: bytes) -> None:
    """§5: a body the documented format does not admit is ``PROVIDER_REFUSED``.

    The provider answered — octets arrived — and what it answered is not something this
    system will read, which is a different operator fact from a channel that could not be
    opened. §10 puts this member on the **nothing-either-way** side of the contact
    partition all the same, because it carries no value separating that cause from
    ADR-0148 §6's pre-transmit refusal.
    """
    subject = await built(channels=[far_end(response(payload=malformed))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "status",
    [
        pytest.param("HTTP/1.1 204 No Content", id="no-representation"),
        pytest.param("HTTP/1.1 429 Too Many Requests", id="rate-limited"),
        pytest.param("HTTP/1.1 500 Internal Server Error", id="server-error"),
    ],
)
async def test_a_status_a_forecast_cannot_be_read_out_of_is_refused(status: str) -> None:
    """§5: one status a read is taken out of, and the rest are the provider's answer.

    A ``2xx`` that is not ``200`` carries no representation, so it is a response no day
    can be read from rather than a successful read of zero days; calling it the latter
    would report ``NO_RESULT`` where the honest answer is that the provider answered
    something else.
    """
    subject = await built(channels=[far_end(response(status=status, payload=body(day())))])

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED


async def test_a_channel_that_could_not_be_opened_is_a_transport_failure() -> None:
    """§4: ``TRANSPORT_FAILED`` is a statement about this system's own reach.

    "A refused connection, a TLS failure, a channel closed mid-response — and never about
    what the provider said, which is ``PROVIDER_REFUSED``."
    """
    subject = await built(transport=RaisingTransport(TransportError("refused")))

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.TRANSPORT_FAILED


async def test_a_redirect_is_refused_and_is_never_a_second_request() -> None:
    """§3: "One ask is one read … no implementation follows a link out of a response".

    A redirect is the one shape that would tempt a second request out of a seam whose
    whole bound is that there is exactly one, so the exchange refuses it and this seam
    reports the refusal rather than the location.
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
    call = authorised_read(await request(subject))

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

    **Zero cannot pass as an instant expiry**, which is the clause the three orderings
    exist for: an implementation reading "expired" as "do not call" would be promising
    something the event loop does not keep, and one that accepted the value and then
    expired would have read a credential for a call it never made.
    """
    subject = await built(channels=[answering(day())])
    call = authorised_read(await request(subject))

    with pytest.raises(ValueError, match=r"timeout|deadline"):
        await subject.forecaster.read(call, timeout=bound)

    assert subject.keyring.reads == []
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
    call = authorised_read(await request(subject))
    rewritten = call.request.model_copy(update={"parameters": {"origin": "https://elsewhere"}})
    call.__dict__["request"] = rewritten

    with pytest.raises(ToolBindingError):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.keyring.reads == []
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
    call = authorised_read(await request(subject, tool=weakened))

    with pytest.raises(ToolBindingError, match="not the one this forecaster registered"):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.keyring.reads == []
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
    **no credential read and no channel opened**.
    """
    subject = await built(channels=[answering(day())])
    call = authorised_read(await request(subject))
    call.__dict__["request"] = await request(subject, latitude=0.0, longitude=0.0)

    with pytest.raises(ToolBindingError, match="not the call that was authorised"):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


@pytest.mark.parametrize(
    "elsewhere",
    [
        pytest.param(elsewhere_account(reference="another-account"), id="another-connection"),
        pytest.param({"transport_endpoint": "https://elsewhere.invalid"}, id="another-endpoint"),
    ],
)
async def test_a_call_bound_elsewhere_reaches_no_credential(elsewhere: dict[str, Any]) -> None:
    """ADR-0148 §6 at the seam: a call this integration is not the registration for.

    Refused **before** the record is read, because the record is read *by the
    registration's* reference: without the comparison, a binding for account B's
    connection is checked against account A's record, both record checks pass where the
    two share an identity, and the request goes out under A's credential although the
    approval named B.
    """
    subject = await built(channels=[answering(day())])
    call = authorised_read(await request(subject, elsewhere=elsewhere))

    with pytest.raises(TransportPinError):
        await subject.forecaster.read(call, timeout=_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        pytest.param(entry(state=ProvisioningState.PENDING), "pending", id="not-connectable"),
        pytest.param(
            entry(identity="someone.else@example.invalid"), "identity", id="other-identity"
        ),
        pytest.param(None, "absent", id="no-record"),
    ],
)
async def test_adr_0148_s_conditions_refuse_before_a_byte_is_transmitted(
    record: Any, reason: str
) -> None:
    """§6: ADR-0148 §6's pre-transmit refusals are ``PROVIDER_REFUSED``, **returned**.

    "Each refuses **before any byte is transmitted**, and each yields a
    ``ForecastOutcome`` whose ``refusal`` is ``ForecastRefusal.PROVIDER_REFUSED``." That
    is what ``WebSearcher`` does with these same limbs today, and "one fault classified
    two ways at two seams is what ADR-0264 §13's third arm exists to catch".

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


async def test_a_keyring_holding_nothing_refuses_before_a_byte_is_transmitted() -> None:
    """ADR-0148 §6's fourth condition: a slot the keyring holds nothing under.

    What an interrupted provisioning act leaves behind — an active record naming a slot
    with no credential in it — and the read refuses rather than sending an unauthenticated
    request under the owner's own name.
    """
    subject = await built(channels=[answering(day())], holds=None)

    outcome = await _read(subject)

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()


async def test_a_reprovisioning_across_the_credential_read_discards_and_returns() -> None:
    """§13's arm (c): ADR-0148 §6's interleaving, "asserted **beside** them and **apart**
    from them".

    "A reprovisioning landing between the credential read and the re-read discards the
    credential, opens no channel, and **returns ``PROVIDER_REFUSED``** where the three
    **raise** — a seam answering either with the other's value passes every arm that
    tests one of them alone."
    """
    records = ReprovisioningRecords(entry(revision=1), entry(revision=2))
    ring = await suspendable(records=records)
    subject = await built(channels=[answering(day())], records=records, secrets=ring)
    call = authorised_read(await request(subject))

    # Held **inside** ``Secrets.get``, which is the interleaving the clause is about and
    # the one a fake answering immediately cannot reach: the record moves while the
    # credential read is suspended, so §6's post-read check runs against a record that
    # moved under it.
    gate = ring.suspend_next()
    running = asyncio.ensure_future(subject.forecaster.read(call, timeout=_BOUND))
    await gate.reached()
    await records._reprovision()
    gate.release()
    outcome = await running

    assert outcome.refusal is ForecastRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()


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
    call = authorised_read(await request(subject))
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
    call = authorised_read(await request(subject))
    running = asyncio.ensure_future(subject.forecaster.read(call, timeout=_BOUND))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running
    assert transport.absorbed == 1


async def test_a_transport_that_invents_a_cancellation_raises_a_fault() -> None:
    """ADR-0031 §2 through ADR-0241 §7: a cancellation with nothing cancelled is a fault.

    "Not a teardown that ends the turn, and not an outcome." It leaves as an
    ``AssistantError``, which is what reaches ADR-0226 §5's degradation — where letting
    the ``CancelledError`` out would tear down a turn nobody cancelled.
    """
    subject = await built(transport=RaisingTransport(asyncio.CancelledError()))
    call = authorised_read(await request(subject))

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
        # ADR-0148 §6's own limb: an unconnectable record, refused before the send.
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
    assert [tier.value for tier in FORECAST_READ.reads] == ["secret"]
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

    And ``None`` for ``step_id``, ``execution_id`` and ``egress_binding``: a forecast
    decision has no plan step and no execution, and the binding is derived by
    ``EgressBinder`` and accepted from nobody.
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
    assert proposal.step_id is None
    assert proposal.execution_id is None
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
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "max_days": MAX_DAYS,
        "max_day_chars": 2048,
        field: value,
    }

    with pytest.raises(ValueError, match=field):
        ForecastEgress(**fields)


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
    suite drives is the production order — the bound, ADR-0029 §2's three checks and
    ADR-0148 §6's four pre-transmit conditions — and not a stand-in for it.
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
                conditions=f"c{index}",
                temperature_min=f"{index}.0",
                temperature_max=f"1{index}.0",
                precipitation="0.0",
            )
            for index in range(days)
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
        return subject.forecaster, authorised_read(await request(subject))

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
