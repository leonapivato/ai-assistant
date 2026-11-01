"""The Telegram line's reader, against a fake Telegram (ADR-0323 §4, §5, §6:10, §10).

Driven with a stand-in for the engine's activation, which takes the input in as the
engine's does, so each case reads what the reader brought in and what it told
Telegram. What comes in is a text message or a forward from the configured account in
its private chat with the bot (§5:1); anything else is ignored and recorded nowhere
(§5:2), and a non-text message is answered by rule (§5:3). Every input starts its own
activation once its start wait has passed (ADR-0332 §5:3), whatever runs (ADR-0349
§8:1-§8:2), and the reader keeps polling, paced, while anything runs (ADR-0332
§8:7-§8:8, amending §5:7). What the start wait holds the engine is told of (ADR-0349
§7:12). A bare ``/stop`` with its entity stops every activation running from the chat
and is answered by rule once (ADR-0332 §8, ADR-0349 §4:3). An update is confirmed
only once dealt with (§5:6), and one taken in or answered once is never taken in or
answered again (§5:9). After a restart the
activation it cut off gets the one fixed message (§6:10). The window is the line's
recent episodes (§10).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING

from story_support import episode
from telegram_support import (
    AT,
    CHAT,
    REFERENCE,
    SETTLE,
    YieldingTelegram,
    photo,
    stop_command,
    text,
)

from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodicMemory,
    JoinedInput,
    MessageAuthor,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    RecordedCall,
    RecordedDelivery,
    RecordedInputMessage,
    TelegramCallKind,
    TelegramCallOutcome,
    TelegramFailure,
    TelegramForwardKind,
    TelegramForwardOrigin,
    TelegramIntake,
    TelegramIntakeKind,
    TelegramMessage,
    TelegramQuotedMessage,
    TelegramUpdate,
)
from ai_assistant.orchestration.matters import HeldInput
from ai_assistant.orchestration.telegram import (
    DEFAULT_TELEGRAM_START_WAIT,
    INTERRUPTED_LINE,
    NON_TEXT_LINE,
    NOTHING_RUNNING_LINE,
    POLL_BACKOFF,
    RUNNING_POLL_PACE,
    STOPPED_LINE,
    TYPING_RENEWAL,
    UNAVAILABLE_BACKOFF,
    TelegramInput,
    TelegramLineSeams,
    TelegramReader,
    TelegramWriter,
    is_stop_command,
    line_channel,
)
from ai_assistant.orchestration.understanding import AskedIn, LineMessage, WrittenBy
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
)
from ai_assistant.testing.parties import OWNERS_WORDS
from ai_assistant.testing.telegram import GET_UPDATES, SEND_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence


class _Hold(HeldInput):
    """A held input recording what the reader told of it, in order."""

    def __init__(self, place: ChannelIdentity, told: list[tuple[str, str | None]]) -> None:
        super().__init__(place=place)
        self._told = told
        told.append(("held", None))

    def admitted(self, activation_id: str) -> None:
        super().admitted(activation_id)
        self._told.append(("admitted", activation_id))

    def release(self) -> None:
        super().release()
        self._told.append(("released", self.activation_id))


class _Line:
    """A reader over the fakes, its activation a stand-in that takes the input in."""

    def __init__(  # noqa: PLR0913 — the fakes, the writers' links, and the two bounds a case varies
        self,
        *,
        client: FakeTelegramBotClient | None = None,
        intake: FakeTelegramIntakeRecord | None = None,
        memory: FakeMemoryStore | None = None,
        written: Callable[
            [str, Sequence[str], Sequence[int] | None], Awaitable[Mapping[int, WrittenBy]]
        ]
        | None = None,
        poll_bound: timedelta = timedelta(seconds=2),
        start_wait: timedelta = DEFAULT_TELEGRAM_START_WAIT,
    ) -> None:
        self.fake = client or FakeTelegramBotClient(chat_id=CHAT, first_message_id=900)
        self.intake = intake or FakeTelegramIntakeRecord()
        self.memory = memory or FakeMemoryStore(now=lambda: AT)
        self.telegram = YieldingTelegram(self.fake)
        self.seams = TelegramLineSeams(
            client=self.telegram,
            intake=self.intake,
            reference=REFERENCE,
            poll_wait=timedelta(0),
            poll_bound=poll_bound,
            send_bound=timedelta(seconds=1),
            start_wait=start_wait,
        )
        self.rests: list[float] = []
        self.inputs: list[TelegramInput] = []
        self.marked: list[tuple[int, ...]] = []
        self.held_then: list[dict[int, TelegramIntake]] = []
        self.gate: asyncio.Event | None = None
        # Where set, each activation marks its input only once it is.
        self.marking: asyncio.Event | None = None
        # Where set, the reader's rests last until it is.
        self.pause: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.closing = False
        # ADR-0332 §8: what the reader handed the stop, which stops what runs.
        self.stops: list[str] = []
        # ADR-0349 §7:12: what the reader told of the input its start wait held.
        self.told: list[tuple[str, str | None]] = []
        self._ids = iter(f"act-{n}" for n in range(1, 100))
        self.reader = TelegramReader(
            seams=self.seams,
            writer=TelegramWriter(
                client=self.seams.client,
                intake=self.intake,
                channel=self.seams.channel,
                send_bound=self.seams.send_bound,
                sleep=self._rest,
            ),
            memory=self.memory,
            activate=self._activate,
            stop=self._stop,
            closing=lambda: self.closing,
            mint=lambda: next(self._ids),
            written=written,
            hold=lambda place: _Hold(place, self.told),
            sleep=self._rest,
        )
        self.task: asyncio.Task[None] | None = None

    async def _rest(self, seconds: float) -> None:
        self.rests.append(seconds)
        if self.pause is not None:
            await self.pause.wait()
        await asyncio.sleep(0.001)

    async def _stop(self, activation_id: str) -> bool:
        self.stops.append(activation_id)
        return True

    async def _activate(self, taken: TelegramInput) -> bool:
        self.inputs.append(taken)
        marked: list[int] = []
        if self.marking is not None:
            await self.marking.wait()
        await self.reader.take_in(taken, into=marked)
        self.marked.append(tuple(marked))
        self.held_then.append(dict(await self.intake.recorded(taken.update_ids)))
        self.entered.set()
        gate = self.gate
        if gate is not None:
            await gate.wait()
        return bool(marked)

    def start(self) -> None:
        self.task = asyncio.ensure_future(self.reader.run())

    async def until(self, check: Callable[[], bool], *, what: str) -> None:
        """Wait for ``check`` to hold, polling the loop; fail rather than hang."""
        deadline = asyncio.get_running_loop().time() + SETTLE
        while not check():
            if asyncio.get_running_loop().time() > deadline:
                msg = f"never settled: {what}"
                raise AssertionError(msg)
            await asyncio.sleep(0.001)

    async def stop(self) -> None:
        self.reader.close()
        assert self.task is not None
        await asyncio.gather(self.task, return_exceptions=True)

    def polls(self) -> list[Mapping[str, object]]:
        return [one.parameters for one in self.fake.calls if one.method == GET_UPDATES]

    def sent(self) -> list[str]:
        return [body for _, body in self.fake.messages]


# --- what comes in (§5:1-§5:3) ----------------------------------------------------------


async def test_a_text_from_the_owner_is_one_input_taken_in_and_then_confirmed() -> None:
    line = _Line()
    line.fake.hold(text(10, "What's on tomorrow?", message_id=55))
    line.start()

    await line.until(
        lambda: any(one.get("offset") == 11 for one in line.polls()),
        what="a later poll confirmed it",
    )
    await line.stop()

    (taken,) = line.inputs
    assert taken.text == "What's on tomorrow?"
    assert taken.channel == line.seams.channel
    # ADR-0351 §2:6, §3:1: the message carries the owner's words, as the line declares.
    assert taken.recorded == (
        RecordedInputMessage(
            text="What's on tomorrow?", sent_at=AT, position=55, party=OWNERS_WORDS[0]
        ),
    )
    assert line.marked == [(10,)], "taken in by its activation as it was admitted"
    (held,) = line.held_then[0].values()
    assert (held.kind, held.activation_id) == (TelegramIntakeKind.TAKEN_IN, taken.activation_id)
    assert line.rests[0] == DEFAULT_TELEGRAM_START_WAIT.total_seconds(), (
        "taken in once the start wait has passed (ADR-0332 §5:3)"
    )
    assert line.fake.held == ()
    assert (await line.intake.export()).intake == (), "dropped once Telegram forgot it"


async def test_everything_but_the_owners_own_chat_is_ignored_and_recorded_nowhere() -> None:
    """§5:2: another account, another chat, a bot, a group, or no message at all."""
    line = _Line()
    line.fake.hold(
        text(1, "hi", sender=7, chat=7),
        text(2, "hi", chat=-100, private=False),
        text(3, "hi", sender=7),
        text(4, "hi", bot=True),
        TelegramUpdate(update_id=5),
    )
    line.start()

    await line.until(lambda: line.fake.held == (), what="every update was confirmed")
    await line.stop()

    assert line.inputs == []
    assert line.sent() == [], "the bot answers none of them"
    exported = await line.intake.export()
    assert exported.intake == (), "recorded nowhere"
    assert {one.kind for one in exported.calls} == {TelegramCallKind.POLL}


async def test_a_non_text_message_is_answered_once_by_rule_and_starts_nothing() -> None:
    line = _Line()
    line.fake.hold(photo(3))
    line.start()

    await line.until(lambda: line.fake.held == (), what="the photo was confirmed")
    await line.stop()

    assert line.inputs == []
    assert line.sent() == [NON_TEXT_LINE]
    assert line.polls()[1]["offset"] == 4, "confirmed once the record shows it answered"


async def test_an_update_taken_in_once_is_never_taken_in_again() -> None:
    """§5:9: a duplicate fetch starts no second activation and sends no second line."""
    intake = FakeTelegramIntakeRecord()
    await intake.take_in([8], activation_id="act-earlier")
    await intake.claim_reply(9)
    line = _Line(intake=intake)
    line.fake.hold(text(8, "already in"), photo(9))
    line.start()

    await line.until(lambda: line.fake.held == (), what="both were confirmed as dealt with")
    await line.stop()

    assert line.inputs == []
    assert line.sent() == []


async def test_a_forward_is_taken_in_with_its_original_sender_claimed() -> None:
    origin = TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Sam", account_id=77)
    line = _Line()
    line.fake.hold(text(1, "Lunch at noon?", forward=origin), text(2, "Is that ok?", minute=1))
    line.start()

    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()

    (taken,) = line.inputs
    forwarded, own = taken.recorded
    assert forwarded.forwarded_from is not None
    assert (forwarded.forwarded_from.name, forwarded.forwarded_from.account_id) == ("Sam", 77)
    assert own.forwarded_from is None
    assert set(taken.window.forwarded) == {1}
    assert [one.author for one in taken.window.input_messages] == [MessageAuthor.USER] * 2


# --- no place waits (ADR-0349 §8:1-§8:2, ADR-0332 §8:7-§8:8) ----------------------------


async def test_what_arrives_while_one_runs_starts_its_own_after_its_start_wait() -> None:
    """ADR-0349 §8:1-§8:2: its own start wait, then its own activation, beside the first."""
    line = _Line()
    line.gate = asyncio.Event()
    line.fake.hold(text(1, "first"))
    line.start()
    await asyncio.wait_for(line.entered.wait(), SETTLE)

    line.fake.hold(text(2, "second", minute=1), text(3, "third", minute=2))
    await line.until(lambda: len(line.inputs) == 2, what="the second was taken in")
    assert not line.gate.is_set(), "while the first still runs"
    assert line.reader.working == tuple(one.activation_id for one in line.inputs)
    assert line.rests.count(DEFAULT_TELEGRAM_START_WAIT.total_seconds()) == 2, (
        "a start wait of its own"
    )

    later = line.inputs[1]
    assert later.text == "second\n\nthird", "what arrived inside one start wait is one input"
    assert [one.sent_at for one in later.recorded] == [
        AT + timedelta(minutes=1),
        AT + timedelta(minutes=2),
    ], "each message keeps its own time (§5:4)"
    line.gate.set()
    await line.until(lambda: line.fake.held == (), what="everything was confirmed")
    await line.stop()
    assert line.reader.working == ()


async def test_an_input_its_activation_did_not_take_in_is_not_confirmed() -> None:
    """§5:6: input is confirmed once its activation is admitted and has marked it."""
    line = _Line()
    line.closing = True  # the engine is closing: nothing is admitted
    line.fake.hold(text(1, "hello"))

    await line.reader.run()

    assert line.inputs == []
    assert line.fake.held != (), "Telegram still holds it, for a restart to take in"


# --- polls (§11:10-§11:11) ----------------------------------------------------------------


async def test_a_poll_cut_off_by_the_close_is_finished_unknown() -> None:
    line = _Line()
    line.fake.hang_next()
    line.start()
    await line.until(lambda: bool(line.polls()), what="the poll was sent")

    await line.stop()

    assert line.task is not None
    assert line.task.cancelled()
    (poll,) = (await line.intake.export()).calls
    assert poll.kind is TelegramCallKind.POLL
    assert poll.outcome is TelegramCallOutcome.UNKNOWN, "never left open"


async def test_a_poll_that_is_not_done_rests_before_the_next() -> None:
    line = _Line()
    line.fake.fail_next(TelegramFailure.REFUSED)
    line.fake.fail_next(TelegramFailure.UNAVAILABLE)
    line.start()

    await line.until(lambda: len(line.polls()) >= 3, what="the reader polled again")
    await line.stop()

    assert line.rests[:2] == [
        POLL_BACKOFF.total_seconds(),
        UNAVAILABLE_BACKOFF.total_seconds(),
    ]


async def test_a_poll_at_its_bound_is_polled_again_at_once_and_takes_nothing_in() -> None:
    line = _Line(poll_bound=timedelta(milliseconds=20))
    line.fake.hang_next()
    line.fake.hold(text(1, "hello"))
    line.start()

    await line.until(lambda: bool(line.inputs), what="the next poll took it in")
    await line.stop()

    first = (await line.intake.export()).calls[0]
    assert first.outcome is TelegramCallOutcome.UNKNOWN
    assert line.rests == [DEFAULT_TELEGRAM_START_WAIT.total_seconds()], (
        "an unknown poll is polled again at once; the one rest is the start wait"
    )


def _polled(line: _Line) -> bool:
    return bool(line.polls())


# --- after a restart (§5:10, §6:10) ---------------------------------------------------------


async def _cut_off(
    status: ProcessingStatus, reason: ProcessingReason, *, confirmed: bool = False
) -> tuple[FakeTelegramIntakeRecord, FakeMemoryStore]:
    """The line's last episode, closed as given; its update 4 still held unless ``confirmed``.

    A confirmed update has left the intake record (§5:6), as the reader confirms an
    activation's updates while it runs (ADR-0332 §8:7): the episode is what remains.
    """
    intake = FakeTelegramIntakeRecord()
    if not confirmed:
        await intake.take_in([4], activation_id="act-cut")
    memory = FakeMemoryStore(now=lambda: AT)
    record = episode("act-cut", channel=line_channel(REFERENCE, CHAT))
    assert record.processing_record is not None
    await memory.add(
        record.model_copy(
            update={
                "processing_record": record.processing_record.model_copy(
                    update={"status": status, "reason": reason}
                )
            }
        )
    )
    return intake, memory


async def test_after_a_restart_the_activation_it_cut_off_gets_one_fixed_message() -> None:
    intake, memory = await _cut_off(ProcessingStatus.INTERRUPTED, ProcessingReason.HUB_STOPPED)
    line = _Line(intake=intake, memory=memory)
    line.fake.hold(text(4, "the message it took in"))
    line.start()
    await line.until(lambda: len(line.polls()) >= 2, what="the reader polled")
    await line.stop()

    again = _Line(intake=intake, memory=memory, client=line.fake)
    again.start()
    await again.until(lambda: len(again.polls()) >= 4, what="the reader polled")
    await again.stop()

    assert line.sent() == [INTERRUPTED_LINE], "sent once, after the first restart alone"
    assert line.inputs == [] == again.inputs, "what it took in is not taken in again"
    restart = [
        one for one in (await intake.export()).calls if one.kind is TelegramCallKind.INTERRUPTED
    ]
    assert [one.activation_id for one in restart] == ["act-cut"]


async def test_a_restart_after_its_updates_were_confirmed_still_sends_it() -> None:
    """§6:10 under ADR-0332 §8:7: read from the newest episode, not the intake record."""
    intake, memory = await _cut_off(
        ProcessingStatus.INTERRUPTED, ProcessingReason.HUB_STOPPED, confirmed=True
    )
    line = _Line(intake=intake, memory=memory)
    line.start()
    await line.until(lambda: bool(line.polls()), what="the reader polled")
    await line.stop()

    assert line.sent() == [INTERRUPTED_LINE]


async def test_only_the_lines_newest_episode_is_the_one_a_restart_cut_off() -> None:
    """An older interrupted episode, behind one that finished, sends nothing."""
    intake, memory = await _cut_off(ProcessingStatus.INTERRUPTED, ProcessingReason.HUB_STOPPED)
    await memory.add(episode("act-later", channel=line_channel(REFERENCE, CHAT)))
    line = _Line(intake=intake, memory=memory)
    line.start()
    await line.until(lambda: bool(line.polls()), what="the reader polled")
    await line.stop()

    assert line.sent() == []


async def test_a_restart_that_cut_off_a_cancelled_activation_sends_it_too() -> None:
    intake, memory = await _cut_off(ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED)
    line = _Line(intake=intake, memory=memory)
    line.start()
    await line.until(lambda: bool(line.polls()), what="the reader polled")
    await line.stop()

    assert line.sent() == [INTERRUPTED_LINE]


async def test_a_stopped_or_finished_activation_gets_no_restart_message() -> None:
    for status, reason in (
        (ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED),
        (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED),
    ):
        intake, memory = await _cut_off(status, reason)
        line = _Line(intake=intake, memory=memory)
        line.start()
        await line.until(partial(_polled, line), what="the reader polled")
        await line.stop()

        assert line.sent() == [], f"{status}/{reason} writes nothing new (ADR-0295 §3:3)"


# --- the window (§10, §4:12-§4:13) ------------------------------------------------------------


def _line_episode(
    activation_id: str,
    channel_messages: tuple[RecordedInputMessage, ...],
    *,
    channel: ChannelIdentity,
    rounds: tuple[tuple[str, str], ...] = (),
) -> EpisodicMemory:
    """A frozen episode on the line, its trigger holding ``channel_messages``."""
    record = episode(
        activation_id, channel=channel, text="\n\n".join(one.text for one in channel_messages)
    )
    processing = record.processing_record
    assert processing is not None
    return record.model_copy(
        update={
            "processing_record": processing.model_copy(
                update={
                    "trigger": processing.trigger.model_copy(update={"messages": channel_messages}),
                    "rounds": tuple(
                        PlanningRound(id=round_id, recorded_at=AT, text=said)
                        for round_id, said in rounds
                    ),
                }
            )
        }
    )


async def test_the_window_is_the_lines_recent_episodes_and_a_reply_brings_its_quote_in() -> None:
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    await memory.add(
        _line_episode(
            "act-a",
            (RecordedInputMessage(text="Book Friday?", sent_at=AT, position=20),),
            rounds=(("round:1", "Shall I book Friday?"),),
            channel=channel,
        )
    )
    # An episode on another bot's channel, or of another account, is not this window's.
    for elsewhere in (line_channel("conn-x", CHAT), line_channel(REFERENCE, CHAT + 1)):
        await memory.add(
            _line_episode(
                f"act-{elsewhere.instance_id}",
                (RecordedInputMessage(text="elsewhere", sent_at=AT, position=5),),
                channel=elsewhere,
            )
        )

    async def written(
        place: str, activations: Sequence[str], positions: Sequence[int] | None
    ) -> Mapping[int, WrittenBy]:
        assert place == f"telegram:{channel.instance_id}"
        assert positions is None
        assert list(activations) == ["act-a"]
        return {
            21: WrittenBy(
                activation_id="act-a", asked=AskedIn(round="round:1", parts=(1,)), round="round:1"
            )
        }

    line = _Line(memory=memory, written=written)
    quoted = TelegramQuotedMessage(
        message_id=21, sender_id=1, sender_is_bot=True, text="Shall I book Friday?"
    )
    line.fake.hold(text(30, "yes", message_id=30, reply_to=quoted))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()

    window = line.inputs[0].window
    assert window.conversation == channel
    assert [(one.position, one.author, one.text) for one in window.messages] == [
        (20, MessageAuthor.USER, "Book Friday?"),
        (21, MessageAuthor.ASSISTANT, "Shall I book Friday?"),
    ]
    assert window.links == {20: "act-a", 21: "act-a"}
    assert window.asked == {21: AskedIn(round="round:1", parts=(1,))}
    (input_message,) = window.input_messages
    assert (input_message.position, input_message.replies_to) == (30, 21)


async def test_the_window_shows_a_message_that_joined_an_earlier_activation() -> None:
    """ADR-0332 §3:16: a joined message is the activation's input, so the window shows it.

    One a takeover brought from another place is that place's, and is not shown.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    earlier = _line_episode(
        "act-a",
        (RecordedInputMessage(text="book Riverside", sent_at=AT, position=20),),
        channel=channel,
    )
    processing = earlier.processing_record
    assert processing is not None
    joined = (
        JoinedInput(
            joined_at=AT,
            channel=channel,
            messages=(RecordedInputMessage(text="actually Saturday", sent_at=AT, position=21),),
        ),
        JoinedInput(
            joined_at=AT,
            channel=ChannelIdentity(channel_type="conversation", instance_id="c-1"),
            messages=(RecordedInputMessage(text="for two", sent_at=AT, position=3),),
            taken_over_from="act-z",
        ),
    )
    await memory.add(
        earlier.model_copy(
            update={"processing_record": processing.model_copy(update={"joined": joined})}
        )
    )
    line = _Line(memory=memory)
    line.fake.hold(text(30, "and a table outside", message_id=30))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()

    window = line.inputs[0].window
    assert [(one.position, one.author, one.text) for one in window.messages] == [
        (20, MessageAuthor.USER, "book Riverside"),
        (21, MessageAuthor.USER, "actually Saturday"),
    ]
    assert window.links == {20: "act-a", 21: "act-a"}


