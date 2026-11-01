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

**No place waits** (ADR-0349 §8:1-§8:2). Every message starts its own activation once
its conversation's start wait has passed, whatever runs there or anywhere else: the
reader holds nothing back for running work, and no input joins one by code. Several
activations may run from one conversation at once; how one relates to another is
understanding's to judge, and the waits between them are the engine's (ADR-0349 §7).
Each read of a conversation runs its start wait and then the one activation it admits,
and a message noticed once that read has taken its input in starts a read of its own.

**The start wait, and composing** (ADR-0332 §5:1-§5:2, §5:6-§5:7, ADR-0349 §8:2). The
reader takes a conversation's waiting messages in, **together, as one input**, only once
``start_wait`` has passed since the latest of them and no composing signal for the
conversation is live, and no later than ``composing_cap`` after the first, whether or
not anything runs there. A composing signal (:meth:`ChatReader.composing`) stays live
for ``composing_lapse``; it only extends a start wait already running, and starts
nothing and is written nowhere (§5:8). What a read holds in its start wait it tells
the engine of (``hold``), so an older activation's act waits for it (ADR-0349 §7:12).

**The reader's bookkeeping** (§6:6-§6:9) is the conversation store's ``take_in``,
which holds no text: the messages are marked taken in, by the activation's id, when
the activation is admitted — its first step once its episode is written, before any
of its processing (:meth:`ChatReader.take_in`, ADR-0349 §8:3), and until that
activation has ended no later read takes them in again, marked or not. So an
activation a shutdown cancels at any point is one whose episode closes interrupted:
either it marked its messages, and after a restart they are not taken in again, since
it may have acted on them, or it did not, and they are taken in as usual. A message
never taken in is found by ``conversations_awaiting`` (:meth:`ChatReader.notice_awaiting`).

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
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import (
    ConversationStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    DeletedMessage,
    MessageAuthor,
    NewMessage,
    TranscriptMessage,
)
from ai_assistant.orchestration.conversations import conversation_channel, fitted_message
from ai_assistant.orchestration.understanding import TranscriptWindow, WrittenBy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import ChannelIdentity, MessageReceipt
    from ai_assistant.orchestration.matters import HeldInput

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

#: How many positions one ``take_in`` call marks, and one ``taken_in`` call reads: the
#: store's own bound. Every message waiting once the start wait has passed is taken in
#: together, as one input (ADR-0332 §5:1), so an input holding more is marked over
#: several calls under the one activation's id.
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

#: What separates two waiting messages taken in as one input (ADR-0332 §5:1).
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


