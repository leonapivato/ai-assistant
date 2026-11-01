"""Shared pieces for the Telegram line's cases (ADR-0323): updates, and a yielding Telegram.

The canonical :class:`~ai_assistant.testing.FakeTelegramBotClient` answers a poll at
once, as nothing is waiting; a real Telegram holds a poll open for its wait. A reader
looping over the fake would never give the loop back, so the cases drive it through
:class:`YieldingTelegram`, which yields before each poll as a real one would.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import (
    TelegramFailure,
    TelegramForwardOrigin,
    TelegramMessage,
    TelegramQuotedMessage,
    TelegramUpdate,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import TelegramOutcome, TelegramPollOutcome, TelegramSendOutcome
    from ai_assistant.testing import FakeTelegramBotClient

#: The owner's account, and so their chat with the bot.
CHAT: Final = 424242
REFERENCE: Final = "conn-0001"
AT: Final = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
#: How long a case waits for the reader before it fails rather than hangs.
SETTLE: Final = 5.0

#: The line's start wait in a case that runs the engine's reader on the real clock
#: (ADR-0332 §5:3): short, so a message is taken in at once.
CASE_START_WAIT: Final = timedelta(milliseconds=5)


def stop_command(update_id: int, *, minute: int = 0) -> TelegramUpdate:
    """The owner's bare ``/stop``, marked by its ``bot_command`` entity (ADR-0332 §8:1)."""
    return text(update_id, "/stop", minute=minute, command="/stop")


def text(  # noqa: PLR0913 — one knob per field of the message a case varies
    update_id: int,
    words: str,
    *,
    message_id: int | None = None,
    sender: int = CHAT,
    chat: int = CHAT,
    private: bool = True,
    bot: bool = False,
    minute: int = 0,
    forward: TelegramForwardOrigin | None = None,
    reply_to: TelegramQuotedMessage | None = None,
    command: str | None = None,
) -> TelegramUpdate:
    """One update carrying a message, by default the owner's text in their chat.

    ``command`` is the part of the text a ``bot_command`` entity at its first character
    covers, as the client reads it (ADR-0332 §7:9).
    """
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id if message_id is None else message_id,
            chat_id=chat,
            private_chat=private,
            sender_id=sender,
            sender_is_bot=bot,
            sent_at=AT + timedelta(minutes=minute),
            text=words,
            forward_origin=forward,
            reply_to=reply_to,
            command=command,
        ),
    )


def photo(update_id: int) -> TelegramUpdate:
    """A non-text message from the owner, in their chat."""
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id, chat_id=CHAT, private_chat=True, sender_id=CHAT, sent_at=AT
        ),
    )


class YieldingTelegram:
    """The fake Telegram, each poll yielding to the loop first, as a real one waits.

    ``failing_sends`` ends each next ``sendMessage`` with its failure, in turn.
    """

    def __init__(self, fake: FakeTelegramBotClient) -> None:
        self.fake = fake
        self.failing_sends: list[TelegramFailure] = []

    @property
    def chat_id(self) -> int:
        return self.fake.chat_id

    async def poll(self, **arguments: Any) -> TelegramPollOutcome:
        await asyncio.sleep(0.001)
        return await self.fake.poll(**arguments)

    async def send(self, **arguments: Any) -> TelegramSendOutcome:
        if self.failing_sends:
            self.fake.fail_next(self.failing_sends.pop(0))
        return await self.fake.send(**arguments)

    async def show_typing(self, **arguments: Any) -> TelegramOutcome:
        return await self.fake.show_typing(**arguments)

    async def send_with_buttons(self, **arguments: Any) -> TelegramSendOutcome:
        if self.failing_sends:
            self.fake.fail_next(self.failing_sends.pop(0))
        return await self.fake.send_with_buttons(**arguments)

    async def edit_message(self, **arguments: Any) -> TelegramOutcome:
        return await self.fake.edit_message(**arguments)

    async def answer_callback(self, **arguments: Any) -> TelegramOutcome:
        return await self.fake.answer_callback(**arguments)
