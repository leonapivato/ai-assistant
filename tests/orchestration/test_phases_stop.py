"""Stopping an activation the phases run, through the engine (ADR-0297, ADR-0295 §3).

``test_engine_stop`` drives these cases through today's table. A stop that lands mid
round is ``test_engine_phases``'s; each case here is one of the others run with the
phases wired, so it stays pinned once the switch lands: a stop whose record cannot be
written still ends the activation stopped, a stop naming an ended or unknown activation
writes nothing, and what waited behind a stopped activation is then taken in.
"""

from __future__ import annotations

import asyncio

import pytest
from phases_support import PHONE, SETTLE, chat_turn, open_conversation, phases_harness, written
from test_chat_reader import _episodes
from test_engine import AT, Harness
from test_engine_phases import _GatedCompleter
from test_engine_stop import _stopped, _working

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    MessageAuthor,
    RoundResponse,
    UserMessage,
)
from ai_assistant.orchestration.conversations import activation_ending
from ai_assistant.testing import FakePlanStore


class _RefusingStops(FakePlanStore):
    """A plan store whose stop record cannot be written."""

    async def record_stop(self, activation_id: str, /) -> None:
        del activation_id
        msg = "the plan store cannot be written"
        raise PlanningError(msg)


def _said(message_id: str, text: str) -> UserMessage:
    return UserMessage(device_id=PHONE.device_id, message_id=message_id, text=text)


async def _idle(harness: Harness, conversation: str) -> None:
    engine = harness.engine
    deadline = asyncio.get_running_loop().time() + SETTLE
    while True:
        digest = await engine.conversation(conversation)
        if digest is not None and not digest.state.working:
            return
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activation never ended"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def test_a_stop_whose_record_fails_raises_and_its_mark_stays_set() -> None:
    """§3:7: the stop raises the store's error, and the activation still ends stopped."""
    completer = _GatedCompleter(RoundResponse(text="Working on it."), gated=1)
    plans = _RefusingStops(now=lambda: AT)
    harness = phases_harness(completer, plans=plans)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await _working(harness, conversation)

    with pytest.raises(PlanningError, match="cannot be written"):
        await harness.engine.stop_activation(running)
    completer.gate.set()
    await _idle(harness, conversation)

    assert (await plans.export()).stopped_activations == ()
    (episode,) = await _episodes(harness.memory)
    _stopped(episode)
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.STOPPED


async def test_already_ended_and_no_such_activation_each_write_nothing() -> None:
    """§5:4-§5:5: neither marks, neither writes a stop record, neither moves an episode."""
    harness = phases_harness()
    _, episode = await chat_turn(harness, "hi")
    before = await _episodes(harness.memory)
    assert episode.processing_record is not None
    plans_before = await harness.plans.export()

    ended = await harness.engine.stop_activation(episode.processing_record.activation_id)
    unknown = await harness.engine.stop_activation("0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11")

    assert (ended, unknown) == (ActivationStop.ALREADY_ENDED, ActivationStop.NO_SUCH_ACTIVATION)
    assert await _episodes(harness.memory) == before
    after = await harness.plans.export()
    assert after.stopped_activations == ()
    assert after.model_dump(exclude={"exported_at"}) == plans_before.model_dump(
        exclude={"exported_at"}
    )


async def test_what_waited_behind_a_stopped_activation_is_then_taken_in() -> None:
    """ADR-0295 §3:6: a stop holds nothing back; the correction is answered after it."""
    completer = _GatedCompleter(
        RoundResponse(text="Saturday it is."), RoundResponse(text="Sunday it is."), gated=1
    )
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "book it Saturday"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await _working(harness, conversation)
    await harness.engine.write_message(conversation, message=_said("m-2", "actually Sunday"))

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    completer.gate.set()

    deadline = asyncio.get_running_loop().time() + SETTLE
    while len(await _episodes(harness.memory)) < 2 or not all(
        one.processing_record is not None and not one.processing_record.is_open
        for one in await _episodes(harness.memory)
    ):
        assert asyncio.get_running_loop().time() < deadline, "the second never ended"
        await asyncio.sleep(0.001)
    await _idle(harness, conversation)

    said = [(one.author, one.text) for one in await written(harness, conversation)]
    assert said[:2] == [
        (MessageAuthor.USER, "book it Saturday"),
        (MessageAuthor.USER, "actually Sunday"),
    ]
    assert said[-1] == (MessageAuthor.ASSISTANT, "Sunday it is.")
    episodes = await _episodes(harness.memory)
    (first,) = [
        one
        for one in episodes
        if one.processing_record is not None and one.processing_record.activation_id == running
    ]
    _stopped(first)
    (second,) = [one for one in episodes if one is not first]
    assert activation_ending(second) is ActivationEnding.DONE
    # Each message was taken in by the activation that ran on it, and nothing waits.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken[1] == running
    assert taken[2] == second.id.removeprefix("activation:")
    assert await harness.conversation_store.untaken_messages(conversation) == ()
