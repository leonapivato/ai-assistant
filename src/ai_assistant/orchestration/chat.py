"""The chat's spokes in the hub: its reader and its writer (ADR-0293).

The conversation channel's medium is the hub's chat space, and its spokes are in the
hub (ADR-0293 §1:2): a **reader**, its sensor, which notices the user's new messages
and brings them in as a push, and a **writer**, its actuator, which adds the
assistant's messages.

**The reader** (§6). A user's message is recorded by the act that wrote it and starts
nothing there; the engine tells this reader the conversation has a message, and the
reader takes in every message waiting in that conversation that no activation has
taken in. The assistant's own messages are never among them, so they never start an
activation (§6:1).

**One activation at a time per conversation** (ADR-0332 §2:3-§2:4, ADR-0293 §6:2-§6:3).
The conversation kind declares that each of its places runs one activation at a time,
and the reader keeps one read running per conversation. A message written while an
activation started from that conversation runs **joins it** where ADR-0332 §3:3 allows:
the reader hands it to the engine's join (``join``), which takes it only where the
activation has not committed and is not stopped, its author and standing are the
running input's, and fewer than ``join_limit`` joins are taken; the reader holds the
fourth condition itself, that no earlier input on the place is waiting, since once one
message has not joined nothing after it joins. The join is taken pending the reader's
marking of the message, taken in by the activation it joins, and that activation leaves
running by no route until the marking has settled (§3:18), so the store's bookkeeping is what a
restart reads. A message that does not join waits: it is never
refused, and when the activation ends the reader looks again and takes in everything
waiting **together, as one input**.

**The start wait, and composing** (ADR-0332 §5:1-§5:2, §5:6-§5:7). Where nothing is
running, the reader takes a conversation's waiting messages in only once
``start_wait`` has passed since the latest of them and no composing signal for the
conversation is live, and no later than ``composing_cap`` after the first. A composing
signal (:meth:`ChatReader.composing`) stays live for ``composing_lapse``; it only
extends a start wait already running, and starts nothing, joins nothing and is written
nowhere (§5:8).

**The reader's bookkeeping** (§6:6-§6:9) is the conversation store's ``take_in``,
which holds no text: the messages are marked taken in, by the activation's id, when
the activation is admitted — its first step once its episode is written, before any
of its processing (:meth:`ChatReader.take_in`). So an activation a shutdown cancels at
any point is one whose episode closes interrupted: either it marked its messages, and
after a restart they are not taken in again, since it may have acted on them, or it
did not, and they are taken in as usual. A message never taken in is found by
``conversations_awaiting`` (:meth:`ChatReader.notice_awaiting`).

**The window** (§6:4, §6:5) is the conversation's recent transcript, read by the
reader with the input and handed to the activation beside it: each message keeps its
author, and the window informs and never authorizes. The reader brings its bookkeeping
with it: the activation that took in each message of the window, where one did, which
is what the message links to (ADR-0303 §7:3). Where the phases write messages, it also
brings the activation that **wrote** each assistant message, by acting's effect record
(ADR-0303 §7:1, ADR-0306 §5:3), read through the ``written`` reader it is handed, and
the question each such message is, where it is one (ADR-0322 §4:2).

**The writer** (§9, §10). The phases write the activation's messages into the
conversation the input came from as it runs, and a pass that cannot finish writes the
fixed *couldn't finish* message, listing any effect that did happen
(:func:`couldnt_finish`; ADR-0307 §3, ADR-0317 §3). A restart writes nothing (§9:2):
an activation cancelled by a shutdown has its episode closed as interrupted and nothing
is written for it, and the conversation's current state shows *interrupted* (§8:3).

Nothing concrete is imported: the conversation store arrives by injection and is seen
only through its Protocol (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.channel_validation import input_origin
from ai_assistant.core.errors import (
    ConversationStoreError,
    TraceStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    DeletedMessage,
    MessageAuthor,
    NewMessage,
    RecordedInputMessage,
    TranscriptMessage,
)
from ai_assistant.orchestration.conversations import conversation_channel, fitted_message
from ai_assistant.orchestration.joining import JoinCheck, JoiningInput, input_standing, settle
from ai_assistant.orchestration.understanding import AskedIn, TranscriptWindow, WrittenBy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import MessageReceipt
    from ai_assistant.orchestration.joining import PendingJoin

__all__ = [
    "CHAT_TURN_BUDGET",
    "CHAT_WINDOW_SIZE",
    "COULDNT_FINISH",
    "DEFAULT_CHAT_COMPOSING_CAP",
    "DEFAULT_CHAT_COMPOSING_LAPSE",
    "DEFAULT_CHAT_START_WAIT",
    "ChatInput",
    "ChatReader",
    "ChatWriter",
    "couldnt_finish",
]

_log = structlog.get_logger(__name__)

#: How many of the conversation's recent messages the window holds (ADR-0293 §7:5:
#: the kind declares its window size). The replay bound the retired episode tail had
#: (``HISTORY_REPLAY_BOUND``), so the window an input arrives with is as wide as it was.
CHAT_WINDOW_SIZE: Final = 20

#: The budget one activation the reader starts is given, where the engine is built
#: without one. The reader has no caller to hand it one (ADR-0029 §4), so the engine
#: takes it as ``chat_turn_budget``; the composition root passes its own
#: ``PHASES_TURN_BUDGET``, so this default holds only for an engine built without it.
CHAT_TURN_BUDGET: Final = timedelta(seconds=60)

#: ``Settings.chat_start_wait``'s default (ADR-0332 §6:1), which an engine built without
#: the composition root's value takes.
DEFAULT_CHAT_START_WAIT: Final = timedelta(seconds=1.5)

#: ``Settings.chat_composing_lapse``'s default (ADR-0332 §6:2).
DEFAULT_CHAT_COMPOSING_LAPSE: Final = timedelta(seconds=3)

#: ``Settings.chat_composing_cap``'s default (ADR-0332 §6:3).
DEFAULT_CHAT_COMPOSING_CAP: Final = timedelta(seconds=10)

#: How long the joiner waits before it asks again, where the activation running on the
#: conversation has not yet begun its pass, so its input's standing is not yet set: the
#: admission's two writes, the episode and the marking (ADR-0332 §3:3).
_JOIN_RETRY: Final = timedelta(milliseconds=20)

#: How many positions one ``take_in`` call marks, and one ``taken_in`` call reads: the
#: store's own bound. Every message waiting is taken in together, as one input
#: (ADR-0293 §6:3), so an input holding more is marked over several calls under the one
#: activation's id.
_MARK_CHUNK: Final = 1000

#: The read of what waits asks for every waiting message: the store's own ceiling.
_WAITING_ALL: Final = 2**63 - 1

#: How many conversation ids one page of the restart walk reads.
_AWAITING_PAGE: Final = 100

#: The fixed text of the *couldn't finish* message (ADR-0293 §9:1). Fixed rather than
#: composed (§5:2's note), so it says the same thing whatever failed.
COULDNT_FINISH: Final = "I couldn't finish this."

#: How the effects that did happen are introduced, where there are any (§9:1).
_EFFECTS_INTRODUCED: Final = " Before it stopped, this happened:"

#: What separates two waiting messages taken in as one input (§6:3).
_INPUT_SEPARATOR: Final = "\n\n"


@dataclass(frozen=True, slots=True)
class ChatInput:
    """What the reader brings in for one activation (ADR-0293 §6).

    Attributes:
        conversation_id: The conversation the messages were written in, which is the
            one the reply is written into (§10:1).
        activation_id: The id the activation is admitted with, which the messages
            were marked taken in by (§6:6).
        messages: The user's messages taken in, ascending: the input.
        window: The conversation's recent transcript, brought in with the input.
    """

    conversation_id: str
    activation_id: str
    messages: tuple[TranscriptMessage, ...]
    window: TranscriptWindow

    @property
    def text(self) -> str:
        """The input: the messages' text, in the order they were written (§6:3)."""
        return _INPUT_SEPARATOR.join(message.text for message in self.messages)

    def narrowed(self, positions: Sequence[int]) -> ChatInput:
        """The input as its activation took it in: only the messages at ``positions``.

        A message read as waiting and not marked — deleted, or taken in elsewhere, in
        between — is neither input nor window (§6:6).
        """
        kept = frozenset(positions)
        messages = tuple(message for message in self.messages if message.position in kept)
        return replace(
            self, messages=messages, window=replace(self.window, input_messages=messages)
        )


