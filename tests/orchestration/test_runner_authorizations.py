"""Writing and settling the path-(i) row through a whole turn (ADR-0254 §1, §15).

``test_authorizing.py`` pins *which* `CONFIRM` proposes a row. This pins what the
stage then does with the answer: the row is written before the question is put,
and the answer settles it — ADR-0244's shape, which ADR-0254 §1 adopts rather than
re-derives.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing
here imports ``permissions/`` or ``planning/`` (CLAUDE.md golden rule 1).

**The coverage a row carries is minted from the goal** (ADR-0266 §11's L2), so a
case whose goal states no bound writes an empty one and the cases at the end of this
module state a ceiling and read it back off the row. The mint itself is
``test_stated_bounds.py``'s; what is pinned here is that this stage asks about what
it minted and writes what it asked about.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from authorizing_builders import (
    ACCOUNT,
    ACT_TURN,
    AT,
    GOAL,
    RETENTION,
    a_binding,
    a_goal,
    a_tool,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    ActionPlan,
    ActionQuote,
    AttemptTransition,
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
    BoundKind,
    DataTier,
    Disposition,
    GoalAttempt,
    GoalElement,
    Ground,
    IntendedAction,
    IntendedActionMinting,
    PlanStep,
    ResolutionRule,
    StepOutputRef,
    StepStatus,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.authorizing import authorization_id_for
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeCoverageAnswers,
    FakeEgressBinder,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.protocols import CoverageAnswers
    from ai_assistant.core.types import ExecutionState, Goal, ToolDefinition

#: The one step every test here disposes of. It carries **no argument**, which is
#: the request ADR-0254 §20's arm 54 is stated over.
STEP = "step-1"
ATTEMPT = "a-1"
CAPABILITY = "send_email"
CONNECTION = "conn-1"
IDENTITY = "work@example.com"

#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def a_confirmable_tool() -> ToolDefinition:
    """An egress declaration ``FakeActionPolicy`` confirms: it discloses off-device."""
    return a_tool(discloses=(DataTier.PERSONAL,))


class Harness:
    """A wired ``StepRunner`` with a binder and a goal-authorization store."""

    def __init__(  # noqa: PLR0913 — one parameter per collaborator the cases vary
        self,
        *,
        tool: ToolDefinition | None = None,
        retention: timedelta | None = RETENTION,
        authorizations: FakeGoalAuthorizationStore | None = None,
        answers: CoverageAnswers | None = None,
        wired: bool = True,
        answering: bool = True,
        bound: bool = True,
        now: datetime = AT,
    ) -> None:
        """Wire the stage over canonical fakes.

        ``wired=False`` builds the stage with **no** store, which is ADR-0254
        §15's fail-closed default: it proposes nothing and settles nothing.
        ``answering=False`` is the same default one seam over (ADR-0270 §1): a
        stage holding no condition-6 answerer cannot obtain §1's completeness
        condition by any other means, so it proposes nothing either.

        ``answers`` defaults to condition 6's **one** implementation, holding no
        `GoalQuotes` — the real comparison, so what these cases pin is the answer
        `permissions` gives rather than a fake's configuration. A case that needs
        the answer counted, faulted or set to something this tree cannot produce
        passes `FakeCoverageAnswers`.

        ``bound=False`` registers the declaration at **no** egress seam, so
        ``_bound`` answers ``None`` and the request is built on
        ``_requested``'s other branch (ADR-0152 §8). It is the same call in every
        other respect, which is what makes it a control for the value that branch
        must also carry.
        """
        self.tool = a_confirmable_tool() if tool is None else tool
        self.plans = FakePlanStore(now=lambda: now)
        self.policy = FakeActionPolicy()
        self.trail = FakeAuditTrail()
        self.invoker = FakeToolInvoker([(self.tool, _succeeds)], ledger=self.trail, gate=self.trail)
        self.binder = FakeEgressBinder()
        if bound:
            self.binder.register_egress(self.tool, reference=CONNECTION, identity=IDENTITY)
        self.authorizations = (
            FakeGoalAuthorizationStore() if authorizations is None else authorizations
        )
        self.answers: CoverageAnswers = ThresholdActionPolicy() if answers is None else answers
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: now
            ),
            binder=self.binder,
            authorizations=self.authorizations if wired else None,
            coverage_answers=self.answers if answering else None,
            episode_retention=retention,
            now=lambda: now,
            id_factory=lambda: next(self.ids),
        )

    async def an_execution(self, goal: Goal, *, act: str | None = None) -> ExecutionState:
        """Store ``goal``, a one-step argument-free plan, and open an execution.

        ``act`` is the :class:`~ai_assistant.core.types.IntendedAction` the step is
        an attempt at (ADR-0265 §1), minted onto the goal first because
        ``save_plan`` refuses a step naming an action the goal does not hold. The
        default is ``None``, which is a conforming plan rather than a degraded one
        and is what every case here that is not about the request builder wants.
        """
        await self.plans.save_goal(goal)
        if act is not None:
            await self.plans.record_intended_actions(
                IntendedActionMinting(
                    goal_id=goal.id,
                    actions=(IntendedAction(id=act, intent="send the note"),),
                    expected_version=0,
                )
            )
        step = PlanStep(id=STEP, intent="send the note", capability=CAPABILITY, intended_action=act)
        plan = ActionPlan(
            id="p-1", goal_id=goal.id, steps=(step,), created_at=AT, targets_revision=1
        )
        await self.plans.save_plan(plan)
        state = await self.plans.start_execution(plan.id)
        await self.plans.open_attempt(_an_attempt(goal.id))
        await self.plans.commit_attempt(_appends_execution(state.id))
        return state

    async def rows(self) -> tuple[Authorization, ...]:
        """Every row the store holds, whatever its disposition."""
        return await self.authorizations.export()


def _an_attempt(goal_id: str) -> GoalAttempt:
    """The attempt every execution here is opened under (ADR-0255 §3)."""
    return GoalAttempt(id=ATTEMPT, goal_id=goal_id, opened_at=AT)


def _appends_execution(execution_id: str) -> AttemptTransition:
    """ADR-0249 §12's own ordering: the execution is appended before it is driven."""
    return AttemptTransition(attempt_id=ATTEMPT, expected_version=0, add_execution_id=execution_id)


