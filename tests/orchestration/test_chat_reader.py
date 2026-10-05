"""The chat's reader and writer, end to end through the engine (ADR-0293 §6, §8-§10).

A message written into a conversation is recorded and answered *received* by the act
that wrote it; the chat's reader then takes it in as a push, the activation it starts
runs as a typed turn over the conversation's recent transcript, and the adapter writes
what the compose stage produced as one assistant message into the conversation the
input came from — or the fixed *couldn't finish* message where the pass ended without a
reply. One activation runs per conversation at a time: what is written meanwhile waits
and is taken in together, as one input, when it ends. A restart takes in what was never
taken in, never what an interrupted activation took in, and writes nothing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEnding,
    ChatDevice,
    DeviceAccess,
    Disposition,
    EpisodicMemory,
    ExecutionState,
    MessageAuthor,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    StepOutcome,
    TranscriptMessage,
    TurnOutcome,
    UserMessage,
)
from ai_assistant.orchestration.chat import (
    COULDNT_FINISH,
    chat_effects,
    chat_reply,
    couldnt_finish,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import Message

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: How long a case waits for the reader to settle before it fails, rather than hangs.
_SETTLE: Final = 5.0


class _GatedModel(FakeModelProvider):
    """A composing model that answers each call only once its gate is opened."""

    def __init__(self, reply: str = "Done.") -> None:
        super().__init__(reply)
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.entered.set()
        await self.gate.wait()
        return await super().complete(messages, model=model)


class _FailingModel(FakeModelProvider):
    """A composing model whose every call fails, as a provider outage does."""

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del messages, model
        msg = "the provider is down"
        raise ModelError(msg)


def _harness(
    *,
    composer: FakeModelProvider | None = None,
    store: FakeConversationStore | None = None,
    memory: FakeMemoryStore | None = None,
    **knobs: Any,
) -> Harness:
    return Harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=composer if composer is not None else FakeModelProvider("Hello there."),
            streaming=FakeStreamingCompleter(),
        ),
        conversation_store=store,
        memory=memory,
        **knobs,
    )


def _said(message_id: str, text: str, *, replies_to: int | None = None) -> UserMessage:
    return UserMessage(
        device_id=_PHONE.device_id, message_id=message_id, text=text, replies_to=replies_to
    )


async def _conversation(harness: Harness) -> str:
    await harness.engine.set_my_devices([_PHONE])
    return (await harness.engine.start_conversation()).id


async def _messages(store: FakeConversationStore, conversation_id: str) -> list[TranscriptMessage]:
    page = await store.transcript(conversation_id, limit=100)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


async def _until(check: Callable[[], Any], *, what: str) -> None:
    """Wait for ``check`` to hold, polling the loop; fail rather than hang."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            msg = f"the reader never settled: {what}"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def _answered(harness: Harness, conversation_id: str, count: int) -> list[TranscriptMessage]:
    """Wait for ``count`` assistant messages and for the reader to be idle, then read."""
    store = harness.conversation_store

    async def done() -> bool:
        written = await _messages(store, conversation_id)
        state = await harness.engine.conversation(conversation_id)
        assistant = [one for one in written if one.author is MessageAuthor.ASSISTANT]
        return len(assistant) >= count and state is not None and not state.state.working

    await _until(done, what=f"{count} assistant message(s)")
    return await _messages(store, conversation_id)


def _input_of(episode: EpisodicMemory) -> str:
    """The text an episode's activation was admitted with."""
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    assert isinstance(trigger.payload, RecordedTextInput)
    return trigger.payload.text


def _replied(text: str, *, degraded: bool = False) -> TurnOutcome:
    """An outcome carrying a composed reply; the adapter reads nothing else of it."""
    return TurnOutcome.model_construct(
        turn=None, step=None, reply=text, reply_degraded=degraded, routed=None
    )


async def _episodes(memory: FakeMemoryStore) -> list[EpisodicMemory]:
    return [one for one in await memory.export() if isinstance(one, EpisodicMemory)]


# --- the reader, the writer and the adapter (§6, §10) ---------------------------------


async def test_a_written_message_is_answered_by_an_assistant_message() -> None:
    """§6:1, §10:1: the reader takes the message in and the reply is written back."""
    harness = _harness()
    conversation = await _conversation(harness)
    receipt = await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    assert receipt.position == 1
    written = await _answered(harness, conversation, 1)
    assert [(one.author, one.text) for one in written] == [
        (MessageAuthor.USER, "hi"),
        (MessageAuthor.ASSISTANT, "Hello there."),
    ]
    assert not written[1].cut_off
    (episode,) = await _episodes(harness.memory)
    assert episode.processing_record is not None
    assert _input_of(episode) == "hi"
    # §6:6: marked taken in by the activation the episode records.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken == {1: episode.id.removeprefix("activation:")}


async def test_the_assistants_own_message_starts_no_activation() -> None:
    """§6:1: after the reply nothing waits, and no second activation runs."""
    harness = _harness()
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await _answered(harness, conversation, 1)
    assert await harness.conversation_store.untaken_messages(conversation) == ()
    await harness.engine.start()
    await _answered(harness, conversation, 1)
    assert len(await _episodes(harness.memory)) == 1


