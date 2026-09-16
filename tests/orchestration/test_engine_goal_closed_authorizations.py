"""ADR-0268's act-level arms: the ending at the abandon, and the reopen's pair.

§9's arms **4, 5, 6**, arm **7**'s act half and arm **10**'s reopen half. Each is a
fact about an *act* — which store call it takes, in what order, with which instant
and which version, and what each half of a two-write sequence failing leaves — so
each is driven through the production engine over a real ``PlanStore`` and a real
``GoalAuthorizationStore``. Arms 1, 2, 3, 8 and 9 are the store's own surface and
are ``tests/permissions/goal_authorization_contract.py``'s; arm 10's *database*
half is about bytes on disk and is the durable store's.

**Two limbs of arm 4 have no tree to run against, and that is recorded rather than
skipped.** Arm 4 states the act's answer is *"``ABANDONED`` or
``ABANDONED_EFFECT_IN_FLIGHT`` exactly as ADR-0261 §6 fixes it"* and that *"a
``StaleExecutionError`` retry calls ``end_for_goal`` **once per attempt it
makes**"*. ``AssistantEngine._abandon_goal`` takes **neither** on this tree: it
discards the ``bool`` ``close_goal_abandoned`` answers and takes no retry, both
booked to ADR-0261 L2 by that decision's §13 and recorded on #2435. ADR-0268 §9
anticipates exactly this — *"the lane above wires ``end_for_goal`` on the
``ABANDONED`` close alone, that being the one closing write that exists"* — so what
is asserted here is the act as it is, the per-attempt structure the retry will wrap
is pinned, and the two limbs are filed against that lane (#2452).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import _associating, _goal, _seed

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    AssociationVerdict,
    AuthorizationDisposition,
    EngagementDisposition,
    GoalAbandonment,
    GoalStatus,
    Ground,
    TurnReference,
)
from ai_assistant.testing import (
    AUTHORIZATION_TOOL,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    opening_act,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import Authorization, Goal

#: The declarations a goal's two rows are established about. ADR-0268 §1's *"the
#: ending is stated over the set and never over one row"* needs two, because *"an
#: act that ended one would leave the other standing under a closed goal"*.
_FIRST: Final = "tool_one"
_SECOND: Final = "tool_two"

#: Far enough past :data:`AT` that nothing in these cases lapses on its own.
_EXPIRES: Final = AT + timedelta(days=30)


def _row(goal_id: str, tool_id: str, *, row_id: str) -> Authorization:
    """A path-(iii) opening act of ``goal_id`` through ``tool_id``, standing live."""
    return opening_act(
        id=row_id,
        goal=goal_id,
        tool=AUTHORIZATION_TOOL.model_copy(update={"id": tool_id}),
        proposed_at=AT,
        expires_at=_EXPIRES,
    )


async def _goal_with_two_rows(
    harness: Harness, store: FakeGoalAuthorizationStore, *, conversation: str
) -> Goal:
    """An open goal of ``harness`` holding two established authorizations."""
    goal = await _seed(
        harness.plans,
        _goal("goal-campsite", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await store.record(_row(goal.id, _FIRST, row_id="a1"))
    await store.record(_row(goal.id, _SECOND, row_id="a2"))
    return goal


def _dispositions(
    rows: tuple[Authorization, ...],
) -> dict[str, tuple[AuthorizationDisposition, datetime | None]]:
    """Each row's disposition and its instant, keyed by id."""
    return {row.id: (row.disposition, row.settled_at) for row in rows}


# --------------------------------------------------------------------------- #
# Arm 4: the closing act, in order                                            #
# --------------------------------------------------------------------------- #


