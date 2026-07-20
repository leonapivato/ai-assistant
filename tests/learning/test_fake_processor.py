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

from ai_assistant.core.types import (
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import FakeFeedbackProcessor, FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import FeedbackProcessor

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _event(
    *,
    kind: FeedbackKind = FeedbackKind.PREFERENCE,
    memory_kind: MemoryKind = MemoryKind.PREFERENCE,
    content: str = "prefers concise replies",
    subject: str | None = None,
    evidence: tuple[str, ...] = (),
) -> FeedbackEvent:
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        evidence=list(evidence),
        created_at=_WHEN,
    )


def _proposal(content: str = "scripted memory") -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="scripted-1",
            content=content,
            fact=content,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_WHEN),
        ),
        rationale="scripted by the test",
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


async def test_synthesised_record_carries_the_feedbacks_provenance() -> None:
    event = _event(subject="email tone", evidence=("ep-9",))

    [proposal] = await FakeFeedbackProcessor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.preference == "prefers concise replies"
    assert record.context == "email tone"
    assert record.provenance.source is MemorySource.USER_ASSERTED
    assert record.provenance.evidence == ["ep-9"]
    assert record.provenance.last_updated == _WHEN


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


async def test_mutating_a_scripted_proposal_after_construction_has_no_effect() -> None:
    # Ingress: the caller keeps its reference to the proposal it passed in.
    scripted = _proposal()
    processor = FakeFeedbackProcessor([scripted])

    scripted.rationale = "mutated after the fact"

    [returned] = await processor.process(_event())
    assert returned.rationale == "scripted by the test"


async def test_mutating_a_returned_proposal_does_not_affect_later_calls() -> None:
    processor = FakeFeedbackProcessor([_proposal()])

    [first] = await processor.process(_event())
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


async def test_a_recorded_event_is_a_snapshot_not_the_callers_object() -> None:
    # Otherwise a caller that reuses one event object across calls would rewrite
    # the record of what it already sent.
    event = _event(content="likes tea")
    processor = FakeFeedbackProcessor()

    await processor.process(event)
    event.content = "something else entirely"

    assert processor.last_event.content == "likes tea"
    assert processor.last_event is not event


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
    proposal = _proposal()
    proposal.proposed.content = content
    proposal.rationale = rationale

    with pytest.raises(ValueError, match=match):
        FakeFeedbackProcessor([proposal])
