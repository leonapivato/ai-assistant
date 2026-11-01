"""The Telegram line's writer, against a fake Telegram (ADR-0323 §6, §13:2, §15:5).

Each failure rule of §6 is a case here: a part is retried only where Telegram did not
get it or said it was not sent and a retry can succeed (§6:3), a send whose outcome is
unknown is never retried (§6:4), and every other refusal is *not done* (§6:5). A
message for a chat other than the line's is refused before any byte (§6:1). A message
longer than one Telegram message is split at paragraph breaks, then line breaks, then
between words, and at the limit only where a run has no break (§6:6). The typing
indicator and the fixed lines are each claimed on the intake record before they are
sent, and finished with their outcome (§13:2).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Final

import pytest

from ai_assistant.core.types import (
    TELEGRAM_MESSAGE_LIMIT,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    TelegramCallKind,
    TelegramCallOutcome,
    TelegramFailure,
    TelegramOutcome,
    TelegramPollOutcome,
    TelegramSendOutcome,
    ToolOutcome,
    telegram_length,
)
from ai_assistant.orchestration.telegram import (
    NON_TEXT_LINE,
    SEND_ATTEMPTS,
    TelegramWriter,
    line_channel,
    split_message,
)
from ai_assistant.testing import FakeTelegramBotClient, FakeTelegramIntakeRecord
from ai_assistant.testing.telegram import SEND_CHAT_ACTION, SEND_MESSAGE

#: The owner's account, and so their chat with the bot.
CHAT: Final = 424242

#: The line's connection.
REFERENCE: Final = "conn-0001"

#: The effect record an activation's message is claimed under.
EFFECT: Final = "effect:1"

LINE: Final = line_channel(REFERENCE, CHAT)


class _FailingNthSend:
    """The fake Telegram, its ``n``-th ``sendMessage`` ending with ``failure``.

    The fake takes its arrangements in call order, so a failure of a later part is
    arranged as that part is sent.
    """

    def __init__(self, fake: FakeTelegramBotClient, *, n: int, failure: TelegramFailure) -> None:
        self._fake = fake
        self._n = n
        self._failure = failure
        self._sends = 0

    @property
    def chat_id(self) -> int:
        return self._fake.chat_id

    async def poll(self, **arguments: Any) -> TelegramPollOutcome:
        return await self._fake.poll(**arguments)

    async def send(self, **arguments: Any) -> TelegramSendOutcome:
        self._sends += 1
        if self._sends == self._n:
            self._fake.fail_next(self._failure)
        return await self._fake.send(**arguments)

    async def show_typing(self, **arguments: Any) -> TelegramOutcome:
        return await self._fake.show_typing(**arguments)

    async def send_with_buttons(self, **arguments: Any) -> TelegramSendOutcome:
        return await self._fake.send_with_buttons(**arguments)

    async def edit_message(self, **arguments: Any) -> TelegramOutcome:
        return await self._fake.edit_message(**arguments)

    async def answer_callback(self, **arguments: Any) -> TelegramOutcome:
        return await self._fake.answer_callback(**arguments)


class _Rig:
    """A writer over a fake Telegram and a fake intake record, its waits recorded."""

    def __init__(
        self,
        *,
        fail_send: int | None = None,
        failure: TelegramFailure = TelegramFailure.UNKNOWN,
        bound: timedelta = timedelta(seconds=5),
    ) -> None:
        self.client = FakeTelegramBotClient(chat_id=CHAT, first_message_id=100)
        self.intake = FakeTelegramIntakeRecord()
        self.waits: list[float] = []
        self.writer = TelegramWriter(
            client=self.client
            if fail_send is None
            else _FailingNthSend(self.client, n=fail_send, failure=failure),
            intake=self.intake,
            channel=LINE,
            send_bound=bound,
            sleep=self._sleep,
        )

    async def _sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        await asyncio.sleep(0)

    def sends(self) -> list[str]:
        """The attempts each sendMessage named, in order."""
        return [one.attempt for one in self.client.calls if one.method == SEND_MESSAGE]


# --- splitting (§6:6) -----------------------------------------------------------------


def test_a_message_that_fits_is_one_part() -> None:
    assert split_message("Hello there.") == ("Hello there.",)


def test_paragraphs_are_packed_into_parts_and_split_only_at_their_breaks() -> None:
    paragraph = "word " * 30
    text = "\n\n".join(paragraph.strip() for _ in range(6))

    parts = split_message(text, limit=400)

    assert len(parts) > 1
    assert all(telegram_length(one) <= 400 for one in parts)
    # Every break between parts is a paragraph break: each part holds whole paragraphs.
    assert all(one.count("word") % 30 == 0 for one in parts)
    assert "\n\n".join(parts) == text


def test_a_paragraph_longer_than_a_part_is_split_at_line_breaks_then_between_words() -> None:
    line = " ".join(f"w{n}" for n in range(40))
    long_paragraph = "\n".join(line for _ in range(4))
    one_long_line = " ".join(f"x{n}" for n in range(400))

    by_lines = split_message(long_paragraph, limit=len(line) + 5)
    by_words = split_message(one_long_line, limit=100)

    assert by_lines == tuple(line for _ in range(4))
    assert all(len(one) <= 100 for one in by_words)
    assert " ".join(by_words).split() == one_long_line.split()


def test_a_run_with_no_break_is_cut_at_the_limit_never_inside_a_character() -> None:
    run = "a" * 250
    emoji = "\N{GRINNING FACE}" * 101  # two UTF-16 units each

    assert split_message(run, limit=100) == ("a" * 100, "a" * 100, "a" * 50)
    parts = split_message(emoji, limit=100)
    assert all(telegram_length(one) <= 100 for one in parts)
    assert "".join(parts) == emoji


def test_a_message_at_telegrams_limit_is_one_part_and_one_past_it_is_two() -> None:
    at = "a" * TELEGRAM_MESSAGE_LIMIT

    assert split_message(at) == (at,)
    assert len(split_message(at + " b")) == 2


def test_a_part_that_would_be_blank_is_not_sent() -> None:
    assert split_message(("a" * 10) + "\n\n\n\n" + ("b" * 10), limit=12) == ("a" * 10, "b" * 10)


def test_a_limit_no_character_fits_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one character"):
        split_message("x", limit=1)


# --- an activation's message (§6:1-§6:6) ----------------------------------------------


async def test_a_message_is_sent_once_and_its_id_is_the_position() -> None:
    rig = _Rig()

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.SUCCEEDED
    assert delivered.position == 100
    assert delivered.written == "Hi."
    assert rig.client.messages == ((100, "Hi."),)
    assert rig.sends() == [EFFECT], "the message names its claimed effect record"


async def test_a_long_message_is_sent_in_parts_and_recorded_as_one() -> None:
    rig = _Rig()
    text = "\n\n".join("p" * 3000 for _ in range(3))

    delivered = await rig.writer.deliver(LINE, text, effect_id=EFFECT)

    assert [one for _, one in rig.client.messages] == ["p" * 3000] * 3
    assert delivered.outcome is ToolOutcome.SUCCEEDED
    assert delivered.position == 102, "the last part's id, which a reply to its end quotes"
    assert delivered.written == text
    assert rig.sends() == [EFFECT] * 3


@pytest.mark.parametrize(
    ("failure", "retry_after", "wait"),
    [
        (TelegramFailure.NOT_WRITTEN, None, 1.0),
        (TelegramFailure.RATE_LIMITED, 2, 2.0),
        (TelegramFailure.RATE_LIMITED, None, 1.0),
    ],
    ids=["never-written", "rate-limited", "rate-limited-no-wait-given"],
)
async def test_a_send_telegram_did_not_get_is_retried(
    failure: TelegramFailure, retry_after: int | None, wait: float
) -> None:
    """§6:3: retried where the request was never written, or Telegram said not sent."""
    rig = _Rig()
    rig.client.fail_next(failure, retry_after_seconds=retry_after)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.SUCCEEDED
    assert rig.waits == [wait]
    assert len(rig.sends()) == 2
    assert rig.client.messages == ((100, "Hi."),)


async def test_a_send_with_an_unknown_outcome_is_never_retried() -> None:
    """§6:4: it may have been delivered, so a retry could deliver it twice."""
    rig = _Rig()
    rig.client.fail_next(TelegramFailure.UNKNOWN, delivered=True)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.INDETERMINATE
    assert (delivered.position, delivered.reason, delivered.written) == (None, None, None)
    assert len(rig.sends()) == 1
    assert rig.client.messages == ((100, "Hi."),), "delivered once, and only once"


async def test_a_send_cut_off_by_its_bound_after_its_write_is_unknown_and_not_retried() -> None:
    rig = _Rig(bound=timedelta(milliseconds=20))
    rig.client.hang_next(written=True)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.INDETERMINATE
    assert len(rig.sends()) == 1


@pytest.mark.parametrize(
    "failure",
    [TelegramFailure.REFUSED, TelegramFailure.UNAVAILABLE],
    ids=["refused", "unavailable"],
)
async def test_every_other_refusal_is_not_done_and_not_retried(failure: TelegramFailure) -> None:
    """§6:5."""
    rig = _Rig()
    rig.client.fail_next(failure)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.FAILED
    assert delivered.reason == f"telegram_did_not_send:{failure.value}"
    assert delivered.written is None
    assert len(rig.sends()) == 1
    assert rig.waits == []


async def test_a_rate_limit_longer_than_an_activation_waits_is_not_done() -> None:
    rig = _Rig()
    rig.client.fail_next(TelegramFailure.RATE_LIMITED, retry_after_seconds=600)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.FAILED
    assert len(rig.sends()) == 1


async def test_retries_stop_after_their_bound() -> None:
    rig = _Rig()
    for _ in range(SEND_ATTEMPTS):
        rig.client.fail_next(TelegramFailure.NOT_WRITTEN)

    delivered = await rig.writer.deliver(LINE, "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.FAILED
    assert len(rig.sends()) == SEND_ATTEMPTS
    assert len(rig.waits) == SEND_ATTEMPTS - 1, "no wait after the last try"


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (TelegramFailure.UNKNOWN, ToolOutcome.INDETERMINATE),
        (TelegramFailure.REFUSED, ToolOutcome.FAILED),
    ],
    ids=["unknown", "refused"],
)
async def test_a_message_cut_short_between_parts_is_never_done(
    failure: TelegramFailure, outcome: ToolOutcome
) -> None:
    """§6:6: never done for a part Telegram did not accept; the chat's part is recorded."""
    rig = _Rig(fail_send=2, failure=failure)
    first, second = "a" * 4000, "b" * 4000

    delivered = await rig.writer.deliver(LINE, f"{first}\n\n{second}", effect_id=EFFECT)

    assert delivered.outcome is outcome
    assert delivered.position is None
    assert delivered.written == first
    assert len(rig.sends()) == 2, "the part that failed is not retried"


