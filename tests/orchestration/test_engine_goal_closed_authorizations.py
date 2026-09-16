"""ADR-0268's act-level arms: the ending at the abandon, and the reopen's pair.

§9's arms **4, 5, 6**, arm **7**'s act half and arm **10**'s reopen half. Each is a
fact about an *act* — which store call it takes, in what order, with which instant
and which version, and what each half of a two-write sequence failing leaves — so
each is driven through the production engine over a real ``PlanStore`` and a real
``GoalAuthorizationStore``. Arms 1, 2, 3, 8 and 9 are the store's own surface and
are ``tests/permissions/goal_authorization_contract.py``'s; arm 10's *database*
half is about bytes on disk and is the durable store's.

**Arm 4's last two limbs land here with ADR-0261's L2** (#2452, closed by it). Arm 4
states the act's answer is *"``ABANDONED`` or ``ABANDONED_EFFECT_IN_FLIGHT`` exactly as
ADR-0261 §6 fixes it"* and that *"a ``StaleExecutionError`` retry calls ``end_for_goal``
**once per attempt it makes**, each carrying **that attempt's own instant**"*. Until that
lane the engine discarded the ``bool`` and took no retry (#2435), so neither limb had a
tree; both are now asserted in this module's last section — the per-attempt call count,
the re-read's two branches, ``clear_closure`` called not at all on either, and the
``ABANDONED_EFFECT_IN_FLIGHT`` answer with the ending fired beside it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner
from test_engine_cancellation_act import _an_attempt_with_a_claimed_step
from test_engine_goal_association import _associating, _goal, _seed

from ai_assistant.core.errors import AuthorizationError, StaleExecutionError
from ai_assistant.core.types import (
    AssociationVerdict,
    AuthorizationDisposition,
    EngagementDisposition,
    GoalAbandonment,
    GoalStatus,
    Ground,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    StepStatus,
    TurnReference,
)
from ai_assistant.testing import (
    AUTHORIZATION_TOOL,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    opening_act,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from ai_assistant.core.types import Authorization, Goal

#: The declarations a goal's two rows are established about. ADR-0268 §1's *"the
#: ending is stated over the set and never over one row"* needs two, because *"an
#: act that ended one would leave the other standing under a closed goal"*.
_FIRST: Final = "tool_one"
_SECOND: Final = "tool_two"

#: Far enough past :data:`AT` that nothing in these cases lapses on its own.
_EXPIRES: Final = AT + timedelta(days=30)


class _Advancing:
    """A clock that moves on with every reading, and counts them.

    **What a fixed clock cannot falsify**: an implementation reading the clock a
    second time between its status write and its ending passes every arm stated
    against a constant, and writes a ``settled_at`` no act happened at. A day per
    reading, so a second one is far outside every interval these cases describe.
    """

    def __init__(self, at: datetime, *, step: timedelta) -> None:
        """Create a clock reading ``at`` and advancing by ``step`` each reading."""
        self._at = at
        self._step = step
        self.readings = 0

    def __call__(self) -> datetime:
        """Return the current reading, count it, and move on."""
        reading = self._at
        self._at += self._step
        self.readings += 1
        return reading

    @property
    def step_would_move(self) -> bool:
        """Whether this clock really advances, so a fixed one cannot pass as one."""
        return self._step > timedelta(0)


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


class _Raw(NamedTuple):
    """The store's two ending members as they were before the journal wrapped them.

    **Needed so a competing act does not pollute the journal**: the arm about two
    racing reopens asserts what the **losing** act called, and a marker recorded
    mid-wrapper would be defeated by exactly the mutation the arm exists to catch —
    an ending hoisted above the ``ACTIVE`` write runs *before* the competing act,
    and a reset taken after that act would wipe the evidence.
    """

    end_for_goal: Callable[..., Awaitable[int]]
    clear_closure: Callable[..., Awaitable[bool]]


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
        #: The instants the **closing write** was given, so the single-reading clause
        #: can be asserted over the pair rather than over the ending alone.
        self.closings: list[datetime] = []
        #: Armed by the case that needs ADR-0268 §9 arm 7's *"closing write raising
        #: after a successful ending"*. ``FakePlanStore`` carries no fault hook of
        #: its own, and putting one on the shipping fake for a single arm would add a
        #: knob to every consumer's double.
        self.closing_fault: Exception | None = None
        #: One-shot faults for the closing write, consumed in order, so ADR-0261 §2's
        #: single retry can be driven: a scripted ``StaleExecutionError`` on the first
        #: attempt and nothing on the second. Distinct from :attr:`closing_fault`, which
        #: stays armed and is what arm 7's *"the act propagates"* needs.
        self.closing_faults: list[Exception | None] = []
        #: Run as a closing write leaves, which is ADR-0261 §2's window *"between the
        #: stale refusal and the re-read"* — where a second act, a deletion or a reopen
        #: lands. It is given the harness's stores by the case that arms it.
        self.after_closing: Callable[[], Awaitable[None]] | None = None
        #: Armed to fault **one** ending member rather than the store. ADR-0268 §9
        #: arm 10 injects each reopen call *separately*, and the canonical fake's
        #: ``fail_writes`` is store-wide — so arming it before the reopen faults the
        #: act's own ``end_for_goal`` first and ``clear_closure`` is never reached at
        #: all. Adversarial review, round 3, ``blocker``.
        self.ending_faults: dict[str, Exception] = {}
        #: The store's own members, unwrapped. Set by :meth:`install`.
        self.raw: _Raw

    def install(self, store: FakeGoalAuthorizationStore, plans: FakePlanStore) -> None:
        """Wrap the three calls these arms are stated over.

        The unwrapped handles are kept on :attr:`raw`, so a case arranging a
        **competing** act can drive the store without its calls landing in a journal
        that is about the act under test.
        """
        end_for_goal = store.end_for_goal
        clear_closure = store.clear_closure
        closing_write = plans.close_goal_abandoned
        self.raw = _Raw(end_for_goal=end_for_goal, clear_closure=clear_closure)

        async def ending(goal: str, /, *, at: datetime, goal_version: int) -> int:
            self.calls.append("end_for_goal")
            self.endings.append((goal, at, goal_version))
            # **Recorded before the fault**, so the arm can assert the call was made
            # and then failed rather than never made.
            if (fault := self.ending_faults.get("end_for_goal")) is not None:
                raise fault
            return await end_for_goal(goal, at=at, goal_version=goal_version)

        async def clearing(goal: str, /, *, goal_version: int) -> bool:
            self.calls.append("clear_closure")
            self.clears.append((goal, goal_version))
            if (fault := self.ending_faults.get("clear_closure")) is not None:
                raise fault
            return await clear_closure(goal, goal_version=goal_version)

        async def closing(goal_id: str, /, **fields: Any) -> bool:
            # **Appended before the fault**, because arm 7 asserts the order on this
            # path too: the ending ran, and then the closing write was attempted.
            self.calls.append("close_goal_abandoned")
            self.closings.append(fields["at"])
            if self.closing_fault is not None:
                raise self.closing_fault
            if self.closing_faults:
                queued = self.closing_faults.pop(0)
                if queued is not None:
                    if self.after_closing is not None:
                        after, self.after_closing = self.after_closing, None
                        await after()
                    raise queued
            return await closing_write(goal_id, **fields)

        setattr(store, "end_for_goal", ending)  # noqa: B010 — an instance lever, not an attribute
        setattr(store, "clear_closure", clearing)  # noqa: B010
        setattr(plans, "close_goal_abandoned", closing)  # noqa: B010

    def reset(self) -> None:
        """Forget what has been recorded, leaving any armed fault alone."""
        self.calls.clear()
        self.endings.clear()
        self.clears.clear()
        self.closings.clear()


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
    it and never a second reading taken between the two writes — so the rows, the
    ending's own argument and the closing write's own argument are one value.

    **Three things are asserted, and each is free without the others.**

    The clock **advances**, so an act reading it twice cannot produce one value by
    luck — a fixed clock falsifies nothing, which is what round 5 found.

    Both writes were given the **same** value, the closing write's own ``at`` being
    captured rather than inferred from the rows — asserting only over the rows leaves
    the other half free, which is what round 5 found.

    And the attempt takes **exactly one reading**, which is the clause's own word —
    *"reads the clock **once**"* — and which an act taking a second reading and
    discarding it breaches while satisfying both assertions above. Adversarial
    review, round 6, ``blocker``.

    **The one reading is measured against a baseline act rather than hard-coded.**
    A bare count over the whole call is not the attempt's: the tracing seam stamps
    every tracked operation from the same clock (``orchestration/traces.py``), so
    the engine reads it once before ``abandon_goal`` has done anything. So the act
    is run twice — once over a goal the store does not hold, which answers
    ``NO_SUCH_GOAL`` from its first read and *"ends **nothing** and fences
    **nothing**"* (§1), and once for real — and the difference between the two
    deltas is the attempt's own reading and nothing else. That is self-calibrating:
    it stays true if the tracing seam ever stamps differently, where a hard-coded
    total would break for a reason this arm is not about.

    **The goal is arranged with no open question** so that no third party reads
    inside either act: ``_withdraw_open_question`` reads no clock where a goal holds
    none, ``_open_question`` returning before its own reading.

    The reopen path's half of this clause was closed in round 1, and rounds 5 and 6
    are this path's twin arriving in two pieces.
    """
    journal = _Journal()
    clock = _Advancing(AT, step=timedelta(days=1))
    store = FakeGoalAuthorizationStore(now=lambda: AT)
    plans = FakePlanStore(now=lambda: AT)
    journal.install(store, plans)
    harness = Harness(
        planner=NoStepPlanner(),
        plans=plans,
        authorizations=store,
        episode_retention=timedelta(days=365),
        associator=_associating(AssociationVerdict.CONTINUES),
        now=clock,
    )
    goal = await _goal_with_two_rows(harness, store, conversation="conversation-1")
    assert await harness.plans.open_question(goal.id) is None, (
        "arranged with no open question, so the attempt's own reading is the only one"
    )
    journal.reset()

    # The baseline: a tracked act that makes no closing-write attempt at all.
    baseline = clock.readings
    assert await harness.engine.abandon_goal("no-such-goal") is GoalAbandonment.NO_SUCH_GOAL
    overhead = clock.readings - baseline
    assert journal.calls == [], "and it takes no ending, which is what makes it a baseline"

    before = clock.readings
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED

    assert (clock.readings - before) - overhead == 1, (
        "the attempt reads the clock once (ADR-0268 §1), so a discarded second "
        "reading is a breach even where both writes get the same value"
    )
    assert clock.step_would_move, "the clock advances, so one value cannot happen by luck"
    (_, ending_at, _version) = journal.endings[0]
    assert journal.closings == [ending_at], (
        "the closing write takes the ending's own instant, not a later reading"
    )
    assert {row.settled_at for row in await store.export()} == {ending_at}, (
        "and every row the act ended carries it too"
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
    """Arm 6's second limb, at the **act**: the abandon leaves ``live_for`` at ``None``.

    ADR-0254 §7's route-(d) refusal reads the resolved row's ``disposition`` and
    requires ``ESTABLISHED`` — *"every other disposition is retired and none of them is
    live"* — and that reason is true of ``GOAL_CLOSED`` as it is of the other four, so
    **the check is unchanged and needs no conjunct** (ADR-0268 §6).

    **What this half pins is the reason, over the real act**: that ``abandon_goal``
    leaves every row of the goal in a disposition the seam refuses to answer with.
    *"``decide`` reaches route (d) in no case"* is the claim itself, and a seam
    answering ``None`` is not evidence for it — a policy reaching the route anyway
    would pass here. That half is driven against the real ``ThresholdActionPolicy``
    in ``tests/permissions/test_goal_authorization_policy.py``
    (``TestAGoalWhoseRowsAreAllGoalClosedReachesRouteDInNoCase``), which is where the
    policy's own seam-read arms live. Adversarial review, round 14, ``blocker``.
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


# --------------------------------------------------------------------------- #
# Arm 5's concurrency limbs, which a sequential case cannot reach              #
# --------------------------------------------------------------------------- #


async def test_a_reopen_whose_active_write_is_refused_stale_calls_neither_member() -> None:
    """Arm 5: *"of **two acts reopening one goal**, the one whose ``ACTIVE`` write is
    refused stale calls **neither** member and retires **no** row the winner
    established."*

    **The compare-and-swap is what serialises two reopens** (ADR-0268 §2): both acts
    read the goal at the same version, exactly one writes ``ACTIVE``, and exactly one
    takes the pair. **A sequential case cannot reach this**, and an implementation
    that hoisted either call above the ``ACTIVE`` write would pass every sequential
    arm while letting the loser retire the winner's row — an authority established
    for the reopened request, retired by an act that reopened nothing.

    The competing act is run **inside** the losing act's own status write, so the
    interleaving is deterministic rather than a scheduling coincidence.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    closed = await harness.plans.get_goal(goal.id)
    assert closed is not None
    journal.reset()

    winner_ran = False
    real_write = harness.plans.set_goal_status

    async def racing(goal_id: str, /, **fields: Any) -> Goal:
        """Let the *other* reopen win, then take this act's own — now stale — write."""
        nonlocal winner_ran
        if not winner_ran and fields.get("status") is GoalStatus.ACTIVE:
            winner_ran = True
            await real_write(
                goal_id, status=GoalStatus.ACTIVE, at=AT, expected_version=closed.version
            )
            # **Through the unwrapped handles**, so the winner's own pair leaves the
            # journal alone and every entry in it is the losing act's.
            await journal.raw.end_for_goal(goal_id, at=AT, goal_version=closed.version)
            await journal.raw.clear_closure(goal_id, goal_version=closed.version)
            await store.record(_row(goal_id, "tool_three", row_id="winners"))
        return await real_write(goal_id, **fields)

    setattr(harness.plans, "set_goal_status", racing)  # noqa: B010 — an instance lever

    second = (await harness.conversations.begin(None)).id
    with pytest.raises(StaleExecutionError):
        await harness.engine.converse(
            "back to that one",
            timeout=PATIENT,
            conversation_id=second,
            reference=TurnReference(goal_id=goal.id),
        )

    assert journal.calls == [], "the loser's write was refused, so it takes neither member"
    winners = await store.resolve("winners")
    assert winners is not None
    assert winners.disposition is AuthorizationDisposition.ESTABLISHED, (
        "the loser retires no row the winner established"
    )
    assert [row.id for row in await store.standing(goal.id)] == ["winners"]


async def test_the_ending_takes_the_active_writes_reading_under_an_advancing_clock() -> None:
    """Arm 5: *"asserted against a clock advanced between the two calls"*, and §1's
    *"read **once**"* with it.

    **Three things, and each is free without the others** — the same trio the
    abandonment path carries, arrived at the same way (rounds 5, 6 and 9).

    The clock **advances**, so an act reading it twice cannot produce one value by
    luck. Both the ``ACTIVE`` write and the ending were given the **same** value, the
    status write's own ``at`` being captured rather than inferred from the rows. And
    the act takes **exactly one reading**, which the first two do not imply: an act
    making an additional discarded read satisfies both while breaching the clause,
    and would leave a ``GOAL_CLOSED`` row's ``settled_at`` an instant no act happened
    at. Adversarial review, round 9, ``major``.

    **The one reading is measured against a baseline turn rather than hard-coded.**
    A bare count over ``converse`` is not the reopen's: a turn reads the clock for
    the tracing seam, the engagement stamp and its own machinery whatever it
    associates to. So two turns run on one harness and one clock — one engaging an
    **open** goal, which ADR-0250 §13 does not reopen and which therefore takes
    neither member, and one reopening a closed one — and the difference between
    their deltas is the reopen's own reading and nothing else. That stays true if
    the surrounding machinery ever reads differently, where a hard-coded total would
    break for a reason this arm is not about.
    """
    journal = _Journal()
    clock = _Advancing(AT, step=timedelta(days=1))
    store = FakeGoalAuthorizationStore(now=lambda: AT)
    plans = FakePlanStore(now=lambda: AT)
    journal.install(store, plans)
    harness = Harness(
        planner=NoStepPlanner(),
        plans=plans,
        authorizations=store,
        episode_retention=timedelta(days=365),
        associator=_associating(AssociationVerdict.CONTINUES),
        now=clock,
    )
    conversation = "conversation-1"
    # The baseline: a goal left **open**, which a turn resumes rather than reopens.
    open_goal = await _seed(
        harness.plans,
        _goal("goal-open", "book a ferry", conversation=conversation),
        engaged_in=conversation,
    )
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    journal.reset()

    baseline = clock.readings
    resumed = await harness.engine.converse(
        "carry on",
        timeout=PATIENT,
        conversation_id=(await harness.conversations.begin(None)).id,
        reference=TurnReference(goal_id=open_goal.id),
    )
    overhead = clock.readings - baseline
    assert resumed.goal_engagement is not None
    assert resumed.goal_engagement.disposition is EngagementDisposition.RESUMED
    assert journal.calls == [], "the baseline takes neither member, which is what makes it one"

    written: list[datetime] = []
    real_write = plans.set_goal_status

    async def noting(goal_id: str, /, **fields: Any) -> Goal:
        """Record the instant the ``ACTIVE`` write itself was given."""
        if fields.get("status") is GoalStatus.ACTIVE:
            written.append(fields["at"])
        return await real_write(goal_id, **fields)

    setattr(plans, "set_goal_status", noting)  # noqa: B010 — an instance lever

    before = clock.readings
    reopened = await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=(await harness.conversations.begin(None)).id,
        reference=TurnReference(goal_id=goal.id),
    )

    assert reopened.goal_engagement is not None
    assert reopened.goal_engagement.disposition is EngagementDisposition.REOPENED
    assert clock.step_would_move, "the clock advances, so one value cannot happen by luck"
    assert (clock.readings - before) - overhead == 1, (
        "the reopen reads the clock once (ADR-0268 §1), so a discarded second "
        "reading is a breach even where the write and the ending get the same value"
    )
    assert len(written) == 1
    assert journal.endings[0][1] == written[0], (
        "the ending carries the ACTIVE write's own instant and not a later reading"
    )
    # **The rows are not re-asserted here**, and deliberately: this store *was* told
    # of the closure, so the ending finds nothing left to move and the rows still
    # carry the abandonment's instant. That the reopen's ending stamps the rows it
    # does move is the legacy-database arm's, where it moves one.
    assert journal.endings[0][0] == goal.id


