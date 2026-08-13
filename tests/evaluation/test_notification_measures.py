"""ADR-0141's reader: §5's four states, §6's two measures, §7's five diagnostics.

The classifier is what most of this suite is about, because §5 is where two
implementations would diverge: its four states are "disjoint and exhaustive by
construction", and every clause of it was found by a review round rather than
written down first. Each of those rounds gets a case here, named after what it
found.

The measures themselves are short once the population is decided, which is the
point of §5 being long.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from measure_fixtures import (
    ADMIT,
    END,
    RECONSIDER,
    SETTLING,
    START,
    at,
    configuration,
    notification,
    operation,
    ruled,
)

from ai_assistant.core.types import (
    DROP_CONDITIONS,
    INTERRUPT_CONDITIONS,
    NotificationCondition,
    NotificationDispositionKind,
    TraceKind,
    TraceOutcome,
)
from ai_assistant.evaluation._notifications import NotificationState, read
from ai_assistant.evaluation._vocabulary import (
    HELD_SECONDS,
    NOTIFICATION_CONDITION_KEYS,
    NOTIFICATION_DISPOSITION_KEYS,
)
from ai_assistant.evaluation.measures import compute
from ai_assistant.testing import FakeTraceStore

if TYPE_CHECKING:
    from ai_assistant.core.types import EvaluationTrace
    from ai_assistant.evaluation._figures import NotificationFigures

INTERRUPT = NotificationDispositionKind.INTERRUPT
HOLD = NotificationDispositionKind.HOLD
DROP = NotificationDispositionKind.DROP

RULED_INTERRUPT = NOTIFICATION_DISPOSITION_KEYS[INTERRUPT]
RULED_HOLD = NOTIFICATION_DISPOSITION_KEYS[HOLD]
RULED_DROP = NOTIFICATION_DISPOSITION_KEYS[DROP]
DUPLICATE = NOTIFICATION_CONDITION_KEYS[NotificationCondition.DUPLICATE]
BUDGET = NOTIFICATION_CONDITION_KEYS[NotificationCondition.BUDGET]
PERISHABLE = NOTIFICATION_CONDITION_KEYS[NotificationCondition.PERISHABLE]
EXPIRED = NOTIFICATION_CONDITION_KEYS[NotificationCondition.EXPIRED]
AT_CAP = NOTIFICATION_CONDITION_KEYS[NotificationCondition.AT_CAP]


def state_of(trace: EvaluationTrace) -> NotificationState:
    """Which of §5's four states decides ``trace``."""
    return read(trace).state


async def figures(*traces: EvaluationTrace) -> NotificationFigures:
    """ADR-0141's figures over the standard window, anchored at its start."""
    anchor = operation("start", when=START, correlation="boot")
    report = await compute(
        FakeTraceStore((anchor, *traces)), start=START, end=END, settling=SETTLING
    )
    assert report.notifications is not None
    return report.notifications


class TestIncomplete:
    """§5's first test — the ordinary pre-ruling fault path, not a defect."""

    async def test_a_trace_carrying_no_metric_key_is_incomplete(self) -> None:
        """§3's fault path: "carrying its outcome and its fault class and **none** of
        the metric keys §4 defines"."""
        trace = notification(when=at(days=1), metrics={}, outcome=TraceOutcome.FAULT)
        assert state_of(trace) is NotificationState.INCOMPLETE

    async def test_it_enters_no_population(self) -> None:
        result = await figures(
            notification(when=at(days=1), metrics={}, outcome=TraceOutcome.FAULT),
            notification(when=at(days=2), metrics=ruled(INTERRUPT)),
        )
        assert result.health.incomplete == 1
        assert result.interruption.numerator == 1
        assert result.interruption.denominator == 1

    async def test_a_corrupt_condition_and_no_disposition_is_malformed_not_incomplete(
        self,
    ) -> None:
        """§5's seventh round: *incomplete* is defined over §4's **whole** key set.

        Defined over the disposition keys alone, "a trace carrying
        ``condition_budget = 2`` and no disposition would satisfy the first test, be
        decided there, and never reach the checks that would have called it
        malformed" — so emitter corruption would read as an ordinary outage.
        """
        trace = notification(when=at(days=1), metrics={BUDGET: 2})
        assert state_of(trace) is NotificationState.MALFORMED

    async def test_valid_conditions_and_no_disposition_are_malformed_too(self) -> None:
        """The hole the same round's widened first disjunct closes.

        Narrowing *incomplete* alone "would have left a hole, because a trace
        carrying valid drop conditions and no disposition at all passed every
        remaining test and entered the ruling population as well-formed"; the first
        malformed disjunct now reads "does not carry all three disposition keys".
        """
        conditions = dict.fromkeys(NOTIFICATION_CONDITION_KEYS.values(), 0)
        assert state_of(notification(when=at(days=1), metrics=conditions)) is (
            NotificationState.MALFORMED
        )


