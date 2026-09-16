"""The composed producer and consumer: a price is read, and a ceiling is proved on it.

ADR-0267 §11's arm 4 is the mint in isolation (``test_quote_mint.py``) and its arm 5 is
the comparison in isolation (``tests/permissions/``). **Neither of them is this**: what
is driven here is one goal, one act and two steps of one plan — an investigation step
whose output states ``120``/``EUR``, and a booking step at a **different declaration**
whose `CONFIRM` proposes a row carrying that very quote, proved against the ``150``
euro ceiling the user's own words stated.

Everything the answer turns on is **produced** rather than configured. The quote is the
one this lane's mint appended; condition 6's answer is
:class:`~ai_assistant.permissions.policy.ThresholdActionPolicy`'s, which ADR-0270 §1
makes its one implementation, over the goal's own quotes through ``GoalQuotes`` — so
what these cases pin is the two halves actually meeting, which no arm over a configured
``FakeCoverageAnswers`` can show. ``test_closed_loop.py``'s own reason for reaching a
production collaborator, one seam over.

**And §8's writer clause, driven where a model could actually reach it.** A planner
envelope is ``extra="forbid"``, so the only route for any value this decision adds is a
plan step's free-form ``parameters`` — and a step carrying every one of them mints
exactly what the same step without them mints.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from authorizing_builders import ACT_TURN, AT, GOAL, RETENTION, a_tool

from ai_assistant.core.types import (
    ActionPlan,
    ActionQuote,
    Authorization,
    BoundKind,
    CostBasis,
    DataTier,
    Disposition,
    Goal,
    GoalAttempt,
    GoalElement,
    GoalInterpretation,
    Ground,
    Idempotency,
    IntendedAction,
    IntendedActionMinting,
    MemorySource,
    PlanStep,
    Provenance,
    QuotedOutput,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import ExecutionState, FrozenJson
    from ai_assistant.testing.invoker import FakeToolImplementation

PATIENT: Final = timedelta(seconds=30)
PLAN: Final = "p-1"
ATTEMPT: Final = "a-1"
READ: Final = "step-read"
BOOK: Final = "step-book"
ACT: Final = "ia-1"
CONNECTION: Final = "conn-1"
IDENTITY: Final = "work@example.com"

#: The user's own words, and the ceiling ADR-0266 §4 reads out of them.
CEILING: Final = (
    GoalElement(
        id="e-1",
        text="the ceiling for the trip",
        ground=Ground.USER_STATED,
        span="up to 150 euros",
    ),
)

#: What the investigation step's provider returns — a price, a currency, and a number
#: of the right shape in the wrong slot (ADR-0267 §3).
PRICED: Final[dict[str, FrozenJson]] = {"price": "120", "stars": 4, "currency": "EUR"}

#: The declaration's own statement of where its price is (ADR-0267 §3).
QUOTED: Final = QuotedOutput(amount="price", currency="currency")

#: What §8 forbids a model to contribute, as a planner could actually smuggle it: an
#: `ActionQuote`, a `QuotedOutput`, a `QuoteView`, an amount, a currency, an output key
#: and an arguments digest — every value on ADR-0267 §8's list.
SMUGGLED: Final[dict[str, FrozenJson]] = {
    "quote": {
        "intended_action": ACT,
        "arguments_digest": "f" * 64,
        "amount": "1",
        "currency": "EUR",
        "plan": "p-forged",
        "read_from": {"step": "step-forged", "field": "stars"},
        "read_at": "2020-01-01T00:00:00Z",
    },
    "quoted_output": {"amount": "stars", "currency": "currency"},
    "quote_view": {"amount": "1", "currency": "EUR", "read_at": "2020-01-01T00:00:00Z"},
    "amount": "1",
    "currency": "USD",
    "output_key": "stars",
    "arguments_digest": "f" * 64,
}


def a_quoting_tool(*, quoted: QuotedOutput | None = QUOTED) -> ToolDefinition:
    """The **investigation** declaration, saying where its price is (ADR-0267 §3)."""
    return a_tool(
        "rooms", capability="check_price", description="Quote a room.", quoted_output=quoted
    )


def a_booking_tool() -> ToolDefinition:
    """The **booking** declaration: a different tool, quoting nothing of its own.

    ADR-0267 §1: *"a quote is bound to the act and to the arguments, and never to the
    declaration that produced it"* — *"the owner's own case reads a price from an
    availability tool and performs the act at a **booking** tool"*. It discloses
    off-device, so the fake policy `CONFIRM`s it and a row is proposed.
    """
    return a_tool(
        "booking",
        capability="book_room",
        description="Book a room.",
        discloses=(DataTier.PERSONAL,),
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


def a_priced_goal() -> Goal:
    """A goal whose one ``USER_STATED`` constraint states the ceiling."""
    return Goal(
        id=GOAL,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room in Lisbon",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room in Lisbon",
                constraints=CEILING,
                recorded_at=AT,
                raised_by=ACT_TURN,
            ),
        ),
        deadline=AT + timedelta(hours=12),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


def returning(output: FrozenJson) -> FakeToolImplementation:
    """A provider that succeeds with ``output``."""

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        return output

    return implementation


class Walk:
    """One goal, one act, and a two-step plan driven a step at a time.

    The engine drives one step per turn, so the *"subsequent turn"* every arm of
    ADR-0267 §11 is stated as is a second :meth:`drive` here. The collaborators are the
    canonical fakes, except the one the arm is about: condition 6's answer is
    ``permissions``' own.
    """

    def __init__(
        self,
        *,
        output: FrozenJson = PRICED,
        parameters: Mapping[str, FrozenJson] | None = None,
        reader: ToolDefinition | None = None,
    ) -> None:
        """Wire the stage, the real answerer reading this store's quotes."""
        self.plans = FakePlanStore(now=lambda: AT)
        self.trail = FakeAuditTrail()
        self.reader = a_quoting_tool() if reader is None else reader
        self.booker = a_booking_tool()
        self.invoker = FakeToolInvoker(
            [(self.reader, returning(output)), (self.booker, returning(None))],
            ledger=self.trail,
            gate=self.trail,
        )
        self.binder = FakeEgressBinder()
        # Only the **booking** call is an egress one, which is ADR-0254 §1's second
        # proposal condition. The investigation reads a price and transmits nothing.
        self.binder.register_egress(self.booker, reference=CONNECTION, identity=IDENTITY)
        self.authorizations = FakeGoalAuthorizationStore()
        #: **The real condition 6**, over this very store's quotes (ADR-0270 §1,
        #: ADR-0267 §5): `permissions` selects the governing quote, compares the
        #: digest against the concrete request and takes the currency conjunct at the
        #: quote's own currency. Nothing here configures the answer.
        self.answers = ThresholdActionPolicy(quotes=self.plans)
        ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=FakeActionPolicy(),
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            binder=self.binder,
            authorizations=self.authorizations,
            coverage_answers=self.answers,
            episode_retention=RETENTION,
            now=lambda: AT,
            id_factory=lambda: next(ids),
        )
        self.parameters: Mapping[str, FrozenJson] = {} if parameters is None else parameters

    async def opened(self) -> ExecutionState:
        """Store the goal, mint the act, save the two-step plan and open the walk."""
        await self.plans.save_goal(a_priced_goal())
        await self.plans.record_intended_actions(
            IntendedActionMinting(
                goal_id=GOAL,
                actions=(IntendedAction(id=ACT, intent="book the room"),),
                expected_version=0,
            )
        )
        plan = ActionPlan(
            id=PLAN,
            goal_id=GOAL,
            steps=(
                # **Both steps serve one act and carry one set of arguments**, which is
                # what ADR-0266 §7's digest conjunct requires of a covered call: *"a
                # quoting call and an acting call differing in **any** key carry
                # different digests, are covered by no quote, and ask"*.
                PlanStep(
                    id=READ,
                    intent="price the room",
                    capability="check_price",
                    parameters=self.parameters,
                    intended_action=ACT,
                ),
                PlanStep(
                    id=BOOK,
                    intent="book the room",
                    capability="book_room",
                    intended_action=ACT,
                ),
            ),
            created_at=AT,
            targets_revision=1,
        )
        await self.plans.save_plan(plan)
        state = await self.plans.start_execution(plan.id)
        await self.plans.open_attempt(
            GoalAttempt(
                id=ATTEMPT,
                goal_id=GOAL,
                opened_at=AT,
                plan_ids=(plan.id,),
                execution_ids=(state.id,),
            )
        )
        return state

    async def drive(
        self, state: ExecutionState, step_id: str
    ) -> tuple[Disposition, ExecutionState]:
        """Dispose of one step and hand back what it became."""
        result = await self.runner.run(
            state, step_id, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
        )
        return result.disposition, result.state

    async def quotes(self) -> tuple[ActionQuote, ...]:
        """The quotes the goal holds."""
        goal = await self.plans.get_goal(GOAL)
        assert goal is not None
        return goal.quotes

    async def rows(self) -> tuple[Authorization, ...]:
        """Every row the authorization store holds."""
        return await self.authorizations.export()


