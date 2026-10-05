"""The change stream's engine half: what one device is sent, as it happens (ADR-0298 §7).

ADR-0296 §4 makes the conversation's change stream one streaming method on the
existing wire, and ADR-0298 §7:10 divides its writing: **the changes, with their
snapshots, and the current state are the engine's**, and the device's roles and the
heartbeat are the hub's session layer's (``wire.server``). This module is the engine's
half, shared by the engine and the canonical fake engine, so both send one device the
same stream.

**The stream reads the chat space on an interval.** The conversation store has no
notification, so an open stream asks it for what happened after its cursor every
:data:`CHANGE_STREAM_POLL_SECONDS`, and at once again while a page comes back full.
That is the latency a change reaches a following device with, and its cost is one
read per open stream per interval.

**What one device is sent** is ``ConversationStore.device_changes``' as-of
membership, kept by one more rule at the moment of sending (ADR-0298 §7:5), read
again before each chunk about a conversation is sent: for a conversation the device
does not read when the stream sends to it, the stream sends
only the change that removed the device and the conversation's deletion, and never a
message, a snapshot or a current state of it. So a device catching up from an old
cursor gets a conversation it no longer reads as a removal or a deletion, with none
of the content from when it did read it. The hub's own machine is an end of every
conversation (ADR-0298 §3:2), so it is sent every change, with no snapshot.

**The current state is pushed when it changes** (ADR-0296 §4:9), and it changes when
an activation started from the conversation starts or ends: the engine's account of
what it runs (:class:`Activity`) is read on each interval, and a conversation whose
account differs from the last reading has its state read and sent, to a device that
reads it. The account carries a count that moves at every start and end, so an
activation that began and ended between two readings still sends the state it left;
what a device is sent is the state as of the reading, not every state in between. A
stream opening sends the state of each conversation running then. The state is also
read from the episodes on the conversation's place, so when the engine destroys
episodes — a forget, a conversation's forgetting, a retention sweep — the state of
every conversation the device reads is sent again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, NamedTuple

from ai_assistant.core.types import (
    ChatStreamChunk,
    ChatStreamEnd,
    ConversationDeletedChange,
    CurrentState,
    DeviceChange,
    DeviceChanges,
    DevicesChangedChange,
)
from ai_assistant.orchestration.conversations import fit_stream_chunk

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import ConversationState, RequestingDevice

#: How often an open change stream reads the chat space for what happened after its
#: cursor, in seconds: the latency a change reaches a following device with.
CHANGE_STREAM_POLL_SECONDS: Final = 0.25

#: How many changes one read of the stream asks the store for. A full page is read
#: on at once rather than after the interval, so a device far behind catches up at
#: the store's pace.
CHANGE_STREAM_PAGE: Final = 100


class Activity(NamedTuple):
    """What the engine runs from one conversation, and how often that has changed.

    Attributes:
        turns: A count that moves each time an activation started from the
            conversation begins or ends, so a reading that differs from the last by
            this alone is an activation that began and ended between the two.
        running: The activation ids running now, oldest first, ``None`` for one
            whose id is not known (ADR-0297 §5).
    """

    turns: int
    running: tuple[str | None, ...]


#: What the engine runs, per conversation an activation was ever started from.
type Running = Mapping[str, Activity]


class _EngineClosingError(Exception):
    """A read the engine refused because it had begun shutting down."""


class ChangeStream:
    """One engine's change streams over its chat space (ADR-0298 §7).

    Holds what every stream reads; :meth:`follow` is one device's stream.
    """

    def __init__(  # noqa: PLR0913 — one keyword per seam the stream reads
        self,
        *,
        chat: ConversationStore,
        running: Callable[[], Running],
        state_of: Callable[[str, Sequence[str | None]], Awaitable[ConversationState]],
        closing: Callable[[], bool],
        tracked: Callable[[Awaitable[object]], Awaitable[object]],
        max_payload_bytes: int,
        forgotten: Callable[[], int] = lambda: 0,
        poll_seconds: float = CHANGE_STREAM_POLL_SECONDS,
    ) -> None:
        """Read the chat space and the engine's account of what it runs.

        Args:
            chat: The engine's chat space.
            running: What the engine runs now, per conversation.
            state_of: A conversation's current state, given what runs from it.
            closing: Whether the engine is shutting down, which ends every stream.
            tracked: How a read is run so that shutdown drains it: each read the
                stream makes is handed through here, and one refused with a
                ``RuntimeError`` once ``closing`` holds ends the stream as shutdown
                does.
            max_payload_bytes: The contract limit a chunk is fitted to (§7:8).
            forgotten: A count that moves whenever the engine destroys episodes a
                conversation's current state is read from — a forget, a
                conversation's forgetting, a retention sweep — so every state the
                device may have been shown is sent again as it now reads.
            poll_seconds: The interval; :data:`CHANGE_STREAM_POLL_SECONDS` but in a
                test that steps it.
        """
        self._chat = chat
        self._running = running
        self._state_of = state_of
        self._closing = closing
        self._tracked = tracked
        self._max_payload_bytes = max_payload_bytes
        self._forgotten = forgotten
        self._poll_seconds = poll_seconds

    async def follow(
        self, device: RequestingDevice, *, after: int
    ) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Send ``device`` every change after ``after`` it may see, then each as it happens.

        **Whether the device reads a conversation is read again before each chunk
        about it is sent** (ADR-0298 §7:5), after the iterator has resumed from the
        chunk before: a device removed while it was being sent a page is sent nothing
        more of it but its removal. Ends only when the engine shuts down, with the
        cursor to reopen from; the device ends it otherwise, by closing the iterator.

        Raises:
            ConversationStoreError: If the chat space cannot be read.
            MemoryStoreError: If a conversation's current state cannot be read.
        """
        cursor = after
        # The first reading is taken as the stream opens, so whatever runs or ends
        # from here on differs from it; what runs at this moment is sent with the
        # first page.
        seen: Running = dict(self._running())
        due = {one for one, held in seen.items() if held.running}
        forgotten = self._forgotten()
        try:
            while not self._closing():
                page = await self._page(device, cursor)
                reading: dict[str, bool] = {}
                for entry in page.changes:
                    if not await self._sendable(device, entry, reading):
                        continue
                    yield fit_stream_chunk(
                        ChatStreamChunk(change=entry), max_bytes=self._max_payload_bytes
                    )
                    reading.clear()  # resumed: read again before the next one
                cursor = page.next_after
                now = dict(self._running())
                due |= {one for one in now.keys() | seen.keys() if now.get(one) != seen.get(one)}
                seen = now
                if (moved := self._forgotten()) != forgotten:
                    forgotten = moved
                    due |= await self._read_conversations(device)
                for conversation_id in sorted(due):
                    state = await self._state(device, conversation_id, seen)
                    if state is not None:
                        yield ChatStreamChunk(state=state)
                due = set()
                if len(page.changes) < CHANGE_STREAM_PAGE:
                    await asyncio.sleep(self._poll_seconds)
        except _EngineClosingError:
            pass
        yield ChatStreamEnd(next_after=cursor)

    async def _page(self, device: RequestingDevice, cursor: int) -> DeviceChanges:
        """The next page of the device's changes: every change, for the hub's machine."""
        if device.is_hub:
            whole = await self._read(self._chat.changes(after=cursor, limit=CHANGE_STREAM_PAGE))
            return DeviceChanges(
                changes=tuple(DeviceChange(change=one) for one in whole.changes),
                next_after=whole.next_after,
            )
        return await self._read(
            self._chat.device_changes(device.device_id, after=cursor, limit=CHANGE_STREAM_PAGE)
        )

    async def _read[T](self, work: Awaitable[T]) -> T:
        """Run one read so shutdown drains it.

        Raises:
            _EngineClosingError: If the engine refused the read because it had begun
                shutting down, which ends the stream as shutdown does.
        """
        try:
            return await self._tracked(work)  # type: ignore[return-value]
        except RuntimeError:
            if self._closing():
                raise _EngineClosingError from None
            raise

    async def _reads(self, device: RequestingDevice, conversation_id: str) -> bool:
        """Whether the device is one of the conversation's ends for reading now."""
        devices = await self._read(self._chat.conversation_devices(conversation_id))
        if devices is None:
            return False
        if device.is_hub:
            return True
        return any(one.device_id == device.device_id and one.access.reads for one in devices)

    async def _sendable(
        self, device: RequestingDevice, entry: DeviceChange, reading: dict[str, bool]
    ) -> bool:
        """Whether ``entry`` is sent to the device now (ADR-0298 §7:5).

        A change belonging to no conversation — "my devices" — is sent. A change in a
        conversation the device reads now is sent as the store gave it. For any other
        conversation, only its deletion and a change to its devices that leaves the
        device no reader — the change that removed it — are sent, never with a
        snapshot. ``reading`` holds what was read since the stream last resumed.
        """
        named = entry.conversation_id
        if device.is_hub or named is None:
            return True
        if named not in reading:
            reading[named] = await self._reads(device, named)
        return reading[named] or _ends_reading(device.device_id, entry)

    async def _read_conversations(self, device: RequestingDevice) -> set[str]:
        """Every conversation the device reads now: every one held, for the hub's."""
        found: set[str] = set()
        offset = 0
        while True:
            if device.is_hub:
                page = [
                    one.id
                    for one in await self._read(
                        self._chat.recent(limit=CHANGE_STREAM_PAGE, offset=offset)
                    )
                ]
            else:
                page = [
                    one.conversation.id
                    for one in await self._read(
                        self._chat.device_conversations(
                            device.device_id, limit=CHANGE_STREAM_PAGE, offset=offset
                        )
                    )
                ]
            found.update(page)
            if len(page) < CHANGE_STREAM_PAGE:
                return found
            offset += CHANGE_STREAM_PAGE

    async def _state(
        self, device: RequestingDevice, conversation_id: str, now: Running
    ) -> CurrentState | None:
        """The conversation's current state, where the device reads it now, else ``None``.

        Whether it reads is asked again once the state is read, so a device removed
        while the episodes were being read is not sent it (ADR-0298 §7:5).
        """
        if not await self._reads(device, conversation_id):
            return None
        held = now.get(conversation_id)
        running = () if held is None else held.running
        state = await self._read(self._state_of(conversation_id, running))
        if not await self._reads(device, conversation_id):
            return None
        return CurrentState(conversation_id=conversation_id, state=state)


def _ends_reading(device_id: str, entry: DeviceChange) -> bool:
    """Whether ``entry`` is a change a device that does not read the conversation is sent.

    The conversation's deletion, and a change to its devices after which the device
    is no reader: the change that removed it, or took its reading away (ADR-0296
    §4:8). A start removes no device. The store sends a device a change to a set it
    is in before or after, so a device that only writes in the conversation is also
    sent a change to its devices that leaves it writing; it holds no such
    conversation, so it drops nothing, and the store has already decided that a
    device in the set may see the set.
    """
    change = entry.change
    if isinstance(change, ConversationDeletedChange):
        return True
    if isinstance(change, DevicesChangedChange):
        return not any(one.device_id == device_id and one.access.reads for one in change.devices)
    return False


__all__ = [
    "CHANGE_STREAM_PAGE",
    "CHANGE_STREAM_POLL_SECONDS",
    "Activity",
    "ChangeStream",
    "Running",
]
