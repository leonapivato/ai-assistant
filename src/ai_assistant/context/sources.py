"""Context sources — the internal, composable seam of the context subsystem.

A ``ContextSource`` contributes part of the situational context. This seam is
**internal to `context/`** (ADR-0008 §2): it is not a cross-subsystem contract,
so its partial ``Mapping`` contributions never cross a boundary — only the
assembled :class:`~ai_assistant.core.types.CurrentContext` does.

``ClockContextSource`` derives the temporal context (time of day, weekend,
working hours) from an injected clock and configured locale.
``CalendarContextSource`` is the first source that reads the world: it holds a
``Reader`` and a ``SourceGrants``, and contributes the calendar facet when — and
only when — a live grant covers that read. ``EmailContextSource`` is the second
(ADR-0140 §6), and the two are the same object with two pairings: both derive
from ``_GrantedFacetSource``, which owns ADR-0097 §5a's gate once and takes the
``CurrentContext`` field and the facet type it accepts from the concrete class.

Nothing concrete is imported. The reader and the grant seam arrive by injection
and are seen only through their Protocols (CLAUDE.md golden rule 1), which
``lint-imports`` enforces literally: no subsystem may import
``ai_assistant.readers`` or ``ai_assistant.permissions``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConfigurationError, ContextError
from ai_assistant.core.types import (
    CalendarFacet,
    ContextFacet,
    EmailFacet,
    GrantScope,
    TimeOfDay,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import Reader, SourceGrants


def _utcnow() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class ContextSource(Protocol):
    """A single contributor to the situational context (internal to `context`).

    A source may additionally carry a ``required`` attribute. It is deliberately
    **not** declared here (ADR-0026 §4): a ``Protocol`` member is mandatory for
    structural conformance and supplies no default, so declaring it would make
    every existing source non-conforming and a bare ``source.required`` would
    raise ``AttributeError`` inside the very degradation path it selects. The
    assembler reads it as ``getattr(source, "required", False)``; absent means
    optional, which is both the safe default and the one that keeps this seam
    additive.
    """

    @property
    def name(self) -> str:
        """A stable identifier, used for collision reporting and logging.

        It is **Tier 2 / operational** (ADR-0004 §1) and must stay that way: the
        assembler logs it verbatim when a source degrades, times out, or is
        abandoned, so it must never embed Tier 0/1 data — no secret, and no value
        derived from user or third-party personal data (ADR-0004 §5). A source
        that wraps personal data names *itself* (``"calendar"``), never the data
        it holds (``"alice@example.com calendar"``). This obligation is what lets
        the assembler log ``name`` verbatim in the same line where it reduces an
        exception to its class, and is stated so a future source cannot read
        "used for logging" as licence to smuggle personal data through it
        (ADR-0055).
        """
        ...

    async def contribute(self) -> Mapping[str, object]:
        """Return this source's partial set of ``CurrentContext`` fields."""
        ...


def _time_of_day(hour: int) -> TimeOfDay:
    """Bucket a local 24h ``hour`` into a coarse time of day."""
    if 5 <= hour < 12:  # noqa: PLR2004  boundary hours are self-evident
        return TimeOfDay.MORNING
    if 12 <= hour < 17:  # noqa: PLR2004
        return TimeOfDay.AFTERNOON
    if 17 <= hour < 21:  # noqa: PLR2004
        return TimeOfDay.EVENING
    return TimeOfDay.NIGHT


