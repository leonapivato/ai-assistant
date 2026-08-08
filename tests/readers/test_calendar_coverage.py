"""ADR-0117 §5 and §6: what the calendar declares it exhausted, and where entries lie.

The two halves of the opt-in ADR-0110 §3 needs, and neither alone does anything.
§5 is the reading-wide claim — the interval this read resolved, withheld outright
where the read skipped an entry it could not interpret. §6 is the per-proposal
claim — the occurrence's own span, declined rather than raised where that span has
no width.

**Why the withholding cases are the bulk of this file.** §5's second clause is the
one this lane owes and the one with a silent cost: a calendar carrying a single
entry this reader cannot read loses absence-demotion entirely, for as long as that
entry is in the window. Every shape ADR-0093 §7b skips is exercised here, one case
each, because a skip site added later without withholding coverage would close
windows on a warrant the reading does not have — and nothing else in the tree would
notice.

**And the exemption is exercised too.** "Declining to emit an occurrence the source
itself says does not occur is not a skip" (§5). A cancelled entry and an ``EXDATE``
exclusion are the source speaking, not this reader failing, so they must leave the
coverage intact — a reader that withheld on those would opt out of the mechanism on
the most ordinary calendar there is.

With the fixtures' clock at 12:00Z and a two-hour window each way, the read's
interval is ``[10:00, 14:00)``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import NOW, calendar, reader, source, utc, vevent

from ai_assistant.core.types import ReadCoverage, ReportedExtent
from ai_assistant.readers._occurrences import UTC_MAX

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import MemoryUpdateProposal, SourceReading

_LOWER = NOW - timedelta(hours=2)
_UPPER = NOW + timedelta(hours=2)

#: A well-formed entry inside the window, so a case about *another* entry still
#: has something the reader would happily have proposed.
_INSIDE = vevent(
    f"DTSTART:{utc(NOW)}",
    f"DTEND:{utc(NOW + timedelta(hours=1))}",
    "SUMMARY:standup",
    uid="good",
)


async def _read(tmp_path: Path, *events: str, **overrides: object) -> SourceReading:
    return await reader(source(tmp_path, calendar(*events)), **overrides).read()


def _extent_of(proposal: MemoryUpdateProposal) -> ReportedExtent | None:
    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None, "a reader's proposals are attested (ADR-0092 §1)"
    return attestation.extent


# --- §5's first clause: the interval the read resolved -----------------------


async def test_the_coverage_is_the_interval_the_read_resolved(tmp_path: Path) -> None:
    """§5's first clause, at the figures the window decision was made on.

    Not what the reader was *configured* to cover in the abstract and not what the
    source is presumed to hold: ADR-0093 §5 enforces the bound by **refusing**
    rather than truncating and §8 makes a read that cannot complete raise, so a
    ``SourceReading`` that exists at all is a read that reached its whole window.
    """
    reading = await _read(tmp_path, _INSIDE)

    assert reading.coverage == ReadCoverage(covers_from=_LOWER, covers_until=_UPPER)


async def test_an_empty_calendar_still_declares_what_it_exhausted(tmp_path: Path) -> None:
    """The most consequential reading in the decision declares a coverage.

    A cleared calendar produces an empty reading, which ADR-0093 §8 rules a
    **success**. It is the reading that retires the most on the least, and it can
    only do so because the coverage says the reader looked.
    """
    reading = await _read(tmp_path)

    assert reading.proposals == ()
    assert reading.coverage == ReadCoverage(covers_from=_LOWER, covers_until=_UPPER)


async def test_the_coverage_tracks_the_configured_window(tmp_path: Path) -> None:
    """It states this read's interval, so a differently configured read differs.

    Which is also what stops the value being a constant nobody would notice going
    stale: change the window and the declared interval moves with it, because it is
    computed from the same two edges the membership decision used.
    """
    reading = await _read(tmp_path, _INSIDE, window_past=timedelta(days=1))

    assert reading.coverage == ReadCoverage(
        covers_from=NOW - timedelta(days=1), covers_until=_UPPER
    )


def test_a_degenerate_saturated_interval_declares_no_coverage(tmp_path: Path) -> None:
    """A pair that exhausted no instant declares none rather than raising.

    ``ReadCoverage`` refuses ``[F, F)`` for its own good reason, so constructing one
    anyway would raise and ADR-0093 §8 would report a source fault against a source
    that parsed perfectly — the outcome §7b's saturation rule exists to prevent.
    Nothing is lost either way: such a read warrants no absence.

    **Driven directly, because it is not reachable through** :meth:`read`. Both
    edges collapse only for a ``read_at`` at the representable maximum with a zero
    ``window_past``, and :func:`~ai_assistant.core.clock.checked_clock` refuses a
    reading outside the localizable range — a whole day clear of ``datetime.max``
    — so no conforming clock can produce one. The guard stays anyway, and is read
    rather than asserted, for the reason ``_refuse_unconformable`` keeps its own
    unreachable check: that unreachability is *another module's* invariant, and a
    ``ValueError`` escaping this reader on a source that parsed perfectly is the
    one failure ADR-0093 §8 rules out entirely.
    """
    subject = reader(source(tmp_path, calendar()))

    assert subject._coverage(UTC_MAX, UTC_MAX, accounted=True) is None
    assert subject._coverage(_UPPER, _LOWER, accounted=True) is None
    assert subject._coverage(_LOWER, _UPPER, accounted=True) == ReadCoverage(
        covers_from=_LOWER, covers_until=_UPPER
    )


# --- §5's second clause: an unaccounted read declares no coverage ------------


@pytest.mark.parametrize(
    ("skipped", "why"),
    [
        (
            vevent("SUMMARY:no start at all", uid="bad"),
            "a component with no usable DTSTART",
        ),
        (
            vevent(
                f"DTSTART:{utc(NOW)}",
                # Parseable as an iCalendar property and refused by the recurrence
                # expander, which is the shape §7b's rule is about: the *document*
                # is fine, one component's rule is not (a document `icalendar`
                # cannot read at all raises instead, ADR-0093 §8).
                "RRULE:FREQ=DAILY;BYSETPOS=0",
                "SUMMARY:a rule that will not expand",
                uid="bad",
            ),
            "an RRULE this reader cannot parse",
        ),
        (
            vevent(
                f"DTSTART:{utc(NOW)}",
                f"DTEND:{utc(NOW - timedelta(hours=1))}",
                "SUMMARY:ends before it starts",
                uid="bad",
            ),
            "a negative duration",
        ),
    ],
    ids=["no-dtstart", "bad-rrule", "negative-duration"],
)
async def test_a_component_this_reader_cannot_reduce_withholds_the_coverage(
    tmp_path: Path, skipped: str, why: str
) -> None:
    """§5's second clause over ADR-0093 §7b's component-level skips.

    Each of these is an entry the source **does** hold and the reading does not
    account for. Letting such a reading warrant an absence would close windows on a
    false warrant: §3's warrant is that the source was read to exhaustion over the
    region and did not report the entry, and here the source did report it.

    **And the close would not be recoverable**, which is the decisive half. ADR-0110
    §3's error calculus is ADR-0092 §4's — a wrongly closed attested window "is
    re-proposed by the next scheduled read" — and an entry this reader cannot
    interpret is not re-proposed by any read until the source is repaired.

    The skipped entry's *position* is unknown by construction, so the withholding
    cannot be scoped to the interval it occupies. Coarse is the honest answer, and
    it is coarse in the shape ADR-0110 §4 already chose.
    """
    reading = await _read(tmp_path, _INSIDE, skipped)

    assert reading.coverage is None, why
    assert len(reading.proposals) == 1, "the good entry is still proposed (§7b skips, not raises)"


async def test_a_series_whose_extent_cannot_be_established_withholds_the_coverage(
    tmp_path: Path,
) -> None:
    """Two masters sharing a ``UID``: §7b suppresses the series, §5 withholds the read.

    The master's values for the affected occurrences are known to be untrustworthy
    and nothing else is, so the whole series goes — and with it any claim this read
    could make about having exhausted the region those occurrences sit in.
    """
    twin = vevent(f"DTSTART:{utc(NOW)}", "SUMMARY:one of two masters", uid="twins")
    other = vevent(f"DTSTART:{utc(NOW + timedelta(minutes=5))}", "SUMMARY:the other", uid="twins")

    reading = await _read(tmp_path, _INSIDE, twin, other)

    assert reading.coverage is None
    assert len(reading.proposals) == 1


async def test_an_override_whose_form_is_opaque_withholds_the_coverage(tmp_path: Path) -> None:
    """§7b's opaque override suppresses what it might have changed, so §5 withholds.

    ``RANGE=THISANDPRIOR`` states an extent this reader does not implement, and
    inferring one from a value we decline to interpret is the mis-scoping §7b warns
    about: an override is a **correction**, so getting its scope wrong proposes
    stale information as current.
    """
    master = vevent(
        f"DTSTART:{utc(NOW)}", "RRULE:FREQ=DAILY", "SUMMARY:a daily thing", uid="series"
    )
    opaque = vevent(
        f"RECURRENCE-ID;RANGE=THISANDPRIOR:{utc(NOW)}",
        f"DTSTART:{utc(NOW)}",
        "SUMMARY:an override we cannot scope",
        uid="series",
    )

    reading = await _read(tmp_path, _INSIDE, master, opaque)

    assert reading.coverage is None


async def test_two_overrides_contesting_one_occurrence_withhold_the_coverage(
    tmp_path: Path,
) -> None:
    """§7b fails closed on a contested occurrence, and §5 follows it.

    Two corrections of equal specificity at the same point are genuinely
    contradictory, so the reader emits neither — which means the source held an
    occurrence there that this read cannot describe.
    """
    master = vevent(
        f"DTSTART:{utc(NOW)}", "RRULE:FREQ=DAILY", "SUMMARY:a daily thing", uid="series"
    )
    first = vevent(
        f"RECURRENCE-ID:{utc(NOW)}",
        f"DTSTART:{utc(NOW)}",
        "SUMMARY:moved here",
        uid="series",
    )
    second = vevent(
        f"RECURRENCE-ID:{utc(NOW)}",
        f"DTSTART:{utc(NOW + timedelta(minutes=30))}",
        "SUMMARY:no, moved here",
        uid="series",
    )

    reading = await _read(tmp_path, _INSIDE, master, first, second)

    assert reading.coverage is None


async def test_an_rdate_this_reader_cannot_localise_withholds_the_coverage(
    tmp_path: Path,
) -> None:
    """A ``PERIOD``-valued ``RDATE`` is an occurrence the source states and we drop.

    An unread ``RDATE`` omits an occurrence the source declares, and an unread
    ``EXDATE`` emits one it excludes; neither is "the source says this does not
    occur", which is the one shape §5 exempts.
    """
    entry = vevent(
        f"DTSTART:{utc(NOW)}",
        f"RDATE;VALUE=PERIOD:{utc(NOW + timedelta(minutes=10))}/PT1H",
        "SUMMARY:a period we cannot read",
        uid="periodic",
    )

    reading = await _read(tmp_path, _INSIDE, entry)

    assert reading.coverage is None


async def test_an_entry_with_no_dtstamp_withholds_the_coverage(tmp_path: Path) -> None:
    """The skip ``CalendarReader`` itself performs, and the facet still counts it.

    ADR-0092 §3 permits no substitute for a report time the source did not make, so
    the occurrence is skipped rather than attested — and it is an entry inside this
    read's interval that the reading does not account for.

    **The facet is untouched**, which ADR-0117 §7 states expressly: §5's clause acts
    on the reading's coverage and never on the facet, so ADR-0096 §5's asymmetry
    survives exactly as it was. Nobody should "fix" it by making the facet skip the
    same entries.
    """
    stampless = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:unstamped",
            f"DTSTART:{utc(NOW)}",
            f"DTEND:{utc(NOW + timedelta(hours=1))}",
            "SUMMARY:nobody said when they said this",
            "END:VEVENT",
        ]
    )

    reading = await _read(tmp_path, _INSIDE, stampless)

    assert reading.coverage is None
    assert len(reading.proposals) == 1, "the stampless entry is skipped, not proposed"
    assert reading.facet is not None
    assert reading.facet.entries_in_progress == 2, "the facet counts what the proposals skip"


# --- §5's exemption: the source saying "this does not occur" is not a skip ----


async def test_a_cancelled_entry_leaves_the_coverage_intact(tmp_path: Path) -> None:
    """§5's exemption, and getting it wrong would opt out on an ordinary calendar.

    ``STATUS:CANCELLED`` is the source itself saying the entry does not occur, so
    declining to emit it is reading the source correctly — the point ``_resolve``
    already makes about why the "is declining to emit a cancelled occurrence an
    absence claim?" question disappears rather than needing an answer.
    """
    cancelled = vevent(
        f"DTSTART:{utc(NOW)}",
        f"DTEND:{utc(NOW + timedelta(hours=1))}",
        "STATUS:CANCELLED",
        "SUMMARY:called off",
        uid="off",
    )

    reading = await _read(tmp_path, _INSIDE, cancelled)

    assert reading.coverage == ReadCoverage(covers_from=_LOWER, covers_until=_UPPER)
    assert len(reading.proposals) == 1


async def test_an_exdate_exclusion_leaves_the_coverage_intact(tmp_path: Path) -> None:
    """The same exemption through the other mechanism the source has for it."""
    excluded = vevent(
        f"DTSTART:{utc(NOW - timedelta(days=1))}",
        "RRULE:FREQ=DAILY",
        f"EXDATE:{utc(NOW)}",
        "SUMMARY:daily, except today",
        uid="most-days",
    )

    reading = await _read(tmp_path, excluded)

    assert reading.coverage == ReadCoverage(covers_from=_LOWER, covers_until=_UPPER)
    assert reading.proposals == (), "today's occurrence is excluded by the source"


async def test_an_entry_merely_outside_the_window_leaves_the_coverage_intact(
    tmp_path: Path,
) -> None:
    """Not reporting what the read did not look at is not a gap in what it did."""
    elsewhere = vevent(
        f"DTSTART:{utc(NOW + timedelta(days=30))}",
        f"DTEND:{utc(NOW + timedelta(days=30, hours=1))}",
        "SUMMARY:next month",
        uid="later",
    )

    reading = await _read(tmp_path, _INSIDE, elsewhere)

    assert reading.coverage == ReadCoverage(covers_from=_LOWER, covers_until=_UPPER)


# --- §6: the extent is the occurrence's own span -----------------------------


async def test_the_extent_is_the_occurrences_own_span(tmp_path: Path) -> None:
    """§6's first clause, in UTC, exactly as the window decision was made on it."""
    reading = await _read(tmp_path, _INSIDE)

    assert _extent_of(reading.proposals[0]) == ReportedExtent(
        extends_from=NOW, extends_until=NOW + timedelta(hours=1)
    )


