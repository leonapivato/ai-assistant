"""A channel's reader reads a work's window only once its sight is made (ADR-0383 §7:9).

Milestone 22's B8b. The hub chat's reader and the line's admit a work with its own inputs,
the messages they take in, which reach it as its input and not through the filter; only
once the activation has marked them, its sight made at its admission, is its window read,
and every read made for it is of a store the holder binds to that sight (§7:7): the
transcript, the bookkeeping's links, the effect records, the Task Scheduler's episodes and
the line's cards. With stores built to withhold, the windows answer by §6's table: an
unidentified sender's work is shown none of its chat's earlier messages, and the owner's,
at normal or lowered to weak, reads its window as today. In the counting build the windows
are as today and each read writes its count as a work's (§11:1). Through the engine, no
window read is made but inside the admitted work, by its sight.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import (
    answered,
    frozen,
    open_conversation,
    phases_harness,
    processing,
    say,
    until,
)
from sight_support import OWNER_WEAK, UNIDENTIFIED, sight_of
from structlog.testing import capture_logs
from task_support import schedule_episode
from task_support import seams as task_seams
from telegram_support import CHAT, REFERENCE, text
from test_engine import AT
from test_phases_telegram import _harness as _line_harness
from test_phases_telegram import _Line as _EngineLine
from test_phases_telegram import _settled as _line_settled
from test_telegram_reader import (
    _calling_episode,
    _card_on_the_line,
    _Line,
    _sent,
)

from ai_assistant.core.errors import ConversationStoreError, MemoryStoreError
from ai_assistant.core.types import (
    ActivationEffect,
    CallOutcomeKind,
    ChatDevice,
    DeliveryStatus,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
    ProcessingStatus,
    RecordedCall,
    RecordedDelivery,
    RecordedInputMessage,
    RecordHome,
    SightMode,
    TelegramIntakeKind,
    ToolOutcome,
)
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.channel_kinds import place_of
from ai_assistant.orchestration.chat import COULDNT_FINISH, ChatInput, ChatReader
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.orchestration.telegram import line_channel
from ai_assistant.orchestration.understanding import WrittenBy
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakePlanStore,
    FakeStoryStore,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.parties import OWNER_SENDER

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, MutableMapping, Sequence

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import (
        ChannelEpisodePage,
        ChannelIdentity,
        InputSender,
        Sight,
        TranscriptPage,
    )
    from ai_assistant.orchestration.understanding import TranscriptWindow

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_A: Final = "act-a"
_B: Final = "act-b"
_SETTLE: Final = 5.0

#: The senders whose work reads as the owner's: §6's first row, at normal and lowered.
_OWNERS: Final = pytest.mark.parametrize(
    "sender", [OWNER_SENDER, OWNER_WEAK], ids=["normal", "weak"]
)


async def _by_effects(
    place: str, activation_ids: Sequence[str], positions: Sequence[int] | None, plans: PlanStore
) -> Mapping[int, WrittenBy]:
    """The phases' ``written_in``, over the plan store the reader hands it bound."""
    del place
    wanted = None if positions is None else frozenset(positions)
    return {
        one.position: WrittenBy(activation_id=one.activation_id, round=one.round)
        for one in await plans.activation_effects(activation_ids)
        if one.position is not None
        and one.outcome is ToolOutcome.SUCCEEDED
        and (wanted is None or one.position in wanted)
    }


async def _wrote(plans: FakePlanStore, activation_id: str, place: str, position: int) -> None:
    """``activation_id``'s message at ``position`` in ``place``, by its effect record."""
    effect = ActivationEffect(
        home=RecordHome.owners(),
        id=f"effect:{activation_id}:{position}",
        activation_id=activation_id,
        round="round:1",
        place=place,
        claimed_at=AT,
    )
    await plans.claim_activation_effect(effect, match=None)
    await plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED, position=position)


# --- the hub chat ---------------------------------------------------------------------------


