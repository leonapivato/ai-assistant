"""ADR-0093 §7b's window: overlap, half-open edges, saturation and localisation.

Three of these are not the concrete reader's to settle, and §7b says why: two
implementations can satisfy §7a's table exactly and still disagree, and **§5's
no-cursor result is false under the wrong choice**. So each case here pins a
ratified clause rather than a preference.

With the fixtures' clock at 12:00Z and a two-hour window each way, the window is
``[10:00, 14:00)`` — chosen so that "exactly at the lower edge" names an instant a
reader of the test can see without arithmetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import NOW, calendar, reader, source, utc, vevent

if TYPE_CHECKING:
    from pathlib import Path

_LOWER = NOW - timedelta(hours=2)
_UPPER = NOW + timedelta(hours=2)


async def _titles(path: Path, **overrides: object) -> list[str]:
    reading = await reader(path, **overrides).read()
    return [proposal.proposed.content.split('"')[1] for proposal in reading.proposals]


def _entry(uid: str, start: datetime, end: datetime, summary: str) -> str:
    return vevent(f"DTSTART:{utc(start)}", f"DTEND:{utc(end)}", f"SUMMARY:{summary}", uid=uid)


# --- overlap, never the start instant alone ---------------------------------


async def test_an_event_that_began_before_the_window_and_is_still_running_is_in(
    tmp_path: Path,
) -> None:
    """The clause that would have broken the ADR.

    Under start-instant membership, an event that began before the window and is
    still running is excluded by *every* future run — the window moves forward and
    the event's start recedes — so it is permanently unreachable. That is exactly
    the coverage failure §5 argues a reader does not have, reintroduced by a filter
    choice rather than by a missing cursor, and it fails hardest on the entry the
    facet most wants: the meeting happening now.
    """
    raw = calendar(_entry("a", _LOWER - timedelta(hours=1), NOW + timedelta(minutes=30), "Running"))

    assert await _titles(source(tmp_path, raw)) == ["Running"]


async def test_an_event_that_starts_inside_and_ends_after_the_window_is_in(
    tmp_path: Path,
) -> None:
    raw = calendar(_entry("a", NOW + timedelta(hours=1), _UPPER + timedelta(hours=3), "Spanning"))

    assert await _titles(source(tmp_path, raw)) == ["Spanning"]


# --- half-open, on both edges (ADR-0093 §7b) --------------------------------


@pytest.mark.parametrize(
    ("name", "start", "end", "present"),
    [
        # `end > window_start` is false, so it is out. Half-open is chosen because
        # adjacent windows then partition time without double-counting — and with
        # the entry cap otherwise exactly filled, this single entry is the
        # difference between a successful read and a refusal, from identical
        # settings and an identical clock.
        ("ends exactly at the lower edge", _LOWER - timedelta(hours=1), _LOWER, False),
        ("starts exactly at the lower edge", _LOWER, _LOWER + timedelta(hours=1), True),
        ("ends exactly at the upper edge", _UPPER - timedelta(hours=1), _UPPER, True),
        # `start < window_end` is false.
        ("starts exactly at the upper edge", _UPPER, _UPPER + timedelta(hours=1), False),
    ],
)
async def test_a_non_zero_duration_entry_on_an_edge(
    tmp_path: Path, name: str, start: datetime, end: datetime, present: bool
) -> None:
    raw = calendar(_entry("a", start, end, "Edge"))

    assert await _titles(source(tmp_path, raw)) == (["Edge"] if present else []), name


@pytest.mark.parametrize(
    ("name", "start", "present"),
    [
        # The general overlap test degenerates here: `end > window_start` is false
        # for an instant sitting exactly *on* `window_start`, which would silently
        # exclude the one entry shape that has no duration to spare — hence §7b's
        # separate arm, `window_start <= start < window_end`.
        ("exactly on the lower edge", _LOWER, True),
        ("just inside the upper edge", _UPPER - timedelta(seconds=1), True),
        ("exactly on the upper edge", _UPPER, False),
    ],
)
async def test_a_zero_duration_entry_on_an_edge(
    tmp_path: Path, name: str, start: datetime, present: bool
) -> None:
    raw = calendar(_entry("a", start, start, "Instant"))

    assert await _titles(source(tmp_path, raw)) == (["Instant"] if present else []), name


async def test_an_all_day_entry_at_each_edge_of_a_day_scale_window(tmp_path: Path) -> None:
    """A date-valued entry covers ``[midnight, next midnight)`` in the configured zone.

    With the window ``[2026-08-02 12:00, 2026-08-04 12:00)`` in UTC, the 1 August
    entry has already ended, the 2 August one is still running when the window
    opens, the 4 August one starts inside it, and the 5 August one has not begun.
    """
    raw = calendar(
        vevent(
            "DTSTART;VALUE=DATE:20260801", "DTEND;VALUE=DATE:20260802", "SUMMARY:Before", uid="1"
        ),
        vevent(
            "DTSTART;VALUE=DATE:20260802", "DTEND;VALUE=DATE:20260803", "SUMMARY:Lower", uid="2"
        ),
        vevent(
            "DTSTART;VALUE=DATE:20260804", "DTEND;VALUE=DATE:20260805", "SUMMARY:Upper", uid="3"
        ),
        vevent(
            "DTSTART;VALUE=DATE:20260805", "DTEND;VALUE=DATE:20260806", "SUMMARY:After", uid="4"
        ),
    )

    titles = await _titles(
        source(tmp_path, raw), window_past=timedelta(days=1), window_future=timedelta(days=1)
    )

    assert titles == ["Lower", "Upper"]


# --- localisation and DST (ADR-0093 §7b) ------------------------------------


async def test_a_floating_entry_is_localised_in_the_configured_zone(tmp_path: Path) -> None:
    """A reader may not invent a second timezone source.

    Two components resolving "today" against different zones is the class of defect
    ADR-0026 exists to prevent, arriving through data rather than through a clock.
    A floating 08:00 is 12:00Z in ``America/New_York`` in August, and 08:00Z in UTC
    — so the same file read under two zones selects different entries, which is why
    the zone is the configured one and not the reader's guess.
    """
    raw = calendar(vevent("DTSTART:20260803T080000", "DURATION:PT1H", "SUMMARY:Floating"))
    path = source(tmp_path, raw)

    assert await _titles(path, timezone="America/New_York") == ["Floating"]
    assert await _titles(path, timezone="UTC") == []


@pytest.mark.parametrize(
    ("name", "local", "resolved"),
    [
        # 01:30 happens twice on 1 November 2026 in America/New_York. `fold=0`
        # names the earlier offset — EDT, -04:00 — which is 05:30Z.
        ("ambiguous", "20261101T013000", datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
        # 02:30 happens never on 8 March 2026. `fold=0` resolves it through the
        # pre-transition offset — EST, -05:00 — which is 07:30Z.
        ("nonexistent", "20260308T023000", datetime(2026, 3, 8, 7, 30, tzinfo=UTC)),
    ],
)
async def test_a_floating_time_on_a_dst_transition_resolves_at_fold_zero(
    tmp_path: Path, name: str, local: str, resolved: datetime
) -> None:
    """RFC 5545 does not settle this, so the requirement is **agreement**.

    A floating time is under-specified *by the source*, so no reading recovers the
    author's intent — which makes the cheapest available agreement the right
    answer, and ``fold=0`` is the platform default in both directions with no
    special case.

    **Not skipping is the other half, and it is the half the user feels.** §7b
    skips an entry the reader *cannot interpret*; a time on a transition is
    interpretable the moment a rule exists, and the entry is a real appointment
    someone holds. Skipping would drop an hour of a calendar twice a year — and §4
    forbids the reader saying anything about the absence, so the loss would also be
    silent.
    """
    raw = calendar(vevent(f"DTSTART:{local}", "DURATION:PT1H", "SUMMARY:Transition"))
    path = source(tmp_path, raw)

    inside = await _titles(path, timezone="America/New_York", now=lambda: resolved)
    assert inside == ["Transition"], name

    # An hour before the resolved instant the window has not reached it, which is
    # what makes the case above an assertion about *which* instant was chosen
    # rather than merely that something was proposed.
    missed = await _titles(
        path,
        timezone="America/New_York",
        now=lambda: resolved - timedelta(hours=4),
        window_past=timedelta(hours=1),
        window_future=timedelta(hours=1),
    )
    assert missed == [], name


# --- saturation (ADR-0093 §7b) ----------------------------------------------


async def test_a_window_that_would_overflow_saturates_rather_than_raising(
    tmp_path: Path,
) -> None:
    """A clock near the representable maximum must not become a source fault.

    The bounded figures make an overflow unreachable from configuration alone, but
    not from configuration *and* a clock, and a reader is not entitled to assume
    where in time the clock sits. Saturation is total where a check is conditional
    and it loses nothing — there is no entry beyond the maximum representable
    instant to exclude, so the clamped window and the ideal one select the same
    set. It is deliberately **not** a refusal: a clock that near the limit is a
    wiring problem the reader neither causes nor can diagnose, and a
    ``ReaderError`` would report a source fault against a source that is fine.
    """
    late = datetime.max.replace(tzinfo=UTC) - timedelta(days=2)
    start = late + timedelta(hours=1)
    raw = calendar(_entry("a", start, start + timedelta(hours=1), "Late"))

    titles = await _titles(
        source(tmp_path, raw),
        now=lambda: late,
        window_past=timedelta(days=1),
        window_future=timedelta(days=3650),
    )

    assert titles == ["Late"]


async def test_the_lower_edge_saturates_too(tmp_path: Path) -> None:
    early = datetime.min.replace(tzinfo=UTC) + timedelta(days=2)
    start = early - timedelta(hours=1)
    raw = calendar(_entry("a", start, start + timedelta(hours=2), "Early"))

    titles = await _titles(
        source(tmp_path, raw),
        now=lambda: early,
        window_past=timedelta(days=3650),
        window_future=timedelta(days=1),
    )

    assert titles == ["Early"]


# --- a gap inside a readable source is a skip, not a raise (ADR-0093 §7b) ---


async def test_an_uninterpretable_entry_among_valid_ones_is_skipped(tmp_path: Path) -> None:
    """A read that *completed with gaps* is not one that *could not complete*.

    ADR-0074 §5's rule carried unchanged — "an id that does not resolve is
    **skipped, not an error**" — which ADR-0077 §8 applied with "a short batch is
    the honest consequence of a gap". Skipping proposes nothing about the skipped
    entry, so §4's absence rule is respected rather than strained.
    """
    broken = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:broken",
            "DTSTAMP:20260101T000000Z",
            "SUMMARY:No start at all",
            "END:VEVENT",
        ]
    )
    raw = calendar(_entry("ok", NOW, NOW + timedelta(hours=1), "Valid"), broken)

    assert await _titles(source(tmp_path, raw)) == ["Valid"]


async def test_an_entry_whose_local_end_is_unrepresentable_saturates_too(
    tmp_path: Path,
) -> None:
    """Saturation covers the **wall-clock** arithmetic as well as the UTC instants.

    ``read_at ± window`` is not the only computed instant near the bound: an entry
    at ``9999-12-31`` with a two-day duration is a perfectly valid entry inside a
    perfectly valid window whose *local* end is not representable. Computed
    unguarded, the ``OverflowError`` reaches §8 as a source fault against a source
    that is fine — the exact outcome §7b's "none of this arithmetic raises" exists
    to prevent, and one the UTC-side clamp does not cover because the entry is
    rendered from its own zone.
    """
    raw = calendar(vevent("DTSTART:99991231T000000Z", "DURATION:P2D", "SUMMARY:Last call"))

    titles = await _titles(
        source(tmp_path, raw),
        now=lambda: datetime.max.replace(tzinfo=UTC) - timedelta(days=2),
        window_past=timedelta(hours=2),
        window_future=timedelta(days=3650),
    )

    assert titles == ["Last call"]


async def test_a_degenerate_all_day_entry_at_the_minimum_date_still_renders(
    tmp_path: Path,
) -> None:
    """Rendering computes an instant too, and §7b's saturation covers it.

    ``DTEND`` equal to ``DTSTART`` on a ``DATE`` value is degenerate but
    parseable, and stepping back a day from its exclusive end to name the span's
    last date is not representable at ``0001-01-01``. Unguarded that raises, and
    §8 then reports a source fault against a source that parsed perfectly — which
    is the failure the saturation rule exists to prevent, arriving through the one
    arithmetic nobody counts as arithmetic.

    The entry is **not** skipped for being degenerate: §7b skips what the reader
    cannot interpret, and a zero-width day is interpretable — it is the
    zero-duration arm of the overlap test, which the entry satisfies.
    """
    raw = calendar(
        vevent(
            "DTSTART;VALUE=DATE:00010101",
            "DTEND;VALUE=DATE:00010101",
            "SUMMARY:Dawn of time",
        )
    )

    titles = await _titles(
        source(tmp_path, raw),
        now=lambda: datetime.min.replace(tzinfo=UTC) + timedelta(days=2),
        window_past=timedelta(days=3650),
        window_future=timedelta(days=1),
    )

    assert titles == ["Dawn of time"]
