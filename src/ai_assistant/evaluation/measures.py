"""ADR-0120's three measures and ADR-0141's two, computed offline over the stream.

`docs/roadmap.md`'s leg 8 exits when *"is the user model getting more accurate?"
is answered by data, not opinion*, and names three of ``VISION.md``'s success
measures. ADR-0119 built the stream they are computed over and deferred what each
one *is*; ADR-0120 defines them, and this module is that definition in code.

**Every measure is a rate over one window, and the window and its settling are
part of the figure** (§1). None of them carries a threshold, a target or a
verdict — "a measure is a number; whether it is good is the operator's ruling,
which is what leg 8's exit test asks for" — and every ratio whose denominator is
zero is reported as *undefined* rather than as a zero.

**This runs while the hub is stopped, in its own process** (§9). It is not an
``Engine`` operation, not a wire operation and not an ``assistant`` subcommand:
ADR-0119 §7 rules that no component of the request pipeline reads a trace back,
because "an instrument whose readings change behaviour is measuring a system that
includes the instrument". The placement here is what makes that mechanical —
``lint-imports`` forbids every subsystem from importing this package — rather
than a promise. The entry point is
:mod:`ai_assistant.service.measures`, which takes the hub's own instance lock, the
route ADR-0083 §10 already names for an offline tool.

**One capability of the store is used** (§9): :meth:`TraceStore.walk`. Nothing
here emits a trace, purges one, or opens any store but the trace store, and no
figure it states is derived from anything but retained traces (§10).

**Leg 10's instrument rides in the same walk** (ADR-0141). Its §6 adds the
interruption share and the duplicate share, §7 five diagnostics beside them, and §5
the classifier that decides which rulings any of them is over. Its §10 reuses
ADR-0120 §9's placement "whole" and narrows none of it: same package, same console
script, same window, no new argument and no ``Settings`` field. The one thing it
needed that ADR-0120 could not supply is a ``CONFIGURATION`` boundary the
notification chassis's own tunings move, which its §10 bought by putting three
``Settings`` figures on ``service/configuration.py``'s allowlist — so §8's partition
here is a thing ADR-0141 *created* rather than one it inherited.

**What the measures cannot see is stated rather than approximated** (§11, §12).
Five emitter gaps bite here — most of all that no emitter populates
``TraceRef.CONVERSATION`` or ``TraceRef.TURN``, so §6's rate is over direct user
acts rather than over turns as ``VISION`` phrases it. Each is a follow-on lane;
none is worked around in this module.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING

from ai_assistant.core.types import TraceKind, TraceRecordSet
from ai_assistant.evaluation._figures import (
    Distribution,
    MeasureReport,
    Overturns,
    Part,
    Rate,
    Restart,
    SeamLatency,
    StreamHealth,
)
from ai_assistant.evaluation._notifications import Tally
from ai_assistant.evaluation._notifications import read as read_ruling
from ai_assistant.evaluation._stream import (
    SeamClass,
    attribution,
    classify,
    counts,
    index,
    is_counter_inconsistent,
    is_malformed,
    joinable,
    retrieval_counts,
    truncates_a_joined_set,
    walk,
)
from ai_assistant.evaluation._vocabulary import (
    DECISION_KEYS,
    DECISIONS_REINFORCE,
    DECISIONS_SUPERSEDE,
    DIRECT_SEAMS,
    OBSERVE_SEAM,
)
from ai_assistant.evaluation.sqlite_store import SqliteTraceStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from ai_assistant.core.protocols import TraceStore
    from ai_assistant.core.types import EvaluationTrace
    from ai_assistant.evaluation._figures import NotificationFigures
    from ai_assistant.evaluation._stream import Extent, Index

__all__ = ["MeasureReader", "MeasureReport"]


class MeasureReader:
    """The offline reporting tool's mechanism: open, walk, compute, close.

    Shaped after :class:`~ai_assistant.memory.reembed.Reembedder`, which is the
    precedent ADR-0120 §9 transfers term by term — the offline tool holds the
    **path** to its store, opens it for the length of one run, and exposes the
    path so the entry point can say something useful about a deployment that has
    never written one.

    The composition root constructs it (:func:`~ai_assistant.app.build_measure_reader`),
    because ``service`` may not import this package directly and this package may
    not import ``service``.
    """

    def __init__(self, *, store: Path) -> None:
        """Point the reader at a trace database.

        Args:
            store: ``<data_dir>/traces.db``. Not opened here: a reader that
                opened it on construction would create an empty database as a
                side effect of asking whether one exists.
        """
        self._store = store

    @property
    def store(self) -> Path:
        """Where the trace store is, whether or not it exists yet."""
        return self._store

    async def report(self, *, start: datetime, end: datetime, settling: timedelta) -> MeasureReport:
        """Compute every measure and diagnostic over ``[start, end)``.

        Args:
            start: The window's inclusive start, timezone-aware.
            end: The window's exclusive end, timezone-aware.
            settling: How long a surfacing is given to be overturned (§8). Part
                of the figure, not an implementation detail: two windows are
                comparable only when their settling agrees.

        Returns:
            The report — the figures, a refusal, or the empty-stream statement.

        Raises:
            TraceStoreError: If the store cannot be opened or read.
        """
        store = SqliteTraceStore(path=self._store)
        try:
            return await compute(store, start=start, end=end, settling=settling)
        finally:
            store.close()


async def compute(
    store: TraceStore, *, start: datetime, end: datetime, settling: timedelta
) -> MeasureReport:
    """Walk ``store`` twice and produce the report (§1 through §8).

    Args:
        store: The trace store, read through :meth:`TraceStore.walk` alone.
        start: The window's inclusive start.
        end: The window's exclusive end.
        settling: The settling period.

    Returns:
        The report.

    Raises:
        TraceStoreError: If the store cannot be read.
    """
    stream = await index(store)
    if stream.extent is None:
        # §8: "Over an **empty** retained stream the report states that the stream
        # is empty, states no measure and no diagnostic, and applies no window
        # validation." The emptiness test comes first for that last clause, which
        # is unqualified — including over the three refusals below that this ADR
        # does not itself require. A stream with nothing in it has nothing to
        # measure whatever window was asked for, and saying so is the answer §8
        # picked over the three an implementation would otherwise have to choose
        # between.
        return MeasureReport()
    refusal = _refused(start=start, end=end, settling=settling, extent=stream.extent)
    if refusal is not None:
        return MeasureReport(refusal=refusal)

    collector = _Collector(stream, stream.extent, start=start, end=end, settling=settling)
    async for ordinal, trace in walk(store):
        collector.add(ordinal, trace)
    return collector.report()


def _refused(*, start: datetime, end: datetime, settling: timedelta, extent: Extent) -> str | None:
    """Why no figure can be stated over this window, or ``None``.

    One of the four is ADR-0120's: §8's refusal of a window whose start precedes
    the oldest retained trace. The other three are this implementation's, covering
    arguments the ADR's notation excludes rather than rules on — a negative
    settling period, a window that is not half-open, and a settling period the
    window's end cannot be moved forward by. They are reported through the same
    path rather than raised, so that every way this exits without a figure exits
    the same way: a refused window and a swept one are one thing to an operator.

    Args:
        start: The window's inclusive start.
        end: The window's exclusive end.
        settling: The settling period.
        extent: The retained stream's span.

    Returns:
        The refusal, or ``None`` when the window is one this report can state.
    """
    if settling < timedelta(0):
        return f"a settling period cannot be negative; got {settling}"
    if start >= end:
        return (
            f"the window [{start:%Y-%m-%dT%H:%M:%S%z}, {end:%Y-%m-%dT%H:%M:%S%z}) is "
            f"empty or inverted; a measure is a rate over a half-open interval"
        )
    if not _representable(end, settling):
        return (
            f"a settling period of {settling} reaches past the last instant this report "
            f"can represent, so no surfacing in the window could ever be given it. Ask "
            f"for a settling period the window's end can be moved forward by"
        )
    if start < extent.oldest:
        return _swept(start, extent)
    return None


def _representable(end: datetime, settling: timedelta) -> bool:
    """Whether the window's end can be moved forward by the settling period.

    Checked once, here, and never again: every instant this walk adds ``settling``
    to is a read's ``occurred_at``, which lies in ``[start, end)`` and so is
    strictly before ``end``. One guard therefore covers §4's candidate horizon and
    §8's settling test alike, and turns what would otherwise be an ``OverflowError``
    out of the middle of the walk into a refusal that says what to ask for instead.

    Args:
        end: The window's exclusive end.
        settling: The settling period.

    Returns:
        Whether ``end + settling`` is a representable instant.
    """
    try:
        end + settling
    except OverflowError:
        return False
    return True


def _swept(start: datetime, extent: Extent) -> str:
    """§8's refusal, naming both instants.

    "A retention horizon that has swept the window's early traces makes the
    figure a statement about a different period than the one asked for."
    """
    return (
        f"the window starts at {start:%Y-%m-%dT%H:%M:%S%z}, before the oldest retained "
        f"trace at {extent.oldest:%Y-%m-%dT%H:%M:%S%z}. Traces from the window's early "
        f"period have been swept by the retention horizon, so a figure over it would be a "
        f"statement about a different period. Ask for a window starting at or after the "
        f"oldest retained trace."
    )


@dataclass(frozen=True, slots=True)
class _Read:
    """One eligible ``RETRIEVAL`` trace, reduced to what §4's join needs."""

    ordinal: int
    occurred_at: datetime
    elapsed: timedelta | None
    ids: tuple[str, ...]
    part: int