class ClockContextSource:
    """Contributes the temporal context from a clock and configured locale.

    Structurally implements :class:`ContextSource`. It performs no I/O, so a
    *conforming* clock cannot fail per request and the temporal core of the
    context is always available (ADR-0008 §4, as amended by ADR-0026 §6). A
    reading that is naive, indeterminate or outside the localizable range is a
    wiring bug, not degradation: it raises ``ContextError`` and, because this
    source is :attr:`required`, that failure reaches the caller rather than
    leaving the facet absent.
    """

    def __init__(
        self,
        *,
        timezone: str = "UTC",
        working_hours_start: int = 9,
        working_hours_end: int = 17,
        now: Clock = _utcnow,
    ) -> None:
        """Initialise the source, validating the locale at construction (startup).

        Args:
            timezone: IANA timezone name for local-time computation.
            working_hours_start: First hour of the working window (local, 0-23).
            working_hours_end: End hour of the working window (local, exclusive).
            now: Clock returning the reference instant; injectable for tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                naive, indeterminate or unlocalizable reading is a wiring bug
                rather than a fabricated UTC instant (ADR-0026 §2).

        Raises:
            ConfigurationError: If the timezone is unknown or the working-hours
                window is not a valid, non-empty range.
        """
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown timezone {timezone!r}"
            raise ConfigurationError(msg) from exc
        if not 0 <= working_hours_start < working_hours_end <= 24:  # noqa: PLR2004
            msg = (
                f"invalid working-hours window: start={working_hours_start}, "
                f"end={working_hours_end} (require 0 <= start < end <= 24)"
            )
            raise ConfigurationError(msg)
        self._working_start = working_hours_start
        self._working_end = working_hours_end
        self._now = checked_clock(now, owner="ClockContextSource")

    @property
    def name(self) -> str:
        """This source's stable identifier."""
        return "clock"

    @property
    def required(self) -> bool:
        """Always ``True``: the temporal core cannot be degraded away.

        ADR-0008 §4 skips a failing *optional* source and leaves its facet
        ``None``. ``now`` has no ``None`` to fall back to — ``CurrentContext``
        could not be constructed without it — so a broken clock here is a wiring
        bug that must reach the caller with its cause intact, not a facet that
        quietly goes absent (ADR-0026 §4). Read by
        :class:`~ai_assistant.context.provider.AssemblingContextProvider` as
        ``getattr(source, "required", False)``; every other source omits it and
        is therefore optional.
        """
        return True

    async def contribute(self) -> Mapping[str, object]:
        """Contribute ``now``, ``time_of_day``, ``is_weekend``, ``within_working_hours``.

        Raises:
            ContextError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
                ``core`` raises ``ValueError``; translating it here is `context`
                declaring its own boundary error for a wiring bug (ADR-0026 §4).
                It is *not* degradation: see :attr:`required`.
        """
        try:
            instant = self._now()
        except ClockReadingError as exc:
            raise ContextError(str(exc)) from exc
        local = instant.astimezone(self._zone)
        return {
            "now": instant,
            "time_of_day": _time_of_day(local.hour),
            "is_weekend": local.weekday() >= 5,  # noqa: PLR2004  Sat=5, Sun=6
            "within_working_hours": self._working_start <= local.hour < self._working_end,
        }


