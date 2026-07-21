"""Tests for the memory ingestor (conflict detection + policy + application)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor

if TYPE_CHECKING:
    from collections.abc import Sequence

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


class _RecordingPolicy:
    """A policy that records the conflicts it was offered and rejects everything."""

    def __init__(self) -> None:
        self.conflicts: list[list[str]] = []

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        self.conflicts.append([record.id for record in conflicts])
        return MemoryDecision(kind=MemoryDecisionKind.REJECT, reason="test recording")


async def test_proposal_itself_does_not_consume_a_conflict_slot() -> None:
    """Excluding the proposal must not cost a slot the limit already spent (#110).

    The store applies ``conflict_limit`` before the ingestor can drop the
    proposal's own record, so at ``conflict_limit=1`` a re-proposal used to leave
    the policy seeing no conflict at all — while a genuine one sat just below it.
    """
    store = InMemoryMemoryStore()
    # Added self-first so the equally-scoring pair ranks it above the rival: the
    # exact order in which the old code discarded the only slot it fetched.
    await store.add(_preference("self", "prefers concise emails"))
    await store.add(_preference("rival", "prefers concise emails"))
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=1, now=_fixed_now)

    await ingestor.ingest(_proposal(_preference("self", "prefers concise emails")))

    assert policy.conflicts == [["rival"]]


async def test_conflicts_offered_never_exceed_the_limit() -> None:
    """Over-fetching to make room for the exclusion must not widen the limit."""
    store = InMemoryMemoryStore()
    for index in range(3):
        await store.add(_preference(f"existing-{index}", "prefers concise emails"))
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=2, now=_fixed_now)

    await ingestor.ingest(_proposal(_preference("new", "prefers concise emails")))

    assert policy.conflicts == [["existing-0", "existing-1"]]


class _MergeToAbsentTargetPolicy:
    """A policy that always asks to merge into a record that isn't a conflict."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        return MemoryDecision(
            kind=MemoryDecisionKind.MERGE, merge_into="ghost", reason="test misdirection"
        )


async def test_merge_into_absent_target_raises_and_stores_nothing() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(store=store, policy=_MergeToAbsentTargetPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="not among the conflicts"):
        await ingestor.ingest(_proposal(_semantic("1", "some fact", confidence=0.9)))

    assert await store.get("1") is None  # nothing was silently stored as new


class _MaxTtlPolicy:
    """A policy whose STORE_TEMPORARY ttl overflows the representable date range."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        return MemoryDecision(
            kind=MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta.max, reason="test overflow"
        )


async def test_overflowing_temporary_ttl_raises_and_stores_nothing() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(store=store, policy=_MaxTtlPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="overflows"):
        await ingestor.ingest(_proposal(_semantic("1", "some fact", confidence=0.9)))

    assert await store.get("1") is None


async def test_low_confidence_is_stored_temporarily_with_expiry() -> None:
    # The store shares the ingestor's fixed clock, so the just-stamped expiry
    # (a week out) is still in the future and the record remains retrievable.
    store = InMemoryMemoryStore(now=_fixed_now)

    result = await _ingestor(store).ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert result.decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    stored = await store.get("1")
    assert stored is not None
    # _fixed_now (2026-06-01) + the policy's 7-day TTL.
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)


async def test_a_naive_clock_cannot_leak_a_naive_expiry() -> None:
    """``_expiry`` installs ``expires_at`` through ``model_copy``, which skips
    validators — so the clock is the only place this can be caught.

    ``LearningLoop`` already guards the identical write and says why; this path
    did not, and since ADR-0023 makes ``MemoryBase.expires_at`` reject a naive
    value rather than assume UTC, there is no longer a validator behind it. The
    boundary shim ADR-0023 §6 requires until ADR-0026's producer guard lands.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    naive_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1),  # noqa: DTZ001 — the naive clock is the subject
    )

    await naive_clock.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    stored = await store.get("1")
    assert stored is not None
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)


async def test_a_non_utc_clock_stamps_the_same_instant() -> None:
    """Conversion is information-preserving, so only the representation moves."""
    store = InMemoryMemoryStore(now=_fixed_now)
    berlin_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=timezone(timedelta(hours=2))),
    )

    await berlin_clock.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    stored = await store.get("1")
    assert stored is not None
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)
