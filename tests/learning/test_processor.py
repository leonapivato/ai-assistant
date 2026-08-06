"""Tests for the RuleBasedFeedbackProcessor (feedback -> memory proposal)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from feedback_processor_contract import FeedbackProcessorContract

from ai_assistant.core.protocols import FeedbackProcessor
from ai_assistant.core.types import (
    FeedbackEvent,
    FeedbackKind,
    MemoryKind,
    MemorySource,
    PreferenceMemory,
    SemanticMemory,
)
from ai_assistant.learning import RuleBasedFeedbackProcessor

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _event(  # noqa: PLR0913 — one keyword per event field a case may need to vary
    *,
    kind: FeedbackKind = FeedbackKind.PREFERENCE,
    memory_kind: MemoryKind = MemoryKind.PREFERENCE,
    content: str = "prefers concise replies",
    subject: str | None = None,
    about_person: str | None = None,
    evidence: tuple[str, ...] = (),
    created_at: datetime = _WHEN,
) -> FeedbackEvent:
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        about_person=about_person,
        evidence=evidence,
        created_at=created_at,
    )


def _processor() -> RuleBasedFeedbackProcessor:
    return RuleBasedFeedbackProcessor(id_factory=lambda: "rec-1")


class TestRuleBasedFeedbackProcessorContract(FeedbackProcessorContract):
    """Runs RuleBasedFeedbackProcessor through the shared FeedbackProcessor suite."""

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        return RuleBasedFeedbackProcessor()


def test_conforms_to_protocol() -> None:
    assert isinstance(RuleBasedFeedbackProcessor(), FeedbackProcessor)


async def test_preference_feedback_becomes_a_user_asserted_preference() -> None:
    event = _event(subject="email tone", evidence=("ep-9",))

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.id == "rec-1"
    assert record.preference == "prefers concise replies"
    assert record.context == "email tone"
    assert record.provenance.source is MemorySource.USER_ASSERTED
    assert record.provenance.confidence == 1.0
    assert record.provenance.evidence == ("ep-9",)
    assert record.provenance.last_updated == _WHEN


async def test_semantic_correction_becomes_a_semantic_memory() -> None:
    event = _event(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="office is in Boston",
    )

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, SemanticMemory)  # a fact-correction is not a preference
    assert record.fact == "office is in Boston"
    assert record.provenance.source is MemorySource.USER_ASSERTED


async def test_procedural_and_episodic_targets_are_deferred() -> None:
    processor = _processor()

    assert await processor.process(_event(memory_kind=MemoryKind.PROCEDURAL)) == []
    assert await processor.process(_event(memory_kind=MemoryKind.EPISODIC)) == []


# --- the subject axis: the user's route into it (ADR-0100 §7) ----------------


async def test_a_stated_subject_reaches_the_preference_branch() -> None:
    """The scope and the subject land in their own places, not each other's."""
    event = _event(subject="travel", about_person="Marta")

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.about_person == "Marta"
    assert record.context == "travel"  # the scope axis, unmoved


async def test_a_stated_subject_reaches_the_semantic_branch_too() -> None:
    """The branch that discards a *scope* must still carry the subject.

    This is the specific way ADR-0100 §7 could be got wrong, because the two
    fields look alike at the call site: the semantic branch has nowhere to put a
    ``subject`` scope and drops it, as ADR-0009 §1 decided. Dropping the subject
    with it would write ``None``, which ADR-0100 §3 reads as *the owner's*, over a
    subject the user had just stated — the false record §7's route exists to
    avoid, reintroduced one layer down.
    """
    event = _event(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="works from the Lisbon office",
        subject="offices",
        about_person="Marta",
    )

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, SemanticMemory)
    assert record.about_person == "Marta"


async def test_the_subject_is_carried_verbatim() -> None:
    """Nothing on the way in normalises a label (ADR-0100 §6)."""
    [proposal] = await _processor().process(_event(about_person="  marta  "))

    assert proposal.proposed.about_person == "  marta  "


@pytest.mark.parametrize("memory_kind", [MemoryKind.PREFERENCE, MemoryKind.SEMANTIC])
async def test_an_unstated_subject_stays_unstated(memory_kind: MemoryKind) -> None:
    """Silence is carried across as silence, never repaired into a name."""
    [proposal] = await _processor().process(_event(memory_kind=memory_kind))

    assert proposal.proposed.about_person is None


async def test_rationale_records_the_feedback() -> None:
    [proposal] = await _processor().process(_event(content="likes tea"))
    assert "likes tea" in proposal.rationale


async def test_deferred_target_does_not_consume_an_id() -> None:
    issued: list[str] = []

    def factory() -> str:
        issued.append(f"id-{len(issued) + 1}")
        return issued[-1]

    processor = RuleBasedFeedbackProcessor(id_factory=factory)

    assert await processor.process(_event(memory_kind=MemoryKind.PROCEDURAL)) == []
    assert issued == []  # a deferred target minted no id

    [proposal] = await processor.process(_event(memory_kind=MemoryKind.PREFERENCE))
    assert proposal.proposed.id == "id-1"  # the first id goes to the first real record


async def test_the_confirming_instant_is_the_utterances_and_not_the_write() -> None:
    """ADR-0109 §4's ``ASSERTED`` arm: the user stating it is the confirming event.

    ``last_confirmed_at`` is ``event.created_at``, so a feedback event re-processed
    a month later does not look freshly confirmed. That is the same discipline
    which keeps ``ATTESTED`` off our ingestion clock and ``DERIVED`` off the moment
    of derivation (ADR-0103 §9).

    The two fields coincide here by construction — this producer already takes its
    transaction stamp from the same event — so no fixture can separate them, which
    ADR-0109 §10 anticipates and exempts. What proves the field is not transaction
    time is the calendar reader's case, whose ``last_updated`` is ``read_at``, and
    the fold's, whose survivor takes the two from different sides. Whether *this*
    producer should be setting transaction time from the event at all is #775, and
    the equality below is deliberately written as an equality with the event rather
    than with ``last_updated``, so a fix there does not silently rewrite this claim.
    """
    when = datetime(2025, 11, 30, 9, 15, tzinfo=UTC)

    [proposal] = await _processor().process(_event(created_at=when))

    assert proposal.proposed.provenance.last_confirmed_at == when


async def test_a_feedback_event_created_in_our_future_is_stored_unchanged() -> None:
    """ADR-0109 §4's fourth clause, at the ``ASSERTED`` producer.

    ``FeedbackEvent.created_at`` has no upper bound, so this producer is separately
    capable of dropping or clamping an instant ahead of its own clock and must do
    neither — the usability test belongs to the fold, where two candidates exist.
    Asserting the exact instant refuses ``None``, a local clock reading and a clamp
    at once.
    """
    ahead = datetime(2027, 4, 1, tzinfo=UTC)

    [proposal] = await _processor().process(_event(created_at=ahead))

    assert proposal.proposed.provenance.last_confirmed_at == ahead
