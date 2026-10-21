"""The readers' half of joining and the line's ``/stop``, through the engine (ADR-0332).

Each case drives whole passes over the phases, with the hub chat's reader or the line's
over their fakes, as ADR-0332 §1:3's third step builds them:

- a message on a place while its activation runs and has not committed joins it, is
  recorded on its episode and marked taken in by it (§3:3, §3:16, §3:18);
- §1:4's first case on both places: a stop while understanding runs, then a message,
  then the stage's end — the message joins nothing, waits, and is taken in when the
  stopped activation ends (§3, ADR-0295 §3:6);
- the line's ``/stop`` stops its running activation, which writes nothing, and the line
  answers by rule (§8:4-§8:5);
- the composing signal reaches the hub chat's reader (§5:9);
- the per-place rule as the kinds declare it (§2:3).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import (
    SETTLE,
    Gated,
    answered,
    frozen,
    input_of,
    open_conversation,
    phases_harness,
    processing,
    said,
    stopped,
    until,
    working,
)
from telegram_support import (
    CASE_START_WAIT,
    CHAT,
    REFERENCE,
    YieldingTelegram,
    stop_command,
    text,
)
from test_engine import AT
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    TelegramIntakeRecordError,
)
from ai_assistant.core.types import (
    ActivationStop,
    ChannelIdentity,
    InputOrigin,
    RecordedInputMessage,
    TelegramIntakeKind,
)
from ai_assistant.orchestration.channel_kinds import one_at_a_time
from ai_assistant.orchestration.chat import (
    DEFAULT_CHAT_COMPOSING_CAP,
    DEFAULT_CHAT_COMPOSING_LAPSE,
    DEFAULT_CHAT_START_WAIT,
)
from ai_assistant.orchestration.joining import (
    JoiningInput,
    input_standing,
    join_running,
    place_busy,
)
from ai_assistant.orchestration.telegram import (
    DEFAULT_TELEGRAM_START_WAIT,
    NOTHING_RUNNING_LINE,
    STOPPED_LINE,
    TELEGRAM,
    TelegramLineSeams,
    line_channel,
)
from ai_assistant.testing import (
    FakeConversationStore,
    FakeModelProvider,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import EpisodicMemory, Message, TelegramIntake

#: The line's channel, keyed by its connection and its chat.
_LINE: Final = line_channel(REFERENCE, CHAT)


class _GatedUnderstanding(FakeModelProvider):
    """Understanding's model, answering only once :attr:`release` is set."""

    def __init__(self) -> None:
        super().__init__(reply=STATED_PROPOSAL)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.entered.set()
        await self.release.wait()
        return await super().complete(messages, model=model)


class _Line:
    """The line's fakes, and the seams the engine is handed."""

    def __init__(self) -> None:
        self.fake = FakeTelegramBotClient(chat_id=CHAT, first_message_id=700)
        self.intake = FakeTelegramIntakeRecord()
        self.seams = TelegramLineSeams(
            client=YieldingTelegram(self.fake),
            intake=self.intake,
            reference=REFERENCE,
            poll_wait=timedelta(seconds=1),
            poll_bound=timedelta(seconds=2),
            send_bound=timedelta(seconds=1),
            start_wait=CASE_START_WAIT,
        )

    def sent(self) -> list[str]:
        return [body for _, body in self.fake.messages]


async def _frozen(harness: Harness, count: int) -> list[EpisodicMemory]:
    async def done() -> bool:
        return len(await frozen(harness)) >= count

    await until(done, what=f"{count} frozen episode(s)")
    return await frozen(harness)


def _started_by(found: Sequence[EpisodicMemory], text: str) -> EpisodicMemory:
    (episode,) = [one for one in found if input_of(one) == text]
    return episode


# --- the hub chat ----------------------------------------------------------------------


async def test_a_message_written_before_it_commits_joins_it_on_its_episode() -> None:
    """§3:3, §3:16, §3:18: one activation, its episode naming the join, marked by it."""
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    await harness.engine.write_message(conversation, message=said("m-2", "for Saturday"))

    async def marked() -> bool:
        return bool(await harness.conversation_store.taken_in(conversation, positions=[2]))

    await until(marked, what="the joined message to be marked")
    completer.release.set()
    (episode,) = await _frozen(harness, 1)
    await answered(harness, conversation, 1)

    record = processing(episode)
    assert record.activation_id == running
    (joined,) = record.joined
    assert [(one.text, one.position) for one in joined.messages] == [("for Saturday", 2)]
    assert joined.channel == ChannelIdentity(channel_type="conversation", instance_id=conversation)
    assert joined.taken_over_from is None
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken == {1: running, 2: running}, "marked taken in by the activation it joined"
    assert len(await frozen(harness)) == 1, "no second activation took it in"