async def _parked(harness: Harness, goal: Goal, *, act: str | None = None) -> ExecutionState:
    """Drive the step to its `CONFIRM` park and return the execution."""
    state = await harness.an_execution(goal, act=act)
    result = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )
    assert result.disposition is Disposition.AWAITING_CONFIRMATION
    return result.state


# --- the proposal (ADR-0254 §1's path (i)) -------------------------------


async def test_a_confirm_proposes_the_row_before_the_question_is_put() -> None:
    """ADR-0254 §1: written `PROPOSED`, against the recorded `CONFIRM`'s own id."""
    harness = Harness()
    goal = a_goal(deadline=AT + timedelta(hours=12))

    await _parked(harness, goal)

    (row,) = await harness.rows()
    (decision,) = await harness.trail.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.confirmation == decision.id
    assert row.proposed_at == decision.decided_at
    assert row.expires_at == AT + timedelta(hours=12)
    assert row.goal == GOAL
    assert row.coverage == ()
    assert row.settled_at is None


async def test_the_row_takes_the_retention_window_where_the_goal_carries_no_deadline() -> None:
    """ADR-0256 §9's ordinary case, driven end to end."""
    harness = Harness()

    await _parked(harness, a_goal(deadline=None))

    (row,) = await harness.rows()
    assert row.expires_at == AT + RETENTION


