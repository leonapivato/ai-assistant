"""Shared conformance suite for the TelegramBotClient Protocol (ADR-0323 §6, §11, §15).

Every ``TelegramBotClient`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`TelegramBotClientContract`, supplies the ``client`` fixture, and overrides the
hooks below.

**Here rather than under ``tests/core/``**, beside ``forecaster_contract.py``: ADR-0323
§11:1 puts the production client in ``ai_assistant.tools.egress``, and this package is
where the suite sits beside it.

**Hooks, because the clauses are about what Telegram answered.** "A rate limit is
retryable", "a request written and never answered is unknown" and "nothing reaches
Telegram for another chat" can only be reached by a harness that controls the far end:
the production client's is a scripted channel under the fake transport, and the fake's
is its own arrangement. So each hook returns a :class:`Prepared` client whose Telegram
will answer the next call as the hook says, with a way to read back what reached
Telegram — the method and the JSON body, as the Bot API names them.

**The line's one origin is in here** (rule 5): every subject says which origin its
line reaches, through :meth:`TelegramBotClientContract.line_origin`, and every harness
reports the origin of each channel its client opened. **And so is relayed mode**
(ADR-0330 §12:1, §12's table): :class:`RelayedTelegramBotClientContract` runs every
case above against a subject in relayed mode — the relay serves the Bot API faithfully
(§4), so each holds of the relay's answers unchanged — and adds the obligations only a
relayed line has: no call to Telegram's own origin (§3:2), a credential carrying ``:``
refused before anything is opened (§6:3), and a relay whose certificate is outside the
configured set, or names another host, refused before any byte (§7).

**What is deliberately not in here** is everything only the production client has:
the credential's read order and its absence from every log, record and error (§11:4,
§11:9), the redirect (§11:5), the read bound (§11:13) and the one channel per call
(§11:14). A suite cannot see a keyring or a socket through the contract, so those are
the production client's own arms, in ``test_telegram_bot_client.py``.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, final

import pytest

from ai_assistant.core.protocols import TelegramBotClient
from ai_assistant.core.types import (
    TELEGRAM_BUTTONS_MAX,
    TELEGRAM_CALLBACK_ANSWER_MAX_CHARS,
    TELEGRAM_MESSAGE_LIMIT,
    TelegramButton,
    TelegramCallback,
    TelegramFailure,
    TelegramMessage,
    TelegramUpdate,
)
from ai_assistant.testing.telegram import TELEGRAM_DIRECT_ORIGIN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

pytestmark = pytest.mark.anyio

#: The bound every case passes unless it is about the bound. Generous, so a case
#: that fails is failing on its clause rather than on a machine's load.
A_BOUND: Final = timedelta(seconds=30)

#: The bound the expiry cases set: a real wait past it is a fraction of a second.
SHORT_BOUND: Final = timedelta(milliseconds=50)

#: The poll's wait every case passes, below :data:`A_BOUND`.
A_WAIT: Final = timedelta(seconds=20)

#: The attempt every case names: the claimed record's id.
ATTEMPT: Final = "effect-0001"

#: The card's two buttons, as the line posts them (ADR-0361 §4:2).
BUTTONS: Final = (
    TelegramButton(label="Approve", data="tok-1:y"),
    TelegramButton(label="Deny", data="tok-1:n"),
)

#: The Bot API's inline keyboard for :data:`BUTTONS`, one row.
KEYBOARD: Final = {
    "inline_keyboard": [
        [
            {"text": "Approve", "callback_data": "tok-1:y"},
            {"text": "Deny", "callback_data": "tok-1:n"},
        ]
    ]
}

#: How long a case waits for something it is owed. Failing here is a hang.
_WAIT_SECONDS: Final = 5.0


@final
@dataclass(frozen=True, slots=True)
class Reached:
    """One request that reached Telegram: its method and its JSON body.

    Attributes:
        method: The Bot API method, as Telegram names it.
        parameters: The body, decoded.
    """

    method: str
    parameters: Mapping[str, object]


@final
@dataclass(frozen=True, slots=True)
class Prepared:
    """A client whose Telegram will answer as its hook said, and what reached it.

    Attributes:
        client: The subject.
        reached: Every request that reached Telegram so far, in order.
        opened: The origin of every channel the client opened, or tried to, in
            order and in canonical form, ``https://host:port`` — whether or not
            anything was written on it.
    """

    client: TelegramBotClient
    reached: Callable[[], tuple[Reached, ...]]
    opened: Callable[[], tuple[str, ...]]


def a_tap(update_id: int, *, data: str = "tok-1:y", sender: int = 424242) -> TelegramUpdate:
    """An update carrying a tap on a button of message 900, in the owner's chat.

    Args:
        update_id: Telegram's id for the update.
        data: The button's callback data.
        sender: The account that tapped; the owner's by default.

    Returns:
        The update.
    """
    return TelegramUpdate(
        update_id=update_id,
        callback=TelegramCallback(
            callback_id=f"cb-{update_id}",
            sender_id=sender,
            chat_id=424242,
            private_chat=True,
            message_id=900,
            data=data,
        ),
    )


def an_update(
    update_id: int, *, text: str = "hello", sender: int | None = None, command: str | None = None
) -> TelegramUpdate:
    """An update carrying one text message from ``sender`` in their private chat.

    Args:
        update_id: Telegram's id for the update.
        text: The message's text.
        sender: The sending account; the line's chat by default.
        command: The text a ``bot_command`` entity at its first character covers, or
            ``None`` for a message with none (ADR-0332 §7:9).

    Returns:
        The update.
    """
    account = 424242 if sender is None else sender
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id + 1000,
            chat_id=account,
            private_chat=True,
            sender_id=account,
            sent_at=datetime(2026, 10, 17, 12, 0, update_id % 60, tzinfo=UTC),
            text=text,
            command=command,
        ),
    )


async def _reached_soon(prepared: Prepared) -> None:
    """Wait until a request has reached Telegram, failing on a hang.

    Args:
        prepared: The subject in flight.
    """
    async with asyncio.timeout(_WAIT_SECONDS):
        while not prepared.reached():  # noqa: ASYNC110 — two harnesses, no shared event
            await asyncio.sleep(0.001)


class TelegramBotClientContract:
    """Behaviour every ``TelegramBotClient`` implementation must exhibit (ADR-0323)."""

    @pytest.fixture
    def client(self) -> TelegramBotClient:
        """Override in a subclass with any conforming subject."""
        raise NotImplementedError

    def line_origin(self) -> str:
        """The one origin the subject's line reaches, canonical (rule 5).

        Telegram's in direct mode, which is the default; a relayed subject overrides it
        with its relay's.
        """
        return TELEGRAM_DIRECT_ORIGIN

    async def accepting(self, *, message_id: int) -> Prepared:
        """Override: a client whose Telegram does the next call it is asked.

        A send is accepted with ``message_id``; a typing indicator is shown; a poll
        finds nothing waiting.
        """
        raise NotImplementedError

    async def holding(self, *updates: TelegramUpdate) -> Prepared:
        """Override: a client whose Telegram answers the next poll with ``updates``."""
        raise NotImplementedError

    async def rate_limiting(self, *, retry_after: int | None) -> Prepared:
        """Override: a client whose Telegram answers the next call ``429``."""
        raise NotImplementedError

    async def refusing(self) -> Prepared:
        """Override: a client whose Telegram answers the next call with a ``400``."""
        raise NotImplementedError

    async def failing_inside(self) -> Prepared:
        """Override: a client whose Telegram answers the next call with a ``500``."""
        raise NotImplementedError

    async def unreachable(self) -> Prepared:
        """Override: a client whose next call's channel to Telegram never opens."""
        raise NotImplementedError

    async def garbled(self) -> Prepared:
        """Override: a client whose next call is written and answered with no Bot API
        answer at all."""
        raise NotImplementedError

    async def silent(self) -> Prepared:
        """Override: a client whose next call is written and never answered."""
        raise NotImplementedError

    async def disconnected(self) -> Prepared:
        """Override: a client whose line's connection is not active."""
        raise NotImplementedError

    # --- the shape ----------------------------------------------------------

    def test_conforms_to_protocol(self, client: TelegramBotClient) -> None:
        """The subject is a ``TelegramBotClient``, structurally."""
        assert isinstance(client, TelegramBotClient)

    def test_chat_id_is_the_owners_account(self, client: TelegramBotClient) -> None:
        """The one chat is an id, the owner's (§3:2)."""
        assert type(client.chat_id) is int
        assert client.chat_id > 0

    # --- the one origin (rule 5: §11:5, ADR-0330 §3:2) ----------------------

    async def test_every_call_goes_to_the_lines_one_origin(self) -> None:
        """A send, a typing indicator and a poll, each to the line's origin alone."""
        prepared = await self.accepting(message_id=3)
        chat = prepared.client.chat_id

        await prepared.client.send(attempt=ATTEMPT, chat_id=chat, text="hi", timeout=A_BOUND)
        await prepared.client.show_typing(attempt=ATTEMPT, chat_id=chat, timeout=A_BOUND)
        await prepared.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)

        assert prepared.opened() == (self.line_origin(),) * 3
        assert len(prepared.reached()) == 3

    # --- a send (§6) --------------------------------------------------------

    async def test_an_accepted_send_carries_the_id_telegram_returned(self) -> None:
        """Sent is accepted with an id, and the id is the message's position (§6:2)."""
        prepared = await self.accepting(message_id=77)
        chat = prepared.client.chat_id

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=chat, text="It is done.", timeout=A_BOUND
        )

        assert outcome.done
        assert outcome.message_id == 77
        assert prepared.reached() == (
            Reached("sendMessage", {"chat_id": chat, "text": "It is done."}),
        )

    async def test_a_send_to_another_chat_reaches_nothing(self) -> None:
        """The channel's rule: only the configured chat, before any byte (§6:1)."""
        prepared = await self.accepting(message_id=1)

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id + 1, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.OTHER_CHAT
        assert not outcome.failure.retryable
        assert prepared.reached() == ()

    async def test_a_rate_limit_is_retryable_and_carries_its_wait(self) -> None:
        """Telegram said it did not send, and a retry can succeed (§6:3)."""
        prepared = await self.rate_limiting(retry_after=7)

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.RATE_LIMITED
        assert outcome.failure.retryable
        assert outcome.retry_after_seconds == 7
        assert outcome.message_id is None

    async def test_a_rate_limit_naming_no_wait_carries_none(self) -> None:
        """No figure is invented where Telegram gave none."""
        prepared = await self.rate_limiting(retry_after=None)

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.RATE_LIMITED
        assert outcome.retry_after_seconds is None

    async def test_any_other_refusal_is_not_done_and_not_retried(self) -> None:
        """Every other refusal is *not done* (§6:5), and the client sends once."""
        prepared = await self.refusing()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.REFUSED
        assert not outcome.failure.retryable
        assert len(prepared.reached()) == 1

    async def test_a_server_error_is_unknown(self) -> None:
        """A server error does not say the message was not sent, so it is unknown."""
        prepared = await self.failing_inside()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.UNKNOWN
        assert not outcome.failure.retryable

    async def test_a_send_that_never_left_is_not_written_and_retryable(self) -> None:
        """Telegram did not get it, because the request was never written (§6:3)."""
        prepared = await self.unreachable()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.NOT_WRITTEN
        assert outcome.failure.retryable
        assert prepared.reached() == ()

    async def test_a_written_send_answered_with_no_answer_is_unknown(self) -> None:
        """What came back is no word from the Bot API, so it may have been sent (§6:4)."""
        prepared = await self.garbled()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.UNKNOWN
        assert len(prepared.reached()) == 1

    async def test_a_written_send_cut_off_by_its_bound_is_unknown(self) -> None:
        """A send cut off after its request was written is unknown (§11:12)."""
        prepared = await self.silent()

        async with asyncio.timeout(_WAIT_SECONDS):
            outcome = await prepared.client.send(
                attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=SHORT_BOUND
            )

        assert outcome.failure is TelegramFailure.UNKNOWN
        assert not outcome.failure.retryable

    async def test_a_disconnected_line_writes_nothing(self) -> None:
        """No active connection, no token and no byte (§11:4)."""
        prepared = await self.disconnected()
        chat = prepared.client.chat_id

        sent = await prepared.client.send(attempt=ATTEMPT, chat_id=chat, text="hi", timeout=A_BOUND)
        shown = await prepared.client.show_typing(attempt=ATTEMPT, chat_id=chat, timeout=A_BOUND)
        polled = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert sent.failure is shown.failure is polled.failure is TelegramFailure.UNAVAILABLE
        assert prepared.reached() == ()

    async def test_a_part_at_the_limit_is_sent(self) -> None:
        """Exactly one message's worth of text is one message (§6:6)."""
        prepared = await self.accepting(message_id=5)
        text = "x" * TELEGRAM_MESSAGE_LIMIT

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text=text, timeout=A_BOUND
        )

        assert outcome.done

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   \n ",
            "x" * (TELEGRAM_MESSAGE_LIMIT + 1),
            "\U0001f600" * (TELEGRAM_MESSAGE_LIMIT // 2 + 1),
            "\ud800",
        ],
        ids=["empty", "blank", "one-past", "emoji-past", "lone-surrogate"],
    )
    async def test_a_text_no_message_could_carry_is_refused_before_anything(
        self, text: str
    ) -> None:
        """A blank, over-long or unwritable text is the caller's fault (§6:6)."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match="text"):
            await prepared.client.send(
                attempt=ATTEMPT, chat_id=prepared.client.chat_id, text=text, timeout=A_BOUND
            )

        assert prepared.reached() == ()

    # --- the typing indicator (§6:7) ------------------------------------------

    async def test_the_typing_indicator_is_one_chat_action(self) -> None:
        """Typing is shown, and nothing is written into the chat (§6:7)."""
        prepared = await self.accepting(message_id=1)
        chat = prepared.client.chat_id

        outcome = await prepared.client.show_typing(attempt=ATTEMPT, chat_id=chat, timeout=A_BOUND)

        assert outcome.done
        assert prepared.reached() == (
            Reached("sendChatAction", {"chat_id": chat, "action": "typing"}),
        )

    async def test_typing_in_another_chat_reaches_nothing(self) -> None:
        """The same rule as a send's (§6:1)."""
        prepared = await self.accepting(message_id=1)

        outcome = await prepared.client.show_typing(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id + 1, timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.OTHER_CHAT
        assert prepared.reached() == ()

    async def test_a_refused_typing_indicator_is_not_done(self) -> None:
        """Classed as a send's is."""
        prepared = await self.refusing()

        outcome = await prepared.client.show_typing(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.REFUSED

    # --- the card: buttons, an edit and a callback's answer (ADR-0361 §8:3) -----

    async def test_a_message_with_buttons_carries_its_one_row(self) -> None:
        """A card is one ``sendMessage`` with an inline keyboard of one row (§4:2)."""
        prepared = await self.accepting(message_id=41)
        chat = prepared.client.chat_id

        outcome = await prepared.client.send_with_buttons(
            attempt=ATTEMPT, chat_id=chat, text="Approve this?", buttons=BUTTONS, timeout=A_BOUND
        )

        assert outcome.done
        assert outcome.message_id == 41
        assert prepared.reached() == (
            Reached(
                "sendMessage", {"chat_id": chat, "text": "Approve this?", "reply_markup": KEYBOARD}
            ),
        )

    async def test_buttons_to_another_chat_reach_nothing(self) -> None:
        """The channel's rule holds for a card as for a message (§6:1, ADR-0361 §4:12)."""
        prepared = await self.accepting(message_id=1)

        sent = await prepared.client.send_with_buttons(
            attempt=ATTEMPT,
            chat_id=prepared.client.chat_id + 1,
            text="hi",
            buttons=BUTTONS,
            timeout=A_BOUND,
        )
        edited = await prepared.client.edit_message(
            attempt=ATTEMPT,
            chat_id=prepared.client.chat_id + 1,
            message_id=1,
            text="hi",
            buttons=(),
            timeout=A_BOUND,
        )
        answered = await prepared.client.answer_callback(
            attempt=ATTEMPT,
            chat_id=prepared.client.chat_id + 1,
            callback_id="cb-1",
            text="Approved.",
            timeout=A_BOUND,
        )

        assert sent.failure is edited.failure is answered.failure is TelegramFailure.OTHER_CHAT
        assert prepared.reached() == ()

    @pytest.mark.parametrize(
        "buttons",
        [
            (),
            "Approve",
            (BUTTONS[0], BUTTONS[0]),
            (BUTTONS[0], "Deny"),
            tuple(
                TelegramButton(label=f"b{at}", data=f"d{at}")
                for at in range(TELEGRAM_BUTTONS_MAX + 1)
            ),
        ],
        ids=["none", "a-string", "one-data-twice", "not-a-button", "past-the-bound"],
    )
    async def test_buttons_no_message_could_carry_are_refused_before_anything(
        self, buttons: object
    ) -> None:
        """A row Telegram could not carry, or a tap could not tell apart, is refused."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match="buttons"):
            await prepared.client.send_with_buttons(
                attempt=ATTEMPT,
                chat_id=prepared.client.chat_id,
                text="hi",
                buttons=buttons,  # type: ignore[arg-type]  # the refusal is the point
                timeout=A_BOUND,
            )

        assert prepared.reached() == ()

    async def test_an_edit_replaces_the_text_and_takes_the_buttons_away(self) -> None:
        """``editMessageText`` with an empty keyboard: the card's state, no buttons (§4:5)."""
        prepared = await self.accepting(message_id=42)
        chat = prepared.client.chat_id
        posted = await prepared.client.send_with_buttons(
            attempt=ATTEMPT, chat_id=chat, text="Approve this?", buttons=BUTTONS, timeout=A_BOUND
        )
        assert posted.message_id is not None

        outcome = await prepared.client.edit_message(
            attempt=ATTEMPT,
            chat_id=chat,
            message_id=posted.message_id,
            text="Approved.",
            buttons=(),
            timeout=A_BOUND,
        )

        assert outcome.done
        assert prepared.reached()[-1] == Reached(
            "editMessageText",
            {
                "chat_id": chat,
                "message_id": posted.message_id,
                "text": "Approved.",
                "reply_markup": {"inline_keyboard": []},
            },
        )

    async def test_a_refused_edit_is_not_done(self) -> None:
        """Classed as a send's is, and not retried."""
        prepared = await self.refusing()

        outcome = await prepared.client.edit_message(
            attempt=ATTEMPT,
            chat_id=prepared.client.chat_id,
            message_id=5,
            text="Denied.",
            buttons=(),
            timeout=A_BOUND,
        )

        assert outcome.failure is TelegramFailure.REFUSED
        assert len(prepared.reached()) == 1

    @pytest.mark.parametrize("message_id", [0, -1, True, "5"], ids=["zero", "neg", "bool", "str"])
    async def test_an_edit_naming_no_message_is_refused_before_anything(
        self, message_id: object
    ) -> None:
        """A message id is the positive ``int`` Telegram gave."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match="message_id"):
            await prepared.client.edit_message(
                attempt=ATTEMPT,
                chat_id=prepared.client.chat_id,
                message_id=message_id,  # type: ignore[arg-type]  # the refusal is the point
                text="hi",
                buttons=(),
                timeout=A_BOUND,
            )

        assert prepared.reached() == ()

    async def test_a_callback_is_answered_by_one_answer_callback_query(self) -> None:
        """The tapper is shown the answer; nothing is written into the chat (§4:9)."""
        prepared = await self.accepting(message_id=1)

        outcome = await prepared.client.answer_callback(
            attempt=ATTEMPT,
            chat_id=prepared.client.chat_id,
            callback_id="cb-7",
            text="Approved.",
            timeout=A_BOUND,
        )

        assert outcome.done
        assert prepared.reached() == (
            Reached("answerCallbackQuery", {"callback_query_id": "cb-7", "text": "Approved."}),
        )

    @pytest.mark.parametrize(
        ("callback_id", "text", "named"),
        [
            ("", "Approved.", "callback_id"),
            (None, "Approved.", "callback_id"),
            ("cb-1", "", "text"),
            ("cb-1", "x" * (TELEGRAM_CALLBACK_ANSWER_MAX_CHARS + 1), "text"),
        ],
        ids=["blank-id", "no-id", "blank-text", "long-text"],
    )
    async def test_an_answer_no_call_could_make_is_refused_before_anything(
        self, callback_id: object, text: object, named: str
    ) -> None:
        """The id is the callback's, and the text fits Telegram's answer."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match=named):
            await prepared.client.answer_callback(
                attempt=ATTEMPT,
                chat_id=prepared.client.chat_id,
                callback_id=callback_id,  # type: ignore[arg-type]  # the refusal is the point
                text=text,  # type: ignore[arg-type]  # the refusal is the point
                timeout=A_BOUND,
            )

        assert prepared.reached() == ()

    async def test_a_disconnected_line_posts_edits_and_answers_nothing(self) -> None:
        """No active connection, no token and no byte, for the card's calls too (§11:4)."""
        prepared = await self.disconnected()
        chat = prepared.client.chat_id

        sent = await prepared.client.send_with_buttons(
            attempt=ATTEMPT, chat_id=chat, text="hi", buttons=BUTTONS, timeout=A_BOUND
        )
        edited = await prepared.client.edit_message(
            attempt=ATTEMPT, chat_id=chat, message_id=3, text="hi", buttons=(), timeout=A_BOUND
        )
        answered = await prepared.client.answer_callback(
            attempt=ATTEMPT, chat_id=chat, callback_id="cb-1", text="ok", timeout=A_BOUND
        )

        assert sent.failure is edited.failure is answered.failure is TelegramFailure.UNAVAILABLE
        assert prepared.reached() == ()

    # --- a poll (§5, §11:10 to §11:11) ----------------------------------------

    async def test_a_poll_hands_back_what_telegram_holds(self) -> None:
        """The updates come back typed, in order (§5)."""
        updates = (an_update(10), an_update(11, text="and this"))
        prepared = await self.holding(*updates)

        outcome = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert outcome.done
        assert outcome.updates == updates

    async def test_a_poll_hands_back_a_tap_as_a_callback(self) -> None:
        """A button's callback comes back typed, beside messages, in order (§8:3)."""
        updates = (an_update(30), a_tap(31), a_tap(32, data="tok-1:n", sender=7))
        prepared = await self.holding(*updates)

        outcome = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert outcome.done
        assert outcome.updates == updates

    async def test_a_stop_is_told_from_its_text_by_telegrams_entity_alone(self) -> None:
        """ADR-0332 §1:4, §7:9: two ``/stop`` texts, one marked a command by Telegram.

        They differ only in the ``bot_command`` entity, so one comes back carrying the
        command and the other as a message with none, and both are read whole. The
        command never comes from the text.
        """
        updates = (
            an_update(20, text="/stop", command="/stop"),
            an_update(21, text="/stop"),
            an_update(22, text="/stop@another_bot please", command="/stop@another_bot"),
        )
        prepared = await self.holding(*updates)

        outcome = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert outcome.done
        assert outcome.updates == updates
        commands = [one.message.command for one in outcome.updates if one.message is not None]
        assert commands == ["/stop", None, "/stop@another_bot"]

    async def test_a_poll_asks_for_new_messages_and_sends_its_offset(self) -> None:
        """The offset confirms; the wait is whole seconds, never more than asked."""
        prepared = await self.holding(an_update(10))

        await prepared.client.poll(
            attempt=ATTEMPT,
            offset=10,
            wait=timedelta(seconds=20, milliseconds=900),
            timeout=A_BOUND,
        )

        assert prepared.reached() == (
            Reached(
                "getUpdates",
                {"timeout": 20, "allowed_updates": ["message", "callback_query"], "offset": 10},
            ),
        )

    async def test_a_poll_with_no_offset_confirms_nothing(self) -> None:
        """``None`` sends no offset at all (§5:6)."""
        prepared = await self.holding()

        await prepared.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)

        (reached,) = prepared.reached()
        assert "offset" not in reached.parameters

    async def test_a_poll_cut_off_by_its_bound_is_unknown_and_takes_nothing(self) -> None:
        """A poll at its bound is unknown and takes nothing in (§11:11)."""
        prepared = await self.silent()

        async with asyncio.timeout(_WAIT_SECONDS):
            outcome = await prepared.client.poll(
                attempt=ATTEMPT, offset=None, wait=timedelta(0), timeout=SHORT_BOUND
            )

        assert outcome.failure is TelegramFailure.UNKNOWN
        assert outcome.updates == ()

    async def test_a_refused_poll_takes_nothing(self) -> None:
        """A poll not done carries no updates."""
        prepared = await self.refusing()

        outcome = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.REFUSED
        assert outcome.updates == ()

    @pytest.mark.parametrize(
        ("offset", "wait", "bound"),
        [
            (-1, A_WAIT, A_BOUND),
            (True, A_WAIT, A_BOUND),
            (None, timedelta(seconds=-1), A_BOUND),
            (None, A_BOUND, A_BOUND),
            (None, A_WAIT, A_WAIT - timedelta(seconds=1)),
            (None, A_WAIT, 30),
        ],
        ids=[
            "negative-offset",
            "bool-offset",
            "negative-wait",
            "bound-at-wait",
            "bound-below-wait",
            "bound-not-a-duration",
        ],
    )
    async def test_a_poll_no_call_could_make_is_refused_before_anything(
        self, offset: object, wait: object, bound: object
    ) -> None:
        """The bound exceeds the wait, and the offset confirms nothing it should not."""
        prepared = await self.holding()

        with pytest.raises(ValueError):  # noqa: PT011 — the parameter is named in the case id
            await prepared.client.poll(
                attempt=ATTEMPT,
                offset=offset,  # type: ignore[arg-type]  # the refusal is the point
                wait=wait,  # type: ignore[arg-type]  # the refusal is the point
                timeout=bound,  # type: ignore[arg-type]  # the refusal is the point
            )

        assert prepared.reached() == ()

    # --- every call -----------------------------------------------------------

    @pytest.mark.parametrize("attempt", ["", "   ", None])
    async def test_a_call_naming_no_claimed_record_is_refused(self, attempt: object) -> None:
        """Every call names the record claimed for it (§13:2)."""
        prepared = await self.accepting(message_id=1)
        chat = prepared.client.chat_id

        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.send(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                chat_id=chat,
                text="hi",
                timeout=A_BOUND,
            )
        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.show_typing(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                chat_id=chat,
                timeout=A_BOUND,
            )
        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.poll(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                offset=None,
                wait=A_WAIT,
                timeout=A_BOUND,
            )
        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.send_with_buttons(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                chat_id=chat,
                text="hi",
                buttons=BUTTONS,
                timeout=A_BOUND,
            )
        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.edit_message(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                chat_id=chat,
                message_id=1,
                text="hi",
                buttons=(),
                timeout=A_BOUND,
            )
        with pytest.raises(ValueError, match="attempt"):
            await prepared.client.answer_callback(
                attempt=attempt,  # type: ignore[arg-type]  # the refusal is the point
                chat_id=chat,
                callback_id="cb-1",
                text="ok",
                timeout=A_BOUND,
            )

        assert prepared.reached() == ()

    @pytest.mark.parametrize(
        "bound",
        [timedelta(0), timedelta(seconds=-1), 5, None],
        ids=["zero", "negative", "a-number", "none"],
    )
    async def test_a_bound_outside_its_domain_is_refused(self, bound: object) -> None:
        """There is no spelling for "unbounded" (ADR-0241 §1)."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match="timeout"):
            await prepared.client.send(
                attempt=ATTEMPT,
                chat_id=prepared.client.chat_id,
                text="hi",
                timeout=bound,  # type: ignore[arg-type]  # the refusal is the point
            )

        assert prepared.reached() == ()

    @pytest.mark.parametrize("chat_id", [True, 1.0, "424242"], ids=["bool", "float", "str"])
    async def test_a_chat_that_is_not_an_int_is_refused(self, chat_id: object) -> None:
        """A flag or a spelling is not a chat."""
        prepared = await self.accepting(message_id=1)

        with pytest.raises(ValueError, match="chat_id"):
            await prepared.client.send(
                attempt=ATTEMPT,
                chat_id=chat_id,  # type: ignore[arg-type]  # the refusal is the point
                text="hi",
                timeout=A_BOUND,
            )

        assert prepared.reached() == ()

    async def test_a_cancelled_call_is_delivered_onward(self) -> None:
        """ADR-0060 through this seam: a cancellation is never an outcome."""
        prepared = await self.silent()
        call = asyncio.ensure_future(
            prepared.client.send(
                attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
            )
        )
        await _reached_soon(prepared)

        call.cancel()

        with pytest.raises(asyncio.CancelledError):
            await call


class RelayedTelegramBotClientContract(TelegramBotClientContract):
    """What a line in relayed mode owes besides everything above (ADR-0330 §12:1).

    A subclass's subject is in relayed mode: :meth:`line_origin` is its relay's origin,
    and every hook above arranges its **relay**, which answers as Telegram would (§4).
    The four hooks below arrange what only a relayed line can meet.
    """

    def line_origin(self) -> str:
        """Override: the relay's canonical origin, which is never Telegram's."""
        raise NotImplementedError

    async def holding_a_bot_token(self) -> Prepared:
        """Override: a relayed client whose connection's slot holds a bot token.

        A credential carrying ``:``, the mark every Bot API token carries (§6:2).
        """
        raise NotImplementedError

    async def unanchored(self) -> Prepared:
        """Override: a relayed client whose relay presents a certificate chaining to
        no certificate in the configured set (§7:1)."""
        raise NotImplementedError

    async def misnamed(self) -> Prepared:
        """Override: a relayed client whose relay presents a certificate chaining to
        the configured set, issued for another host (§7:1, §7:5)."""
        raise NotImplementedError

    async def refusing_the_credential(self) -> Prepared:
        """Override: a relayed client whose relay does not know its credential.

        The relay answers ``401``, as Telegram answers an unknown token (§4:14).
        """
        raise NotImplementedError

    async def test_no_call_reaches_telegram_directly(self) -> None:
        """Every call goes to the relay, and none to ``https://api.telegram.org`` (§3:2)."""
        prepared = await self.accepting(message_id=8)
        chat = prepared.client.chat_id

        await prepared.client.send(attempt=ATTEMPT, chat_id=chat, text="hi", timeout=A_BOUND)
        await prepared.client.show_typing(attempt=ATTEMPT, chat_id=chat, timeout=A_BOUND)
        await prepared.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)

        assert self.line_origin() != TELEGRAM_DIRECT_ORIGIN
        assert TELEGRAM_DIRECT_ORIGIN not in prepared.opened()
        assert set(prepared.opened()) == {self.line_origin()}

    async def test_a_bot_token_in_the_slot_reaches_no_relay(self) -> None:
        """A credential carrying ``:`` is unavailable, and nothing is opened (§6:3)."""
        prepared = await self.holding_a_bot_token()
        chat = prepared.client.chat_id

        sent = await prepared.client.send(attempt=ATTEMPT, chat_id=chat, text="hi", timeout=A_BOUND)
        shown = await prepared.client.show_typing(attempt=ATTEMPT, chat_id=chat, timeout=A_BOUND)
        polled = await prepared.client.poll(
            attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
        )

        assert sent.failure is shown.failure is polled.failure is TelegramFailure.UNAVAILABLE
        assert not sent.failure.retryable
        assert prepared.reached() == ()
        assert prepared.opened() == ()

    @pytest.mark.parametrize("arrangement", ["unanchored", "misnamed"])
    async def test_a_relay_that_does_not_verify_is_written_nothing(self, arrangement: str) -> None:
        """A certificate outside the set, or for another host: a channel never opened (§7:4).

        Not written, so retryable, and nothing of the request — the credential
        included — reached the relay (§7:2).
        """
        hook: Callable[[], Awaitable[Prepared]] = getattr(self, arrangement)
        prepared = await hook()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.NOT_WRITTEN
        assert outcome.failure.retryable
        assert prepared.reached() == ()

    @pytest.mark.parametrize("arrangement", ["unanchored", "misnamed"])
    async def test_a_poll_to_a_relay_that_does_not_verify_takes_nothing(
        self, arrangement: str
    ) -> None:
        """A poll whose channel was never opened is not written, and takes nothing in."""
        hook: Callable[[], Awaitable[Prepared]] = getattr(self, arrangement)
        prepared = await hook()

        outcome = await prepared.client.poll(
            attempt=ATTEMPT, offset=5, wait=A_WAIT, timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.NOT_WRITTEN
        assert outcome.updates == ()
        assert prepared.reached() == ()

    async def test_an_unknown_credential_is_refused_and_not_retried(self) -> None:
        """The relay's ``401`` is a refusal: not done, and not retryable (§4's table)."""
        prepared = await self.refusing_the_credential()

        outcome = await prepared.client.send(
            attempt=ATTEMPT, chat_id=prepared.client.chat_id, text="hi", timeout=A_BOUND
        )

        assert outcome.failure is TelegramFailure.REFUSED
        assert not outcome.failure.retryable
        assert len(prepared.reached()) == 1
