"""The `.ics` semantics ADR-0093 §7b makes normative, as pure computation.

Everything here is a function of the source's bytes, one clock reading and the
configuration — never of the filesystem, never of the clock a second time, and
never of durable state recording what a previous run read (ADR-0093 §5). That is
what makes a read re-runnable, and re-readability is what buys the no-cursor
result the whole seam rests on.

**Why these semantics are ratified rather than this module's.** Adversarial
review of ADR-0093 demonstrated that two implementations can satisfy §7a's table
exactly and still disagree, and that under the wrong choice §5's no-cursor
argument is *false*. So §7b decides them, and each clause below is implemented
because it is decided, not because it seemed reasonable:

* an entry is in the window when its interval **overlaps** it — never on the
  start instant alone, which would make an event that began before the window and
  is still running permanently unreachable by every future run;
* both intervals are **half-open**, with a separate arm for a zero-duration entry
  because the general overlap test degenerates for it;
* every computed instant **saturates** at the representable bounds, including the
  seek anchor, and none of that arithmetic raises;
* a recurrence is **seeked to**, not walked to;
* the expansion budget is a **single accumulator across the whole read**, because
  one that resets per component bounds each piece of the work and not the work;
* a cancelled component contributes nothing over the extent it governs, and
  ``RECURRENCE-ID`` overrides are resolved into the expansion **before anything
  is counted or proposed**;
* the entry cap counts in-window occurrences **before interpretation**, so a
  source that busts its cap cannot be turned into a successful "your calendar is
  clear" by every one of those occurrences also being unreadable.

**What is delegated and what is not.** ``icalendar`` does the format — line
unfolding, property escaping, ``TZID`` resolution — and ``dateutil.rrule`` does
the ``RRULE`` arithmetic. The window, the seek, the override composition and the
budgets are all here, because they are what §7b ratified; a library's own
"expand between these dates" helper would be a second, unreviewed answer to the
questions this section exists to settle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from dateutil.rrule import rrulestr
from icalendar import Calendar
from icalendar.prop import vRecur

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import tzinfo

#: The representable bounds every computed instant saturates at (ADR-0093 §7b).
#: Saturation is total where a check is conditional, and it loses nothing: there
#: is no entry beyond the maximum representable instant to exclude, so the
#: clamped window and the ideal one select the same set.
UTC_MIN: Final = datetime.min.replace(tzinfo=UTC)
UTC_MAX: Final = datetime.max.replace(tzinfo=UTC)

#: Used only to pick a saturation *direction* when a conversion overflows, which
#: can happen at most a day either side of the bounds above.
_MIDPOINT: Final = datetime(5000, 1, 1)  # noqa: DTZ001 — a naive yardstick, never an instant

#: Frequencies whose period is a fixed wall-clock length, and therefore the ones
#: an occurrence grid can be jumped along arithmetically. ``MONTHLY`` and
#: ``YEARLY`` are deliberately absent: their periods are at least 28 days, so
#: walking to the window from any ``DTSTART`` ``datetime`` can represent costs a
#: few tens of thousands of steps at worst — inside the budget, and far cheaper
#: than the day-of-month alignment a correct month seek would have to get right.
_FIXED_PERIOD: Final = {
    "SECONDLY": timedelta(seconds=1),
    "MINUTELY": timedelta(minutes=1),
    "HOURLY": timedelta(hours=1),
    "DAILY": timedelta(days=1),
    "WEEKLY": timedelta(weeks=1),
}

#: How many whole periods the seek deliberately **undershoots** by.
#:
#: Landing the synthetic ``DTSTART`` exactly on the anchor would be wrong, not
#: merely tight. ``dateutil`` filters out occurrences earlier than ``DTSTART``
#: *within its first period*, so a ``WEEKLY;BYDAY=MO,WE`` rule re-anchored on a
#: Wednesday would lose that week's Monday — an occurrence the real series has.
#: Two periods of slack puts every occurrence at or after the anchor into a
#: period strictly later than the synthetic start's, where no such filtering
#: applies. It costs two extra iterations of the budget.
_SEEK_UNDERSHOOT: Final = 2


class SourceNotParseableError(Exception):
    """The source is not an iCalendar document at all (ADR-0093 §7b, §8).

    The distinction the skip rule turns on is between a read that *completed with
    gaps* and one that *could not complete*. An entry a parseable source contains
    but this reader cannot interpret is skipped; a source that cannot be parsed at
    all raises.
    """


class EntryCapExceededError(Exception):
    """More in-window occurrences than ``calendar_max_entries`` (ADR-0093 §7a).

    Refused, never truncated (§5). A deployment with a genuinely larger calendar
    widens the cap or narrows the window, and does so knowingly.
    """


class ExpansionBudgetExhaustedError(Exception):
    """``calendar_max_expansion`` was spent before the read finished (§7b).

    It bounds a different thing from the other caps and neither substitutes for
    it: the occurrences a read makes an implementation *consider*, which is
    unbounded by the byte cap (a pathological component is tiny) and by the entry
    cap (that counts what lands in the window, not what is walked to reach it).
    """


class _Form(Enum):
    """What a component is, for the resolution clause (ADR-0093 §7b)."""

    MASTER = "master"
    """No ``RECURRENCE-ID``: it governs its whole series."""

    SINGLE = "single"
    """A ``RECURRENCE-ID`` with no ``RANGE``: it governs the occurrence it names."""

    RANGE = "range"
    """``RANGE=THISANDFUTURE``: it governs that occurrence and every later one."""

    OPAQUE = "opaque"
    """A form this reader cannot interpret, whose extent is therefore unknown.

    §7b: "An override whose form a reader cannot interpret **suppresses the
    occurrences it could affect** rather than leaving them to the master. Where
    the affected extent is itself unknown, the whole series is suppressed."

    Every ``RANGE`` value other than ``THISANDFUTURE`` lands here — including the
    deprecated ``THISANDPRIOR``, whose *name* states an extent this reader does
    not implement. Inferring an extent from a value we decline to interpret is
    exactly the mis-scoping §7b warns about: an override is a **correction**, so
    getting its scope wrong does not merely omit information, it proposes stale
    information as current.
    """


@dataclass(frozen=True)
class Occurrence:
    """One resolved, in-window occurrence, ready to be interpreted.

    Attributes:
        start: The occurrence's start, in UTC. The window decision was made on
            this and on :attr:`end`.
        end: Its end, in UTC. Half-open: the occurrence covers ``[start, end)``.
        local_start: The same instant in the entry's own zone, for rendering.
        local_end: Likewise.
        all_day: Whether the source expressed it as a date rather than a time.
        summary: The entry's ``SUMMARY``, possibly empty.
        location: The entry's ``LOCATION``, possibly empty.
        reported_at: The governing component's ``DTSTAMP``, in UTC, or ``None``
            where it declares none. ``None`` makes the occurrence
            **uninterpretable** — it still counts towards the entry cap (§7b) and
            is then skipped rather than proposed, because ADR-0092 §3 permits no
            substitute for a report time the source did not make.
        text_bytes: How many UTF-8 bytes :attr:`summary` and :attr:`location`
            take, measured **once per component** and carried as an ``int``.
            ``calendar_max_content_bytes`` must be charged *before* a proposal is
            materialised — "a check that runs after the allocation has already
            paid for it" (§7a) — and re-encoding a near-8 MiB summary once per
            occurrence to find its size would pay a large part of that cost to
            avoid it.
    """

    start: datetime
    end: datetime
    local_start: datetime
    local_end: datetime
    all_day: bool
    summary: str
    location: str
    reported_at: datetime | None
    text_bytes: int


def occurrences_in_window(  # noqa: PLR0913 — the source plus the five figures ADR-0093 §7a makes this function's bound; collapsing them into a settings object would hide which ones it reads
    raw: bytes,
    *,
    window_start: datetime,
    window_end: datetime,
    zone: tzinfo,
    max_entries: int,
    max_expansion: int,
) -> tuple[Occurrence, ...]:
    """Resolve the source into the occurrences that overlap the window.

    Args:
        raw: The source's bytes, already bounded by ``calendar_max_bytes``.
        window_start: The window's inclusive lower edge, in UTC.
        window_end: Its **exclusive** upper edge, in UTC.
        zone: ``Settings.timezone``, used to localise floating and date-only
            times. A reader may not invent a second timezone source (§7b).
        max_entries: ``calendar_max_entries``.
        max_expansion: ``calendar_max_expansion``, spent across the whole read.

    Returns:
        The in-window occurrences, in ascending start order. Possibly empty,
        which is a successful reading (ADR-0093 §8).

    Raises:
        SourceNotParseableError: If the bytes are not an iCalendar document.
        EntryCapExceededError: If more occurrences fall in the window than the cap.
        ExpansionBudgetExhaustedError: If the read considers more occurrences than the
            budget allows.
    """
    budget = _Budget(max_expansion)
    found: list[Occurrence] = []
    for group in _grouped(_parse(raw), zone).values():
        found.extend(
            _resolve(group, window_start=window_start, window_end=window_end, budget=budget)
        )
    # The cap is applied **before** the skip rule, and the order is load-bearing:
    # 501 in-window occurrences of which all 501 are uninterpretable would, under
    # skip-first, produce a successful empty reading from a source that busted its
    # cap — a refusal turned into a false "your calendar is clear" (§7b).
    if len(found) > max_entries:
        msg = f"the source has more than {max_entries} occurrences in the window"
        raise EntryCapExceededError(msg)
    found.sort(key=lambda occurrence: (occurrence.start, occurrence.end, occurrence.summary))
    return tuple(found)


# --- saturating arithmetic (ADR-0093 §7b) ------------------------------------


def saturating_add(instant: datetime, delta: timedelta) -> datetime:
    """Add ``delta`` to an aware UTC instant, clamping instead of raising.

    Deliberately **not** a refusal. A clock sitting close enough to the
    representable maximum that even the seven-day default window overflows is a
    wiring problem the reader neither causes nor can diagnose, and turning it into
    a :class:`~ai_assistant.core.errors.ReaderError` would report a source fault
    against a source that is fine (ADR-0093 §7b).
    """
    try:
        return instant + delta
    except OverflowError:
        return UTC_MAX if delta > timedelta(0) else UTC_MIN


def _to_utc(instant: datetime) -> datetime:
    """Normalise an aware instant to UTC, saturating rather than raising."""
    try:
        return instant.astimezone(UTC)
    except OverflowError, ValueError, OSError:
        return UTC_MIN if instant.replace(tzinfo=None) < _MIDPOINT else UTC_MAX


def _in_zone(instant: datetime, zone: tzinfo | None) -> datetime | None:
    """Express a UTC instant in ``zone``, or ``None`` where it is not expressible.

    ``None`` is only reachable within a day of the representable bounds, and its
    single caller treats it as "do not seek" — which costs iterations, never
    correctness.
    """
    if zone is None:
        return None
    try:
        return instant.astimezone(zone)
    except OverflowError, ValueError, OSError:
        return None


# --- the expansion budget ----------------------------------------------------


class _Budget:
    """One accumulator across the whole read (ADR-0093 §7b).

    Source-wide rather than per component, and a per-component version was tried
    and does not hold: an 8 MiB file can carry thousands of non-seekable
    recurrences, each spending its full allowance to establish that it has *no*
    in-window occurrence. Every component conforms, no entry is produced so the
    entry cap never fires, and the read still performs hundreds of millions of
    steps.
    """

    def __init__(self, limit: int) -> None:
        self._left = limit
        self._limit = limit

    def spend(self) -> None:
        """Charge one considered occurrence.

        Raises:
            ExpansionBudgetExhaustedError: When the budget is gone.
        """
        self._left -= 1
        if self._left < 0:
            msg = f"the read considered more than {self._limit} occurrences"
            raise ExpansionBudgetExhaustedError(msg)


# --- parsing -----------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    """One ``VEVENT``, reduced to what the window and the proposal need."""

    local_start: datetime
    duration: timedelta
    all_day: bool
    cancelled: bool
    reported_at: datetime | None
    summary: str
    location: str
    #: The UTF-8 size of the two fields above, measured once (see
    #: :attr:`Occurrence.text_bytes`).
    text_bytes: int
    form: _Form
    #: The occurrence this component overrides, in UTC. ``None`` for a master.
    recurrence_id: datetime | None
    #: ``RRULE`` bodies, already normalised so ``dateutil`` will accept them.
    rules: tuple[vRecur, ...]
    #: Explicit ``RDATE`` starts, aware and localised.
    rdates: tuple[datetime, ...]
    #: ``EXDATE`` instants, keyed in UTC.
    exdates: frozenset[datetime]

    @property
    def start_utc(self) -> datetime:
        return _to_utc(self.local_start)


def _parse(raw: bytes) -> list[Any]:
    """Parse the bytes into ``VEVENT`` components.

    Raises:
        SourceNotParseableError: If ``icalendar`` cannot read the document. The catch
            is broad on purpose: a parser's failure modes are its own, they change
            between versions, and letting one out unwrapped is exactly what §8
            forbids — both consumers would have to catch by *implementation*.
    """
    try:
        calendar = Calendar.from_ical(raw)
        return list(calendar.walk("VEVENT"))
    except Exception as exc:
        msg = "the source is not a readable iCalendar document"
        raise SourceNotParseableError(msg) from exc


def _grouped(components: list[Any], zone: tzinfo) -> dict[object, list[_Entry]]:
    """Reduce every component and group it with the series it belongs to.

    Grouped by ``UID``, because that is what ties an override to its master. A
    component with no ``UID`` is malformed but parseable, so it becomes its own
    singleton group rather than joining every other unnamed one — merging them
    would invent a series the source never declared.
    """
    groups: dict[object, list[_Entry]] = {}
    for index, component in enumerate(components):
        entry = _reduce(component, zone)
        if entry is None:
            # Skipped, not raised: an entry a parseable source contains but this
            # reader cannot interpret proposes nothing about itself, which is what
            # keeps §4's absence rule respected rather than strained (§7b).
            continue
        uid = component.get("UID")
        key: object = str(uid) if uid is not None else ("\x00anonymous", index)
        groups.setdefault(key, []).append(entry)
    return groups


def _reduce(component: Any, zone: tzinfo) -> _Entry | None:
    """Reduce one ``VEVENT``, or return ``None`` if it cannot be interpreted."""
    start = _localised(component.get("DTSTART"), zone)
    if start is None:
        return None
    local_start, all_day = start

    duration = _duration(component, local_start, all_day=all_day, zone=zone)
    if duration is None or duration < timedelta(0):
        return None

    form, recurrence_id = _override_form(component, zone)
    if form is _Form.OPAQUE:
        # Carried rather than dropped: an opaque override suppresses what it might
        # have changed, so the group's resolution has to *see* it.
        return _Entry(
            local_start=local_start,
            duration=duration,
            all_day=all_day,
            cancelled=True,
            reported_at=None,
            summary="",
            location="",
            text_bytes=0,
            form=form,
            recurrence_id=recurrence_id,
            rules=(),
            rdates=(),
            exdates=frozenset(),
        )

    rules = _rules(component, local_start, zone)
    if rules is None:
        return None

    summary = _text(component.get("SUMMARY"))
    location = _text(component.get("LOCATION"))
    return _Entry(
        local_start=local_start,
        duration=duration,
        all_day=all_day,
        cancelled=str(component.get("STATUS") or "").upper() == "CANCELLED",
        reported_at=_reported_at(component, zone),
        summary=summary,
        location=location,
        text_bytes=len(summary.encode()) + len(location.encode()),
        form=form,
        recurrence_id=recurrence_id,
        rules=rules,
        rdates=_dates(component, "RDATE", zone),
        exdates=frozenset(_to_utc(moment) for moment in _dates(component, "EXDATE", zone)),
    )


def _localised(prop: Any, zone: tzinfo) -> tuple[datetime, bool] | None:
    """Return ``(aware start, all_day)``, localising a floating or date-only value.

    ``fold=0`` is the platform default and is exactly what §7b requires of a
    floating local time a DST transition makes ambiguous or nonexistent: it names
    the earlier offset for an ambiguous time and resolves a nonexistent one
    through the pre-transition offset, deterministically in both directions with
    no special case. Such an entry is **never skipped** for sitting on a
    transition — it is a real appointment someone holds, and skipping would drop
    an hour of a calendar twice a year, silently.
    """
    value = getattr(prop, "dt", None)
    # `datetime` before `date`: it is a subclass of it.
    if isinstance(value, datetime):
        return (value if value.tzinfo is not None else value.replace(tzinfo=zone)), False
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=zone), True
    return None


def _duration(
    component: Any,
    local_start: datetime,
    *,
    all_day: bool,
    zone: tzinfo,
) -> timedelta | None:
    """The occurrence duration the component declares, by RFC 5545's defaults."""
    end = _localised(component.get("DTEND"), zone)
    if end is not None:
        return end[0] - local_start
    declared = getattr(component.get("DURATION"), "dt", None)
    if isinstance(declared, timedelta):
        return declared
    # RFC 5545: a DATE-valued DTSTART with no end is one day; a DATE-TIME one is
    # instantaneous. The second is the zero-duration arm §7b states separately.
    return timedelta(days=1) if all_day else timedelta(0)


