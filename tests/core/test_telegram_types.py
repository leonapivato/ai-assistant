"""ADR-0323's `core` shapes for the Bot API client: the split rule and the outcomes.

§6:6's split is a rule both sides of the line need — the writer cuts, and the client
refuses what was not cut — so it is pinned here, on its own, by the properties §6:6
states: no part longer than one message, the parts holding the whole text in order,
and the cut taken at the latest paragraph break, else line break, else whitespace,
and at the limit only where a run has no break.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    TELEGRAM_MESSAGE_LIMIT,
    TelegramFailure,
    TelegramMessage,
    TelegramOutcome,
    TelegramPollOutcome,
    TelegramSendOutcome,
    TelegramUpdate,
    telegram_length,
    telegram_message_parts,
)

LIMIT = TELEGRAM_MESSAGE_LIMIT


def _holds_the_whole(parts: tuple[str, ...], text: str) -> bool:
    """The parts, joined, are the text: §6:6's "the whole text in order"."""
    return "".join(parts) == text


def test_a_text_within_the_limit_is_one_part() -> None:
    """Nothing to cut."""
    assert telegram_message_parts("hello\n\nworld") == ("hello\n\nworld",)


def test_a_text_at_the_limit_is_one_part() -> None:
    """Exactly one message's worth is one message."""
    text = "x" * LIMIT

    assert telegram_message_parts(text) == (text,)


def test_a_long_text_is_cut_at_its_latest_paragraph_break() -> None:
    """Paragraphs first (§6:6)."""
    first, second, third = ("a" * 1500, "b" * 1500, "c" * 1500)
    text = f"{first}\n\n{second}\n\n{third}"

    parts = telegram_message_parts(text)

    assert parts == (f"{first}\n\n{second}\n\n", third)
    assert _holds_the_whole(parts, text)


def test_a_paragraph_longer_than_a_part_is_cut_at_a_line_break() -> None:
    """Then lines (§6:6)."""
    text = "a" * 3000 + "\n" + "b" * 3000

    parts = telegram_message_parts(text)

    assert parts == ("a" * 3000 + "\n", "b" * 3000)


def test_a_line_longer_than_a_part_is_cut_between_words() -> None:
    """Then words (§6:6), never inside one while a space is there."""
    text = "word " * 2000

    parts = telegram_message_parts(text)

    assert all(part.endswith(" ") for part in parts[:-1])
    assert all(telegram_length(part) <= LIMIT for part in parts)
    assert _holds_the_whole(parts, text)


def test_a_run_with_no_break_is_cut_at_the_limit() -> None:
    """And at the limit only where a run of text has no break (§6:6)."""
    text = "x" * (LIMIT * 2 + 10)

    parts = telegram_message_parts(text)

    assert [len(part) for part in parts] == [LIMIT, LIMIT, 10]


def test_characters_outside_the_bmp_count_twice() -> None:
    """Telegram measures UTF-16, so an emoji takes two of the 4,096."""
    emoji = "\U0001f600"
    text = emoji * LIMIT

    parts = telegram_message_parts(text)

    assert telegram_length(emoji) == 2
    assert [telegram_length(part) for part in parts] == [LIMIT, LIMIT]
    assert _holds_the_whole(parts, text)


def test_a_cut_never_leaves_a_part_of_whitespace_alone() -> None:
    """A part that would hold only whitespace carries nothing Telegram can show."""
    text = "a" + " " * (LIMIT * 2) + "b"

    parts = telegram_message_parts(text)

    assert all(part.strip() for part in parts)
    assert parts[0].startswith("a")
    assert parts[-1].endswith("b")


def test_a_leading_break_is_not_taken_as_the_cut() -> None:
    """A break with no text before it would make an empty part."""
    text = "\n\n" + "x" * (LIMIT + 5)

    parts = telegram_message_parts(text)

    assert all(part.strip() for part in parts)
    assert _holds_the_whole(parts, text)


def test_a_text_of_whitespace_has_no_parts() -> None:
    """Nothing to send."""
    assert telegram_message_parts("  \n\n  ") == ()
    assert telegram_message_parts("") == ()


@pytest.mark.parametrize(
    "text",
    [
        "para.\n\n" * 1500,
        ("line\n" * 900 + "\n") * 3,
        "mixed words\nand lines\n\nand paragraphs " * 400,
        "\U0001f600 " * 3000,
    ],
)
def test_every_part_fits_and_together_they_are_the_text(text: str) -> None:
    """§6:6's two properties, over texts of every shape."""
    parts = telegram_message_parts(text)

    assert len(parts) > 1
    assert all(0 < telegram_length(part) <= LIMIT for part in parts)
    assert _holds_the_whole(parts, text)


# --- the outcomes ----------------------------------------------------------------


def test_done_is_the_absence_of_a_failure() -> None:
    """One field, so the two cannot disagree."""
    assert TelegramOutcome().done
    assert not TelegramOutcome(failure=TelegramFailure.REFUSED).done


@pytest.mark.parametrize("failure", list(TelegramFailure))
def test_only_a_rate_limit_carries_a_wait(failure: TelegramFailure) -> None:
    """A wait is what Telegram asked for on a ``429``, and on nothing else."""
    if failure is TelegramFailure.RATE_LIMITED:
        assert TelegramOutcome(failure=failure, retry_after_seconds=3).retry_after_seconds == 3
    else:
        with pytest.raises(ValidationError, match="rate_limited"):
            TelegramOutcome(failure=failure, retry_after_seconds=3)


def test_the_retry_rule_is_section_6_3s() -> None:
    """Only a request never written, or a rate limit, is retried (§6:3 to §6:5)."""
    assert {failure for failure in TelegramFailure if failure.retryable} == {
        TelegramFailure.NOT_WRITTEN,
        TelegramFailure.RATE_LIMITED,
    }


def test_a_sent_message_has_an_id_and_only_a_sent_one() -> None:
    """Sent means Telegram returned its id (§6:2)."""
    assert TelegramSendOutcome(message_id=5).done
    with pytest.raises(ValidationError, match="message_id"):
        TelegramSendOutcome()
    with pytest.raises(ValidationError, match="message_id"):
        TelegramSendOutcome(failure=TelegramFailure.UNKNOWN, message_id=5)


def _update(update_id: int) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=1,
            chat_id=1,
            private_chat=True,
            sent_at=datetime(2026, 10, 17, tzinfo=UTC),
            text="hi",
        ),
    )


def test_a_poll_not_done_takes_nothing_in() -> None:
    """§11:11: a poll at its bound takes nothing in."""
    with pytest.raises(ValidationError, match="takes nothing in"):
        TelegramPollOutcome(failure=TelegramFailure.UNKNOWN, updates=(_update(1),))


@pytest.mark.parametrize("ids", [(2, 1), (1, 1)], ids=["descending", "repeated"])
def test_a_polls_updates_ascend(ids: tuple[int, int]) -> None:
    """Every offset computed from them relies on the order."""
    with pytest.raises(ValidationError, match="ascending"):
        TelegramPollOutcome(updates=tuple(_update(update_id) for update_id in ids))


def test_a_message_time_is_a_utc_instant() -> None:
    """Each message keeps the time Telegram gives it (§5:4), as every core instant is."""
    with pytest.raises(ValidationError):
        TelegramMessage(
            message_id=1,
            chat_id=1,
            private_chat=True,
            sent_at=datetime(2026, 10, 17),  # noqa: DTZ001 — the naive value is the point
        )


def test_an_id_that_is_a_flag_is_refused() -> None:
    """``True`` is not an update id."""
    with pytest.raises(ValidationError):
        TelegramUpdate(update_id=True)