async def test_a_reopen_overtaken_by_a_later_closure_unfences_nothing() -> None:
    """Arm 5: *"each act overtaken by the other changes nothing, which is what the
    watermark is for"* — the first direction, at the act.

    With the reopen's ``ACTIVE`` write landed and a closing act then fencing at its
    own **higher** version, the reopen's delayed ``clear_closure`` answers ``False``,
    the fence **stands**, and a ``record`` for that goal is refused. The delayed call
    is the reopen's own, arriving after the closure — which is the state the version
    exists to make harmless.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    closed = await harness.plans.get_goal(goal.id)
    assert closed is not None
    journal.reset()

    # The reopen's ACTIVE write lands; a closing act then fences at a higher version.
    reopened = await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.ACTIVE, at=AT, expected_version=closed.version
    )
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    assert journal.endings[-1][2] > reopened.version - 1

    assert await store.clear_closure(goal.id, goal_version=closed.version) is False
    with pytest.raises(AuthorizationError):
        await store.record(_row(goal.id, "tool_three", row_id="refused"))


async def test_a_closing_act_overtaken_by_a_reopen_ends_no_row_written_since() -> None:
    """Arm 5's other direction: *"the first act's delayed ``end_for_goal`` at its
    **own** version answers ``0``, leaves that row ``ESTABLISHED`` and **live**, and
    leaves the fence **lifted**"*.

    A first closure fenced at its version, a reopen then lifting that fence at a
    higher one, and a **fresh** row recorded under the reopened goal. The overtaken
    act's delayed ending is the whole point of the watermark: the rows it would have
    ended are of a request established **after** its read, which it never had an
    authority over.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await harness.engine.abandon_goal(goal.id)
    first_version = journal.endings[0][2]
    closed = await harness.plans.get_goal(goal.id)
    assert closed is not None

    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )
    await store.record(_row(goal.id, "tool_three", row_id="afresh"))

    assert await store.end_for_goal(goal.id, at=AT, goal_version=first_version) == 0
    fresh = await store.resolve("afresh")
    assert fresh is not None
    assert fresh.disposition is AuthorizationDisposition.ESTABLISHED
    assert await store.live_for(goal.id, "tool_three") is not None, "and still live"
    assert await store.record(_row(goal.id, "tool_four", row_id="another")) == "another"