def _override_form(component: Any, zone: tzinfo) -> tuple[_Form, datetime | None]:
    """Classify the component and, for an override, key the occurrence it names."""
    prop = component.get("RECURRENCE-ID")
    if prop is None:
        return _Form.MASTER, None
    named = _localised(prop, zone)
    if named is None:
        return _Form.OPAQUE, None
    scope = str(prop.params.get("RANGE") or "").upper()
    if not scope:
        return _Form.SINGLE, _to_utc(named[0])
    if scope == "THISANDFUTURE":
        return _Form.RANGE, _to_utc(named[0])
    return _Form.OPAQUE, _to_utc(named[0])


def _reported_at(component: Any, zone: tzinfo) -> datetime | None:
    """The instant the source declares for this component — its ``DTSTAMP``.

    **``DTSTAMP`` and nothing else, which is a choice this lane made and states.**
    ADR-0093 §10 is normative that "for the calendar sensor that value is the
    occurrence's ``DTSTAMP``, which RFC 5545 makes mandatory", and ADR-0092 §3
    permits no substitute for a report time the source did not make — "not our
    clock, not the ingest instant, and in particular **not the file's mtime**".
    ``LAST-MODIFIED`` was available and is declined: §10 names one value, RFC 5545
    makes it mandatory, and a component missing it is malformed at the component
    level, which §7b's skip rule already covers. Widening to a second property
    would be this module inventing a rule where a ratified one exists.
    """
    stamped = getattr(component.get("DTSTAMP"), "dt", None)
    if not isinstance(stamped, datetime):
        return None
    return _to_utc(stamped if stamped.tzinfo is not None else stamped.replace(tzinfo=zone))


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _dates(component: Any, name: str, zone: tzinfo) -> tuple[datetime, ...]:
    """Every ``RDATE``/``EXDATE`` instant, localised. ``PERIOD`` values are skipped."""
    prop = component.get(name)
    if prop is None:
        return ()
    found: list[datetime] = []
    for group in prop if isinstance(prop, list) else [prop]:
        for item in getattr(group, "dts", ()):
            localised = _localised(item, zone)
            if localised is not None:
                found.append(localised[0])
    return tuple(found)


