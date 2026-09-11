"""The canonical engine fake's parked-read surface (ADR-0244 §§4-6, §9, §11).

:class:`~ai_assistant.testing.FakeAssistantEngine` is the double every consumer of
``AssistantEngine`` is certified against, so ADR-0026 §7 binds it to the contract and
not to a convenience: "a fake looser than the contract certifies consumers the real
implementation will reject". Two of ADR-0244's clauses are exactly that shape here —
the establishing act's refusals, which a fake that ignored ``remember_recipients_until``
would let a consumer sail past, and the one-answer rule, which a fake that re-offered a
spent park would hide.

**Lanes 3 and 4 are the consumers this file protects.** ADR-0244 §18 gives the command
line and the browser the floor for a read's confirmation, the exact query, the answer
collected, the seven ``ReadAnswerOutcome`` statements and the cancellation act — and
every one of those is driven against this fake before it is driven against a hub.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.errors import UngrantableActError, UnknownContinuationError
from ai_assistant.core.types import (
    BoundAccount,
    ContinuationToken,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ReadAnswerOutcome,
    ReadCancellation,
    ReadKind,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import FakeAssistantEngine

#: The instant every decision here is recorded at, **before** the fake's own fixed
#: reading: a resolution is decided at or after the confirmation it answers (ADR-0235
#: §4), and the answer this fake stamps carries that reading.
AT: Final = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)

#: The fake's own fixed reading, which every answer it records carries.
ENGINE_NOW: Final = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PATIENT: Final = timedelta(seconds=30)
LATER: Final = ENGINE_NOW + timedelta(days=30)


def _confirm(*, external: bool) -> PermissionDecision:
    """A recorded ``CONFIRM`` over a search call, with or without external footing.

    The two shapes ADR-0235 §2's binding refusal parts: a clean one the act may ride,
    and one carrying ``planned_with_external_content``, which ADR-0193 §4 covers with no
    grant whatever grants exist.
    """
    return PermissionDecision(
        id="decision-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it would leave here"),
        tool=ToolDefinition(
            id="web_search",
            capability="search_web",
            description="Ask one connected search account a question.",
            risk_level=RiskLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            side_effecting=True,
            reads=(),
            writes=(),
            discloses=(DataTier.PERSONAL,),
            cost=ToolCost(basis=CostBasis.FREE),
            idempotency=Idempotency.NATURAL,
        ),
        parameters_digest="d" * 64,
        decided_at=AT,
        egress_binding=EgressBinding(
            spans=(
                EgressSpan(
                    argument="query",
                    index=0,
                    provenance=DiscloserProvenance.SYSTEM_SELECTED,
                    extent=16,
                    destination=EgressDestination(
                        protocol=DestinationProtocol.HTTPS,
                        supplied="search.example",
                        canonical="search.example",
                    ),
                ),
            ),
            account=BoundAccount(reference="search-account", identity="owner@example.com"),
            transport_endpoint="https://search.example",
            planned_with_external_content=external,
            coverage=SpanCoverage.NOT_COVERED,
        ),
    )


async def test_the_question_a_park_offers_carries_the_query_and_the_discriminator() -> None:
    """ADR-0244 §4, §13: the exact query, and ``read`` as the branch a surface takes."""
    engine = FakeAssistantEngine()

    offered = engine.park_read("h-1", query="bell tower porto")

    assert offered.read is ReadKind.WEB_SEARCH
    assert offered.parameters["query"] == "bell tower porto"
    listed = await engine.pending_confirmations()
    assert [one.token.handle for one in listed] == ["h-1"]


async def test_a_parked_read_is_answered_once_and_then_restates() -> None:
    """ADR-0244 §6: "one answer, at most one dispatch, however many times a token is
    presented"."""
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")

    first = await engine.resume(offered.token, approved=True, timeout=PATIENT)
    second = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert first.read_answer is ReadAnswerOutcome.DISPATCHED
    assert first.turn is not None, "ADR-0244 §8's resumed turn, not a step"
    assert second.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert second.turn is None
    assert await engine.pending_confirmations() == ()