class TestMalformed:
    """§5's second test — a key set no emitter in this tree can write."""

    async def test_a_strict_subset_of_the_dispositions_is_malformed(self) -> None:
        metrics = ruled(HOLD)
        del metrics[RULED_DROP]
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.MALFORMED
        )

    async def test_dispositions_that_do_not_sum_to_one_are_malformed(self) -> None:
        assert state_of(notification(when=at(days=1), metrics=ruled(HOLD) | {RULED_DROP: 1})) is (
            NotificationState.MALFORMED
        )

    async def test_no_disposition_set_at_all_is_malformed(self) -> None:
        """Three zeros carry all three keys and still say nothing was ruled."""
        metrics = ruled(HOLD) | {RULED_HOLD: 0}
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.MALFORMED
        )

    async def test_a_boolean_count_is_malformed(self) -> None:
        """ADR-0120 §2's rule, serving both ADRs: a ``bool`` *is* an ``int``."""
        metrics = ruled(HOLD) | {RULED_HOLD: True}
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.MALFORMED
        )

    async def test_a_negative_count_is_malformed(self) -> None:
        metrics = ruled(HOLD) | {RULED_DROP: -1, RULED_HOLD: 2}
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.MALFORMED
        )

    async def test_a_condition_value_above_one_is_malformed(self) -> None:
        assert state_of(notification(when=at(days=1), metrics=ruled(HOLD) | {BUDGET: 2})) is (
            NotificationState.MALFORMED
        )

    async def test_an_absent_drop_condition_key_is_malformed(self) -> None:
        """§5: "A missing key is malformed rather than merely uncounted."

        Under a rule checking consistency only where the keys are present, such a
        trace "would have entered the condition incidence, shrinking that one
        condition's denominator while appearing in no exclusion count at all".
        """
        for condition in DROP_CONDITIONS:
            metrics = ruled(HOLD)
            del metrics[NOTIFICATION_CONDITION_KEYS[condition]]
            assert state_of(notification(when=at(days=1), metrics=metrics)) is (
                NotificationState.MALFORMED
            ), condition

    async def test_a_non_drop_missing_an_interrupt_condition_is_malformed(self) -> None:
        for condition in INTERRUPT_CONDITIONS:
            metrics = ruled(HOLD)
            del metrics[NOTIFICATION_CONDITION_KEYS[condition]]
            assert state_of(notification(when=at(days=1), metrics=metrics)) is (
                NotificationState.MALFORMED
            ), condition

    async def test_a_drop_carrying_an_interrupt_condition_is_malformed(self) -> None:
        """§4 forbids the half a ``DROP``'s policy never evaluated."""
        metrics = ruled(DROP) | {PERISHABLE: 0}
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.MALFORMED
        )

    async def test_the_order_decides_a_trace_two_clauses_would_both_claim(self) -> None:
        """§5's first round found both overlaps; the order is what closes them.

        "A trace carrying ``ruled_interrupt = 2`` satisfies 'carries all three
        disposition keys' and also fails the sum rule" — one trace, one state, one
        exclusion count.
        """
        result = await figures(
            notification(when=at(days=1), metrics=ruled(HOLD) | {RULED_INTERRUPT: 2})
        )
        assert result.health.malformed == 1
        assert result.health.incomplete == 0
        assert result.health.counter_inconsistent == 0
        assert result.health.well_formed == 0
        assert result.health.walked == 1


