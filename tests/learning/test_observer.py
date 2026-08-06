"""The model-backed observer: the contract, plus what only a scripted model can pin.

``ModelBackedObserver`` is run through the shared ``Observer`` suite first, so it
is held to the same contract as ``FakeObserver``. Everything below the binding is
what ADR-0077 §9.3 rules **cannot** be a suite clause: the counting rules of §4
and the whole confidence ladder of §5 are statements about a *model response*,
which a conforming observer need not have, and only a scripted response holds
their inputs still.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from observer_contract import (
    GatedObservation,
    ObserverContract,
    assert_conforms,
    batch_of,
    episode,
)

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import MemoryKind, Message, Role
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.testing import FakeModelProvider, ObservationGate

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import Observer

_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)
_MAX_PROPOSALS: Final = 4
_MAX_BATCH: Final = 6

#: The label the prompt assigns each episode, as the reply helpers read it back.
_LABEL: Final = re.compile(r"\[(E\d+)\]")


def _fixed_now() -> datetime:
    return _WHEN


def _belief(
    *,
    evidence: Sequence[str],
    step: str = "observed",
    kind: str = "semantic",
    content: str = "the user prefers concise replies",
    **extra: Any,
) -> dict[str, Any]:
    """One envelope entry."""
    return {
        "kind": kind,
        "step": step,
        "content": content,
        "evidence": list(evidence),
        "rationale": "the cited episodes show it",
        **extra,
    }


def _envelope(*beliefs: dict[str, Any]) -> str:
    return json.dumps({"beliefs": list(beliefs)})


def _observer(
    reply: str | Callable[[Sequence[Message]], str],
    *,
    max_proposals: int = _MAX_PROPOSALS,
    max_batch_size: int = _MAX_BATCH,
    now: Callable[[], datetime] = _fixed_now,
) -> tuple[ModelBackedObserver, FakeModelProvider]:
    """An observer over a scripted provider, and the provider, for assertions."""
    provider = FakeModelProvider(reply=reply)
    observer = ModelBackedObserver(
        provider,
        now=now,
        id_factory=_counting_ids(),
        max_proposals=max_proposals,
        max_batch_size=max_batch_size,
    )
    return observer, provider


def _counting_ids() -> Callable[[], str]:
    """Deterministic ids, so a test can assert exactly what was proposed."""
    counter = iter(range(1000))
    return lambda: f"belief-{next(counter)}"


def _eager_reply(messages: Sequence[Message]) -> str:
    """One ``OBSERVED`` belief per labelled episode, plus one ``INFERRED`` over two.

    Reads the labels back out of the prompt this observer built, so the reply
    scales with whatever batch the conformance suite hands the subject — and asks
    for one more belief than the batch has episodes, so a configured maximum at or
    below the batch size actually bites.
    """
    labels = _LABEL.findall(messages[-1].content)
    beliefs = [
        _belief(evidence=[label], content=f"a belief drawn from {label}") for label in labels
    ]
    if len(labels) >= 2:
        beliefs.append(
            _belief(evidence=labels[:2], step="inferred", content="a belief across the batch")
        )
    return _envelope(*beliefs)


class _GatedProvider:
    """A provider that suspends at the observer's first ``await``, then answers.

    The lever ADR-0065's and ADR-0060's conformance cases need for a model-backed
    subject: the first ``await`` in ``observe`` is the model call, so holding the
    call *inside* ``complete`` holds it exactly where the clause bites — after the
    batch has been observed once and the prompt built from it.
    """

    def __init__(self, gate: ObservationGate) -> None:
        self._gate = gate

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Suspend on the gate, then answer from the prompt as handed."""
        await self._gate.hold()
        return Message(role=Role.ASSISTANT, content=_eager_reply(messages))


class TestModelBackedObserverContract(ObserverContract):
    """Runs ModelBackedObserver through the shared Observer conformance suite."""

    #: This observer cannot be *asked* to state a subject, which is why it opts
    #: out of the counting half of ADR-0100 §5 rather than proving it. §5 records
    #: the reason as a property of the implementation: it "builds every record
    #: itself from a fixed JSON envelope whose schema has no subject key, so the
    #: shipped observer *cannot* state one however the model answers". What that
    #: leaves unproven is proven directly instead, by
    #: ``test_a_model_cannot_state_a_subject_however_it_spells_one`` below, which
    #: is the stronger statement for this implementation: not "a stated subject is
    #: refused" but "there is no way to state one".
    states_no_subject_by_construction = True

    @pytest.fixture
    def observer(self) -> Observer:
        subject, _ = _observer(_eager_reply)
        return subject

    @pytest.fixture
    def max_proposals(self) -> int:
        return _MAX_PROPOSALS

    @pytest.fixture
    def max_batch_size(self) -> int:
        return _MAX_BATCH

    def gated_observation(self) -> GatedObservation:
        gate = ObservationGate()
        return GatedObservation(
            observer=ModelBackedObserver(_GatedProvider(gate), now=_fixed_now),
            episodes=batch_of(2),
            gate=gate,
        )