async def test_a_stop_while_understanding_runs_then_a_message_waits_and_is_taken_in_after() -> None:
    """§1:4's first case on the hub chat: the stop holds nothing back (ADR-0295 §3:6)."""
    model = _GatedUnderstanding()
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    await harness.engine.write_message(conversation, message=said("m-2", "make it Saturday"))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert await harness.conversation_store.taken_in(conversation, positions=[2]) == {}, (
        "it joins nothing, and waits"
    )
    model.release.set()

    found = await _frozen(harness, 2)
    await answered(harness, conversation, 1)
    first = _started_by(found, "book Riverside")
    later = _started_by(found, "make it Saturday")
    stopped(first)
    assert processing(first).joined == ()
    assert processing(later).activation_id != running
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken == {1: running, 2: processing(later).activation_id}


async def test_the_composing_signal_reaches_the_chats_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:9: the engine hands the signal to the reader, after the Writing check."""
    harness = phases_harness()
    conversation = await open_conversation(harness)
    reader = harness.engine._chat_reader
    assert reader is not None
    signalled: list[str] = []
    monkeypatch.setattr(reader, "composing", signalled.append)

    await harness.engine.composing(conversation)

    assert signalled == [conversation]
    assert await harness.conversation_store.untaken_messages(conversation) == ()


def test_the_engines_waits_are_the_settings_defaults_and_held_to_their_bounds() -> None:
    """§6:1-§6:4: the engine's own defaults are the settings', and a bad set is refused."""
    fields = Settings.model_fields
    assert fields["chat_start_wait"].default == DEFAULT_CHAT_START_WAIT
    assert fields["chat_composing_lapse"].default == DEFAULT_CHAT_COMPOSING_LAPSE
    assert fields["chat_composing_cap"].default == DEFAULT_CHAT_COMPOSING_CAP
    assert fields["telegram_start_wait"].default == DEFAULT_TELEGRAM_START_WAIT
    with pytest.raises(ConfigurationError, match="ADR-0332"):
        phases_harness(chat_start_wait=timedelta(seconds=11))
    with pytest.raises(ValueError, match="ADR-0332"):
        TelegramLineSeams(
            client=YieldingTelegram(FakeTelegramBotClient(chat_id=CHAT)),
            intake=FakeTelegramIntakeRecord(),
            reference=REFERENCE,
            poll_wait=timedelta(seconds=1),
            poll_bound=timedelta(seconds=2),
            send_bound=timedelta(seconds=1),
            start_wait=timedelta(0),
        )


# --- the line ---------------------------------------------------------------------------


def _line_harness(line: _Line, **knobs: Any) -> Harness:
    return phases_harness(telegram=line.seams, **knobs)


async def _line_running(harness: Harness) -> str:
    """The id of the activation the line's reader runs, once it has one."""
    reader = harness.engine._telegram_reader
    assert reader is not None
    found: list[str] = []

    async def shown() -> bool:
        if reader.working is not None:
            found.append(reader.working)
        return bool(found)

    await until(shown, what="the line's activation to run")
    return found[0]


async def test_a_message_on_the_line_before_it_commits_joins_it() -> None:
    """§3:3, §3:18 on the line: one activation, the join on its episode, marked by it."""
    line = _Line()
    completer = Gated()
    harness = _line_harness(line, completer=completer)
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await _line_running(harness)

    line.fake.hold(text(2, "for Saturday", message_id=41))

    held: list[TelegramIntake] = []

    async def marked() -> bool:
        held.extend((await line.intake.recorded([2])).values())
        return bool(held)

    await until(marked, what="the joined update to be marked")
    completer.release.set()
    (episode,) = await _frozen(harness, 1)
    await harness.engine.aclose()

    record = processing(episode)
    (joined,) = record.joined
    assert [(one.text, one.position) for one in joined.messages] == [("for Saturday", 41)]
    assert joined.channel == _LINE
    assert (held[0].kind, held[0].activation_id) == (TelegramIntakeKind.TAKEN_IN, running)


async def test_a_stop_on_the_line_while_understanding_runs_then_a_message_waits() -> None:
    """§1:4's first case on the line: the ``/stop``, a message, then the stage's end."""
    line = _Line()
    model = _GatedUnderstanding()
    harness = _line_harness(line, understanding=understanding_stage(model=model))
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await _line_running(harness)

    line.fake.hold(stop_command(2))
    answered_as: list[TelegramIntake] = []

    async def answered_stop() -> bool:
        answered_as.extend((await line.intake.recorded([2])).values())
        return STOPPED_LINE in line.sent() and bool(answered_as)

    await until(answered_stop, what="the stop to be answered")
    line.fake.hold(text(3, "make it Saturday", message_id=42))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert 3 not in await line.intake.recorded([3]), "it joins nothing, and waits"
    model.release.set()

    found = await _frozen(harness, 2)
    await harness.engine.aclose()

    first = _started_by(found, "book Riverside")
    later = _started_by(found, "make it Saturday")
    stopped(first)
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    assert line.sent()[0] == STOPPED_LINE, "the stopped activation wrote nothing"
    assert answered_as[0].kind is TelegramIntakeKind.ANSWERED
    assert processing(later).activation_id != running


