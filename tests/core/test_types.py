"""Tests for the shared memory domain types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    DataTier,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def test_user_asserted_provenance_must_be_certain() -> None:
    with pytest.raises(ValidationError, match="must have confidence"):
        Provenance(source=MemorySource.USER_ASSERTED, confidence=0.5, last_updated=_WHEN)


def test_user_asserted_provenance_accepts_full_confidence() -> None:
    prov = Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)
    assert prov.confidence == 1.0


def test_inferred_provenance_may_be_uncertain() -> None:
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.5, last_updated=_WHEN)
    assert prov.confidence == 0.5


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Provenance(source=MemorySource.INFERRED, confidence=1.5, last_updated=_WHEN)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"kind": "episodic", "occurred_at": _WHEN}, EpisodicMemory),
        ({"kind": "semantic", "fact": "f"}, SemanticMemory),
        ({"kind": "preference", "preference": "concise"}, PreferenceMemory),
        ({"kind": "procedural", "situation": "s"}, ProceduralMemory),
    ],
)
def test_discriminated_union_resolves_by_kind(
    payload: dict[str, object], expected: type[object]
) -> None:
    adapter: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
    record = adapter.validate_python(
        {
            "id": "1",
            "content": "c",
            "provenance": {"source": "inferred", "confidence": 0.4, "last_updated": _WHEN},
            **payload,
        }
    )
    assert isinstance(record, expected)


def test_merge_decision_requires_target() -> None:
    with pytest.raises(ValidationError, match="requires merge_into"):
        MemoryDecision(kind=MemoryDecisionKind.MERGE, reason="x")


def test_store_temporary_decision_requires_ttl() -> None:
    with pytest.raises(ValidationError, match="requires ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x")


def test_accept_decision_needs_no_extra_fields() -> None:
    decision = MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="ok")
    assert decision.merge_into is None


def test_store_temporary_decision_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValidationError, match="positive ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x", ttl=timedelta(0))
    with pytest.raises(ValidationError, match="positive ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x", ttl=timedelta(days=-1))


def test_decision_rejects_fields_foreign_to_its_kind() -> None:
    with pytest.raises(ValidationError, match="merge_into is only valid"):
        MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="x", merge_into="other")
    with pytest.raises(ValidationError, match="ttl is only valid"):
        MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="x", ttl=timedelta(days=1))


def test_proposal_defaults_to_personal_sensitivity() -> None:
    record = SemanticMemory(
        id="1",
        content="c",
        fact="f",
        provenance=Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN),
    )
    proposal = MemoryUpdateProposal(proposed=record, rationale="because")
    assert proposal.sensitivity is DataTier.PERSONAL
