"""The canonical ``TelegramBotClient`` fake, against the suite the real one passes.

``CONTRIBUTING.md`` requires that "each Protocol gets a shared test suite that every
implementation must pass". **Here rather than beside the fake**, following
``test_fake_forecaster.py``: the suite lives in this package because the production
client does, and a subclass has to sit where the suite is importable from.

Below the binding are the fake's own arrangements, which consumers lean on and the
suite does not reach: an offset forgetting what it confirms, a delivered *unknown*,
and a held call that never wrote.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from telegram_bot_client_contract import (
    A_BOUND,
    A_WAIT,
    ATTEMPT,
    SHORT_BOUND,
    Prepared,
    Reached,
    RelayedTelegramBotClientContract,
    TelegramBotClientContract,
    an_update,
)

from ai_assistant.core.types import TelegramButton, TelegramFailure, TelegramUpdate
from ai_assistant.testing import FakeTelegramBotClient
from ai_assistant.testing.telegram import TELEGRAM_DIRECT_ORIGIN

pytestmark = pytest.mark.anyio

#: The relay a relayed fake stands for, in canonical form.
RELAY_ORIGIN = "https://telegram-relay:8443"


def _prepared(fake: FakeTelegramBotClient) -> Prepared:
    """The fake with its record of what reached Telegram, and where."""

    def reached() -> tuple[Reached, ...]:
        return tuple(
            Reached(call.method, dict(call.parameters)) for call in fake.calls if call.reached
        )

    def opened() -> tuple[str, ...]:
        return tuple(call.origin for call in fake.calls if call.reached)

    return Prepared(client=fake, reached=reached, opened=opened)


class TestFakeTelegramBotClientContract(TelegramBotClientContract):
    """Binds :class:`FakeTelegramBotClient` to the shared suite."""

    @pytest.fixture
    def client(self) -> FakeTelegramBotClient:
        """A fake over a healthy Telegram."""
        return FakeTelegramBotClient()

    async def accepting(self, *, message_id: int) -> Prepared:
        """A fake whose next message gets ``message_id``."""
        return _prepared(FakeTelegramBotClient(first_message_id=message_id))

    async def holding(self, *updates: TelegramUpdate) -> Prepared:
        """A fake holding ``updates``."""
        return _prepared(FakeTelegramBotClient().hold(*updates))

    async def rate_limiting(self, *, retry_after: int | None) -> Prepared:
        """A fake whose next call is rate limited."""
        fake = FakeTelegramBotClient().fail_next(
            TelegramFailure.RATE_LIMITED, retry_after_seconds=retry_after
        )
        return _prepared(fake)

    async def refusing(self) -> Prepared:
        """A fake whose next call is refused."""
        return _prepared(FakeTelegramBotClient().fail_next(TelegramFailure.REFUSED))

    async def failing_inside(self) -> Prepared:
        """A fake whose next call meets a server error: unknown."""
        return _prepared(FakeTelegramBotClient().fail_next(TelegramFailure.UNKNOWN))

    async def unreachable(self) -> Prepared:
        """A fake whose next call never leaves."""
        return _prepared(FakeTelegramBotClient().fail_next(TelegramFailure.NOT_WRITTEN))

    async def garbled(self) -> Prepared:
        """A fake whose next call is answered with no answer: unknown."""
        return _prepared(FakeTelegramBotClient().fail_next(TelegramFailure.UNKNOWN))

    async def silent(self) -> Prepared:
        """A fake whose next call is written and never answered."""
        return _prepared(FakeTelegramBotClient().hang_next())

    async def disconnected(self) -> Prepared:
        """A fake whose line is not connected."""
        fake = FakeTelegramBotClient()
        fake.disconnect()
        return _prepared(fake)


class TestRelayedFakeTelegramBotClientContract(
    TestFakeTelegramBotClientContract, RelayedTelegramBotClientContract
):
    """Binds a fake standing for a relayed line to the suite and its relayed obligations.

    Every hook builds its fake through :meth:`_fake`, so each is relayed; the relay's
    own conditions are the fake's ordinary arrangements (the fake's module docstring).
    """

    @pytest.fixture
    def client(self) -> FakeTelegramBotClient:
        """A relayed fake over a healthy relay."""
        return FakeTelegramBotClient(origin=RELAY_ORIGIN)

    def line_origin(self) -> str:
        """The relay's."""
        return RELAY_ORIGIN

    async def accepting(self, *, message_id: int) -> Prepared:
        """A relayed fake whose next message gets ``message_id``."""
        return _prepared(FakeTelegramBotClient(first_message_id=message_id, origin=RELAY_ORIGIN))

    async def holding(self, *updates: TelegramUpdate) -> Prepared:
        """A relayed fake holding ``updates``."""
        return _prepared(FakeTelegramBotClient(origin=RELAY_ORIGIN).hold(*updates))

    async def rate_limiting(self, *, retry_after: int | None) -> Prepared:
        """A relayed fake whose relay rate-limits the next call."""
        fake = FakeTelegramBotClient(origin=RELAY_ORIGIN).fail_next(
            TelegramFailure.RATE_LIMITED, retry_after_seconds=retry_after
        )
        return _prepared(fake)

    async def refusing(self) -> Prepared:
        """A relayed fake whose relay refuses the next call."""
        return _prepared(
            FakeTelegramBotClient(origin=RELAY_ORIGIN).fail_next(TelegramFailure.REFUSED)
        )

    async def failing_inside(self) -> Prepared:
        """A relayed fake whose relay passed it on and heard nothing: unknown."""
        return _prepared(
            FakeTelegramBotClient(origin=RELAY_ORIGIN).fail_next(TelegramFailure.UNKNOWN)
        )

    async def unreachable(self) -> Prepared:
        """A relayed fake whose next call never leaves."""
        return _prepared(
            FakeTelegramBotClient(origin=RELAY_ORIGIN).fail_next(TelegramFailure.NOT_WRITTEN)
        )

    async def garbled(self) -> Prepared:
        """A relayed fake whose next call is answered with no answer: unknown."""
        return _prepared(
            FakeTelegramBotClient(origin=RELAY_ORIGIN).fail_next(TelegramFailure.UNKNOWN)
        )

    async def silent(self) -> Prepared:
        """A relayed fake whose next call is written and never answered."""
        return _prepared(FakeTelegramBotClient(origin=RELAY_ORIGIN).hang_next())

    async def disconnected(self) -> Prepared:
        """A relayed fake whose line is not connected."""
        fake = FakeTelegramBotClient(origin=RELAY_ORIGIN)
        fake.disconnect()
        return _prepared(fake)

    async def holding_a_bot_token(self) -> Prepared:
        """A bot token in the slot is the fake's *unavailable*, every call (§6:3)."""
        return await self.disconnected()

    async def unanchored(self) -> Prepared:
        """An unverified relay is a channel never opened: not written."""
        return await self.unreachable()

    async def misnamed(self) -> Prepared:
        """As :meth:`unanchored`."""
        return await self.unreachable()

    async def refusing_the_credential(self) -> Prepared:
        """The relay's ``401`` is a refusal."""
        return await self.refusing()


