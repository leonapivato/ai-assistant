"""The calendar reader: one local ``.ics`` file, read into attested proposals.

Leg 6's first concrete :class:`~ai_assistant.core.protocols.Reader`, specified in
unusual detail by ADR-0093 §7, §7a and §7b and read under ADR-0095 §1's
substitution. It opens one file, resolves what that file says about the window
around *now*, and proposes each in-window occurrence as an ``ATTESTED`` belief.
It holds no store, writes nothing, and is never its own caller.

**The supported deployment is one `.ics` file, and that is a real constraint
rather than a simplification.** ADR-0093 §7 is normative that a filesystem source
is a **regular file**, checked on the descriptor. ADR-0095 §Context, reasoning
from the project owner's dedicated-always-on-box steer, names the two source
patterns that survive it: a file synced onto the hub (a calendar export mirrored
by Syncthing or ``rsync``), and a **co-located fetcher** running on the hub box
with this reader reading its output. For the second, ``vdirsyncer``'s
``singlefile`` storage — ``type = "singlefile"``, writing all of a collection's
items into one ``.ics`` — is the arrangement that fits; its default ``filesystem``
storage writes one file per item into a *directory*, which §7 refuses on the
descriptor check. Widening the seam to read a directory is **#649**: it reopens
the byte cap's scope, §7b's single acquisition instant, and mid-read mutation,
so it is its own decision and not a looser version of this one.

**Configuration is not consent**, and no surface may present it as one (§7). A
``Settings`` field cannot be revoked by the user through the assistant, cannot be
scoped, and leaves no audit record. The grant model is deferred (§11, #629), and
this reader shipping disabled by default is what keeps that deferral from being
quietly discharged: nothing may read a user's personal files because a default
said so.

**What is deliberately absent.** No cursor and no durable per-source state (§5):
the window moves with the clock, so every run recomputes it and an entry inside
it is read whether or not a previous run read it. No lifecycle method (§7): the
only thing a ``close`` could do about a thread blocked in an uninterruptible
syscall is wait for it, which re-creates the hang the abandonment rule removes
while making it look handled. No configurable display label and no configurable
identity (§7): a free-text setting is precisely how a path or an email address
would reach ``Provenance``, every export and every log line, and no validator can
tell a chosen label from a personal one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    CalendarFacet,
    DataTier,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    ReadCoverage,
    ReportedExtent,
    SemanticMemory,
    SourceReading,
)
from ai_assistant.readers._occurrences import (
    occurrences_in_window,
    saturating_add,
    saturating_shift,
)
from ai_assistant.readers._source import OneWorker, acquire

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import tzinfo
    from pathlib import Path

    from ai_assistant.core.clock import Clock
    from ai_assistant.readers._occurrences import Occurrence

#: This reader's declared identity (ADR-0093 §7). **Declared, never configured**:
#: it lands on the reading, on every belief the gate then stores, in every export
#: and in every log line, and a declared constant cannot carry personal data at
#: all — which is a property rather than a rule. An earlier draft of §7 said
#: "configured", and resolving that by adding a setting is the worse of the two
#: repairs, because a free-text field is the mechanism by which a user would put
#: a home directory or an address there.
CALENDAR_READER_NAME: Final = "calendar"

#: ADR-0093 §7a's nine figures. The *dimensions* are the decision and the numbers
#: are revisable; each is named here rather than left to this module so that two
#: conforming implementations cannot diverge while each believes it conforms
#: (ADR-0074 §9.3, applied by §5).
#:
#: They are repeated in ``core/config.py`` rather than imported from it, because
#: `core` depends on nothing else in ``ai_assistant`` (golden rule 2) and the
#: dependency can only point this way. ``tests/readers/test_calendar_settings.py``
#: pins the two to each other.
DEFAULT_CALENDAR_WINDOW_PAST: Final = timedelta(days=1)
DEFAULT_CALENDAR_WINDOW_FUTURE: Final = timedelta(days=7)
DEFAULT_CALENDAR_MAX_ENTRIES: Final = 500
DEFAULT_CALENDAR_MAX_BYTES: Final = 8 * 1024 * 1024
DEFAULT_CALENDAR_MAX_EXPANSION: Final = 100_000
DEFAULT_CALENDAR_READ_TIMEOUT: Final = timedelta(seconds=10)
DEFAULT_CALENDAR_MAX_CONTENT_BYTES: Final = 4 * 1024 * 1024

#: The ceiling on either window arm, and it is not decoration. ``> 0`` alone
#: admits ``timedelta.max``, for which ``read_at + calendar_window_future`` is not
#: a representable instant — so a figure that passed a load-time range check would
#: produce an ``OverflowError`` on the first run, escaping §8's two outcomes
#: entirely and reaching the scheduler as neither a source failure nor a
#: cancellation. Ten years is far past any calendar anyone reads and far short of
#: the representable limit, which is the whole requirement of the number (§7a).
MAX_CALENDAR_WINDOW: Final = timedelta(days=3650)

#: The upper bound §7a puts on the two counting caps, and the reason is the one
#: ``observation_batch_size`` already carries: a value outside ``[0, 2**63)``
#: is a ``ValueError`` wherever it is eventually used, and a setting the runtime
#: would refuse must fail at load rather than at the first read.
MAX_CALENDAR_COUNT: Final = 2**63

#: What a connected source's report is worth. Below 1.0 — nothing forces that in
#: the ``ATTESTED`` band, since a source may legitimately report a fact it is
#: certain of (ADR-0038 §2a), but a third party's claim about the user is not the
#: user's own word, and 0.9 is what the corpus's other attested fixtures use.
_ATTESTED_CONFIDENCE: Final = 0.9

#: A flat allowance for the fixed scaffolding of one rendered proposal — the
#: quoting, the dates, the zone name — charged against
#: ``calendar_max_content_bytes`` alongside the entry's own text. Generous rather
#: than exact: the budget exists to stop a *multiplicative* blow-up, and a
#: rendering that measured itself precisely would have to be materialised first,
#: which is the ordering §7a forbids.
_RENDER_OVERHEAD_BYTES: Final = 256


class ContentBudgetExhaustedError(Exception):
    """``calendar_max_content_bytes`` would be exceeded (ADR-0093 §7a).

    It bounds the **output**, which none of the other caps do. A source can
    satisfy every one of them while the proposals blow up: one recurrence carrying
    a near-8 MiB field with exactly 500 in-window occurrences is inside the byte
    cap, the entry cap and the expansion budget, and materialises roughly 4 GiB,
    because an occurrence repeats its component's content and nothing was counting
    bytes on the way out.
    """


def _utcnow() -> datetime:
    return datetime.now(UTC)


@final
class CalendarReader:
    """Reads one ``.ics`` file and proposes the entries in its window.

    Structurally implements :class:`~ai_assistant.core.protocols.Reader`.
    """

    def __init__(  # noqa: PLR0913 — one source, one clock, one zone and §7a's seven figures; each is one knob a deployment sets
        self,
        path: Path,
        *,
        now: Clock = _utcnow,
        timezone: str = "UTC",
        window_past: timedelta = DEFAULT_CALENDAR_WINDOW_PAST,
        window_future: timedelta = DEFAULT_CALENDAR_WINDOW_FUTURE,
        max_entries: int = DEFAULT_CALENDAR_MAX_ENTRIES,
        max_bytes: int = DEFAULT_CALENDAR_MAX_BYTES,
        max_expansion: int = DEFAULT_CALENDAR_MAX_EXPANSION,
        read_timeout: timedelta = DEFAULT_CALENDAR_READ_TIMEOUT,
        max_content_bytes: int = DEFAULT_CALENDAR_MAX_CONTENT_BYTES,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create a reader over one configured source.

        Every bound is refused **here**, not at the first read. ADR-0093 §10 names
        this as a clause the shared conformance suite cannot reach — "``Reader``
        specifies no constructor and no configuration surface … so a generic suite
        has nothing to over-supply. It is a concrete reader's test and a
        ``Settings`` test" — and this is the concrete reader's half of it. The
        settings layer states the same rules again, because this constructor is a
        second seam a test or a second composition root reaches directly.

        Args:
            path: The source. **Absolute**, which is the *shape* validated at
                load; its existence and readability are properties of the world at
                an instant and are checked at run time, where they degrade under
                §8 rather than refusing to start. A hub that would not boot because
                a calendar file sat on an unmounted volume would turn an advisory
                source into a boot dependency (§7).
            now: The clock, read **exactly once per read, at the instant the
                source's bytes are acquired** (§7b). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            timezone: The IANA zone floating and date-only entries are localised
                in — ``Settings.timezone``, the same value ADR-0008 §5 gives the
                temporal context. A reader may not invent a second timezone
                source: two components resolving "today" against different zones
                is the class of defect ADR-0026 exists to prevent, arriving
                through data rather than through a clock.
            window_past: How far back the clock-relative window reaches. May be
                zero — a deployment that wants only what is ahead is coherent.
            window_future: How far forward. May **not** be zero: a window of zero
                width is a reader that reads nothing while reporting health, which
                is what ADR-0077 §1 refused for a zero batch.
            max_entries: In-window occurrences, and so proposals. Exceeding it
                raises; it is never truncated (§5).
            max_bytes: The source read **before** parsing. Separate from
                ``max_entries`` and the one that must exist: an entry cap can only
                be applied *after* parsing, so a cap on entries alone lets a 2 GiB
                ``.ics`` be fully parsed before anything refuses it.
            max_expansion: Occurrences considered across the **whole** read.
            read_timeout: This reader's deadline on its own read.
            max_content_bytes: Proposal content materialised across the whole read.
            id_factory: Mints the id of every record proposed. ``None`` mints a
                ``uuid4``. Injectable so tests assert exact ids; it is guarded at
                its output, which is the discipline ADR-0092 §6 owes a minted id.

        Raises:
            ValueError: If ``path`` is not absolute, ``timezone`` is not a known
                IANA zone, or any figure is outside ADR-0093 §7a's range.
        """
        if not path.is_absolute():
            msg = (
                f"the calendar source must be an absolute path, got {str(path)!r}; a "
                f"relative value resolves against each process's working directory "
                f"(ADR-0093 §7)"
            )
            raise ValueError(msg)
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown timezone {timezone!r}"
            raise ValueError(msg) from exc

        _check_window("calendar_window_past", window_past, allow_zero=True)
        _check_window("calendar_window_future", window_future, allow_zero=False)
        _check_count("calendar_max_entries", max_entries)
        _check_count("calendar_max_expansion", max_expansion)
        _check_positive_int("calendar_max_bytes", max_bytes)
        _check_positive_int("calendar_max_content_bytes", max_content_bytes)
        if read_timeout <= timedelta(0):
            msg = f"calendar_read_timeout must be > 0, got {read_timeout!r}"
            raise ValueError(msg)

        self._path = path
        self._now = checked_clock(now, owner="CalendarReader")
        self._zone: tzinfo = zone
        self._window_past = window_past
        self._window_future = window_future
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_expansion = max_expansion
        self._read_timeout = read_timeout
        self._max_content_bytes = max_content_bytes
        self._id_factory = id_factory
        self._worker = OneWorker(thread_name=f"{CALENDAR_READER_NAME}-reader")

    @property
    def name(self) -> str:
        """This reader's declared identity — stable, Tier 2, and never a path."""
        return CALENDAR_READER_NAME

    async def read(self) -> SourceReading:
        """Read the source once, within this reader's own bound, and report it.

        Returns:
            The reading. An empty ``proposals`` tuple is a **success** and means
            the source had nothing to propose within the bound (ADR-0093 §8).

        Raises:
            ReaderError: If the read cannot complete — a missing, unreadable,
                non-regular, oversized, unparseable or over-cap source, a deadline
                expiry, or a worker from an earlier read still outstanding. The
                underlying failure is preserved as ``__cause__``; the **message**
                carries only this reader's identity and the failure's class.
            CancelledError: Delivered onward unchanged. A cancellation from
                outside is **excepted** from the wrapping rule above, and the
                carve-out matters because the wording it qualifies invites the
                mistake: a cancelled read has, in plain English, "not completed",
                and a reader wrapping everything it catches would convert it —
                leaving the facet degraded and the scheduler logging a source
                fault, on a shutdown that was working correctly (§8).
        """
        try:
            return await self._worker.run(
                self._read_source, seconds=self._read_timeout.total_seconds()
            )
        except asyncio.CancelledError:
            # Explicit, though `except Exception` below would not catch it:
            # this is the one clause a conforming-looking reader gets wrong.
            raise
        except Exception as exc:
            # **Broad on purpose, and the cause is what keeps it honest.** §8
            # forbids letting a source-level exception — an ``OSError``, a
            # parser's own class — cross the seam unwrapped, because both
            # consumers would then have to catch by *implementation*: the
            # `context/` adapter and the scheduler job would each need to know
            # which exceptions this reader's parser can throw. A programming
            # error is not hidden by this, it is relabelled: it arrives as a
            # ``ReaderError`` whose ``__cause__`` is a ``TypeError``, which reads
            # unambiguously in the one place ADR-0083 §7 puts it.
            raise ReaderError(self._failure(exc)) from exc

    def _failure(self, exc: BaseException) -> str:
        """A payload-free message: this reader's identity and the failure's class.

        ``raise ReaderError(str(exc)) from exc`` satisfies every word of §8's
        wrapping rule and, for a missing ``/home/alice/Private/therapy.ics``,
        produces a message that **is** that path — which the scheduler then writes
        to a log under ADR-0083 §7. That is Tier 1 data in an operational log,
        which ADR-0004 §5 forbids outright. The path is exactly as sensitive as
        the identity — arguably more, since a filename is chosen by the user and a
        directory names them — so it gets the same treatment rather than a weaker
        one because it arrived inside an exception.

        The cause's class is included alongside this reader's own because it is
        the useful half and it is Tier 2: ``PermissionError`` and
        ``FileNotFoundError`` tell an operator which action to take, and the
        operator already knows the path, because they configured it. Only the
        **class** — never ``str(cause)``, which for an ``OSError`` is the path.
        """
        cause = exc.__cause__
        if cause is None:
            return f"{self.name}: {type(exc).__name__}"
        return f"{self.name}: {type(exc).__name__} ({type(cause).__name__})"

    def _read_source(self) -> SourceReading:
        """The whole read, on the worker thread (ADR-0093 §7).

        **Every step is here and none of it is on the loop** — resolving the path,
        opening it, reading it, parsing it, expanding recurrences, and building the
        proposals alike. An earlier draft of §7 said "filesystem work", which left
        the loop exposed to the other bounded thing this reader does: §7b's budget
        allows 100,000 occurrence expansions, and an 8 MiB calendar within every
        stated cap can require them. Run on the loop after the worker returned,
        that CPU work starves ADR-0083 §7's deliberately serial scheduler exactly
        as a blocked syscall does — and worse for the deadline, because the timer
        callback cannot fire while the loop is occupied, so ``read()`` would
        overrun its timeout and then *return successfully*. A deadline that cannot
        be observed is not a deadline.
        """
        raw = acquire(self._path, max_bytes=self._max_bytes)
        # **Here, and exactly once.** Anchoring before the read is deterministic
        # and untrue: a capture at 10:00 that waits on its worker, opens a file
        # replaced at 10:05 and reads it at 10:10 returns proposals describing the
        # 10:05 file stamped 10:00, with membership evaluated against an instant
        # that predates the data — so a just-ended event is proposed as current.
        # Acquisition is a single point, so nothing drifts, and it is the moment
        # the bytes this reading describes came into our hands (§7b).
        read_at = self._now()
        window_start = saturating_add(read_at, -self._window_past)
        window_end = saturating_add(read_at, self._window_future)
        resolved = occurrences_in_window(
            raw,
            window_start=window_start,
            window_end=window_end,
            zone=self._zone,
            max_entries=self._max_entries,
            max_expansion=self._max_expansion,
        )
        occurrences = resolved.occurrences
        proposals, proposed_all = self._propose(occurrences, read_at)
        return SourceReading(
            source=self.name,
            read_at=read_at,
            # **Never filled**, and that is a ruling rather than laxity. A local
            # `.ics` declares no reading-level as-of: the format's report times
            # are per-`VEVENT`, and the file's mtime is a fact about our
            # filesystem rather than a claim the source made (ADR-0093 §10,
            # ADR-0092 §3).
            as_of=None,
            proposals=proposals,
            # What this read **exhausted**, and only where it accounted for every
            # entry the source held there (ADR-0117 §5). `_coverage` decides both
            # halves; a reading that skipped anything declares none, and takes
            # ADR-0115 §4's ruled no-coverage path.
            coverage=self._coverage(
                window_start,
                window_end,
                accounted=resolved.accounted and proposed_all,
            ),
            # The other consumer's half of the same read, from the same
            # occurrences and the same acquisition instant (ADR-0096 §5). It is
            # built here rather than by the `context/` adapter because an adapter
            # that built its own would be stamping a value with instants it did
            # not observe, and `SourceReading`'s validator refuses exactly that.
            facet=self._facet(occurrences, read_at, window_end),
        )

    def _facet(
        self, occurrences: Sequence[Occurrence], read_at: datetime, window_end: datetime
    ) -> CalendarFacet:
        """The situational view of this read: what is happening, and what is next.

        ADR-0096 §6's three scalars, and **no entry text at all** — no summary,
        location, description, organiser, attendee or identifier. The same read's
        proposals already carry the occurrences into memory as ``ATTESTED``
        beliefs, so putting them here too would ship one content into one prompt by
        two routes carrying two different stamps, which is the "neither is mistaken
        for the other" hazard ADR-0093 §3 names — manufactured by us rather than
        found. What the beliefs cannot answer at request time without a scan is
        exactly this: is something happening right now, and when is the next thing.

        **It counts occurrences the proposals skip, and that is the design.** An
        occurrence with no ``DTSTAMP`` is skipped by :meth:`_propose`, because
        ADR-0092 §3 permits no substitute for a report time the source did not make
        — but the facet makes no attestation and owes no report time, so it counts
        it. ADR-0096 §5 rules that the two halves describing overlapping-but-unequal
        sets is the design rather than an error, and states it so nobody "fixes" it
        by making the facet skip the same entries.

        Args:
            occurrences: The in-window occurrences, as the proposals see them.
            read_at: Our own clock at acquisition — the single anchor §7b fixes,
                and the instant membership below is evaluated at.
            window_end: The window's **exclusive** upper edge, already saturated by
                :func:`saturating_add`, which is what makes ``covers_until`` an
                always-representable instant.

        Returns:
            The facet, stamped exactly as the reading that will carry it —
            ``source`` and ``read_at`` from this read, and ``as_of`` ``None``
            because a local ``.ics`` declares none.
        """
        later = [occurrence.start for occurrence in occurrences if occurrence.start > read_at]
        return CalendarFacet(
            source=self.name,
            read_at=read_at,
            # The reading's own, and the validator on `SourceReading` refuses any
            # other value — so the two cannot drift apart by an edit here.
            as_of=None,
            entries_in_progress=sum(
                1 for occurrence in occurrences if _in_progress_at(occurrence, read_at)
            ),
            # `min` rather than "the first one after `read_at`": the occurrences
            # arrive in ascending start order today, and a fact this value depends
            # on is one worth not depending on.
            next_starts_at=min(later, default=None),
            covers_until=window_end,
        )

    def _coverage(
        self, window_start: datetime, window_end: datetime, *, accounted: bool
    ) -> ReadCoverage | None:
        """The interval this read exhausted, or ``None`` (ADR-0117 §5).

        **The interval is the one ``occurrences_in_window`` was asked to resolve**,
        with the same saturated edges the window decision was made on, so both ends
        are always representable instants. It is honest for reasons this reader does
        not have to supply: ADR-0093 §5 enforces a bound "by **refusing**, never by
        truncating" and §8 makes a read that cannot complete raise, so a
        ``SourceReading`` that exists at all is a read that reached its whole
        window; and the entry cap is applied *before* the skip rule, so a source
        busting its cap cannot become a successful "your calendar is clear". It is
        never widened to what this reader was *configured* to cover, because for
        this reader those are the same interval and ADR-0110 §2 forbids the
        difference from ever appearing.

        **And it is withheld outright where the read skipped anything** (§5's
        second clause). One uninterpretable entry withholds coverage for the whole
        reading — deliberately coarse, in the same shape ADR-0110 §4 already chose
        when one stored-nothing proposal suspends absence for a whole reading. The
        alternative is a coverage that is a *set* of intervals, which ADR-0110 §2's
        single half-open pair does not admit and ADR-0117 §11 files as a different
        decision. The cost is real and silent: a calendar carrying one entry this
        reader cannot read loses absence-demotion for as long as that entry is in
        the window.

        **A degenerate saturated interval declares none too, and the guard is belt
        and braces rather than a live branch.** ``ReadCoverage`` refuses a pair
        whose end is at or before its start, for its own good reason — such a
        coverage exhausted no instant — and both edges collapse onto one instant
        only for a ``read_at`` at the representable maximum with a zero
        ``window_past``, which :func:`~ai_assistant.core.clock.checked_clock`
        makes unreachable by refusing any reading outside the localizable range.
        It is **read rather than asserted** for the reason
        ``_refuse_unconformable`` keeps its own unreachable check: the
        unreachability is another module's invariant, not this one's, and a
        ``ValueError`` escaping this reader on a source that parsed perfectly is
        precisely the outcome §8 and ADR-0093 §7b's saturation rule exist to
        prevent. Declaring no coverage costs only a demotion such a read could not
        have warranted.

        Args:
            window_start: The window's inclusive lower edge, already saturated.
            window_end: Its exclusive upper edge, already saturated.
            accounted: Whether the read resolved every entry the source held —
                both halves, the resolution's and :meth:`_propose`'s.

        Returns:
            The coverage, or ``None`` where this reading warrants no absence.
        """
        if not accounted or window_end <= window_start:
            return None
        return ReadCoverage(covers_from=window_start, covers_until=window_end)

    def _propose(
        self, occurrences: Sequence[Occurrence], read_at: datetime
    ) -> tuple[tuple[MemoryUpdateProposal, ...], bool]:
        """Turn in-window occurrences into attested proposals, within the budget.

        Returns:
            The proposals, and whether every in-window occurrence became one. A
            ``False`` second element means an occurrence the source held inside the
            read's interval was skipped, so the reading declares no coverage
            (ADR-0117 §5).

        Raises:
            ContentBudgetExhaustedError: Before materialising a proposal that would
                take the read past ``calendar_max_content_bytes``.
        """
        spent = 0
        proposed_all = True
        proposals: list[MemoryUpdateProposal] = []
        for occurrence in occurrences:
            if occurrence.reported_at is None:
                # Skipped, not raised, and it has already been counted against the
                # entry cap (§7b). ADR-0092 §3 permits no substitute for a report
                # time the source did not make, and §1's validator then settles the
                # outcome structurally: no attestation means no `EXTERNAL`
                # provenance, so the record is not proposed as attested at all.
                #
                # It is also an entry the source **does** hold inside this read's
                # interval which the reading does not account for, so it withholds
                # the coverage (ADR-0117 §5). The facet still counts it: §5's
                # clause acts on the reading's coverage and never on the facet, and
                # ADR-0096 §5's asymmetry is preserved exactly as it was.
                proposed_all = False
                continue
            spent += occurrence.text_bytes + _RENDER_OVERHEAD_BYTES
            if spent > self._max_content_bytes:
                msg = (
                    f"the proposals would exceed the {self._max_content_bytes}-byte content budget"
                )
                raise ContentBudgetExhaustedError(msg)
            proposals.append(self._proposal(occurrence, occurrence.reported_at, read_at))
        return tuple(proposals), proposed_all

    def _proposal(
        self, occurrence: Occurrence, reported_at: datetime, read_at: datetime
    ) -> MemoryUpdateProposal:
        """One attested belief about one occurrence.

        **``reported_at`` lands in two fields for two different reasons**
        (ADR-0109 §4). In the ``Attestation`` it records who said what and when
        they said it — a disclosure obligation (ADR-0073 §4). As
        ``last_confirmed_at`` it records when the *world* last confirmed the
        belief, which for the ``ATTESTED`` band is the reporting source's report
        and never our ingestion of it (ADR-0103 §9). They are not redundant: a
        corroborating fold keeps this attestation while advancing the instant to
        an incoming derived record's (ADR-0103 §6), so the field must be stored
        and independently writable rather than derived from the attestation
        beside it (ADR-0109 §11).

        Args:
            occurrence: What the source says happens.
            reported_at: Its ``DTSTAMP``, already known to be present — the
                caller skips an occurrence without one rather than substituting.
            read_at: Our own clock, at acquisition.
        """
        content = _render(occurrence)
        return MemoryUpdateProposal(
            proposed=SemanticMemory(
                id=_mint(self._id_factory),
                content=content,
                fact=content,
                provenance=Provenance(
                    source=MemorySource.EXTERNAL,
                    confidence=_ATTESTED_CONFIDENCE,
                    # Ours: when *we* last revised the belief (ADR-0045 §3).
                    last_updated=read_at,
                    attestation=Attestation(
                        reported_by=self.name,
                        # Theirs, and never reconciled with ours. `reported_at`
                        # earlier than `last_updated` is the normal case rather
                        # than an anomaly: Monday's report, revised into the store
                        # on Tuesday (ADR-0092 §3).
                        reported_at=reported_at,
                        # Where this entry lies in the calendar's own world
                        # (ADR-0117 §6): the occurrence's own resolved span, in
                        # UTC, exactly as the window decision was made on it. A
                        # different fact from `reported_at` and never derived from
                        # it — an entry reported on Monday about a meeting on
                        # Thursday has both, and they disagree by design.
                        extent=_extent(occurrence),
                    ),
                    # The band's confirming event, written as it stands: a
                    # `reported_at` in our future is stored unchanged rather than
                    # dropped or clamped (ADR-0092 §3, ADR-0109 §4's fourth
                    # clause), because the fold is the only place a choice between
                    # two candidates exists. Never `read_at` — that would be
                    # transaction time, and a months-old report imported this
                    # morning would read as perfectly fresh (ADR-0103 §9).
                    last_confirmed_at=reported_at,
                ),
            ),
            rationale=f"the {self.name} source reported this entry",
            # Stated, never defaulted. `MemoryUpdateProposal.sensitivity` defaults
            # to `PERSONAL`, which is correct for a calendar and must not be
            # *assumed* correct for the next source; a producer that defaults its
            # way past this classification is the failure ADR-0004 §1's tiering
            # exists to prevent (ADR-0093 §4).
            sensitivity=DataTier.PERSONAL,
        )


