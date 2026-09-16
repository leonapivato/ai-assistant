"""The path-(i) proposal and its expiry ladder (ADR-0254 §1, §12; ADR-0256).

These are the total functions ADR-0254 §1's four conditions and ADR-0256 §1's
ladder are stated as, exercised directly. What a turn then *does* with a
proposal — writing it, settling it on the answer — is
``test_runner_authorizations.py``'s.

**The completeness condition is the member's answer and never this module's**
(ADR-0270 §1, §3): the writer hands `CoverageAnswers.coverage_met` the request and
the coverage the row would carry, and records `Authorization.quoted` from what
comes back. Most tests here drive the **real** `ThresholdActionPolicy` under that
annotation, so what they pin is the answer the one implementation gives; the ones
that need a fault, a call count or an answer no tree can produce name
`FakeCoverageAnswers` instead.

**No caller in `orchestration` mints a coverage member**, because no clause of the
corpus said how one is minted from a recorded act until ADR-0266 (#2373, ruled
there), and that decision's §11 **L2** lands the mint and has not landed. So the
runner passes an empty tuple and ADR-0254 §1's completeness
condition holds only vacuously — §10's own fail-closed sentence and §20 arm 59's
third case. The arms that need a non-empty ``coverage`` drive it **through this
function's parameter**, which is the shape a minter will fill.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final

import pytest
from authorizing_builders import (
    ACCOUNT,
    AT,
    GOAL,
    RETENTION,
    a_binding,
    a_decision,
    a_goal,
    a_request,
    a_tool,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    ActionQuote,
    ActionRequest,
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
    BoundKind,
    CoverageAnswer,
    CoverageMember,
    Goal,
    PermissionOutcome,
    PermissionRuling,
    QuoteView,
    SpanCoverage,
    StepOutputRef,
    ToolDefinition,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import CoverageAnswers, GoalQuotes

from ai_assistant.orchestration.authorization_surface import projection_of
from ai_assistant.orchestration.authorizing import (
    authorization_id_for,
    horizon,
    proposed_authorization,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeCoverageAnswers,
    FakeGoalQuotes,
    authorization_basis,
    coverage_member,
    money_bound,
    period_bound,
    terms_bound,
)

# --- ADR-0256 §1's ladder ------------------------------------------------


def test_rung_2_takes_the_goals_own_deadline() -> None:
    """ADR-0254 §12's rung 2, transcribed unchanged."""
    deadline = AT + timedelta(hours=12)

    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == deadline


def test_rung_2_is_not_displaced_by_a_finite_window() -> None:
    """ADR-0256 §9: rung 2 is taken though a window exists and would differ."""
    deadline = AT + timedelta(hours=12)
    assert deadline != AT + RETENTION

    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == deadline


def test_the_ordinary_case_takes_the_retention_window() -> None:
    """ADR-0256 §9's ordinary case: no deadline, no stated instant, a finite window."""
    assert horizon(AT, goal=a_goal(deadline=None), retention=RETENTION) == AT + RETENTION


@pytest.mark.parametrize("deadline", [AT, AT - timedelta(seconds=1)], ids=["equal", "stale"])
def test_a_stale_or_equal_deadline_reaches_rung_3_not_rung_2(deadline: datetime) -> None:
    """ADR-0256 §9: rung 2 does not take it, and a row **is** written on rung 3.

    That arm exists because it is "the one an implementation keeping the old
    no-row behaviour would otherwise still pass".
    """
    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == AT + RETENTION


def test_a_window_of_none_writes_no_row() -> None:
    """ADR-0256 §3: "keep forever" is not a horizon to invent one against."""
    assert horizon(AT, goal=a_goal(deadline=None), retention=None) is None


def test_a_stale_deadline_and_no_window_writes_no_row() -> None:
    """ADR-0254 §12's ratified rung 3, standing as the ladder's last (ADR-0256 §3)."""
    assert horizon(AT, goal=a_goal(deadline=AT), retention=None) is None


def test_a_goal_the_store_no_longer_holds_falls_to_rung_3() -> None:
    """An absent goal takes rung 2 out; it is not an error and invents nothing."""
    assert horizon(AT, goal=None, retention=RETENTION) == AT + RETENTION


def test_the_arithmetic_edge_writes_no_row() -> None:
    """ADR-0256 §2: "Nothing is clamped, rounded, saturated or defaulted."."""
    near_max = datetime.max.replace(tzinfo=UTC) - timedelta(seconds=1)

    assert horizon(near_max, goal=a_goal(deadline=None), retention=RETENTION) is None


def test_a_deadline_the_ladder_takes_is_never_clamped_by_the_window() -> None:
    """ADR-0256 §6: rung 2 takes no ceiling from this decision."""
    far = AT + timedelta(days=3650)

    assert horizon(AT, goal=a_goal(deadline=far), retention=RETENTION) == far