async def test_a_deployment_keeping_turns_forever_proposes_nothing() -> None:
    """ADR-0256 §9: `episode_retention = None`, no deadline → no row, route (a)."""
    harness = Harness(retention=None)

    await _parked(harness, a_goal(deadline=None))

    assert await harness.rows() == ()


async def test_a_stage_holding_no_store_proposes_nothing() -> None:
    """ADR-0254 §15's fail-closed default, and the shape §6 gives a sourceless policy."""
    harness = Harness(wired=False)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.authorizations.export() == ()


async def test_an_allowed_call_proposes_nothing() -> None:
    """Only a question proposes a row: a ruling that asks nothing establishes nothing."""
    harness = Harness(tool=a_tool())
    state = await harness.an_execution(a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )

    assert result.disposition is Disposition.EXECUTED
    assert await harness.rows() == ()


async def test_a_store_that_refuses_the_write_still_puts_the_question() -> None:
    """ADR-0254 §1's own outcome for proposing none, reached by a fault instead.

    "the `CONFIRM` is resolved and the one call is authorised by ADR-0148 §3's
    route (a)". The cost of a store that could not be written is an authority the
    user has to grant again, never one granted without them — so the dispatch is
    not failed on the strength of a second store.
    """
    store = FakeGoalAuthorizationStore()
    store.fail_writes()
    harness = Harness(authorizations=store)

    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.rows() == ()
    assert len(await harness.trail.export()) == 1
    assert parked.step(STEP) is not None
    assert parked.step(STEP).status is StepStatus.AWAITING_APPROVAL  # type: ignore[union-attr]


async def test_a_stage_holding_no_condition_6_answerer_proposes_nothing() -> None:
    """ADR-0270 §1's fail-closed default, one seam over from the store's.

    *"Where a component that is not ``permissions`` needs condition 6's answer
    about a row it would write, it obtains it from this member and by no other
    means"* — so a stage that cannot ask cannot satisfy ADR-0254 §1's completeness
    condition, and the disposition is §1's own: the `CONFIRM` is resolved and the
    one call is authorised by ADR-0148 §3's route (a).
    """
    harness = Harness(answering=False)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.rows() == ()


async def test_the_stage_asks_the_seam_once_per_recorded_confirm() -> None:
    """ADR-0270 §3: nothing is memoised and nothing is carried to a dispatch.

    One `CONFIRM`, one question. A stage that asked twice to be sure would take a
    second durable read for one proposal, and one that cached across proposals
    would be the *"cached coverage verdict"* ADR-0254 §13 rules out everywhere.
    """
    answers = FakeCoverageAnswers()
    harness = Harness(answers=answers)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert answers.call_count == 1
    (row,) = await harness.rows()
    assert row.quoted is None


async def test_the_stage_asks_about_the_request_and_the_coverage_it_would_write() -> None:
    """ADR-0270 §1: the operands are the request and the tuple, *"and never the row"*.

    The coverage is empty because this goal states no bound ADR-0266 §4 reads, and
    the row is written with the very tuple that was asked about — which is what
    makes the answer an answer about *this* proposal.
    """
    answers = FakeCoverageAnswers()
    harness = Harness(answers=answers)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    ((asked, coverage),) = answers.calls
    assert asked.tool.id == harness.tool.id
    assert asked.goal == GOAL
    assert coverage == ()
    (row,) = await harness.rows()
    assert row.coverage == coverage


async def test_an_unreadable_quote_seam_still_puts_the_question() -> None:
    """ADR-0270 §4: *"a fault is never an absence"*, and the disposition is §1's own.

    ``coverage_met`` propagates ``GoalQuotes.for_action``'s ``AuthorizationError``
    rather than answering unmet, and this stage's existing refusal clause catches
    it one frame up: no row is written, ``Confirmation.authorization`` is absent
    (ADR-0254 §11), and the question still reaches the user — the cost of an
    unreadable seam is an authority granted again, never a dispatch refused on the
    strength of a second store.
    """
    answers = FakeCoverageAnswers()
    answers.fail_coverage_met()
    harness = Harness(answers=answers)

    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    assert await harness.rows() == ()
    assert len(await harness.trail.export()) == 1
    step = parked.step(STEP)
    assert step is not None
    assert step.status is StepStatus.AWAITING_APPROVAL


