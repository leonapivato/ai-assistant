"""ADR-0251 at the loop: an attempt investigates in bounded rounds.

§16's L2 arms that are turn-shaped. Each drives the **real orchestration path** — the
production :class:`~ai_assistant.orchestration.loop.LearningLoop` over the real
:func:`~ai_assistant.orchestration.reads.service_read_request`, with an injected clock
and a scripted planner — because §17 is explicit that "no arm is discharged by a unit
test of a helper in isolation".

**The helpers are ``test_loop_reads``' and ``test_loop_revision``'s**, imported rather
than restated: this is the same loop over the same store shapes, one decision on, and a
second set of record builders would be a second statement of what a belief with
evidence looks like.

What lives elsewhere and is not restated here: §2's classifier and the seven members
reaching the planner (``test_read_outcomes``); the per-turn budget's own boundary and
ADR-0228 §7's monotonicity over a turn's rounds (``test_loop_revision``); ADR-0240 §6's
own shapes under the run test (``test_loop_structured``); and the engine-side stop and
its prompt (``test_engine_revision``).
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_loop_reads import (
    _belief,
    _both,
    _bounded,
    _clock,
    _episode,
    _hop,
    _ids,
    _Journal,
    _loop,
    _query,
    _record,
)
from test_loop_revision import _ASKED, _Elapsed, _Script, _system_prompt_over

from ai_assistant import orchestration
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    AttemptEffort,
    AttemptKind,
    AttemptPhase,
    AttemptState,
    Goal,
    GoalAttempt,
    GoalStatus,
    PlannerOutput,
)
from ai_assistant.orchestration.loop import (
    _ALLOWANCES,
    _UNPRODUCTIVE_RUN,
    ConversationalOperation,
    LearningLoop,
)
from ai_assistant.orchestration.reads import SearchDisposition, StopReason

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.orchestration.loop import RespondedTurn

#: ADR-0251 §5's declaration for ``CONVERSATIONAL``, read off the mapping the loop
#: actually enforces rather than restated — so a case that reads as "exactly at the
#: investigation share" cannot drift from the figure the gate compares against.
_DECLARED: Final = _ALLOWANCES[AttemptKind.CONVERSATIONAL]

#: §6's investigation share: the working allowance **less** the reserve.
_SHARE: Final = _DECLARED.investigation_share


async def _turn(  # noqa: PLR0913 — the store, the planner, the operation, the clock and the two things a turn may continue; every one is a fact a case varies on its own
    memory: _Journal,
    planner: _Script,
    *,
    operation: ConversationalOperation | None = ConversationalOperation.CONVERSE,
    now: Clock = _clock,
    goal: Any = None,
    attempt: GoalAttempt | None = None,
) -> RespondedTurn:
    """Run one turn of a budgeted, bounded-audience operation.

    Args:
        memory: The store the turn reads and the servicer hops through.
        planner: The scripted planner.
        operation: Which operation the turn runs under.
        now: The loop's injected clock.
        goal: The goal this turn continues, or ``None`` where it opens one.
        attempt: The attempt this turn continues (ADR-0251 §13), or ``None``.

    Returns:
        What the turn produced.
    """
    return await _loop(memory, planner=planner, now=now).respond(
        _ASKED,
        narrow=_bounded(),
        operation=operation,
        continuing=goal,
        continuing_attempt=attempt,
    )


def _goal(responded: RespondedTurn) -> Goal:
    """The goal record the loop built, narrowed for the same reason as :func:`_left`."""
    assert responded.goal is not None
    return responded.goal.goal


def _phases(responded: RespondedTurn) -> tuple[AttemptPhase, ...]:
    """Which phases this turn stamped, narrowed for the same reason as :func:`_left`."""
    assert responded.attempt is not None
    return responded.attempt.phases


def _left(responded: RespondedTurn) -> GoalAttempt:
    """The attempt as the loop left it, refusing the ``None`` no turn of this lane returns.

    ``RespondedTurn.attempt`` is optional because ADR-0249 §11's carrier is, but every
    turn that reaches a plan carries one; narrowing here keeps every arm below reading
    the ledger rather than re-stating that.
    """
    assert responded.attempt is not None
    return responded.attempt.attempt


def _carried(working: timedelta) -> GoalAttempt:
    """A non-terminal attempt an earlier turn left, with ``working`` already spent.

    **The working gate is the attempt's and the per-turn budget is the turn's** (§5),
    and this is what lets an arm drive one without the other: ADR-0228 §4's PT20S is
    measured from *this* turn's entry into the loop, so an arm that pushed one turn's
    clock to the investigation share would reach the per-turn guard first and read the
    wrong gate's figure. An attempt that arrives with most of its share already spent
    reaches §4(h) inside a turn that has run for a second — which is exactly the tail
    guard's own case, "an attempt whose rounds ran long or whose turns were many".
    """
    return GoalAttempt(
        id="attempt-1",
        goal_id="goal-1",
        opened_at=_clock(),
        phase=AttemptPhase.INVESTIGATE,
        effort=AttemptEffort(working=working, kind=AttemptKind.CONVERSATIONAL),
    )


async def _chain() -> _Journal:
    """A store whose retrieved belief starts a three-level citation chain.

    Each level cites the next and **no level cites more than one**, so a round can only
    reach level *n* by naming the record level *n-1* put in the supply — which is what
    makes the third ask one no earlier round could have composed (§17 arm 1).
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("level-1",)))
    await memory.add(_belief("level-1", "the agent is Marta", evidence=("level-2",)))
    await memory.add(_belief("level-2", "Marta's office is on Rua da Boavista", evidence=("l3",)))
    await memory.add(_episode("l3", "Ada: the office moved in March."))
    return memory


