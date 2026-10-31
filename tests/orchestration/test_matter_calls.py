"""Planning's stop call, findings look-up and answer call, over constructed states (ADR-0349).

The runner alone (:class:`~ai_assistant.orchestration.matter_calls.MatterCalls`), its
caller handed in as the phases hand it: who calls, whether its input carries the user's
authority, and what it was shown as running. The engine drives them through whole passes
in ``test_phases_matters``.

- The stop call (§4:6-§4:11) is refused whole, stopping nothing, where the input does not
  carry the user's authority, where the label was not shown for a running activation,
  in a waiting round where it names work not waited on, and where the activation was
  absorbed since it was shown, naming the absorber; it stops nothing where the activation
  has ended or been stopped since; and otherwise it is the Task Manager's stop, its result
  the activation's finished work through the peer view.
- The look-up (§6:1, §6:5-§6:6) is refused whole for a label not shown as running, and
  otherwise shows the activation's work, saying whether it has ended.
- The answer call (§7:20-§7:21) is refused whole for a label naming no open offer; a take
  writes the offering activation's stop record, as an absorption's is (§4:5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from test_matters import _running, _understood

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    ActivationStop,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.matter_calls import (
    ANSWER_OFFER,
    LOOK_UP_ACTIVATION,
    STOP_ACTIVATION,
    MatterCaller,
    MatterCalls,
    calling,
)
from ai_assistant.orchestration.matters import Matters, NotAsAsked
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.task_scheduler import StillLive
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson, ToolDefinition
    from ai_assistant.orchestration.activation_state import ActivationState

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_A: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_B: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"
_C: Final = "2dab0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33"


def _call(tool: ToolDefinition, **arguments: FrozenJson) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=arguments)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id=f"decision:{tool.capability}", decided_at=_AT
    )
    return ToolCall(request=request, decision=decision)


class _Stops:
    """The Task Manager's stop, recording what it was asked to stop."""

    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def __call__(self, activation_id: str) -> ActivationStop:
        self.stopped.append(activation_id)
        return ActivationStop.STOPPED


def _wired(states: list[ActivationState]) -> tuple[Matters, MatterCalls, _Stops, FakePlanStore]:
    stops = _Stops()
    plans = FakePlanStore(now=lambda: _AT)
    matters = Matters(
        running=lambda: states,
        plans=plans,
        memory=FakeMemoryStore(now=lambda: _AT),
        stop=stops,
        held_input_limit=4,
        in_progress_limit=5,
    )
    return matters, MatterCalls(matters=matters), stops, plans


def _caller(
    state: ActivationState,
    *,
    authority: bool = True,
    running: frozenset[str] = frozenset(),
    waiting: frozenset[str] | None = None,
) -> MatterCaller:
    return MatterCaller(
        state=state,
        users_authority=authority,
        owner_records=True,
        running=running,
        waiting=waiting,
    )


def _episode(activation_id: str) -> str:
    return f"activation:{activation_id}"


# --- the stop call (§4:6-§4:11) ------------------------------------------------------


async def test_a_stop_call_without_the_users_authority_is_refused_and_stops_nothing() -> None:
    """§4:8, §1:5's case: a forward, a reminder or a message of no established author."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    _, calls, stops, _ = _wired([older, asker])
    caller = _caller(asker, authority=False, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, NotDone)
    assert "authority" in answer.reason
    # #3452: planning's rendering says "not done" before the reason, so it never does.
    assert not answer.reason.startswith("not done")
    assert stops.stopped == []
    assert not older.stopped


async def test_a_stop_call_naming_a_label_not_shown_as_running_is_refused_whole() -> None:
    """§4:8, §1:5's case: a label shown for no running activation stops nothing."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    _, calls, stops, _ = _wired([older, asker])
    with calling(_caller(asker)):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, NotDone)
    assert "not shown as running" in answer.reason
    assert stops.stopped == []