async def _walked(
    output: FrozenJson = PRICED,
    *,
    parameters: Mapping[str, FrozenJson] | None = None,
    reader: ToolDefinition | None = None,
) -> Walk:
    """Drive the investigation step and then the booking step."""
    walk = Walk(output=output, parameters=parameters, reader=reader)
    opened = await walk.opened()

    read, after = await walk.drive(opened, READ)
    assert read is Disposition.EXECUTED

    booked, _ = await walk.drive(after, BOOK)
    assert booked is Disposition.AWAITING_CONFIRMATION
    return walk


# --- the composition (the walkthrough's own shape) ----------------------


async def test_a_price_read_at_one_declaration_proves_the_ceiling_at_another() -> None:
    """Producer to consumer, end to end, with nothing between them configured.

    The investigation step mints one quote at ``120``/``EUR`` for the act; the booking
    step's `CONFIRM` then proposes a row whose ``coverage`` is the ``150`` euro member
    the user's own words minted (ADR-0266 §4) and whose ``quoted`` is that quote **field
    for field** (ADR-0267 §7). The two declarations are different, which is *"the owner's
    own check-then-book case"*, and no clause compares them.
    """
    walk = await _walked()

    (minted,) = await walk.quotes()
    assert minted.amount == Decimal("120")
    assert minted.currency == "EUR"
    assert minted.intended_action == ACT
    assert minted.read_from.step == READ, "read at the investigation step"

    (row,) = await walk.rows()
    (member,) = row.coverage
    assert member.kind is BoundKind.MONEY
    assert member.bound is not None
    assert member.bound.maximum == Decimal("150")
    assert member.basis.span == "up to 150 euros"
    assert row.quoted is not None
    assert row.quoted.model_dump() == minted.model_dump(), "the row records the figure read"
    assert row.tool.id == walk.booker.id, "and the act is at the other declaration"