def _extent(occurrence: Occurrence) -> ReportedExtent | None:
    """The occurrence's own span as producer testimony, or none (ADR-0117 §6).

    ``[occurrence.start, occurrence.end)`` — entry-anchored, stable across reads,
    and stating exactly what ADR-0110 §3's condition 3 wants stated: where in the
    calendar's world this entry lies. It is neither trimmed to the read's window
    nor widened past it, which ADR-0117 §2 forbids in both directions and §6
    restates for the two shapes that invite each.

    **A span with no width declines the extent, and must never raise.** ADR-0093
    §7b gives a date-time ``DTSTART`` with no end an instantaneous occurrence, and
    ``ReportedExtent`` refuses ``until == from`` for a reason of its own: an
    interval admitting no instant would be contained by *every* coverage, making
    such a record demotable by any reading at all. So the honest value is none. The
    entry is still proposed, still retrievable and still folded exactly as it is
    today; only its absence-demotability is withheld. Widening it by an invented
    epsilon would state an extent the source never gave (§2, §6).

    The comparison is ``<=`` rather than ``==`` because saturation can collapse a
    positive duration too: an occurrence starting at the representable maximum has
    an end saturated onto the same instant, and ``_duration`` has already refused a
    genuinely negative one by skipping the component.

    **An occurrence straddling the window edge needs no rule and is given none**
    (§6). ``_overlaps`` admits it deliberately, its span is simply not contained in
    the coverage, and ADR-0110 §3's containment therefore withholds the demotion on
    its own — the correct answer, since the reading did not exhaust the region that
    entry occupies.
    """
    if occurrence.end <= occurrence.start:
        return None
    return ReportedExtent(extends_from=occurrence.start, extends_until=occurrence.end)