# --- ADR-0254 §1's four conditions (§20 arm 59) --------------------------


def an_answerer(*, quotes: GoalQuotes | None = None) -> CoverageAnswers:
    """Condition 6's **one** implementation, as the call site reaches it (ADR-0270 §1).

    Every test below that does not name an answerer drives the real comparison
    through the real policy, so the vacuity this call site preserves is the
    member's own answer rather than a fake's configuration. ADR-0270 §6's arm 1
    pins that answer at the member; these are the same fact one seam later, which
    is what a call-site change is obliged to show it did not move.
    """
    return ThresholdActionPolicy(quotes=quotes)


async def _proposed(  # noqa: PLR0913 — one parameter per operand the four conditions vary over
    *,
    request_kwargs: dict[str, object] | None = None,
    coverage: tuple[CoverageMember, ...] = (),
    answers: CoverageAnswers | None = None,
    goal: Goal | None = None,
    retention: timedelta | None = RETENTION,
    standing: tuple[Authorization, ...] = (),
) -> Authorization | None:
    """Run the four conditions over one varied input."""
    request = a_request(**(request_kwargs or {}))  # type: ignore[arg-type]  # heterogeneous test kwargs
    return await proposed_authorization(
        request,
        a_decision(),
        answers=an_answerer() if answers is None else answers,
        coverage=coverage,
        goal=a_goal(deadline=AT + timedelta(hours=12)) if goal is None else goal,
        retention=retention,
        standing=standing,
    )


async def test_a_confirm_meeting_all_four_conditions_proposes_a_row() -> None:
    """ADR-0254 §1, §20 arm 59's last clause, and arm 54's proposal half.

    An argument-free egress call: the row carries ``coverage=()``, which §1
    permits and which covers exactly one request — one carrying no argument at
    all.
    """
    row = await _proposed()

    assert row is not None
    assert row.id == authorization_id_for("d-1")
    assert row.goal == GOAL
    assert row.coverage == ()
    assert row.origin is AuthorizationOrigin.CONFIRMED
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.settled_at is None
    assert row.confirmation == "d-1"
    assert row.supersedes is None
    assert row.proposed_at == AT
    assert row.expires_at == AT + timedelta(hours=12)
    assert row.account == ACCOUNT
    assert row.destinations == a_binding().canonical_destination_set


async def test_a_request_carrying_no_goal_proposes_nothing() -> None:
    """ADR-0254 §1: such a request "reaches route (d) in no case"."""
    assert await _proposed(request_kwargs={"goal": None}) is None


async def test_a_request_carrying_no_egress_binding_proposes_nothing() -> None:
    """ADR-0254 §1: "every clause of this decision is scoped to one"."""
    assert await _proposed(request_kwargs={"binding": None}) is None


async def test_a_request_carrying_a_user_facing_argument_proposes_nothing() -> None:
    """ADR-0254 §20 arm 59's third case, on the minting gap ADR-0266 §11's L2 closes.

    "a `CONFIRM` on an egress request one of whose arguments no resolution minted
    a member for → **no row is written**". Every user-facing argument is such an
    argument until ADR-0266 lands.
    """
    assert await _proposed(request_kwargs={"parameters": {"to": "a@example.com"}}) is None


async def test_a_request_carrying_only_system_supplied_arguments_proposes_a_row() -> None:
    """ADR-0254 §3: such a request carries no user-facing argument, so §1 holds.

    The completeness condition is over **user-facing** arguments alone, so a
    declaration that classifies its whole parameter set is one whose calls this
    lane can still found an authority on.
    """
    row = await _proposed(
        request_kwargs={
            "tool": a_tool(system_supplied=("idempotency_key",)),
            "parameters": {"idempotency_key": "k-1"},
        }
    )

    assert row is not None
    assert row.coverage == ()


async def test_a_ladder_yielding_no_instant_proposes_nothing() -> None:
    """ADR-0254 §1's fourth condition, and §20 arm 69's no-row case."""
    assert await _proposed(goal=a_goal(deadline=None), retention=None) is None


# --- the supersession a proposal names (ADR-0254 §1, §5) -----------------


def _established(tool_id: str = "smtp") -> Authorization:
    """An `ESTABLISHED` row of this goal and that declaration id."""
    return Authorization(
        id=f"auth-prior-{tool_id}",
        goal=GOAL,
        tool=a_tool(tool_id=tool_id),
        account=ACCOUNT,
        destinations=a_binding().canonical_destination_set,
        origin=AuthorizationOrigin.CONFIRMED,
        coverage=(),
        proposed_at=AT - timedelta(hours=2),
        expires_at=AT + timedelta(hours=2),
        confirmation="d-0",
        supersedes=None,
        disposition=AuthorizationDisposition.ESTABLISHED,
        settled_at=AT - timedelta(hours=2),
    )


