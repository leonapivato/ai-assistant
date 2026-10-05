"""The chat's spokes in the hub: its reader, its writer, and the adapter between (ADR-0293).

The conversation channel's medium is the hub's chat space, and its spokes are in the
hub (ADR-0293 §1:2): a **reader**, its sensor, which notices the user's new messages
and brings them in as a push, and a **writer**, its actuator, which adds the
assistant's messages. Until the phases send messages, an **adapter** writes what
today's compose stage produced (§10).

**The reader** (§6). A user's message is recorded by the act that wrote it and starts
nothing there; the engine tells this reader the conversation has a message, and the
reader takes in every message waiting in that conversation that no activation has
taken in. The assistant's own messages are never among them, so they never start an
activation (§6:1).

**One activation at a time per conversation, for now** (§6:2, §6:3, ADR-0292 §11:5).
The reader keeps one read running per conversation. A message written while an
activation started from that conversation runs lands at once and waits: it is never
refused, and when the activation ends the reader looks again and takes in everything
waiting **together, as one input**.

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
author, and the window informs and never authorizes.

**The adapter and the writer** (§9, §10). The reply the compose stage produced is
written as one assistant message into the conversation the input came from; a pass
that ends without one writes the fixed *couldn't finish* message, listing any effect
that did happen. A restart writes nothing (§9:2): an activation cancelled by a
shutdown has its episode closed as interrupted and nothing is written for it, and the
conversation's current state shows *interrupted* (§8:3).

Nothing concrete is imported: the conversation store arrives by injection and is seen
only through its Protocol (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    DeletedMessage,
    Disposition,
    MessageAuthor,
    NewMessage,
    RouteOutcome,
    TranscriptMessage,
)
from ai_assistant.orchestration.conversations import conversation_channel, fitted_message
from ai_assistant.orchestration.understanding import TranscriptWindow

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import MessageReceipt, StepOutcome, TurnOutcome

__all__ = [
    "CHAT_TURN_BUDGET",
    "CHAT_WINDOW_SIZE",
    "COULDNT_FINISH",
    "ChatInput",
    "ChatReader",
    "ChatWriter",
    "chat_effects",
    "chat_reply",
    "couldnt_finish",
]

_log = structlog.get_logger(__name__)

#: How many of the conversation's recent messages the window holds (ADR-0293 §7:5:
#: the kind declares its window size). The replay bound the episode tail had
#: (``HISTORY_REPLAY_BOUND``), so the window an input arrives with is as wide as it was.
CHAT_WINDOW_SIZE: Final = 20

#: The budget one activation the reader starts is given. The reader has no caller to
#: hand it one (ADR-0029 §4), so it takes the turn budget the interfaces give a typed
#: turn on today's wire — the gateway's ``_TURN_BUDGET`` and the CLI's ``--timeout``
#: default.
CHAT_TURN_BUDGET: Final = timedelta(seconds=60)

#: How many positions one ``take_in`` call marks: the store's own bound. Every message
#: waiting is taken in together, as one input (ADR-0293 §6:3), so an input holding more
#: is marked over several calls under the one activation's id.
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


def chat_effects(
    outcome: TurnOutcome | None, *, step: StepOutcome | None = None
) -> tuple[str, ...]:
    """The effects a pass made, as the *couldn't finish* message lists them (§9:1).

    An effect is what the pass did outside the conversation: a step it drove that ran
    its tool, and a routed operation it performed that is not a listing. ``step`` is
    the step a pass that raised had driven, where it had driven one; a pass that
    returned carries its own.
    """
    effects: list[str] = []
    driven = step if outcome is None else outcome.step
    if driven is not None and driven.disposition is Disposition.EXECUTED:
        effects.append("a step ran" if driven.tool_id is None else f"the tool {driven.tool_id} ran")
    routed = None if outcome is None else outcome.routed
    if routed is not None and routed.outcome is RouteOutcome.PERFORMED and routed.listing is None:
        effects.append(f"the operation {routed.operation.value} was performed")
    return tuple(effects)


def couldnt_finish(effects: Sequence[str] = ()) -> NewMessage:
    """The fixed *couldn't finish* message, listing any effects that did happen (§9:1)."""
    text = COULDNT_FINISH
    if effects:
        text += _EFFECTS_INTRODUCED + "".join(f"\n- {one}" for one in effects)
    return NewMessage(author=MessageAuthor.ASSISTANT, text=text)


