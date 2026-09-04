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

**The ``singlefile`` arrangement is verified, not assumed.** #649 recorded the
storage's existence as "unverified in-session", and the deferral of §7's widening
rests on it — so it was checked against ``vdirsyncer`` 0.20.0 rather than left
asserted. ``SingleFileStorage`` exists, writes an entire collection into one
``VCALENDAR``, and ``checkfile`` refuses a path that exists and is not a file, so
the output is a regular file by construction. ``tests/readers/`` pins bytes it
actually produced.

**Its writes are atomic, and that is what makes the pairing safe rather than
merely workable.** ``singlefile`` writes through ``atomic_write(..., overwrite=
True)``, which is ``mkstemp`` in the target's own directory followed by
``os.rename`` — so **once a sync has succeeded** the configured path resolves to
a *complete* collection and never a half-written one, and a sync landing mid-read
swaps the inode under a descriptor this reader already holds rather than
corrupting what it is reading. §7b's acquisition instant therefore always
describes bytes that were whole, and the mid-read mutation hazard #649 raises
against a *directory* source has no counterpart here. Nothing in this module
depends on that — the descriptor check and the capped read stand on their own —
but a deployment note that recommended a fetcher writing in place would be
recommending something weaker.

**Atomicity has nothing to offer before the first sync, so the order of the
deployment steps is load-bearing** (#890). Run ``vdirsyncer discover calendar``
*and* one successful ``vdirsyncer sync calendar`` **before** arming
``ASSISTANT_CALENDAR_READER_INTERVAL`` or ``ASSISTANT_CALENDAR_UPCOMING_INTERVAL``
and before granting the source. Until a sync has landed there is nothing whole to
read, and this reader says so on every tick:

* **Before the local side is created**, the path does not exist, ``os.open``
  raises ``FileNotFoundError``, and ``read()`` raises ``ReaderError`` reading
  ``calendar: SourceUnavailableError (FileNotFoundError)``.
* **After it is created but before a sync has landed**, the path exists and holds
  **zero bytes** — ``SingleFileStorage.create_collection``, which is what
  ``vdirsyncer discover`` calls, creates it through ``checkfile(path,
  create=True)``, and that opens the path ``"wb"`` and closes it. Zero bytes is
  not an iCalendar document, so ``read()`` raises ``ReaderError`` reading
  ``calendar: SourceNotParseableError (ValueError)``. **Discovering the
  collection is therefore not enough**, which is the half of this ordering that
  surprises: the path an operator checks for is there, and the read still fails.

Once one sync has landed a collection, a calendar that is *genuinely* empty is a
well-formed ``VCALENDAR`` carrying no ``VEVENT``, and that reads as a **success
with zero proposals** (§8) rather than as either failure above — so the two states
are distinguishable and neither is silently read as "no events".

Neither failure needs an operator to intervene. §8 gives a read's failure both its
postures — advisory on the facet side, and on the ingestion side ADR-0083 §7's
"logged with its class, retried at the next due instant, never a process exit" —
so the hub keeps running, nothing is corrupted and nothing is lost, and the first
successful sync clears it. It is an ordering gotcha rather than a defect, and it
is written down because the paragraph above is a statement about the *write* and
reads, on its own, as a promise about the path's whole lifetime.

**Deploying it** (the fetcher is a co-located mature tool and deliberately not a
dependency of this project, ADR-0095 §Context). Install ``vdirsyncer`` on the hub
box as a *tool* — ``uv tool install vdirsyncer`` — and give it a ``singlefile``
side::

    [general]
    status_path = "~/.vdirsyncer/status"

    [pair calendar]
    a = "remote"
    b = "local"
    collections = null

    [storage remote]
    type = "caldav"          # or "http" for an .ics subscription URL
    url = "..."
    read_only = true         # REQUIRED for caldav — see below

    [storage local]
    type = "singlefile"      # NOT "filesystem" — that writes a directory (#649)
    path = "~/.calendars/calendar.ics"

**``read_only = true`` on the remote is not optional, and leaving it out points a
write path at the user's real calendar.** ``vdirsyncer``'s sync is bidirectional
by default — ``Storage.read_only`` is ``False`` on the base class, and ``caldav``
inherits it — so anything that edits the local ``.ics`` is treated as a local
change and **uploaded to the calendar server** on the next sync. Nothing in this
project writes to that file, but the file is an ordinary path on the user's
machine and the seam it feeds is read-only by construction (ADR-0093 §1: a reader
"holds no store, writes nothing"); a deployment that can push edits outward has a
capability the design never granted it. With the flag set, ``vdirsyncer`` reverts
local divergence instead of uploading it, which is what makes the local file a
*mirror* rather than a replica. ``type = "http"`` needs no flag — ``HttpStorage``
sets ``read_only = True`` itself, since a subscription URL has nothing to write
to.

Run ``vdirsyncer discover calendar`` once, then ``vdirsyncer sync calendar`` on a
timer the fetcher owns (cron or a systemd timer) — the network is the fetcher's
and never this seam's, which is the whole point of the pattern. **One sync must
have succeeded before the settings below are armed**, for the reason given above.
Point the hub at its output and arm the job::

    ASSISTANT_CALENDAR_READER_PATH=/home/you/.calendars/calendar.ics
    ASSISTANT_CALENDAR_READER_INTERVAL=PT15M

The two settings are a matrix ``Settings`` refuses to leave incoherent: an
interval with no path fails at load (§7a). **Configuration is not consent** — the
hub reads nothing until the user grants the source through a client, and until
then the scheduler's job fails every tick with ``SourceNotGrantedError`` rather
than reading (ADR-0097 §5)::

    assistant sources                                    # shows the location
    assistant grant calendar --scope facet --scope ingest
    assistant revoke calendar                            # prospective (ADR-0097 §6)

The reader's identity is ``calendar`` and a grant keys on **that**, never on the
path (ADR-0097 §1) — so repointing the path leaves the grant standing over the new
location, which ADR-0097 §9a states and does not close.

**Arming unprompted contact is three further acts, and none implies another**
(ADR-0132 §4, ADR-0133 §3). Everything above arms *ingestion* — this file read
into beliefs. The upcoming-event producer is a second, independent consumer of
the same reading (ADR-0093 §3), so arming one arms neither the other nor any
interruption. In the order they can be performed:

1. **The operator arms the producer**, in the hub's environment. It needs the
   path above and nothing else — it does **not** need
   ``ASSISTANT_CALENDAR_READER_INTERVAL``, and setting either changes the other
   job's cadence in no way (ADR-0132 §4)::

       ASSISTANT_CALENDAR_READER_PATH=/home/you/.calendars/calendar.ics
       ASSISTANT_CALENDAR_UPCOMING_INTERVAL=PT5M     # unset: the producer is off
       ASSISTANT_CALENDAR_UPCOMING_LEAD=PT30M        # the default

   Every duration setting takes **either an ISO-8601 duration or an
   ``HH:MM:SS`` clock string**, and a clock string is read from the left as
   **hours** — ``PT5M`` and ``00:05:00`` are both five minutes, ``PT30S`` is
   thirty seconds, ``15:00`` is fifteen **hours** rather than fifteen minutes,
   and ``5:00`` is refused outright. Write the full ``HH:MM:SS`` and none of
   that arises. The wrong-by-a-factor-of-sixty form is the one that costs an
   afternoon, because it *loads*: ``ASSISTANT_CALENDAR_READER_INTERVAL=15:00``
   arms a read every fifteen **hours** and nothing refuses it. On the pair
   above it happens to be refused at the defaults, but only because the lead
   rule below catches a lead no greater than the interval — that is a
   coherence rule about the two settings, not a guard on the form.

   What is **not** accepted from the environment is a bare number of seconds:
   ``15`` and ``300`` are both refused at load with a parse error naming a
   ``"day"`` identifier nobody typed. That is pydantic's message and the same
   for every duration setting here, and it is the one thing about this chain
   most likely to stop an operator (#981).

   The lead must be strictly greater than the interval — a shorter one leaves
   occurrences that no tick ever sees — and no larger than
   ``ASSISTANT_CALENDAR_WINDOW_FUTURE``, which would select from occurrences the
   read never returns. Both are refused at load rather than discovered as a job
   that runs, logs nothing and reports health.

2. **The user grants the read**, a third use of the source that ``facet`` and
   ``ingest`` do not back-fill (ADR-0133 §3)::

       assistant grant calendar --scope notify

   The source is **positional**; there is no ``--source`` option. A source holds
   one grant at a time, so adding ``notify`` to a calendar already granted for
   ingestion is ``assistant revoke calendar`` and then one ``grant`` naming every
   scope wanted — ``--scope facet --scope ingest --scope notify`` — and both acts
   stay on the record.

3. **The user raises the class's reach.** Every class ships at ``hold``, so a
   producer cannot interrupt on the day it ships (ADR-0130 §6)::

       assistant tune --class upcoming_event --reach interrupt

   ``assistant notification-settings`` prints what is set now, ``assistant
   notifications`` prints each held record beside its own class, and ``assistant
   tune --help`` carries these same three acts from the user's side.

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
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast, final
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
                IANA zone, or any figure is outside ADR-0093 §7a's range —
                **including when that argument is of the wrong type**. Every
                argument validated here is typed before it is compared or called
                into, so a direct caller's mistake is refused as a value naming
                the field rather than escaping as an operator's ``TypeError`` or
                as an ``AttributeError`` naming a method (#1057).

                ``now`` is deliberately **not** among them, and its absence is a
                decision rather than a gap: a clock is a callable whose readings
                change, so ADR-0026 has :func:`~ai_assistant.core.clock.checked_clock`
                guard every reading instead — "validating once at startup would
                certify a property the clock does not have". ``id_factory`` is
                guarded at its output for ADR-0092 §6's reason, likewise not here.
        """
        source = _checked_path(path)
        zone = _checked_zone(timezone)
        past = _checked_window("calendar_window_past", window_past, allow_zero=True)
        future = _checked_window("calendar_window_future", window_future, allow_zero=False)
        _check_count("calendar_max_entries", max_entries)
        _check_count("calendar_max_expansion", max_expansion)
        _check_positive_int("calendar_max_bytes", max_bytes)
        _check_positive_int("calendar_max_content_bytes", max_content_bytes)
        timeout = _checked_timeout("calendar_read_timeout", read_timeout)

        self._path = source
        self._now = checked_clock(now, owner="CalendarReader")
        self._zone: tzinfo = zone
        self._window_past = past
        self._window_future = future
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_expansion = max_expansion
        self._read_timeout = timeout
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


def _checked_path(value: object) -> Path:
    """The configured source as an absolute built-in ``Path``, or a refusal naming it.

    **Typed before it is called into**, which is this constructor's rule for every
    argument rather than a guard bolted onto one: a ``str`` has no ``is_absolute``
    and ``None`` has no attributes at all, so an unguarded call turns a caller's
    mistake into an ``AttributeError`` naming a *method* instead of the
    ``ValueError`` naming the field this seam documents. The ``str`` case is the
    one a second composition root actually writes, because it looks correct.

    Typed ``object`` and returning the narrowed value, for
    :func:`_refuse_a_non_duration`'s reason: a ``Path`` annotation would make the
    refusal statically unreachable, which is the reasoning that let the value
    through. The type refusal names the type rather than the value — a hostile
    ``__repr__`` must not raise past a guard (#1978) — and it reaches that name
    through :func:`_type_name_of`, because the read is itself a call into the
    refused object's class and owes it the same distrust (#2104).

    **The type test is put to the *real* class, never to the object.**
    ``isinstance`` falls back to ``value.__class__`` when the concrete type does not
    match, so an object of an unrelated class answering that attribute with ``Path``
    passes it — and one whose ``__class__`` *raises* takes the guard down before any
    refusal is built. ``issubclass(type(value), Path)`` asks ``Py_TYPE``, which no
    object can override, and it admits exactly the same honest subclasses.

    **Accepted, then rebuilt**, which is :func:`_checked_duration`'s two halves at
    this seam and for its reason (#1979). Acceptance stays a subclass test because
    honest ``Path`` subclasses exist and none is *silently* accepted the way
    ``bool`` is by the integer guards. The rebuild is what makes the check below
    hold and its message safe, because both ask the refused value about itself: a
    subclass may override ``is_absolute`` to answer ``True`` for a relative
    location, and ``__str__`` or ``__fspath__`` to raise inside the message that
    reports one. ``Path(value)`` copies the unparsed strings a ``PurePath`` already
    holds, so it consults none of those three, and it is **not** ``resolve()`` — no
    symbolic link is followed and no component is renamed, so a plain ``Path``
    rebuilds to itself. It is the rebuilt path that is checked, reported and
    returned.

    **The rebuild is itself guarded**, unlike :func:`_checked_duration`'s C-level
    ``timedelta.__sub__``: it reads ``PurePath``'s own ``parser`` and
    ``_raw_paths``, which are ordinary Python attributes a genuine subclass can
    override to raise. Catching that and refusing is what makes "nothing but a
    ``ValueError`` leaves this constructor" true rather than nearly true.
    ``Exception`` is caught and ``BaseException`` deliberately is not, for
    :func:`_type_name_of`'s reason (ADR-0060 §1).

    Returns:
        The same location as a built-in ``Path``, whatever subclass carried it.

    Raises:
        ValueError: If ``value`` is not a ``Path``, will not rebuild as one, or is
            not absolute. Absoluteness is the *shape* checked here; existence is a
            property of the world at an instant and is checked at run time, where it
            degrades under ADR-0093 §8.
    """
    if not issubclass(type(value), Path):
        msg = f"the calendar source must be a Path, got {_type_name_of(value)}"
        raise ValueError(msg)
    # `issubclass(type(...))` establishes the type without asking the object, but it
    # narrows nothing for `mypy`; the cast records what the line above proved.
    try:
        source = Path(cast("Path", value))
    # A blind `except Exception` on purpose — see the docstring; `BaseException`
    # is deliberately not caught.
    except Exception as exc:
        msg = (
            f"the calendar source must be a Path that rebuilds to a built-in one, "
            f"got {_type_name_of(value)}"
        )
        raise ValueError(msg) from exc
    if not source.is_absolute():
        msg = (
            f"the calendar source must be an absolute path, got {str(source)!r}; a "
            f"relative value resolves against each process's working directory "
            f"(ADR-0093 §7)"
        )
        raise ValueError(msg)
    return source


def _checked_zone(value: object) -> ZoneInfo:
    """The configured zone resolved, or a refusal naming what was wrong with it.

    Typed before it is called into, for :func:`_checked_path`'s reason: ``ZoneInfo``
    accepts anything ``os.PathLike``-ish and raises its own ``TypeError`` for the
    rest, so ``timezone=None`` escaped as ``expected str, bytes or os.PathLike
    object, not NoneType`` — a message naming neither this reader's field nor the
    rule the ``Raises:`` clause above promises for it.

    **The type test is put to the real class**, for :func:`_checked_path`'s
    reason: ``isinstance`` falls back to ``value.__class__``, so an impostor
    answering it with ``str`` reaches the rebuild below, where ``str.__str__``
    refuses it with a ``TypeError`` rather than this guard's ``ValueError``.

    **Accepted, then rebuilt**, for :func:`_checked_path`'s reason at the other end
    of the same problem: a ``str`` subclass overriding ``__repr__`` raises inside
    the refusal that reports an unknown zone. Here the rebuild needs no guard of
    its own — ``str.__str__`` reads the C-level slot and answers with a built-in
    ``str`` — and it changes nothing a caller sees, because ``ZoneInfo`` keys on
    the characters rather than on the object.

    Raises:
        ValueError: If ``value`` is not a ``str``, or is not a known IANA zone.
    """
    if not issubclass(type(value), str):
        msg = f"the calendar timezone must be a str, got {_type_name_of(value)}"
        raise ValueError(msg)
    name = str.__str__(value)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"unknown timezone {name!r}"
        raise ValueError(msg) from exc


def _checked_duration(field: str, value: object) -> timedelta:
    """A configured duration as a built-in ``timedelta``, or a refusal naming the field.

    Typed ``object`` because the guard **disbelieves the annotation, which is the
    point** — the same reason :func:`~ai_assistant.core.clock.checked_clock`
    states for its own parameter. A ``timedelta`` annotation here would make the
    refusal statically unreachable, which is exactly the reasoning that let the
    value through in the first place.

    **The type check is the two integer guards' rule for the durations**, and
    without it this constructor is asymmetric with itself: ``_check_count``
    refuses anything that is not exactly an ``int`` while a duration reached a
    bare ``<``, so ``window_past=None`` escaped as a ``TypeError`` from an
    operator rather than as the ``ValueError`` this constructor documents
    (#1057). The type rather than ``repr``, for :func:`_checked_path`'s reason:
    this guard is reached by a value of *arbitrary* type, so a hostile
    ``__repr__`` would raise straight past a refusal whose whole purpose is that
    nothing but a ``ValueError`` leaves this constructor — and the type is named
    through :func:`_type_name_of`, because the name read is itself a call into
    the refused object's class (#2104).

    **The type test is put to the *real* class, never to the object.**
    ``isinstance`` falls back to ``value.__class__`` when the concrete type does not
    match, so an object of an unrelated class answering that attribute with ``timedelta``
    passes it — and one whose ``__class__`` *raises* takes the guard down before any
    refusal is built. ``issubclass(type(value), timedelta)`` asks ``Py_TYPE``, which no
    object can override, and it admits exactly the same honest subclasses.

    **Accepted, then canonicalised** — the two halves answer different problems and
    neither substitutes for the other. Acceptance is a subclass test rather than an
    exact-type test, unlike the integer guards:
    they are exact for a *reachable* reason (``bool`` is an ``int`` by
    inheritance, so ``max_entries=True`` passes ``mypy`` and loads as a cap of
    one — #471), while no ``timedelta`` subclass is silently accepted that way
    and honest ones exist, so refusing a caller genuinely passing a duration
    would buy nothing.

    Canonicalisation is what makes the *bounds* hold. A subclass overriding
    ``__lt__`` and ``__gt__`` to answer ``False`` evades every comparison below,
    and one overriding ``__repr__`` raises past the range message that reports
    it — because both ask the refused value about itself. An exact-type test
    would not fix that shape either; **not comparing against the caller's object
    at all** does. ``timedelta.__sub__`` reads the C-level slots and builds a
    built-in ``timedelta``, so it is immune to an override of ``__sub__``,
    ``days``, the comparisons or ``__repr__``, and it is the returned value that
    is range-checked, reported and stored.

    Returns:
        The same duration as a built-in ``timedelta``, whatever subclass carried it.

    Raises:
        ValueError: If ``value`` is not a ``timedelta``.
    """
    if not issubclass(type(value), timedelta):
        msg = f"{field} must be a timedelta, got {_type_name_of(value)}"
        raise ValueError(msg)
    # `issubclass(type(...))` establishes the type without asking the object, but it
    # narrows nothing for `mypy`; the cast records what the line above proved.
    return timedelta.__sub__(cast("timedelta", value), timedelta(0))


def _checked_timeout(field: str, value: object) -> timedelta:
    duration = _checked_duration(field, value)
    if duration <= timedelta(0):
        msg = f"{field} must be > 0, got {duration!r}"
        raise ValueError(msg)
    return duration


def _checked_window(field: str, value: object, *, allow_zero: bool) -> timedelta:
    duration = _checked_duration(field, value)
    floor = timedelta(0)
    if duration < floor or (duration == floor and not allow_zero) or duration > MAX_CALENDAR_WINDOW:
        bound = ">= 0" if allow_zero else "> 0"
        msg = (
            f"{field} must be {bound} and <= {MAX_CALENDAR_WINDOW}, got {duration!r}; "
            f"the ceiling is what keeps `read_at + {field}` representable (ADR-0093 §7a)"
        )
        raise ValueError(msg)
    return duration


#: What a type refusal names when the type will not say what it is called.
_UNNAMEABLE_TYPE: Final = "an unnameable type"


def _type_name_of(value: object) -> str:
    """``type(value).__name__``, or a fixed literal where reading it will not answer.

    **The name read is itself a call into the refused object's class**, which is
    the half of #1978 that survived substituting ``repr``: a metaclass may
    override ``__getattribute__`` for ``"__name__"`` and raise, or answer with
    something that is not a built-in ``str`` whose own rendering then raises.
    Either takes the refusal down with the value it was refusing — the same
    wrong-exception-class escape one level in, so a guard that reaches for a type
    name owes this read the same distrust it gives the value.

    :func:`~ai_assistant.core.types.fault_class_of` guards the same read for the
    same reason and this mirrors its shape rather than inventing a second one:
    ``Exception`` is caught and ``BaseException`` is **not**, so a
    ``CancelledError`` raised by the name read is delivered onward (ADR-0060 §1).
    ``type(name) is str`` rather than ``isinstance`` for :func:`_checked_int`'s
    reason — a ``str`` subclass is a second object with a second chance to raise,
    and this one is asked to render itself into the message.

    Args:
        value: The refused object, asked only what its type is called.

    Returns:
        The type's name, or :data:`_UNNAMEABLE_TYPE` where it could not be read.
    """
    try:
        name = type(value).__name__
        nameable = type(name) is str and bool(name)
    # A blind `except Exception` on purpose — see the docstring; `BaseException`
    # is deliberately not caught. `BLE` is not enabled in this tree and `RUF100`
    # fails the gate on an unused directive, so the reason stays a comment.
    except Exception:
        return _UNNAMEABLE_TYPE
    return name if nameable else _UNNAMEABLE_TYPE


def _checked_int(field: str, value: object, domain: str) -> int:
    """A configured figure as a built-in ``int``, or a refusal naming its type.

    Typed ``object`` because the guard **disbelieves the annotation**, for
    :func:`_checked_duration`'s reason: an ``int`` annotation would make the
    refusal statically unreachable, which is the reasoning that lets a value
    through.

    **The type test is separated from the range test below it, and the two
    refusals render the offending value differently on purpose** (#1978). This
    guard is reached by a value of *arbitrary* type, so a message built with
    ``repr`` lets the refused object's own ``__repr__`` run inside the message
    that refuses it — a hostile one then raises straight past the guard, turning
    the wrong-exception-class defect the guard exists to fix into a different
    one. That is :func:`_checked_path`'s discipline, and it is why the type
    refusal names the type — through :func:`_type_name_of`, because the name read
    is a call into the refused object's class and owes the same distrust. Below
    this guard ``repr`` is not
    merely safe but *right*: what a caller needs from a range violation is
    ``got 0``, and ``got int`` tells them nothing.

    **Exact rather than ``isinstance``**, which is what draws both lines at
    once: ``bool`` is an ``int`` by inheritance, so ``max_entries=True`` passes
    ``mypy`` and would load as a cap of one — a value silently accepted, which
    is #471's defect. Exactness is also what makes the range message safe
    without the canonicalisation :func:`_checked_duration` needs. That guard
    accepts a ``timedelta`` subclass and so must build its own built-in value
    before reporting one; here no subclass is accepted at all, so the figure the
    range message renders is a built-in ``int`` whose ``__repr__`` is
    ``int.__repr__``.

    Args:
        field: The setting's name, spelled as an operator configures it.
        value: The configured figure, disbelieved until it has been checked.
        domain: The rule, phrased once for both of this figure's refusals.

    Returns:
        The same figure, as the built-in ``int`` it has been proved to be.

    Raises:
        ValueError: If ``value`` is not exactly an ``int``.
    """
    if type(value) is not int:
        msg = f"{field} must be {domain}, got {_type_name_of(value)}"
        raise ValueError(msg)
    return value


def _check_count(field: str, value: object) -> None:
    domain = "an int in [1, 2**63)"
    figure = _checked_int(field, value, domain)
    if not 1 <= figure < MAX_CALENDAR_COUNT:
        msg = f"{field} must be {domain}, got {figure!r}"
        raise ValueError(msg)


def _check_positive_int(field: str, value: object) -> None:
    domain = "a positive int"
    figure = _checked_int(field, value, domain)
    if figure <= 0:
        msg = f"{field} must be {domain}, got {figure!r}"
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
