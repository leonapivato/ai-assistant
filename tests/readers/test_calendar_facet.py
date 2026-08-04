"""The calendar reader's situational half: the facet it builds (ADR-0096 §6, §8).

ADR-0093 §3 splits one reading between two consumers at two cadences, and this is
the half that reaches the situational context rather than memory. ADR-0096 §8
assigns it to the reader — the adapter may not build one, because an adapter
building its own would be stamping a value with instants it never observed.

**Every case here is about the three scalars and the window edge**, and none about
what an entry says: the facet carries no summary, location, description,
organiser, attendee or identifier, and there is no field on it to assert one
against. That absence is the ruling (ADR-0096 §6), and under ADR-0098 §5 it is
what keeps attacker-authored strings off the facet path entirely.

The window here is :func:`ics_fixtures.reader`'s narrow default — ``NOW`` at
12:00Z with two hours each way, so ``[10:00, 14:00)`` — which is what lets a case
name a boundary instant a reader of the test can see.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ics_fixtures import NOW, calendar, frozen, reader, source, utc, vevent

from ai_assistant.core.types import CalendarFacet
from ai_assistant.readers import CALENDAR_READER_NAME

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


def _entry(
    start: datetime, *, duration: str = "PT1H", uid: str = "e1", summary: str = "Thing"
) -> str:
    """One stamped ``VEVENT`` starting at ``start``."""
    return vevent(f"DTSTART:{utc(start)}", f"DURATION:{duration}", f"SUMMARY:{summary}", uid=uid)


async def _facet_of(tmp_path: Path, *events: str, **overrides: object) -> CalendarFacet:
    """Read a calendar of ``events`` and return the facet it carried."""
    reading = await reader(source(tmp_path, calendar(*events)), **overrides).read()
    assert reading.facet is not None
    return reading.facet


# --- the stamp: the facet is the reading's, not a value of its own -----------


async def test_a_reading_carries_a_facet_stamped_exactly_as_the_reading_is(
    tmp_path: Path,
) -> None:
    """ADR-0096 §5: the facet's stamp is the carrying reading's, unchanged.

    ``SourceReading``'s validator refuses anything else, so this is less a check on
    the reader than a check that the reader is *reachable* through it — a producer
    that stamped its facet from a second clock reading would fail at construction
    rather than here. What this pins is the value the adapter will lift out, where
    the reading is gone and the stamp is the only thing left saying who produced it
    and when.
    """
    reading = await reader(source(tmp_path, calendar(_entry(NOW)))).read()

    assert reading.facet is not None
    assert reading.facet.source == reading.source == CALENDAR_READER_NAME
    assert reading.facet.read_at == reading.read_at == NOW
    assert reading.facet.as_of is reading.as_of is None


async def test_the_facet_declares_no_as_of_because_the_source_declares_none(
    tmp_path: Path,
) -> None:
    """A local ``.ics`` makes no reading-level claim about when it was current.

    The ``None`` is load-bearing rather than an omission: the format's report times
    are per-``VEVENT``, and the file's mtime is a fact about our filesystem that
    moves under a copy, a restore or a ``touch``. ADR-0096 §2 refuses it by name,
    for ADR-0092 §3's reason — a facet is a **weaker** record than a belief, so it
    does not get a licence a belief is denied.
    """
    assert (await _facet_of(tmp_path, _entry(NOW))).as_of is None


# --- entries_in_progress: §6's membership rule, at an instant ----------------


async def test_an_entry_spanning_the_read_instant_is_in_progress(tmp_path: Path) -> None:
    """The entry the facet most wants: the meeting happening now (ADR-0093 §7b)."""
    facet = await _facet_of(tmp_path, _entry(NOW - timedelta(minutes=30)))

    assert facet.entries_in_progress == 1


async def test_an_entry_starting_exactly_at_the_read_instant_is_in_progress(
    tmp_path: Path,
) -> None:
    """``start <= read_at``: the lower edge is inclusive."""
    assert (await _facet_of(tmp_path, _entry(NOW))).entries_in_progress == 1


async def test_an_entry_ending_exactly_at_the_read_instant_is_not_in_progress(
    tmp_path: Path,
) -> None:
    """``read_at < end``: the upper edge is exclusive.

    Half-open, so a meeting that ended on the hour is over on the hour. The
    alternative would report an entry as current for the instant after it stopped,
    which is the direction that produces a wrong answer rather than a debatable
    one.
    """
    ended = await _facet_of(tmp_path, _entry(NOW - timedelta(hours=1)))

    assert ended.entries_in_progress == 0


async def test_an_entry_yet_to_start_is_not_in_progress(tmp_path: Path) -> None:
    facet = await _facet_of(tmp_path, _entry(NOW + timedelta(minutes=30)))

    assert facet.entries_in_progress == 0


async def test_a_zero_duration_entry_is_in_progress_only_at_its_own_instant(
    tmp_path: Path,
) -> None:
    """ADR-0096 §6's second arm, which exists for ADR-0093 §7b's reason.

    A half-open interval of zero width contains nothing, so a reminder expressed as
    an instant would be *never* in progress under the first arm alone — the entry
    vanishing rather than its boundary being debatable.
    """
    at_now = await _facet_of(tmp_path, _entry(NOW, duration="PT0S"))
    elsewhere = await _facet_of(tmp_path, _entry(NOW + timedelta(minutes=1), duration="PT0S"))

    assert at_now.entries_in_progress == 1
    assert elsewhere.entries_in_progress == 0


async def test_overlapping_entries_are_counted_rather_than_collapsed(tmp_path: Path) -> None:
    """A count rather than a ``busy: bool``, and the difference is a ruling.

    ``busy`` has to decide what counts as busy, and the first case breaks it: an
    all-day "Holiday" covers the instant and is not a meeting. Choosing is a
    judgement about the user's day, and ADR-0093 §2 rules that "A reader infers
    nothing: it reads a file and reports what the file says".
    """
    facet = await _facet_of(
        tmp_path,
        _entry(NOW - timedelta(minutes=30), uid="a", summary="Standup"),
        _entry(NOW - timedelta(minutes=10), uid="b", summary="Interrupt"),
    )

    assert facet.entries_in_progress == 2


async def test_an_all_day_entry_covering_the_instant_counts(tmp_path: Path) -> None:
    """Because the reader is not the one deciding whether a holiday is "busy"."""
    facet = await _facet_of(
        tmp_path,
        vevent(
            "DTSTART;VALUE=DATE:20260803",
            "DTEND;VALUE=DATE:20260804",
            "SUMMARY:Holiday",
        ),
    )

    assert facet.entries_in_progress == 1


# --- next_starts_at: the earliest start strictly after the read instant ------


async def test_the_next_start_is_the_earliest_one_after_the_read_instant(
    tmp_path: Path,
) -> None:
    """Earliest, not first-encountered: the value does not lean on parse order."""
    facet = await _facet_of(
        tmp_path,
        _entry(NOW + timedelta(minutes=90), uid="late", summary="Later"),
        _entry(NOW + timedelta(minutes=30), uid="soon", summary="Sooner"),
    )

    assert facet.next_starts_at == NOW + timedelta(minutes=30)


async def test_an_entry_starting_exactly_now_is_in_progress_and_not_next(
    tmp_path: Path,
) -> None:
    """ "Strictly after" is what keeps the two fields from double-counting one entry.

    An entry starting at ``read_at`` is happening, not upcoming, and reporting it
    as both would let a surface say "starting now" about the thing it also said was
    in progress.
    """
    facet = await _facet_of(tmp_path, _entry(NOW))

    assert facet.entries_in_progress == 1
    assert facet.next_starts_at is None


async def test_no_later_entry_in_the_window_leaves_the_next_start_absent(
    tmp_path: Path,
) -> None:
    """And it says the reading found none **within its window** (ADR-0096 §6).

    Never that none exists — which is why ``covers_until`` travels beside it. The
    entry below starts three hours out, comfortably past the two-hour window, so
    the source really does hold a later occurrence that this reading did not see.
    """
    facet = await _facet_of(tmp_path, _entry(NOW + timedelta(hours=3)))

    assert facet.next_starts_at is None
    assert facet.covers_until == NOW + timedelta(hours=2)


# --- covers_until: what makes the absence above interpretable ----------------


async def test_covers_until_is_the_windows_exclusive_upper_edge(tmp_path: Path) -> None:
    """One field rather than two, and the forward edge is the one that is read.

    A consumer of ``CurrentContext`` does not read ``Settings``, so the horizon has
    to travel with the value or not exist. The backward edge is not carried because
    nothing a consumer reads is bounded by it: ``entries_in_progress`` is anchored
    at ``read_at``, and §7b's overlap membership already guarantees that an
    occurrence which began before the window and is still running is in the
    reading (which the first case in this file relies on).
    """
    facet = await _facet_of(
        tmp_path,
        _entry(NOW),
        window_future=timedelta(days=3),
        window_past=timedelta(hours=1),
    )

    assert facet.covers_until == NOW + timedelta(days=3)


async def test_a_saturating_window_leaves_covers_until_representable(tmp_path: Path) -> None:
    """Both edges saturate under ADR-0093 §7b, so this is always an instant.

    A ten-year window from a clock near the representable ceiling is the case that
    would otherwise raise — and it would raise *after* a source that parsed
    perfectly, escaping ADR-0093 §8's two outcomes entirely.
    """
    late = NOW.replace(year=9999, month=12, day=30)
    facet = await _facet_of(
        tmp_path,
        _entry(late),
        now=frozen(late),
        window_future=timedelta(days=3650),
    )

    assert facet.covers_until.year == 9999
    assert isinstance(facet, CalendarFacet)


# --- the two halves of one reading may describe different sets --------------


async def test_an_unstamped_entry_is_counted_in_the_facet_and_missing_from_the_proposals(
    tmp_path: Path,
) -> None:
    """ADR-0096 §5's named asymmetry, pinned so nobody "fixes" it.

    ``_propose`` skips an occurrence with no ``DTSTAMP`` because ADR-0092 §3
    permits no substitute for a report time the source did not make. The facet is
    making no attestation and owes no report time, so it counts it. The two halves
    therefore describe overlapping-but-unequal sets, which ADR-0093 §3 already
    rules is the design: "What matters is not that they agree but that neither is
    mistaken for the other."

    It looks like a bug to whoever finds it first, which is exactly why it is a
    test rather than a comment.
    """
    unstamped = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:b",
            f"DTSTART:{utc(NOW - timedelta(minutes=15))}",
            "DURATION:PT1H",
            "SUMMARY:Unstamped",
            "END:VEVENT",
        ]
    )

    reading = await reader(source(tmp_path, calendar(unstamped))).read()

    assert reading.proposals == ()
    assert reading.facet is not None
    assert reading.facet.entries_in_progress == 1


# --- an empty window is a facet, not an absent one ---------------------------


async def test_a_source_with_nothing_in_the_window_still_carries_a_facet(
    tmp_path: Path,
) -> None:
    """An empty reading is a **success** (ADR-0093 §8), and it has something to say.

    "Nothing is happening and nothing is next within the next two hours" is a
    situational fact, and it is the one a facet withheld here would leave the
    consumer unable to distinguish from a source that was never read.
    """
    facet = await _facet_of(tmp_path, _entry(NOW + timedelta(days=30)))

    assert facet.entries_in_progress == 0
    assert facet.next_starts_at is None
    assert facet.covers_until == NOW + timedelta(hours=2)


async def test_an_empty_calendar_still_carries_a_facet(tmp_path: Path) -> None:
    """The same, with no entries in the source at all."""
    facet = await _facet_of(tmp_path)

    assert facet.entries_in_progress == 0
    assert facet.next_starts_at is None


async def test_each_read_recomputes_the_facet_against_the_moving_window(
    tmp_path: Path,
) -> None:
    """No cursor and no cached facet: the window moves with the clock (ADR-0093 §5).

    The same file, read at two instants an hour apart, answers differently about
    the same entry — in progress at the first and over at the second. That is the
    property ADR-0096 §3's no-cache clause is checkable against: a facet whose
    ``read_at`` did not move is a cache someone introduced.
    """
    path = source(tmp_path, calendar(_entry(NOW)))
    later = NOW + timedelta(hours=1, minutes=30)

    during = await reader(path).read()
    after = await reader(path, now=frozen(later)).read()

    assert during.facet is not None
    assert after.facet is not None
    assert during.facet.entries_in_progress == 1
    assert after.facet.entries_in_progress == 0
    assert after.facet.read_at == later