@dataclass(slots=True)
class _StartWait:
    """A start wait running for one conversation (ADR-0332 §5:1-§5:2, §5:6).

    Each instant is the reader's clock's reading: when the first waiting message was
    noticed, when the latest was, and until when the latest composing signal is live.
    """

    first: float
    latest: float
    composing_until: float = -math.inf


@dataclass(slots=True)
class _Turn:
    """One activation a read admitted, while it runs: what it holds, and whether one waited.

    Attributes:
        activation_id: The activation.
        handed: The positions of the messages it was handed, its trigger's and each
            joined one's, which no later look hands anything again.
        due: Set by a notice while it runs: a message may be waiting to join. Set at
            admission too, for a message noticed while the admitting read ran.
        waited: Whether a message did not join it, after which nothing joins it, since
            no input joins past one that is waiting (ADR-0332 §3:3).
        over: Whether it has ended, so the joiner stops once its attempt is done.
    """

    activation_id: str
    handed: set[int]
    due: asyncio.Event = field(default_factory=asyncio.Event)
    waited: bool = False
    over: bool = False


def couldnt_finish(effects: Sequence[str] = ()) -> NewMessage:
    """The fixed *couldn't finish* message, listing any effects that did happen (§9:1)."""
    text = COULDNT_FINISH
    if effects:
        text += _EFFECTS_INTRODUCED + "".join(f"\n- {one}" for one in effects)
    return NewMessage(author=MessageAuthor.ASSISTANT, text=text)


