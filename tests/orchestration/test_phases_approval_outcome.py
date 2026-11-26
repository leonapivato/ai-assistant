"""An approval's work tells its outcome where the request was asked (ADR-0382).

Each case drives the engine with the phases, the Approvals channel and the check wired, the
owner's phone linked at normal. The owner asks in the hub chat; the asking work ends; a tap
(or the card's expiry) starts the approval's own work, which carries no authority. A text
it sends into the conversation the request was asked from stays outside the check and is
sent (§2:1), whatever the outcome, and that conversation is shown in its Connections
section (§2:5); a takeover is the asking work answering as itself (§4:5); and where the
asking activation cannot be read, no place is kept outside (§4:4). Every other call of that
work is checked as before (§3), which ``test_authorizer_check`` holds case by case.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from exchange_support import section, tags, text_call
from phases_support import open_conversation, phases_harness, said, until, written
from structlog.testing import capture_logs
from test_engine import AT
from test_phases_approvals import (
    _ask,
    _authorizing,
    _Clock,
    _frozen,
    _held,
    _offer,
    _Planner,
    _Policy,
    _requests,
    _seams,
    _tap,
    _until_requests,
)
from test_phases_check import _linked
from test_phases_could_use import _DECLARED_BOOK

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ApprovalRequestState,
    CallCheck,
    CallCheckKind,
    CallOutcomeKind,
    EpisodicMemory,
    MessageAuthor,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.approvals import AskedFrom
from ai_assistant.testing import FakePermissionLineStore, FakePlanStore

if TYPE_CHECKING:
    from test_engine import Harness

    from ai_assistant.core.types import MemoryRecord, PlanningExchange, RecordedCall, Sight
    from ai_assistant.orchestration.authorizer import (
        AuthorizingStage,
        RoundAuthorization,
        RoundToAuthorize,
    )

#: The three outcomes a card's request can have (ADR-0361 §3:5).
State = ApprovalRequestState
_DAY: Final = timedelta(hours=24)
_TOLD: Final = "Booked for the 2nd."


class _Rounds:
    """Every round authorizing was handed, as the phases built it."""

    def __init__(self) -> None:
        self.handed: list[RoundToAuthorize] = []


def _recording(plans: FakePlanStore, rounds: _Rounds) -> type[AuthorizingStage]:
    """Authorizing as ``test_phases_approvals`` wires it, noting each round it is handed."""
    build = _authorizing(plans)

    def recording(**seams: Any) -> AuthorizingStage:
        stage = build(**seams)
        authorize = stage.authorize

        async def noted(given: RoundToAuthorize, *, sight: Sight) -> RoundAuthorization:
            rounds.handed.append(given)
            return await authorize(given, sight=sight)

        stage.authorize = noted  # type: ignore[method-assign]
        return stage

    return cast("type[AuthorizingStage]", recording)


def _checked_harness(
    planner: _Planner, rounds: _Rounds, *, clock: _Clock | None = None, **stores: Any
) -> Harness:
    """The approvals' harness, with the check over no made line and the owner linked."""
    plans = FakePlanStore(now=lambda: AT)
    knobs: dict[str, Any] = {
        "approvals": _seams(),
        "plans": plans,
        "tools": (_DECLARED_BOOK,),
        "identities": _linked(),
        "phases": {
            "policy": _Policy(),
            "round_limit": 8,
            "authorizing": _recording(plans, rounds),
            "lines": FakePermissionLineStore(),
        },
        **stores,
    }
    if clock is not None:
        knobs["now"] = clock
    return phases_harness(planner, **knobs)


def _conversation_label(exchange: PlanningExchange) -> str | None:
    """The ``L`` label of the hub chat conversation its Connections section shows, if any."""
    shown = [
        one
        for one in tags(section(exchange.briefing, "## Connections"), "connection")
        if one.text == "a conversation in the system's own chat"
    ]
    return None if not shown else str(shown[0].get("label"))


