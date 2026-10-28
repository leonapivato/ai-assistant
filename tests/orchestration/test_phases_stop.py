"""Stopping an activation the phases run, through the engine (ADR-0297, ADR-0295 §3).

``test_engine_stop`` drives these cases through today's table. A stop that lands mid
round is ``test_engine_phases``'s; each case here is one of the others run with the
phases wired, so it stays pinned once the switch lands: a stop whose record cannot be
written still ends the activation stopped, a stop naming an ended or unknown activation
writes nothing, and a correction after a stop starts its own activation.
"""

from __future__ import annotations

import asyncio

import pytest
from phases_support import (
    SETTLE,
    Gated,
    chat_turn,
    episodes,
    idle,
    open_conversation,
    phases_harness,
    said,
    stopped,
    until,
    working,
    written,
)
from test_engine import AT

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    MessageAuthor,
    RoundResponse,
)
from ai_assistant.orchestration.conversations import activation_ending
from ai_assistant.testing import FakePlanStore


class _RefusingStops(FakePlanStore):
    """A plan store whose stop record cannot be written."""

    async def record_stop(self, activation_id: str, /) -> None:
        del activation_id
        msg = "the plan store cannot be written"
        raise PlanningError(msg)


async def test_a_stop_whose_record_fails_raises_and_its_mark_stays_set() -> None:
    """§3:7: the stop raises the store's error, and the activation still ends stopped."""
    completer = Gated(RoundResponse(text="Working on it."))
    plans = _RefusingStops(now=lambda: AT)
    harness = phases_harness(completer, plans=plans)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    with pytest.raises(PlanningError, match="cannot be written"):
        await harness.engine.stop_activation(running)
    completer.release.set()
    await idle(harness, conversation)

    assert (await plans.export()).stopped_activations == ()
    (episode,) = await episodes(harness.memory)
    stopped(episode)
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.STOPPED


async def test_already_ended_and_no_such_activation_each_write_nothing() -> None:
    """§5:4-§5:5: neither marks, neither writes a stop record, neither moves an episode."""
    harness = phases_harness()
    _, episode = await chat_turn(harness, "hi")
    before = await episodes(harness.memory)
    assert episode.processing_record is not None
    plans_before = await harness.plans.export()

    ended = await harness.engine.stop_activation(episode.processing_record.activation_id)
    unknown = await harness.engine.stop_activation("0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11")

    assert (ended, unknown) == (ActivationStop.ALREADY_ENDED, ActivationStop.NO_SUCH_ACTIVATION)
    assert await episodes(harness.memory) == before
    after = await harness.plans.export()
    assert after.stopped_activations == ()
    assert after.model_dump(exclude={"exported_at"}) == plans_before.model_dump(
        exclude={"exported_at"}
    )


async def test_a_correction_after_a_stop_starts_its_own_activation() -> None:
    """ADR-0295 §3:6: a stop holds nothing back; the correction is answered after it.

    No place waits (ADR-0349 §8:1): the correction starts its own activation once its
    start wait has passed, whatever still runs on the place, and is taken in by it.
    """
    completer = Gated(RoundResponse(text="Saturday it is."), RoundResponse(text="Sunday it is."))
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book it Saturday"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    await harness.engine.write_message(conversation, message=said("m-2", "actually Sunday"))
    completer.release.set()

    async def both_frozen() -> bool:
        found = await episodes(harness.memory)
        return len(found) == 2 and all(
            one.processing_record is not None and not one.processing_record.is_open for one in found
        )

    await until(both_frozen, what="both activations to end")
    await idle(harness, conversation)

    messages = [(one.author, one.text) for one in await written(harness, conversation)]
    assert messages[:2] == [
        (MessageAuthor.USER, "book it Saturday"),
        (MessageAuthor.USER, "actually Sunday"),
    ]
    assert messages[-1] == (MessageAuthor.ASSISTANT, "Sunday it is.")
    ended = await episodes(harness.memory)
    (first,) = [
        one
        for one in ended
        if one.processing_record is not None and one.processing_record.activation_id == running
    ]
    stopped(first)
    (second,) = [one for one in ended if one is not first]
    assert activation_ending(second) is ActivationEnding.DONE
    # Each message was taken in by the activation that ran on it, and nothing waits.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken[1] == running
    assert taken[2] == second.id.removeprefix("activation:")
    assert await harness.conversation_store.untaken_messages(conversation) == ()