async def test_a_reply_to_a_message_older_than_the_window_is_brought_in_from_its_quote() -> None:
    line = _Line()
    quoted = TelegramQuotedMessage(message_id=3, sender_id=CHAT, text="my old note")
    line.fake.hold(text(40, "about this", message_id=40, reply_to=quoted))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()

    window = line.inputs[0].window
    (replied,) = window.replied_to
    assert isinstance(replied, LineMessage)
    assert (replied.position, replied.author, replied.text) == (
        3,
        MessageAuthor.USER,
        "my old note",
    )
    assert window.links == {}, "nothing links a message the window's records do not name"
    assert window.claimed == {3}, "a quote the assistant did not write is claimed (§4:2)"


async def test_a_fixed_line_telegram_refused_is_still_answered_and_never_sent_again() -> None:
    """§5:3, §5:9: the record holds it answered, so it is confirmed and not re-sent."""
    line = _Line()
    line.telegram.failing_sends.append(TelegramFailure.REFUSED)
    line.fake.hold(photo(1))
    line.start()
    await line.until(lambda: line.fake.held == (), what="the photo was dealt with")
    await line.stop()

    sends = [one for one in line.fake.calls if one.method == SEND_MESSAGE]
    assert len(sends) == 1
    assert line.sent() == []


async def test_a_reply_to_the_last_part_of_a_long_message_finds_its_question_whole() -> None:
    """§4:13, §6:2: the message's position is its last part's, and the window holds it whole."""
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    long_text = "\n\n".join("p" * 3990 for _ in range(5)) + "\n\nWould you prefer Tuesday?"
    await memory.add(
        _line_episode(
            "act-long",
            (RecordedInputMessage(text="Tell me everything.", sent_at=AT, position=20),),
            rounds=(("round:1", long_text),),
            channel=channel,
        )
    )

    async def written(
        place: str, activations: Sequence[str], positions: Sequence[int] | None
    ) -> Mapping[int, WrittenBy]:
        return {
            26: WrittenBy(
                activation_id="act-long",
                asked=AskedIn(round="round:1", parts=(1,)),
                round="round:1",
            )
        }

    line = _Line(memory=memory, written=written)
    quoted = TelegramQuotedMessage(
        message_id=26, sender_id=1, sender_is_bot=True, text="Would you prefer Tuesday?"
    )
    line.fake.hold(text(30, "Tuesday", message_id=30, reply_to=quoted))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()

    window = line.inputs[0].window
    (said,) = [one for one in window.messages if one.position == 26]
    assert said.text == long_text, "the whole message, its question at its end"
    assert said.text.endswith("Would you prefer Tuesday?")
    assert window.asked == {26: AskedIn(round="round:1", parts=(1,))}
    assert window.input_messages[0].replies_to == 26


