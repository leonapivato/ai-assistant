"""ADR-0262 §12's arms 1, 2, 7, 9 and 10's L4 half, at the engine (L4).

What these arms are about is the **phase** rather than the comparison: the order §1
fixes, the three ending conditions §4 names, the two commits it and §5 take after the
composing stage, and the report §6 hands the surface. The comparison's own arms — §2's
three results, §3's ladder and §4's six limbs — are
``test_verification_comparison.py``'s, over records built one fact at a time.

**One double stands in for one lane's records and says so.** :class:`_Ruled` answers the
verification read with a route-(d) ``ALLOW`` over a declared tool, which is the shape
ADR-0254 §7's ten conditions admit and ADR-0254 §20 drives end to end. Establishing such
a row through a turn is that lane's subject; what these arms need is for the operand to
be a fact they chose, so that what they assert is §4's commit and §5's write and not the
path that made them reachable.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from test_engine import (
    AT,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    confirmable,
    tool,
)
from test_engine_attempts import _Recording
from test_engine_composing import _refusing, _TwoStepPlanner
from verification_builders import (
    Rows,
    a_member,
    a_row,
    a_ruling,
    field_equals,
)

from ai_assistant.core.errors import StaleExecutionError, ToolError
from ai_assistant.core.types import (
    ActionPlan,
    AttemptOutcome,
    AttemptPhase,
    AttemptState,
    AttemptTransition,
    GoalStatus,
    Ground,
    Idempotency,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
    StepStatus,
    StepTransition,
    StepVerification,
)
from ai_assistant.orchestration import engine as engine_module
from ai_assistant.orchestration import verification
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

    from ai_assistant.core.types import (
        Authorization,
        Goal,
        GoalAttempt,
        PermissionDecision,
        ToolDefinition,
        TurnOutcome,
        UtcInstant,
    )

_ASKED = "what is two plus two?"
_SEND = "send the note"

#: What the tool's own declaration says a successful invocation establishes. The
#: harness's tool answers ``{"sent": True}``, so this is the declaration that answer
#: satisfies — and the one a reply quoting it verbatim still does not (arm 2).
_DECLARED: tuple[StepVerification, ...] = (field_equals("booked", True),)

#: The span the criterion rests on, which is a span of the utterance itself — the
#: shape ADR-0249 §1 gives a ``USER_STATED`` element.
_SPAN = "the note"


async def _books(parameters: object, *, idempotency_key: str | None) -> dict[str, bool]:
    """A tool that succeeds and **answers**, which is the operand §2 compares.

    The default handler answers ``None``, and §2 is explicit that *"a ``SUCCEEDED`` step
    records that the tool returned, and **what it returned** is the operand"* — so a
    case about a met criterion needs a tool that returned something.
    """
    del parameters, idempotency_key
    return {"booked": True}


class _Established:
    """The two reads ADR-0262 §2 takes, over a row the turn's own goal is the subject of.

    It wraps the harness's trail and answers :meth:`get` with the stored ruling as a
    route-(d) ``ALLOW`` over a declaring tool, and answers :meth:`resolve` with the
    ``CONFIRMED`` row that ``ALLOW`` names. **Both name the goal the turn actually
    opened**, read off the store at call time, because that id is minted inside the turn.

    **What it stands in for is named rather than implied**: ADR-0254 §20's lane drives
    the establishment of such a row end to end, and ADR-0262 §2 reads the result. A case
    about §4's ending commit has no business re-driving that path, and one that did would
    fail for reasons about ADR-0254 rather than about this decision.
    """

    def __init__(
        self,
        inner: Any,
        plans: _Recording,
        *,
        postconditions: Sequence[StepVerification],
        span: str = _SPAN,
    ) -> None:
        """Answer over ``plans``' own attempt, declaring ``postconditions``."""
        self._inner = inner
        self._plans = plans
        self._postconditions = tuple(postconditions)
        self._span = span
        self._decision: str = ""

    def __getattr__(self, name: str) -> Any:
        """Every member but :meth:`get` is the wrapped trail's own."""
        return getattr(self._inner, name)

    @property
    def _goal(self) -> str:
        """The goal this turn opened, as the store recorded it."""
        return self._plans.opened[0].goal_id

    def _declaring(self, stored: PermissionDecision) -> ToolDefinition:
        """The declaration both sides of the pair carry (ADR-0254 §7)."""
        return stored.tool.model_copy(update={"postconditions": self._postconditions})

    async def get(self, decision_id: str) -> Any:
        """The stored ruling, as a route-(d) ``ALLOW`` over a declaring tool."""
        stored = await self._inner.get(decision_id)
        if stored is None:
            return None
        self._decision = decision_id
        declaring = self._declaring(stored)
        row = self._row(declaring)
        return stored.model_copy(
            update={
                "ruling": a_ruling(goal=self._goal, subject=row.subject_digest),
                "tool": declaring,
            }
        )

    def _row(self, declaring: ToolDefinition) -> Authorization:
        """The ``CONFIRMED`` row that ``ALLOW`` names, over that same declaration."""
        return a_row("auth-1", a_member(self._span), goal=self._goal, tool=declaring)

    async def resolve(self, authorization_id: str) -> Any:
        """The row, or ``None`` — over the declaration the ruling carries (§7).

        **The row and the ruling are one pair the trail could have stored**: ADR-0254 §7
        compares the row's ``tool`` with the request's by value and recomputes the
        subject digest, so a double answering a row built over some *other* declaration
        would be standing in for a record ``record`` would have refused. Adversarial
        review, round 5, ``blocker``.
        """
        if authorization_id != "auth-1":
            return None
        stored = await self._inner.get(self._decision)
        if stored is None:  # pragma: no cover — the drive records before the comparison
            return None
        return self._row(self._declaring(stored))