# --- the payload and the citations (ADR-0077 §3, §5) ------------------------


async def test_the_prompt_carries_the_episodes_content_and_nothing_that_identifies_them() -> None:
    """The batch and nothing else — and no store id a model could echo back.

    The ids are the producer's (ADR-0077 §5), so an id in the prompt is an id a
    model can cite for an episode it never read, defeating the label mapping the
    rule exists for.
    """
    observer, provider = _observer(_envelope())
    episodes = [episode("ep-alpha", content="the user asked for shorter answers")]

    await observer.observe(episodes)

    prompt = provider.last_messages[-1].content
    assert "the user asked for shorter answers" in prompt
    assert "ep-alpha" not in prompt
    assert "[E1]" in prompt


async def test_a_cited_label_becomes_the_id_of_the_episode_actually_read() -> None:
    observer, _ = _observer(_envelope(_belief(evidence=["E2"])))
    episodes = batch_of(3)

    outcome = await observer.observe(episodes)

    (proposal,) = outcome.proposals
    assert proposal.proposed.provenance.evidence == ("e1",)
    assert proposal.proposed.id == "belief-0"
    assert proposal.sensitivity.value == "personal"
    assert proposal.conflicts == ()


#: Three instants for the out-of-order batch below, none of them the observer's
#: clock (:data:`_WHEN`). ADR-0109 §10 forbids a fixture whose expected value
#: coincides with an instant the code could have reached for instead — here the
#: clock, which is already ``last_updated``, and the *first* cited episode's
#: instant, which is what "take the first citation" would answer.
_EARLY: Final = datetime(2025, 9, 3, tzinfo=UTC)
_LATEST: Final = datetime(2025, 12, 24, tzinfo=UTC)
_MIDDLE: Final = datetime(2025, 10, 17, tzinfo=UTC)


async def test_a_derived_beliefs_confirming_instant_is_the_latest_cited_occurred_at() -> None:
    """ADR-0109 §4's ``DERIVED`` arm, over a batch deliberately out of order.

    ADR-0103 §9 rules the band's confirming event as "the most recent observation
    supporting it, the latest ``occurred_at`` among the episodes
    ``Provenance.evidence`` cites, and never the moment of derivation". The cited
    episodes run ``_EARLY, _LATEST, _MIDDLE``, so an implementation taking the
    first citation, the last, or the batch's own order answers differently from
    one taking the maximum — which is the only assertion that separates them.

    ``last_updated`` is the observer's clock and is a *fourth* distinct value, so
    this case also carries ADR-0109 §10's transaction-time clause on the producer
    side.

    The **uncited** episode is what makes "among the episodes it cites" mean
    something: it is the latest in the batch by a year, and a producer computing
    over the batch rather than over the citations it resolved would answer with
    it. The citations are ours and never the model's (ADR-0077 §5), and ADR-0106
    §3 has the instant taken over that same selected set for the same reason.
    """
    observer, _ = _observer(_envelope(_belief(evidence=["E1", "E2", "E3"], step="inferred")))
    episodes = [
        episode("e-early", occurred_at=_EARLY),
        episode("e-latest", occurred_at=_LATEST),
        episode("e-middle", occurred_at=_MIDDLE),
        episode("e-uncited", occurred_at=_LATEST.replace(year=_LATEST.year + 1)),
    ]

    outcome = await observer.observe(episodes)

    (proposal,) = outcome.proposals
    provenance = proposal.proposed.provenance
    assert provenance.evidence == ("e-early", "e-latest", "e-middle")
    assert provenance.last_confirmed_at == _LATEST
    assert provenance.last_updated == _WHEN
    assert provenance.last_confirmed_at != provenance.last_updated