class _Journal:
    """What each act called, in order, with the arguments ADR-0268 §1 keys on.

    **Arms 4, 5 and 7 all assert over the call sequence and the call count**, not
    only over the stored state: *"the order is asserted directly"*, *"``clear_closure``
    is called **not at all** — asserted over the call count"*, and *"asserted over the
    call count of ``close_goal_abandoned`` and ``set_goal_status``"*. A store left
    holding a fenced goal looks the same whether nothing cleared it or something
    cleared another goal's, and a closed goal with ended rows looks the same whichever
    write landed first — so the sequence is recorded as it happens.

    **Installed onto the shipping fakes rather than subclassed**, because both are
    ``@final``: the instance's bound methods are wrapped, which is
    ``tests/permissions/test_goal_authorizations.py``'s own lever one subsystem over
    and keeps the subject under test the real canonical fake.
    """

    def __init__(self) -> None:
        """An empty journal with no fault armed."""
        self.calls: list[str] = []
        self.endings: list[tuple[str, datetime, int]] = []
        self.clears: list[tuple[str, int]] = []
        #: Armed by the case that needs ADR-0268 §9 arm 7's *"closing write raising
        #: after a successful ending"*. ``FakePlanStore`` carries no fault hook of
        #: its own, and putting one on the shipping fake for a single arm would add a
        #: knob to every consumer's double.
        self.closing_fault: Exception | None = None

    def install(self, store: FakeGoalAuthorizationStore, plans: FakePlanStore) -> None:
        """Wrap the three calls these arms are stated over."""
        end_for_goal = store.end_for_goal
        clear_closure = store.clear_closure
        closing_write = plans.close_goal_abandoned

        async def ending(goal: str, /, *, at: datetime, goal_version: int) -> int:
            self.calls.append("end_for_goal")
            self.endings.append((goal, at, goal_version))
            return await end_for_goal(goal, at=at, goal_version=goal_version)

        async def clearing(goal: str, /, *, goal_version: int) -> bool:
            self.calls.append("clear_closure")
            self.clears.append((goal, goal_version))
            return await clear_closure(goal, goal_version=goal_version)

        async def closing(goal_id: str, /, **fields: Any) -> bool:
            # **Appended before the fault**, because arm 7 asserts the order on this
            # path too: the ending ran, and then the closing write was attempted.
            self.calls.append("close_goal_abandoned")
            if self.closing_fault is not None:
                raise self.closing_fault
            return await closing_write(goal_id, **fields)

        setattr(store, "end_for_goal", ending)  # noqa: B010 — an instance lever, not an attribute
        setattr(store, "clear_closure", clearing)  # noqa: B010
        setattr(plans, "close_goal_abandoned", closing)  # noqa: B010

    def reset(self) -> None:
        """Forget what has been recorded, leaving any armed fault alone."""
        self.calls.clear()
        self.endings.clear()
        self.clears.clear()


def _journalled() -> tuple[Harness, FakeGoalAuthorizationStore, _Journal, str]:
    """A harness whose two stores share one journal, and a fresh conversation id."""
    journal = _Journal()
    # **The store's clock is the harness's own.** Liveness is the store's one clock
    # read, and a row proposed at the harness's instant would be neither live nor
    # lapsed against the testing module's default — which would make arm 6's
    # *"``live_for`` answered something before the ending"* precondition vacuous.
    store = FakeGoalAuthorizationStore(now=lambda: AT)
    plans = FakePlanStore(now=lambda: AT)
    journal.install(store, plans)
    harness = Harness(
        planner=NoStepPlanner(),
        plans=plans,
        authorizations=store,
        episode_retention=timedelta(days=30),
        associator=_associating(AssociationVerdict.CONTINUES),
    )
    return harness, store, journal, "conversation-1"


async def test_abandoning_ends_both_rows_and_then_closes_the_goal() -> None:
    """Arm 4's first limb: *"ends both and **then** closes the goal"*.

    **The order is asserted directly**, because the end state cannot tell the two
    orders apart: a goal closed with its rows ended looks identical whichever write
    landed first, and the order is the whole of what makes the ending total rather
    than raceable by an establishment.

    **The ending is over the set and never over one row**: a goal whose plan reached
    two declarations holds two rows under ADR-0254 §1's per-declaration uniqueness,
    and an act that ended one would leave the other standing under a closed goal.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED

    assert journal.calls == ["end_for_goal", "close_goal_abandoned"]
    assert _dispositions(await store.export()) == {
        "a1": (AuthorizationDisposition.GOAL_CLOSED, AT),
        "a2": (AuthorizationDisposition.GOAL_CLOSED, AT),
    }
    held = await harness.plans.get_goal(goal.id)
    assert held is not None
    assert held.status is GoalStatus.ABANDONED
    assert await store.standing(goal.id) == ()


async def test_the_ending_carries_the_version_the_closing_write_expects() -> None:
    """ADR-0268 §1: *"the one its own status write **expects**, never the one that
    write returns"*.

    ``close_goal_abandoned`` advances ``Goal.version``, so the act holds two versions
    and **the record is keyed to the earlier**. A lane passing the returned version
    would key the record above the goal's own read, and a later reopen carrying *its*
    ``ACTIVE`` write's expectation could then find a record standing above it and
    unfence nothing.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    before = (await harness.plans.get_goal(goal.id)).version  # type: ignore[union-attr]

    await harness.engine.abandon_goal(goal.id)

    after = (await harness.plans.get_goal(goal.id)).version  # type: ignore[union-attr]
    assert after > before, "the closing write advances it, which is what makes this a test"
    assert journal.endings == [(goal.id, AT, before)]