# --------------------------------------------------------------------------- #
# §17 arm 1: more than two rounds, choosing from discovered evidence           #
# --------------------------------------------------------------------------- #


async def test_a_third_round_asks_a_question_no_earlier_round_could_have_composed() -> None:
    """§17 arm 1, and the arm the whole decision exists for. **Fails on origin/main.**

    "An attempt whose round 1 read yields a record, whose round 2 asks a question
    composed from that record and yields another, and whose round 3 asks a third
    question composed from the second — four planner calls, three servicings planned
    over, and the third ask asserted to be one no earlier round could have composed."
    This is #2169's "A later investigation step depends on a fact discovered after the
    initial search and fetch", and ADR-0228 §3's bound of two makes it unreachable.

    **The labels are what make the claim checkable.** A label is an ordinal into the
    sequence passed on *that* call (ADR-0226 §3, ADR-0228 §8), so ``M3`` names nothing
    on round 1 — the supply has one record — and names level 2 only after round 2's
    servicing appended it. An implementation that followed evidence transitively rather
    than one level per servicing would reach level 3 without a third plan, and the
    per-call supplies below are where that shows.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1"), _hop("M2"), _hop("M3"), None])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    first, second, third, _settling = (supply for supply, _ in planner.calls)
    assert _ids(first) == ["belief-1"], "M3 named nothing here"
    assert _ids(second) == ["belief-1", "level-1"], "one level per servicing, and no more"
    assert _ids(third) == ["belief-1", "level-1", "level-2"], "M3 is round 2's own yield"
    assert _ids(responded.turn.memories) == ["belief-1", "level-1", "level-2", "l3"]
    assert len(planner.calls) == 4, "three servicings planned over, then the planner settled"
    record = _record(captured)
    assert len(record["servicings"]) == 3
    assert record["stop"] == StopReason.SETTLED.value, "the planner stopped asking"
    assert record["attempt_planner_calls"] == 4


# --------------------------------------------------------------------------- #
# §17 arm 7: sufficient-context restraint                                     #
# --------------------------------------------------------------------------- #


async def test_a_turn_needing_no_read_makes_exactly_one_planner_call() -> None:
    """§17 arm 7: "what is two plus two" still costs one planner call.

    #2170's "A sufficient-context task takes no unnecessary read", and §7 is explicit
    that this is **the absence of a mechanism rather than the presence of one**: the
    plan carries no ``read_request``, ADR-0228 §2(b) fails, and nothing about this
    decision is reached — no progress test runs, no gate is consulted and no clock is
    read for one.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question"))
    planner = _Script(requests=[None])
    elapsed = _Elapsed(timedelta(seconds=1))

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, now=elapsed)

    assert len(planner.calls) == 1
    record = _record(captured)
    assert record["servicings"] == (), "nothing was serviced"
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert responded.stopped_while_asking is False, "it stopped because it was done asking"
    assert elapsed.readings == 3, (
        "entry, the goal's own instant, and the ledger's reading as the turn ends — "
        "and no fourth, because no gate of §4 was reached to read one"
    )


# --------------------------------------------------------------------------- #
# §17 arms 8, 9, 10, 12: the progress fold and the unproductive run            #
# --------------------------------------------------------------------------- #


