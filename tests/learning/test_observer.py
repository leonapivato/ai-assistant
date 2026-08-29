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

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.core.types import (
    EpisodicMemory,
    MemoryKind,
    Message,
    ObservationOutcome,
    Role,
)
from ai_assistant.learning import DEFAULT_OBSERVATION_MAX_PROPOSALS, ModelBackedObserver
from ai_assistant.testing import FakeModelProvider, ObservationGate
from ai_assistant.testing.observation import (
    DEFAULT_MAX_BATCH_SIZE as FAKE_DEFAULT_MAX_BATCH_SIZE,
)
from ai_assistant.testing.observation import (
    DEFAULT_MAX_PROPOSALS as FAKE_DEFAULT_MAX_PROPOSALS,
)

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
    timezone: str | None = None,
) -> tuple[ModelBackedObserver, FakeModelProvider]:
    """An observer over a scripted provider, and the provider, for assertions.

    ``timezone`` defaults to ``None`` — no local calendar — so every case that is
    not about the temporal anchor drives the producer ADR-0156 §3's second clause
    describes, and the anchor's own cases are the ones that name a zone.
    """
    provider = FakeModelProvider(reply=reply)
    observer = ModelBackedObserver(
        provider,
        now=now,
        id_factory=_counting_ids(),
        timezone=timezone,
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


@pytest.mark.parametrize("minted", [None, 42], ids=["none", "an-int"])
async def test_a_malformed_minted_id_is_discarded_not_raised(minted: object) -> None:
    """One bad belief in a batch is a degradation, not a failed observation (ADR-0077 §4).

    ``self._id_factory()`` is evaluated *inside* the ``try`` that guards record
    construction, so a factory returning a value ``MemoryRecord`` refuses costs one
    unusable proposal and no more. Pinned here because ``FakeObserver`` is required
    to mirror it (ADR-0026 §7) and now can: it mints rather than deriving (#736), so
    the failure mode exists on both sides and the mirroring claim is testable.

    Only a non-``str`` is swept: an empty or whitespace id is *accepted* by
    ``MemoryRecord`` and therefore by both observers, and refusing it is the
    writer's job (``MemoryIngestor._checked_id``).
    """
    observer = ModelBackedObserver(
        FakeModelProvider(reply=_envelope(_belief(evidence=["E1"]))),
        now=_fixed_now,
        id_factory=lambda: minted,  # type: ignore[arg-type, return-value]
        max_proposals=_MAX_PROPOSALS,
        max_batch_size=_MAX_BATCH,
    )

    outcome = await observer.observe(batch_of(2))

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 1


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


# --- the temporal anchor (ADR-0156 §2, §3, §7) ------------------------------

#: A zone west of UTC, so a late-evening utterance falls on the *following* UTC
#: day: the error ADR-0156 §3 says a UTC calendar would make "for a fixed fraction
#: of all evidence, always in the same direction".
_ZONE: Final = "America/New_York"

#: 21:30 on Sunday 7 May 2023 in :data:`_ZONE`, and 8 May in UTC. The one instant
#: that separates a producer localising the calendar from one rendering the stored
#: ``UtcInstant``, which is why the two dates below are asserted as a pair.
_EVENING: Final = datetime(2023, 5, 8, 1, 30, tzinfo=UTC)
_EVENING_LOCAL: Final = "Sun 2023-05-07 21:30 -0400"
_EVENING_UTC_DATE: Final = "2023-05-08"

#: A second instant on a different day of the week, so "every episode's" means
#: more than "the first one's" (§7's first test clause).
_MORNING: Final = datetime(2023, 6, 9, 14, 5, tzinfo=UTC)
_MORNING_LOCAL: Final = "Fri 2023-06-09 10:05 -0400"

#: The two instants either side of :data:`_ZONE`'s 2023 fall-back, an hour apart and
#: sharing a wall-clock reading of 01:30.
_BEFORE_FALL_BACK: Final = datetime(2023, 11, 5, 5, 30, tzinfo=UTC)
_AFTER_FALL_BACK: Final = datetime(2023, 11, 5, 6, 30, tzinfo=UTC)


def _prompt_of(provider: FakeModelProvider) -> tuple[str, str]:
    """The system turn and the batch turn of the last observation, in that order."""
    messages = provider.last_messages
    return messages[0].content, messages[-1].content


# --- complete intake and the assistant's half (ADR-0162 §1, §8) -------------


def _told(episode_id: str, *, content: str, outcome: str | None = None) -> EpisodicMemory:
    """One episode of ADR-0162 §1's class, optionally carrying the assistant's half.

    Built by copy off the shared suite's ``episode`` rather than inline, so a batch
    here is the same capture-shaped record every other case uses and the only thing
    this helper adds is the field §8 rules on.
    """
    record = episode(episode_id, content=content)
    return record if outcome is None else record.model_copy(update={"outcome": outcome})


async def test_the_prompt_asks_for_a_record_of_everything_the_user_stated() -> None:
    """ADR-0162 §1's recording rule, which replaces ADR-0077 §2's warrant bar here.

    The bar asked the model to judge whether a thing was worth believing, and the
    measurement says that filter's false-negative rate is the system's dominant loss
    — 39.3% of pilot-4's answerable LoCoMo questions had gold no belief cited. §1
    asks a question the model can answer from the batch in front of it instead. Three
    halves of the rule are pinned because a partial edit is the failure that would
    read as compliance: the completeness instruction, the enumeration of what counts
    as a thing a later question could ask about, and the explicit repeal of "that it
    merely happened" as a ground for refusing.

    The filler clause is pinned with them, because §1 keeps exactly one refusal and a
    prompt that dropped it would be a different rule.
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "Record what the user told you, completely" in system
    assert "one belief for each distinct thing the user stated" in system
    assert "That a thing merely happened is not a reason to leave it out" in system
    assert "Pass over pure conversational filler" in system
    assert "pass over nothing else" in system


async def test_the_prompt_asks_for_one_thing_per_record() -> None:
    """§1's third clause, which is what stops completeness becoming a summary.

    A model told to record everything and not told the unit will fold a session into
    one dense sentence, which retrieval then returns whole or not at all. The unit is
    the thing a later question could ask about because that is the unit a search
    returns — so the reason is in the prompt and not only in the ADR.
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "One belief states ONE thing" in system
    assert "the unit is the thing a later question could ask about" in system


async def test_the_prompt_partitions_the_assistants_half_by_what_a_record_claims() -> None:
    """ADR-0162 §8's two clauses, which are a boundary and not a volume control.

    What the assistant said independently supports a record of the assistant's own
    *act* — that it was asked something, that it answered or did a particular thing,
    and when — which the ``outcome`` field witnesses. It never supports a record that
    adopts the proposition it asserted as a fact about the world or the user: that
    would let the assistant launder its own assertions into the user's model, a
    belief citing an episode that witnesses only the *saying*. Both halves are pinned
    because either alone is a different rule — the permission alone opens the
    laundering route, and the refusal alone loses the
    single-session-assistant material (#1029 scores that arm at 50%).

    The citation clause rides here because the rendering below puts two texts under
    one label: ADR-0077 §5's floor counts labels, and an episode split into two would
    let one episode supply the two distinct supports an ``INFERRED`` record owes.
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert 'on an "Assistant:" line' in system
    assert "evidence about what HAPPENED, never about what is TRUE" in system
    assert "propose a belief about the assistant's own act" in system
    assert "You may NOT take a claim the assistant asserted" in system
    assert "record such a fact only where the USER stated it" in system
    assert "one episode is one label and one support" in system


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_an_episodes_outcome_reaches_the_prompt_under_that_episodes_label(
    timezone: str | None,
) -> None:
    """§8's first clause, in both rendered variants.

    The field has been stored and outside the prompt since it existed: the harness
    pairs a user turn with the assistant turn that follows it and puts the latter
    here, so under the pre-#1184 LoCoMo mapping roughly half the corpus was never
    visible to distillation at all (#1185). Parametrised over the zone because the
    two variants build their lines separately and an edit to one is not an edit to
    the other.

    **Under the same label is the assertion, not merely present.** An episode is
    cited whole (§8's second clause), so the two texts share one label and the batch
    grows a line rather than an entry — which is what the index comparison checks:
    the assistant's half falls between this episode's label and the next one's.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)
    episodes = [
        _told("e1", content="I asked which route to take", outcome="I recommended the coastal one"),
        _told("e2", content="I took it and it was lovely"),
    ]

    await observer.observe(episodes)

    _, batch = _prompt_of(provider)
    assert "Assistant: I recommended the coastal one" in batch
    assert batch.index("[E1]") < batch.index("Assistant:") < batch.index("[E2]")
    assert "[E3]" not in batch, "the outcome is a line of E1, never an episode of its own"


async def test_an_episode_carrying_no_outcome_renders_exactly_as_it_did() -> None:
    """The rendering adds a line where there is one to add, and nothing where there
    is not — so a corpus with no assistant half (LoCoMo, under #1177's framing, where
    every exchange carries ``outcome=None``) is byte for byte what it was."""
    observer, provider = _observer(_envelope())

    await observer.observe([_told("e1", content="I took the coastal route")])

    _, batch = _prompt_of(provider)
    assert "Assistant:" not in batch
    assert batch.splitlines() == [
        "Episodes (recorded times withheld: no local calendar is configured):",
        "  [E1] I took the coastal route",
    ]


def test_the_producers_default_proposal_bound_is_the_one_settings_ships() -> None:
    """ADR-0162 §13 holds the two equal, and nothing else in the tree checks it.

    ``core.config`` and ``learning.observer`` state the figure separately — the
    composition root passes the operator's value, and this constant is what a direct
    construction gets — so the two are held in step by a rule rather than by a
    dependency. A rule stated only in two comments is one a later edit moves by half.

    The value's *ground* is what changed with it (§6): 5 was ADR-0077 §2's
    selectivity bar expressed as a number, and §1 repeals that bar for a told
    episode, so what bounds the return value now is one pass's cost and egress alone.
    """
    assert DEFAULT_OBSERVATION_MAX_PROPOSALS == 40
    assert Settings().observation_max_proposals == DEFAULT_OBSERVATION_MAX_PROPOSALS


def test_the_canonical_fakes_proposal_bound_deliberately_does_not_follow() -> None:
    """§13's fourth clause: ``testing``'s ``DEFAULT_MAX_PROPOSALS`` **stays 5**.

    ``FakeObserver`` synthesises one ``OBSERVED`` belief per episode plus one
    ``INFERRED`` over the first two, so a batch of *n* asks for more than *n*
    proposals — which is what makes the configured maximum bite, and at
    ``DEFAULT_MAX_BATCH_SIZE`` 20 that is 21 proposals against a maximum of 5. Taking
    the fake to 40 would put 21 under it and retire the very clause the fake exists
    to exercise, so its number follows the *fixture's* purpose and not a
    deployment's. That is the difference between a canonical fake and a default, and
    it is asserted here rather than left to a comment because the two constants now
    differ and the obvious tidy-up is to make them agree.
    """
    assert FAKE_DEFAULT_MAX_PROPOSALS == 5
    assert FAKE_DEFAULT_MAX_BATCH_SIZE + 1 > FAKE_DEFAULT_MAX_PROPOSALS, (
        "a batch of n asks for n + 1 proposals, which is what makes the bound bite"
    )
    assert FAKE_DEFAULT_MAX_BATCH_SIZE + 1 <= DEFAULT_OBSERVATION_MAX_PROPOSALS, (
        "and the deployment default is where 21 proposals would fit under the bound, "
        "which is the divergence §13 rules deliberate"
    )


async def test_the_batch_states_every_episodes_occurred_at_in_the_configured_zone() -> None:
    """ADR-0156 §2's first clause, over a batch of two dated on different days.

    The instants are the producer's own — snapshotted off the frozen tuple beside
    the labels — so this is the whole enabling change of the decision: the model
    that writes the belief sentence could not previously see when anything was
    said, and could therefore not resolve *"yesterday"* however it was prompted.

    The weekday is asserted with the date because §3 has the producer resolve a
    relative expression against that instant, and *"last Friday"* is not resolvable
    from a calendar date whose day of week the reader has to derive.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)
    episodes = [
        episode("e-evening", occurred_at=_EVENING, content="I went to a support group yesterday"),
        episode("e-morning", occurred_at=_MORNING, content="the picnic was lovely"),
    ]

    await observer.observe(episodes)

    _, batch = _prompt_of(provider)
    assert f"[E1] {_EVENING_LOCAL}" in batch
    assert f"[E2] {_MORNING_LOCAL}" in batch
    assert "I went to a support group yesterday" in batch, "the content is still carried"
    assert "e-evening" not in batch, "and still no store id a model could echo back"


async def test_an_episode_whose_utc_and_local_dates_differ_carries_the_local_one() -> None:
    """ADR-0156 §3's calendar clause, on the instant that separates the two answers.

    ``occurred_at`` is a ``UtcInstant`` (ADR-0030 §4) and this one is 8 May in UTC
    and 7 May in the configured zone. A producer rendering the stored value would
    date *"yesterday"* to 7 May where the speaker meant 6 May — wrong by a day,
    silently, and in one direction for every evening utterance west of UTC.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe([episode("e-evening", occurred_at=_EVENING, content="a quiet evening")])

    _, batch = _prompt_of(provider)
    assert _EVENING_LOCAL in batch
    assert _EVENING_UTC_DATE not in batch


async def test_two_instants_sharing_a_wall_clock_across_the_dst_fold_render_apart() -> None:
    """A repeated local hour is two instants, and the prompt must not merge them.

    At ``America/New_York``'s 2023 fall-back both of these read *"Sun 2023-11-05
    01:30"*, so a sub-day expression — "two hours ago" — resolves to 4 November from
    one and 5 November from the other while the model sees identical input. The
    numeric offset is what separates them, and it is why :data:`_INSTANT_FORMAT`
    carries one.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)
    episodes = [
        episode("e-edt", occurred_at=_BEFORE_FALL_BACK, content="the earlier one"),
        episode("e-est", occurred_at=_AFTER_FALL_BACK, content="the later one"),
    ]

    await observer.observe(episodes)

    _, batch = _prompt_of(provider)
    assert "[E1] Sun 2023-11-05 01:30 -0400" in batch
    assert "[E2] Sun 2023-11-05 01:30 -0500" in batch


@pytest.mark.parametrize(
    ("boundary", "zone"),
    [
        (datetime(9999, 12, 31, 23, 59, tzinfo=UTC), "Pacific/Kiritimati"),
        (datetime(1, 1, 1, 0, 1, tzinfo=UTC), "America/New_York"),
    ],
    ids=["max-shifted-forward", "min-shifted-back"],
)
async def test_an_instant_with_no_local_representation_is_withheld_not_raised(
    boundary: datetime, zone: str
) -> None:
    """Both ends of the representable calendar, from the side that shifts off it.

    ``EpisodicMemory`` accepts either instant and ADR-0092 §3 forbids refusing or
    rewriting a source instant, but ``astimezone`` cannot express one within an
    offset of the boundary: an unhandled ``OverflowError`` would escape ``observe``
    and take the whole batch with it. The good episode beside it is what makes the
    withholding observable as a *per-episode* answer rather than a refusal, and the
    model is still called.
    """
    observer, provider = _observer(_envelope(), timezone=zone)
    episodes = [
        episode("e-boundary", occurred_at=boundary, content="at the edge of the calendar"),
        episode("e-ordinary", occurred_at=_EVENING, content="an ordinary evening"),
    ]

    outcome = await observer.observe(episodes)

    assert outcome.discarded_unusable == 0
    assert provider.call_count == 1, "the batch was observed, not refused"
    _, batch = _prompt_of(provider)
    assert "[E1] (recorded time unavailable) — at the edge of the calendar" in batch
    assert "[E2] " in batch
    assert "an ordinary evening" in batch


async def test_the_prompt_names_the_zone_it_rendered_the_instants_in() -> None:
    """§2's first clause names the zone as well as rendering in it.

    An unnamed local time is an ambiguous one: the model is asked to work a date
    out from it, and a reader of the transcript cannot check the arithmetic without
    knowing which calendar it was done in.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(2))

    system, batch = _prompt_of(provider)
    assert _ZONE in batch
    assert _ZONE in system


async def test_a_producer_built_without_a_zone_renders_no_instant() -> None:
    """ADR-0156 §3's second clause: no zone, no calendar, so nothing is stated.

    The two fallbacks it names are UTC and a zone the producer chose for itself,
    and both would put a calendar date the deployment never authorised in front of
    a model that will write it into a belief. Asserting the absence of *both* dates
    refuses each fallback separately — the stored UTC value, and the value a
    host-locale conversion would have produced.
    """
    observer, provider = _observer(_envelope())

    await observer.observe([episode("e-evening", occurred_at=_EVENING, content="a quiet evening")])

    system, batch = _prompt_of(provider)
    assert "2023" not in batch, "no date in any calendar at all"
    assert "21:30" not in batch
    assert "01:30" not in batch
    assert "a quiet evening" in batch, "the batch is still rendered"
    assert "Do not work a date out from context, and do not guess one" in system
    assert "work the date out against that episode's recorded time" not in system


async def test_a_producer_without_a_zone_still_asks_for_a_date_the_evidence_states() -> None:
    """§3's second clause is scoped to the *resolution*, not to the anchor.

    Evidence reading "I went to the gym on 7 May 2026" establishes a date no zone is
    needed to carry, and §2's second clause requires the belief to state it. A
    blanket "no zone, no time" would make that input unsatisfiable under both
    sections at once, which is why §3 says so in terms.
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "names a calendar date" in system
    assert "state that date in the belief's own sentence" in system


async def test_the_zoned_prompt_asks_for_an_absolute_date_and_refuses_a_relative_one() -> None:
    """§3's first clause, as the instruction the producer actually carries.

    A stored belief reading "joined the mentorship programme last weekend" is worse
    than one with no date: it points at an episode under a finite retention horizon
    (ADR-0074 §7, §8) that ADR-0077 §6 expects the belief to outlive. The resolution
    is possible only here, where both halves are in hand.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "work the date out against that episode's recorded time" in system
    assert "Never write the relative words themselves" in system


async def test_the_prompt_refuses_a_date_the_recorded_time_alone_would_supply() -> None:
    """§2's third clause, which is the operative half of that section.

    The cheapest reading of "carry the date" is to append the session's date to
    every belief, which states a falsehood about a trait, pays the embedding
    dilution on every record rather than on the datable ones, and puts a date where
    a reader takes it for an event time.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "Where the cited episodes establish no such time, state none" in system
    assert "acquires no date from the day it happened to be mentioned" in system


async def test_the_prompt_does_not_let_a_date_widen_what_may_be_proposed() -> None:
    """ADR-0156 §2's fourth clause: the rule above is applied unchanged.

    The temptation ADR-0156 §6 priced was to buy some of the measured ingestion loss
    back by letting the *time section* admit beliefs the rule above refuses. That
    clause is untouched by ADR-0162: what widened is the rule itself, in §1, by a
    ratified decision in the paragraph that owns it — and the time section still
    hands the decision back rather than taking any of it.

    **Two of the three sentences this used to assert were the bar and are gone**
    (ADR-0162 §1). "Do not summarise the exchange" and "Do not propose what merely
    happened" said exactly what §1 repeals for an episode recording what the user
    told the assistant; asserting them now would pin the prompt to a rule no longer
    in force. What survives unchanged is the *relation* — the time section decides
    what a belief says and never how many — and that is what is checked, together
    with the one refusal §1 keeps, so this cannot pass on a prompt that has quietly
    stopped refusing anything at all.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "A date is never a reason to propose a belief" in system
    assert "This governs how a belief is written, never whether" in system
    assert "Pass over pure conversational filler" in system


async def test_the_zoned_prompt_states_that_clause_in_both_directions() -> None:
    """§2's fourth clause is symmetric, and shipped it read as a brake only.

    "Applied unchanged" constrains the anchor in both directions: a date is no
    reason to propose a belief the bar refuses, and having none is no reason to
    withhold a belief the bar admits. Only the first half was said, at the end of a
    section that had already said "state none", "acquires no date" and "not worth
    holding with one", after a head that had already said "proposing nothing is a
    perfectly good answer" — and the measurement says a model reads the stack
    cumulatively (conv-26 re-ingested three times per tree: {28, 26, 25} beliefs
    before the anchor against {19, 22, 24} after, preferences 6/7/5 against 2/5/4,
    the time section the only prompt text that differs). This pins the restored
    half without letting the refusing half go: both are asserted here.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "The bar above is unchanged, in both directions" in system
    assert "the absence of one is never a reason to withhold one" in system
    assert "a belief that clears the bar is proposed whether or not the evidence" in system


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_neither_time_section_asks_for_fewer_beliefs(timezone: str | None) -> None:
    """The counterbalance is carried by both variants, in each one's own terms.

    The unzoned variant never carried §2's fourth clause — nothing in it invites a
    date the bar would refuse — but it is denser in prohibitions than the zoned one
    and reaches the same reader, so the half of the clause that is true whatever
    calendar the producer holds is stated there too. Pinning it in both is what
    stops the two texts drifting on the point.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "is never a reason to withhold" in system
    assert "not how many you propose" in system


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_the_timestamp_ban_is_narrowed_to_fields_and_not_lifted(
    timezone: str | None,
) -> None:
    """ADR-0156 §7's delicate half, in both prompt variants.

    The shipped sentence did two jobs: it correctly forbade the model to supply
    values for *fields* the producer computes (ADR-0106 §3, ADR-0109 §4 stated to
    the model) and it incorrectly forbade a date in the belief *sentence*, which no
    ratified decision requires. The first job survives; the second stops. The
    superseded blanket wording is asserted absent so that a later edit restoring it
    fails here rather than silently re-breaking the anchor.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "Do not include ids, confidence values, or any timestamp field of your own" in system
    assert "or timestamps; those are assigned downstream" not in system
    assert "belongs in the belief's `content` sentence and nowhere else" in system


#: Spellings a model might reach for if it decided to state a time as a field
#: rather than in the sentence ADR-0156 §1 confines it to. ``last_confirmed_at``
#: and ``valid_until`` are the two that name real fields of the record types, which
#: is what makes them the hazard rather than the curiosity.
_TEMPORAL_KEYS: Final = [
    "occurred_at",
    "event_at",
    "last_confirmed_at",
    "last_updated",
    "valid_until",
    "expires_at",
    "timestamp",
]


@pytest.mark.parametrize("key", _TEMPORAL_KEYS)
async def test_a_temporal_value_the_model_emits_is_discarded_rather_than_installed(
    key: str,
) -> None:
    """ADR-0156 §7's second test clause, and §1's whole reason for choosing content.

    A prompt instruction is not an enforcement point and never was, so the ban
    above is verified here independently of the prompt's wording: the envelope
    schema has no temporal key, ``_record`` builds every record itself from a fixed
    set of fields, and every instant on the result is the producer's. An
    unrecognised key is unused, not unusable — the entry is proposed, without it.

    The stimulus value is deliberately far from every instant the producer could
    have reached for, so "the model's value did not land" is separable from "the
    producer computed the same thing anyway" (ADR-0109 §10).
    """
    stated = "1999-12-31T23:59:00+00:00"
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], **{key: stated})), timezone=_ZONE)
    episodes = [episode("e-dated", occurred_at=_EVENING, content="something happened")]

    outcome = await observer.observe(episodes)

    (proposal,) = outcome.proposals
    assert outcome.discarded_unusable == 0, "an unrecognised key is unused, not unusable"
    record = proposal.proposed
    assert record.provenance.last_confirmed_at == _EVENING, "computed over the citations we read"
    assert record.provenance.last_updated == _WHEN, "the injected clock, not the model"
    assert record.expires_at is None
    assert record.validity.valid_until is None
    assert "1999" not in record.model_dump_json(), "no field on the record took the model's instant"


async def test_the_zone_changes_no_refusal_and_no_confidence() -> None:
    """ADR-0156 §7's fourth test clause: the prompt edit moved nothing else.

    One scripted reply through two producers differing only in the calendar, so the
    evidence floor (an ``INFERRED`` belief on one episode), the label mapping (a
    citation outside the batch) and the confidence function are each compared
    against themselves rather than against a remembered constant. The counts are
    also asserted absolutely, so a change that broke *both* producers identically
    still fails.
    """
    reply = _envelope(
        _belief(evidence=["E1"], step="inferred", content="a leap from one episode"),
        _belief(evidence=["E9"], content="cites nothing real"),
        _belief(evidence=["E1", "E2"], step="inferred", content="a belief across two"),
    )
    zoned, _ = _observer(reply, timezone=_ZONE)
    bare, _ = _observer(reply)

    with_zone = await zoned.observe(batch_of(2))
    without_zone = await bare.observe(batch_of(2))

    assert without_zone.discarded_unusable == 2, "the floor and the label mapping both bit"
    assert with_zone.discarded_unusable == without_zone.discarded_unusable
    assert [p.proposed.provenance.evidence for p in with_zone.proposals] == [("e0", "e1")]
    assert [p.proposed.provenance.evidence for p in without_zone.proposals] == [("e0", "e1")]
    assert (
        with_zone.proposals[0].proposed.provenance.confidence
        == without_zone.proposals[0].proposed.provenance.confidence
    )


def test_an_unknown_zone_is_refused_at_construction() -> None:
    """Like the bounds, and for ADR-0022 §4a's reason.

    Deferred to first use, a mistyped zone would be a producer that silently states
    no time — health reported, half the decision not implemented.
    """
    with pytest.raises(ConfigurationError, match="unknown timezone"):
        ModelBackedObserver(FakeModelProvider(), timezone="Definitely/Not_A_Zone")


# --- how a belief is phrased once it clears the bar (ADR-0077 §2) -----------


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_the_prompt_asks_a_belief_to_keep_the_particulars_the_evidence_gives(
    timezone: str | None,
) -> None:
    """The dominant loss the void run measured, addressed where it happens.

    A belief that clears ADR-0077 §2's bar and is then written as the trait it
    illustrates — *"Caroline is passionate about supporting the LGBTQ+ community"*
    out of an episode naming the group, the speech and the day — keeps its citation
    and loses everything a later question could match on, so the answerer correctly
    declines (62 of 149 records on #1029's paired prefix; 416 of 1,540 in pilot 1).
    ADR-0156 §6's first bullet names that loss and scopes it out of the anchor
    decision as an ingestion question; this paragraph is that question, and it is
    prompt prose rather than machinery because ADR-0156 §1 puts the whole sentence
    in the model's hands.

    Asserted in both variants because the paragraph is in the shared head: what a
    belief says about *time* depends on the calendar, what it says about a name or
    a place does not.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "keep the concrete particulars the belief is about" in system
    assert (
        "the proper names, places, organisations and quantities that identify or qualify" in system
    )
    assert "where it gives no particular the belief is about, state the trait alone" in system


async def test_the_specificity_paragraph_decides_no_part_of_which_beliefs() -> None:
    """It governs *how* a belief is written, never *whether* — and says so.

    Two things hold that line and both are pinned: the paragraph opens on "when you
    do propose", and it hands the decision back in its last sentence. The ordering
    assertion is the one a re-flow of the prompt would break silently — it sits after
    every paragraph that decides *which* beliefs and before the epistemic steps.

    **What is no longer asserted, and why** (ADR-0162 §1). The closing sentence used
    to add "and a retelling of what happened is refused however specific it is", and
    the ordering anchor used to be "Proposing nothing is a perfectly good answer".
    Both were ADR-0077 §2's bar, which §1 replaces for an episode recording what the
    user told the assistant: a record of what happened is now the point, and
    proposing nothing is relocated to the filler case rather than standing as the
    paragraph's opening posture. The anchor moves to the recording rule's own first
    line, which is what the paragraph now sits after.
    """
    observer, provider = _observer(_envelope(), timezone=_ZONE)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "This governs how a belief is written, never whether" in system
    assert "the rule above decides that" in system
    assert (
        system.index("Record what the user told you, completely")
        < system.index("One belief states ONE thing")
        < system.index("When you do propose a belief")
        < system.index("Each belief takes one of two epistemic steps")
    )


async def test_a_belief_that_names_a_particular_reaches_the_record_unaltered() -> None:
    """The instruction is only worth issuing if the pipeline preserves the answer.

    ``content`` is wholly model-authored (ADR-0156 §1) and nothing between the reply
    and the record rewrites it — no truncation, no normalisation, no summarising
    second pass — so a proper name, a place and a date survive distillation exactly
    as written. Pinned directly rather than assumed, because everything else on the
    record *is* recomputed by the producer, and a later lane adding a content step
    would defeat the prompt edit above without touching it.
    """
    content = "the user climbs at Boulder Barn in Leeds on Tuesdays, and has since 7 May 2023"
    # Every particular in it is one the belief is *about* — the venue, the city, the
    # recurrence — so this is the shape the paragraph above asks for, not a case of
    # the incidental detail it excludes.
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], content=content)), timezone=_ZONE)

    outcome = await observer.observe(
        [episode("e-climbing", occurred_at=_EVENING, content="I climb at Boulder Barn on Tuesdays")]
    )

    (proposal,) = outcome.proposals
    assert proposal.proposed.content == content