class _Criteria(NoStepPlanner):
    """A planner that plans nothing and proposes one ``USER_STATED`` criterion."""

    def __init__(self, span: str = _SPAN) -> None:
        """Propose a criterion whose ``span`` is ``span``."""
        self._span = span

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan nothing, and propose the criterion."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": _proposing(self._span)})


class _CriteriaDriving(OneStepPlanner):
    """The same proposal, on a planner that plans the one step the turn drives."""

    def __init__(self, span: str = _SPAN) -> None:
        """Plan one step and propose a criterion whose ``span`` is ``span``."""
        super().__init__()
        self._span = span

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan the step, and propose the criterion."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": _proposing(self._span)})


def _proposing(span: str) -> ProposedUnderstanding:
    """One ``USER_STATED`` criterion resting on ``span``, and nothing else."""
    return ProposedUnderstanding(
        retains_outcome=True,
        criteria=(ProposedElement(text=span, ground=Ground.USER_STATED, span=span),),
    )


class _Statuses(_Recording):
    """The recording store, also recording — and optionally refusing — status writes."""

    def __init__(self, *, refuse_status: bool = False, refuse_ending: bool = False) -> None:
        """Record every status write; refuse the ones the case asked to be refused."""
        super().__init__()
        self.statuses: list[tuple[str, GoalStatus]] = []
        self._refuse_status = refuse_status
        self._refuse_ending = refuse_ending

    async def set_goal_status(
        self, goal_id: str, /, *, status: GoalStatus, at: UtcInstant, expected_version: int
    ) -> Goal:
        """Record and delegate, or refuse as ADR-0262 §5's clause has the store refuse."""
        self.statuses.append((goal_id, status))
        if self._refuse_status:
            msg = "the goal moved between the comparison and the write"
            raise StaleExecutionError(msg)
        return await super().set_goal_status(
            goal_id, status=status, at=at, expected_version=expected_version
        )

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Refuse the ending transition where the case asked for §4's lost race."""
        if self._refuse_ending and transition.to_state is AttemptState.ENDED:
            self.moves.append(transition)
            msg = "a step was claimed between the comparison and the commit"
            raise StaleExecutionError(msg)
        return await super().commit_attempt(transition)


def _ended(plans: _Recording) -> AttemptTransition | None:
    """The one ``→ ENDED`` transition this store was asked for, or ``None``."""
    ending = [move for move in plans.moves if move.to_state is AttemptState.ENDED]
    return ending[0] if ending else None


# --------------------------------------------------------------------------- #
# Arm 1 — S1, end to end, unchanged in cost                                    #
# --------------------------------------------------------------------------- #