async def _chat(store: FakeConversationStore, plans: FakePlanStore) -> str:
    """The owner's conversation: A took in 1 and wrote 2; B took in 3 and wrote 4; 5, which
    replies to 1, waits."""
    await store.set_my_devices([_PHONE])
    conversation = (await store.start(home=RecordHome.owners())).id
    for n, author in enumerate((MessageAuthor.USER, MessageAuthor.ASSISTANT) * 2, 1):
        user = author is MessageAuthor.USER
        await store.append_message(
            conversation,
            NewMessage(
                author=author,
                text=f"message {n}",
                device_id=_PHONE.device_id if user else None,
                message_id=f"m-{n}" if user else None,
                home=RecordHome.owners(),
            ),
        )
    await store.append_message(
        conversation,
        NewMessage(
            author=MessageAuthor.USER,
            text="message 5",
            device_id=_PHONE.device_id,
            message_id="m-5",
            replies_to=1,
            home=RecordHome.owners(),
        ),
    )
    for position, activation_id in ((1, _A), (3, _B)):
        await store.take_in(conversation, positions=[position], activation_id=activation_id)
    for position, activation_id in ((2, _A), (4, _B)):
        await _wrote(plans, activation_id, f"conversation:{conversation}", position)
    return conversation


async def _chat_input(mode: SightMode, sight: Sight) -> ChatInput:
    """The input the hub chat's reader brings in for the waiting message, as the engine's
    activation has it once admitted: marked, then its window read by ``sight``."""
    store = FakeConversationStore(now=lambda: AT, new_id=lambda: "c-1", sight_mode=mode)
    plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
    conversation = await _chat(store, plans)
    taken: list[ChatInput] = []
    tasks: list[asyncio.Future[None]] = []

    async def activate(one: ChatInput) -> bool:
        marked: list[int] = []
        await reader.take_in(one, into=marked)
        taken.append((await reader.windowed(one, sight=sight)).narrowed(marked))
        return bool(marked)

    reader = ChatReader(
        conversations=store,
        activate=activate,
        spawn=lambda work: tasks.append(asyncio.ensure_future(work)),
        closing=lambda: False,
        mint=lambda: "00000000-0000-4000-8000-00000000000c",
        window_size=2,
        stores=BoundStores(
            memory=FakeMemoryStore(now=lambda: AT, sight_mode=mode),
            stories=FakeStoryStore(now=lambda: AT, sight_mode=mode),
            conversations=store,
            plans=plans,
        ),
        written=_by_effects,
    )
    reader.notice(conversation)
    await asyncio.wait_for(asyncio.gather(*tasks), _SETTLE)
    (one,) = taken
    return one


def _window(taken: ChatInput) -> TranscriptWindow:
    assert taken.window is not None
    return taken.window


def _shown(window: TranscriptWindow) -> tuple[list[int], list[int], dict[int, str]]:
    return (
        [one.position for one in window.messages],
        [one.position for one in window.replied_to],
        dict(window.links),
    )


#: The owner's window today: the recent two, the message the input replies to, and each
#: linked to what took it in or wrote it.
_CHAT_TODAY: Final = ([3, 4], [1], {1: _A, 3: _B, 4: _B})


async def test_an_unidentified_senders_work_in_the_hub_chat_gets_its_own_messages_alone() -> None:
    """§6's second row, §7:9: its own messages are its input, and its chat's earlier
    messages, the one it replies to among them, are withheld."""
    taken = await _chat_input(SightMode.WITHHOLD, sight_of(UNIDENTIFIED, at=AT))
    assert [one.text for one in taken.messages] == ["message 5"]
    window = _window(taken)
    assert window.input_messages == taken.messages
    assert _shown(window) == ([], [], {})


@_OWNERS
async def test_the_owners_work_reads_its_hub_chat_window_as_today(sender: InputSender) -> None:
    """§6's first row: the owner's domain, at every level, as the unbound read gave it."""
    taken = await _chat_input(SightMode.WITHHOLD, sight_of(sender, at=AT))
    window = _window(taken)
    assert _shown(window) == _CHAT_TODAY
    # The same window the counting build reads, which answers as the unbound store does.
    assert window == _window(await _chat_input(SightMode.COUNT, sight_of(sender, at=AT)))
    assert [one.text for one in window.messages] == ["message 3", "message 4"]


