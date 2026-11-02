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
from test_engine import AT
from test_phases_task_scheduler import (
    _first_place,
    _Request,
    _responder,
    _spawning,
    _until_scheduled,
)

from ai_assistant.core.types import (
    CallOutcomeKind,
    MessageAuthor,
    NewMessage,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH

if TYPE_CHECKING:
    from collections.abc import Callable

#: Which connection a case's text names: the first its task suggests, the stimulus's own
#: origin, the schedule, or a label it was never shown.
_FIRST, _ORIGIN = "first place", "origin"
#: A conversation the task's work was shown that takes a text, which its task does not
#: suggest.
_UNSUGGESTED = "unsuggested"


def _texting(connection: str) -> Callable[[_Request], RoundResponse]:
    """The task's activation: one ``send_text`` call in its first round, then nothing."""

    def task(request: _Request) -> RoundResponse:
        if request.rounds:
            return RoundResponse()
        if connection == _FIRST:
            named = _first_place(request)
        elif connection == _UNSUGGESTED:
            named = next(
                str(one.get("label"))
                for one in request.connections
                if "takes text messages" in str(one.get("can")) and one.get("suggested") is None
            )
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


async def test_a_tasks_text_into_a_shown_conversation_its_task_does_not_suggest_is_refused() -> (
    None
):
    """§9:4: a task's work keeps its list. Another conversation, shown and taking text
    messages, is no connection its task suggests, so nothing goes into it."""
    completer = _responder(_spawning(connections=_FIRST), _texting(_UNSUGGESTED))
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()
    try:
        # Another conversation the person keeps, recent enough to be shown, where no work
        # runs.
        other = await open_conversation(harness)
        await harness.conversation_store.append_message(
            other, NewMessage(author=MessageAuthor.ASSISTANT, text="Good morning.")
        )
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        (episode,) = await _until_scheduled(harness, 1)

        async def told() -> bool:
            # Where the task's work says it couldn't finish is its own origin's to say.
            for place in (other, conversation):
                if any(one.text == COULDNT_FINISH for one in await written(harness, place)):
                    return True
            return False

        await until(told, what="the task's couldn't finish")
        assert episode.processing_record is not None
        (entry,) = [one for one in episode.processing_record.call_records if one.call_id == "t1"]
        assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
        for place in (other, conversation):
            texts = [one.text for one in await written(harness, place)]
            assert "hello from the schedule" not in texts
    finally:
        await harness.engine.aclose()


async def test_a_tasks_work_may_reply_into_the_origin_of_an_input_it_took() -> None:
    """ADR-0364 §9:4, §14:4: a task's work keeps its list, and the list holds the origin
    of each input it took by a take, where it takes a text, beside what its task
    suggests."""
    from types import SimpleNamespace  # noqa: PLC0415

    from task_support import activation, write_task  # noqa: PLC0415

    from ai_assistant.core.types import (  # noqa: PLC0415
        ChannelContext,
        JoinedInput,
        RecordedChannelTrigger,
        RecordedInputMessage,
        RecordedTextInput,
        WholeTextReply,
    )
    from ai_assistant.orchestration.channel_kinds import place_of  # noqa: PLC0415
    from ai_assistant.orchestration.conversations import conversation_channel  # noqa: PLC0415
    from ai_assistant.orchestration.matters import Became, Named  # noqa: PLC0415
    from ai_assistant.orchestration.task_scheduler import SCHEDULE  # noqa: PLC0415
    from ai_assistant.testing.parties import OWNERS_WORDS  # noqa: PLC0415

    harness = phases_harness(task_scheduler=seams())
    await harness.engine.start()
    try:
        suggested = conversation_channel(await open_conversation(harness))
        taken = conversation_channel(await open_conversation(harness))
        task = await write_task(harness.plans, activation(), places=(suggested,))
        state = SimpleNamespace(
            trigger=RecordedChannelTrigger(
                target=SCHEDULE,
                channel=SCHEDULE,
                payload=RecordedTextInput(text="a step came due"),
                context=ChannelContext(),
                reply=WholeTextReply(),
                parties=OWNERS_WORDS,
            ),
            took=[Named("act-newer", None, Became.TAKEN)],
            joined=[
                JoinedInput(
                    joined_at=AT,
                    channel=taken,
                    messages=(RecordedInputMessage(text="tell me there", sent_at=AT),),
                    taken_over_from="act-newer",
                )
            ],
        )

        scheduling = harness.engine._scheduling(state, SCHEDULE, task)  # type: ignore[arg-type]
        assert scheduling is not None
        places, targets = await scheduling.build()

        assert place_of(taken) in targets
        assert place_of(suggested) in targets
        (listed,) = [one for one in places if one.channel == taken]
        assert not listed.suggested
    finally:
        await harness.engine.aclose()