async def test_a_message_for_another_chat_is_refused_before_any_byte() -> None:
    """§6:1, §9:2: the place is the input's, and the line writes only to its own chat."""
    rig = _Rig()

    delivered = await rig.writer.deliver(line_channel(REFERENCE, CHAT + 1), "Hi.", effect_id=EFFECT)
    elsewhere = await rig.writer.deliver(line_channel("conn-other", CHAT), "Hi.", effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.FAILED
    assert delivered.reason == "telegram_other_chat"
    assert elsewhere.outcome is ToolOutcome.FAILED
    assert rig.client.calls == (), "nothing reached the client"


async def test_a_message_past_the_hub_chats_transcript_bound_is_sent_whole() -> None:
    """§6:6: the parts hold the whole text; the conversation's bound is not the line's."""
    rig = _Rig()
    text = "\n\n".join(f"{n}:" + "y" * 3990 for n in range(5)) + "\n\nThe end."
    assert len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS

    fitted = rig.writer.for_place(LINE).fitted(text)
    delivered = await rig.writer.for_place(LINE).deliver(fitted, effect_id=EFFECT)

    assert delivered.outcome is ToolOutcome.SUCCEEDED
    assert delivered.written == text
    assert "\n\n".join(one for _, one in rig.client.messages) == text
    assert rig.client.messages[-1][1].endswith("The end.")


async def test_the_place_writer_writes_whole_and_into_its_own_place() -> None:
    rig = _Rig()
    place = rig.writer.for_place(LINE)
    text = "x" * 5000

    fitted = place.fitted(text)
    assert (fitted.text, fitted.cut_off) == (text, False)
    delivered = await place.deliver(fitted, effect_id=EFFECT)
    assert delivered.outcome is ToolOutcome.SUCCEEDED
    assert len(rig.client.messages) == 2


# --- the fixed lines and the typing indicator (§5:3, §6:7, §6:10, §13:2) ----------------


async def test_a_fixed_line_is_claimed_then_sent_then_finished() -> None:
    rig = _Rig()

    claimed = await rig.writer.fixed(lambda: rig.intake.claim_reply(7), NON_TEXT_LINE)
    again = await rig.writer.fixed(lambda: rig.intake.claim_reply(7), NON_TEXT_LINE)

    assert claimed is True
    assert again is False, "an update answered once is never answered again (§5:9)"
    assert [one for _, one in rig.client.messages] == [NON_TEXT_LINE]
    (record,) = (await rig.intake.export()).calls
    assert record.kind is TelegramCallKind.FIXED_REPLY
    assert record.outcome is TelegramCallOutcome.DONE
    assert rig.client.calls[0].attempt == record.attempt


async def test_a_fixed_line_telegram_did_not_get_is_claimed_again_and_retried() -> None:
    rig = _Rig()
    rig.client.fail_next(TelegramFailure.NOT_WRITTEN)

    await rig.writer.fixed(lambda: rig.intake.claim_reply(7), NON_TEXT_LINE)

    first, second = (await rig.intake.export()).calls
    assert first.outcome is TelegramCallOutcome.NOT_DONE
    assert second.outcome is TelegramCallOutcome.DONE
    assert first.attempt != second.attempt, "each try is a claim of its own"
    assert len(rig.client.messages) == 1


async def test_a_fixed_line_whose_outcome_is_unknown_is_never_sent_again() -> None:
    rig = _Rig()
    rig.client.fail_next(TelegramFailure.UNKNOWN)

    await rig.writer.fixed(lambda: rig.intake.claim_reply(7), NON_TEXT_LINE)
    again = await rig.writer.fixed(lambda: rig.intake.claim_reply(7), NON_TEXT_LINE)

    (record,) = (await rig.intake.export()).calls
    assert record.outcome is TelegramCallOutcome.UNKNOWN
    assert again is False
    assert len([one for one in rig.client.calls if one.method == SEND_MESSAGE]) == 1


async def test_the_typing_indicator_is_renewed_each_time_claimed_until_cancelled() -> None:
    rig = _Rig()
    typing = asyncio.ensure_future(rig.writer.typing("act-1"))
    for _ in range(20):
        await asyncio.sleep(0)
        if rig.client.typing_shown >= 3:
            break
    rig.client.hang_next()
    for _ in range(20):
        await asyncio.sleep(0)
        if any(
            one.failure is None and one.method == SEND_CHAT_ACTION for one in rig.client.calls[3:]
        ):
            break
    typing.cancel()
    await asyncio.gather(typing, return_exceptions=True)

    records = (await rig.intake.export()).calls
    assert rig.client.typing_shown >= 3
    assert all(one.kind is TelegramCallKind.TYPING for one in records)
    assert all(one.activation_id == "act-1" for one in records)
    assert all(one.finished for one in records), "a renewal cut off is finished unknown"
    assert records[-1].outcome is TelegramCallOutcome.UNKNOWN
    assert {one.attempt for one in records} == {
        one.attempt for one in rig.client.calls if one.method == SEND_CHAT_ACTION
    }


class _GatedFinish:
    """The fake intake record, its ``finish`` held until :attr:`release` is set."""

    def __init__(self, record: FakeTelegramIntakeRecord) -> None:
        self._record = record
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)

    async def finish(self, attempt: str, outcome: TelegramOutcome) -> None:
        self.entered.set()
        await self.release.wait()
        await self._record.finish(attempt, outcome)
        self.finished = True


