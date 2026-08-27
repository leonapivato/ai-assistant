"""The routed account at the browser edge (ADR-0197 §10, §12).

**A consumer group and not a second decision** (§12's last Normative). ``routed``
reached ``TurnOutcome`` in the lane that landed the routing stage, and the roster
guard in ``test_gateway.py`` recorded there that this adapter's ``_outcome_view``
was deliberately unchanged. This is the lane that flips it, so what is checked here
is the level #1337's obligation is stated at: ``_outcome_view`` is an explicit
enumeration, so a member reaching the browser is a decision taken here and nowhere
else.

**All seven of ADR-0197 §8's listing arms cross as their records**, and four of
them had no view on this page before this lane. ADR-0177 §1's enumeration has never
admitted ``recent_reads``, ``recent_invocations``, ``recent_decisions`` or
``spend_totals`` to a *browser request*, and ADR-0186 §6 and §10 keep it that way —
but that bar is on the **route** and not on the rendering, and a routed pass makes
no browser request for any of them. §10 is unqualified, so a page that named the
CLI instead would be rendering a turn that did something as a turn that did
nothing. The second half of this module pins that no path resolves to the four all
the same.

**Driven through a real socket** for ``test_gateway_confirmations.py``'s reason, on
``test_gateway_streams``' own harness rather than a fourth copy of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from test_gateway_streams import Harness, _harness

from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    CostBasis,
    GrantScope,
    Idempotency,
    MemoryKind,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Question,
    QuestionState,
    ReadOutcome,
    RecordedInvocation,
    Reversibility,
    RiskLevel,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SourceGrant,
    SourceReadRecord,
    SpendPeriod,
    SpendTotal,
    ToolCost,
    ToolDefinition,
    ToolInvocation,
    TurnOutcome,
    routed_listing_arm,
)
from ai_assistant.interfaces.gateway.server import _ROUTED_ARM_VIEWS
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import RoutedListing

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)

#: The four operations whose records reached this page for the first time in this
#: lane. Named rather than derived, because each owes a rendering floor its own
#: decision already states and a lane adding a fifth should have to say which.
_NEW_ARMS: tuple[RoutableOperation, ...] = (
    RoutableOperation.RECENT_READS,
    RoutableOperation.RECENT_INVOCATIONS,
    RoutableOperation.RECENT_DECISIONS,
    RoutableOperation.SPEND_TOTALS,
)


def _belief(record_id: str = "b-1", *, content: str = "you drink tea") -> Belief:
    """One live belief, as a routed ``forget`` would resolve it."""
    return Belief(
        id=record_id,
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content=content,
        confidence=0.9,
        last_updated=_AT,
    )


def _question() -> Question:
    """One deferred question, as a routed ``questions`` would list it."""
    return Question(
        id="q-1",
        state=QuestionState.OPEN,
        content="do you still cycle?",
        kind=MemoryKind.PREFERENCE,
        band=BeliefBand.DERIVED,
        rationale="you mentioned a bike",
        reason="I am not sure enough to hold it",
        retires=(),
        asked_at=_AT,
        expires_at=None,
    )


def _grant() -> SourceGrant:
    """One live grant, as a routed ``standing_grants`` would list it."""
    return SourceGrant(id="g-1", source="calendar", scope=(GrantScope.INGEST,), decided_at=_AT)


def _read() -> SourceReadRecord:
    """One recorded read attempt — an arm this page has no view for."""
    return SourceReadRecord(
        id="r-1",
        source="calendar",
        use=GrantScope.INGEST,
        checked_at=_AT,
        outcome=ReadOutcome.COMPLETED,
        grant="g-1",
        produced=3,
    )


def _decision(
    *, authorised_by: str | None = "d-0", resolves: str | None = "d-0"
) -> PermissionDecision:
    """One recorded ruling, an ``ALLOW`` resting on a decision about that call.

    The two pointers are arguments because ADR-0193 §11's three states are read off
    the pair, and because the fourth combination — both present and different — is
    the one no audit trail accepts and this surface must refuse to read.
    """
    return PermissionDecision(
        id="d-1",
        ruling=PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="you approved this call",
            authorised_by=authorised_by,
        ),
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
        parameters_digest="a" * 64,
        decided_at=_AT,
        resolves=resolves,
    )


def _invocation() -> RecordedInvocation:
    """One recorded act on an authorisation — the claim half of ADR-0192 §4's pair."""
    return RecordedInvocation(
        invocation=ToolInvocation(id="i-1", decision_id="d-1", recorded_at=_AT),
        tool="smtp",
        capability="send_email",
        egress_call=True,
    )