async def test_a_proposal_names_the_standing_row_of_that_pair() -> None:
    """ADR-0254 §1: a path-(i) proposal may name any `ESTABLISHED` row of the pair.

    Naming it is what keeps the uniqueness rule satisfiable: approving a second
    row of one pair would otherwise answer `WOULD_DUPLICATE` and establish
    nothing.
    """
    row = await _proposed(standing=(_established(),))

    assert row is not None
    assert row.supersedes == "auth-prior-smtp"


async def test_a_proposal_names_no_row_of_another_declaration() -> None:
    """The uniqueness key is the goal and the declaration **id** (ADR-0254 §1)."""
    row = await _proposed(standing=(_established(tool_id="other"),))

    assert row is not None
    assert row.supersedes is None


async def test_a_proposal_names_a_lapsed_row_of_that_pair() -> None:
    """ADR-0254 §1: "live or expired" — "That is what renews an authority"."""
    lapsed = _established().model_copy(update={"expires_at": AT - timedelta(minutes=1)})

    row = await _proposed(standing=(lapsed,))

    assert row is not None
    assert row.supersedes == "auth-prior-smtp"


# --- finding the proposal an answer names --------------------------------


async def test_the_proposals_id_is_derived_from_the_confirmation_it_names() -> None:
    """ADR-0254 §16 carries no lookup by `confirmation`, so the id **is** the lookup.

    Issue #2375: reading back over a bounded `recent` page lost a proposal that
    newer rows of other goals had displaced. An id derived from the confirmation
    makes §16's keyed `resolve` an exact lookup at any age, and adds no ninth
    store signature to do it.
    """
    row = await _proposed()

    assert row is not None
    assert row.confirmation == "d-1"
    assert row.id == authorization_id_for("d-1")


def test_the_derivation_is_a_total_function_of_the_confirmation_id() -> None:
    """Deterministic and injective: the writer and the reader agree without a search."""
    assert authorization_id_for("d-1") == authorization_id_for("d-1")
    assert authorization_id_for("d-1") != authorization_id_for("d-9")


def test_a_derived_id_is_namespaced_away_from_the_id_it_is_derived_from() -> None:
    """The prefix is what keeps derived names disjoint from drawn ones.

    An `Authorization` id is a `DurableIdentifier` — non-blank encodable text and
    nothing narrower — so a row minted by any other route could carry any string.
    Namespacing removes the collision by construction rather than by probability.
    """
    derived = authorization_id_for("d-1")

    assert derived != "d-1"
    assert derived.endswith("d-1")


# --- what a proposal deliberately does not read (ADR-0254 §1) ------------


#: Every ``SpanCoverage`` an egress binding over external content can carry.
#: ``PATH_WITHOUT_MODEL`` is refused at construction by ADR-0155 §3 and ADR-0233
#: §6 — "forbidden absolutely, whatever any authorisation, policy, grant or user
#: answer says" — so there is no such binding for a proposal to read a floor off.
_CARRIED_COVERAGES = (SpanCoverage.NOT_COVERED, SpanCoverage.MODEL_ON_EVERY_PATH)


@pytest.mark.parametrize(
    "coverage", _CARRIED_COVERAGES, ids=[member.name for member in _CARRIED_COVERAGES]
)
async def test_the_proposal_reads_no_floor_of_route_ds(coverage: SpanCoverage) -> None:
    """ADR-0254 §1: "The proposal reads none of §6's floors, and that is deliberate".

    Conditions 3, 4 and 5 of route (d)'s reachability are taken over a concrete
    request at **every dispatch**, so putting them at the write would refuse an
    authority on the strength of one call's taint — "a different rule from the
    one §6 states and a weaker one". §20 arm 60 is this over the coverage limb.
    """
    binding = a_binding(coverage=coverage, planned_with_external_content=True)

    assert await _proposed(request_kwargs={"binding": binding}) is not None


async def test_the_outcome_test_is_the_writers_and_not_this_functions() -> None:
    """The four conditions say nothing about the ruling's outcome.

    Keeping that guard at the call site is what lets this stay a total function
    of the request and the decision, and it is pinned here so a later lane does
    not come to state it twice.
    """
    row = await proposed_authorization(
        a_request(),
        a_decision(
            ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed outright")
        ),
        answers=an_answerer(),
        coverage=(),
        goal=a_goal(deadline=AT + timedelta(hours=12)),
        retention=RETENTION,
        standing=(),
    )

    assert row is not None


# --- the figure the row records (ADR-0267 §11 arm 7; ADR-0270 §2) --------


#: The act every priced call below is an attempt at (ADR-0265 §1). A request
#: carrying none is met by ADR-0266 §7's evidence route in no case.
ACT: Final = "ia-1"