def _in_progress_at(occurrence: Occurrence, instant: datetime) -> bool:
    """Whether ``occurrence`` is in progress at ``instant`` (ADR-0096 §6).

    ADR-0093 §7b's half-open membership, evaluated at an instant rather than over a
    window: ``start <= instant < end``. The zero-duration arm exists for §7b's own
    reason — a half-open interval of zero width contains nothing, so a reminder
    expressed as an instant would be *never* in progress rather than in progress
    for a moment, which is the entry vanishing rather than the boundary being
    debatable.
    """
    if occurrence.start == occurrence.end:
        return occurrence.start == instant
    return occurrence.start <= instant < occurrence.end


def _mint(factory: Callable[[], str] | None) -> str:
    """Mint one opaque record id, guarded at its output (ADR-0092 §6, ADR-0045 §4).

    **Opaque, and never the source's key.** ADR-0092 §6 rules that an ``EXTERNAL``
    producer "proposes each record at an id it mints, opaque to the source" and
    may never use a ``VEVENT`` ``UID``, a row id or a URL, "whether directly or
    namespaced" — nor may it *derive* one from content, which ADR-0081 §8 names in
    the same breath ("a content hash, or an external system's key adopted as the
    id"). A derived id is an **address**, aimed at the same record on every
    re-read, deterministically; "minting removes the aim", and with it the
    ADR-0038 §2a resurrection where a re-sync recomputes a retired record's id and
    erases its closed validity window through ``ACCEPT``'s blind upsert.

    **Idempotency does not vanish; it moves.** An unchanged re-read proposes the
    same content, ``_detect_conflicts`` ranks the identical live record top, and
    ``DefaultMemoryPolicy`` rules ``REINFORCE``, which folds at the *target's* id.

    Raises:
        ValueError: If the factory returns anything that is not a non-blank
            built-in ``str``. ADR-0092 §6 owes exactly this — "the producer's id
            factory is **guarded at its output**" — so a malformed mint fails
            loudly instead of becoming a key.
    """
    minted = factory() if factory is not None else f"calendar-{uuid4().hex}"
    # An **exact** ``str`` is required rather than an ``isinstance`` one: a
    # hostile subclass — one whose ``strip`` or ``__hash__`` raises — passes
    # ``isinstance`` and then leaks an arbitrary exception across the seam as a
    # store key. Nothing about the returned object is introspected in the message
    # either (not ``repr``, not ``type(...).__name__``), because a hostile
    # ``__repr__`` could raise past the guard.
    if type(minted) is not str or not minted.strip():
        msg = (
            "the id factory did not return a non-blank built-in str; "
            "a malformed mint must not become a key (ADR-0092 §6)"
        )
        raise ValueError(msg)
    return minted


