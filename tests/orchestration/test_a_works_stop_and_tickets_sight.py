"""A work's stop call and the tickets it is shown read through its sight (ADR-0383 §7:7).

Milestone 22's B8g. A work's stop call (``Matters.stop``, planning's stop, ADR-0349 §4:7)
reads whether an episode stands, and writes its stop record, through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the sight of the
work that makes it; the tickets a work is shown (ADR-0361 §5:6) are read through the plan
store bound to its sight. With stores built to withhold, an unidentified sender's work
that stops an ended activation of the owner's gets what stopping one never written gets
(§8:2), and writes nothing; the owner's work, at normal and lowered to weak, as today. In
the counting build every read answers as today and writes its count with the reader
"work" (§11:1).

The owner's own ``stop_activation`` is not a work's: it reads unbound, as today, until
the owner's sight is built (ADR-0385, lane B10).
"""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import (
    SETTLE,
    Gated,
    idle,
    open_conversation,
    phases_harness,
    said,
    until,
    working,
)
from sight_support import OWNER_WEAK, UNIDENTIFIED
from story_support import address, episode, work_of
from structlog.testing import capture_logs
from task_support import activation as task_activation
from task_support import seams as task_seams
from task_support import write_task
from test_engine import AT, Harness
from test_phases_task_scheduler import _responder, _silent

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationEffect,
    ActivationStop,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    EpisodicMemory,
    OccurrenceState,
    RecordHome,
    RequestedCall,
    RoundResponse,
    SightMode,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore, FakePlanStore
from ai_assistant.testing.parties import OWNER_SENDER

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    from ai_assistant.core.types import InputSender, Sight
    from ai_assistant.orchestration.activation_state import ActivationState

#: An activation of the owner's that ran and ended: its episode stands, in their domain.
_ENDED: Final = "5d0c6a37-3c1e-4b8e-9e43-6f7a1c2b9d10"
#: An activation no record was ever written for.
_NEVER: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"

_OWNERS: Final = pytest.mark.parametrize(
    "sender", [OWNER_SENDER, OWNER_WEAK], ids=["normal", "weak"]
)
_EVERY: Final = pytest.mark.parametrize(
    "sender", [OWNER_SENDER, OWNER_WEAK, UNIDENTIFIED], ids=["normal", "weak", "unidentified"]
)


class _Kept(FakePlanStore):
    """A plan store that keeps the sight each stop record was written by, and each
    ``approval_requests`` was read by with what it gave back; a bound copy shares both
    lists (``FakePlanStore.bound``)."""

    def __init__(self, mode: SightMode) -> None:
        super().__init__(now=lambda: AT, sight_mode=mode)
        self.stops: list[tuple[Sight | None, str]] = []
        self.read: list[tuple[Sight | None, tuple[str, ...]]] = []

    async def record_stop(self, activation_id: str, /) -> None:
        await super().record_stop(activation_id)
        self.stops.append((self._sight, activation_id))

    async def approval_requests(self, request_ids: Sequence[str], /) -> tuple[ApprovalRequest, ...]:
        found = await super().approval_requests(request_ids)
        self.read.append((self._sight, tuple(one.id for one in found)))
        return found


def _engine(mode: SightMode) -> Harness:
    """An engine whose memory and plan stores are built in ``mode``, with the Task
    Scheduler wired, so the owner's stop of an activation not running asks whether it was
    pushed (ADR-0350 §9:10) before it reads the episode, and a work's never does."""
    return phases_harness(
        memory=FakeMemoryStore(now=lambda: AT, sight_mode=mode),
        plans=FakePlanStore(now=lambda: AT, sight_mode=mode),
        task_scheduler=task_seams(),
    )


async def _ended(harness: Harness) -> None:
    await harness.memory.add(episode(_ENDED))


async def _works_stop(harness: Harness, sender: InputSender, activation_id: str) -> ActivationStop:
    """``activation_id`` stopped by the stop call of a work ``sender``'s input started."""
    with work_of(sender):
        return await harness.engine._matters.stop(activation_id)


