"""The chat's reader and writer, end to end through the engine (ADR-0293 §6, §8-§10).

A message written into a conversation is recorded and answered *received* by the act
that wrote it; the chat's reader then takes it in as a push, the activation it starts
runs as a typed turn over the conversation's recent transcript, and the phases write
its messages into the conversation the input came from — or the fixed *couldn't finish*
message where the pass could not finish. No conversation waits (ADR-0349 §8:1): what is
written while an activation runs starts its own once its start wait has passed, what
arrived inside one start wait taken in together, as one input. A restart takes in what
was never taken in, never what an interrupted activation took in, and writes nothing.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from phases_support import hold_start_waits, phases_harness
from test_engine import AT, Harness
from understanding_support import STATED_PROPOSAL, Rendered, rendered, understanding_stage

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    ActivationEnding,
    ChatDevice,
    DeviceAccess,
    EpisodicMemory,
    Message,
    MessageAuthor,
    NewMessage,
    PlanningExchange,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    Role,
    RoundResponse,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.chat import (
    COULDNT_FINISH,
    ChatInput,
    ChatReader,
    couldnt_finish,
)
from ai_assistant.orchestration.conversations import fitted_message
from ai_assistant.orchestration.understanding import AskedIn, WrittenBy
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import pytest

    from ai_assistant.core.types import OfferedTool
    from ai_assistant.orchestration.understanding import TranscriptWindow

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


class _Composing(FakeToolCallingCompleter):
    """Planning whose one round writes what ``composer`` answers, and proposes nothing.

    The reader runs every activation through the phases (ADR-0309 §2:6), so the reply a
    case scripts on ``composer`` is planning's message: a gate on it holds planning, a
    failure fails it, and an empty answer writes nothing.
    """

    def __init__(self, composer: FakeModelProvider) -> None:
        super().__init__()
        self.composer = composer

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        await super().respond(exchange, tools, model=model)
        answer = await self.composer.complete(
            (
                Message(role=Role.SYSTEM, content=exchange.instruction),
                Message(role=Role.USER, content=exchange.briefing),
            )
        )
        return RoundResponse(text=answer.content)


def _harness(
    *,
    composer: FakeModelProvider | None = None,
    store: FakeConversationStore | None = None,
    memory: FakeMemoryStore | None = None,
    **knobs: Any,
) -> Harness:
    """The engine with its reader on and the phases wired, or the medium alone."""
    if knobs.get("chat_reader") is False:
        return Harness(conversation_store=store, memory=memory, **knobs)
    return phases_harness(
        _Composing(composer if composer is not None else FakeModelProvider("Hello there.")),
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


async def _episodes(memory: FakeMemoryStore) -> list[EpisodicMemory]:
    return [one for one in await memory.export() if isinstance(one, EpisodicMemory)]


# --- the reader and the writer (§6, §10) ---------------------------------------------


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


# --- no conversation waits (ADR-0349 §8:1-§8:2) --------------------------------------


async def test_messages_written_while_one_runs_start_their_own_activation_as_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0349 §8:1: nothing is refused or held back; what arrived inside one start wait
    is one input (ADR-0332 §5:1), taken in while the first still runs."""
    composer = _GatedModel()
    harness = _harness(composer=composer, chat_start_wait=timedelta(milliseconds=200))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "first"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    second = await harness.engine.write_message(conversation, message=_said("m-2", "second"))
    third = await harness.engine.write_message(conversation, message=_said("m-3", "third"))
    assert (second.position, third.position) == (2, 3)
    over.set()

    async def both_taken() -> bool:
        marked = await harness.conversation_store.taken_in(conversation, positions=[2, 3])
        return len(marked) == 2

    await _until(both_taken, what="the waiting messages to be taken in")
    state = await harness.engine.conversation(conversation)
    assert state is not None
    assert state.state.working
    assert len(state.state.activation_ids) == 2, "both run, and the state names both"
    assert not composer.gate.is_set(), "taken in while the first still runs"
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
    """ADR-0349 §8:1: each conversation's activations run beside every other's."""
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
    message = rendered(model.calls[-1].messages)
    assert message.stimulus == "Who is it?"
    window = message.tags("Stimulus origin knowledge", "message")
    assert [(item.get("label"), item.get("from"), item.text) for item in window] == [
        ("H1", "the owner", "My dentist is Rao."),
        ("H2", "the system", "Hello there."),
    ]
    # §4:5: the input names the message it replies to by its label.
    (words,) = message.tags("The stimulus")
    assert words.get("replies_to") == "H1"
    assert all(item.get("after_stimulus") is None for item in window)


