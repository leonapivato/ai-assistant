"""ADR-0267 §11's **arm 4**: the mint, driven through ``orchestration``.

Everything here is driven over the canonical fakes, through the stage that actually
mints — :class:`~ai_assistant.orchestration.runner.StepRunner`, whose ``_execute`` is
every path a step's output is recorded in this subsystem — or, where the arm is about
the **write** rather than the reading, through
:mod:`ai_assistant.orchestration.quotes`'s own two halves.

The three clocks are deliberately distinguishable. The **store's** is :data:`AT`, so
``StepExecution.finished_at`` — the instant the output was recorded — is ``AT``; the
**runner's** is :data:`MUCH_LATER`, so a mint that read a clock of its own would be
visible in ``read_at`` at once (§4: *"``read_at`` is the step's instant, never the
mint's"*).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import PlanningError, StaleExecutionError
from ai_assistant.core.types import (
    MAX_ACTION_QUOTES,
    ActionPlan,
    ActionQuote,
    ActionQuoteMinting,
    CostBasis,
    Disposition,
    Goal,
    GoalAttempt,
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
    StepOutputRef,
    StepStatus,
    StepVerification,
    ToolCost,
    ToolDefinition,
    VerificationKind,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.orchestration.quotes import mint_quote, record_minted_quote
from ai_assistant.testing import FakeActionPolicy, FakeAuditTrail, FakePlanStore, FakeToolInvoker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.types import ExecutionState, FrozenJson, PermissionDecision
    from ai_assistant.orchestration.runner import Ruled
    from ai_assistant.testing.invoker import FakeToolImplementation

#: The **store's** clock. Every durable instant here is this one, ``finished_at``
#: included, which is what ``read_at`` must equal.
AT: Final = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)

#: The **runner's** clock, a day on. Nothing this lane writes may carry it: it exists
#: so that a mint reading a clock of its own is caught rather than assumed absent.
MUCH_LATER: Final = AT + timedelta(days=1)

PATIENT: Final = timedelta(seconds=30)
GOAL: Final = "g-1"
PLAN: Final = "p-1"
STEP: Final = "step-1"
NEIGHBOUR: Final = "step-2"
ATTEMPT: Final = "a-1"
ACT: Final = "act-1"
OTHER_ACT: Final = "act-2"
CAPABILITY: Final = "check_price"

#: What the owner's own case reads: a price, a currency, and a number of the right
#: **shape in the wrong slot** (ADR-0267 §3). ``stars`` must appear nowhere in a quote.
PRICED: Final[dict[str, FrozenJson]] = {"price": "120", "stars": 4, "currency": "EUR"}

#: The declaration's own statement of where its price is (§3).
QUOTED: Final = QuotedOutput(amount="price", currency="currency")


# --- builders -----------------------------------------------------------


def declaration(tool_id: str = "rooms", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright, quoting its output."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": CAPABILITY,
        "description": "Quote a room.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
        "quoted_output": QUOTED,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def step(
    step_id: str = STEP,
    *,
    intended_action: str | None = ACT,
    verifies: StepVerification | None = None,
) -> PlanStep:
    """The step whose output a price is read from."""
    return PlanStep(
        id=step_id,
        intent="price the room",
        capability=CAPABILITY,
        parameters={"city": "Lisbon", "nights": 2},
        intended_action=intended_action,
        verifies=verifies,
    )


def quote(
    amount: str = "120",
    *,
    currency: str = "EUR",
    action: str = ACT,
    digest: str | None = None,
    at: datetime = AT,
) -> ActionQuote:
    """A quote of the shape the mint produces, for the arms that write directly."""
    return ActionQuote(
        intended_action=action,
        arguments_digest=digest if digest is not None else "0" * 64,
        amount=Decimal(amount),
        currency=currency,
        plan=PLAN,
        read_from=StepOutputRef(step=STEP, field="price"),
        read_at=at,
    )


async def a_goal(store: FakePlanStore, *, actions: tuple[str, ...] = (ACT,)) -> Goal:
    """Store a goal holding ``actions``, through the writers that own each field."""
    await store.save_goal(
        Goal(
            id=GOAL,
            interpretation=(
                GoalInterpretation(
                    revision=1,
                    outcome="book a room in Lisbon",
                    outcome_ground=Ground.USER_STATED,
                    outcome_span="book a room in Lisbon",
                    recorded_at=AT,
                    raised_by="t-1",
                ),
            ),
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
            created_at=AT,
        )
    )
    return await store.record_intended_actions(
        IntendedActionMinting(
            goal_id=GOAL,
            actions=tuple(IntendedAction(id=one, intent=f"perform {one}") for one in actions),
            expected_version=0,
        )
    )


async def an_execution(
    store: FakePlanStore, *steps: PlanStep, actions: tuple[str, ...] = (ACT,)
) -> ExecutionState:
    """Store the goal, a plan over ``steps``, and open an execution under an attempt."""
    await a_goal(store, actions=actions)
    plan = ActionPlan(id=PLAN, goal_id=GOAL, steps=steps, created_at=AT, targets_revision=1)
    await store.save_plan(plan)
    state = await store.start_execution(plan.id)
    await store.open_attempt(
        GoalAttempt(
            id=ATTEMPT,
            goal_id=GOAL,
            opened_at=AT,
            plan_ids=(plan.id,),
            execution_ids=(state.id,),
        )
    )
    return state


def returning_each(*outputs: FrozenJson) -> FakeToolImplementation:
    """A tool that succeeds with each of ``outputs`` in turn — one re-quote, one call."""
    remaining = list(outputs)

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        return remaining.pop(0)

    return implementation


def returning(output: FrozenJson) -> FakeToolImplementation:
    """A tool that succeeds with ``output``."""

    async def implementation(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        return output

    return implementation


class Harness:
    """A wired ``StepRunner`` whose store clock and runner clock are distinguishable."""

    def __init__(
        self,
        *,
        tools: tuple[tuple[ToolDefinition, FakeToolImplementation], ...] = (),
        plans: FakePlanStore | None = None,
    ) -> None:
        """Wire the stage over canonical fakes, the store stamping :data:`AT`."""
        self.plans = plans if plans is not None else FakePlanStore(now=lambda: AT)
        self.policy = FakeActionPolicy()
        self.trail = FakeAuditTrail()
        self.invoker = FakeToolInvoker(tools, ledger=self.trail, gate=self.trail)
        #: The execution the last :meth:`drive` ran a step of, for reading it back.
        self.drove: ExecutionState | None = None
        ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans,
                registry=self.invoker,
                invoker=self.invoker,
                now=lambda: MUCH_LATER,
            ),
            # The runner's own clock, a day after every durable instant here.
            now=lambda: MUCH_LATER,
            id_factory=lambda: next(ids),
        )

    async def drive(
        self, state: ExecutionState, step_id: str = STEP, *, on_ruled: Ruled | None = None
    ) -> Disposition:
        """Run one step and report how it was disposed of.

        ``on_ruled`` is ADR-0249 §12's boundary — the earliest ``await`` after the
        request is built and before the step is claimed, and therefore the earliest
        place a collaborator of this stage can act.
        """
        self.drove = state
        result = await self.runner.run(
            state,
            step_id,
            attempt_id=ATTEMPT,
            timeout=PATIENT,
            origin=NOTHING_EXTERNAL,
            on_ruled=on_ruled,
        )
        return result.disposition

    async def quotes(self) -> tuple[ActionQuote, ...]:
        """The goal's quotes as stored."""
        goal = await self.plans.get_goal(GOAL)
        assert goal is not None
        return goal.quotes