#: The refusal each time variant makes in its own words, for the case where the
#: evidence dates only the *telling*. Zoned, that is §2's third clause; unzoned,
#: the producer states no time at all unless the evidence names the date itself.
_UNDATED_TRAIT_REFUSAL: Final = {
    None: "Otherwise state no time",
    _ZONE: "a lasting trait acquires no date from the day it happened to be mentioned",
}


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_keeping_the_particulars_never_dates_a_belief_the_time_rule_undates(
    timezone: str | None,
) -> None:
    """The one place the two paragraphs could be read as contradicting each other.

    Evidence reading *"on 7 May I told Alex I enjoy climbing"* dates the telling and
    nothing the belief asserts. "Keep the particulars the evidence gives" would, if
    it enumerated dates, invite *"enjoys climbing; told Alex on 7 May"* — a dated
    transcript fragment, and precisely the naive implementation ADR-0156 §2's third
    clause refuses in terms and §6 prices. So the enumeration names no dates and the
    paragraph hands every time question to the section below it, which is more
    precise about *which* date than the head could be; §2's second clause still gets
    the dates a belief is entitled to, from that section.

    Pinned in both variants, and both halves are asserted together: the carve-out
    without the refusal it defers to would leave the trait undefended, and the
    refusal without the carve-out is the conflict this test exists for.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "quantities, dates" not in system, "the enumeration must not name dates"
    assert "organisations, dates" not in system, "the enumeration must not name dates"
    assert "Times are the one exception" in system
    assert "keeping the particulars is never a reason to date a belief" in system
    assert _UNDATED_TRAIT_REFUSAL[timezone] in system
    assert system.index("keep the concrete particulars") < system.index(
        _UNDATED_TRAIT_REFUSAL[timezone]
    ), "the section it defers to has to come after it"


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_the_particulars_kept_are_scoped_to_the_belief_and_not_the_exchange(
    timezone: str | None,
) -> None:
    """Specificity is not a licence to retain whoever else was in the room.

    On *"at Acme's dinner with Priya I realised I prefer vegan meals"*, the durable
    belief is the preference; Acme and Priya identify nothing about it and qualify
    nothing about it. An unscoped instruction would keep them, which is ADR-0077 §2's
    transcript failure mode arriving one belief at a time — third-party personal data
    at indefinite retention because it shared a sentence with something durable — and
    more than ADR-0004 §7's minimisation allows.

    The prompt therefore scopes by the particular's *role* rather than by its
    category, which is the only test that separates the two: the same proper name is
    kept where it is the thing believed and dropped where it merely attended. Both
    halves are pinned, because the scoping sentence without the exclusion sentence
    still reads as "keep the names".
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "that identify or qualify the thing believed" in system
    assert "whoever happened to be present" in system
    assert "are the exchange, not this belief, and are left out of its sentence" in system
    # ADR-0162 §1's boundary on that exclusion, pinned because without it the
    # sentence now reads as a refusal to record the diner at all — which §1 requires
    # as a belief of its own, from the same episode, in its own sentence.
    assert "never whether a person or place the user named gets a belief of its own" in system


