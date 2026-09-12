"""ADR-0249 §11's carrier, and the absences §1 and §8 admit exactly one route to.

The loop builds the goal record and its revisions; ``Engine`` persists them, at the one
site that persists a plan today. What crosses the wire is the **brief**; the record
travels inside ``ai_assistant.orchestration`` as data, on ``RespondedTurn.goal``.

This file carries §16's arms that name L1 and that only an engine-level case can reach:
item 8 (the bootstrap is byte-equal), item 14 (a turn that ends early persists nothing),
and item 18 (the absences have exactly one producer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from test_engine import PATIENT, Harness, NoStepPlanner

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptPhase,
    AttemptState,
    GoalStatus,
    Ground,
    ReadAskOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        MemoryRecord,
        PlannerOutput,
        ShownFile,
    )

_ASKED = "  what is two plus two?  "
_STRIPPED = "what is two plus two?"


async def test_the_turn_carries_the_brief_and_the_record_reaches_the_store() -> None:
    """§11: the projection goes on the turn, the record goes to the store.

    "A turn carrying a projection carries no record to save", so ``Engine``'s
    ``save_goal`` reads the loop's carrier instead — which is what keeps ADR-0228 §5's
    prohibition intact: **no lane gives** ``LearningLoop`` **a** ``PlanStore``.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    brief = outcome.turn.goal
    stored = await harness.plans.get_goal(brief.goal_id)
    assert stored is not None, "the record the loop built, persisted at the plan's own site"
    assert stored.statement == brief.outcome
    assert stored.status is brief.status
    assert not hasattr(brief, "interpretation"), "the chain does not ride on the turn"
    assert not hasattr(brief, "provenance"), "and neither does the goal-level provenance"


async def test_the_bootstrap_is_byte_equal_across_all_three_values() -> None:
    """§16 item 8, over a turn that came off the production path.

    "On a goal's first turn, revision 1's ``outcome``, ``Goal.statement`` and
    ``TurnResult.utterance`` are the same string, which keeps ADR-0248 §6's assertion
    true on that path." The padding is the observable: one normalisation in one place
    (ADR-0248 §1) is what makes the three agree rather than three that happen to.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    [revision] = stored.interpretation
    assert revision.outcome == stored.statement == outcome.turn.utterance == _STRIPPED
    assert outcome.turn.goal.outcome == _STRIPPED, "and the brief the planner saw"


async def test_revision_one_is_opened_grounded_and_carries_no_element() -> None:
    """§3, over the record the production path actually wrote.

    Revision 1 "carries **no** ``GoalElement``, and its ``outcome_ground`` is
    ``USER_STATED`` with its ``outcome_span`` the whole request — which is exactly true,
    since its outcome **is** the request". And an *opened* revision 1 always carries a
    ``raised_by`` where a **migrated** one never does, "so no reader has to guess which
    of the two it holds".
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    [revision] = stored.interpretation
    assert revision.revision == 1
    assert (revision.constraints, revision.criteria, revision.conditions) == ((), (), ())
    assert revision.outcome_ground is Ground.USER_STATED
    assert revision.outcome_span == _STRIPPED
    assert revision.outcome_evidence_id is None
    assert revision.raised_by is not None


async def test_no_path_writes_none_into_the_absences_this_decision_admits() -> None:
    """§16 item 18: the absences have exactly one producer, and it is not this path.

    ``Goal.conversation_id``, ``Goal.last_engaged_at``, ``GoalInterpretation.raised_by``
    and ``ActionPlan.targets_revision`` are each typed ``| None`` and "``None`` is
    reachable by exactly one route: a row written before this decision" (§1, §8). No
    path through ``orchestration`` writes one, and none **authors** a ``USER_STATED``
    outcome whose ``outcome_span`` is absent.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert stored.conversation_id is not None
    assert stored.last_engaged_at is not None
    for revision in stored.interpretation:
        assert revision.raised_by is not None
        if revision.outcome_ground is Ground.USER_STATED:
            assert revision.outcome_span is not None, "a lane never authors the absence"
    export = await harness.plans.export()
    assert all(plan.targets_revision is not None for plan in export.plans)
    assert all(plan.targets_revision == 1 for plan in export.plans), "always 1 in this lane"


class _RaisingPlanner(NoStepPlanner):
    """A planner that fails the turn before any plan exists."""

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        msg = "no plan for that"
        raise PlanningError(msg)


async def test_a_turn_that_ends_before_the_site_writes_no_goal_row() -> None:
    """§16 item 14, extended to the goal: ADR-0228 §5's clause over a second record kind.

    "A turn that ends before that site persists nothing, exactly as it does today" binds
    for the goal exactly as it binds for the plan (§11), and the reason is structural:
    the loop holds no ``PlanStore``, so there is nowhere else the record could be
    written from.
    """
    harness = Harness(planner=_RaisingPlanner())

    with pytest.raises(PlanningError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    export = await harness.plans.export()
    assert export.goals == (), "no goal row"
    assert export.plans == (), "no plan row"
    assert export.attempts == (), "and no attempt row — the attempt was opened in memory only"


async def test_a_plain_question_records_one_interpretation_and_one_attempt() -> None:
    """ADR-0249 §16 item 1 (S1), the halves an engine-level case reaches.

    A planner that proposes no understanding leaves the goal at revision 1 and its
    ``version`` unmoved — §6: "recording an interpretation revision does not move the
    phase", and a turn that records none moves nothing at all — while the attempt is
    still opened, stamped through all six phases and ended ``ANSWERED``. The phase
    sequence itself is asserted in ``test_engine_attempts.py``; what this case holds is
    that the goal side of S1 is unchanged by the attempt side.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert len(stored.interpretation) == 1, "no understanding is proposed and none recorded"
    assert stored.version == 0, "and the goal's compare-and-swap token has not moved"
    assert stored.status is GoalStatus.ACTIVE, "§4: producing a reply establishes nothing"
    (attempt,) = await harness.plans.attempts_of(outcome.turn.goal.goal_id)
    assert attempt.goal_id == stored.id
    assert attempt.phase is AttemptPhase.VERIFY
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED


def test_the_loop_holds_no_plan_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0228 §5, restated because ADR-0249 §11 relies on it.

    "No lane adds a second persistence site, gives ``LearningLoop`` a ``PlanStore``, or
    carries a plan out of a failing turn in order to write it" — and §11 adds the goal
    record to what that clause covers, which only holds while the loop cannot write.
    """
    del monkeypatch
    harness = Harness(planner=NoStepPlanner())
    loop: Any = harness.engine._loop

    assert not any(hasattr(getattr(loop, name, None), "save_goal") for name in vars(loop)), (
        "no attribute of the loop is a PlanStore"
    )
