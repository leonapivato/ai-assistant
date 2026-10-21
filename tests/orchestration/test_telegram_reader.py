"""The Telegram line's reader, against a fake Telegram (ADR-0323 §4, §5, §6:10, §10).

Driven with a stand-in for the engine's activation, which takes the input in as the
engine's does, so each case reads what the reader brought in and what it told
Telegram. What comes in is a text message or a forward from the configured account in
its private chat with the bot (§5:1); anything else is ignored and recorded nowhere
(§5:2), and a non-text message is answered by rule (§5:3). One activation runs at a
time, taken in once the start wait has passed (ADR-0332 §5:3), and the reader keeps
polling, paced, while it runs (ADR-0332 §8:7-§8:8, amending §5:7): a message joins it
where the join takes it and is marked taken in by it (ADR-0332 §3:3, §3:18), and
otherwise waits. A bare ``/stop`` with its entity stops what runs and is answered by
rule (ADR-0332 §8). An update is confirmed only once dealt with (§5:6), and one taken
in or answered once is never taken in or answered again (§5:9). After a restart the
activation it cut off gets the one fixed message (§6:10). The window is the line's
recent episodes (§10).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, cast

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
    ChannelIdentity,
    EpisodicMemory,
    InputOrigin,
    JoinedInput,
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
    TelegramMessage,
    TelegramQuotedMessage,
    TelegramUpdate,
)
from ai_assistant.orchestration.joining import THE_USER, JoinCheck
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
from ai_assistant.testing.telegram import GET_UPDATES, SEND_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence

    from ai_assistant.orchestration.joining import JoiningInput, PendingJoin


class _Pending:
    """A stand-in for a join taken pending its marking, recording what confirms it."""

    def __init__(self, activation_id: str, confirmed: list[tuple[int, ...]]) -> None:
        self.activation_id = activation_id
        self._confirmed = confirmed

    def confirm(self, positions: Iterable[int | None]) -> None:
        self._confirmed.append(tuple(sorted(one for one in positions if one is not None)))

    def withdraw(self) -> None:
        self._confirmed.append(())


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
        # ADR-0332 §3, §8: what the reader handed the join and the stop, and what each
        # answers: no join is taken, and a stop stops what runs, unless a case says.
        # What the reader handed the join (`joins`), which takes it pending its marking
        # into the activation `answer` names, and the message ids each was confirmed with.
        self.joins: list[JoiningInput] = []
        self.confirmed: list[tuple[int, ...]] = []
        self.joined: str | None = None
        self.answer: Callable[[JoiningInput], str | None] = lambda joining: self.joined
        self.stops: list[str] = []
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
            join=self._join,
            stop=self._stop,
            closing=lambda: self.closing,
            mint=lambda: next(self._ids),
            written=written,
            sleep=self._rest,
        )
        self.task: asyncio.Task[None] | None = None

    async def _rest(self, seconds: float) -> None:
        self.rests.append(seconds)
        await asyncio.sleep(0.001)

    def _join(self, joining: JoiningInput) -> tuple[JoinCheck, PendingJoin | None]:
        self.joins.append(joining)
        into = self.answer(joining)
        if into is None:
            return JoinCheck.REFUSED, None
        return JoinCheck.JOINABLE, cast("PendingJoin", _Pending(into, self.confirmed))

    async def _stop(self, activation_id: str) -> bool:
        self.stops.append(activation_id)
        return True

    async def _activate(self, taken: TelegramInput) -> bool:
        self.inputs.append(taken)
        marked: list[int] = []
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
    assert taken.recorded == (
        RecordedInputMessage(text="What's on tomorrow?", sent_at=AT, position=55),
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


# --- one activation at a time (§5:4-§5:7, ADR-0332 §2:4, §8:7-§8:8) ---------------------


async def test_polling_goes_on_while_one_runs_and_what_did_not_join_comes_in_together() -> None:
    """ADR-0332 §8:7-§8:8, amending §5:7: the reader polls, paced, while it runs."""
    line = _Line()
    line.gate = asyncio.Event()
    line.fake.hold(text(1, "first"))
    line.start()
    await asyncio.wait_for(line.entered.wait(), SETTLE)
    polls = len(line.polls())

    line.fake.hold(text(2, "second", minute=1), text(3, "third", minute=2))
    await line.until(lambda: bool(line.joins), what="the join was asked")
    await line.until(lambda: len(line.polls()) > polls + 2, what="the reader kept polling")
    assert line.reader.working == line.inputs[0].activation_id
    (joining,) = line.joins
    assert [one.text for one in joining.messages] == ["second", "third"], "one input"
    assert RUNNING_POLL_PACE.total_seconds() in line.rests, "paced, never in a loop"
    assert {one.update_id for one in line.fake.held} == {2, 3}, "left waiting, unconfirmed"

    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="what waited was taken in")
    await line.stop()

    assert line.joins == [joining], "nothing joins past what waits (ADR-0332 §3:3)"
    assert line.rests.count(DEFAULT_TELEGRAM_START_WAIT.total_seconds()) == 1, (
        "what waited while it ran is taken in at once, with no second start wait"
    )

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


# --- joining while one runs (ADR-0332 §3:3, §3:18) ----------------------------------------


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


async def test_a_message_sent_while_one_runs_joins_it_and_is_marked_taken_in_by_it() -> None:
    """§3:3, §3:18: handed to the join, marked by the activation it joined, confirmed."""
    line = _Line()
    running = await _running(line)
    line.joined = running

    line.fake.hold(text(2, "actually Saturday", message_id=60, minute=1))
    held = await _until_held(line, 2)
    await line.until(lambda: line.fake.held == (), what="it was confirmed")

    assert (held.kind, held.activation_id) == (TelegramIntakeKind.TAKEN_IN, running)
    assert line.confirmed == [(60,)], "confirmed with what the record marked"
    (joining,) = line.joins
    assert joining.channel == line.seams.channel
    assert joining.messages == (
        RecordedInputMessage(
            text="actually Saturday", sent_at=AT + timedelta(minutes=1), position=60
        ),
    )
    assert (joining.standing.author, joining.standing.users_authority) == (THE_USER, True)
    assert joining.standing.origin is InputOrigin.USER

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: line.reader.working is None, what="the activation ended")
    for _ in range(10):
        await asyncio.sleep(0.001)
    await line.stop()
    assert len(line.inputs) == 1, "a joined message is never taken in again"


async def test_a_forward_is_handed_to_the_join_apart_from_the_users_own_message() -> None:
    """§3:3: a forward's author is claimed, so it is an input of its own standing."""
    line = _Line()
    running = await _running(line)
    line.answer = lambda joining: running if joining.standing.author is not None else None
    origin = TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Sam", account_id=77)

    line.fake.hold(text(2, "also this"), text(3, "Sam's note", forward=origin), text(4, "and"))
    await line.until(lambda: len(line.joins) == 2, what="both runs were handed")
    await _until_held(line, 2)
    for _ in range(20):
        await asyncio.sleep(0.001)

    own, forwarded = line.joins
    assert [one.text for one in own.messages] == ["also this"]
    assert [one.text for one in forwarded.messages] == ["Sam's note"]
    assert forwarded.standing.author is None
    assert forwarded.standing.origin is not InputOrigin.USER
    assert len(line.joins) == 2, "nothing after the forward that waits is handed on"
    assert await _held(line, 3) is None
    assert await _held(line, 4) is None

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="what waited was taken in")
    await line.stop()
    assert line.inputs[1].text == "Sam's note\n\nand"