# --- the settlement (ADR-0254 §1's five edges) ---------------------------


async def test_an_approval_settles_the_row_established() -> None:
    """ADR-0254 §1: "An approval settles `ESTABLISHED`"."""
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.ESTABLISHED
    assert row.settled_at == AT
    # The row still carries the confirmation it was proposed against, which is
    # ADR-0254 §1's write-path rule and not a validator (§20 arm 38).
    assert row.confirmation is not None
    assert await harness.authorizations.standing(GOAL) == (row,)


async def test_a_refusal_settles_the_row_declined_and_establishes_nothing() -> None:
    """ADR-0254 §1: "a refusal settles `DECLINED`", and `standing` returns it not."""
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=False, timeout=PATIENT
    )

    assert result.disposition is Disposition.DENIED
    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.DECLINED
    assert await harness.authorizations.standing(GOAL) == ()


async def test_the_settlement_instant_is_the_resolving_decisions_own() -> None:
    """ADR-0254 §7 refuses a row whose `settled_at` is after the ruling's instant.

    Equality at the lower end is live (§1), so taking the resolving decision's own
    reading is the one value that cannot put the row and the trail out of step.
    """
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await harness.rows()
    resolving = next(one for one in await harness.trail.export() if one.resolves is not None)
    assert row.settled_at == resolving.decided_at


async def test_an_answer_at_or_after_the_expiry_establishes_nothing() -> None:
    """ADR-0254 §12: the row settles `EXPIRED` and no standing authority comes to be.

    The `CONFIRM` is answered under a stage whose clock has passed the instant the
    row carries; the store settles the lapsed proposal first, so the approval finds
    a disposition the `ESTABLISHED` edge does not leave.
    """
    store = FakeGoalAuthorizationStore()
    parking = Harness(authorizations=store, retention=timedelta(minutes=5))
    parked = await _parked(parking, a_goal(deadline=None))
    (proposal,) = await parking.rows()
    assert proposal.expires_at == AT + timedelta(minutes=5)

    # A second stage over the same stores, reading a clock past that instant --
    # the restart ADR-0254 §11 promises recovers the row, with the instant read off
    # the row rather than recomputed.
    later = StepRunner(
        plans=parking.plans,
        registry=parking.invoker,
        policy=parking.policy,
        trail=parking.trail,
        executor=StepExecutor(
            plans=parking.plans,
            registry=parking.invoker,
            invoker=parking.invoker,
            now=lambda: AT + timedelta(hours=1),
        ),
        binder=parking.binder,
        authorizations=store,
        coverage_answers=parking.answers,
        episode_retention=RETENTION,
        now=lambda: AT + timedelta(hours=1),
        id_factory=lambda: "d-late",
    )

    await later.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.EXPIRED
    assert await store.standing(GOAL) == ()


async def test_a_settlement_the_store_refuses_leaves_the_answer_standing() -> None:
    """A fault at the settlement loses the authority and retracts nothing."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    store.fail_writes()

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    store.fail_writes(None)
    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED


async def test_a_stage_holding_no_store_settles_nothing() -> None:
    """The fail-closed default again, on the answering side."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    unwired = StepRunner(
        plans=harness.plans,
        registry=harness.invoker,
        policy=harness.policy,
        trail=harness.trail,
        executor=StepExecutor(
            plans=harness.plans, registry=harness.invoker, invoker=harness.invoker, now=lambda: AT
        ),
        binder=harness.binder,
        episode_retention=RETENTION,
        now=lambda: AT,
        id_factory=lambda: "d-unwired",
    )

    await unwired.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED


# --- the settlement is an exact lookup, at any age (#2375) ---------------