class TestCounterInconsistent:
    """§5's third test — every key admissible, and the values disagree."""

    async def test_an_interrupt_missing_an_interrupt_condition_is_inconsistent(self) -> None:
        """ADR-0130 §5 rules ``INTERRUPT`` exactly when all four hold."""
        assert state_of(notification(when=at(days=1), metrics=ruled(INTERRUPT, budget=0))) is (
            NotificationState.COUNTER_INCONSISTENT
        )

    async def test_a_drop_with_no_drop_condition_is_inconsistent(self) -> None:
        assert state_of(notification(when=at(days=1), metrics=ruled(DROP, at_cap=0))) is (
            NotificationState.COUNTER_INCONSISTENT
        )

    async def test_a_hold_with_every_interrupt_condition_met_is_inconsistent(self) -> None:
        """A ``HOLD`` whose ``failed`` set is empty is an ``INTERRUPT``."""
        assert state_of(notification(when=at(days=1), metrics=ruled(HOLD, perishable=1))) is (
            NotificationState.COUNTER_INCONSISTENT
        )

    async def test_a_non_drop_with_a_drop_condition_is_inconsistent(self) -> None:
        """§5's second round, and "the one a reader is most likely to leave out".

        ADR-0130 §5 evaluates the four drop conditions **first**, "each yielding
        ``DROP`` naming itself", so a duplicate that interrupted "is not a policy
        this tree can run". Without the clause such a trace "counts a refusal as an
        interruption, moving the one measure §6 exists for".
        """
        assert state_of(notification(when=at(days=1), metrics=ruled(INTERRUPT, duplicate=1))) is (
            NotificationState.COUNTER_INCONSISTENT
        )

    async def test_expired_and_perishable_together_are_inconsistent(self) -> None:
        """§4's two propositions "are not opposites", but they are never both ``1``.

        Reached by the clause above as well: ``condition_expired`` is a drop
        condition, and a trace carrying ``condition_perishable`` at all is not a
        ``DROP``. So this pins the verdict rather than the route to it — which is
        what a report reads, and both clauses agree on it.
        """
        metrics = ruled(HOLD, expired=1, perishable=1)
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.COUNTER_INCONSISTENT
        )

    async def test_no_expiry_at_all_leaves_both_at_zero_and_is_well_formed(self) -> None:
        """The ordinary case ADR-0130 §5 holds rather than drops."""
        metrics = ruled(HOLD)
        assert metrics[EXPIRED] == 0
        assert metrics[PERISHABLE] == 0
        assert state_of(notification(when=at(days=1), metrics=metrics)) is (
            NotificationState.WELL_FORMED
        )

    async def test_it_stays_in_the_ruling_population_and_leaves_the_condition_figures(
        self,
    ) -> None:
        """§5: the damage is localised, so the disposition is still trusted.

        "The trace can still say truthfully that an interruption happened while
        being untrustworthy about why. Excluding it from the interruption share as
        well would discard a real ruling for a reason the share does not depend on."
        """
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT, duplicate=1)),
            notification(when=at(days=2), metrics=ruled(HOLD)),
        )
        assert result.health.counter_inconsistent == 1
        assert result.interruption.numerator == 1
        assert result.interruption.denominator == 2
        # It carried `condition_duplicate = 1` and is not in the duplicate share.
        assert result.duplicate.numerator == 0
        assert result.duplicate.denominator == 1


