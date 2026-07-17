"""Tests for the memory ingestor (conflict detection + policy + application)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_assistant.core.types import (
    DataTier,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _prov(confidence: float, evidence: tuple[str, ...] = ()) -> Provenance:
    return Provenance(
        source=MemorySource.OBSERVED,
        confidence=confidence,
        last_updated=_WHEN,
        evidence=list(evidence),
    )


def _semantic(record_id: str, content: str, *, confidence: float = 0.6) -> MemoryRecord:
    return SemanticMemory(id=record_id, content=content, fact=content, provenance=_prov(confidence))


def _preference(
    record_id: str,
    content: str,
    *,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (),
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_prov(confidence, evidence)
    )


def _proposal(
    record: MemoryRecord, *, sensitivity: DataTier = DataTier.PERSONAL
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=sensitivity)


def _ingestor(store: InMemoryMemoryStore) -> MemoryIngestor:
    return MemoryIngestor(store=store, policy=DefaultMemoryPolicy(), now=_fixed_now)


async def test_accepts_and_stores_a_novel_memory() -> None:
    store = InMemoryMemoryStore()

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "unique gardening fact", confidence=0.9))
    )

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert result.record_id == "1"
    assert await store.get("1") is not None


async def test_secret_proposal_is_deferred_and_not_stored() -> None:
    store = InMemoryMemoryStore()

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "a secret", confidence=0.9), sensitivity=DataTier.SECRET)
    )

    assert result.decision.kind is MemoryDecisionKind.ASK_USER
    assert result.record_id is None
    assert await store.get("1") is None


async def test_conflicting_proposal_merges_into_existing() -> None:
    store = InMemoryMemoryStore()
    await store.add(_preference("e", "prefers concise emails", confidence=0.5, evidence=("ev1",)))

    result = await _ingestor(store).ingest(
        _proposal(_preference("new", "prefers concise emails", confidence=0.7, evidence=("ev2",)))
    )

    assert result.decision.kind is MemoryDecisionKind.MERGE
    assert result.record_id == "e"
    merged = await store.get("e")
    assert merged is not None
    assert merged.provenance.confidence == 0.7  # max of the two
    assert set(merged.provenance.evidence) == {"ev1", "ev2"}
    assert await store.get("new") is None  # merged in place, not duplicated


async def test_low_confidence_is_stored_temporarily_with_expiry() -> None:
    store = InMemoryMemoryStore()

    result = await _ingestor(store).ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert result.decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    stored = await store.get("1")
    assert stored is not None
    # _fixed_now (2026-06-01) + the policy's 7-day TTL.
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)