def _another_goals_row(n: int) -> Authorization:
    """A `PROPOSED` row of some *other* goal, newer than the proposal under test."""
    return Authorization(
        id=f"auth-other-{n}",
        goal=f"g-other-{n}",
        tool=a_tool(),
        account=ACCOUNT,
        destinations=a_binding().canonical_destination_set,
        origin=AuthorizationOrigin.CONFIRMED,
        coverage=(),
        proposed_at=AT + timedelta(minutes=1 + n),
        expires_at=AT + timedelta(days=1),
        confirmation=f"d-other-{n}",
        supersedes=None,
        disposition=AuthorizationDisposition.PROPOSED,
        settled_at=None,
    )


async def test_an_answer_settles_its_proposal_past_any_bounded_lookback() -> None:
    """Issue #2375: the settlement carries no finite-history assumption.

    Reading back over a bounded `recent` page lost a proposal that newer rows of
    **other** goals had displaced: the row stayed `PROPOSED` for ever, and the
    authority the user had answered for was never established. The id is derived
    from the confirmation, so ADR-0254 §16's keyed `resolve` finds it exactly —
    no page, no limit, no ordering assumption, and no ninth store signature.

    Two hundred and one rows is one past the page the lookback used to read.
    """
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    for n in range(201):
        await harness.authorizations.record(_another_goals_row(n))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    (standing,) = await harness.authorizations.standing(GOAL)
    assert standing.disposition is AuthorizationDisposition.ESTABLISHED
    assert standing.id == authorization_id_for(standing.confirmation or "")


async def test_a_row_under_that_id_naming_another_question_settles_nothing() -> None:
    """The derived id is a **key**, never the evidence that a row answers a question.

    The store is handed a row already occupying the id this turn's `CONFIRM` would
    derive, naming a different confirmation. The proposal is refused as a duplicate
    id — which ADR-0254 §1 already rules harmless, the call falling back to route
    (a) — and the answer must then settle **nothing** rather than settle the row it
    found there.
    """
    store = FakeGoalAuthorizationStore()
    squatter = _another_goals_row(0).model_copy(
        update={"id": authorization_id_for("d-1"), "confirmation": "d-0"}
    )
    await store.record(squatter)
    harness = Harness(authorizations=store)

    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    assert result.disposition is Disposition.EXECUTED
    (row,) = await store.export()
    assert row == squatter
    assert await store.standing(GOAL) == ()


# --- the resolving decision is not itself a question ---------------------


async def test_the_answer_proposes_no_second_row() -> None:
    """A `CONFIRM` recorded with `resolves` set is a resolution, not a question.

    A second row against a decision that was itself an answer would be a proposal
    nobody was ever shown.
    """
    harness = Harness()
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=False, timeout=PATIENT)

    assert len(await harness.rows()) == 1


@pytest.mark.parametrize("approved", [True, False], ids=["approved", "declined"])
async def test_the_store_is_read_and_written_and_never_raises_into_the_turn(
    *, approved: bool
) -> None:
    """A read fault is as survivable as a write fault, on both answers."""
    store = FakeGoalAuthorizationStore()
    harness = Harness(authorizations=store)
    parked = await _parked(harness, a_goal(deadline=AT + timedelta(hours=12)))
    store.fail_reads(AuthorizationError("the store could not be read"))

    result = await harness.runner.resume(
        parked, STEP, attempt_id=ATTEMPT, approved=approved, timeout=PATIENT
    )

    assert result.disposition is (Disposition.EXECUTED if approved else Disposition.DENIED)


# --- ADR-0266 §11's L2: the mint at its call site, and the request builder ----

#: The act the builder cases put on the step, and the one the goal holds.
ACT = "ia-1"

#: A goal whose one ``USER_STATED`` constraint states a ceiling ADR-0266 §4 reads.
CEILING = (
    GoalElement(
        id="e-1", text="the ceiling for the trip", ground=Ground.USER_STATED, span="up to 150 euros"
    ),
)

