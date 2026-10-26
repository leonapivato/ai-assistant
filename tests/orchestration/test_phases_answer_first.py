"""An offer's answer settles before the round acts, through the engine (ADR-0352 §4).

Each case drives whole passes of the hub chat's activations with the phases wired, over
the routed models of ``test_phases_matters``: understanding names in ``continues`` every
in-progress entry whose input holds a word the input lists after ``continues:``, and
planning answers each input's rounds from its own script.

An older activation that has acted is offered newer input on its own place, and its
round answers the offer beside a spawn (ADR-0349 §7:17-§7:22). Acting runs the answer
first and alone (§4:1):

- where a take does not come to a take, refused at ``held_input_limit``, withdrawn, or
  naming no open offer, nothing else of the round that is not a pure read is dispatched,
  and not its message; planning runs a round again, shown what the answer came to, and
  each held-back call as not done (§4:2);
- where every answer came to what it asked, a take or the decline planning chose, the
  rest of the round is dispatched (§4:3), and only once the take has landed.

These are ADR-0352 §7:7's cases.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from phases_support import SETTLE, open_conversation, until
from task_support import seams
from test_phases_matters import (
    _acted_on_one_place,
    _assistant,
    _beside,
    _call,
    _frozen,
    _harness,
    _has,
    _of,
    _Planner,
    _start,
    _Understanding,
)

from ai_assistant.core.types import RoundResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from test_engine import Harness

    from ai_assistant.orchestration.activation_state import ActivationState

#: Why a call of a round whose answer did not come to what it asked was not done, in part.
_NOT_TAKEN: Final = "did not come to what it asked"
#: A decline's reason at ``held_input_limit`` (ADR-0349 §7:22).
_LIMIT_REACHED: Final = "it already holds as much input as it may"
#: What a refusal at the limit tells the older's planning, in part (#3471).
_AT_LIMIT: Final = "this work already holds as much input as it may"
#: What a withdrawal tells the older's planning, after the offering work's name (#3477).
_WITHDRAWN: Final = (
    " was stopped before the answer, so the input it carried is no longer asked for, and "
    "the work that input asked for is not to be done"
)


def _state(harness: Harness, activation_id: str) -> ActivationState | None:
    return next(
        (
            one.state
            for one in harness.engine._running
            if one.state is not None and one.state.activation_id == activation_id
        ),
        None,
    )


async def _offered(harness: Harness, older: str, count: int = 1) -> None:
    """Wait until ``count`` offers are open to ``older``."""

    async def made() -> bool:
        state = _state(harness, older)
        return state is not None and len(state.offers) >= count

    await until(made, what=f"{count} offer(s) to be made")


def _offer_label(request: dict[str, Any], words: str) -> str:
    """The label of the offer whose input holds ``words``, or of the only one open.

    An offering activation that has ended is shown with no input, so the only offer
    open is named whatever it shows.
    """
    offers = list(request.get("offers") or ())
    if len(offers) == 1:
        return str(offers[0]["offer"])
    for one in offers:
        if words in str(one.get("input")):
            return str(one["offer"])
    msg = f"no offer holding {words!r}"
    raise AssertionError(msg)


def _answer_and_spawn(
    *answers: tuple[str, bool], text: str = "Changed it to 9 PM."
) -> Callable[[dict[str, Any]], RoundResponse]:
    """A round answering each offer named by its input's words, beside a spawn."""

    def reply(request: dict[str, Any]) -> RoundResponse:
        calls = [
            _call(
                f"a{index}",
                "answer_offer",
                offer=_offer_label(request, words),
                take=take,
                **({} if take else {"reason": "not this work's"}),
            )
            for index, (words, take) in enumerate(answers, 1)
        ]
        calls.append(_call("s1", "spawn", instruction="Remind them at 9 PM.", delay_minutes=60))
        return RoundResponse(text=text, calls=tuple(calls))

    return reply


def _older_script(planner: _Planner, older_text: str, answering: Any) -> None:
    """The older's rounds: it acts, a round the offer holds back, the answer, a reply."""
    planner.script(
        older_text,
        RoundResponse(
            text="Reminder set for 9:30 PM.",
            calls=(
                _call("c1", "remember", fact="Takes vitamins.", why="a habit", rests_on_input=True),
            ),
        ),
        # Planned before the offer, so held back by ADR-0349 §7:14 and never written.
        RoundResponse(text="Still working."),
        answering,
        RoundResponse(text="Your reminder stays at 9:30 PM for now."),
    )
    planner.hold(older_text, from_round=2)


async def _started(understanding: _Understanding, planner: _Planner, **knobs: Any) -> Harness:
    harness = _harness(understanding, planner, task_scheduler=seams(), **knobs)
    await harness.engine.start()
    return harness