# --- the window under ADR-0356: a message call's words, from its entry (§8:1, §8:4) ------

#: A hub conversation, where a message call of a line's activation may also go.
_CONVERSATION = ChannelIdentity(channel_type="conversation", instance_id="c-1")


def _sent(
    round_id: str,
    call_id: str,
    words: str,
    *,
    went: ChannelIdentity,
    status: DeliveryStatus = DeliveryStatus.SENT,
) -> RecordedCall:
    """A ``text`` call's entry: what it sent, where and how (ADR-0356 §8:4)."""
    outcome = {
        DeliveryStatus.SENT: CallOutcomeKind.DONE,
        DeliveryStatus.FAILED: CallOutcomeKind.NOT_DONE,
        DeliveryStatus.UNKNOWN: CallOutcomeKind.UNKNOWN,
    }[status]
    reason = None if status is DeliveryStatus.SENT else "it did not go"
    return RecordedCall(
        round=round_id,
        call_id=call_id,
        capability="text",
        effect=True,
        outcome=outcome,
        reason=reason,
        delivered=RecordedDelivery(words=words, went=went, status=status, reason=reason),
        recorded_at=AT,
    )


def _calling_episode(
    activation_id: str,
    channel_messages: tuple[RecordedInputMessage, ...],
    *,
    channel: ChannelIdentity,
    rounds: tuple[tuple[str, tuple[str, ...]], ...],
    entries: tuple[RecordedCall, ...],
) -> EpisodicMemory:
    """A frozen episode on the line in ADR-0356's shape: rounds with no text, and entries.

    Each round is its id and its calls' ids, every one a ``text`` call; ``entries`` are
    the episode's call entries, in the order they were appended.
    """
    record = _line_episode(activation_id, channel_messages, channel=channel)
    processing = record.processing_record
    assert processing is not None
    return record.model_copy(
        update={
            "processing_record": processing.model_copy(
                update={
                    "rounds": tuple(
                        PlanningRound(
                            id=round_id,
                            recorded_at=AT,
                            calls=tuple(
                                ProposedCall(call_id=one, name="text", arguments={"words": "x"})
                                for one in calls
                            ),
                        )
                        for round_id, calls in rounds
                    ),
                    "call_records": entries,
                }
            )
        }
    )