async def test_a_row_recorded_in_the_unfenced_reopen_window_is_ended_with_the_rest() -> None:
    """Arm 5's last limb: *"asserted over the ending and not over the asking"*.

    Reopening a goal the store holds **no** closure record of, a ``record`` between
    the ``ACTIVE`` write and the ending **succeeds** — there is no fence to stand in
    that window — and **that row is then ended ``GOAL_CLOSED`` with the rest**. That
    is the row ADR-0268 §2's meaning clause is stated over: it was written after the
    closing act and **no closing act ended it**, which is why the member means *the
    ending a closure of its goal takes* rather than *a closing act of its goal ended
    this row*.

    **And a route-(d) ``ALLOW`` already recorded against it with its trail written is
    not retracted by the ending** — the row stands ``GOAL_CLOSED`` and the trail entry
    is **unmoved**. The ending is prospective exactly as a revocation is (ADR-0254
    §13): it *"retracts no decision already recorded and stops no request already
    claimed"*.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _seed(
        harness.plans,
        _goal("goal-legacy", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    # Closed without the store being told: §9's pre-decision database, or one the
    # user has `clear`ed since. So no fence stands and the window is genuinely open.
    await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.ABANDONED, at=AT, expected_version=goal.version
    )
    await store.record(_row(goal.id, _FIRST, row_id="legacy"))

    window = _row(goal.id, "tool_three", row_id="window")
    real_write = harness.plans.set_goal_status

    async def windowed(goal_id: str, /, **fields: Any) -> Goal:
        """Record a row **after** the ``ACTIVE`` write and **before** the ending."""
        written = await real_write(goal_id, **fields)
        if fields.get("status") is GoalStatus.ACTIVE:
            assert await store.record(window) == "window", "no fence stands in the window"
            # The route-(d) ``ALLOW`` is built here rather than driven through the
            # policy: what the arm is about is what the **ending** does to a decision
            # already recorded, not how that decision came to be recorded.
            await harness.trail.record(
                PermissionDecision(
                    id="d-window",
                    ruling=PermissionRuling(
                        outcome=PermissionOutcome.ALLOW,
                        reason="the user's own recorded act for this goal covers this call",
                        authorised_by=window.id,
                        authorised_subject=window.subject_digest,
                        authorised_goal=window.goal,
                    ),
                    tool=window.tool,
                    parameters_digest="0" * 64,
                    decided_at=AT,
                )
            )
        return written

    setattr(harness.plans, "set_goal_status", windowed)  # noqa: B010 — an instance lever
    journal.reset()

    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal.id),
    )

    held = await store.resolve("window")
    assert held is not None
    assert held.disposition is AuthorizationDisposition.GOAL_CLOSED, (
        "the window's row is ended with the rows the closure never reached"
    )
    legacy = await store.resolve("legacy")
    assert legacy is not None
    assert legacy.disposition is AuthorizationDisposition.GOAL_CLOSED
    recorded = [one for one in await harness.trail.export() if one.id == "d-window"]
    assert len(recorded) == 1, "the ending retracts no decision already recorded"
    assert recorded[0].ruling.authorised_by == "window"


# --------------------------------------------------------------------------- #
# Arm 10's reopen failure matrix, on both databases, through the engine        #
# --------------------------------------------------------------------------- #


async def _legacy_goal(
    harness: Harness, store: FakeGoalAuthorizationStore, *, conversation: str
) -> Goal:
    """A goal closed **without** this store being told, holding one standing row.

    ADR-0268 §9's pre-decision database, and a store the user has ``clear``\\ ed
    since: no closure record stands, so nothing is fenced and the legacy row is
    still `ESTABLISHED`.
    """
    goal = await _seed(
        harness.plans,
        _goal("goal-legacy", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await harness.plans.set_goal_status(
        goal.id, status=GoalStatus.ABANDONED, at=AT, expected_version=goal.version
    )
    await store.record(_row(goal.id, _FIRST, row_id="legacy"))
    return goal


async def _reopen(harness: Harness, goal_id: str) -> None:
    """Drive ADR-0250 §13's reopen through the production engine."""
    second = (await harness.conversations.begin(None)).id
    await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal_id),
    )


