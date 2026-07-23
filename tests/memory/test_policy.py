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


async def test_user_assertion_supersedes_a_conflicting_inference() -> None:
    # ADR-0038: the correction must displace the stale belief, not land beside
    # it. Before this rule the ACCEPT above fired first and both stayed live.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    stale = _semantic("stale", source=MemorySource.INFERRED, confidence=0.6)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[stale])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "stale"


async def test_user_assertion_supersedes_the_best_ranked_inference_not_an_assertion() -> None:
    # `conflicts` is score-ordered, so the highest-ranked conflict can be a
    # user-asserted record. Superseding it would destroy something the user
    # said on the strength of a lexical match; the rule skips to the first
    # non-asserted candidate instead (ADR-0038 §3).
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    conflicts = [
        _semantic("their-words", source=MemorySource.USER_ASSERTED, confidence=1.0),
        _semantic("our-guess", source=MemorySource.OBSERVED, confidence=0.6),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "our-guess"


async def test_user_assertion_does_not_supersede_an_external_record() -> None:
    # ADR-0038 §2a: supersedable is an allow-list of OBSERVED/INFERRED, not
    # "anything that is not USER_ASSERTED". Merging into an external record
    # would give the correction that system's idempotency key, and the next
    # sync would overwrite it (see the ingest-level test). Pinned because
    # `is not MemorySource.USER_ASSERTED` is the natural-looking simplification
    # that reintroduces the hole.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    imported = _semantic("imported", source=MemorySource.EXTERNAL, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[imported])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_user_assertion_skips_an_external_conflict_to_supersede_an_inference() -> None:
    # The allow-list scans, it does not stop at the first entry: an external
    # record ranked above an inference must be passed over, not treated as a
    # reason to abandon supersession altogether.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    conflicts = [
        _semantic("imported", source=MemorySource.EXTERNAL, confidence=1.0),
        _semantic("our-guess", source=MemorySource.INFERRED, confidence=0.6),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "our-guess"


async def test_external_proposal_conflicting_with_an_assertion_defers() -> None:
    # Rule 2, restated for EXTERNAL specifically: a sync is a non-asserted
    # proposal, so it may not silently overwrite what the user told us.
    proposal = _proposal(_semantic("sync", source=MemorySource.EXTERNAL, confidence=1.0))
    corrected = _semantic("corrected", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[corrected])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_user_assertion_conflicting_only_with_assertions_is_accepted() -> None:
    # Two things the user said, both at confidence 1.0: nothing ranks them, and
    # the conflict signal is not strong enough to destroy either. Accept beside
    # (ADR-0038 §5) — deliberately unchanged from the pre-ADR behaviour.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    earlier = _semantic("earlier", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_secret_tier_assertion_still_defers_before_superseding() -> None:
    # Rule 1 outranks supersession: a secret-tier correction must not silently
    # overwrite a record on its way to being confirmed.
    proposal = _proposal(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        sensitivity=DataTier.SECRET,
    )
    stale = _semantic("stale", source=MemorySource.INFERRED, confidence=0.6)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[stale])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_conflict_with_non_asserted_merges() -> None:
    proposal = _proposal(_semantic("new"))
    existing = _semantic("existing")

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[existing])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "existing"


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


async def test_decide_does_not_mutate_its_inputs() -> None:
    # Not part of the shared suite: the MemoryPolicy Protocol does not promise
    # this, and a conformance suite may not invent obligations (TODO item 7
    # tracks ratifying it). It is still true of this policy, which holds no state
    # and only reads its arguments.
    conflicts = [_semantic("existing")]
    proposal = _proposal(_semantic("new"))
    proposal_before = proposal.model_copy(deep=True)
    conflicts_before = [c.model_copy(deep=True) for c in conflicts]

    await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert proposal == proposal_before
    assert conflicts == conflicts_before


async def test_decision_carries_a_non_blank_reason() -> None:
    # Also not in the shared suite (TODO item 7): `reason=""` passes the model,
    # so requiring otherwise would be the suite inventing an obligation. This
    # implementation does explain itself, and that is worth pinning here.
    decision = await DefaultMemoryPolicy().decide(_proposal(_semantic("new")), conflicts=[])

    assert decision.reason.strip()
