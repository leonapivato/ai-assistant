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


@pytest.mark.parametrize(
    "member",
    [
        ReadAnswerOutcome.UNAVAILABLE_NOW,
        ReadAnswerOutcome.OPERATION_CHANGED,
        ReadAnswerOutcome.EXPIRED,
    ],
)
async def test_an_outcome_that_rules_nothing_records_nothing_and_establishes_nothing(
    member: ReadAnswerOutcome,
) -> None:
    """ADR-0244 §9: four members say in terms that **nothing was ruled**.

    ``UNAVAILABLE_NOW`` — "nothing was ruled and nothing was dispatched";
    ``OPERATION_CHANGED`` on its subject and binding grounds — "no ruling recorded";
    ``EXPIRED`` — "the settlement records no ruling" (§10). A fake that recorded an
    ``ALLOW`` and established a grant and *then* returned one of them would certify a
    consumer against a trail no hub writes, and would tell a user a standing request
    landed on an answer that was never given.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = member

    outcome = await engine.resume(
        offered.token, approved=True, timeout=PATIENT, remember_recipients_until=LATER
    )

    assert outcome.read_answer is member
    assert outcome.recipient_grant is None, "no act landed on an answer nobody gave"
    assert await engine.standing_recipient_grants() == ()
    assert [row.id for row in await engine.export_decisions()] == [confirmed.id], (
        "and the trail holds the CONFIRM alone: nothing resolved it"
    )


async def test_an_authority_changed_answer_records_its_ruling_and_declines_the_act() -> None:
    """ADR-0244 §9's one member that rules **and** refuses.

    "``ActionPolicy.resolve`` answered other than an ``ALLOW`` at the instant of the
    answer; the ruling **is** recorded" — ADR-0004 §7's reason — "nothing was dispatched,
    and the park is spent". A grant cannot be established from a ruling that is not an
    ``ALLOW``, so the act's carrier is ``DECLINED`` (ADR-0235 §4).
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = ReadAnswerOutcome.AUTHORITY_CHANGED

    outcome = await engine.resume(
        offered.token, approved=True, timeout=PATIENT, remember_recipients_until=LATER
    )

    assert outcome.read_answer is ReadAnswerOutcome.AUTHORITY_CHANGED
    assert outcome.recipient_grant is not None
    assert outcome.recipient_grant.established is None
    assert outcome.recipient_grant.not_established is not None, "the act is reported declined"
    resolutions = [row for row in await engine.export_decisions() if row.resolves == confirmed.id]
    assert len(resolutions) == 1, "and the ruling **is** recorded"
    assert resolutions[0].ruling.outcome is not PermissionOutcome.ALLOW


async def test_an_interrupted_dispatch_leaves_no_question_to_answer_again() -> None:
    """ADR-0244 §11: "a cancelled dispatch leaves the park ``APPROVED`` and does not
    re-open it".

    A dispatch is only ever reached **after** the park was settled, so a fake that left
    the question listed would offer one already answered — and a consumer would read
    ``INTERRUPTED`` beside a park it could answer a second time, which is the one state
    §11 says is not reachable.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.dispatching_read("h-1")

    assert await engine.cancel_read(offered.token) is ReadCancellation.INTERRUPTED

    assert await engine.pending_confirmations() == (), "the question is not offered again"
    answered = await engine.resume(offered.token, approved=True, timeout=PATIENT)
    assert answered.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert answered.turn is None, "and nothing was dispatched a second time"


@pytest.mark.parametrize("external", [False, True], ids=["clean_binding", "external_content"])
async def test_an_ordinary_approval_runs_no_standing_grant_check(external: bool) -> None:
    """ADR-0244 §5, ADR-0235 §2: **the act's conditions bind the act and nothing else.**

    An ordinary approval requests no standing authority, so nothing about a grant may be
    tested for it — a user must be able to approve a lookup without being told their
    binding cannot carry a grant they never asked for. Driven over **both** binding
    shapes, because it is the external-content one that a grant may never ride and the
    one an implementation testing eligibility unconditionally would refuse: #2221's own
    row, and the case this whole decision exists to make answerable.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=external)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)

    outcome = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.recipient_grant is None, "no act was collected, so none is reported"
    resolutions = [row for row in await engine.export_decisions() if row.resolves == confirmed.id]
    assert len(resolutions) == 1, "and the answer **is** recorded"
    assert resolutions[0].ruling.outcome is PermissionOutcome.ALLOW