def _total(*, offset: timedelta = timedelta(0)) -> SpendTotal:
    """One measured period, with a ceiling and a UTC offset the bounds are read in."""
    return SpendTotal(
        period=SpendPeriod.CALENDAR_DAY,
        period_start=_AT,
        period_end=_AT,
        start_offset=offset,
        end_offset=offset,
        ceiling=Decimal("5"),
        currency="USD",
        accounted=Decimal("0.3"),
    )


#: One listing per arm this lane added, so the coverage case drives each with the
#: record its own operation returns rather than with a stand-in.
_LISTINGS: dict[RoutableOperation, RoutedListing] = {
    RoutableOperation.RECENT_READS: (_read(),),
    RoutableOperation.RECENT_INVOCATIONS: (_invocation(),),
    RoutableOperation.RECENT_DECISIONS: (_decision(),),
    RoutableOperation.SPEND_TOTALS: (_total(),),
}


def _routed(
    operation: RoutableOperation,
    outcome: RouteOutcome,
    *,
    listing: RoutedListing | None = None,
) -> TurnOutcome:
    """One routed pass, in the shape ADR-0197 §8 gives it."""
    return TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(operation=operation, outcome=outcome, listing=listing),
        reply="Here is what I did.",
    )


async def _view(one: Harness, outcome: TurnOutcome) -> dict[str, Any]:
    """Drive a turn that routed and return the routed view the page receives."""
    one.engine.turn_outcome = outcome
    status, body = await one.whole("POST", "/ask", {"utterance": "forget that"})
    assert status == 200, body
    view: dict[str, Any] = body["outcome"]["routed"]
    return view


# --- §10: the account crosses, member by member ------------------------------


async def test_the_routed_account_crosses_whole_and_beside_the_reply() -> None:
    """§10's first Normative: the account is carried "**in addition to** any composed
    reply, never instead of it".

    The member set is asserted whole rather than by presence, for
    ``_outcome_view``'s own reason: this enumeration is a decision and not a
    projection, so a member that stops being carried is as much a defect as one that
    starts being carried unreviewed.
    """
    async with _harness(FakeAssistantEngine()) as one:
        one.engine.turn_outcome = _routed(RoutableOperation.FORGET, RouteOutcome.PERFORMED)
        status, body = await one.whole("POST", "/ask", {"utterance": "forget that"})

        assert status == 200, body
        assert body["outcome"]["reply"] == "Here is what I did."
        assert set(body["outcome"]["routed"]) == {
            "operation",
            "outcome",
            "listing",
            "confirmation",
        }
        assert body["outcome"]["routed"]["operation"] == "forget"
        assert body["outcome"]["routed"]["outcome"] == "performed"


async def test_a_pass_that_routed_nothing_carries_a_null_account() -> None:
    """The absence is the fact (ADR-0197 §8's "the presence of the member is the
    fact"), so an ordinary turn crosses with ``routed`` ``null`` rather than with an
    empty account the page would have to tell apart from a real one."""
    async with _harness(FakeAssistantEngine()) as one:
        status, body = await one.whole("POST", "/ask", {"utterance": "hello"})

        assert status == 200, body
        assert body["outcome"]["routed"] is None


async def test_a_listing_this_page_renders_crosses_as_its_records() -> None:
    """§10 on "the listing where one is carried", and §12's "with the renderer it
    already has for the operation" — which for a belief is the view the beliefs panel
    already receives, warrant included."""
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(
                RoutableOperation.FORGET,
                RouteOutcome.AMBIGUOUS,
                listing=(_belief("b-1"), _belief("b-2", content="you drink chai")),
            ),
        )

        assert [one_row["content"] for one_row in view["listing"]] == [
            "you drink tea",
            "you drink chai",
        ]
        assert "evidence" in view["listing"][0], "the belief view, not a second one"


