"""ADR-0250's three promoted operations, its focus rule, and the arms around them.

``goals``, ``withdraw_clarification`` and ``abandon_goal`` (§§12, 15); §1's four
engaging acts and what leaves focus alone; §14's elision disclosure; §11's crash
windows; and the brief's one open-question text (§8). Each is driven through the
production engine, because each is a fact about what the store holds afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_engine import (
    AT,
    Harness,
    NoStepPlanner,
)
from test_engine_goal_association import (
    _goal,
    _seed,
)

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    ActionPlan,
    PlanStep,
)
from ai_assistant.testing import (
    FakePlanStore,
)

# --------------------------------------------------------------------------- #
# §15: the listing                                                            #
# --------------------------------------------------------------------------- #


async def test_goals_lists_what_is_outstanding_in_the_engagement_order() -> None:
    """§15: the listing a user learns what is outstanding from, in §1's order.

    "The **focused goal** … with the **greatest ``last_engaged_at``**, with the
    ``goal_id`` ascending as the tie-break, and a goal whose ``last_engaged_at`` is
    absent sorts **after** every goal carrying one."
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id
    await _seed(harness.plans, _goal("g-never", "an untouched goal", conversation=conversation))
    older = _goal("g-older", "book a flight", conversation=conversation)
    await harness.plans.save_goal(older)
    await harness.plans.engage_goal(
        older.id, at=AT, conversation_id=conversation, expected_version=older.version
    )
    newer = _goal("g-newer", "book a campsite", conversation=conversation)
    await harness.plans.save_goal(newer)
    await harness.plans.engage_goal(
        newer.id,
        at=AT + timedelta(hours=1),
        conversation_id=conversation,
        expected_version=newer.version,
    )

    listed = await harness.engine.goals()

    assert [summary.id for summary in listed] == ["g-newer", "g-older", "g-never"]
    assert [summary.outcome for summary in listed] == [
        "book a campsite",
        "book a flight",
        "an untouched goal",
    ]
    assert all(not summary.paused for summary in listed), "no attempt, so nothing is paused"


async def test_goals_refuses_a_non_positive_limit_and_a_negative_offset() -> None:
    """§15: paged on ADR-0085 §3's own convention, refused as every other page is."""
    harness = Harness(planner=NoStepPlanner())

    with pytest.raises(ValueError, match="positive"):
        await harness.engine.goals(limit=0)
    with pytest.raises(ValueError, match=r"offset must be in"):
        await harness.engine.goals(offset=-1)


# --------------------------------------------------------------------------- #
# §1: focus, and what does not move it                                        #
# --------------------------------------------------------------------------- #


async def test_a_resumed_park_engages_the_goal_its_park_names() -> None:
    """§20 arm 18: §1's third act, "on the path that dispatches".

    Driven at the seam a park's id is answerable from — the goal id the park carries —
    because ADR-0249 §11 makes that id "an identifier and **not** a resolution guarantee"
    and this act is what reads it.
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    await harness.engine._engage(campsite.id, conversation_id=conversation)

    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert held.last_engaged_at is not None
    assert held.last_engaged_in == conversation
    assert held.conversation_id == conversation, "§13: provenance is never rewritten"


async def test_an_engagement_of_a_goal_the_store_lost_is_not_a_fault() -> None:
    """ADR-0249 §11: "a resolution guarantee" is exactly what a park's goal id is not.

    "No lane repairs, back-fills or refuses such a park", so a resumption naming a goal
    no row holds engages nothing and raises nothing.
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id

    await harness.engine._engage("no-such-goal", conversation_id=conversation)
    await harness.engine._engage(None, conversation_id=conversation)


# --------------------------------------------------------------------------- #
# §8, §11, §16: the brief, a crash window, and an early end                   #
# --------------------------------------------------------------------------- #


async def test_a_contended_engagement_raises_where_the_stamp_precedes_the_act() -> None:
    """§1's act 4 is stamped **before** the runner is entered, so a lost write refuses.

    ADR-0014 §5 makes a stale write "a detectable, **retryable** failure", and moving
    the stamp ahead of the irreversible work is what makes raising the right answer: the
    resumption has consumed nothing, so what the caller retries costs nothing.
    """
    plans = _AlwaysStale(now=lambda: AT)
    harness = Harness(planner=NoStepPlanner(), plans=plans)
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    with pytest.raises(StaleExecutionError):
        await harness.engine._engage(campsite.id, conversation_id=conversation)

    assert plans.attempts == 1, "one read, one write, and the refusal is the caller's to retry"