async def _window_of(
    memory: FakeMemoryStore, writes: Mapping[int, WrittenBy], *, at: int = 40
) -> tuple[tuple[int, MessageAuthor, str], ...]:
    """The window the line builds over ``memory`` and ``writes``, for an input at ``at``."""

    async def written(
        place: str, activations: Sequence[str], positions: Sequence[int] | None
    ) -> Mapping[int, WrittenBy]:
        return writes

    line = _Line(memory=memory, written=written)
    line.fake.hold(text(at, "and then?", message_id=at))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the input was taken in")
    await line.stop()
    return tuple((one.position, one.author, one.text) for one in line.inputs[0].window.messages)


async def test_the_window_shows_what_a_text_call_sent_and_an_older_rounds_text() -> None:
    """ADR-0356 §8:1, §8:4: a round with no text shows its ``text`` call's delivered words.

    An episode recorded before the decision keeps its round's text as its message (#3569).
    """
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    await memory.add(
        _line_episode(
            "act-old",
            (RecordedInputMessage(text="Book Friday?", sent_at=AT, position=10),),
            rounds=(("round:1", "Shall I book Friday?"),),
            channel=channel,
        )
    )
    await memory.add(
        _calling_episode(
            "act-new",
            (RecordedInputMessage(text="And Saturday?", sent_at=AT, position=20),),
            channel=channel,
            rounds=(("round:1", ("call-1",)),),
            entries=(_sent("round:1", "call-1", "Saturday is free too.", went=channel),),
        )
    )

    window = await _window_of(
        memory,
        {
            11: WrittenBy(activation_id="act-old", round="round:1"),
            21: WrittenBy(activation_id="act-new", round="round:1"),
        },
    )

    assert window == (
        (10, MessageAuthor.USER, "Book Friday?"),
        (11, MessageAuthor.ASSISTANT, "Shall I book Friday?"),
        (20, MessageAuthor.USER, "And Saturday?"),
        (21, MessageAuthor.ASSISTANT, "Saturday is free too."),
    )


