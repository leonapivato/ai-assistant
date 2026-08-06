"""Shared conformance suite for the Observer Protocol (ADR-0077).

Every ``Observer`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`ObserverContract` and
overrides the ``observer`` fixture, the two bound fixtures, and
:meth:`ObserverContract.gated_observation`.

**What is in here, and what deliberately is not.** The suite encodes the clauses
that bind *every* observer — the ones expressible without a model. What a given
batch justifies believing is each implementation's judgement and cannot be
asserted generically; ADR-0077 §9.3 is explicit that the counting rules of §4
("proposals plus both counts equal the entries the model emitted", the
validate-then-cap order, an out-of-batch citation label, an undecodable envelope)
are **not** suite clauses, because each is a statement about a *model response*,
which a conforming observer need not have — the canonical fake has none. The
whole confidence *ladder* is likewise the model-backed implementation's, for the
same reason: only a scripted response holds the function's inputs still, and a
suite asserting "the same batch twice yields the same confidence" would fail a
conforming observer that legitimately proposed a different belief the second
time. What is universal about confidence — that it is below 1.0 and that it is a
*function* of the step and the support count within one outcome — is here.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.protocols import Observer
from ai_assistant.core.types import (
    BeliefBand,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    ObservationOutcome,
    Provenance,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.testing import ObservationGate

_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: The confidence only the user's own word carries (ADR-0072 §3). A derived
#: belief may never reach it, and ``Provenance`` now enforces that — but an
#: observer returning one would be a contract violation this suite must name in
#: its own terms rather than leave to a pydantic error somewhere upstream.
_FULL_CONFIDENCE: Final = 1.0

#: What a failure of the input-observation case means, in one place (ADR-0065):
#: ``observe`` derived its outcome from more than one observation of the caller's
#: batch, so the citations it returned describe no single version of the input.
_TORN_BATCH: Final = (
    "observe derived its outcome from more than one observation of its batch: a "
    "caller's mid-flight mutation reached the citations of some proposals and not "
    "others, so no single version of the episodes describes the result"
)


def episode(
    episode_id: str, *, content: str | None = None, occurred_at: datetime | None = None
) -> EpisodicMemory:
    """One well-formed episode for a batch, with a documented sub-1.0 confidence.

    Exported rather than private: an implementation's own tests build batches for
    the same subject and must not re-derive what a capture-shaped episode looks
    like (ADR-0074 §4's derived-band obligation included).

    ``occurred_at`` defaults to the shared instant every other case wants held
    still, and is a parameter for the one that cannot: a ``DERIVED`` belief's
    confirming instant is the **latest** ``occurred_at`` among the episodes cited
    (ADR-0103 §9, ADR-0109 §4), which no batch of identically-dated episodes can
    tell apart from the first, the last, or an arbitrary one.
    """
    return EpisodicMemory(
        id=episode_id,
        content=content if content is not None else f"the user said something in {episode_id}",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=_WHEN,
        ),
        occurred_at=occurred_at if occurred_at is not None else _WHEN,
    )


def batch_of(size: int, *, prefix: str = "e") -> list[EpisodicMemory]:
    """A batch of ``size`` distinct episodes, as a **list** the caller still owns."""
    return [episode(f"{prefix}{index}") for index in range(size)]


@dataclass(frozen=True)
class GatedObservation:
    """One ``observe`` call an implementation can be held inside, plus its levers.

    What ADR-0065's and ADR-0060's cases need from an implementation, and no more.
    Neither property has a positive signal through ``observe`` alone: a suite has
    to hold the call open *after* it has taken its one observation of the batch,
    and only the implementation knows where its first ``await`` is — inside a
    model provider for a model-backed observer, on a gate for a fake.

    ``episodes`` is deliberately the **caller's own list**, not a copy: the
    input-observation case mutates it in place while the call is suspended, which
    is the whole stimulus.

    Attributes:
        observer: The subject, ready to be called.
        episodes: The mutable batch to hand it. Must hold at least one episode,
            so a case asserting on the citations is not vacuous.
        gate: Waits until the call is suspended, and lets it go again.
    """

    observer: Observer
    episodes: list[EpisodicMemory]
    gate: ObservationGate


def _cited(outcome: ObservationOutcome) -> set[str]:
    """Every episode id cited by any proposal in ``outcome``."""
    return {
        evidence
        for proposal in outcome.proposals
        for evidence in proposal.proposed.provenance.evidence
    }


class ObserverContract:
    """Behaviour every ``Observer`` implementation must exhibit (ADR-0077)."""

    @pytest.fixture
    def observer(self) -> Observer:
        """Override in a subclass to supply the implementation under test.

        The subject must be one that *tries* to propose as much as the batch
        justifies. Several clauses below are about a bound biting, and an
        implementation configured to propose nothing would pass them having
        exercised nothing.
        """
        raise NotImplementedError

    @pytest.fixture
    def max_proposals(self) -> int:
        """Override with the maximum number of proposals ``observer`` may return."""
        raise NotImplementedError

    @pytest.fixture
    def max_batch_size(self) -> int:
        """Override with the largest batch ``observer`` accepts."""
        raise NotImplementedError

    def gated_observation(self) -> GatedObservation:
        """Override with a subject that can be held at its first ``await``.

        Called once per case that needs it, so each gets a fresh gate and a fresh
        subject. See :class:`GatedObservation`.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, observer: Observer) -> None:
        assert isinstance(observer, Observer)

    # --- what may be proposed (ADR-0077 §2) ---------------------------------

    async def test_every_proposal_is_in_the_derived_band(self, observer: Observer) -> None:
        """An observer works beliefs out; it never speaks for the user (ADR-0072 §2)."""
        outcome = await observer.observe(batch_of(2))

        assert outcome.proposals, "the subject proposed nothing, so this clause is vacuous"
        for proposal in outcome.proposals:
            source = proposal.proposed.provenance.source
            assert band_of(source) is BeliefBand.DERIVED, source

    async def test_no_proposal_is_an_episodic_record(self, observer: Observer) -> None:
        """Only the capture path that witnessed an event may write one (ADR-0074 §3)."""
        outcome = await observer.observe(batch_of(3))

        assert outcome.proposals
        assert all(
            proposal.proposed.kind != MemoryKind.EPISODIC.value for proposal in outcome.proposals
        )

    # --- the subject axis (ADR-0100 §5) -------------------------------------

    async def test_no_proposal_states_a_subject(self, observer: Observer) -> None:
        """An observer proposes only about the user, so it never names a subject.

        The clause ADR-0100 §5 puts in this suite rather than in one
        implementation: an observer's proposal leaves ``about_person`` unset, and
        one that would state it is not proposed at all. It adds no obligation —
        a belief warranted only when it is *about the user* (ADR-0077 §2) has no
        non-owner subject to state — but until the field existed there was nowhere
        for the obligation to be *seen*, so the bar could only be asserted in
        prose and requested in a prompt.

        **The batch is the provocation, not a neutral one.** Every episode names a
        third party, so an implementation that reached for the obvious shortcut —
        reading a name out of content and calling it the subject — fails here.
        That is ADR-0100 §4's no-inference rule arriving through §5: a subject is
        stated only from a subject actually received, and a name in a sentence is
        scenery until someone says otherwise.

        **It binds nothing about the shipped observer and everything about the
        next one.** ``ModelBackedObserver`` builds every record itself from an
        envelope whose schema has no subject key, so it *cannot* state one however
        the model answers; the second ``Observer`` implementation is the one this
        corpus cannot inspect, and this is where it fails closed.
        """
        episodes = [
            episode("e0", content="Marta said she prefers a window seat"),
            episode("e1", content="the user booked Marta an aisle seat by mistake"),
            episode("e2", content="the user asked what Marta usually chooses"),
        ]

        outcome = await observer.observe(episodes)

        assert outcome.proposals, "the subject proposed nothing, so this clause is vacuous"
        for proposal in outcome.proposals:
            stated = proposal.proposed.about_person
            assert stated is None, (
                f"an observer proposal states no subject, and this one states {stated!r}: "
                "a proposal that would is not proposed at all, and is counted in "
                "discarded_unusable (ADR-0100 §5)"
            )

    #: Whether this implementation **cannot be asked** to propose a stated
    #: subject at all — no input it accepts can express one, so the state the
    #: clause below observes is unreachable rather than merely unreached.
    #: ``ModelBackedObserver`` is that case and says why: ADR-0100 §5 records that
    #: it "builds every record itself from a fixed JSON envelope whose schema has
    #: no subject key, so the shipped observer *cannot* state one however the
    #: model answers".
    #:
    #: Left ``False``, the suite requires the implementation to **prove** the
    #: counting half by overriding :meth:`observation_asked_to_state_a_subject` —
    #: the direction §5 wants the default to run in, since the clause exists to
    #: fail closed against the next implementation rather than to describe this
    #: one.
    states_no_subject_by_construction: bool = False

    def observation_asked_to_state_a_subject(self) -> Observer:
        """Override with a subject that has been *asked* for a stated subject.

        The returned observer must, when handed a two-episode batch, be scripted
        so that it would propose **exactly one** belief and that belief states a
        subject. Only the implementation knows how to ask — a template field on a
        fake, an envelope key on a model-backed producer — which is why this is a
        hook rather than a fixture the suite could build, exactly as
        :meth:`gated_observation` is.

        Not needed where :attr:`states_no_subject_by_construction` is ``True``.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_proposal_that_would_state_a_subject_is_refused_and_counted(self) -> None:
        """Refused **and counted** — the second half of ADR-0100 §5's clause.

        The case above pins that no proposal states a subject, and an
        implementation could satisfy it by silently swallowing such a candidate:
        it would return its other proposals, leave ``discarded_unusable``
        untouched, and report a clean pass over work it had quietly dropped. That
        is the shape ADR-0022 §3 exists to prevent — a degradation reported as a
        normal outcome — and the count is the only thing that distinguishes them.

        **Refused, never repaired.** Stripping the subject and proposing the
        belief anyway is the failure that looks most like success: ADR-0100 §3
        reads an unstated subject as *the owner's*, so a stripped proposal is not
        a neutral one, it is a belief about someone else asserted about the owner.
        Hence both assertions — nothing proposed, and something counted.

        Skippable only where the implementation cannot be asked at all
        (:attr:`states_no_subject_by_construction`), which is a statement about
        the input surface rather than an exemption from the obligation.
        """
        if self.states_no_subject_by_construction:
            pytest.skip("implementation cannot be asked to state a subject at all")

        outcome = await self.observation_asked_to_state_a_subject().observe(batch_of(2))

        assert outcome.proposals == (), "the belief that stated a subject was proposed anyway"
        assert outcome.discarded_unusable >= 1, (
            "the refused proposal was dropped without being counted, so the outcome "
            "is indistinguishable from an observer that honestly proposed nothing"
        )

    # --- evidence discipline (ADR-0077 §5) ----------------------------------

    async def test_every_proposal_cites_only_episodes_from_the_batch(
        self, observer: Observer
    ) -> None:
        """The ids are the producer's, never a model's.

        A model that can write an id can write one for an episode it never saw,
        and the provenance display would then confidently cite a record with
        nothing to do with the belief. Both halves are asserted: at least one
        citation each, and nothing from outside the batch.
        """
        episodes = batch_of(3)
        given = {record.id for record in episodes}

        outcome = await observer.observe(episodes)

        assert outcome.proposals
        for proposal in outcome.proposals:
            evidence = set(proposal.proposed.provenance.evidence)
            assert evidence, "a DERIVED proposal cites at least one evidence reference"
            assert evidence <= given, f"cited outside the batch: {sorted(evidence - given)}"

    async def test_an_inferred_proposal_cites_at_least_two_distinct_episodes(
        self, observer: Observer
    ) -> None:
        """A generalisation from one instance is the failure the floor exists for.

        Counted over **distinct** ids, never over citations: two references
        resolving to one episode are one support (ADR-0077 §5). The batch is large
        enough for the floor to be met, so an implementation that proposes an
        ``INFERRED`` belief here is not being asked to break the rule to pass.
        """
        outcome = await observer.observe(batch_of(3))

        for proposal in outcome.proposals:
            if proposal.proposed.provenance.source is MemorySource.INFERRED:
                distinct = set(proposal.proposed.provenance.evidence)
                assert len(distinct) >= 2, f"INFERRED on {len(distinct)} distinct episode(s)"

    # --- confidence (ADR-0077 §5) -------------------------------------------

    async def test_confidence_is_strictly_below_full(self, observer: Observer) -> None:
        """1.0 is the standing only the user's own word carries (ADR-0072 §3)."""
        outcome = await observer.observe(batch_of(3))

        assert outcome.proposals
        for proposal in outcome.proposals:
            assert proposal.proposed.provenance.confidence < _FULL_CONFIDENCE

    async def test_equal_step_and_support_carry_equal_confidence(self, observer: Observer) -> None:
        """Confidence is a *function* of the step and the distinct-support count.

        Stated over proposals **in one outcome**, deliberately. Across two calls
        it would not be a contract at all: a conforming model-backed observer may
        legitimately return a different belief the second time — an ``OBSERVED``
        proposal citing one episode, then an ``INFERRED`` one citing two — and a
        suite asserting equality across calls would fail it for doing nothing
        wrong (ADR-0077 §9.3). What is fixed is the function, not the model.
        """
        outcome = await observer.observe(batch_of(4))

        by_input: dict[tuple[MemorySource, int], set[float]] = {}
        for proposal in outcome.proposals:
            provenance = proposal.proposed.provenance
            key = (provenance.source, len(set(provenance.evidence)))
            by_input.setdefault(key, set()).add(provenance.confidence)
        for key, values in by_input.items():
            assert len(values) == 1, f"{key} produced more than one confidence: {sorted(values)}"

    # --- the bounds, which are refusals rather than repairs (ADR-0077 §1, §2) --

    async def test_the_returned_proposal_count_never_exceeds_the_maximum(
        self, observer: Observer, max_proposals: int, max_batch_size: int
    ) -> None:
        """The bound is on the *return value*, so it holds whatever a model emits.

        The second assertion is what stops the first from passing vacuously: an
        implementation only drops a usable proposal to meet the bound when the
        bound is full, so a non-zero ``discarded_over_limit`` alongside fewer than
        ``max_proposals`` returned would mean something else was thrown away and
        mislabelled.
        """
        outcome = await observer.observe(batch_of(min(max_proposals, max_batch_size)))

        assert len(outcome.proposals) <= max_proposals
        if outcome.discarded_over_limit:
            assert len(outcome.proposals) == max_proposals

    async def test_an_oversized_batch_is_refused_rather_than_truncated(
        self, observer: Observer, max_batch_size: int
    ) -> None:
        """Truncating would disable half the work while the caller reported health.

        The episodes the caller believed were observed would never have been read.
        ADR-0073 §2's posture applied to a batch: out of range is a ``ValueError``,
        not a clamp.
        """
        with pytest.raises(ValueError, match=r"(?i)batch|maximum|exceed"):
            await observer.observe(batch_of(max_batch_size + 1))

    async def test_a_batch_repeating_an_episode_id_is_refused(self, observer: Observer) -> None:
        """A batch is a set, and a silent de-duplication would hide the caller's bug.

        Worse than hiding it: one episode cited under two labels would supply the
        two *distinct* supports an ``INFERRED`` belief owes, and would raise the
        confidence computed from that count (ADR-0077 §1).
        """
        repeated = episode("e0")

        with pytest.raises(ValueError, match=r"(?i)set|twice|repeat|duplicate|once"):
            await observer.observe([repeated, episode("e1"), repeated])

    async def test_both_discard_counts_are_non_negative(self, observer: Observer) -> None:
        outcome = await observer.observe(batch_of(2))

        assert outcome.discarded_unusable >= 0
        assert outcome.discarded_over_limit >= 0

    async def test_an_empty_batch_yields_no_proposals_and_no_discards(
        self, observer: Observer
    ) -> None:
        """Nothing to observe is not a degradation, and must not read as one."""
        outcome = await observer.observe([])

        assert outcome == ObservationOutcome()

    # --- input observation (ADR-0065) ---------------------------------------

    async def test_observe_cannot_tear_on_a_mid_flight_mutation_of_its_batch(self) -> None:
        """One call, one observation of the caller's list.

        ``Sequence[EpisodicMemory]`` is the case ADR-0065 is *for*: every episode
        in it is frozen (ADR-0068), but the container is the caller's and stays
        mutable, and the model call an observer makes is the widest suspension
        window in the system. A torn implementation renders the prompt from one
        version of the list and maps its citation labels back through another, so
        the beliefs it returns cite episodes that were never shown to the model.

        The gate is positioned at the implementation's **first await**, not at
        method entry (ADR-0065 §3): a hook at entry would let the mutation land
        before the one observation was taken, so a conforming subject would see a
        single coherent mutated version and a tear at the real window would
        survive.
        """
        gated = self.gated_observation()
        before = {record.id for record in gated.episodes}
        replacement = batch_of(len(gated.episodes), prefix="z")
        after = {record.id for record in replacement}
        assert before, "the stimulus needs a non-empty batch to replace"
        assert not before & after, "the replacement must share no id with the original"

        call = asyncio.ensure_future(gated.observer.observe(gated.episodes))
        try:
            await gated.gate.reached()
            gated.episodes[:] = replacement
        finally:
            gated.gate.release()
        outcome = await call

        cited = _cited(outcome)
        assert cited, "the subject cited nothing, so this case would pass vacuously"
        assert cited <= before or cited <= after, _TORN_BATCH

    # --- cancellation (ADR-0060) --------------------------------------------

    async def test_a_cancellation_is_delivered_onward_rather_than_absorbed(self) -> None:
        """A cancellation from outside is re-raised, never turned into a result.

        The resource half of ``core.protocols``' clause is vacuous here — nothing
        an observer acquires outlives the coroutine — but the propagation half is
        not, and it is the half an implementation can quietly get wrong: an
        observer that caught the cancellation and returned an empty
        :class:`~ai_assistant.core.types.ObservationOutcome` would report "nothing
        to learn" for work that never happened, which is exactly the silence
        ADR-0022 §3 exists to prevent.
        """
        gated = self.gated_observation()

        call = asyncio.ensure_future(gated.observer.observe(gated.episodes))
        try:
            await gated.gate.reached()
            call.cancel()
        finally:
            gated.gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call


def assert_conforms(outcome: ObservationOutcome, batch: Sequence[EpisodicMemory]) -> None:
    """Assert the batch-relative clauses of the contract on one outcome.

    The suite's own cases each assert one clause against a fixed batch, which is
    what makes a failure name the obligation it broke. An implementation's tests
    often want the whole set asserted over a batch *they* chose — a scripted
    response, a degradation path — without restating five loops, so the same
    checks are available here as one call.
    """
    given = {record.id for record in batch}
    for proposal in outcome.proposals:
        provenance = proposal.proposed.provenance
        assert band_of(provenance.source) is BeliefBand.DERIVED
        assert proposal.proposed.kind != MemoryKind.EPISODIC.value
        assert proposal.proposed.about_person is None
        assert provenance.confidence < _FULL_CONFIDENCE
        distinct = set(provenance.evidence)
        assert distinct
        assert distinct <= given
        if provenance.source is MemorySource.INFERRED:
            assert len(distinct) >= 2
    assert outcome.discarded_unusable >= 0
    assert outcome.discarded_over_limit >= 0
