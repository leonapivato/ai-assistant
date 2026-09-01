"""The canonical FakeFeedbackProcessor passes the shared FeedbackProcessor suite.

This is what lets other subsystems trust
``ai_assistant.testing.FakeFeedbackProcessor`` as a stand-in for a real
processor: it is held to the same contract as ``RuleBasedFeedbackProcessor``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from feedback_processor_contract import FeedbackProcessorContract
from pydantic import ValidationError

from ai_assistant.core.types import (
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    Placement,
    PlacementReach,
    PlacementSetter,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import FakeFeedbackProcessor, FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import FeedbackProcessor

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _event(  # noqa: PLR0913 — one keyword per event field a case may need to vary
    *,
    kind: FeedbackKind = FeedbackKind.PREFERENCE,
    memory_kind: MemoryKind | None = MemoryKind.PREFERENCE,
    content: str = "prefers concise replies",
    subject: str | None = None,
    about_person: str | None = None,
    evidence: tuple[str, ...] = (),
    guarded: bool = False,
) -> FeedbackEvent:
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        about_person=about_person,
        evidence=evidence,
        created_at=_WHEN,
        guarded=guarded,
    )


def _proposal(
    content: str = "scripted memory",
    rationale: str = "scripted by the test",
    placement: Placement | None = None,
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="scripted-1",
            content=content,
            fact=content,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_WHEN),
            placement=placement if placement is not None else Placement(),
        ),
        rationale=rationale,
    )


class TestFakeFeedbackProcessorContract(FeedbackProcessorContract):
    """Runs the default FakeFeedbackProcessor through the shared suite."""

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        return FakeFeedbackProcessor()


class TestScriptedFakeFeedbackProcessorContract(FeedbackProcessorContract):
    """The suite must hold for a scripted processor too, not just the default.

    The two modes are different code paths — synthesis from the event versus a
    fixed script — and only the default one is covered above.
    """

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        return FakeFeedbackProcessor([_proposal()])


class TestSilentFakeFeedbackProcessorContract(FeedbackProcessorContract):
    """Proposing nothing is a contract-legal outcome, and consumers rely on it."""

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        return FakeFeedbackProcessor([])


# Behaviour specific to FakeFeedbackProcessor, beyond the shared contract: the
# contract deliberately says nothing about *which* proposals come back or what was
# recorded, so the fake's own affordances are pinned here.


async def test_synthesises_a_typed_record_for_every_memory_kind() -> None:
    # The point of the fake over RuleBasedFeedbackProcessor, which defers two of
    # the four kinds: a consumer can exercise whichever branch it cares about.
    expected: dict[MemoryKind, type] = {
        MemoryKind.PREFERENCE: PreferenceMemory,
        MemoryKind.SEMANTIC: SemanticMemory,
        MemoryKind.PROCEDURAL: ProceduralMemory,
        MemoryKind.EPISODIC: EpisodicMemory,
    }

    for memory_kind, record_type in expected.items():
        [proposal] = await FakeFeedbackProcessor().process(_event(memory_kind=memory_kind))
        assert isinstance(proposal.proposed, record_type)


@pytest.mark.parametrize(
    "memory_kind",
    [MemoryKind.PREFERENCE, MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.EPISODIC],
)
async def test_a_stated_subject_reaches_every_kind(memory_kind: MemoryKind) -> None:
    """``about_person`` is on the envelope, so no kind lacks somewhere to put it.

    Where ``subject`` reaches only the two kinds that have room for a *scope*,
    the subject axis reaches all four — the axes' own asymmetry (ADR-0100 §7),
    and what keeps ``_derived_id``'s reasoning true: every field of the event
    reaches the synthesised record.
    """
    [proposal] = await FakeFeedbackProcessor().process(
        _event(memory_kind=memory_kind, about_person="Marta")
    )

    assert proposal.proposed.about_person == "Marta"


async def test_synthesised_record_carries_the_feedbacks_provenance() -> None:
    event = _event(subject="email tone", evidence=("ep-9",))

    [proposal] = await FakeFeedbackProcessor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.preference == "prefers concise replies"
    assert record.context == "email tone"
    assert record.provenance.source is MemorySource.USER_ASSERTED
    assert record.provenance.evidence == ("ep-9",)
    assert record.provenance.last_updated == _WHEN
    # The `ASSERTED` band's confirming event is the user stating it (ADR-0109 §4),
    # so this fake takes the utterance's instant exactly as `FeedbackProcessor`
    # does. Asserted against the *event* rather than against `last_updated` beside
    # it, so the claim stays about the confirming event if #775 moves the other.
    assert record.provenance.last_confirmed_at == event.created_at


async def test_synthesised_ids_are_derived_from_the_feedback() -> None:
    # Deterministic ids are what make the fake usable as a fixture, but a counter
    # would make them depend on how many events came first. Deriving them from the
    # feedback keeps them stable under reordering — and identical across instances.
    processor = FakeFeedbackProcessor()

    [first] = await processor.process(_event(content="likes tea"))
    [second] = await processor.process(_event(content="likes coffee"))
    [elsewhere] = await FakeFeedbackProcessor().process(_event(content="likes tea"))

    assert first.proposed.id != second.proposed.id  # different feedback, different record
    assert first.proposed.id == elsewhere.proposed.id  # same feedback, same record


async def test_two_fakes_do_not_overwrite_each_other_in_a_shared_store() -> None:
    # The failure a per-instance counter would cause: both fakes issue id #1, and
    # the second write silently replaces the first. Exercised against the real
    # shared store, not just asserted on the ids.
    store = FakeMemoryStore()
    for content in ("likes tea", "likes coffee"):
        [proposal] = await FakeFeedbackProcessor().process(_event(content=content))
        await store.add(proposal.proposed)

    assert sorted(record.content for record in await store.export()) == [
        "likes coffee",
        "likes tea",
    ]


async def test_ids_distinguish_feedback_that_differs_only_in_kind_or_subject() -> None:
    # Content alone is not the identity: the same words targeting a different
    # memory kind, or scoped to a different subject, is a different record.
    words = "office is in Boston"
    processor = FakeFeedbackProcessor()

    [baseline] = await processor.process(_event(content=words))
    [other_kind] = await processor.process(_event(content=words, memory_kind=MemoryKind.SEMANTIC))
    [other_subject] = await processor.process(_event(content=words, subject="work"))

    ids = {baseline.proposed.id, other_kind.proposed.id, other_subject.proposed.id}
    assert len(ids) == 3


async def test_field_boundaries_cannot_be_smuggled_into_an_id_collision() -> None:
    # Any separator-joined derivation can be defeated by putting the separator
    # inside a field. These two events are different feedback and must not land on
    # one record — MemoryStore.add treats a repeated id as an upsert.
    store = FakeMemoryStore()
    for content, subject in [("a\x00b", "c"), ("a", "b\x00c")]:
        [proposal] = await FakeFeedbackProcessor().process(_event(content=content, subject=subject))
        await store.add(proposal.proposed)

    assert len(await store.export()) == 2


async def test_episodes_that_differ_only_in_when_are_distinct_records() -> None:
    # `created_at` reaches the record — as an episode's `occurred_at` and as every
    # record's provenance — so two events differing only there produce different
    # records, and must not share an upsert key.
    store = FakeMemoryStore()
    for when in (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)):
        event = FeedbackEvent(
            kind=FeedbackKind.CORRECTION,
            memory_kind=MemoryKind.EPISODIC,
            content="met Alice",
            created_at=when,
        )
        [proposal] = await FakeFeedbackProcessor().process(event)
        await store.add(proposal.proposed)

    assert len(await store.export()) == 2


_ACT = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_WHEN)


@pytest.mark.parametrize(
    "memory_kind",
    [MemoryKind.PREFERENCE, MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.EPISODIC],
)
async def test_a_guarded_event_places_a_synthesised_record_at_the_events_instant(
    memory_kind: MemoryKind,
) -> None:
    """ADR-0217 §7, on all four kinds this fake covers and none the real rules defer.

    The shared suite pins the reach and the setter. What is this fake's own is that
    it covers every kind — which is the whole reason a consumer reaches for it — so
    a guarded event drives the ``PROCEDURAL`` and ``EPISODIC`` branches
    ``RuleBasedFeedbackProcessor`` cannot reach at all.

    The instant is the **event's**, matching the real processor, so a consumer
    swapping one for the other sees the same record: ``set_at`` names when the
    narrowing was made and the narrowing is the owner's act, which is the
    utterance rather than our write (ADR-0109 §4's reading of
    ``last_confirmed_at``).
    """
    [proposal] = await FakeFeedbackProcessor().process(
        _event(memory_kind=memory_kind, guarded=True)
    )

    assert proposal.proposed.placement == _ACT


async def test_a_guarded_event_places_a_scripted_record_too() -> None:
    """ADR-0217 §7: the fake honours the member on the path a script takes as well.

    Everywhere else this fake treats a script as the consumer's stated outcome and
    returns it verbatim. Here it does not, and the reason is the clause itself: "A
    fake that ignores it would put a default placement on records in every
    orchestration and world test that uses one, which is the silent loss this
    clause exists to prevent." The obligation is the Protocol's, and
    ``FeedbackProcessorContract`` binds the scripted subclass beside the other two
    — a fake configurable out of its own contract is what its constructor already
    refuses for a blank proposal.
    """
    processor = FakeFeedbackProcessor([_proposal()])

    [proposal] = await processor.process(_event(guarded=True))

    assert proposal.proposed.placement == _ACT


async def test_an_unguarded_event_leaves_a_scripted_records_own_placement_alone() -> None:
    """``guarded=False`` is not an act, so it writes nothing — not even the default.

    This is why the act is computed as "a placement or nothing" rather than as a
    placement that happens to be the default: applying ``Placement()`` for an
    unguarded event would overwrite whatever the consumer's script carried, which
    on an ``OWNER``-placed record is a widening no clause of ADR-0217 permits and
    on a ``DERIVED`` one is the in-place clearing §3's closing clause forbids
    outright.
    """
    scripted = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_WHEN)
    processor = FakeFeedbackProcessor([_proposal(placement=scripted)])

    [proposal] = await processor.process(_event())

    assert proposal.proposed.placement == scripted


async def test_a_guarded_event_does_not_launder_a_derived_narrowing_into_an_act() -> None:
    """ADR-0217 §3's same-act precedence, at the one place this fake can reach it.

    "Where two would write the same reach, the recorded setter is decided by one
    total order, strongest first: ``DERIVED``, then ``OWNER_ACT``, then
    ``PROPOSED``", and §10 pins the case: "a record the derivation and an owner's
    act both place ``OWNER`` records setter ``DERIVED``". The reach is the same
    either way, so a reach-only assertion would pass on the wrong answer — and the
    wrong answer matters, because an ``OWNER_ACT`` stamp is one a later ``unguard``
    may lift and a ``DERIVED`` stamp is one no act may.
    """
    derived = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_WHEN)
    processor = FakeFeedbackProcessor([_proposal(placement=derived)])

    [proposal] = await processor.process(_event(guarded=True))

    assert proposal.proposed.placement == derived


async def test_a_guarded_event_narrows_a_record_the_owner_had_unguarded() -> None:
    """The differing-reach half of the same rule: the narrower reach stands (§3).

    A script carrying reach ``ANYONE`` with setter ``OWNER_ACT`` is a record the
    owner had unguarded. This is a *fresh* write rather than a fold of two stored
    placements, so nothing here is the eligibility clause: the act simply narrows,
    and the stamp it leaves is its own.
    """
    unguarded = Placement(
        reach=PlacementReach.ANYONE,
        set_by=PlacementSetter.OWNER_ACT,
        set_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    processor = FakeFeedbackProcessor([_proposal(placement=unguarded)])

    [proposal] = await processor.process(_event(guarded=True))

    assert proposal.proposed.placement == _ACT


async def test_the_guard_is_part_of_a_records_identity() -> None:
    """``_derived_id`` hashes the whole event, and the guard now reaches the record.

    The id derivation's own reasoning is that "every field of the event reaches the
    synthesised record", so a subset would let two events producing *different*
    records share an id and ``MemoryStore.add``'s upsert would destroy the first.
    A guarded and an unguarded statement of the same words produce records that
    differ in placement, so they must not collide.
    """
    [guarded] = await FakeFeedbackProcessor().process(_event(guarded=True))
    [plain] = await FakeFeedbackProcessor().process(_event())

    assert guarded.proposed.id != plain.proposed.id


async def test_evidence_is_part_of_a_records_identity() -> None:
    # Likewise: evidence becomes provenance.evidence, so it distinguishes records.
    [without] = await FakeFeedbackProcessor().process(_event())
    [with_evidence] = await FakeFeedbackProcessor().process(_event(evidence=("ep-9",)))

    assert without.proposed.id != with_evidence.proposed.id


async def test_an_absent_subject_is_distinct_from_an_empty_one() -> None:
    [absent] = await FakeFeedbackProcessor().process(_event(subject=None))
    [empty] = await FakeFeedbackProcessor().process(_event(subject=""))

    assert absent.proposed.id != empty.proposed.id


async def test_id_factory_is_injectable() -> None:
    processor = FakeFeedbackProcessor(id_factory=lambda: "rec-1")

    [proposal] = await processor.process(_event())

    assert proposal.proposed.id == "rec-1"


async def test_scripted_proposals_are_returned_for_any_event() -> None:
    scripted = _proposal()
    processor = FakeFeedbackProcessor([scripted])

    proposals = await processor.process(_event(memory_kind=MemoryKind.EPISODIC))

    assert proposals == [scripted]  # the script wins over synthesis


async def test_an_empty_script_proposes_nothing() -> None:
    # Distinct from the `None` default: a consumer needs to exercise its "the
    # learning step produced no proposal" path.
    assert await FakeFeedbackProcessor([]).process(_event()) == []


async def test_an_unresolved_kind_is_refused_rather_than_synthesised() -> None:
    """The fake keeps ADR-0122 §7's discipline on the branch that would invent one.

    ``None`` is not a kind: it is a request that has not chosen one yet, which the
    calling stage resolves before any processor is called. Synthesising a record for
    it would let a consumer's test pass while its subject skipped the resolution
    stage — certifying the exact silent drop §7 makes loud, from the double every
    consumer of the learning step reaches for.
    """
    with pytest.raises(ValueError, match="must carry a resolved memory_kind"):
        await FakeFeedbackProcessor().process(_event(memory_kind=None))


async def test_a_scripted_fake_answers_an_unresolved_event_with_its_script() -> None:
    """The refusal belongs to synthesis, not to the fake.

    A script is the consumer's own stated outcome — it is how a test says "this
    processor proposes exactly this" — and it names a record rather than deriving
    one from the event, so there is no drawer for the fake to invent. The
    ``FeedbackProcessor`` Protocol is unchanged by ADR-0122 (§7), so nothing here is
    a contract clause: the shared conformance suite states no such rule, and an
    implementation that answered an unresolved event some other way still conforms.
    """
    scripted = _proposal()

    assert await FakeFeedbackProcessor([scripted]).process(_event(memory_kind=None)) == [scripted]


async def test_a_scripted_proposal_cannot_be_mutated_after_construction() -> None:
    # Ingress: the caller keeps its reference to the proposal it passed in.
    # MemoryUpdateProposal is frozen (ADR-0068), so the mutation raises.
    scripted = _proposal()
    processor = FakeFeedbackProcessor([scripted])

    with pytest.raises(ValidationError):
        scripted.rationale = "mutated after the fact"

    [returned] = await processor.process(_event())
    assert returned.rationale == "scripted by the test"


async def test_a_returned_proposal_cannot_be_mutated() -> None:
    processor = FakeFeedbackProcessor([_proposal()])

    [first] = await processor.process(_event())
    with pytest.raises(ValidationError):
        first.rationale = "mutated by the caller"

    [second] = await processor.process(_event())
    assert second.rationale == "scripted by the test"


async def test_records_every_event_and_counts_calls() -> None:
    processor = FakeFeedbackProcessor()
    assert processor.call_count == 0

    await processor.process(_event(content="likes tea"))
    await processor.process(_event(content="likes coffee"))

    assert processor.call_count == 2
    assert [e.content for e in processor.events] == ["likes tea", "likes coffee"]
    assert processor.last_event.content == "likes coffee"


async def test_a_recorded_event_cannot_be_rewritten_by_the_caller() -> None:
    # Under ADR-0068 FeedbackEvent is frozen, so a caller that reuses one event
    # object across calls cannot rewrite the record of what it already sent:
    # isolation is subsumed by immutability.
    event = _event(content="likes tea")
    processor = FakeFeedbackProcessor()

    await processor.process(event)
    with pytest.raises(ValidationError):
        event.content = "something else entirely"

    assert processor.last_event.content == "likes tea"


def test_last_event_before_any_call_raises() -> None:
    with pytest.raises(IndexError):
        _ = FakeFeedbackProcessor().last_event


@pytest.mark.parametrize(
    ("content", "rationale", "match"),
    [
        ("   ", "a reason", "content must not be blank"),
        ("some content", "  ", "rationale must not be blank"),
    ],
)
def test_a_script_that_would_break_the_contract_is_rejected(
    content: str, rationale: str, match: str
) -> None:
    # MemoryUpdateProposal permits both, but the conformance suite does not — so
    # the canonical fake must not be configurable into failing its own contract.
    # The proposal is frozen (ADR-0068), so the bad value is passed at
    # construction rather than mutated in afterwards.
    proposal = _proposal(content=content, rationale=rationale)

    with pytest.raises(ValueError, match=match):
        FakeFeedbackProcessor([proposal])
