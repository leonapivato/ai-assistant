"""The chat's reader end to end through the engine, on the phase path (ADR-0293 §6, §8-§10).

``test_chat_reader`` drives these cases through today's table, where the compose stage
writes the reply and the adapter writes it into the conversation. On the phases,
planning writes each message as the activation runs (ADR-0307 §3), so the adapter
writes nothing (ADR-0309 §2:6). What the reader does: every message its own activation
once its start wait has passed, whatever runs (ADR-0349 §8:1), what arrived inside one
start wait taken in together as one input, a repeated send taken in once, the state
reading *working…* and then how it ended, a shutdown writing nothing, and the window
the transcript. Each case here is one of today's run with the
phases wired, so it stays pinned once the switch lands.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from phases_support import (
    SETTLE,
    Gated,
    answered,
    episodes,
    hold_start_waits,
    idle,
    input_of,
    open_conversation,
    phases_harness,
    said,
    until,
    working,
    written,
)
from structlog.testing import capture_logs
from test_engine import AT, Harness
from understanding_support import STATED_PROPOSAL, rendered, understanding_stage

from ai_assistant.core.errors import ConversationStoreError, ModelError
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    MessageAuthor,
    ProcessingStatus,
    ToolOutcome,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanStore,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange, RoundResponse


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

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__(now=lambda: AT)
        self.calls = 0
        self._error = error

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        self.calls += 1
        if self.calls == 2:
            if self._error is not None:
                raise self._error
            msg = "the store is busy"
            raise ConversationStoreError(msg)
        return await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )


class _HeldSecondMarking(FakeConversationStore):
    """A store whose second ``take_in`` call waits for :attr:`release`, then fails.

    The first call commits, so the activation has marked messages before its phases
    begin; :attr:`entered` is set once the second call is waiting.
    """

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        self.calls += 1
        if self.calls == 2:
            self.entered.set()
            await self.release.wait()
            msg = "the store is busy"
            raise ConversationStoreError(msg)
        return await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )


class _FailingRounds(FakeToolCallingCompleter):
    """Planning whose every round raises ``error`` as itself, once the phases began."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
        raise self._error


async def _backlog(store: FakeConversationStore, memory: FakeMemoryStore) -> str:
    """A conversation holding more waiting messages than one marking call takes in."""
    before = _idle(store, memory)
    conversation = await open_conversation(before)
    for n in range(1, 1002):
        await before.engine.write_message(conversation, message=said(f"m-{n}", f"w{n}"))
    await before.engine.aclose()
    return conversation


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


async def test_a_backlog_past_one_marking_call_is_still_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0332 §5:1: every message waiting in one start wait is taken in together,
    whatever the store's bound, beside the activation already running (ADR-0349 §8:1)."""
    completer = Gated()
    harness = phases_harness(completer, chat_start_wait=timedelta(milliseconds=200))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-0", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    for n in range(1, 1002):
        await harness.engine.write_message(conversation, message=said(f"m-{n}", f"w{n}"))
    over.set()
    completer.release.set()
    await answered(harness, conversation, 2)
    inputs = sorted((input_of(one) for one in await episodes(harness.memory)), key=len)
    assert inputs[0] == "first"
    assert inputs[1].split("\n\n") == [f"w{n}" for n in range(1, 1002)]


async def test_a_reply_written_during_a_messages_start_wait_is_marked_as_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6: the window shows that a message was written before the reply it follows.

    The reply lands while the message waits out its start wait (ADR-0349 §8:2).
    """
    model = FakeModelProvider(STATED_PROPOSAL)
    completer = Gated()
    harness = phases_harness(
        completer,
        understanding=understanding_stage(model=model),
        chat_start_wait=timedelta(milliseconds=200),
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    # The engine is not told of this start wait, so the first one's act does not wait
    # for it (ADR-0349 §7:12) and its reply lands inside it, as a reply from work that
    # waits on nothing here would: the window is the case, not the waits.
    reader = harness.engine._chat_reader
    assert reader is not None
    monkeypatch.setattr(reader, "_hold", None)
    await harness.engine.write_message(conversation, message=said("m-2", "meanwhile"))
    completer.release.set()
    await answered(harness, conversation, 1)
    over.set()
    await answered(harness, conversation, 2)
    message = rendered(model.calls[-1].messages)
    assert message.stimulus == "meanwhile"
    window = message.tags("Stimulus origin knowledge", "message")
    assert [(item.text, item.get("after_stimulus")) for item in window] == [
        ("first", None),
        (window[1].text, "yes"),
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
    assert running.state.activation_ids == (taken[1],)
    completer.release.set()
    await answered(harness, conversation, 1)
    ended = await harness.engine.conversation(conversation)
    assert ended is not None
    assert not ended.state.working
    assert ended.state.activation_ids == ()
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
        "DELETED ORDER" not in one
        for call in completer.calls
        for one in (call.exchange.instruction, call.exchange.briefing)
    )


async def test_messages_written_while_one_runs_start_their_own_activation_as_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0349 §8:1: nothing is refused or held back; what arrived inside one start wait
    is one input (ADR-0332 §5:1), taken in while the first still runs."""
    completer = Gated()
    harness = phases_harness(completer, chat_start_wait=timedelta(milliseconds=200))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "first"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    over = hold_start_waits(harness, monkeypatch)
    second = await harness.engine.write_message(conversation, message=said("m-2", "second"))
    third = await harness.engine.write_message(conversation, message=said("m-3", "third"))
    assert (second.position, third.position) == (2, 3)
    over.set()

    async def both_taken() -> bool:
        marked = await harness.conversation_store.taken_in(conversation, positions=[2, 3])
        return len(marked) == 2

    await until(both_taken, what="the waiting messages to be taken in")
    state = await harness.engine.conversation(conversation)
    assert state is not None
    assert state.state.working
    assert len(state.state.activation_ids) == 2, "both run, and the state names both"
    assert not completer.release.is_set(), "taken in while the first still runs"
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


