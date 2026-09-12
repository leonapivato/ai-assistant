"""ADR-0249 §5, §6, §11 and §12 at the engine: the attempt is opened, stamped and ended.

The attempt-shaped half of §16's L3 arms. Every one of them is engine-level by
construction: ``LearningLoop`` holds no ``PlanStore`` and gains none (ADR-0228 §5), so
the attempt is opened **in memory** by the loop and every write of it is this
component's, at the one site that persists a plan today (§11).

What lives here is §16 item 1's attempt half (S1's six phase stamps, its stored row and
the goal's status), item 14's second clause (a turn that reaches the site records what it
actually finished on), item 19 within a turn, and §12's two-route persistence — a goal
this turn opened through ``save_goal``, a goal the store already holds through
``record_interpretation`` under the compare-and-swap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner, tool
from test_engine_read_envelope import _recorder

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptPhase,
    AttemptState,
    Disposition,
    Goal,
    GoalInterpretation,
    GoalStatus,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
)
from ai_assistant.testing import FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import AttemptTransition, GoalAttempt, GoalRevision
    from ai_assistant.orchestration.loop import RespondedTurn

_ASKED: Final = "what is two plus two?"

#: The phases a turn stamps **at the store**: the one the row is opened at, then one per
#: ``commit_attempt``. The three before it — ``UNDERSTAND``, ``INVESTIGATE`` and ``PLAN``
#: — are stamped in memory by the loop before any row exists to carry them, and are
#: asserted there (``test_loop_understanding``). §12's own rule is what joins the two
#: halves into §16 item 1's six: "§6 makes the order fixed and monotonic, so the phases an
#: attempt has passed are exactly those at or before its current one".
_STORED_PHASES: Final = [
    AttemptPhase.PLAN,
    AttemptPhase.AUTHORIZE,
    AttemptPhase.EXECUTE,
    AttemptPhase.VERIFY,
]


class _Recording(FakePlanStore):
    """The canonical store, recording the attempt writes it was asked for.

    §6 makes the six phases "six responsibilities and **six observable transitions**",
    and three of a turn's six happen before any row exists to observe them on — so what
    a case can see at the store is the phase the row was **opened** at and each
    ``to_phase`` after it. Together they are the sequence the attempt occupied.
    """

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.opened: list[GoalAttempt] = []
        self.moves: list[AttemptTransition] = []
        self.appended: list[GoalRevision] = []

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Record and delegate."""
        self.opened.append(attempt)
        return await super().open_attempt(attempt)

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Record and delegate."""
        self.moves.append(transition)
        return await super().commit_attempt(transition)

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Record and delegate."""
        self.appended.append(revision)
        return await super().record_interpretation(revision)

    @property
    def phases(self) -> list[AttemptPhase]:
        """Every phase the attempt was stamped with at this store, in order."""
        return [one.phase for one in self.opened] + [
            move.to_phase for move in self.moves if move.to_phase is not None
        ]


# --------------------------------------------------------------------------- #
# §16 item 1 — S1, end to end                                                  #
# --------------------------------------------------------------------------- #


async def test_a_plain_question_passes_through_all_six_phases_on_one_planner_call() -> None:
    """§16 item 1 (S1): six phase stamps, and the stored row ends ``ANSWERED``.

    "*What is two plus two?* on a conversation's first turn: … **one** ``Planner.plan``
    call and **one** composing call, which is exactly today's cost; six phase stamps; no
    read request; no question; the attempt passing through all six phases and its
    **stored** row ending at ``VERIFY``/``ENDED``/``ANSWERED``, written first at §11's
    site and moved there by a same-turn ``commit_attempt`` once the answer exists; and
    the goal's status still **``ACTIVE``**."

    §6 is why the vacuous ones are stamped at all: "no phase mandates a model call, a
    store read, a park or a user interaction", and "a turn that answers a plain question
    passes through all six phases on one planner call".
    """
    plans = _Recording()
    planner = NoStepPlanner()
    composing, model = _recorder()
    harness = Harness(planner=planner, plans=plans, composing=composing)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    assert planner._calls == 1, "one Planner.plan call, which is exactly today's cost"
    assert len(model.calls) == 1, "and one composing call"
    assert outcome.turn.plan.read_request is None, "no read request"
    assert outcome.turn.goal.open_questions == (), "and no question"
    assert plans.phases == _STORED_PHASES, "in §6's order, and never backwards"
    assert plans.appended == [], "§12: an opened goal's revisions ride on save_goal"
    (stored,) = plans.opened
    assert stored.phase is AttemptPhase.PLAN, "written carrying the phase it stood at"
    assert stored.state is AttemptState.RUNNING
    assert (stored.outcome, stored.ended_at) == (None, None), "nothing claimed in advance"
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED
    assert attempt.ended_at == AT
    goal = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "§4: ACHIEVED gets no producer here"


async def test_the_attempt_references_the_plans_the_turn_produced() -> None:
    """§5: "plans, executions and authorizations are referenced by id and never inlined".

    ADR-0228 §5 persists **every** plan a turn produced, so the attempt references the
    whole sequence — and the reference resolves, which is what ``open_attempt`` refuses
    an attempt for when it does not (§12).
    """
    plans = _Recording()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    (stored,) = plans.opened
    assert stored.plan_ids == (outcome.turn.plan.id,)
    assert stored.execution_ids == (), "a no-action turn opened none"
    assert stored.effort.planner_calls == 1, "§5's ledger: the one call this turn made"