async def _held(harness: Harness) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """What the memory and plan stores hold, unbound, to say a stop wrote nothing."""
    memory = [one.model_dump() for one in await harness.memory.export()]
    plans = await harness.plans.export()
    return memory, plans.model_dump(exclude={"exported_at"})


def _without(logs: Sequence[MutableMapping[str, Any]], *ids: str) -> list[dict[str, Any]]:
    """``logs`` with each of ``ids`` written as one placeholder, to compare two stops."""
    pattern = re.compile("|".join(re.escape(one) for one in ids))
    return [
        {
            key: pattern.sub("<id>", value) if isinstance(value, str) else value
            for key, value in row.items()
        }
        for row in logs
    ]


def _counted(logs: Sequence[MutableMapping[str, Any]]) -> list[tuple[str, str, str]]:
    return [
        (row["store"], row["member"], row["reader"])
        for row in logs
        if row["event"] == "sight_counted"
    ]


# --- a work's stop call (ADR-0349 §4:7, ADR-0297 §3, ADR-0383 §8:2) -------------------------


async def test_an_unidentified_senders_stop_of_the_owners_ended_one_is_as_never_written() -> None:
    """§8:2: the same answer, the same log entries, and nothing written in either store."""
    harness = _engine(SightMode.WITHHOLD)
    await _ended(harness)
    before = await _held(harness)

    with capture_logs() as ended_logs:
        ended = await _works_stop(harness, UNIDENTIFIED, _ENDED)
    with capture_logs() as never_logs:
        never = await _works_stop(harness, UNIDENTIFIED, _NEVER)

    assert ended is never is ActivationStop.NO_SUCH_ACTIVATION
    assert _without(ended_logs, _ENDED) == _without(never_logs, _NEVER)
    assert await _held(harness) == before
    assert (await harness.plans.export()).stopped_activations == ()


async def test_the_owners_own_stop_of_that_activation_reads_unbound_as_today() -> None:
    """The owner's act is not a work's: it reads as it does today (ADR-0385, lane B10)."""
    harness = _engine(SightMode.WITHHOLD)
    await _ended(harness)
    before = await _held(harness)

    assert await harness.engine.stop_activation(_ENDED) is ActivationStop.ALREADY_ENDED
    assert await harness.engine.stop_activation(_NEVER) is ActivationStop.NO_SUCH_ACTIVATION
    assert await _held(harness) == before


@_OWNERS
async def test_the_owners_works_stop_answers_as_today_under_stores_that_withhold(
    sender: InputSender,
) -> None:
    """§6's first row, and lowered: its own domain's episode is seen, so ended stays ended."""
    harness = _engine(SightMode.WITHHOLD)
    await _ended(harness)
    before = await _held(harness)

    with capture_logs() as logs:
        ended = await _works_stop(harness, sender, _ENDED)
        never = await _works_stop(harness, sender, _NEVER)

    assert (ended, never) == (ActivationStop.ALREADY_ENDED, ActivationStop.NO_SUCH_ACTIVATION)
    assert await _held(harness) == before
    assert _counted(logs) == [], "a store that withholds writes no count"


@_EVERY
async def test_in_the_counting_build_a_works_stop_answers_as_today_and_counts_each_read(
    sender: InputSender,
) -> None:
    """§11:1: each episode read writes its count, the reader a work; nothing is withheld.

    One read each: a work's stop of an activation not running never asks whether it was
    pushed (ADR-0350 §9:10), so the answer's read is its only one.
    """
    harness = _engine(SightMode.COUNT)
    await _ended(harness)
    before = await _held(harness)

    with capture_logs() as logs:
        ended = await _works_stop(harness, sender, _ENDED)
        never = await _works_stop(harness, sender, _NEVER)

    assert (ended, never) == (ActivationStop.ALREADY_ENDED, ActivationStop.NO_SUCH_ACTIVATION)
    assert await _held(harness) == before
    assert _counted(logs) == [("memory", "get", "work")] * 2


