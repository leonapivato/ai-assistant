"""ADR-0270 §6's four arms, over the one implementation of condition 6.

The seam that joins ADR-0266 §7's *"One implementation, in ``permissions``"* to
ADR-0254 §15's *"written and settled by ``orchestration`` and by nothing else"*, and
this module is what the ADR makes the lane incomplete without. Every arm is driven
over controlled fakes; none is demonstrated against a live integration.

**What is here.** Arm 1 — the vacuous case preserved exactly. Arm 2 — a ``MONEY``
member, the governing quote and the answer carrying it, including the ordering the
arm fails an implementation for reversing. Arm 3 — it rules nothing, records nothing
and caches nothing. Arm 4 — condition 6 and no other condition. And the binding that
runs the shared conformance suite against this implementation, so a divergence
between it and the canonical fake is a failure rather than a latent surprise.

**What is deliberately not here.** The two routes' own readings — the digest, the
currency conjunct, the Sunday re-quote, the argument route's comparisons — are
ADR-0266 §7's and ADR-0267 §11's, in ``test_quote_coverage.py`` and
``test_goal_authorization_policy.py``. This member reaches them through the **same**
``covers_arguments``, which is the whole of what makes it one implementation, so
re-driving them here would assert the same function twice and would drift the moment
one copy was edited. The **call site** — ``orchestration``'s in-place evaluation
replaced by this call, and ``Authorization.quoted`` written from the answer — is
ADR-0254 §20's Lane 2's, briefed after this lane (ADR-0270 §§5, 6).
"""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from authorization_builders import GOAL, OTHER_SITE, SITE, binding, request
from coverage_answers_contract import (
    ACT,
    BARE,
    DATED,
    DISPLACING_QUOTE,
    GOVERNING_QUOTE,
    MONEY_COVERAGE,
    PERIOD_COVERAGE,
    PRICED,
    SUITE_TOOL,
    CoverageAnswersContract,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    ActionQuote,
    BoundKind,
    CoverageAnswer,
    PermissionRuling,
    RiskLevel,
    StepOutputRef,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeGoalAuthorizations,
    FakeGoalQuotes,
    coverage_member,
    money_bound,
    terms_bound,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import CoverageAnswers
    from ai_assistant.core.types import ActionRequest, CoverageMember

#: A ceiling above :data:`GOVERNING_QUOTE`'s figure, in another currency. ADR-0254
#: §4's currency conjunct is read **at the quote's own currency** on the evidence
#: route, and at no key of the request.
USD_COVERAGE: Final[tuple[CoverageMember, ...]] = (
    coverage_member(BoundKind.MONEY, bound=money_bound("150", currency="USD")),
)

#: A ``TERMS`` member no route can meet over :data:`BARE`: the evidence route meets a
#: member of no kind but ``MONEY`` (ADR-0266 §7), and :data:`SUITE_TOOL` declares no
#: argument at ``TERMS`` — so the argument route has nothing to compare it against.
UNMEETABLE_COVERAGE: Final[tuple[CoverageMember, ...]] = (
    coverage_member(BoundKind.TERMS, bound=terms_bound("refundable")),
)


def quote_over(
    call: ActionRequest, *, amount: str = "120", currency: str = "EUR", act: str = ACT
) -> ActionQuote:
    """A quote for ``act`` taken over **this call's own arguments**.

    ``arguments_digest`` is ``call.parameters_digest`` — the request's own property,
    *"never a value computed a second way"* (ADR-0267 §1) — so a case that varies an
    argument gets a different digest for free rather than a second canonicalisation
    written in test code.
    """
    return ActionQuote(
        intended_action=act,
        arguments_digest=call.parameters_digest,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=GOVERNING_QUOTE.read_at,
    )


class _SuppressingQuotes:
    """A ``GoalQuotes`` that **catches** a cancellation and answers an empty tuple.

    The collaborator ADR-0060's propagation clause is stated over, and it cannot be
    ``FakeGoalQuotes``: the canonical fake is cancellation-cooperative, which is what
    makes it a *conforming* seam. What is under test here is the policy's own conduct
    when a seam is not, and the rule is *"stated in the weaker, true form: no seam can
    stop work that declines to be cancelled"*.
    """

    def __init__(self, *, then_raise: Exception | None = None) -> None:
        """Create the seam.

        Args:
            then_raise: What to raise **after** swallowing the cancellation. ``None``
                returns an empty tuple instead. The two are the seam's two exits, and
                ADR-0060's clause reaches both.
        """
        self.entered = asyncio.Event()
        self.absorbed = False
        self._then_raise = then_raise

    async def for_action(self, goal: str, intended_action: str) -> tuple[ActionQuote, ...]:
        """Wait to be cancelled, swallow it, and then answer or fault.

        Args:
            goal: Unread — this seam answers one way.
            intended_action: Unread, likewise.

        Returns:
            An empty tuple, which is exactly the shape *"the goal holds no quote for
            this act"* takes.

        Raises:
            Exception: ``then_raise``, where one was given.
        """
        del goal, intended_action
        self.entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.absorbed = True
            if self._then_raise is not None:
                raise self._then_raise from None
            return ()
        return ()  # pragma: no cover — the case always cancels


def answering(
    quotes: Sequence[ActionQuote] | None = (GOVERNING_QUOTE,), **kwargs: object
) -> tuple[ThresholdActionPolicy, FakeGoalQuotes | None]:
    """The policy under test, holding ``quotes`` as its ``GoalQuotes`` (ADR-0267 §5).

    ``None`` is the policy ADR-0270 §4's last clause is about — one constructed with
    **no** seam at all, which answers unmet for every ``MONEY`` member.
    """
    seam = None if quotes is None else FakeGoalQuotes(quotes, goal=GOAL)
    return (
        ThresholdActionPolicy(quotes=seam, **kwargs),  # type: ignore[arg-type]  # heterogeneous thresholds
        seam,
    )


class TestThresholdActionPolicyCoverageAnswersContract(CoverageAnswersContract):
    """Runs the one implementation through the shared suite (ADR-0270 §1)."""

    #: The seam the ``answers`` subject was built over, so :meth:`displace` can move
    #: the goal's quotes **underneath** it rather than rebuilding the policy — the
    #: subject of that assertion being that this policy re-reads.
    seam: FakeGoalQuotes

    @pytest.fixture
    def answers(self) -> CoverageAnswers:
        """The policy over a goal holding the governing quote.

        Returns:
            The subject, at its narrow face.
        """
        gate, seam = answering()
        assert seam is not None
        self.seam = seam
        return gate

    @pytest.fixture
    def unmet_answers(self) -> CoverageAnswers:
        """The same policy over a goal whose quote is **above** the ceiling.

        Returns:
            The subject, at its narrow face.
        """
        return answering([quote_over(PRICED, amount="170")])[0]

    def displace(self, answers: CoverageAnswers) -> None:
        """Append the later quote to the goal the policy reads.

        ADR-0267 §2's refresh — *"a position in the tuple"* — landing between two
        calls, and §7 then makes it the governing one. Reached through the seam the
        policy holds rather than by rebuilding the policy, because the subject of the
        assertion is that this policy **re-reads**.
        """
        assert answers is not None
        self.seam.hold_for(GOAL, DISPLACING_QUOTE)


# --- arm 1: the vacuous case, preserved exactly -------------------------------


class TestTheVacuousCaseIsPreservedExactly:
    """ADR-0270 §6 arm 1, which is what makes Lane 2's call-site change a
    behaviour-preserving one rather than a widening."""

    async def test_an_empty_coverage_over_a_request_carrying_no_argument_is_met(self) -> None:
        """``proposed_authorization``'s present answer, reached through the member.

        A row with ``coverage=()`` has no member to meet and a request carrying no
        user-facing argument leaves the third conjunct's set empty, so condition 6
        holds — *"the one request such a row covers"*.
        """
        gate, seam = answering()
        answer = await gate.coverage_met(BARE, ())
        assert (answer.met, answer.quoted) == (True, None)
        assert seam is not None
        assert seam.call_count == 0, "a coverage carrying no MONEY member reads no quote seam"

    async def test_an_empty_coverage_over_a_request_carrying_one_argument_is_not_met(
        self,
    ) -> None:
        """The other half of arm 1, and the reason the present evaluation is *"only
        ever vacuous"* (#2373): a request carrying any user-facing argument its
        declaration declares at no kind needs a member met through the evidence route,
        and an empty coverage has none.
        """
        gate, _ = answering()
        answer = await gate.coverage_met(PRICED, ())
        assert (answer.met, answer.quoted) == (False, None)


# --- arm 2: the MONEY member, the governing quote, and the answer carrying it --


class TestTheAnswerCarriesTheGoverningQuoteItWasProvedOver:
    """ADR-0270 §6 arm 2."""

    async def test_a_quote_inside_the_ceiling_is_met_and_rides_back_on_the_answer(
        self,
    ) -> None:
        """§2: ``quoted`` is the quote the evidence route was taken over, *"and no
        other"* — the one value a path-(i) writer records on the row."""
        gate, _ = answering()
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert answer.met is True
        assert answer.quoted == GOVERNING_QUOTE

    async def test_the_last_of_two_quotes_for_that_action_is_the_one_carried(self) -> None:
        """ADR-0267 §7's selection, reached inside condition 6's answer: *"the last
        member of the goal's ``quotes`` naming the request's ``intended_action``"*.

        Both readings satisfy the ceiling here, so the arm is about **which** is
        recorded rather than about whether the request is covered — a reading that
        returned the first would record a figure the user's confirmation never
        rendered.
        """
        later = quote_over(PRICED, amount="130")
        gate, _ = answering([GOVERNING_QUOTE, later])
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert (answer.met, answer.quoted) == (True, later)

    async def test_a_quote_above_the_ceiling_is_not_met_and_carries_no_quote(self) -> None:
        """§2: ``quoted`` is absent wherever the evidence route decided nothing, and
        an unmet member is one of those cases."""
        gate, _ = answering([quote_over(PRICED, amount="170")])
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)

    async def test_the_currency_conjunct_is_read_at_the_quotes_own_currency(self) -> None:
        """ADR-0266 §7: the evidence route's currency conjunct is taken at the
        **quote's** currency and at no key of the request.

        120 is inside 150 as a figure; the two are denominated differently, and a
        reading that compared the numbers would authorise a spend in a currency the
        user never bounded.
        """
        gate, _ = answering()
        answer = await gate.coverage_met(PRICED, USD_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)

    async def test_a_goal_holding_no_quote_for_that_action_is_not_met(self) -> None:
        """An empty answer from the seam means *the goal holds no quote for this act*
        — an absence, and the fail-closed direction (ADR-0267 §5)."""
        gate, seam = answering([quote_over(PRICED, act="ia-other")])
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)
        assert seam is not None
        assert seam.call_count == 1

    async def test_a_policy_holding_no_quote_seam_at_all_is_not_met(self) -> None:
        """ADR-0270 §4: *"An implementation constructed with **no** ``GoalQuotes``
        answers ``met`` false … for any ``coverage`` carrying a member the evidence
        route alone can meet"*.

        ``decide``'s own *"no authorisation source"* floor read one member over, and
        it is what makes the writer's call behaviour-preserving on a tree carrying no
        quote at all.
        """
        gate, seam = answering(None)
        assert seam is None
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)

    def test_the_answer_refuses_construction_with_a_quote_and_an_unmet_verdict(self) -> None:
        """§2's model validator, which is the half of the presence rule a model can
        hold: a quote beside an unmet answer states a proof that was not taken."""
        with pytest.raises(ValueError, match="carries no quote"):
            CoverageAnswer(met=False, quoted=GOVERNING_QUOTE)

    async def test_the_selection_is_driven_ahead_of_the_digest(self) -> None:
        """ADR-0266 §7: *"An earlier quote is consulted in no case"*.

        The goal holds two quotes naming this act: the **later** taken over different
        arguments, the **earlier** over this request's own. The governing quote is
        the later one by position, its digest does not match, and the member is unmet
        — *"nothing here scans the tuple for a matching digest"*. **An implementation
        that filtered by digest before taking the position would revive the quote the
        re-quote displaced** and would answer met, over a price read for a call this
        one is not.
        """
        elsewhere = request(binding(OTHER_SITE), tool=SUITE_TOOL, act=ACT)
        gate, _ = answering([quote_over(PRICED), quote_over(elsewhere)])
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)

    async def test_no_quote_rides_back_on_an_answer_the_evidence_route_did_not_decide(
        self,
    ) -> None:
        """§2's presence rule, over a goal that **does** hold a governing quote.

        A ``PERIOD`` member is met on the argument route alone, so the evidence route
        decided nothing here however many quotes the goal holds — and the seam is not
        read at all, which is ADR-0267 §5's *"only where a ceiling could be proved by
        one"*. The answer's own model cannot enforce this, carrying no coverage to
        test itself against.
        """
        seam = FakeGoalQuotes([quote_over(DATED)], goal=GOAL)
        gate = ThresholdActionPolicy(quotes=seam)
        answer = await gate.coverage_met(DATED, PERIOD_COVERAGE)
        assert (answer.met, answer.quoted) == (True, None)
        assert seam.call_count == 0