async def test_a_marking_that_fails_part_way_ends_as_couldnt_finish() -> None:
    """ADR-0317 §3:3, ADR-0293 §10:2: what was marked is consumed, so its activation's
    failure is written; what was not is taken in by the next activation."""
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


async def test_a_defect_marking_part_way_is_logged_at_error_and_still_answered() -> None:
    """#2904: before the phases began too, a defect is told apart only in the log."""
    store = _FailsSecondMarking(ValueError("the user's private words"))
    memory = FakeMemoryStore(now=lambda: AT)
    conversation = await _backlog(store, memory)
    after = phases_harness(conversation_store=store, memory=memory)
    with capture_logs() as logs:
        await after.engine.start()
        messages = await answered(after, conversation, 2)
    replies = [one.text for one in messages if one.author is MessageAuthor.ASSISTANT]
    assert replies == [COULDNT_FINISH, DEFAULT_ROUND_TEXT]
    (line,) = [one for one in logs if one["log_level"] == "error"]
    assert line["event"] == "chat_activation_failed"
    assert (line["stage"], line["error"]) == ("chat_reader", "ValueError")
    taken = await store.taken_in(conversation, positions=[1])
    assert line["activation_id"] == taken[1]
    assert "private words" not in repr(logs)


@pytest.mark.parametrize("error", [ModelError("provider down"), ValueError("a bug")])
async def test_a_failure_once_the_phases_began_writes_couldnt_finish_once(
    error: Exception,
) -> None:
    """ADR-0317 §3:3: the phases' run writes the message, and nothing again (#2900)."""
    harness = phases_harness(_FailingRounds(error))
    conversation = await open_conversation(harness)
    with capture_logs():
        await harness.engine.write_message(conversation, message=said("m-1", "hi"))
        await answered(harness, conversation, 1)
    replies = [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]
    assert replies == [COULDNT_FINISH]


async def test_a_stop_before_the_phases_began_writes_nothing() -> None:
    """ADR-0295 §3:3: a stopped activation writes no *couldn't finish*, however early."""
    store = _HeldSecondMarking()
    memory = FakeMemoryStore(now=lambda: AT)
    conversation = await _backlog(store, memory)
    after = phases_harness(conversation_store=store, memory=memory)
    await after.engine.start()
    await asyncio.wait_for(store.entered.wait(), SETTLE)
    running = await working(after, conversation)

    assert await after.engine.stop_activation(running) is ActivationStop.STOPPED
    store.release.set()

    # What the stopped activation did not mark is answered by the next (ADR-0295 §3:6),
    # and that answer is the only message written.
    messages = await answered(after, conversation, 1)
    replies = [one.text for one in messages if one.author is MessageAuthor.ASSISTANT]
    assert replies == [DEFAULT_ROUND_TEXT]
    taken = await store.taken_in(conversation, positions=[1, 1001])
    assert taken[1] == running != taken[1001]


async def test_a_shutdown_before_the_phases_began_writes_nothing() -> None:
    """§9:2: a cancellation is not a failure, so nothing is written for it."""
    store = _HeldSecondMarking()
    memory = FakeMemoryStore(now=lambda: AT)
    conversation = await _backlog(store, memory)
    after = phases_harness(
        conversation_store=store, memory=memory, drain_timeout=timedelta(milliseconds=10)
    )
    await after.engine.start()
    await asyncio.wait_for(store.entered.wait(), SETTLE)
    await after.engine.aclose()

    assert all(one.author is MessageAuthor.USER for one in await written(after, conversation))


class _HeldFinish(FakePlanStore):
    """A plan store whose effect finishes wait, once the place took the message."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.entered = asyncio.Event()

    async def finish_activation_effect(
        self,
        effect_id: str,
        /,
        outcome: ToolOutcome,
        *,
        reason: str | None = None,
        position: int | None = None,
    ) -> None:
        del effect_id, outcome, reason, position
        self.entered.set()
        await asyncio.Event().wait()


async def test_a_shutdown_once_couldnt_finish_landed_keeps_it_as_the_outcome() -> None:
    """ADR-0284 §4:1: the episode's outcome is what the place took, however it was cut."""
    store = _FailsSecondMarking()
    memory = FakeMemoryStore(now=lambda: AT)
    plans = _HeldFinish()
    conversation = await _backlog(store, memory)
    after = phases_harness(
        conversation_store=store,
        memory=memory,
        plans=plans,
        drain_timeout=timedelta(milliseconds=10),
    )
    with capture_logs():
        await after.engine.start()
        await asyncio.wait_for(plans.entered.wait(), SETTLE)
        await after.engine.aclose()

    replies = [
        one.text
        for one in await written(after, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]
    assert replies == [COULDNT_FINISH]
    (episode,) = await episodes(memory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED
    assert episode.outcome == COULDNT_FINISH


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
    message = rendered(model.calls[-1].messages)
    assert message.stimulus == "Who is it?"
    window = message.tags("Stimulus origin knowledge", "message")
    assert [(item.get("label"), item.get("from"), item.text) for item in window] == [
        ("H1", "the owner", "My dentist is Rao."),
        ("H2", "the system", DEFAULT_ROUND_TEXT),
    ]
    # §4:5: the input names the message it replies to by its label.
    (words,) = message.tags("The stimulus")
    assert words.get("replies_to") == "H1"
    assert all(item.get("after_stimulus") is None for item in window)
