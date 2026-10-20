"""A canonical :class:`~ai_assistant.core.protocols.TelegramBotClient` fake (ADR-0323 §15).

The shared test double for the Bot API client, so the line's reader and writer in
``orchestration`` can exercise every branch they owe — a poll that confirms, a send
that is refused, a send that may have gone, a line that is not connected — without a
token, a channel or Telegram (``CLAUDE.md`` golden rule 1). It **is** a fake Telegram
for those consumers, which ADR-0323 §15:5 requires the line to be tested against.

**It behaves as a healthy Telegram until told otherwise.** Updates it is told to
:meth:`~FakeTelegramBotClient.hold` are handed back by every poll until an offset
confirms them, exactly as Telegram keeps an unconfirmed update; every send is
accepted with the next message id; every typing indicator is shown.

**And it can be told otherwise into every class the contract distinguishes**:
:meth:`~FakeTelegramBotClient.fail_next` ends the next call with any failure a far end
can produce, :meth:`~FakeTelegramBotClient.hang_next` holds the next call open past its
bound — the honest route to an expiry, and the lever a cancellation case needs — and
:meth:`~FakeTelegramBotClient.disconnect` stands for the connection no longer being
active. :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT` is not arrangeable:
it is decided by the arguments, here as in production.

**It records every call on entry**, with whether its request reached Telegram, so a
case asserting that something was *not* sent reads a record rather than an absence.
It holds no token and records no target: there is none to record.

**It stands for a line in either mode** (ADR-0330 §3). Built with no ``origin`` it is a
direct line, whose every request reaches :data:`TELEGRAM_DIRECT_ORIGIN`; built with a
relay's canonical origin, every request reaches that one instead and none reaches
Telegram's (§3:2). The relay serves the Bot API faithfully (§4), so nothing else about
the fake changes with the mode: a relay's refusal, silence or unverified certificate is
arranged with the same :meth:`~FakeTelegramBotClient.fail_next` and
:meth:`~FakeTelegramBotClient.hang_next` as Telegram's, and a relayed line holding a bot
token in its slot is :meth:`~FakeTelegramBotClient.disconnect`'s *unavailable* (§6:3).

**It checks its arguments exactly as the production client does**, written out rather
than imported — ``ai_assistant.testing`` imports ``core`` and nothing else — because a
fake that answered a call production refuses would let a consumer's test pass over an
exchange no deployment can have. The shared suite holds both to the same refusals.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self, final

from ai_assistant.core.types import (
    TELEGRAM_MESSAGE_LIMIT,
    TelegramFailure,
    TelegramOutcome,
    TelegramPollOutcome,
    TelegramSendOutcome,
    TelegramUpdate,
    telegram_length,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The owner's account, and so their private chat with the bot, unless a case names
#: another.
DEFAULT_TELEGRAM_CHAT_ID: Final = 424242

#: The origin a line in direct mode reaches, in the canonical form the seam pins it in
#: (ADR-0323 §11:5, ADR-0231 §8): ``https://api.telegram.org`` with its port written.
TELEGRAM_DIRECT_ORIGIN: Final = "https://api.telegram.org:443"

#: The Bot API methods, by the names Telegram gives them and the production client
#: calls.
GET_UPDATES: Final = "getUpdates"
SEND_MESSAGE: Final = "sendMessage"
SEND_CHAT_ACTION: Final = "sendChatAction"

#: How many updates one poll hands back at most, Telegram's own default ``limit``.
_POLL_LIMIT: Final = 100

#: The failures a far end can end a call with, which :meth:`fail_next` takes, and
#: whether each one's request had reached Telegram. ``OTHER_CHAT`` is absent: no far
#: end decides it.
_REACHED: Final[Mapping[TelegramFailure, bool]] = MappingProxyType(
    {
        TelegramFailure.UNAVAILABLE: False,
        TelegramFailure.NOT_WRITTEN: False,
        TelegramFailure.RATE_LIMITED: True,
        TelegramFailure.REFUSED: True,
        TelegramFailure.UNKNOWN: True,
    }
)


@final
@dataclass(frozen=True, slots=True)
class TelegramCall:
    """One call the fake was asked to make, as Telegram would have seen it.

    Attributes:
        attempt: The claimed record's id the caller named.
        method: The Bot API method: :data:`GET_UPDATES`, :data:`SEND_MESSAGE` or
            :data:`SEND_CHAT_ACTION`.
        parameters: The request's JSON body, as the production client writes it — so
            a case can assert the offset a poll confirmed or the text a send carried.
        reached: Whether the request reached Telegram. ``False`` for a call refused
            before anything was written.
        failure: How it ended, or ``None`` where it was done. ``None`` too while a
            held call is still open.
        origin: The origin the call was made to: the line's one origin, Telegram's
            in direct mode and the relay's in relayed mode (ADR-0330 §3:2).
    """

    attempt: str
    method: str
    parameters: Mapping[str, object]
    reached: bool
    failure: TelegramFailure | None
    origin: str = TELEGRAM_DIRECT_ORIGIN


@final
@dataclass(frozen=True, slots=True)
class _Arranged:
    """One arranged ending for the next call."""

    failure: TelegramFailure | None
    retry_after_seconds: int | None = None
    delivered: bool = False
    hang: bool = False
    written: bool = True


@final
class FakeTelegramBotClient:
    """A :class:`~ai_assistant.core.protocols.TelegramBotClient` with Telegram in memory.

    Constructed with no arguments, deliberately: the Protocol-triad check evaluates the
    suite's subject fixture with nothing but ``self``.
    """

    __slots__ = (
        "_arranged",
        "_calls",
        "_chat_id",
        "_connected",
        "_held",
        "_messages",
        "_next_message_id",
        "_origin",
        "_typing",
    )

    def __init__(
        self,
        *,
        chat_id: int = DEFAULT_TELEGRAM_CHAT_ID,
        first_message_id: int = 1,
        origin: str = TELEGRAM_DIRECT_ORIGIN,
    ) -> None:
        """Open a line to the user's chat, with nothing held and nothing sent.

        Args:
            chat_id: The user's account id, so the one chat the fake writes to.
            first_message_id: The id the first accepted message gets; each later one
                gets the next.
            origin: The line's one origin: :data:`TELEGRAM_DIRECT_ORIGIN` for a direct
                line, or a relay's canonical origin for a relayed one (ADR-0330 §3).
        """
        self._origin = origin
        self._chat_id = chat_id
        self._next_message_id = first_message_id
        self._held: list[TelegramUpdate] = []
        self._arranged: deque[_Arranged] = deque()
        self._calls: list[TelegramCall] = []
        self._messages: list[tuple[int, str]] = []
        self._typing = 0
        self._connected = True

    def __repr__(self) -> str:
        """Describe the fake by its counts, never by what was written."""
        return (
            f"FakeTelegramBotClient(calls={len(self._calls)}, held={len(self._held)}, "
            f"messages={len(self._messages)}, connected={self._connected})"
        )

    # --- arranging Telegram -------------------------------------------------

    def hold(self, *updates: TelegramUpdate) -> Self:
        """Have Telegram hold these updates until an offset confirms them.

        Args:
            updates: In ascending update id, and above every update already held.

        Returns:
            This fake, so an arrangement reads as one expression.

        Raises:
            ValueError: If the ids do not ascend — Telegram's never do, and an offset
                is computed on that.
        """
        ids = [update.update_id for update in (*self._held, *updates)]
        if any(later <= earlier for earlier, later in pairwise(ids)):
            msg = "held updates are in strictly ascending update_id, as Telegram's are"
            raise ValueError(msg)
        self._held.extend(updates)
        return self

    def fail_next(
        self,
        failure: TelegramFailure,
        *,
        retry_after_seconds: int | None = None,
        delivered: bool = False,
    ) -> Self:
        """End the next call, whatever its method, with ``failure``.

        Queued: each call takes the earliest arrangement still waiting.

        Args:
            failure: Any failure but :attr:`TelegramFailure.OTHER_CHAT`, which the
                arguments decide.
            retry_after_seconds: The wait a :attr:`TelegramFailure.RATE_LIMITED`
                carries, where Telegram said one.
            delivered: For an :attr:`TelegramFailure.UNKNOWN` send, whether the
                message did in fact reach the chat — the half of *unknown* the caller
                can never see, and the reason it is never retried.

        Returns:
            This fake.

        Raises:
            ValueError: For ``OTHER_CHAT``, for a wait on any other failure, or for
                ``delivered`` on anything but ``UNKNOWN``.
        """
        if failure not in _REACHED:
            msg = "other_chat is decided by the call's arguments, not by Telegram"
            raise ValueError(msg)
        TelegramOutcome(failure=failure, retry_after_seconds=retry_after_seconds)
        if delivered and failure is not TelegramFailure.UNKNOWN:
            msg = "only an unknown outcome can hide a delivered message"
            raise ValueError(msg)
        self._arranged.append(
            _Arranged(
                failure=failure,
                retry_after_seconds=retry_after_seconds,
                delivered=delivered,
                written=_REACHED[failure],
            )
        )
        return self

    def hang_next(self, *, written: bool = True) -> Self:
        """Hold the next call open until its bound ends, or it is cancelled.

        Args:
            written: Whether the request had been written when it stalled — ``True``
                for a far end that never answers, ``False`` for a channel that never
                opened. A send's expiry is then *unknown* or *not written*; a poll's is
                *unknown* either way (ADR-0323 §11:11).

        Returns:
            This fake.
        """
        self._arranged.append(_Arranged(failure=None, hang=True, written=written))
        return self

    def disconnect(self) -> None:
        """Stand for the line's connection no longer being active.

        Every call is then :attr:`TelegramFailure.UNAVAILABLE`, and nothing is written.
        """
        self._connected = False

    def reconnect(self) -> None:
        """Lift :meth:`disconnect`."""
        self._connected = True

    # --- observing ----------------------------------------------------------

    @property
    def calls(self) -> tuple[TelegramCall, ...]:
        """Every call made, in order, recorded on entry and completed on exit."""
        return tuple(self._calls)

    @property
    def messages(self) -> tuple[tuple[int, str], ...]:
        """Every message the chat holds, as ``(message_id, text)``, in order."""
        return tuple(self._messages)

    @property
    def held(self) -> tuple[TelegramUpdate, ...]:
        """The updates Telegram still holds, unconfirmed."""
        return tuple(self._held)

    @property
    def typing_shown(self) -> int:
        """How many typing indicators Telegram showed."""
        return self._typing

    @property
    def origin(self) -> str:
        """The line's one origin, which every call it makes is made to."""
        return self._origin

    # --- the contract -------------------------------------------------------

    @property
    def chat_id(self) -> int:
        """The owner's private chat with the bot."""
        return self._chat_id

    async def poll(
        self,
        *,
        attempt: str,
        offset: int | None,
        wait: timedelta,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1)
    ) -> TelegramPollOutcome:
        """Hand back what Telegram holds, after forgetting what ``offset`` confirms.

        Args:
            attempt: The claimed record's id.
            offset: The lowest update id still wanted, or ``None``.
            wait: How long Telegram may hold the request open. The fake answers at
                once: it has nothing to wait for.
            timeout: The bound on the poll, strictly greater than ``wait``.

        Returns:
            The outcome.

        Raises:
            ValueError: As the contract states, before anything is recorded.
        """
        attempt = _checked_attempt(attempt)
        if offset is not None and (type(offset) is not int or not 0 <= offset < 2**63):
            msg = "offset is None or a non-negative int"
            raise ValueError(msg)
        held = _checked_duration(wait, name="wait", positive=False)
        bound = _checked_duration(timeout, name="timeout", positive=True)
        if bound <= held:
            msg = f"timeout ({bound}) must be strictly greater than wait ({held})"
            raise ValueError(msg)
        parameters: dict[str, object] = {
            "timeout": int(held.total_seconds()),
            "allowed_updates": ["message"],
        }
        if offset is not None:
            parameters["offset"] = offset
        ended = await self._ended(attempt, GET_UPDATES, parameters, bound, poll=True)
        if ended is None or (ended.failure is TelegramFailure.UNKNOWN and ended.written):
            # A poll Telegram received confirms its offset, whether or not its answer
            # came back: an unknown poll may have confirmed, and the fake takes the
            # case a reader must survive (§11:11).
            self._confirm(offset)
        if ended is not None:
            return TelegramPollOutcome(
                failure=ended.failure, retry_after_seconds=ended.retry_after_seconds
            )
        return TelegramPollOutcome(updates=tuple(self._held[:_POLL_LIMIT]))

    async def send(
        self,
        *,
        attempt: str,
        chat_id: int,
        text: str,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1)
    ) -> TelegramSendOutcome:
        """Put one message into the chat, or end as arranged.

        Args:
            attempt: The claimed record's id.
            chat_id: The chat, which must be :attr:`chat_id`.
            text: The text, within one Telegram message.
            timeout: The bound on the send.

        Returns:
            The outcome.

        Raises:
            ValueError: As the contract states, before anything is recorded.
        """
        attempt = _checked_attempt(attempt)
        chat = _checked_chat(chat_id)
        body = _checked_text(text)
        bound = _checked_duration(timeout, name="timeout", positive=True)
        parameters = {"chat_id": chat, "text": body}
        if chat != self._chat_id:
            self._record(attempt, SEND_MESSAGE, parameters, TelegramFailure.OTHER_CHAT)
            return TelegramSendOutcome(failure=TelegramFailure.OTHER_CHAT)
        ended = await self._ended(attempt, SEND_MESSAGE, parameters, bound, poll=False)
        if ended is not None:
            if ended.delivered:
                self._deliver(body)
            return TelegramSendOutcome(
                failure=ended.failure, retry_after_seconds=ended.retry_after_seconds
            )
        return TelegramSendOutcome(message_id=self._deliver(body))

    async def show_typing(
        self,
        *,
        attempt: str,
        chat_id: int,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1)
    ) -> TelegramOutcome:
        """Show "typing…" in the chat, or end as arranged.

        Args:
            attempt: The claimed record's id.
            chat_id: The chat, which must be :attr:`chat_id`.
            timeout: The bound on the call.

        Returns:
            The outcome.

        Raises:
            ValueError: As the contract states, before anything is recorded.
        """
        attempt = _checked_attempt(attempt)
        chat = _checked_chat(chat_id)
        bound = _checked_duration(timeout, name="timeout", positive=True)
        parameters = {"chat_id": chat, "action": "typing"}
        if chat != self._chat_id:
            self._record(attempt, SEND_CHAT_ACTION, parameters, TelegramFailure.OTHER_CHAT)
            return TelegramOutcome(failure=TelegramFailure.OTHER_CHAT)
        ended = await self._ended(attempt, SEND_CHAT_ACTION, parameters, bound, poll=False)
        if ended is not None:
            return TelegramOutcome(
                failure=ended.failure, retry_after_seconds=ended.retry_after_seconds
            )
        self._typing += 1
        return TelegramOutcome()

    # --- the far end --------------------------------------------------------

    async def _ended(
        self,
        attempt: str,
        method: str,
        parameters: Mapping[str, object],
        bound: timedelta,
        *,
        poll: bool,
    ) -> _Arranged | None:
        """Decide how this call ends: done (``None``), or the arranged failure.

        Args:
            attempt: The claimed record's id.
            method: The Bot API method.
            parameters: The request body.
            bound: The call's bound.
            poll: Whether a held call's expiry is a poll's, which is always unknown.

        Returns:
            ``None`` for a call Telegram did, or how it ended otherwise.
        """
        if not self._connected:
            self._record(attempt, method, parameters, TelegramFailure.UNAVAILABLE)
            return _Arranged(failure=TelegramFailure.UNAVAILABLE, written=False)
        arranged = self._arranged.popleft() if self._arranged else None
        if arranged is None:
            self._record(attempt, method, parameters, None)
            return None
        if not arranged.hang:
            failure = arranged.failure
            reached = failure is None or _REACHED[failure]
            self._record(attempt, method, parameters, failure, reached=reached)
            return arranged
        index = self._record(attempt, method, parameters, None, reached=arranged.written)
        # Nothing sets the event: the call ends at its bound, or by a cancellation from
        # outside, which leaves through here unconverted (ADR-0060 §1).
        with suppress(TimeoutError):
            async with asyncio.timeout(bound.total_seconds()):
                await asyncio.Event().wait()
        failure = (
            TelegramFailure.UNKNOWN if poll or arranged.written else TelegramFailure.NOT_WRITTEN
        )
        self._complete(index, failure)
        return _Arranged(failure=failure, written=arranged.written)

    def _record(
        self,
        attempt: str,
        method: str,
        parameters: Mapping[str, object],
        failure: TelegramFailure | None,
        *,
        reached: bool | None = None,
    ) -> int:
        """Record a call, returning its index.

        Args:
            attempt: The claimed record's id.
            method: The Bot API method.
            parameters: The request body, copied.
            failure: How it ended, or ``None``.
            reached: Whether the request reached Telegram; by default, whether the
                failure is one decided at Telegram.

        Returns:
            The call's position in :attr:`calls`.
        """
        if reached is None:
            reached = failure is None or _REACHED.get(failure, False)
        self._calls.append(
            TelegramCall(
                attempt=attempt,
                method=method,
                parameters=MappingProxyType(dict(parameters)),
                reached=reached,
                failure=failure,
                origin=self._origin,
            )
        )
        return len(self._calls) - 1

    def _complete(self, index: int, failure: TelegramFailure) -> None:
        """Write a held call's ending onto its record.

        Args:
            index: The call's position.
            failure: How it ended.
        """
        call = self._calls[index]
        self._calls[index] = TelegramCall(
            attempt=call.attempt,
            method=call.method,
            parameters=call.parameters,
            reached=call.reached,
            failure=failure,
            origin=call.origin,
        )

    def _confirm(self, offset: int | None) -> None:
        """Forget every held update ``offset`` confirms, as Telegram does.

        Args:
            offset: The poll's offset, or ``None``, which confirms nothing.
        """
        if offset is not None:
            self._held = [update for update in self._held if update.update_id >= offset]

    def _deliver(self, text: str) -> int:
        """Put a message into the chat under the next id.

        Args:
            text: The message.

        Returns:
            Its id.
        """
        message_id = self._next_message_id
        self._next_message_id += 1
        self._messages.append((message_id, text))
        return message_id