def _render(occurrence: Occurrence) -> str:
    """One occurrence as the belief's canonical text.

    **``DESCRIPTION`` is deliberately not rendered.** It is where a calendar's
    bulk and its most sensitive content both live — meeting notes, dial-in
    credentials, a medical referral — and a belief is a durable, retrievable,
    exportable record. Title, time and place are what make an entry useful to the
    assistant; the rest is Tier 1 payload nobody asked us to keep.
    """
    title = occurrence.summary.strip() or "an untitled entry"
    where = occurrence.location.strip()
    place = f" at {where}" if where else ""
    return f'Calendar entry "{title}"{place}, {_when(occurrence)}.'


def _when(occurrence: Occurrence) -> str:
    """The occurrence's extent, rendered in the entry's own zone.

    **Rendering computes an instant too**, which is easy to forget because it
    looks like formatting. ADR-0093 §7b's saturation is stated over "every instant
    these sections compute", and the last date of an all-day span is one of them:
    a degenerate ``DTSTART;VALUE=DATE:00010101`` / ``DTEND;VALUE=DATE:00010101``
    entry is parseable, in-window under a window that reaches the minimum, and
    stepping back a day from its exclusive end is not representable. Unguarded
    that raises, and §8 then reports a source fault against a source that parsed
    perfectly — the outcome the saturation rule exists to prevent, arriving
    through the one arithmetic nobody counts as arithmetic.
    """
    start, end = occurrence.local_start, occurrence.local_end
    if start is None or end is None:
        # One end of the interval has no honest name in this entry's own zone,
        # which is reachable only within a day of a representable bound: an
        # unrepresentable *end* at the top (`Pacific/Kiritimati`, UTC+14), and at
        # the bottom a stated *start* whose true instant underflows, so the wall
        # time the source gave stops describing the instant we saturated to
        # (`Asia/Kolkata`, whose year-1 offset is +05:53:28). Naming the whole
        # interval in UTC is unambiguous; clamping a wall clock to make it fit
        # names a *different* instant, and the rendered duration is then one the
        # source never gave.
        return f"from {occurrence.start:%Y-%m-%d %H:%M} to {occurrence.end:%Y-%m-%d %H:%M} (UTC)"
    if occurrence.all_day:
        # The end is exclusive, so a one-day entry ends on the following date.
        # Saturated: see this function's docstring.
        last = saturating_shift(end, -timedelta(days=1))
        if last.date() <= start.date():
            return f"all day on {start:%Y-%m-%d}"
        return f"all day from {start:%Y-%m-%d} to {last:%Y-%m-%d}"
    zone = occurrence.zone_label
    if start == end:
        return f"at {start:%Y-%m-%d %H:%M} ({zone})"
    if start.date() == end.date():
        return f"on {start:%Y-%m-%d} from {start:%H:%M} to {end:%H:%M} ({zone})"
    return f"from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} ({zone})"