async def test_a_reply_written_during_a_messages_start_wait_is_marked_as_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6: the window shows that a message was written before the reply it follows.

    The reply lands while the message waits out its start wait (ADR-0349 §8:2).
    """
    model = FakeModelProvider(STATED_PROPOSAL)
    composer = _GatedModel()
    harness = _harness(
        composer=composer,
        understanding=understanding_stage(model=model),
        chat_start_wait=timedelta(milliseconds=200),
    )
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "first"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    # The engine is not told of this start wait, so the first one's act does not wait
    # for it (ADR-0349 §7:12) and its reply lands inside it, as a reply from work that
    # waits on nothing here would: the window is the case, not the waits.
    reader = harness.engine._chat_reader
    assert reader is not None
    monkeypatch.setattr(reader, "_hold", None)
    await harness.engine.write_message(conversation, message=_said("m-2", "meanwhile"))
    composer.gate.set()
    await _answered(harness, conversation, 1)
    over.set()
    await _answered(harness, conversation, 2)
    message = rendered(model.calls[-1].messages)
    assert message.stimulus == "meanwhile"
    window = message.tags("Stimulus origin knowledge", "message")
    assert [(item.text, item.get("after_stimulus")) for item in window] == [
        ("first", None),
        (window[1].text, "yes"),
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
    message = rendered(model.calls[-1].messages)
    window = message.tags("Stimulus origin knowledge", "message")
    # The window's one recent message, then the earlier one the input replies to.
    assert [item.get("label") for item in window] == ["H1", "H2"]
    assert window[1].text == "Book Pinecrest."
    (words,) = message.tags("The stimulus")
    assert words.get("replies_to") == "H2"


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
    assert running.state.activation_ids == (taken[1],)
    composer.gate.set()
    await _answered(harness, conversation, 1)
    ended = await harness.engine.conversation(conversation)
    assert ended is not None
    assert not ended.state.working
    assert ended.state.activation_ids == ()
    assert ended.state.last_ended is ActivationEnding.DONE


def test_couldnt_finish_lists_the_effects_that_did_happen() -> None:
    """§9:1: the fixed text, then each effect that happened."""
    assert couldnt_finish() == NewMessage(author=MessageAuthor.ASSISTANT, text=COULDNT_FINISH)
    written = couldnt_finish(("the tool calendar.book ran",))
    assert written.author is MessageAuthor.ASSISTANT
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


# --- review regressions ---------------------------------------------------------------


class _MarksThenWaits(FakeConversationStore):
    """A store whose ``take_in`` commits, then waits: SQLite's commit-then-cancel shape."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.marking = asyncio.Event()
        self.gate = asyncio.Event()

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        marked = await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )
        self.marking.set()
        await self.gate.wait()
        return marked


