"""A ``TZID`` this reader cannot resolve, and why the entry is skipped rather than the read.

Found by the milestone-23 QA run against a live hub (#1484, #1491). Planting
``DTSTART;TZID=/etc/passwd:20260823T182300`` beside a UTC ``DTEND`` produced no
``ReaderError`` at all: the read *completed*, and a thirty-minute invite landed as
an attested belief spanning two and a half hours in the user's own zone.

**What was broken was the reader's knowledge, not the sandbox.** ADR-0183 §5's
marked clause — a parser hands adversary-chosen bytes to a namespace it "can never
denote a path outside" — held throughout, and these cases assert it directly: no
``TZID`` here opens anything, because ``zoneinfo`` refuses an absolute path, refuses
a key leaving ``TZPATH``, and holds no key for a name the database does not carry.
``icalendar``'s ``ZONEINFO`` provider then catches both of those refusals and
returns ``None``, with no warning, and the property is rebuilt from its wall clock
alone. So a stated zone arrives here byte-identical to a floating one, and ADR-0093
§7b localises a floating value in ``Settings.timezone``. That substitution is what
these cases close.

**Why the entry and not the read, argued from the texts rather than from taste.**

* ADR-0093 §7b is marked normative: "An entry a parseable source contains but the
  sensor cannot interpret is **skipped**, not raised on. A source that cannot be
  parsed at all raises under §8." A source carrying one such entry parses — every
  other ``VEVENT`` in it reads correctly — so the entry is the unit, and refusing
  the whole read would contradict that clause rather than implement it.
* ADR-0183 §5 disclaims deciding it, in as many words: "**The refusal half of
  #641's question is already answered and this ADR adds nothing to it**", pointing
  at ADR-0093 §8 and §7b. Its "the worst a hostile one produces is … a legible
  refusal" is unmarked supporting prose stating an **upper bound** on the harm, and
  ADR-0183's own header records it as "a stacked addition under ADR-0082 §1: no
  earlier ADR's status line changes". Unmarked prose in an ADR that changes no
  earlier decision does not override an earlier marked clause; and a skip sits
  strictly inside the bound that prose states, because it costs one entry where a
  refusal costs the reading.
* ADR-0183 §1's capability ladder is explicit that its members "are not
  interchangeable": one who can only *send* "controls the content of fields the
  framing admits, and nothing else". Refusing the whole read on one entry would
  promote the lowest rung — an invite sender, whose reach is one ``VEVENT`` in a
  file a fetcher assembles — to suppressing the user's entire calendar on every
  tick until a human repairs the file.
* ADR-0183 §6 already names this direction the safe one: withholding coverage where
  the read skipped something means "the cheapest way to manufacture a retirement —
  feed the reader one uninterpretable entry so it stops accounting — produces
  *fewer* retirements rather than more".

**The reading-level statement is where the legibility lives.** A skip is not
silent at the reading: ADR-0117 §5 withholds ``SourceReading.coverage``, so the read
warrants no absence and closes no window. Every case here asserts both halves,
because a skip site that did not withhold would close windows on a warrant the
reading does not have and nothing else in the tree would notice.

**One shape already refused the whole read before this change, and still does.**
``ZONEINFO.timezone`` catches ``ZoneInfoNotFoundError`` and ``ValueError`` and
nothing else, so a key past the filesystem's ``NAME_MAX`` raises ``OSError`` out of
``Calendar.from_ical`` — the ``OSError`` half of §5's prose, live in the tree. That
case is pinned for what it must never do rather than for which path it takes.

Refs #1491, #1484, ADR-0183 §5, ADR-0093 §7b/§8, ADR-0117 §5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import pytest
from ics_fixtures import NOW, calendar, reader, source, summaries, utc, vevent

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import CalendarFacet
from ai_assistant.readers._occurrences import SourceNotParseableError

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import SourceReading

#: The zone the QA run's hub was configured with, and the one a floating value is
#: localised in here. Two hours ahead of UTC in August, which is what makes the
#: substitution visible: a 12:30 wall time read as Rome is 10:30Z.
_ROME: Final = "Europe/Rome"

#: A well-formed entry inside the window, so a case about *another* entry still has
#: something the reader would happily have proposed — and so "skipped the entry"
#: and "refused the read" are told apart by the assertion rather than by intent.
_GOOD: Final = vevent(
    f"DTSTART:{utc(NOW)}",
    f"DTEND:{utc(NOW + timedelta(hours=1))}",
    "SUMMARY:standup",
    uid="good",
)

#: What the good entry renders as, once.
_GOOD_RENDERED: Final = 'Calendar entry "standup", on 2026-08-03 from 12:00 to 13:00 (UTC).'

#: The three shapes, each refused by ``zoneinfo`` for its own reason and every one
#: of them swallowed by ``icalendar``. The first two are the issue's; the third is
#: the ordinary unknown key, which takes the identical route and must not be
#: treated more leniently for being innocent-looking.
_UNRESOLVABLE: Final = [
    pytest.param("/etc/passwd", id="absolute-path"),
    pytest.param("../../../../etc/passwd", id="traversal"),
    pytest.param("Mars/Olympus", id="unknown-key"),
]


async def _read(tmp_path: Path, *events: str, **overrides: object) -> SourceReading:
    settings: dict[str, object] = {"timezone": _ROME}
    settings.update(overrides)
    return await reader(source(tmp_path, calendar(*events)), **settings).read()


def _invite(tzid: str, *, uid: str = "hostile") -> str:
    """The QA run's entry: a stated zone, a UTC end, and thirty minutes between them.

    The asymmetry is the point and it is the source's own: the start states a zone
    and the end is in UTC. Where ``tzid`` names UTC the entry runs 12:30Z to
    13:00Z, a half hour. Where ``tzid`` is silently replaced by ``Settings.timezone`` the
    start moves back to 10:30Z while the end does not move at all, and the same
    bytes read as two and a half hours — the shape #1491 reports, in the ratio it
    reports it in.
    """
    return vevent(
        f"DTSTART;TZID={tzid}:20260803T123000",
        "DTEND:20260803T130000Z",
        "SUMMARY:Traversal tzid",
        uid=uid,
    )


# --- the defect itself -------------------------------------------------------


@pytest.mark.parametrize("tzid", _UNRESOLVABLE)
async def test_an_unresolvable_tzid_proposes_nothing_rather_than_floating_time(
    tmp_path: Path, tzid: str
) -> None:
    """The entry is skipped, and the reading says it did not account for it.

    Before this rule the same source produced a proposal reading ``on 2026-08-03
    from 10:30 to 13:00 (Europe/Rome)`` — the source's own entry, at its own tier,
    at an instant the sender did not write. Nothing about the stored record would
    have said so, which is what makes a silent reinterpretation worse than a gap.
    """
    reading = await _read(tmp_path, _invite(tzid))

    assert reading.proposals == ()
    assert reading.coverage is None, "an entry the source holds and this read skipped (§5)"


@pytest.mark.parametrize("tzid", _UNRESOLVABLE)
async def test_one_unreadable_entry_costs_its_entry_and_not_the_read(
    tmp_path: Path, tzid: str
) -> None:
    """§7b's skip rule, at the granularity that decides an adversary's reach.

    The source parses; one ``VEVENT`` in it does not resolve. Refusing the whole
    read would hand a member of ADR-0183 §1's *lowest* rung — someone who can send
    an invite, and so write one component of a file a fetcher assembles — the power
    to blank the user's calendar on every tick. The entry beside it is proposed
    exactly as it would have been.
    """
    reading = await _read(tmp_path, _GOOD, _invite(tzid))

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


@pytest.mark.parametrize("tzid", _UNRESOLVABLE)
def test_no_tzid_here_denotes_a_file_of_the_adversarys_choosing(tzid: str) -> None:
    """ADR-0183 §5's marked clause, asserted rather than inherited from the ADR.

    The clause admits resolving a source-supplied name only "where the namespace
    refuses to be escaped by the name". These are the three ways it refuses, and
    they are asserted here because the fix under test is about the *reader noticing*
    the refusal — a change that would be pointless if the refusal itself were the
    thing at risk, and a regression in ``zoneinfo`` would otherwise show up only as
    a test that still passes.
    """
    with pytest.raises((ValueError, LookupError)):
        ZoneInfo(tzid)


# --- every property the reader reads a zone from -----------------------------


async def test_an_unresolvable_zone_on_the_dtend_is_not_a_dtend_absent(
    tmp_path: Path,
) -> None:
    """The end moves too, and it moves independently of the start.

    Here the start is in UTC and only the *end* names the unresolvable zone, so
    before this rule the entry ran to 15:00 read as Rome — 13:00Z — and was proposed
    as a well-formed one-hour meeting the source never described.

    ``_duration`` asks the question itself rather than reading ``_localised``'s
    ``None``, because that ``None`` is also what an **absent** ``DTEND`` produces,
    and the code below it then applies RFC 5545's default: instantaneous for a
    ``DATE-TIME`` start, a whole day for a ``DATE`` one. Either would be a duration
    invented from a property the source did write and this reader could not read.
    """
    entry = vevent(
        f"DTSTART:{utc(NOW)}",
        "DTEND;TZID=Mars/Olympus:20260803T150000",
        "SUMMARY:ends somewhere",
        uid="ended",
    )

    reading = await _read(tmp_path, _GOOD, entry)

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


async def test_an_unresolvable_zone_on_the_dtstamp_leaves_no_report_time(
    tmp_path: Path,
) -> None:
    """``DTSTAMP`` is a UTC value; a ``TZID`` on it is malformed and never substituted.

    It reaches the attestation's ``reported_at`` **and** the belief's
    ``last_confirmed_at`` (ADR-0103 §9), so a localised guess would date the
    source's testimony as well as the world's last confirmation of it. The ruled
    path for a component with no usable report time is the one taken: counted
    against the entry cap, skipped, coverage withheld (ADR-0092 §3, ADR-0117 §5).
    """
    entry = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:stamped-wrong",
            "DTSTAMP;TZID=Mars/Olympus:20260101T000000",
            f"DTSTART:{utc(NOW)}",
            f"DTEND:{utc(NOW + timedelta(hours=1))}",
            "SUMMARY:when did you say that",
            "END:VEVENT",
        ]
    )

    reading = await _read(tmp_path, _GOOD, entry)

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None
    # The facet still counts it — §5's clause acts on the coverage and never on the
    # facet, and ADR-0096 §5's asymmetry survives this skip like every other.
    assert isinstance(reading.facet, CalendarFacet)
    assert reading.facet.entries_in_progress == 2


async def test_an_unresolvable_zone_on_an_rdate_omits_that_occurrence_alone(
    tmp_path: Path,
) -> None:
    """An unread ``RDATE`` drops an occurrence the source states, and says so.

    The parameter sits on the ``RDATE`` **line**, and ``icalendar`` copies it onto
    the individual values only where it resolved — so a value whose zone failed
    arrives bare, and a check reading the value's own parameters would see nothing
    wrong with it. The line is what carries the declaration.
    """
    entry = vevent(
        f"DTSTART:{utc(NOW)}",
        "DURATION:PT30M",
        "RDATE;TZID=Mars/Olympus:20260803T130000",
        "SUMMARY:series",
        uid="rdated",
    )

    reading = await _read(tmp_path, entry)

    # The ``DTSTART`` occurrence stands — it names no zone and is read exactly as
    # before. Only the ``RDATE``'s extra occurrence is missing.
    assert summaries(reading.proposals) == [
        'Calendar entry "series", on 2026-08-03 from 12:00 to 12:30 (UTC).'
    ]
    assert reading.coverage is None


async def test_an_unresolvable_zone_on_an_exdate_leaves_the_exclusion_unapplied(
    tmp_path: Path,
) -> None:
    """The other direction of the same rule: an unread ``EXDATE`` emits what it excludes.

    The occurrence is still proposed, because dropping it would act on an
    instruction this read could not resolve — but the reading declares no coverage,
    which is ADR-0117 §5's answer to "we did not apply everything the source said".
    """
    entry = vevent(
        f"DTSTART:{utc(NOW)}",
        "DURATION:PT30M",
        "RRULE:FREQ=HOURLY;COUNT=2",
        "EXDATE;TZID=Mars/Olympus:20260803T130000",
        "SUMMARY:hourly",
        uid="exdated",
    )

    reading = await _read(tmp_path, entry)

    assert len(reading.proposals) == 2
    assert reading.coverage is None


async def test_an_unresolvable_zone_on_a_recurrence_id_suppresses_the_series(
    tmp_path: Path,
) -> None:
    """§7b's opaque-override rule, reached through a zone rather than a ``RANGE``.

    The ``RECURRENCE-ID`` keys the occurrence a correction is *about*. Without that
    instant the affected extent is unknown, and §7b is explicit: "where the affected
    extent is itself unknown, the whole series is suppressed". Leaving those
    occurrences to the master would propose precisely what the correction says is
    stale — an override is a correction, so mis-scoping it does not omit
    information, it re-states superseded information as current.
    """
    master = vevent(
        f"DTSTART:{utc(NOW)}",
        "DURATION:PT30M",
        "RRULE:FREQ=HOURLY;COUNT=2",
        "SUMMARY:hourly",
        uid="series",
    )
    override = vevent(
        "RECURRENCE-ID;TZID=Mars/Olympus:20260803T130000",
        f"DTSTART:{utc(NOW + timedelta(hours=1, minutes=15))}",
        "DURATION:PT30M",
        "SUMMARY:moved",
        uid="series",
    )

    reading = await _read(tmp_path, _GOOD, master, override)

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


# --- and what must keep working ----------------------------------------------


async def test_an_honest_tzid_keeps_the_half_hour_the_substitution_stretched(
    tmp_path: Path,
) -> None:
    """The same bytes with a zone that resolves: thirty minutes, and coverage declared.

    This is the control for every hostile case above — identical structure, one
    resolvable id — so the two and a half hours are demonstrably the substitution's
    doing and not the fixture's. The check fires on a declared zone beside a
    **naive** value, and a resolved zone is never naive.
    """
    reading = await _read(tmp_path, _invite("UTC", uid="honest"))

    assert summaries(reading.proposals) == [
        'Calendar entry "Traversal tzid", on 2026-08-03 from 12:30 to 13:00 (UTC).'
    ]
    assert reading.coverage is not None, "nothing was skipped, so the read accounts for itself"


async def test_a_resolved_zone_is_never_replaced_by_the_configured_one(
    tmp_path: Path,
) -> None:
    """A zone far from ``Settings.timezone``, so the substitution would be visible.

    ``Asia/Tokyo`` is nine hours ahead, ``Europe/Rome`` two: a 20:00 wall time is
    11:00Z in the entry's own zone and 18:00Z in the hub's. Only the first is inside
    the read's ``[10:00, 14:00)`` window, so a reader that reached for
    ``Settings.timezone`` here would not merely mis-time this entry — it would lose
    it, and report a calendar with nothing in it.
    """
    entry = vevent(
        "DTSTART;TZID=Asia/Tokyo:20260803T200000",
        "DTEND;TZID=Asia/Tokyo:20260803T203000",
        "SUMMARY:tokyo standup",
        uid="tokyo",
    )

    reading = await _read(tmp_path, entry)

    assert summaries(reading.proposals) == [
        'Calendar entry "tokyo standup", on 2026-08-03 from 20:00 to 20:30 (Asia/Tokyo).'
    ]
    assert reading.coverage is not None


async def test_a_tzid_naming_a_custom_vtimezone_is_untouched(tmp_path: Path) -> None:
    """A zone the *source itself* defines resolves, and this rule does not reach it.

    ``icalendar`` builds a tzinfo from the ``VTIMEZONE`` component and hands it to
    the value, so the value is aware and the check does not fire. That matters
    beyond tidiness: ``VTIMEZONE`` is how Exchange and every CalDAV server that
    emits a non-IANA ``TZID`` stay readable, and a rule keyed on "is the id an IANA
    key" rather than on "did it resolve" would have skipped all of them.

    The rendered label is the numeric offset rather than the id, which is
    ``_zone_label``'s existing bound on source text reaching a rendering and is
    asserted here only so this case cannot be read as changing it.
    """
    vtimezone = "\r\n".join(
        [
            "BEGIN:VTIMEZONE",
            "TZID:Tzidlane/Custom",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            "TZOFFSETFROM:+0100",
            "TZOFFSETTO:+0100",
            "TZNAME:CUST",
            "END:STANDARD",
            "END:VTIMEZONE",
        ]
    )
    entry = vevent(
        "DTSTART;TZID=Tzidlane/Custom:20260803T123000",
        "DTEND;TZID=Tzidlane/Custom:20260803T130000",
        "SUMMARY:corporate",
        uid="custom",
    )

    reading = await _read(tmp_path, vtimezone, entry)

    # ``+01:00`` rather than Rome's ``+02:00``, which is what makes this an
    # assertion about the source's zone rather than about the hub's.
    assert summaries(reading.proposals) == [
        'Calendar entry "corporate", on 2026-08-03 from 12:30 to 13:00 (UTC+01:00).'
    ]
    assert reading.coverage is not None


async def test_a_genuinely_floating_value_is_still_localised(tmp_path: Path) -> None:
    """The regression this check is one line away from causing.

    A value carrying **no** ``TZID`` is floating time, which §7b rules is localised
    in ``Settings.timezone`` — and §7b is emphatic that such an entry is "never
    skipped", because it is a real appointment someone holds. The distinction the
    fix draws is between a value that named no zone and one that named a zone we
    could not resolve; a check that could not tell them apart would drop every
    floating entry in every calendar.
    """
    entry = vevent(
        "DTSTART:20260803T123000",
        "DTEND:20260803T130000",
        "SUMMARY:floating",
        uid="floats",
    )

    reading = await _read(tmp_path, entry)

    assert summaries(reading.proposals) == [
        'Calendar entry "floating", on 2026-08-03 from 12:30 to 13:00 (Europe/Rome).'
    ]
    assert reading.coverage is not None


async def test_an_all_day_entry_is_not_skipped_over_a_parameter_rfc_5545_forbids(
    tmp_path: Path,
) -> None:
    """A ``DATE`` value carrying a ``TZID`` stays an all-day entry.

    RFC 5545 §3.2.19 forbids the parameter on a ``DATE`` property, ``icalendar``
    yields a ``date`` rather than a ``datetime``, and §7b rules a date-only value
    localised in ``Settings.timezone`` unconditionally — there is no stated instant
    for a zone to have moved. Skipping over a parameter the standard says is not
    there would drop entries on a rule no section states.
    """
    entry = vevent(
        "DTSTART;VALUE=DATE;TZID=Mars/Olympus:20260803",
        "SUMMARY:all day",
        uid="dated",
    )

    reading = await _read(tmp_path, entry)

    assert summaries(reading.proposals) == ['Calendar entry "all day", all day on 2026-08-03.']
    assert reading.coverage is not None


# --- the shape that already refused the whole read ---------------------------


async def test_an_overlong_tzid_never_reaches_a_proposal(tmp_path: Path) -> None:
    """The one hostile shape whose refusal ``icalendar`` does **not** swallow.

    ``ZONEINFO.timezone`` catches ``ZoneInfoNotFoundError`` and ``ValueError`` and
    nothing else, so a key past the filesystem's ``NAME_MAX`` raises ``OSError``
    from ``zoneinfo``'s own ``stat`` and escapes ``Calendar.from_ical`` — which is
    the ``OSError`` half of ADR-0183 §5's prose, live in the tree and reaching §8's
    wrapping as a whole-read ``ReaderError``.

    **Which of the two defences fires is the platform's to decide**, and the
    assertion is written so that either passes: where a filesystem admits the name,
    ``ZoneInfo`` raises ``ZoneInfoNotFoundError`` instead, ``icalendar`` swallows it,
    and the entry is skipped by the rule this module adds. What is pinned is what
    neither may do — read the entry at a wall time in ``Settings.timezone``.
    """
    entry = _invite("A" * 300, uid="overlong")

    refused: ReaderError | None = None
    reading = None
    try:
        reading = await _read(tmp_path, _GOOD, entry)
    except ReaderError as exc:
        refused = exc

    if refused is not None:
        # The whole-read path: `SourceNotParseableError` wrapping the `OSError`,
        # reported by ADR-0093 §8's payload-free message as a class name and never
        # as the 300-character id or the tzdata path the `OSError` carries.
        assert isinstance(refused.__cause__, SourceNotParseableError)
        assert "A" * 8 not in str(refused)
        return

    assert reading is not None
    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


# --- the instant that must never be proposed ---------------------------------


def test_the_substitution_this_forbids_would_have_been_visible(tmp_path: Path) -> None:
    """What the QA run measured, computed here so the numbers in this file are checked.

    A 12:30 wall time localised in ``Europe/Rome`` is 10:30Z, and the entry's UTC
    ``DTEND`` at 13:00Z is then two and a half hours after it rather than thirty
    minutes. This asserts the arithmetic behind every case above rather than the
    reader; if the fixture's zone or clock ever changed, the cases would stop
    testing the thing they say they test and nothing else would notice.
    """
    stated = datetime(2026, 8, 3, 12, 30, tzinfo=ZoneInfo(_ROME))
    end = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)

    assert stated.astimezone(UTC) == datetime(2026, 8, 3, 10, 30, tzinfo=UTC)
    assert end - stated.astimezone(UTC) == timedelta(hours=2, minutes=30)
    assert NOW - timedelta(hours=2) <= stated.astimezone(UTC) < NOW + timedelta(hours=2)
