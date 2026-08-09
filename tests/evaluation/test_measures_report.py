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