@pytest.mark.parametrize("failing", ["end_for_goal", "clear_closure"])
async def test_a_reopen_call_faulting_on_a_pre_decision_database_leaves_it_unfenced(
    failing: str,
) -> None:
    """Arm 10: *"each reopen call faulting is injected, on both databases"* — the
    database ADR-0268 §9's prospectivity leaves behind.

    *"``end_for_goal`` faulting after a successful ``ACTIVE`` write leaves the goal
    **active and unfenced**, its legacy row **still ``ESTABLISHED`` and still
    covering a call** until its own ``expires_at``"* — its step being all-or-nothing,
    so a fault writes no fence either. **That is §9's prospectivity bound exactly, no
    worse than the pre-decision behaviour and the state the reopen exists to improve
    on rather than one this decision creates**; *"no clause claims every call of such
    a goal asks"*.

    *"And on both, ``clear_closure`` raising leaves whatever the ending left"* — here
    a goal the reopen's own ending has just fenced for the first time, so that half
    **does** ask, and the repair is the user's two acts.

    **The fault is member-specific and the call sequence is asserted**, because a
    store-wide one faults the act's own ``end_for_goal`` first and ``clear_closure``
    is never reached — an engine that swallowed, retried or compensated a real
    clearing fault would pass a case that never made the call. Adversarial review,
    round 3, ``blocker``.

    **Driven through ``Engine.converse``**, because the fault is about what the
    *reopen* leaves: a direct call proves the store is all-or-nothing and says
    nothing about whether the act compensates, retries or swallows.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _legacy_goal(harness, store, conversation=conversation)
    journal.ending_faults[failing] = AuthorizationError(f"fake: {failing} is unwritable")

    with pytest.raises(AuthorizationError, match=failing):
        await _reopen(harness, goal.id)

    expected = ["end_for_goal"] if failing == "end_for_goal" else ["end_for_goal", "clear_closure"]
    assert journal.calls == expected, "the faulting call was reached, and nothing followed it"

    held = await harness.plans.get_goal(goal.id)
    assert held is not None
    assert held.status is GoalStatus.ACTIVE, "the ACTIVE write landed; the act propagates after it"

    legacy = await store.resolve("legacy")
    assert legacy is not None
    if failing == "end_for_goal":
        assert legacy.disposition is AuthorizationDisposition.ESTABLISHED
        assert [row.id for row in await store.standing(goal.id)] == ["legacy"], (
            "still covering a call, until its own expires_at and no longer"
        )
        assert await store.record(_row(goal.id, "tool_three", row_id="unfenced")) == "unfenced", (
            "unfenced: an end_for_goal that faults writes no fence either"
        )
    else:
        assert legacy.disposition is AuthorizationDisposition.GOAL_CLOSED, (
            "the ending landed; only the clear failed"
        )
        with pytest.raises(AuthorizationError):
            await store.record(_row(goal.id, "tool_three", row_id="fenced"))

    # **The repair is the user's own two acts, on both halves.**
    journal.ending_faults.clear()
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    await _reopen(harness, goal.id)
    assert await store.record(_row(goal.id, "tool_four", row_id="repaired")) == "repaired"


@pytest.mark.parametrize("failing", ["end_for_goal", "clear_closure"])
async def test_a_reopen_call_faulting_on_a_goal_closed_under_this_decision_leaves_it_fenced(
    failing: str,
) -> None:
    """Arm 10's other database: *"on a goal closed **under** this decision the same
    injection leaves it active and **fenced**, every ``record`` refused"*.

    The closure raised a fence, so neither fault lifts it: an ``end_for_goal`` that
    raises writes nothing and leaves the closure's fence standing, and a
    ``clear_closure`` that raises leaves what the ending left — which on this
    database is a fence either way. **Every call of that goal asks** until the user
    repairs it, which is ADR-0254 §12's own stated cost reached by one further route,
    and *"the repair is the user's own two acts and no mechanism"*.

    **Nothing compensates**, asserted over the call sequence: no second
    ``clear_closure`` follows a failed one, and none follows a failed ending.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    journal.reset()
    journal.ending_faults[failing] = AuthorizationError(f"fake: {failing} is unwritable")

    with pytest.raises(AuthorizationError, match=failing):
        await _reopen(harness, goal.id)

    expected = ["end_for_goal"] if failing == "end_for_goal" else ["end_for_goal", "clear_closure"]
    assert journal.calls == expected, "the faulting call was reached, and nothing followed it"

    held = await harness.plans.get_goal(goal.id)
    assert held is not None
    assert held.status is GoalStatus.ACTIVE
    with pytest.raises(AuthorizationError):
        await store.record(_row(goal.id, "tool_three", row_id="refused"))

    # The repair, again the user's own two acts.
    journal.ending_faults.clear()
    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    await _reopen(harness, goal.id)
    assert await store.record(_row(goal.id, "tool_four", row_id="repaired")) == "repaired"