def _round_shown(planner: _Planner, older_text: str, number: int) -> dict[str, Any]:
    """Round ``number`` of the older, as its round after it was shown it."""
    later = planner.requests[older_text][number]
    return dict(later["rounds"][number - 1])


def _answers(shown: dict[str, Any]) -> list[str]:
    return [
        str(one["result"]["value"]["answer"])
        for one in shown["calls"]
        if one["capability"] == "answer_offer"
    ]


def _answer_values(shown: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(one["result"]["value"])
        for one in shown["calls"]
        if one["capability"] == "answer_offer"
    ]


def _spawn_outcome(shown: dict[str, Any]) -> str:
    (spawn,) = [one for one in shown["calls"] if one["capability"] == "spawn"]
    return str(spawn.get("outcome"))


# --- §4:2: a take that did not come to a take holds the round back ------------------------


async def test_a_take_refused_at_the_limit_dispatches_no_spawn_and_no_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's first case, #3463's run: the older holds one input and is offered two."""
    understanding, planner = _Understanding(), _Planner()
    older_text = "remind me about vitamins at 9:30"
    maths, newer_text = "what's 12 squared?", "make it 9pm, continues: squared, vitamins"
    _older_script(planner, older_text, _answer_and_spawn(("squared", True)))
    planner.hold(maths)
    harness = await _started(understanding, planner, held_input_limit=2)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    _, _ = await _beside(harness, conversation, maths, message_id="b-1")
    await asyncio.wait_for(planner.hold(maths)[0].wait(), SETTLE)

    # The newer absorbs the maths question, which has not acted, and so holds two
    # inputs, which it offers to the older, which holds one (ADR-0349 §7:4, §7:17).
    _, newer_done = await _beside(harness, conversation, newer_text, message_id="c-1")
    await _offered(harness, older)
    state = _state(harness, older)
    assert state is not None
    (offer,) = state.offers.values()
    assert len(offer.inputs) == 2
    planner.hold(maths)[1].set()
    planner.hold(older_text)[1].set()
    await newer_done
    found = await _frozen(harness, 3)

    assert await harness.plans.spawned_tasks([older]) == (), "the spawn was never dispatched"
    said = await _assistant(harness, conversation)
    assert "Changed it to 9 PM." not in said, "the answering round wrote no message"
    assert "Your reminder stays at 9:30 PM for now." in said
    assert _of(found, older).joined == (), "nothing was taken"
    shown = _round_shown(planner, older_text, 3)
    assert _answers(shown) == ["declined"]
    (value,) = _answer_values(shown)
    assert _AT_LIMIT in value["because"], "#3471: the next round is told why"
    assert value["episode"] in value["because"], "naming the offering work by its label"
    assert _NOT_TAKEN in _spawn_outcome(shown)
    assert _AT_LIMIT in _spawn_outcome(shown), "the held-back call says what it came to"
    assert _NOT_TAKEN in shown["text_was"]
    assert len(planner.requests[older_text]) == 4, "planning ran a round again"
    (waited,) = planner.requests[newer_text][0]["waiting_on"]
    assert waited["declined_this_input"] == _LIMIT_REACHED
    await harness.engine.aclose()


async def test_a_take_of_an_offer_withdrawn_dispatches_no_spawn_and_no_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's second case: the offering activation is stopped between offer and answer."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"
    _older_script(planner, older_text, _answer_and_spawn(("9pm", True)))
    harness = await _started(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)
    await harness.engine.stop_activation(newer)
    await newer_done
    planner.hold(older_text)[1].set()
    found = await _frozen(harness, 2)

    assert await harness.plans.spawned_tasks([older]) == ()
    assert await _assistant(harness, conversation) == [
        "Reminder set for 9:30 PM.",
        "Your reminder stays at 9:30 PM for now.",
    ]
    assert _of(found, older).joined == ()
    shown = _round_shown(planner, older_text, 3)
    assert _answers(shown) == ["withdrawn"]
    (value,) = _answer_values(shown)
    assert value["because"] == value["episode"] + _WITHDRAWN, (
        "#3477: the next round is told the offering work was stopped, by its label, and "
        "that the work its input asked for is not to be done"
    )
    assert value["understood_as"] == newer_text, "the stopped input is named"
    assert _NOT_TAKEN in _spawn_outcome(shown)
    assert _WITHDRAWN in _spawn_outcome(shown), "the held-back call says what it came to"
    assert newer_text not in planner.requests, "the stopped input's work is not done"
    await harness.engine.aclose()


async def test_two_answers_one_taken_and_one_refused_dispatch_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's fifth case: at a limit of three, whichever take lands second is refused.

    The older holds one input and is offered one by the first newer, and two by the
    second, which absorbed a question that had not acted. One take lands, the other is
    refused at the limit, in either order, and the spawn beside them is not dispatched.
    """
    understanding, planner = _Understanding(), _Planner()
    older_text = "remind me about vitamins at 9:30"
    first_text = "at the kitchen, continues: vitamins"
    maths, second_text = "what's 12 squared?", "make it 9pm, continues: squared, 9:30"
    _older_script(planner, older_text, _answer_and_spawn(("kitchen", True), ("squared", True)))
    planner.hold(maths)
    harness = await _started(understanding, planner, held_input_limit=3)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    _, first_done = await _beside(harness, conversation, first_text, message_id="b-1")
    await _offered(harness, older)
    _, _ = await _beside(harness, conversation, maths, message_id="c-1")
    await asyncio.wait_for(planner.hold(maths)[0].wait(), SETTLE)
    _, second_done = await _beside(harness, conversation, second_text, message_id="d-1")
    await _offered(harness, older, 2)
    planner.hold(maths)[1].set()
    planner.hold(older_text)[1].set()
    await first_done
    await second_done
    await _frozen(harness, 4)

    assert await harness.plans.spawned_tasks([older]) == ()
    shown = _round_shown(planner, older_text, 3)
    assert sorted(_answers(shown)) == ["declined", "taken"]
    assert [("because" in one) for one in _answer_values(shown)].count(True) == 1
    assert _NOT_TAKEN in _spawn_outcome(shown)
    assert _AT_LIMIT in _spawn_outcome(shown)
    assert "Changed it to 9 PM." not in await _assistant(harness, conversation)
    await harness.engine.aclose()


