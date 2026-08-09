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

    from ai_assistant.core.types import TraceKind

_UNDEFINED = "undefined (denominator is zero)"


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
        """The ratio, or ``None`` when the denominator is zero."""
        return self.numerator / self.denominator if self.defined else None

    def rendered(self) -> str:
        """The ratio and its two counts, or the undefined statement.

        The numerator is printed even when the ratio is undefined, rather than
        assumed to be zero with it. Most of this ADR's ratios cannot have one
        without the other — a correction is one of the rulings it is a share of —
        but beliefs-per-correction sums two quantities a single trace could
        report inconsistently, and a suppressed numerator there would hide the
        inconsistency behind the word *undefined*.
        """
        if self.value is None:
            return f"{_UNDEFINED}  ({self.numerator} of 0)"
        return f"{self.value:.4f}  ({self.numerator} of {self.denominator})"


@dataclass(frozen=True, slots=True)
class Distribution:
    """A summary of a sample the report states rather than a rate.

    Used for the two §7 diagnostics that are per-event figures: an ``OPERATION``
    trace's ``elapsed``, and the window share of each shortfall read. Summarised
    rather than listed because the per-read figures run to thousands of lines on
    a real stream and none of them is a measure.

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
        """``1 -`` the overturn rate, withheld where the settling is unequal."""
        if not self.settled:
            return "withheld — the stream does not yet extend the settling period past the window"
        value = self.rate.value
        if value is None:
            return f"{_UNDEFINED}  (no non-ambiguous surfacing)"
        return f"{1 - value:.4f}  ({self.overturned} overturned of {self.non_ambiguous})"

    def rendered_overturn(self) -> str:
        """The overturn rate itself, withheld under the same condition."""
        if not self.settled:
            return "withheld — the stream does not yet extend the settling period past the window"
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
        gap: The interval from the preceding trace of any kind, or ``None``.
            An **upper bound** on how long the hub was not running, never the
            downtime: the stream cannot say when the previous process stopped.
        changed: Whether the effective figures moved. Only a changed stamp
            partitions the window (§8).
    """

    at: datetime
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
class Shortfall:
    """#824's watch, defined inside the bound the emitter imposes (§7).

    Attributes:
        incidence: Saturated shortfall reads over every retrieval in the window
            carrying the eight counts — "the population the question is about".
        shares: ``excluded_window ÷ (candidates - returned)`` for each shortfall
            read where the two differ. A shortfall that excluded nothing is one
            the KNN ceiling alone bound; it is counted in the incidence and left
            out of the share.
    """

    incidence: Rate
    shares: Distribution


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
        counter_inconsistent: Excluded from §7's population and no other.
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
        shortfall: §7's #824 watch, or ``None``.
        latency: §7's per-seam operation latency, in seam order.
        health: §7's stream-health counts, or ``None``.
    """

    refusal: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    settling: timedelta | None = None
    whole: Part | None = None
    parts: tuple[Part, ...] = ()
    shortfall: Shortfall | None = None
    latency: tuple[SeamLatency, ...] = ()
    health: StreamHealth | None = None

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
        return "\n".join(lines)

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
        """§7's shortfall watch and latency summary, over the whole window."""
        lines = ["diagnostics over the window entire — none of these is a measure"]
        if self.shortfall is not None:
            lines.append(f"  shortfall incidence (#824)     {self.shortfall.incidence.rendered()}")
            lines.append(f"  window share of a shortfall    {self.shortfall.shares.rendered()}")
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
    """One ``CONFIGURATION`` trace: when, the bounding gap, and whether it moved."""
    gap = "no preceding trace" if restart.gap is None else f"gap at most {restart.gap}"
    moved = "configuration CHANGED" if restart.changed else "configuration unchanged"
    return f"    {restart.at:%Y-%m-%dT%H:%M:%S%z}  {gap}  {moved}"
