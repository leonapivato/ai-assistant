"""What the report says: §7's stream health, §8's restarts, and §10's content rule.

The measures themselves are on test in ``test_measures.py``. What is on test here
is the part an operator actually reads — that every exclusion is stated under the
rule that caused it, that a zero denominator is *undefined* rather than a zero,
and that no identifier of any kind reaches the page.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from measure_fixtures import (
    END,
    SETTLING,
    START,
    at,
    configuration,
    decisions,
    operation,
    read_counts,
    retrieval,
    settled_marker,
    write,
)

from ai_assistant.core.types import TraceKind
from ai_assistant.evaluation._figures import Rate
from ai_assistant.evaluation.measures import compute
from ai_assistant.testing import FakeTraceStore

if TYPE_CHECKING:
    from ai_assistant.core.types import EvaluationTrace
    from ai_assistant.evaluation._figures import MeasureReport


async def report(*traces: EvaluationTrace) -> MeasureReport:
    """Every figure over the standard window, anchored at its start."""
    anchor = operation("start", when=START, correlation="boot")
    return await compute(FakeTraceStore((anchor, *traces)), start=START, end=END, settling=SETTLING)


class TestStreamHealth:
    """§7 — the counts that let a reader distrust the rest."""

    async def test_the_walk_is_counted_by_kind_over_the_window(self) -> None:
        result = await report(
            retrieval(when=at(days=1), returned=("r1",)),
            write(when=at(days=1)),
            configuration(when=at(days=2)),
            operation("converse", when=END + timedelta(days=2)),
        )
        assert result.health is not None
        assert result.health.by_kind[TraceKind.RETRIEVAL] == 1
        assert result.health.by_kind[TraceKind.MEMORY_WRITE] == 1
        assert result.health.by_kind[TraceKind.CONFIGURATION] == 1
        assert result.health.by_kind[TraceKind.OPERATION] == 1  # the anchor; not the one after
        assert result.health.walked == 4
        assert result.health.retained == 5

    async def test_the_extent_is_over_the_whole_retained_stream(self) -> None:
        """Oldest and newest are retained-stream facts, not window facts."""
        result = await report(operation("converse", when=END + timedelta(days=3)))
        assert result.health is not None
        assert result.health.oldest == START
        assert result.health.newest == END + timedelta(days=3)

    async def test_each_exclusion_is_stated_under_the_rule_that_caused_it(self) -> None:
        """Malformed, counter-inconsistent and unclassified are three counts, not one."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics={"decisions_accept": 1}),
            operation("learn", when=at(days=1), correlation="c1"),
            retrieval(when=at(days=2), returned=None, counts=read_counts(candidates=0, returned=1)),
            write(when=at(days=3), correlation="c3", metrics=decisions(accept=1)),
            operation("belief", when=at(days=3), correlation="c3"),
        )
        assert result.health is not None
        assert result.health.malformed == 1
        assert result.health.counter_inconsistent == 1
        assert result.health.unclassified == 1
        assert result.health.unclassified_seams == ("belief",)


class TestRestarts:
    """§8 — every configuration trace, with the gap that bounds the downtime."""

    async def test_a_gap_bounds_the_downtime_and_a_change_is_marked(self) -> None:
        result = await report(
            configuration(when=at(days=1), metrics={"observation_batch_size": 25}),
            configuration(when=at(days=5), metrics={"observation_batch_size": 50}),
        )
        assert result.health is not None
        first, second = result.health.restarts
        assert first.gap == timedelta(days=1)
        assert first.changed is False
        assert second.gap == timedelta(days=4)
        assert second.changed is True
        assert "upper bound on downtime" in result.render()

    async def test_a_restart_outside_the_window_is_still_reported(self) -> None:
        """§8's clause is over the retained stream, not over the window."""
        result = await report(configuration(when=END + timedelta(days=1)))
        assert result.health is not None
        assert len(result.health.restarts) == 1


