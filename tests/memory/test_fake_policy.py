"""The canonical FakeMemoryPolicy passes the shared MemoryPolicy conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryPolicy``
as a stand-in for a real policy: it is held to the same contract as
``DefaultMemoryPolicy``.

The suite runs against *every* configured outcome, not just the default one — a
fake that only conforms when left at its defaults would be contract-correct in
tests and a trap in use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from memory_policy_contract import MemoryPolicyContract
from pydantic import ValidationError

from ai_assistant.core.types import (
    DataTier,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import FakeMemoryPolicy

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryPolicy
    from ai_assistant.core.types import MemoryRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _record(record_id: str = "r") -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=record_id,
        fact=record_id,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
    )


def _proposal(*, sensitivity: DataTier = DataTier.PERSONAL) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=_record("proposed"), rationale="because", sensitivity=sensitivity
    )


class TestFakeMemoryPolicyContract(MemoryPolicyContract):
    """Runs the default-configured FakeMemoryPolicy through the shared suite."""

    @pytest.fixture
    def policy(self) -> MemoryPolicy:
        return FakeMemoryPolicy()


@pytest.mark.parametrize("kind", list(MemoryDecisionKind))
class TestFakeMemoryPolicyContractEveryKind(MemoryPolicyContract):
    """Runs FakeMemoryPolicy through the shared suite at every configured kind."""

    @pytest.fixture
    def policy(self, kind: MemoryDecisionKind) -> MemoryPolicy:
        return FakeMemoryPolicy(kind)


# Behaviour specific to FakeMemoryPolicy, beyond the shared contract.


async def test_returns_the_configured_kind() -> None:
    policy = FakeMemoryPolicy(MemoryDecisionKind.REJECT)

    decision = await policy.decide(_proposal(), conflicts=[])

    assert decision.kind is MemoryDecisionKind.REJECT


@pytest.mark.parametrize(
    "kind", [MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE], ids=str
)
async def test_fold_without_conflicts_falls_back_to_accept(kind: MemoryDecisionKind) -> None:
    policy = FakeMemoryPolicy(kind)

    decision = await policy.decide(_proposal(), conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT
    assert "fold" in decision.reason


async def test_secret_tier_overrides_the_configured_kind() -> None:
    policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)

    decision = await policy.decide(_proposal(sensitivity=DataTier.SECRET), conflicts=[])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_store_temporary_uses_the_configured_ttl() -> None:
    ttl = timedelta(hours=3)
    policy = FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=ttl)

    decision = await policy.decide(_proposal(), conflicts=[])

    assert decision.ttl == ttl


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_ttl_is_rejected_at_construction(ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="ttl must be positive"):
        FakeMemoryPolicy(ttl=ttl)


async def test_records_every_call_in_order() -> None:
    policy = FakeMemoryPolicy()
    first, second = _proposal(), _proposal(sensitivity=DataTier.OPERATIONAL)

    await policy.decide(first, conflicts=[])
    await policy.decide(second, conflicts=[_record("c")])

    assert policy.call_count == 2
    assert [c.proposal for c in policy.calls] == [first, second]
    assert policy.last_proposal == second


async def test_recorded_conflicts_survive_the_caller_clearing_the_list() -> None:
    policy = FakeMemoryPolicy()
    conflicts = [_record("c")]

    await policy.decide(_proposal(), conflicts=conflicts)
    conflicts.clear()

    assert len(policy.calls[0].conflicts) == 1


async def test_recorded_call_is_immune_to_caller_mutation() -> None:
    # ADR-0068 freezes the record graph, so a caller reusing a record or proposal
    # after the call cannot rewrite the fake's recorded history: the snapshot is
    # subsumed by immutability rather than defended by copying.
    policy = FakeMemoryPolicy()
    proposal = _proposal()
    conflict = _record("original")

    await policy.decide(proposal, conflicts=[conflict])
    with pytest.raises(ValidationError):
        conflict.id = "changed"
    with pytest.raises(ValidationError):
        proposal.rationale = "rewritten"

    assert policy.calls[0].conflicts[0].id == "original"
    assert policy.last_proposal.rationale == "because"


def test_last_proposal_raises_before_any_call() -> None:
    # The property is documented to raise on an unused fake rather than invent a
    # value; a regression returning None or a stale proposal would otherwise let
    # an assertion about "the last call" pass with no call having happened.
    with pytest.raises(IndexError):
        _ = FakeMemoryPolicy().last_proposal


# `test_decide_does_not_mutate_its_inputs` moved to the shared `MemoryPolicyContract`
# (ADR-0068 §5), which runs it against this fake too.


async def test_decision_carries_a_non_blank_reason() -> None:
    # Also not in the shared suite (TODO item 7): `reason=""` passes the model,
    # so requiring otherwise would be the suite inventing an obligation. This
    # implementation does explain itself, and that is worth pinning here.
    decision = await FakeMemoryPolicy().decide(_proposal(), conflicts=[])

    assert decision.reason.strip()
