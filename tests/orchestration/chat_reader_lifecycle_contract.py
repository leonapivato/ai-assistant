"""Shared obligations the cutover keeps, held over the chat's reader and a started
conversation rather than ``converse`` or a spoken turn.

The clauses these replace drive their activation through ``converse`` or a spoken turn
on ``receive``, both of which retire at the cutover (ADR-0309 §5:1, ADR-0313 §3:1). What
they hold survives it: a stop naming an ended activation answers *already ended*;
forgetting reaches an activation still running on the conversation; a message's exact
text is what its episode records, and forgetting the conversation takes its episodes and
no other place's; the listing is ordered by activity; and ``receive`` refuses a typed
input to a conversation. Each is held here on every ``AssistantEngine`` — the engine,
the canonical fake and the wire client — with the activation the reader runs on a
message written into the conversation (ADR-0293 §6).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from channel_receiver_contract import event_input, read_episode
from chat_surface_contract import (
    _PHONE,
    _SETTLE,
    ChatReaderSubject,
    _answered,
    _held_take_in,
    _input_of,
    _started,
    _until,
    _working,
    said,
)

from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    ChannelIdentity,
    ChannelInput,
    ConversationState,
    NewConversation,
    ProcessingReason,
    StreamingTextReply,
    TextChannelPayload,
    WholeTextReply,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

_BUDGET = timedelta(seconds=10)


async def _answered_once(subject: ChatReaderSubject, conversation: str, text: str) -> str:
    """Write ``text``, wait for the reader's activation to end, and return its id."""
    engine = subject.engine
    receipt = await engine.write_message(conversation, message=said(_PHONE, f"m-{text}", text))
    position = receipt.position
    assert position is not None

    async def ended() -> bool:
        marked = await subject.chat.taken_in(conversation, positions=[position])
        digest = await engine.conversation(conversation)
        return bool(marked) and digest is not None and not digest.state.working

    await _until(ended, what="the message to be taken in and its activation to end")
    await _answered(engine, conversation, 1)
    marked = await subject.chat.taken_in(conversation, positions=[position])
    return marked[position]


class ChatReaderLifecycleContract:
    """What the retired drivers held, held over the reader (ADR-0293 §2, §6, §11)."""

    async def test_a_stop_naming_an_activation_the_reader_ended_answers_already_ended(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0297 §5:4: its episode stands at its address, and nothing is written."""
        engine = chat_reader_surface.engine
        conversation = await _started(engine, _PHONE)
        ended = await _answered_once(chat_reader_surface, conversation, "hello")
        address = f"activation:{ended}"
        before = await read_episode(engine, address)

        answer = await engine.stop_activation(ended)

        assert answer is ActivationStop.ALREADY_ENDED
        after = await read_episode(engine, address)
        assert after == before
        assert after.processing_record is not None
        assert after.processing_record.reason is not ProcessingReason.STOPPED
        digest = await engine.conversation(conversation)
        assert digest is not None
        assert digest.state == ConversationState(last_ended=ActivationEnding.DONE)

    async def test_forgetting_reaches_an_activation_the_reader_is_running(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0293 §2:6: an activation running when its conversation is forgotten leaves
        no episode once it finishes, and the conversation stays.

        The reader's activation is held at its marking, so it is running — "working…",
        with its id — when the conversation is forgotten.
        """
        engine, memory = chat_reader_surface.engine, chat_reader_surface.memory
        conversation = await _started(engine, _PHONE)
        entered, release = _held_take_in(chat_reader_surface.chat)
        await engine.write_message(conversation, message=said(_PHONE, "m-1", "hi"))
        try:
            async with asyncio.timeout(_SETTLE):
                await entered.wait()
            running = await _working(engine, conversation)
            # Whether anything was held yet is the implementation's: the engine admits
            # with an open episode (ADR-0286), the fake records only at capture.
            await engine.forget_conversation(conversation)
        finally:
            release.set()

        async def idle() -> bool:
            digest = await engine.conversation(conversation)
            return digest is not None and not digest.state.working

        await _until(idle, what="the forgotten activation to end")
        assert await memory.get(f"activation:{running}") is None
        channel = ChannelIdentity(channel_type="conversation", instance_id=conversation)
        assert (await engine.episodes(channel=channel)).items == ()
        assert await engine.conversation(conversation) is not None

    async def test_a_messages_exact_text_is_its_input_and_forgetting_takes_only_its_place(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0293 §2:4, §6:1: what the user wrote is recorded byte for byte, and
        forgetting the conversation takes every episode on it and none elsewhere."""
        engine, memory = chat_reader_surface.engine, chat_reader_surface.memory
        exact = "  café\nexact input "
        conversation = await _started(engine, _PHONE)
        first = await _answered_once(chat_reader_surface, conversation, exact)
        second = await _answered_once(chat_reader_surface, conversation, f"{exact}again")
        event = await engine.receive(event_input(), reply=None, timeout=_BUDGET)
        channel = ChannelIdentity(channel_type="conversation", instance_id=conversation)
        typed = (await engine.episodes(channel=channel)).items
        assert {row.position.episode_id for row in typed} == {
            f"activation:{first}",
            f"activation:{second}",
        }
        assert await _input_of(memory, first) == exact

        assert await engine.forget_conversation(conversation) is True

        for row in typed:
            assert await engine.episode_chunk(row.position.episode_id) is None
        assert event.capture.episode_id is not None
        assert await engine.episode_chunk(event.capture.episode_id) is not None

    async def test_conversations_are_listed_by_activity_and_not_by_last_message(
        self, chat_reader_surface: ChatReaderSubject
    ) -> None:
        """ADR-0074 §2: most recently active first, and the key is never "has a message
        landed" — a conversation opened a minute ago is not sunk below an older one."""
        engine = chat_reader_surface.engine
        first = await _started(engine, _PHONE)
        await _answered_once(chat_reader_surface, first, "one")
        second = await _started(engine, _PHONE)
        assert [one.id for one in await engine.recent_conversations()] == [second, first]

        await _answered_once(chat_reader_surface, first, "again")

        listed = await engine.recent_conversations()
        assert [one.id for one in listed] == [first, second]
        assert listed[0].last_active_at >= listed[1].last_active_at

    @pytest.mark.parametrize("reply", [WholeTextReply(), StreamingTextReply()])
    @pytest.mark.parametrize("fresh", [True, False])
    async def test_a_typed_input_to_a_conversation_is_refused_and_starts_nothing(
        self, engine: AssistantEngine, reply: WholeTextReply | StreamingTextReply, fresh: bool
    ) -> None:
        """ADR-0293 §11: the text conversational combination is off the surface.

        A typed message is written into a conversation as an act in the medium, so
        ``receive`` refuses one before any work — whichever reply it offers, and whether
        it names a started conversation or asks for a new one — and nothing is recorded.
        """
        conversation = (await engine.start_conversation()).id
        before = await engine.episodes()
        listed = await engine.recent_conversations()
        target = (
            NewConversation()
            if fresh
            else ChannelIdentity(channel_type="conversation", instance_id=conversation)
        )
        supplied = ChannelInput(target=target, payload=TextChannelPayload(text="Hello"))
        with pytest.raises(ValueError, match="unsupported channel"):
            await engine.receive(supplied, reply=reply, timeout=_BUDGET)  # type: ignore[arg-type]  # the refused combination, on purpose
        assert await engine.episodes() == before
        assert await engine.recent_conversations() == listed