def _rules(component: Any, local_start: datetime, zone: tzinfo) -> tuple[vRecur, ...] | None:
    """Every ``RRULE`` on the component, with ``UNTIL`` made compatible with ``DTSTART``.

    ``dateutil`` refuses an ``RRULE`` whose ``UNTIL`` is naive when ``DTSTART`` is
    aware — and every ``DTSTART`` is aware by the time it reaches here, because
    §7b localises floating and date-only values. A file whose ``UNTIL`` is
    floating or date-valued is therefore ordinary rather than exotic, so the two
    are reconciled in the same zone the start was localised in rather than left to
    fail. Anything else that will not parse makes the whole component
    uninterpretable, and it is skipped (``None``).
    """
    prop = component.get("RRULE")
    if prop is None:
        return ()
    normalised: list[vRecur] = []
    for rule in prop if isinstance(prop, list) else [prop]:
        adjusted = vRecur(dict(rule))
        until = _only(adjusted.get("UNTIL"))
        if isinstance(until, datetime):
            aware = until if until.tzinfo is not None else until.replace(tzinfo=zone)
            adjusted["UNTIL"] = [_to_utc(aware)]
        elif isinstance(until, date):
            # A DATE-valued UNTIL bounds the whole of that day.
            end_of_day = datetime.combine(until, time(23, 59, 59), tzinfo=zone)
            adjusted["UNTIL"] = [_to_utc(end_of_day)]
        try:
            rrulestr(_rule_text(adjusted), dtstart=local_start)
        except Exception:
            return None
        normalised.append(adjusted)
    return tuple(normalised)