async def test_a_cited_episode_dated_in_our_future_is_stored_unchanged() -> None:
    """ADR-0109 §4's fourth clause, at the ``DERIVED`` producer.

    Nothing constrains ``EpisodicMemory.occurred_at`` to the past, so this producer
    is separately capable of dropping or clamping a future instant, and it must do
    neither: it "writes its band's instant as it stands and applies no usability
    test to it". The usability test is the fold's, where two candidates exist.

    Asserting the exact instant refuses ``None``, the observer's own clock, and a
    clamp to it, in one assertion.
    """
    ahead = _WHEN.replace(year=_WHEN.year + 2)
    observer, _ = _observer(_envelope(_belief(evidence=["E1", "E2"], step="inferred")))
    episodes = [episode("e-past", occurred_at=_EARLY), episode("e-ahead", occurred_at=ahead)]

    outcome = await observer.observe(episodes)

    (proposal,) = outcome.proposals
    assert proposal.proposed.provenance.last_confirmed_at == ahead
    assert ahead > _WHEN


async def test_an_entry_citing_a_label_outside_the_batch_is_discarded_not_repaired() -> None:
    """Evidence attached to satisfy a rule is not evidence (ADR-0077 §5)."""
    observer, _ = _observer(_envelope(_belief(evidence=["E9"])))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1
    assert outcome.discarded_over_limit == 0


async def test_two_labels_resolving_to_one_episode_are_one_support() -> None:
    """Support is counted over distinct ids, never over citations (ADR-0077 §5)."""
    observer, _ = _observer(_envelope(_belief(evidence=["E1", "E1"], step="inferred")))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == (), "one episode cannot supply an INFERRED belief's two supports"
    assert outcome.discarded_unusable == 1


async def test_an_inferred_entry_below_the_evidence_floor_is_discarded() -> None:
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], step="inferred")))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_an_entry_of_a_forbidden_kind_is_discarded() -> None:
    """A model-authored episode would be a fabricated event (ADR-0077 §2)."""
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], kind="episodic")))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


@pytest.mark.parametrize("key", ["about_person", "subject", "about"])
async def test_a_model_cannot_state_a_subject_however_it_spells_one(key: str) -> None:
    """This observer states no subject *by construction* (ADR-0100 §5).

    The shared suite pins that no proposal states a subject. This pins the
    mechanism the ADR relies on for that holding today rather than merely being
    observed to: the envelope schema has no subject key, ``_record`` builds every
    record itself from a fixed set of fields, and so there is no spelling of a
    subject the model can reach. An unrecognised key is unused, not unusable —
    the entry is proposed, without a subject.

    Three spellings, because the hazard is a *later* edit threading one of them
    into ``_record``'s inputs without noticing ADR-0100 §5 forbids it. The day a
    subject legitimately reaches a producer — §4's "structured field of a source"
    case, which has no instance today — it arrives with an ADR, and this is the
    case that fails and asks for one.
    """
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], **{key: "Marta"})))

    outcome = await observer.observe(batch_of(2))

    (proposal,) = outcome.proposals
    assert proposal.proposed.about_person is None
    assert outcome.discarded_unusable == 0


@pytest.mark.parametrize(
    ("kind", "memory_kind"),
    [
        ("semantic", MemoryKind.SEMANTIC),
        ("preference", MemoryKind.PREFERENCE),
        ("procedural", MemoryKind.PROCEDURAL),
    ],
)
async def test_each_proposable_kind_becomes_its_typed_record(
    kind: str, memory_kind: MemoryKind
) -> None:
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], kind=kind, steps=["do the thing"])))

    outcome = await observer.observe(batch_of(1))

    (proposal,) = outcome.proposals
    assert proposal.proposed.kind == memory_kind


# --- the counting rules (ADR-0077 §4) ---------------------------------------


async def test_the_two_counts_are_exhaustive_over_the_entries_the_model_emitted() -> None:
    """Proposals plus both counts equal what the model actually returned.

    The invariant ``ObservationOutcome`` documents but cannot enforce, since it is
    a statement about a response an observer need not have. Here it is a statement
    about a response that is right in front of us: six entries in, six accounted
    for.
    """
    entries = [
        _belief(evidence=["E1"], content="one"),
        _belief(evidence=["E9"], content="cites nothing real"),
        _belief(evidence=["E2"], content="two"),
        _belief(evidence=["E1"], step="inferred", content="a leap"),
        _belief(evidence=["E3"], content="three"),
        _belief(evidence=["E1", "E2"], step="inferred", content="four"),
    ]
    observer, _ = _observer(_envelope(*entries), max_proposals=2)

    outcome = await observer.observe(batch_of(3))

    assert len(outcome.proposals) + outcome.discarded_unusable + outcome.discarded_over_limit == 6
    assert outcome.discarded_unusable == 2
    assert outcome.discarded_over_limit == 2