async def test_a_shutdown_while_marking_leaves_an_interrupted_activation() -> None:
    """§6:8, §6:9: cancelled as its marking commits, the activation is still recorded,
    interrupted, and its messages are not taken in again."""
    store = _MarksThenWaits()
    memory = FakeMemoryStore(now=lambda: AT)
    harness = _harness(store=store, memory=memory, drain_timeout=timedelta(milliseconds=10))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "hi"))
    await asyncio.wait_for(store.marking.wait(), _SETTLE)
    await harness.engine.aclose()
    assert [one.author for one in await _messages(store, conversation)] == [MessageAuthor.USER]
    (episode,) = await _episodes(memory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED
    taken = await store.taken_in(conversation, positions=[1])
    assert taken == {1: episode.id.removeprefix("activation:")}
    assert await store.untaken_messages(conversation) == ()


async def test_a_backlog_past_one_marking_call_is_still_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0332 §5:1: every message waiting in one start wait is taken in together,
    whatever the store's bound, beside the activation already running (ADR-0349 §8:1)."""
    composer = _GatedModel()
    harness = _harness(composer=composer, chat_start_wait=timedelta(milliseconds=200))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-0", "first"))
    await asyncio.wait_for(composer.entered.wait(), _SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    for n in range(1, 1002):
        await harness.engine.write_message(conversation, message=_said(f"m-{n}", f"w{n}"))
    over.set()
    composer.gate.set()
    await _answered(harness, conversation, 2)
    inputs = sorted((_input_of(one) for one in await _episodes(harness.memory)), key=len)
    assert inputs[0] == "first"
    assert inputs[1].split("\n\n") == [f"w{n}" for n in range(1, 1002)]


async def test_each_input_message_carries_the_message_it_replies_to() -> None:
    """§4:5: two corrections alike in words are told apart by what they reply to."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(understanding=understanding_stage(model=model))
    conversation = await _conversation(harness)
    await harness.engine.write_message(conversation, message=_said("m-1", "Book it."))
    await _answered(harness, conversation, 1)
    await harness.engine.write_message(conversation, message=_said("m-2", "And dinner."))
    await _answered(harness, conversation, 2)
    await harness.engine.write_message(conversation, message=_said("m-3", "No.", replies_to=2))
    await _answered(harness, conversation, 3)
    first = rendered(model.calls[-1].messages)
    await harness.engine.write_message(conversation, message=_said("m-4", "No.", replies_to=4))
    await _answered(harness, conversation, 4)
    second = rendered(model.calls[-1].messages)

    def answered_by(message: Rendered) -> str | None:
        # The label of the window message the input's one message replies to, by its text.
        (words,) = message.tags("The stimulus")
        assert words.text == "No."
        by_label = {
            one.get("label"): one.text
            for one in message.tags("Stimulus origin knowledge", "message")
        }
        return by_label.get(words.get("replies_to"))

    # Each "No." replies to a reply of the assistant's: the first to the one after "Book
    # it.", the second to the one after "And dinner.", each named by its label.
    assert answered_by(first) == answered_by(second) == "Hello there."
    (one,) = first.tags("The stimulus")
    (other,) = second.tags("The stimulus")
    assert (one.get("replies_to"), other.get("replies_to")) == ("H2", "H4")


def test_the_writer_fits_a_message_with_leading_whitespace_and_wide_characters() -> None:
    """§7:3: the longest prefix one read can return, found whatever the text holds."""
    conversation = "0" * 36
    padded = NewMessage(author=MessageAuthor.ASSISTANT, text=" " * 9000 + "x" * 7000)
    fitted = fitted_message(conversation, padded, max_bytes=12000)
    assert fitted.cut_off
    assert fitted.text.strip()
    assert padded.text.startswith(fitted.text)
    wide = NewMessage(author=MessageAuthor.ASSISTANT, text='é"\n' * 5000)
    fitted = fitted_message(conversation, wide, max_bytes=4096)
    assert fitted.cut_off
    assert wide.text.startswith(fitted.text)
    longer = NewMessage(author=MessageAuthor.ASSISTANT, text=wide.text[: len(fitted.text) + 1])
    # The longest: one more character no longer fits.
    assert fitted_message(conversation, longer, max_bytes=4096) is not longer
    short = NewMessage(author=MessageAuthor.ASSISTANT, text="fits")
    assert fitted_message(conversation, short, max_bytes=4096) is short


class _DeletedBeforeMarking(FakeConversationStore):
    """A store where one message is deleted just as the reader marks its input."""

    def __init__(self, doomed: int) -> None:
        super().__init__(now=lambda: AT)
        self._doomed = doomed

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        if self._doomed in positions:
            await self.delete_message(conversation_id, self._doomed)
        return await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )


async def test_a_message_deleted_before_it_is_marked_never_reaches_the_activation() -> None:
    """§6:6: the pass runs on what it took in alone; its episode keeps what it was
    admitted with, since an open episode is only extended (ADR-0286 §12:2)."""
    store = _DeletedBeforeMarking(doomed=1)
    memory = FakeMemoryStore(now=lambda: AT)
    before = _harness(store=store, memory=memory, chat_reader=False)
    conversation = await _conversation(before)
    await before.engine.write_message(conversation, message=_said("m-1", "DELETED ORDER"))
    await before.engine.write_message(conversation, message=_said("m-2", "kept"))
    await before.engine.aclose()
    composer = FakeModelProvider("Hello there.")
    after = _harness(composer=composer, store=store, memory=memory)
    await after.engine.start()
    await _answered(after, conversation, 1)
    (episode,) = await _episodes(memory)
    assert _input_of(episode) == "DELETED ORDER\n\nkept"
    assert composer.calls
    assert all(
        "DELETED ORDER" not in one.content for call in composer.calls for one in call.messages
    )


# --- what wrote each assistant message (ADR-0303 §7:1) ------------------------------------

_WRITER_A: Final = "00000000-0000-4000-8000-00000000000a"
_WRITER_B: Final = "00000000-0000-4000-8000-00000000000b"


class _Writers:
    """A ``written`` reader over a fixed table of which activation wrote each position.

    A position ``questions`` names is a question: its round ``round:<position>`` asked
    about one part.
    """

    def __init__(self, table: dict[int, str], *, questions: frozenset[int] = frozenset()) -> None:
        self._table = table
        self._questions = questions
        self.asked: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    async def __call__(
        self, conversation_id: str, activation_ids: Sequence[str], positions: Sequence[int]
    ) -> dict[int, WrittenBy]:
        del conversation_id
        self.asked.append((tuple(activation_ids), tuple(positions)))
        return {
            position: WrittenBy(
                activation_id=writer,
                asked=AskedIn(round=f"round:{position}", parts=(1,))
                if position in self._questions
                else None,
            )
            for position, writer in self._table.items()
            if position in positions and writer in activation_ids
        }


_USER: Final = MessageAuthor.USER
_ASSISTANT: Final = MessageAuthor.ASSISTANT


async def _seeded(
    store: FakeConversationStore,
    authors: Sequence[MessageAuthor] = (_USER, _ASSISTANT, _ASSISTANT, _USER, _ASSISTANT, _USER),
    taken: dict[int, str] | None = None,
    *,
    replies_to: int | None = None,
) -> str:
    """A conversation of ``authors``, the ``taken`` positions taken in by their activation.

    By default: A took in 1 and wrote 2 and 3; B took in 4 and wrote 5; 6 waits. The
    last message, which waits, replies to ``replies_to``.
    """
    await store.set_my_devices([_PHONE])
    conversation = (await store.start()).id
    for n, author in enumerate(authors, 1):
        user = author is _USER
        message = NewMessage(
            author=author,
            text=f"message {n}",
            device_id=_PHONE.device_id if user else None,
            message_id=f"m-{n}" if user else None,
            replies_to=replies_to if n == len(authors) else None,
        )
        await store.append_message(conversation, message)
    for position, activation_id in (taken or {1: _WRITER_A, 4: _WRITER_B}).items():
        await store.take_in(conversation, positions=[position], activation_id=activation_id)
    return conversation


async def _window(
    store: FakeConversationStore,
    conversation: str,
    written: _Writers | None,
    *,
    window_size: int = 3,
) -> TranscriptWindow:
    """The window the reader brings in with the waiting message."""
    taken: list[ChatInput] = []
    tasks: list[asyncio.Future[None]] = []

    async def activate(one: ChatInput) -> bool:
        taken.append(one)
        return False

    reader = ChatReader(
        conversations=store,
        activate=activate,
        spawn=lambda work: tasks.append(asyncio.ensure_future(work)),
        closing=lambda: False,
        mint=lambda: "00000000-0000-4000-8000-00000000000c",
        window_size=window_size,
        written=written,
    )
    reader.notice(conversation)
    await asyncio.wait_for(asyncio.gather(*tasks), _SETTLE)
    (one,) = taken
    return one.window


async def _window_links(
    store: FakeConversationStore, conversation: str, written: _Writers | None
) -> dict[int, str]:
    """The links of the default conversation's window, its recent messages 3 to 5."""
    window = await _window(store, conversation, written)
    assert [message.position for message in window.messages] == [3, 4, 5]
    return dict(window.links)


async def test_an_assistant_message_links_to_the_activation_that_wrote_it() -> None:
    """ADR-0303 §7:1: by acting's effect record, beside the bookkeeping's links.

    The window's head, 3, was written by A, whose input lies just before the window:
    the look-back over as many positions again finds it.
    """
    store = FakeConversationStore(now=lambda: AT)
    conversation = await _seeded(store)
    writers = _Writers({2: _WRITER_A, 3: _WRITER_A, 5: _WRITER_B})

    links = await _window_links(store, conversation, writers)

    assert links == {3: _WRITER_A, 4: _WRITER_B, 5: _WRITER_B}
    # The candidates are the window's and the look-back's; only its assistant
    # messages are asked about.
    assert writers.asked == [((_WRITER_B, _WRITER_A), (3, 5))]


async def test_an_assistant_message_carries_the_question_it_is() -> None:
    """ADR-0322 §4:2: the reader brings the question beside the link, where it is one."""
    store = FakeConversationStore(now=lambda: AT)
    conversation = await _seeded(store)
    writers = _Writers({2: _WRITER_A, 3: _WRITER_A, 5: _WRITER_B}, questions=frozenset({3}))

    window = await _window(store, conversation, writers)

    assert dict(window.links) == {3: _WRITER_A, 4: _WRITER_B, 5: _WRITER_B}
    assert dict(window.asked) == {3: AskedIn(round="round:3", parts=(1,))}


async def test_without_a_writers_reader_no_assistant_message_links() -> None:
    """Before the phases nothing records a writer, so only taken-in messages link."""
    store = FakeConversationStore(now=lambda: AT)
    conversation = await _seeded(store)

    assert await _window_links(store, conversation, None) == {4: _WRITER_B}


async def test_an_assistant_message_no_record_names_stays_not_linkable() -> None:
    """ADR-0303 §7:5: one the old path wrote carries no effect record."""
    store = FakeConversationStore(now=lambda: AT)
    conversation = await _seeded(store)

    links = await _window_links(store, conversation, _Writers({5: _WRITER_B}))

    assert links == {4: _WRITER_B, 5: _WRITER_B}


async def test_an_earlier_assistant_message_an_input_replies_to_links_to_its_writer() -> None:
    """ADR-0303 §7:1, §7:3: the look-back runs before a replied-to message too.

    A took in 1 and wrote 2; B took in 3 and wrote 4; C took in 5 and wrote 6. The
    waiting 7 replies to 2, which the two-message window does not show, so the
    reader brings it in, and finds its writer by looking back from it.
    """
    store = FakeConversationStore(now=lambda: AT)
    writer_c = "00000000-0000-4000-8000-00000000000e"
    conversation = await _seeded(
        store,
        (_USER, _ASSISTANT, _USER, _ASSISTANT, _USER, _ASSISTANT, _USER),
        {1: _WRITER_A, 3: _WRITER_B, 5: writer_c},
        replies_to=2,
    )
    writers = _Writers({2: _WRITER_A, 4: _WRITER_B, 6: writer_c})

    window = await _window(store, conversation, writers, window_size=2)

    assert [one.position for one in window.messages] == [5, 6]
    assert [one.position for one in window.replied_to] == [2]
    assert dict(window.links) == {2: _WRITER_A, 5: writer_c, 6: writer_c}
