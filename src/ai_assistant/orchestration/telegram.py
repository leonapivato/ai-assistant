"""The Telegram line's spoke in the hub: its reader and its writer (ADR-0323).

The line is a private Telegram chat between the owner's account and a bot the owner
connected (§2:1). Its spoke is in the hub (§2:2): a **reader**, its sensor, which polls
the bot for new messages and brings them in as a push, and a **writer**, its actuator,
which writes the assistant's messages into the one chat the settings name. Both reach
Telegram only through :class:`~ai_assistant.core.protocols.TelegramBotClient`, whose one
production implementation is in ``ai_assistant.tools.egress`` (§11:1), and keep the
line's bookkeeping on :class:`~ai_assistant.core.protocols.TelegramIntakeRecord`. They
copy the hub chat's :class:`~ai_assistant.orchestration.chat.ChatReader` and
:class:`~ai_assistant.orchestration.chat.ChatWriter` (ADR-0293), with what a medium
held by another party changes.

**What comes in** (§5). Each poll is claimed on the intake record first, which hands it
the offset it is to send (§13:2, §5:6). Of the updates it returns, a text message or a
forward from the configured account, in its private chat with the bot, is input
(§5:1); a non-text message from that account is answered by rule with
:data:`NON_TEXT_LINE` and starts nothing (§5:3); and anything else — another account,
another chat, an update carrying no message — is not input: it starts nothing, is
recorded nowhere and is not answered (§5:2). An update the intake record already holds
was dealt with and is passed over, so a duplicate fetch starts no second activation and
sends no second fixed line (§5:9).

**One activation at a time, and polling while it runs** (ADR-0332 §2:3-§2:4, §8:7-§8:8,
amending ADR-0323 §5:5 and §5:7). The reader is one loop: it polls and deals with what
came back. Where nothing is running, the first message starts the start wait
(``telegram_start_wait``, ADR-0332 §5:3), and once it has passed the reader takes in
everything that has arrived **together, as one input**, each message keeping the time
Telegram gave it (§5:4), and runs its activation beside the loop. While it runs, the
loop keeps polling: a message from the same author **joins it** where ADR-0332 §3:3
allows: the engine's join takes it pending the reader's marking of it, taken in by
that activation, which commits nothing until the marking has landed (§3:18). One that
does not join waits in Telegram,
unconfirmed, and so does everything after it, until the activation ends and the next
poll takes them in. Those polls are paced
(:data:`RUNNING_POLL_PACE`), so updates left waiting never make the reader poll in a
loop.

**The line's** ``/stop`` (ADR-0332 §8). A message from the configured account in its
chat, not forwarded, whose whole text is ``/stop`` and which Telegram marked as that
``bot_command`` (:func:`is_stop_command`), is no input: the reader records it answered
on the intake record (``claim_reply``), then stops the activation running from the
chat, as ``stop_activation`` does, and answers by rule, :data:`STOPPED_LINE` or
:data:`NOTHING_RUNNING_LINE`. It acts on one as soon as a poll returns it, which is only
while it is within the page Telegram returns past the confirmed offset (§8:4).

**The confirm rule** (§5:6). The reader tells the intake record which updates are dealt
with — input once its activation is admitted and has marked it taken in, a non-text
message once its fixed reply is claimed, an update that is not input once it is seen —
and the record hands the next poll the offset that confirms them. An update not dealt
with, as one whose activation could not mark it, is not confirmed, and Telegram hands
it back.

**Restarts** (§5:10, §6:10). The activation takes its updates in as its first step once
its episode is written, as the chat's does (ADR-0293 §6:8): so after a restart, updates
an interrupted activation took in are not taken in again, and updates never taken in
are taken in as usual. A joined update is marked so too, before the activation can
act on it (ADR-0332 §3:18). Before its first poll the reader looks at the chat's last
activation, by its newest episode, and where the restart cut it off — its episode
closed *interrupted*, and not by the user's stop — the writer sends
:data:`INTERRUPTED_LINE` once, by rule.

**The window** (§10). A bot cannot read its chat's history, so the kind declares an
episode window: the recent episodes on the line's channel and place, each linked to
the activation it records. The reader builds it as the chat's window is shaped
(:class:`~ai_assistant.orchestration.understanding.TranscriptWindow`): each episode's
messages, the user's from its recorded trigger and the assistant's from its message
effect records, at their Telegram message ids; and a reply brings in the message it
quotes, with its author (§4:12), linked to the activation that wrote it where the bot
did (§4:13).

**What goes out** (§6). The writer writes an activation's message only after it is
claimed on its effect record (§11:3), only to the configured chat (§6:1), as plain text
(§6:6), split into parts no longer than Telegram's limit at paragraph breaks, then line
breaks, then between words, and at the limit only where a run has no break
(:func:`split_message`). It retries a part only where Telegram did not get it or said
it was not sent and a retry can succeed (§6:3), never one whose outcome is unknown
(§6:4), and records every other refusal *not done* (§6:5). While an activation runs it
renews the typing indicator, each renewal claimed on the intake record (§6:7, §13:2).

**It logs code-owned reasons only.** No line, record or error here carries a message's
text, and the bot's token never reaches this module: the client binds it (§11:8-§11:9).

Nothing concrete is imported: the client, the intake record and the memory store arrive
by injection and are seen only through their Protocols (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field, replace
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import (
    MemoryStoreError,
    TelegramIntakeRecordError,
    TraceStoreError,
)
from ai_assistant.core.types import (
    TELEGRAM_MESSAGE_LIMIT,
    ApprovalGiver,
    ChannelIdentity,
    ClaimedAuthor,
    EpisodicMemory,
    MessageAuthor,
    ProcessingReason,
    ProcessingStatus,
    RecordedInputMessage,
    TelegramFailure,
    TelegramOutcome,
    TelegramPollOutcome,
    ToolOutcome,
    telegram_length,
)
from ai_assistant.orchestration.channel_kinds import (
    Audience,
    ChannelKind,
    Direction,
    Reach,
    WindowSource,
    place_of,
)
from ai_assistant.orchestration.chat import CHAT_WINDOW_SIZE, COULDNT_FINISH
from ai_assistant.orchestration.defects import is_defect, log_defect
from ai_assistant.orchestration.joining import JoinCheck, JoiningInput, input_standing
from ai_assistant.orchestration.phase_path import Delivery, Fitted
from ai_assistant.orchestration.understanding import (
    AskedIn,
    LineMessage,
    TranscriptWindow,
    WrittenBy,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import MemoryStore, TelegramBotClient, TelegramIntakeRecord
    from ai_assistant.core.types import (
        ChannelEpisodePage,
        TelegramMessage,
        TelegramSendOutcome,
        TelegramUpdate,
    )
    from ai_assistant.orchestration.joining import PendingJoin
    from ai_assistant.orchestration.phase_path import PlaceWriter

__all__ = [
    "DEFAULT_TELEGRAM_START_WAIT",
    "INTERRUPTED_LINE",
    "LINE_GIVER",
    "NON_TEXT_LINE",
    "NOTHING_RUNNING_LINE",
    "RUNNING_POLL_PACE",
    "STOPPED_LINE",
    "STOP_COMMAND",
    "TELEGRAM",
    "TELEGRAM_CHANNEL_TYPE",
    "TELEGRAM_DESCRIPTION",
    "TelegramInput",
    "TelegramLineSeams",
    "TelegramReader",
    "TelegramWriter",
    "is_stop_command",
    "line_channel",
    "split_message",
]

_log = structlog.get_logger(__name__)

#: The line's channel type (ADR-0323 §2, §15's first row).
TELEGRAM_CHANNEL_TYPE: Final = "telegram"

#: The fixed line a non-text message from the owner is answered with (§5:3).
NON_TEXT_LINE: Final = "I can only read text here for now."

#: The line's one stop command, as its whole text and its ``bot_command`` (ADR-0332 §8:1).
STOP_COMMAND: Final = "/stop"

#: The fixed line a stop command is answered with where it stopped an activation (§8:5).
STOPPED_LINE: Final = "Stopped."

#: The fixed line a stop command is answered with where nothing was running (§8:5).
NOTHING_RUNNING_LINE: Final = "Nothing was running."

#: ``Settings.telegram_start_wait``'s default (ADR-0332 §6:4), which the line's seams
#: take where the composition root passes none.
DEFAULT_TELEGRAM_START_WAIT: Final = timedelta(seconds=2)

#: The rest between two polls while an activation runs and an update is left waiting, or
#: handed to the activation and not yet marked: those come back in every poll at once, so
#: the rest is what keeps the reader from polling in a loop (ADR-0332 §8:8). It ends early
#: when the activation does.
RUNNING_POLL_PACE: Final = timedelta(seconds=1)

#: The fixed message sent after a restart cut the chat's last activation off (§6:10).
INTERRUPTED_LINE: Final = (
    "I was interrupted before I could answer. Send it again if you still need it."
)

#: The kind's description, which planning is shown with the place (§9's description
#: row, ADR-0292 §8:1). It tells planning the chat shows plain text (§6:6).
TELEGRAM_DESCRIPTION: Final = (
    "The user's private Telegram chat with their assistant, on their phone and any "
    "Telegram app signed into their account. It shows plain text only: formatting such "
    "as Markdown is not rendered. The user's own messages here carry their authority, "
    "and a forward is someone else's words. A message you write is sent into this chat "
    "for the user to read, and a reply, a question or a notice is expected."
)

#: Who a yes on the line is given by: the user, through it (§4:9).
LINE_GIVER: Final = ApprovalGiver.USER_THROUGH_TELEGRAM

#: ADR-0323 §9: what the Telegram kind declares, each row in the ADR-0292 clause its
#: table's first column names. The first kind declared in code, so its shape is
#: :class:`~ai_assistant.orchestration.channel_kinds.ChannelKind`'s.
TELEGRAM: Final = ChannelKind(
    channel_type=TELEGRAM_CHANNEL_TYPE,
    channels=(
        "one for each connected bot the line's settings name, created by connecting it "
        "and naming it"
    ),
    direction=Direction.IN_AND_OUT,
    reach=Reach.PUSHES,
    input=(
        "text messages and forwards from the configured account, in its private chat with the bot"
    ),
    push_filter=None,
    authors=(
        "the configured account, not forwarding, is the user, established; every other "
        "author is claimed"
    ),
    places="each private chat with the bot, keyed by its chat id",
    window=WindowSource.EPISODES,
    window_items=CHAT_WINDOW_SIZE,
    sent="Telegram accepted it and returned its message id",
    description=TELEGRAM_DESCRIPTION,
    text_only=True,
    message_limit=TELEGRAM_MESSAGE_LIMIT,
    audience=Audience.PRIVATE,
    approval_giver=LINE_GIVER,
)

#: How often the typing indicator is renewed while an activation runs. Telegram shows
#: it for about five seconds, so a renewal comes before it lapses (§6:7).
TYPING_RENEWAL: Final = timedelta(seconds=4)

#: How many times one message part, or one fixed line, is sent at most, the first time
#: included, where every failure was one §6:3 lets the writer retry.
SEND_ATTEMPTS: Final = 3

#: The longest wait before a retry, whatever Telegram asked: a longer rate limit is not
#: waited out inside an activation, and the part is recorded *not done*.
RETRY_WAIT_CAP: Final = timedelta(seconds=10)

#: The wait before retrying a request that was never written (§6:3).
NOT_WRITTEN_WAIT: Final = timedelta(seconds=1)

#: How long the reader rests after a poll or a batch that failed, before it polls again.
POLL_BACKOFF: Final = timedelta(seconds=5)

#: How long the reader rests while the line is unavailable — its connection not active,
#: or its token gone — before it polls again (§3:3, §3:7).
UNAVAILABLE_BACKOFF: Final = timedelta(seconds=60)

#: The episodes the window reads, newest, before its messages are cut to its size
#: (§10, §9's window row).
_WINDOW_EPISODES: Final = CHAT_WINDOW_SIZE

#: What separates two waiting messages taken in as one input (§5:5), as the chat's.
_INPUT_SEPARATOR: Final = "\n\n"

#: The breaks a message is split at, coarsest first (§6:6).
_BREAKS: Final = ("\n\n", "\n", " ")

#: A *not done* message's reason, as its effect record names it (§6:5).
_NOT_SENT: Final = "telegram_did_not_send"

#: A message for a chat other than the line's, refused before any byte (§6:1).
_OTHER_CHAT: Final = "telegram_other_chat"


def line_channel(reference: str, chat_id: int) -> ChannelIdentity:
    """The line's channel identity: its connection's reference, with its chat (§2:3).

    Read as (that bot's channel, that chat), so every read of the place, its window
    and its message positions included, is keyed by both: a changed account, or a new
    bot connected for the same account, is a new place.
    """
    return ChannelIdentity(channel_type=TELEGRAM_CHANNEL_TYPE, instance_id=f"{reference}/{chat_id}")


def split_message(text: str, *, limit: int = TELEGRAM_MESSAGE_LIMIT) -> tuple[str, ...]:
    """``text`` as consecutive parts, none longer than ``limit``, holding it in order (§6:6).

    Split at paragraph breaks; a paragraph longer than a part at line breaks, then
    between words; and at the limit only where a run of text has no break. Length is
    :func:`~ai_assistant.core.types.telegram_length`'s, UTF-16 code units, which is
    never fewer than the characters a part holds. A break a split falls at is not
    carried into either part, and a part that would be blank is not sent.

    Args:
        text: The message.
        limit: The longest part, in UTF-16 code units; Telegram's by default.

    Returns:
        The parts, in order: ``(text,)`` where it fits whole.

    Raises:
        ValueError: If ``limit`` is below 2, which no character outside the Basic
            Multilingual Plane fits.
    """
    if limit < 2:  # noqa: PLR2004 — one character outside the Basic Multilingual Plane
        msg = "a part holds at least one character of any plane"
        raise ValueError(msg)
    return tuple(part for part in _split(text, limit, 0) if part.strip())


def _split(text: str, limit: int, level: int) -> list[str]:
    """``text`` split at ``_BREAKS[level]`` and finer, packed into parts within ``limit``."""
    if telegram_length(text) <= limit:
        return [text]
    if level == len(_BREAKS):
        return _cut(text, limit)
    separator = _BREAKS[level]
    parts: list[str] = []
    current: str | None = None
    for chunk in text.split(separator):
        if not chunk:
            continue  # a run of breaks is one break: nothing between them is sent
        if telegram_length(chunk) > limit:
            if current is not None:
                parts.append(current)
                current = None
            parts.extend(_split(chunk, limit, level + 1))
            continue
        joined = chunk if current is None else current + separator + chunk
        if telegram_length(joined) <= limit:
            current = joined
        else:
            if current is not None:
                parts.append(current)
            current = chunk
    if current is not None:
        parts.append(current)
    return parts


def _cut(text: str, limit: int) -> list[str]:
    """A run with no break, cut at the limit, never inside a character."""
    parts: list[str] = []
    current: list[str] = []
    used = 0
    for character in text:
        width = telegram_length(character)
        if used + width > limit:
            parts.append("".join(current))
            current, used = [], 0
        current.append(character)
        used += width
    if current:
        parts.append("".join(current))
    return parts


@dataclass(frozen=True, slots=True)
class TelegramLineSeams:
    """What the composition root hands the engine for the line, where it is configured.

    Built only while both of the line's settings are set (§3:2-§3:3); the client then
    refuses every call while the connection they name is not active (§3:7).

    Attributes:
        client: The bot, through its contract.
        intake: The line's intake record and its own call records.
        reference: ``Settings.telegram_connection``, which keys the line's channel.
        poll_wait: ``Settings.telegram_poll_wait``.
        poll_bound: ``Settings.telegram_poll_bound``, strictly above the wait.
        send_bound: ``Settings.telegram_send_bound``, one send's or indicator's bound.
        start_wait: ``Settings.telegram_start_wait`` (ADR-0332 §5:3), strictly
            positive: how long after the first message, where nothing is running, the
            reader waits before it takes in what has arrived.

    Raises:
        ValueError: If ``start_wait`` is not strictly positive.
    """

    client: TelegramBotClient
    intake: TelegramIntakeRecord
    reference: str
    poll_wait: timedelta
    poll_bound: timedelta
    send_bound: timedelta
    start_wait: timedelta = DEFAULT_TELEGRAM_START_WAIT

    def __post_init__(self) -> None:
        """The start wait is strictly positive (ADR-0332 §6:4)."""
        if self.start_wait <= timedelta(0):
            msg = "telegram_start_wait is strictly positive (ADR-0332 §6:4)"
            raise ValueError(msg)

    @property
    def channel(self) -> ChannelIdentity:
        """The line's channel, keyed by its connection and its one chat (§2:3)."""
        return line_channel(self.reference, self.client.chat_id)


@dataclass(frozen=True, slots=True)
class TelegramInput:
    """What the reader brings in for one activation (§5).

    Attributes:
        channel: The line's channel, whose place the reply is written into (§6:1).
        activation_id: The id the activation is admitted with, which the updates are
            marked taken in by (§5:8).
        updates: The updates taken in, ascending: each a text message or a forward
            from the configured account.
        window: The line's episode window, brought in with the input (§10).
    """

    channel: ChannelIdentity
    activation_id: str
    updates: tuple[TelegramUpdate, ...]
    window: TranscriptWindow

    @property
    def messages(self) -> tuple[TelegramMessage, ...]:
        """The input's messages, in the order Telegram gave them."""
        return tuple(one.message for one in self.updates if one.message is not None)

    @property
    def text(self) -> str:
        """The input: the messages' text, in the order they were sent (§5:5)."""
        return _INPUT_SEPARATOR.join(one.text or "" for one in self.messages)

    @property
    def update_ids(self) -> tuple[int, ...]:
        """The updates' ids, which the intake record marks."""
        return tuple(one.update_id for one in self.updates)

    @property
    def recorded(self) -> tuple[RecordedInputMessage, ...]:
        """Each message as the trigger records it: dated, a forward with its sender (§5:4)."""
        return _recorded(self.messages)

    def narrowed(self, update_ids: Sequence[int]) -> TelegramInput:
        """The input as its activation took it in: only the updates ``update_ids`` name."""
        kept = frozenset(update_ids)
        updates = tuple(one for one in self.updates if one.update_id in kept)
        positions = {one.message.message_id for one in updates if one.message is not None}
        window = replace(
            self.window,
            input_messages=tuple(
                one for one in self.window.input_messages if one.position in positions
            ),
        )
        return replace(self, updates=updates, window=window)


def _recorded(messages: Sequence[TelegramMessage]) -> tuple[RecordedInputMessage, ...]:
    """Each message as an episode records it: dated, a forward with its sender (§5:4)."""
    return tuple(
        RecordedInputMessage(
            text=one.text or "",
            sent_at=one.sent_at,
            position=one.message_id,
            forwarded_from=None
            if one.forward_origin is None
            else ClaimedAuthor(
                name=one.forward_origin.name, account_id=one.forward_origin.account_id
            ),
        )
        for one in messages
    )


def is_stop_command(message: TelegramMessage) -> bool:
    """Whether a message from the configured account in its chat is a stop (ADR-0332 §8:1).

    Not forwarded, its whole text :data:`STOP_COMMAND`, and its ``command`` that too:
    Telegram marked the text as a ``bot_command`` entity at its first character. Nothing
    else is one (§8:2): a forward, ``/stop@`` followed by a name, ``/stop`` without the
    entity, and text that only mentions it. That the message is the configured
    account's, in its private chat, is the reader's to have checked first (§5:1).
    """
    return (
        message.forward_origin is None
        and message.text == STOP_COMMAND
        and message.command == STOP_COMMAND
    )


async def _finished[O: TelegramOutcome](
    intake: TelegramIntakeRecord,
    attempt: str,
    call: Callable[[], Awaitable[O]],
) -> O:
    """Make one claimed call and finish its record with what came of it (§13:2).

    A call cancelled from outside may have reached Telegram, so its record is finished
    *unknown* before the cancellation goes on, so it is never left open by a shutdown
    (T2's ordering note). **The finish is awaited to its end whatever else is
    cancelled meanwhile**: a shutdown's drain cancels what is left after its budget,
    and a finish abandoned then would still be writing when the store is closed
    (ADR-0042 §2), so a further cancellation is held until the write has returned and
    the cancellation then goes on. A record that cannot be finished stays claimed with
    no outcome, which is never resolved by guessing; the call's outcome is still
    returned.

    Raises:
        CancelledError: Re-raised once the record is finished.
    """
    try:
        outcome = await call()
    except asyncio.CancelledError:
        finishing = asyncio.ensure_future(
            intake.finish(attempt, TelegramOutcome(failure=TelegramFailure.UNKNOWN))
        )
        while not finishing.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(finishing)
        if not finishing.cancelled() and finishing.exception() is not None:
            _log.warning("telegram_call_unfinished", stage="line", reason="store_failed")
        raise
    try:
        await intake.finish(attempt, outcome)
    except TelegramIntakeRecordError:
        _log.warning("telegram_call_unfinished", stage="line", reason="store_failed")
    return outcome


def _wait_before_retry(outcome: TelegramOutcome) -> float | None:
    """How long to wait before §6:3's retry, or ``None`` where there is none."""
    if outcome.failure is None or not outcome.failure.retryable:
        return None
    if outcome.failure is TelegramFailure.RATE_LIMITED:
        asked = outcome.retry_after_seconds
        if asked is not None and asked > RETRY_WAIT_CAP.total_seconds():
            return None
        return float(asked or NOT_WRITTEN_WAIT.total_seconds())
    return NOT_WRITTEN_WAIT.total_seconds()


class TelegramWriter:
    """The line's writer, its actuator: *send a message* into the one chat (§6, §9:2).

    It writes an activation's messages (:meth:`for_place`), the fixed lines the line
    sends by rule (:meth:`fixed`), and the typing indicator (:meth:`typing`). Every call
    goes to the client's one chat, which is the settings' (§6:1), and the channel's
    rules — text only, and only that chat — hold here whatever a model produced (§9:2).
    """

    def __init__(
        self,
        *,
        client: TelegramBotClient,
        intake: TelegramIntakeRecord,
        channel: ChannelIdentity,
        send_bound: timedelta,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Wire the writer to the bot, the line's records and its one place.

        Args:
            client: The bot.
            intake: Where a fixed line's and a typing indicator's calls are claimed.
            channel: The line's channel, whose place is the one chat (§2:3).
            send_bound: The bound on one send or indicator (§11:12).
            sleep: How the writer waits before a retry and between renewals.
        """
        self._client = client
        self._intake = intake
        self._channel = channel
        self._send_bound = send_bound
        self._sleep = sleep

    def for_place(self, channel: ChannelIdentity) -> PlaceWriter:
        """The writer of an activation's messages into ``channel``'s place (§6:1).

        A place other than the line's is refused at :meth:`deliver` time, before any
        byte is sent: the activation's place is its input's (ADR-0306 §4:7), and the
        line writes to the chat its settings name and nowhere else.
        """
        return _PlaceWriter(self, channel)

    async def deliver(self, channel: ChannelIdentity, text: str, *, effect_id: str) -> Delivery:
        """Send one activation message, claimed under ``effect_id``, in parts (§6:2-§6:6).

        A message is *sent* when Telegram accepted every part and returned its id: the
        effect record's position is the last part's, which a reply to the message's
        end, where its question is, quotes (§6:2, §4:13). A message cut short between
        parts is never recorded done: it is *unknown* where the part that failed may
        have reached Telegram, and *not done* otherwise, and what the chat holds of it
        is what the episode records as sent. The whole text is sent, however long: the
        line splits a message and cuts none (§6:6).

        Returns:
            What came of it.
        """
        if channel != self._channel:
            _log.warning("telegram_message_unsent", stage="writer", reason="other_chat")
            return Delivery(ToolOutcome.FAILED, reason=_OTHER_CHAT)
        parts = split_message(text)
        sent: list[str] = []
        last: int | None = None
        for part in parts:
            outcome = await self._send(part, attempt=effect_id)
            if outcome is None or not outcome.done:
                return _cut_short(outcome, sent, len(parts))
            sent.append(part)
            last = outcome.message_id
        if last is None:
            return Delivery(ToolOutcome.FAILED, reason=_NOT_SENT)
        return Delivery(ToolOutcome.SUCCEEDED, position=last, written=text)

    async def _send(self, text: str, *, attempt: str) -> TelegramSendOutcome | None:
        """Send one part, retrying only as §6:3 allows; ``None`` where it cannot be sent."""
        outcome: TelegramSendOutcome | None = None
        for tried in range(1, SEND_ATTEMPTS + 1):
            try:
                outcome = await self._client.send(
                    attempt=attempt,
                    chat_id=self._client.chat_id,
                    text=text,
                    timeout=self._send_bound,
                )
            except ValueError:
                # Refused before anything was read: nothing reached Telegram.
                _log.warning("telegram_message_unsent", stage="writer", reason="unsendable")
                return None
            wait = _wait_before_retry(outcome)
            if wait is None or tried == SEND_ATTEMPTS:
                return outcome
            await self._sleep(wait)
        return outcome

    async def fixed(self, claim: Callable[[], Awaitable[str | None]], text: str) -> bool:
        """Send one fixed line by rule, each try claimed through ``claim`` (§13:2).

        ``claim`` is the intake record's claim for the line — a non-text message's
        reply, or the message after a restart — which answers ``None`` where no line
        may be sent: one already sent, possibly sent, or refused for good. A try that
        came back with a failure §6:3 lets the writer retry is claimed again, which is
        the retry, as many times as :data:`SEND_ATTEMPTS` allows.

        Returns:
            Whether the line was claimed at least once, so the intake record holds it.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written for the claim.
        """
        claimed = False
        for tried in range(1, SEND_ATTEMPTS + 1):
            attempt = await claim()
            if attempt is None:
                return claimed
            claimed = True
            outcome = await _finished(
                self._intake,
                attempt,
                partial(
                    self._client.send,
                    attempt=attempt,
                    chat_id=self._client.chat_id,
                    text=text,
                    timeout=self._send_bound,
                ),
            )
            wait = _wait_before_retry(outcome)
            if wait is None or tried == SEND_ATTEMPTS:
                if not outcome.done:
                    _log.info(
                        "telegram_fixed_line_unsent", stage="writer", reason=_failure(outcome)
                    )
                return claimed
            await self._sleep(wait)
        return claimed

    async def typing(self, activation_id: str) -> None:
        """Renew the typing indicator for ``activation_id`` until cancelled (§6:7).

        Each renewal is claimed on the intake record and finished with its outcome; a
        renewal cut off by the cancellation is finished *unknown*. It shows the
        assistant's state to the user's end and writes nothing into the chat
        (ADR-0292 §11:7). A record that cannot be claimed ends the renewals: nothing is
        sent unclaimed (§13:2).
        """
        while True:
            try:
                attempt = await self._intake.claim_typing(activation_id)
            except TelegramIntakeRecordError:
                _log.warning("telegram_typing_stopped", stage="writer", reason="store_failed")
                return
            await _finished(
                self._intake,
                attempt,
                partial(
                    self._client.show_typing,
                    attempt=attempt,
                    chat_id=self._client.chat_id,
                    timeout=self._send_bound,
                ),
            )
            await self._sleep(TYPING_RENEWAL.total_seconds())


def _cut_short(outcome: TelegramSendOutcome | None, sent: Sequence[str], parts: int) -> Delivery:
    """A message whose part was not sent: unknown where it may have been, else not done."""
    written = _INPUT_SEPARATOR.join(sent) if sent else None
    if outcome is not None and outcome.failure is TelegramFailure.UNKNOWN:
        _log.info("telegram_message_unknown", stage="writer", parts_sent=len(sent), parts=parts)
        return Delivery(ToolOutcome.INDETERMINATE, written=written)
    reason = (
        _NOT_SENT
        if outcome is None or outcome.failure is None
        else f"{_NOT_SENT}:{outcome.failure.value}"
    )
    _log.info("telegram_message_unsent", stage="writer", parts_sent=len(sent), parts=parts)
    return Delivery(ToolOutcome.FAILED, reason=reason, written=written)


@dataclass(frozen=True, slots=True)
class _PlaceWriter:
    """The writer of one place's activation messages, as the phases are handed it."""

    writer: TelegramWriter
    channel: ChannelIdentity

    def fitted(self, text: str) -> Fitted:
        """The text, whole: a longer one is split into parts, never cut (§6:6)."""
        return Fitted(text=text)

    async def deliver(self, fitted: Fitted, *, effect_id: str) -> Delivery:
        """:meth:`TelegramWriter.deliver`, into this place."""
        return await self.writer.deliver(self.channel, fitted.text, effect_id=effect_id)


@dataclass(slots=True)
class _Batch:
    """What one poll handed back, as the reader deals with it (§5:6)."""

    ids: list[int]
    dealt: set[int] = field(default_factory=set)
    inputs: list[TelegramUpdate] = field(default_factory=list)

    @property
    def through(self) -> int | None:
        """The highest id every update up to which is dealt with, or ``None``."""
        through: int | None = None
        for one in self.ids:
            if one not in self.dealt:
                break
            through = one
        return through


@dataclass(slots=True)
class _Turn:
    """The activation the reader runs beside its loop, while it runs (ADR-0332 §8:7).

    Attributes:
        activation_id: The activation.
        task: What runs it: the activation, then the reader's account of what it marked.
        handed: The updates handed to it, its trigger's and each joined one's, which no
            later poll hands anything again while it runs.
        waited: Whether an input did not join it, after which nothing joins it, since no
            input joins past one that is waiting (§3:3).
    """

    activation_id: str
    task: asyncio.Future[None]
    handed: set[int]
    waited: bool = False


class TelegramReader:
    """The line's reader, its sensor: one loop that polls, deals and polls again (§5).

    :meth:`run` is the line's long-running task, which the engine starts with the hub
    and stops with it: :meth:`close` ends a poll or a rest at once, and an activation
    running then is drained as any other, the loop ending once it has.
    """

    def __init__(  # noqa: PLR0913 — the bot and its records, the episodes, how an activation runs, joins and stops, the engine's two seams, the writers' links, and two bounds
        self,
        *,
        seams: TelegramLineSeams,
        writer: TelegramWriter,
        memory: MemoryStore,
        activate: Callable[[TelegramInput], Awaitable[bool]],
        join: Callable[[JoiningInput], tuple[JoinCheck, PendingJoin | None]],
        stop: Callable[[str], Awaitable[bool]],
        closing: Callable[[], bool],
        mint: Callable[[], str],
        written: Callable[
            [str, Sequence[str], Sequence[int] | None], Awaitable[Mapping[int, WrittenBy]]
        ]
        | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Wire the reader.

        Args:
            seams: The bot, the line's records, its channel and its bounds.
            writer: The line's writer, which answers by rule and shows typing.
            memory: The store the window's episodes are read from (§10).
            activate: Admits one activation for an input, which marks its updates taken
                in (:meth:`take_in`) and writes its reply. It returns whether anything
                was marked, once the activation has ended, or raises
                ``CancelledError`` where a shutdown cancelled it.
            join: The engine's join (ADR-0332 §3:3, §3:6, §3:18): it takes an input
                into the activation running on the line's chat where that activation
                may take it, pending the reader's marking of its updates taken in by
                that activation, which the reader then confirms or withdraws.
            stop: Stops a running activation as ``stop_activation`` does (ADR-0332
                §8:4), and answers whether it stopped one.
            closing: Whether the engine has begun shutting down, after which nothing
                new is taken in.
            mint: The activation id the next input is admitted with.
            written: Reads which activation wrote each message in a place, by its
                effect record (ADR-0303 §7:1): the phases' ``written_in``. ``None``
                links no assistant message, and the window then holds only the user's.
            sleep: How the reader rests between polls.
        """
        self._client = seams.client
        self._intake = seams.intake
        self._channel = seams.channel
        self._place = place_of(seams.channel)
        self._poll_wait = seams.poll_wait
        self._poll_bound = seams.poll_bound
        self._writer = writer
        self._memory = memory
        self._activate = activate
        self._closing = closing
        self._mint = mint
        self._written = written
        self._sleep = sleep
        self._join = join
        self._stop = stop
        self._start_wait = seams.start_wait
        self._task: asyncio.Task[object] | None = None
        # Whether the loop is polling or resting, which a close ends at once; an
        # activation it runs is the drain's.
        self._idle = False
        self._stopped = False
        # What each running activation marked taken in, by its id, until it ends.
        self._marked: dict[str, list[int]] = {}
        # The activation the reader has admitted for an input, until it ends.
        self._current: str | None = None
        # ADR-0332 §8:7: the activation running beside the loop, until it ends.
        self._turn: _Turn | None = None
        # ADR-0332 §5:3: the start wait has passed for the input waiting, so the next
        # poll that returns it takes it in. Also set when an activation ends with input
        # left waiting, which arrived while it ran, so it is taken in at once (§5:5).
        self._started = False

    @property
    def channel(self) -> ChannelIdentity:
        """The line's channel (§2:3)."""
        return self._channel

    @property
    def working(self) -> str | None:
        """The activation the reader has an input in for, until it ends."""
        return self._current

    def close(self) -> None:
        """Stop the loop: a poll or a rest in progress ends at once (§11:11).

        A poll cut off so is finished *unknown* and takes nothing in; an activation
        running beside the loop is left to finish or be cancelled by the engine's drain,
        and the loop ends once it has, without polling again.
        """
        self._stopped = True
        if self._idle and self._task is not None:
            self._task.cancel()

    async def run(self) -> None:
        """The line's long-running task: restart's message, then poll until closed.

        Raises:
            CancelledError: Where :meth:`close` or a shutdown cancelled it.
        """
        self._task = asyncio.current_task()
        try:
            await self._after_restart()
            while not self._done():
                await self._once()
        finally:
            # An activation running beside the loop is the drain's: the loop ends once it
            # has, and a further cancellation reaches it.
            turn = self._turn
            if turn is not None:
                await asyncio.gather(turn.task, return_exceptions=True)

    async def _once(self) -> None:
        """One poll, what it returned dealt with, and the rest before the next."""
        try:
            outcome = await self._poll()
            if outcome.done:
                wait = await self._deal_with(outcome.updates)
            else:
                wait = _poll_backoff(outcome)
        except asyncio.CancelledError:
            raise
        except TelegramIntakeRecordError, MemoryStoreError:
            _log.warning("telegram_read_failed", stage="reader", reason="store_failed")
            wait = POLL_BACKOFF
        except Exception as exc:  # the line runs as long as the hub: a defect is logged
            if is_defect(exc):
                log_defect("telegram_read_failed", exc, stage="reader", activation_id=None)
            else:
                _log.warning("telegram_read_failed", stage="reader", reason="failed")
            wait = POLL_BACKOFF
        if wait is not None and not self._done():
            await self._idly(self._rest(wait))

    async def _rest(self, wait: timedelta) -> None:
        """Rest before the next poll; a pace while an activation runs ends with it (§8:8)."""
        turn = self._turn
        resting = asyncio.ensure_future(self._sleep(wait.total_seconds()))
        try:
            if turn is None or wait != RUNNING_POLL_PACE:
                await resting
            else:
                await asyncio.wait((resting, turn.task), return_when=asyncio.FIRST_COMPLETED)
        finally:
            resting.cancel()
            await asyncio.gather(resting, return_exceptions=True)

    def _done(self) -> bool:
        return self._stopped or self._closing()

    async def _idly[T](self, work: Awaitable[T]) -> T:
        """Await ``work`` as a wait :meth:`close` cuts short by cancelling the loop."""
        self._idle = True
        try:
            return await work
        finally:
            self._idle = False

    async def _poll(self) -> TelegramPollOutcome:
        """One claimed poll, sending the offset the intake record owes (§5:6, §11:10).

        Only the call itself is a wait :meth:`close` cuts short: the claim and the
        finish are the record's, and a poll cut off is finished *unknown* (§11:11). A
        close that came while the poll was being claimed sends nothing, and the claim
        is finished as a request never written.
        """
        claim = await self._intake.claim_poll()

        async def call() -> TelegramPollOutcome:
            if self._done():
                return TelegramPollOutcome(failure=TelegramFailure.NOT_WRITTEN)
            return await self._idly(
                self._client.poll(
                    attempt=claim.attempt,
                    offset=claim.offset,
                    wait=self._poll_wait,
                    timeout=self._poll_bound,
                )
            )

        outcome = await _finished(self._intake, claim.attempt, call)
        if not outcome.done:
            _log.info("telegram_poll_not_done", stage="reader", reason=_failure(outcome))
        return outcome

    async def _deal_with(self, updates: Sequence[TelegramUpdate]) -> timedelta | None:
        """Deal with what one poll handed back, then say what is dealt with (§5:6).

        In the order Telegram gave them (:meth:`_scan`), and then the input left: where
        an activation runs, it joins it or waits (:meth:`_joined`), and where none runs it
        is taken in once the start wait has passed (:meth:`_begin`). An update handed to
        the running activation and not yet marked is neither dealt with nor input, and
        is dealt with once a later poll finds it taken in.

        Returns:
            The rest before the next poll: none where every update was dealt with, or
            where the activation ended meanwhile and what waited is to be taken in; the
            start wait where it has just begun; the pace while an activation runs; and
            the backoff otherwise.

        Raises:
            TelegramIntakeRecordError: If the record cannot be read or written.
        """
        batch = _Batch(ids=[one.update_id for one in updates])
        if not batch.ids:
            return None
        turn = self._turn
        pending = await self._scan(updates, turn, batch)
        begun: bool | None = None
        if pending and turn is not None:
            batch.dealt.update(await self._joined(turn, pending))
        elif pending and not self._closing():
            begun = await self._begin(pending)
        through = batch.through
        if through is not None:
            await self._intake.confirm_through(through)
        if through == batch.ids[-1] or begun is False:
            # All dealt with; or just taken in, its updates dealt with once a poll
            # finds them marked, so the next poll is at once.
            return None
        if begun:
            return self._start_wait
        if self._turn is not None:
            return RUNNING_POLL_PACE
        return None if turn is not None else POLL_BACKOFF

    async def _scan(
        self, updates: Sequence[TelegramUpdate], turn: _Turn | None, batch: _Batch
    ) -> list[TelegramUpdate]:
        """Deal with each update in order, but the input; answer the input left after.

        An update held already, or not input, is dealt with; a stop command is acted on
        (:meth:`_stopping`), once the input before it has joined or not (ADR-0332 §8:4),
        so an input that joined before the stop is the stopped activation's; and a
        non-text message is answered by rule (§5:3).

        Returns:
            The input after the last stop command, in order.
        """
        recorded = await self._intake.recorded(batch.ids)
        pending: list[TelegramUpdate] = []
        for update in updates:
            if update.update_id in recorded:
                batch.dealt.add(update.update_id)  # §5:9: taken in or answered once
                continue
            if turn is not None and update.update_id in turn.handed:
                continue  # the running activation's, its marking not yet landed
            message = self._own(update)
            if message is None:
                batch.dealt.add(update.update_id)  # §5:2: not input, recorded nowhere
            elif is_stop_command(message):
                if turn is not None:
                    batch.dealt.update(await self._joined(turn, pending))
                    pending = []
                if await self._stopping(update.update_id):
                    batch.dealt.add(update.update_id)
            elif message.text is None or not message.text.strip():
                # §5:3: answered by rule. Whether this claimed the reply or the record
                # already held it answered or taken in, the record now holds it.
                await self._writer.fixed(
                    partial(self._intake.claim_reply, update.update_id), NON_TEXT_LINE
                )
                batch.dealt.add(update.update_id)
            else:
                pending.append(update)
        return pending

    def _own(self, update: TelegramUpdate) -> TelegramMessage | None:
        """The update's message, where it is the configured account's in its chat (§5:1)."""
        message = update.message
        if (
            message is None
            or not message.private_chat
            or message.chat_id != self._client.chat_id
            or message.sender_id != self._client.chat_id
            or message.sender_is_bot
            or message.message_id < 1
        ):
            return None
        return message

    async def _begin(self, updates: Sequence[TelegramUpdate]) -> bool:
        """Start the start wait, or once it has passed take ``updates`` in (ADR-0332 §5:3).

        Returns:
            Whether this began the start wait: nothing is taken in yet, and the next poll
            after it takes in what has arrived.
        """
        if not self._started:
            self._started = True
            return True
        await self._admit(updates)
        self._started = False
        return False

    async def _admit(self, updates: Sequence[TelegramUpdate]) -> None:
        """Bring the updates in, with the window, as one activation's input (§5:5).

        The activation runs beside the loop (ADR-0332 §8:7): the loop goes on polling
        while it runs, and its updates are dealt with once a later poll finds them taken
        in.
        """
        page = await self._memory.channel_episodes(self._channel, limit=_WINDOW_EPISODES)
        messages = [one.message for one in updates if one.message is not None]
        taken = TelegramInput(
            channel=self._channel,
            activation_id=self._mint(),
            updates=tuple(updates),
            window=await self._window(messages, page),
        )
        self._marked[taken.activation_id] = []
        self._current = taken.activation_id
        task = asyncio.ensure_future(self._running(taken))
        self._turn = _Turn(
            activation_id=taken.activation_id, task=task, handed=set(taken.update_ids)
        )
        task.add_done_callback(self._ended)

    async def _running(self, taken: TelegramInput) -> None:
        """Run the input's activation, showing typing while it runs (§6:7)."""
        typing = asyncio.ensure_future(self._writer.typing(taken.activation_id))
        try:
            await self._activate(taken)
        except asyncio.CancelledError:
            raise
        except TelegramIntakeRecordError, MemoryStoreError:
            _log.warning("telegram_read_failed", stage="reader", reason="store_failed")
        except Exception as exc:  # the line runs as long as the hub: a defect is logged
            if is_defect(exc):
                log_defect(
                    "telegram_read_failed", exc, stage="reader", activation_id=taken.activation_id
                )
            else:
                _log.warning("telegram_read_failed", stage="reader", reason="failed")
        finally:
            self._current = None
            self._marked.pop(taken.activation_id, None)
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)

    def _ended(self, task: asyncio.Future[None]) -> None:
        """The activation has ended: what waited meanwhile is taken in at once (§5:5)."""
        turn = self._turn
        if turn is not None and turn.task is task:
            self._turn = None
            self._started = turn.waited
        if not task.cancelled():
            task.exception()  # retrieved, so a failure is never reported unretrieved

    async def _joined(self, turn: _Turn | None, updates: Sequence[TelegramUpdate]) -> set[int]:
        """Join ``updates`` to the running activation, in order, as far as they may.

        ADR-0332 §3:3: each run of consecutive updates of one standing is one input. The
        engine's join checks and takes it in one step, **pending this marking** (§3:6,
        §3:18): the reader marks the run taken in by that activation, as at admission
        (ADR-0293 §6:8), and only what the record marked joins. Acting's commitment step
        waits for it, so the activation acts on nothing the record does not hold taken
        in by it, and a marking that fails leaves the run waiting with nothing having
        read it; the rest of the page is still dealt with, a stop command among it. The
        first run the join refuses waits, and so does everything after it (§3:4); one
        whose activation has not begun its pass is asked again by the next poll.

        Returns:
            The updates marked, which are dealt with.
        """
        dealt: set[int] = set()
        if turn is None:
            return dealt
        for run in _runs(updates):
            if turn.task.done():
                # It ended meanwhile: what is left arrived while it ran, so it is taken
                # in at once by the next poll (§5:5).
                turn.waited = True
                self._started = True
            if turn.waited:
                break
            try:
                found, pending = self._join(self._joining(run))
            except TraceStoreError:
                _log.warning("telegram_join_failed", stage="reader", reason="clock")
                found, pending = JoinCheck.REFUSED, None
            if found is JoinCheck.NOT_YET:
                break
            if pending is None:
                turn.waited = True
                break
            marked: set[int] = set()
            try:
                marked.update(
                    await self._intake.take_in(
                        [one.update_id for one in run], activation_id=pending.activation_id
                    )
                )
            except TelegramIntakeRecordError:
                _log.warning("telegram_join_failed", stage="reader", reason="store_failed")
                turn.waited = True
                break
            finally:
                # Settled however the marking ended: what the record holds joins, and the
                # activation's commitment step goes on.
                pending.confirm(
                    one.message.message_id
                    for one in run
                    if one.update_id in marked and one.message is not None
                )
                turn.handed.update(marked)
                dealt.update(marked)
        return dealt

    def _joining(self, updates: Sequence[TelegramUpdate]) -> JoiningInput:
        """The updates as one input a join takes, each message kept apart and dated."""
        messages = [one.message for one in updates if one.message is not None]
        forward = any(one.forward_origin is not None for one in messages)
        return JoiningInput(
            channel=self._channel,
            messages=_recorded(messages),
            standing=input_standing(
                origin=TELEGRAM.input_origin(self._channel, takes_in_forward=forward),
                established=not forward,
            ),
        )

    async def _stopping(self, update_id: int) -> bool:
        """Act on a stop command: record it answered, stop what runs, answer (§8:4-§8:6).

        The record holds it answered before anything is stopped, so a poll that returns
        it again stops nothing and answers nothing (§8:6). Then the activation running
        from the line's chat is stopped, where one is, and the line answers by rule from
        the writer, never from the activation (§8:5).

        Returns:
            Whether the record holds it answered, so it is dealt with.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written for the claim; it
                is then not dealt with, and nothing is stopped.
        """
        first = await self._intake.claim_reply(update_id)
        if first is None:
            return True  # held already: a repeat stops nothing (§5:9)
        running = self._current
        stopped = running is not None and await self._stop(running)
        _log.info("telegram_stop_command", stage="reader", stopped=stopped)
        claims: list[str] = [first]

        async def claim() -> str | None:
            if claims:
                return claims.pop()
            return await self._intake.claim_reply(update_id)

        await self._writer.fixed(claim, STOPPED_LINE if stopped else NOTHING_RUNNING_LINE)
        return True

    async def take_in(self, taken: TelegramInput, *, into: list[int]) -> None:
        """Mark the input's updates taken in by its activation (§5:8, ADR-0293 §6:8).

        Called by the activation once it is admitted, so the marking and the episode
        that records the activation stand or fall together. The ids it marked are
        added to ``into``, and kept for the reader, which confirms them once the
        activation has ended (§5:6).

        Raises:
            TelegramIntakeRecordError: If the record cannot be written.
        """
        marked = await self._intake.take_in(taken.update_ids, activation_id=taken.activation_id)
        into.extend(marked)
        self._marked.setdefault(taken.activation_id, []).extend(marked)

    async def _after_restart(self) -> None:
        """Send the restart's one fixed message, where it cut the chat's last activation off.

        The chat's last activation is the one its newest episode records (ADR-0283 §3:1):
        the engine closes a dead process's open episodes before the reader starts, so
        the activation a restart cut off is among them. It is read from the episodes and
        not from the intake record, since the reader confirms an activation's updates
        while it runs (ADR-0332 §8:7), and a confirmed update leaves the record. Where
        that episode closed *interrupted*, and not by the user's stop, which writes
        nothing (ADR-0295 §3:3), the writer sends :data:`INTERRUPTED_LINE`, claimed once
        per activation (§6:10). Anything that cannot be read sends nothing.
        """
        try:
            page = await self._memory.channel_episodes(self._channel, limit=1)
            newest = page.entries[-1].record if page.entries else None
            if not isinstance(newest, EpisodicMemory) or not _cut_off(newest):
                return
            assert newest.processing_record is not None  # noqa: S101 — read by _cut_off
            last = newest.processing_record.activation_id
            await self._writer.fixed(lambda: self._intake.claim_interrupted(last), INTERRUPTED_LINE)
        except TelegramIntakeRecordError, MemoryStoreError:
            _log.warning("telegram_restart_unread", stage="reader", reason="store_failed")
        except Exception as exc:  # the line still starts: a defect is logged, never raised
            if is_defect(exc):
                log_defect("telegram_restart_unread", exc, stage="reader", activation_id=None)
            else:
                _log.warning("telegram_restart_unread", stage="reader", reason="failed")

    # --- the window (§10) ---

    async def _window(
        self, messages: Sequence[TelegramMessage], page: ChannelEpisodePage
    ) -> TranscriptWindow:
        """The line's episode window, with what the input replies to (§10, §4:12).

        Args:
            messages: The input's messages.
            page: The line's recent episodes, the newest :data:`_WINDOW_EPISODES`.

        Raises:
            MemoryStoreError: If the episodes cannot be read.
        """
        episodes = [
            one.record
            for one in page.entries
            if isinstance(one.record, EpisodicMemory) and one.record.processing_record is not None
        ]
        activations = [
            one.processing_record.activation_id
            for one in episodes
            if one.processing_record is not None
        ]
        writes: Mapping[int, WrittenBy] = (
            {}
            if self._written is None or not activations
            else await self._written(self._place, activations, None)
        )
        inputs = tuple(self._input_message(one) for one in messages)
        taken = {one.position for one in inputs}
        shown: dict[int, LineMessage] = {}
        links: dict[int, str] = {}
        asked: dict[int, AskedIn] = {}
        forwarded: dict[int, ClaimedAuthor] = {}
        for episode in episodes:
            self._episode_items(episode, writes, shown, links, forwarded)
        for position, writer in writes.items():
            if position in shown and writer.asked is not None:
                asked[position] = writer.asked
        recent = tuple(one for position, one in sorted(shown.items()) if position not in taken)[
            -CHAT_WINDOW_SIZE:
        ]
        replied, claimed = self._replied(messages, inputs, recent, writes, links, asked)
        for one in messages:
            if one.forward_origin is not None:
                forwarded[one.message_id] = ClaimedAuthor(
                    name=one.forward_origin.name, account_id=one.forward_origin.account_id
                )
        kept = {one.position for one in (*recent, *replied, *inputs)}
        return TranscriptWindow(
            conversation=self._channel,
            messages=recent,
            input_messages=inputs,
            replied_to=replied,
            links={position: one for position, one in links.items() if position in kept},
            asked={position: one for position, one in asked.items() if position in kept},
            forwarded={position: one for position, one in forwarded.items() if position in kept},
            claimed=frozenset(claimed),
        )

    def _episode_items(
        self,
        episode: EpisodicMemory,
        writes: Mapping[int, WrittenBy],
        shown: dict[int, LineMessage],
        links: dict[int, str],
        forwarded: dict[int, ClaimedAuthor],
    ) -> None:
        """One episode's messages: the user's from its trigger, the assistant's by record."""
        processing = episode.processing_record
        if processing is None:
            return
        activation_id = processing.activation_id
        for one in processing.trigger.messages:
            if one.position is None or one.position < 1 or not one.text.strip():
                continue
            shown[one.position] = LineMessage(
                position=one.position,
                written_at=one.sent_at,
                author=MessageAuthor.USER,
                text=one.text,
            )
            links[one.position] = activation_id
            if one.forwarded_from is not None:
                forwarded[one.position] = one.forwarded_from
        rounds = {one.id: one.text for one in processing.rounds}
        at = processing.ended_at or episode.occurred_at
        for position, writer in writes.items():
            if writer.activation_id != activation_id or position < 1:
                continue
            text = COULDNT_FINISH if writer.round is None else rounds.get(writer.round, "")
            if not text.strip():
                continue
            shown[position] = LineMessage(
                position=position,
                written_at=at,
                author=MessageAuthor.ASSISTANT,
                text=text,
            )
            links[position] = activation_id

    def _input_message(self, message: TelegramMessage) -> LineMessage:
        """One message of the input, at its Telegram id and time (§5:4)."""
        quoted = message.reply_to
        replies_to = (
            quoted.message_id
            if quoted is not None and 1 <= quoted.message_id < message.message_id
            else None
        )
        return LineMessage(
            position=message.message_id,
            written_at=message.sent_at,
            author=MessageAuthor.USER,
            text=message.text or "",
            replies_to=replies_to,
        )

    def _replied(  # noqa: PLR0913 — the input, as Telegram sent it and as taken in, the window, and the three links it extends
        self,
        messages: Sequence[TelegramMessage],
        inputs: Sequence[LineMessage],
        recent: Sequence[LineMessage],
        writes: Mapping[int, WrittenBy],
        links: dict[int, str],
        asked: dict[int, AskedIn],
    ) -> tuple[tuple[LineMessage, ...], set[int]]:
        """Each message the input replies to that the window does not show (§4:12-§4:13).

        Telegram sends the quoted message with the reply, so it is brought in as it
        came: the assistant's where the bot wrote it, and otherwise an author the line
        does not establish (§4:2). That one is claimed — it may be the user's own, or a
        forward Telegram quotes without its origin — so planning is never shown its
        raw text (ADR-0307 §9:2). Telegram gives no time with it, so it is dated by the
        reply that quotes it. One the bot wrote links to the activation that wrote it by
        that message's effect record, where the window's activations include the
        writer.

        Returns:
            The messages, ascending, and the positions of those whose author is claimed.
        """
        shown = {one.position for one in (*recent, *inputs)}
        replied: dict[int, LineMessage] = {}
        claimed: set[int] = set()
        for one in messages:
            quoted = one.reply_to
            if (
                quoted is None
                or quoted.message_id in shown
                or quoted.message_id in replied
                or not 1 <= quoted.message_id < one.message_id
                or quoted.text is None
                or not quoted.text.strip()
            ):
                continue
            bot = quoted.sender_is_bot
            replied[quoted.message_id] = LineMessage(
                position=quoted.message_id,
                written_at=one.sent_at,
                author=MessageAuthor.ASSISTANT if bot else MessageAuthor.USER,
                text=quoted.text,
            )
            if not bot:
                claimed.add(quoted.message_id)
            writer = writes.get(quoted.message_id) if bot else None
            if writer is not None:
                links[quoted.message_id] = writer.activation_id
                if writer.asked is not None:
                    asked[quoted.message_id] = writer.asked
        return tuple(one for _, one in sorted(replied.items())), claimed


def _runs(updates: Sequence[TelegramUpdate]) -> list[list[TelegramUpdate]]:
    """``updates`` in runs of consecutive ones of one standing: forwards, or the user's own.

    A forward's author is claimed (ADR-0323 §4:10), so a run that takes one in has a
    standing of its own, and never joins one whose author is established (ADR-0332 §3:3).
    """
    runs: list[list[TelegramUpdate]] = []
    for one in updates:
        forward = one.message is not None and one.message.forward_origin is not None
        if runs and _forwarded(runs[-1][-1]) == forward:
            runs[-1].append(one)
        else:
            runs.append([one])
    return runs


def _forwarded(update: TelegramUpdate) -> bool:
    return update.message is not None and update.message.forward_origin is not None


def _cut_off(record: EpisodicMemory) -> bool:
    """Whether a restart cut the episode's activation off: closed *interrupted*, not stopped."""
    processing = record.processing_record
    return (
        processing is not None
        and processing.status is ProcessingStatus.INTERRUPTED
        and processing.reason is not ProcessingReason.STOPPED
    )


def _failure(outcome: TelegramOutcome) -> str:
    """A failed call's class, as a log line names it."""
    return "done" if outcome.failure is None else outcome.failure.value


def _poll_backoff(outcome: TelegramOutcome) -> timedelta | None:
    """How long to rest after a poll that was not done, before polling again (§11:11).

    A poll at its bound, or one whose answer was lost, is polled again at once; one
    that was never written, or that Telegram refused, rests; a rate limit rests as long
    as Telegram asked; and a line that is unavailable rests longest, until the owner's
    act changes the answer (§3:7).
    """
    failure = outcome.failure
    if failure is None or failure is TelegramFailure.UNKNOWN:
        return None
    if failure is TelegramFailure.UNAVAILABLE:
        return UNAVAILABLE_BACKOFF
    if failure is TelegramFailure.RATE_LIMITED and outcome.retry_after_seconds is not None:
        return timedelta(seconds=outcome.retry_after_seconds)
    return POLL_BACKOFF
