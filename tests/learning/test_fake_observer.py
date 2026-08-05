"""The canonical FakeObserver passes the shared Observer suite (ADR-0077).

This is what lets other subsystems trust ``ai_assistant.testing.FakeObserver`` as
a stand-in for a real producer: it is held to the same contract as
``ModelBackedObserver`` (see ``test_observer.py``).

Below the binding are the behaviours specific to the fake — its scripting, its
refusals at construction, and the degradation report a consumer needs — none of
which are contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from observer_contract import GatedObservation, ObserverContract, batch_of, episode

from ai_assistant.core.types import MemoryKind, MemorySource
from ai_assistant.testing import FakeObserver, ObservationGate, ObservedBelief

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import Observer

_MAX_PROPOSALS = 4
_MAX_BATCH = 6


class TestFakeObserverContract(ObserverContract):
    """Runs FakeObserver through the shared Observer conformance suite."""

    @pytest.fixture
    def observer(self) -> Observer:
        return FakeObserver(max_batch_size=_MAX_BATCH, max_proposals=_MAX_PROPOSALS)

    @pytest.fixture
    def max_proposals(self) -> int:
        return _MAX_PROPOSALS

    @pytest.fixture
    def max_batch_size(self) -> int:
        return _MAX_BATCH

    def gated_observation(self) -> GatedObservation:
        gate = ObservationGate()
        return GatedObservation(
            observer=FakeObserver(gate=gate),
            episodes=batch_of(2),
            gate=gate,
        )

    def observation_asked_to_state_a_subject(self) -> Observer:
        """One template naming a subject and nothing else, so the refusal *is* the outcome."""
        return FakeObserver([ObservedBelief(content="prefers a window seat", about_person="Marta")])


# --- behaviour specific to FakeObserver, beyond the shared contract ---------


async def test_the_default_script_uses_both_epistemic_steps() -> None:
    """A suite run against this fake must not pass the INFERRED clause vacuously."""
    outcome = await FakeObserver().observe(batch_of(3))

    steps = {p.proposed.provenance.source for p in outcome.proposals}
    assert steps == {MemorySource.OBSERVED, MemorySource.INFERRED}


async def test_an_empty_script_proposes_nothing_and_is_not_a_degradation() -> None:
    """The explicit "this observer proposes nothing", distinct from the default."""
    outcome = await FakeObserver([]).observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 0
    assert outcome.discarded_over_limit == 0


async def test_a_scripted_belief_cites_the_batch_it_was_actually_handed() -> None:
    """The consumer scripts the belief; the fake supplies the producer's ids."""
    episodes = batch_of(3)

    outcome = await FakeObserver(
        [ObservedBelief(content="prefers concise replies", start=1)]
    ).observe(episodes)

    (proposal,) = outcome.proposals
    assert proposal.proposed.content == "prefers concise replies"
    assert proposal.proposed.provenance.evidence == ("e1",)


async def test_a_belief_the_batch_cannot_support_is_discarded_and_counted() -> None:
    """The evidence floor, from the inside: an unsupportable belief is not repaired."""
    outcome = await FakeObserver(
        [ObservedBelief(content="a broad generalisation", step=MemorySource.INFERRED, supports=2)]
    ).observe(batch_of(1))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_a_subject_stating_template_is_dropped_without_taking_the_pass_with_it() -> None:
    """One refusal degrades the pass; it does not fail it (ADR-0077 §4, ADR-0100 §5).

    The suite's clause scripts the refusal alone, so it can say the outcome *is*
    the refusal. This is the mixed case it cannot express: the belief stating a
    subject is discarded and counted, and the one beside it is proposed
    untouched. Losing the whole pass over one unusable entry would throw away the
    proposals that were fine, which is the degradation posture ADR-0077 §4 takes
    of a malformed model response, reached here through a different door.
    """
    outcome = await FakeObserver(
        [
            ObservedBelief(content="prefers a window seat", about_person="Marta"),
            ObservedBelief(content="the user prefers concise replies"),
        ]
    ).observe(batch_of(2))

    (proposal,) = outcome.proposals
    assert proposal.proposed.content == "the user prefers concise replies"
    assert proposal.proposed.about_person is None
    assert outcome.discarded_unusable == 1
    assert outcome.discarded_over_limit == 0