async def _asks(exchange: PlanningExchange) -> RoundResponse:
    """The owner's work: it asks for the yes in its first round, then ends."""
    return RoundResponse(calls=(_ask(),)) if not exchange.steps else RoundResponse()


class _Telling:
    """The approval's work: it tells the outcome where it was asked, then ends."""

    def __init__(self) -> None:
        self.labels: list[str | None] = []

    async def __call__(self, exchange: PlanningExchange) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        label = _conversation_label(exchange)
        self.labels.append(label)
        if label is None:
            return RoundResponse()
        call = ProposedCall(
            call_id="t1", name="send_text", arguments={"connection": label, "words": _TOLD}
        )
        return RoundResponse(calls=(call,))


def _entry(episode: EpisodicMemory, call_id: str) -> RecordedCall:
    assert episode.processing_record is not None
    (entry,) = [one for one in episode.processing_record.call_records if one.call_id == call_id]
    return entry


async def _answered(harness: Harness, state: State, clock: _Clock) -> str:
    """The owner asks in the hub chat; once the asking work has ended, the card is
    answered with ``state``, or left to expire. Returns the conversation it was asked in."""
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book the table"))
    (request,) = await _until_requests(harness, 1)
    await _frozen(harness, str(request.activation_id))
    if state is State.EXPIRED:
        clock.at = AT + _DAY + timedelta(minutes=1)
        harness.engine.approvals_changed()
    else:
        await _tap(harness, request, state)
    return conversation


async def _approvals_episode(harness: Harness) -> EpisodicMemory:
    (request,) = await _requests(harness)

    async def pushed() -> bool:
        return (await _held(harness, str(request.id))).pushed_to is not None

    await until(pushed, what="the outcome to be pushed")
    approval = (await _held(harness, str(request.id))).pushed_to
    assert approval is not None
    return await _frozen(harness, approval)


@pytest.mark.parametrize("state", [State.APPROVED, State.DENIED, State.EXPIRED])
async def test_the_outcome_is_told_where_the_request_was_asked_outside_the_check(
    state: State,
) -> None:
    """§2:1, §2:5: approved, denied or expired alike, the asking conversation is shown to
    the approval's work, and its text into it stays outside the check and is sent."""
    telling = _Telling()
    planner = _Planner(_asks, telling)
    rounds = _Rounds()
    clock = _Clock()
    harness = _checked_harness(planner, rounds, clock=clock)
    await harness.engine.start()
    try:
        conversation = await _answered(harness, state, clock)
        episode = await _approvals_episode(harness)
        messages = await written(harness, conversation)
    finally:
        await harness.engine.aclose()

    (label,) = telling.labels
    assert label is not None, "the asking conversation is shown to the approval's work"
    entry = _entry(episode, "t1")
    assert entry.check == CallCheck(kind=CallCheckKind.OUTSIDE)
    assert entry.outcome is CallOutcomeKind.DONE
    assert any(one.author is MessageAuthor.ASSISTANT and one.text == _TOLD for one in messages)
    (asked,) = {one.asked_from for one in rounds.handed if one.asked_from is not None}
    assert asked == AskedFrom(places=(f"conversation:{conversation}",))


async def test_every_other_work_is_handed_no_asking_place() -> None:
    """§3, §6: nothing else's check changes: the owner's own work, the asking one, is
    handed no asking place, and its reply into its own place stays outside as before."""
    planner = _Planner(_asks, _Telling())
    rounds = _Rounds()
    harness = _checked_harness(planner, rounds)
    await harness.engine.start()
    try:
        conversation = await _answered(harness, State.APPROVED, _Clock())
        await _approvals_episode(harness)
    finally:
        await harness.engine.aclose()

    asking = [one for one in rounds.handed if one.input_place == f"conversation:{conversation}"]
    assert asking, "the asking work's rounds"
    assert all(one.asked_from is None for one in asking)
    approvals = [one for one in rounds.handed if one.places is not None]
    assert approvals, "the approval's work's rounds"
    assert all(one.asked_from is not None for one in approvals)