def chat_reply(outcome: TurnOutcome | None, *, effects: Sequence[str] = ()) -> NewMessage:
    """The adapter: what a pass the reader started writes into its conversation (§10).

    The reply today's compose stage produced is written as one assistant message
    (§10:1); one held past the transcript's bound is cut there and marked cut off, as
    is a reply whose composing did not complete (§5:2, §6:16). A pass that ended
    without a reply — it raised, its composing failed, or it parked on a
    confirmation — writes the fixed *couldn't finish* message (§10:2), listing
    ``effects``.
    """
    if outcome is None or outcome.reply is None:
        return couldnt_finish(effects)
    text = outcome.reply
    cut = outcome.reply_degraded
    if len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS:
        text = text[:TRANSCRIPT_MESSAGE_MAX_CHARS]
        cut = True
    if not text.strip():
        return couldnt_finish(effects)
    return NewMessage(author=MessageAuthor.ASSISTANT, text=text, cut_off=cut)


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

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        """Write one assistant message into a conversation, or ``None`` where it is gone.

        A conversation deleted while its activation ran is not written into: deleting
        it removed the place (§2:3), and a message is never what creates one (§2:2).

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        fitted = fitted_message(conversation_id, message, max_bytes=self._max_payload_bytes)
        try:
            return await self._conversations.append_message(conversation_id, fitted)
        except UnknownConversationError:
            _log.info("chat_message_unwritten", reason="conversation_gone")
            return None


class ChatReader:
    """The chat's reader, its sensor, under the interim (ADR-0293 §6, ADR-0292 §11:5).

    One read runs per conversation at a time. :meth:`notice` starts one where none is
    running and otherwise asks the running one to look again; the read takes in every
    waiting message as one input, runs one activation for it through ``activate``,
    and looks again when that activation has ended, until nothing is waiting.
    """

    def __init__(  # noqa: PLR0913 — the medium, how an activation runs, and three engine seams
        self,
        *,
        conversations: ConversationStore,
        activate: Callable[[ChatInput], Awaitable[bool]],
        spawn: Callable[[Coroutine[None, None, None]], object],
        closing: Callable[[], bool],
        mint: Callable[[], str],
        window_size: int = CHAT_WINDOW_SIZE,
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
        """
        self._conversations = conversations
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

    def notice(self, conversation_id: str) -> None:
        """Tell the reader a user's message was written into a conversation (§6:1).

        Starts a read of the conversation where none is running; otherwise the running
        read looks again before it ends, so a message written while an activation runs
        waits and is taken in after it (§6:2, §6:3). Nothing is started once the engine
        is closing: the message waits, and a restart takes it in (§6:9).
        """
        if self._closing():
            return
        if conversation_id in self._reading:
            self._reading[conversation_id] = True
            return
        self._reading[conversation_id] = False
        self._spawn(self._read(conversation_id))

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
                self._reading[conversation_id] = False
                waiting = await self._conversations.untaken_messages(
                    conversation_id, limit=_WAITING_ALL
                )
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

    async def _admit(self, conversation_id: str, waiting: Sequence[TranscriptMessage]) -> bool:
        """Bring the waiting messages in, with the window, as one activation's input.

        Returns:
            Whether the activation marked anything taken in.
        """
        window = await self._window(conversation_id, waiting)
        activation_id = self._mint()
        self._current[conversation_id] = activation_id
        self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1
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
            self._current.pop(conversation_id, None)
            self._turns[conversation_id] = self._turns.get(conversation_id, 0) + 1

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
        return TranscriptWindow(
            conversation=conversation_channel(conversation_id),
            messages=recent,
            input_messages=tuple(waiting),
            replied_to=tuple(replied),
        )