async def test_an_answer_naming_no_open_offer_dispatches_no_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's sixth case: refused whole (ADR-0349 §7:20), so nothing else is dispatched.

    The answer names an episode the round was shown, which is no offer open to it: an
    earlier one of the conversation, in the episode window.
    """
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"

    def misnamed(request: dict[str, Any]) -> RoundResponse:
        (earlier,) = request["episode_window"]
        return RoundResponse(
            text="Changed it to 9 PM.",
            calls=(
                _call("a1", "answer_offer", offer=str(earlier["label"]), take=True),
                _call("s1", "spawn", instruction="Remind them at 9 PM.", delay_minutes=60),
            ),
        )

    _older_script(planner, older_text, misnamed)
    harness = await _started(understanding, planner)
    phases = harness.engine._phases
    assert phases is not None
    monkeypatch.setattr(phases, "_round_limit", 6)
    await open_conversation(harness)
    conversation, _ = await _start(harness, "hello there", message_id="a-0")
    await _frozen(harness, 1)
    older, _ = await _beside(harness, conversation, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the older to act and plan again")
    _, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)
    planner.hold(older_text)[1].set()
    await newer_done
    await _frozen(harness, 3)

    assert await harness.plans.spawned_tasks([older]) == ()
    assert "Changed it to 9 PM." not in await _assistant(harness, conversation)
    shown = _round_shown(planner, older_text, 3)
    (answer,) = [one for one in shown["calls"] if one["capability"] == "answer_offer"]
    assert "names no offer open" in str(answer["outcome"])
    assert _NOT_TAKEN in _spawn_outcome(shown)
    assert "names no offer open to this work" in _spawn_outcome(shown)
    assert "offers" in planner.requests[older_text][3], "the offer is still open to answer"
    await harness.engine.aclose()


async def test_an_answer_planning_refused_before_acting_dispatches_no_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4:2: an answer that never reached acting came to no take, so nothing else runs.

    It names a label the round was never shown, which planning refuses whole (ADR-0307
    §5:3), so the round's allowed calls hold no answer at all.
    """
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"
    _older_script(
        planner,
        older_text,
        RoundResponse(
            text="Changed it to 9 PM.",
            calls=(
                _call("a1", "answer_offer", offer="E99", take=True),
                _call("s1", "spawn", instruction="Remind them at 9 PM.", delay_minutes=60),
            ),
        ),
    )
    harness = await _started(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    _, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)
    planner.hold(older_text)[1].set()
    await newer_done
    await _frozen(harness, 2)

    assert await harness.plans.spawned_tasks([older]) == ()
    assert "Changed it to 9 PM." not in await _assistant(harness, conversation)
    shown = _round_shown(planner, older_text, 3)
    (answer,) = [one for one in shown["calls"] if one["capability"] == "answer_offer"]
    assert "result" not in answer, "it never ran"
    assert _NOT_TAKEN in _spawn_outcome(shown)
    assert "it was not allowed, so it settled nothing" in _spawn_outcome(shown)
    assert _NOT_TAKEN in shown["text_was"]
    await harness.engine.aclose()