async def test_an_establishing_act_on_an_external_binding_is_refused_before_the_answer() -> None:
    """ADR-0026 §7 at its sharpest, on the clause ADR-0244 §5 preserves from ADR-0235 §2.

    A fake that ignored ``remember_recipients_until`` would let a consumer's approval
    land and report a grant the hub refuses — and would consume the question doing it.
    **The park survives**, so the same token answers it again without the argument.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.hold_confirmation_decision("h-1", _confirm(external=True))

    with pytest.raises(UngrantableActError, match="external content"):
        await engine.resume(
            offered.token, approved=True, timeout=PATIENT, remember_recipients_until=LATER
        )

    assert [one.token.handle for one in await engine.pending_confirmations()] == ["h-1"], (
        "nothing was claimed and the question may still be answered (ADR-0235 §2)"
    )


async def test_an_establishing_act_on_a_clean_binding_rides_the_answer() -> None:
    """ADR-0244 §5: "the act still rides an answer where a park holds the confirmation"."""
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    # The answer this act rides ``resolves`` the confirmation, and the trail refuses a
    # resolution of a row it does not hold — so the decision is recorded as well as
    # bound, which is what :meth:`hold_confirmation_decision` says in terms.
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)

    outcome = await engine.resume(
        offered.token, approved=True, timeout=PATIENT, remember_recipients_until=LATER
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.recipient_grant is not None
    established = outcome.recipient_grant.established
    assert established is not None, "the act landed rather than being reported declined"
    assert established.expires_at == LATER, "at the instant the user chose, unrounded"
    assert established.established_by == confirmed.id, (
        "and transcribed from the recorded CONFIRM the answer rode (ADR-0235 §2)"
    )


async def test_a_stale_expiry_is_refused_before_the_answer() -> None:
    """ADR-0235 §1's expiry refusal, on the instant the answer would carry."""
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.hold_confirmation_decision("h-1", _confirm(external=False))

    with pytest.raises(UngrantableActError, match="strictly after"):
        await engine.resume(
            offered.token,
            approved=True,
            timeout=PATIENT,
            remember_recipients_until=ENGINE_NOW - timedelta(days=1),
        )

    assert [one.token.handle for one in await engine.pending_confirmations()] == ["h-1"]


async def test_the_three_cancellation_states_are_each_reachable() -> None:
    """ADR-0244 §11's three members, so a surface rendering one has a way to reach it."""
    engine = FakeAssistantEngine()
    engine.park_read("h-1", query="bell tower porto")
    engine.park_read("h-2", query="something else")
    engine.dispatching_read("h-2")

    assert await engine.cancel_read(ContinuationToken(handle="h-1")) is (ReadCancellation.WITHDRAWN)
    assert await engine.cancel_read(ContinuationToken(handle="h-2")) is (
        ReadCancellation.INTERRUPTED
    )
    assert await engine.cancel_read(ContinuationToken(handle="h-1")) is (
        ReadCancellation.NOTHING_TO_CANCEL
    )


async def test_a_token_this_engine_never_held_is_refused_and_never_denied() -> None:
    """ADR-0084 §7: an unknown token raises, and never answers ``NOTHING_TO_CANCEL``."""
    engine = FakeAssistantEngine()

    with pytest.raises(UnknownContinuationError):
        await engine.cancel_read(ContinuationToken(handle="never-minted"))


@pytest.mark.parametrize("member", list(ReadAnswerOutcome))
async def test_every_read_answer_member_is_reachable_through_the_fake(
    member: ReadAnswerOutcome,
) -> None:
    """ADR-0244 §13: a surface owes a statement per member, so every member is reachable.

    A fake that could produce only the members its own machinery reaches would leave a
    consumer unable to drive the statements ADR-0244 §18 gives Lanes 3 and 4 — which is
    why the dispatching answer's member is scriptable rather than derived.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    approved = member is not ReadAnswerOutcome.DECLINED
    if member is ReadAnswerOutcome.ALREADY_SETTLED:
        await engine.resume(offered.token, approved=True, timeout=PATIENT)
    else:
        engine.read_answers["h-1"] = member

    outcome = await engine.resume(offered.token, approved=approved, timeout=PATIENT)

    assert outcome.read_answer is member
    assert outcome.read_confirmation is None, "ADR-0244 §9's mutual exclusion"