# --- arm 3: it rules nothing, records nothing and caches nothing ---------------


class TestItRulesNothingRecordsNothingAndCachesNothing:
    """ADR-0270 §6 arm 3, and §§3 and 4's clauses behind it."""

    async def test_the_member_returns_no_ruling(self) -> None:
        """§4: *"It returns no ``PermissionRuling``, so it has no field in which to
        allow, deny or confirm"*.

        The ruling on the request is ``decide``'s, unchanged, and a met answer
        authorises nothing by itself.
        """
        gate, _ = answering()
        answer = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert not isinstance(answer, PermissionRuling)
        assert set(type(answer).model_fields) == {"met", "quoted"}

    async def test_it_writes_no_authorization_and_appends_to_no_store(self) -> None:
        """§4: it *"writes and settles no ``Authorization``"* and *"writes to no store
        and holds none"*.

        Driven over a policy holding an authorization seam as well, because that is
        the seam a writer would be reached through: the store is asked nothing, and
        the goal holds exactly what it held.
        """
        rows = FakeGoalAuthorizations()
        gate, quotes = answering(authorizations=rows)
        await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert await rows.live_for(GOAL, SUITE_TOOL.id) is None
        assert quotes is not None
        assert quotes.call_count == 1, "one read of the one seam this member has"

    async def test_two_calls_with_equal_arguments_each_read_the_seam(self) -> None:
        """§3: *"no answer this member returns is cached, carried to a dispatch or
        read by any later comparison"*, and ADR-0254 §13's *"no cached coverage
        verdict anywhere"*.

        A proposal-time answer answers **that** proposal. A memoised one would be a
        verdict surviving a call, and the quote it carried would be a figure a later
        refresh had already displaced.
        """
        gate, seam = answering()
        first = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        second = await gate.coverage_met(PRICED, MONEY_COVERAGE)
        assert first == second
        assert seam is not None
        assert seam.call_count == 2

    async def test_a_faulting_quote_seam_propagates_and_is_never_an_absence(self) -> None:
        """§4: *"Where ``GoalQuotes.for_action`` raises ``AuthorizationError`` … this
        member **propagates it**"*.

        Not converted into a met answer, into an unmet one, or into an empty tuple of
        quotes. ``decide``'s own fault clause takes ADR-0254 §6's bar instead, because
        it is producing a *ruling*; here there is no ruling to take, and a component
        that asked writes no row.
        """
        gate, seam = answering()
        assert seam is not None
        seam.fail_for_action()
        with pytest.raises(AuthorizationError):
            await gate.coverage_met(PRICED, MONEY_COVERAGE)

    async def test_a_cancellation_the_seam_absorbed_is_delivered_onward(self) -> None:
        """ADR-0060: *"never lets a collaborator's suppressed cancellation stand in
        for its own"*.

        Nothing forces a ``GoalQuotes`` to let a ``CancelledError`` through, and one
        that catches it and answers ``()`` hands this member an **empty tuple** —
        which is the seam's word for *the goal holds no quote for this act*. Without
        the count check the caller would get an ordinary unmet answer after asking
        for the work to stop, and a proposal would be declined for a reason that
        never happened. Adversarial review, round 5, ``blocker``.
        """
        seam = _SuppressingQuotes()
        gate = ThresholdActionPolicy(quotes=seam)
        pending = asyncio.ensure_future(gate.coverage_met(PRICED, MONEY_COVERAGE))
        await seam.entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert seam.absorbed, "the arm is vacuous unless the seam really swallowed it"

    async def test_a_fault_raised_after_swallowing_a_cancellation_does_not_stand_in_for_it(
        self,
    ) -> None:
        """The same clause on the seam's **other** exit (ADR-0060).

        A seam that absorbs the cancellation and then raises
        :class:`AuthorizationError` leaves that error standing in for the
        cancellation one step over from an unmet answer: the caller is told the
        request could not be read when what happened is that it asked for the work to
        stop. The cancellation takes precedence and the fault rides out as its
        ``__cause__``. Adversarial review, round 6, ``blocker``.
        """
        fault = AuthorizationError("the goal's quotes could not be read")
        seam = _SuppressingQuotes(then_raise=fault)
        gate = ThresholdActionPolicy(quotes=seam)
        pending = asyncio.ensure_future(gate.coverage_met(PRICED, MONEY_COVERAGE))
        await seam.entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError) as raised:
            await pending
        assert seam.absorbed
        assert raised.value.__cause__ is fault, "the fault is carried, not discarded"

    async def test_a_fault_with_no_cancellation_behind_it_still_leaves_as_itself(self) -> None:
        """The control, and the reason the check is a **delta**.

        An ordinary unreadable seam is ADR-0270 §4's own case and propagates as
        :class:`AuthorizationError` — the guard must not convert every fault into a
        cancellation on the strength of a count that never moved.
        """
        gate, seam = answering()
        assert seam is not None
        seam.fail_for_action()
        with pytest.raises(AuthorizationError):
            await gate.coverage_met(PRICED, MONEY_COVERAGE)

    async def test_a_cancellation_count_standing_from_before_the_call_is_not_read_as_one(
        self,
    ) -> None:
        """The same check read as *"a baseline and a delta, never a boolean"*.

        ``Task.cancelling()`` is a lifetime count only ``uncancel()`` lowers, so a
        caller that absorbed an earlier cancellation to finish some work and then
        asked this policy a question still reports a positive count with nothing
        about **this** call cancelled. Read as a flag it would refuse every later
        question on that task.
        """
        gate, _ = answering()

        async def asked() -> CoverageAnswer:
            inner = asyncio.current_task()
            assert inner is not None
            inner.cancel()
            # Absorbed, and **no** ``uncancel()`` — which is what leaves the count
            # standing for the rest of this task's life.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(0)
            assert inner.cancelling() == 1
            return await gate.coverage_met(PRICED, MONEY_COVERAGE)

        answer = await asyncio.ensure_future(asked())
        assert (answer.met, answer.quoted) == (True, GOVERNING_QUOTE)

    async def test_a_coverage_rewritten_mid_call_does_not_move_the_answer(self) -> None:
        """ADR-0065, over the argument ``coverage_subject`` does not reach.

        The member suspends on the quote seam and the tuple is the caller's; a frozen
        model is rewritable through ``__dict__`` on a shared object. A policy that
        counted a ``MONEY`` member on the way in and compared its ceiling on the way
        out would answer about a coverage that is neither the one presented nor the
        one substituted — and the answer authorises the proposal of a row carrying
        whatever the caller ends up writing.
        """
        gate, seam = answering()
        assert seam is not None
        member = MONEY_COVERAGE[0].model_copy(deep=True)
        held = seam.suspend_next_operation()
        pending = asyncio.ensure_future(gate.coverage_met(PRICED, (member,)))
        await held.reached()
        member.__dict__["bound"] = money_bound("1", currency="EUR")
        held.release()
        answer = await pending
        assert (answer.met, answer.quoted) == (True, GOVERNING_QUOTE)