async def test_a_stop_on_the_line_with_nothing_running_stops_nothing() -> None:
    """§8:5: answered "Nothing was running.", and no activation starts."""
    line = _Line()
    harness = _line_harness(line)
    line.fake.hold(stop_command(1))
    await harness.engine.start()

    async def confirmed() -> bool:
        return line.fake.held == () and bool(line.sent())

    await until(confirmed, what="the stop to be answered and confirmed")
    await harness.engine.aclose()

    assert line.sent() == [NOTHING_RUNNING_LINE]
    assert await frozen(harness) == []


# --- the per-place rule (§2:3) ----------------------------------------------------------


def test_the_conversation_kind_and_the_line_run_one_activation_at_a_time() -> None:
    """§2:3: as the kinds declare it; every other kind runs side by side (§2:2)."""
    assert one_at_a_time("conversation")
    assert TELEGRAM.one_at_a_time
    assert one_at_a_time(TELEGRAM.channel_type)
    assert not one_at_a_time("upcoming_event")


async def test_a_join_on_a_place_that_runs_side_by_side_joins_nothing() -> None:
    """§2:2-§2:3: only a place that runs one activation at a time takes joins."""
    elsewhere = ChannelIdentity(channel_type="upcoming_event", instance_id="calendar")
    joining = JoiningInput(
        channel=elsewhere,
        messages=(RecordedInputMessage(text="hi", sent_at=AT),),
        standing=input_standing(origin=InputOrigin.USER, established=True),
    )
    assert join_running((), joining, limit=3, at=AT) is None
    assert not place_busy((), elsewhere)
    assert not place_busy((), _LINE)


# --- a joined message's marking lost with the process (§3:18) ----------------------------


class _JoinMarkingFails(FakeConversationStore):
    """A conversation store that refuses to mark one position, until told otherwise."""

    def __init__(self, refused: int) -> None:
        super().__init__(now=lambda: AT)
        self.refused: int | None = refused

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        if self.refused in positions:
            msg = "the store refuses the marking"
            raise ConversationStoreError(msg)
        return await super().take_in(
            conversation_id, positions=positions, activation_id=activation_id
        )


async def test_a_joined_message_whose_marking_never_landed_is_not_taken_in_after_a_restart() -> (
    None
):
    """§3:18 through a restart: the episode records the join, so the next hub marks it."""
    store = _JoinMarkingFails(refused=2)
    completer = Gated()
    harness = phases_harness(completer, conversation_store=store)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)
    await harness.engine.write_message(conversation, message=said("m-2", "for Saturday"))
    await until(
        lambda: _joined_count(harness, running), what="the message to join, its marking refused"
    )
    completer.release.set()
    (episode,) = await _frozen(harness, 1)
    await harness.engine.aclose()
    assert [one.position for one in processing(episode).joined[0].messages] == [2]
    assert await store.taken_in(conversation, positions=[2]) == {}, "never marked"

    store.refused = None
    again = phases_harness(memory=harness.memory, conversation_store=store)
    await again.engine.start()
    for _ in range(50):
        await asyncio.sleep(0.001)
    await again.engine.aclose()

    assert await store.taken_in(conversation, positions=[2]) == {2: running}
    assert len(await frozen(again)) == 1, "the restarted hub took nothing in again"


async def _joined_count(harness: Harness, activation_id: str) -> bool:
    for one in harness.engine._running:
        state = one.state
        if state is not None and state.activation_id == activation_id and state.joined:
            return True
    return False


async def test_a_joined_update_whose_marking_never_landed_is_not_taken_in_after_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3:18 through a restart on the line: Telegram hands it back, and the episode says."""
    line = _Line()
    completer = Gated()
    harness = _line_harness(line, completer=completer)
    take_in = line.intake.take_in

    async def refusing(update_ids: Sequence[int], *, activation_id: str) -> tuple[int, ...]:
        if 2 in update_ids:
            msg = "the record refuses the marking"
            raise TelegramIntakeRecordError(msg)
        return await take_in(update_ids, activation_id=activation_id)

    monkeypatch.setattr(line.intake, "take_in", refusing)
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await _line_running(harness)
    line.fake.hold(text(2, "for Saturday", message_id=41))
    await until(
        lambda: _joined_count(harness, running), what="the update to join, its marking refused"
    )
    completer.release.set()
    (episode,) = await _frozen(harness, 1)
    await harness.engine.aclose()
    assert [one.position for one in processing(episode).joined[0].messages] == [41]

    monkeypatch.setattr(line.intake, "take_in", take_in)
    again = _line_harness(line, memory=harness.memory)
    await again.engine.start()

    async def confirmed() -> bool:
        return line.fake.held == ()

    await until(confirmed, what="Telegram to be told it was dealt with")
    await again.engine.aclose()
    assert len(await frozen(again)) == 1, "the restarted hub took nothing in again"