#: A declaration carrying one user-facing argument the argument route can meet,
#: and **no** ``MONEY`` argument — so a ``MONEY`` member here is proved against
#: the quote alone, which is ADR-0266 §7's *"a declaration declaring no amount
#: keeps its ceiling proved against the quote"*.
PRICED_TOOL: Final = a_tool(
    bounded_arguments=({"argument": "nights", "kind": "period", "currency_argument": None},)
)


#: A declaration whose one user-facing argument is declared at ``TERMS``, so a
#: ``TERMS`` member can actually reach it. ADR-0266 §7's argument route is
#: available only where the declaration carries **exactly one**
#: ``BoundedArgument`` at the member's kind; a member names no argument itself.
SITED_TOOL: Final = a_tool(
    bounded_arguments=({"argument": "site", "kind": "terms", "currency_argument": None},)
)


def a_priced_request(**overrides: object) -> ActionRequest:
    """A booking call carrying one user-facing argument and naming its act."""
    fields: dict[str, object] = {
        "tool": PRICED_TOOL,
        "parameters": {"site": "hotel-1"},
        "intended_action": ACT,
    }
    fields.update(overrides)
    return a_request(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_quote(request: ActionRequest, *, amount: str = "120", currency: str = "EUR") -> ActionQuote:
    """A quote naming ``request``'s act, read over ``request``'s own arguments.

    ``arguments_digest`` is taken from the call rather than written as a literal,
    because it is the request's **own** property (ADR-0267 §1) — so a case that
    varies an argument gets a different digest for free.
    """
    return ActionQuote(
        intended_action=ACT,
        arguments_digest=request.parameters_digest,
        amount=Decimal(amount),
        currency=currency,
        plan="p-1",
        read_from=StepOutputRef(step="s-1", field="price"),
        read_at=AT,
    )


#: A ceiling of 150 EUR — one ``MONEY`` member, the one kind the evidence route
#: meets, and the coverage every priced case below is taken over.
PRICE_CEILING: Final[tuple[CoverageMember, ...]] = (
    coverage_member(BoundKind.MONEY, bound=money_bound("150", currency="EUR")),
)


async def test_a_priced_row_records_the_governing_quote_field_for_field() -> None:
    """ADR-0267 §11 arm 7's first case, and ADR-0270 §2's *"a row is written from this value"*.

    The writer **records** and selects nothing: what lands on the row is the
    object ``coverage_met`` returned, which is the quote ADR-0266 §7's evidence
    route was taken over.
    """
    request = a_priced_request()
    quote = a_quote(request)

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=FakeGoalQuotes([quote], goal=GOAL)),
    )

    assert row is not None
    assert row.quoted == quote
    assert row.quoted is not None
    assert row.quoted.amount == Decimal("120")
    assert row.quoted.currency == "EUR"
    assert row.quoted.read_at == AT
    assert row.quoted.arguments_digest == request.parameters_digest
    assert row.coverage == PRICE_CEILING


async def test_the_last_quote_of_that_action_is_the_one_recorded() -> None:
    """ADR-0267 §2's order is the total order: *"the last naming an action"* governs."""
    request = a_priced_request()
    earlier = a_quote(request, amount="100")
    later = a_quote(request, amount="130")

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=FakeGoalQuotes([earlier, later], goal=GOAL)),
    )

    assert row is not None
    assert row.quoted == later


@pytest.mark.parametrize(
    ("act", "held", "why"),
    [
        (None, True, "no intended_action, so the evidence route decides nothing"),
        (ACT, False, "no quote of the goal names that act"),
    ],
    ids=["no-act", "no-quote-for-the-act"],
)
async def test_a_money_member_the_evidence_route_cannot_meet_proposes_nothing(
    *, act: str | None, held: bool, why: str
) -> None:
    """ADR-0267 §11 arm 7's second and third cases, taken at their real strength.

    The arm names them as rows *"carrying ``quoted`` absent"*, and on this corpus
    that reading is unavailable: ADR-0270 §2 makes a quote **present exactly**
    where a met answer's coverage carries a ``MONEY`` member, so a ``MONEY``
    member the evidence route cannot meet leaves condition 6 unmet and **no row
    is written at all** (ADR-0254 §1, §11). That is strictly stronger than an
    absent field — the authority is not granted — and it is what this tree does.
    The absent-field half is the case below, over a coverage carrying no ``MONEY``
    member.
    """
    request = a_priced_request(intended_action=act)
    quotes = FakeGoalQuotes([a_quote(request)] if held else [], goal=GOAL)

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": act,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=quotes),
    )

    assert row is None, why