async def test_a_round_after_an_unproductive_one_is_admitted_and_the_run_resets() -> None:
    """§17 arm 8: #2169's "justified alternative", and the run count resetting.

    The first round's hop reaches a record the supply already holds, so it admits
    nothing and the round is unproductive; §4 admits the next round anyway, because
    (e) is dissolved and §3's carrier hands that round ``DUPLICATE`` rather than
    nothing. The second round asks a **different** source, admits a record, and the run
    resets — so the third round is admitted too, and the attempt answers rather than
    stopping at a guard.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("belief-2",)))
    # Carries the asked term, so the turn's own belief read retrieves it and the hop
    # reaches nothing the supply does not already hold.
    await memory.add(_belief("belief-2", "the lease was signed in March"))
    await memory.add(_belief("deposit-1", "the deposit was four hundred"))
    planner = _Script(requests=[_hop("M1"), _query("deposit"), None])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    record = _record(captured)
    assert [entry["new"] for entry in record["servicings"]] == [0, 1], "then the run reset"
    assert [entry["outcomes"] for entry in record["servicings"]] == [
        ("duplicate",),
        ("returned_records",),
    ], "§17 arm 12: a serviced duplicate is reported as one"
    assert len(planner.calls) == 3, "the round after the unproductive one was admitted"
    assert record["stop"] == StopReason.SETTLED.value, "and the attempt answered"
    assert "deposit-1" in _ids(responded.turn.memories)
    assert responded.stopped_while_asking is False


async def test_a_round_whose_every_ask_admitted_nothing_is_one_unproductive_round() -> None:
    """§17 arm 10: the fold is a single disjunction over the whole round.

    "A round whose request carried several asks — one admitting a record and one
    ``EMPTY`` — is **productive** and resets the run; a round whose every ask admitted
    nothing is **one** unproductive round and never two, however many asks it carried."

    Both halves are here on one turn. Round 1 carries a hop that admits a record beside
    a query that matches nothing: productive, and the run stays at zero. Rounds 2 and 3
    carry the same two asks over a supply that now holds everything either can reach:
    each is **one** unproductive round, so the turn stops after the second of them —
    at three calls, and not at two, which is where a per-ask count would have stopped
    it.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("level-1",)))
    await memory.add(_belief("level-1", "the agent is Marta"))
    planner = _Script(requests=[_both("nothing-matches-this-term", "M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    record = _record(captured)
    assert [entry["new"] for entry in record["servicings"]] == [1, 0, 0]
    assert len(planner.calls) == 3, "one productive round, then two unproductive ones"
    assert record["stop"] == StopReason.UNPRODUCTIVE.value
    assert responded.stopped_while_asking is True, "§7 widens ADR-0228 §10's trigger"
    assert "stopped before you could" in await _system_prompt_over(responded)


async def test_the_run_stops_the_turn_before_the_allowance_is_reached() -> None:
    """§17 arm 9: #2170's "stops before blindly exhausting the maximum".

    "Two consecutive rounds admitting no record stop with ``UNPRODUCTIVE`` **before**
    the planner-call allowance is reached, and the planner is asserted **not** to have
    been called a third time." The figure is stated rather than hoped for: two is the
    smallest increment that changes anything, because under ADR-0228 §2(e) it was
    effectively one.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("belief-2",)))
    await memory.add(_belief("belief-2", "the lease was signed in March"))
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner)

    record = _record(captured)
    assert len(planner.calls) == _UNPRODUCTIVE_RUN, "and never a third"
    assert record["stop"] == StopReason.UNPRODUCTIVE.value
    assert record["attempt_planner_calls"] < record["attempt_allowance"]


# --------------------------------------------------------------------------- #
# §17 arms 13, 14, 15: the working allowance, the reserve, and both gates      #
# --------------------------------------------------------------------------- #


async def test_exhausting_the_investigation_share_leaves_a_composing_call_to_make() -> None:
    """§17 arm 13: a useful partial answer at exhaustion, with §6's honest bound.

    "An attempt that spends its whole investigation share composes an answer over the
    supply it gathered, with ``AttemptEffort.working`` asserted to be at or past the
    investigation share at the moment composing is entered."

    **This is #2255's requirement as a mechanism and never an instruction to a model**
    (§6): no prompt, no rendered line and no ``Settings`` value asks for a partial
    answer. What the reserve buys is that an attempt which spent its whole
    investigation share **stops investigating with a composing call still to make** —
    the composing stage is gated on nothing — and ADR-0228 §10's fact, which §7 widens
    to this stop, is what gives that call something true to say.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, now=_Elapsed(_SHARE))

    assert len(planner.calls) == 1, "the share was spent before the second call"
    assert _record(captured)["stop"] == StopReason.WORKING_ALLOWANCE_REACHED.value
    assert _left(responded).effort.working >= _SHARE, "at or past the share"
    assert _ids(responded.turn.memories) == ["belief-1", "level-1"], "over what it gathered"
    assert responded.stopped_while_asking is True
    assert "stopped before you could" in await _system_prompt_over(responded)


async def test_a_round_admitted_below_the_share_is_not_cancelled_and_composing_runs() -> None:
    """§17 arm 13's second arm: the margin's honest bound, and what §6 does not claim.

    "A round admitted at one tick below the investigation share whose planner call
    outlasts the reserve is **not** cancelled, composing **still runs**, and the test
    asserts that **that check** admitted one round and no more — and asserts **no**
    upper bound on ``working``, because §6 claims none."

    §4(h) is a gate on **starting** a round and never a cancellation of one in flight,
    which is ADR-0228 §4's posture kept in its own words. So the guarantee is over one
    gate check: without the reserve that check would have admitted a round up to the
    whole allowance and overrun from there.
    """
    memory = await _chain()
    overrun = _Elapsed(timedelta(seconds=1))

    def _overruns(ordinal: int) -> None:
        """Push the clock past the whole working allowance **during** the second call."""
        if ordinal == 2:
            overrun.elapsed = _DECLARED.working + timedelta(minutes=1)

    planner = _Script(requests=[_hop("M1"), _hop("M2")], on_call=_overruns)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(
            memory, planner, now=overrun, attempt=_carried(_SHARE - timedelta(seconds=2))
        )

    assert len(planner.calls) == 2, "that check admitted one round and no more"
    assert _record(captured)["stop"] == StopReason.WORKING_ALLOWANCE_REACHED.value
    assert _left(responded).effort.working > _DECLARED.working, (
        "§6 claims no upper bound on working, and the overrunning round was not cancelled"
    )
    assert responded.turn.plan is responded.plans[-1], "the overrunning call's plan stands"
    assert await _system_prompt_over(responded), "and composing ran"


@pytest.mark.parametrize(
    ("carried", "calls", "stop"),
    [
        (_SHARE - timedelta(seconds=1), 1, StopReason.WORKING_ALLOWANCE_REACHED),
        (_SHARE - timedelta(seconds=3), 2, StopReason.SETTLED),
    ],
    ids=["exactly-at-the-share", "one-tick-below-it"],
)
async def test_the_investigation_shares_boundary_instant_is_spent_not_available(
    carried: timedelta, calls: int, stop: StopReason
) -> None:
    """§17 arm 14: ADR-0228 §4's own arm, one level up.

    "With the injected clock set to exactly the investigation share, no further round
    is admitted and the stop is ``WORKING_ALLOWANCE_REACHED``; at one tick less, one
    is." §4(h) closes the boundary in the implementation for ADR-0228 §4's own reason:
    leaving equality open would let two conforming loops differ on identical input, and
    "an injected clock makes equality an ordinary case in a test rather than a
    measure-zero curiosity".

    **The clock is this turn's and the figure is the attempt's**, which is why each arm
    arrives carrying a ledger rather than pushing one turn's clock: the turn runs for a
    second either way, and what separates the two arms is whether that second takes
    ``AttemptEffort.working`` **to** the share or leaves it one second short.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1"), None])

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner, now=_Elapsed(timedelta(seconds=1)), attempt=_carried(carried))

    assert len(planner.calls) == calls
    assert _record(captured)["stop"] == stop.value


async def test_the_per_turn_budget_binds_while_the_attempt_is_well_inside_its_allowance() -> None:
    """§17 arm 15's first half: both gates bind, and this one is ADR-0228 §4's.

    "An attempt inside its allowance whose turn has spent ADR-0228 §4's PT20S stops
    with ``BUDGET_REACHED``." §5 keeps that gate **entire and not re-keyed**, because
    it measures *one user's wait* where the attempt's working allowance measures *one
    attempt's consumption* — two quantities with two jobs, and the honest reading is
    that both are kept, each where its argument holds. The arm's second half is
    ``test_loop_revision``'s allowance case.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner, now=_Elapsed(timedelta(seconds=25)))

    record = _record(captured)
    assert len(planner.calls) == 1
    assert record["stop"] == StopReason.BUDGET_REACHED.value
    assert record["attempt_planner_calls"] < record["attempt_allowance"], "well inside it"


# --------------------------------------------------------------------------- #
# §17 arms 16, 18, 20, 6a: the ledger across turns, and the phase              #
# --------------------------------------------------------------------------- #


async def test_a_second_turn_of_one_attempt_starts_from_the_ledger_the_first_left() -> None:
    """§17 arm 16's first half, and §13's re-entry rule.

    "An attempt's second turn is asserted to start from the ``planner_calls`` and
    ``working`` the first turn left." ADR-0251 §13: a turn that engages a goal whose
    attempt is non-terminal **continues** that attempt, "with its consumed figures as
    they stand and its ``kind`` as stamped", and ADR-0249 §5's monotonicity binds
    entire — no replan, branch, recovery or phase transition resets either.
    """
    memory = await _chain()
    first = await _turn(memory, _Script(requests=[_hop("M1"), None]))
    assert _left(first).effort.planner_calls == 2

    second = await _turn(
        memory,
        _Script(requests=[None]),
        goal=_goal(first),
        attempt=_left(first),
    )

    assert _left(second).id == _left(first).id, "ADR-0250 §12: none opened"
    assert _left(second).effort.planner_calls == 3, "two, and this turn's one"
    assert _left(second).effort.working >= _left(first).effort.working
    assert _left(second).plan_ids[: len(_left(first).plan_ids)] == (_left(first).plan_ids), (
        "§12's tuples grow by append and never by replacement"
    )


async def test_a_turn_on_a_spent_allowance_still_plans_once_and_the_ledger_advances() -> None:
    """§17 arm 16's second half: the ungated first call, and no reset.

    "A turn on an attempt whose allowance is **already spent**: it makes **exactly
    one** planner call, iterates no further, records the stop, and the ledger is
    asserted to advance by exactly one rather than to reset."

    §4 is explicit that no gate here takes a user's turn away from them — "every turn
    the owner starts makes its first planner call whatever the attempt's ledger holds"
    — which is the standing rule of 2026-09-12 binding in terms, and which is why the
    attempt's total is bounded by how many times the owner asks rather than by a
    figure this decision sets.
    """
    memory = await _chain()
    spent = GoalAttempt(
        id="attempt-1",
        goal_id="goal-1",
        opened_at=_clock(),
        phase=AttemptPhase.INVESTIGATE,
        effort=AttemptEffort(
            planner_calls=_DECLARED.planner_calls,
            working=_DECLARED.working,
            kind=AttemptKind.CONVERSATIONAL,
        ),
    )
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, attempt=spent)

    assert len(planner.calls) == 1, "one call, and no iteration"
    assert _record(captured)["stop"] == StopReason.BOUND_REACHED.value
    ledger = _left(responded).effort
    assert ledger.planner_calls == _DECLARED.planner_calls + 1, "advanced by one, not reset"
    assert ledger.working >= _DECLARED.working, "and never subtracted from"


async def test_exhausting_an_allowance_opens_no_attempt_and_leaves_the_goal_active() -> None:
    """§17 arm 18: the system opens no attempt to buy budget. §9's clause, asserted.

    "An attempt that exhausts its allowance is asserted to leave ``GoalAttempt`` count
    unchanged and the goal ``ACTIVE``, with no second attempt row written by anything
    but one of ADR-0250 §12's three acts." §10 is what makes this structural rather
    than remembered: "**The investigation loop opens no attempt.** No round, no
    revision, no recorded understanding, no stop, no exhaustion of any counter, no
    unproductive run and no resumption of a stopped investigation opens one" — because
    "an attempt boundary the loop could mint is an allowance the loop could refresh".

    And §9's own clause is the other half: **exhaustion is never a blocker.** An
    attempt that spent its allowance "stops investigating and leaves the goal
    ``ACTIVE``", so the objective is still achievable and nothing in the system is
    entitled to say otherwise.
    """
    memory = await _chain()
    spent = GoalAttempt(
        id="attempt-1",
        goal_id="goal-1",
        opened_at=_clock(),
        phase=AttemptPhase.INVESTIGATE,
        effort=AttemptEffort(
            planner_calls=_DECLARED.planner_calls,
            working=_DECLARED.working,
            kind=AttemptKind.CONVERSATIONAL,
        ),
    )

    responded = await _turn(memory, _Script(requests=[_hop("M1")]), attempt=spent)

    assert _left(responded).id == "attempt-1", "the same attempt, and no second"
    assert _left(responded).state is AttemptState.RUNNING
    assert _goal(responded).status is GoalStatus.ACTIVE, "§9: exhaustion is never a blocker"


@pytest.mark.parametrize(
    ("opened_under", "later"),
    [
        (ConversationalOperation.CONVERSE, ConversationalOperation.CONVERSE_SPOKEN),
        (ConversationalOperation.CONVERSE_SPOKEN, ConversationalOperation.CONVERSE),
    ],
    ids=["typed-then-spoken", "spoken-then-typed"],
)
async def test_the_kind_is_stamped_at_the_open_and_never_taken_from_a_later_turn(
    opened_under: ConversationalOperation, later: ConversationalOperation
) -> None:
    """§17 arm 20: the kind is stamped once, and the reverse holds too.

    "An attempt opened under ``CONVERSE`` and engaged on a later turn under
    ``CONVERSE_SPOKEN`` keeps ``CONVERSATIONAL``, and the reverse." §5 is explicit
    about why: an attempt whose allowance followed the current turn's operation "would
    have a budget the user could change by speaking" — a goal opened in a browser and
    followed up by voice would have its allowance silently halved mid-attempt, or a
    spoken attempt would acquire one by being typed at, "and in neither case did
    anybody decide anything".
    """
    memory = await _chain()
    first = await _turn(memory, _Script(requests=[None]), operation=opened_under)
    stamped = _left(first).effort.kind

    second = await _turn(
        memory,
        _Script(requests=[None]),
        operation=later,
        goal=_goal(first),
        attempt=_left(first),
    )

    assert _left(second).effort.kind is stamped, "never re-stamped from a later turn"


async def test_an_attempt_past_investigate_makes_its_one_call_and_does_not_iterate() -> None:
    """§17 arm 6a: §4(j), and the phase that does not move backwards.

    "A later owner turn on a non-terminal attempt paused in ``AUTHORIZE`` makes its one
    planner call, is asserted **not** to service a further round however productive the
    first read was and however much allowance remains, the attempt's phase is asserted
    unchanged — never moved back to ``INVESTIGATE`` — and the turn is asserted to
    record ``NOT_ITERATED`` and to set **no** composing flag."

    §1 places every round inside **one** occupancy of ``INVESTIGATE`` and creates no
    re-entry from a later phase, so iterating here would either run the loop in a phase
    §1 does not place it in or move the phase backwards, which ADR-0249 §6 forbids.
    ``NOT_ITERATED`` rather than a guard's member is §4(j)'s own clause: ADR-0228 §10's
    carrier "is reserved for a turn that stopped at a **guard** while still asking".
    """
    memory = await _chain()
    paused = GoalAttempt(
        id="attempt-1",
        goal_id="goal-1",
        opened_at=_clock(),
        phase=AttemptPhase.AUTHORIZE,
        effort=AttemptEffort(kind=AttemptKind.CONVERSATIONAL),
    )
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, attempt=paused)

    record = _record(captured)
    assert len(planner.calls) == 1, "one call, however productive the read was"
    assert record["servicings"][0]["new"] == 1, "and it was productive"
    assert record["attempt_planner_calls"] < record["attempt_allowance"], "allowance remained"
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert responded.stopped_while_asking is False, "§4(j) sets no composing flag"
    assert _left(responded).phase is AttemptPhase.AUTHORIZE, "never moved backwards"
    assert _phases(responded) == (), "and no transition was stamped"


