"""The chat's reader end to end through the engine, on the phase path (ADR-0293 §6, §8-§10).

``test_chat_reader`` drives these cases through today's table, where the compose stage
writes the reply and the adapter writes it into the conversation. On the phases,
planning writes each message as the activation runs (ADR-0307 §3), so the adapter
writes nothing (ADR-0309 §2:6). What the reader does is unchanged: one activation per
conversation at a time, what waits taken in together as one input, a repeated send
taken in once, the state reading *working…* and then how it ended, a shutdown writing
nothing, and the window the transcript. Each case here is one of today's run with the
phases wired, so it stays pinned once the switch lands.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from phases_support import (
    SETTLE,
    Gated,
    answered,
    episodes,
    idle,
    input_of,
    open_conversation,
    phases_harness,
    said,
    working,
    written,
)
from test_engine import AT, Harness
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ConversationStoreError
from ai_assistant.core.types import (
    ActivationEnding,
    MessageAuthor,
    ProcessingStatus,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Sequence


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


class _FailsSecondMarking(FakeConversationStore):
    """A store whose second ``take_in`` call fails once, after the first committed."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.calls = 0

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        self.calls += 1
        if self.calls == 2:
            msg = "the store is busy"
            raise ConversationStoreError(msg)
        return await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )


def _idle(store: FakeConversationStore, memory: FakeMemoryStore) -> Harness:
    """An engine whose reader is off, to write messages nothing takes in yet."""
    return Harness(conversation_store=store, memory=memory, chat_reader=False)


async def test_a_written_message_is_answered_by_an_assistant_message() -> None:
    """§6:1: the reader takes the message in, and planning writes the reply back."""
    harness = phases_harness()
    conversation = await open_conversation(harness)
    receipt = await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    assert receipt.position == 1
    messages = await answered(harness, conversation, 1)
    assert [(one.author, one.text) for one in messages] == [
        (MessageAuthor.USER, "hi"),
        (MessageAuthor.ASSISTANT, DEFAULT_ROUND_TEXT),
    ]
    (episode,) = await episodes(harness.memory)
    assert input_of(episode) == "hi"
    # §6:6: marked taken in by the activation the episode records.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1])
    assert taken == {1: episode.id.removeprefix("activation:")}


async def test_a_repeated_send_is_taken_in_once() -> None:
    """§4:2: the same device's same message id is one message, starting one activation."""
    harness = phases_harness()
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    messages = await answered(harness, conversation, 1)
    assert [one.author for one in messages] == [MessageAuthor.USER, MessageAuthor.ASSISTANT]
    assert len(await episodes(harness.memory)) == 1


async def test_a_backlog_past_one_marking_call_is_still_one_input() -> None:
    """§6:3: every waiting message is taken in together, whatever the store's bound."""
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-0", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    for n in range(1, 1002):
        await harness.engine.write_message(conversation, message=said(f"m-{n}", f"w{n}"))
    completer.release.set()
    await answered(harness, conversation, 2)
    inputs = sorted((input_of(one) for one in await episodes(harness.memory)), key=len)
    assert inputs[0] == "first"
    assert inputs[1].split("\n\n") == [f"w{n}" for n in range(1, 1002)]