# --- the line -------------------------------------------------------------------------------


async def _line_window(mode: SightMode, sight: Sight) -> tuple[TranscriptWindow, int, str]:
    """The line's window for a message after an exchange that asked by card, read by
    ``sight``; with the card's position and words."""
    memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
    plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
    line = _Line(memory=memory, plans=plans, written_bound=_by_effects, sight=sight)
    request = await _card_on_the_line(line, plans)
    (card,) = request.cards
    assert card.position is not None
    words = dict(line.fake.messages)[card.position]
    channel = line.seams.channel
    await _wrote(plans, "act-ask", place_of(channel), 21)
    await memory.add(
        _calling_episode(
            "act-ask",
            (RecordedInputMessage(text="Book the table", sent_at=AT, position=20),),
            channel=channel,
            rounds=(("round:1", ("call-1", "call-2")),),
            entries=(
                _sent("round:1", "call-1", "I'll ask you first.", went=channel),
                RecordedCall(
                    round="round:1",
                    call_id="call-2",
                    capability="request_approval",
                    effect=True,
                    outcome=CallOutcomeKind.DONE,
                    delivered=RecordedDelivery(
                        words=words, went=channel, status=DeliveryStatus.SENT
                    ),
                    recorded_at=AT,
                ),
            ),
        )
    )
    line.fake.hold(text(40, "and then?", message_id=990))
    line.start()
    await line.until(lambda: bool(line.windows), what="the window was read")
    await line.stop()
    (window,) = line.windows
    return window, card.position, words


async def test_an_unidentified_senders_work_on_the_line_gets_its_own_messages_alone() -> None:
    window, _, _ = await _line_window(SightMode.WITHHOLD, sight_of(UNIDENTIFIED, at=AT))
    assert [(one.position, one.text) for one in window.input_messages] == [(990, "and then?")]
    assert (window.messages, window.replied_to, dict(window.links)) == ((), (), {})


@_OWNERS
async def test_the_owners_work_reads_its_line_window_as_today(sender: InputSender) -> None:
    window, card, words = await _line_window(SightMode.WITHHOLD, sight_of(sender, at=AT))
    assert [(one.position, one.author, one.text) for one in window.messages] == [
        (20, MessageAuthor.USER, "Book the table"),
        (21, MessageAuthor.ASSISTANT, "I'll ask you first."),
        (card, MessageAuthor.ASSISTANT, words),
    ]
    assert dict(window.links) == {20: "act-ask", 21: "act-ask", card: "act-ask"}
    counted, _, _ = await _line_window(SightMode.COUNT, sight_of(sender, at=AT))
    assert window == counted


# --- the counting build: as today, and each read counted as a work's (§11:1) ----------------


def _counted(logs: Sequence[MutableMapping[str, Any]]) -> Iterator[tuple[object, object, object]]:
    for one in logs:
        if one["event"] == "sight_counted":
            yield one["store"], one["member"], one["reader"]


async def test_in_the_counting_build_the_windows_are_as_today_and_each_read_is_counted() -> None:
    """An unidentified sender's work reads what every work reads today; each read of its
    window writes its count, as a work's, its withheld records counted."""
    unidentified = sight_of(UNIDENTIFIED, at=AT)
    with capture_logs() as logs:
        chat = await _chat_input(SightMode.COUNT, unidentified)
        line, _, _ = await _line_window(SightMode.COUNT, unidentified)
    assert _shown(_window(chat)) == _CHAT_TODAY
    assert [one.position for one in line.messages][:2] == [20, 21]
    counted = set(_counted(logs))
    assert {
        ("conversations", "transcript", "work"),
        ("conversations", "taken_in", "work"),
        ("plans", "activation_effects", "work"),
        ("memory", "channel_episodes", "work"),
        ("plans", "person_approval_requests", "work"),
    } <= counted
    assert {reader for _, _, reader in counted} == {"work"}
    withheld = [one for one in logs if one["event"] == "sight_counted" and one["given"]]
    assert withheld
    assert all(one["sees_nothing"] == one["given"] for one in withheld)


# --- the order: no window read before the work's sight exists (§7:9) ------------------------