@pytest.mark.parametrize("timezone", [None, _ZONE], ids=["no-zone", "zoned"])
async def test_the_prompt_asks_for_no_particular_the_evidence_does_not_give(
    timezone: str | None,
) -> None:
    """The failure mode specific to asking for concreteness: inventing it.

    An instruction to name the thing is an invitation to name more than the evidence
    names — to read one climbing session into *"goes to the Tuesday session every
    week"*. That would be a fabricated routine wearing an ``OBSERVED`` label, and the
    citation check cannot catch it: it verifies that the cited episodes exist and were
    in the batch (ADR-0077 §3), never what they support.

    Three things are pinned, because the clause alone is not the whole defence. The
    prohibition itself; that the worked example *cannot* model the error, because its
    two halves make the same claim and differ only in the particular — *"owns a 2012
    Honda Civic"* against *"owns a car"*, so the preferred half adds a detail and not
    a step, and the habit-shaped spellings it replaced are asserted gone; and that the
    paragraph still sits directly above the two epistemic steps, which is where the
    mechanism takes over from the wording. A model that labels its leap honestly is refused by the
    evidence floor rather than by this paragraph
    (``test_an_inferred_entry_below_the_evidence_floor_is_discarded``).

    The example is pinned by its exact text on purpose. It is the one line of a prompt
    a model imitates rather than reasons about, so a later lane swapping in a pair
    that changes predicate as well as detail — the shape three review rounds kept
    finding a one-occasion reading of — should have to change this assertion and say
    why.
    """
    observer, provider = _observer(_envelope(), timezone=timezone)

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "Add nothing the evidence does not give" in system
    assert "a particular you cannot point to in a cited episode is an invention" in system
    assert "one occasion is not a routine" in system
    assert 'Two ways of writing the same belief are not equally useful: "owns a 2012' in system
    assert 'Honda Civic" beats "owns a car"' in system
    assert "Tuesday" not in system, "the worked example must not model a recurrence claim"
    assert "climbs at" not in system, "nor a habit a single occasion could be read into"
    assert system.index("Add nothing the evidence does not give") < system.index(
        "a generalisation from a single episode will be discarded"
    )


