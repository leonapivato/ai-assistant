"""ADR-0120's three measures and their populations, over a scripted stream.

Each test is a clause of the ADR rather than a behaviour of the code, because the
ADR's own claim is that "two implementations must produce the same number" —
which is only checkable if the tests are written against the clauses. The
docstrings name the section each one holds.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from measure_fixtures import (
    END,
    QUICK,
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

from ai_assistant.evaluation.measures import compute
from ai_assistant.testing import FakeTraceStore

from ai_assistant.core.types import EvaluationTrace, TraceOutcome  # isort: skip


if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import EvaluationTrace
    from ai_assistant.evaluation._figures import MeasureReport


async def report(*traces: EvaluationTrace, settling: timedelta = SETTLING) -> MeasureReport:
    """Every measure over the standard window, against a stream of ``traces``.

    An anchor trace at the window's own start is prepended, because §8 refuses a
    window beginning before the oldest retained trace — a real stream always has
    the startup that opened the period in it, and a suite that omitted one would
    be testing the refusal rather than the measure.
    """
    anchor = operation("start", when=START, correlation="boot")
    return await compute(FakeTraceStore((anchor, *traces)), start=START, end=END, settling=settling)


def _surfaced(record: str = "r1") -> tuple[EvaluationTrace, EvaluationTrace]:
    """A read that returned ``record``, inside a ``converse`` operation."""
    return (
        retrieval(when=at(days=1), returned=(record,), correlation="c1"),
        operation("converse", when=at(days=1), correlation="c1"),
    )


def _overturning(
    *, seam: str, when_hours: int = 2, record: str = "r1", correlation: str = "c2"
) -> tuple[EvaluationTrace, EvaluationTrace]:
    """A write that superseded ``record``, inside an operation at ``seam``."""
    when = at(days=1, hours=when_hours)
    return (
        write(
            when=when,
            correlation=correlation,
            metrics=decisions(supersede=1),
            written=("fresh",),
            superseded=(record,),
        ),
        operation(seam, when=when, correlation=correlation),
    )


class TestMemoryPrecision:
    """§4 — one minus the rate at which surfaced records are later overturned."""

    async def test_a_user_supersession_within_settling_overturns_the_surfacing(self) -> None:
        """The whole measure in one stream: one surfacing, one user overturn."""
        result = await report(*_surfaced(), *_overturning(seam="learn"), settled_marker())
        assert result.whole is not None
        assert result.whole.user.overturned == 1
        assert result.whole.user.non_ambiguous == 1
        assert result.whole.user.rate.value == 1.0

    async def test_a_surfacing_nothing_overturned_stays_in_the_denominator(self) -> None:
        """ "Every wrong belief the user never corrects counts here as correct"."""
        result = await report(*_surfaced(), settled_marker())
        assert result.whole is not None
        assert result.whole.user.overturned == 0
        assert result.whole.user.non_ambiguous == 1

    async def test_a_write_that_began_before_the_read_finished_is_ambiguous(self) -> None:
        """A pair the stream cannot order leaves numerator and denominator alike."""
        read, op = _surfaced()
        overlapping = write(
            when=read.occurred_at,
            correlation="c2",
            metrics=decisions(supersede=1),
            superseded=("r1",),
        )
        result = await report(
            read,
            op,
            overlapping,
            operation("learn", when=at(days=1), correlation="c2"),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.ambiguous == 1
        assert result.whole.user.non_ambiguous == 0

    async def test_a_candidate_beyond_the_settling_horizon_is_not_a_candidate(self) -> None:
        """The numerator's search is bounded at ``r.occurred_at + s`` (§8)."""
        result = await report(
            *_surfaced(), *_overturning(seam="learn", when_hours=25), settled_marker()
        )
        assert result.whole is not None
        assert result.whole.user.overturned == 0
        assert result.whole.user.non_ambiguous == 1

    async def test_a_write_appended_before_the_read_is_not_a_candidate(self) -> None:
        """``r ≺ w`` is a conjunct, and it is insertion order rather than the clock."""
        earlier = write(
            when=at(days=1, hours=2),
            correlation="c2",
            metrics=decisions(supersede=1),
            superseded=("r1",),
        )
        result = await report(
            earlier,
            operation("learn", when=at(days=1, hours=2), correlation="c2"),
            *_surfaced(),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.overturned == 0
        assert result.whole.user.non_ambiguous == 1

    async def test_a_retirement_overturns_and_a_fresh_written_id_does_not(self) -> None:
        """``SUPERSEDED`` and ``RETIRED`` count; a supersession's ``WRITTEN`` id does not."""
        retiring = write(
            when=at(days=1, hours=2),
            correlation="c2",
            metrics=decisions(supersede=1),
            written=("r2",),
            retired=("r1",),
        )
        result = await report(
            *_surfaced(),
            retrieval(when=at(days=1), returned=("r2",), correlation="c1"),
            retiring,
            operation("learn", when=at(days=1, hours=2), correlation="c2"),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.overturned == 1
        assert result.whole.user.non_ambiguous == 2

    async def test_one_id_returned_twice_is_two_surfacings(self) -> None:
        """ "A belief surfaced in ten turns and then retired was wrong ten times"."""
        result = await report(
            *_surfaced(),
            retrieval(when=at(days=1, hours=1), returned=("r1",), correlation="c1"),
            *_overturning(seam="learn", when_hours=3),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.overturned == 2
        assert result.whole.user.non_ambiguous == 2

    async def test_a_machine_supersession_moves_only_the_diagnostic(self) -> None:
        """#829's experiment: the arming moves the machine rate, not precision."""
        result = await report(*_surfaced(), *_overturning(seam="consolidate"), settled_marker())
        assert result.whole is not None
        assert result.whole.user.overturned == 0
        assert result.whole.user.non_ambiguous == 1
        assert result.whole.machine.overturned == 1
        assert result.whole.machine.rate.value == 1.0

    async def test_the_figure_is_withheld_until_the_stream_outruns_the_settling(self) -> None:
        """§8: an unequal settling is not compared, it is refused."""
        result = await report(*_surfaced())
        assert result.whole is not None
        assert result.whole.user.settled is False
        assert "withheld" in result.whole.user.rendered_precision()

    async def test_a_read_without_elapsed_is_ambiguous(self) -> None:
        """The interval test cannot be evaluated, so §4 declines to guess."""
        result = await report(
            retrieval(when=at(days=1), returned=("r1",), elapsed=None),
            operation("converse", when=at(days=1)),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.ambiguous == 1


class TestCorrectionRate:
    """§5 — the share of rulings that overturned a held belief."""

    async def test_the_rate_is_supersessions_over_the_six_decision_counts(self) -> None:
        """The denominator is the sum of the six, and the numerator one of them."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(accept=2, supersede=1)),
            operation("converse", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.numerator == 1
        assert result.whole.correction.denominator == 3

    async def test_the_denominator_is_never_the_proposals_metric(self) -> None:
        """§5: ``proposals`` is an entry quantity and does not lose rows with the rest."""
        metrics: dict[str, int | float | bool] = {
            **decisions(accept=1, supersede=1),
            "proposals": 9,
        }
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=metrics),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.denominator == 2

    async def test_a_machine_write_is_outside_the_population(self) -> None:
        """A consolidation's supersession is the system revising itself, not a correction."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=4)),
            operation("consolidate", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.defined is False

    async def test_beliefs_per_correction_reads_the_sets_total(self) -> None:
        """ "A correction resolves every conflict it is shown" — acts against beliefs."""
        result = await report(
            write(
                when=at(days=1),
                correlation="c1",
                metrics=decisions(supersede=1),
                superseded=("a", "b", "c"),
            ),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.beliefs_per_correction.numerator == 3
        assert result.whole.beliefs_per_correction.denominator == 1

    async def test_a_correction_without_a_superseded_set_leaves_the_diagnostic(self) -> None:
        """The diagnostic is over the sub-population carrying the set, both halves."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=2)),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.numerator == 2
        assert result.whole.beliefs_per_correction.defined is False


class TestRepeatedExplanationRate:
    """§6 — direct user acts that added nothing new."""

    async def test_the_rate_is_over_learn_and_answer_only(self) -> None:
        """A reinforcement the user supplied directly is a repeated explanation."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(accept=1, reinforce=1)),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.repeated_explanation.numerator == 1
        assert result.whole.repeated_explanation.denominator == 2

    async def test_observe_reinforcements_are_excluded_and_reported_apart(self) -> None:
        """§6's finding: the observation stage's overlap is not a product signal."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(reinforce=5)),
            operation("observe", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.repeated_explanation.defined is False
        assert result.whole.observe_share.numerator == 5
        assert result.whole.observe_share.denominator == 5

    async def test_a_converse_reinforcement_is_in_neither_figure(self) -> None:
        """``converse`` is a user seam and not a *direct* one, and not ``observe``."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(reinforce=3)),
            operation("converse", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.repeated_explanation.defined is False
        assert result.whole.observe_share.defined is False
        assert result.whole.correction.denominator == 3


class TestEligibility:
    """§2 — presence is the completeness test, not the outcome."""

    async def test_a_faulted_crossing_that_ruled_is_counted(self) -> None:
        """A partial reading is "a truthful account of the rulings that did happen"."""
        result = await report(
            write(
                when=at(days=1),
                correlation="c1",
                metrics=decisions(accept=1, supersede=1),
                outcome=TraceOutcome.FAULT,
            ),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.denominator == 2

    async def test_a_crossing_that_observed_no_ruling_enters_nothing(self) -> None:
        """An absent key means *not observed*, and the fault path carries none of the six."""
        result = await report(
            write(
                when=at(days=1),
                correlation="c1",
                metrics={"proposals": 2},
                outcome=TraceOutcome.FAULT,
            ),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.defined is False
        assert result.health is not None
        assert result.health.malformed == 0

    async def test_a_strict_subset_of_the_decision_keys_is_malformed(self) -> None:
        """No emitter can produce one, and a measure that divided by it would be wrong."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics={"decisions_supersede": 1}),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.defined is False
        assert result.health is not None
        assert result.health.malformed == 1

    async def test_a_boolean_count_is_malformed(self) -> None:
        """``bool`` *is* an ``int``, so an integrality test alone would admit it."""
        metrics: dict[str, int | float | bool] = {**decisions(), "decisions_accept": True}
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=metrics),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.health is not None
        assert result.health.malformed == 1

    async def test_a_negative_count_is_malformed(self) -> None:
        """A negative numerator would be reported as a figure rather than caught."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=-1)),
            operation("learn", when=at(days=1), correlation="c1"),
        )
        assert result.health is not None
        assert result.health.malformed == 1

    async def test_a_truncated_returned_set_leaves_the_identity_population(self) -> None:
        """#848: a read declaring truncation cannot be joined on, and says so."""
        capped = tuple(f"r{ordinal}" for ordinal in range(256))
        result = await report(
            retrieval(when=at(days=1), returned=capped, returned_total=300, correlation="c1"),
            operation("converse", when=at(days=1), correlation="c1"),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.non_ambiguous == 0
        assert result.health is not None
        assert result.health.truncated == 1


class TestAttribution:
    """§3 — a write is attributed to the operation that caused it, by seam."""

    async def test_a_write_without_a_correlation_is_unattributed(self) -> None:
        """ "``None`` is the honest answer outside an operation"."""
        result = await report(
            write(when=at(days=1), correlation=None, metrics=decisions(supersede=1))
        )
        assert result.health is not None
        assert result.health.unattributed == 1
        assert result.whole is not None
        assert result.whole.correction.defined is False

    async def test_a_correlation_matching_no_operation_is_unattributed(self) -> None:
        """The join is a lookup over the retained stream, not a heuristic."""
        result = await report(
            write(when=at(days=1), correlation="orphan", metrics=decisions(supersede=1))
        )
        assert result.health is not None
        assert result.health.unattributed == 1

    async def test_a_correlation_carried_by_two_operations_is_unattributed(self) -> None:
        """§3 says *the unique* operation trace, so two of them name none."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=1)),
            operation("learn", when=at(days=1), correlation="c1"),
            operation("answer", when=at(days=1, hours=1), correlation="c1"),
        )
        assert result.health is not None
        assert result.health.unattributed == 1

    async def test_an_unlisted_seam_is_unclassified_and_named(self) -> None:
        """ "An unclassified count that rises is a visible prompt to classify the seam"."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=1)),
            operation("belief", when=at(days=1), correlation="c1"),
        )
        assert result.health is not None
        assert result.health.unclassified == 1
        assert result.health.unclassified_seams == ("belief",)
        assert result.whole is not None
        assert result.whole.correction.defined is False

    async def test_attribution_reaches_outside_the_window(self) -> None:
        """ "A write inside the window whose operation trace falls outside it is
        attributed normally"."""
        result = await report(
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=1)),
            operation("learn", when=END + timedelta(days=1), correlation="c1"),
        )
        assert result.whole is not None
        assert result.whole.correction.numerator == 1
        assert result.health is not None
        assert result.health.unattributed == 0

    async def test_a_write_outside_the_window_can_still_overturn_a_surfacing(self) -> None:
        """§4's candidate window is the settling period, not the measurement window."""
        overturn_at = END - timedelta(hours=1)
        result = await report(
            retrieval(when=overturn_at - timedelta(hours=1), returned=("r1",), correlation="c1"),
            operation("converse", when=overturn_at - timedelta(hours=1), correlation="c1"),
            write(
                when=END + timedelta(hours=1),
                correlation="c2",
                metrics=decisions(supersede=1),
                superseded=("r1",),
            ),
            operation("learn", when=END + timedelta(hours=1), correlation="c2"),
            settled_marker(),
        )
        assert result.whole is not None
        assert result.whole.user.overturned == 1
        assert result.whole.correction.defined is False


class TestRetrievalDiagnostics:
    """§7's surviving diagnostics, after ADR-0128 §3 retired #824's watch."""

    async def test_no_shortfall_figure_is_stated_at_all(self) -> None:
        """ADR-0128 §3: "``MeasureReport`` carries no shortfall figure".

        Asserted over the read that used to *be* the watch's whole subject — a
        saturated shortfall, ``returned < limit`` with ``candidates >= fetch_k``
        and a window exclusion to take a share of. The old suite read two
        figures off exactly this stream; the report now states neither, and the
        rendered text names neither.
        """
        saturated = read_counts(
            candidates=40, returned=3, excluded_kind=10, excluded_retention=7, excluded_window=20
        )
        result = await report(
            retrieval(when=at(days=1), returned=None, counts=read_counts()),
            retrieval(when=at(days=2), returned=None, counts=saturated),
        )
        assert not hasattr(result, "shortfall")
        assert "shortfall" not in result.render()

    async def test_counter_inconsistency_is_counted_and_excludes_nothing(self) -> None:
        """ADR-0128 §3 leaves §2's rule standing; §4 still gets the ids that came back."""
        impossible = read_counts(candidates=0, returned=1)
        result = await report(
            retrieval(when=at(days=1), returned=("r1",), counts=impossible, correlation="c1"),
            operation("converse", when=at(days=1), correlation="c1"),
            settled_marker(),
        )
        assert result.health is not None
        assert result.health.counter_inconsistent == 1
        assert result.health.malformed == 0
        assert result.whole is not None
        assert result.whole.user.non_ambiguous == 1

    async def test_the_latency_summary_is_per_seam(self) -> None:
        """#829's other baseline half, and it needs no new definition."""
        result = await report(
            operation("converse", when=at(days=1), elapsed=timedelta(seconds=2)),
            operation("converse", when=at(days=2), elapsed=timedelta(seconds=4)),
            operation("learn", when=at(days=3), elapsed=QUICK),
        )
        summaries = {summary.seam: summary.elapsed for summary in result.latency}
        assert summaries["converse"].count == 2
        assert summaries["converse"].mean == 3.0
        assert summaries["learn"].count == 1


class TestWindowAndParts:
    """§8 — the partition, the settling, and the two refusals."""

    async def test_a_changed_configuration_partitions_the_window(self) -> None:
        """ "The report finds the change and reports the two sides"."""
        result = await report(
            configuration(when=START, metrics={"observation_batch_size": 25}),
            write(when=at(days=1), correlation="c1", metrics=decisions(supersede=1)),
            operation("learn", when=at(days=1), correlation="c1"),
            configuration(when=at(days=10), metrics={"observation_batch_size": 50}),
            write(when=at(days=11), correlation="c2", metrics=decisions(accept=1)),
            operation("learn", when=at(days=11), correlation="c2"),
        )
        assert len(result.parts) == 2
        assert result.parts[0].correction.numerator == 1
        assert result.parts[1].correction.numerator == 0
        assert result.whole is not None
        assert result.whole.correction.denominator == 2

    async def test_an_unchanged_configuration_partitions_nothing(self) -> None:
        """A restart that changed no figure is a restart, not an intervention."""
        result = await report(
            configuration(when=START, metrics={"observation_batch_size": 25}),
            configuration(when=at(days=10), metrics={"observation_batch_size": 25}),
        )
        assert result.parts == ()

    async def test_a_window_starting_before_the_oldest_trace_is_refused(self) -> None:
        """A swept early period makes the figure a statement about another period."""
        result = await compute(
            FakeTraceStore([operation("start", when=at(days=5))]),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert result.refusal is not None
        assert "before the oldest retained trace" in result.refusal
        assert result.whole is None

    async def test_an_empty_stream_states_that_and_nothing_else(self) -> None:
        """§8 applies no window validation to a stream with nothing in it."""
        result = await compute(FakeTraceStore([]), start=START, end=END, settling=SETTLING)
        assert result.refusal is None
        assert result.whole is None
        assert result.health is None
        assert "empty" in result.render()

    async def test_an_inverted_window_is_refused(self) -> None:
        """A measure is a rate over a half-open interval, so it needs one."""
        result = await compute(
            FakeTraceStore([operation("start", when=START)]),
            start=END,
            end=START,
            settling=SETTLING,
        )
        assert result.refusal is not None
        assert "inverted" in result.refusal

    async def test_a_negative_settling_is_refused(self) -> None:
        """``s`` is a non-negative settling period (§1's notation)."""
        result = await compute(
            FakeTraceStore([operation("start", when=START)]),
            start=START,
            end=END,
            settling=timedelta(hours=-1),
        )
        assert result.refusal is not None
        assert "negative" in result.refusal


class TestSettlingBounds:
    """A settling period the window's end cannot be moved forward by."""

    async def test_a_settling_reaching_past_the_last_instant_is_refused(self) -> None:
        """One guard covers §4's candidate horizon and §8's settling test alike.

        Every instant the walk adds the settling to is a read's ``occurred_at``,
        which lies in ``[start, end)``. So if ``end + s`` is representable, every
        addition inside the walk is — and if it is not, an ``OverflowError`` would
        otherwise come out of the middle of the walk rather than as a refusal.
        """
        result = await compute(
            FakeTraceStore([operation("start", when=START)]),
            start=START,
            end=END,
            settling=timedelta(days=999999999),
        )

        assert result.refusal is not None
        assert "reaches past the last instant" in result.refusal
        assert result.whole is None

    async def test_the_largest_workable_settling_still_reports(self) -> None:
        """The guard refuses only what cannot be represented, not what is merely large."""
        result = await compute(
            FakeTraceStore([operation("start", when=START)]),
            start=START,
            end=END,
            settling=timedelta(days=365 * 100),
        )

        assert result.refusal is None
        assert result.whole is not None


class TestTheEmptyStreamComesFirst:
    """§8: an empty stream "applies no window validation", and that is unqualified.

    The clause is stated ahead of every refusal, including the two this
    implementation adds that the ADR does not require. A stream with nothing in
    it has nothing to measure whatever window was asked for, so the emptiness is
    the answer — and the window's own fault surfaces on the next run, against a
    stream that has something to say.
    """

    @pytest.mark.parametrize(
        ("start", "end", "settling"),
        [
            (END, START, SETTLING),
            (START, END, timedelta(hours=-1)),
            (START, END, timedelta(days=999999999)),
            (START - timedelta(days=365), END, SETTLING),
        ],
        ids=["inverted", "negative-settling", "unrepresentable-settling", "before-any-trace"],
    )
    async def test_no_window_is_validated_over_an_empty_stream(
        self, start: datetime, end: datetime, settling: timedelta
    ) -> None:
        result = await compute(FakeTraceStore([]), start=start, end=end, settling=settling)

        assert result.refusal is None
        assert result.whole is None
        assert "empty" in result.render()

    async def test_the_same_window_is_refused_once_the_stream_has_something_in_it(self) -> None:
        """The refusals are not removed by the clause above, only ordered behind it."""
        result = await compute(
            FakeTraceStore([operation("start", when=START)]),
            start=END,
            end=START,
            settling=SETTLING,
        )

        assert result.refusal is not None
        assert "inverted" in result.refusal
