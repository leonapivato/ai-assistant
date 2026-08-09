"""The literals ADR-0120's populations are keyed on, checked against the emitters.

``evaluation`` may import ``core`` and nothing else, so
:mod:`ai_assistant.evaluation._vocabulary` restates the emitters' metric keys and
seam labels rather than importing them. A duplicated string is only as good as
the check that it still matches, and this is that check: a test may import both
sides, because a test is not a subsystem.

A rename on either side fails here instead of silently emptying a population,
which is the failure mode the duplication would otherwise have — every rate would
still be computed, and every one of them would be *undefined* or zero, which
reads like a quiet system rather than like a broken instrument.
"""

from __future__ import annotations

from ai_assistant.evaluation import _vocabulary as vocabulary
from ai_assistant.memory import traces as emitters
from ai_assistant.orchestration.engine import Engine


class TestMetricKeys:
    """Each key this package reads is the key ``memory/traces.py`` writes."""

    def test_the_retrieval_counts_match(self) -> None:
        assert vocabulary.LIMIT == emitters.LIMIT
        assert vocabulary.FETCH_K == emitters.FETCH_K
        assert vocabulary.CANDIDATES == emitters.CANDIDATES
        assert vocabulary.RETURNED == emitters.RETURNED

    def test_the_four_exclusion_counters_match_and_are_the_whole_partition(self) -> None:
        assert vocabulary.EXCLUSION_KEYS == (
            emitters.EXCLUDED_KIND,
            emitters.EXCLUDED_RETENTION,
            emitters.EXCLUDED_WINDOW,
            emitters.EXCLUDED_BAND,
        )

    def test_the_six_decision_keys_are_exactly_the_emitters(self) -> None:
        """All six, because §2 reads them as a unit and a strict subset is malformed."""
        assert set(vocabulary.DECISION_KEYS) == set(emitters.DECISION_METRICS.values())
        assert len(vocabulary.DECISION_KEYS) == len(emitters.DECISION_METRICS)

    def test_the_two_named_decisions_are_members_of_the_six(self) -> None:
        assert vocabulary.DECISIONS_SUPERSEDE in vocabulary.DECISION_KEYS
        assert vocabulary.DECISIONS_REINFORCE in vocabulary.DECISION_KEYS

    def test_the_constrained_counts_are_the_decisions_and_the_retrieval_counts(self) -> None:
        """§2's integrality rule is stated over exactly the keys this ADR reads."""
        assert set(vocabulary.COUNT_KEYS) == set(vocabulary.DECISION_KEYS) | set(
            vocabulary.RETRIEVAL_COUNT_KEYS
        )


class TestSeamSets:
    """§3's two allowlists, and the subset relation the direct set stands in."""

    def test_every_named_seam_is_a_public_engine_operation(self) -> None:
        """``Engine._tracked`` labels each trace with the public method's own name."""
        for seam in vocabulary.USER_SEAMS | vocabulary.MACHINE_SEAMS:
            assert hasattr(Engine, seam), seam

    def test_the_two_sets_are_disjoint(self) -> None:
        """A seam on both lists would put one write in two causes."""
        assert not vocabulary.USER_SEAMS & vocabulary.MACHINE_SEAMS

    def test_the_direct_set_is_a_subset_of_the_user_set(self) -> None:
        """§3 says so in as many words, and §6's population depends on it."""
        assert vocabulary.DIRECT_SEAMS < vocabulary.USER_SEAMS

    def test_observe_is_a_user_seam_and_not_a_direct_one(self) -> None:
        """The content originates with the user; the act is the observation stage's."""
        assert vocabulary.OBSERVE_SEAM in vocabulary.USER_SEAMS
        assert vocabulary.OBSERVE_SEAM not in vocabulary.DIRECT_SEAMS
