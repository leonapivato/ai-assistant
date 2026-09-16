"""The `STATED_BOUND` mint, over the goal alone (ADR-0266 §§1-5, §8; §11's L2).

ADR-0266 §11 assigns **L2** arms **1(a)**, **2(a)**, **3(a)'s mints and refusals**,
**4(b)** and **7**, *"each over controlled fakes"*. The mint is a total function of
one `Goal`, so most of them are taken over that function directly; the halves that
are about a **caller** — the request builder and the proposal that carries a minted
member — are driven through a whole `StepRunner` in
``test_runner_authorizations.py`` and through ``proposed_authorization`` in
``test_authorizing.py``.

**What is deliberately absent here.** 1(b), 5, 6(a)'s with-a-quote limbs and 2(b)'s
quote half ride with the quote decision (§11); 2(b)'s kind-agreement half, 3(b),
3(c), 4(a) and 6 are L1's, taken in `permissions`. Nothing here mints a quote —
ADR-0267 §11's Q2 is the next lane — and nothing here drives the end-to-end
proposal, its question and its answer, which §11's 3(c) note assigns to ADR-0254
§20's Lane 2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from inspect import signature
from typing import TYPE_CHECKING, Final

import pytest
from test_loop_reads import _NOW, _bounded, _loop

from ai_assistant.core.types import (
    ActionPlan,
    BoundKind,
    Goal,
    GoalElement,
    GoalInterpretation,
    Ground,
    MemorySource,
    PlannerOutput,
    PlanStep,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    ResolutionRule,
)
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.stated_bounds import stated_bound_coverage
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import (
        CoverageMember,
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        MemoryRecord,
        ReadAskOutcome,
        ShownFile,
    )

#: A fixed instant, so nothing here reads a clock — which is also §5's own refusal.
AT: Final = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)

#: A space the reading does not collapse (ADR-0266 §4), written as an escape: the
#: whole point of the case is that this byte is not the one beside it.
NON_ASCII_SPACE: Final = "\N{NO-BREAK SPACE}"

#: The turn the first revision was raised by, and therefore the ``act`` every member
#: minted from its elements names (ADR-0266 §2).
FIRST_TURN: Final = "t-1"


def an_element(
    span: str | None,
    *,
    element_id: str | None = "e-1",
    text: str = "what the user fixed",
    ground: Ground = Ground.USER_STATED,
) -> GoalElement:
    """One constraint of an interpretation, carrying ``span``.

    ``text`` is *"what the element says, in the system's own words"* and ``span`` is
    the user's own words inside the turn's utterance. **The mint reads the span and
    never the text** (ADR-0266 §4's *"Nothing outside the span is read"*), so the two
    are varied independently below.
    """
    fields: dict[str, object] = {"text": text, "ground": ground, "id": element_id}
    if span is not None:
        fields["span"] = span
    return GoalElement(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_revision(
    revision: int, *, elements: Sequence[GoalElement], raised_by: str | None = FIRST_TURN
) -> GoalInterpretation:
    """One revision carrying ``elements`` as its constraints."""
    return GoalInterpretation(
        revision=revision,
        outcome="book the trip",
        outcome_ground=Ground.USER_STATED,
        outcome_span="book the trip",
        constraints=tuple(elements),
        recorded_at=AT,
        raised_by=raised_by,
    )


def a_goal(*revisions: GoalInterpretation, elided: int = 0) -> Goal:
    """A goal whose retained history is ``revisions``, oldest first."""
    return Goal(
        id="g-1",
        interpretation=revisions,
        interpretation_elided=elided,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


def stating(span: str | None, **overrides: object) -> Goal:
    """The one-revision goal whose one ``USER_STATED`` constraint carries ``span``."""
    return a_goal(a_revision(1, elements=(an_element(span, **overrides),)))  # type: ignore[arg-type]  # heterogeneous test kwargs


def only_member(goal: Goal) -> CoverageMember:
    """The one member ``goal`` mints, asserted to be exactly one."""
    minted = stated_bound_coverage(goal)
    assert len(minted) == 1
    return minted[0]


# --- arm 1(a): a stated ceiling, end to end ------------------------------


def test_a_stated_ceiling_mints_exactly_one_member_field_for_field() -> None:
    """ADR-0266 §11 arm 1(a), first half, read off the minted member field by field.

    §1's candidate, §2's basis and §4's reading in one assertion each: the ceiling is
    the figure the span states, the currency is the table's code for the word beside
    it, the resolution is the fourth rule, and the act is the ``raised_by`` of the
    revision that first carried the element.
    """
    member = only_member(stating("up to 150 euros"))

    assert member.kind is BoundKind.MONEY
    assert member.fixed is None
    assert member.bound is not None
    assert member.bound.kind is BoundKind.MONEY
    assert member.bound.maximum == Decimal("150")
    assert member.bound.maximum_exclusive is False
    assert member.bound.minimum is None
    assert member.bound.currency == "EUR"
    assert member.basis.act == FIRST_TURN
    assert member.basis.span == "up to 150 euros"
    assert member.basis.resolution.rule is ResolutionRule.STATED_BOUND
    assert member.basis.resolution.now is None
    assert member.basis.resolution.timezone is None
    assert member.basis.resolution.record is None


def test_no_second_member_of_any_kind_rides_with_it() -> None:
    """ADR-0266 §11 arm 1(a): *"and **no second member of any kind**"*.

    §4 mints a ``MONEY`` ceiling or nothing, so a goal stating one ceiling states
    exactly one member — there is no `PERIOD` inferred from the trip, no `TERMS`
    inferred from the outcome, and nothing minted from the outcome at all.
    """
    assert len(stated_bound_coverage(stating("up to 150 euros"))) == 1


def test_the_same_span_inside_a_longer_utterance_mints_the_same_member() -> None:
    """ADR-0266 §11 arm 1(a): *"nothing outside it being read"*.

    The span is *"a proper part of a longer utterance"* in the second goal — its
    element says something else entirely in the system's own words — and the member
    is the same one, because the reading's whole input is the span.
    """
    alone = only_member(stating("up to 150 euros", text="the ceiling for the trip"))
    embedded = only_member(
        stating("up to 150 euros", text="book a hotel for the week, spending carefully")
    )

    assert alone == embedded


# --- arm 2(a): kind agreement and not numeric fit ------------------------


def test_a_star_rating_mints_no_member_at_all() -> None:
    """ADR-0266 §11 arm 2(a), and §3's *"Why the argument key was the defect"*.

    *"a hotel's star rating has a number in it and would fit a price, while `"four
    stars"` has no `MONEY` reading at all"*. The span carries a figure; the table
    carries no form it matches; nothing is minted, and no rule had to decide that a
    rating is not a price.
    """
    assert stated_bound_coverage(stating("4 stars")) == ()


# --- arm 3(a): the mints -------------------------------------------------

#: ADR-0266 §11 arm 3(a)'s mints, one row per case: the span, the ceiling it states
#: and whether that ceiling **excludes** its endpoint.
MINTS: Final[tuple[tuple[str, str, bool], ...]] = (
    ("under 100 euros", "100", True),
    ("at most 100 euros", "100", False),
    ("up to 150 euros", "150", False),
    ("Under 100 Euros.", "100", True),
    ("under 100 euros!", "100", True),
)


@pytest.mark.parametrize(("span", "maximum", "exclusive"), MINTS)
def test_the_table_mints_the_ceiling_it_states(span: str, maximum: str, exclusive: bool) -> None:
    """ADR-0266 §11 arm 3(a)'s mints, one case each.

    *"a strict word mints a strict bound, and the endpoint is never widened"*, and
    case and **one** trailing stop or bang normalise away.
    """
    member = only_member(stating(span))

    assert member.bound is not None
    assert member.bound.maximum == Decimal(maximum)
    assert member.bound.maximum_exclusive is exclusive
    assert member.bound.currency == "EUR"


#: ADR-0266 §11 arm 3(a)'s refusals, one row per case, with what refuses each.
REFUSALS: Final[tuple[tuple[str, str], ...]] = (
    ("under 100 euros!!", "exactly one trailing character is trimmed"),
    ("under 100 euros..", "exactly one trailing character is trimmed"),
    ("under 100 euros.!", "exactly one trailing character is trimmed"),
    ("under 100 euros?", "a span carrying a ? mints nothing, before any other step"),
    ("Under 100 Euros?", "a span carrying a ? mints nothing, before any other step"),
    ("at least 150 euros", "a floor is no form of the table"),
    ("more than 150 euros", "a floor is no form of the table"),
    ("over 150 euros", "a floor is no form of the table"),
    ("never spend over 100 euros", "a negated form is no row of the table"),
    ("no more than 100 euros", "a negated form is no row of the table"),
    ("not over 100 euros", "a negated form is no row of the table"),
    ("not exactly 100 euros", "a negated form is no row of the table"),
    ("never spending over 100 euros", "a negated form is no row of the table"),
    ("up to fifty pounds", "a figure written in words is no decimal figure"),
    ("under one hundred euros", "a figure written in words is no decimal figure"),
)


@pytest.mark.parametrize(("span", "why"), REFUSALS)
def test_a_span_the_table_does_not_carry_mints_nothing(span: str, why: str) -> None:
    """ADR-0266 §11 arm 3(a)'s refusals, one case each, and the act asks instead.

    **Four forms and no fifth**, every one of them a ``maximum``: a floor, a negated
    ceiling and a figure written in words each mint nothing rather than being read by
    a rule that would have to invert or interpret the user's words on their behalf.
    """
    assert stated_bound_coverage(stating(span)) == (), why


def test_a_question_is_refused_before_the_table_is_consulted() -> None:
    """ADR-0266 §4: *"before any other step"*, and the ``?`` need not be trailing.

    A span the table would otherwise match, with a ``?`` in the middle of it, mints
    nothing — which is the check running first rather than the trailing character
    being trimmed and the rest matching.
    """
    assert stated_bound_coverage(stating("under 100 euros? maybe")) == ()


# --- arm 3(a): the whole closed reading, not its illustrations -----------

#: ADR-0266 §4's currency table, whole: every word and symbol, with the code it
#: mints. Parameterised over both orders below.
CURRENCIES: Final[tuple[tuple[str, str], ...]] = (
    ("euro", "EUR"),
    ("euros", "EUR"),
    ("eur", "EUR"),
    ("€", "EUR"),
    ("dollar", "USD"),
    ("dollars", "USD"),
    ("usd", "USD"),
    ("$", "USD"),
    ("pound", "GBP"),
    ("pounds", "GBP"),
    ("gbp", "GBP"),
    ("£", "GBP"),
)

#: §4's four forms, with whether each withdraws its endpoint.
FORMS: Final[tuple[tuple[str, bool], ...]] = (
    ("under", True),
    ("below", True),
    ("at most", False),
    ("up to", False),
)


@pytest.mark.parametrize(("word", "code"), CURRENCIES)
@pytest.mark.parametrize(("form", "exclusive"), FORMS)
@pytest.mark.parametrize("figure", ["100", "99.50"])
@pytest.mark.parametrize("currency_first", [False, True])
def test_the_reading_is_taken_over_its_whole_table(  # noqa: PLR0913 — one parameter per axis of ADR-0266 §4's closed reading; collapsing any pair would stop the product being taken over the whole table
    word: str, code: str, form: str, exclusive: bool, figure: str, currency_first: bool
) -> None:
    """ADR-0266 §11 arm 3(a), *"parameterised over the whole of §4's closed reading"*.

    Every one of the four forms against every currency word and symbol, in **both**
    orders, and ``99.50`` as well as ``100`` — because a reading stated as closed and
    demonstrated over three illustrations is a reading nobody has checked is closed.
    """
    amount = f"{word} {figure}" if currency_first else f"{figure} {word}"
    member = only_member(stating(f"{form} {amount}"))

    assert member.bound is not None
    assert member.bound.maximum == Decimal(figure)
    assert member.bound.maximum_exclusive is exclusive
    assert member.bound.currency == code


@pytest.mark.parametrize("whitespace", [" ", "\t", "\n", "\r", "\f", "\v"])
def test_every_ascii_whitespace_character_collapses(whitespace: str) -> None:
    """ADR-0266 §4: *"collapse runs of ASCII whitespace to one space"*, all six of them.

    A run of any of them, anywhere in the span, reads as one space — so the form and
    the two words are found whatever separates them.
    """
    member = only_member(stating(f"up{whitespace}to{whitespace * 3}150{whitespace}euros"))

    assert member.bound is not None
    assert member.bound.maximum == Decimal("150")


def test_a_non_ascii_space_is_not_collapsed_and_mints_nothing() -> None:
    """ADR-0266 §11 arm 3(a): *"against a non-ASCII space that is **not** collapsed"*.

    The class §4 names is ASCII whitespace, so a non-breaking space stays inside the
    word and the span matches the table in no form. That is the refusing direction,
    and it is why the mint spells the class out rather than writing ``\\s`` — the
    pattern Python gives a `str` would fold this one silently.
    """
    assert stated_bound_coverage(stating(f"up to 150{NON_ASCII_SPACE}euros")) == ()


@pytest.mark.parametrize("figure", ["infinity", "nan", "-100", "-0.01", "Infinity", "NaN", "snan"])
def test_a_figure_adr_0254_s_money_reading_refuses_mints_nothing(figure: str) -> None:
    """ADR-0254 §4's own refusals, over a word of the span rather than an argument.

    ``Decimal`` accepts every one of these and §4 then refuses it — *"the resulting
    `Decimal` is finite and not negative"* — so none of them reaches a ceiling. A
    ``maximum`` of ``Infinity`` would be an authority over every price there is.
    """
    assert stated_bound_coverage(stating(f"under {figure} euros")) == ()


def test_a_mis_chosen_span_mints_the_same_member_as_a_well_chosen_one() -> None:
    """ADR-0266 §11 arm 3(a)'s last half, and §4's answer to it.

    *"the span `"under 100 euros"` of `"avoid booking hotels under 100 euros"` and of
    `"avoid these prices — under 100 euros"` each mint a `MONEY` ceiling of `100`"* —
    the reading has no negation vocabulary and no adjacency test, and what the words
    around the span meant is settled by the user's answer to the rendered proposal.
    """
    avoiding_hotels = only_member(stating("under 100 euros", text="avoid booking hotels"))
    avoiding_prices = only_member(stating("under 100 euros", text="avoid these prices"))

    assert avoiding_hotels == avoiding_prices
    assert avoiding_hotels.bound is not None
    assert avoiding_hotels.bound.maximum == Decimal("100")
    assert avoiding_hotels.bound.maximum_exclusive is True


# --- arm 4(b): one member per kind ---------------------------------------


def test_two_constraints_that_each_read_as_money_mint_neither() -> None:
    """ADR-0266 §11 arm 4(b), first half, and §5's refusal.

    *"No precedence, no ordering, no most-recent rule and no narrowest-wins rule"* —
    choosing between two ceilings the user stated is an interpretation of which one
    they meant, and §9 clause (iii)'s answer to an ambiguity is that the user is
    asked. **Not the narrower one**, which is what a lane optimising for safety would
    have written.
    """
    goal = a_goal(
        a_revision(
            1,
            elements=(
                an_element("under 100 euros", element_id="e-1"),
                an_element("up to 150 euros", element_id="e-2"),
            ),
        )
    )

    assert stated_bound_coverage(goal) == ()


def test_a_ceiling_beside_a_constraint_no_reading_mints_still_mints_the_ceiling() -> None:
    """ADR-0266 §11 arm 4(b), second half: §5 refuses a **kind**, not a goal.

    The second constraint mints nothing, so the ``MONEY`` kind is reached by exactly
    one element and the ambiguity §5 refuses does not arise.
    """
    goal = a_goal(
        a_revision(
            1,
            elements=(
                an_element("up to 150 euros", element_id="e-1"),
                an_element("4 stars", element_id="e-2"),
            ),
        )
    )

    member = only_member(goal)
    assert member.bound is not None
    assert member.bound.maximum == Decimal("150")


# --- arm 7: the goal-only read and the three refusals --------------------


def test_the_mint_takes_the_goal_and_nothing_else() -> None:
    """ADR-0266 §5, as a property of the signature rather than of a call.

    *"**No request, no plan, no step, no declaration, no registry, no quote, no
    utterance beyond the element's own `span` and no clock.**"* A function taking one
    parameter cannot read one, which is why the arm about *"two different requests,
    two different plans and two different declarations"* is decided here and
    demonstrated once, through a whole runner, in ``test_runner_authorizations.py``.
    """
    parameters = signature(stated_bound_coverage).parameters

    assert list(parameters) == ["goal"]


def test_the_same_goal_mints_the_same_members_every_time() -> None:
    """ADR-0266 §5: the member is *"the same value whatever call was being built"*."""
    goal = stating("up to 150 euros")

    assert stated_bound_coverage(goal) == stated_bound_coverage(goal)


def test_no_goal_mints_nothing() -> None:
    """A caller that could not read a goal proposes over an empty coverage.

    ADR-0254 §1's completeness condition then holds only vacuously, which is the
    disposition a goal stating no bound already has.
    """
    assert stated_bound_coverage(None) == ()


def test_an_element_carrying_no_id_mints_nothing() -> None:
    """ADR-0266 §2's first refusal: *"a row written before ADR-0253 §7"*.

    No history can locate an element with no id, so the act cannot be named and the
    member is not minted — rather than resting on the current revision's own turn,
    which would name a later act than the one the user stated the bound on.
    """
    assert stated_bound_coverage(stating("up to 150 euros", element_id=None)) == ()


def test_a_carrying_revision_recording_no_act_mints_nothing() -> None:
    """ADR-0266 §2's second refusal: *"a row written before ADR-0249"*.

    ``raised_by`` is the whole of the act, and ``AuthorizationBasis.act`` is
    required — so a revision that never recorded one mints nothing rather than a
    member resting on a turn this system never recorded.
    """
    goal = a_goal(a_revision(1, elements=(an_element("up to 150 euros"),), raised_by=None))

    assert stated_bound_coverage(goal) == ()


def test_an_element_carrying_no_span_mints_nothing() -> None:
    """ADR-0266 §2's third refusal, and ADR-0254 §10's own fail-closed sentence.

    *"A resolution the loop cannot take is not taken, and no member is minted"*. The
    element is ``INFERRED`` — the one ground ADR-0249 §1 admits with neither a span
    nor an ``evidence_id`` — so §1 excludes it twice over, and §2's refusal is stated
    because this function is handed an element rather than a proof about one.
    """
    goal = stating(None, ground=Ground.INFERRED)

    assert stated_bound_coverage(goal) == ()


def test_an_elided_history_whose_oldest_retained_revision_is_the_carrier_mints_nothing() -> None:
    """ADR-0266 §2's fourth refusal, and the test is exact rather than approximate.

    ADR-0249 §2 drops the **oldest** revisions, so a dropped one may have carried the
    element first — and the act would then name the wrong turn. Decided from values
    on the goal, with no store read.
    """
    element = an_element("up to 150 euros")
    goal = a_goal(
        a_revision(1, elements=(element,), raised_by="t-9"),
        a_revision(2, elements=(element,), raised_by="t-10"),
        elided=3,
    )

    assert stated_bound_coverage(goal) == ()


def test_an_elided_history_with_a_retained_predecessor_mints_normally() -> None:
    """ADR-0266 §11 arm 7's own second half of that clause.

    *"a goal whose `interpretation_elided` is non-zero and whose oldest retained
    revision does **not** carry the element mints it normally"* — the retained
    predecessor proves the carrying revision is the first, whatever was dropped
    before it.
    """
    element = an_element("up to 150 euros")
    goal = a_goal(
        a_revision(1, elements=(), raised_by="t-9"),
        a_revision(2, elements=(element,), raised_by="t-10"),
        elided=3,
    )

    member = only_member(goal)
    assert member.basis.act == "t-10"


def test_the_act_is_the_earliest_carrying_revision_and_not_the_current_one() -> None:
    """ADR-0266 §2: *"the earliest revision … that carries an element with that id"*.

    The user stated the bound on turn ``t-1``; two later revisions retained the
    element byte for byte. The basis names the turn they said it on, which is what
    ADR-0254 §8's span check was taken against.
    """
    element = an_element("up to 150 euros")
    goal = a_goal(
        a_revision(1, elements=(element,), raised_by="t-1"),
        a_revision(2, elements=(element,), raised_by="t-2"),
        a_revision(3, elements=(element,), raised_by="t-3"),
    )

    assert only_member(goal).basis.act == "t-1"


def test_a_revision_carrying_the_id_as_a_criterion_is_still_the_earliest_carrier() -> None:
    """ADR-0266 §2: *"an element with that element's `id`"*, and not its constraints alone.

    The id names one element of the interpretation. A revision that carried it in
    another position still carried it, and the act is that revision's.
    """
    element = an_element("up to 150 euros")
    earlier = GoalInterpretation(
        revision=1,
        outcome="book the trip",
        outcome_ground=Ground.USER_STATED,
        outcome_span="book the trip",
        criteria=(element,),
        recorded_at=AT,
        raised_by="t-1",
    )
    goal = a_goal(earlier, a_revision(2, elements=(element,), raised_by="t-2"))

    assert only_member(goal).basis.act == "t-1"


# --- arm 7 and §1: what is not a candidate -------------------------------


@pytest.mark.parametrize("ground", [Ground.FROM_EVIDENCE, Ground.INFERRED])
def test_only_a_user_stated_constraint_is_a_candidate(ground: Ground) -> None:
    """ADR-0266 §1: the ground is the candidate test, and the type is why.

    ADR-0249 §1's validator gives ``FROM_EVIDENCE`` an ``evidence_id`` and **no**
    span and ``INFERRED`` neither, so neither can reach a basis at all — this states
    a consequence of two ratified types rather than a third refusal.
    """
    fields: dict[str, object] = {"text": "a constraint", "ground": ground, "id": "e-1"}
    if ground is Ground.FROM_EVIDENCE:
        fields["evidence_id"] = "ev-1"
    goal = a_goal(a_revision(1, elements=(GoalElement(**fields),)))  # type: ignore[arg-type]  # heterogeneous test kwargs

    assert stated_bound_coverage(goal) == ()


def test_a_criterion_and_a_condition_mint_nothing() -> None:
    """ADR-0266 §1: *"`criteria` and `conditions` mint nothing"*.

    A criterion states what success would be and a condition when a step may run;
    ADR-0254 §1's path (iii) says where a bound lives in terms — *"the bound is an
    element of its `constraints`"* — so a ceiling stated in either position is not a
    candidate however it reads.
    """
    stated = an_element("up to 150 euros")
    goal = a_goal(
        GoalInterpretation(
            revision=1,
            outcome="book the trip",
            outcome_ground=Ground.USER_STATED,
            outcome_span="book the trip",
            criteria=(stated,),
            conditions=(an_element("under 100 euros", element_id="e-2"),),
            recorded_at=AT,
            raised_by=FIRST_TURN,
        )
    )

    assert stated_bound_coverage(goal) == ()


def test_the_outcome_mints_nothing_however_it_reads() -> None:
    """ADR-0266 §1: *"The interpretation's own `outcome` mints nothing"*.

    It carries no identity — ADR-0249 §7 copies ``outcome``, ``outcome_ground`` and
    ``outcome_span`` forward byte for byte, so two revisions carrying one outcome are
    indistinguishable from two that restated it and §2's act could not be named.
    """
    goal = a_goal(
        GoalInterpretation(
            revision=1,
            outcome="spend up to 150 euros",
            outcome_ground=Ground.USER_STATED,
            outcome_span="up to 150 euros",
            recorded_at=AT,
            raised_by=FIRST_TURN,
        )
    )

    assert stated_bound_coverage(goal) == ()


def test_a_constraint_a_later_revision_dropped_mints_nothing() -> None:
    """ADR-0266 §1: the **current** interpretation alone, and *"omission is removal"*.

    Minting from an earlier revision would restore a constraint the user's own later
    words removed — an authority over a ceiling they had withdrawn.
    """
    goal = a_goal(
        a_revision(1, elements=(an_element("up to 150 euros"),), raised_by="t-1"),
        a_revision(2, elements=(), raised_by="t-2"),
    )

    assert stated_bound_coverage(goal) == ()


def test_a_constraint_a_later_revision_replaced_mints_the_later_reading() -> None:
    """ADR-0266 §1: the current revision is what is read, and §2 dates it.

    ADR-0253 §7 mints a new id for a restated element, so the correction is a
    different element carried first by the later revision — and the act the member
    names is the turn the user corrected it on.
    """
    goal = a_goal(
        a_revision(1, elements=(an_element("up to 150 euros", element_id="e-1"),), raised_by="t-1"),
        a_revision(2, elements=(an_element("under 100 euros", element_id="e-2"),), raised_by="t-2"),
    )

    member = only_member(goal)
    assert member.bound is not None
    assert member.bound.maximum == Decimal("100")
    assert member.bound.maximum_exclusive is True
    assert member.basis.act == "t-2"


# --- arm 7's discard: no value a model produced reaches the mint ---------


#: The turn these two cases drive. It carries the span the planner grounds its
#: constraint on, because ADR-0249 §7 checks a ``USER_STATED`` span against the
#: turn's own utterance before the revision is recorded.
DISCARD_UTTERANCE: Final = "book the trip, spending up to 150 euros"

#: **Every value ADR-0266 §8's discard list names**, as a model could actually smuggle
#: one: `PlannerOutput` sets ``extra="forbid"``, so no field of the envelope admits
#: them and the only route left is a step's free-form ``parameters``. A
#: ``CoverageMember``, a ``ValueBound``, an ``AuthorizationBasis``, a ``BoundKind``,
#: an argument key and a ``BoundedArgument``, all six, all authored by the planner.
SMUGGLED: Final[dict[str, object]] = {
    "coverage": (
        {
            "kind": "money",
            "bound": {"kind": "money", "currency": "EUR", "maximum": "9999"},
            "basis": {
                "act": "t-forged",
                "span": "up to 9999 euros",
                "resolution": {"rule": "stated_bound"},
            },
        },
    ),
    "bound": {"kind": "money", "currency": "EUR", "maximum": "9999"},
    "basis": {
        "act": "t-forged",
        "span": "up to 9999 euros",
        "resolution": {"rule": "stated_bound"},
    },
    "kind": "money",
    "argument": "price",
    "bounded_arguments": ({"argument": "price", "kind": "money", "currency_argument": "currency"},),
}


class _Smuggling:
    """A planner whose envelope carries this turn's understanding and steps."""

    def __init__(self, *, parameters: Mapping[str, object]) -> None:
        self.parameters = parameters

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str] = (),
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        """One plan, one proposed constraint, and whatever the step's parameters carry."""
        return PlannerOutput(
            plan=ActionPlan(
                id="plan-1",
                goal_id=goal.goal_id,
                steps=(
                    PlanStep(
                        id="step-1",
                        intent="book it",
                        capability="book_room",
                        parameters=self.parameters,  # type: ignore[arg-type]  # the envelope's free-form JSON
                    ),
                ),
                created_at=_NOW,
                rationale="scripted",
            ),
            understanding=ProposedUnderstanding(
                retains_outcome=True,
                constraints=(
                    ProposedElement(
                        text="spend up to 150 euros",
                        ground=Ground.USER_STATED,
                        span="up to 150 euros",
                    ),
                ),
            ),
        )


