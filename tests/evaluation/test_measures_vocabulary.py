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

import ast
from pathlib import Path

from ai_assistant import evaluation
from ai_assistant.core.types import DROP_CONDITIONS, INTERRUPT_CONDITIONS, NotificationCondition
from ai_assistant.evaluation import _vocabulary as vocabulary
from ai_assistant.memory import notification_traces as ruling_emitter
from ai_assistant.memory import traces as emitters
from ai_assistant.orchestration.engine import Engine

#: The two seams ADR-0285 §2 removed from the engine and §7 from the sets.
_RETIRED_OBSERVATION_SEAMS = frozenset({"observe", "observe_due"})

#: ``learn``, which ADR-0293 §11 retires from the engine and which stays on both of
#: ADR-0120 §3's sets: no decision has reclassified the traces a store already holds
#: under it, as ADR-0285 §7 reclassified the observation seams', so they keep counting
#: where they always did. No operation emits it again.
_RETIRED_BUT_CLASSIFIED = frozenset({"learn"})


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
        """``Engine._tracked`` labels each trace with the public method's own name.

        Less the retired seam that keeps its classification, which is named so that it
        is asserted retired rather than passed over.
        """
        for seam in (vocabulary.USER_SEAMS | vocabulary.MACHINE_SEAMS) - _RETIRED_BUT_CLASSIFIED:
            assert hasattr(Engine, seam), seam
        for seam in _RETIRED_BUT_CLASSIFIED:
            assert not hasattr(Engine, seam), seam
            assert seam in vocabulary.USER_SEAMS, seam

    def test_the_two_sets_are_disjoint(self) -> None:
        """A seam on both lists would put one write in two causes."""
        assert not vocabulary.USER_SEAMS & vocabulary.MACHINE_SEAMS

    def test_the_direct_set_is_a_subset_of_the_user_set(self) -> None:
        """§3 says so in as many words, and §6's population depends on it."""
        assert vocabulary.DIRECT_SEAMS < vocabulary.USER_SEAMS

    def test_neither_observation_seam_is_on_any_set(self) -> None:
        """ADR-0285 §7:1: ``observe`` and ``observe_due`` leave the seam sets."""
        for seam in _RETIRED_OBSERVATION_SEAMS:
            assert seam not in vocabulary.USER_SEAMS, seam
            assert seam not in vocabulary.MACHINE_SEAMS, seam
            assert seam not in vocabulary.DIRECT_SEAMS, seam

    def test_no_evaluation_module_names_either_observation_seam(self) -> None:
        """ADR-0285 §7:2's last clause: "No reader special-cases either name."

        Checked over every string literal of every module in the package, because a
        special case needs the name as a value to compare a seam against — and a
        comparison against a constant defined elsewhere would need the constant
        here too. Prose naming the seams (a docstring that says why they are gone)
        is a literal that is never *equal* to either name, so it passes.
        """
        package = Path(evaluation.__file__).parent
        modules = sorted(package.rglob("*.py"))
        assert modules
        for module in modules:
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            literals = {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            assert not literals & _RETIRED_OBSERVATION_SEAMS, module.name


class TestNotificationLiterals:
    """ADR-0141 §10's last clause: the restated literals against the emitter's own.

    "``evaluation`` may import only ``core``, so the emitter's keys are duplicated by
    construction and the test is what keeps the two copies honest." A rename on
    either side has to fail here — a measure over a key nobody writes is *undefined*
    or zero, which reads like a quiet chassis rather than like a broken instrument.
    """

    def test_the_two_ruling_seams_match(self) -> None:
        assert vocabulary.NOTIFICATION_ADMIT_SEAM == ruling_emitter.SEAM_ADMIT
        assert vocabulary.NOTIFICATION_RECONSIDER_SEAM == ruling_emitter.SEAM_RECONSIDER

    def test_the_three_disposition_keys_are_exactly_the_emitters(self) -> None:
        """Keyed by member, so a key bound to the wrong disposition fails too."""
        assert vocabulary.NOTIFICATION_DISPOSITION_KEYS == ruling_emitter.DISPOSITION_METRICS

    def test_the_eight_condition_keys_are_exactly_the_emitters(self) -> None:
        assert vocabulary.NOTIFICATION_CONDITION_KEYS == ruling_emitter.CONDITION_METRICS

    def test_the_condition_roster_is_total_over_the_enumeration(self) -> None:
        """§4 defines a key per member, so a member added later must fail loudly."""
        assert set(vocabulary.NOTIFICATION_CONDITION_KEYS) == set(NotificationCondition)

    def test_held_seconds_matches_and_is_not_read_as_a_count(self) -> None:
        """§4: ``held_seconds`` "is **not** a count and the clause above does not reach it"."""
        assert vocabulary.HELD_SECONDS == ruling_emitter.HELD_SECONDS
        assert vocabulary.HELD_SECONDS not in vocabulary.NOTIFICATION_COUNT_KEYS
        assert vocabulary.HELD_SECONDS in vocabulary.NOTIFICATION_METRIC_KEYS

    def test_the_two_condition_halves_are_cores_own_groups_in_order(self) -> None:
        """§4 states the split over ``DROP_CONDITIONS`` and ``INTERRUPT_CONDITIONS``."""
        keys = vocabulary.NOTIFICATION_CONDITION_KEYS
        assert tuple(keys[c] for c in DROP_CONDITIONS) == vocabulary.DROP_CONDITION_KEYS
        assert tuple(keys[c] for c in INTERRUPT_CONDITIONS) == vocabulary.INTERRUPT_CONDITION_KEYS
        assert not set(vocabulary.DROP_CONDITION_KEYS) & set(vocabulary.INTERRUPT_CONDITION_KEYS)

    def test_the_count_keys_are_the_eleven_and_the_metric_keys_the_twelve(self) -> None:
        """§5's two rosters: the count rule reads eleven, *incomplete* reads twelve."""
        assert len(vocabulary.NOTIFICATION_COUNT_KEYS) == 11
        assert len(set(vocabulary.NOTIFICATION_METRIC_KEYS)) == 12

    def test_no_notification_key_collides_with_a_memory_key(self) -> None:
        """The two rosters are disjoint, which is what lets one walk classify both."""
        assert not set(vocabulary.NOTIFICATION_METRIC_KEYS) & set(vocabulary.COUNT_KEYS)