#: A quote the seam rides back with, so a ``MONEY``-carrying coverage can be
#: answered met at all (``FakeCoverageAnswers``' second override).
QUOTED = ActionQuote(
    intended_action=ACT,
    arguments_digest="a" * 64,
    amount=Decimal("120"),
    currency="EUR",
    plan="p-1",
    read_from=StepOutputRef(step="s-1", field="price"),
    read_at=AT,
)


async def test_the_stage_asks_about_the_member_the_goal_minted_and_writes_it() -> None:
    """ADR-0266 §11's L2 at its call site, and ADR-0270 §1's operand rule with it.

    The goal states a ceiling, so the coverage this stage puts to ``coverage_met``
    is the member ADR-0266 §4 mints from it — not an empty tuple and not a literal
    — and the row is written with the very tuple that was asked about.
    """
    answers = FakeCoverageAnswers(quote=QUOTED)
    harness = Harness(answers=answers)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT)

    ((_, asked),) = answers.calls
    (member,) = asked
    assert member.kind is BoundKind.MONEY
    assert member.bound is not None
    assert member.bound.maximum == Decimal("150")
    assert member.bound.maximum_exclusive is False
    assert member.bound.currency == "EUR"
    assert member.basis.act == ACT_TURN
    assert member.basis.span == "up to 150 euros"
    assert member.basis.resolution.rule is ResolutionRule.STATED_BOUND
    (row,) = await harness.rows()
    assert row.coverage == asked
    assert row.quoted == QUOTED


async def test_a_row_carrying_a_minted_member_is_proposed_and_never_an_opening_act() -> None:
    """ADR-0266 §4: a `STATED_BOUND` member *"reaches a path-(iii) opening act in no case"*.

    ``orchestration`` constructs an ``Authorization`` in exactly one place —
    ``proposed_authorization`` — and that one writes ``PROPOSED`` under
    ``CONFIRMED`` unconditionally. So the ceiling is on the screen before it is an
    authority, and the user's answer is the whole of what establishes it.
    """
    harness = Harness(answers=FakeCoverageAnswers(quote=QUOTED))

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT)

    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.origin is AuthorizationOrigin.CONFIRMED
    assert row.settled_at is None
    assert row.coverage != ()


async def test_a_declined_ceiling_establishes_nothing() -> None:
    """ADR-0266 §4: the user *"answers no, and no authority exists"*.

    The row carrying the minted member is settled `DECLINED`, and the goal is left
    with nothing standing for that declaration.
    """
    harness = Harness(answers=FakeCoverageAnswers(quote=QUOTED))
    parked = await _parked(
        harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT
    )

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=False, timeout=PATIENT)

    (row,) = await harness.rows()
    assert row.disposition is AuthorizationDisposition.DECLINED
    assert await harness.authorizations.standing(GOAL) == ()


async def test_the_same_goal_mints_the_same_member_against_a_different_declaration() -> None:
    """ADR-0266 §11 arm 7: *"two different requests, two different plans and two
    different declarations"*.

    One declaring a bounded argument and one declaring nothing, over two plans and
    two requests, leave byte-identical coverage — because §5's mint reads the goal
    and none of the three.
    """
    goal = a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING)
    declaring_nothing = Harness(answers=FakeCoverageAnswers(quote=QUOTED))
    declaring_a_period = Harness(
        tool=a_tool(
            tool_id="smtp-2",
            discloses=(DataTier.PERSONAL,),
            bounded_arguments=(
                {"argument": "nights", "kind": "period", "currency_argument": None},
            ),
        ),
        answers=FakeCoverageAnswers(quote=QUOTED),
    )

    await _parked(declaring_nothing, goal, act=ACT)
    await _parked(declaring_a_period, goal, act=ACT)

    (bare,) = await declaring_nothing.rows()
    (declared,) = await declaring_a_period.rows()
    assert bare.coverage == declared.coverage
    assert bare.tool.id != declared.tool.id


