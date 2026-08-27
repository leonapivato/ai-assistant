"""The routed account at the browser edge (ADR-0197 §10, §12).

**A consumer group and not a second decision** (§12's last Normative). ``routed``
reached ``TurnOutcome`` in the lane that landed the routing stage, and the roster
guard in ``test_gateway.py`` recorded there that this adapter's ``_outcome_view``
was deliberately unchanged. This is the lane that flips it, so what is checked here
is the level #1337's obligation is stated at: ``_outcome_view`` is an explicit
enumeration, so a member reaching the browser is a decision taken here and nowhere
else.

**Four of ADR-0197 §8's seven listing arms deliberately do not cross as records.**
This page has no view for a ``SourceReadRecord``, a ``RecordedInvocation``, a
``PermissionDecision`` or a ``SpendTotal``, because ADR-0186 §6 and §10 rule that a
browser view of either trail "is a later consumer lane with its own ratified
decision" and ADR-0177 §1's enumeration has admitted none of the four operations.
What crosses instead is the **fact** that a listing was carried and is not rendered
here — never a summary, never a count and never a subset (ADR-0197 §5's last
clause) — and that boundary is what the second half of this module pins.

**Driven through a real socket** for ``test_gateway_confirmations.py``'s reason, on
``test_gateway_streams``' own harness rather than a fourth copy of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from test_gateway_streams import Harness, _harness

from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    GrantScope,
    MemoryKind,
    Question,
    QuestionState,
    ReadOutcome,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SourceGrant,
    SourceReadRecord,
    TurnOutcome,
    routed_listing_arm,
)
from ai_assistant.interfaces.gateway.server import _ROUTED_ARM_VIEWS
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import RoutedListing

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)

#: The four operations whose records this page has no view for, each with the
#: surface where they *are* read. Written out rather than derived from
#: ``_ROUTED_ARM_VIEWS``, so a lane that added a view without deciding what the page
#: says about it fails here.
_UNRENDERED: dict[RoutableOperation, str] = {
    RoutableOperation.RECENT_READS: "assistant reads",
    RoutableOperation.RECENT_INVOCATIONS: "assistant invocations",
    RoutableOperation.RECENT_DECISIONS: "assistant decisions",
    RoutableOperation.SPEND_TOTALS: "assistant spend",
}


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
            "listing_unrendered",
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

        assert view["listing_unrendered"] is False
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

        assert view["listing_unrendered"] is False
        assert len(view["listing"]) == 1


# --- the boundary: four arms this page has no view for ------------------------


def test_the_arms_this_page_renders_are_the_ones_its_panels_render() -> None:
    """ADR-0186 §6 and §10, and ADR-0177 §1's closed enumeration.

    "A browser view of either trail is a later consumer lane with its own ratified
    decision", and no such decision exists — so this lane renders the three arms the
    page's own panels already render and mints no view for the other four. Pinned as
    a set, so adding one is a decision taken deliberately rather than by a helper
    someone reached for.
    """
    assert set(_ROUTED_ARM_VIEWS) == {Belief, Question, SourceGrant}
    for operation in _UNRENDERED:
        assert routed_listing_arm(operation) not in _ROUTED_ARM_VIEWS, operation


async def test_a_listing_this_page_cannot_render_crosses_as_an_absence_that_says_so() -> None:
    """The one thing this surface must not do is turn a carried listing into silence.

    ``listing`` ``null`` beside ``listing_unrendered`` ``true`` is a listing that was
    carried and has no renderer here; ``listing`` ``null`` beside
    ``listing_unrendered`` ``false`` is a pass that carried none. Collapsing the two
    would let the page say nothing was listed over records the hub returned, which is
    ADR-0170 §6's failure arriving through the view.

    **And no part of the records crosses** — not a count, not a summary, not a subset
    (ADR-0197 §5's last clause). The source below is what a leaked field would carry,
    so it is searched for in the whole response body rather than in the account alone.
    """
    async with _harness(FakeAssistantEngine()) as one:
        one.engine.turn_outcome = _routed(
            RoutableOperation.RECENT_READS, RouteOutcome.PERFORMED, listing=(_read(),)
        )
        status, body = await one.whole("POST", "/ask", {"utterance": "what did you read"})

        assert status == 200, body
        view = body["outcome"]["routed"]
        assert view["listing"] is None
        assert view["listing_unrendered"] is True
        assert view["operation"] == "recent_reads"
        assert "r-1" not in str(body)


async def test_an_operation_that_carried_no_listing_is_not_reported_as_withheld() -> None:
    """The other side of the pair above, which is the assertion that fails on a view
    computing ``listing_unrendered`` from the arm alone."""
    async with _harness(FakeAssistantEngine()) as one:
        view = await _view(one, _routed(RoutableOperation.RECENT_READS, RouteOutcome.FAILED))

        assert view["listing"] is None
        assert view["listing_unrendered"] is False


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