# --------------------------------------------------------------------------- #
# Arm 4's two limbs that presupposed ADR-0261 L2 (#2452)                      #
# --------------------------------------------------------------------------- #


async def test_the_retry_takes_its_own_ending_under_its_own_version_and_instant() -> None:
    """Arm 4: ``end_for_goal`` **once per attempt the act makes**, asserted over the count.

    "A ``StaleExecutionError`` retry calls ``end_for_goal`` **once per attempt it makes**,
    each carrying **that attempt's own instant**" (ADR-0268 §1) — so the second attempt is
    not the first one's write re-issued: it re-reads the goal, takes a fresh ending under
    the version its own closing write will name, and only then writes.

    **And a fresh row a reopen admitted between the attempts is ended with the rest.** The
    interference here is that reopen's two halves — the fence lifted, a row recorded —
    followed by a write that moves ``Goal.version``, which is what makes the act's first
    call stale in the first place.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    first_version = goal.version

    async def _reopened_between_the_attempts() -> None:
        # The reopen's own pair, taken through the **unwrapped** members so the arm's
        # "the act clears nothing" assertion is about the act and not about this setup.
        await journal.raw.clear_closure(goal.id, goal_version=first_version)
        await store.record(_row(goal.id, _FIRST, row_id="a3"))
        await harness.plans.engage_goal(
            goal.id, at=AT, conversation_id=conversation, expected_version=first_version
        )

    journal.closing_faults = [StaleExecutionError("the goal has advanced"), None]
    journal.after_closing = _reopened_between_the_attempts

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED

    assert journal.calls == [
        "end_for_goal",
        "close_goal_abandoned",
        "end_for_goal",
        "close_goal_abandoned",
    ]
    # Each attempt's ending carries the version that attempt's own closing write names,
    # and the second is the **re-read** version rather than the first one again.
    assert [version for _, _, version in journal.endings] == [first_version, first_version + 1]
    # One clock reading per attempt, serving that attempt's two writes.
    assert [at for _, at, _ in journal.endings] == journal.closings
    # "`clear_closure` is called **not at all** on either path."
    assert journal.clears == []
    ended = _dispositions(await store.export())
    assert {ended[row][0] for row in ("a1", "a2", "a3")} == {AuthorizationDisposition.GOAL_CLOSED}


async def test_a_retry_whose_re_read_finds_the_goal_closed_ends_nothing_further() -> None:
    """Arm 4: "one whose re-read finds the goal **closed** calls it once in the whole act".

    It "answers ``ALREADY_CLOSED`` and **leaves the fence standing**" — the first attempt's
    ending is not compensated, because a fence lifted here could not be told from one a
    concurrent act is relying on.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    async def _closed_by_somebody_else() -> None:
        await harness.plans.set_goal_status(
            goal.id, status=GoalStatus.ABANDONED, at=AT, expected_version=goal.version
        )

    journal.closing_faults = [StaleExecutionError("the goal has advanced"), None]
    journal.after_closing = _closed_by_somebody_else

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ALREADY_CLOSED

    assert journal.calls == ["end_for_goal", "close_goal_abandoned"]
    assert journal.clears == []
    # The fence the first attempt raised stands: every later `record` of this goal asks.
    with pytest.raises(AuthorizationError):
        await store.record(_row(goal.id, _SECOND, row_id="a4"))


