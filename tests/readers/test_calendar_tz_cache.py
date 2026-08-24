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

**And the id-keyed half is the one an "did it resolve" check cannot see.** The
cache is written only for an id it does not already hold, so where a later document
defines the same ``TZID``, the *earlier* file's definition keeps being applied: the
value is aware, the id is the one the source wrote, and only the offsets are
another document's. That is why the fix re-seats every custom zone on the
definition in front of it rather than merely noticing zones that arrived from
nowhere.

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

**What it deliberately leaves alone is the library's cache itself**, and ADR-0096
§5 decides that: three ``CalendarReader`` instances exist so that no consumer waits
on another's read, and emptying one shared structure around the parse needs a lock
that hands that coupling back. The cache therefore still fills; it just no longer
decides anything a reading carries.

Refs #1497, #1491, ADR-0183 §1/§5, ADR-0093 §5/§7/§7b, ADR-0117 §5.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from icalendar import Calendar
from icalendar.timezone import tzp
from ics_fixtures import NOW, calendar, reader, source, summaries, utc, vevent

from ai_assistant.core.errors import ReaderError
from ai_assistant.readers import _occurrences
from ai_assistant.readers._occurrences import SourceNotParseableError

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


def _unbuildable(tzid: str = _HOSTILE) -> str:
    """A ``VTIMEZONE`` carrying a ``TZID`` and nothing a zone can be built from.

    No ``STANDARD`` and no ``DAYLIGHT``, which is ``ValueError: at least one
    component is needed`` from ``to_tz``.
    """
    return "\r\n".join(["BEGIN:VTIMEZONE", f"TZID:{tzid}", "END:VTIMEZONE"])


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


async def test_a_second_definition_of_the_same_id_is_the_one_that_is_applied(
    tmp_path: Path,
) -> None:
    """The half of the leak an id-keyed check would have missed entirely.

    ``TZP.cache_timezone_component`` writes an id **only when the cache does not
    already hold it**, so where two reads define the same ``TZID`` the parser keeps
    answering with the *first* file's definition — same id, the other document's
    offsets, and no naive value anywhere for a "did it resolve" check to notice.
    The second read here defines ``-01:00`` for an id an earlier read defined at
    ``+01:00``, and must be read at the offsets in front of it — two hours' error in
    the direction that would have gone unnoticed, since both readings are
    well-formed, in-window, and carry the id the source wrote.
    """
    earlier = _written(tmp_path, "earlier.ics", _vtimezone(), _entry(uid="defined"))
    later = _written(tmp_path, "later.ics", _vtimezone(offset="-0100"), _entry(uid="redefined"))

    await _read(earlier)
    reading = await _read(later)

    assert summaries(reading.proposals) == [_WESTERN_RENDERED]
    assert reading.coverage is not None


async def test_the_library_cache_is_left_alone_and_no_longer_decides_anything(
    tmp_path: Path,
) -> None:
    """What this fix deliberately does **not** do, pinned so nobody "completes" it.

    Emptying the shared cache around the parse is the shorter repair and it needs a
    lock: ADR-0093 §7 reserves one outstanding worker *per reader*, and
    ``app/composition.py`` builds three calendar readers for exactly the reason
    ADR-0096 §5 gives — "a shared reader would let a scheduled ingestion read
    suppress the request-path facet for as long as it runs". A lock around the parse
    hands that coupling straight back, at the most expensive step of the read.

    So the cache is left as it is found, and the definition is still in it
    afterwards. That is inert rather than tolerable-in-principle, and the cases
    above are what make it inert: every value is re-seated on this document's own
    definition or made unreadable. What is left is the library's own memory
    growth (#1541), which is not this reader's state and is filed rather than fixed here.
    """
    reading = await _read(_written(tmp_path, "defines.ics", _vtimezone(), _entry(uid="defined")))

    assert reading.proposals != ()
    assert tzp.timezone(_HOSTILE) is not None, "left alone on purpose — see the docstring"


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