async def driven(
    output: FrozenJson,
    *,
    tool: ToolDefinition | None = None,
    plan_step: PlanStep | None = None,
) -> tuple[Harness, tuple[ActionQuote, ...]]:
    """Drive one step returning ``output`` and hand back the harness and the quotes."""
    definition = declaration() if tool is None else tool
    harness = Harness(tools=((definition, returning(output)),))
    state = await an_execution(harness.plans, plan_step if plan_step is not None else step())

    assert await harness.drive(state) is Disposition.EXECUTED

    return harness, await harness.quotes()


# --- the positive mint (§11 arm 4, first paragraph) ----------------------


async def test_a_quoted_output_mints_exactly_one_quote_naming_where_it_was_read() -> None:
    """*"mints exactly one quote, at ``120``/``EUR``"*, and ``stars`` appears nowhere.

    The whole of arm 4's positive limb: the amount and the currency come from the keys
    the **declaration** names, the digest is *"the ``parameters_digest`` of the
    ``ActionRequest`` whose output it was read from"* and never a value computed a
    second way, and ``plan``/``read_from`` name the place — *"a step id alone names no
    place"* (§1).
    """
    harness, quotes = await driven(PRICED)

    (minted,) = quotes
    assert minted.amount == Decimal("120")
    assert minted.currency == "EUR"
    assert minted.intended_action == ACT
    assert minted.plan == PLAN
    assert minted.read_from == StepOutputRef(step=STEP, field="price")
    (ruled,) = harness.policy.requests
    assert minted.arguments_digest == ruled.parameters_digest, "the quoting request's own"
    assert minted.amount != Decimal("4"), "the number in the right shape and the wrong slot"
    assert "stars" not in minted.model_dump_json(), "the key appears nowhere in the record"
    assert 4 not in minted.model_dump().values(), "and neither does its value"


