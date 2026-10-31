"""ADR-0357 §2:4 for an activation the Task Scheduler started: where a ``text`` call goes.

End to end over the engine, the phases and the Task Scheduler's fakes: a person's
activation spawns a task suggesting their conversation, and the task's activation sends
a ``text`` call naming its place by label, by platform or not at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from phases_support import open_conversation, phases_harness, said, until, written
from task_support import seams
from test_phases_task_scheduler import (
    _first_place,
    _Request,
    _responder,
    _spawning,
    _until_scheduled,
)

from ai_assistant.core.types import CallOutcomeKind, MessageAuthor, ProposedCall, RoundResponse
from ai_assistant.orchestration.chat import COULDNT_FINISH

if TYPE_CHECKING:
    from collections.abc import Callable


def _texting(**via: str) -> Callable[[_Request], RoundResponse]:
    """The task's activation: one ``text`` call in its first round, then nothing."""

    def task(request: _Request) -> RoundResponse:
        if request.rounds:
            return RoundResponse()
        named = {
            key: _first_place(request) if value == "first place" else value
            for key, value in via.items()
        }
        return RoundResponse(
            calls=(
                ProposedCall(
                    call_id="t1",
                    name="text",
                    arguments={"to": "the user", "words": "hello from the schedule", **named},
                ),
            )
        )

    return task


@pytest.mark.parametrize(
    "via",
    [
        pytest.param({}, id="naming-none-goes-to-the-one-place-its-task-suggests"),
        pytest.param({"via": "first place"}, id="by-its-label"),
        pytest.param({"via": "hub_chat"}, id="by-its-platform"),
    ],
)
async def test_a_tasks_text_goes_into_the_place_it_names_or_its_task_suggests(
    via: dict[str, str],
) -> None:
    """§2:4: left out, the one place its task suggests; named, by label or platform."""
    completer = _responder(_spawning(places="first place"), _texting(**via))
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        (episode,) = await _until_scheduled(harness, 1)

        async def spoken() -> bool:
            return any(
                one.author is MessageAuthor.ASSISTANT and one.text == "hello from the schedule"
                for one in await written(harness, conversation)
            )

        await until(spoken, what="the task's message")
        assert episode.processing_record is not None
        (entry,) = [one for one in episode.processing_record.call_records if one.call_id == "t1"]
        assert entry.outcome is CallOutcomeKind.DONE
        assert entry.delivered is not None
        assert entry.delivered.went.instance_id == conversation
    finally:
        await harness.engine.aclose()


@pytest.mark.parametrize(
    ("via", "says"),
    [
        pytest.param({"via": "L9"}, "'L9' names no place you were shown", id="a-label-off-it"),
        pytest.param({"via": "telegram"}, "no place on your list is on Telegram", id="a-platform"),
    ],
)
async def test_a_tasks_text_naming_nowhere_on_its_list_comes_back_with_its_places(
    via: dict[str, str], says: str
) -> None:
    """§2:4, §6:2: it runs nothing, and comes back with the places it may name."""
    completer = _responder(_spawning(places="first place"), _texting(**via))
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        (episode,) = await _until_scheduled(harness, 1)

        async def told() -> bool:
            return any(one.text == COULDNT_FINISH for one in await written(harness, conversation))

        await until(told, what="the task's couldn't finish")
        texts = [one.text for one in await written(harness, conversation)]
        assert "hello from the schedule" not in texts
        assert episode.processing_record is not None
        (entry,) = [one for one in episode.processing_record.call_records if one.call_id == "t1"]
        assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
        assert entry.reason is not None
        assert says in entry.reason
        assert "the places it may name: L1 (the hub chat)" in entry.reason
    finally:
        await harness.engine.aclose()