async def test_a_stop_landing_while_the_answer_runs_dispatches_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0295 §2:1, ADR-0349 §7:14: the take lands, then the stop, then nothing starts.

    The take's stop record is held until the older is stopped, so the round's spawn and
    message would be dispatched after the stop were the stop mark not read again. Every
    spawn the round attempts is recorded, so one the store would refuse on the stop
    record still shows.
    """
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"
    _older_script(planner, older_text, _answer_and_spawn(("9pm", True)))
    harness = await _started(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)

    attempted: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()
    write, record_stop = harness.plans.write_scheduled_task, harness.plans.record_stop

    async def spawn_probe(*args: Any, **kwargs: Any) -> Any:
        attempted.append("spawn")
        return await write(*args, **kwargs)

    async def stop_probe(activation_id: str, /) -> None:
        if activation_id == newer:
            entered.set()
            await release.wait()
        await record_stop(activation_id)

    monkeypatch.setattr(harness.plans, "write_scheduled_task", spawn_probe)
    monkeypatch.setattr(harness.plans, "record_stop", stop_probe)
    planner.hold(older_text)[1].set()
    await asyncio.wait_for(entered.wait(), SETTLE)
    await harness.engine.stop_activation(older)
    release.set()
    await newer_done
    found = await _frozen(harness, 2)

    assert attempted == [], "nothing of the round was dispatched after the stop"
    assert "Changed it to 9 PM." not in await _assistant(harness, conversation)
    assert [one.taken_over_from for one in _of(found, older).joined] == [newer], (
        "what the answer did happened"
    )
    await harness.engine.aclose()


# --- §4:3: every answer came to what it asked, so the rest runs --------------------------


async def test_a_take_that_lands_dispatches_the_spawn_only_once_it_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's third case, with an ordering probe: the spawn is written after the take.

    The take's stop record, the last write the answer awaits (ADR-0349 §7:21), is slowed,
    so a spawn dispatched beside the answer, rather than after it, would be written first.
    """
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"
    _older_script(planner, older_text, _answer_and_spawn(("9pm", True)))
    harness = await _started(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)

    order: list[str] = []
    write, record_stop = harness.plans.write_scheduled_task, harness.plans.record_stop

    async def spawn_probe(*args: Any, **kwargs: Any) -> Any:
        state = _state(harness, older)
        order.append(f"spawn, holding {-1 if state is None else state.inputs_held}")
        return await write(*args, **kwargs)

    async def stop_probe(activation_id: str, /) -> None:
        await asyncio.sleep(0.05)
        await record_stop(activation_id)
        order.append("the newer's stop" if activation_id == newer else activation_id)

    monkeypatch.setattr(harness.plans, "write_scheduled_task", spawn_probe)
    monkeypatch.setattr(harness.plans, "record_stop", stop_probe)
    planner.hold(older_text)[1].set()
    await newer_done
    found = await _frozen(harness, 2)

    assert order == ["the newer's stop", "spawn, holding 2"], (
        "the answer ran to its end, its stop record included, before the spawn was written"
    )
    assert len(await harness.plans.spawned_tasks([older])) == 1
    assert [one.taken_over_from for one in _of(found, older).joined] == [newer]
    assert "Changed it to 9 PM." in await _assistant(harness, conversation)
    shown = _round_shown(planner, older_text, 3)
    assert _answers(shown) == ["taken"]
    assert _NOT_TAKEN not in _spawn_outcome(shown)
    await harness.engine.aclose()


async def test_a_decline_planning_chose_dispatches_the_spawn_beside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:7's fourth case: a decline means the input is not this work's, so it runs."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me about vitamins at 9:30", "make it 9pm, continues: vitamins"
    _older_script(planner, older_text, _answer_and_spawn(("9pm", False), text="Set for 9:30 PM."))
    harness = await _started(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    _, newer_done = await _beside(harness, conversation, newer_text, message_id="b-1")
    await _offered(harness, older)
    planner.hold(older_text)[1].set()
    await newer_done
    await _frozen(harness, 2)

    assert len(await harness.plans.spawned_tasks([older])) == 1
    assert "Set for 9:30 PM." in await _assistant(harness, conversation)
    shown = _round_shown(planner, older_text, 3)
    assert _answers(shown) == ["declined"]
    assert _NOT_TAKEN not in _spawn_outcome(shown)
    (waited,) = planner.requests[newer_text][0]["waiting_on"]
    assert waited["declined_this_input"] == "not this work's"
    await harness.engine.aclose()