async def test_read_at_is_the_instant_the_output_was_recorded_and_never_the_mints() -> None:
    """§4: *"``read_at`` is the step's instant, never the mint's"*.

    The store stamps ``AT`` on the step's ``finished_at`` and every clock the runner and
    the executor hold reads ``MUCH_LATER``, a day on — so a quote minted late still
    states **when the price was read**, which is the instant §6's disclosure renders and
    §7 transcribes. The assertion is against the step's own stored record rather than
    against the constant, so it is the recorded instant and not a matching one.
    """
    harness, quotes = await driven(PRICED)

    assert harness.drove is not None
    stored = await harness.plans.get_execution(harness.drove.id)
    assert stored is not None
    recorded = stored.step(STEP)
    assert recorded is not None
    (minted,) = quotes
    assert minted.read_at == recorded.finished_at == AT
    assert minted.read_at != MUCH_LATER, "no clock of the mint's own reached the record"


async def test_a_json_integer_and_the_string_form_each_record_the_same_decimal() -> None:
    """§11 arm 4: *"the mint of a JSON integer ``0`` and a string ``"0"`` each records
    ``Decimal("0")``"*. **Zero is a price** (§1) and is no absence."""
    _, from_integer = await driven({"price": 0, "currency": "EUR"})
    _, from_string = await driven({"price": "0", "currency": "EUR"})

    (one,) = from_integer
    (other,) = from_string
    assert one.amount == Decimal("0") == other.amount


# --- every failure of the reading (§4, §11 arm 4's refusal list) ---------


@pytest.mark.parametrize(
    ("output", "why"),
    [
        pytest.param("a string", "an `output` that is not a JSON object", id="not-an-object"),
        pytest.param({"currency": "EUR"}, "a missing `price` key", id="no-amount-key"),
        pytest.param({"price": "120"}, "a missing `currency` key", id="no-currency-key"),
        pytest.param({"price": 120.0, "currency": "EUR"}, "a JSON float", id="json-float"),
        pytest.param({"price": True, "currency": "EUR"}, "a JSON boolean true", id="json-true"),
        pytest.param({"price": False, "currency": "EUR"}, "a JSON boolean false", id="json-false"),
        pytest.param({"price": "-1", "currency": "EUR"}, "a negative amount", id="negative"),
        pytest.param({"price": -1, "currency": "EUR"}, "a negative integer", id="negative-int"),
        pytest.param(
            {"price": "free", "currency": "EUR"}, "a non-numeric string", id="not-a-number"
        ),
        pytest.param({"price": "NaN", "currency": "EUR"}, "`Decimal` accepts NaN", id="nan"),
        pytest.param({"price": "Infinity", "currency": "EUR"}, "and Infinity", id="inf"),
        pytest.param({"price": "-Infinity", "currency": "EUR"}, "and -Infinity", id="-inf"),
        pytest.param(
            {"price": "120", "currency": 978}, "a currency that is not a string", id="code"
        ),
        pytest.param(
            {"price": "120", "currency": "usd"}, "a currency of the wrong shape", id="usd"
        ),
        pytest.param({"price": "120", "currency": "EURO"}, "and another", id="euro"),
        pytest.param({"price": "120", "currency": "€"}, "and a symbol", id="symbol"),
    ],
)
async def test_a_reading_that_fails_mints_nothing_and_raises_nothing(
    output: FrozenJson, why: str
) -> None:
    """§4: *"every failure of that reading mints nothing … and raises nothing"*.

    Nothing is repaired, coerced, defaulted or substituted, *"the validator's own
    exception included"*, and the step still executed: the consequence *"in every case
    is that the act is proved against no quote and asks"*, never a turn that failed.
    """
    harness, quotes = await driven(output)

    assert quotes == (), why
    goal = await harness.plans.get_goal(GOAL)
    assert goal is not None
    assert goal.quotes_elided == 0


async def test_a_step_naming_no_intended_action_mints_nothing() -> None:
    """§4's second condition: *"A step with no ``intended_action``"* mints nothing."""
    _, quotes = await driven(PRICED, plan_step=step(intended_action=None))

    assert quotes == ()