async def test_a_contended_resumed_park_retries_and_then_gives_up_its_stamp() -> None:
    """§1's act 3 is stamped **after** the dispatch, because its own clause places it there.

    §1 admits a resumed park "on the path that **dispatches**", so whether this act
    engages at all is decided by the answer having dispatched — and the dispatch is the
    irreversible work. No ordering puts the stamp ahead of it, so raising there would
    throw away the outcome of a read that already left the device, for a value §1 reads
    for focus alone. The read is retaken and exhaustion is logged, which is ADR-0014 §5's
    "re-read and retry" with the one bound that stops a spin.
    """
    plans = _AlwaysStale(now=lambda: AT)
    harness = Harness(planner=NoStepPlanner(), plans=plans)
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    await harness.engine._engage_after_the_act(campsite.id, conversation_id=conversation)

    assert plans.attempts == 3, "ADR-0014 §5: the read is retaken rather than the token guessed"
    held = await plans.get_goal(campsite.id)
    assert held is not None
    assert held.last_engaged_at is None, "and the completed read's outcome is not thrown away"


class _AlwaysStale(FakePlanStore):
    """A store whose goal is engaged by somebody else between every read and write."""

    attempts: int = 0

    async def engage_goal(self, goal_id: str, /, **fields: Any) -> Any:
        """Refuse as a lost compare-and-swap does, every time."""
        self.attempts += 1
        msg = "another turn advanced this goal"
        raise StaleExecutionError(msg)


@pytest.mark.parametrize(
    "ttl",
    [
        pytest.param(timedelta(0), id="zero"),
        pytest.param(timedelta(seconds=-1), id="a negative duration"),
    ],
)
def test_a_non_positive_lifetime_is_refused_at_construction(ttl: timedelta) -> None:
    """§8: the lifetime is "required, positive, with no disable spelling".

    ``Settings`` refuses it at load (``gt=timedelta(0)``), and the façade refuses it at
    construction too — exactly as it already does for ``routed_confirmation_ttl``, and
    for the same reason. A lifetime of zero or less produces a clarification already
    expired at the instant it is asked: the user is shown a question that the very next
    read settles ``EXPIRED``, and no answer can ever reach it.
    """
    with pytest.raises(ConfigurationError, match="goal_question_ttl must be positive"):
        Harness(planner=NoStepPlanner(), goal_question_ttl=ttl)


def test_a_clock_near_the_end_of_the_calendar_is_refused_by_the_clock_seam() -> None:
    """The other half of that boundary is ADR-0026's, and it is already closed.

    A deployment whose clock reads near ``datetime.max`` would overflow **every**
    lifetime, the default included — and it never reaches ADR-0250 §8's check, because
    ``checked_clock`` refuses a reading "outside the localizable range" first. This case
    pins that, so the deadline check is stated over the one axis that can actually vary:
    the configured lifetime.
    """
    harness = Harness(
        planner=NoStepPlanner(),
        now=lambda: datetime.max.replace(tzinfo=UTC) - timedelta(hours=1),
    )

    with pytest.raises(ClockReadingError, match="localizable range"):
        harness.engine._question_instants()


async def test_a_binding_lookup_that_failed_is_not_a_binding_that_resolved_to_nothing() -> None:
    """§1's fourth act: an unreadable index refuses the resume rather than skipping the stamp.

    ``None`` from ``conversation_of_binding`` is ADR-0074 §3's "not captured at all, and
    no conversation invented" — a park predating capture, or one whose conversation the
    user deleted — and leaves nothing to stamp ``last_engaged_in`` with. A
    ``ConversationStoreError`` is the index being unreadable for a moment, and treating
    the two alike would let a confirmed step run **unengaged** on a turn where the very
    next lookup succeeds. Propagating it costs nothing, because this runs before the
    runner is entered.
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )
    await harness.plans.save_plan(
        ActionPlan(
            id="plan-1",
            goal_id=campsite.id,
            steps=(PlanStep(id="step-1", intent="send it", capability="send_email"),),
            created_at=AT,
            targets_revision=1,
        )
    )
    state = await harness.plans.start_execution("plan-1")
    harness.engine._conversations = _UnreadableBindings(  # type: ignore[assignment]  # a case arming one read
        harness.conversations
    )

    with pytest.raises(ConversationStoreError):
        await harness.engine._engage_execution(state.id, "step-1")

    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert held.last_engaged_at is None, "and the resumption is refused before it runs"


class _UnreadableBindings:
    """A lifecycle whose binding lookup is the one read that fails."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        """Everything but the binding lookup is the real lifecycle's."""
        return getattr(self._inner, name)

    async def conversation_of_binding(self, binding: Any) -> Any:
        """Fail as an unreadable index does."""
        msg = "the index could not be read"
        raise ConversationStoreError(msg)