async def test_a_rounds_messages_are_its_calls_sent_into_the_line_in_the_rounds_order() -> None:
    """Several ``text`` calls in one round: by position, the round's calls in its order.

    A call whose message went into another place, or failed, wrote nothing into the
    line's chat, so it is no message there; the entries' own order is not the calls'.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    await memory.add(
        _calling_episode(
            "act-a",
            (RecordedInputMessage(text="Plan Saturday", sent_at=AT, position=20),),
            channel=channel,
            rounds=(("round:1", ("call-1", "call-2", "call-3", "call-4")),),
            entries=(
                _sent("round:1", "call-4", "Then dinner at eight.", went=channel),
                _sent("round:1", "call-2", "Noted in the hub.", went=_CONVERSATION),
                _sent(
                    "round:1", "call-3", "never went", went=channel, status=DeliveryStatus.FAILED
                ),
                _sent("round:1", "call-1", "Lunch at noon first.", went=channel),
            ),
        )
    )

    window = await _window_of(
        memory,
        {
            21: WrittenBy(activation_id="act-a", round="round:1"),
            23: WrittenBy(activation_id="act-a", round="round:1"),
        },
    )

    assert window == (
        (20, MessageAuthor.USER, "Plan Saturday"),
        (21, MessageAuthor.ASSISTANT, "Lunch at noon first."),
        (23, MessageAuthor.ASSISTANT, "Then dinner at eight."),
    )


async def test_a_round_whose_messages_and_entries_do_not_pair_shows_none_of_them() -> None:
    """Two entries sent and one message done: which entry it is is not known (#3569).

    So nothing of that round is shown, never one message's words at another's position,
    while the next round, whose one message pairs with its one entry, is shown.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    channel = line_channel(REFERENCE, CHAT)
    await memory.add(
        _calling_episode(
            "act-a",
            (RecordedInputMessage(text="Plan Saturday", sent_at=AT, position=20),),
            channel=channel,
            rounds=(("round:1", ("call-1", "call-2")), ("round:2", ("call-3",))),
            entries=(
                _sent("round:1", "call-1", "Lunch at noon first.", went=channel),
                _sent("round:1", "call-2", "Then dinner at eight.", went=channel),
                _sent("round:2", "call-3", "All booked.", went=channel),
            ),
        )
    )

    window = await _window_of(
        memory,
        {
            22: WrittenBy(activation_id="act-a", round="round:1"),
            23: WrittenBy(activation_id="act-a", round="round:2"),
        },
    )

    assert window == (
        (20, MessageAuthor.USER, "Plan Saturday"),
        (23, MessageAuthor.ASSISTANT, "All booked."),
    )


# --- holding while one runs (ADR-0332 §2:4, until ADR-0349 §1:4's step 3) ----------------


async def _running(line: _Line) -> str:
    """The line with its first activation admitted and held."""
    line.gate = asyncio.Event()
    line.fake.hold(text(1, "book Riverside"))
    line.start()
    await asyncio.wait_for(line.entered.wait(), SETTLE)
    return line.inputs[0].activation_id


async def _held(line: _Line, update_id: int) -> TelegramIntake | None:
    return (await line.intake.recorded([update_id])).get(update_id)


async def _until_held(line: _Line, update_id: int) -> TelegramIntake:
    deadline = asyncio.get_running_loop().time() + SETTLE
    while (held := await _held(line, update_id)) is None:
        if asyncio.get_running_loop().time() > deadline:
            msg = f"update {update_id} was never recorded"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)
    return held