# --- ADR-0213 §4: the topics entry the envelope carries ---------------------
# §12's tests 5-7, 12 and 14 on the observer's side. Every one names an input and
# the outcome it fixes: a topics entry the producer cannot use is **ignored**, the
# proposal it rode on is unaffected, and no counter moves for it.


def _topics_of(outcome: object) -> list[tuple[str, ...]]:
    """The topics of each proposal an outcome carries, in order."""
    assert isinstance(outcome, ObservationOutcome)
    return [proposal.proposed.topics for proposal in outcome.proposals]


async def test_a_usable_topics_entry_reaches_the_proposed_record() -> None:
    """The ordinary case, without which every refusal below passes a producer that
    ignores the entry unconditionally."""
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], topics=["health", "sleep"])))

    outcome = await observer.observe(batch_of(1))

    assert _topics_of(outcome) == [("health", "sleep")]


async def test_a_topics_entry_is_stored_in_canonical_order() -> None:
    """§1's order is the *tuple's*, and applying it changes no label (§3).

    A model emits a list; the field is a set with one spelling. Sorting is therefore
    required rather than optional, and it is not the normalisation §3 forbids —
    nothing here case-folds, strips or aliases a label, and a non-canonical one is
    still refused whole below.
    """
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], topics=["sleep", "health"])))

    outcome = await observer.observe(batch_of(1))

    assert _topics_of(outcome) == [("health", "sleep")]


