"""The canonical FakeObserver passes the shared Observer suite (ADR-0077).

This is what lets other subsystems trust ``ai_assistant.testing.FakeObserver`` as
a stand-in for a real producer: it is held to the same contract as
``ModelBackedObserver`` (see ``test_observer.py``).

Below the binding are the behaviours specific to the fake — its scripting, its
refusals at construction, and the degradation report a consumer needs — none of
which are contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


#: Three instants for the case below, none of them the fake's own clock, so an
#: implementation reading `last_updated` would be visible (ADR-0109 §10).
_EARLY: Final = datetime(2025, 9, 3, tzinfo=UTC)
_LATEST: Final = datetime(2025, 12, 24, tzinfo=UTC)
_MIDDLE: Final = datetime(2025, 10, 17, tzinfo=UTC)


async def test_the_fake_takes_the_latest_occurred_at_over_the_window_it_cited() -> None:
    """ADR-0109 §4's ``DERIVED`` arm, in the canonical fake (ADR-0109 §10 item 4).

    The instant is the **latest** ``occurred_at`` among the episodes cited, taken
    over the same ``window`` this fake already slices to build its citations. The
    batch runs ``_MIDDLE, _LATEST, _EARLY`` and the citation window is its last
    two, which separates three wrong implementations with one assertion: the
    window's first entry is ``_LATEST`` but its last is ``_EARLY``, and a maximum
    taken over the whole *batch* would also have to survive the uncited head.

    Held to the same rule as ``ModelBackedObserver``, because a fake that diverged
    would make every consumer's test written against it a test of nothing
    (ADR-0026 §7) — the reason the fold's two copies are run over one table too.
    """
    episodes = [
        episode("e-head", occurred_at=_MIDDLE),
        episode("e-latest", occurred_at=_LATEST),
        episode("e-early", occurred_at=_EARLY),
    ]

    outcome = await FakeObserver(
        [ObservedBelief(content="prefers concise replies", start=1, supports=2)]
    ).observe(episodes)

    (proposal,) = outcome.proposals
    provenance = proposal.proposed.provenance
    assert provenance.evidence == ("e-latest", "e-early")
    assert provenance.last_confirmed_at == _LATEST
    assert provenance.last_confirmed_at != provenance.last_updated


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


async def test_re_observing_one_batch_proposes_a_fresh_id_and_the_same_confidence() -> None:
    """The fake **mints** like the producer it doubles (#736, ADR-0026 §7).

    This used to assert the opposite — a *stable* id across re-observations, "what a
    consumer testing a ``REINFORCE`` fold depends on". Both halves were wrong about
    ``ModelBackedObserver``, which takes an ``id_factory`` defaulting to ``uuid4``
    and calls it per proposal, and the fold that premise promised never happened:
    ``MemoryIngestor._detect_conflicts`` filters the proposal's own id (#110), so a
    repeat was never in its own conflict set. Since ADR-0159 it does not merely fail
    to fold — it is *refused*, because ADR-0108 §2 will not install at an id already
    stored.

    What a consumer testing a ``REINFORCE`` actually needs is the production shape:
    identical **content** at a fresh id, which ADR-0121 §1's predicate labels
    ``RESTATES`` and ADR-0159 §4(a) folds at the stored record's own id.

    **Confidence is still stable, and that is the half worth keeping.** ADR-0077 §5
    makes it pure in the step and the support count, which is what closes the
    repetition route to inflation: a second pass over one batch re-proposes the same
    number rather than a higher one.
    """
    observer = FakeObserver([ObservedBelief(content="prefers concise replies")])
    episodes = batch_of(2)

    first = await observer.observe(episodes)
    second = await observer.observe(episodes)

    assert first.proposals[0].proposed.id != second.proposals[0].proposed.id
    assert first.proposals[0].proposed.content == second.proposals[0].proposed.content
    assert (
        first.proposals[0].proposed.provenance.confidence
        == second.proposals[0].proposed.provenance.confidence
    )


async def test_a_scripted_record_id_still_names_the_record() -> None:
    """The mint is the *default*, not the only path (#736).

    A consumer that needs an exact id names it on the template, which is what the
    derivation was standing in for and what the collision cases now use to build
    ADR-0108 §2's own-id refusal deliberately rather than by accident.
    """
    observer = FakeObserver([ObservedBelief(content="a belief", record_id="pinned")])

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals[0].proposed.id == "pinned"


async def test_an_injected_factory_mints_every_proposals_id() -> None:
    """The seam ``ModelBackedObserver`` has, mirrored (ADR-0047 §2).

    A consumer that wants a deterministic *sequence* rather than one pinned id gets
    it the same way production does, so a test asserting exact ids does not have to
    reach for a derivation nobody else has.
    """
    minted = iter(["first", "second"])
    observer = FakeObserver(id_factory=lambda: next(minted))

    outcome = await observer.observe(batch_of(1))

    assert [proposal.proposed.id for proposal in outcome.proposals] == ["first"]


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


@pytest.mark.parametrize("minted", [None, 42], ids=["none", "an-int"])
async def test_a_malformed_minted_id_is_discarded_and_never_raised(minted: object) -> None:
    """The fake degrades exactly where ``ModelBackedObserver`` does (ADR-0026 §7).

    The producer evaluates its own ``id_factory`` inside the ``try`` that guards
    record construction and catches ``ValidationError``, so a factory returning a
    non-``str`` or a blank one costs **one unusable proposal** rather than a failed
    observation — "one bad belief in a batch is a degradation, not a failed
    observation" (ADR-0077 §4). A fake that raised instead would fail a consumer's
    test on an outcome production never produces.

    The failure mode is *new to this fake*: while it derived its ids from content
    there was no factory to get wrong. It arrived with the mint (#736), so its
    degradation arrives with it too.

    **Only the values a ``core`` invariant actually refuses are swept here**, which
    is a non-``str``. An *empty* or whitespace id is accepted by ``MemoryRecord`` and
    therefore by both observers alike — refusing it is the **writer's** job, where
    ``MemoryIngestor._checked_id`` guards the factory it owns, and a producer-side
    assertion here would pin a rule neither implementation carries.
    """
    observer = FakeObserver(
        [ObservedBelief(content="prefers concise replies")],
        id_factory=lambda: minted,  # type: ignore[arg-type, return-value]
    )

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_an_id_factory_that_raises_propagates_from_the_fake() -> None:
    """And the other half of the mirror: a *raising* factory is not swallowed.

    ``ModelBackedObserver`` catches ``ValidationError`` alone, so a factory that
    raises anything else propagates out of ``observe`` there — a broken collaborator
    is not a degraded belief. The fake matches, rather than being quietly more
    forgiving than the thing it doubles.
    """

    def explode() -> str:
        msg = "the id factory is broken"
        raise RuntimeError(msg)

    observer = FakeObserver([ObservedBelief(content="a belief")], id_factory=explode)

    with pytest.raises(RuntimeError, match="broken"):
        await observer.observe(batch_of(2))


# --- ADR-0213 §6: the fake proposes topics, and refuses a template it could
# only honour by breaking the contract ---------------------------------------


async def test_a_scripted_topic_reaches_the_proposed_record() -> None:
    """An observer *is* a producer that proposes topics (§6), so the fake honours them.

    Unlike ``about_person``, which §5 of ADR-0100 has the fake **discard and count**
    because an observer's proposal states no subject. The two templates are treated
    differently on purpose, and a consumer scripting a labelled belief is scripting
    something a real producer can emit.
    """
    observer = FakeObserver([ObservedBelief(content="a belief", topics=("health", "sleep"))])

    outcome = await observer.observe(batch_of(2))

    assert [proposal.proposed.topics for proposal in outcome.proposals] == [("health", "sleep")]


def test_a_template_carrying_no_topics_proposes_the_empty_tuple() -> None:
    """The default, which is what every producer but two writes (§6)."""
    assert ObservedBelief(content="a belief").topics == ()


@pytest.mark.parametrize(
    "topics",
    [
        pytest.param(("a", "b", "c", "d", "e"), id="past-the-proposal-bound"),
        pytest.param(("Health",), id="not-casefolded"),
        pytest.param(("health  care",), id="two-consecutive-spaces"),
        pytest.param(("sleep", "health"), id="unsorted"),
        pytest.param(("health", "health"), id="a-repeated-label"),
    ],
)
def test_a_template_the_producer_could_only_ignore_is_refused_at_construction(
    topics: tuple[str, ...],
) -> None:
    """Refused rather than silently emptied, and the shape of the refusal is the point.

    §4 rules that a topics entry a producer cannot use is **ignored** with no counter
    moving — so "the entry was ignored" is not an observable outcome, and a fake that
    quietly emptied a bad template would hide the mistake in the one place nothing
    can see it. ``EPISODIC``'s refusal has the same shape for the same reason;
    ``about_person``'s does not, because *there* the outcome is observable as a
    discard.
    """
    with pytest.raises(ValueError, match=r"topic|Value error"):
        ObservedBelief(content="a belief", topics=topics)