def _check_window(field: str, value: timedelta, *, allow_zero: bool) -> None:
    floor = timedelta(0)
    if value < floor or (value == floor and not allow_zero) or value > MAX_CALENDAR_WINDOW:
        bound = ">= 0" if allow_zero else "> 0"
        msg = (
            f"{field} must be {bound} and <= {MAX_CALENDAR_WINDOW}, got {value!r}; "
            f"the ceiling is what keeps `read_at + {field}` representable (ADR-0093 §7a)"
        )
        raise ValueError(msg)


def _check_count(field: str, value: int) -> None:
    # `bool` is an `int` by inheritance and a flag is not a count — the rule the
    # four layers under `Settings` already state, at the seam a direct caller
    # reaches (issue #471).
    if isinstance(value, bool) or type(value) is not int or not 1 <= value < MAX_CALENDAR_COUNT:
        msg = f"{field} must be an int in [1, 2**63), got {value!r}"
        raise ValueError(msg)


def _check_positive_int(field: str, value: int) -> None:
    if isinstance(value, bool) or type(value) is not int or value <= 0:
        msg = f"{field} must be a positive int, got {value!r}"
        raise ValueError(msg)


__all__ = [
    "CALENDAR_READER_NAME",
    "DEFAULT_CALENDAR_MAX_BYTES",
    "DEFAULT_CALENDAR_MAX_CONTENT_BYTES",
    "DEFAULT_CALENDAR_MAX_ENTRIES",
    "DEFAULT_CALENDAR_MAX_EXPANSION",
    "DEFAULT_CALENDAR_READ_TIMEOUT",
    "DEFAULT_CALENDAR_WINDOW_FUTURE",
    "DEFAULT_CALENDAR_WINDOW_PAST",
    "MAX_CALENDAR_COUNT",
    "MAX_CALENDAR_WINDOW",
    "CalendarReader",
    "ContentBudgetExhaustedError",
]