async def test_a_row_carrying_no_money_member_records_no_quote_though_one_governs() -> None:
    """ADR-0270 §2's presence rule, and ADR-0267 §11 arm 7's third case.

    *"Absent in every other case"*: the goal **does** hold a governing quote for
    this request's act, and the row still carries none, the evidence route having
    decided nothing about a coverage that carries no ``MONEY`` member. This is the
    half of the rule ``CoverageAnswer``'s own validator cannot enforce — it carries
    no coverage to test itself against — so it is asserted at the row.
    """
    request = a_priced_request(parameters={"nights": "2026-09-13T09:00:00+00:00"})
    period = (
        coverage_member(
            BoundKind.PERIOD,
            bound=period_bound(starts_at=AT, ends_at=AT + timedelta(days=30)),
        ),
    )

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"nights": "2026-09-13T09:00:00+00:00"},
            "intended_action": ACT,
        },
        coverage=period,
        answers=an_answerer(quotes=FakeGoalQuotes([a_quote(request)], goal=GOAL)),
    )

    assert row is not None
    assert row.quoted is None


async def test_the_subject_digest_is_unchanged_across_two_rows_differing_only_in_quoted() -> None:
    """ADR-0267 §11 arm 7: what keeps ADR-0254 §7's recompute parity.

    ``subject_digest`` is taken over §7's five fields and ``quoted`` is none of
    them, so a row that records a figure and one that does not fingerprint the
    same — which is what lets the trail recompute a digest over a row written
    before this lane and one written after it.
    """
    request = a_priced_request()

    priced = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=FakeGoalQuotes([a_quote(request)], goal=GOAL)),
    )

    assert priced is not None
    assert priced.quoted is not None
    unpriced = priced.model_copy(update={"quoted": None})

    assert unpriced.quoted is None
    assert priced.subject_digest == unpriced.subject_digest


@final
class _RefreshingQuotes:
    """A ``GoalQuotes`` that lands a re-quote the instant the read returns.

    The window ADR-0267 §7's snapshot rule is about is between the read the proof
    was taken over and the write of the row, and it is **inside**
    :func:`proposed_authorization` — after ``coverage_met`` answers and before the
    ``Authorization`` is constructed. Nothing else can put a quote there, so the
    seam does it itself: what it answers is the goal as it stood, and what the
    goal holds immediately afterwards is one reading newer.
    """

    def __init__(self, held: tuple[ActionQuote, ...], refresh: ActionQuote) -> None:
        """Hold ``held``, and append ``refresh`` as soon as anyone reads."""
        self._held = held
        self._refresh = refresh
        self.calls = 0

    async def for_action(self, goal: str, intended_action: str) -> tuple[ActionQuote, ...]:
        """That action's quotes as the goal stands, then advance the goal."""
        del goal
        self.calls += 1
        answered = tuple(one for one in self._held if one.intended_action == intended_action)
        self._held = (*self._held, self._refresh)
        return answered


async def test_the_recorded_quote_is_the_reads_own_snapshot() -> None:
    """ADR-0267 §7, and §11 arm 7's snapshot limb.

    One goal read per row built, and a quote appended **between** that read and the
    write leaves the row carrying the quote the read returned. There is no version
    check and no coordination in the builder: the row records the figure the proof
    was actually taken over, and a later reading is a different fact about a later
    moment — one ADR-0254 §13's recheck reads at dispatch and this row does not
    (ADR-0270 §3).

    **The refresh is chosen to be one a comparison would notice**: at 170 it is
    outside the 150 ceiling, so a builder that re-read, compared versions or
    coordinated at all would answer unmet and write no row at all.
    """
    request = a_priced_request()
    quotes = _RefreshingQuotes((a_quote(request),), a_quote(request, amount="170"))

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=quotes),
    )

    assert row is not None
    assert row.quoted is not None
    assert row.quoted.amount == Decimal("120")
    assert quotes.calls == 1, "one goal read per row built"


async def test_the_answer_is_asked_exactly_once_per_proposal() -> None:
    """ADR-0270 §3: nothing is memoised and nothing is carried to a dispatch.

    Two proposals ask twice, and each proposal asks once — a writer that cached
    the answer across the pair, or took it twice to be sure, would fail one half
    or the other.
    """
    answers = FakeCoverageAnswers()

    first = await _proposed(answers=answers)
    assert answers.call_count == 1

    second = await _proposed(answers=answers)

    assert first is not None
    assert second is not None
    assert answers.call_count == 2


async def test_the_seam_is_asked_about_the_request_and_the_coverage_and_never_the_row() -> None:
    """ADR-0270 §1: *"It takes the coverage tuple and never the row"*.

    What the writer is obliged to put through this seam is the whole question, so
    the arm reads back what was actually asked rather than only what came out.
    """
    answers = FakeCoverageAnswers()
    request = a_request()

    await _proposed(coverage=(), answers=answers)

    ((asked, coverage),) = answers.calls
    assert asked.tool.id == request.tool.id
    assert asked.parameters == request.parameters
    assert coverage == ()