class TestPopulations:
    """§5's ruling population and its two sub-populations."""

    async def test_membership_is_decided_by_keys_and_never_by_outcome(self) -> None:
        """§5, on ADR-0120 §2's rule. A complete key set is a completed ruling."""
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT), outcome=TraceOutcome.FAULT)
        )
        assert result.interruption.denominator == 1
        assert result.health.not_ok == 1
        assert result.health.well_formed == 1

    async def test_an_unrecognised_seam_stays_in_the_population_and_is_named(self) -> None:
        """§5's allowlist: "the count that rises is the prompt to classify it"."""
        result = await figures(
            notification(when=at(days=1), seam="notification_retract", metrics=ruled(INTERRUPT)),
            notification(when=at(days=2), seam=ADMIT, metrics=ruled(DROP, duplicate=1, at_cap=0)),
        )
        assert result.health.unclassified == 1
        assert result.health.unclassified_seams == ("notification_retract",)
        # In the ruling population: its disposition still counts.
        assert result.interruption.denominator == 2
        # In neither sub-population: the duplicate share saw only the admit trace.
        assert result.duplicate.denominator == 1
        # And the held-first share's numerator is over reconsiderations alone.
        assert result.held_first.numerator == 0

    async def test_a_trace_outside_the_window_contributes_nowhere(self) -> None:
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT)),
            notification(when=END, metrics=ruled(HOLD)),
        )
        assert result.health.walked == 1
        assert result.interruption.denominator == 1


class TestMeasures:
    """§6's two measures."""

    async def test_the_interruption_share_is_over_every_ruling(self) -> None:
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT)),
            notification(when=at(days=2), metrics=ruled(HOLD)),
            notification(when=at(days=3), metrics=ruled(HOLD)),
            notification(when=at(days=4), metrics=ruled(DROP)),
        )
        assert result.interruption.numerator == 1
        assert result.interruption.denominator == 4
        assert result.interruption.value == 0.25

    async def test_an_empty_population_makes_every_rate_undefined(self) -> None:
        """§6 restates ADR-0120 §1's rule: "undefined rather than a figure or a zero"."""
        result = await figures(notification(when=at(days=1), metrics={}))
        assert not result.interruption.defined
        assert not result.duplicate.defined
        assert not result.held_first.defined
        assert "undefined" in result.interruption.rendered()

    async def test_the_duplicate_share_is_over_offers_alone(self) -> None:
        """§6: "``condition_duplicate`` is structurally ``0`` on every
        reconsideration and pooling the two would divide a real numerator by an
        inflated denominator"."""
        result = await figures(
            notification(when=at(days=1), seam=ADMIT, metrics=ruled(DROP, duplicate=1)),
            notification(when=at(days=2), seam=ADMIT, metrics=ruled(HOLD)),
            notification(when=at(days=3), seam=RECONSIDER, metrics=ruled(HOLD)),
            notification(when=at(days=4), seam=RECONSIDER, metrics=ruled(HOLD)),
        )
        assert result.duplicate.numerator == 1
        assert result.duplicate.denominator == 2

    async def test_each_measure_states_its_denominator(self) -> None:
        """§6's last clause."""
        result = await figures(notification(when=at(days=1), metrics=ruled(INTERRUPT)))
        assert "(1 of 1)" in result.interruption.rendered()