async def test_the_ending_and_the_closing_write_share_one_clock_reading() -> None:
    """ADR-0268 §1: *"that instant is the act's own, read **once**"*.

    A ``GOAL_CLOSED`` row's ``settled_at`` is the instant of the **act** that ended
    it and never a second reading taken between the two writes, so the rows and the
    goal's own closing instant agree.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    await harness.engine.abandon_goal(goal.id)

    (_, at, _version) = journal.endings[0]
    assert {row.settled_at for row in await store.export()} == {at}, (
        "every row the act ended carries the act's own instant"
    )


@pytest.mark.parametrize(
    ("goal_id", "expected"),
    [
        ("goal-campsite", GoalAbandonment.ALREADY_CLOSED),
        ("no-such-goal", GoalAbandonment.NO_SUCH_GOAL),
    ],
)
async def test_an_act_answering_from_its_first_read_ends_nothing_and_fences_nothing(
    goal_id: str, expected: GoalAbandonment
) -> None:
    """Arm 4: *"an act answering ``NO_SUCH_GOAL`` or ``ALREADY_CLOSED`` from its first
    read ends **nothing** and fences **nothing**"*.

    **An attempt that is never made takes no ending** — the ending is taken *once per
    closing-write attempt*, so an act that makes none calls the member not at all.
    The fence's absence is asserted the only way the store's surface allows: a
    ``record`` for that goal afterwards succeeds.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    if goal_id == goal.id:
        # Close it first, so the second act answers from its own first read.
        await harness.engine.abandon_goal(goal.id)
        journal.reset()

    assert await harness.engine.abandon_goal(goal_id) is expected

    assert journal.calls == []
    assert journal.endings == []
    assert journal.clears == []
    assert await store.record(_row("goal-fresh", _FIRST, row_id="fresh")) == "fresh"


async def test_the_abandon_path_clears_no_fence() -> None:
    """Arm 4: *"``clear_closure`` is called **not at all**"* on either path.

    **Asserted over the call count**, because a store whose fence stands looks the
    same whether nothing cleared it or something cleared a *different* goal's. ADR-0268
    §1 gives that member exactly one caller — §2's reopen — and refuses the obvious
    compensation with its reasons: a ``clear_closure`` on a failed closing write cannot
    tell its own orphaned fence from one a concurrent act is relying on.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    await harness.engine.abandon_goal(goal.id)
    await harness.engine.abandon_goal(goal.id)

    assert journal.clears == []
    with pytest.raises(AuthorizationError):
        await store.record(_row(goal.id, "tool_three", row_id="after"))


# --------------------------------------------------------------------------- #
# Arm 5: `BLOCKED`, the reopen, and two reopens racing                        #
# --------------------------------------------------------------------------- #


async def test_a_blocked_write_ends_no_row_and_fences_nothing() -> None:
    """Arm 5's first limb, and ADR-0268 §1's own ``BLOCKED`` clause.

    ADR-0250 §1 rules ``BLOCKED`` **open**, on ADR-0249 §4's ground that it means
    *"this objective cannot currently be achieved"*: such a goal is still associated
    to, still planned for and still holds attempts, so its request has not ended and
    neither has its authority. **A lane that ended an authorization on a ``→ BLOCKED``
    write has breached that clause**, and a reader who takes *terminal* to mean *any
    status but ``ACTIVE``* has read a set this decision does not state.

    ``set_goal_status`` is driven directly because no act in this tree writes
    ``BLOCKED``: what is asserted is that the *engine* takes no ending for it, which
    is a fact about the act inventory rather than about the store.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.BLOCKED, at=AT, expected_version=goal.version
    )

    assert journal.calls == []
    assert _dispositions(await store.export()) == {
        "a1": (AuthorizationDisposition.ESTABLISHED, AT),
        "a2": (AuthorizationDisposition.ESTABLISHED, AT),
    }
    assert len(await store.standing(goal.id)) == 2, "the goal's rows still cover a later request"
    assert await store.record(_row(goal.id, "tool_three", row_id="still")) == "still"