async def test_s1_ends_answered_at_verify_with_the_goal_still_active() -> None:
    """Arm 1: *"What is two plus two?"* — ADR-0249 §16's arm 1 asserted verbatim.

    A goal whose ``criteria`` are empty, one ``Planner.plan`` call and one composing
    call, no step claimed, and the attempt's stored row ending at
    ``VERIFY``/``ENDED``/**``ANSWERED``** with the goal's status still ``ACTIVE``.
    **And the negative half**: no ``set_goal_status`` call is made,
    ``attempt_report.outcome`` is ``ANSWERED`` and ``continues`` is ``False``.
    """
    plans = _Statuses()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    (stored,) = plans.opened
    attempt = await plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED
    goal = await plans.get_goal(stored.goal_id)
    assert goal is not None
    assert goal.interpretation[-1].criteria == (), "the ordinary shape of a goal at revision 1"
    assert goal.status is GoalStatus.ACTIVE
    assert plans.statuses == [], "§5: an attempt that ends ANSWERED moves no status at all"
    assert outcome.attempt_report is not None
    assert outcome.attempt_report.outcome is AttemptOutcome.ANSWERED
    assert outcome.attempt_report.continues is False


# --------------------------------------------------------------------------- #
# Arm 2 — the two moments, asserted as an order                                #
# --------------------------------------------------------------------------- #


