"""ADR-0297 at the engine: a stop is a mark, then a record, and the pass ends stopped.

§6:6's engine arms, over the real :class:`~ai_assistant.orchestration.engine.Engine`
wired with seeded fakes. **Every stop here lands at a fixed point rather than in a
race**: a hook inside a fake store or seam calls ``stop_activation`` at exactly the
instant the arm is about — inside the claim's write before it applies, after it has
landed, inside the admission write, inside a stage — so the store's ordering decides
each case, as §2:10 has it, and nothing depends on scheduling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from structlog.testing import capture_logs
from test_chat_reader import _answered as chat_answered
from test_chat_reader import _conversation as chat_conversation
from test_chat_reader import _GatedModel
from test_chat_reader import _harness as chat_harness
from test_chat_reader import _messages as chat_messages
from test_chat_reader import _said as chat_said
from test_chat_reader import _until as chat_until
from test_engine import AT, Harness

from ai_assistant.core.errors import ActivationStoppedError, PlanningError
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    MessageAuthor,
    NewConversation,
    PermissionOutcome,
    ProcessingReason,
    ProcessingStatus,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.conversations import activation_ending
from ai_assistant.orchestration.engine import _stopped_failure

if TYPE_CHECKING:
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.testing import FakeMemoryStore


async def _episodes(memory: FakeMemoryStore) -> list[EpisodicMemory]:
    return [one for one in await memory.export() if isinstance(one, EpisodicMemory)]


def _stopped(episode: EpisodicMemory) -> None:
    """The record says a stop ended it: its reason, its status and its end entry."""
    record = episode.processing_record
    assert record is not None
    assert (record.status, record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )
    assert record.stages[-1].stage is ControllerStage.END
    assert record.stages[-1].due is ControllerRule.STOPPED
    assert activation_ending(episode) is ActivationEnding.STOPPED


# --- §4: a resume stopped after its answer was recorded --------------------------------


async def _answered(harness: Harness) -> list[PermissionOutcome]:
    return [
        row.ruling.outcome
        for row in reversed(await harness.trail.export())
        if row.resolves is not None
    ]


# --- ADR-0295 §3, ADR-0297 §4: the conversation a stopped activation started from -------


async def _working(harness: Harness, conversation_id: str) -> str:
    """Wait for the conversation to show "working…" with an id, and return the id."""
    found: list[str] = []

    async def shown() -> bool:
        digest = await harness.engine.conversation(conversation_id)
        if digest is None or not digest.state.activation_ids:
            return False
        found.append(digest.state.activation_ids[-1])
        return True

    await chat_until(shown, what="the running activation's id")
    return found[-1]


async def test_a_stopped_chat_activation_writes_nothing_and_shows_stopped() -> None:
    """ADR-0295 §3:3-§3:4: no reply — even one already composed — and no *couldn't finish*.

    The stop lands while the composing stage runs, so the reply is composed; the
    controller reads the mark once that stage's result is in hand, ends the pass, and the
    adapter writes nothing at all. The current state then shows *stopped*.
    """
    composer = _GatedModel("Done.")
    harness = chat_harness(composer=composer)
    conversation = await chat_conversation(harness)
    await harness.engine.write_message(conversation, message=chat_said("m-1", "hi"))
    await asyncio.wait_for(composer.entered.wait(), timeout=5)
    running = await _working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    composer.gate.set()

    async def idle() -> bool:
        digest = await harness.engine.conversation(conversation)
        return digest is not None and not digest.state.working

    await chat_until(idle, what="the stopped activation to end")
    written = await chat_messages(harness.conversation_store, conversation)
    assert [(one.author, one.text) for one in written] == [(MessageAuthor.USER, "hi")]
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.STOPPED
    (episode,) = await _episodes(harness.memory)
    _stopped(episode)
    assert episode.processing_record is not None
    assert episode.processing_record.activation_id == running


async def test_a_correction_after_a_stop_starts_its_own_activation() -> None:
    """ADR-0295 §3:6: a stop holds nothing back; the correction is answered after it.

    No place waits (ADR-0349 §8:1): the correction starts its own activation once its
    start wait has passed, whatever still runs on the place, and is taken in by it.
    """
    composer = _GatedModel("Sunday it is.")
    harness = chat_harness(composer=composer)
    conversation = await chat_conversation(harness)
    await harness.engine.write_message(conversation, message=chat_said("m-1", "book it Saturday"))
    await asyncio.wait_for(composer.entered.wait(), timeout=5)
    running = await _working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    await harness.engine.write_message(conversation, message=chat_said("m-2", "actually Sunday"))
    composer.gate.set()

    written = await chat_answered(harness, conversation, 1)
    assert [(one.author, one.text) for one in written] == [
        (MessageAuthor.USER, "book it Saturday"),
        (MessageAuthor.USER, "actually Sunday"),
        (MessageAuthor.ASSISTANT, "Sunday it is."),
    ]
    episodes = await _episodes(harness.memory)
    stopped = [
        one
        for one in episodes
        if one.processing_record is not None and (one.processing_record.activation_id == running)
    ]
    (first,) = stopped
    _stopped(first)
    (second,) = [one for one in episodes if one is not first]
    assert activation_ending(second) is ActivationEnding.DONE
    # Each message was taken in by the activation that ran on it, and nothing waits.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken[1] == running
    assert taken[2] == second.id.removeprefix("activation:")
    assert await harness.conversation_store.untaken_messages(conversation) == ()


def _admitted() -> ActivationState:
    return admit_channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
        WholeTextReply(),
        clock=lambda: AT,
        id_factory=lambda: "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11",
    )


def test_a_call_awaiting_a_stopped_pass_is_answered_with_the_stop() -> None:
    """§4:9: the stop takes the place of what the pass ended with, a cancellation aside."""
    state = _admitted()
    raised = PlanningError("refused before any answer")
    cancelled = asyncio.CancelledError()
    assert _stopped_failure(state, raised) is raised
    assert _stopped_failure(state, None) is None
    assert state.stop()
    assert _stopped_failure(state, cancelled) is cancelled
    assert isinstance(_stopped_failure(state, raised), ActivationStoppedError)
    assert isinstance(_stopped_failure(state, None), ActivationStoppedError)


def _defect() -> ValueError:
    """A defect raised, so it carries the frames it passed through."""
    words = "the user's " + "private words"
    try:
        raise ValueError(words)
    except ValueError as exc:
        return exc


def test_a_defect_behind_a_stop_is_logged_once_by_its_class_and_frames() -> None:
    """#2927: past the stop the defect survives only as the stop's cause, so it is logged here.

    Once, at error level, by its class and the frames it passed through, never its
    message (ADR-0314 §3:2); an expected failure behind a stop, or a defect no stop
    reached, logs nothing here.
    """
    state = _admitted()
    defect = _defect()
    with capture_logs() as logs:
        assert _stopped_failure(state, defect) is defect, "no stop: answered as it ended"
        assert state.stop()
        expected = _stopped_failure(state, PlanningError("expected"))
        stopped = _stopped_failure(state, defect)
    assert isinstance(expected, ActivationStoppedError)
    assert isinstance(stopped, ActivationStoppedError)
    assert stopped.__cause__ is defect
    (line,) = [one for one in logs if one["log_level"] == "error"]
    assert line["event"] == "stopped_activation_failed"
    assert line["error"] == "ValueError"
    assert line["activation_id"] == state.activation_id
    assert "_defect" in line["traceback"], "the frames it passed through"
    assert line["traceback"].rstrip().endswith("ValueError")
    assert "private" not in str(line), "never its message"