async def test_a_reopen_writes_active_then_ends_then_clears() -> None:
    """Arm 5: *"the three asserted in that order"*.

    **The ending is taken first and it is what makes the reopen total** rather than
    dependent on the closure having run; **the clear is second and lifts the fence the
    ending just wrote**, and without it the goal stays fenced against every new
    authorization and the reopened request can establish none — *"every call of it
    asking for ever"*.

    **The rows it ends carry the ``settled_at`` of that ``ACTIVE`` write's own ``at``**
    and not a later reading, and both calls carry that write's own
    ``expected_version``.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    closed = await harness.plans.get_goal(goal.id)
    assert closed is not None
    journal.reset()

    second = (await harness.conversations.begin(None)).id
    reopened = await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    assert reopened.goal_engagement is not None
    assert reopened.goal_engagement.disposition is EngagementDisposition.REOPENED
    assert journal.calls == ["end_for_goal", "clear_closure"], "ADR-0268 §2's order"
    assert journal.endings == [(goal.id, AT, closed.version)]
    assert journal.clears == [(goal.id, closed.version)]
    # The fence is lifted, so the reopened request can establish afresh.
    assert await store.record(_row(goal.id, "tool_three", row_id="afresh")) == "afresh"


async def test_the_reopens_ending_carries_the_active_writes_own_instant() -> None:
    """Arm 5: *"asserted against a clock advanced between the two calls"*.

    The act reads its clock **once** and passes that instant to both its status write
    and its ending, so a ``GOAL_CLOSED`` row this path writes carries the act's own
    instant. The harness's clock is fixed at :data:`AT`, so what this pins is that the
    instant the ending carried is the one the ``ACTIVE`` write carried and not a
    reading taken after it.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _seed(
        harness.plans,
        _goal("goal-legacy", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    # A row the closure never reached: the goal is closed *without* the store being
    # told, which is §9's pre-decision database and a `clear`ed store alike.
    await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.ABANDONED, at=AT, expected_version=goal.version
    )
    await store.record(_row(goal.id, _FIRST, row_id="legacy"))

    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    (_, at, _version) = journal.endings[0]
    held = await store.resolve("legacy")
    assert held is not None
    assert (held.disposition, held.settled_at) == (AuthorizationDisposition.GOAL_CLOSED, at)


async def test_a_reopen_ends_the_row_a_closure_this_store_was_never_told_of_left() -> None:
    """Arm 10's reopen half, and arm 5's *"on one it was not"* limb.

    A goal closed while the store was never told — ADR-0268 §9's pre-decision database,
    or a store the user has ``clear``\\ ed since — holds a row the closure never
    reached. **The reopen's ending is the only route by which such a row otherwise
    reaches a call of the reopened goal**, and it settles it ``GOAL_CLOSED``
    *truthfully*: the goal **was** closed, by an act this store was never told of, and
    the reopen's ending completes that act rather than asserting a closure of its own.

    So **a call of the reopened goal is covered by no row written before the upgrade**.
    """
    harness, store, _journal, conversation = _journalled()
    goal = await _seed(
        harness.plans,
        _goal("goal-legacy", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.ABANDONED, at=AT, expected_version=goal.version
    )
    await store.record(_row(goal.id, _FIRST, row_id="legacy"))
    assert len(await store.standing(goal.id)) == 1

    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    assert await store.standing(goal.id) == ()
    assert await store.live_for(goal.id, _FIRST) is None
    held = await store.resolve("legacy")
    assert held is not None
    assert held.disposition is AuthorizationDisposition.GOAL_CLOSED


async def test_a_reopens_ending_over_a_told_store_moves_nothing() -> None:
    """Arm 5: *"on a goal this store was told about it answers ``0``"*.

    The closure already ended the rows, so the reopen's ending finds none left to move
    — and the clear then lifts the fence the closure raised, which is the whole of what
    the reopen owes on that path.
    """
    harness, store, _journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    before = {row.id: (row.disposition, row.settled_at) for row in await store.export()}

    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    assert {row.id: (row.disposition, row.settled_at) for row in await store.export()} == before
    assert await store.record(_row(goal.id, "tool_three", row_id="afresh")) == "afresh"


async def test_the_goals_user_stated_constraints_survive_the_closure_and_the_reopening() -> None:
    """Arm 5: *"the goal's ``USER_STATED`` constraints are **unchanged** across the
    closure and the reopening"*.

    ADR-0268 §2: **the ending ends the authority and never the interpretation.**
    ADR-0250 §13's *"Reopening preserves everything the goal holds"* and ADR-0249 §1's
    append-only chain bind entire, so a ``USER_STATED`` constraint of the goal — the
    money ceiling among them — survives unchanged. **No lane reads a closure as licence
    to ask the user to restate a bound.**
    """
    harness, store, _journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    before = (await harness.plans.get_goal(goal.id)).interpretation  # type: ignore[union-attr]
    assert before[0].outcome_ground is Ground.USER_STATED

    await harness.engine.abandon_goal(goal.id)
    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    after = (await harness.plans.get_goal(goal.id)).interpretation  # type: ignore[union-attr]
    assert after == before


# --------------------------------------------------------------------------- #
# Arm 6: the recheck                                                          #
# --------------------------------------------------------------------------- #


async def test_a_goal_whose_rows_are_all_ended_reaches_route_d_in_no_case() -> None:
    """Arm 6's second limb: ``live_for`` answers ``None``, so route (d) is unreachable.

    ADR-0254 §7's route-(d) refusal reads the resolved row's ``disposition`` and
    requires ``ESTABLISHED`` — *"every other disposition is retired and none of them is
    live"* — and that reason is true of ``GOAL_CLOSED`` as it is of the other four, so
    **the check is unchanged and needs no conjunct** (ADR-0268 §6).
    """
    harness, store, _journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    assert await store.live_for(goal.id, _FIRST) is not None

    await harness.engine.abandon_goal(goal.id)

    assert await store.live_for(goal.id, _FIRST) is None
    assert await store.live_for(goal.id, _SECOND) is None


# --------------------------------------------------------------------------- #
# Arm 7: each half of the two-write sequence failing                          #
# --------------------------------------------------------------------------- #


async def test_a_faulting_ending_writes_no_status_and_leaves_no_fence() -> None:
    """Arm 7's first half: *"the act propagates and **no write of ``PlanStore``
    follows**"*.

    **Asserted over the call count** of ``close_goal_abandoned`` and not only over the
    stored state — the act's own first read being no part of that count — because a
    store left holding an open goal looks the same whether the closing write never ran
    or ran and was refused. **No status is written, no attempt is committed, no fence
    stands**, the ending's step being all-or-nothing, and **a re-run performs the act
    whole**.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    store.fail_writes()

    with pytest.raises(AuthorizationError):
        await harness.engine.abandon_goal(goal.id)

    assert journal.calls == ["end_for_goal"], "the closing write never ran"
    held = await harness.plans.get_goal(goal.id)
    assert held is not None
    assert held.status is GoalStatus.ACTIVE
    assert not [one for one in await harness.plans.attempts_of(goal.id) if one.ended_at], (
        "no attempt is committed: the closing write is what ends them, and it never ran"
    )

    # A re-run performs the act whole.
    store.stop_failing()
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    assert await store.standing(goal.id) == ()


async def test_a_failing_closing_write_leaves_the_rows_ended_the_goal_open_and_fenced() -> None:
    """Arm 7's second half: *"the act propagates and **clears nothing**"*.

    The rows stand ``GOAL_CLOSED``, truthfully under ADR-0268 §2's meaning — *"the
    ending their goal's closure takes is what ended them, which is what happened"* —
    the goal is left **open and fenced**, and **every later ``record`` of that goal is
    refused**, which is ADR-0254 §12's own stated cost for its rung 3 reached by one
    further route.

    **``clear_closure`` is called not at all**, asserted over the call count: §1 refuses
    the compensation because it *"cannot tell its own orphaned fence from one a
    concurrent act is relying on"*, and the version does not separate them.

    **And the goal is recoverable**: abandoning it succeeds and closes it, and
    reopening it then leaves a goal a fresh row records under. That is the repair, and
    it is the user's own two acts and no mechanism.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    journal.closing_fault = RuntimeError("the plan store is unwritable")

    with pytest.raises(RuntimeError, match="unwritable"):
        await harness.engine.abandon_goal(goal.id)

    assert journal.calls == ["end_for_goal", "close_goal_abandoned"]
    assert journal.clears == [], "no compensation, on any path"
    assert _dispositions(await store.export()) == {
        "a1": (AuthorizationDisposition.GOAL_CLOSED, AT),
        "a2": (AuthorizationDisposition.GOAL_CLOSED, AT),
    }
    held = await harness.plans.get_goal(goal.id)
    assert held is not None
    assert held.status is GoalStatus.ACTIVE, "open, and fenced — every call of it asks"
    with pytest.raises(AuthorizationError):
        await store.record(_row(goal.id, "tool_three", row_id="refused"))

    # The repair is the user's own two acts.
    journal.closing_fault = None
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )
    assert await store.record(_row(goal.id, "tool_three", row_id="repaired")) == "repaired"
