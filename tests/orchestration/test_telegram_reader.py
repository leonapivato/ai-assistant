"""The Telegram line's reader, against a fake Telegram (ADR-0323 §4, §5, §6:10, §10).

Driven with a stand-in for the engine's activation, which takes the input in as the
engine's does, so each case reads what the reader brought in and what it told
Telegram. What comes in is a text message or a forward from the configured account in
its private chat with the bot (§5:1); anything else is ignored and recorded nowhere
(§5:2), and a non-text message is answered by rule (§5:3). One activation runs at a
time and nothing is asked of Telegram while it does (§5:5, §5:7); an update is
confirmed only once dealt with (§5:6), and one taken in or answered once is never
taken in or answered again (§5:9). After a restart the activation it cut off gets the
one fixed message (§6:10). The window is the line's recent episodes (§10).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING

from story_support import episode
from telegram_support import AT, CHAT, REFERENCE, SETTLE, YieldingTelegram, photo, text

from ai_assistant.core.types import (
    ChannelIdentity,
    EpisodicMemory,
    MessageAuthor,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    RecordedInputMessage,
    TelegramCallKind,
    TelegramCallOutcome,
    TelegramFailure,
    TelegramForwardKind,
    TelegramForwardOrigin,
    TelegramIntake,
    TelegramIntakeKind,
    TelegramQuotedMessage,
    TelegramUpdate,
)
from ai_assistant.orchestration.telegram import (
    INTERRUPTED_LINE,
    NON_TEXT_LINE,
    POLL_BACKOFF,
    UNAVAILABLE_BACKOFF,
    TelegramInput,
    TelegramLineSeams,
    TelegramReader,
    TelegramWriter,
    line_channel,
)
from ai_assistant.orchestration.understanding import AskedIn, LineMessage, WrittenBy
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
)
from ai_assistant.testing.telegram import GET_UPDATES, SEND_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence


class _Line:
    """A reader over the fakes, its activation a stand-in that takes the input in."""

    def __init__(
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
        )
        self.rests: list[float] = []
        self.inputs: list[TelegramInput] = []
        self.marked: list[tuple[int, ...]] = []
        self.held_then: list[dict[int, TelegramIntake]] = []
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.closing = False
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
            closing=lambda: self.closing,
            mint=lambda: next(self._ids),
            written=written,
            sleep=self._rest,
        )
        self.task: asyncio.Task[None] | None = None

    async def _rest(self, seconds: float) -> None:
        self.rests.append(seconds)
        await asyncio.sleep(0.001)

    async def _activate(self, taken: TelegramInput) -> bool:
        self.inputs.append(taken)
        marked: list[int] = []
        await self.reader.take_in(taken, into=marked)
        self.marked.append(tuple(marked))
        self.held_then.append(dict(await self.intake.recorded(taken.update_ids)))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
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

    await line.until(lambda: len(line.polls()) >= 2, what="the reader polled again")
    await line.stop()

    (taken,) = line.inputs
    assert taken.text == "What's on tomorrow?"
    assert taken.channel == line.seams.channel
    assert taken.recorded == (
        RecordedInputMessage(text="What's on tomorrow?", sent_at=AT, position=55),
    )
    assert line.marked == [(10,)], "taken in by its activation as it was admitted"
    (held,) = line.held_then[0].values()
    assert (held.kind, held.activation_id) == (TelegramIntakeKind.TAKEN_IN, taken.activation_id)
    assert line.polls()[1]["offset"] == 11, "the next poll confirms what was dealt with"
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


# --- one activation at a time (§5:4-§5:7) -------------------------------------------------


async def test_nothing_is_asked_while_an_activation_runs_and_what_waits_comes_in_together() -> None:
    line = _Line()
    line.gate = asyncio.Event()
    line.fake.hold(text(1, "first"))
    line.start()
    await asyncio.wait_for(line.entered.wait(), SETTLE)
    polls = len(line.polls())

    line.fake.hold(text(2, "second", minute=1), text(3, "third", minute=2))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert len(line.polls()) == polls, "nothing is asked of Telegram while it runs (§5:7)"
    assert line.reader.working == line.inputs[0].activation_id

    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="what waited was taken in")
    await line.stop()

    later = line.inputs[1]
    assert later.text == "second\n\nthird", "taken in together, as one input"
    assert [one.sent_at for one in later.recorded] == [
        AT + timedelta(minutes=1),
        AT + timedelta(minutes=2),
    ], "each message keeps its own time (§5:4)"


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
    assert line.rests == [], "an unknown poll is polled again at once"


def _polled(line: _Line) -> bool:
    return bool(line.polls())


# --- after a restart (§5:10, §6:10) ---------------------------------------------------------


async def _cut_off(
    status: ProcessingStatus, reason: ProcessingReason
) -> tuple[FakeTelegramIntakeRecord, FakeMemoryStore]:
    """A record an activation took update 4 in, whose episode closed as given."""
    intake = FakeTelegramIntakeRecord()
    await intake.take_in([4], activation_id="act-cut")
    memory = FakeMemoryStore(now=lambda: AT)
    record = episode("act-cut")
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