async def test_a_retry_whose_re_read_finds_no_goal_makes_no_second_call() -> None:
    """Arm 4 and ADR-0261 §14 arm 6's deleter, over the ending's own call count.

    The act "answers ``NO_SUCH_GOAL`` and **makes no second call at all**", which is what
    pins the retry to re-taking the act's first-read *decision* rather than its call.
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)

    async def _deleted_by_somebody_else() -> None:
        await harness.plans.delete_goal(goal.id)

    journal.closing_faults = [StaleExecutionError("the goal has advanced"), None]
    journal.after_closing = _deleted_by_somebody_else

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.NO_SUCH_GOAL

    assert journal.calls == ["end_for_goal", "close_goal_abandoned"]
    assert journal.clears == []


async def test_an_effect_in_flight_answer_fires_the_ending_like_any_other_close() -> None:
    """Arm 4's first limb: the answer is §6's member, and the ending is taken all the same.

    ADR-0268 §4: *"the ending fires there like any other"* — an authority ends when its
    goal closes, whatever the closing act had to report about what was outstanding, and
    what was already dispatched is unaffected by that (ADR-0261 §2: the act "does not end
    an execution and does not cancel anything in flight").
    """
    harness, store, journal, conversation = _journalled()
    goal = await _goal_with_two_rows(harness, store, conversation=conversation)
    await _an_attempt_with_a_claimed_step(
        harness.plans,
        harness.trail,
        goal_id=goal.id,
        attempt_id="a-running",
        plan_ordinal=1,
        status=StepStatus.RUNNING,
    )

    answer = await harness.engine.abandon_goal(goal.id)

    assert answer is GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT
    assert journal.calls == ["end_for_goal", "close_goal_abandoned"]
    assert journal.clears == []
    ended = _dispositions(await store.export())
    assert {ended[row][0] for row in ("a1", "a2")} == {AuthorizationDisposition.GOAL_CLOSED}