async def test_the_comparison_runs_before_composing_and_the_commits_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arm 2: *"the order is forced, not assumed"*.

    The composing stage records whether it was entered: at the instant the comparison
    ran it had **not** been, and by the time the commit was taken it **had**.

    **The comparison is instrumented at itself and not at a store read it shares.** The
    engine takes several ``get_goal`` reads in a turn — the engagement's among them — so
    a probe keyed on one of those would be satisfied by a turn that compared *after*
    composing, and would detect no ADR-0262 §1 regression at all. What is wrapped here is
    the comparison function the engine calls and nothing else, so each recorded event
    belongs to exactly one of the three moments §1 puts in order.
    """
    entered: list[str] = []

    class _Watching(_Statuses):
        async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
            if transition.to_state is AttemptState.ENDED:
                entered.append("committed")
            return await super().commit_attempt(transition)

    plans = _Watching()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    async def _compared(*args: Any, **kwargs: Any) -> Any:
        entered.append("compared")
        return await verification.compare(*args, **kwargs)

    monkeypatch.setattr(engine_module, "compare", _compared)

    stage: Any = harness.composing
    original = stage.compose

    async def _compose(*args: Any, **kwargs: Any) -> Any:
        entered.append("composed")
        return await original(*args, **kwargs)

    stage.compose = _compose

    await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert entered == ["compared", "composed", "committed"], (
        "§1: the comparison wholly before the composing stage, and the commits after it"
    )


async def test_an_execution_appended_while_composing_refuses_the_ending() -> None:
    """§4's other conjunct: the attempt's own compare-and-swap, over the same window.

    An execution appended to the attempt advances ``GoalAttempt.version``, so an ending
    transition computed against the row the comparison read is refused on its
    ``expected_version`` — *"an execution appended after the caller's read is reported as
    the race it is and never as a malformed set"*, which is what keeps the two refusals
    apart. **The arm that fails against an implementation re-reading the attempt after
    composing**, which would take the compare-and-swap over ground that had already
    moved and would then commit an outcome computed without that execution's answer.
    """
    plans = _Statuses()
    harness = Harness(planner=NoStepPlanner(), plans=plans)
    stage: Any = harness.composing
    original = stage.compose
    appended: list[str] = []

    async def _compose(*args: Any, **kwargs: Any) -> Any:
        """Append a second execution of this goal inside the window §4 is about."""
        if not appended:
            appended.append("once")
            stored = plans.opened[0]
            goal = await plans.get_goal(stored.goal_id)
            assert goal is not None
            other = ActionPlan(
                id="plan-second",
                goal_id=stored.goal_id,
                steps=(),
                created_at=AT,
                targets_revision=goal.revision,
            )
            await plans.save_plan(other)
            second = await plans.start_execution(other.id)
            held = await plans.get_attempt(stored.id)
            assert held is not None
            await plans.commit_attempt(
                AttemptTransition(
                    attempt_id=stored.id,
                    expected_version=held.version,
                    add_execution_id=second.id,
                )
            )
        return await original(*args, **kwargs)

    stage.compose = _compose

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.state is not AttemptState.ENDED, "the appended execution moved the row"
    assert attempt.outcome is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


async def test_a_reply_quoting_every_declared_value_establishes_nothing() -> None:
    """Arm 2's second half: the arm that fails against verification over a composed reply.

    The composing stage returns text carrying every declared postcondition's key and
    value, and the criterion is still **unestablished** — the attempt ends ``ANSWERED``
    at rung 0 and the goal stays ``ACTIVE``. §1's order is what makes that structural:
    at the instant the comparison ran **no reply existed**.
    """
    plans = _Statuses()
    harness = Harness(
        planner=_Criteria(), plans=plans, resolution=Rows(a_row("auth-1", a_member(_SPAN)))
    )

    stage: Any = harness.composing
    original = stage.compose

    async def _compose(*args: Any, **kwargs: Any) -> Any:
        composed = await original(*args, **kwargs)
        return replace(composed, text='{"booked": true} — the note')

    stage.compose = _compose

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.attempt_report is not None
    assert outcome.attempt_report.outcome is AttemptOutcome.ANSWERED
    assert plans.statuses == []
    goal = await plans.get_goal(plans.opened[0].goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE


# --------------------------------------------------------------------------- #
# Arms 2 and 9 — `ACHIEVED`'s one producer, R53, and the no-retry rule         #
# --------------------------------------------------------------------------- #


async def _verified(
    *, refuse_status: bool = False, refuse_ending: bool = False
) -> tuple[_Statuses, TurnOutcome]:
    """Drive one turn whose criterion the record establishes, and answer with both."""
    plans = _Statuses(refuse_status=refuse_status, refuse_ending=refuse_ending)
    harness = Harness(
        planner=_CriteriaDriving(_SPAN), plans=plans, tools=(tool(),), tool_handler=_books
    )
    established = _Established(harness.trail, plans, postconditions=_DECLARED)
    harness.engine._trail = established
    harness.engine._authorizations = established
    outcome = await harness.engine.converse(_SEND, timeout=PATIENT)
    return plans, outcome


async def test_a_verified_attempt_writes_achieved_after_the_ending_commit() -> None:
    """Arms 2 and 9: ``ACHIEVED`` is written on limb 5 alone, and **after** the commit.

    *"No lane writes the status first"*, which would leave an ``ACHIEVED`` goal carrying
    a live, claimable attempt for the width of a store call — R53's failure with a window
    in it.
    """
    plans, outcome = await _verified()

    ending = _ended(plans)
    assert ending is not None
    assert ending.outcome is AttemptOutcome.VERIFIED
    assert plans.statuses == [(plans.opened[0].goal_id, GoalStatus.ACHIEVED)]
    goal = await plans.get_goal(plans.opened[0].goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACHIEVED
    assert outcome.attempt_report is not None
    assert outcome.attempt_report.outcome is AttemptOutcome.VERIFIED
    assert outcome.attempt_report.continues is False


async def test_a_refused_status_write_is_never_retried() -> None:
    """Arm 9's refusal: *"nothing further is written and no second call is made"*.

    The turn does not fail, and the attempt still reads ``ENDED``/``VERIFIED`` under an
    open goal — *"the attempt established the outcome as the goal then stood, and the
    goal has since moved"*. **The arm that fails against a retrying implementation**,
    which would write ``ACHIEVED`` over a criterion the comparison never saw.
    """
    plans, outcome = await _verified(refuse_status=True)

    assert len(plans.statuses) == 1, "one call, and no second"
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.VERIFIED
    goal = await plans.get_goal(plans.opened[0].goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "§6's VERIFIED statement is worded to stay true"
    assert outcome.attempt_report is not None
    assert outcome.attempt_report.outcome is AttemptOutcome.VERIFIED


async def test_a_refused_ending_commit_writes_nothing_further_and_reports_nothing() -> None:
    """Arm 9's paired refusal, one commit earlier.

    *"No second commit, no ``set_goal_status`` call"*, the turn does not fail, the reply
    that already went is not re-rendered or retracted, and ``attempt_report`` comes back
    ``None`` so **no fixed statement is rendered on that turn** (§6) — a silence rather
    than a false outcome word.
    """
    plans, outcome = await _verified(refuse_ending=True)

    assert plans.statuses == [], "§4: the phase takes no GoalStatus write after a refusal"
    assert len([move for move in plans.moves if move.to_state is AttemptState.ENDED]) == 1, (
        "one attempt at the commit, and no second bite"
    )
    assert outcome.reply is not None, "the reply the stage already composed stands"
    assert outcome.attempt_report is None


async def test_every_other_member_ends_an_attempt_and_moves_no_status() -> None:
    """Arm 9's R53 half: *"an attempt ending is not the same event as the task completing"*.

    ``ANSWERED`` here; the other four are the comparison's own arms. What is asserted is
    that the goal's status is **unchanged** by an attempt reaching a terminal state —
    ADR-0249 §4 untouched, and nothing inferring a status from an attempt's state.
    """
    plans = _Statuses()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    await harness.engine.converse(_ASKED, timeout=PATIENT)

    ending = _ended(plans)
    assert ending is not None
    assert ending.outcome is AttemptOutcome.ANSWERED
    assert plans.statuses == []


# --------------------------------------------------------------------------- #
# §4's two conjuncts, over the window the composing stage opens                #
# --------------------------------------------------------------------------- #


async def test_the_ending_carries_the_versions_the_comparison_read() -> None:
    """§4: the snapshot is *"the ``ExecutionState.version`` the caller read"* at the comparison.

    A step that **failed** is retried and succeeds while the composing stage is out —
    ``FAILED → RUNNING → SUCCEEDED``, every step terminal at both instants and the status
    conjunct therefore silent. *"The version pairs close it."* So the ending transition
    must carry the figure the comparison read, the store must refuse it, and the turn
    must come back carrying **no report**: an outcome computed from the failure is not
    written over an execution whose answer the comparison never saw.

    **This is the arm that fails against an implementation re-reading the versions at
    the commit**, which would report the ground as unmoved over exactly the interval the
    field exists to cover — an arbitrarily slow model call.
    """

    async def _fails(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        msg = "the provider refused it"
        raise ToolError(msg)

    plans = _Statuses()
    harness = Harness(tools=(tool(),), plans=plans, tool_handler=_fails)
    stage: Any = harness.composing
    original = stage.compose
    retried: list[int] = []

    async def _compose(*args: Any, **kwargs: Any) -> Any:
        """Land ADR-0262 §4's retry inside the composing call it opens the window for."""
        if not retried:
            attempt = plans.opened[0]
            (execution_id,) = (await plans.get_attempt(attempt.id)).execution_ids  # type: ignore[union-attr]
            state = await plans.get_execution(execution_id)
            assert state is not None
            retried.append(state.version)
            state = await plans.commit_transition(
                StepTransition(
                    execution_id=execution_id,
                    step_id="step-1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    attempt_id=attempt.id,
                )
            )
            await plans.commit_transition(
                StepTransition(
                    execution_id=execution_id,
                    step_id="step-1",
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=state.version,
                    output={"booked": True},
                )
            )
        return await original(*args, **kwargs)

    stage.compose = _compose

    outcome = await harness.engine.converse(_SEND, timeout=PATIENT)

    ending = _ended(plans)
    assert ending is not None, "the engine proposed the ending the comparison computed"
    ((_, carried),) = ending.execution_versions
    assert carried == retried[0], "the version the comparison read, not the retry's"
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.state is not AttemptState.ENDED, "the store refused the stale commit"
    assert attempt.outcome is None
    assert plans.statuses == [], "§4: no second bite, and no GoalStatus write"
    assert outcome.attempt_report is None, "§6: a silence rather than a false outcome word"