async def test_a_repeated_send_is_taken_in_once() -> None:
    """§4:2: the same device's same message id is one message, starting one activation."""
    harness = _harness()
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    written = await _answered(harness, conversation, 1)
    assert [one.author for one in written] == [MessageAuthor.USER, MessageAuthor.ASSISTANT]
    assert len(await _episodes(harness.memory)) == 1


# --- the interim: one activation at a time per conversation (§6:2, §6:3) -------------


async def test_messages_written_while_one_runs_wait_and_are_taken_in_as_one_input() -> None:
    """§6:2, §6:3: nothing is refused; what waited is one input when the first ends."""
    composer = _GatedModel()
    harness = _harness(composer=composer)
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "first"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    second = await harness.engine.write_message(conversation, message=_said("m-2", "second"))
    third = await harness.engine.write_message(conversation, message=_said("m-3", "third"))
    assert (second.position, third.position) == (2, 3)
    state = await harness.engine.conversation(conversation)
    assert state is not None
    assert state.state.working
    assert len(await _episodes(harness.memory)) == 1
    composer.gate.set()
    written = await _answered(harness, conversation, 2)
    assert [(one.position, one.author) for one in written] == [
        (1, MessageAuthor.USER),
        (2, MessageAuthor.USER),
        (3, MessageAuthor.USER),
        (4, MessageAuthor.ASSISTANT),
        (5, MessageAuthor.ASSISTANT),
    ]
    inputs = sorted(_input_of(episode) for episode in await _episodes(harness.memory))
    assert inputs == ["first", "second\n\nthird"]
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2, 3])
    assert taken[2] == taken[3] != taken[1]


async def test_two_conversations_run_side_by_side() -> None:
    """The interim is per conversation: another conversation's message is not held."""
    composer = _GatedModel()
    harness = _harness(composer=composer)
    first = await _conversation(harness)
    second = (await harness.engine.start_conversation()).id
    await harness.engine.write_message(first, message=_said("m-1", "one"))
    await harness.engine.write_message(second, message=_said("m-1", "two"))

    async def both_running() -> bool:
        one = await harness.engine.conversation(first)
        two = await harness.engine.conversation(second)
        return bool(one and two and one.state.working and two.state.working)

    await _until(both_running, what="both conversations working")
    composer.gate.set()
    await _answered(harness, first, 1)
    await _answered(harness, second, 1)


# --- the window (§6:4, §6:5) ----------------------------------------------------------


async def test_the_window_is_the_recent_transcript_each_message_keeping_its_author() -> None:
    """§6:4, §6:5: the understanding stage sees the transcript, not the episode tail."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(understanding=understanding_stage(model=model))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "My dentist is Rao."))
    await _answered(harness, conversation, 1)
    await harness.engine.write_message(
        conversation, message=_said("m-2", "Who is it?", replies_to=1)
    )
    await _answered(harness, conversation, 2)
    payload = json.loads(model.calls[-1].messages[1].content)
    assert payload["input"]["text"] == "Who is it?"
    window = payload["channel_window"]
    assert [(item["label"], item["author"], item["text"]) for item in window] == [
        ("H1", "the user", "My dentist is Rao."),
        ("H2", "the assistant", "Hello there."),
    ]
    assert [item["position"] for item in window] == [1, 2]
    assert all("written_after_the_input_began" not in item for item in window)


async def test_a_reply_written_after_a_waiting_message_is_marked_as_after_it() -> None:
    """§6: the window shows that a message was written before the reply it follows."""
    model = FakeModelProvider(STATED_PROPOSAL)
    composer = _GatedModel()
    harness = _harness(composer=composer, understanding=understanding_stage(model=model))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "first"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    await harness.engine.write_message(conversation, message=_said("m-2", "meanwhile"))
    composer.gate.set()
    await _answered(harness, conversation, 2)
    payload = json.loads(model.calls[-1].messages[1].content)
    assert payload["input"]["text"] == "meanwhile"
    window = payload["channel_window"]
    assert [(item["position"], item.get("written_after_the_input_began")) for item in window] == [
        (1, None),
        (3, True),
    ]


async def test_a_message_replying_outside_the_window_brings_that_message_in() -> None:
    """§4:5, §6:4: a correction names the message it corrects, wherever it is."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(understanding=understanding_stage(model=model))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "Book Pinecrest."))
    await _answered(harness, conversation, 1)
    # A window of one message, so the message the correction names falls outside it.
    reader = harness.engine._chat_reader
    assert reader is not None
    reader._window_size = 1
    await harness.engine.write_message(conversation, message=_said("m-2", "Filler."))
    await _answered(harness, conversation, 2)
    await harness.engine.write_message(
        conversation, message=_said("m-3", "No, the other one.", replies_to=1)
    )
    await _answered(harness, conversation, 3)
    window = json.loads(model.calls[-1].messages[1].content)["channel_window"]
    assert [(item["item"], item["position"]) for item in window] == [
        ("a recent message of this conversation", 4),
        ("an earlier message the input replies to", 1),
    ]
    assert window[1]["text"] == "Book Pinecrest."


