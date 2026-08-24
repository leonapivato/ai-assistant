"""A ``VTIMEZONE`` one read defines, resolving in a later read that never did (#1497).

Found while writing #1491's fix, and not caused by it. ``icalendar`` 7.2.2 keeps
the timezones it builds from parsed ``VTIMEZONE`` components in a cache that lives
on the ``icalendar.timezone.tzp`` **module-level singleton**, so it is per
*process* rather than per ``Calendar.from_ical`` call:
``TZP.cache_timezone_component`` writes every id the provider does not already
know, and ``TZP.timezone`` consults the cache as its last resort. The hub is one
resident process reading the source on a timer (ADR-0093 §7), so before this
module's fix a definition that appeared in the source **once** kept resolving that
``TZID``, at whatever offset it declared, for every later read — including reads of
a different file, and reads of the same file after the definition was removed.

**Why that is this seam's problem rather than a library curiosity.**

* ADR-0183 §1 makes whoever can place bytes in the source the adversary, and §1's
  ladder is about what each rung *reaches*. A cache that outlives the read lets a
  rung that could place bytes once keep an offset alive across every later read it
  no longer influences.
* ADR-0183 §5 admits resolving a source-supplied name only against "a **fixed
  local namespace the source cannot direct or extend**". A cache the source writes
  into, and which survives the read that wrote it, is precisely a namespace the
  source extends — so the isolation is what keeps that clause's premise true for
  the second read, not an extra defence beyond it.
* ADR-0093 §5's no-cursor argument rests on the property ``_occurrences`` states in
  its own first line: "Everything here is a function of the source's bytes, one
  clock reading and the configuration". A process-global cache makes a reading a
  function of **read order** as well, which is the one thing that section leans on
  being false.
* The reach is concrete rather than theoretical. #1491's rule skips an entry whose
  stated zone did not resolve and withholds the reading's coverage (ADR-0117 §5);
  a leaked definition makes the same entry *resolve*, so it is proposed as an
  attested belief at an instant nobody wrote — the substitution #1491 closed,
  re-opened through a different door.

**What the fix does not change, and each case here says so.** A zone the source
defines still resolves **within the read that defines it**, in either component
order, because that is one document read whole and it is how every CalDAV server
emitting a non-IANA ``TZID`` stays readable (#1499). And an IANA key is never
shadowed: the cache is consulted after the provider, so a source's own
``VTIMEZONE:TZID=Europe/Rome`` was inert before this change and is inert after it.

Refs #1497, #1491, ADR-0183 §1/§5, ADR-0093 §5/§7/§7b, ADR-0117 §5.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from icalendar import Calendar
from icalendar.timezone import tzp
from ics_fixtures import NOW, calendar, reader, source, summaries, utc, vevent

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.types import SourceReading

#: The zone the hub is configured with in these cases, two hours ahead of UTC in
#: August. Distinct from the offset the planted ``VTIMEZONE`` declares, so a
#: rendering names which of the two was used.
_ROME: Final = "Europe/Rome"

#: A non-IANA id, which is the only kind the cache is reachable for at all: the
#: provider is consulted first, so a key the timezone database holds never gets
#: there (pinned by :func:`test_an_iana_key_is_never_shadowed_by_the_source`).
_HOSTILE: Final = "Tzcache/Hostile"

#: What the leaked definition declares. Neither UTC nor ``Europe/Rome``, so the
#: rendered label alone says whether a read used it.
_HOSTILE_OFFSET: Final = "+0100"

#: A well-formed entry inside the window, so "the read completed and skipped one
#: entry" and "the read failed" are told apart by the assertion rather than by
#: intent.
_GOOD: Final = vevent(
    f"DTSTART:{utc(NOW)}",
    f"DTEND:{utc(NOW + timedelta(hours=1))}",
    "SUMMARY:standup",
    uid="good",
)

#: What the good entry renders as, once.
_GOOD_RENDERED: Final = 'Calendar entry "standup", on 2026-08-03 from 12:00 to 13:00 (UTC).'

#: What the leaking entry renders as when a definition reaches it. Asserted only
#: as the thing that must **not** appear, and by the library-level case that pins
#: the cache is still process-global.
_LEAKED_RENDERED: Final = (
    'Calendar entry "quarterly review", on 2026-08-03 from 12:30 to 13:00 (UTC+01:00).'
)

#: The mirror of the above, for the concurrent case's second source. A negative
#: offset, so a reading that picked up the *other* thread's zone renders visibly
#: differently rather than by an hour nobody notices.
_WESTERN_RENDERED: Final = (
    'Calendar entry "quarterly review", on 2026-08-03 from 12:30 to 13:00 (UTC-01:00).'
)


def _vtimezone(tzid: str = _HOSTILE, *, offset: str = _HOSTILE_OFFSET) -> str:
    """One ``VTIMEZONE`` at a fixed offset, written out as RFC 5545 lines."""
    return "\r\n".join(
        [
            "BEGIN:VTIMEZONE",
            f"TZID:{tzid}",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            f"TZOFFSETFROM:{offset}",
            f"TZOFFSETTO:{offset}",
            "TZNAME:HOST",
            "END:STANDARD",
            "END:VTIMEZONE",
        ]
    )


def _entry(tzid: str = _HOSTILE, *, uid: str = "leak") -> str:
    """An entry naming ``tzid`` on both ends, and defining nothing.

    12:30 to 13:00 wall time. At the planted ``+01:00`` that is 11:30Z to 12:00Z,
    inside the fixture window ``[10:00Z, 14:00Z)`` — so a leaked definition shows
    up as a **proposal**, not as an entry that silently fell outside the window.
    """
    return vevent(
        f"DTSTART;TZID={tzid}:20260803T123000",
        f"DTEND;TZID={tzid}:20260803T130000",
        "SUMMARY:quarterly review",
        uid=uid,
    )


async def _read(path: Path, **overrides: object) -> SourceReading:
    settings: dict[str, object] = {"timezone": _ROME}
    settings.update(overrides)
    return await reader(path, **settings).read()


def _written(tmp_path: Path, name: str, *parts: str) -> Path:
    return source(tmp_path, calendar(*parts), name=name)


@pytest.fixture(autouse=True)
def _empty_process_cache() -> Iterator[None]:
    """Start and end every case here with the library's cache genuinely empty.

    These cases plant definitions in a **process-global** structure, so without a
    teardown this module would decide what its siblings read — the exact coupling
    it exists to remove. Re-selecting the provider is ``TZP``'s own public reset
    (``TZP._use`` rebinds the cache), and the assertion is here rather than assumed
    so that a case which finds a definition found it because the case planted it.
    """
    tzp.use(tzp.name)
    assert tzp.timezone(_HOSTILE) is None
    yield
    tzp.use(tzp.name)


# --- the defect itself -------------------------------------------------------


async def test_a_definition_from_an_earlier_read_does_not_resolve_in_a_later_one(
    tmp_path: Path,
) -> None:
    """The issue's shape, across two sources, through the real reader.

    The first source defines ``Tzcache/Hostile`` and uses it; the second names it
    and defines nothing. The second read must see what a fresh process would see —
    a stated zone that did not resolve, which #1491's rule skips, withholding the
    reading's coverage. Before the fix it saw ``+01:00`` and proposed the entry.
    """
    defines = _written(tmp_path, "first.ics", _vtimezone(), _entry(uid="defined"))
    names_only = _written(tmp_path, "second.ics", _GOOD, _entry())

    first = await _read(defines)
    later = await _read(names_only)

    assert first.proposals != (), "the defining read is the one that plants the cache"
    assert summaries(later.proposals) == [_GOOD_RENDERED]
    assert _LEAKED_RENDERED not in summaries(later.proposals)
    assert later.coverage is None, "an entry the source holds and this read skipped (§5)"


async def test_a_definition_planted_by_anything_else_in_the_process_does_not_reach_a_read(
    tmp_path: Path,
) -> None:
    """The same defect, with the plant made directly rather than by a first read.

    Isolating at the parse means the reader is unreachable from *whatever* filled
    the cache — a previous read of a different source, another caller of
    ``icalendar`` in the same process, or a test that ran before this one. Planting
    it through ``Calendar.from_ical`` says that in one line, and pins the reader's
    behaviour to the source's bytes rather than to which read got there first.
    """
    Calendar.from_ical(calendar(_vtimezone(), _entry(uid="planted")))
    assert tzp.timezone(_HOSTILE) is not None, "the plant is what this case is about"

    reading = await _read(_written(tmp_path, "names-only.ics", _GOOD, _entry()))

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


async def test_a_read_leaves_no_definition_behind_for_the_next_caller(tmp_path: Path) -> None:
    """Isolation in the outward direction, which is the half a per-read clear misses.

    Emptying the cache only on the way *in* would still hand every later caller of
    ``icalendar`` in this process a zone the source defined — including the next
    reader instance, whose own clear would then be the only thing standing between
    them. Restoring on the way out makes the read leave the process as it found it,
    so the guarantee does not depend on every other caller having one.
    """
    reading = await _read(_written(tmp_path, "defines.ics", _vtimezone(), _entry(uid="defined")))

    assert reading.proposals != ()
    assert tzp.timezone(_HOSTILE) is None


async def test_the_same_bytes_read_twice_produce_the_same_reading(tmp_path: Path) -> None:
    """ADR-0093 §5's premise, asserted at the seam that leans on it.

    A read is meant to be a function of the source's bytes, one clock reading and
    the configuration. Reading a source that *defines* the zone in between is the
    cheapest way to make read order observable, so a reading that survives it
    unchanged is the property §5's no-cursor argument needs — and the property that
    makes a scheduled re-read of an unrepaired source re-propose exactly what the
    last one did.
    """
    names_only = _written(tmp_path, "names-only.ics", _GOOD, _entry())
    defines = _written(tmp_path, "defines.ics", _vtimezone(), _entry(uid="defined"))

    before = await _read(names_only)
    await _read(defines)
    after = await _read(names_only)

    assert summaries(after.proposals) == summaries(before.proposals)
    assert after.coverage == before.coverage


async def test_two_readers_parsing_at_once_each_see_only_their_own_zone(
    tmp_path: Path,
) -> None:
    """The hazard the isolation's own lock exists for, exercised rather than reasoned.

    ADR-0093 §7 reserves one outstanding worker **per reader**, so two readers over
    two configured sources parse on two threads at the same time — and the cache
    they clear is one structure shared by both. An unserialised clear empties the
    other read's in-flight document out from under it, and the other read then
    skips an entry whose zone its own bytes define.

    **A witness rather than a proof, and it is written to say so.** Two threads
    interleaving is the scheduler's decision, so this can only ever demonstrate the
    hazard, never bound it; the documents are padded and the rounds repeated to make
    the overlap likely. It is a sharp witness in practice: with the lock replaced by
    a ``nullcontext`` it failed on the **first** of the twenty rounds, on the padded
    documents below. With the region serialised it passes deterministically, so it
    does not trade a real defect for a flaky suite.
    """
    padding = [
        vevent(f"DTSTART:{utc(NOW)}", f"SUMMARY:filler {n}", uid=f"pad{n}") for n in range(200)
    ]
    first = _written(
        tmp_path,
        "east.ics",
        _vtimezone("Tzcache/East", offset="+0100"),
        *padding,
        _entry("Tzcache/East"),
    )
    second = _written(
        tmp_path,
        "west.ics",
        _vtimezone("Tzcache/West", offset="-0100"),
        *padding,
        _entry("Tzcache/West"),
    )

    for _ in range(20):
        east, west = await asyncio.gather(_read(first), _read(second))
        assert _LEAKED_RENDERED in summaries(east.proposals), "east lost its own definition"
        assert _WESTERN_RENDERED in summaries(west.proposals), "west lost its own definition"


# --- what the isolation may not cost -----------------------------------------


@pytest.mark.parametrize(
    "parts",
    [
        pytest.param((_vtimezone(), _entry()), id="definition-first"),
        pytest.param((_entry(), _vtimezone()), id="entry-first"),
    ],
)
async def test_a_zone_the_source_itself_defines_still_resolves(
    tmp_path: Path, parts: tuple[str, ...]
) -> None:
    """The regression the fix is one line away from causing (#1499).

    A ``VTIMEZONE`` beside the entry that names it is one document, read whole, and
    it must keep resolving — it is how Exchange and every CalDAV server emitting a
    non-IANA ``TZID`` stays readable, and skipping those entries would be a far
    larger loss than the defect this module closes. Both component orders are
    asserted because the cache is written when the ``VTIMEZONE`` component *ends*,
    so an entry-first document is the order that would break first if the isolation
    were narrowed to the wrong span.

    The label is the numeric offset rather than the id, which is ``_zone_label``'s
    existing bound on source text reaching a rendering (#1499); it is asserted here
    only so this case cannot be read as changing it.
    """
    reading = await _read(_written(tmp_path, "self-contained.ics", *parts))

    assert summaries(reading.proposals) == [_LEAKED_RENDERED]
    assert reading.coverage is not None


async def test_an_iana_key_is_never_shadowed_by_the_source(tmp_path: Path) -> None:
    """A ``VTIMEZONE`` claiming a real key changes nothing, before or after the fix.

    ``TZP.cache_timezone_component`` writes only ids the provider does not already
    know, and ``TZP.timezone`` consults the provider first — so the reachable
    surface has always been non-IANA ids alone. That bound is asserted rather than
    inherited: it is what makes the leak's blast radius the ids nobody else uses,
    and a change in ``icalendar`` that reversed the lookup order would make this
    module's isolation the only thing between a source and the user's own zone.
    """
    hostile_rome = _vtimezone(_ROME, offset="+1000")
    entry = _entry(_ROME, uid="rome")

    reading = await _read(_written(tmp_path, "claims-rome.ics", hostile_rome, entry))

    # Rome's own ``+02:00`` in August, so 12:30 local is 10:30Z — not the ``+10:00``
    # the source declared for the key it does not own.
    assert summaries(reading.proposals) == [
        'Calendar entry "quarterly review", on 2026-08-03 from 12:30 to 13:00 (Europe/Rome).'
    ]
    assert reading.coverage is not None


# --- the library property this isolation exists to contain -------------------


def test_the_librarys_timezone_cache_is_still_process_global() -> None:
    """Why the code under test exists, asserted rather than taken on trust.

    If ``icalendar`` ever scopes this cache to the parse, this case fails and the
    isolation can be revisited on evidence. Without it, the same repair arriving
    upstream would leave a defence in the tree with nothing left to say why —
    and the cases above would keep passing whether or not the reader still did
    anything.

    Nothing here goes through the reader: this is the raw library, planted and read
    back by the same call the reader wraps.
    """
    naive = _dtstart(calendar(_GOOD, _entry()))
    assert naive.tzinfo is None, "a fresh process resolves nothing for a zone nobody defined"

    Calendar.from_ical(calendar(_vtimezone(), _entry(uid="defined")))

    leaked = _dtstart(calendar(_GOOD, _entry()))
    assert leaked.tzinfo is not None
    assert leaked.utcoffset() == timedelta(hours=1)


def _dtstart(raw: bytes) -> datetime:
    """The ``DTSTART`` of the entry naming :data:`_HOSTILE`, straight from the library."""
    for component in Calendar.from_ical(raw).walk("VEVENT"):
        if str(component.get("UID")) == "leak":
            # Read the way `_occurrences` reads it: `icalendar`'s property union has
            # members with no `dt` at all, and the reader never assumes which one it
            # got either.
            value = getattr(component.get("DTSTART"), "dt", None)
            assert isinstance(value, datetime)
            return value
    raise AssertionError("the fixture no longer carries the entry this reads")


def test_the_instants_these_cases_turn_on() -> None:
    """The arithmetic behind every assertion above, checked rather than asserted twice.

    A 12:30 wall time at the planted ``+01:00`` is 11:30Z, inside the fixture window
    ``[10:00Z, 14:00Z)`` — so a leaked definition really would have produced a
    proposal, and the defect cases are not passing because the entry fell outside
    the window for an unrelated reason. If the fixture's clock or window ever moved,
    this fails instead of the cases quietly stopping testing anything.
    """
    planted = datetime(2026, 8, 3, 12, 30, tzinfo=UTC) - timedelta(hours=1)

    assert planted == datetime(2026, 8, 3, 11, 30, tzinfo=UTC)
    assert NOW - timedelta(hours=2) <= planted < NOW + timedelta(hours=2)