async def test_a_waiting_rounds_stop_call_names_only_what_it_waits_on() -> None:
    """§7:26: offered only the stop call, naming an activation it waits on."""
    older, other, asker = (
        _running("a", _A, order=1),
        _running("c", _C, order=3),
        _running("b", _B, order=2),
    )
    _, calls, stops, _ = _wired([older, other, asker])
    caller = _caller(asker, running=frozenset({_A, _C}), waiting=frozenset({_A}))
    with calling(caller):
        refused = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_C)))
        done = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(refused, NotDone)
    assert isinstance(done, ToolResult)
    assert stops.stopped == [_A]


async def test_a_stop_call_naming_an_absorbed_activation_is_refused_and_names_its_absorber() -> (
    None
):
    """§4:9, §1:5's case: refused, stopping nothing, and not followed forward."""
    older = _running("a", _A, order=1)
    absorber = _running("c", _C, order=3)
    asker = _running("b", _B, order=2)
    matters, calls, stops, _ = _wired([older, absorber, asker])
    _understood(older)
    matters.merge(absorber, _understood(absorber, _A), at=_AT)
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, NotDone)
    assert "absorbed" in answer.reason
    (shown,) = caller.shown.values()
    assert shown.absorbed_by == _C
    assert stops.stopped == [], "the absorber is not stopped in its place"


async def test_a_stop_call_naming_work_stopped_since_it_was_shown_stops_nothing() -> None:
    """§4:10: its result says so; the stop is asked again, which writes any lost record."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    _, calls, stops, _ = _wired([older, asker])
    older.stop()
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.SUCCEEDED
    (shown,) = caller.shown.values()
    assert (shown.stopped, shown.ended) == (False, True)
    assert stops.stopped == [_A], "ADR-0297 §3:7: a repeated stop retries the record"


async def test_a_stop_whose_record_cannot_be_written_is_not_done_in_full_and_retried() -> None:
    """ADR-0297 §3:7: the mark holds it; the call says so, and asking again writes it."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    attempts: list[str] = []

    async def failing_once(activation_id: str) -> ActivationStop:
        attempts.append(activation_id)
        older.stop()
        if len(attempts) == 1:
            msg = "the plan store is unavailable"
            raise PlanningError(msg)
        return ActivationStop.STOPPED

    matters, calls, _, _ = _wired([older, asker])
    matters._stop = failing_once  # the Task Manager's stop, its first record write failing
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        first = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
        again = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(first, NotDone)
    assert "could not be recorded" in first.reason
    assert isinstance(again, ToolResult)
    assert attempts == [_A, _A], "the second call wrote what the first could not"