async def test_a_condition_the_writer_takes_first_asks_the_seam_nothing() -> None:
    """A `CONFIRM` an earlier condition refused takes no durable read (ADR-0270 §3).

    Not an optimisation: the seam reads a goal's quotes, and a read taken for a
    row that was never going to be written is work done on the answer's behalf
    about a proposal that does not exist.
    """
    answers = FakeCoverageAnswers()

    assert await _proposed(request_kwargs={"goal": None}, answers=answers) is None
    assert await _proposed(request_kwargs={"binding": None}, answers=answers) is None

    assert answers.call_count == 0


async def test_a_seam_fault_propagates_and_proposes_nothing() -> None:
    """ADR-0270 §4: *"a fault is never an absence"*, and arm 3's propagation limb.

    The writer converts it into neither a met answer nor an unmet one — an unmet
    one would be indistinguishable from a coverage that genuinely is not met, and
    the caller could not tell an authority withheld from one refused. ``_propose``
    catches it one frame up, writes no row, and the one call is confirmed under
    ADR-0148 §3's route (a).
    """
    answers = FakeCoverageAnswers()
    answers.fail_coverage_met()

    with pytest.raises(AuthorizationError):
        await _proposed(answers=answers)


async def test_a_met_coverage_over_a_user_facing_argument_proposes_a_row_now() -> None:
    """ADR-0254 §20 arm 59's third case, as it now reads (ADR-0270 §1).

    Arm 59 states it as *"a `CONFIRM` on an egress request one of whose arguments
    **no resolution minted a member for**"* — the condition is about the coverage
    and never about the argument. Before this lane the writer asked the weaker
    question, refusing every request carrying a user-facing argument whatever the
    coverage; now condition 6 is the member's answer, and a coverage that meets
    the argument **does** found an authority. Nothing on this tree mints such a
    coverage until ADR-0266 §11's L2 lands, which is why the row here is proposed
    over one the test
    supplies.
    """
    covered = (coverage_member(BoundKind.TERMS, bound=terms_bound("hotel-1")),)

    row = await _proposed(
        request_kwargs={"tool": SITED_TOOL, "parameters": {"site": "hotel-1"}},
        coverage=covered,
        answers=an_answerer(),
    )

    assert row is not None
    assert row.coverage == covered
    assert row.quoted is None, "no MONEY member, so the evidence route decided nothing"


async def test_an_argument_no_member_covers_still_proposes_nothing() -> None:
    """Arm 59's third case at its other limb: the completeness condition still bites.

    A coverage naming one argument leaves the *other* one uncovered, so condition 6
    fails and no row is written — which is what makes the case above a real
    condition rather than the writer having stopped asking.
    """
    row = await _proposed(
        request_kwargs={
            "tool": SITED_TOOL,
            "parameters": {"site": "hotel-1", "nights": "2"},
        },
        coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound("hotel-1")),),
        answers=an_answerer(),
    )

    assert row is None


# --- the projection is a transcription (ADR-0267 §7, §11 arm 7) ----------


async def test_the_projection_transcribes_the_rows_own_quote() -> None:
    """ADR-0267 §11 arm 7's projection limb, over a row this writer proposed.

    The figure and the bound are rendered **beside** each other: ADR-0267 §7 is
    explicit that *"a surface that renders a ceiling without the figure the act was
    quoted at is not a disclosure of the same thing"*.
    """
    request = a_priced_request()
    quote = a_quote(request)
    ceiling = (
        coverage_member(
            BoundKind.MONEY,
            bound=money_bound("150", currency="EUR"),
            basis=authorization_basis(span="under a hundred and fifty euros"),
        ),
    )

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=ceiling,
        answers=an_answerer(quotes=FakeGoalQuotes([quote], goal=GOAL)),
    )

    assert row is not None
    projection = projection_of(row)

    assert projection.quote == QuoteView(
        amount=Decimal("120"), currency="EUR", read_at=quote.read_at
    )
    (view,) = projection.coverage
    assert view.bound is not None
    assert view.bound.maximum == Decimal("150")
    assert view.bound.currency == "EUR"
    assert view.span == "under a hundred and fifty euros"


async def test_the_projection_carries_no_quote_where_the_row_carries_none() -> None:
    """ADR-0267 §7: the projection's figure is absent **exactly** where ``quoted`` is."""
    row = await _proposed()

    assert row is not None
    assert row.quoted is None
    assert projection_of(row).quote is None