@dataclass(frozen=True, slots=True)
class _Overturn:
    """One write that retired an id, reduced to what §4's join needs."""

    ordinal: int
    occurred_at: datetime
    timed: bool
    seam_class: SeamClass


class _Verdict(Enum):
    """What §4 makes of one surfacing against one of §3's seam sets.

    ``INTACT`` is the surfacing nothing overturned within the settling period:
    it stays in the denominator as evidence of correctness, which is exactly why
    §4 calls itself an upper bound — "every wrong belief the user never corrects
    counts here as correct".
    """

    OVERTURNED = auto()
    INTACT = auto()
    AMBIGUOUS = auto()


@dataclass
class _Totals:
    """§5's and §6's sums over one part of the window."""

    rulings: int = 0
    corrections: int = 0
    retired_beliefs: int = 0
    corrections_with_a_set: int = 0
    direct_rulings: int = 0
    direct_reinforcements: int = 0
    observe_rulings: int = 0
    observe_reinforcements: int = 0

    def __iadd__(self, other: _Totals) -> _Totals:
        """Fold another part's sums in, which is how the whole window is formed."""
        self.rulings += other.rulings
        self.corrections += other.corrections
        self.retired_beliefs += other.retired_beliefs
        self.corrections_with_a_set += other.corrections_with_a_set
        self.direct_rulings += other.direct_rulings
        self.direct_reinforcements += other.direct_reinforcements
        self.observe_rulings += other.observe_rulings
        self.observe_reinforcements += other.observe_reinforcements
        return self