@pytest.mark.parametrize(
    "topics",
    [
        pytest.param(["a", "b", "c", "d", "e"], id="five-labels"),
        pytest.param(["Health"], id="not-casefolded"),
        pytest.param([" health"], id="a-leading-space"),
        pytest.param(["health\tcare"], id="a-tab"),
        pytest.param(["health\u00a0care"], id="a-no-break-space"),
        pytest.param([""], id="empty-label"),
        pytest.param(["x" * 65], id="past-the-length-bound"),
        pytest.param(["health", "health"], id="a-repeated-label"),
        pytest.param(["health", 3], id="a-non-string-member"),
        pytest.param("health", id="a-bare-string-rather-than-a-list"),
        pytest.param({"health": True}, id="an-object"),
        pytest.param(None, id="null"),
        pytest.param([], id="an-empty-list"),
    ],
)
async def test_a_topics_entry_it_cannot_use_yields_no_topics_and_keeps_the_belief(
    topics: object,
) -> None:
    """§12.5 and §12.6, over every shape §4 names and the two the JSON allows.

    The entry is ignored — never repaired, never truncated to the bound, never
    re-prompted for and never inferred locally — and the record itself is
    unaffected. A rule that discarded the proposal over a bad label would trade a
    belief for a filing word, which §4 forbids in as many words.
    """
    observer, _ = _observer(_envelope(_belief(evidence=["E1"], topics=topics)))

    outcome = await observer.observe(batch_of(1))

    assert _topics_of(outcome) == [()]
    assert len(outcome.proposals) == 1