async def test_entries_are_validated_before_the_bound_is_applied() -> None:
    """An unusable entry never occupies a slot a good one could have filled.

    Capping first would yield one proposal here instead of two, and would put the
    junk entry in ``discarded_over_limit`` when it happened to sit past the cut —
    two conforming producers reporting different outcomes for one response
    (ADR-0077 §4).
    """
    entries = [
        _belief(evidence=["E1"], content="one"),
        _belief(evidence=["E9"], content="junk sitting inside the bound"),
        _belief(evidence=["E2"], content="two"),
        _belief(evidence=["E3"], content="three"),
    ]
    observer, _ = _observer(_envelope(*entries), max_proposals=2)

    outcome = await observer.observe(batch_of(3))

    assert [p.proposed.content for p in outcome.proposals] == ["one", "two"]
    assert outcome.discarded_unusable == 1
    assert outcome.discarded_over_limit == 1


async def test_a_response_that_does_not_decode_counts_as_exactly_one_unusable_entry() -> None:
    """And the producer does not re-prompt: nothing is waiting on an observation."""
    observer, provider = _observer("I cannot help with that.")

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1
    assert outcome.discarded_over_limit == 0
    assert provider.call_count == 1


async def test_a_decoded_envelope_with_no_beliefs_list_is_the_same_single_discard() -> None:
    """An object that is not an envelope is no more usable than no object at all."""
    observer, _ = _observer(json.dumps({"thoughts": "hmm"}))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_an_empty_beliefs_list_is_a_normal_outcome_not_a_discard() -> None:
    """A model that read the batch and honestly proposed nothing (ADR-0022 §4)."""
    observer, _ = _observer(_envelope())

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 0
    assert outcome.discarded_over_limit == 0


async def test_the_envelope_is_found_behind_prose_and_a_decoy_object() -> None:
    """ADR-0071's scan, not ADR-0047 §4's superseded brace slice (#293)."""
    reply = f"Here you go {{not: the envelope}} — {_envelope(_belief(evidence=['E1']))} done."

    observer, _ = _observer(reply)

    outcome = await observer.observe(batch_of(2))

    assert len(outcome.proposals) == 1


async def test_a_model_failure_propagates_rather_than_reporting_nothing_to_learn() -> None:
    """ "No beliefs" would be indistinguishable from "nothing happened" (ADR-0022 §3)."""

    def fail(_messages: Sequence[Message]) -> str:
        msg = "the provider is down"
        raise ModelError(msg)

    observer, _ = _observer(fail)

    with pytest.raises(ModelError):
        await observer.observe(batch_of(2))


# --- the confidence ladder (ADR-0077 §5) ------------------------------------


async def _confidence_for(step: str, supports: int) -> float:
    """The confidence this producer assigns ``supports`` episodes taken by ``step``."""
    labels = [f"E{index + 1}" for index in range(supports)]
    observer, _ = _observer(_envelope(_belief(evidence=labels, step=step)))
    outcome = await observer.observe(batch_of(supports))
    (proposal,) = outcome.proposals
    return proposal.proposed.provenance.confidence


async def test_confidence_is_non_decreasing_in_distinct_support() -> None:
    assert await _confidence_for("observed", 1) <= await _confidence_for("observed", 2)
    assert await _confidence_for("inferred", 2) <= await _confidence_for("inferred", 3)


async def test_observed_outranks_inferred_on_equal_support() -> None:
    """The inferred belief took a step its evidence does not entail (ADR-0072 §3)."""
    assert await _confidence_for("observed", 2) > await _confidence_for("inferred", 2)
    assert await _confidence_for("observed", 3) > await _confidence_for("inferred", 3)


async def test_confidence_is_strictly_below_the_users_own_word() -> None:
    """Including at the top of the ladder, where a ceiling is the only thing holding it."""
    for supports in (1, 2, _MAX_BATCH):
        assert await _confidence_for("observed", supports) < 1.0


async def test_the_same_response_twice_yields_byte_identical_confidences() -> None:
    """Re-observation cannot inflate a belief: the fold's maximum finds nothing higher."""
    reply = _envelope(_belief(evidence=["E1", "E2"], step="inferred"))
    observer, _ = _observer(reply)
    episodes = batch_of(2)

    first = await observer.observe(episodes)
    second = await observer.observe(episodes)

    assert (
        first.proposals[0].proposed.provenance.confidence
        == second.proposals[0].proposed.provenance.confidence
    )


