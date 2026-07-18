"""Tests for the RuleBasedFeedbackProcessor (feedback -> memory proposal)."""

from __future__ import annotations

from datetime import UTC, datetime

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


def _processor() -> RuleBasedFeedbackProcessor:
    return RuleBasedFeedbackProcessor(id_factory=lambda: "rec-1")


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
    assert record.provenance.evidence == ["ep-9"]
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


async def test_rationale_records_the_feedback() -> None:
    [proposal] = await _processor().process(_event(content="likes tea"))
    assert "likes tea" in proposal.rationale
