"""Tests for the default memory policy.

The universal ``MemoryPolicy`` obligations live in ``memory_policy_contract.py``
and are run against this policy by :class:`TestDefaultMemoryPolicyContract`. What
remains here is what makes *this* policy the default one: its specific rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from memory_policy_contract import MemoryPolicyContract

from ai_assistant.core.types import (
    DataTier,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import DefaultMemoryPolicy

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryPolicy

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _semantic(
    record_id: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=record_id,
        fact=record_id,
        provenance=Provenance(source=source, confidence=confidence, last_updated=_WHEN),
    )


def _proposal(
    record: MemoryRecord,
    *,
    sensitivity: DataTier = DataTier.PERSONAL,
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=sensitivity)


class TestDefaultMemoryPolicyContract(MemoryPolicyContract):
    """Runs DefaultMemoryPolicy through the shared MemoryPolicy conformance suite."""

    @pytest.fixture
    def policy(self) -> MemoryPolicy:
        return DefaultMemoryPolicy()


async def test_secret_tier_defers_to_user() -> None:
    proposal = _proposal(_semantic("s"), sensitivity=DataTier.SECRET)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_inference_conflicting_with_asserted_defers_to_user() -> None:
    proposal = _proposal(_semantic("new", source=MemorySource.INFERRED, confidence=0.9))
    asserted = _semantic("old", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[asserted])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_user_asserted_is_accepted() -> None:
    proposal = _proposal(_semantic("a", source=MemorySource.USER_ASSERTED, confidence=1.0))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_conflict_with_non_asserted_merges() -> None:
    proposal = _proposal(_semantic("new"))
    existing = _semantic("existing")

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[existing])

    assert decision.kind is MemoryDecisionKind.MERGE
    assert decision.merge_into == "existing"


async def test_low_confidence_is_stored_temporarily() -> None:
    proposal = _proposal(_semantic("weak", confidence=0.1))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    assert decision.ttl is not None


async def test_confident_and_unconflicted_is_accepted() -> None:
    proposal = _proposal(_semantic("ok", confidence=0.9))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_temporary_ttl_is_rejected_at_construction(ttl: timedelta) -> None:
    # Without this guard the policy builds fine and raises later from `decide`,
    # and only for a low-confidence proposal — a crash far from its cause. Both
    # zero and negative are checked: a guard narrowed to `== 0` would let a
    # negative window through and restore exactly that delayed failure.
    with pytest.raises(ValueError, match="temporary_ttl must be positive"):
        DefaultMemoryPolicy(temporary_ttl=ttl)