async def test_while_updates_handed_to_a_running_one_wait_unmarked_the_polls_are_paced() -> None:
    """ADR-0332 §8:8: an update handed and not yet marked comes back in every poll."""
    line = _Line()
    line.marking = asyncio.Event()
    line.gate = asyncio.Event()
    line.fake.hold(text(1, "book Riverside"))
    line.start()
    await line.until(lambda: len(line.inputs) == 1, what="the first was admitted")
    rests = len(line.rests)
    polls = len(line.polls())
    await line.until(lambda: len(line.rests) > rests + 5, what="the reader went on polling")

    assert len(line.inputs) == 1, "what a running one was handed is never taken in again"
    assert await _held(line, 1) is None, "not yet marked"
    typing = TYPING_RENEWAL.total_seconds()  # the writer's, which rests on the same sleep
    paced = [one for one in line.rests[rests:] if one != typing]
    assert set(paced) == {RUNNING_POLL_PACE.total_seconds()}
    assert len(line.polls()) - polls <= len(paced) + 1, "a rest before every poll"

    line.marking.set()
    line.gate.set()
    await line.until(lambda: line.fake.held == (), what="it was confirmed once marked")
    await line.stop()
    assert len(line.inputs) == 1


async def test_a_start_wait_as_long_as_the_pace_is_not_cut_short_by_an_activations_end() -> None:
    """ADR-0332 §5:3, ADR-0349 §8:2: only the pace ends with an activation; a start wait
    of the same length runs its whole length."""
    line = _Line(start_wait=RUNNING_POLL_PACE)
    first = await _running(line)
    line.pause = asyncio.Event()
    mark = len(line.rests)
    line.fake.hold(text(2, "and the weather?"))
    await line.until(lambda: len(line.told) == 3, what="its start wait to begin")
    await line.until(
        lambda: RUNNING_POLL_PACE.total_seconds() in line.rests[mark:],
        what="its start wait's rest, while the first runs",
    )

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: first not in line.reader.working, what="the first to end")
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert len(line.inputs) == 1, "the start wait has not passed, so nothing is taken in"

    line.pause.set()
    await line.until(lambda: len(line.inputs) == 2, what="taken in once it passed")
    await line.stop()