class TestRendering:
    """§1's undefined statement, §10's content rule, and the report's own shape."""

    async def test_no_record_id_reaches_the_page(self) -> None:
        """§10: "no record id, correlation id or trace id"."""
        surfaced = "a-record-id-nobody-should-see"
        result = await report(
            retrieval(when=at(days=1), returned=(surfaced,), correlation="a-correlation-id"),
            operation("converse", when=at(days=1), correlation="a-correlation-id"),
            write(
                when=at(days=1, hours=2),
                correlation="c2",
                metrics=decisions(supersede=1),
                superseded=(surfaced,),
            ),
            operation("learn", when=at(days=1, hours=2), correlation="c2"),
            settled_marker(),
        )
        rendered = result.render()
        assert surfaced not in rendered
        assert "a-correlation-id" not in rendered

    async def test_a_zero_denominator_is_stated_as_undefined(self) -> None:
        """ "A zero asserts a rate that was measured to be zero" — this one was not."""
        result = await report(operation("converse", when=at(days=1)))
        assert result.whole is not None
        assert result.whole.correction.defined is False
        assert "undefined" in result.render()

    async def test_the_heading_states_the_window_and_the_settling(self) -> None:
        """§1: "a figure reported without both is not one of these measures"."""
        rendered = (await report()).render()
        assert "2026-07-01T00:00:00+0000" in rendered
        assert "2026-08-01T00:00:00+0000" in rendered
        assert "settling 1 day, 0:00:00" in rendered

    async def test_the_report_disclaims_a_verdict(self) -> None:
        """§1: no threshold, no target, no pass/fail, no trend claim."""
        rendered = (await report()).render()
        assert "None carries a" in rendered
        assert "threshold, a target or a verdict" in rendered

    async def test_each_part_is_rendered_beside_the_whole_window(self) -> None:
        """§8: "states every measure for each part as well as for ``W`` whole"."""
        result = await report(
            configuration(when=at(days=1), metrics={"observation_batch_size": 25}),
            configuration(when=at(days=10), metrics={"observation_batch_size": 50}),
        )
        rendered = result.render()
        assert "the window entire" in rendered
        assert "part 1 of 2" in rendered
        assert "part 2 of 2" in rendered

    async def test_an_empty_stream_renders_only_that(self) -> None:
        result = await compute(FakeTraceStore([]), start=START, end=END, settling=SETTLING)
        rendered = result.render()
        assert rendered.startswith("the retained trace stream is empty")
        assert "memory precision" not in rendered

    async def test_a_refusal_renders_alone(self) -> None:
        result = await compute(
            FakeTraceStore([operation("start", when=at(days=5))]),
            start=START,
            end=END,
            settling=SETTLING,
        )
        rendered = result.render()
        assert rendered == result.refusal
        assert "memory precision" not in rendered


class TestUnboundedCounts:
    """A count the *type* admits and no emitter writes still must not abort a run.

    ADR-0120 §2 constrains a count to "a non-negative integer that is not a
    ``bool``" and puts no ceiling on it, and ``RecordIdSet.total`` carries only
    ``ge=0``. Every ratio this ADR defines is a share of a population containing
    its own numerator — at most one, and so representable — except
    beliefs-per-correction, which divides beliefs by corrective acts and is
    unbounded above by construction. That is the one that would otherwise raise
    ``OverflowError`` out of the middle of the render and take the whole report
    with it.
    """

    def test_an_unrepresentable_ratio_states_both_counts_instead(self) -> None:
        figure = Rate(numerator=10**400, denominator=1)

        assert figure.defined is True
        assert figure.value is None
        assert "too large to state as a decimal" in figure.rendered()
        assert str(10**400) in figure.rendered()

    async def test_a_vast_superseded_total_does_not_abort_the_report(self) -> None:
        """End to end: the trace validates, hydrates, and reaches the diagnostic."""
        vast = write(
            when=at(days=1),
            correlation="c1",
            metrics=decisions(supersede=1),
            superseded=tuple(f"r{ordinal}" for ordinal in range(256)),
            superseded_total=10**400,
        )
        result = await report(vast, operation("learn", when=at(days=1), correlation="c1"))

        assert result.whole is not None
        assert result.whole.beliefs_per_correction.numerator == 10**400
        assert "too large to state as a decimal" in result.render()
        assert result.whole.correction.value == 1.0


class TestOutOfOrderInstants:
    """Insertion order and instant order can disagree, and §8's bound cannot.

    ADR-0119 §7a: the emitter stamps the instant, so "a slow sink can land an
    earlier instant after a later one" — and a wall clock that stepped backwards
    across a restart puts the same shape in the stream. The interval from the
    preceding trace is then negative, and §8 requires the figure to be stated as
    an **upper bound** on how long the hub was not running. A negative duration
    bounds no downtime, so the report declines to claim one.
    """

    async def test_a_configuration_stamped_before_its_predecessor_claims_no_bound(self) -> None:
        result = await report(
            operation("converse", when=at(days=5)),
            configuration(when=at(days=2)),
        )

        assert result.health is not None
        stamp = result.health.restarts[0]
        assert stamp.preceded is True
        assert stamp.gap is None
        assert "no downtime bound" in result.render()
        assert "gap at most -" not in result.render()

    async def test_the_first_trace_in_the_stream_is_not_a_zero_bound(self) -> None:
        """No predecessor is a third state, not a gap of nothing."""
        result = await compute(
            FakeTraceStore([configuration(when=START)]),
            start=START,
            end=END,
            settling=SETTLING,
        )

        assert result.health is not None
        stamp = result.health.restarts[0]
        assert stamp.preceded is False
        assert stamp.gap is None
        assert "no preceding trace" in result.render()

    async def test_an_equal_instant_is_a_zero_bound_and_not_an_inversion(self) -> None:
        """The boundary between the two: equal instants order fine."""
        result = await report(configuration(when=START))

        assert result.health is not None
        assert result.health.restarts[0].gap == timedelta(0)
        assert "gap at most 0:00:00" in result.render()