async def test_nothing_joins_past_a_message_that_waits_and_the_polls_are_paced() -> None:
    """§3:3's fourth condition, §8:8: once one waits nothing after it joins."""
    line = _Line()
    await _running(line)
    line.fake.hold(text(2, "actually Saturday"))
    await line.until(lambda: len(line.joins) == 1, what="the join was asked")

    line.joined = line.inputs[0].activation_id
    line.fake.hold(text(3, "and at seven"))
    rests = len(line.rests)
    polls = len(line.polls())
    await line.until(lambda: len(line.rests) > rests + 5, what="the reader went on polling")

    assert len(line.joins) == 1, "nothing is handed to the join past what waits"
    typing = TYPING_RENEWAL.total_seconds()  # the writer's, which rests on the same sleep
    paced = [one for one in line.rests[rests:] if one != typing]
    assert set(paced) == {RUNNING_POLL_PACE.total_seconds()}
    assert len(line.polls()) - polls <= len(paced) + 1, "a rest before every poll"

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="what waited was taken in")
    await line.stop()
    assert line.inputs[1].text == "actually Saturday\n\nand at seven"


def _failing_marking(line: _Line, running: str) -> Callable[[JoiningInput], str]:
    """A check that finds the run joinable, and makes the record refuse its marking."""

    def answer(joining: JoiningInput) -> str:
        del joining
        # The join's marking is the record's very next call: it fails.
        line.intake.fail_next()
        return running

    return answer


async def test_a_join_whose_marking_failed_joins_nothing_and_is_taken_in_after() -> None:
    """§3:18: the marking comes first, so a refused one leaves the update waiting."""
    line = _Line()
    running = await _running(line)
    line.answer = _failing_marking(line, running)
    line.fake.hold(text(2, "actually Saturday"))
    await line.until(lambda: bool(line.confirmed), what="the join was settled")
    assert line.confirmed == [()], "nothing the record does not hold taken in is joined"

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="it was taken in after")
    await line.stop()
    assert line.inputs[1].update_ids == (2,)


async def test_a_stop_after_a_join_whose_marking_failed_still_stops() -> None:
    """§8:4: a marking the record refused never keeps a stop in the page from acting."""
    line = _Line()
    running = await _running(line)
    line.answer = _failing_marking(line, running)
    line.fake.hold(text(2, "actually Saturday"), stop_command(3))

    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")
    assert line.stops == [running]
    assert line.confirmed == [()], "nothing joined"

    assert line.gate is not None
    line.gate.set()
    await line.until(lambda: len(line.inputs) == 2, what="the correction was taken in after")
    await line.stop()
    assert line.inputs[1].update_ids == (2,)


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
    assert line.joins == [], "a stop command is not input: it joins nothing"

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
    """§1:4, §8:4: past one page of waiting updates, it waits with them."""
    line = _Line()
    first = await _running(line)
    line.fake.hold(*(text(n, f"m{n}") for n in range(2, 102)), stop_command(102))
    await line.until(lambda: len(line.joins) == 1, what="the page was handed to the join")
    rests = len(line.rests)
    await line.until(lambda: len(line.rests) > rests + 3, what="the reader went on polling")
    assert line.stops == [], "a full page waits in front of it, so no poll returned it"
    assert line.sent() == []

    released = line.gate
    assert released is not None
    line.gate = asyncio.Event()
    released.set()
    await line.until(lambda: len(line.inputs) == 2, what="the page was taken in")
    await line.until(lambda: bool(line.stops), what="a poll returned the stop")
    await line.until(lambda: STOPPED_LINE in line.sent(), what="the stop was answered")

    second = line.inputs[1].activation_id
    assert second != first
    assert line.stops == [second], "it stops what runs when a poll first returns it"
    assert len(line.inputs[1].updates) == 100
    line.gate.set()
    await line.stop()