async def test_a_clock_moved_between_calls_does_not_move_the_confidence() -> None:
    """The only way "no clock" is observable at all (ADR-0077 §9.3).

    The timestamp *does* move, which is what makes the assertion about confidence
    meaningful rather than about a clock that was never read.
    """
    instants = iter([_WHEN, _WHEN + timedelta(days=400)])
    observer, _ = _observer(_envelope(_belief(evidence=["E1"])), now=lambda: next(instants))
    episodes = batch_of(2)

    first = await observer.observe(episodes)
    second = await observer.observe(episodes)

    assert (
        first.proposals[0].proposed.provenance.confidence
        == second.proposals[0].proposed.provenance.confidence
    )
    assert (
        first.proposals[0].proposed.provenance.last_updated
        != second.proposals[0].proposed.provenance.last_updated
    )


async def test_a_non_conforming_clock_reading_is_refused_rather_than_stored() -> None:
    """The guard ADR-0026 §7 puts on every injected clock seam."""
    observer, _ = _observer(
        _envelope(_belief(evidence=["E1"])),
        now=lambda: datetime(2026, 1, 1),  # noqa: DTZ001 — a naive reading is the stimulus
    )

    with pytest.raises(ValueError, match=r"(?i)naive|aware|utc"):
        await observer.observe(batch_of(2))


# --- the batch, and the bounds on it (ADR-0077 §1) --------------------------


async def test_an_empty_batch_reaches_no_model_at_all() -> None:
    """Nothing to observe, so no egress of the most sensitive data the system holds."""
    observer, provider = _observer(_eager_reply)

    outcome = await observer.observe([])

    assert outcome.proposals == ()
    assert provider.call_count == 0


async def test_an_oversized_batch_is_refused_before_the_model_is_called() -> None:
    observer, provider = _observer(_eager_reply)

    with pytest.raises(ValueError, match="exceeds the configured maximum"):
        await observer.observe(batch_of(_MAX_BATCH + 1))

    assert provider.call_count == 0


async def test_a_repeated_episode_is_refused_before_the_model_is_called() -> None:
    observer, provider = _observer(_eager_reply)
    repeated = episode("e0")

    with pytest.raises(ValueError, match="a batch is a set"):
        await observer.observe([repeated, episode("e1"), repeated])

    assert provider.call_count == 0


#: The two bounds, each as a one-argument builder, so a case can drive either
#: without a ``**kwargs`` dict mypy cannot check against the real signature.
_BOUNDS: Final[list[Callable[[int], ModelBackedObserver]]] = [
    lambda value: ModelBackedObserver(FakeModelProvider(), max_batch_size=value),
    lambda value: ModelBackedObserver(FakeModelProvider(), max_proposals=value),
]
_BOUND_IDS: Final = ["max_batch_size", "max_proposals"]


@pytest.mark.parametrize("build", _BOUNDS, ids=_BOUND_IDS)
def test_a_non_positive_bound_is_refused_at_construction(
    build: Callable[[int], ModelBackedObserver],
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        build(0)


@pytest.mark.parametrize("build", _BOUNDS, ids=_BOUND_IDS)
def test_a_boolean_bound_is_refused_at_construction(
    build: Callable[[int], ModelBackedObserver],
) -> None:
    """``True`` is an ``int`` in Python, and a bound of 1 by accident is a bug."""
    with pytest.raises(TypeError, match="must be an integer"):
        build(True)


async def test_a_full_batch_at_the_bound_is_accepted_and_conforms() -> None:
    """The boundary from the accepting side, so the refusal above is not off by one."""
    observer, _ = _observer(_eager_reply)
    episodes = batch_of(_MAX_BATCH)

    outcome = await observer.observe(episodes)

    assert_conforms(outcome, episodes)
    assert len(outcome.proposals) == _MAX_PROPOSALS


async def test_the_batch_is_observed_once_even_though_its_records_are_frozen() -> None:
    """The container is the caller's, and clearing it mid-flight must change nothing.

    The suite's gated case covers the tear at the model round trip; this covers
    the plainer half — that the observer never re-reads the caller's list after
    building its prompt from it.
    """
    observer, _ = _observer(_eager_reply)
    episodes = batch_of(3)

    outcome = await observer.observe(episodes)
    episodes.clear()

    assert_conforms(outcome, batch_of(3))
    assert outcome.proposals


async def test_an_entry_naming_no_step_is_discarded() -> None:
    observer, _ = _observer(_envelope({"kind": "semantic", "content": "x", "evidence": ["E1"]}))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


async def test_an_entry_with_blank_content_is_discarded() -> None:
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], content="   ")))

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1