class _WatchedChat(FakeConversationStore):
    """A chat space that notes, for each read a window makes, the sight it was bound to and
    the work running where it was made."""

    def __init__(self, reads: list[tuple[Sight | None, Sight | None]], **knobs: Any) -> None:
        super().__init__(**knobs)
        self.reads = reads

    def _note(self) -> None:
        state = active_state()
        self.reads.append((self._sight, None if state is None else state.sight))

    async def transcript(self, conversation_id: str, **page: Any) -> TranscriptPage | None:
        self._note()
        return await super().transcript(conversation_id, **page)

    async def taken_in(
        self, conversation_id: str, *, positions: Sequence[int]
    ) -> Mapping[int, str]:
        self._note()
        return await super().taken_in(conversation_id, positions=positions)


class _WatchedMemory(FakeMemoryStore):
    """A memory store that notes each read of a watched channel's episodes: the channel, its
    page size, the sight it was bound to and the work running where it was made."""

    def __init__(
        self,
        reads: list[tuple[ChannelIdentity, int, Sight | None, Sight | None]],
        watched: frozenset[ChannelIdentity],
        **knobs: Any,
    ) -> None:
        super().__init__(**knobs)
        self.reads = reads
        self.watched = watched

    async def channel_episodes(
        self, channel: ChannelIdentity, *, after: int | None = None, limit: int
    ) -> ChannelEpisodePage:
        if channel in self.watched:
            state = active_state()
            self.reads.append((channel, limit, self._sight, None if state is None else state.sight))
        return await super().channel_episodes(channel, after=after, limit=limit)


async def test_the_hub_chats_window_is_read_inside_the_admitted_work_by_its_sight() -> None:
    """A read of the window before admission would be unbound, with no work running: each
    is bound, and made inside the work by the sight its admission made, the Task
    Scheduler's episodes read for a writer of its messages among them (ADR-0350 §9:1)."""
    reads: list[tuple[Sight | None, Sight | None]] = []
    scheduled: list[tuple[ChannelIdentity, int, Sight | None, Sight | None]] = []
    memory = _WatchedMemory(scheduled, frozenset({SCHEDULE}), now=lambda: AT)
    await memory.add(schedule_episode("a-task"))
    harness = phases_harness(
        conversation_store=_WatchedChat(reads, now=lambda: AT),
        memory=memory,
        task_scheduler=task_seams(),
    )
    conversation = await open_conversation(harness)
    await say(harness, conversation, "first")

    async def frozen_once() -> bool:
        return len(await frozen(harness)) >= 2

    await until(frozen_once, what="the first work to end")
    with capture_logs() as logs:
        await say(harness, conversation, "second", message_id="m-2")

        async def frozen_twice() -> bool:
            return len(await frozen(harness)) >= 3

        await until(frozen_twice, what="the second work to end")
    await harness.engine.aclose()

    assert reads, "the window was read"
    assert all(bound is not None and bound == working for bound, working in reads), reads
    # The second window shows the first reply, so it reads the schedule for its writer.
    assert scheduled, "the Task Scheduler's episodes were read for a writer"
    assert all(bound is not None and bound == working for _, _, bound, working in scheduled)
    windows = [
        one for one in logs if one["event"] == "sight_counted" and one["store"] == "conversations"
    ]
    # The window's reads, and the Connections section's recent conversations, which a
    # work reads through the same holder (ADR-0387 §4:3).
    assert {one["member"] for one in windows} == {"transcript", "taken_in", "recent"}
    assert all(one["reader"] == "work" and one["bounds"] == ["person_owner"] for one in windows)


