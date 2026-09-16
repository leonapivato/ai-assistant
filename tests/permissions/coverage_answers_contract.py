"""Shared conformance suite for the ``CoverageAnswers`` Protocol (ADR-0270 §1).

Every :class:`~ai_assistant.core.protocols.CoverageAnswers` implementation must pass
:class:`CoverageAnswersContract`. A concrete test subclasses it and supplies two
subjects: ``answers``, which answers **met** over :data:`MONEY_COVERAGE` for
:data:`PRICED` carrying :data:`GOVERNING_QUOTE`; and ``unmet_answers``, which answers
**not met** over that same pair. It also supplies :meth:`CoverageAnswersContract.displace`,
which moves the governing quote **underneath** a subject without touching the
arguments — the hook ADR-0270 §3's no-cached-verdict rule needs, because two identical
calls over an unmoved source cannot tell a fresh answer from a replayed one.

**This suite fixes a shape, not a verdict.** Condition 6 has *"One implementation, in
``permissions``"* (ADR-0266 §7), so a suite that re-derived which coverages are met
would be a second place the governing rule lives — and the first conforming
implementation to read it differently would be right in one of them. What is driven
here is therefore what ADR-0270 states about the **answer**: what may ride back on
one, what may not, and that asking twice asks twice. Whether a given coverage is
actually met over a given request is ``tests/permissions/test_coverage_answers.py``'s,
against the one implementation, and ADR-0270 §6's four arms are there.

The one **semantic** floor here is the vacuous case, and it is here because it is not
a matter of an implementation's reading: an empty ``coverage`` has no member to meet
and a request carrying no user-facing argument declares nothing, so condition 6 holds
over the pair whatever an implementation does with the rest (ADR-0254 §1, §3).

**Here rather than under ``tests/core/``.** The suite sits beside the subsystem that
implements it, as ``GoalQuotesContract`` does: ADR-0270 §6 puts the one implementation
in ``permissions``, reached through the policy object that already answers
``ActionPolicy``. The Protocol itself stays in ``core``, which is what lets a proposal
writer hold the narrow face by injection without importing ``permissions``.

**What is deliberately not in here.** The **fault** clause — *"a fault is never an
absence"* (ADR-0270 §4) — is asserted of each implementation in its own module: a
fake satisfies it by construction, and what the clause is actually about is a
``GoalQuotes.for_action`` that raised. The **selection** of the governing quote, the
digest, the currency conjunct and the two routes are ADR-0266 §7's and ADR-0267 §5's,
driven in ``tests/permissions/test_quote_coverage.py`` and in this lane's own arms.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from authorization_builders import AT, GOAL, SITE, TOOL, binding, request

from ai_assistant.core.types import (
    ActionQuote,
    BoundKind,
    CoverageAnswer,
    StepOutputRef,
    ToolDefinition,
)
from ai_assistant.testing import coverage_member, money_bound, period_bound

if TYPE_CHECKING:
    from ai_assistant.core.protocols import CoverageAnswers
    from ai_assistant.core.types import ActionRequest, CoverageMember

#: The goal every subject of this suite is asked about, re-exported so a binding
#: seeds one goal rather than two.
SUITE_GOAL: Final = GOAL

#: The act every priced call here is an attempt at (ADR-0265 §1). A request carrying
#: none is met by the evidence route in no case, so every case that is about a quote
#: has to say which act it is about.
ACT: Final = "ia1"

#: :data:`TOOL` declaring **one** bounded argument, ``stay_from`` at ``PERIOD``.
#:
#: Two things at once, and both are needed. It declares **no** ``MONEY`` argument, so
#: a ``MONEY`` member is proved against the quote alone — ADR-0266 §7's *"a
#: declaration declaring no amount keeps its ceiling proved against the quote"* — and
#: :data:`PRICED` is then about the evidence route rather than also about a missing
#: amount. And it declares one argument at ``PERIOD``, so :data:`DATED` carries an
#: argument the argument route can actually meet, which is the whole of how a
#: ``PERIOD`` member is met (§7, the evidence route meeting no member of that kind).
SUITE_TOOL: Final[ToolDefinition] = ToolDefinition.model_validate(
    {
        **TOOL.model_dump(),
        "bounded_arguments": (
            {"argument": "stay_from", "kind": "period", "currency_argument": None},
        ),
    }
)

#: The booking call a ``MONEY`` member is proved for. It carries ``site`` — a
#: user-facing argument the declaration declares at no kind — so condition 6's third
#: conjunct is live and the quote's digest is what pins it.
PRICED: Final[ActionRequest] = request(binding(SITE), tool=SUITE_TOOL, act=ACT)

#: A call carrying exactly one argument, declared at ``PERIOD``. **No ``MONEY``
#: member is in play here at all**, which is what makes it the case ADR-0270 §2's
#: *"absent in every other case"* is asserted over.
DATED: Final[ActionRequest] = request(
    binding(), tool=SUITE_TOOL, act=ACT, stay_from="2026-09-13T09:00:00+00:00"
)

#: A call carrying **no** user-facing argument at all — the one request an empty
#: coverage covers (ADR-0254 §1, §3).
BARE: Final[ActionRequest] = request(binding(), tool=SUITE_TOOL, act=ACT)

#: The governing quote :data:`PRICED`'s ``MONEY`` member is proved against.
#:
#: ``arguments_digest`` is the request's **own** property, *"never a value computed a
#: second way"* (ADR-0267 §1) — taken from the call rather than written as a literal,
#: so a case that varied an argument would get a different digest for free.
GOVERNING_QUOTE: Final = ActionQuote(
    intended_action=ACT,
    arguments_digest=PRICED.parameters_digest,
    amount=Decimal("120"),
    currency="EUR",
    plan="p1",
    read_from=StepOutputRef(step="s1", field="price"),
    read_at=AT,
)

#: A ceiling of 150 EUR — one ``MONEY`` member, which is the one kind the evidence
#: route can meet (ADR-0266 §7).
MONEY_COVERAGE: Final[tuple[CoverageMember, ...]] = (
    coverage_member(BoundKind.MONEY, bound=money_bound("150", currency="EUR")),
)

#: A **later** reading for the same act, over the same arguments, at a figure still
#: inside the ceiling.
#:
#: ADR-0267 §2 makes a refresh a **position in the tuple**, so this is what a
#: re-quote landing between two calls looks like — and under §7 it displaces
#: :data:`GOVERNING_QUOTE` as the governing one. What it buys the suite is the one
#: thing two identical calls cannot show: whether the second call actually **read**.
DISPLACING_QUOTE: Final = GOVERNING_QUOTE.model_copy(update={"amount": Decimal("130")})

#: One ``PERIOD`` member, met on the **argument** route alone and by no quote.
PERIOD_COVERAGE: Final[tuple[CoverageMember, ...]] = (
    coverage_member(
        BoundKind.PERIOD, bound=period_bound(starts_at=AT, ends_at=AT + timedelta(days=30))
    ),
)


class CoverageAnswersContract:
    """``CoverageAnswers.coverage_met``'s clauses (ADR-0270 §§1, 2, 3)."""

    @pytest.fixture
    def answers(self) -> CoverageAnswers:
        """A subject answering **met** over :data:`MONEY_COVERAGE` for :data:`PRICED`.

        It must have :data:`GOVERNING_QUOTE` available as that pair's governing
        quote, and must answer :data:`PERIOD_COVERAGE` over :data:`DATED` and the
        empty coverage over :data:`BARE` as the one implementation does.

        Returns:
            The implementation under test, at its narrow face.

        Raises:
            NotImplementedError: If a subclass has not supplied one.
        """
        raise NotImplementedError

    @pytest.fixture
    def unmet_answers(self) -> CoverageAnswers:
        """A subject answering **not met** over :data:`MONEY_COVERAGE` for :data:`PRICED`.

        Returns:
            The implementation under test, at its narrow face.

        Raises:
            NotImplementedError: If a subclass has not supplied one.
        """
        raise NotImplementedError

    async def test_the_answer_is_a_coverage_answer_and_nothing_else(
        self, answers: CoverageAnswers
    ) -> None:
        """§2: two fields and no third, and the member returns that value itself.

        *"No route, no digest, no unmet member's kind, no ruling and no record
        crosses the seam."* A tuple, a ``bool`` or a ``PermissionRuling`` here would
        be a different contract, and ``extra="forbid"`` is what keeps a later lane
        from hanging a reason on the value instead of widening the member (§2).
        """
        answer = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert isinstance(answer, CoverageAnswer)
        assert set(type(answer).model_fields) == {"met", "quoted"}

    async def test_a_met_money_coverage_carries_the_governing_quote(
        self, answers: CoverageAnswers
    ) -> None:
        """§2: ``quoted`` is *"set where ``met`` is true **and** ``coverage`` carries a
        ``MONEY`` member"*.

        The half of the presence rule the model cannot hold: a met answer over a
        priced coverage that carried **no** quote would leave ``Authorization.quoted``
        unset on the row the answer authorises the proposal of, and ADR-0267 §10's
        two-read window would reopen — the writer having nothing to record, it would
        have to select one for itself.
        """
        answer = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert answer.met is True
        assert answer.quoted == GOVERNING_QUOTE

    async def test_no_quote_rides_back_on_a_coverage_the_evidence_route_did_not_decide(
        self, answers: CoverageAnswers
    ) -> None:
        """§2: *"It is **absent in every other case**"*, and this is the other case.

        A ``coverage`` carrying no ``MONEY`` member leaves nothing the evidence route
        decided — it meets a member of no other kind in any case (ADR-0266 §7) — so a
        quote here would be a value *"no implementation sets on any other ground"*.
        **The model cannot enforce it**, carrying no coverage to test itself against,
        which is exactly why it is a clause of the Protocol and is driven here.
        """
        assert (await answers.coverage_met(DATED, PERIOD_COVERAGE)).quoted is None

    async def test_an_empty_coverage_over_a_bare_request_is_met_and_carries_no_quote(
        self, answers: CoverageAnswers
    ) -> None:
        """ADR-0254 §1, §3: condition 6 holds **vacuously** over this pair.

        An empty ``coverage`` has no member to meet, and a request carrying no
        user-facing argument declares nothing and leaves the third conjunct's set
        empty. That is not a matter of an implementation's reading, which is why it
        is the one semantic floor in this suite — and it is the coverage this system
        proposes today, so it is also what ADR-0270 §6's *"the interval costs
        questions and authorises nothing"* rests on.
        """
        answer = await answers.coverage_met(BARE, ())
        assert answer.met is True
        assert answer.quoted is None

    async def test_an_unmet_answer_carries_no_quote(self, unmet_answers: CoverageAnswers) -> None:
        """§2's refusal, reached through the **member** and not only through the model.

        :class:`~ai_assistant.core.types.CoverageAnswer` refuses construction with
        ``quoted`` set and ``met`` false, so an implementation cannot return one — but
        it could raise trying, and a ``ValidationError`` out of this member is not the
        answer ADR-0254 §1 disposes of. The unmet answer is an ordinary value.
        """
        answer = await unmet_answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert answer.met is False
        assert answer.quoted is None

    def displace(self, answers: CoverageAnswers) -> None:
        """Make :data:`DISPLACING_QUOTE` the governing quote of the ``answers`` subject.

        **Without touching either argument.** ADR-0270 §3 forbids a cached verdict,
        and two identical calls over an unmoved source cannot tell a fresh answer
        from a replayed one — an implementation that memoised by ``(request,
        coverage)`` and handed back detached copies would pass. This hook is what
        moves the source underneath, so the next call's answer says whether it read.

        Args:
            answers: The subject the ``answers`` fixture returned.

        Raises:
            NotImplementedError: If a subclass has not supplied one.
        """
        raise NotImplementedError

    async def test_asking_twice_asks_twice_and_nothing_is_memoised(
        self, answers: CoverageAnswers
    ) -> None:
        """§3: *"no answer is cached, carried to a dispatch or read by any later
        comparison"*, and ADR-0254 §13's *"no cached coverage verdict anywhere"*.

        Two identical calls answer equally; then the governing quote is displaced
        **underneath** the subject and a third identical call answers with the new
        one. That last step is the whole test: *"a proposal-time answer answers that
        proposal"*, and an implementation memoising by ``(request, coverage)`` would
        hand a path-(i) writer a figure a re-quote had already displaced — which is
        the two-read window §2 closes, reopened from the other side. The first two
        calls stay, because a member that answered twice differently over an unmoved
        source is a separate failure. Adversarial review, round 5, ``major``.
        """
        first = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        second = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert first == second
        assert (await answers.coverage_met(BARE, ())).met is True

        self.displace(answers)
        third = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert third.met is True
        assert third.quoted == DISPLACING_QUOTE, "the answer was replayed, not read"

    async def test_the_call_leaves_its_arguments_where_it_found_them(
        self, answers: CoverageAnswers
    ) -> None:
        """ADR-0065's direction: the arguments are the **caller's**.

        A member that rewrote the request it was handed, or the tuple's members,
        would move what the caller goes on to write onto the row — and the coverage
        here is precisely what a path-(i) proposal is about to carry.
        """
        before = PRICED.model_dump()
        members = tuple(member.model_dump() for member in MONEY_COVERAGE)
        await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert PRICED.model_dump() == before
        assert tuple(member.model_dump() for member in MONEY_COVERAGE) == members

    async def test_the_quote_it_answers_with_is_detached(self, answers: CoverageAnswers) -> None:
        """The quote crosses this seam detached, as it crosses ``GoalQuotes``' (§5).

        *"``frozen=True`` does not close the bypass: a caller could rewrite …
        through ``__dict__`` on a shared object"* — and one record over, the value
        rewritten is the **amount a ceiling was proved against**, which a path-(i)
        writer is about to record on the row. Asserted by rewriting a returned quote
        and asking again, not by comparing two consecutive answers, which an
        implementation handing back the same aliased object passes trivially.
        """
        answer = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert answer.quoted is not None
        before = answer.quoted.amount
        answer.quoted.__dict__["amount"] = before + Decimal("1000")

        again = await answers.coverage_met(PRICED, MONEY_COVERAGE)
        assert again.quoted is not None
        assert again.quoted.amount == before, "a rewritten answer moved what the seam holds"