@pytest.mark.parametrize("mode", [SightMode.WITHHOLD, SightMode.COUNT])
async def test_a_works_stop_of_a_running_activation_writes_its_record_through_the_bound_store(
    mode: SightMode,
) -> None:
    """ADR-0297 §3:4, ADR-0383 §3:3, §7:11: the mark, then the record, which carries no
    home and is written whatever the sight sees; no read is counted for the write."""
    completer = Gated(RoundResponse(text="Working on it."))
    plans = _Kept(mode)
    harness = phases_harness(
        completer,
        memory=FakeMemoryStore(now=lambda: AT, sight_mode=mode),
        conversation_store=FakeConversationStore(now=lambda: AT, sight_mode=mode),
        plans=plans,
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    with work_of(OWNER_SENDER) as stopping, capture_logs() as logs:
        stopped = await harness.engine._matters.stop(running)
    completer.release.set()
    await idle(harness, conversation)

    assert stopped is ActivationStop.STOPPED
    assert plans.stops == [(stopping.sight, running)]
    assert (await harness.plans.export()).stopped_activations == (running,)
    assert _counted(logs) == []


class _HeldAdmission(FakePlanStore):
    """A plan store, built in ``mode``, whose admission read is held right after the
    pushed write (ADR-0350 §9:10), so an occurrence stays pushed and not admitted."""

    def __init__(self, mode: SightMode) -> None:
        super().__init__(now=lambda: AT, sight_mode=mode)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.asked: list[str] = []

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        if not self.entered.is_set():
            self.asked.extend(activation_ids)
            self.entered.set()
            await self.release.wait()
        return await super().stopped_activations(activation_ids)


async def _occurrence_state(plans: FakePlanStore, task_id: str) -> OccurrenceState | None:
    held = await plans.scheduled_tasks([task_id])
    return held[0].occurrences[0].state if held else None


@pytest.mark.parametrize("sender", [OWNER_SENDER, UNIDENTIFIED], ids=["owners", "unseen"])
async def test_a_works_stop_of_a_pushed_occurrence_is_as_one_never_written(
    sender: InputSender,
) -> None:
    """ADR-0349 §4:8, ADR-0383 §8:2: a work names only running work, so its stop of an
    occurrence of the owner's pushed and not admitted, whether its sight sees the task or
    not, sets no mark, writes no record, answers as for an activation never written, and
    the occurrence is admitted and runs to its end."""
    plans = _HeldAdmission(SightMode.WITHHOLD)
    harness = phases_harness(
        _responder(_silent, _silent),
        memory=FakeMemoryStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD),
        plans=plans,
        task_scheduler=task_seams(),
    )
    await write_task(plans, task_activation())
    await harness.engine.start()
    try:
        await asyncio.wait_for(plans.entered.wait(), SETTLE)
        (pushed,) = plans.asked
        assert harness.engine._pushed.get(pushed) is False, "pushed, not admitted"

        stopped = await _works_stop(harness, sender, pushed)
        never = await _works_stop(harness, sender, _NEVER)

        assert stopped is never is ActivationStop.NO_SUCH_ACTIVATION
        assert harness.engine._pushed.get(pushed) is False, "no mark is set"
        assert (await plans.export()).stopped_activations == ()
        plans.release.set()

        async def ran() -> bool:
            ran = await harness.memory.get(address(pushed))
            if not isinstance(ran, EpisodicMemory) or ran.processing_record is None:
                return False
            return not ran.processing_record.is_open

        await until(ran, what="the occurrence's activation to run and end")
        assert (await plans.export()).stopped_activations == ()
    finally:
        plans.release.set()
        await harness.engine.aclose()


async def test_the_owners_own_stop_of_a_pushed_occurrence_still_stops_it() -> None:
    """ADR-0350 §9:10 as today: the owner's act marks it and writes its record, unbound."""
    plans = _HeldAdmission(SightMode.WITHHOLD)
    harness = phases_harness(
        _responder(_silent, _silent),
        memory=FakeMemoryStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD),
        plans=plans,
        task_scheduler=task_seams(),
    )
    task = await write_task(plans, task_activation())
    await harness.engine.start()
    try:
        await asyncio.wait_for(plans.entered.wait(), SETTLE)
        (pushed,) = plans.asked

        assert await harness.engine.stop_activation(pushed) is ActivationStop.STOPPED
        assert (await plans.export()).stopped_activations == (pushed,)
        plans.release.set()

        async def ended() -> bool:
            return await _occurrence_state(plans, task.id) in {None, OccurrenceState.STOPPED}

        await until(ended, what="the occurrence to end stopped")
        assert await harness.memory.get(address(pushed)) is None
    finally:
        plans.release.set()
        await harness.engine.aclose()