async def test_the_instant_the_expiry_was_checked_against_is_the_one_the_answer_carries() -> None:
    """ADR-0235 §1: **one clock reading, used for both the comparison and the record.**

    Two readings admit an expiry that passes the check and then fails against a later
    one, and the cost is precisely the failure §1 exists to remove: the question is gone,
    no resolution is recorded, and the user has nothing to retry. Driven with an
    **advancing** clock, which a fixed-clock case cannot reach.
    """
    readings = iter(
        [
            datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, 4, tzinfo=UTC),
        ]
    )
    engine = FakeAssistantEngine()
    engine.recipient_grant_clock = lambda: next(readings)
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)

    outcome = await engine.resume(
        offered.token,
        approved=True,
        timeout=PATIENT,
        # After the first reading and before the second: an implementation reading twice
        # passes the check and then refuses, with the question already consumed.
        remember_recipients_until=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.recipient_grant is not None
    assert outcome.recipient_grant.established is not None, "the act landed"


@pytest.mark.parametrize(
    "member", [ReadAnswerOutcome.UNAVAILABLE_NOW, ReadAnswerOutcome.OPERATION_CHANGED]
)
async def test_a_refusal_that_precedes_the_gate_leaves_the_question_standing(
    member: ReadAnswerOutcome,
) -> None:
    """ADR-0244 §6: the availability clauses are taken **before** the gate.

    §9 says it member by member — ``UNAVAILABLE_NOW`` is clause 2's and
    ``OPERATION_CHANGED``'s first two grounds are clause 4's, and "a park spent on an
    answer the subject check would have refused is an answer the user has to give again
    for no reason". A fake that consumed the question on either would certify a consumer
    against a recovery the hub does not have: the retry it was told to make would meet
    ``ALREADY_SETTLED``, and the enumeration it falls back on would list nothing.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.read_answers["h-1"] = member

    refused = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert refused.read_answer is member
    assert [one.token.handle for one in await engine.pending_confirmations()] == ["h-1"], (
        "the question is still offered"
    )

    del engine.read_answers["h-1"]
    retried = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert retried.read_answer is ReadAnswerOutcome.DISPATCHED, "and the retry answers it"


# --- the whole read-answer surface, as one table ------------------------------
#
# **A probe rather than another arm** (ADR-0243 §1). Four review rounds found four
# separate defects on this one path, and three of them were introduced by the previous
# round's fix to it: each round pinned the arm it was about and left the neighbouring
# cells unstated, so the next patch was free to move one. What follows states the whole
# product at once — the park's state, the user's answer, the scripted member, whether a
# decision is bound, whether an act was asked for and what its binding carries — as five
# properties over every cell, so a change that moves any of them fails here rather than
# in the round after next.


_SCRIPTABLE: Final = tuple(ReadAnswerOutcome)


@pytest.mark.parametrize("member", _SCRIPTABLE)
@pytest.mark.parametrize("bound", [False, True], ids=["no_decision", "decision_bound"])
async def test_the_read_answer_surface_holds_its_five_properties(
    member: ReadAnswerOutcome, *, bound: bool
) -> None:
    """Five properties, over every scripted member and both binding states.

    1. **The member returned is the member scripted**, on an approving answer over an
       open park (ADR-0244 §9's deterministic order, held by the fake by construction).
    2. **The question stands afterwards exactly where the member's ground precedes the
       gate** (§6): ``UNAVAILABLE_NOW`` and ``OPERATION_CHANGED`` leave it, every other
       member spends it.
    3. **A resolution is recorded exactly for the three members that carry a ruling**
       (§9), and only where a decision is bound for one to answer.
    4. **The act's carrier is present exactly where a resolution was recorded**, because
       ADR-0235 §4 makes every one of its members an assertion about a recorded answer.
    5. **Nothing is dispatched on any member but** ``DISPATCHED``: the outcome carries no
       turn and no reply, which is ADR-0170 §4's second shape (§9, §10).
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    if bound:
        await engine.trail.record(confirmed)
        engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = member

    # The act is asked for exactly where a decision is bound for it to ride: §2's first
    # shape refuses an approving answer over a park with none, which is its own arm
    # above, and the product here is about what the *answer* does.
    outcome = await engine.resume(
        offered.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=LATER if bound else None,
    )

    spends = member not in {
        ReadAnswerOutcome.UNAVAILABLE_NOW,
        ReadAnswerOutcome.OPERATION_CHANGED,
    }
    rules = member in {
        ReadAnswerOutcome.DISPATCHED,
        ReadAnswerOutcome.DECLINED,
        ReadAnswerOutcome.AUTHORITY_CHANGED,
    }
    listed = [one.token.handle for one in await engine.pending_confirmations()]
    resolutions = [row for row in await engine.export_decisions() if row.resolves == confirmed.id]

    assert outcome.read_answer is member, "1. the member returned is the member scripted"
    assert listed == ([] if spends else ["h-1"]), (
        "2. the question stands exactly where the member's ground precedes the gate"
    )
    assert len(resolutions) == (1 if rules and bound else 0), (
        "3. a resolution is recorded exactly for the members that carry a ruling"
    )
    assert (outcome.recipient_grant is not None) == (rules and bound), (
        "4. the act's carrier is present exactly where a resolution was recorded"
    )
    if member is not ReadAnswerOutcome.DISPATCHED:
        assert outcome.turn is None, "5. nothing but DISPATCHED carries a turn"
        assert outcome.reply is None, "5. nor a reply"


@pytest.mark.parametrize("member", _SCRIPTABLE)
async def test_a_declining_answer_reaches_declined_whatever_was_scripted(
    member: ReadAnswerOutcome,
) -> None:
    """A refusal is the **user's** and not the deployment's (ADR-0042 §4, ADR-0244 §10).

    "Only ``approved=False -> DENY`` is guaranteed", so a declining answer over an open
    park is ``DECLINED`` whatever a case scripted for the approving one — and the
    ``DENY`` is recorded exactly as it is today.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = member

    outcome = await engine.resume(offered.token, approved=False, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.DECLINED
    assert await engine.pending_confirmations() == (), "the park is spent either way"
    resolutions = [row for row in await engine.export_decisions() if row.resolves == confirmed.id]
    assert [row.ruling.outcome for row in resolutions] == [PermissionOutcome.DENY]


@pytest.mark.parametrize("member", _SCRIPTABLE)
@pytest.mark.parametrize("external", [False, True], ids=["clean_binding", "external_content"])
async def test_an_ordinary_approval_is_unaffected_by_the_binding_or_the_script(
    member: ReadAnswerOutcome, *, external: bool
) -> None:
    """The property the fourth round's defect broke, stated over the whole product.

    An approval that asks for nothing standing tests nothing about a grant, whatever the
    binding carries and whatever member the deployment reaches — which is ADR-0244 §5's
    "the act still rides an answer" read the other way: what rides an answer is the act,
    and an answer with no act rides nothing.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=external)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = member

    outcome = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is member, "the answer landed rather than being refused"
    assert outcome.recipient_grant is None, "and no act was collected, so none is reported"


# --- the second answer, which is the axis round 5 found the table missing -----
#
# The table above states what the **first** answer does over the whole product; these
# state what a **second** one does, which is the axis every one of round 5's findings
# lived on. It is one axis rather than three arms for the diagnosis's own reason: three
# arms would pin three cells and leave the rest free to move again.


@pytest.mark.parametrize("member", _SCRIPTABLE)
async def test_a_second_answer_restates_the_terminal_fact_and_performs_nothing(
    member: ReadAnswerOutcome,
) -> None:
    """ADR-0244 §6 and §9, over every member the first answer could have reached.

    **The member is the park's own terminal disposition**: §9 states ``EXPIRED`` over the
    disposition "whether this call settled it or an earlier read did", and every other
    terminal member reads as ``ALREADY_SETTLED`` — "the park was answered, denied or
    cancelled before this answer arrived". A fake remembering only *that* a question was
    gone would report an expired one as merely settled, and a surface would render the
    wrong one of two fixed statements.

    **And it performs nothing**: no policy is consulted, no channel opened, nothing
    recorded and nothing minted, so the trail holds exactly what the first answer left.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    confirmed = _confirm(external=False)
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)
    engine.read_answers["h-1"] = member
    first = await engine.resume(offered.token, approved=True, timeout=PATIENT)
    rows = len(await engine.export_decisions())
    if first.read_answer not in _SETTLING:
        pytest.skip(f"{member} leaves the question standing; the first-answer table has it")

    second = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert second.read_answer is (
        ReadAnswerOutcome.EXPIRED
        if member is ReadAnswerOutcome.EXPIRED
        else ReadAnswerOutcome.ALREADY_SETTLED
    )
    assert second.turn is None, "a duplicate answer performs nothing"
    assert second.reply is None
    assert second.recipient_grant is None
    assert len(await engine.export_decisions()) == rows, "and records nothing further"


#: The members that take the question, so the second-answer case knows which cells have
#: a second answer to make. The complement is the first-answer table's subject.
_SETTLING: Final = frozenset(
    {
        ReadAnswerOutcome.DISPATCHED,
        ReadAnswerOutcome.DECLINED,
        ReadAnswerOutcome.AUTHORITY_CHANGED,
        ReadAnswerOutcome.EXPIRED,
        ReadAnswerOutcome.ALREADY_SETTLED,
    }
)


async def test_a_duplicate_answer_leaves_a_running_dispatch_cancellable() -> None:
    """ADR-0244 §6 and §11: repeated answers and cancellation are two operations.

    "A duplicate answer dispatches nothing and says so: it consults no policy, opens no
    channel, records nothing and mints nothing" — and because it performs nothing it
    touches no other state either. A restatement that tore down the dispatch registry
    would let a double-clicked confirm button make the cancellation act unreachable, on
    the one operation ADR-0244 §11 exists to provide.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.dispatching_read("h-1")

    duplicate = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert duplicate.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert await engine.cancel_read(offered.token) is ReadCancellation.INTERRUPTED, (
        "the running dispatch is still there to interrupt"
    )


async def test_a_refused_resolving_append_is_returned_and_not_raised() -> None:
    """ADR-0244 §6: "**it is returned and not raised**, because a refusal on ``resume``
    is a result (§9)".

    Clause 5 makes ``InvalidResolutionError``'s already-resolved ground unreachable here —
    the park's one answer was taken before the append was attempted — so what a refusal
    is is one of that class's other grounds, or a fault. **The answer is not recorded, the
    park stays spent, nothing is dispatched**, and the outcome is ``OPERATION_CHANGED``.

    The step path still propagates an ``AuditError``, and the asymmetry is §6 rather than
    an inconsistency: a step's resume has a disposition it would have to author over a
    decision the trail would not hold, and a read's has a member for exactly this.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    # Bound to the park but **never recorded**, so the trail refuses the resolution on
    # its own invariant — "the referenced decision is absent" — which is one of
    # ``InvalidResolutionError``'s grounds other than the already-resolved one clause 5
    # makes unreachable. A real refusal rather than an injected fault, so what is under
    # test is the path and not a hook.
    engine.hold_confirmation_decision("h-1", _confirm(external=False))

    outcome = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert outcome.turn is None, "nothing was dispatched"
    assert outcome.recipient_grant is None
    assert await engine.pending_confirmations() == (), "and the park stays spent"