async def test_a_stop_call_runs_the_task_managers_stop_and_shows_the_work() -> None:
    """§4:7, §4:11: the one stop, and its result the activation's work."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    _, calls, stops, _ = _wired([older, asker])
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, ToolResult)
    assert stops.stopped == [_A]
    (shown,) = caller.shown.values()
    assert shown.stopped is True
    assert shown.activation_id == _A


async def test_a_call_with_no_caller_or_malformed_arguments_is_not_done() -> None:
    older = _running("a", _A, order=1)
    _, calls, stops, _ = _wired([older])
    assert isinstance(await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A))), NotDone)
    with calling(_caller(older, running=frozenset({_A}))):
        # A label maps to its episode's id; anything else names no activation.
        assert isinstance(await calls.run(_call(STOP_ACTIVATION, activation=_A)), NotDone)
    assert stops.stopped == []


# --- the look-up (§6:1, §6:5-§6:6) ---------------------------------------------------


async def test_a_look_up_naming_a_label_not_shown_as_running_runs_nothing() -> None:
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    _, calls, _, _ = _wired([older, asker])
    caller = _caller(asker)
    with calling(caller):
        answer = await calls.run(_call(LOOK_UP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, NotDone)
    assert caller.shown == {}


async def test_a_look_up_shows_the_work_and_whether_it_has_ended() -> None:
    """§6:5-§6:6: a running one's work, and an ended one's saying it has ended."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    states = [older, asker]
    _, calls, _, _ = _wired(states)
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        running = await calls.run(_call(LOOK_UP_ACTIVATION, activation=_episode(_A)))
        states.remove(older)
        ended = await calls.run(_call(LOOK_UP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(running, ToolResult)
    assert isinstance(ended, ToolResult)
    assert [one.ended for one in caller.shown.values()] == [True], (
        "one decision, read again: the latest says it has ended"
    )


# --- the answer call (§7:20-§7:21) -------------------------------------------------


async def test_an_answer_naming_no_open_offer_is_refused_whole() -> None:
    older = _running("a", _A, order=1)
    _, calls, _, _ = _wired([older])
    with calling(_caller(older)):
        answer = await calls.run(_call(ANSWER_OFFER, offer=_episode(_B), take=True))
    assert isinstance(answer, NotDone)
    assert "no offer" in answer.reason


async def test_a_take_writes_the_offering_activations_stop_record() -> None:
    """§7:21, §4:5: after the step, internal, with no cascade."""
    older = _running("a", _A, order=1)
    older.committed = True
    newer = _running("a", _B, order=2)
    matters, calls, stops, plans = _wired([older, newer])
    matters.merge(newer, _understood(newer, _A), at=_AT)
    caller = _caller(older)
    with calling(caller):
        answer = await calls.run(_call(ANSWER_OFFER, offer=_episode(_B), take=True))
    assert isinstance(answer, ToolResult)
    assert answer.output == {"kind": "matter_answer", "answered": "taken"}
    held = await plans.export()
    assert _B in held.stopped_activations
    assert stops.stopped == [], "the take's stop is internal, not the Task Manager's"
    (shown,) = caller.shown.values()
    assert shown.answered == "taken"


async def test_a_decline_carries_its_reason() -> None:
    older = _running("a", _A, order=1)
    older.committed = True
    newer = _running("a", _B, order=2)
    matters, calls, _, _ = _wired([older, newer])
    matters.merge(newer, _understood(newer, _A), at=_AT)
    with calling(_caller(older)):
        answer = await calls.run(
            _call(ANSWER_OFFER, offer=_episode(_B), take=False, reason="already booked")
        )
    assert isinstance(answer, ToolResult)
    assert answer.output == {
        "kind": "matter_answer",
        "answered": "declined",
        "reason": "already booked",
    }
    assert newer.declined == ((_A, "already booked"),)


@pytest.mark.parametrize(
    ("case", "take", "why"),
    [
        ("open", True, None),
        ("open", False, None),
        ("at_the_limit", True, NotAsAsked.AT_LIMIT),
        ("withdrawn", True, NotAsAsked.STOPPED),
        ("withdrawn", False, NotAsAsked.STOPPED),
        ("no_offer", True, NotAsAsked.NO_OFFER),
        ("no_offer", False, NotAsAsked.NO_OFFER),
    ],
)
async def test_an_answer_is_held_as_asked_only_where_it_came_to_what_it_asked(
    case: str, *, take: bool, why: NotAsAsked | None
) -> None:
    """ADR-0352 §4:2-§4:3: a take to a take, a decline to the decline, and nothing else.

    Each answer that did not is held with why, for acting's held-back reason, and one
    that ran is shown to planning with it (ADR-0349 §7:23).
    """
    older = _running("a", _A, order=1)
    older.committed = True
    newer = _running("a", _B, order=2)
    matters, calls, _, _ = _wired([older, newer])
    if case != "no_offer":
        matters.merge(newer, _understood(newer, _A), at=_AT)
    if case == "at_the_limit":
        matters.held_input_limit = 1
    if case == "withdrawn":
        newer.stop()
    caller = _caller(older)
    arguments: dict[str, FrozenJson] = {"offer": _episode(_B), "take": take}
    if not take:
        arguments["reason"] = "not this work's"
    with calling(caller):
        await calls.run(_call(ANSWER_OFFER, **arguments))
    assert caller.as_asked == ({"decision:answer_offer"} if why is None else set())
    assert caller.not_as_asked == ({} if why is None else {"decision:answer_offer": why})
    shown = caller.shown.get("decision:answer_offer")
    if case == "no_offer":
        assert shown is None, "refused whole, so no result to show"
    else:
        assert shown is not None
        assert shown.not_as_asked is why
        assert shown.meaning == "reading 1"


async def test_a_stop_whose_findings_cannot_be_read_is_still_done() -> None:
    """§4:11: what the call did happened, whatever the read after it found."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    matters, calls, stops, _ = _wired([older, asker])

    async def unreadable(activation_id: str, *, owner_records: bool) -> None:
        del activation_id, owner_records
        msg = "the memory store is unavailable"
        raise MemoryStoreError(msg)

    matters.peer = unreadable  # type: ignore[method-assign]  # the read fails, once stopped
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
        refused = await calls.run(_call(LOOK_UP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.SUCCEEDED
    assert stops.stopped == [_A]
    assert isinstance(refused, NotDone), "a look-up is its read, so its failure is the call's"


# --- what the stopped work set up (ADR-0352 §3:1-§3:2) -------------------------------


class _SetUp:
    """The engine's read of what a stopped activation set up, recording when it ran."""

    def __init__(self, stops: _Stops) -> None:
        self._stops = stops
        self.asked: list[tuple[str, str, str | None, tuple[str, ...]]] = []

    async def __call__(
        self, activation_id: str, /, *, person: str, viewer: str | None, supply: object
    ) -> StillLive:
        del supply
        self.asked.append((activation_id, person, viewer, tuple(self._stops.stopped)))
        return StillLive(more_tasks=1)


def _wired_with_set_up(
    states: list[ActivationState],
) -> tuple[MatterCalls, _Stops, _SetUp]:
    stops = _Stops()
    set_up = _SetUp(stops)
    matters = Matters(
        running=lambda: states,
        plans=FakePlanStore(now=lambda: _AT),
        memory=FakeMemoryStore(now=lambda: _AT),
        stop=stops,
        held_input_limit=4,
        in_progress_limit=5,
        set_up=set_up,
    )
    return MatterCalls(matters=matters), stops, set_up


async def test_a_stop_calls_result_reads_what_the_work_set_up_once_it_is_stopped() -> None:
    """ADR-0352 §3:1-§3:2: read after the stop's record, for the caller's person."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    calls, stops, set_up = _wired_with_set_up([older, asker])
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, ToolResult)
    ((named, person, viewer, stopped_then),) = set_up.asked
    assert (named, viewer) == (_A, _B)
    assert person
    assert stopped_then == (_A,), "the read is made once the stop is written"
    (shown,) = caller.shown.values()
    assert shown.set_up == StillLive(more_tasks=1)
    assert stops.stopped == [_A]


async def test_a_stop_call_finding_the_work_ended_still_reads_what_it_set_up() -> None:
    """ADR-0352 §3:1: or found it ended or stopped, the result lists the same."""
    asker = _running("b", _B, order=2)
    calls, stops, set_up = _wired_with_set_up([asker])
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        answer = await calls.run(_call(STOP_ACTIVATION, activation=_episode(_A)))
    assert isinstance(answer, ToolResult)
    assert stops.stopped == []
    ((named, _, _, _),) = set_up.asked
    assert named == _A
    (shown,) = caller.shown.values()
    assert shown.stopped is False
    assert shown.set_up is not None


async def test_a_look_up_reads_nothing_of_what_the_work_set_up() -> None:
    """ADR-0352 §3:1 is the stop call's result alone."""
    older, asker = _running("a", _A, order=1), _running("b", _B, order=2)
    calls, _, set_up = _wired_with_set_up([older, asker])
    caller = _caller(asker, running=frozenset({_A}))
    with calling(caller):
        await calls.run(_call(LOOK_UP_ACTIVATION, activation=_episode(_A)))
    assert set_up.asked == []
    (shown,) = caller.shown.values()
    assert shown.set_up is None


def test_the_stop_calls_declaration_is_the_routed_text() -> None:
    """ADR-0352 §3:9-§3:10: it stops that work alone, and its result lists what is live.

    ADR-0357 §7:1: ADR-0352 §3:8's line, that a stop reaches only what the person's words
    cover, is said in this description, not in planning's instruction.
    """
    assert STOP_ACTIVATION.description == (
        "Stop running work you were shown as running, and that work alone. Nothing it "
        "already did is undone, and what it set up stays. The result shows what it "
        "had finished and what it set up that is still live, so say that. Stop work "
        'only where the person asks for it, such as "never mind the booking" after it '
        "has booked, or means to take over work this work waits on. Stop exactly what "
        "their words cover, including what a stop's result lists, and keep the rest; "
        "where it is unclear what the words cover, ask which."
    )