async def test_a_works_stop_outside_any_work_reads_nothing() -> None:
    """§7:7, §9:2: a work's stop reads by the sight of the work running where it is called,
    and is never made unbound for want of one."""
    harness = _engine(SightMode.WITHHOLD)
    await _ended(harness)

    with pytest.raises(RuntimeError, match="sight"):
        await harness.engine._matters.stop(_ENDED)


# --- the tickets a work is shown (ADR-0361 §5:6) --------------------------------------------

_WRITTEN: Final = AT - timedelta(hours=1)
_REQUEST: Final = "approval:1"


async def _holding_the_owners_approval(harness: Harness, state: ActivationState) -> None:
    """``state`` holds the input of an approval of the owner's, approved by a tap, as the
    approval's own work does (§5:6)."""
    request = ApprovalRequest(
        id=_REQUEST,
        person=OWNER_PERSON_ID,
        activation_id="ask",
        round="r-ask",
        call=RequestedCall(
            tool=REMEMBER_CANDIDATE,
            values={
                "fact": "Prefers aisle seats.",
                "why": "you asked me to keep it",
                "episode": address("ask"),
                "rests_on_outside_content": False,
            },
        ),
        why="You asked me to keep it.",
        written_at=_WRITTEN,
        expires_at=_WRITTEN + timedelta(hours=24),
    )
    asking = ActivationEffect(
        home=RecordHome.owners(),
        id="effect-ask",
        activation_id="ask",
        round="r-ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision-ask",
        claimed_at=_WRITTEN,
        request=request.id,
    )
    await harness.plans.write_approval_request(request, asking, match=None)
    await harness.plans.answer_approval_request(
        request.id,
        ApprovalRequestState.APPROVED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=_WRITTEN),
    )
    assert state.activation_id is not None
    harness.engine._approval_inputs[state.activation_id] = request


@_OWNERS
@pytest.mark.parametrize("mode", [SightMode.WITHHOLD, SightMode.COUNT])
async def test_the_owners_work_is_shown_its_ticket_as_today(
    sender: InputSender, mode: SightMode
) -> None:
    """§5:1, §5:6 as today at every level, read by the work's own sight (ADR-0383 §7:7);
    in the counting build the read writes its count, the reader a work (§11:1)."""
    plans = _Kept(mode)
    harness = Harness(plans=plans)
    with work_of(sender) as state:
        await _holding_the_owners_approval(harness, state)
        plans.read.clear()
        with capture_logs() as logs:
            tickets = await harness.engine._tickets_held(state)

    assert [one.request.id for one in tickets] == [_REQUEST]
    assert plans.read == [(state.sight, (_REQUEST,))]
    expected = [("plans", "approval_requests", "work")] if mode is SightMode.COUNT else []
    assert _counted(logs) == expected


@pytest.mark.parametrize("mode", [SightMode.WITHHOLD, SightMode.COUNT])
async def test_a_request_the_works_sight_does_not_see_is_not_shown(mode: SightMode) -> None:
    """ADR-0383 §8:2: the owner's request, held by an unidentified sender's work, is not
    given back where the stores withhold, as one never written; in the counting build it
    is, and counted. Either way no ticket is shown: this work is no person's (§5:1)."""
    plans = _Kept(mode)
    harness = Harness(plans=plans)
    with work_of(UNIDENTIFIED) as state:
        await _holding_the_owners_approval(harness, state)
        plans.read.clear()
        with capture_logs() as logs:
            tickets = await harness.engine._tickets_held(state)

    assert tickets == ()
    given = (_REQUEST,) if mode is SightMode.COUNT else ()
    assert plans.read == [(state.sight, given)]
    expected = [("plans", "approval_requests", "work")] if mode is SightMode.COUNT else []
    assert _counted(logs) == expected