class _GrantedFacetSource:
    """A context source that reads one source under a grant and contributes its facet.

    Structurally implements :class:`ContextSource`. ADR-0093 §3's ruling in one
    object — "A ``ContextSource`` in `context/` holds a ``Reader``" — with
    ADR-0097 §5's gate in front of it, which is the caller's and never the
    reader's: "A ``Reader`` neither holds a grant seam nor learns of one."

    **The pairing of a ``CurrentContext`` field with the facet type admissible in
    it is declared by the concrete class and is the whole of what a concrete class
    declares.** ADR-0096 §5 rules that the adapter "contributes the facet from the
    reading it took, under the ``CurrentContext`` field it was wired for" and that
    "a facet whose type does not match that field is a wiring bug" — one field, one
    type, decided where the source is defined. Holding that pair in two class-level
    :data:`~typing.ClassVar` declarations rather than in two literals inside a
    copied ``contribute`` is what makes the second facet source *be* the first: the
    gate below, whose five ADR-0097 §5a cases are the expensive part, exists once.

    **That is a defence against a named hazard rather than tidiness.** ADR-0140
    §13's facet item observes that the calendar adapter "writes its field as a
    literal in the mapping it returns, so a lane copying that module and changing
    only the reader ships it" — an adapter that reads email under a live grant and
    contributes the facet under ``calendar``. Deriving the key from the same
    declaration the type guard reads makes the two impossible to disagree: there is
    no second place to change and forget.

    **The pair is class-level and deliberately not a constructor argument.** A
    composition root free to pass ``field="calendar"`` beside ``EmailFacet`` could
    wire the mismatch this class exists to refuse, and the refusal would then be
    checking one runtime value against another. Declared on the class, the pairing
    is fixed where it is reviewed, and a composition root chooses only *which*
    source it builds.

    **It reads at assembly time and contributes what that read carried, never a
    cached value** (ADR-0096 §3). A facet is built from a reading taken during the
    assembly that returns it; a failed read yields an absent facet rather than the
    previous one. That is ADR-0008 §5's "computes fresh each call — context is a
    point-in-time snapshot, not cached state" stated over the facet the snapshot
    now contains, and it is what makes the no-cache rule *checkable*: a facet whose
    ``read_at`` is materially older than ``now`` is a cache someone introduced.

    **It carries no ``required`` marker, so every fault here ends at an absent
    facet** (ADR-0026 §4, ADR-0008 §4). A ``ReaderError``, a ``GrantError``, a
    timeout, a wiring bug — the assembler's ``_safe_contribute`` logs the class and
    skips the source, and :attr:`_field` is ``None`` on the assembled context.
    ADR-0096 §4 rules that the ``None`` says nothing beyond its absence, and
    ADR-0097 §5 adds *ungranted* to the states it does not distinguish: an
    ungranted source is observationally identical to one that failed to read,
    because a field saying "this source is not granted" is a model being handed a
    script to ask for access.

    **A slow source degrades the facet for more than one request, and that is the
    ratified design working rather than a defect.** The assembler's
    ``source_timeout`` defaults to 5 s while a reader's own deadline is 10 s
    (``calendar_read_timeout``, ``email_read_timeout``), so a slow source is
    skipped before that deadline fires — and the reader's worker is still
    outstanding, so the *next* assembly's ``read()`` raises immediately and its
    facet is absent too, until the worker returns (ADR-0093 §7). A consumer
    watching a facet blink in and out will be tempted to read something into the
    pattern; ADR-0096 §4 forbids exactly that.

    **Its reader is its own** (ADR-0096 §5). The ingestion stage holds a separate
    instance of the same reader: ADR-0093 §7 bounds a reader at one outstanding
    worker, per instance, so sharing one would let a scheduled ingestion read
    suppress the request-path facet for as long as it runs — coupling a request
    cadence to a periodic job, in the direction that makes an advisory facet wait.
    ADR-0140 §6 is where that clause "acquires a second instance for the first
    time", and the composition root is what holds it: this class cannot detect a
    shared reader and does not pretend to.
    """

    _field: ClassVar[str]
    """The ``CurrentContext`` field this source is wired for."""

    _facet_type: ClassVar[type[ContextFacet]]
    """The one facet type admissible in :attr:`_field`; any other is a wiring bug."""

    def __init__(self, *, reader: Reader, grants: SourceGrants) -> None:
        """Wire the source from an injected reader and the grant query seam.

        Args:
            reader: The producer, holding its own source and its own bound
                (ADR-0093 §1, §5) — so this source neither locates the source nor
                widens the read. **Not shared with the ingestion stage**, for the
                reason in the class docstring.
            grants: The **query** seam, and never a ``SourceGrantStore``
                (ADR-0097 §3, §5). Required, with no default: a composition that
                omits it does not type-check, which is what makes the gate a
                mechanism rather than an obligation stated in prose and honoured
                by review. Narrow by type as well as by name — a source that could
                *record* a grant is a source that could authorise its own read, and
                ``mypy --strict`` refuses to let this one name ``record`` at all.
        """
        self._reader = reader
        self._grants = grants

    @property
    def name(self) -> str:
        """This source's stable identifier — the reader's declared identity.

        The reader's own ``name`` rather than a second constant, so an operator
        reading a degradation log sees which source degraded rather than which
        adapter wrapped it. It is Tier 2 by construction: ADR-0093 §7 makes a
        reader's identity **declared, never configured**, precisely so it cannot
        carry a path or an address into a log line.
        """
        return self._reader.name

    async def contribute(self) -> Mapping[str, object]:
        """Read the source once, if a live ``FACET`` grant covers it, and contribute.

        The gate is ADR-0097 §5's, and its guarantee is bounded in a way worth
        stating so nothing reads it as a stronger one: **every read is authorised
        at the instant it starts, and nothing produced by a read whose grant has
        gone by the time it returns is used.** It is *not* a guarantee that no byte
        is read after a revocation is recorded — a read already in flight completes
        on a worker the reader owns, which nothing here can stop (ADR-0093 §7).

        Three properties hold it, and none needs a lock:

        * **Nothing is opened without a grant.** The source is not resolved, not
          opened and not parsed — opening the user's calendar or their mail store
          *is* the act the grant is about, so a design that read the file and then
          declined to use it would already have done the thing it was not
          permitted to do.
        * **No ``await`` stands between the ``live()`` answer and ``read()``.**
          Awaiting a coroutine does not yield to the event loop, so with nothing in
          between this source cannot sit on a stale answer at all; a driver free to
          await anything there could hold one for arbitrarily long, which is the
          difference between a race bounded by a worker's scheduling and one
          bounded by nothing (ADR-0021 §4, ADR-0097 §5a).
        * **The grant is re-checked when ``read()`` returns**, and a reading whose
          grant died in between is discarded. That is what makes a revocation
          *win* rather than merely arrive: nothing crosses into a prompt.

        **It fails closed on an unanswerable check.** A ``live()`` that raises
        ``GrantError`` is not a grant — before the read nothing is opened, and
        after the read the reading is discarded. The error is left to propagate
        rather than converted, so a store fault and a withdrawn grant stay
        different facts for an operator reading the assembler's log; both end at an
        absent facet, as every optional-source fault does (ADR-0097 §5a).

        Returns:
            ``{self._field: facet}`` when a granted read carried a facet of
            :attr:`_facet_type`, and ``{}`` otherwise — no grant, a grant withdrawn
            mid-read, or a reading with no facet in it. The empty mapping is the
            *only* absence: this source never contributes a marker saying which of
            them happened (ADR-0096 §4).

        Raises:
            ContextError: If the reading carried a facet of a type this source is
                not wired to contribute — a deployment wired wrongly rather than
                data to reconcile, which is exactly what ADR-0008 §4 reserves this
                error for. It is raised *instead of* contributing, under either
                this source's field or any other (ADR-0096 §5, ADR-0140 §13).
            GrantError: If the grant store could not answer, before or after the
                read. Propagated, never converted (above).
            ReaderError: As the reader raises. Propagated for the same reason: the
                assembler degrades this source and logs the class, and converting
                it here would tell an operator the wrong thing about where the
                fault lives.
        """
        source = self._reader.name
        # The check and the start of the read are one synchronous step: nothing
        # between this `await` returning and `read()` being called may suspend.
        if await self._grants.live(source=source, use=GrantScope.FACET) is None:
            return {}
        reading = await self._reader.read()
        # The revocation that landed while the read ran wins: the reading is
        # discarded whole, and nothing records that it happened.
        if await self._grants.live(source=source, use=GrantScope.FACET) is None:
            return {}
        # Widened deliberately: `SourceReading.facet` is a union of every concrete
        # facet type (ADR-0096 §5), and this source accepts one member of it. The
        # guard below is what turns the rest into a wiring bug rather than a
        # silently mis-filed field.
        facet: ContextFacet | None = reading.facet
        if facet is None:
            return {}
        if not isinstance(facet, self._facet_type):
            msg = (
                f"the {source!r} reader contributed a {type(facet).__name__} to the "
                f"{self._field!r} field of the situational context; a source is wired "
                f"for one facet type and this is a wiring bug (ADR-0096 §5)"
            )
            raise ContextError(msg)
        return {self._field: facet}