async def test_a_reading_above_the_ceiling_proposes_no_row_and_the_act_asks() -> None:
    """The control, and it is the fail-closed direction.

    The same walk with the provider quoting ``170`` leaves condition 6 unmet, so **no
    row is proposed** — ADR-0254 §1: *"``Confirmation.authorization`` is absent … and the
    answer establishes nothing"*. The quote is still minted: the mint states what was
    read and draws no conclusion from it (ADR-0267 §4).
    """
    walk = await _walked({"price": "170", "currency": "EUR"})

    (minted,) = await walk.quotes()
    assert minted.amount == Decimal("170")
    assert await walk.rows() == (), "a ceiling nothing proves leaves no authority to grant"


async def test_a_reading_in_another_currency_proves_nothing() -> None:
    """ADR-0266 §7 compares the currency **byte for byte** (ADR-0254 §4).

    ``120``/``USD`` is a smaller number than the ``150`` ``EUR`` ceiling and covers
    nothing, which is the whole reason ADR-0267 §1 puts the shape on the record.
    """
    walk = await _walked({"price": "120", "currency": "USD"})

    (minted,) = await walk.quotes()
    assert minted.currency == "USD"
    assert await walk.rows() == ()


async def test_a_declaration_quoting_nothing_leaves_the_ceiling_unproved() -> None:
    """ADR-0267 §3: *"A declaration carrying ``None`` yields no quote ever"*.

    So every act proved against a quote of that declaration's output is uncovered and
    **asks** — the fail-closed ground on which ADR-0016 §1's default is taken.
    """
    walk = await _walked(reader=a_quoting_tool(quoted=None))

    assert await walk.quotes() == ()
    assert await walk.rows() == ()