class ChatWriter:
    """The chat's writer, its actuator: *send a message* (ADR-0293 §6:10-§6:13).

    It adds an assistant message to a conversation, held to the writer's rules —
    text only, and a size bound (§7:3) — and the message is *sent* once the
    conversation has recorded it, whatever devices are showing it (§6:12).
    """

    def __init__(self, *, conversations: ConversationStore, max_payload_bytes: int) -> None:
        """Wire the writer to the chat space and the payload limit its reads are held to.

        Args:
            conversations: The chat space.
            max_payload_bytes: The contract limit, so a message the writer records is
                one a read can return (``fitted_message``).
        """
        self._conversations = conversations
        self._max_payload_bytes = max_payload_bytes

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        """``message`` exactly as :meth:`send` records it: cut to what a read can return.

        So a caller that keeps what it wrote keeps the text the conversation holds
        (ADR-0307 §10's ``outcome``), and :meth:`send` of what this returns writes it
        unchanged.

        Raises:
            OversizedValueError: If no non-blank prefix of the text fits.
        """
        return fitted_message(conversation_id, message, max_bytes=self._max_payload_bytes)

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        """Write one assistant message into a conversation, or ``None`` where it is gone.

        A conversation deleted while its activation ran is not written into: deleting
        it removed the place (§2:3), and a message is never what creates one (§2:2).

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        fitted = self.fitted(conversation_id, message)
        try:
            return await self._conversations.append_message(conversation_id, fitted)
        except UnknownConversationError:
            _log.info("chat_message_unwritten", reason="conversation_gone")
            return None


class ChatReader:
    """The chat's reader, its sensor (ADR-0293 §6, ADR-0332 §2-§3, §5).

    One read runs per conversation at a time. :meth:`notice` starts one where none is
    running and otherwise asks the running one to look again; the read waits out the
    start wait, takes in every waiting message as one input, runs one activation for it
    through ``activate``, and looks again when that activation has ended, until nothing
    is waiting. While the activation runs, a message noticed joins it where it may.
    """

    def __init__(  # noqa: PLR0913 — the medium, how an activation runs, four engine seams, the writers' links, and the waits with their clock
        self,
        *,
        conversations: ConversationStore,
        activate: Callable[[ChatInput], Awaitable[bool]],
        spawn: Callable[[Coroutine[None, None, None]], object],
        closing: Callable[[], bool],
        mint: Callable[[], str],
        window_size: int = CHAT_WINDOW_SIZE,
        written: Callable[[str, Sequence[str], Sequence[int]], Awaitable[Mapping[int, WrittenBy]]]
        | None = None,
        join: Callable[[JoiningInput], tuple[JoinCheck, PendingJoin | None]] | None = None,
        start_wait: timedelta | None = None,
        composing_lapse: timedelta = DEFAULT_CHAT_COMPOSING_LAPSE,
        composing_cap: timedelta = DEFAULT_CHAT_COMPOSING_CAP,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Wire the reader.

        Args:
            conversations: The chat space, whose bookkeeping, waiting messages and
                transcript the reader reads and writes.
            activate: Admits one activation for an input, which marks the input taken
                in (:meth:`take_in`) and writes its reply. It returns whether anything
                was marked, once the reply is written, or raises ``CancelledError``
                where a shutdown cancelled it.
            spawn: Starts a read as a task the engine tracks, so shutdown drains it.
            closing: Whether the engine has begun shutting down, after which no new
                input is taken in.
            mint: The activation id the next input is admitted with, and marked taken
                in by.
            window_size: How many recent messages the window holds.
            written: Reads which activation wrote each assistant message, by its
                effect record, where the phases write messages (ADR-0303 §7:1):
                given the conversation, the candidate activations and the assistant
                messages' positions, it answers the activation, and the question the
                message is where it is one, by position, a position no record names
                simply missing. ``None``, the default, links no assistant message, as
                before the phases.
            join: The engine's join (ADR-0332 §3:3, §3:6, §3:18): it takes an input
                into the activation running on its place where that activation may
                take it, pending the reader's marking of its messages taken in by that
                activation, which the reader then confirms or withdraws. ``None``, the
                default, joins nothing: every message written while an activation runs
                waits.
            start_wait: ``Settings.chat_start_wait`` (ADR-0332 §5:1): how long after
                the latest waiting message the reader waits, where nothing is running,
                before it takes them in. ``None``, the default, waits for nothing, and
                a composing signal then extends nothing.
            composing_lapse: ``Settings.chat_composing_lapse`` (§5:6): how long one
                composing signal stays live.
            composing_cap: ``Settings.chat_composing_cap`` (§5:2): the longest a start
                wait lasts after the first waiting message.
            clock: The monotonic clock the waits are read on, in seconds; the running
                loop's by default.
            sleep: How the reader waits.

        Raises:
            ValueError: If a wait is not strictly positive, or ``composing_cap`` is
                shorter than ``start_wait`` or ``composing_lapse`` (§6:1-§6:3).
        """
        if start_wait is not None and (
            start_wait <= timedelta(0)
            or composing_lapse <= timedelta(0)
            or composing_cap < max(start_wait, composing_lapse)
        ):
            msg = (
                "the start wait and the composing lapse are strictly positive, and the "
                "cap no shorter than either (ADR-0332 §6:1-§6:3)"
            )
            raise ValueError(msg)
        self._conversations = conversations
        self._written = written
        self._activate = activate
        self._spawn = spawn
        self._closing = closing
        self._mint = mint
        self._window_size = window_size
        # A conversation is a key while a read of it runs; its value is whether it was
        # noticed again since that read last looked.
        self._reading: dict[str, bool] = {}
        # The activation each conversation's read has admitted for an input, until its
        # reply is written.
        self._current: dict[str, str] = {}
        # Per conversation, how many times its entry in `_current` was set or cleared:
        # what lets a reader of `activity` tell that an activation began and ended
        # between two of its readings (ADR-0296 §4:9).
        self._turns: dict[str, int] = {}
        self._join = join
        self._start_wait = None if start_wait is None else start_wait.total_seconds()
        self._composing_lapse = composing_lapse.total_seconds()
        self._composing_cap = composing_cap.total_seconds()
        self._clock = clock if clock is not None else _loop_time
        self._sleep = sleep
        # ADR-0332 §5:1: the start wait running for each conversation where nothing is,
        # from the first message noticed until the read takes the messages in.
        self._waits: dict[str, _StartWait] = {}
        # Set by :meth:`close`: every start wait ends at once, and nothing is taken in.
        self._closed = asyncio.Event()
        # The activation each conversation's read has admitted, while it runs.
        self._running: dict[str, _Turn] = {}

    def notice(self, conversation_id: str) -> None:
        """Tell the reader a user's message was written into a conversation (§6:1).

        Starts a read of the conversation where none is running; otherwise the running
        read looks again before it ends. Where an activation the read admitted is
        running, the message joins it where it may, and otherwise waits and is taken in
        after it (ADR-0332 §2:4, §3:3; §6:2, §6:3). Where nothing is running, it starts
        or extends the start wait (ADR-0332 §5:1). Nothing is started once the engine is
        closing: the message waits, and a restart takes it in (§6:9).
        """
        if self._closing():
            return
        turn = self._running.get(conversation_id)
        if turn is not None:
            turn.due.set()
        elif self._start_wait is not None:
            now = self._clock()
            wait = self._waits.get(conversation_id)
            if wait is None:
                self._waits[conversation_id] = _StartWait(first=now, latest=now)
            else:
                wait.latest = now
        if conversation_id in self._reading:
            self._reading[conversation_id] = True
            return
        self._reading[conversation_id] = False
        self._spawn(self._read(conversation_id))

    def close(self) -> None:
        """End every start wait at once: the engine is closing, so nothing is taken in.

        The messages stay waiting, and a restart takes them in (§6:9).
        """
        self._closed.set()

    def composing(self, conversation_id: str) -> None:
        """Take the hub chat page's signal that the person is typing (ADR-0332 §5:6-§5:8).

        It extends the start wait running for the conversation, the signal staying live
        for ``composing_lapse``, and does nothing where none is running (§5:7). It is not
        input: it starts no read and no wait, joins nothing, and is written nowhere.
        """
        wait = self._waits.get(conversation_id)
        if wait is not None:
            wait.composing_until = self._clock() + self._composing_lapse

    async def notice_awaiting(self) -> int:
        """Notice every conversation holding a message no activation took in (§6:9).

        Run at start, after a restart closed what a dead process left open, and on each
        later sweep, so a message that waited past a missed notice is still taken in.

        Returns:
            How many conversations were noticed.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        noticed = 0
        after: str | None = None
        while page := await self._conversations.conversations_awaiting(
            limit=_AWAITING_PAGE, after_id=after
        ):
            for conversation_id in page:
                self.notice(conversation_id)
                noticed += 1
            after = page[-1]
        return noticed

    def working(self, conversation_id: str) -> str | None:
        """The activation this reader has an input in for, until its reply is written.

        From its admission to the written reply, so a conversation shows "working…"
        until the message answering it is in the transcript (§8:2).
        """
        return self._current.get(conversation_id)

    def activity(self) -> dict[str, tuple[int, str | None]]:
        """Per conversation this reader has read for, a count of changes and its activation.

        The count moves each time an activation is admitted for the conversation and
        each time its reply is written, and the activation is :meth:`working`'s. What
        the change stream reads to push a conversation's current state when it changes
        (ADR-0296 §4:9): a count that moved between two readings is a change even where
        the activation began and ended between them. A fresh mapping on every call.
        """
        return {one: (turns, self._current.get(one)) for one, turns in self._turns.items()}

    async def take_in(self, taken: ChatInput, *, into: list[int]) -> None:
        """Mark the input's messages taken in by its activation (§6:6, §6:8).

        Called by the activation once it is admitted, so the marking and the episode
        that records the activation stand or fall together. Every message of the input
        is marked under the one id, in as many calls as the store's bound needs, and
        each call's positions are added to ``into`` as it returns: a call that fails
        after an earlier one committed leaves ``into`` holding what is marked, so the
        caller can tell an input partly taken in from one not taken in at all.

        Args:
            taken: The input.
            into: Where the positions this activation marked are added. A message
                deleted, or taken in elsewhere, since it was read as waiting is not
                among them.

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        positions = [message.position for message in taken.messages]
        for start in range(0, len(positions), _MARK_CHUNK):
            into.extend(
                await self._conversations.take_in(
                    taken.conversation_id,
                    positions=positions[start : start + _MARK_CHUNK],
                    activation_id=taken.activation_id,
                )
            )

    async def _read(self, conversation_id: str) -> None:
        """Take in what waits in one conversation, one input at a time, until none does."""
        try:
            while not self._closing():
                if not await self._waited(conversation_id):
                    return
                self._reading[conversation_id] = False
                waiting = await self._conversations.untaken_messages(
                    conversation_id, limit=_WAITING_ALL
                )
                if self._wait_end(conversation_id) > self._clock():
                    # A message noticed during those reads moved the wait's end, its cap
                    # still the first message's (ADR-0332 §5:1-§5:2).
                    continue
                if not waiting:
                    if self._reading[conversation_id]:
                        continue
                    return
                taken = await self._admit(conversation_id, waiting)
                if not taken and not self._reading[conversation_id]:
                    # Nothing was marked: the engine began closing, the store refused
                    # the marking, or what was read as waiting went in between. Stop
                    # rather than re-read in a loop; a later notice or sweep looks again.
                    return
        except asyncio.CancelledError:
            raise
        except ConversationStoreError:
            # The messages stay waiting, and the next notice or sweep takes them in.
            _log.warning("chat_read_failed", stage="reader", exc_info=True)
        except Exception:
            _log.exception("chat_read_failed", stage="reader")
        finally:
            self._reading.pop(conversation_id, None)
            self._waits.pop(conversation_id, None)

    async def _admit(self, conversation_id: str, waiting: Sequence[TranscriptMessage]) -> bool:
        """Bring the waiting messages in, with the window, as one activation's input.

        Returns:
            Whether the activation marked anything taken in.
        """
        # What it takes in ends any start wait; a message noticed from here on is one
        # for this activation to join, where it may, or to wait behind.
        self._waits.pop(conversation_id, None)
        activation_id = self._mint()
        turn = _Turn(activation_id=activation_id, handed={one.position for one in waiting})
        # Due from the start: a message noticed after the read took ``waiting`` and
        # before this turn was running found none to wake, so the joiner looks once,
        # whatever was noticed during that read (ADR-0332 §3:3). Where nothing waits,
        # the look is one read.
        turn.due.set()
        self._running[conversation_id] = turn
        try:
            window = await self._window(conversation_id, waiting)
        except BaseException:
            self._running.pop(conversation_id, None)
            raise
        self._current[conversation_id] = activation_id
        self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1
        joins = (
            None
            if self._join is None
            else asyncio.ensure_future(self._joining(conversation_id, turn))
        )
        try:
            return await self._activate(
                ChatInput(
                    conversation_id=conversation_id,
                    activation_id=activation_id,
                    messages=tuple(waiting),
                    window=window,
                )
            )
        finally:
            self._running.pop(conversation_id, None)
            if joins is not None:
                turn.over = True
                turn.due.set()
                await _joiner_ended(joins)
            self._current.pop(conversation_id, None)
            self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1

    async def _waited(self, conversation_id: str) -> bool:
        """Wait out the conversation's start wait, where one is running (ADR-0332 §5:1).

        It ends once ``start_wait`` has passed since the latest message noticed and no
        composing signal is live, and no later than ``composing_cap`` after the first
        (§5:2). A notice or a signal only ever moves its end later, so sleeping to the
        end as it stands and reading it again is enough.

        Returns:
            Whether the read goes on: ``False`` once the engine is closing.
        """
        while not self._closing():
            remaining = self._wait_end(conversation_id) - self._clock()
            if remaining <= 0:
                return True
            await self._nap(remaining)
        return False

    def _wait_end(self, conversation_id: str) -> float:
        """When the conversation's start wait ends; minus infinity where none is running.

        ``start_wait`` after the latest message noticed or the end of the live composing
        signal, whichever is later, and no later than ``composing_cap`` after the first
        (§5:1-§5:2). The wait stays recorded until the read admits what it covers, so a
        message noticed meanwhile still extends it, under the first message's cap.
        """
        wait = self._waits.get(conversation_id)
        if wait is None or self._start_wait is None:
            return -math.inf
        return min(
            wait.first + self._composing_cap,
            max(wait.latest + self._start_wait, wait.composing_until),
        )

    async def _nap(self, seconds: float) -> None:
        """Sleep ``seconds``, or until :meth:`close`, whichever comes first."""
        napping = asyncio.ensure_future(self._sleep(seconds))
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            await asyncio.wait((napping, closed), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for one in (napping, closed):
                one.cancel()
            await asyncio.gather(napping, closed, return_exceptions=True)

    async def _joining(self, conversation_id: str, turn: _Turn) -> None:
        """Join what is noticed to the running activation, until one message waits.

        Runs beside the activation, and ends when it does, once the attempt under way
        has finished, so a marking is never cut off half-written. Each notice wakes it
        (:meth:`notice`); where the activation's pass has not yet begun, it asks again
        shortly. A store that cannot be read or written leaves what it held waiting.
        """
        while not turn.waited and not turn.over:
            await turn.due.wait()
            turn.due.clear()
            try:
                found = await self._join_waiting(conversation_id, turn)
            except ConversationStoreError, TraceStoreError:
                # What it held waits, and so does everything after it.
                _log.warning("chat_join_failed", stage="reader", reason="store_failed")
                turn.waited = True
                return
            if found is JoinCheck.NOT_YET:
                asyncio.get_running_loop().call_later(_JOIN_RETRY.total_seconds(), turn.due.set)

    async def _join_waiting(self, conversation_id: str, turn: _Turn) -> JoinCheck | None:
        """Hand what waits to the join, then mark it taken in by the activation it joins.

        ADR-0332 §3:3: the messages not yet taken in, and handed to nothing, are one
        input, since nothing before them is waiting. The engine's join checks and takes
        it in one step, **pending this marking** (§3:6, §3:18): the reader marks the
        messages taken in by that activation, as at admission (ADR-0293 §6:8), and only
        what the store marked joins; a message deleted or taken in elsewhere meanwhile
        does not. Every route out of running waits for it, so the activation acts on
        nothing, and freezes on nothing, the store does not hold taken in by it, and a
        marking that fails leaves the message waiting with nothing having read it. Where
        the join refuses, the input waits, and so does everything after it (§3:4).

        Returns:
            What the join found, or ``None`` where nothing was waiting.

        Raises:
            ConversationStoreError: If the store cannot be read or written; what was
                marked before then joins, and the rest waits.
        """
        join = self._join
        assert join is not None  # noqa: S101 — the joiner runs only beside it
        if turn.over:
            return None
        untaken = await self._conversations.untaken_messages(conversation_id, limit=_WAITING_ALL)
        waiting = [one for one in untaken if one.position not in turn.handed]
        if not waiting or turn.waited:
            return None
        found, pending = join(self._joining_input(conversation_id, waiting))
        if pending is None:
            turn.waited = found is JoinCheck.REFUSED
            return found
        marked: set[int] = set()
        positions = [one.position for one in waiting]

        async def marking() -> None:
            for start in range(0, len(positions), _MARK_CHUNK):
                marked.update(
                    await self._conversations.take_in(
                        conversation_id,
                        positions=positions[start : start + _MARK_CHUNK],
                        activation_id=pending.activation_id,
                    )
                )

        try:
            # Settled however the marking ended, and written to its end through a
            # shutdown's cancellation: what the store holds joins, and the activation,
            # whose every route out of running waits for this, goes on.
            await settle(pending, marking(), lambda: marked)
        finally:
            turn.handed.update(marked)
        return found

    def _joining_input(
        self, conversation_id: str, messages: Sequence[TranscriptMessage]
    ) -> JoiningInput:
        """The messages as one input a join takes, each kept apart and dated (§3:10)."""
        channel = conversation_channel(conversation_id)
        return JoiningInput(
            channel=channel,
            messages=tuple(
                RecordedInputMessage(text=one.text, sent_at=one.written_at, position=one.position)
                for one in messages
            ),
            standing=input_standing(
                origin=input_origin(channel),
                established=all(one.author is MessageAuthor.USER for one in messages),
            ),
        )

    async def _window(
        self, conversation_id: str, waiting: Sequence[TranscriptMessage]
    ) -> TranscriptWindow:
        """The conversation's recent transcript and what the input replies to (§6:4).

        The recent messages without the input's own; then each earlier message an
        input message replies to that they do not show, read by its position.
        """
        positions = {message.position for message in waiting}
        page = await self._conversations.transcript(
            conversation_id, limit=self._window_size + len(positions)
        )
        entries = () if page is None else page.entries
        recent = tuple(
            one
            for one in entries
            if isinstance(one, TranscriptMessage) and one.position not in positions
        )[-self._window_size :]
        shown = positions | {one.position for one in recent}
        replied: list[TranscriptMessage | DeletedMessage] = []
        for wanted in sorted({one.replies_to for one in waiting if one.replies_to is not None}):
            if wanted in shown:
                continue
            earlier = await self._conversations.transcript(
                conversation_id, before=wanted + 1, limit=1
            )
            if earlier is not None and earlier.entries and earlier.entries[-1].position == wanted:
                replied.append(earlier.entries[-1])
        links, asked = await self._links(conversation_id, recent, replied)
        return TranscriptWindow(
            conversation=conversation_channel(conversation_id),
            messages=recent,
            input_messages=tuple(waiting),
            replied_to=tuple(replied),
            links=links,
            asked=asked,
        )

    async def _links(
        self,
        conversation_id: str,
        recent: Sequence[TranscriptMessage],
        replied: Sequence[TranscriptMessage | DeletedMessage],
    ) -> tuple[dict[int, str], dict[int, AskedIn]]:
        """The activation each window message links to, and the question each one is.

        ADR-0303 §7:1-§7:3, with ADR-0322 §4:2's question: for an assistant message
        linked by its effect record, the question it is, where ``written`` found one.

        Brought with the window, so the understanding phase reads no further store to
        link a message. A user's message links to the activation that took it in, by
        the bookkeeping (§6:6). An assistant's message links to the activation that
        wrote it, by acting's effect record, where the reader is handed ``written``:
        the candidates are the activations the bookkeeping names for the window's
        messages, and for as many positions again just before the recent messages and
        just before each earlier assistant message an input replies to, since such a
        message was written by an activation whose input may lie just before it. A
        writer whose whole input lies further back is not found, and its message stays
        not linkable, the conservative direction (§7:5). A message nothing links is
        simply missing.
        """
        shown = [one.position for one in (*recent, *replied)]
        links = await self._taken_in(conversation_id, shown)
        writes = [
            one.position
            for one in (*recent, *replied)
            if isinstance(one, TranscriptMessage) and one.author is MessageAuthor.ASSISTANT
        ]
        asked: dict[int, AskedIn] = {}
        if self._written is None or not writes:
            return links, asked
        recent_positions = {one.position for one in recent}
        heads = {min(recent_positions)} if recent_positions else set()
        heads.update(position for position in writes if position not in recent_positions)
        looked = sorted(
            {
                position
                for head in heads
                for position in range(max(1, head - self._window_size), head)
            }
        )
        before = await self._taken_in(conversation_id, looked)
        candidates = list(dict.fromkeys((*links.values(), *before.values())))
        if not candidates:
            return links, asked
        written = await self._written(conversation_id, candidates, writes)
        for position in writes:
            writer = written.get(position)
            if writer is not None and position not in links:
                links[position] = writer.activation_id
                if writer.asked is not None:
                    asked[position] = writer.asked
        return links, asked

    async def _taken_in(self, conversation_id: str, positions: Sequence[int]) -> dict[int, str]:
        """The bookkeeping for ``positions``, in as many calls as the store's bound needs."""
        links: dict[int, str] = {}
        for start in range(0, len(positions), _MARK_CHUNK):
            links.update(
                await self._conversations.taken_in(
                    conversation_id, positions=positions[start : start + _MARK_CHUNK]
                )
            )
        return links


async def _joiner_ended(joins: asyncio.Future[None]) -> None:
    """Wait for the joiner to end once its activation has (ADR-0332 §3:18).

    A read cancelled by a shutdown cancels the joiner too, so a store read it is
    suspended in never holds the shutdown; a marking it has begun is still written to
    its end (:func:`~ai_assistant.orchestration.joining.settle`). Otherwise
    the joiner finishes the attempt under way, so a marking is never cut off, and a
    cancellation that arrives meanwhile reaches it too.

    Raises:
        CancelledError: Where the read was cancelled, once the joiner has ended.
    """
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        joins.cancel()
    try:
        await asyncio.gather(joins, return_exceptions=True)
    except asyncio.CancelledError:
        joins.cancel()
        await asyncio.gather(joins, return_exceptions=True)
        raise


def _loop_time() -> float:
    """The running loop's monotonic clock, in seconds."""
    return asyncio.get_running_loop().time()