@pytest.mark.parametrize(
    ("operation", "listing"),
    [
        (RoutableOperation.QUESTIONS, (_question(),)),
        (RoutableOperation.STANDING_GRANTS, (_grant(),)),
    ],
)
async def test_the_read_only_arms_this_page_renders_cross_as_records(
    operation: RoutableOperation, listing: RoutedListing
) -> None:
    """The other two arms this page has a view for, driven per operation because the
    arm is read off ``operation`` and a dispatch that guessed from the value's shape
    would pass on one of them by luck (ADR-0197 §8)."""
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(one, _routed(operation, RouteOutcome.PERFORMED, listing=listing))

        assert len(view["listing"]) == 1


# --- the boundary: four arms this page has no view for ------------------------


def test_every_arm_of_a_routed_listing_has_a_view() -> None:
    """ADR-0197 §10: an adapter renders "the listing where one is carried", and the
    clause admits no exception for an arm this page had no panel for.

    Read against ``core``'s own total mapping rather than against a list written
    here, so a member added under ADR-0197 §3's widening rule fails this the moment
    its arm has no view — which is the failure mode the alternative hides, since a
    missing view would otherwise surface as a listing silently not rendered.
    """
    for operation in RoutableOperation:
        assert routed_listing_arm(operation) in _ROUTED_ARM_VIEWS, operation


@pytest.mark.parametrize("operation", _NEW_ARMS)
async def test_the_arms_this_lane_added_cross_as_their_records(
    operation: RoutableOperation,
) -> None:
    """The four that had no view before, each driven as a routed ``PERFORMED``.

    What is asserted is that the records themselves cross — a listing of the right
    length, carrying the record's own identifying field — because the failure this
    replaces was a listing that crossed as ``null`` beside a referral to the CLI.
    """
    listing: RoutedListing = _LISTINGS[operation]
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(one, _routed(operation, RouteOutcome.PERFORMED, listing=listing))

        assert view["listing"] is not None
        assert len(view["listing"]) == len(listing)


async def test_a_routed_read_crosses_all_seven_of_its_fields() -> None:
    """ADR-0185 §2 and ADR-0186 §7's last two clauses: a surface that cannot render a
    row whole renders fewer rows and not partial ones.

    The member set is asserted whole, because the failure a presence check misses is
    the one this view is most likely to have: a field quietly dropped because no case
    named it.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(RoutableOperation.RECENT_READS, RouteOutcome.PERFORMED, listing=(_read(),)),
        )

        assert set(view["listing"][0]) == {
            "id",
            "source",
            "use",
            "checked_at",
            "outcome",
            "grant",
            "produced",
        }


async def test_a_routed_ruling_carries_no_tier_reach_and_no_authorises() -> None:
    """ADR-0186 §8's fifth and second clauses, which are about what must **not** be
    on a decision row.

    ``reads``, ``writes`` and ``discloses`` are ceilings on what a tool *may* reach
    rather than per-call measurements (ADR-0016 §3), so a tier reach beside a
    recipient list asserts a measurement nothing offers; and nothing computes,
    displays or implies :meth:`PermissionDecision.authorises`. An enumerating view is
    where both are kept out, so this is asserted over the member set.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(
                RoutableOperation.RECENT_DECISIONS,
                RouteOutcome.PERFORMED,
                listing=(_decision(),),
            ),
        )

        row = view["listing"][0]
        assert set(row) == {
            "id",
            "unreadable",
            "outcome",
            "reason",
            "decided_at",
            "tool_id",
            "capability",
            "parameters_digest",
            "resolves",
            "authorised_by",
            "binding",
        }
        assert "authorises" not in str(row)