async def test_a_declaration_naming_no_quoted_output_mints_nothing() -> None:
    """§3: *"A declaration carrying ``None`` yields no quote ever"* — the act asks."""
    _, quotes = await driven(PRICED, tool=declaration(quoted_output=None))

    assert quotes == ()


async def test_a_step_the_seam_did_not_finish_succeeded_mints_nothing() -> None:
    """§4's first condition: the step is ``SUCCEEDED``, and this one is not."""

    async def fails(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        msg = "the provider refused"
        raise RuntimeError(msg)

    harness = Harness(tools=((declaration(), fails),))
    state = await an_execution(harness.plans, step())

    assert await harness.drive(state) is Disposition.EXECUTED

    stored = await harness.plans.get_execution(state.id)
    assert stored is not None
    finished = stored.step(STEP)
    assert finished is not None
    assert finished.status is StepStatus.FAILED
    assert await harness.quotes() == ()


# --- what the mint reads, and what it does not ---------------------------


async def test_the_mint_reads_its_own_step_alone() -> None:
    """§4: *"the mint reads the step's own output, its own request and its own
    declaration, and reads nothing else"*.

    A second step of the same walk returning a **different** price changes nothing about
    the quote minted from the first: two steps, two drives, two quotes, each stating its
    own reading — and neither derived from the other (§4: no arithmetic, no sum of
    components, no conversion).
    """
    harness = Harness(
        tools=(
            (declaration("rooms"), returning(PRICED)),
            (
                declaration("flights", capability="check_fare"),
                returning({"price": "900", "currency": "EUR"}),
            ),
        )
    )
    state = await an_execution(
        harness.plans,
        step(),
        step(NEIGHBOUR, intended_action=OTHER_ACT).model_copy(update={"capability": "check_fare"}),
        actions=(ACT, OTHER_ACT),
    )

    assert await harness.drive(state) is Disposition.EXECUTED
    reloaded = await harness.plans.get_execution(state.id)
    assert reloaded is not None
    assert await harness.drive(reloaded, NEIGHBOUR) is Disposition.EXECUTED

    first, second = await harness.quotes()
    assert (first.intended_action, first.amount) == (ACT, Decimal("120"))
    assert (second.intended_action, second.amount) == (OTHER_ACT, Decimal("900"))
    assert first.read_from.step == STEP
    assert second.read_from.step == NEIGHBOUR


async def test_no_verifies_is_read_and_a_failing_predicate_mints_exactly_as_a_holding_one() -> None:
    """§4: *"No ``verifies`` is among the four and none is evaluated here."*

    ADR-0255 §8 reads that predicate at exactly two sites; a mint conditioned on it would
    be a **third**, and would put a plan-carried, model-authored predicate in the path of
    a quote. So a ``SUCCEEDED`` step whose plan-declared predicate would **fail** over its
    own output mints exactly as one whose predicate holds.
    """
    failing = step(
        verifies=StepVerification(kind=VerificationKind.FIELD_EQUALS, field="price", equals="99999")
    )
    holding = step(
        verifies=StepVerification(kind=VerificationKind.FIELD_EQUALS, field="price", equals="120")
    )

    _, from_failing = await driven(PRICED, plan_step=failing)
    _, from_holding = await driven(PRICED, plan_step=holding)

    assert len(from_failing) == 1
    assert from_failing[0].amount == Decimal("120")
    assert from_failing[0].model_dump() == from_holding[0].model_dump()


async def test_a_second_reading_appends_and_never_edits_and_the_last_governs() -> None:
    """§4: *"a second reading is an append and never an edit"*.

    *"no lane marks, supersedes, invalidates, edits or removes the quote it displaced"* —
    the Sunday re-quote governs by **position** (§2) and the Saturday one is left exactly
    where it was, unmarked.
    """
    harness = Harness(
        tools=((declaration(), returning_each(PRICED, {"price": "135", "currency": "EUR"})),)
    )
    state = await an_execution(harness.plans, step(), step(NEIGHBOUR))
    assert await harness.drive(state) is Disposition.EXECUTED
    reloaded = await harness.plans.get_execution(state.id)
    assert reloaded is not None

    assert await harness.drive(reloaded, NEIGHBOUR) is Disposition.EXECUTED

    saturday, sunday = await harness.quotes()
    assert saturday.amount == Decimal("120")
    assert sunday.amount == Decimal("135")
    assert saturday.intended_action == sunday.intended_action == ACT


# --- the two interruption boundaries (§4, §11 arm 4) --------------------


class _Refusing(FakePlanStore):
    """A store whose ``record_quote`` stops the process, as a crash between two writes."""

    async def record_quote(self, minting: ActionQuoteMinting) -> Goal:
        """Never land the append."""
        msg = "the process stopped between the transition and the mint"
        raise asyncio.CancelledError(msg)


async def test_a_stop_between_the_transition_and_the_mint_leaves_the_output_and_no_quote() -> None:
    """§4: *"the mint is not atomic with the transition that recorded the output"*.

    *"A process stopping between the two writes leaves the step ``SUCCEEDED`` with its
    output and the goal without that reading"* — and **no lane reconciles a missing quote
    from a stored output**, so a later drive over the same execution mints nothing either.
    The act asks.
    """
    harness = Harness(tools=((declaration(), returning(PRICED)),), plans=_Refusing(now=lambda: AT))
    state = await an_execution(harness.plans, step())

    with pytest.raises(asyncio.CancelledError):
        await harness.drive(state)

    stored = await harness.plans.get_execution(state.id)
    assert stored is not None
    finished = stored.step(STEP)
    assert finished is not None
    assert finished.status is StepStatus.SUCCEEDED, "the transition committed"
    assert finished.output == PRICED, "with its output"
    assert await harness.quotes() == (), "and the goal without that reading"

    # A second drive over the same stored execution reconciles nothing: the step is no
    # longer `PENDING`, so nothing re-reads that output and nothing mints from it.
    reloaded = await harness.plans.get_execution(state.id)
    assert reloaded is not None
    with pytest.raises(PlanningError):
        await harness.drive(reloaded)
    assert await harness.quotes() == ()


async def test_the_ambiguous_retry_of_one_command_appends_nothing_further() -> None:
    """§4's ambiguous retry: the write landed and its answer was lost.

    The same command — the same ``expected_version``, because *"a refused write is never
    rebased"* — sent twice. The second is refused stale, the minter re-reads **once**,
    finds that action's last quote **equal** to the one it is minting, and *"stops
    silently, appending nothing"*. The goal holds exactly one quote.
    """
    store = FakePlanStore(now=lambda: AT)
    goal = await a_goal(store)
    command = ActionQuoteMinting(goal_id=GOAL, quote=quote(), expected_version=goal.version)

    await record_minted_quote(store, command)
    await record_minted_quote(store, command)

    stored = await store.get_goal(GOAL)
    assert stored is not None
    assert len(stored.quotes) == 1
    assert stored.quotes[0].amount == Decimal("120")


# --- the barrier-driven race (§4, §11 arm 4's four outcomes) ------------


class _Interposing(FakePlanStore):
    """A store a test can act on **between** the mint's goal read and its write."""

    def __init__(self, **kwargs: object) -> None:
        """Count what the minter does and hold a hook for the winner's write."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.between: Callable[[], Awaitable[None]] | None = None
        self.goal_reads = 0
        self.quote_writes = 0

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Count the reads, so *"re-reads at most once"* is an assertion."""
        self.goal_reads += 1
        return await super().get_goal(goal_id)

    async def record_quote(self, minting: ActionQuoteMinting) -> Goal:
        """Let the winner land first, once, and count every attempt."""
        self.quote_writes += 1
        hook, self.between = self.between, None
        if hook is not None:
            await hook()
        return await super().record_quote(minting)

    async def concurrently_append(self, appended: ActionQuote) -> None:
        """Append as another writer would, without counting as this minter's write."""
        goal = await FakePlanStore.get_goal(self, GOAL)
        assert goal is not None
        await FakePlanStore.record_quote(
            self,
            ActionQuoteMinting(goal_id=GOAL, quote=appended, expected_version=goal.version),
        )

    async def concurrently_engage(self) -> None:
        """Advance the version *"touching some other field"* and no quote."""
        goal = await FakePlanStore.get_goal(self, GOAL)
        assert goal is not None
        await self.engage_goal(GOAL, at=AT, conversation_id="c-1", expected_version=goal.version)


async def _raced(
    between: Callable[[_Interposing], Awaitable[None]],
    *,
    minted: ActionQuote | None = None,
    actions: tuple[str, ...] = (ACT,),
) -> tuple[_Interposing, BaseException | None]:
    """Mint ``minted`` with ``between`` landing between this minter's read and write."""
    store = _Interposing(now=lambda: AT)
    await a_goal(store, actions=actions)
    store.between = lambda: between(store)
    try:
        await mint_quote(store, goal_id=GOAL, quote=quote() if minted is None else minted)
    except BaseException as exc:
        return store, exc
    return store, None


async def test_a_refused_write_whose_own_quote_already_stands_stops_silently() -> None:
    """§4: *"stops silently — appending nothing and raising nothing — where that
    action's last quote equals the one it is minting"*.

    **One re-read and no second ``record_quote``** (§11 arm 4), and the goal is left
    holding exactly one.
    """
    store, raised = await _raced(lambda one: one.concurrently_append(quote()))

    assert raised is None
    assert store.quote_writes == 1, "no second `record_quote`"
    assert store.goal_reads == 2, "the read the mint was computed against, and one re-read"
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert len(stored.quotes) == 1


async def test_a_refused_write_the_winner_left_a_different_quote_for_raises() -> None:
    """§4: *"a different quote for that action … raises"*, appending nothing.

    Asserted as **a ``PlanningError`` that is not a ``StaleExecutionError``** — both
    halves, since a bare propagation satisfies the first and is the retry-inviting class
    §4 refuses.
    """
    store, raised = await _raced(lambda one: one.concurrently_append(quote("170")))

    assert isinstance(raised, PlanningError)
    assert not isinstance(raised, StaleExecutionError)
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert [one.amount for one in stored.quotes] == [Decimal("170")], "as the winner left it"


async def test_a_refused_write_that_finds_no_quote_at_all_raises() -> None:
    """§4: *"no quote at all whether or not ``quotes_elided`` has advanced"* raises.

    Here the concurrent advance touched **some other field** — the goal's engagement —
    so ``quotes_elided`` is unchanged and the goal holds no quote for that action.
    """
    store, raised = await _raced(lambda one: one.concurrently_engage())

    assert isinstance(raised, PlanningError)
    assert not isinstance(raised, StaleExecutionError)
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert stored.quotes == ()
    assert stored.quotes_elided == 0


async def test_a_refused_write_whose_quote_landed_and_was_then_elided_raises() -> None:
    """§4's fourth outcome: *"its quote landed and was then **elided**"*.

    ``quotes_elided`` has advanced, the action has no quote left, and the minter still
    raises rather than concluding its write landed — the conclusion §4 permits it to draw
    is **only** the equal-last-quote one.
    """

    async def landed_then_elided(one: _Interposing) -> None:
        await one.concurrently_append(quote())
        for _ in range(MAX_ACTION_QUOTES):
            await one.concurrently_append(quote("5", action=OTHER_ACT))

    store, raised = await _raced(landed_then_elided, actions=(ACT, OTHER_ACT))

    assert isinstance(raised, PlanningError)
    assert not isinstance(raised, StaleExecutionError)
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert stored.quotes_elided > 0
    assert all(one.intended_action == OTHER_ACT for one in stored.quotes)


class _Rendezvous(FakePlanStore):
    """Two minters read at one version, and ``second`` writes after ``first`` landed.

    The inverted schedule §4 names: *"a minter can read ``120``, stall, and commit after
    another has read ``170``"*. The barrier makes the two reads genuinely concurrent, and
    the event pins **which** of them commits first, so the arm asserts the rule rather
    than a scheduling accident.
    """

    def __init__(self, *, second: Decimal, **kwargs: object) -> None:
        """Hold the first two goal reads, and hold ``second``'s write until the other."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self._read = asyncio.Barrier(2)
        self._held = 2
        self._second = second
        self._first_landed = asyncio.Event()

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Answer, holding the first two reads until both minters have taken one."""
        goal = await super().get_goal(goal_id)
        if self._held:
            self._held -= 1
            await self._read.wait()
        return goal

    async def record_quote(self, minting: ActionQuoteMinting) -> Goal:
        """Land the first reading's write, then release the second's."""
        if minting.quote.amount == self._second:
            await self._first_landed.wait()
        try:
            return await super().record_quote(minting)
        finally:
            self._first_landed.set()


async def test_the_inverted_schedule_pins_commit_order_against_read_order() -> None:
    """§11 arm 4: *"the arm that pins commit order against read order"*.

    With the ``120`` reading taken **before** the ``170`` one and its write landing while
    the ``170`` minter still holds ``expected_version`` from the earlier read, the ``170``
    minter's write is refused, its re-read finds the **different** ``120``, and it
    **raises** — the goal holding ``120``, *"the **earlier** reading, which no clause
    treats as evidence of a later one"*.
    """
    store = _Rendezvous(second=Decimal("170"), now=lambda: AT)
    await a_goal(store)

    early, late = await asyncio.gather(
        mint_quote(store, goal_id=GOAL, quote=quote("120")),
        mint_quote(store, goal_id=GOAL, quote=quote("170")),
        return_exceptions=True,
    )

    assert early is None, "the reading taken first is the one the goal holds"
    assert isinstance(late, PlanningError)
    assert not isinstance(late, StaleExecutionError)
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert [one.amount for one in stored.quotes] == [Decimal("120")]


async def test_every_quote_a_goal_holds_was_appended_against_the_version_its_read_saw() -> None:
    """§4's ordering claim, over a goal a mint and a concurrent writer both wrote to.

    *"Because a refused write is never rebased, every quote a goal holds was appended
    against the version the read that produced it observed"* — so what a stale mint
    leaves behind is the winner's reading alone, in the order the writes landed, with no
    instant compared, no sequence minted and no test at the store.
    """
    store, raised = await _raced(lambda one: one.concurrently_append(quote("170")))

    assert isinstance(raised, PlanningError)
    stored = await FakePlanStore.get_goal(store, GOAL)
    assert stored is not None
    assert len(stored.quotes) == 1, "the loser's reading is discarded and never reconciled"


async def test_a_minting_the_store_refuses_outright_is_not_swallowed() -> None:
    """§4: *"nothing swallows the failure"*.

    A quote naming an action the goal does not hold is the store's one refusal (§2), and
    it is an invariant breach at the current version rather than a lost race — so it
    leaves as itself and the walk stops.
    """
    store = FakePlanStore(now=lambda: AT)
    await a_goal(store)

    with pytest.raises(PlanningError):
        await mint_quote(store, goal_id=GOAL, quote=quote(action="act-nobody-holds"))


async def test_a_mint_for_a_goal_that_is_not_there_raises_rather_than_passing() -> None:
    """A reading the minter could not record stops the walk (§4)."""
    store = FakePlanStore(now=lambda: AT)

    with pytest.raises(PlanningError):
        await mint_quote(store, goal_id=GOAL, quote=quote())


# --- the mutation window across the seam (ADR-0018 §3) -------------------


class _Leaky(FakePlanStore):
    """A **conforming** store, and a handle on the very plan it handed the runner.

    ``PlanStore`` contracts no detached snapshot — unlike ``MemoryStore``,
    ``ToolRegistry`` and ``AuditTrail`` — so the caller is the one that has to hold its
    own copy (``test_runner.py``'s ``LeakyPlanStore``, for the same reason one stage
    over). What this makes reachable is the window ADR-0018 §3 names: ``frozen=True``
    refuses ``plan.goal_id = ...`` and does nothing about ``plan.__dict__``.
    """

    def __init__(self, **kwargs: object) -> None:
        """Keep the plan most recently handed out, so a test can rewrite it."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.handed_out: ActionPlan | None = None

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Answer as the fake does, and remember the object the caller now holds."""
        plan = await super().get_plan(plan_id)
        self.handed_out = plan
        return plan

    def rewrite(self, *, plan: str, goal: str) -> None:
        """Repoint the handed-out plan at another plan and another goal."""
        assert self.handed_out is not None
        self.handed_out.__dict__["id"] = plan
        self.handed_out.__dict__["goal_id"] = goal


async def test_the_quote_names_the_plan_and_goal_the_step_was_dispatched_under() -> None:
    """The mint's whole input is taken **before** the seam is awaited (ADR-0018 §3).

    A quote names *where* it was read, and the goal it is appended to is that plan's
    own — both read off the stored plan, which ``PlanStore`` hands over attached. A
    holder that repoints it while the tool is running would otherwise have the price
    appended to **another goal** and recorded as read in a plan it was not read in,
    which no later reader could detect: ADR-0267 §1's *"a step id alone names no
    place"*, reached through the one window that is open on it.

    The rewrite really lands — asserted below — and reaches nothing.
    """
    plans = _Leaky(now=lambda: AT)

    async def acts_and_rewrites(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Act, and repoint the plan the runner is holding on the way out."""
        plans.rewrite(plan="p-elsewhere", goal="g-elsewhere")
        return PRICED

    harness = Harness(tools=((declaration(), acts_and_rewrites),), plans=plans)
    state = await an_execution(harness.plans, step())

    assert await harness.drive(state) is Disposition.EXECUTED

    (minted,) = await harness.quotes()
    assert minted.plan == PLAN, "the plan the step was really dispatched under"
    assert minted.read_from.step == STEP
    assert plans.handed_out is not None
    assert plans.handed_out.goal_id == "g-elsewhere", "the rewrite landed, and reached nothing"


class _Rewriting(FakeToolInvoker):
    """A registry that rewrites the declaration it holds while the tool is running.

    A **control**, and it is one on purpose: ``FakeToolInvoker.register`` and ``find``
    each deep-copy, and ``ActionRequest.tool`` is rebuilt through validation
    (``_detached_tool``), so this rewrite reaches the request by no route at all. What
    the arm below records is that the declaration the mint reads is the request's own
    and never the registry's — which is a property of the **types**, held whatever a
    registry does with what it kept. Adversarial review, round 3, ``major``: an earlier
    version of this case claimed to close a window that was already closed.
    """

    def rewrite_the_quoted_key(self, tool_id: str, key: str) -> None:
        """Point the held declaration's quoted amount at another key of the output."""
        self._held(tool_id).__dict__["amount"] = key

    def quoted_key(self, tool_id: str) -> str:
        """What the held declaration names as its amount key, right now."""
        return self._held(tool_id).amount

    def _held(self, tool_id: str) -> QuotedOutput:
        """The very ``QuotedOutput`` this registry holds."""
        held = self._bindings[tool_id].definition.quoted_output
        assert held is not None
        return held


async def test_the_selector_is_the_requests_own_declaration_and_never_the_registrys() -> None:
    """ADR-0267 §3's selector, read off a declaration nobody else holds.

    Were it the registry's, a ``quoted_output.amount`` repointed from ``"price"`` to
    ``"stars"`` mid-call would mint ``4`` out of ``{"price": "200", "stars": 4}`` — a
    number of the right **shape** in the wrong **slot**, satisfying a ``150`` ceiling
    the act breaches. It is the request's, and ``ActionRequest`` rebuilds that
    declaration through validation, so the rewrite is inert.
    """
    harness = Harness()
    rewriting = _Rewriting([], ledger=harness.trail, gate=harness.trail)

    async def acts_and_rewrites(
        parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Act, and point the held declaration at the other key on the way out."""
        rewriting.rewrite_the_quoted_key("rooms", "stars")
        return {"price": "200", "stars": 4, "currency": "EUR"}

    rewriting.register(declaration(), acts_and_rewrites)
    ids = iter(f"d-{n}" for n in range(1, 100))
    harness.invoker = rewriting
    harness.runner = StepRunner(
        plans=harness.plans,
        registry=rewriting,
        policy=harness.policy,
        trail=harness.trail,
        executor=StepExecutor(
            plans=harness.plans, registry=rewriting, invoker=rewriting, now=lambda: MUCH_LATER
        ),
        now=lambda: MUCH_LATER,
        id_factory=lambda: next(ids),
    )
    state = await an_execution(harness.plans, step())

    assert await harness.drive(state) is Disposition.EXECUTED

    (minted,) = await harness.quotes()
    assert minted.amount == Decimal("200"), "the key the call was dispatched under"
    assert minted.read_from.field == "price"
    assert rewriting.quoted_key("rooms") == "stars", "the rewrite landed, and reached nothing"


async def test_the_plan_and_goal_are_the_ones_the_request_was_built_from() -> None:
    """One read of one stored plan, used by the request builder **and** by the mint.

    ADR-0254 §15 sources ``ActionRequest.goal`` from *"the plan the execution names"*,
    and that read happens before the ruling; ADR-0267 §4's mint happens after the act.
    Every awaited collaborator of this stage sits between them — the registry, the
    binder, the policy, the trail, ADR-0249 §12's boundary — and the store hands the
    plan over attached. A repoint landed at the **earliest** of those awaits must
    therefore reach neither: the request is about ``g-1`` and so is the quote, or one
    authorised act has quoted a price onto another goal entirely.
    """
    plans = _Leaky(now=lambda: AT)
    harness = Harness(tools=((declaration(), returning(PRICED)),), plans=plans)
    state = await an_execution(harness.plans, step())

    async def repoint(decision: PermissionDecision) -> None:
        """Rewrite the plan the runner is holding, at the first await after it read it."""
        plans.rewrite(plan="p-elsewhere", goal="g-elsewhere")

    assert await harness.drive(state, on_ruled=repoint) is Disposition.EXECUTED

    (ruled,) = harness.policy.requests
    assert ruled.goal == GOAL
    (minted,) = await harness.quotes()
    assert minted.plan == PLAN, "the plan the request was built from"
    assert plans.handed_out is not None
    assert plans.handed_out.goal_id == "g-elsewhere", "the rewrite landed, and reached nothing"