async def test_the_lines_window_is_read_inside_the_admitted_work_by_its_sight() -> None:
    """The line's only unbound read of its episodes is the engine's start's, the chat's last
    activation (§7:8); every read for a work's window, the Task Scheduler's episodes
    among them, is bound, inside the work."""
    reads: list[tuple[ChannelIdentity, int, Sight | None, Sight | None]] = []
    line = _EngineLine()
    line.fake.hold(text(1, "What's on today?", message_id=40))
    channel = line_channel(REFERENCE, CHAT)
    memory = _WatchedMemory(reads, frozenset({channel, SCHEDULE}), now=lambda: AT)
    await memory.add(schedule_episode("a-task"))
    harness = _line_harness(line, memory=memory, task_scheduler=task_seams())
    await harness.engine.start()
    await _line_settled(harness)
    await harness.engine.aclose()

    unbound = [(where, limit, working) for where, limit, bound, working in reads if bound is None]
    assert unbound == [(channel, 1, None)], "only the start's read of the chat's last activation"
    windows = {
        where: [(bound, working) for one, _, bound, working in reads if one == where and bound]
        for where in (channel, SCHEDULE)
    }
    assert windows[channel], "the line's episodes were read for the window"
    assert windows[SCHEDULE], "the Task Scheduler's were read for a writer"
    assert all(bound == working for each in windows.values() for bound, working in each)


# --- a window that cannot be read: the work's failure, its input consumed (FLAG 1) ---------


class _UnreadableWindowChat(FakeConversationStore):
    """A chat space whose transcript cannot be read through a store bound to a sight: the
    window's, and no other read of it."""

    async def transcript(self, conversation_id: str, **page: Any) -> TranscriptPage | None:
        if self._sight is not None:
            msg = "the window's transcript cannot be read"
            raise ConversationStoreError(msg)
        return await super().transcript(conversation_id, **page)


async def test_a_hub_chat_window_that_cannot_be_read_fails_the_work_once_its_input_is_marked() -> (
    None
):
    """The window is read after the input is marked (§7:9, ADR-0293 §6:8), so a store that
    fails then fails the work: its input stays consumed, no stage runs, *couldn't finish*
    is written once, and its episode closes failed (ADR-0317 §3:3)."""
    completer = FakeToolCallingCompleter.scripted()
    store = _UnreadableWindowChat(now=lambda: AT)
    harness = phases_harness(completer, conversation_store=store)
    conversation = await open_conversation(harness)
    with capture_logs():
        await say(harness, conversation, "hello")
        messages = await answered(harness, conversation, 1)
    await harness.engine.aclose()

    assert [one.text for one in messages if one.author is MessageAuthor.ASSISTANT] == [
        COULDNT_FINISH
    ]
    (first,) = [one for one in messages if one.author is MessageAuthor.USER]
    (episode,) = await frozen(harness)
    record = processing(episode)
    assert await store.taken_in(conversation, positions=[first.position]) == {
        first.position: record.activation_id
    }, "consumed: marked by the work it was admitted with"
    assert completer.calls == [], "no stage ran"
    assert record.status is ProcessingStatus.FAILED


class _UnreadableWindowMemory(FakeMemoryStore):
    """A memory store whose line episodes cannot be read through a store bound to a sight:
    the window's; the start's unbound read of the chat's last activation still answers."""

    async def channel_episodes(
        self, channel: ChannelIdentity, *, after: int | None = None, limit: int
    ) -> ChannelEpisodePage:
        if self._sight is not None and channel.channel_type == "telegram":
            msg = "the window's episodes cannot be read"
            raise MemoryStoreError(msg)
        return await super().channel_episodes(channel, after=after, limit=limit)


async def test_a_line_window_that_cannot_be_read_fails_the_work_once_its_input_is_marked() -> None:
    completer = FakeToolCallingCompleter.scripted()
    line = _EngineLine()
    line.fake.hold(text(1, "What's on today?", message_id=40))
    harness = _line_harness(line, completer, memory=_UnreadableWindowMemory(now=lambda: AT))
    with capture_logs():
        await harness.engine.start()
        (episode,) = await _line_settled(harness)

        async def written_once() -> bool:
            return bool(line.sent())

        await until(written_once, what="the line's message")
    await harness.engine.aclose()

    record = processing(episode)
    assert line.sent() == [COULDNT_FINISH]
    (held,) = (await line.intake.recorded([1])).values()
    assert (held.kind, held.activation_id) == (TelegramIntakeKind.TAKEN_IN, record.activation_id)
    assert completer.calls == [], "no stage ran"
    assert record.status is ProcessingStatus.FAILED
