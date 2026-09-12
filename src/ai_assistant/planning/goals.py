"""Applying ADR-0249 §12's two commands to a stored record.

The goal half of what :mod:`ai_assistant.planning.execution` is for steps: one
statement of what appending an interpretation revision and committing an attempt
transition *do*, so the two conforming ``PlanStore`` implementations in this package
cannot drift on it. ADR-0049's own note for the transition graph is the precedent —
"the ADR-0014 §4 transition graph is authoritative in exactly one place and the two
stores cannot drift on it" — applied to the two writes ADR-0249 §12 adds.

The canonical fake in :mod:`ai_assistant.testing.planning` deliberately does **not**
import this module, for the reason that module states: a consumer's tests would then
pull in the very subsystem the fake stands in for. The shared conformance suite is
what holds the two statements honest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.errors import IllegalTransitionError, PlanningError
from ai_assistant.core.types import (
    MAX_GOAL_INTERPRETATIONS,
    TERMINAL_ATTEMPT_STATES,
    AttemptPhase,
    GoalAttempt,
    GoalCandidates,
    GoalQuestionDisposition,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import (
        AttemptTransition,
        Goal,
        GoalInterpretation,
        GoalQuestion,
        GoalStatus,
        UtcInstant,
    )

#: ADR-0249 §6's order, read off the declaration rather than restated: "within one
#: attempt, ``phase`` advances in that order and never moves backwards".
_PHASE_ORDER: Final[dict[AttemptPhase, int]] = {
    phase: index for index, phase in enumerate(AttemptPhase)
}


def bounded(goal: Goal) -> Goal:
    """Hold ``goal``'s history to ADR-0249 §2's bound, disclosing what it drops.

    §2 states the bound over **the write**, not over one member: "a goal whose sequence
    would exceed it drops its **oldest** element on the write that would exceed it, and
    the **current** interpretation is never dropped". So both writes take it —
    :meth:`PlanStore.save_goal`, which is the opening write, and
    :meth:`PlanStore.record_interpretation`, which is every later one — and a store
    that applied it to only the second would accept an oversized history at the door
    and enforce the bound on nothing.

    **The elision is disclosed and never silent**, on ADR-0086 §4's own ground: a goal
    reporting fewer revisions than happened "answers the question *when did the
    system's understanding change, and why* falsely". A write that drops *k* elements
    advances ``interpretation_elided`` by *k*.

    Args:
        goal: The goal as it would be written.

    Returns:
        The goal itself where the bound is not exceeded — a copy that changes no field
        is a copy for nothing — and a trimmed one where it is.
    """
    dropped = max(0, len(goal.interpretation) - MAX_GOAL_INTERPRETATIONS)
    if not dropped:
        return goal
    return goal.model_copy(
        update={
            "interpretation": goal.interpretation[dropped:],
            "interpretation_elided": goal.interpretation_elided + dropped,
        }
    )


def appended(goal: Goal, interpretation: GoalInterpretation) -> Goal:
    """Append one revision to ``goal``, eliding the oldest if it must (§1, §2).

    The revision must be **one greater** than the goal's current one (§1), the
    **current** interpretation is never dropped (§2), and a write that drops *k*
    elements advances ``interpretation_elided`` by *k* — silent truncation is not
    available, on ADR-0086 §4's own ground. ``version`` advances by one because this
    is a mutation of the goal (§1).

    Args:
        goal: The goal as stored.
        interpretation: The revision to append.

    Returns:
        The goal as it stands after the append.

    Raises:
        PlanningError: If the revision does not follow the goal's current one.
    """
    current = goal.interpretation[-1]
    if interpretation.revision != current.revision + 1:
        msg = (
            f"goal {goal.id} is at revision {current.revision}, so the next revision is "
            f"{current.revision + 1} and not {interpretation.revision}: a goal's "
            f"interpretation is append-only and each revision is one greater than the "
            f"one before it (ADR-0249 §1)"
        )
        raise PlanningError(msg)
    return bounded(
        goal.model_copy(
            update={
                "interpretation": (*goal.interpretation, interpretation),
                "version": goal.version + 1,
            }
        )
    )


def engaged(goal: Goal, *, at: UtcInstant, conversation_id: str) -> Goal:
    """Stamp ``goal``'s engagement and advance its version (ADR-0250 §1, §9).

    The **one** place either engagement field is written, so the two conforming stores
    in this package cannot drift on §1's "exactly one writer" clause. It writes
    **nothing else**: not the status, not the interpretation, not the attempt — and
    :attr:`Goal.conversation_id` is **never rewritten**, because that stays the
    conversation the goal was opened in (ADR-0249 §1's provenance clause).

    Args:
        goal: The goal as stored.
        at: The engagement instant.
        conversation_id: The conversation the engaging turn ran under.

    Returns:
        The goal as it stands after the stamp.
    """
    return goal.model_copy(
        update={
            "last_engaged_at": at,
            "last_engaged_in": conversation_id,
            "version": goal.version + 1,
        }
    )


def with_status(goal: Goal, *, status: GoalStatus) -> Goal:
    """Move ``goal``'s status and advance its version (ADR-0250 §9).

    The goal's **only** status-mutation route, stated once for both stores. It writes
    **nothing else**: not the engagement stamp, not the interpretation, not the
    attempt. **No member of the vocabulary is refused here**, because A10 and A3 write
    ``ACHIEVED`` and ``BLOCKED`` through this same route and "a store that refused a
    member would be a second place the vocabulary is decided" — which act may write
    which member is the caller's rule.

    Args:
        goal: The goal as stored.
        status: The status to write.

    Returns:
        The goal as it stands after the move.
    """
    return goal.model_copy(update={"status": status, "version": goal.version + 1})


def capped(goals: Iterable[Goal], *, limit: int) -> GoalCandidates:
    """Order a candidate set by ADR-0250 §1's key and hold it to ``limit`` (§2).

    The order is ``last_engaged_at`` **descending** with the ``goal_id`` **ascending**
    as the tie-break, and a goal carrying **no** instant sorts **after** every goal
    that carries one. ADR-0074 §2's reason binds: "some total order must be named or
    two implementations answer the same page differently", and two goals engaged in
    the same instant is reachable because a migrated pair carries no instant at all.

    **The absent instant sorts last rather than first, and that is the conservative
    direction**: sorting it first would make the oldest, least-touched objective in
    the store the focused goal of every conversation that holds one.

    Args:
        goals: The whole membership of the set, in any order.
        limit: The most candidates to return.

    Returns:
        The capped set, with ``elided`` counting what the truncation dropped.

    Raises:
        PlanningError: If ``limit`` is not positive.
    """
    if limit < 1:
        msg = f"a candidate set is read with a positive limit and not {limit} (ADR-0250 §9)"
        raise PlanningError(msg)
    ordered = sorted(
        goals,
        key=lambda goal: (
            goal.last_engaged_at is None,
            -(goal.last_engaged_at.timestamp() if goal.last_engaged_at is not None else 0.0),
            goal.id,
        ),
    )
    return GoalCandidates(goals=tuple(ordered[:limit]), elided=max(0, len(ordered) - limit))


def settled(
    question: GoalQuestion, *, disposition: GoalQuestionDisposition, at: UtcInstant
) -> GoalQuestion:
    """Settle ``question``, clearing its content in the same step (ADR-0250 §8).

    "A settled question keeps its facts and loses its content": ``text`` and ``about``
    are cleared **in the same step that moves the disposition**, and no implementation
    retains a copy, a digest, a snapshot or an archive of either. ``goal_id`` and
    ``attempt_id`` survive, so a late answer still reaches the goal (§11).

    Args:
        question: The open question as stored.
        disposition: The terminal member to write.
        at: The settlement instant.

    Returns:
        The question as it stands after the settlement.

    Raises:
        PlanningError: If ``disposition`` is ``OPEN``, which settles nothing.
    """
    if disposition is GoalQuestionDisposition.OPEN:
        msg = (
            "settle_question moves an OPEN question to a terminal member: OPEN settles "
            "nothing and no disposition is inferred from silence (ADR-0250 §9, §12)"
        )
        raise PlanningError(msg)
    return question.model_copy(
        update={"disposition": disposition, "settled_at": at, "text": None, "about": None}
    )


def advanced(attempt: GoalAttempt, transition: AttemptTransition) -> GoalAttempt:
    """Apply one transition to ``attempt`` and return the result (§5, §6, §12).

    Every absent member leaves its field unchanged; an ``add_*`` member appends its
    identifier, and one the tuple already holds is **ignored** rather than duplicated
    or refused. The phase never moves backwards, no transition leaves a terminal
    state, and neither effort counter is ever reduced.

    Args:
        attempt: The attempt as stored.
        transition: The command to apply.

    Returns:
        The attempt as it stands after the transition.

    Raises:
        IllegalTransitionError: If the move would take the phase backwards or move a
            terminal attempt to another state.
        PlanningError: If an effort counter would be reduced, or the result is not a
            shape ADR-0249 §5 admits.
    """
    state = attempt.state if transition.to_state is None else transition.to_state
    if attempt.state in TERMINAL_ATTEMPT_STATES and state is not attempt.state:
        msg = (
            f"attempt {attempt.id} is {attempt.state.value} and no transition leaves a "
            f"terminal member (ADR-0249 §5)"
        )
        raise IllegalTransitionError(msg)
    phase = attempt.phase if transition.to_phase is None else transition.to_phase
    if _PHASE_ORDER[phase] < _PHASE_ORDER[attempt.phase]:
        msg = (
            f"attempt {attempt.id} stands at {attempt.phase.value} and a phase advances "
            f"in ADR-0249 §6's order and never moves backwards: {phase.value} is earlier"
        )
        raise IllegalTransitionError(msg)
    effort = attempt.effort
    if transition.planner_calls is not None or transition.working is not None:
        calls = (
            effort.planner_calls if transition.planner_calls is None else transition.planner_calls
        )
        working = effort.working if transition.working is None else transition.working
        if calls < effort.planner_calls or working < effort.working:
            msg = (
                f"attempt {attempt.id}'s effort is monotonically non-decreasing and no "
                f"implementation subtracts from it (ADR-0249 §5)"
            )
            raise PlanningError(msg)
        effort = effort.model_copy(update={"planner_calls": calls, "working": working})
    try:
        return GoalAttempt(
            id=attempt.id,
            goal_id=attempt.goal_id,
            opened_at=attempt.opened_at,
            phase=phase,
            state=state,
            outcome=attempt.outcome if transition.outcome is None else transition.outcome,
            effort=effort,
            plan_ids=_appended_id(attempt.plan_ids, transition.add_plan_id),
            execution_ids=_appended_id(attempt.execution_ids, transition.add_execution_id),
            authorization_ids=_appended_id(
                attempt.authorization_ids, transition.add_authorization_id
            ),
            ended_at=attempt.ended_at if transition.ended_at is None else transition.ended_at,
            version=attempt.version + 1,
        )
    except ValidationError as exc:
        msg = (
            f"the transition would leave attempt {attempt.id} in a shape ADR-0249 §5 refuses: {exc}"
        )
        raise PlanningError(msg) from exc


def _appended_id(held: tuple[str, ...], addition: str | None) -> tuple[str, ...]:
    """Append ``addition`` unless the tuple already holds it (ADR-0249 §12).

    Args:
        held: The identifiers already on the attempt, in order.
        addition: The identifier to append, or ``None``.

    Returns:
        The tuple with ``addition`` at its end, or unchanged where it was absent or
        already held — "an identifier the tuple already holds is ignored rather than
        duplicated or refused".
    """
    if addition is None or addition in held:
        return held
    return (*held, addition)