async def test_a_refresh_landing_after_the_question_moves_no_rendering() -> None:
    """ADR-0267 §11 arm 7: *"the row being the source and nothing re-selecting"*.

    A re-quote arriving between the question and the answer changes the **ruling**
    — ADR-0254 §13's recheck reads the current governing quote at every dispatch —
    and the **rendering** in no way. That is what makes a restart between the two
    recover the same question (ADR-0254 §11), and it is why the row carries the
    figure at all rather than the surface selecting one.
    """
    request = a_priced_request()
    quotes = FakeGoalQuotes([a_quote(request)], goal=GOAL)

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=an_answerer(quotes=quotes),
    )

    assert row is not None
    before = projection_of(row)
    quotes.hold_for(GOAL, a_quote(request, amount="170"))

    assert projection_of(row) == before


# --- the collaborator holds no object the row is written from -------------


@final
class _SubstitutingAnswers:
    """An answerer that swaps the subject out while it holds the writer's operands.

    ADR-0021 §3's substitution capability, one seam over from ``decide``.
    ``frozen=True`` refuses ``request.tool = ...`` and does nothing about
    ``request.__dict__`` (ADR-0018 §3), so an answerer given the writer's own
    objects could answer ``met`` about a harmless call and leave a different
    declaration — and a wider bound — behind for the row.
    """

    def __init__(
        self,
        substitute: ToolDefinition,
        *,
        racing: ActionRequest | None = None,
        racing_coverage: tuple[CoverageMember, ...] = (),
    ) -> None:
        """Answer met, having rewritten whatever it is handed — and ``racing``.

        Args:
            substitute: The declaration it swaps in.
            racing: The **caller's own** request, standing in for any holder that
                rewrites it while this call is suspended. It is reached here
                because that is the only way a unit can put a mutation inside the
                await; what it models is a second task, not this collaborator.
            racing_coverage: The caller's own coverage, for the same reason.
        """
        self.substitute = substitute
        self.racing = racing
        self.racing_coverage = racing_coverage
        self.held: list[ActionRequest] = []

    async def coverage_met(
        self, request: ActionRequest, coverage: tuple[CoverageMember, ...]
    ) -> CoverageAnswer:
        """Rewrite the operands through ``__dict__``, then answer met."""
        self.held.append(request)
        request.__dict__["tool"] = self.substitute
        request.__dict__["goal"] = "g-substituted"
        for member in coverage:
            member.__dict__["fixed"] = "widened"
        if self.racing is not None:
            # **Nested**, which is the half a top-level rebinding does not reach:
            # a name bound to ``request.tool`` before the await aliases this very
            # object, so rewriting a field of it moves what a shallow snapshot
            # would write. Adversarial review, round 2, ``blocker``.
            # **The nested object itself, and it is never replaced first.**
            # Rebinding ``racing.__dict__["tool"]`` would leave a name taken
            # before the await pointing at the untouched original, so the arm
            # would pass the very implementation it exists to reject. What moves
            # here is the declaration a shallow snapshot would still be holding.
            self.racing.tool.__dict__["id"] = "substitute"
            self.racing.__dict__["goal"] = "g-substituted"
        for member in self.racing_coverage:
            member.__dict__["fixed"] = "widened"
        return CoverageAnswer(met=True)


async def test_an_answerer_cannot_substitute_the_subject_of_the_row() -> None:
    """The row names what the `CONFIRM` was recorded over, and never a substitute.

    Two defences and one assertion. The seam is handed :func:`detached_request`'s
    copy and a detached coverage, so it never reaches the writer's objects; and
    every value the row is written from is read **before** the one await, so a
    substitution made anywhere reaches nothing. Either alone would pass this arm,
    and both are written because they close different doors — the first a
    collaborator inside this process, the second anything holding the request while
    the seam is suspended.

    A row naming a substituted declaration would be the failure ADR-0021 §3 calls
    *"the security property, not an economy"*: the `CONFIRM`'s own record names the
    original, so approving the question the user was shown would establish an
    authority over a declaration they were never asked about.
    """
    answers = _SubstitutingAnswers(a_tool(tool_id="substitute"))
    covered = (coverage_member(BoundKind.TERMS, bound=terms_bound("hotel-1")),)

    row = await _proposed(
        request_kwargs={"tool": SITED_TOOL, "parameters": {"site": "hotel-1"}},
        coverage=covered,
        answers=answers,
    )

    assert row is not None
    assert row.tool == SITED_TOOL, "the row names the declaration the CONFIRM was ruled on"
    assert row.goal == GOAL
    assert row.coverage == covered
    assert row.coverage[0].fixed is None
    assert answers.substitute.id != SITED_TOOL.id, "the substitute really was a second tool"


