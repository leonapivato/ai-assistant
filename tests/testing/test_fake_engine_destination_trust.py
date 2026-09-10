"""The canonical fake's trust act, where it could drift from a production engine (#2203).

:class:`~ai_assistant.testing.FakeAssistantEngine` passes the shared
``AssistantEngine`` suite, and that suite holds it to what ADR-0242 §2 and §4 bind on
**every** implementation over a store holding nothing. What it deliberately does not
hold it to is what a *populated* store does — those clauses are about a trail and a
store the fake seeds itself — and that is exactly where a fake can be quietly stricter
than the engine every consumer's test stands in for.

**Two divergences are pinned here because a first draft of this lane had both.** The
fake minted a record id from the *decision* id, so a second act on one decision hit
ADR-0238 §1's write-once refusal: a repeat while the first record was live raised the
**base** class where §2 fixes the subclass — making the *already chosen* rendering
unreachable in a consumer's test — and a repeat **after a revocation** failed outright,
where a production engine succeeds because ADR-0242 §1 makes the act indifferent to a
decision's ruling and resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.errors import DuplicateDestinationTrustError
from ai_assistant.core.types import (
    BoundAccount,
    CostBasis,
    DestinationProtocol,
    DestinationTrust,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import FakeAssistantEngine

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)
_ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-0001")


def _decision(decision_id: str, *, canonical: str = "a@example.com") -> PermissionDecision:
    """One recorded ``CONFIRM`` the trust act may ride (ADR-0242 §1's three conditions)."""
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="within policy"),
        tool=ToolDefinition(
            id="smtp",
            capability="send_email",
            description="Send an email.",
            risk_level=RiskLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            side_effecting=True,
            reads=(),
            writes=(),
            discloses=(),
            cost=ToolCost(basis=CostBasis.FREE),
            idempotency=Idempotency.NATURAL,
        ),
        parameters_digest="d" * 64,
        decided_at=_AT,
        egress_binding=EgressBinding(
            spans=(
                EgressSpan(
                    argument="to",
                    index=0,
                    provenance=DiscloserProvenance.SYSTEM_SELECTED,
                    extent=13,
                    destination=EgressDestination(
                        protocol=DestinationProtocol.SMTP,
                        supplied=canonical,
                        canonical=canonical,
                    ),
                ),
            ),
            account=_ACCOUNT,
            transport_endpoint="smtp://mail.example.com:587",
            planned_with_external_content=False,
            coverage=SpanCoverage.NOT_COVERED,
        ),
    )


async def _seeded(*decisions: PermissionDecision) -> FakeAssistantEngine:
    """A fake engine whose trail holds ``decisions``."""
    engine = FakeAssistantEngine()
    for decision in decisions:
        await engine.trail.record(decision)
    return engine


async def test_a_second_act_over_one_live_set_raises_the_discriminating_subclass() -> None:
    """ADR-0242 §2's one moved refusal type, reachable through the fake.

    A surface reads *already chosen* from the **type** and from nothing else — no message
    parsed, no ``standing_destination_trust`` read taken afterwards. A fake raising the
    base class here would make that rendering unreachable in every consumer's test while
    passing every arm the shared suite carries.
    """
    engine = await _seeded(_decision("d-1"), _decision("d-2"))
    await engine.establish_destination_trust("d-1")

    with pytest.raises(DuplicateDestinationTrustError):
        await engine.establish_destination_trust("d-2")

    assert len(await engine.standing_destination_trust()) == 1


async def test_the_same_decision_may_be_trusted_again_after_a_revocation() -> None:
    """ADR-0242 §1: the act is indifferent to a decision's ruling and resolution.

    "A user may record trust from a decision they answered a month ago", and nothing in
    §1 makes a decision spent by having been used once — ADR-0238 §1's write-once rule is
    about the *record's* id, which the engine mints, not about the decision's. A fake
    reusing the decision's id would refuse the second act outright, so a consumer's test
    for *revoke, then choose again* would fail against the fake and pass against a hub.
    """
    engine = await _seeded(_decision("d-1"))
    first = await engine.establish_destination_trust("d-1")
    assert await engine.revoke_destination_trust(first.id) is True

    second = await engine.establish_destination_trust("d-1")

    assert second.id != first.id, "a fresh record per act, as the production engine mints"
    assert [record.id for record in await engine.standing_destination_trust()] == [second.id]


async def test_two_acts_over_different_sets_both_stand() -> None:
    """ADR-0238 §1: what is refused is a second record that **is** the first.

    "Not one that shares a member with it — so a store refusing on overlap would refuse
    an act the user is entitled to make." The fake's ids must therefore differ per act
    even where no revocation has happened.
    """
    engine = await _seeded(_decision("d-1"), _decision("d-2", canonical="b@example.com"))

    first = await engine.establish_destination_trust("d-1")
    second = await engine.establish_destination_trust("d-2")

    assert first.id != second.id
    assert {record.id for record in await engine.standing_destination_trust()} == {
        first.id,
        second.id,
    }
    assert first.trust is second.trust is DestinationTrust.USER_CHOSEN