# --- arm 4: condition 6 and no other condition --------------------------------


class TestItEvaluatesConditionSixAndNoOtherCondition:
    """ADR-0270 §6 arm 4, and §1's clause behind it."""

    async def test_a_binding_planned_over_external_content_is_answered_the_same(self) -> None:
        """§1: ADR-0254 §1's *"the proposal reads none of §6's floors, and that is
        deliberate"* binds entire, and this member reads none either.

        The floor is ``decide``'s, taken at dispatch over a **live** row; a proposal
        is written ``PROPOSED`` and there is no live row for one to be taken over.
        """
        external = request(binding(SITE, external=True), tool=SUITE_TOOL, act=ACT)
        gate, _ = answering([quote_over(external)])
        answer = await gate.coverage_met(external, MONEY_COVERAGE)
        assert answer.met is True
        assert answer.quoted == quote_over(external)

    async def test_a_goal_holding_no_live_row_is_answered_the_same(self) -> None:
        """§1: conditions 1 to 5 have nothing to be taken over — *"there is no live
        row for them"*, a proposal being written ``PROPOSED``.

        Driven at both ends: a policy holding an authorization seam whose store is
        empty, and one holding **no** seam at all. Neither changes the answer, which
        is what makes the coverage tuple and the request the whole operand.
        """
        empty = FakeGoalAuthorizations()
        with_seam, _ = answering(authorizations=empty)
        without, _ = answering()
        assert (await with_seam.coverage_met(PRICED, MONEY_COVERAGE)).met is True
        assert (await without.coverage_met(PRICED, MONEY_COVERAGE)).met is True

    async def test_a_policy_that_denies_every_declaration_answers_the_same(self) -> None:
        """§1: not ADR-0254 §12's ladder and not this policy's own rule table.

        ``deny_at_risk=LOW`` refuses **every** action at ``decide``; condition 6 is a
        comparison of recorded values and is unmoved by it, so a met answer here says
        nothing about whether the act may be performed — *"a met answer authorises
        nothing by itself"* (§4).
        """
        gate, _ = answering(deny_at_risk=RiskLevel.LOW)
        assert (await gate.coverage_met(PRICED, MONEY_COVERAGE)).met is True

    async def test_no_answer_is_met_on_a_coverage_carrying_a_member_met_by_no_route(
        self,
    ) -> None:
        """Condition 6's **second direction** (ADR-0254 §3, ADR-0266 §7).

        A ``TERMS`` member is met on the argument route alone, and this declaration
        declares no argument at ``TERMS``, so no route can meet it — *"no default
        kind, no inference from a value's JSON type, no schema keyword and no
        fallback to an exact comparison"*. An act that bounded something the call
        proves nothing about is not a met coverage, whatever else holds.
        """
        gate, _ = answering()
        answer = await gate.coverage_met(BARE, UNMEETABLE_COVERAGE)
        assert (answer.met, answer.quoted) == (False, None)