def _rule_text(rule: vRecur) -> str:
    """Serialise one ``RRULE`` body back to the line ``dateutil`` parses.

    ``vRecur.to_ical`` is the one part of ``icalendar``'s public surface this
    module uses that its own annotations leave untyped, so the ignore is narrowed
    to the single call site rather than to the module.
    """
    return str(rule.to_ical().decode())  # type: ignore[no-untyped-call]


def _only(value: object) -> object:
    """ICalendar property values arrive as one-item lists; take the item."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


# --- resolution and expansion ------------------------------------------------


def _resolve(
    group: list[_Entry], *, window_start: datetime, window_end: datetime, budget: _Budget
) -> Iterator[Occurrence]:
    """Expand one ``UID``'s series, with cancellation and overrides applied.

    Overrides are resolved **against the master's expansion before anything is
    counted or proposed**, which is what makes the "is declining to emit a
    cancelled occurrence an absence claim?" question disappear rather than need
    answering: not emitting an occurrence the source says does not occur is
    reading the source correctly, where emitting some "cancelled" marker would be
    the absence claim §4 actually forbids.
    """
    masters = [entry for entry in group if entry.form is _Form.MASTER]
    overrides = [entry for entry in group if entry.form is not _Form.MASTER]

    # Fail closed on a shape whose extent cannot be established: two masters
    # sharing a UID, an override with no master, or an override whose form this
    # reader does not interpret. In each case the master's values for the affected
    # occurrences are known to be untrustworthy and nothing else is (§7b).
    if len(masters) != 1 or any(entry.form is _Form.OPAQUE for entry in overrides):
        return
    master = masters[0]
    if master.cancelled:
        return

    singles = _by_key(entry for entry in overrides if entry.form is _Form.SINGLE)
    ranges = _by_key(entry for entry in overrides if entry.form is _Form.RANGE)
    range_keys = sorted(ranges)

    slack = _shift_slack(overrides)
    band_start = saturating_add(saturating_add(window_start, -master.duration), -slack)
    band_end = saturating_add(window_end, slack)

    for moment in _starts(master, band_start=band_start, band_end=band_end, budget=budget):
        key = _to_utc(moment)
        governing = _governing(key, master=master, singles=singles, ranges=ranges, keys=range_keys)
        if governing is None or governing.cancelled:
            # `None` is the contested case: two overrides of the same form sharing
            # a RECURRENCE-ID are genuinely contradictory — two corrections of
            # equal specificity at the same point — so it fails closed rather than
            # picking one (§7b).
            continue
        occurrence = _occurrence(moment, governing=governing)
        if _overlaps(occurrence, window_start=window_start, window_end=window_end):
            yield occurrence


def _by_key(entries: Iterator[_Entry]) -> dict[datetime, list[_Entry]]:
    grouped: dict[datetime, list[_Entry]] = {}
    for entry in entries:
        if entry.recurrence_id is not None:
            grouped.setdefault(entry.recurrence_id, []).append(entry)
    return grouped


def _shift_slack(overrides: list[_Entry]) -> timedelta:
    """How far outside the window a master occurrence may still be relevant.

    An override *moves* the occurrence it governs, so an occurrence generated
    outside the window can be pulled into it and one generated inside can be
    pushed out. The band the master is expanded over is widened by the largest
    shift any override on this series declares, plus the longest duration one
    gives an occurrence — computed from the components themselves, so it is
    bounded by the source rather than guessed.
    """
    slack = timedelta(0)
    for override in overrides:
        if override.recurrence_id is not None:
            slack = max(slack, abs(override.start_utc - override.recurrence_id))
        slack = max(slack, override.duration)
    return slack


def _starts(
    master: _Entry, *, band_start: datetime, band_end: datetime, budget: _Budget
) -> Iterator[datetime]:
    """Every start the master generates in the band, ascending, in its own zone.

    Local rather than UTC-normalised, because a recurrence is a statement about
    **wall time**: a daily 09:00 series stays at 09:00 across a DST transition,
    and reconstructing that from a UTC instant by adding elapsed UTC would render
    the entry an hour out twice a year. The UTC form is derived per occurrence for
    ordering, de-duplication, ``EXDATE`` matching and the window test, all of
    which are statements about instants.
    """
    seen: set[datetime] = set()
    candidates: list[datetime] = []

    if not master.rules and not master.rdates:
        budget.spend()
        candidates.append(master.local_start)
    for rule in master.rules:
        candidates.extend(
            _rule_starts(
                rule, master.local_start, band_start=band_start, band_end=band_end, budget=budget
            )
        )
    for moment in master.rdates:
        budget.spend()
        candidates.append(moment)

    for moment in sorted(candidates, key=_to_utc):
        key = _to_utc(moment)
        if key in seen or key in master.exdates:
            continue
        seen.add(key)
        # An RDATE may sit outside the band; the band only bounds the *rule*.
        if band_start <= key < band_end:
            yield moment


def _rule_starts(
    rule: vRecur,
    local_start: datetime,
    *,
    band_start: datetime,
    band_end: datetime,
    budget: _Budget,
) -> Iterator[datetime]:
    """Expand one ``RRULE`` by **seeking** to the band rather than walking to it.

    An in-window cap does not bound the work of reaching the window, and this is
    the one hole a byte cap cannot cover: ``DTSTART:19700101T000000Z`` with
    ``RRULE:FREQ=SECONDLY`` is a few dozen bytes and has roughly 1.8 billion
    occurrences before it reaches a window centred on today. The seek is the right
    answer for the rules that admit one; :data:`_FIXED_PERIOD` says which those
    are, and the budget is belt and braces for the rest.
    """
    anchor = _seek_from(rule, local_start, band_start)
    expanded = rrulestr(_rule_text(rule), dtstart=anchor)
    for moment in expanded:
        budget.spend()
        key = _to_utc(moment)
        if key >= band_end:
            return
        if key >= band_start:
            yield moment


def _seek_from(  # noqa: PLR0911 — each early return is one rule form that does not admit a seek, named separately so the fallback to the budget is legible
    rule: vRecur, local_start: datetime, band_start: datetime
) -> datetime:
    """A synthetic ``DTSTART`` on the real occurrence grid, just before the band.

    The arithmetic is done in **wall time**, which is ``dateutil``'s own model: it
    advances a ``DAILY`` rule by calendar days and an ``HOURLY`` one by clock
    hours, attaching the start's ``tzinfo`` to each result. Doing it in UTC
    instead would drift by whatever DST did in between — and for a ``SECONDLY``
    rule an hour of drift is 3,600 occurrences, which is the difference between a
    seek and a slower walk.

    ``COUNT`` disables the seek outright: the count is measured from the real
    ``DTSTART``, so re-anchoring would silently change which occurrences exist.
    Such a series is bounded by the budget instead, which is §7b's own posture — a
    source too expensive to read is refused, not silently trimmed.
    """
    if "COUNT" in rule:
        return local_start
    period = _FIXED_PERIOD.get(str(_only(rule.get("FREQ")) or "").upper())
    if period is None:
        return local_start
    interval = _only(rule.get("INTERVAL"))
    step = period * (int(interval) if isinstance(interval, int) and interval >= 1 else 1)

    local_band_start = _in_zone(band_start, local_start.tzinfo)
    if local_band_start is None:
        return local_start
    gap = local_band_start.replace(tzinfo=None) - local_start.replace(tzinfo=None)
    if gap <= timedelta(0):
        return local_start
    periods = gap // step - _SEEK_UNDERSHOOT
    if periods <= 0:
        return local_start
    try:
        return local_start + periods * step
    except OverflowError, OSError:
        return local_start


def _governing(
    key: datetime,
    *,
    master: _Entry,
    singles: dict[datetime, list[_Entry]],
    ranges: dict[datetime, list[_Entry]],
    keys: Sequence[datetime],
) -> _Entry | None:
    """Which component governs the occurrence at ``key``, or ``None`` to suppress.

    §7b's composition rule verbatim: "the governing override is the
    **single-instance** one naming it if there is one; otherwise the
    ``RANGE=THISANDFUTURE`` override with the **greatest ``RECURRENCE-ID`` at or
    before** that occurrence; otherwise the master."

    Last-writer-wins by ``RECURRENCE-ID`` is the reading that matches what the
    overrides *mean*: each is a correction made at a point in the series, so the
    most recent correction at or before an occurrence is the one still standing.
    Single-instance beats range for the occurrence it names, because it is the
    more specific statement about it.
    """
    named = singles.get(key)
    if named is not None:
        return named[0] if len(named) == 1 else None
    latest: _Entry | None = None
    contested = False
    for candidate in keys:
        if candidate > key:
            break
        governed = ranges[candidate]
        latest, contested = governed[0], len(governed) > 1
    if contested:
        return None
    return latest if latest is not None else master


def _occurrence(moment: datetime, *, governing: _Entry) -> Occurrence:
    """Build the occurrence the master generated at ``moment``, under ``governing``."""
    if governing.form is _Form.MASTER:
        local_start = moment
    elif governing.form is _Form.SINGLE:
        local_start = governing.local_start
    else:
        # A range override is a *shift* applied from its own RECURRENCE-ID onward:
        # a daily 09:00 master with a THISANDFUTURE override moving 3 August to
        # 10:00 leaves 4-7 August at 10:00, not at the time the calendar no longer
        # says (§7b). The shift is kept in the master's zone so the whole series
        # renders in one frame, and applied in wall time so the series does not
        # walk an hour on a DST boundary.
        shift = governing.start_utc - (governing.recurrence_id or governing.start_utc)
        local_start = moment + shift
    local_end = local_start + governing.duration
    start = _to_utc(local_start)
    return Occurrence(
        start=start,
        end=saturating_add(start, governing.duration),
        local_start=local_start,
        local_end=local_end,
        all_day=governing.all_day,
        summary=governing.summary,
        location=governing.location,
        reported_at=governing.reported_at,
        text_bytes=governing.text_bytes,
    )


def _overlaps(occurrence: Occurrence, *, window_start: datetime, window_end: datetime) -> bool:
    """Half-open membership, with the separate arm a zero-duration entry needs.

    "Overlaps" alone is not a predicate, and the gap is not academic: an event
    ending exactly at the window's lower edge is in under a closed reading and out
    under a half-open one — with the cap otherwise exactly filled, the difference
    between a successful read and a refusal, from identical settings and an
    identical clock. Half-open is chosen because adjacent windows then partition
    time without double-counting.

    The zero-duration arm is stated separately because the general test
    degenerates for it: ``end > window_start`` is false for an instant sitting
    exactly *on* ``window_start``, which would silently exclude the one entry
    shape that has no duration to spare (§7b).
    """
    if occurrence.end == occurrence.start:
        return window_start <= occurrence.start < window_end
    return occurrence.start < window_end and occurrence.end > window_start


__all__ = [
    "UTC_MAX",
    "UTC_MIN",
    "EntryCapExceededError",
    "ExpansionBudgetExhaustedError",
    "Occurrence",
    "SourceNotParseableError",
    "occurrences_in_window",
    "saturating_add",
]