async def test_a_call_cancelled_twice_still_waits_for_its_record_to_be_finished() -> None:
    """ADR-0042 §2: a drain that cancels again must not leave the finish writing alone.

    The first cancellation is the close cutting a poll short; the second is the drain's,
    once its budget is spent. The finish is the store's write, and the store is closed
    only after the task has ended, so the task waits for the write.
    """
    rig = _Rig()
    gated = _GatedFinish(rig.intake)
    attempt = await rig.intake.claim_typing("act-1")
    rig.client.hang_next()
    writer = TelegramWriter(
        client=rig.client,
        intake=gated,
        channel=LINE,
        send_bound=timedelta(seconds=5),
    )
    task = asyncio.ensure_future(writer.typing("act-1"))
    for _ in range(50):
        await asyncio.sleep(0)
        if rig.client.calls:
            break
    task.cancel()
    await asyncio.wait_for(gated.entered.wait(), 5)
    task.cancel()
    for _ in range(20):
        await asyncio.sleep(0)

    assert not task.done(), "the second cancellation is held until the record is finished"
    gated.release.set()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert gated.finished
    records = {one.attempt: one for one in (await rig.intake.export()).calls}
    assert records[attempt].outcome is None, "the earlier claim is untouched"
    (cut,) = [one for one in records.values() if one.attempt != attempt]
    assert cut.outcome is TelegramCallOutcome.UNKNOWN