@dataclass
class _Health:
    """The exclusions this ADR's own rules caused, over the window (§7)."""

    walked: int = 0
    by_kind: dict[TraceKind, int] = field(default_factory=dict)
    malformed: int = 0
    truncated: int = 0
    counter_inconsistent: int = 0
    unattributed: int = 0
    unclassified: int = 0
    unclassified_seams: set[str] = field(default_factory=set)


class _Collector:
    """Accumulates the second pass, then forms every figure from it.

    One instance per run. The second pass is where every population is decided,
    because attribution — which the first pass established — is what most of them
    are conditioned on.
    """

    def __init__(
        self,
        stream: Index,
        extent: Extent,
        *,
        start: datetime,
        end: datetime,
        settling: timedelta,
    ) -> None:
        """Fix the window, its parts, and the settling period.

        Args:
            stream: What the first pass established.
            extent: The stream's span. Passed separately from ``stream`` because
                :func:`compute` has already refused the empty stream, and taking
                it as non-optional here is what keeps that refusal from having to
                be re-asserted at every use.
            start: The window's inclusive start.
            end: The window's exclusive end.
            settling: The settling period.
        """
        self._stream = stream
        self._extent = extent
        self._start = start
        self._end = end
        self._settling = settling
        self._cuts = _partition(stream, start=start, end=end)
        self._bounds = tuple(zip((start, *self._cuts), (*self._cuts, end), strict=True))
        self._totals = [_Totals() for _ in self._bounds]
        self._rulings = [Tally() for _ in self._bounds]
        self._health = _Health()
        self._reads: list[_Read] = []
        self._overturns: defaultdict[str, list[_Overturn]] = defaultdict(list)
        self._latency: defaultdict[str, list[float]] = defaultdict(list)

    def add(self, ordinal: int, trace: EvaluationTrace) -> None:
        """Fold one trace into every population it belongs to.

        A trace **outside** the window is not ignored: §3 resolves attribution
        over the whole retained stream, and §4's candidate window reaches
        ``settling`` past a read, so a write after the window's end can still
        overturn a surfacing inside it. ADR-0141's figures are the other case —
        every one of them is a rate over rulings that happened inside the window,
        joined to nothing outside it, so a notification trace outside contributes
        nowhere.

        Args:
            ordinal: Its position in the store's total insertion order.
            trace: The trace.
        """
        inside = self._start <= trace.occurred_at < self._end
        if inside:
            self._health.walked += 1
            self._health.by_kind[trace.kind] = self._health.by_kind.get(trace.kind, 0) + 1
        if trace.kind is TraceKind.NOTIFICATION:
            # ADR-0141 §5 is the sole classifier of a notification trace: its four
            # states are "disjoint and exhaustive by construction", so a second
            # classifier reaching one would be a way for the exclusion counts to
            # double. Decided ahead of ADR-0120 §2's tests, which are stated over
            # the memory emitters' keys — a roster no notification trace carries,
            # so today the two cannot meet and this keeps that true by structure
            # rather than by the two rosters happening to stay disjoint.
            if inside:
                self._rulings[self._part_of(trace.occurred_at)].add(trace, read_ruling(trace))
            return
        if is_malformed(trace):
            if inside:
                self._health.malformed += 1
            return
        if inside and truncates_a_joined_set(trace):
            self._health.truncated += 1
        if trace.kind is TraceKind.MEMORY_WRITE:
            self._add_write(ordinal, trace, inside=inside)
        elif trace.kind is TraceKind.RETRIEVAL and inside:
            self._add_retrieval(ordinal, trace)
        elif trace.kind is TraceKind.OPERATION and inside and trace.elapsed is not None:
            self._latency[trace.seam].append(trace.elapsed.total_seconds())

    def _add_write(self, ordinal: int, trace: EvaluationTrace, *, inside: bool) -> None:
        """Attribute the write (§3), then feed §4's index and §5's and §6's sums."""
        seam = attribution(trace, self._stream.seam_of)
        if seam is None:
            if inside:
                self._health.unattributed += 1
            return
        seam_class = classify(seam)
        if seam_class is None:
            if inside:
                self._health.unclassified += 1
                self._health.unclassified_seams.add(seam)
            return
        self._index_overturns(ordinal, trace, seam_class)
        if inside:
            self._add_rulings(trace, seam=seam, seam_class=seam_class)

    def _index_overturns(self, ordinal: int, trace: EvaluationTrace, seam_class: SeamClass) -> None:
        """Record every id this write retired, for §4's join.

        ``SUPERSEDED`` and ``RETIRED`` both count and ``WRITTEN`` does not: a
        supersession installs its correction at a freshly-minted id, and "a
        definition that joined on ``WRITTEN`` would count the *correction* as the
        thing overturned".
        """
        retired: set[str] = set()
        for key in (TraceRecordSet.SUPERSEDED, TraceRecordSet.RETIRED):
            joined = joinable(trace, key)
            if joined is not None:
                retired.update(joined)
        overturn = _Overturn(
            ordinal=ordinal,
            occurred_at=trace.occurred_at,
            timed=trace.elapsed is not None,
            seam_class=seam_class,
        )
        for record in retired:
            self._overturns[record].append(overturn)

    def _add_rulings(self, trace: EvaluationTrace, *, seam: str, seam_class: SeamClass) -> None:
        """Add an eligible write's six decision counts to its part's sums.

        Eligibility is presence and never outcome (§2): a crossing that faulted
        before ruling carries none of the six and enters nothing, while one that
        faulted *after* applying part of a reading carries all six as "a truthful
        account of the rulings that *did* happen".
        """
        decisions = counts(trace, DECISION_KEYS)
        if decisions is None or seam_class is not SeamClass.USER:
            return
        totals = self._totals[self._part_of(trace.occurred_at)]
        rulings = sum(decisions.values())
        corrections = decisions[DECISIONS_SUPERSEDE]
        totals.rulings += rulings
        totals.corrections += corrections
        superseded = trace.records.get(TraceRecordSet.SUPERSEDED)
        if superseded is not None:
            totals.retired_beliefs += superseded.total
            totals.corrections_with_a_set += corrections
        if seam in DIRECT_SEAMS:
            totals.direct_rulings += rulings
            totals.direct_reinforcements += decisions[DECISIONS_REINFORCE]
        if seam == OBSERVE_SEAM:
            totals.observe_rulings += rulings
            totals.observe_reinforcements += decisions[DECISIONS_REINFORCE]

    def _add_retrieval(self, ordinal: int, trace: EvaluationTrace) -> None:
        """Count §2's counter-inconsistency and feed §4's surfacings from one read."""
        read = retrieval_counts(trace)
        if read is not None and is_counter_inconsistent(read):
            self._health.counter_inconsistent += 1
        returned = joinable(trace, TraceRecordSet.RETURNED)
        if returned is None:
            return
        self._reads.append(
            _Read(
                ordinal=ordinal,
                occurred_at=trace.occurred_at,
                elapsed=trace.elapsed,
                ids=returned,
                part=self._part_of(trace.occurred_at),
            )
        )

    def _part_of(self, instant: datetime) -> int:
        """Which part of the window ``instant`` falls in."""
        return bisect_right(self._cuts, instant)

    def report(self) -> MeasureReport:
        """Form every figure from what the two passes accumulated."""
        user = self._overturns_by_part(SeamClass.USER)
        machine = self._overturns_by_part(SeamClass.MACHINE)
        parts = [
            self._part(bound, self._totals[ordinal], user[ordinal], machine[ordinal])
            for ordinal, bound in enumerate(self._bounds)
        ]
        whole_totals = _Totals()
        for totals in self._totals:
            whole_totals += totals
        whole_rulings = Tally()
        for tally in self._rulings:
            whole_rulings.absorb(tally)
        whole = self._part(
            (self._start, self._end),
            whole_totals,
            _summed(user),
            _summed(machine),
        )
        return MeasureReport(
            start=self._start,
            end=self._end,
            settling=self._settling,
            whole=whole,
            parts=tuple(parts) if len(parts) > 1 else (),
            latency=tuple(
                SeamLatency(seam=seam, elapsed=Distribution.over(self._latency[seam]))
                for seam in sorted(self._latency)
            ),
            health=self._stream_health(whole.user.ambiguous),
            notifications=whole_rulings.figures(start=self._start, end=self._end),
            notification_parts=self._notification_parts(),
        )

    def _notification_parts(self) -> tuple[NotificationFigures, ...]:
        """ADR-0141 §8's per-part figures, over the cuts ADR-0120 §8 already made.

        Empty where the window has one part, matching :attr:`MeasureReport.parts`:
        a single part is the window entire, and stating it twice says nothing.

        §8 is what *creates* this partition for these figures rather than
        inheriting it. The notification chassis's three ``Settings`` figures — the
        cap, the retention horizon and the reconsideration interval — reached
        ``service/configuration.py``'s allowlist only with ADR-0141 §10, and until
        they did, "two startups differing only in the cap emit identical
        ``CONFIGURATION`` metric mappings, no boundary is created", and one figure
        would be stated across rulings made under different caps.
        """
        if len(self._bounds) <= 1:
            return ()
        return tuple(
            tally.figures(start=start, end=end)
            for tally, (start, end) in zip(self._rulings, self._bounds, strict=True)
        )

    def _part(
        self,
        bound: tuple[datetime, datetime],
        totals: _Totals,
        user: Overturns,
        machine: Overturns,
    ) -> Part:
        """One block of measures over ``bound``, with its settling verdict applied."""
        start, end = bound
        settled = self._settled(end)
        return Part(
            start=start,
            end=end,
            user=_with_settling(user, settled=settled),
            machine=_with_settling(machine, settled=settled),
            correction=Rate(numerator=totals.corrections, denominator=totals.rulings),
            beliefs_per_correction=Rate(
                numerator=totals.retired_beliefs, denominator=totals.corrections_with_a_set
            ),
            repeated_explanation=Rate(
                numerator=totals.direct_reinforcements, denominator=totals.direct_rulings
            ),
            observe_share=Rate(
                numerator=totals.observe_reinforcements, denominator=totals.observe_rulings
            ),
        )

    def _settled(self, end: datetime) -> bool:
        """Whether the stream extends the settling period past ``end`` (§4, §8).

        Tested against the **last** trace in insertion order, which is the
        instant §4 names. It is at or before the newest retained instant §8
        names, so this satisfies §4 exactly and is never weaker than §8 — and
        withholding is the direction every conservative clause of this ADR takes.
        """
        return self._extent.last >= end + self._settling

    def _overturns_by_part(self, seam_class: SeamClass) -> list[Overturns]:
        """§4's three counts per part, over one of §3's seam sets."""
        overturned = [0] * len(self._bounds)
        non_ambiguous = [0] * len(self._bounds)
        ambiguous = [0] * len(self._bounds)
        for read in self._reads:
            for record in read.ids:
                verdict = self._verdict(read, record, seam_class)
                if verdict is _Verdict.AMBIGUOUS:
                    ambiguous[read.part] += 1
                    continue
                non_ambiguous[read.part] += 1
                if verdict is _Verdict.OVERTURNED:
                    overturned[read.part] += 1
        return [
            Overturns(
                overturned=overturned[ordinal],
                non_ambiguous=non_ambiguous[ordinal],
                ambiguous=ambiguous[ordinal],
                settled=True,
            )
            for ordinal in range(len(self._bounds))
        ]

    def _candidates(self, read: _Read, record: str, seam_class: SeamClass) -> list[_Overturn]:
        """§4's candidates for one surfacing: this seam set, after it, within ``s``.

        ``ordinal`` decides "after", never the instant: insertion order is the
        only total, stable order the stream has, and a clock step cannot reorder
        appends. The instant decides only the settling horizon, which is a
        wall-clock notion the operator chose.
        """
        horizon = read.occurred_at + self._settling
        return [
            overturn
            for overturn in self._overturns.get(record, ())
            if overturn.seam_class is seam_class
            and overturn.ordinal > read.ordinal
            and overturn.occurred_at <= horizon
        ]

    def _verdict(self, read: _Read, record: str, seam_class: SeamClass) -> _Verdict:
        """What §4 makes of one surfacing.

        **Overturned** is "some candidate reports having begun at or after the
        read reports having finished" — ``occurred_at`` is when the work began
        and ``elapsed`` is how long it took, so a write already in flight when
        the read finished is not evidence that the user retired what the read
        surfaced.

        **Ambiguous** has three ways in, and §4 names all three: a read carrying
        no ``elapsed``, so the interval test cannot be evaluated at all; a
        candidate carrying none; and a surfacing with at least one candidate the
        interval test did not turn into an overturn, which is "a pair the stream
        genuinely cannot order". Ambiguity is checked before the overturn where
        the two could both apply, because guessing either way "puts a fabricated
        fact in a measure" and dropping the surfacing is the disposition ADR-0119
        §3 gives an unobserved quantity.
        """
        if read.elapsed is None:
            return _Verdict.AMBIGUOUS
        candidates = self._candidates(read, record, seam_class)
        if not candidates:
            return _Verdict.INTACT
        if any(not overturn.timed for overturn in candidates):
            return _Verdict.AMBIGUOUS
        finished = read.occurred_at + read.elapsed
        if any(overturn.occurred_at >= finished for overturn in candidates):
            return _Verdict.OVERTURNED
        return _Verdict.AMBIGUOUS

    def _stream_health(self, ambiguous: int) -> StreamHealth:
        """§7's counts, plus the restarts §8 has the report bound downtime with."""
        return StreamHealth(
            retained=self._extent.traces,
            oldest=self._extent.oldest,
            newest=self._extent.newest,
            walked=self._health.walked,
            by_kind=dict(self._health.by_kind),
            malformed=self._health.malformed,
            truncated=self._health.truncated,
            counter_inconsistent=self._health.counter_inconsistent,
            unattributed=self._health.unattributed,
            unclassified=self._health.unclassified,
            unclassified_seams=tuple(sorted(self._health.unclassified_seams)),
            ambiguous_surfacings=ambiguous,
            restarts=tuple(
                Restart(
                    at=stamp.occurred_at,
                    preceded=stamp.preceded,
                    gap=stamp.gap,
                    changed=stamp.changed,
                )
                for stamp in self._stream.configurations
            ),
        )