async def test_a_stop_leaves_a_message_still_in_its_start_wait_to_start() -> None:
    """ADR-0349 §4:3: it stops what runs; an input not yet taken in is not running."""
    line = _Line()
    running = await _running(line)
    line.fake.hold(text(2, "actually Saturday"), stop_command(3))

    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    assert line.stops == [running]
    await line.until(lambda: len(line.inputs) == 2, what="the message was taken in")
    assert line.inputs[1].update_ids == (2,)
    assert line.stops == [running], "and it was not stopped"

    assert line.gate is not None
    line.gate.set()
    await line.stop()


async def test_a_stop_stops_every_activation_running_from_the_chat() -> None:
    """ADR-0349 §4:3, §1:5: each by the one stop, and "Stopped." once."""
    line = _Line()
    first = await _running(line)
    line.fake.hold(text(2, "and the weather?"))
    await line.until(lambda: len(line.inputs) == 2, what="the second was taken in")
    second = line.inputs[1].activation_id

    line.fake.hold(stop_command(3))
    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    assert line.stops == [first, second], "each running one, oldest first"
    assert line.sent() == [STOPPED_LINE]

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: line.fake.held == (), what="everything was confirmed")
    await line.stop()
    assert line.sent() == [STOPPED_LINE], "answered once"


async def test_one_stop_that_fails_leaves_the_others_to_be_made() -> None:
    """ADR-0349 §4:3: each running one is stopped by a stop of its own."""
    line = _Line()
    first = await _running(line)
    line.fake.hold(text(2, "and the weather?"))
    await line.until(lambda: len(line.inputs) == 2, what="the second was taken in")
    second = line.inputs[1].activation_id
    stopping = line.reader._stop

    async def failing(activation_id: str) -> bool:
        if activation_id == first:
            msg = "the stop could not be made"
            raise RuntimeError(msg)
        return await stopping(activation_id)

    line.reader._stop = failing
    line.fake.hold(stop_command(3))
    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    assert line.stops == [second], "the second was stopped all the same"

    assert line.gate is not None
    line.gate.set()
    await line.stop()


