"""ADR-0093 §7b's expansion: the seek, the budgets, cancellation and overrides.

The override clauses are the ones worth reading the ADR for. An override is a
**correction**, so mis-scoping one does not merely omit information — it proposes
stale information as current, which is worse than proposing nothing. Hence the
composition rule, and hence the fail-closed posture for a form the reader cannot
interpret: the master's values for those occurrences are known to be
untrustworthy and nothing else is.

The window here is the default seven days forward and one day back from a clock
at ``2026-08-03 12:00Z``, so a daily 09:00Z master generates exactly eight
in-window occurrences, 3 to 10 August.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import calendar, reader, source, vevent

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import CalendarFacet
from ai_assistant.readers._occurrences import (
    EntryCapExceededError,
    ExpansionBudgetExhaustedError,
)
from ai_assistant.readers.calendar import ContentBudgetExhaustedError

if TYPE_CHECKING:
    from pathlib import Path

#: The daily master every override case corrects.
_MASTER = vevent(
    "DTSTART:20260803T090000Z",
    "DURATION:PT1H",
    "RRULE:FREQ=DAILY",
    "SUMMARY:Standup",
    uid="series",
)

#: What that master alone produces, as ``(day, HH:MM, title)``.
_UNTOUCHED = [(day, "09:00", "Standup") for day in range(3, 11)]

_WIDE = {"window_past": timedelta(days=1), "window_future": timedelta(days=7)}


async def _occurrences(path: Path, **overrides: object) -> list[tuple[int, str, str]]:
    """Every proposal as ``(day of August, start time, title)``."""
    reading = await reader(path, **{**_WIDE, **overrides}).read()
    found = []
    for proposal in reading.proposals:
        # Rendered as: Calendar entry "X", on 2026-08-05 from 10:00 to 11:00 (UTC).
        text = proposal.proposed.content
        title = text.split('"')[1]
        stamp = text.rsplit(" on ", 1)[1]
        day = int(stamp[8:10])
        found.append((day, stamp.split(" from ")[1][:5], title))
    return found


def _override(*lines: str, recurrence_id: str, scope: str = "") -> str:
    marker = f"RECURRENCE-ID{scope}:{recurrence_id}"
    return vevent(marker, *lines, uid="series")


# --- the seek, and the budget behind it (ADR-0093 §7b) ----------------------


async def test_an_old_high_frequency_recurrence_reaches_the_window_without_walking(
    tmp_path: Path,
) -> None:
    """An in-window cap does not bound the work of *reaching* the window.

    ``DTSTART:19700101T000000Z`` with an hourly rule is a few dozen bytes and has
    roughly half a million occurrences before it reaches a window centred on
    today, so the byte cap cannot catch it and the entry cap counts only what
    lands. Under enumeration-from-``DTSTART`` a conforming implementation walks
    every one of them and the read §5 calls bounded hangs.

    The budget here is a hundred: enough for the four in-window occurrences and
    the seek's deliberate undershoot, and four orders of magnitude short of the
    walk.
    """
    raw = calendar(
        vevent(
            "DTSTART:19700101T000000Z",
            "DURATION:PT1S",
            "RRULE:FREQ=SECONDLY;INTERVAL=3600",
            "SUMMARY:Tick",
        )
    )

    reading = await reader(source(tmp_path, raw), max_expansion=100).read()

    assert len(reading.proposals) == 4


async def test_a_long_running_occurrence_that_began_years_earlier_is_not_seeked_past(
    tmp_path: Path,
) -> None:
    """The seek is anchored a **duration** early, and ``window_start`` would not do.

    A yearly event with ``DTSTART`` in 2020 and a multi-month duration has
    occurrences running *through* a 2026 window; a seek to the first occurrence at
    or after ``window_start`` lands in 2027 and skips every one of them. That is
    the start-instant membership rule defeated one level down by the optimisation
    added to satisfy the bound — and it fails on exactly the same entries,
    permanently, because the window moves forward each run and the occurrence's
    start recedes.
    """
    raw = calendar(
        vevent(
            "DTSTART:20200101T000000Z",
            "DURATION:P400D",
            "RRULE:FREQ=YEARLY",
            "SUMMARY:Long haul",
        )
    )

    reading = await reader(source(tmp_path, raw)).read()

    assert len(reading.proposals) == 1


async def test_a_seek_anchor_that_underflows_saturates_rather_than_raising(
    tmp_path: Path,
) -> None:
    """The clause an earlier draft's edge-only saturation escaped immediately.

    A recurrence with a multi-millennium ``DURATION`` makes ``window_start - D``
    underflow *before* the seek begins, leaving an implementation to raise a raw
    arithmetic error or skip an occurrence that genuinely overlaps — breaking §8's
    error contract or §7b's overlap rule respectively, and the second one
    silently. Saturating the anchor is right for the reason it is right at the
    edges: there is no instant before the minimum for a predecessor to have
    started at.
    """
    raw = calendar(
        vevent(
            "DTSTART:20200101T000000Z",
            "DURATION:P900000D",
            "RRULE:FREQ=YEARLY;COUNT=3",
            "SUMMARY:Aeon",
        )
    )

    reading = await reader(source(tmp_path, raw)).read()

    assert len(reading.proposals) == 3


async def test_the_expansion_budget_is_spent_across_the_whole_read(tmp_path: Path) -> None:
    """Source-wide, and a per-component version was tried and does not hold.

    Under a per-component cap, a file can carry thousands of non-seekable
    recurrences, each spending its full allowance to establish that it has *no*
    in-window occurrence. Every component conforms, no entry is produced so the
    entry cap never fires, and the read still performs hundreds of millions of
    steps. A budget that resets per component bounds each piece of the work and
    not the work.

    Each component here costs about 680 steps, so **one** fits inside a
    thousand-step budget and **three** do not — which is the difference the two
    accounting rules produce, on the same file.
    """
    monthly = [
        vevent(
            "DTSTART:19700115T030000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=15",
            f"SUMMARY:Rent {index}",
            uid=f"m{index}",
        )
        for index in range(3)
    ]

    one = reader(source(tmp_path, calendar(monthly[0]), name="one.ics"), max_expansion=1000)
    assert (await one.read()).proposals == ()

    three = reader(source(tmp_path, calendar(*monthly), name="three.ics"), max_expansion=1000)
    with pytest.raises(ReaderError) as raised:
        await three.read()

    assert isinstance(raised.value.__cause__, ExpansionBudgetExhaustedError)


# --- the entry cap, applied before the skip rule (ADR-0093 §7b) -------------


async def test_a_recurrence_expanding_past_the_entry_cap_is_refused(tmp_path: Path) -> None:
    """Refused, never truncated (§5), and counted as **occurrences**.

    A cap counting components would accept a single ``VEVENT`` carrying
    ``RRULE:FREQ=SECONDLY`` — a few dozen bytes — while the reader built the tuple
    the cap exists to bound.
    """
    path = source(tmp_path, calendar(_MASTER))

    assert len(await _occurrences(path, max_entries=8)) == 8

    with pytest.raises(ReaderError) as raised:
        await _occurrences(path, max_entries=7)

    assert isinstance(raised.value.__cause__, EntryCapExceededError)


async def test_a_source_over_the_cap_and_wholly_uninterpretable_is_still_refused(
    tmp_path: Path,
) -> None:
    """The order is load-bearing and the two rules contradict without it.

    Eight in-window occurrences of which all eight are uninterpretable would, under
    skip-first, produce a successful empty reading from a source that busted its
    cap — a refusal turned into a false "your calendar is clear", which is the
    failure §8 exists to prevent. It is also the only order under which the cap
    bounds anything: interpreting more entries to discover that fewer survive is
    precisely the work a cap is for.
    """
    unstamped = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:series",
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY",
            "SUMMARY:No stamp",
            "END:VEVENT",
        ]
    )
    path = source(tmp_path, calendar(unstamped))

    # Under the cap, every occurrence is skipped and the reading is a success.
    assert await _occurrences(path, max_entries=8) == []

    with pytest.raises(ReaderError) as raised:
        await _occurrences(path, max_entries=7)

    assert isinstance(raised.value.__cause__, EntryCapExceededError)


# --- the content budget (ADR-0093 §7a) --------------------------------------


async def test_the_content_budget_refuses_before_the_memory_is_spent(tmp_path: Path) -> None:
    """It bounds the **output**, which none of the other caps do.

    A source can satisfy every one of them while the proposals blow up, because an
    occurrence repeats its component's content and nothing was counting bytes on
    the way out. The budget is checked **before** each proposal is materialised
    rather than after — the same ordering as the byte cap, for the same reason: a
    check that runs after the allocation has already paid for it.

    Counting the ids minted is what turns "before" into an assertion: an
    implementation that built every proposal and then measured would have minted
    eight.
    """
    minted: list[str] = []

    def factory() -> str:
        minted.append(f"id-{len(minted)}")
        return minted[-1]

    raw = calendar(
        vevent(
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY",
            f"SUMMARY:{'x' * 20_000}",
            uid="series",
        )
    )

    with pytest.raises(ReaderError) as raised:
        await _occurrences(source(tmp_path, raw), max_content_bytes=60_000, id_factory=factory)

    assert isinstance(raised.value.__cause__, ContentBudgetExhaustedError)
    assert len(minted) <= 3, minted


# --- cancellation, decided before anything is counted (ADR-0093 §7b) --------


async def test_a_cancelled_recurring_master_contributes_no_occurrences_at_all(
    tmp_path: Path,
) -> None:
    """The plainer case an override-only rule leaves open.

    A recurring ``VEVENT`` carrying ``STATUS:CANCELLED`` and no ``RECURRENCE-ID``
    is a **master**, not an override, so nothing would suppress it and every
    in-window occurrence would be counted and proposed — beliefs in a whole series
    of meetings the calendar marks off. Keying the rule on *what the source says
    about a component* covers both, and covers whatever third shape the format has
    that neither the ADR nor this reader enumerated.
    """
    raw = calendar(
        vevent(
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY",
            "STATUS:CANCELLED",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    assert await _occurrences(source(tmp_path, raw)) == []


async def test_a_cancelled_single_occurrence_is_absent_from_the_proposals_and_the_count(
    tmp_path: Path,
) -> None:
    """And nothing at all is proposed *about* the cancellation.

    Declining to emit an occurrence the source's own content says does not happen
    is not "proposing an absence": §4 governs what a reader *asserts about the
    world*, and this is reading the source correctly. The alternatives are both
    worse and both were available — emitting the occurrence proposes a meeting the
    calendar explicitly says is off, and emitting some "cancelled" marker is the
    absence claim §4 actually forbids.

    The cap is set to exactly the surviving count, which is what makes "absent
    from the cap's count" an assertion rather than a hope.
    """
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T090000Z",
            "DURATION:PT1H",
            "STATUS:CANCELLED",
            "SUMMARY:Standup",
            recurrence_id="20260805T090000Z",
        ),
    )

    found = await _occurrences(source(tmp_path, raw), max_entries=7)

    assert found == [item for item in _UNTOUCHED if item[0] != 5]
    assert not any("cancel" in title.lower() for _, _, title in found)


# --- resolution and composition (ADR-0093 §7b) ------------------------------


async def test_a_non_cancelled_override_replaces_rather_than_duplicates(
    tmp_path: Path,
) -> None:
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T110000Z",
            "DURATION:PT1H",
            "SUMMARY:Moved",
            recurrence_id="20260805T090000Z",
        ),
    )

    found = await _occurrences(source(tmp_path, raw))

    assert found == sorted([item for item in _UNTOUCHED if item[0] != 5] + [(5, "11:00", "Moved")])


async def test_a_this_and_future_override_governs_every_later_occurrence(
    tmp_path: Path,
) -> None:
    """The clause an earlier draft got wrong, and the reason it matters.

    "Replaces the occurrence it names" is right for the common form and wrong for
    ``RANGE=THISANDFUTURE``: for a daily 09:00 master with an in-window override
    moving 5 August to 10:00, that rule leaves 6-10 August proposed at a time the
    calendar no longer says.
    """
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:Shifted",
            recurrence_id="20260805T090000Z",
            scope=";RANGE=THISANDFUTURE",
        ),
    )

    found = await _occurrences(source(tmp_path, raw))

    assert found == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
        *[(day, "10:00", "Shifted") for day in range(5, 11)],
    ]


async def test_a_this_and_future_override_that_is_shifted_and_cancelled_suppresses_the_rest(
    tmp_path: Path,
) -> None:
    """Later occurrences follow **it** rather than the master — and it is off.

    Cancellation says *whether*; resolution says *how far*. An earlier draft had
    cancellation asserting both, which contradicted the resolution clause outright
    for a cancelled range override: 6 August then had to be both suppressed (by the
    range) and proposed (by the single-occurrence reading), so no output conformed.
    """
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "STATUS:CANCELLED",
            "SUMMARY:Shifted",
            recurrence_id="20260805T090000Z",
            scope=";RANGE=THISANDFUTURE",
        ),
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
    ]


async def test_two_overlapping_this_and_future_overrides_compose_by_last_writer(
    tmp_path: Path,
) -> None:
    """ "Replaces every later occurrence" is not a function when two ranges overlap.

    An implementation obeying only the replacement clause may emit either time, or
    both. Last-writer-wins by ``RECURRENCE-ID`` is the reading that matches what
    the overrides *mean*: each is a correction made at a point in the series, so
    the most recent correction at or before an occurrence is the one still
    standing — and the earlier one still governs between them.
    """
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:First",
            recurrence_id="20260805T090000Z",
            scope=";RANGE=THISANDFUTURE",
        ),
        _override(
            "DTSTART:20260807T110000Z",
            "DURATION:PT1H",
            "SUMMARY:Second",
            recurrence_id="20260807T090000Z",
            scope=";RANGE=THISANDFUTURE",
        ),
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
        (5, "10:00", "First"),
        (6, "10:00", "First"),
        *[(day, "11:00", "Second") for day in range(7, 11)],
    ]


async def test_a_single_instance_override_wins_inside_a_range_overrides_extent(
    tmp_path: Path,
) -> None:
    """And it wins for **its occurrence alone**, because it is the more specific claim."""
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:Range",
            recurrence_id="20260805T090000Z",
            scope=";RANGE=THISANDFUTURE",
        ),
        _override(
            "DTSTART:20260807T140000Z",
            "DURATION:PT1H",
            "SUMMARY:Single",
            recurrence_id="20260807T090000Z",
        ),
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
        (5, "10:00", "Range"),
        (6, "10:00", "Range"),
        (7, "14:00", "Single"),
        (8, "10:00", "Range"),
        (9, "10:00", "Range"),
        (10, "10:00", "Range"),
    ]


async def test_two_overrides_of_one_form_sharing_a_recurrence_id_suppress_that_occurrence(
    tmp_path: Path,
) -> None:
    """Genuinely contradictory rather than merely unspecified, so it fails closed."""
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:A",
            recurrence_id="20260805T090000Z",
        ),
        _override(
            "DTSTART:20260805T110000Z",
            "DURATION:PT1H",
            "SUMMARY:B",
            recurrence_id="20260805T090000Z",
        ),
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        item for item in _UNTOUCHED if item[0] != 5
    ]


async def test_an_override_of_an_uninterpretable_form_suppresses_the_series(
    tmp_path: Path,
) -> None:
    """Not left to the master, because the master's values are known untrustworthy.

    ``RANGE=THISANDPRIOR`` is the deprecated form this reader does not implement.
    Its *name* states an extent — but inferring one from a value we decline to
    interpret is exactly the mis-scoping §7b warns about, so the extent counts as
    unknown and the whole series is suppressed. That is the same fail-closed
    posture §5 takes on a source too expensive to read, applied to one too complex
    to read, and it is deliberately stated over **forms** rather than over the two
    that happened to be enumerated.
    """
    raw = calendar(
        _MASTER,
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:Unknown scope",
            recurrence_id="20260805T090000Z",
            scope=";RANGE=THISANDPRIOR",
        ),
    )

    assert await _occurrences(source(tmp_path, raw)) == []


async def test_an_exdate_removes_the_occurrence_it_names(tmp_path: Path) -> None:
    """Ordinary RFC 5545, asserted because the expansion is this module's own."""
    raw = calendar(
        vevent(
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY",
            "EXDATE:20260806T090000Z",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        item for item in _UNTOUCHED if item[0] != 6
    ]


async def test_an_rdate_adds_an_occurrence_the_rule_does_not_generate(tmp_path: Path) -> None:
    """``RDATE`` is part of the recurrence set, and it is bounded like the rest."""
    raw = calendar(
        vevent(
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY;COUNT=2",
            "RDATE:20260809T160000Z",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
        (9, "16:00", "Standup"),
    ]


@pytest.mark.parametrize(
    ("until", "expected_days"),
    [
        # RFC 5545 wants a UTC `UNTIL` beside a UTC `DTSTART`, and that is the
        # ordinary case.
        ("UNTIL=20260805T090000Z", [3, 4, 5]),
        # A DATE-valued UNTIL bounds the whole of that day. `dateutil` refuses an
        # UNTIL whose awareness disagrees with `DTSTART`'s, and every `DTSTART`
        # here is aware because §7b localises floating and date-only values — so
        # reconciling the two is what keeps an ordinary file from being skipped as
        # uninterpretable.
        ("UNTIL=20260805", [3, 4, 5]),
        # And a floating one, reconciled in the same zone the start was localised
        # in rather than left to fail.
        ("UNTIL=20260805T090000", [3, 4, 5]),
    ],
)
async def test_an_until_bound_is_reconciled_with_the_start(
    tmp_path: Path, until: str, expected_days: list[int]
) -> None:
    raw = calendar(
        vevent(
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            f"RRULE:FREQ=DAILY;{until}",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    found = await _occurrences(source(tmp_path, raw))

    assert [day for day, _, _ in found] == expected_days


async def test_two_masters_sharing_a_uid_suppress_the_whole_group(tmp_path: Path) -> None:
    """A shape whose extent cannot be established, so it fails closed.

    §7b defines extent by the resolution clause "and nowhere else", and two
    masters leave that clause with no single series to resolve against. The
    fail-closed reading is the same one an uninterpretable override gets, for the
    same reason: the values are known to be untrustworthy and nothing else is.
    """
    raw = calendar(
        vevent("DTSTART:20260803T090000Z", "DURATION:PT1H", "SUMMARY:One", uid="clash"),
        vevent("DTSTART:20260804T090000Z", "DURATION:PT1H", "SUMMARY:Two", uid="clash"),
    )

    assert await _occurrences(source(tmp_path, raw)) == []


async def test_an_orphan_override_with_no_master_suppresses_the_group(tmp_path: Path) -> None:
    """There is no expansion to resolve it against, so nothing is proposed."""
    raw = calendar(
        _override(
            "DTSTART:20260805T100000Z",
            "DURATION:PT1H",
            "SUMMARY:Orphan",
            recurrence_id="20260805T090000Z",
        )
    )

    assert await _occurrences(source(tmp_path, raw)) == []


async def test_a_dtstart_the_rule_does_not_generate_is_still_part_of_the_set(
    tmp_path: Path,
) -> None:
    """RFC 5545 puts ``DTSTART`` in the recurrence set whatever the rule selects.

    A ``FREQ=WEEKLY;BYDAY=TU`` rule whose ``DTSTART`` is a Monday is
    under-synchronised rather than start-less, and dropping the one occurrence the
    source states outright would be the wrong reading of a sloppy file. The
    ordinary synchronised case is absorbed by de-duplication, which is why the
    counts elsewhere in this module are unchanged.
    """
    raw = calendar(
        vevent(
            # 3 August 2026 is a Monday; the rule selects Tuesdays.
            "DTSTART:20260803T090000Z",
            "DURATION:PT1H",
            "RRULE:FREQ=WEEKLY;BYDAY=TU",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    assert await _occurrences(source(tmp_path, raw)) == [
        (3, "09:00", "Standup"),
        (4, "09:00", "Standup"),
    ]


def _custom_timezone(tzid: str, *, dst: bool = False, offset: str = "+0000") -> str:
    """A ``VTIMEZONE`` whose ``TZID`` is whatever the case wants it to be.

    With ``dst``, it also carries a March transition, so a recurrence crossing it
    changes offset the way a real zone's would. ``offset`` sets the standard
    offset in ``TZOFFSETTO`` form, which RFC 5545 allows to carry seconds; it is
    ignored under ``dst``, whose two offsets are the transition's point.
    """
    daylight = (
        [
            "BEGIN:DAYLIGHT",
            "DTSTART:19700308T020000",
            "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
            "TZOFFSETFROM:-0500",
            "TZOFFSETTO:-0400",
            f"TZNAME:{tzid}-DT",
            "END:DAYLIGHT",
        ]
        if dst
        else []
    )
    return "\r\n".join(
        [
            "BEGIN:VTIMEZONE",
            f"TZID:{tzid}",
            "BEGIN:STANDARD",
            "DTSTART:19701101T020000",
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
            "TZOFFSETFROM:-0400" if dst else f"TZOFFSETFROM:{offset}",
            "TZOFFSETTO:-0500" if dst else f"TZOFFSETTO:{offset}",
            f"TZNAME:{tzid}-ST",
            "END:STANDARD",
            *daylight,
            "END:VTIMEZONE",
        ]
    )


async def test_a_source_supplied_zone_name_never_reaches_the_rendering(tmp_path: Path) -> None:
    """The zone label carries no source text, which closes a content-budget route.

    A ``TZID`` naming a custom ``VTIMEZONE`` resolves to a tzinfo whose ``str`` is
    a repr wrapped around that identifier, and ``TZNAME`` is source text too —
    both unbounded, both repeated once per occurrence, and neither reached by a
    cap on summaries. Rendering the numeric offset instead makes the label bounded
    by construction, which is what ADR-0093 §7a's bound needs and what makes
    charging it per occurrence free.
    """
    tzid = "Z" * 250
    raw = calendar(
        _custom_timezone(tzid),
        vevent(
            f"DTSTART;TZID={tzid}:20260803T120000",
            "DURATION:PT1H",
            "SUMMARY:x",
            uid="one",
        ),
    )
    path = source(tmp_path, raw)

    reading = await reader(path, max_content_bytes=10_000).read()

    (proposal,) = reading.proposals
    assert tzid not in proposal.proposed.content
    assert "tzicalvtz" not in proposal.proposed.content
    assert proposal.proposed.content == (
        'Calendar entry "x", on 2026-08-03 from 12:00 to 13:00 (UTC+00:00).'
    )

    # And the label is charged: a budget that cannot hold one proposal refuses
    # rather than building it.
    with pytest.raises(ReaderError) as raised:
        await reader(path, max_content_bytes=1).read()
    assert isinstance(raised.value.__cause__, ContentBudgetExhaustedError)


async def test_a_sub_minute_zone_offset_keeps_its_seconds_in_the_label(tmp_path: Path) -> None:
    """``UTC±HH:MM`` is exact only while the offset is a whole number of minutes.

    RFC 5545's ``TZOFFSETTO`` carries seconds, and a label that drops them names a
    *different* instant from the one printed beside it: ``+005328`` puts a 13:00
    local start at 12:06:32Z, which ``UTC+00:53`` renders as 12:06:00Z — an offset
    the source never declared, stated as if it had. That is the worse of the two
    ways to be wrong, because the label and the local time still look consistent.

    Only the label was ever affected — ``start`` and ``end`` come from the tzinfo
    itself — so the case pins **both**: the rendered label and the instant the
    facet reports for the same occurrence, which agree only if the seconds survive.

    An IANA zone cannot reach this path, since it is named by its key, so it takes
    a hand-written ``VTIMEZONE``. Sub-minute offsets are not contrived: LMT offsets
    carry them (``Asia/Kolkata`` was ``+05:53:28`` in 1900), they just arrive as
    ``ZoneInfo`` and take the key path.
    """
    raw = calendar(
        _custom_timezone("Corp/LMT", offset="+005328"),
        vevent(
            "DTSTART;TZID=Corp/LMT:20260803T130000",
            "DURATION:PT1H",
            "SUMMARY:x",
            uid="one",
        ),
    )

    reading = await reader(source(tmp_path, raw)).read()

    (proposal,) = reading.proposals
    assert proposal.proposed.content == (
        'Calendar entry "x", on 2026-08-03 from 13:00 to 14:00 (UTC+00:53:28).'
    )
    assert isinstance(reading.facet, CalendarFacet)
    assert reading.facet.next_starts_at == datetime(2026, 8, 3, 12, 6, 32, tzinfo=UTC)


async def test_a_sub_minute_zone_offset_west_of_utc_keeps_its_sign_and_its_seconds(
    tmp_path: Path,
) -> None:
    """The east-of-UTC case above, mirrored — because the sign and the seconds are
    computed on separate lines.

    ``_zone_label`` takes the sign off the *signed* total and then formats
    ``abs(total)``, so a negative offset with seconds exercises a combination the
    positive case cannot reach: ``-005328`` is ``-3208`` seconds, whose remainder is
    only correct because the components are taken from the absolute value. Reading
    the seconds off the signed total instead would render ``UTC-00:-53:-28`` here
    while leaving the case above green.

    Coverage rather than a defect: west-of-UTC renders correctly today, and this is
    the assertion that holds it there. It pins **both** halves for the same reason
    the positive case does — the label and the instant the facet reports agree only
    if the offset is read the same way twice. 13:00 local at ``-00:53:28`` is
    13:53:28Z, an hour and a half from the positive case's answer.
    """
    raw = calendar(
        _custom_timezone("Corp/WLMT", offset="-005328"),
        vevent(
            "DTSTART;TZID=Corp/WLMT:20260803T130000",
            "DURATION:PT1H",
            "SUMMARY:x",
            uid="one",
        ),
    )

    reading = await reader(source(tmp_path, raw)).read()

    (proposal,) = reading.proposals
    assert proposal.proposed.content == (
        'Calendar entry "x", on 2026-08-03 from 13:00 to 14:00 (UTC-00:53:28).'
    )
    assert isinstance(reading.facet, CalendarFacet)
    assert reading.facet.next_starts_at == datetime(2026, 8, 3, 13, 53, 28, tzinfo=UTC)


async def test_a_recurrence_across_a_dst_transition_labels_each_occurrence_itself(
    tmp_path: Path,
) -> None:
    """An offset is a property of *when*, so the label is read per occurrence.

    A label fixed from the component's ``DTSTART`` states the pre-transition
    offset for every occurrence after it — the belief then names a zone offset the
    source does not have on that date, while the time beside it is correct, which
    is the worst of the two ways to be wrong because it looks consistent.
    """
    raw = calendar(
        _custom_timezone("Corp/HQ", dst=True),
        vevent(
            "DTSTART;TZID=Corp/HQ:20260307T090000",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY;COUNT=3",
            "SUMMARY:Standup",
            uid="series",
        ),
    )

    reading = await reader(
        source(tmp_path, raw),
        now=lambda: datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
        window_past=timedelta(days=2),
        window_future=timedelta(days=2),
    ).read()

    labels = [proposal.proposed.content.rsplit("(", 1)[1] for proposal in reading.proposals]
    assert labels == ["UTC-05:00).", "UTC-04:00).", "UTC-04:00)."]


async def test_an_iana_zone_is_named_by_its_key_across_a_transition(tmp_path: Path) -> None:
    """A key names the *zone*, not the offset, so it is stable and preferred.

    It is also what a user recognises: ``America/New_York`` says more than
    ``UTC-05:00``, and unlike an abbreviation it does not go stale in March.
    """
    raw = calendar(
        vevent(
            "DTSTART;TZID=America/New_York:20260307T090000",
            "DURATION:PT1H",
            "RRULE:FREQ=DAILY;COUNT=3",
            "SUMMARY:Standup",
            uid="series",
        )
    )

    reading = await reader(
        source(tmp_path, raw),
        now=lambda: datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
        window_past=timedelta(days=2),
        window_future=timedelta(days=2),
    ).read()

    labels = {proposal.proposed.content.rsplit("(", 1)[1] for proposal in reading.proposals}
    assert labels == {"America/New_York)."}