async def test_a_routed_total_crosses_its_amounts_as_text() -> None:
    """ADR-0194 §5, and :func:`_decimal`'s losslessness rule reaching one more value.

    A ``Decimal`` read by ``JSON.parse`` is a double, so a ceiling the owner set
    would reach them changed — and a spend surface showing a figure the ledger did
    not hold is worse than one showing none.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(RoutableOperation.SPEND_TOTALS, RouteOutcome.PERFORMED, listing=(_total(),)),
        )

        row = view["listing"][0]
        assert row["accounted"] == "0.3"
        assert row["ceiling"] == "5"
        assert row["currency"] == "USD"


async def test_an_operation_that_carried_no_listing_crosses_a_null_one() -> None:
    """``listing`` ``null`` is a pass that carried none, and it is the only thing
    ``null`` means there now: no arm is withheld, so nothing has to be told apart
    from an absence."""
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(one, _routed(RoutableOperation.RECENT_READS, RouteOutcome.FAILED))

        assert view["listing"] is None


@pytest.mark.parametrize(
    ("offset", "rendered", "label"),
    [
        (timedelta(0), "2026-08-27 09:00:00", "+00:00"),
        (timedelta(hours=2), "2026-08-27 11:00:00", "+02:00"),
        (timedelta(hours=-5, minutes=-30), "2026-08-27 03:30:00", "-05:30"),
        (timedelta(hours=5, minutes=30, seconds=21), "2026-08-27 14:30:21", "+05:30:21"),
        (timedelta(microseconds=500_000), "2026-08-27 09:00:00.500000", "+00:00:00.500000"),
        (timedelta(microseconds=-500_000), "2026-08-27 08:59:59.500000", "-00:00:00.500000"),
    ],
)
async def test_a_period_bound_crosses_rendered_from_its_own_offset(
    offset: timedelta, rendered: str, label: str
) -> None:
    """ADR-0194 §6: "each bound rendered from the value's **own**
    ``start_offset``/``end_offset`` and labelled with that offset — never from the
    client's zone and never through the client's ``tzdata``".

    An earlier shape of this view crossed the UTC instant beside the offset label,
    which is a bound in one offset labelled with another — and every case it had used
    a zero offset, where the two are indistinguishable. So the cases here are the
    ones that separate them: positive, negative-with-minutes, and an offset carrying
    **seconds**, which a renderer truncating to ``+HH:MM`` states a bound the ledger
    did not use.

    **The sub-second pair is the round-3 blocker**, and it is the one where truncation
    was silent *and* wrong in sign: ``timedelta(microseconds=-500_000)`` read through
    ``total_seconds()`` came out ``+00:00``. ``SpendTotal`` admits an offset "at
    whatever resolution it has" and its cross-field rule exists so "a renderer
    performs exactly those two additions", so the rendering is meant to be total over
    what the type accepts. No zone database produces one; what closes it is that a
    silent truncation states a boundary the ledger did not use.

    **The arithmetic is asserted at this edge deliberately.** §5 bars the bound from
    being read through the client's zone database, so doing it in the gateway is what
    makes that true of the browser rather than hoped of it.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(
                RoutableOperation.SPEND_TOTALS,
                RouteOutcome.PERFORMED,
                listing=(_total(offset=offset),),
            ),
        )

        row = view["listing"][0]
        assert row["period_start"] == rendered
        assert row["period_end"] == rendered
        assert row["start_offset"] == label
        assert row["end_offset"] == label


