"""ADR-0364 §9:1-§9:4 for an activation the Task Scheduler started: where a text goes.

End to end over the engine, the phases and the Task Scheduler's fakes: a person's
activation spawns a task suggesting their conversation, and the task's activation sends
a ``send_text`` call naming a connection by its ``L`` label. A task's work keeps its
list: it speaks only in the connections its task suggests and the line (§9:4).
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

#: Which connection a case's text names: the first its task suggests, the stimulus's own
#: origin, the schedule, or a label it was never shown.
_FIRST, _ORIGIN = "first place", "origin"


def _texting(connection: str) -> Callable[[_Request], RoundResponse]:
    """The task's activation: one ``send_text`` call in its first round, then nothing."""

    def task(request: _Request) -> RoundResponse:
        if request.rounds:
            return RoundResponse()
        if connection == _FIRST:
            named = _first_place(request)
        elif connection == _ORIGIN:
            origin = request.origin
            assert origin is not None
            named = str(origin.get("label"))
        else:
            named = connection
        return RoundResponse(
            calls=(
                ProposedCall(
                    call_id="t1",
                    name="send_text",
                    arguments={"connection": named, "words": "hello from the schedule"},
                ),
            )
        )

    return task


async def test_a_tasks_text_goes_into_the_connection_its_task_suggests_by_its_label() -> None:
    """§9:1, §9:4: by label, into a connection its task suggests."""
    completer = _responder(_spawning(connections=_FIRST), _texting(_FIRST))
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
    ("connection", "says"),
    [
        pytest.param("L9", "'L9' names no connection you were shown", id="a-label-never-shown"),
        pytest.param(_ORIGIN, "takes no text message", id="the-schedule"),
    ],
)
async def test_a_tasks_text_naming_no_connection_it_may_speak_in_comes_back_refused(
    connection: str, says: str
) -> None:
    """§9:2: it runs nothing, and comes back refused with the connections it may name."""
    completer = _responder(_spawning(connections=_FIRST), _texting(connection))
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
        assert "the connections it may name: L" in entry.reason
    finally:
        await harness.engine.aclose()