async def test_a_subject_stating_template_is_refused_whatever_the_evidence() -> None:
    """The subject refusal is not an evidence failure wearing its clothes.

    Scripted with support the batch amply covers, so the only reason to discard
    it is the subject — which is what makes the fake's ordering observable rather
    than incidental, and stops the clause passing because of a floor it never
    reached.
    """
    outcome = await FakeObserver(
        [ObservedBelief(content="prefers a window seat", supports=1, about_person="Marta")]
    ).observe(batch_of(4))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_scripted_unusable_discards_reach_the_outcome() -> None:
    """A consumer can drive its own degradation path without a model provider."""
    outcome = await FakeObserver(discarded_unusable=2).observe(batch_of(1))

    assert outcome.discarded_unusable == 2
    assert outcome.proposals


async def test_a_scripted_discard_cannot_make_an_empty_batch_report_degradation() -> None:
    """Nothing to observe means nothing was thrown away, whatever the script says."""
    outcome = await FakeObserver(discarded_unusable=3).observe([])

    assert outcome.discarded_unusable == 0


async def test_surplus_usable_beliefs_are_dropped_to_the_bound_and_counted() -> None:
    beliefs = [ObservedBelief(content=f"belief {index}") for index in range(5)]

    outcome = await FakeObserver(beliefs, max_proposals=2).observe(batch_of(1))

    assert len(outcome.proposals) == 2
    assert outcome.discarded_over_limit == 3
    assert outcome.discarded_unusable == 0


async def test_re_observing_one_batch_proposes_the_same_record_id() -> None:
    """What a consumer testing a ``REINFORCE`` fold depends on (ADR-0077 §8)."""
    observer = FakeObserver([ObservedBelief(content="prefers concise replies")])
    episodes = batch_of(2)

    first = await observer.observe(episodes)
    second = await observer.observe(episodes)

    assert first.proposals[0].proposed.id == second.proposals[0].proposed.id
    assert (
        first.proposals[0].proposed.provenance.confidence
        == second.proposals[0].proposed.provenance.confidence
    )


async def test_every_batch_is_recorded_as_an_independent_snapshot() -> None:
    observer = FakeObserver()
    episodes = batch_of(2)

    await observer.observe(episodes)
    episodes.clear()

    assert observer.call_count == 1
    assert [record.id for record in observer.batches[0]] == ["e0", "e1"]


def test_a_template_proposing_an_episode_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="EPISODIC"):
        ObservedBelief(content="something happened", kind=MemoryKind.EPISODIC)


def test_a_template_claiming_the_users_own_word_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="OBSERVED or INFERRED"):
        ObservedBelief(content="the user said so", step=MemorySource.USER_ASSERTED)


def test_an_inferred_template_on_one_support_is_refused_at_construction() -> None:
    """The fake must not be configurable into breaking its own contract."""
    with pytest.raises(ValueError, match="distinct supports"):
        ObservedBelief(content="a leap", step=MemorySource.INFERRED, supports=1)


#: The two bounds, each as a one-argument builder, so a case can drive either
#: without a ``**kwargs`` dict mypy cannot check against the real signature.
_BOUNDS: Final[list[Callable[[int], FakeObserver]]] = [
    lambda value: FakeObserver(max_batch_size=value),
    lambda value: FakeObserver(max_proposals=value),
]
_BOUND_IDS: Final = ["max_batch_size", "max_proposals"]


@pytest.mark.parametrize("build", _BOUNDS, ids=_BOUND_IDS)
def test_a_non_positive_bound_is_refused_at_construction(
    build: Callable[[int], FakeObserver],
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        build(0)


@pytest.mark.parametrize("build", _BOUNDS, ids=_BOUND_IDS)
def test_a_boolean_bound_is_refused_at_construction(
    build: Callable[[int], FakeObserver],
) -> None:
    """``True`` is an ``int`` in Python, and a bound of 1 by accident is a bug."""
    with pytest.raises(TypeError, match="must be an integer"):
        build(True)


def test_a_negative_scripted_discard_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        FakeObserver(discarded_unusable=-1)


async def test_a_repeated_episode_is_refused_before_the_batch_is_recorded() -> None:
    """A refused call is inert: it records nothing and reaches no gate."""
    observer = FakeObserver()
    repeated = episode("e0")

    with pytest.raises(ValueError, match="a batch is a set"):
        await observer.observe([repeated, repeated])

    assert observer.call_count == 0