# --- endings: couldn't finish, and the current state (§8, §9:1, §10:2) ---------------


async def test_a_pass_that_ends_without_a_reply_writes_couldnt_finish() -> None:
    """§9:1, §10:2: a composition that failed leaves the fixed message, and the state."""
    harness = _harness(composer=_FailingModel())
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    written = await _answered(harness, conversation, 1)
    assert written[-1].author is MessageAuthor.ASSISTANT
    assert written[-1].text == COULDNT_FINISH
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.COULDNT_FINISH
    (episode,) = await _episodes(harness.memory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.FAILED


async def test_the_state_is_working_until_the_reply_is_written_then_done() -> None:
    """§8:2, §8:3: "working…" names the running activation; then how it ended."""
    composer = _GatedModel()
    harness = _harness(composer=composer)
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    running = await harness.engine.conversation(conversation)
    assert running is not None
    assert running.state.working
    taken = await harness.conversation_store.taken_in(conversation, positions=[1])
    assert running.state.activation_id == taken[1]
    composer.gate.set()
    await _answered(harness, conversation, 1)
    ended = await harness.engine.conversation(conversation)
    assert ended is not None
    assert not ended.state.working
    assert ended.state.activation_id is None
    assert ended.state.last_ended is ActivationEnding.DONE


def test_the_adapter_writes_the_reply_and_cuts_one_past_the_bound() -> None:
    """§10:1, §5:2: one assistant message; a reply past the bound is cut and says so."""
    outcome = _replied("x" * (TRANSCRIPT_MESSAGE_MAX_CHARS + 5))
    written = chat_reply(outcome)
    assert written.author is MessageAuthor.ASSISTANT
    assert len(written.text) == TRANSCRIPT_MESSAGE_MAX_CHARS
    assert written.cut_off
    assert not chat_reply(_replied("ok")).cut_off
    assert chat_reply(_replied("half", degraded=True)).cut_off
    assert chat_reply(None) == couldnt_finish()


def test_couldnt_finish_lists_the_effects_that_did_happen() -> None:
    """§9:1: the fixed text, then each effect that happened."""
    state = ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=AT)
    ran = StepOutcome(
        disposition=Disposition.EXECUTED, state=state, step_id="s-1", tool_id="calendar.book"
    )
    refused = StepOutcome(disposition=Disposition.DENIED, state=state, step_id="s-1")
    assert chat_effects(None, step=ran) == ("the tool calendar.book ran",)
    assert chat_effects(None, step=refused) == ()
    written = chat_reply(None, effects=chat_effects(None, step=ran))
    assert (
        written.text
        == f"{COULDNT_FINISH} Before it stopped, this happened:\n- the tool calendar.book ran"
    )


# --- restart (§6:9, §9:2) -------------------------------------------------------------


async def test_a_restart_takes_in_what_was_never_taken_in_and_nothing_else() -> None:
    """§6:9: an interrupted activation's messages stay taken in; the rest are taken in."""
    store = FakeConversationStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    before = _harness(store=store, memory=memory, chat_reader=False)
    conversation = await _conversation(before)
    await before.engine.write_message(conversation, message=_said("m-1", "acted on"))
    await before.engine.write_message(conversation, message=_said("m-2", "never taken"))
    # A process that marked the first message and died before answering it.
    await store.take_in(
        conversation, positions=[1], activation_id="00000000-0000-4000-8000-000000000001"
    )
    await before.engine.aclose()
    after = _harness(store=store, memory=memory)
    await after.engine.start()
    written = await _answered(after, conversation, 1)
    assert [(one.position, one.author) for one in written] == [
        (1, MessageAuthor.USER),
        (2, MessageAuthor.USER),
        (3, MessageAuthor.ASSISTANT),
    ]
    (episode,) = await _episodes(memory)
    assert _input_of(episode) == "never taken"


async def test_a_shutdown_that_cancels_the_activation_writes_nothing() -> None:
    """§9:2: the activation is interrupted, nothing is written, and the state says so."""
    composer = _GatedModel()
    store = FakeConversationStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    harness = _harness(
        composer=composer, store=store, memory=memory, drain_timeout=timedelta(milliseconds=10)
    )
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    await harness.engine.aclose()
    assert [one.author for one in await _messages(store, conversation)] == [MessageAuthor.USER]
    (episode,) = await _episodes(memory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED
    # A later engine reads the ending, and takes nothing in again.
    after = _harness(store=store, memory=memory)
    await after.engine.start()
    digest = await after.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.INTERRUPTED
    assert not digest.state.working
    assert await store.untaken_messages(conversation) == ()


async def test_a_reader_switched_off_leaves_the_message_waiting() -> None:
    """The medium alone: recorded and *received*, taken in by nothing."""
    harness = _harness(chat_reader=False)
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await asyncio.sleep(0)
    assert [one.position for one in await store_untaken(harness, conversation)] == [1]
    assert await _episodes(harness.memory) == []


async def store_untaken(harness: Harness, conversation_id: str) -> tuple[TranscriptMessage, ...]:
    return await harness.conversation_store.untaken_messages(conversation_id)
