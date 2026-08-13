"""The figures ADR-0120 defines, and the text the entry point prints.

Every type here is a plain frozen dataclass and none of them is in
``core/types.py``, which ADR-0120 §9 rules explicitly: a report "crosses no
subsystem boundary — it is produced in ``evaluation`` and rendered by the entry
point through ``app``", so putting it in ``core`` "would put a type in ``core``
for a reason ``core`` does not exist for".

**A ratio with a zero denominator is undefined and says so** (§1). "A zero
asserts a rate that was measured to be zero; an omitted line asserts nothing at
all, which a reader takes for zero anyway." :class:`Rate` carries both counts and
refuses to produce a value, so the distinction survives all the way to the page.

**No figure here carries a threshold, a target, a pass/fail verdict or a trend
claim** (§1). "A measure is a number; whether it is good is the operator's
ruling."

**Nothing rendered here is an identifier** (§10). The output carries counts,
rates, instants, seam labels and metric keys, and no record id, correlation id or
trace id — which is what keeps an operator from being invited to go and resolve
one by hand against a store this tool does not open.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.types import NotificationCondition, TraceKind

_UNDEFINED = "undefined (denominator is zero)"
_UNRENDERABLE = "too large to state as a decimal"
_WITHHELD = "withheld — the stream does not yet extend the settling period past the window"


@dataclass(frozen=True, slots=True)
class Rate:
    """One of ADR-0120's ratios, carrying the two counts it was formed from.

    Attributes:
        numerator: The count on top.
        denominator: The population it is a share of. Drawn from the same trace,
            or the same population of traces, as the numerator — ADR-0119 §5's
            rule is that the two must "lose rows at the same rate".
    """

    numerator: int
    denominator: int

    @property
    def defined(self) -> bool:
        """Whether the population was non-empty."""
        return self.denominator > 0

    @property
    def value(self) -> float | None:
        """The ratio, or ``None`` when it is not a decimal this report can state.

        Two ways to get ``None``, and :meth:`rendered` keeps them apart because
        they mean different things.

        **A zero denominator**, which §1 rules is *undefined*.

        **A quotient too large for a float.** ADR-0120 §2 constrains a count to "a
        non-negative integer that is not a ``bool``" and puts no ceiling on it,
        and ``RecordIdSet.total`` is bounded only by ``ge=0`` — so a trace this
        tree's emitters cannot write is still one the type admits and the store
        will hydrate. Every ratio this ADR defines is a share of a population
        containing its own numerator, and so is at most one, *except*
        beliefs-per-correction: it divides beliefs by corrective acts and is
        unbounded above by construction (ADR-0079's "a correction resolves every
        conflict it is shown"). ``int.__truediv__`` raises ``OverflowError``
        rather than returning infinity, so the one unbounded figure is the one
        that would abort the whole report — for a value that is data, not a bug
        in this walk.
        """
        if not self.defined:
            return None
        try:
            return self.numerator / self.denominator
        except OverflowError:
            return None

    def rendered(self) -> str:
        """The ratio and its two counts, or the statement that stands in for it.

        The numerator is printed even when the ratio is undefined, rather than
        assumed to be zero with it. Most of this ADR's ratios cannot have one
        without the other — a correction is one of the rulings it is a share of —
        but beliefs-per-correction sums two quantities a single trace could
        report inconsistently, and a suppressed numerator there would hide the
        inconsistency behind the word *undefined*.

        An unrepresentable quotient states both counts too, which is everything
        the stream holds about it: §1's objection to a zero is that it "asserts a
        rate that was measured to be zero", and the same objection forbids
        substituting any other figure here.
        """
        if not self.defined:
            return f"{_UNDEFINED}  ({self.numerator} of 0)"
        value = self.value
        if value is None:
            return f"{_UNRENDERABLE}  ({self.numerator} of {self.denominator})"
        return f"{value:.4f}  ({self.numerator} of {self.denominator})"


@dataclass(frozen=True, slots=True)
class Distribution:
    """A summary of a sample the report states rather than a rate.

    Used for the §7 diagnostic that is a per-event figure: an ``OPERATION``
    trace's ``elapsed``. Summarised rather than listed because the per-operation
    figures run to thousands of lines on a real stream and none of them is a
    measure. (It summarised the window share of each shortfall read as well until
    ADR-0128 §3 retired that watch.)

    Attributes:
        count: How many observations the summary is over.
        minimum: The smallest, or ``None`` over an empty sample.
        median: The middle, or ``None`` over an empty sample.
        maximum: The largest, or ``None`` over an empty sample.
        mean: The arithmetic mean, or ``None`` over an empty sample.
    """

    count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    mean: float | None

    @classmethod
    def over(cls, sample: Sequence[float]) -> Distribution:
        """Summarise ``sample``, which may be empty.

        Args:
            sample: The observations.

        Returns:
            The summary.
        """
        if not sample:
            return cls(count=0, minimum=None, median=None, maximum=None, mean=None)
        return cls(
            count=len(sample),
            minimum=min(sample),
            median=statistics.median(sample),
            maximum=max(sample),
            mean=statistics.fmean(sample),
        )

    def rendered(self, *, places: int = 4) -> str:
        """The five figures on one line, or a statement that the sample is empty.

        Args:
            places: How many decimal places each figure carries.

        Returns:
            The line.
        """
        if self.minimum is None or self.median is None or self.maximum is None or self.mean is None:
            return "no observations"
        return (
            f"n={self.count}  min {self.minimum:.{places}f}  median {self.median:.{places}f}"
            f"  max {self.maximum:.{places}f}  mean {self.mean:.{places}f}"
        )


@dataclass(frozen=True, slots=True)
class Overturns:
    """§4's surfacing counts, from which precision and the machine rate are read.

    Both figures come from this one shape: memory precision is ``1 -
    overturned ÷ non_ambiguous`` over the **user** seam set, and the machine
    overturn rate is ``overturned ÷ non_ambiguous`` over the machine set.

    Attributes:
        overturned: Surfacings a subsequent write of this seam set retired,
            where the write reports having begun at or after the read reports
            having finished.
        non_ambiguous: The denominator: surfacings the stream can order.
        ambiguous: Surfacings dropped from numerator and denominator alike,
            because the stream "genuinely cannot order" them. Stated because
            "the count of them is what tells an operator whether the exclusion is
            rare or is the measure".
        settled: Whether the stream extends the settling period past the
            window's end. When it does not, §8 withholds the figure rather than
            reporting one over an unequal settling.
    """

    overturned: int
    non_ambiguous: int
    ambiguous: int
    settled: bool

    @property
    def rate(self) -> Rate:
        """The overturn rate."""
        return Rate(numerator=self.overturned, denominator=self.non_ambiguous)

    def rendered_precision(self) -> str:
        """``1 -`` the overturn rate, withheld where the settling is unequal.

        No unrepresentable case, unlike :meth:`Rate.rendered`: both counts here
        are surfacings this walk counted one at a time, so the quotient is at
        most one and the numerator is bounded by the store's own size.
        """
        if not self.settled:
            return _WITHHELD
        value = self.rate.value
        if value is None:
            return f"{_UNDEFINED}  (no non-ambiguous surfacing)"
        return f"{1 - value:.4f}  ({self.overturned} overturned of {self.non_ambiguous})"

    def rendered_overturn(self) -> str:
        """The overturn rate itself, withheld under the same condition."""
        if not self.settled:
            return _WITHHELD
        value = self.rate.value
        if value is None:
            return f"{_UNDEFINED}  (no non-ambiguous surfacing)"
        return f"{value:.4f}  ({self.overturned} of {self.non_ambiguous})"


@dataclass(frozen=True, slots=True)
class Part:
    """Every measure ADR-0120 defines, over one window or one part of one.

    §8 requires each of them "for each part as well as for ``W`` whole", and the
    diagnostics §4, §5 and §6 attach to a measure travel with it — the machine
    overturn rate beside precision, beliefs-per-correction beside the correction
    rate, and the ``observe`` reinforcement share beside the repeated-explanation
    rate. §7's three are stated over the whole window only, which is where §7
    defines them.

    Attributes:
        start: The part's inclusive start.
        end: The part's exclusive end.
        user: §4's surfacing counts over the user seam set.
        machine: The same over the machine set — §4's diagnostic, "never folded
            into" precision.
        correction: §5's correction rate.
        beliefs_per_correction: §5's diagnostic: beliefs retired per corrective
            act, computed from ``total`` so a truncated set costs it nothing.
        repeated_explanation: §6's rate, over direct user acts only.
        observe_share: §6's diagnostic, "labelled as the observation stage's
            re-mining overlap" and never a substitute for the rate above.
    """

    start: datetime
    end: datetime
    user: Overturns
    machine: Overturns
    correction: Rate
    beliefs_per_correction: Rate
    repeated_explanation: Rate
    observe_share: Rate


@dataclass(frozen=True, slots=True)
class Restart:
    """A ``CONFIGURATION`` trace, as §7 and §8 report it.

    Attributes:
        at: When the hub started.
        preceded: Whether any trace precedes this one in the retained stream.
            §8's clause applies only where one does.
        gap: The interval from that predecessor, or ``None`` where no bound can
            be stated. An **upper bound** on how long the hub was not running,
            never the downtime: the stream cannot say when the previous process
            stopped. ``None`` beside a ``True`` ``preceded`` means the two
            instants are out of order, which ADR-0119 §7a permits — and a
            negative duration bounds no downtime.
        changed: Whether the effective figures moved. Only a changed stamp
            partitions the window (§8).
    """

    at: datetime
    preceded: bool
    gap: timedelta | None
    changed: bool


@dataclass(frozen=True, slots=True)
class SeamLatency:
    """One seam's ``OPERATION`` durations over the window (§7).

    Attributes:
        seam: The public method's own name, as ``Engine._tracked`` labelled it.
        elapsed: The distribution, in seconds.
    """

    seam: str
    elapsed: Distribution


@dataclass(frozen=True, slots=True)
class StreamHealth:
    """The counts that let a reader distrust the rest (§7).

    Not a completeness claim: "the stream cannot report its own completeness",
    and a trace lost to an emission failure is logged and never counted. These
    are the exclusions this ADR's own rules caused, "which is a different and
    fully computable thing".

    Attributes:
        retained: Every trace the walk saw.
        oldest: The earliest retained ``occurred_at``.
        newest: The latest retained ``occurred_at``.
        walked: Traces whose ``occurred_at`` lies in the window.
        by_kind: Those traces by kind.
        malformed: Excluded from every population under §2.
        truncated: Excluded from a population joining on a truncated set.
        counter_inconsistent: A retrieval trace whose eight counts cannot all be
            true of one read (§2). It excluded such a trace from §7's shortfall
            population, which ADR-0128 §3 has since retired; §2's rule "stands
            unchanged" there, so the count is still taken and still stated — it
            now excludes a trace from nothing and reports only that the stream
            carries one.
        unattributed: Writes whose causing operation could not be identified.
        unclassified: Writes attributed to a seam on neither of §3's lists.
        unclassified_seams: Each such seam, named so it can be classified.
        ambiguous_surfacings: §4's user-population exclusions, restated here.
        restarts: Every ``CONFIGURATION`` trace in the retained stream.
    """

    retained: int
    oldest: datetime
    newest: datetime
    walked: int
    by_kind: Mapping[TraceKind, int]
    malformed: int
    truncated: int
    counter_inconsistent: int
    unattributed: int
    unclassified: int
    unclassified_seams: tuple[str, ...]
    ambiguous_surfacings: int
    restarts: tuple[Restart, ...]


@dataclass(frozen=True, slots=True)
class ConditionIncidence:
    """One ADR-0141 condition key's §7 incidence over the well-formed population.

    §7 states "the count of **well-formed** traces in the ruling population carrying
    it, the count carrying it as ``1``, and their ratio", and requires each
    condition's own carrying count beside its ratio, "never dividing one condition's
    numerator by another's population". The four interrupt keys are absent from every
    ``DROP``, "so their denominators are the non-``DROP`` rulings and not the ruling
    population" — which falls out of counting carriers per key rather than needing a
    second population.

    Attributes:
        condition: The member whose proposition this is.
        key: The metric key the emitter writes it under.
        carried: Well-formed traces carrying the key at all.
        held: Those carrying it as ``1`` — the proposition held at the ruling.
    """

    condition: NotificationCondition
    key: str
    carried: int
    held: int

    @property
    def rate(self) -> Rate:
        """The share of the carriers on which the proposition held."""
        return Rate(numerator=self.held, denominator=self.carried)


@dataclass(frozen=True, slots=True)
class NotificationHealth:
    """ADR-0141 §7's notification stream-health counts, over one window or part.

    Not a completeness claim, for ADR-0120 §7's reason: a trace lost to an emission
    failure is logged and never counted (ADR-0141 §9). These are the exclusions
    ADR-0141's own rules caused.

    Attributes:
        walked: ``NOTIFICATION`` traces whose ``occurred_at`` lies in the window.
        well_formed: §5's fourth state.
        incomplete: §5's first — the ordinary pre-ruling fault path. Stated apart
            from the two genuine faults "because it is not one": counting it beside
            them "would make an outage look like an emitter bug".
        malformed: §5's second.
        counter_inconsistent: §5's third.
        unclassified: In the ruling population, on neither of §5's two seams.
        unclassified_seams: Each such seam, named so it can be classified.
        misplaced_held_seconds: §7's misplacement count.
        not_ok: Traces carrying an outcome other than ``OK``. Stated and never used
            as a population test: §5 decides membership "by which keys a trace
            carries and never by its ``TraceOutcome``".
    """

    walked: int
    well_formed: int
    incomplete: int
    malformed: int
    counter_inconsistent: int
    unclassified: int
    unclassified_seams: tuple[str, ...]
    misplaced_held_seconds: int
    not_ok: int


@dataclass(frozen=True, slots=True)
class NotificationFigures:
    """ADR-0141 §6's two measures and §7's five diagnostics, over a window or part.

    §8 states every figure ADR-0141 defines "for each part of a partitioned window as
    well as for the window entire", and says *figure* where ADR-0120 §8 says
    *measure* — so the diagnostics cross the partition with the measures, which is
    what §7's own preamble has them do anyway.

    **No settling applies to any of these** (§8). "Nothing here looks forward from
    its event": a ruling's numerator is the ruling itself, so a ruling made one
    second before the window closed contributes exactly what one made on the first
    day does, and no figure is withheld for want of a settling period.

    Attributes:
        start: The part's inclusive start.
        end: The part's exclusive end.
        interruption: §6's interruption share, over §5's ruling population.
        duplicate: §6's duplicate share, over the well-formed offers alone.
        interrupts: §7's disposition mix — the sum of ``ruled_interrupt``.
        holds: The sum of ``ruled_hold``.
        drops: The sum of ``ruled_drop``.
        incidence: §7's condition incidence, in ADR-0130 §5's condition order.
        held_latency: §7's held-to-interruption latency, in seconds.
        held_first: §7's held-first share.
        health: §7's notification stream-health counts.
    """

    start: datetime
    end: datetime
    interruption: Rate
    duplicate: Rate
    interrupts: int
    holds: int
    drops: int
    incidence: tuple[ConditionIncidence, ...]
    held_latency: Distribution
    held_first: Rate
    health: NotificationHealth

    def rendered(self, label: str) -> list[str]:
        """One block of notification figures, headed by which window it is over.

        Args:
            label: Which window this block is over.

        Returns:
            The lines, without a trailing blank.
        """
        return [
            f"{label}  [{self.start:%Y-%m-%dT%H:%M:%S%z}, {self.end:%Y-%m-%dT%H:%M:%S%z})",
            f"  interruption share (§6)     {self.interruption.rendered()}",
            f"  duplicate share (§6)        {self.duplicate.rendered()}",
            "  diagnostics — none of these is a measure",
            f"    disposition mix (§7)      interrupt {self.interrupts}"
            f"  hold {self.holds}  drop {self.drops}",
            f"    held-first share (§7)     {self.held_first.rendered()}",
            f"    held-to-interruption, s   {self.held_latency.rendered(places=3)}",
            "    condition incidence (§7) — each ratio is over its own carrying count",
            *(f"      {entry.key:<25} {entry.rate.rendered()}" for entry in self.incidence),
            *_notification_health_lines(self.health),
        ]


def _notification_health_lines(health: NotificationHealth) -> list[str]:
    """ADR-0141 §7's counts, each under the rule that produced it."""
    lines = [
        f"    notification traces walked  {health.walked}",
        f"      well-formed (§5)          {health.well_formed}",
        f"      incomplete (§5)           {health.incomplete}"
        "  — raised before its ruling committed, not a defect",
        f"      malformed (§5)            {health.malformed}",
        f"      counter-inconsistent (§5) {health.counter_inconsistent}",
        f"      unclassified seam (§5)    {health.unclassified}",
        f"      misplaced held_seconds    {health.misplaced_held_seconds}",
        f"      outcome other than ok     {health.not_ok}",
    ]
    if health.unclassified_seams:
        lines.append(f"      unclassified seams met    {', '.join(health.unclassified_seams)}")
    return lines


#: ADR-0141 §9's second normative clause: "The report states, beside the measures,
#: that no figure it carries is evidence about whether contact was welcome."
_WELCOME_LIMIT = (
    "no figure above is evidence about whether contact was welcome (ADR-0141 §9). Each is",
    "a rate over rulings the system made: what was proposed, what was let through, and",
    "what stopped the rest. Whether a notification was delivered, was read, or was wanted",
    "is recorded nowhere in this tree, and no figure here approximates it.",
)


@dataclass(frozen=True, slots=True)
class MeasureReport:
    """What one run of the reporting tool produced.

    Exactly one of three shapes, because ADR-0120 §8 rules two of them
    separately from the ordinary case: a **refusal**, when the window starts
    before the oldest retained trace; an **empty** stream, over which the report
    "states that the stream is empty, states no measure and no diagnostic, and
    applies no window validation"; or the figures.

    Attributes:
        refusal: Why no figure was computed, or ``None``.
        start: The window's inclusive start, or ``None`` on a refusal or an
            empty stream.
        end: The window's exclusive end, under the same condition.
        settling: The settling period the figures were computed under.
        whole: Every measure over the window entire, or ``None``.
        parts: The window's parts, one per configuration change inside it.
            Empty when the configuration never moved.
        latency: §7's per-seam operation latency, in seam order.
        health: §7's stream-health counts, or ``None``.
        notifications: ADR-0141's figures over the window entire, or ``None`` on a
            refusal or an empty stream. ADR-0141 §8 adopts ADR-0120 §8's window
            rules "unchanged", so the refusal and the empty-stream statement reach
            these figures exactly as they reach the measures above.
        notification_parts: The same per part of a partitioned window, over the
            same cuts as :attr:`parts`. Empty when the configuration never moved.
    """

    refusal: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    settling: timedelta | None = None
    whole: Part | None = None
    parts: tuple[Part, ...] = ()
    latency: tuple[SeamLatency, ...] = ()
    health: StreamHealth | None = None
    notifications: NotificationFigures | None = None
    notification_parts: tuple[NotificationFigures, ...] = ()

    def render(self) -> str:
        """The whole report as text the entry point prints.

        §14 leaves the output format to this lane, "since nothing depends on it",
        and §10 bounds its content: counts, rates, instants, seam labels and
        metric keys, and no identifier of any kind.

        Returns:
            The report, without a trailing newline.
        """
        if self.refusal is not None:
            return self.refusal
        if self.whole is None or self.health is None:
            return (
                "the retained trace stream is empty. No measure and no diagnostic is "
                "stated, and no window was validated."
            )
        lines = [*self._heading(), "", *_health_lines(self.health)]
        lines += ["", *_part_lines(self.whole, "the window entire")]
        for ordinal, part in enumerate(self.parts, start=1):
            lines += ["", *_part_lines(part, f"part {ordinal} of {len(self.parts)}")]
        lines += ["", *self._diagnostic_lines()]
        lines += self._notification_lines()
        return "\n".join(lines)

    def _notification_lines(self) -> list[str]:
        """ADR-0141's section: §6's measures, §7's diagnostics, §9's limit.

        Its own section rather than folded into :meth:`_part_lines`, so each ADR's
        figure set reads as the text that defines it and the two share one
        *partition* rather than one block. §8's per-part requirement is met by
        restating the section for each part, over the same cuts.

        Empty where no figures were computed. That is the report a refusal and an
        empty stream produce — both of which :meth:`render` has already returned
        before reaching here — and the one a caller constructing a
        :class:`MeasureReport` by hand produces. A zero notification population is
        *not* that case: it computes, and every rate over it is stated as
        **undefined** rather than omitted, which is ADR-0120 §1's rule and the one
        ADR-0141 §6 restates for its own.
        """
        if self.notifications is None:
            return []
        lines = ["", "notification measures (ADR-0141) — rates over rulings, not over records"]
        lines += ["", *self.notifications.rendered("the window entire")]
        for ordinal, part in enumerate(self.notification_parts, start=1):
            label = f"part {ordinal} of {len(self.notification_parts)}"
            lines += ["", *part.rendered(label)]
        return [*lines, "", *_WELCOME_LIMIT]

    def _heading(self) -> list[str]:
        """The window, the settling, and what the numbers are not."""
        return [
            f"measures over [{self.start:%Y-%m-%dT%H:%M:%S%z}, {self.end:%Y-%m-%dT%H:%M:%S%z}), "
            f"settling {self.settling}",
            "each figure is a rate over the retained trace stream (ADR-0120). None carries a",
            "threshold, a target or a verdict, and none is a measure of relevance,",
            "correctness, helpfulness or user satisfaction.",
        ]

    def _diagnostic_lines(self) -> list[str]:
        """§7's latency summary, over the whole window.

        §7's #824 shortfall watch stood here until ADR-0128 §3 retired it: after
        the eligibility pre-filter its window share is identically zero and its
        incidence "stops measuring the store", so "the offline report states no
        shortfall incidence and no window share". The question it stood in for is
        answered over the store instead, by the census ADR-0129 defines.
        """
        lines = ["diagnostics over the window entire — none of these is a measure"]
        lines.append("  operation latency, seconds")
        if not self.latency:
            lines.append("    no operation trace in the window")
        lines += [f"    {seam.seam:<20} {seam.elapsed.rendered(places=3)}" for seam in self.latency]
        return lines


def _part_lines(part: Part, label: str) -> list[str]:
    """One block of measures, headed by which window it is over."""
    return [
        f"{label}  [{part.start:%Y-%m-%dT%H:%M:%S%z}, {part.end:%Y-%m-%dT%H:%M:%S%z})",
        f"  memory precision (§4)          {part.user.rendered_precision()}",
        f"  machine overturn rate (§4)     {part.machine.rendered_overturn()}",
        f"  correction rate (§5)           {part.correction.rendered()}",
        f"  beliefs per correction (§5)    {part.beliefs_per_correction.rendered()}",
        f"  repeated-explanation rate (§6) {part.repeated_explanation.rendered()}",
        f"  observe reinforcement share    {part.observe_share.rendered()}",
        "    — the observation stage's re-mining overlap, not a repeated explanation",
    ]


def _health_lines(health: StreamHealth) -> list[str]:
    """The stream-health block, including every exclusion this ADR's rules caused."""
    lines = [
        "stream",
        f"  retained traces                {health.retained}",
        f"  oldest retained                {health.oldest:%Y-%m-%dT%H:%M:%S%z}",
        f"  newest retained                {health.newest:%Y-%m-%dT%H:%M:%S%z}",
        f"  in the window                  {health.walked}",
    ]
    lines += [f"    {kind.value:<28} {count}" for kind, count in sorted(health.by_kind.items())]
    lines += [
        "  excluded, by the rule that excluded it",
        f"    malformed (§2)               {health.malformed}",
        f"    truncated (§2)               {health.truncated}",
        f"    counter-inconsistent (§2)    {health.counter_inconsistent}",
        f"    unattributed writes (§3)     {health.unattributed}",
        f"    unclassified writes (§3)     {health.unclassified}",
        f"    ambiguous surfacings (§4)    {health.ambiguous_surfacings}",
    ]
    if health.unclassified_seams:
        lines.append(f"    unclassified seams met       {', '.join(health.unclassified_seams)}")
    lines.append("  restarts — each gap is an upper bound on downtime, not the downtime")
    if not health.restarts:
        lines.append("    no configuration trace is retained")
    lines += [_restart_line(restart) for restart in health.restarts]
    return lines


def _restart_line(restart: Restart) -> str:
    """One ``CONFIGURATION`` trace: when, the bounding gap, and whether it moved.

    Three things the gap can be, and the third is not a rounding of the first
    two: no predecessor at all; a predecessor whose reported instant is *later*
    than this one's, which bounds nothing; and an interval.
    """
    if not restart.preceded:
        gap = "no preceding trace"
    elif restart.gap is None:
        gap = "no downtime bound — the preceding trace reports a later instant"
    else:
        gap = f"gap at most {restart.gap}"
    moved = "configuration CHANGED" if restart.changed else "configuration unchanged"
    return f"    {restart.at:%Y-%m-%dT%H:%M:%S%z}  {gap}  {moved}"