# --------------------------------------------------------------------------- #
# Arm 7 — the attempt does not end, in every limb of the ending rule           #
# --------------------------------------------------------------------------- #


async def test_a_composition_that_produced_no_text_ends_no_attempt() -> None:
    """Arm 7's fourth limb: §4's **first** ending condition, read as the one ``bool`` §1 admits.

    A composition that returned no text writes no ``AttemptOutcome``, leaves the attempt
    non-terminal, writes no ``GoalStatus``, and returns ``attempt_report`` ``None``.
    """
    plans = _Statuses()
    stage = ComposingStage(model=FakeModelProvider(_refusing), streaming=FakeStreamingCompleter())
    harness = Harness(planner=NoStepPlanner(), plans=plans, composing=stage)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True

    assert _ended(plans) is None
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.state is not AttemptState.ENDED
    assert attempt.outcome is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


async def test_a_parked_attempt_ends_nothing_and_reports_nothing() -> None:
    """Arm 7's first limb: §4's **second** ending condition.

    A turn whose attempt is ``AWAITING_AUTHORIZATION`` is **paused**, not finished, so
    it writes no outcome and carries no report.
    """
    plans = _Statuses()
    harness = Harness(tools=(confirmable(),), plans=plans)

    outcome = await harness.engine.converse(_SEND, timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.confirmation is not None
    assert _ended(plans) is None
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.state is AttemptState.AWAITING_AUTHORIZATION
    assert attempt.outcome is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


async def test_a_turn_that_raised_a_question_ends_nothing_and_reports_nothing() -> None:
    """Arm 7's first limb again, over ``AWAITING_CLARIFICATION``.

    ADR-0250 §10 pauses such an attempt and leaves its phase where it stood, so it never
    reaches ``VERIFY`` — and §4's second ending condition says the same thing from the
    other side.
    """

    class _Asking(NoStepPlanner):
        async def plan(self, goal: Any, **fields: Any) -> Any:
            produced = await super().plan(goal, **fields)
            return produced.model_copy(
                update={
                    "understanding": ProposedUnderstanding(
                        retains_outcome=True,
                        criteria=(
                            ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),
                        ),
                        questions=(ProposedQuestion(text="Which campsite?", about="S1"),),
                    )
                }
            )

    plans = _Statuses()
    harness = Harness(planner=_Asking(), plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is not None
    assert _ended(plans) is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


async def test_an_unsettled_step_leaves_the_attempt_live_and_reports_nothing() -> None:
    """Arm 7's third limb: §4's **third** ending condition (#2477).

    A plan of two steps reaches the ending with the second still ``PENDING``, so the
    attempt stays live: no ``AttemptOutcome`` is written, no ``GoalStatus`` moves, and
    the turn returns ``attempt_report`` ``None``. That is §4's stated cost, bounded to
    one turn by the next turn's reconciliation.
    """
    plans = _Statuses()
    harness = Harness(planner=_TwoStepPlanner(), tools=(tool(),), plans=plans)

    outcome = await harness.engine.converse(_SEND, timeout=PATIENT)

    assert outcome.step is not None
    assert _ended(plans) is None
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.outcome is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


async def test_an_indeterminate_step_ends_no_attempt_and_reports_nothing() -> None:
    """Arm 7's second limb: a step standing ``INDETERMINATE`` **reaches no limb at all**.

    §4: *"the third ending condition refuses to end an attempt naming one …
    ``VERIFIED`` is therefore unreachable beside a possible effect, and with it
    ``ACHIEVED`` — reached by the attempt not ending rather than by a conjunct on limbs
    4 and 5"*, which is also what keeps ADR-0259 §4's acts 3 and 4 reachable.

    The step reaches ``INDETERMINATE`` the way ADR-0029 §8 makes it reachable in a live
    executor: a ``side_effecting`` tool whose ``idempotency`` is not ``NATURAL``, over a
    deadline that passed while the callable was inside the provider.

    **The ending is refused before any member is consulted**, which is asserted here as
    the absence of a proposed ``→ ENDED`` transition at all rather than as an outcome
    that happened not to be ``VERIFIED``: §4 reaches that *"by the attempt not ending
    rather than by a conjunct on limbs 4 and 5"*. Arm 7's pair — the same record with
    **every criterion met** — is stated at the comparison, where the member is decided
    (``test_verification_comparison.py``'s
    ``test_every_criterion_met_beside_an_indeterminate_step_is_still_verified``): that
    arm shows limb 5 really is what such a record earns, and this one shows the attempt
    does not end regardless. An ``INDETERMINATE`` step is never *satisfying* under §2, so
    the two halves cannot be driven through one step and are not pretended to be.
    """

    async def _hangs(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        await asyncio.sleep(30)

    plans = _Statuses()
    harness = Harness(tools=(tool(idempotency=Idempotency.NONE),), plans=plans, tool_handler=_hangs)

    outcome = await harness.engine.converse(_SEND, timeout=timedelta(milliseconds=20))

    assert outcome.step is not None
    held = outcome.step.state.step("step-1")
    assert held is not None
    assert held.status is StepStatus.INDETERMINATE
    assert _ended(plans) is None, "§4's third ending condition refuses it"
    attempt = await plans.get_attempt(plans.opened[0].id)
    assert attempt is not None
    assert attempt.outcome is None
    assert plans.statuses == []
    assert outcome.attempt_report is None


# --------------------------------------------------------------------------- #
# Arm 10's L4 half — where the report is absent, and what `continues` says     #
# --------------------------------------------------------------------------- #


async def test_a_restatement_carries_no_report() -> None:
    """Arm 10: ``attempt_report`` is ``None`` on ADR-0198 §1's restatement.

    A restatement *"drives nothing and searches nothing"*: it composes nothing, captures
    nothing and ends no attempt, so there is no comparison to report — §6's *"``None`` on
    every other returned outcome"*, and the value is absent by construction rather than
    by a branch that could forget it.
    """
    plans = _Statuses()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse(_SEND, timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token
    await harness.engine.resume(token, approved=True, timeout=PATIENT)

    restated = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert restated.turn is None, "ADR-0198 §2's own shape"
    assert restated.attempt_report is None