async def test_the_seam_is_handed_no_object_the_writer_holds() -> None:
    """:func:`detached_request`'s timing clause: the copy is taken **before** the call.

    *"A copy taken afterwards faithfully preserves a substitution already made,
    which is the same hole one instruction later."* So the assertion is **identity**
    and not equality — a seam handed the writer's own object holds the capability,
    whether or not any implementation on this tree uses it — and the substitution
    the answerer does make is confined to the copy it was given.
    """
    request = a_request(tool=SITED_TOOL, parameters={"site": "hotel-1"})
    coverage = (coverage_member(BoundKind.TERMS, bound=terms_bound("hotel-1")),)
    answers = _SubstitutingAnswers(a_tool(tool_id="substitute"))

    await proposed_authorization(
        request,
        a_decision(),
        answers=answers,
        coverage=coverage,
        goal=a_goal(deadline=AT + timedelta(hours=12)),
        retention=RETENTION,
        standing=(),
    )

    (handed,) = answers.held
    assert handed is not request, "the answerer holds a copy and never the caller's object"
    assert handed.tool.id == "substitute", "and what it did to that copy stayed there"
    assert request.tool == SITED_TOOL, "the caller's own request is untouched"
    assert request.goal == GOAL
    assert coverage[0].fixed is None, "and so are the caller's own members"


async def test_a_holder_racing_the_await_cannot_move_what_the_row_names() -> None:
    """The snapshot is a **copy** and not a name, nested values included.

    Adversarial review, round 2, ``blocker``: binding ``tool = request.tool``
    before the await fixes which object the row names and **not** what that object
    says, so a holder that rewrote ``request.tool.__dict__["id"]`` while the
    answerer was suspended still moved the declaration the row was written for.
    ``detached_request`` round-trips through a dump, so the writer's copy shares no
    object with the caller's request at any depth.

    The answerer is given the caller's own values here because a unit has no other
    way to land a mutation **inside** the await; what it stands in for is any
    second holder, and the assertion is about the writer rather than about it.
    """
    request = a_request(tool=SITED_TOOL, parameters={"site": "hotel-1"})
    coverage = (coverage_member(BoundKind.TERMS, bound=terms_bound("hotel-1")),)
    # Compared against afterwards, because the race rewrites ``coverage`` itself —
    # which is the whole point, and which makes an assertion against it vacuous.
    pristine = tuple(member.model_copy(deep=True) for member in coverage)
    answers = _SubstitutingAnswers(
        a_tool(tool_id="substitute"), racing=request, racing_coverage=coverage
    )

    row = await proposed_authorization(
        request,
        a_decision(),
        answers=answers,
        coverage=coverage,
        goal=a_goal(deadline=AT + timedelta(hours=12)),
        retention=RETENTION,
        standing=(),
    )

    assert row is not None
    assert row.tool.id == SITED_TOOL.id, "the row names the declaration that was ruled on"
    assert row.tool == SITED_TOOL
    assert row.goal == GOAL
    assert row.coverage == pristine
    assert row.coverage[0].fixed is None
    # The race really did land: the caller's own request and members now say
    # otherwise, which is what makes the assertions above about the snapshot
    # rather than about an answerer that did nothing.
    assert request.tool.id == "substitute"
    assert request.goal == "g-substituted"
    assert coverage[0].fixed == "widened"


@final
class _RetainingAnswers:
    """An answerer that keeps the quote it handed back, and rewrites it afterwards.

    ADR-0267 §7 makes ``quoted`` *"written once and never edited"*, and ADR-0270
    §2 makes it the operand the proof was taken over. ``Authorization`` stores a
    model field **by reference**, so a writer that passed the answer's own object
    straight through would leave the figure on the row — and therefore the figure
    the projection renders — a value the answerer could still move.
    """

    def __init__(self, quote: ActionQuote) -> None:
        """Answer met, carrying ``quote``, and keep it."""
        self.quote = quote

    async def coverage_met(
        self, request: ActionRequest, coverage: tuple[CoverageMember, ...]
    ) -> CoverageAnswer:
        """The configured met answer, carrying the object this object retains."""
        del request, coverage
        return CoverageAnswer(met=True, quoted=self.quote)


async def test_a_quote_the_answerer_kept_cannot_move_the_figure_on_the_row() -> None:
    """ADR-0267 §7's write-once rule, held at the one place the figure enters a row.

    Adversarial review, round 3, ``blocker``. The answer is the collaborator's
    value and the row is the durable record, so the figure is copied across rather
    than referenced: a price the user was shown, and an approval established, is
    not one a later rewrite may edit.
    """
    request = a_priced_request()
    answers = _RetainingAnswers(a_quote(request))

    row = await _proposed(
        request_kwargs={
            "tool": PRICED_TOOL,
            "parameters": {"site": "hotel-1"},
            "intended_action": ACT,
        },
        coverage=PRICE_CEILING,
        answers=answers,
    )

    assert row is not None
    assert row.quoted is not None
    assert row.quoted is not answers.quote, "the row holds its own copy"
    answers.quote.__dict__["amount"] = Decimal("999")

    assert row.quoted.amount == Decimal("120")
    assert projection_of(row).quote == QuoteView(
        amount=Decimal("120"), currency="EUR", read_at=answers.quote.read_at
    )