class TestDiagnostics:
    """§7's five, none of which is a measure."""

    async def test_the_disposition_mix_is_the_three_sums_as_counts(self) -> None:
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT)),
            notification(when=at(days=2), metrics=ruled(HOLD)),
            notification(when=at(days=3), metrics=ruled(HOLD)),
            notification(when=at(days=4), metrics=ruled(DROP)),
        )
        assert (result.interrupts, result.holds, result.drops) == (1, 2, 1)
        assert result.interrupts + result.holds + result.drops == result.interruption.denominator

    async def test_each_condition_has_its_own_carrying_count(self) -> None:
        """§7: "never divides one condition's numerator by another's population".

        The four interrupt keys are absent from every ``DROP``, "so their
        denominators are the non-``DROP`` rulings and not the ruling population".
        """
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT)),
            notification(when=at(days=2), metrics=ruled(HOLD)),
            notification(when=at(days=3), metrics=ruled(DROP)),
        )
        incidence = {entry.condition: entry for entry in result.incidence}
        assert set(incidence) == set(NotificationCondition)
        for condition in DROP_CONDITIONS:
            assert incidence[condition].carried == 3, condition
        for condition in INTERRUPT_CONDITIONS:
            assert incidence[condition].carried == 2, condition
        # The interrupt held all four; the hold failed `perishable` alone.
        assert incidence[NotificationCondition.PERISHABLE].held == 1
        assert incidence[NotificationCondition.BUDGET].held == 2
        assert incidence[NotificationCondition.BUDGET].rate.value == 1.0
        # `at_cap` is the drop's reason, so it held on exactly that one ruling.
        assert incidence[NotificationCondition.AT_CAP].held == 1

    async def test_the_incidence_reads_the_well_formed_alone(self) -> None:
        result = await figures(
            notification(when=at(days=1), metrics=ruled(INTERRUPT)),
            notification(when=at(days=2), metrics=ruled(INTERRUPT, budget=0)),
        )
        incidence = {entry.condition: entry for entry in result.incidence}
        assert incidence[NotificationCondition.BUDGET].carried == 1
        assert result.interruption.denominator == 2

    async def test_the_incidence_makes_an_untuned_hub_read_as_untuned(self) -> None:
        """§7's reason for existing, and ADR-0141's Consequences.

        ADR-0130 §6 ships every class at reach ``hold``, so an untuned hub
        interrupts nothing. "That is not 'proactivity is not earning its place'; it
        is 'nobody has granted it a place', and the two demand opposite responses."
        """
        result = await figures(
            *(
                notification(when=at(days=day), metrics=ruled(HOLD, reach_interrupt=0))
                for day in range(1, 4)
            )
        )
        assert result.interruption.value == 0.0
        incidence = {entry.condition: entry for entry in result.incidence}
        assert incidence[NotificationCondition.REACH_INTERRUPT].held == 0
        assert incidence[NotificationCondition.REACH_INTERRUPT].carried == 3

    async def test_the_latency_is_over_reconsidered_interrupts(self) -> None:
        result = await figures(
            notification(
                when=at(days=1), seam=RECONSIDER, metrics=ruled(INTERRUPT) | {HELD_SECONDS: 60.0}
            ),
            notification(
                when=at(days=2), seam=RECONSIDER, metrics=ruled(INTERRUPT) | {HELD_SECONDS: 20.0}
            ),
            notification(when=at(days=3), seam=ADMIT, metrics=ruled(INTERRUPT)),
        )
        assert result.held_latency.count == 2
        assert result.held_latency.minimum == 20.0
        assert result.held_latency.maximum == 60.0
        assert result.held_latency.mean == 40.0
        assert result.health.misplaced_held_seconds == 0

    async def test_an_empty_sample_says_the_sample_is_empty(self) -> None:
        """§7: "It is a distribution and not a ratio, so the undefined rule does not
        reach it; over an empty sample the report says the sample is empty"."""
        result = await figures(notification(when=at(days=1), metrics=ruled(HOLD)))
        assert result.held_latency.count == 0
        assert result.held_latency.rendered() == "no observations"

    async def test_the_held_first_share_is_reconsidered_interrupts_over_all(self) -> None:
        result = await figures(
            notification(when=at(days=1), seam=ADMIT, metrics=ruled(INTERRUPT)),
            notification(
                when=at(days=2), seam=RECONSIDER, metrics=ruled(INTERRUPT) | {HELD_SECONDS: 5.0}
            ),
            notification(when=at(days=3), seam=ADMIT, metrics=ruled(HOLD)),
        )
        assert result.held_first.numerator == 1
        assert result.held_first.denominator == 2