def _partition(stream: Index, *, start: datetime, end: datetime) -> tuple[datetime, ...]:
    """Where §8 cuts the window: every configuration change inside it.

    "The operator does not date the intervention and then choose two windows by
    hand; the report finds the change and reports the two sides." A stamp whose
    mapping equals its predecessor's partitions nothing, and one at the window's
    own start would open an empty first part, so it is not a cut either.

    The cuts are sorted and de-duplicated. Configuration traces arrive in
    insertion order and their instants are all but certainly monotone, but a part
    is an interval over ``occurred_at`` and a well-formed partition must not
    depend on that.

    Args:
        stream: What the first pass established.
        start: The window's inclusive start.
        end: The window's exclusive end.

    Returns:
        The interior cut points, ascending.
    """
    return tuple(
        sorted(
            {
                stamp.occurred_at
                for stamp in stream.configurations
                if stamp.changed and start < stamp.occurred_at < end
            }
        )
    )


def _with_settling(overturns: Overturns, *, settled: bool) -> Overturns:
    """The same counts, carrying the part's settling verdict."""
    return Overturns(
        overturned=overturns.overturned,
        non_ambiguous=overturns.non_ambiguous,
        ambiguous=overturns.ambiguous,
        settled=settled,
    )


def _summed(parts: Sequence[Overturns]) -> Overturns:
    """The parts' surfacing counts added up, which is the whole window's.

    Sound because every surfacing belongs to exactly one part: the parts are a
    partition of the window over ``occurred_at``, and a surfacing's part is its
    *read's*.
    """
    return Overturns(
        overturned=sum(part.overturned for part in parts),
        non_ambiguous=sum(part.non_ambiguous for part in parts),
        ambiguous=sum(part.ambiguous for part in parts),
        settled=True,
    )