# --------------------------------------------------------------------------- #
# §17 arm 19: an unpriced kind does not iterate                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("operation", "kind"),
    [
        (ConversationalOperation.CONVERSE_SPOKEN, AttemptKind.SPOKEN),
        (None, None),
    ],
    ids=["spoken", "no-operation"],
)
async def test_an_attempt_kind_that_declares_no_allowance_does_not_iterate(
    operation: ConversationalOperation | None, kind: AttemptKind | None
) -> None:
    """§17 arm 19: the fail-closed arm, and the one a member added tomorrow inherits.

    "An ``AttemptEffort`` whose ``kind`` is ``SPOKEN``, and one whose ``kind`` is
    ``None``, each make exactly one planner call per turn." §5: "**An attempt kind that
    declares no allowance does not iterate**, whatever its audience, and its attempt
    makes exactly one planner call per turn exactly as the tree does today for an
    operation absent from ``_PLANNING_BUDGETS``."

    **Membership is the declaration**, so ``SPOKEN``'s absence from the mapping is
    itself a decision and every future member's absence is an accident — and both fail
    closed, which is ADR-0228 §2(a)'s rule one level up: no implementation reads an
    absent declaration as a default, as unknown-and-therefore-permitted, or as a case
    to decide at run time.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, operation=operation)

    record = _record(captured)
    assert len(planner.calls) == 1
    assert _left(responded).effort.kind is kind, "stamped from the opening operation"
    assert record["attempt_kind"] == (None if kind is None else kind.value)
    assert record["attempt_allowance"] is None, "no figure was in force"
    assert record["stop"] == StopReason.NOT_ITERATED.value


# --------------------------------------------------------------------------- #
# §9 and §11: what this decision writes, and what nothing here advances        #
# --------------------------------------------------------------------------- #


def test_nothing_in_this_lane_writes_a_goal_status() -> None:
    """§17 arm 21, and §9's whole outcome: ``BLOCKED`` gains no producer here.

    §9 fixes the act, the writer, the write path and a three-limb test, and names **no**
    reason that passes it — because limb 3, necessity to the objective, "is a property
    of the goal's ``conditions`` and ``criteria`` that no clause here evaluates". The
    nearest candidate is named and refused in the ADR itself: a ``WEB_SEARCH``
    answering ``NOT_CONFIGURED`` on a turn whose reads admitted nothing passes limbs 1
    and 2 and **fails limb 3**, because "a request to summarise a note already in the
    assembled supply meets exactly that shape, and answers perfectly well".

    So the lane ships the prohibition rather than a call, and "``set_goal_status`` is
    asserted not to be called with ``BLOCKED`` anywhere in this decision's lanes" is an
    **absence over the package** — the only shape such a claim can take. ADR-0250 §9
    ratifies that member and its implementation has not landed, so there is no writer
    to call either.
    """
    package = Path(orchestration.__file__).parent
    naming = sorted(
        path.name
        for path in package.rglob("*.py")
        if "set_goal_status" in path.read_text(encoding="utf-8")
        or "GoalStatus.BLOCKED" in path.read_text(encoding="utf-8")
    )

    assert naming == [], f"§9 names no reason that passes its three-limb test (found in {naming})"


def test_no_planner_envelope_carries_a_value_this_decision_mints() -> None:
    """§17 arm 22, and §12's writer clauses read as a property of the types.

    "**Every value this decision mints is ``orchestration``'s, derived from typed
    values, and no model output sets any of them**" — each round's outcome and the
    model carrying it, the stop reason, ``AttemptEffort``'s three members, the goal's
    ``BLOCKED`` stamp, the attempt's state, and the fact told to composing.

    A planner envelope carrying one has it "discarded silently — not an error, not a
    park, not a degradation of the turn", and the sharpest reason is the read outcome:
    "a planner that could declare its own last read ``RETURNED_RECORDS`` could keep the
    loop running past every progress test this decision has". Asserted here as the
    stronger fact, which is the one the tree actually gives: the envelope has **no
    field any of them could arrive on**, so the discard is structural rather than a
    rule a loop is trusted to keep — the same move ADR-0230 §4 makes for ``ShownFile``.
    """
    minted = {
        "outcome",
        "read_outcome",
        "stop",
        "stop_reason",
        "effort",
        "planner_calls",
        "working",
        "kind",
        "status",
        "state",
        "attempt",
        "stopped_while_asking",
    }

    assert not minted & set(PlannerOutput.model_fields)
    assert not minted & set(ActionPlan.model_fields)


def test_no_per_conversation_bound_on_searching_returns_in_any_form() -> None:
    """§17 arm 23's second half, and §11(c) read where it would show.

    "**Therefore no per-conversation bound on searching is reintroduced, in any
    form.**" ADR-0247 §5's per-conversation clause binds **verbatim** — "Per
    conversation: nothing bounds the number of searches, and that is the decision
    rather than an omission" — so ``SearchDisposition`` regains no ``NOT_ADMITTED``
    and no per-conversation quantity of any kind is substituted.

    This is the half of §11 that is checkable as an absence in this package. What §11(a)
    claims is that no attempt advances without an owner act, and the shape that takes
    here is that this loop exposes exactly one entry point a turn can arrive on and
    nothing schedules it: :meth:`LearningLoop.respond` is called by the engine on a
    turn the caller started, and ``resumed_read`` is an answer the user gave.
    """
    assert "NOT_ADMITTED" not in {member.name for member in SearchDisposition}
    source = inspect.getsource(LearningLoop)
    for scheduled in ("create_task", "call_later", "sleep(", "cron", "schedule"):
        assert scheduled not in source, f"nothing here advances an attempt on a {scheduled}"


# --------------------------------------------------------------------------- #
# §17 arm 24: the audit says what the loop spent                               #
# --------------------------------------------------------------------------- #


async def test_the_audit_carries_the_ledger_and_the_outcomes_and_copies_nothing() -> None:
    """§17 arm 24: one record per turn, and the stop distribution's companion.

    "One record per turn, emitted once and conditioned on nothing, carrying the
    per-servicing ``ReadOutcomeKind`` sequence, the attempt's kind, its consumed
    planner calls and its declared allowance — and asserted to carry **no** query, no
    label, no ask, no excerpt and no identifier but the ambient correlation id."

    ADR-0226 §9's counts-and-kinds rule binds the extension **entire**, and the
    additions are three counts-or-classes and a tuple of members: there is nowhere in
    any of them for a value this system did not mint to sit.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: quinoa-flavoured stroopwafel."))
    await memory.add(_belief("second-1", "marmalade zeppelin bookkeeping"))
    planner = _Script(requests=[_hop("M1"), _query("marmalade zeppelin"), None])

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    record = _record(captured)
    assert record["attempt_kind"] == AttemptKind.CONVERSATIONAL.value
    assert record["attempt_planner_calls"] == 3
    assert record["attempt_allowance"] == _DECLARED.planner_calls
    assert [entry["outcomes"] for entry in record["servicings"]] == [
        ("returned_records",),
        ("returned_records",),
    ]
    rendered = repr(record)
    assert "marmalade" not in rendered, "neither round's query is copied"
    assert "stroopwafel" not in rendered, "no returned record's content is copied"
    assert "M1" not in rendered, "no label either round named is copied"
    for plan in responded.plans:
        assert plan.id not in rendered, "no plan identifier"