class TestMisplacedHeldSeconds:
    """§7's misplacement rule — never read as a latency, never excluded elsewhere."""

    async def test_an_offer_carrying_it_is_misplaced(self) -> None:
        result = await figures(
            notification(
                when=at(days=1), seam=ADMIT, metrics=ruled(INTERRUPT) | {HELD_SECONDS: 5.0}
            )
        )
        assert result.health.misplaced_held_seconds == 1
        assert result.held_latency.count == 0
        # "Its trace stays in every other population."
        assert result.interruption.numerator == 1
        assert result.health.well_formed == 1

    async def test_a_reconsidered_hold_carrying_it_is_misplaced(self) -> None:
        """§4 carries it "exactly when the ruling was ``INTERRUPT``"."""
        result = await figures(
            notification(
                when=at(days=1), seam=RECONSIDER, metrics=ruled(HOLD) | {HELD_SECONDS: 5.0}
            )
        )
        assert result.health.misplaced_held_seconds == 1
        assert result.held_latency.count == 0

    async def test_a_reconsidered_interrupt_without_it_is_misplaced(self) -> None:
        """ "or carrying an inadmissible value or **none** where §4 requires it"."""
        result = await figures(
            notification(when=at(days=1), seam=RECONSIDER, metrics=ruled(INTERRUPT))
        )
        assert result.health.misplaced_held_seconds == 1
        assert result.held_latency.count == 0
        assert result.held_first.numerator == 1

    async def test_an_inadmissible_value_is_misplaced_rather_than_malformed(self) -> None:
        """§4: ``held_seconds`` "is **not** a count and the clause above does not
        reach it", so a negative one leaves §7's distribution and no other
        population — "and the report counts it"."""
        for value in (-1.0, True):
            result = await figures(
                notification(
                    when=at(days=1),
                    seam=RECONSIDER,
                    metrics=ruled(INTERRUPT) | {HELD_SECONDS: value},
                )
            )
            assert result.health.misplaced_held_seconds == 1, value
            assert result.health.malformed == 0, value
            assert result.held_latency.count == 0, value
            assert result.interruption.numerator == 1, value


class TestMisplacementReachesThePopulationOnly:
    """§7's misplacement is about a trace in the populations, and only about one.

    Its clause reads: "A misplaced value is never read as a latency, **its trace
    stays in every other population**, and the report counts it" — which presupposes
    populations to stay in. §5 says an incomplete trace "enters no population" and "a
    malformed trace enters no population", so neither can be misplaced *for a
    diagnostic it is not in*. Establishing otherwise would mean reading a disposition
    off a trace whose defect is that "neither trace can be trusted for anything".

    Adversarial review proposed the wider reading on the second round. It is declined
    here rather than adopted, and these cases are what make the decision checkable.
    """

    async def test_a_malformed_reconsideration_is_counted_once_under_its_own_rule(
        self,
    ) -> None:
        """The reviewer's own example: a readable ``INTERRUPT``, a missing condition
        key, and no ``held_seconds``."""
        metrics = ruled(INTERRUPT)
        del metrics[BUDGET]
        result = await figures(notification(when=at(days=1), seam=RECONSIDER, metrics=metrics))
        assert result.health.malformed == 1
        assert result.health.misplaced_held_seconds == 0
        assert result.interruption.denominator == 0
        assert result.held_latency.count == 0

    async def test_a_malformed_trace_carrying_it_where_forbidden_is_also_counted_once(
        self,
    ) -> None:
        metrics = ruled(HOLD) | {HELD_SECONDS: 5.0}
        del metrics[BUDGET]
        result = await figures(notification(when=at(days=1), seam=ADMIT, metrics=metrics))
        assert result.health.malformed == 1
        assert result.health.misplaced_held_seconds == 0

    async def test_an_incomplete_trace_is_never_misplaced(self) -> None:
        """§4's requirement is not even determinable: there is no disposition."""
        result = await figures(notification(when=at(days=1), seam=RECONSIDER, metrics={}))
        assert result.health.incomplete == 1
        assert result.health.misplaced_held_seconds == 0

    async def test_a_counter_inconsistent_trace_can_be_misplaced(self) -> None:
        """The contrast that shows the line is the population and not the state.

        A counter-inconsistent trace *is* in the ruling population, so §7's clause
        reaches it — which is why the rule above is about membership rather than
        about being defect-free.
        """
        result = await figures(
            notification(when=at(days=1), seam=RECONSIDER, metrics=ruled(INTERRUPT, duplicate=1))
        )
        assert result.health.counter_inconsistent == 1
        assert result.health.misplaced_held_seconds == 1