# --- ADR-0267 §8: what no model contributes ------------------------------


def test_no_field_of_a_plan_or_a_planner_envelope_admits_any_value_this_decision_adds() -> None:
    """§3, §8: *"No plan, no plan step, no planner envelope … carries a key a price is
    read at"*, and no amount, currency, quote or digest either.

    The containment is **structural**, which is what makes the discard silent rather
    than a check somebody has to remember: there is no field for any of these values to
    arrive on, and ``PlannerOutput`` forbids extras, so the only route left is a step's
    free-form ``parameters`` — which the arm below drives.
    """
    forbidden = {
        "quote",
        "quotes",
        "quoted",
        "quoted_output",
        "amount",
        "currency",
        "arguments_digest",
        "output_key",
    }
    assert forbidden.isdisjoint(PlanStep.model_fields)
    assert forbidden.isdisjoint(ActionPlan.model_fields)


async def test_a_step_smuggling_every_value_section_8_names_mints_what_the_others_mint() -> None:
    """§8: those values are *"discarded silently — not an error, not a park, not a
    degradation of the turn"*.

    A plan step whose free-form ``parameters`` carry an `ActionQuote`, a `QuotedOutput`,
    a `QuoteView`, an amount, a currency, an output key and an arguments digest mints a
    quote whose **amount**, **currency**, **act**, **plan** and **read_from** are exactly
    those of the same step without them. The forged ``1``/``USD``, the forged
    ``stars`` output key and the forged plan and step reach nothing.

    The one value that legitimately differs is ``arguments_digest`` — because the
    smuggled keys **are** arguments of the quoting call, and §1 puts *"every argument of
    the quoting call"* inside it. So it is asserted to be **this request's own** property
    and never the digest the envelope carried, which is §8's claim rather than a
    weakening of it.
    """
    bare = await _walked()
    smuggling = await _walked(parameters=SMUGGLED)

    (plain,) = await bare.quotes()
    (minted,) = await smuggling.quotes()
    assert (minted.amount, minted.currency) == (Decimal("120"), "EUR")
    assert minted.model_dump(exclude={"arguments_digest"}) == plain.model_dump(
        exclude={"arguments_digest"}
    )
    assert minted.arguments_digest != "f" * 64, "the request's own property, not the envelope's"
    assert minted.read_from.field == "price", "the declaration's key, never the smuggled one"
    assert minted.plan == PLAN, "and the plan it was actually read in"


async def test_a_smuggled_quoted_output_does_not_make_an_unquoting_declaration_quote() -> None:
    """§3: the key that selects the number lives on the declaration and on nothing a
    turn produces.

    Against ``{"price": "200", "stars": 4, "currency": "EUR"}`` a plan-carried selector
    naming ``stars`` would quote ``4``, satisfy a ``150`` ceiling and authorise the
    ``200`` purchase — *"a number of the right **shape** in the wrong **slot**"*. Here
    the declaration names **no** quoted output and the step carries one: nothing is
    minted, so nothing is covered and the act asks.
    """
    walk = await _walked(
        {"price": "200", "stars": 4, "currency": "EUR"},
        parameters=SMUGGLED,
        reader=a_quoting_tool(quoted=None),
    )

    assert await walk.quotes() == ()
    assert await walk.rows() == ()
