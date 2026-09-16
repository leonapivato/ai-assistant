"""ADR-0262 §11's L2 at the engine: every ``→ ENDED`` commit carries §4's snapshot.

The lane is **compatibility alone** — *"it computes no verdict, writes no
``GoalStatus`` and changes no behaviour"* — so what these arms are about is the value
the store is handed, read off the transitions a recording ``PlanStore`` was asked for.
What the store then does with the pairs is L3's, and which
:class:`~ai_assistant.core.types.AttemptOutcome` an attempt earns is L4's; neither is
asserted here, and the outcome every arm below sees is still ADR-0249 §5's
``ANSWERED``.

**Three sites**, which is the number §11 names and the number ``orchestration`` has at
this base: the authorization resumption's finishing commit
(``Engine._settle_resumption``) and ``_run_turn``'s two ending commits, the driven one
and the undriven one. All three reach ``commit_attempt`` through ``Engine._move_attempt``,
which is also the only ``commit_attempt`` call in this subsystem that can carry
``to_state=ENDED``: the other three — the plan append, the phase/state move and the
planner-call charge — set no state at all.

**Completeness is the half the arms are built around** (§4): the field is *"a snapshot
of the set the comparison read rather than a list of the ones the caller chose to
protect"*, because *"a subset would leave the omitted execution free to move between
the comparison and the commit, which is the whole of the race"*. So the two-execution
arm below is the one that fails against an implementation passing the execution its own
turn drove.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from test_engine import AT, PATIENT, Harness, NoStepPlanner, confirmable, tool
from test_engine_attempts import _Recording

from ai_assistant.core.types import (
    ActionPlan,
    AttemptState,
    AttemptTransition,
    Disposition,
)

if TYPE_CHECKING:
    from ai_assistant.testing import FakePlanStore

_ASKED = "what is two plus two?"


def _ending(plans: _Recording) -> AttemptTransition:
    """The one ``→ ENDED`` transition this store was asked for."""
    (ended,) = [move for move in plans.moves if move.to_state is AttemptState.ENDED]
    return ended


async def _snapshot_of(plans: FakePlanStore, attempt_id: str) -> tuple[tuple[str, int], ...]:
    """The complete snapshot, assembled from the store rather than from the engine.

    Read after the turn, which is the same figure the commit read: the ending commit is
    the last write a turn makes, and nothing moves an execution after it.
    """
    attempt = await plans.get_attempt(attempt_id)
    assert attempt is not None
    pairs: list[tuple[str, int]] = []
    for execution_id in attempt.execution_ids:
        state = await plans.get_execution(execution_id)
        assert state is not None
        pairs.append((execution_id, state.version))
    return tuple(pairs)


# --------------------------------------------------------------------------- #
# Site 1 — `_run_turn`'s undriven ending commit                                #
# --------------------------------------------------------------------------- #


async def test_an_attempt_naming_no_execution_ends_carrying_the_empty_snapshot() -> None:
    """§4: *"an attempt naming no execution therefore takes an empty tuple and nothing else"*.

    The undriven ending commit, over the turn ADR-0262 §12's arm 1 is stated of: a plain
    question, no step claimed, and an attempt whose ``execution_ids`` is empty. The
    empty tuple is the **complete** snapshot here and not an absent one — which is why
    this arm asserts the attempt names nothing rather than only that the field is empty.
    """
    plans = _Recording()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    (stored,) = plans.opened
    ended = _ending(plans)
    assert ended.attempt_id == stored.id
    assert await _snapshot_of(plans, stored.id) == (), "the attempt names no execution"
    assert ended.execution_versions == (), "so the complete snapshot is the empty tuple"


# --------------------------------------------------------------------------- #
# Site 2 — `_run_turn`'s driven ending commit                                  #
# --------------------------------------------------------------------------- #


async def test_a_driving_turn_ends_carrying_its_executions_stored_version() -> None:
    """§4: the pair is the execution's id and *"the ``ExecutionState.version`` the caller read"*.

    The version is asserted to be the one the store holds **after the walk** and not the
    zero a fresh execution opens at — the arm that fails against an implementation
    reading the version before it drove, which would report a race on every turn that
    claimed a step.
    """
    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    (stored,) = plans.opened
    complete = await _snapshot_of(plans, stored.id)
    ((execution_id, version),) = complete
    assert execution_id == outcome.step.state.id, "the execution this turn appended"
    assert version > 0, "the walk advanced it, so a version read before driving is stale"
    assert _ending(plans).execution_versions == complete


# --------------------------------------------------------------------------- #
# Site 3 — the authorization resumption's finishing commit                     #
# --------------------------------------------------------------------------- #


async def test_a_resumption_ends_carrying_the_parked_executions_version() -> None:
    """§11's third site: the commit that finishes a resumed attempt carries the snapshot.

    The attempt is read here by ``_attempt_of`` rather than carried across the turn —
    *"read immediately before each commit rather than carried across one"* — and §11's
    *"read where they read the attempt"* is what puts the snapshot on the same row.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    complete = await _snapshot_of(plans, stored.id)
    ((execution_id, version),) = complete
    assert execution_id == parked.step.state.id
    assert version > 0
    assert _ending(plans).execution_versions == complete