async def test_a_stop_none_of_whose_stops_can_be_made_answers_neither_fixed_line() -> None:
    """ADR-0332 §8:5: something ran, so it is not "Nothing was running.", and nothing was
    stopped, so it is not "Stopped.": it fails as a stop that cannot be made does."""
    line = _Line()
    await _running(line)

    async def failing(activation_id: str) -> bool:
        del activation_id
        msg = "the stop could not be made"
        raise RuntimeError(msg)

    line.reader._stop = failing
    line.fake.hold(stop_command(2))
    await _until_held(line, 2)
    rests = len(line.rests)
    await line.until(lambda: len(line.rests) > rests + 3, what="the reader went on")

    assert line.sent() == [], "neither fixed line"
    assert line.stops == []
    assert line.gate is not None
    line.gate.set()
    await line.stop()


async def test_the_engine_is_told_what_the_start_wait_holds_until_its_activation_ends() -> None:
    """ADR-0349 §7:12: held from the poll that began the wait, admitted, then let go."""
    line = _Line()
    first = await _running(line)
    assert line.told == [("held", None), ("admitted", first)], "held while it runs"

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: line.told[-1] == ("released", first), what="it was let go")
    await line.stop()


async def test_a_start_wait_the_close_cuts_off_lets_its_hold_go() -> None:
    """ADR-0349 §7:12: nothing it held will be taken in, so the engine is told so."""
    line = _Line()
    line.pause = asyncio.Event()
    line.fake.hold(text(1, "hi"))
    line.start()
    await line.until(lambda: bool(line.told), what="the start wait to begin")
    line.closing = True
    await line.stop()

    assert line.inputs == []
    assert line.told == [("held", None), ("released", None)]


# --- the line's /stop (ADR-0332 §8) -----------------------------------------------------


async def test_a_bare_stop_stops_what_runs_and_is_answered_once_by_rule() -> None:
    """§8:4-§8:6: recorded answered, the activation stopped, "Stopped." sent once."""
    line = _Line()
    running = await _running(line)
    line.fake.hold(stop_command(2))

    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    held = await _until_held(line, 2)
    for _ in range(20):
        await asyncio.sleep(0.001)

    assert line.stops == [running], "it stopped the activation running from the chat"
    assert held.kind is TelegramIntakeKind.ANSWERED
    assert line.sent() == [STOPPED_LINE], "answered once, however often a poll returns it"
    assert len(line.inputs) == 1, "a stop command is not input: it starts nothing"

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: line.fake.held == (), what="everything was confirmed")
    await line.stop()
    assert len(line.inputs) == 1, "and starts nothing"


async def test_a_stop_with_nothing_running_is_answered_nothing_was_running() -> None:
    """§8:5: the fixed line where none ran, and nothing is stopped."""
    line = _Line()
    line.fake.hold(stop_command(1))
    line.start()
    await line.until(lambda: line.fake.held == (), what="it was confirmed")
    await line.stop()

    assert line.sent() == [NOTHING_RUNNING_LINE]
    assert line.stops == []
    assert line.inputs == []


async def test_two_stops_alike_but_for_the_entity_are_a_stop_and_a_message() -> None:
    """§1:4, §8:1-§8:2: only the one Telegram marked as a ``bot_command`` is a stop."""
    line = _Line()
    line.fake.hold(stop_command(1), text(2, "/stop"))
    line.start()
    await line.until(lambda: bool(line.inputs), what="the message was taken in")
    await line.stop()

    assert line.sent() == [NOTHING_RUNNING_LINE], "the marked one is answered as a stop"
    (taken,) = line.inputs
    assert taken.update_ids == (2,), "the unmarked one is a message like any other"
    assert taken.text == "/stop"


def test_only_a_bare_marked_unforwarded_stop_is_one() -> None:
    """§8:2: a forward, ``/stop@`` a name, the text unmarked or only mentioning it."""
    origin = TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Sam", account_id=77)

    def message(update: TelegramUpdate) -> TelegramMessage:
        assert update.message is not None
        return update.message

    assert is_stop_command(message(stop_command(1)))
    for update in (
        text(1, "/stop", command="/stop", forward=origin),
        text(1, "/stop@AetherBot", command="/stop@AetherBot"),
        text(1, "/stop"),
        text(1, "/stop now", command="/stop"),
        text(1, "please /stop"),
        text(1, "/stopping", command="/stopping"),
    ):
        assert not is_stop_command(message(update))


async def test_a_stop_behind_a_full_page_waits_and_is_acted_on_when_a_poll_returns_it() -> None:
    """§1:4, §8:4: past one page of updates not yet confirmed, it waits with them.

    The page is its own activation's input (ADR-0349 §8:1), left unconfirmed until that
    activation marks it; then a poll returns the stop, which stops both (§4:3).
    """
    line = _Line()
    first = await _running(line)
    line.marking = asyncio.Event()
    line.fake.hold(*(text(n, f"m{n}") for n in range(2, 102)), stop_command(102))
    await line.until(lambda: len(line.inputs) == 2, what="the page was taken in")
    polls = len(line.polls())
    await line.until(lambda: len(line.polls()) > polls + 3, what="the reader went on polling")
    assert line.stops == [], "a full page waits in front of it, so no poll returned it"
    assert line.sent() == []

    line.marking.set()
    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    second = line.inputs[1].activation_id
    assert second != first
    assert line.stops == [first, second], "it stops what runs when a poll first returns it"
    assert len(line.inputs[1].updates) == 100
    assert line.gate is not None
    line.gate.set()
    await line.stop()