async def test_three_readers_parsing_at_once_each_read_their_own_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent reads, because this reader has three instances by design.

    ``app/composition.py`` builds a facet reader, an ingestion reader and an
    upcoming-event producer over the same path, and ADR-0096 §5 is why: sharing one
    "would let a scheduled ingestion read suppress the request-path facet for as
    long as it runs". Each owns a worker thread, so three parses genuinely overlap —
    which is what rules out the shorter repair of emptying the shared cache around
    the parse, since serialising it re-couples exactly what those three instances
    decouple.

    **The overlap is required rather than hoped for.** Every parse is held at a
    three-party barrier, so the reads can only complete if all three are inside
    ``Calendar.from_ical`` at the same moment: a process-wide lock around the parse
    — the shorter repair this module rejects — would let the first parse in, block
    the other two on the lock, and break the barrier on its timeout. Asserting the
    per-document results alone could not tell that apart from healthy concurrency,
    which adversarial review found on round 5.

    Re-seating writes nothing outside its own call, so the results are deterministic
    on top of that: each read names its own document's offset, and the third — which
    defines nothing — skips its entry however the three interleave.
    """
    barrier = threading.Barrier(3)

    class _GatedCalendar:
        """``Calendar``, with every parse held until three of them are in flight."""

        @staticmethod
        def from_ical(raw: bytes) -> Any:
            barrier.wait(timeout=30)
            return Calendar.from_ical(raw)

    monkeypatch.setattr(_occurrences, "Calendar", _GatedCalendar)

    padding = [
        vevent(f"DTSTART:{utc(NOW)}", f"SUMMARY:filler {n}", uid=f"pad{n}") for n in range(200)
    ]
    east = _written(
        tmp_path,
        "east.ics",
        _vtimezone("Tzcache/East", offset="+0100"),
        *padding,
        _entry("Tzcache/East"),
    )
    west = _written(
        tmp_path,
        "west.ics",
        _vtimezone("Tzcache/West", offset="-0100"),
        *padding,
        _entry("Tzcache/West"),
    )
    neither = _written(tmp_path, "neither.ics", _GOOD, *padding, _entry("Tzcache/East"))

    for _ in range(5):
        first, second, third = await asyncio.gather(_read(east), _read(west), _read(neither))
        assert _LEAKED_RENDERED in summaries(first.proposals), "east lost its own definition"
        assert _WESTERN_RENDERED in summaries(second.proposals), "west lost its own definition"
        assert _LEAKED_RENDERED not in summaries(third.proposals), "a zone it never defined"
        assert third.coverage is None


# --- what the re-seating may not reach ---------------------------------------


async def test_a_dtstamp_naming_a_defined_zone_is_still_no_report_time(
    tmp_path: Path,
) -> None:
    """Re-seating may not make an aware value out of one the parser left naive.

    ``icalendar`` applies a ``TZID`` to six property names and ``DTSTAMP`` is not
    among them, so ``DTSTAMP;TZID=Tzcache/Hostile:20260803T120000`` is naive because
    the parser **decided** that, not because a zone failed to resolve. RFC 5545
    makes ``DTSTAMP`` a UTC value, and ADR-0092 §3 permits no substitute for a
    report time the source did not make — so a re-seating that read "declared id,
    this document defines it" and made the stamp aware would hand ``_reported_at``
    an instant nobody wrote, un-skipping an entry #1491 skips.

    The zone here is one the document **does** define, which is the case an
    id-keyed check gets wrong: the unresolvable-id version of this is already
    pinned by ``test_an_unresolvable_zone_on_the_dtstamp_leaves_no_report_time``,
    and it would have kept passing throughout. Adversarial review found it on
    round 2.
    """
    # Assembled by hand rather than through ``vevent``, which supplies a UTC
    # ``DTSTAMP`` of its own — two ``DTSTAMP`` lines would leave the reader with the
    # well-formed one and this case asserting nothing.
    entry = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:stamped",
            f"DTSTAMP;TZID={_HOSTILE}:20260803T120000",
            f"DTSTART;TZID={_HOSTILE}:20260803T123000",
            f"DTEND;TZID={_HOSTILE}:20260803T130000",
            "SUMMARY:quarterly review",
            "END:VEVENT",
        ]
    )

    reading = await _read(_written(tmp_path, "stamped.ics", _GOOD, _vtimezone(), entry))

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None


@pytest.mark.parametrize("planted", [False, True], ids=["fresh", "id-already-cached"])
async def test_a_definition_this_document_uses_and_cannot_build_refuses_either_way(
    tmp_path: Path, planted: bool
) -> None:
    """The same bytes take the same path whatever the process cached before.

    A ``VTIMEZONE`` carrying a ``TZID`` and no ``STANDARD`` or ``DAYLIGHT`` cannot
    be built — ``ValueError: at least one component is needed``. In a fresh process
    ``cache_timezone_component`` builds every definition whose id the provider does
    not know, so ``Calendar.from_ical`` raises and ADR-0093 §8 reports a refusal.
    Once an earlier read has cached that id the library skips building it, and the
    document parses.

    So the re-seating lets its own build raise rather than swallowing it: the read
    refuses in both columns, which is the fresh-process answer made independent of
    what the process saw first. Swallowing would have left this PR closing the
    read-order dependence for values while leaving it open for refusals. Adversarial
    review found it on round 2.
    """
    if planted:
        await _read(_written(tmp_path, "planted.ics", _vtimezone(), _entry(uid="defined")))

    with pytest.raises(ReaderError) as refusal:
        await _read(_written(tmp_path, "malformed.ics", _GOOD, _unbuildable(), _entry()))

    assert isinstance(refusal.value.__cause__, SourceNotParseableError)
    assert _HOSTILE not in str(refusal.value), "ADR-0093 §8's message is payload-free"


@pytest.mark.parametrize("planted", [False, True], ids=["fresh", "id-already-cached"])
async def test_a_definition_nothing_names_and_cannot_build_refuses_either_way(
    tmp_path: Path, planted: bool
) -> None:
    """The same refusal, for a definition no entry in the document references.

    ``cache_timezone_component`` builds every declared id the cache does not already
    hold, so whether some *value* names it decides nothing about whether the
    cold-cache parse raises. Building only the ids a value named therefore left
    exactly this document read-order dependent: refused in a fresh process, and
    parsed — proposing its UTC entry at full confidence — once any earlier read in
    the same hub had cached that id. The referenced case above kept passing
    throughout, because its ``_entry`` is what triggered the lazy build.

    Adversarial review found it on round 3, and the pair of columns here is the
    assertion: same bytes, same answer, whatever the process read first.
    """
    if planted:
        await _read(_written(tmp_path, "planted.ics", _vtimezone(), _entry(uid="defined")))

    with pytest.raises(ReaderError) as refusal:
        await _read(_written(tmp_path, "unreferenced.ics", _GOOD, _unbuildable()))

    assert isinstance(refusal.value.__cause__, SourceNotParseableError)
    assert _HOSTILE not in str(refusal.value), "ADR-0093 §8's message is payload-free"


@pytest.mark.parametrize("planted", [False, True], ids=["fresh", "id-already-cached"])
async def test_an_id_padded_with_whitespace_is_a_different_id_either_way(
    tmp_path: Path, planted: bool
) -> None:
    """Whitespace is part of a ``TZID``, so trimming one merges two distinct zones.

    ``TZP.clean_timezone_id`` strips ``/`` and nothing else, and ``TZID`` is a
    quotable parameter — so ``TZID=" Tzcache/Hostile "`` and ``TZID:Tzcache/Hostile``
    are two ids that ``icalendar`` caches and resolves separately. The document here
    defines only the bare one; its entry names the padded one, which this document
    therefore does not define and which must be skipped exactly as any other
    unresolvable zone is (#1491, ADR-0117 §5).

    Trimming the stated id made those one id: once an earlier read had cached the
    padded name, the value resolved from that cache, was found "declared", and was
    re-seated onto the bare definition in front of it — so the entry was proposed
    warm and skipped cold, on identical bytes. Adversarial review found it on
    round 4, and the ``fresh`` column is what makes the pair an assertion rather
    than a snapshot.
    """
    padded = f" {_HOSTILE} "
    if planted:
        Calendar.from_ical(calendar(_vtimezone(padded, offset="+0500")))
        assert tzp.timezone(padded) is not None, "the plant is what this case is about"

    parts = (_GOOD, _vtimezone(), _entry(f'"{padded}"'))
    reading = await _read(_written(tmp_path, "padded.ics", *parts))

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is None, "an entry the source holds and this read skipped (§5)"


@pytest.mark.parametrize("planted", [False, True], ids=["fresh", "id-already-cached"])
async def test_a_definition_closed_by_a_mismatched_delimiter_refuses_either_way(
    tmp_path: Path, planted: bool
) -> None:
    """The cache is written from the ``END`` tag, so ``walk`` is not the whole set.

    ``icalendar`` caches on ``vals.upper() == "VTIMEZONE" and "TZID" in component``
    — the tag that *closed* the component, not the component's own type. So
    ``BEGIN:VEVENT`` carrying a ``TZID`` and closed ``END:VTIMEZONE`` is handed to
    ``cache_timezone_component`` while arriving as an ``Event`` that
    ``walk("VTIMEZONE")`` never returns, and which the eager build therefore never
    sees. Cold, the library builds it and ``Event.to_tz`` does not exist, so the
    read refuses; warm, the build is skipped and the same bytes read normally,
    proposing the good entry beside it.

    It is refused on the stray ``TZID`` property instead: RFC 5545 §3.6.5 makes that
    a ``VTIMEZONE`` property alone, so no conforming document has one elsewhere.
    Adversarial review found it on round 5, and both columns are the assertion.
    """
    if planted:
        await _read(_written(tmp_path, "planted.ics", _vtimezone(), _entry(uid="defined")))

    mismatched = "\r\n".join(["BEGIN:VEVENT", f"TZID:{_HOSTILE}", "END:VTIMEZONE"])

    with pytest.raises(ReaderError) as refusal:
        await _read(_written(tmp_path, "mismatched.ics", _GOOD, mismatched))

    assert isinstance(refusal.value.__cause__, SourceNotParseableError)
    assert _HOSTILE not in str(refusal.value), "ADR-0093 §8's message is payload-free"


# --- what the re-seating may not cost ----------------------------------------


async def test_an_unbuildable_definition_of_an_iana_key_costs_the_read_nothing(
    tmp_path: Path,
) -> None:
    """Validating declared definitions may not reach the ids the cache never holds.

    ``cache_timezone_component`` writes only ids the provider knows neither cleaned
    nor as written, so a malformed ``VTIMEZONE:TZID=Europe/Rome`` is never built by
    the library on **any** cache state: this document parses in a fresh process and
    in a warm one alike, and the definition decides nothing a reading carries. So
    refusing it would cost real calendars their reads to close a hole that was never
    open — which is why the eager build is bounded by the id rather than applied to
    everything the document declares.

    The bound is the same one :func:`test_an_iana_key_is_never_shadowed_by_the_source`
    asserts for values, read off the id instead, because an unreferenced definition
    has no resolved value to read it off.
    """
    reading = await _read(_written(tmp_path, "rome.ics", _GOOD, _unbuildable(_ROME)))

    assert summaries(reading.proposals) == [_GOOD_RENDERED]
    assert reading.coverage is not None, "nothing was skipped, so the read is accounted"


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

    Both offsets are checked, and the second is not decoration: ``+03:00`` was the
    first choice for the re-definition case and puts the same entry at 09:30Z to
    10:00Z — wholly outside a half-open window opening at 10:00Z, so the case passed
    its skip assertion while testing the window rather than the zone.
    """
    planted = datetime(2026, 8, 3, 12, 30, tzinfo=UTC) - timedelta(hours=1)
    redefined = datetime(2026, 8, 3, 12, 30, tzinfo=UTC) + timedelta(hours=1)

    assert planted == datetime(2026, 8, 3, 11, 30, tzinfo=UTC)
    assert NOW - timedelta(hours=2) <= planted < NOW + timedelta(hours=2)
    assert redefined == datetime(2026, 8, 3, 13, 30, tzinfo=UTC)
    assert NOW - timedelta(hours=2) <= redefined < NOW + timedelta(hours=2)