async def test_an_absent_topics_key_yields_no_topics() -> None:
    """The pre-field envelope, which a model may still emit (§7's empty tuple)."""
    observer, _ = _observer(_envelope(_belief(evidence=["E1"])))

    outcome = await observer.observe(batch_of(1))

    assert _topics_of(outcome) == [()]


async def test_a_bad_topics_entry_moves_no_counter_and_keeps_the_invariant() -> None:
    """§12.6's second half: ``ObservationOutcome``'s invariant is untouched (§4).

    The two counts are "exhaustive and disjoint over what the model emitted", so
    counting a usable entry whose topics were bad would report one proposal *and*
    one discard for one entry — a producer misreporting the model's output in the
    one direction anything checks.
    """
    observer, _ = _observer(
        _envelope(
            _belief(evidence=["E1"], topics=["Health"]),
            _belief(evidence=["E2"], content="the user runs", topics=["running"]),
            {"kind": "nonsense"},
        )
    )

    outcome = await observer.observe(batch_of(2))

    assert outcome.discarded_unusable == 1
    assert outcome.discarded_over_limit == 0
    assert len(outcome.proposals) + outcome.discarded_unusable + outcome.discarded_over_limit == 3
    assert _topics_of(outcome) == [(), ("running",)]


async def test_a_provider_failure_yields_no_topics_and_no_proposal() -> None:
    """§12.7: the pass raises rather than degrading into unlabelled beliefs.

    ADR-0130 §11's third ground, answered: a provider outage produces *no topics*
    and never a wrong one — and here no record either, because a ``ModelError`` ends
    the pass (ADR-0077 §3) rather than writing beliefs the model never saw.
    """

    def _fail(_messages: Sequence[Message]) -> str:
        raise ModelError("the provider is unreachable")

    observer, _ = _observer(_fail)

    with pytest.raises(ModelError):
        await observer.observe(batch_of(1))


async def test_the_prompt_asks_for_topics_and_states_the_form() -> None:
    """The producer applies §3's form, so the prompt has to state it (§13.3).

    The bound and the canonical form are both asked for, because a model that is
    told neither emits `"Health"` and five labels and has every entry ignored — a
    silent, total loss of the axis that no counter would report (§4).
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(1))

    system, _ = _prompt_of(provider)
    assert "at most FOUR short filing words" in system
    assert "lower case" in system
    assert '"topics": ["<filing word>", ...]' in system


async def test_the_observation_prompt_carries_nothing_derived_from_a_belief() -> None:
    """§12.12's second half, and it is what keeps ADR-0077 §3 true (§5).

    No vocabulary is supplied to the ``Observer`` on this ADR's authority: a
    vocabulary derived from the user's beliefs is the second class of Tier 1 data
    ADR-0077 §3 refuses, arriving for exactly the reason it refuses it. A reader
    holding only ADR-0077 sends the same payload after this decision as before, so
    the assertion is over the whole prompt rather than over one phrase.
    """
    observer, provider = _observer(_envelope())

    await observer.observe(batch_of(2))

    system, batch = _prompt_of(provider)
    assert "already in use" not in system
    assert "already in use" not in batch
    assert "Filing words" not in batch
