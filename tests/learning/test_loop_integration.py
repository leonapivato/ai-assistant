"""The first closed learning loop, end to end.

Composes the *real* learning processor and the *real* memory write-path (no
fakes) to prove the vertical from ADR-0009: an explicit correction becomes a
durable memory the system can reuse. Once `orchestration` exists it will wire
these steps automatically; this test stands in for that wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_assistant.core.types import (
    FeedbackEvent,
    FeedbackKind,
    MemoryDecisionKind,
    MemoryKind,
    PreferenceMemory,
)
from ai_assistant.learning import RuleBasedFeedbackProcessor
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


async def test_feedback_becomes_a_reusable_memory() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(store=store, policy=DefaultMemoryPolicy())
    processor = RuleBasedFeedbackProcessor(id_factory=lambda: "pref-1")

    # 1. The user gives explicit feedback.
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers concise replies",
        subject="email tone",
        created_at=_WHEN,
    )

    # 2. Learning proposes; 3. the policy disposes; 4. the store persists.
    [proposal] = await processor.process(event)
    result = await ingestor.ingest(proposal)

    assert result.decision.kind is MemoryDecisionKind.ACCEPT  # user-asserted -> accepted
    assert result.record_id == "pref-1"

    # 5. The preference is now retrievable — the loop can reuse it next time.
    stored = await store.get("pref-1")
    assert isinstance(stored, PreferenceMemory)
    assert stored.preference == "prefers concise replies"
    assert [r.id for r in await store.search("concise")] == ["pref-1"]