class _TakesItOver:
    """The owner's work: it asks, waits, takes the outcome over and tells it as itself."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.waited = False
        self.took = False
        self.told = False

    async def __call__(self, exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            return RoundResponse(calls=(_ask(),))
        if not self.waited:
            self.waited = True
            await self.gate.wait()
            return RoundResponse(calls=(text_call("I asked for your yes.", call_id="m-2"),))
        offer = _offer(exchange)
        if offer is not None and not self.took:
            self.took = True
            take = ProposedCall(
                call_id="take-1", name="answer_offer", arguments={"offer": offer, "take": True}
            )
            return RoundResponse(calls=(take,))
        if self.took and not self.told:
            self.told = True
            return RoundResponse(calls=(text_call(_TOLD, call_id="t9"),))
        return RoundResponse()


async def test_a_takeover_answers_as_the_asking_work_itself() -> None:
    """§4:5: the asking work takes the outcome over; §2 does not apply, so no round it
    plans is handed an asking place, and its reply into its own place stays outside as
    ADR-0367 §4:7 has its own."""
    taking = _TakesItOver()
    planner = _Planner(taking)
    rounds = _Rounds()
    harness = _checked_harness(planner, rounds)
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "book the table"))
        (request,) = await _until_requests(harness, 1)
        asking = str(request.activation_id)
        await _tap(harness, request)

        async def offered() -> bool:
            state = harness.engine._running_state(asking)
            return state is not None and bool(state.offers)

        await until(offered, what="the approval's input to be offered to the asking work")
        taking.gate.set()
        episode = await _frozen(harness, asking)
    finally:
        await harness.engine.aclose()

    assert taking.took
    assert planner.approval == [], "the approval's own work planned no round"
    assert all(one.asked_from is None for one in rounds.handed)
    entry = _entry(episode, "t9")
    assert entry.check == CallCheck(kind=CallCheckKind.OUTSIDE)
    assert entry.outcome is CallOutcomeKind.DONE


async def test_an_asking_activation_that_cannot_be_read_keeps_no_place_outside() -> None:
    """§4:4: neither its running state nor its episode can be read, so no place is kept
    outside, the place list holds no asking place, and the work is shown none; the read
    is logged under a fixed event name."""
    telling = _Telling()
    planner = _Planner(_asks, telling)
    rounds = _Rounds()
    harness = _checked_harness(planner, rounds)
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "book the table"))
        (request,) = await _until_requests(harness, 1)
        asking = f"activation:{request.activation_id}"
        await _frozen(harness, str(request.activation_id))

        async def ended() -> bool:
            return harness.engine._running_state(str(request.activation_id)) is None

        await until(ended, what="the asking work to have ended")
        memory = harness.memory
        get = memory.get

        async def unreadable(record_id: str) -> MemoryRecord | None:
            if record_id == asking:
                msg = "the store could not be read"
                raise MemoryStoreError(msg)
            return await get(record_id)

        memory.get = unreadable  # type: ignore[method-assign]  # one record cannot be read
        phases = harness.engine._phases
        assert phases is not None
        begin = phases.begin_approval
        begun: list[AskedFrom] = []

        def noting(**given: Any) -> Any:
            begun.append(given["asked_from"])
            return begin(**given)

        phases.begin_approval = noting  # type: ignore[method-assign]
        with capture_logs() as logs:
            await _tap(harness, request)
            await _approvals_episode(harness)
    finally:
        await harness.engine.aclose()

    assert begun == [AskedFrom(read=False)]
    assert telling.labels == [None], "no conversation is shown to it, nor listed for it"
    assert [one for one in logs if one["event"] == "approval_asking_unread"]