async def test_an_entry_ahead_of_the_read_states_where_it_lies_and_stays_retrievable(
    tmp_path: Path,
) -> None:
    """#639's case, and the property ADR-0117 §1 found the envelope window destroys.

    The proposal's envelope window is untouched — fully open, so the belief is on
    the read path from the moment it is stored — while the extent says the entry
    happens later. ADR-0110 §3's original carrier could not express that pairing at
    all, which is what made the mechanism unreachable.
    """
    ahead = vevent(
        f"DTSTART:{utc(NOW + timedelta(hours=1))}",
        f"DTEND:{utc(NOW + timedelta(hours=1, minutes=30))}",
        "SUMMARY:a meeting that has not happened yet",
        uid="ahead",
    )

    reading = await _read(tmp_path, ahead)

    proposal = reading.proposals[0]
    assert proposal.proposed.validity.valid_from is None
    assert proposal.proposed.validity.valid_until is None, "no producer-set window (§4)"
    assert proposal.proposed.validity.live_at(NOW), "retrievable now, an hour before it starts"
    assert _extent_of(proposal) == ReportedExtent(
        extends_from=NOW + timedelta(hours=1), extends_until=NOW + timedelta(hours=1, minutes=30)
    )


async def test_a_zero_duration_entry_declines_the_extent_rather_than_raising(
    tmp_path: Path,
) -> None:
    """§6's second clause, and the shape that would otherwise be demotable by anything.

    ADR-0093 §7b gives a date-time ``DTSTART`` with no end an instantaneous
    occurrence, and an extent of zero width admits no instant — so it would be
    contained by *every* coverage and the record would be absence-demotable by any
    reading at all. The honest value is none; the reminder is proposed, retrievable
    and folded exactly as it is today, and only its demotability is withheld.

    Widening the span by an invented epsilon would state an extent the source did
    not give, which §2's second clause forbids in as many words.
    """
    instant = vevent(f"DTSTART:{utc(NOW)}", "SUMMARY:a reminder", uid="ping")

    reading = await _read(tmp_path, instant)

    assert len(reading.proposals) == 1, "proposed exactly as it is today"
    assert _extent_of(reading.proposals[0]) is None
    assert reading.coverage is not None, "declining an extent is not a skip"