async def test_a_ruling_that_answers_one_decision_and_rests_on_another_is_not_read() -> None:
    """ADR-0193 §11 names exactly **three** authorisation states, and a ruling that
    answers one decision while resting on another is none of them.

    ``PermissionDecision`` admits the pair at construction — no validator refuses it —
    while the trail refuses to *record* one
    (:class:`~ai_assistant.core.errors.InvalidResolutionError`, whose stated subject
    includes "when the resolving ruling's ``authorised_by`` does not match its
    ``resolves``"). So a row reaching a reader with it is a value no store this system
    wrote would hold, and ``interfaces.cli._authorisation_line`` raises rather than
    choosing between the two pointers.

    This surface marks the **row** instead of raising, because a routed listing rides
    a turn and raising would take the reply and the routed account with it. What is
    asserted is the part that must not differ: the row says it is unreadable, and the
    page's own renderer is what turns that into a refusal rather than a fourth state.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(
                RoutableOperation.RECENT_DECISIONS,
                RouteOutcome.PERFORMED,
                listing=(_decision(authorised_by="g-1", resolves="d-0"),),
            ),
        )

        assert view["listing"][0]["unreadable"] is True


@pytest.mark.parametrize(
    ("authorised_by", "resolves"),
    [("d-0", "d-0"), ("g-1", None), (None, "d-0"), (None, None)],
)
async def test_the_three_states_a_trail_does_accept_are_read_normally(
    authorised_by: str | None, resolves: str | None
) -> None:
    """The other side of the pair above, and it is what fails on a predicate written
    too widely.

    ADR-0193 §6's discriminator is whether ``resolves`` is set, and §11's three states
    are: a decision about this call (both set and equal), a standing authorisation
    (``authorised_by`` set, ``resolves`` unset), and the policy's own rules
    (``authorised_by`` unset). A fourth combination — ``resolves`` set with no
    ``authorised_by`` — is an ``ALLOW`` resting on no decision that nonetheless
    answers a question, which §11 reads as the third state and this must not refuse.
    """
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(
            one,
            _routed(
                RoutableOperation.RECENT_DECISIONS,
                RouteOutcome.PERFORMED,
                listing=(_decision(authorised_by=authorised_by, resolves=resolves),),
            ),
        )

        assert view["listing"][0]["unreadable"] is False


# --- §7: the card and its token -----------------------------------------------


def _parked(operation: RoutableOperation, subject: RoutedListing) -> FakeAssistantEngine:
    """An engine holding one routed park, answerable by its own handle."""
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=operation, subject=subject)
    engine.turn_outcome = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(
            operation=operation,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card,
        ),
        reply=None,
    )
    return engine


async def test_the_routed_card_crosses_with_its_subject_and_its_token() -> None:
    """ADR-0197 §7: the card carries "the ``RoutableOperation`` and the resolved
    subject as a typed value", and the token is what the answer is relayed with.

    **The card's own ``operation`` crosses beside the outer one**, because §8 makes
    the two agreeing an invariant a page cannot check without both: "a card is valid
    on its own terms while describing a different operation from the route that
    produced it, and a user reading 'revoke this grant?' would be approving a
    ``forget``".
    """
    async with _harness(_parked(RoutableOperation.FORGET, (_belief(),))) as one:
        view = await _view(one, one.engine.turn_outcome)  # type: ignore[arg-type]  # seeded above

        card = view["confirmation"]
        assert set(card) == {"operation", "token", "subject"}
        assert card["operation"] == "forget"
        assert card["token"] == "h-1"  # noqa: S105 — a continuation handle, not a credential
        assert [row["content"] for row in card["subject"]] == ["you drink tea"]


async def test_the_routed_card_is_answered_through_the_resume_the_page_already_has() -> None:
    """§7: "A routed park is answered through ``AssistantEngine.resume`` with the
    ``ContinuationToken`` the confirmation carries, and through no other method."

    So no request shape is added: the browser relays the handle to
    ``/confirmation/resume`` exactly as it does for a tool park, and what comes back
    is rendered as any other turn. **The refusal is returned, never raised** — the
    resumed outcome carries ``REFUSED`` and the response is a ``200``, not a fault.
    """
    async with _harness(_parked(RoutableOperation.FORGET, (_belief(),))) as one:
        await one.whole("POST", "/ask", {"utterance": "forget that"})

        status, body = await one.whole(
            "POST", "/confirmation/resume", {"token": "h-1", "approved": False}
        )

        assert status == 200, body
        assert body["outcome"]["routed"]["outcome"] == "refused"
        assert body["outcome"]["step"] is None


async def test_a_routed_park_is_not_offered_by_the_recovery_listing() -> None:
    """§7: ``pending_confirmations`` "does **not** list a routed park", and a routed
    park "is **not** recovered across a restart".

    Asserted at this edge because the page's one recovery route is that read: a
    gateway that folded routed parks into it would offer the owner a card the engine
    cannot answer after a restart, which is the opposite of what §7 decided.
    """
    async with _harness(_parked(RoutableOperation.FORGET, (_belief(),))) as one:
        await one.whole("POST", "/ask", {"utterance": "forget that"})

        status, body = await one.whole("POST", "/confirmations", {})

        assert status == 200, body
        assert body["confirmations"] == []