def test_the_stop_distribution_is_readable_over_all_seven_members() -> None:
    """§17 arm 24's second arm: the instrument §14 fires the revision of §5's figures off.

    "A second arm asserts the stop distribution is readable over all seven members."
    §7 makes that distribution "the instrument that revises §5's figures", and what it
    needs is that every member of the vocabulary is a value the one field can take —
    which is a property of the enumeration being closed and of the record carrying the
    member rather than a rendering of it. ADR-0226 §8's prohibition on reporting
    precision or recall from this record alone binds it.
    """
    assert len({member.value for member in StopReason}) == 7, "seven distinct values"
    for member in StopReason:
        assert member.value == member.name.lower(), "valued by lower-cased name"


# --------------------------------------------------------------------------- #
# §17 arm 17: the charge precedes the call, and §12's two cases stay apart      #
# --------------------------------------------------------------------------- #


async def test_a_planner_call_that_raises_is_charged_to_the_attempt_all_the_same() -> None:
    """§17 arm 17(a): a call that raises leaves the ledger advanced.

    §12: ``AttemptEffort.planner_calls`` "is incremented once per ``Planner.plan``
    call, immediately *before* the call and after the capability vocabulary is read,
    and it is counted **whether or not the call returns**. A call that raises, that is
    cancelled, or that the turn does not survive is a call the attempt made and a call
    its allowance paid for; a ledger advanced on return would let a recovery re-invoke
    a planner past an allowance already spent."

    **Every error this admits runs in the same direction**, which is the property worth
    naming: a charge can stand for a call that never ran, and a call can never run
    uncharged. Asserted on the record the turn emits on its way out — ADR-0226 §9's
    ``finally`` writes one on *every* exit, the raising one included — because that is
    where the attempt's figure is observable on a turn that produced no carrier.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1")], raises=1)

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(PlanningError, match="the planner is down"),
    ):
        await _turn(memory, planner, attempt=_carried(timedelta(0)))

    record = _record(captured)
    assert len(planner.calls) == 2, "the second call was entered and raised"
    assert record["attempt_planner_calls"] == 2, "charged before the call, not on return"
    assert record["stop"] == StopReason.PLANNING_FAILED.value


async def test_a_turn_that_dies_carries_no_attempt_out_of_the_loop_to_persist() -> None:
    """§17 arm 17(b), at this seam: a turn that dies leaves no attempt to write.

    §12's **first** case: on an attempt this turn opened, "the charge is on the
    in-memory attempt… and it reaches the store with everything else the turn produced.
    **A turn that dies before that site charges nothing**, exactly as it records no goal
    and no plan." ADR-0249 §11's site is ``Engine``'s and is reached with the carrier
    this loop returns, so what makes that true here is that a raising turn returns
    **nothing at all** — there is no second path out of this method carrying an attempt,
    and ADR-0228 §5 forbids minting one ("no lane… carries a plan out of a failing turn
    in order to write it").

    **§12's *second* case — an attempt an earlier turn persisted — is not reached from
    this lane**, and that is recorded rather than left to be discovered. Its charge is
    an ``AttemptTransition`` through ``commit_attempt``, which only a holder of a
    ``PlanStore`` can issue, and ADR-0249 §11 rules that "**No lane gives
    ``LearningLoop`` a ``PlanStore``**" while ADR-0251 §12 itself "adds no persistence
    site, moves none, and supersedes no clause of §11 or §12". No caller supplies a
    persisted attempt today either: which attempt a turn continues is A2's.
    """
    memory = await _chain()
    planner = _Script(requests=[_hop("M1")], raises=0)

    with pytest.raises(PlanningError, match="the planner is down"):
        await _turn(memory, planner)

    assert len(planner.calls) == 1, "and the turn produced no carrier to persist"