async def test_an_edge_straddling_occurrence_states_its_real_span_untrimmed(
    tmp_path: Path,
) -> None:
    """§6's third clause: no rule is added, and containment answers it on its own.

    ``_occurrences`` admits an occurrence that **overlaps** the window rather than
    one starting inside it, which ADR-0093 §7b decided deliberately. Its extent is
    simply not contained in the coverage, so it is proposed, retrievable and folded
    and is not absence-demotable — the correct answer arriving from ADR-0110 §3's
    containment rule with nothing added.

    Trimming the extent to the window to obtain containment would manufacture a
    warrant, which is why §2's second clause names trimming beside widening.
    """
    straddling = vevent(
        f"DTSTART:{utc(_LOWER - timedelta(hours=1))}",
        f"DTEND:{utc(NOW)}",
        "SUMMARY:started before the window",
        uid="straddles",
    )

    reading = await _read(tmp_path, straddling)

    extent = _extent_of(reading.proposals[0])
    assert extent == ReportedExtent(extends_from=_LOWER - timedelta(hours=1), extends_until=NOW)
    assert reading.coverage is not None
    assert not reading.coverage.contains(extent), "not exhausted, so not demotable"


async def test_the_extent_and_the_report_time_are_different_facts(tmp_path: Path) -> None:
    """§6's last paragraph: neither is derived from the other, and they disagree.

    The ``DTSTAMP`` here is months before the occurrence, which is the ordinary
    shape of a calendar entry rather than an edge case.
    """
    reading = await _read(tmp_path, _INSIDE)

    attestation = reading.proposals[0].proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert attestation.extent is not None
    assert attestation.extent.extends_from == NOW


async def test_every_proposal_of_a_multi_entry_read_states_its_own_extent(
    tmp_path: Path,
) -> None:
    """One extent per occurrence, not one per reading: it is a per-entry fact."""
    second = vevent(
        f"DTSTART:{utc(NOW + timedelta(minutes=30))}",
        f"DTEND:{utc(NOW + timedelta(minutes=45))}",
        "SUMMARY:a second thing",
        uid="two",
    )

    reading = await _read(tmp_path, _INSIDE, second)

    extents = [_extent_of(proposal) for proposal in reading.proposals]
    assert extents == [
        ReportedExtent(extends_from=NOW, extends_until=NOW + timedelta(hours=1)),
        ReportedExtent(
            extends_from=NOW + timedelta(minutes=30),
            extends_until=NOW + timedelta(minutes=45),
        ),
    ]