async def _turn_carrying(
    parameters: Mapping[str, object],
) -> tuple[Goal, tuple[CoverageMember, ...]]:
    """One ``converse`` turn whose plan step's parameters are ``parameters``."""
    loop = _loop(FakeMemoryStore(now=lambda: _NOW), planner=_Smuggling(parameters=parameters))
    responded = await loop.respond(
        DISCARD_UTTERANCE,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
    )
    record = responded.goal
    assert record is not None
    return record.goal, stated_bound_coverage(record.goal)


async def test_a_planner_envelope_carrying_the_discard_list_changes_nothing() -> None:
    """ADR-0266 §11 arm 7's discard half, and §8's list read literally.

    *"a `PlannerOutput` whose envelope carries **every value §8's discard list
    names** … leaves the recorded revision and the minted coverage
    **byte-identical** to the same envelope without them, with the turn completing
    and not failing."* Not an error, not a park, not a degradation of the turn: the
    values are simply not inputs of anything. §5's goal-only read is why — the mint
    reads no plan and no step at all — and §8's *"A model names no argument key, no
    currency key and no identifier anywhere in this decision"* is what the forged
    ``act``, the forged span and the `9999` ceiling are there to falsify.
    """
    bare_goal, bare_coverage = await _turn_carrying({"nights": 2})
    smuggled_goal, smuggled_coverage = await _turn_carrying({"nights": 2, **SMUGGLED})

    assert smuggled_goal.interpretation == bare_goal.interpretation
    assert smuggled_coverage == bare_coverage
    (member,) = smuggled_coverage
    assert member.bound is not None
    assert member.bound.maximum == Decimal("150")
    assert member.basis.act != "t-forged"
    assert member.basis.span == "up to 150 euros"