async def test_a_driving_turn_appends_its_execution_and_ends_answered() -> None:
    """§16 items 1 and 19 over a turn with a step, and §5's ``ANSWERED``.

    "An attempt the store already holds takes a plan id, then an execution id … the first
    two inside the turn that opened it, each appended in order." The execution id reaches
    the row through ``commit_attempt`` "at the moment the fact becomes true" — which is
    after ``start_execution`` and never before it.
    """
    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    assert plans.phases == _STORED_PHASES
    (stored,) = plans.opened
    assert stored.execution_ids == (), "not claimed in advance"
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.execution_ids == (outcome.step.state.id,)
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED


async def test_a_turn_that_ends_before_the_site_writes_no_attempt_row() -> None:
    """§16 item 14's first clause, over the attempt.

    "A turn whose planner raises … leaves **no goal row, no attempt row and no plan
    row**" — the attempt was opened in memory and the turn ended above the one site §11
    names, so there is nothing to repair and nothing to clean up.
    """

    plans = _Recording()
    harness = Harness(planner=_Raising(), plans=plans)

    with pytest.raises(PlanningError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    export = await harness.plans.export()
    assert (export.goals, export.plans, export.attempts) == ((), (), ())
    assert plans.opened == []
    assert plans.moves == []


# --------------------------------------------------------------------------- #
# §12 — the second persistence route, over a goal the store already holds      #
# --------------------------------------------------------------------------- #


class _Raising(NoStepPlanner):
    """A planner that refuses the call, so the turn ends above §11's site."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Refuse."""
        del goal, fields
        msg = "the planner is down"
        raise PlanningError(msg)


class _Continuing(NoStepPlanner):
    """A planner that restates the outcome on a span of this turn's own request."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan as ``NoStepPlanner`` does, proposing one new constraint."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(
            update={
                "understanding": ProposedUnderstanding(
                    retains_outcome=True,
                    constraints=(
                        ProposedElement(text="two plus two", ground=Ground.USER_STATED, span="two"),
                    ),
                )
            }
        )


def _earlier() -> Goal:
    """A goal an earlier turn opened, as this system stores one."""
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a campsite",
                recorded_at=AT,
                raised_by="turn-earlier",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
        last_engaged_at=AT,
    )


async def test_a_continued_goals_revision_goes_through_record_interpretation() -> None:
    """§12: ``save_goal`` is "the opening write alone", so a continued goal takes the other route.

    The revision is appended under the compare-and-swap, against the ``version`` the loop
    read — and the attempt this turn opens is a **new** attempt on that **same** goal
    (§5, §16 item 2).

    **Which goal a turn continues is A2's** (§13), so the association is supplied here by
    a loop that states it rather than decided by anything this lane ships.
    """
    plans = _Recording()
    earlier = _earlier()
    await plans.save_goal(earlier)
    harness = Harness(planner=_Continuing(), plans=plans)
    _continue(harness, earlier)

    outcome = await harness.engine.converse("two plus two", timeout=PATIENT)

    assert outcome.turn is not None
    (appended,) = plans.appended
    assert appended.goal_id == earlier.id
    assert appended.expected_version == earlier.version
    assert appended.interpretation.revision == 2
    assert appended.interpretation.raised_by is not None
    (constraint,) = appended.interpretation.constraints
    assert (constraint.ground, constraint.span) == (Ground.USER_STATED, "two")
    stored = await plans.get_goal(earlier.id)
    assert stored is not None
    assert stored.interpretation[0] == earlier.interpretation[0], "prior revision unedited"
    assert stored.version == 1, "§12: the compare-and-swap token advanced by the write"
    (opened,) = plans.opened
    assert opened.goal_id == earlier.id, "a new attempt on the same goal"


def _continue(harness: Harness, goal: Goal) -> None:
    """Make this harness's loop continue ``goal`` rather than open one.

    A2 decides association (§13) and nothing in this lane does, so a case that needs the
    *continued* route states the association itself — at the one seam
    :meth:`LearningLoop.respond` exposes for it, rather than by reaching past the engine.
    """
    loop = harness.engine._loop
    responds = loop.respond

    async def continuing(utterance: str, **fields: object) -> RespondedTurn:
        return await responds(utterance, **fields, continuing=goal)  # type: ignore[arg-type]  # the keywords the engine passes

    loop.respond = continuing  # type: ignore[method-assign]  # a case stating the association A2 will


# --------------------------------------------------------------------------- #
# The supply a ground resolves against is the turn's own                       #
# --------------------------------------------------------------------------- #


async def test_a_recorded_element_reaches_the_stored_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11, §12: the revision the loop resolved is what the store holds.

    Asserted end to end rather than at the resolver, because §11's carrier is what makes
    it true: the record travels inside ``ai_assistant.orchestration`` as data and
    ``Engine`` persists it, and a lane that built the revision and dropped the carrier
    would pass every resolver case and store nothing.
    """
    del monkeypatch
    harness = Harness(planner=_Continuing())

    outcome = await harness.engine.converse("two plus two", timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert [one.revision for one in stored.interpretation] == [1, 2]
    (constraint,) = stored.interpretation[-1].constraints
    assert constraint.text == "two plus two"
    assert constraint.span == "two", "a span of this turn's own request"
    assert outcome.turn.goal.constraints[0].text == "two plus two", "and the brief shows it"