@dataclass(eq=False, slots=True)
class _Read:
    """One read of a conversation, from its first notice until its input is taken in.

    Attributes:
        again: Whether the conversation was noticed again since the read last looked.
        held: What the engine is told the read holds in its start wait (ADR-0349
            §7:12), until the activation it admits has ended or nothing is taken in.
        queried: How many notices :attr:`held` had when the read last began reading
            what waits: a message noticed after that may be missing from what it read.
    """

    again: bool = False
    held: HeldInput | None = None
    queried: int = 0


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
    """The chat's reader, its sensor (ADR-0293 §6, ADR-0332 §5, ADR-0349 §8).

    At most one read per conversation is in its start wait at a time. :meth:`notice`
    starts one where none is and otherwise asks it to look again; the read waits out
    the start wait, takes in as one input every waiting message no running activation
    was handed, and runs one activation for it through ``activate``. A message noticed
    once the read has taken its input in starts a read of its own, whatever runs.
    """

    def __init__(  # noqa: PLR0913 — the medium, how an activation runs, four engine seams, the writers' links, the hold, and the waits with their clock
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
        writers: Callable[[], Awaitable[Sequence[str]]] | None = None,
        hold: Callable[[ChannelIdentity], HeldInput] | None = None,
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
            writers: The activations started from no conversation that may have
                written into one, the Task Scheduler's (ADR-0350 §9:1), read as further
                candidates for what wrote an assistant message of the window; ``None``
                reads none.
            hold: Tells the engine of an input a read holds in its start wait, given
                its place (ADR-0349 §7:12): the read says which activation it admitted
                it as, and lets it go once that activation has ended or nothing was
                taken in. ``None`` tells nothing.
            start_wait: ``Settings.chat_start_wait`` (ADR-0332 §5:1): how long after
                the latest waiting message the reader waits before it takes them in,
                whatever runs (ADR-0349 §8:2). ``None``, the default, waits for nothing,
                and a composing signal then extends nothing.
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
        # A conversation is a key while a read of it has not yet taken its input in.
        self._reading: dict[str, _Read] = {}
        # The activations the conversation's reads have admitted, oldest first, each
        # until its reply is written (ADR-0349 §8:1).
        self._current: dict[str, list[str]] = {}
        # The positions handed to those activations, each until its activation has
        # ended: marked or not, no later read takes them in again (§6:6).
        self._handed: dict[str, set[int]] = {}
        # The positions each of those activations marked, by its id, until it ends.
        self._marked: dict[str, set[int]] = {}
        # Per conversation, how many times an activation was added to or left
        # `_current`: what lets a reader of `activity` tell that an activation began
        # and ended between two of its readings (ADR-0296 §4:9).
        self._turns: dict[str, int] = {}
        self._writers = writers
        self._hold = hold
        self._start_wait = None if start_wait is None else start_wait.total_seconds()
        self._composing_lapse = composing_lapse.total_seconds()
        self._composing_cap = composing_cap.total_seconds()
        self._clock = clock if clock is not None else _loop_time
        self._sleep = sleep
        # ADR-0332 §5:1, ADR-0349 §8:2: the start wait running for each conversation,
        # from the first message noticed until the read takes the messages in.
        self._waits: dict[str, _StartWait] = {}
        # Set by :meth:`close`: every start wait ends at once, and nothing is taken in.
        self._closed = asyncio.Event()

    def notice(self, conversation_id: str) -> None:
        """Tell the reader a user's message was written into a conversation (§6:1).

        It starts or extends the conversation's start wait (ADR-0332 §5:1), whatever
        runs there (ADR-0349 §8:2). It starts a read of the conversation where none has
        yet to take its input in, and otherwise that read looks again before it does.
        Nothing is started once the engine is closing: the message waits, and a restart
        takes it in (§6:9).
        """
        if self._closing():
            return
        if self._start_wait is not None:
            now = self._clock()
            wait = self._waits.get(conversation_id)
            if wait is None:
                self._waits[conversation_id] = _StartWait(first=now, latest=now)
            else:
                wait.latest = now
        read = self._reading.get(conversation_id)
        if read is not None:
            read.again = True
            if read.held is not None:
                read.held.noticed()
            return
        held = None if self._hold is None else self._hold(conversation_channel(conversation_id))
        if held is not None:
            held.noticed()
        read = _Read(held=held)
        self._reading[conversation_id] = read
        self._spawn(self._read(conversation_id, read))

    def close(self) -> None:
        """End every start wait at once: the engine is closing, so nothing is taken in.

        The messages stay waiting, and a restart takes them in (§6:9).
        """
        self._closed.set()

    def composing(self, conversation_id: str) -> None:
        """Take the hub chat page's signal that the person is typing (ADR-0332 §5:6-§5:8).

        It extends the start wait running for the conversation, the signal staying live
        for ``composing_lapse``, and does nothing where none is running (§5:7). It is not
        input: it starts no read and no wait, and is written nowhere.
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

    def running(self, conversation_id: str) -> tuple[str, ...]:
        """The activations this reader has an input in for, each until its reply is written.

        Oldest first, each from its admission to its written reply, so a conversation
        shows "working…" until the message answering each is in the transcript (§8:2),
        however many run there at once (ADR-0349 §8:1).
        """
        return tuple(self._current.get(conversation_id, ()))

    def working(self, conversation_id: str) -> str | None:
        """The newest of :meth:`running`, or ``None`` where the reader has none."""
        held = self._current.get(conversation_id)
        return held[-1] if held else None

    def activity(self) -> dict[str, tuple[int, str | None]]:
        """Per conversation this reader has read for, a count of changes and its newest one.

        The count moves each time an activation is admitted for the conversation and
        each time its reply is written, and the activation is :meth:`working`'s; every
        one is :meth:`running`'s. What the change stream reads to push a conversation's
        current state when it changes (ADR-0296 §4:9): a count that moved between two
        readings is a change even where an activation began and ended between them. A
        fresh mapping on every call.
        """
        return {one: (turns, self.working(one)) for one, turns in self._turns.items()}

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
        kept = self._marked.setdefault(taken.activation_id, set())
        for start in range(0, len(positions), _MARK_CHUNK):
            marked = await self._conversations.take_in(
                taken.conversation_id,
                positions=positions[start : start + _MARK_CHUNK],
                activation_id=taken.activation_id,
            )
            into.extend(marked)
            kept.update(marked)

    async def _read(self, conversation_id: str, read: _Read) -> None:
        """Wait out the start wait, then take what waits in as one activation's input.

        What an activation still running was handed is not taken in again (§6:6). Where
        nothing else waits, the read ends having admitted nothing, and a later notice or
        sweep looks again. What it admits it runs to its end, while a message noticed
        meanwhile starts a read of its own (ADR-0349 §8:1).
        """
        try:
            while not self._closing():
                if not await self._waited(conversation_id):
                    return
                read.again = False
                read.queried = 0 if read.held is None else read.held.notices
                waiting = await self._conversations.untaken_messages(
                    conversation_id, limit=_WAITING_ALL
                )
                if self._wait_end(conversation_id) > self._clock():
                    # A message noticed during those reads moved the wait's end, its cap
                    # still the first message's (ADR-0332 §5:1-§5:2).
                    continue
                handed = self._handed.get(conversation_id, set())
                waiting = tuple(one for one in waiting if one.position not in handed)
                if not waiting:
                    if read.again:
                        continue
                    return
                # The wait is over, at its cap or with none at all, so what was read is
                # taken in now; a message noticed during the read, which it may have
                # missed, starts a read of its own (:meth:`_admit`).
                await self._admit(conversation_id, read, waiting)
                return
        except asyncio.CancelledError:
            raise
        except ConversationStoreError:
            # The messages stay waiting, and the next notice or sweep takes them in.
            _log.warning("chat_read_failed", stage="reader", exc_info=True)
        except Exception:
            _log.exception("chat_read_failed", stage="reader")
        finally:
            self._taken(conversation_id, read)
            if read.held is not None:
                read.held.release()

    def _taken(self, conversation_id: str, read: _Read) -> None:
        """``read`` has taken its input in, or ends: a later notice starts a read anew."""
        if self._reading.get(conversation_id) is read:
            del self._reading[conversation_id]
            self._waits.pop(conversation_id, None)

    async def _admit(
        self, conversation_id: str, read: _Read, waiting: Sequence[TranscriptMessage]
    ) -> bool:
        """Bring the waiting messages in, with the window, as one activation's input.

        From here a message noticed starts a read of its own, which neither waits for
        this activation nor takes its messages in (ADR-0349 §8:1, §6:6). Once it has
        ended having marked part of what it was handed, as where the store refused the
        rest or a stop came between, the conversation is noticed again, so the next
        activation takes the rest in (ADR-0295 §3:6).

        Returns:
            Whether the activation marked anything taken in.
        """
        self._taken(conversation_id, read)
        activation_id = self._mint()
        positions = {one.position for one in waiting}
        handed = self._handed.setdefault(conversation_id, set())
        handed.update(positions)
        if read.again:
            # Noticed while what waits was read, so possibly missed by it: the message
            # is read again, by a read of its own with a start wait of its own, which
            # what this activation was handed is no part of. An act whose wait began
            # once this read had that notice waits for it there; one whose wait began
            # before does not (ADR-0349 §7:12).
            self.notice(conversation_id)
            successor = self._reading.get(conversation_id)
            if read.held is not None and successor is not None and successor.held is not None:
                read.held.moved_to(successor.held, after=read.queried)
        try:
            window = await self._window(conversation_id, waiting)
            current = self._current.setdefault(conversation_id, [])
            current.append(activation_id)
            self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1
            if read.held is not None:
                read.held.admitted(activation_id)
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
                current.remove(activation_id)
                if not current and self._current.get(conversation_id) is current:
                    del self._current[conversation_id]
                self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1
        finally:
            handed.difference_update(positions)
            if not handed and self._handed.get(conversation_id) is handed:
                del self._handed[conversation_id]
            # Only where it marked some: one that marked none (the engine closing, the
            # store refusing, or all of it gone in between) is not read again in a loop,
            # and a later notice or sweep looks again.
            kept = self._marked.pop(activation_id, set())
            if kept and positions - kept:
                self.notice(conversation_id)

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
        links = await self._links(conversation_id, recent, replied)
        return TranscriptWindow(
            conversation=conversation_channel(conversation_id),
            messages=recent,
            input_messages=tuple(waiting),
            replied_to=tuple(replied),
            links=links,
        )

    async def _links(
        self,
        conversation_id: str,
        recent: Sequence[TranscriptMessage],
        replied: Sequence[TranscriptMessage | DeletedMessage],
    ) -> dict[int, str]:
        """The activation each window message links to (ADR-0303 §7:1-§7:3).

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
        if self._written is None or not writes:
            return links
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
        # ADR-0350 §9:1: a scheduled task's activation took nothing in here, so it is
        # read as a candidate writer of its own.
        elsewhere = () if self._writers is None else await self._writers()
        candidates = list(dict.fromkeys((*links.values(), *before.values(), *elsewhere)))
        if not candidates:
            return links
        written = await self._written(conversation_id, candidates, writes)
        for position in writes:
            writer = written.get(position)
            if writer is not None and position not in links:
                links[position] = writer.activation_id
        return links

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


def _loop_time() -> float:
    """The running loop's monotonic clock, in seconds."""
    return asyncio.get_running_loop().time()