# --------------------------------------------------------------------------- #
# The completeness half, which is the one §4 calls load-bearing                #
# --------------------------------------------------------------------------- #


async def test_the_snapshot_carries_every_execution_the_attempt_names() -> None:
    """§4: a snapshot of the **set**, never *"a list of the ones the caller chose to protect"*.

    The live attempt is given a **second** execution between the park and the resume —
    an execution this turn neither opened nor drove — and the ending commit must carry
    it too, at its own stored version. *"A subset would leave the omitted execution free
    to move between the comparison and the commit, which is the whole of the race."*

    **This is the arm that fails against an implementation passing the execution its own
    turn touched**, which is every naive reading of the field, and against one that
    reports a single version for the whole set: the two executions here stand at
    **different** versions, the driven one advanced by the walk and the second still at
    the zero ``start_execution`` opens it at.

    The second execution runs a plan with **no steps**, so the attempt is left in a state
    ADR-0262 §4's third ending condition still admits — every step of every execution it
    names terminal — and the arm keeps meaning the same thing once L3 makes the store
    enforce that.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened

    # A second execution of this goal, appended through `commit_attempt` — the route
    # ADR-0249 §12 makes the attempt's only one, so the store's own dangling-reference
    # and second-owner refusals both have to pass for this set-up to stand.
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
            attempt_id=held.id, expected_version=held.version, add_execution_id=second.id
        )
    )

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    complete = await _snapshot_of(plans, stored.id)
    assert len(complete) == 2, "the attempt names both, so the snapshot is over both"
    assert dict(complete)[second.id] == 0, "the second was never driven"
    assert dict(complete)[parked.step.state.id] > 0, "and the first was"
    ended = _ending(plans)
    assert ended.execution_versions == complete
    assert set(dict(ended.execution_versions)) == {parked.step.state.id, second.id}, (
        "a snapshot missing either id is a subset, which is the shape §4 refuses"
    )


# --------------------------------------------------------------------------- #
# Every other transition is untouched                                          #
# --------------------------------------------------------------------------- #


async def test_no_transition_but_the_ending_one_carries_a_snapshot() -> None:
    """§4: *"it is the ``→ ENDED`` limb **alone** that reads the field"*.

    Every other transition ignores it, ``→ CANCELLED`` included, *"and every caller this
    decision does not touch, a phase stamp, an effort counter, an append, writes exactly
    as it does today"*.

    **Asserted over the transitions written *after* the execution id reaches the row**,
    which is the only place the claim can be tested: a phase stamp made before the
    append is over an attempt naming nothing, so it would carry the empty tuple under
    any implementation at all. The parking turn writes the attempt again at ADR-0249
    §12's authorization boundary — after its ``add_execution_id`` — and that transition
    is over an attempt that **does** name an execution, so an implementation reading the
    versions on every transition rather than on the ending one is caught here.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)

    parked = await harness.engine.converse("send it", timeout=PATIENT)

    assert parked.step is not None
    assert parked.step.confirmation is not None, "the turn parked, so it ended no attempt"
    appended = next(
        index for index, move in enumerate(plans.moves) if move.add_execution_id is not None
    )
    after = plans.moves[appended + 1 :]
    assert after, "the parking turn writes the attempt again at the authorization boundary"
    (stored,) = plans.opened
    assert await _snapshot_of(plans, stored.id) != (), (
        "and by then the attempt names an execution, so an empty tuple is a choice"
    )
    assert all(move.to_state is not AttemptState.ENDED for move in after), "none of them ends it"
    assert all(move.execution_versions == () for move in after), (
        "a phase stamp, an append and a pause write exactly as they did before L1"
    )