class TestExtremeLatencies:
    """§4 puts no ceiling on ``held_seconds``, and a report must survive the ceiling.

    ADR-0119 §3 constrains a metric value to a finite number and stops there, so an
    ``int`` too large for a ``float`` and a ``float`` near the maximum are both
    values the type admits, the store hydrates and §4 calls **admissible** — they
    belong in the distribution rather than in the misplaced count. Neither may abort
    the walk, on :meth:`Rate.value`'s existing disposition for the same hazard: "a
    value that is data, not a bug in this walk". Adversarial review found both on the
    first round.
    """

    async def test_an_integer_too_large_for_a_float_is_admitted_and_stated(self) -> None:
        """``math.isfinite`` answers by converting, so asking it about this raises."""
        result = await figures(
            notification(
                when=at(days=1),
                seam=RECONSIDER,
                metrics=ruled(INTERRUPT) | {HELD_SECONDS: 10**400},
            )
        )
        assert result.health.misplaced_held_seconds == 0
        assert result.held_latency.count == 1
        assert "n=1" in result.held_latency.rendered()
        assert "too large to state as a decimal" in result.held_latency.rendered()

    async def test_near_maximum_floats_do_not_overflow_the_mean(self) -> None:
        """``fmean`` raises "intermediate overflow in fsum" summing these."""
        result = await figures(
            *(
                notification(
                    when=at(days=day),
                    seam=RECONSIDER,
                    metrics=ruled(INTERRUPT) | {HELD_SECONDS: 1.7e308},
                )
                for day in (1, 2)
            )
        )
        assert result.held_latency.count == 2
        assert result.held_latency.mean is None
        assert result.held_latency.minimum == 1.7e308

    async def test_an_unrepresentable_figure_is_not_an_empty_sample(self) -> None:
        """The count is the emptiness signal, so the two cannot be confused."""
        result = await figures(
            notification(
                when=at(days=1),
                seam=RECONSIDER,
                metrics=ruled(INTERRUPT) | {HELD_SECONDS: 10**400},
            )
        )
        assert result.held_latency.rendered() != "no observations"

    async def test_the_whole_report_still_renders(self) -> None:
        """The blocker's actual shape: one admissible value aborting every figure."""
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore(
                (
                    anchor,
                    notification(
                        when=at(days=1),
                        seam=RECONSIDER,
                        metrics=ruled(INTERRUPT) | {HELD_SECONDS: 10**400},
                    ),
                )
            ),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert report.notifications is not None
        assert report.notifications.interruption.value == 1.0
        assert "interruption share" in report.render()