class CalendarContextSource(_GrantedFacetSource):
    """Contributes the calendar facet from a reader, when a grant covers the read.

    The first source that reads the world (ADR-0096). Everything it does is
    :class:`_GrantedFacetSource`'s; what it declares is the pairing — the calendar
    facet belongs in ``CurrentContext.calendar`` and nothing else does.
    """

    _field: ClassVar[str] = "calendar"
    _facet_type: ClassVar[type[ContextFacet]] = CalendarFacet


class EmailContextSource(_GrantedFacetSource):
    """Contributes the email facet from a reader, when a grant covers the read.

    ADR-0140 §6's adapter, and the second instance of ADR-0096 §5's
    contribute-and-raise clause — "which is exactly the wiring bug it was written
    against". Everything it does is :class:`_GrantedFacetSource`'s; what it
    declares is the pairing — the email facet belongs in ``CurrentContext.email``
    and nothing else does.

    **What reaches the context is two scalars and no span of any message**
    (ADR-0140 §6). That is the reader's obligation and this adapter neither widens
    nor narrows it: it lifts the facet the reading carried, unedited, exactly as
    ADR-0096 §5 requires of every adapter. It is worth naming here because
    ``CurrentContext`` is rendered into every prompt and a subject line would be
    attacker-chosen text on that path — so a later change that gave this source a
    facet to *build* rather than to carry would be re-deciding §6, not extending
    it.

    **An ungranted mail store is absent and says nothing about why** (ADR-0097 §5).
    ADR-0140 §9's fourth clause adds a warning this adapter cannot enforce but that
    a surface reading its output must: withdrawing the grant stops *this system's
    read*, and does not stop the fetcher outside it from collecting mail. A facet
    that is absent means only that it is absent.
    """

    _field: ClassVar[str] = "email"
    _facet_type: ClassVar[type[ContextFacet]] = EmailFacet
