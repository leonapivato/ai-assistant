"""ADR-0323's `core` shapes for the Bot API client: the length measure and the outcomes.

The outcomes carry their invariants as validators, so a send that is done without an
id, a poll not done that took updates in, or a wait on anything but a rate limit cannot
be constructed by any implementation or any caller.
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
)


def test_length_is_counted_in_utf16_units() -> None:
    """Telegram measures UTF-16, so an emoji takes two of the 4,096 (§6:6)."""
    assert telegram_length("hello") == 5
    assert telegram_length("\U0001f600") == 2
    assert telegram_length("é") == 1
    assert TELEGRAM_MESSAGE_LIMIT == 4096


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


def _message(text: str | None, command: str | None) -> TelegramMessage:
    return TelegramMessage(
        message_id=1,
        chat_id=1,
        private_chat=True,
        sent_at=datetime(2026, 10, 21, tzinfo=UTC),
        text=text,
        command=command,
    )


def test_a_message_carries_no_command_by_default() -> None:
    """ADR-0332 §7:9: ``None`` where the message has no ``bot_command`` entity."""
    assert _message("/stop", None).command is None


@pytest.mark.parametrize(("text", "command"), [("/stop", "/stop"), ("/stop now", "/stop")])
def test_a_command_is_where_the_text_begins(text: str, command: str) -> None:
    """§7:9: the part of the text an entity at its first character covers."""
    assert _message(text, command).command == command


@pytest.mark.parametrize(
    ("text", "command"),
    [(None, "/stop"), ("/stop", ""), ("please /stop", "/stop"), ("/st", "/stop")],
    ids=["no-text", "empty", "not-at-the-start", "longer-than-the-text"],
)
def test_a_command_that_is_not_the_start_of_the_text_is_refused(
    text: str | None, command: str
) -> None:
    """No implementation can hand the reader a command Telegram could not have marked."""
    with pytest.raises(ValidationError, match="first character"):
        _message(text, command)