class TestWindow:
    """§8 — ADR-0120's window rules, and the settling that does not apply."""

    async def test_no_figure_is_withheld_for_want_of_a_settling_period(self) -> None:
        """§8: "no figure defined here is withheld… The window is the one the
        operator asked for, whatever its end."

        The same stream withholds ADR-0120 §4's memory precision, which is the
        contrast: "a ruling's numerator is the ruling itself".
        """
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore((anchor, notification(when=at(days=1), metrics=ruled(INTERRUPT)))),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert report.whole is not None
        assert not report.whole.user.settled
        assert "withheld" in report.whole.user.rendered_precision()
        assert report.notifications is not None
        assert report.notifications.interruption.value == 1.0

    async def test_a_configuration_change_partitions_the_figures(self) -> None:
        """§8, and §10 is what makes the boundary reachable at all.

        The notification chassis's cap, retention and reconsideration interval
        "join ``service/configuration.py``'s ``_allowlisted``" — without which "two
        startups differing only in the cap emit identical ``CONFIGURATION`` metric
        mappings, no boundary is created", and one figure would be stated across
        rulings made under different caps.
        """
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore(
                (
                    anchor,
                    configuration(when=at(days=1), metrics={"notification_queue_limit": 50}),
                    notification(when=at(days=2), metrics=ruled(INTERRUPT)),
                    configuration(when=at(days=5), metrics={"notification_queue_limit": 200}),
                    notification(when=at(days=6), metrics=ruled(HOLD)),
                    notification(when=at(days=7), metrics=ruled(HOLD)),
                )
            ),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert report.notifications is not None
        assert report.notifications.interruption.denominator == 3
        assert len(report.notification_parts) == 2
        first, second = report.notification_parts
        assert first.interruption.numerator == 1
        assert first.interruption.denominator == 1
        assert second.interruption.numerator == 0
        assert second.interruption.denominator == 2
        # The parts are a partition: every population is a disjoint union of them.
        assert first.health.walked + second.health.walked == report.notifications.health.walked

    async def test_an_unpartitioned_window_states_no_parts(self) -> None:
        result = await figures(notification(when=at(days=1), metrics=ruled(HOLD)))
        assert result.start == START
        assert result.end == END

    async def test_an_empty_stream_states_no_notification_figure(self) -> None:
        report = await compute(FakeTraceStore(()), start=START, end=END, settling=SETTLING)
        assert report.notifications is None
        assert "empty" in report.render()

    async def test_a_refused_window_states_no_notification_figure(self) -> None:
        report = await compute(
            FakeTraceStore((notification(when=at(days=1), metrics=ruled(HOLD)),)),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert report.refusal is not None
        assert report.notifications is None


class TestReport:
    """§9's limit, and §10's content rule over the page an operator reads."""

    async def test_the_page_states_that_no_figure_is_evidence_of_welcome(self) -> None:
        """§9's second normative clause."""
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore((anchor, notification(when=at(days=1), metrics=ruled(INTERRUPT)))),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert "welcome" in report.render()

    async def test_the_page_carries_every_figure_and_no_identifier(self) -> None:
        """§10's content rule, as ADR-0120 §10 states it: counts, rates, instants,
        seam labels and metric keys, and no id of any kind."""
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore(
                (
                    anchor,
                    notification(
                        when=at(days=1),
                        seam=RECONSIDER,
                        correlation="secret-correlation",
                        metrics=ruled(INTERRUPT) | {HELD_SECONDS: 12.0},
                    ),
                    notification(when=at(days=2), metrics=ruled(HOLD, duplicate=1)),
                )
            ),
            start=START,
            end=END,
            settling=SETTLING,
        )
        page = report.render()
        assert "secret-correlation" not in page
        for line in (
            "interruption share (§6)",
            "duplicate share (§6)",
            "disposition mix (§7)",
            "held-first share (§7)",
            "held-to-interruption, s",
            "condition incidence (§7)",
            "notification traces walked",
        ):
            assert line in page, line
        for key in NOTIFICATION_CONDITION_KEYS.values():
            assert key in page, key

    async def test_the_notification_kind_reaches_the_stream_health_counts(self) -> None:
        """ADR-0141's Consequences: "every consumer that switches on the enumeration
        acquires a case", and this walk is one of the two."""
        anchor = operation("start", when=START, correlation="boot")
        report = await compute(
            FakeTraceStore((anchor, notification(when=at(days=1), metrics=ruled(HOLD)))),
            start=START,
            end=END,
            settling=SETTLING,
        )
        assert report.health is not None
        assert report.health.by_kind[TraceKind.NOTIFICATION] == 1
        # And it entered none of ADR-0120's own exclusion counts.
        assert report.health.malformed == 0
        assert report.health.unattributed == 0