async def test_a_reply_written_after_a_waiting_message_is_marked_as_after_it() -> None:
    """§6: the window shows that a message was written before the reply it follows."""
    model = FakeModelProvider(STATED_PROPOSAL)
    completer = Gated()
    harness = phases_harness(completer, understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    await harness.engine.write_message(conversation, message=said("m-2", "meanwhile"))
    completer.release.set()
    await answered(harness, conversation, 2)
    payload = json.loads(model.calls[-1].messages[1].content)
    assert payload["input"]["text"] == "meanwhile"
    window = payload["channel_window"]
    assert [(item["position"], item.get("written_after_the_input_began")) for item in window] == [
        (1, None),
        (3, True),
    ]


async def test_the_state_is_working_until_the_reply_is_written_then_done() -> None:
    """§8:2, §8:3: "working…" names the running activation; then how it ended."""
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await harness.engine.conversation(conversation)
    assert running is not None
    assert running.state.working
    taken = await harness.conversation_store.taken_in(conversation, positions=[1])
    assert running.state.activation_id == taken[1]
    completer.release.set()
    await answered(harness, conversation, 1)
    ended = await harness.engine.conversation(conversation)
    assert ended is not None
    assert not ended.state.working
    assert ended.state.activation_id is None
    assert ended.state.last_ended is ActivationEnding.DONE


async def test_forgetting_reaches_an_activation_running_on_the_conversation() -> None:
    """ADR-0293 §2:6: an activation running when its conversation is forgotten leaves no
    episode once it finishes, and the conversation stays.

    The shared chat-surface contract drives this over a spoken turn, which retires at the
    cutover (ADR-0313 §3:1); here it is the reader's activation, held in planning.
    """
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.forget_conversation(conversation) is True
    completer.release.set()
    await idle(harness, conversation)

    assert await harness.memory.get(f"activation:{running}") is None
    assert await episodes(harness.memory) == []
    assert await harness.engine.conversation(conversation) is not None


async def test_a_shutdown_that_cancels_the_activation_writes_nothing() -> None:
    """§9:2: the activation is interrupted, nothing is written, and the state says so."""
    completer = Gated()
    store = FakeConversationStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    harness = phases_harness(
        completer,
        conversation_store=store,
        memory=memory,
        drain_timeout=timedelta(milliseconds=10),
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    await harness.engine.aclose()
    assert [one.author for one in await written(harness, conversation)] == [MessageAuthor.USER]
    (episode,) = await episodes(memory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED
    # A later engine reads the ending, and takes nothing in again.
    after = phases_harness(conversation_store=store, memory=memory)
    await after.engine.start()
    digest = await after.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.INTERRUPTED
    assert not digest.state.working
    assert await store.untaken_messages(conversation) == ()


async def test_a_message_deleted_before_it_is_marked_never_reaches_the_activation() -> None:
    """§6:6: the pass runs on what it took in alone; its episode keeps what it was
    admitted with, since an open episode is only extended (ADR-0286 §12:2)."""
    store = _DeletedBeforeMarking(doomed=1)
    memory = FakeMemoryStore(now=lambda: AT)
    before = _idle(store, memory)
    conversation = await open_conversation(before)
    await before.engine.write_message(conversation, message=said("m-1", "DELETED ORDER"))
    await before.engine.write_message(conversation, message=said("m-2", "kept"))
    await before.engine.aclose()
    completer = FakeToolCallingCompleter()
    after = phases_harness(completer, conversation_store=store, memory=memory)
    await after.engine.start()
    await answered(after, conversation, 1)
    (episode,) = await episodes(memory)
    assert input_of(episode) == "DELETED ORDER\n\nkept"
    assert completer.calls
    assert all(
        "DELETED ORDER" not in one.content for call in completer.calls for one in call.messages
    )


async def test_messages_written_while_one_runs_wait_and_are_taken_in_as_one_input() -> None:
    """§6:2, §6:3: nothing is refused; what waited is one input when the first ends."""
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    second = await harness.engine.write_message(conversation, message=said("m-2", "second"))
    third = await harness.engine.write_message(conversation, message=said("m-3", "third"))
    assert (second.position, third.position) == (2, 3)
    state = await harness.engine.conversation(conversation)
    assert state is not None
    assert state.state.working
    assert len(await episodes(harness.memory)) == 1
    completer.release.set()
    messages = await answered(harness, conversation, 2)
    assert [(one.position, one.author) for one in messages] == [
        (1, MessageAuthor.USER),
        (2, MessageAuthor.USER),
        (3, MessageAuthor.USER),
        (4, MessageAuthor.ASSISTANT),
        (5, MessageAuthor.ASSISTANT),
    ]
    inputs = sorted(input_of(episode) for episode in await episodes(harness.memory))
    assert inputs == ["first", "second\n\nthird"]
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2, 3])
    assert taken[2] == taken[3] != taken[1]


@pytest.mark.xfail(
    strict=True,
    reason="#2900: a failure before the phases start writes no couldn't-finish message",
)
async def test_a_marking_that_fails_part_way_ends_as_couldnt_finish() -> None:
    """§9:1, §10:2: what was marked is consumed, so its activation's failure is written;
    what was not is taken in by the next activation."""
    store = _FailsSecondMarking()
    memory = FakeMemoryStore(now=lambda: AT)
    before = _idle(store, memory)
    conversation = await open_conversation(before)
    for n in range(1, 1002):
        await before.engine.write_message(conversation, message=said(f"m-{n}", f"w{n}"))
    await before.engine.aclose()
    after = phases_harness(conversation_store=store, memory=memory)
    await after.engine.start()
    messages = await answered(after, conversation, 2)
    replies = [one.text for one in messages if one.author is MessageAuthor.ASSISTANT]
    assert replies == [COULDNT_FINISH, DEFAULT_ROUND_TEXT]
    taken = await store.taken_in(conversation, positions=[1, 1000, 1001])
    assert taken[1] == taken[1000] != taken[1001]
    inputs = sorted((input_of(one) for one in await episodes(memory)), key=len)
    assert inputs[0] == "w1001"


async def test_the_window_is_the_recent_transcript_each_message_keeping_its_author() -> None:
    """§6:4, §6:5: the understanding stage sees the transcript, not the episode tail."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "My dentist is Rao."))
    await answered(harness, conversation, 1)
    await harness.engine.write_message(
        conversation, message=said("m-2", "Who is it?", replies_to=1)
    )
    await answered(harness, conversation, 2)
    payload = json.loads(model.calls[-1].messages[1].content)
    assert payload["input"]["text"] == "Who is it?"
    window = payload["channel_window"]
    assert [(item["label"], item["author"], item["text"]) for item in window] == [
        ("H1", "the user", "My dentist is Rao."),
        ("H2", "the assistant", DEFAULT_ROUND_TEXT),
    ]
    assert [item["position"] for item in window] == [1, 2]
    assert all("written_after_the_input_began" not in item for item in window)