def _checked_attempt(attempt: object) -> str:
    """Refuse a blank attempt, as the production client does."""
    if type(attempt) is not str or not attempt.strip():
        msg = "attempt is the id of the record claimed for this call, a non-blank string"
        raise ValueError(msg)
    return attempt


def _checked_chat(chat_id: object) -> int:
    """Refuse a chat id that is not an exact ``int``, as the production client does."""
    if type(chat_id) is not int:
        msg = "chat_id is an int"
        raise ValueError(msg)
    return chat_id


def _checked_text(text: object) -> str:
    """Refuse a text Telegram could not take as one message, as production does."""
    if type(text) is not str or not text.strip():
        msg = "text is a non-blank string"
        raise ValueError(msg)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        msg = "text has no UTF-8 form, so it cannot be sent"
        raise ValueError(msg) from None
    if telegram_length(text) > TELEGRAM_MESSAGE_LIMIT:
        msg = f"text is longer than one Telegram message ({TELEGRAM_MESSAGE_LIMIT} UTF-16 units)"
        raise ValueError(msg)
    return text


def _checked_duration(value: object, *, name: str, positive: bool) -> timedelta:
    """Refuse a duration no call could be bounded or asked by, as production does."""
    if not isinstance(value, timedelta):
        msg = f"{name} must be a timedelta, got {type(value).__name__}"
        raise ValueError(msg)
    duration = timedelta(
        days=timedelta.days.__get__(value),
        seconds=timedelta.seconds.__get__(value),
        microseconds=timedelta.microseconds.__get__(value),
    )
    if duration < timedelta(0) or (positive and duration == timedelta(0)):
        msg = f"{name} must be {'strictly positive' if positive else 'zero or more'}"
        raise ValueError(msg)
    return duration


__all__ = [
    "DEFAULT_TELEGRAM_CHAT_ID",
    "GET_UPDATES",
    "SEND_CHAT_ACTION",
    "SEND_MESSAGE",
    "TELEGRAM_DIRECT_ORIGIN",
    "FakeTelegramBotClient",
    "TelegramCall",
]