async def test_the_request_carries_the_act_the_step_names() -> None:
    """ADR-0266 §11's L2, and it is ADR-0254 §6's clause for ``goal`` one field over.

    *"`orchestration` sets it from the plan step the request serves"* — read off the
    request the stage actually built, never a hand-built one, and taken from the
    **stored** plan rather than from the caller's state.
    """
    answers = FakeCoverageAnswers(quote=QUOTED)
    harness = Harness(answers=answers)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT)

    ((asked, _),) = answers.calls
    assert asked.intended_action == ACT
    (decision,) = await harness.trail.export()
    assert decision.intended_action == ACT


async def test_the_resumed_request_carries_it_too() -> None:
    """ADR-0266 §11's L2: *"on every construction and resume path"*.

    ``resume`` rebuilds the request after the answer, and it takes the act from the
    same expression ``run`` does — so a resumed dispatch says which act it is, and
    the resolving decision on the trail carries it.
    """
    harness = Harness(answers=FakeCoverageAnswers(quote=QUOTED))
    parked = await _parked(
        harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT
    )

    await harness.runner.resume(parked, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT)

    confirmed, resolving = await harness.trail.export()
    assert confirmed.intended_action == ACT
    assert resolving.intended_action == ACT


async def test_a_step_naming_no_act_yields_a_request_carrying_none() -> None:
    """ADR-0266 §11 arm 7: *"a step carrying none yielding a request carrying `None`"*.

    ``None`` is a conforming plan rather than a degraded one, and it is the
    fail-closed direction: ADR-0266 §7's evidence route meets such a request in no
    case, so no ``MONEY`` member is met and the act asks.
    """
    answers = FakeCoverageAnswers(quote=QUOTED)
    harness = Harness(answers=answers)

    await _parked(harness, a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING))

    ((asked, _),) = answers.calls
    assert asked.intended_action is None
    (decision,) = await harness.trail.export()
    assert decision.intended_action is None


async def test_an_unbound_call_carries_the_act_on_both_paths() -> None:
    """ADR-0266 §11's L2 over ``_requested``'s **other** branch (ADR-0152 §8).

    A call the seam does not bind is *"built exactly as it was before this seam
    existed"* — a second construction, one branch away from the bound one — and
    ADR-0266 §11 says *"every construction and resume path"*. Without this the
    value could be dropped from that branch and every other case here would stay
    green, because the harness always registers the declaration.

    **No row is proposed here and that is not what this asserts**: an unbound call
    fails ADR-0254 §1's second condition, so what the act rides on is the recorded
    decision, which is where ADR-0266 §7's evidence route reads it anyway.
    """
    harness = Harness(bound=False)
    state = await harness.an_execution(
        a_goal(deadline=AT + timedelta(hours=12), constraints=CEILING), act=ACT
    )

    result = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )
    assert result.disposition is Disposition.AWAITING_CONFIRMATION
    await harness.runner.resume(
        result.state, STEP, attempt_id=ATTEMPT, approved=True, timeout=PATIENT
    )

    confirmed, resolving = await harness.trail.export()
    assert confirmed.egress_binding is None
    assert confirmed.intended_action == ACT
    assert resolving.intended_action == ACT
    assert await harness.rows() == ()


async def test_an_unbound_call_whose_step_names_no_act_carries_none() -> None:
    """The control for the case above: the value is the step's and is not invented.

    ADR-0266 §11 arm 7's *"a step carrying none yielding a request carrying
    `None`"*, over the branch that builds the request from the step's own
    parameters rather than from what the seam returned.
    """
    harness = Harness(bound=False)
    state = await harness.an_execution(a_goal(deadline=AT + timedelta(hours=12)))

    await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )

    (confirmed,) = await harness.trail.export()
    assert confirmed.egress_binding is None
    assert confirmed.intended_action is None