def test_a_fake_is_a_direct_line_unless_told_otherwise() -> None:
    """Built with no origin, every call goes to Telegram's own (ADR-0330 §3:1)."""
    assert FakeTelegramBotClient().origin == TELEGRAM_DIRECT_ORIGIN
    assert FakeTelegramBotClient(origin=RELAY_ORIGIN).origin == RELAY_ORIGIN


async def test_an_offset_forgets_what_it_confirms_and_nothing_else() -> None:
    """Telegram keeps an unconfirmed update and forgets a confirmed one (§5:6)."""
    fake = FakeTelegramBotClient().hold(an_update(10), an_update(11), an_update(12))

    first = await fake.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)
    second = await fake.poll(attempt=ATTEMPT, offset=12, wait=A_WAIT, timeout=A_BOUND)

    assert [update.update_id for update in first.updates] == [10, 11, 12]
    assert [update.update_id for update in second.updates] == [12]
    assert [update.update_id for update in fake.held] == [12]


async def test_an_unknown_poll_may_have_confirmed_its_offset() -> None:
    """Telegram received it, so its offset took effect: the case a reader survives."""
    fake = FakeTelegramBotClient().hold(an_update(10), an_update(11))
    fake.fail_next(TelegramFailure.UNKNOWN)

    outcome = await fake.poll(attempt=ATTEMPT, offset=11, wait=A_WAIT, timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert [update.update_id for update in fake.held] == [11]


async def test_a_poll_that_never_left_confirms_nothing() -> None:
    """Not written, so Telegram never saw the offset."""
    fake = FakeTelegramBotClient().hold(an_update(10), an_update(11))
    fake.fail_next(TelegramFailure.NOT_WRITTEN)

    await fake.poll(attempt=ATTEMPT, offset=11, wait=A_WAIT, timeout=A_BOUND)

    assert [update.update_id for update in fake.held] == [10, 11]


async def test_a_delivered_unknown_is_in_the_chat_and_still_unknown() -> None:
    """The half of *unknown* the caller cannot see, made arrangeable (§6:4)."""
    fake = FakeTelegramBotClient().fail_next(TelegramFailure.UNKNOWN, delivered=True)

    outcome = await fake.send(attempt=ATTEMPT, chat_id=fake.chat_id, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert fake.messages == ((1, "hi"),)


async def test_a_send_held_before_its_write_expires_not_written() -> None:
    """A channel that never opened: Telegram did not get it (§6:3)."""
    fake = FakeTelegramBotClient().hang_next(written=False)

    outcome = await fake.send(attempt=ATTEMPT, chat_id=fake.chat_id, text="hi", timeout=SHORT_BOUND)

    assert outcome.failure is TelegramFailure.NOT_WRITTEN
    assert not fake.calls[0].reached


async def test_a_poll_held_before_its_write_still_expires_unknown() -> None:
    """A poll at its bound is unknown, whatever it had written (§11:11)."""
    fake = FakeTelegramBotClient().hang_next(written=False)

    outcome = await fake.poll(attempt=ATTEMPT, offset=None, wait=timedelta(0), timeout=SHORT_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN


async def test_every_call_is_recorded_with_its_attempt_and_ending() -> None:
    """A consumer completes its record from the outcome; the fake keeps both."""
    fake = FakeTelegramBotClient().fail_next(TelegramFailure.REFUSED)

    await fake.show_typing(attempt="typing-1", chat_id=fake.chat_id, timeout=A_BOUND)
    await fake.send(attempt="effect-2", chat_id=fake.chat_id, text="hi", timeout=A_BOUND)

    assert [(call.attempt, call.method, call.failure) for call in fake.calls] == [
        ("typing-1", "sendChatAction", TelegramFailure.REFUSED),
        ("effect-2", "sendMessage", None),
    ]
    assert fake.typing_shown == 0
    assert fake.messages == ((1, "hi"),)


def test_other_chat_is_not_arrangeable() -> None:
    """The arguments decide it, never Telegram."""
    with pytest.raises(ValueError, match="other_chat"):
        FakeTelegramBotClient().fail_next(TelegramFailure.OTHER_CHAT)


def test_held_updates_ascend() -> None:
    """Telegram's ids ascend, and an offset is computed on that."""
    with pytest.raises(ValueError, match="ascending"):
        FakeTelegramBotClient().hold(an_update(11), an_update(10))


def test_the_repr_names_counts_and_no_text() -> None:
    """Nothing written is rendered."""
    assert "hello" not in repr(FakeTelegramBotClient().hold(an_update(1)))


# --- the fake's own Telegram, for the card (ADR-0361 §8:3) ----------------------------


async def test_the_fake_keeps_a_cards_buttons_until_an_edit_takes_them() -> None:
    """A card's buttons are on its message until an edit replaces them."""
    fake = FakeTelegramBotClient(first_message_id=5)
    buttons = (
        TelegramButton(label="Approve", data="t:y"),
        TelegramButton(label="Deny", data="t:n"),
    )
    bound = timedelta(seconds=5)
    sent = await fake.send_with_buttons(
        attempt="a", chat_id=fake.chat_id, text="Approve?", buttons=buttons, timeout=bound
    )
    assert fake.buttons == {5: buttons}

    edited = await fake.edit_message(
        attempt="b", chat_id=fake.chat_id, message_id=5, text="Approved.", buttons=(), timeout=bound
    )

    assert sent.message_id == 5
    assert edited.done
    assert fake.messages == ((5, "Approved."),)
    assert fake.buttons == {}


async def test_the_fake_refuses_an_edit_of_no_message_and_one_changing_nothing() -> None:
    """Telegram's own two refusals of an edit: no such message, and "not modified"."""
    fake = FakeTelegramBotClient(first_message_id=5)
    bound = timedelta(seconds=5)
    await fake.send(attempt="a", chat_id=fake.chat_id, text="Same.", timeout=bound)

    missing = await fake.edit_message(
        attempt="b", chat_id=fake.chat_id, message_id=6, text="x", buttons=(), timeout=bound
    )
    unchanged = await fake.edit_message(
        attempt="c", chat_id=fake.chat_id, message_id=5, text="Same.", buttons=(), timeout=bound
    )

    assert missing.failure is unchanged.failure is TelegramFailure.REFUSED


async def test_the_fakes_tap_is_held_as_a_callback_from_the_owner() -> None:
    """A tap is held until confirmed, carrying its data, from the owner by default."""
    fake = FakeTelegramBotClient()

    update = fake.tap(3, message_id=9, data="t:y")

    assert fake.held == (update,)
    assert update.callback is not None
    assert update.callback.sender_id == fake.chat_id
    assert update.callback.chat_id == fake.chat_id
