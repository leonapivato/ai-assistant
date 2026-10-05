"""Shared conformance suite for the ConversationStore Protocol (ADR-0074 §9).

Every ``ConversationStore`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ConversationStoreContract` and overrides the ``store`` and ``factory``
fixtures; the suite asserts only behaviour *universal* to the contract.

Two subjects, deliberately. ``store`` is the plain one, built with the
implementation's own defaults — that is what pins the *defaults* the contract
names, and it is the fixture the Protocol-triad check evaluates. ``factory``
builds a store with a movable clock, a scripted id factory and chosen durations,
because most of ADR-0074's obligations — the insert-if-absent retry, the
tombstone grace, the retention horizon and the reclaim race — are unreachable
against a store whose clock and id source are fixed.

What is **not** here, and why. ADR-0074 §9's cross-store protocol — the deletion
sweep, the retention reclaim's liveness question, the compensating delete, the
user-facing export's liveness filter — spans two stores and the coordinator
between them, so it is the capture stage's to test (`tests/orchestration/`). What
this suite holds is every obligation that is *local to one store*, including the
store-level half of the serialisation and reclaim-race clauses, so that every
implementation is held to them rather than only the wiring.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    CHAT_DEVICES_MAX,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ChatDevice,
    ConversationDeletedChange,
    ConversationStartedChange,
    DeletedMessage,
    DeviceAccess,
    DeviceConversation,
    DevicesChangedChange,
    MessageAddedChange,
    MessageAuthor,
    MessageDeletedChange,
    NewMessage,
    SendOutcome,
    SpokenDelivery,
    SpokenDeliveryState,
    TranscriptMessage,
)
from ai_assistant.testing.cancellation import held_at_its_first_await, settle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.testing.cancellation import SuspendedCall, SuspendedMidWrite

#: The instant every store fixture's clock starts at.
_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)

#: The durations the ``factory``-built stores use unless a case varies them:
#: short enough that a case can step over them, long enough that nothing expires
#: by accident.
_GRACE = _HOUR
_RETENTION = 7 * _DAY

#: The three delivery values ADR-0205 §3's cases need: what capture writes, and the
#: two a device can report. ``UNKNOWN`` is the only stampable state and the only one
#: ``record_delivery`` refuses, which is the pair of clauses those cases turn on.
_UNSTAMPED = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
_INTERRUPTED = SpokenDelivery(
    state=SpokenDeliveryState.INTERRUPTED,
    played=timedelta(seconds=3, milliseconds=200),
    rendered=timedelta(seconds=9, milliseconds=800),
)
_COMPLETE = SpokenDelivery(
    state=SpokenDeliveryState.COMPLETE,
    played=timedelta(seconds=9, milliseconds=800),
    rendered=timedelta(seconds=9, milliseconds=800),
)

#: Episode ids in the shape ADR-0283 §2 gives every episode, for the delivery-row
#: cases. Opaque to the store: it neither derives nor parses them.
_EPISODE = "activation:episode-1"
_OTHER_EPISODE = "activation:episode-2"
_LEFT_EPISODE = "activation:left"
_RIGHT_EPISODE = "activation:right"

#: The devices ADR-0293's cases use (§3): a phone that reads and writes, a watch that
#: only reads (§3:5's example), and a laptop that is in no set until a case adds it.
_PHONE = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH = ChatDevice(device_id="watch", access=DeviceAccess.READ)
_LAPTOP = ChatDevice(device_id="laptop", access=DeviceAccess.READ_WRITE)
#: A device that is an end for writing alone: it writes and is not shown the
#: conversation (ADR-0293 §3:5, ADR-0296 §4:5).
_KEYBOARD = ChatDevice(device_id="keyboard", access=DeviceAccess.WRITE)


def _said(
    text: str, *, message_id: str, device: str = "phone", replies_to: int | None = None
) -> NewMessage:
    """A user's message from ``device`` with the id the device chose (ADR-0293 §4:1)."""
    return NewMessage(
        author=MessageAuthor.USER,
        text=text,
        device_id=device,
        message_id=message_id,
        replies_to=replies_to,
    )


def _answered(text: str, *, replies_to: int | None = None, cut_off: bool = False) -> NewMessage:
    """An assistant's message through the chat's writer (ADR-0293 §6)."""
    return NewMessage(
        author=MessageAuthor.ASSISTANT, text=text, replies_to=replies_to, cut_off=cut_off
    )


async def _chat(store: ConversationStore) -> str:
    """Put the phone and the watch in "my devices" and start a conversation on them."""
    await store.set_my_devices([_PHONE, _WATCH])
    return (await store.start()).id


async def _seen_by(store: ConversationStore, device: str, *, after: int = 0) -> list[Any]:
    """Every change after ``after`` that ``device`` may see, walking small pages."""
    seen: list[Any] = []
    cursor = after
    while True:
        page = await store.device_changes(device, after=cursor, limit=2)
        seen.extend(page.changes)
        if not page.changes:
            return seen
        cursor = page.next_after


def _kinds(changes: list[Any]) -> list[str]:
    """Each change's ``kind``, in order."""
    return [one.kind for one in changes]


async def _all_changes(store: ConversationStore, *, after: int = 0) -> list[Any]:
    """Every change after ``after``, walking the pages to the end."""
    seen: list[Any] = []
    cursor = after
    while True:
        page = await store.changes(after=cursor, limit=3)
        seen.extend(page.changes)
        if not page.changes:
            return seen
        cursor = page.next_after


#: What a failure of the exclusion cases means, in one place (ADR-0074 §8): two
#: mutations of one conversation interleaved, so one of them acted on state the
#: other had already replaced.
_INTERLEAVED = (
    "two mutations of one conversation interleaved: the store's per-conversation "
    "exclusion is not holding, so a recorded turn, an activity mark, a deletion "
    "stamp and a reclaim can each act on state another has already replaced"
)

#: What a failure of the cancellation case below means (ADR-0060 §3).
#: What a failure of the input-observation cases below means, in one place.
_TORN_INPUT = (
    "the store derived its outcome from more than one observation of the argument "
    "it was handed, so a caller's mid-flight mutation reached part of the write"
)
#: The read-side version of the same failure.
_LATE_ARGUMENT = (
    "the store read its argument only after suspending, so it answered for a "
    "version of it the caller supplied after the call had begun"
)
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it before the first had finished"
)


class MovableClock:
    """A clock a case can step forward, so a deadline is reachable in a test."""

    def __init__(self, start: datetime = _NOW) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._now += delta


class ScriptedIds:
    """An id factory that hands out a fixed script, then a distinct fallback.

    ADR-0074 §1's insert-if-absent retry is only reachable through an id source
    that repeats, and the source is injected precisely so that it can.
    """

    def __init__(self, script: list[str]) -> None:
        self._script = list(script)
        self._served = 0

    def __call__(self) -> str:
        self._served += 1
        if self._script:
            return self._script.pop(0)
        return f"fallback-{self._served}"


class ConversationStoreFactory(Protocol):
    """Builds the subject with every injected seam the contract names."""

    def __call__(
        self,
        *,
        now: Callable[[], datetime],
        new_id: Callable[[], str],
        retention: timedelta | None,
        tombstone_grace: timedelta,
        purge_batch: int,
    ) -> ConversationStore:
        """Return a store wired to these seams."""
        ...


def _build(  # noqa: PLR0913 — one keyword per injected seam
    factory: ConversationStoreFactory,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], str] | None = None,
    retention: timedelta | None = _RETENTION,
    tombstone_grace: timedelta = _GRACE,
    purge_batch: int = 100,
) -> ConversationStore:
    """Build a subject, filling in whatever the case does not care about."""
    return factory(
        now=now or MovableClock(),
        new_id=new_id or ScriptedIds([]),
        retention=retention,
        tombstone_grace=tombstone_grace,
        purge_batch=purge_batch,
    )


async def _seed(
    store: ConversationStore, count: int, *, at: datetime = _NOW
) -> tuple[str, list[str]]:
    """Start a conversation and record ``count`` episodes on it, returning their ids.

    The ids are in ADR-0283 §2's ``activation:`` shape and opaque to the store.
    """
    conversation = await store.start()
    episode_ids = [f"activation:{conversation.id}-{index}" for index in range(count)]
    for index, episode_id in enumerate(episode_ids):
        await store.record_turn(
            conversation.id, episode_id=episode_id, occurred_at=at + index * _MINUTE
        )
    return conversation.id, episode_ids


async def _walk_stamped(store: ConversationStore, *, page: int) -> list[str]:
    """Walk every stamped conversation id forwards through ``after_id``."""
    seen: list[str] = []
    cursor: str | None = None
    while True:
        batch = await store.stamped_conversation_ids(limit=page, after_id=cursor)
        if not batch:
            return seen
        seen.extend(batch)
        cursor = batch[-1]


async def _walk_stamped_from(
    store: ConversationStore, *, cursor: str | None, page: int
) -> list[str]:
    """Continue a stamped walk from ``cursor``, which may name no row at all."""
    seen: list[str] = []
    while True:
        batch = await store.stamped_conversation_ids(limit=page, after_id=cursor)
        if not batch:
            return seen
        seen.extend(batch)
        cursor = batch[-1]


async def _stamp_many(store: ConversationStore, count: int) -> list[str]:
    """Start ``count`` conversations and stamp every one of them deleted."""
    started = [await store.start() for _ in range(count)]
    for conversation in started:
        assert await store.stamp_deleted(conversation.id) is True
    return sorted(one.id for one in started)


class _CancellationOp(Protocol):
    """One locked ``ConversationStore`` operation ADR-0060's case drives.

    Every ``async with self._lock`` site is a separate place the resource could be
    handed over early (#370), so the same cancelled-first / concurrent-second
    scenario runs against each rather than only against ``start``. :meth:`first`
    and :meth:`second` act on two *independent* subjects, because the clause's
    third paragraph makes the cancelled call's effect indeterminate to the caller
    — under ADR-0054's shield a cancelled write that reached its commit is durably
    written — so only the second's outcome is assertable.

    **Reads are operations too** (#492). ADR-0060 §3 binds any method that acquires
    the resource, and each of this store's five locked reads holds the connection
    lock around its own worker-thread SQL — so a regression replacing one read's
    ``_run_to_completion`` with a bare ``to_thread`` would hand the connection to a
    concurrent caller while that read's worker still used it, and every mutation
    case would still pass.
    """

    name: str

    async def prepare(self, store: ConversationStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, store: ConversationStore) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _PairedOp:
    """Two independent conversations, and one locked mutation driven against each."""

    name = ""

    def __init__(self) -> None:
        self.left = ""
        self.right = ""

    async def prepare(self, store: ConversationStore) -> None:
        """Start the two conversations the two calls act on."""
        self.left = (await store.start()).id
        self.right = (await store.start()).id

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends mid-write and then cancels."""
        raise NotImplementedError

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: ConversationStore) -> None:
        """Assert the resource survived."""
        raise NotImplementedError


class _StartOp(_PairedOp):
    """``start`` — a locked mutation like the rest, and the only one with no subject."""

    name = "start"

    async def prepare(self, store: ConversationStore) -> None:
        """Nothing to seed: ``start`` mints its own subject."""

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Mint a conversation — the call that is cancelled."""
        return store.start()

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Mint another concurrently."""
        return store.start()

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent conversation is there and every record still decodes."""
        assert await store.recent(), "the concurrent start should have landed a conversation"


class _MarkActiveOp(_PairedOp):
    """``mark_active`` — ADR-0074 §9.4's activity stamp, its own lock site."""

    name = "mark_active"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Mark the left conversation active — the call that is cancelled."""
        return store.mark_active(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Mark the right one active concurrently."""
        return store.mark_active(self.right)

    async def verify(self, store: ConversationStore) -> None:
        """Both records are still readable, the concurrent one above all."""
        assert await store.get(self.right) is not None
        assert await store.get(self.left) is not None


class _StampDeletedOp(_PairedOp):
    """``stamp_deleted`` — ADR-0074 §8's tombstone, its own lock site."""

    name = "stamp_deleted"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Stamp the left conversation deleted — the call that is cancelled."""
        return store.stamp_deleted(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Stamp the right one concurrently."""
        return store.stamp_deleted(self.right)

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent stamp landed whole: withheld from reads *and* enumerable."""
        assert await store.get(self.right) is None
        assert self.right in await store.stamped_conversation_ids()


class _DropIfEligibleOp(_PairedOp):
    """``drop_if_eligible`` — a locked mutation whether or not it drops anything.

    The two subjects are deliberately left **ineligible**. The hook builds its own
    store with the implementation's own durations, and neither the suite nor the
    hook can step a clock across the seam :class:`SuspendedMidWrite` exposes — but
    that costs this case nothing, because eligibility is judged *inside* the
    transaction the lock site opens, so an ineligible drop enters and holds the
    resource exactly as an eligible one does. What a drop *does* is pinned by the
    reclaim and tombstone cases above; what is pinned here is the resource.
    """

    name = "drop_if_eligible"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Try to reclaim the left conversation — the call that is cancelled."""
        return store.drop_if_eligible(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Try to reclaim the right one concurrently."""
        return store.drop_if_eligible(self.right)

    async def verify(self, store: ConversationStore) -> None:
        """Neither was eligible, so both records survive and reads still work."""
        assert await store.get(self.right) is not None
        assert {one.id for one in await store.recent()} >= {self.left, self.right}


class _ReadOp:
    """A locked ``ConversationStore`` read, against a store seeded the same way (#492).

    The two calls are the *same* read against independent subjects, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    def __init__(self) -> None:
        """Hold the ids the reads below address."""
        self.left = ""
        self.right = ""
        self.stamped = ""

    async def prepare(self, store: ConversationStore) -> None:
        """Two live conversations with an unstamped delivery row each, plus one stamped."""
        self.left = (await store.start()).id
        self.right = (await store.start()).id
        await store.record_turn(
            self.left, episode_id=_LEFT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        await store.record_turn(
            self.right, episode_id=_RIGHT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        self.stamped = (await store.start()).id
        assert await store.stamp_deleted(self.stamped) is True

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: ConversationStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        assert await store.get(self.right) is not None
        assert await store.deliveries(self.right, episode_ids=[_RIGHT_EPISODE]) == {
            _RIGHT_EPISODE: _UNSTAMPED
        }
        assert await store.stamped_conversation_ids() == [self.stamped]
        exported = await store.export()
        assert {one.id for one in exported.conversations} == {self.left, self.right}


class _GetOp(_ReadOp):
    """``get`` — one conversation by id, under the connection lock."""

    name = "get"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left conversation — the call that is cancelled."""
        return store.get(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one concurrently."""
        return store.get(self.right)


class _StampedConversationIdsOp(_ReadOp):
    """``stamped_conversation_ids`` — ADR-0076 §2's lexical walk, its own lock site."""

    name = "stamped_conversation_ids"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Walk the tombstones — the call that is cancelled."""
        return store.stamped_conversation_ids(limit=1)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Walk them again concurrently, from a cursor."""
        return store.stamped_conversation_ids(limit=1, after_id="")


class _RecentOp(_ReadOp):
    """``recent`` — the activity-ordered page, its own lock site."""

    name = "recent"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the newest page — the call that is cancelled."""
        return store.recent(limit=2)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read a narrower page concurrently."""
        return store.recent(limit=1)


class _ExportOp(_ReadOp):
    """``export`` — the whole-store read, its own lock site."""

    name = "export"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


class _RecordTurnOp(_PairedOp):
    """``record_turn`` — ADR-0283 §6:2's write, its own lock site."""

    name = "record_turn"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Record an episode on the left conversation — the call that is cancelled."""
        return store.record_turn(
            self.left, episode_id=_LEFT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Record an episode on the right one concurrently."""
        return store.record_turn(
            self.right, episode_id=_RIGHT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent write is whole; the cancelled one is all-or-nothing.

        "All" is both halves — the turn stamp and the delivery row — because one
        transaction writes them and a cancellation that tore them apart would leave
        a conversation recorded as having a turn whose delivery nobody can stamp.
        """
        right = await store.get(self.right)
        assert right is not None
        assert right.last_turn_at == _NOW
        assert await store.deliveries(self.right, episode_ids=[_RIGHT_EPISODE]) == {
            _RIGHT_EPISODE: _UNSTAMPED
        }
        left = await store.get(self.left)
        assert left is not None
        held = await store.deliveries(self.left, episode_ids=[_LEFT_EPISODE])
        if left.last_turn_at is None:
            assert held == {}
        else:
            assert held == {_LEFT_EPISODE: _UNSTAMPED}


class _RecordDeliveryOp(_PairedOp):
    """``record_delivery`` — ADR-0205 §3's stamp, its own lock site."""

    name = "record_delivery"

    async def prepare(self, store: ConversationStore) -> None:
        """Start the two conversations, each with an unstamped delivery row."""
        await super().prepare(store)
        await store.record_turn(
            self.left, episode_id=_LEFT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        await store.record_turn(
            self.right, episode_id=_RIGHT_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Stamp the left conversation's row — the call that is cancelled."""
        return store.record_delivery(self.left, episode_id=_LEFT_EPISODE, delivery=_COMPLETE)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Stamp the right one's concurrently."""
        return store.record_delivery(self.right, episode_id=_RIGHT_EPISODE, delivery=_COMPLETE)

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent stamp landed; the cancelled one is all-or-nothing."""
        assert await store.deliveries(self.right, episode_ids=[_RIGHT_EPISODE]) == {
            _RIGHT_EPISODE: _COMPLETE
        }
        left = await store.deliveries(self.left, episode_ids=[_LEFT_EPISODE])
        assert left in ({_LEFT_EPISODE: _UNSTAMPED}, {_LEFT_EPISODE: _COMPLETE})


class _DeliveriesOp(_ReadOp):
    """``deliveries`` — ADR-0283 §6:5's read, its own lock site."""

    name = "deliveries"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left conversation's rows — the call that is cancelled."""
        return store.deliveries(self.left, episode_ids=[_LEFT_EPISODE])

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one's concurrently."""
        return store.deliveries(self.right, episode_ids=[_RIGHT_EPISODE])


class _ChatPairedOp(_PairedOp):
    """A chat-space mutation on two conversations, both on the phone (ADR-0293)."""

    async def prepare(self, store: ConversationStore) -> None:
        """Put the phone in "my devices", then start the two conversations on it."""
        await store.set_my_devices([_PHONE])
        await super().prepare(store)


class _AppendMessageOp(_ChatPairedOp):
    """``append_message`` — ADR-0293 §4's write, its own lock site."""

    name = "append_message"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Write into the left conversation — the call that is cancelled."""
        return store.append_message(self.left, _said("left", message_id="m-1"))

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Write into the right one concurrently."""
        return store.append_message(self.right, _said("right", message_id="m-1"))

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent write is whole; the cancelled one all-or-nothing."""
        right = await store.transcript(self.right)
        left = await store.transcript(self.left)
        assert right is not None
        assert left is not None
        assert [one.position for one in right.entries] == [1]
        assert len(left.entries) in {0, 1}


class _DeleteMessageOp(_ChatPairedOp):
    """``delete_message`` — ADR-0293 §5:8's act, its own lock site."""

    name = "delete_message"

    async def prepare(self, store: ConversationStore) -> None:
        """Start the two conversations, each holding one message."""
        await super().prepare(store)
        await store.append_message(self.left, _said("left", message_id="m-1"))
        await store.append_message(self.right, _said("right", message_id="m-1"))

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Delete the left message — the call that is cancelled."""
        return store.delete_message(self.left, 1)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Delete the right one concurrently."""
        return store.delete_message(self.right, 1)

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent deletion left its marker."""
        right = await store.transcript(self.right)
        assert right is not None
        assert right.entries == (DeletedMessage(conversation_id=self.right, position=1),)


class _SetConversationDevicesOp(_ChatPairedOp):
    """``set_conversation_devices`` — ADR-0293 §3:3's act, its own lock site."""

    name = "set_conversation_devices"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Move the left conversation to the watch — the call that is cancelled."""
        return store.set_conversation_devices(self.left, [_WATCH])

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Move the right one concurrently."""
        return store.set_conversation_devices(self.right, [_WATCH])

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent change landed whole."""
        assert await store.conversation_devices(self.right) == (_WATCH,)
        assert await store.conversation_devices(self.left) in {(_PHONE,), (_WATCH,)}


class _TakeInOp(_DeleteMessageOp):
    """``take_in`` — ADR-0293 §6:6's bookkeeping, its own lock site."""

    name = "take_in"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Take in the left message — the call that is cancelled."""
        return store.take_in(self.left, positions=[1], activation_id="a-left")

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Take in the right one concurrently."""
        return store.take_in(self.right, positions=[1], activation_id="a-right")

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent mark landed."""
        assert await store.taken_in(self.right, positions=[1]) == {1: "a-right"}


class _SetMyDevicesOp(_PairedOp):
    """``set_my_devices`` — ADR-0293 §3:1's act on the chat space, its own lock site."""

    name = "set_my_devices"

    async def prepare(self, store: ConversationStore) -> None:
        """Nothing to seed: the chat space always has its set."""

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Set the phone — the call that is cancelled."""
        return store.set_my_devices([_PHONE])

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Set the watch, after it."""
        return store.set_my_devices([_WATCH])

    async def verify(self, store: ConversationStore) -> None:
        """The second set is the one standing: it was barred until the first finished."""
        assert await store.my_devices() == (_WATCH,)


class _ChatReadOp(_ReadOp):
    """A chat-space read, against two conversations on the phone holding a message each."""

    async def prepare(self, store: ConversationStore) -> None:
        """Seed as the other reads do, with the phone and a message in each."""
        await store.set_my_devices([_PHONE])
        await super().prepare(store)
        await store.append_message(self.left, _said("left", message_id="m-1"))
        await store.append_message(self.right, _said("right", message_id="m-1"))

    async def verify(self, store: ConversationStore) -> None:
        """The reads still answer, the transcript above all."""
        await super().verify(store)
        right = await store.transcript(self.right)
        assert right is not None
        assert [one.position for one in right.entries] == [1]


class _TranscriptOp(_ChatReadOp):
    """``transcript`` — ADR-0293 §5:13's read, its own lock site."""

    name = "transcript"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left transcript — the call that is cancelled."""
        return store.transcript(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one concurrently."""
        return store.transcript(self.right)


class _ChangesOp(_ChatReadOp):
    """``changes`` — ADR-0293 §5:11's read, its own lock site."""

    name = "changes"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the stream — the call that is cancelled."""
        return store.changes(after=0)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read it restricted, concurrently."""
        return store.changes(after=0, conversation_ids=[self.right])


class _MyDevicesOp(_ChatReadOp):
    """``my_devices`` — its own lock site."""

    name = "my_devices"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read "my devices" — the call that is cancelled."""
        return store.my_devices()

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read it again concurrently."""
        return store.my_devices()


class _ConversationDevicesOp(_ChatReadOp):
    """``conversation_devices`` — its own lock site."""

    name = "conversation_devices"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left conversation's devices — the call that is cancelled."""
        return store.conversation_devices(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one's concurrently."""
        return store.conversation_devices(self.right)


class _UntakenMessagesOp(_ChatReadOp):
    """``untaken_messages`` — ADR-0293 §6:3's read, its own lock site."""

    name = "untaken_messages"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left conversation's waiting messages — the call that is cancelled."""
        return store.untaken_messages(self.left)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one's concurrently."""
        return store.untaken_messages(self.right)


class _ConversationsAwaitingOp(_ChatReadOp):
    """``conversations_awaiting`` — ADR-0293 §6:9's walk, its own lock site."""

    name = "conversations_awaiting"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Walk the waiting conversations — the call that is cancelled."""
        return store.conversations_awaiting(limit=1)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Walk them again concurrently, from a cursor."""
        return store.conversations_awaiting(limit=1, after_id="")


class _TakenInOp(_ChatReadOp):
    """``taken_in`` — ADR-0293 §6:6's read, its own lock site."""

    name = "taken_in"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the left conversation's bookkeeping — the call that is cancelled."""
        return store.taken_in(self.left, positions=[1])

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the right one's concurrently."""
        return store.taken_in(self.right, positions=[1])


class _DeviceChangesOp(_ChatReadOp):
    """``device_changes`` — ADR-0296 §4:5's read, its own lock site."""

    name = "device_changes"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read the phone's changes — the call that is cancelled."""
        return store.device_changes("phone", after=0)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Read them again concurrently."""
        return store.device_changes("phone", after=0, limit=1)


class _DeviceConversationsOp(_ChatReadOp):
    """``device_conversations`` — a device's own listing, its own lock site."""

    name = "device_conversations"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """List the phone's conversations — the call that is cancelled."""
        return store.device_conversations("phone")

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """List a narrower page concurrently."""
        return store.device_conversations("phone", limit=1)


class _RemoveDeviceOp(_PairedOp):
    """``remove_device`` — ADR-0296 §3:6's revocation, its own lock site."""

    name = "remove_device"

    async def prepare(self, store: ConversationStore) -> None:
        """Put the phone and the watch in "my devices" and start both conversations on them."""
        await store.set_my_devices([_PHONE, _WATCH])
        await super().prepare(store)

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Remove the phone — the call that is cancelled."""
        return store.remove_device("phone")

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Remove the watch concurrently."""
        return store.remove_device("watch")

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent removal landed whole; the cancelled one all-or-nothing."""
        mine = {one.device_id for one in await store.my_devices()}
        left = await store.conversation_devices(self.left)
        right = await store.conversation_devices(self.right)
        assert left is not None
        assert right is not None
        assert "watch" not in mine | {one.device_id for one in (*left, *right)}
        phone_held = [
            "phone" in mine,
            *("phone" in {d.device_id for d in s} for s in (left, right)),
        ]
        assert all(phone_held) or not any(phone_held)


#: Every locked ``ConversationStore`` operation ADR-0060's case is run against:
#: each is a distinct ``async with self._lock`` site. The mutations came first
#: (#370's granularity, discharged here by #487); the five reads are the same
#: invariant on the other half of the surface (#492), since ADR-0060 §3 binds any
#: method that acquires the resource rather than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _StartOp,
    _MarkActiveOp,
    _StampDeletedOp,
    _DropIfEligibleOp,
    _RecordTurnOp,
    _RecordDeliveryOp,
    _DeliveriesOp,
    _GetOp,
    _StampedConversationIdsOp,
    _RecentOp,
    _ExportOp,
    _AppendMessageOp,
    _DeleteMessageOp,
    _SetConversationDevicesOp,
    _TakeInOp,
    _SetMyDevicesOp,
    _TranscriptOp,
    _ChangesOp,
    _MyDevicesOp,
    _ConversationDevicesOp,
    _UntakenMessagesOp,
    _ConversationsAwaitingOp,
    _TakenInOp,
    _DeviceChangesOp,
    _DeviceConversationsOp,
    _RemoveDeviceOp,
)


class ConversationStoreContract:
    """What every ``ConversationStore`` implementation must do (ADR-0074 §9)."""

    @pytest.fixture
    def store(self) -> ConversationStore:
        """The subject, built with the implementation's own defaults."""
        raise NotImplementedError

    @pytest.fixture
    def factory(self) -> ConversationStoreFactory:
        """Builds a subject with a movable clock and a scripted id source."""
        raise NotImplementedError

    @pytest.fixture
    def defaults(self) -> tuple[ConversationStore, MovableClock]:
        """A subject on the implementation's own durations, with a movable clock.

        The pair ``store`` cannot be: the *defaults* under test here are the two
        durations, and neither is reachable without stepping a clock over them.
        """
        raise NotImplementedError

    @pytest.fixture
    def purge_default(self) -> int:
        """The purge batch the ``store`` fixture's implementation defaults to."""
        raise NotImplementedError

    # --- identity and lifecycle ---------------------------------------------

    async def test_start_mints_a_fresh_conversation_that_has_no_turn_yet(
        self, store: ConversationStore
    ) -> None:
        """§1, §2: the id exists before any turn, and ``last_turn_at`` is unset."""
        first = await store.start()
        second = await store.start()

        assert first.id != second.id, "each conversation gets its own opaque id"
        assert first.last_turn_at is None, "no turn has landed yet"
        assert first.last_active_at == first.started_at, "creation is activity"
        assert await store.get(first.id) == first

    async def test_a_repeating_id_factory_never_overwrites_a_conversation(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§1: ``start`` re-mints on collision instead of clobbering or sharing."""
        store = _build(factory, new_id=ScriptedIds(["taken", "taken", "fresh"]))
        first = await store.start()
        await store.record_turn(first.id, episode_id=_EPISODE, occurred_at=_NOW)

        second = await store.start()

        assert second.id != first.id, "a colliding mint must not hand back someone else's"
        assert second.last_turn_at is None, "the new conversation is empty"
        kept = await store.get(first.id)
        assert kept is not None
        assert kept.last_turn_at == _NOW, "the first was not overwritten"

    async def test_an_id_factory_that_only_repeats_fails_loudly(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§1: an exhausted retry budget raises rather than returning a stranger's."""
        store = _build(factory, new_id=lambda: "always-the-same")
        first = await store.start()
        await store.record_turn(first.id, episode_id=_EPISODE, occurred_at=_NOW)

        with pytest.raises(ConversationStoreError):
            await store.start()

        kept = await store.get(first.id)
        assert kept is not None
        assert kept.last_turn_at == _NOW, "nothing was overwritten"

    async def test_an_id_factory_that_hands_back_something_unusable_is_this_seams_error(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§1: a broken id source is refused, and refused as the seam's own error.

        The id factory is injected, so what it returns is not something the store
        may assume: a blank string identifies nothing while looking present, and a
        value that is not even a string leaks a raw ``TypeError`` out of any store
        that probes its index with the value before validating it. Both are the
        same failure — the store must not build a conversation around an id it
        cannot use — and both must arrive as ``ConversationStoreError``.
        """
        blank = _build(factory, new_id=lambda: "   ")
        with pytest.raises(ConversationStoreError):
            await blank.start()

        # Deliberately violating the factory's own annotation: the point is a
        # source that misbehaves, which no type check at this seam can prevent.
        unusable = _build(factory, new_id=cast("Callable[[], str]", list))
        with pytest.raises(ConversationStoreError):
            await unusable.start()

    async def test_a_deadline_near_the_end_of_time_does_not_overflow(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7, §8: eligibility is a comparison, and a comparison cannot raise.

        ``checked_clock`` admits a reading a *day* short of ``datetime.max``
        (ADR-0026 §3), so a store judging ``stamp + horizon <= now`` raises
        ``OverflowError`` out of a method the contract documents as returning a
        bool. Judged as ``now - stamp >= horizon`` it cannot: the difference of
        two datetimes is always representable.
        """
        clock = MovableClock(datetime.max.replace(tzinfo=UTC) - 2 * _DAY)
        store = _build(factory, now=clock, retention=_RETENTION, tombstone_grace=_GRACE)
        conversation = await store.start()

        assert await store.drop_if_eligible(conversation.id) is False

        await store.stamp_deleted(conversation.id)
        assert await store.drop_if_eligible(conversation.id) is False

    async def test_an_unknown_id_is_refused_rather_than_created(
        self, store: ConversationStore
    ) -> None:
        """§1: a typo or a stale id never silently starts a conversation."""
        assert await store.get("nobody") is None
        for call in (
            store.mark_active("nobody"),
            store.record_delivery("nobody", episode_id=_EPISODE, delivery=_COMPLETE),
        ):
            with pytest.raises(ConversationStoreError):
                await call
        assert await store.record_turn("nobody", episode_id=_EPISODE, occurred_at=_NOW) is None

        assert await store.recent() == [], "no conversation was created by any refusal"

    async def test_mark_active_moves_activity_and_leaves_the_turn_stamp_alone(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2: activity is "someone was here"; a recorded turn is a different fact."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        started = await store.start()
        clock.advance(_HOUR)

        marked = await store.mark_active(started.id)

        assert marked.last_active_at == _NOW + _HOUR
        assert marked.last_turn_at is None, "an attempted continuation is not a recorded turn"
        assert marked.started_at == started.started_at

    # --- the ordinal invariant and the derived id ---------------------------

    # --- ADR-0205 §3: the delivery a device reports ---------------------------

    async def test_a_report_naming_no_episode_of_this_conversation_stamps_nothing(
        self, store: ConversationStore
    ) -> None:
        """ADR-0205 §1: such a report is discarded — nothing recorded, nothing raised.

        "A turn whose index entry was deleted or reclaimed, and an id belonging to
        another conversation, are ordinary states rather than faults." Since ADR-0283
        §6:4 that is an episode with no delivery row here.
        """
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert (
            await store.record_delivery(
                conversation.id, episode_id="activation:nobody", delivery=_COMPLETE
            )
            is False
        )
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {
            _EPISODE: _UNSTAMPED
        }

    async def test_a_report_against_an_unknown_or_stamped_conversation_is_refused(
        self, store: ConversationStore
    ) -> None:
        """ADR-0205 §3's two refusals, kept by ADR-0283 §6:4: an unknown or stamped id."""
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        with pytest.raises(UnknownConversationError):
            await store.record_delivery(
                "no-such-conversation", episode_id=_EPISODE, delivery=_COMPLETE
            )

        assert await store.stamp_deleted(conversation.id) is True
        with pytest.raises(UnknownConversationError):
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)

    # --- ADR-0283 §6: record_turn and the delivery rows -------------------------

    async def test_record_turn_stamps_the_turn_from_the_episode_and_not_the_clock(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§6:2: ``last_turn_at`` is set to ``occurred_at``; activity is left alone.

        The clock is moved away from the reading the call carries, so a store that
        stamped its own clock, or moved ``last_active_at`` too, is caught. The
        returned conversation is the one as written.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation = await store.start()
        clock.advance(_HOUR)
        occurred = _NOW + _MINUTE

        recorded = await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=occurred
        )

        assert recorded is not None
        assert recorded.id == conversation.id
        assert recorded.last_turn_at == occurred
        assert recorded.last_active_at == conversation.last_active_at
        assert await store.get(conversation.id) == recorded

    async def test_record_turn_without_a_delivery_writes_no_delivery_row(
        self, store: ConversationStore
    ) -> None:
        """§6:2: the row is written "where ``delivery`` is given", and only there.

        No row is what every episode not spoken carries, and it reads as no delivery
        fact at all — which is also why a report naming it stamps nothing.
        """
        conversation = await store.start()

        await store.record_turn(conversation.id, episode_id=_EPISODE, occurred_at=_NOW)

        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {}
        assert (
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)
            is False
        )
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {}

    async def test_record_turn_writes_an_unknown_delivery_row_for_the_episode(
        self, store: ConversationStore
    ) -> None:
        """§6:2: the delivery row is keyed by the episode, and reads back ``UNKNOWN``."""
        conversation = await store.start()

        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE, _OTHER_EPISODE]) == {
            _EPISODE: _UNSTAMPED
        }

    @pytest.mark.parametrize("delivery", [_INTERRUPTED, _COMPLETE], ids=["interrupted", "complete"])
    async def test_record_turn_refuses_a_delivery_that_is_not_unknown(
        self, store: ConversationStore, delivery: SpokenDelivery
    ) -> None:
        """§6:3: ``ValueError`` before any I/O, and nothing is written.

        Capture writes ``UNKNOWN`` and nothing else; a device's report reaches a row
        only through ``record_delivery``, whose stamped-once rule a delivery written
        here would bypass. Checked afterwards on both halves of the write.
        """
        conversation = await store.start()

        with pytest.raises(ValueError, match="UNKNOWN"):
            await store.record_turn(
                conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=delivery
            )

        read = await store.get(conversation.id)
        assert read is not None
        assert read.last_turn_at is None
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {}

    async def test_record_turn_refuses_a_naive_instant_or_a_blank_episode_id(
        self, store: ConversationStore
    ) -> None:
        """§6:3: both arguments go through ``core``'s annotated types, before any I/O.

        A naive instant would be localised to the host's zone (ADR-0023 §3), and a
        blank id would key a delivery row nothing can ever name.
        """
        conversation = await store.start()

        naive = datetime(2026, 6, 1)  # noqa: DTZ001 — the naive reading is the subject
        with pytest.raises(ValueError, match="occurred_at"):
            await store.record_turn(conversation.id, episode_id=_EPISODE, occurred_at=naive)
        with pytest.raises(ValueError, match="episode_id"):
            await store.record_turn(conversation.id, episode_id="  ", occurred_at=_NOW)

        read = await store.get(conversation.id)
        assert read is not None
        assert read.last_turn_at is None

    async def test_record_turn_on_an_absent_or_stamped_conversation_writes_nothing(
        self, store: ConversationStore
    ) -> None:
        """§6:2: ``None``, nothing written, and nothing raised.

        The writer reads this ``None`` as its deletion verification (§7:2), so it is
        an ordinary answer rather than ``UnknownConversationError`` — and it never
        creates the conversation it was asked about (ADR-0074 §1).
        """
        assert (
            await store.record_turn(
                "no-such-conversation", episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
            )
            is None
        )
        assert await store.get("no-such-conversation") is None

        conversation = await store.start()
        assert await store.stamp_deleted(conversation.id) is True
        assert (
            await store.record_turn(
                conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
            )
            is None
        )
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {}

    async def test_a_repeated_record_turn_never_resets_a_stamped_delivery(
        self, store: ConversationStore
    ) -> None:
        """ADR-0205 §1's stamped-once rule survives a retried capture.

        The row is written if absent, so a second ``record_turn`` naming the same
        episode leaves the device's report standing rather than putting ``UNKNOWN``
        back — after which a second report would stamp the episode twice.
        """
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        assert (
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_INTERRUPTED)
            is True
        )

        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {
            _EPISODE: _INTERRUPTED
        }
        assert (
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)
            is False
        )

    async def test_record_delivery_stamps_a_delivery_row_once(
        self, store: ConversationStore
    ) -> None:
        """§6:4: ``True`` for the stamp, ``False`` for every report after it.

        The second report carries a different value, which is what tells "left
        alone" from "written twice with the same bytes".
        """
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        first = await store.record_delivery(
            conversation.id, episode_id=_EPISODE, delivery=_INTERRUPTED
        )
        second = await store.record_delivery(
            conversation.id, episode_id=_EPISODE, delivery=_COMPLETE
        )

        assert (first, second) == (True, False)
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {
            _EPISODE: _INTERRUPTED
        }

    async def test_a_delivery_row_report_is_never_applied_across_conversations(
        self, store: ConversationStore
    ) -> None:
        """ADR-0205 §3's first condition, on the delivery rows: they are keyed by both."""
        mine = await store.start()
        theirs = await store.start()
        await store.record_turn(
            theirs.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert (
            await store.record_delivery(mine.id, episode_id=_EPISODE, delivery=_COMPLETE) is False
        )
        assert await store.deliveries(theirs.id, episode_ids=[_EPISODE]) == {_EPISODE: _UNSTAMPED}
        assert await store.deliveries(mine.id, episode_ids=[_EPISODE]) == {}

    async def test_record_delivery_refuses_an_unknown_report_on_a_delivery_row(
        self, store: ConversationStore
    ) -> None:
        """§6:4 keeps ADR-0205 §3:7's ``ValueError``, and the row stays eligible."""
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        with pytest.raises(ValueError, match="UNKNOWN"):
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_UNSTAMPED)

        assert (
            await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)
            is True
        ), "the refused call left the row eligible, so a real report still lands"

    async def test_two_reports_racing_on_one_delivery_row_leave_exactly_one_stamp(
        self, store: ConversationStore
    ) -> None:
        """ADR-0205 §3's one-step rule, on a delivery row: exactly one ``True``."""
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        reports = (_INTERRUPTED, _COMPLETE, _INTERRUPTED, _COMPLETE)

        results = await asyncio.gather(
            *(
                store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=report)
                for report in reports
            )
        )

        winners = [report for report, won in zip(reports, results, strict=True) if won]
        assert len(winners) == 1, (
            "exactly one report stamps the row: the read of the three conditions and "
            "the write are one indivisible step (ADR-0205 §3)"
        )
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {
            _EPISODE: winners[0]
        }

    async def test_deliveries_returns_only_the_rows_this_conversation_holds(
        self, store: ConversationStore
    ) -> None:
        """§6:5: rows among the named ids; anything else is simply missing.

        An id with no row, an id whose row belongs to another conversation, and a
        duplicate in the request: none of them is an error, and none is a ``None``.
        """
        mine = await store.start()
        theirs = await store.start()
        await store.record_turn(mine.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED)
        await store.record_turn(
            theirs.id, episode_id=_OTHER_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        await store.record_delivery(mine.id, episode_id=_EPISODE, delivery=_COMPLETE)

        found = await store.deliveries(
            mine.id, episode_ids=[_EPISODE, _OTHER_EPISODE, "activation:nobody", _EPISODE]
        )

        assert dict(found) == {_EPISODE: _COMPLETE}
        assert await store.deliveries(mine.id, episode_ids=[]) == {}

    async def test_deliveries_answers_an_absent_or_stamped_conversation_with_nothing(
        self, store: ConversationStore
    ) -> None:
        """§6:5: "an empty mapping for a stamped or absent conversation", not a raise."""
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert await store.deliveries("no-such-conversation", episode_ids=[_EPISODE]) == {}
        assert await store.stamp_deleted(conversation.id) is True
        assert await store.deliveries(conversation.id, episode_ids=[_EPISODE]) == {}

    async def test_deliveries_takes_at_most_a_thousand_ids(self, store: ConversationStore) -> None:
        """§6:5: "at most 1000 ``episode_ids``" — the bound, and one past it.

        The row at the far end of a full request is found, so the bound is not a
        silent truncation either.
        """
        conversation = await store.start()
        last = "activation:999"
        await store.record_turn(
            conversation.id, episode_id=last, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        full = [f"activation:{index}" for index in range(1000)]

        assert await store.deliveries(conversation.id, episode_ids=full) == {last: _UNSTAMPED}
        with pytest.raises(ValueError, match="1000"):
            await store.deliveries(conversation.id, episode_ids=[*full, "activation:1000"])

    @pytest.mark.parametrize(
        "bad",
        ["activation:episode-1", [b"activation:episode-1"], [1]],
        ids=["bare-str", "bytes-element", "int-element"],
    )
    async def test_deliveries_refuses_ids_that_are_not_a_sequence_of_str(
        self, store: ConversationStore, bad: object
    ) -> None:
        """A bare ``str`` is a ``Sequence[str]`` to the type checker and is refused.

        Read as its characters it would look up one-letter ids and answer nothing,
        which is the silent wrong answer; a non-``str`` element likewise matches
        nothing rather than failing, so it is refused before any I/O.
        """
        conversation = await store.start()

        with pytest.raises(ValueError, match="episode_ids"):
            await store.deliveries(conversation.id, episode_ids=cast("list[str]", bad))

    async def test_a_recorded_turn_and_a_deletion_issued_together_serialise(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§6:8: the exclusion covers ``record_turn``.

        Whichever lands first, the outcome is one of two consistent states: the
        episode recorded and then the conversation stamped, or the stamp first and
        ``None``. The stamp is never lost under the write — the tombstone stands, and
        the conversation stays enumerable for the sweep.
        """
        store = _build(factory)
        conversation = await store.start()

        recorded, stamped = await asyncio.gather(
            store.record_turn(
                conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
            ),
            store.stamp_deleted(conversation.id),
        )

        assert stamped is True, "the deletion is unconditional and must have happened"
        assert await store.get(conversation.id) is None, _INTERLEAVED
        assert conversation.id in await store.stamped_conversation_ids(), _INTERLEAVED
        if recorded is not None:
            assert recorded.last_turn_at == _NOW
            assert recorded.deleted_at is None, (
                f"{_INTERLEAVED}: a recorded conversation is the one as it stood before the stamp"
            )

    async def test_dropping_a_conversation_drops_its_delivery_rows(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§6:7: the delivery rows go with the record.

        Observable through the contract only where an id is reused: a conversation
        minted later under the dropped one's id must not inherit its rows, which is
        what a store that left them behind would hand it.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["reused", "reused"]))
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        await store.stamp_deleted(conversation.id)
        clock.advance(_GRACE)
        assert await store.drop_if_eligible(conversation.id) is True

        again = await store.start()

        assert again.id == conversation.id
        assert await store.deliveries(again.id, episode_ids=[_EPISODE]) == {}

    # --- the reverse lookups -------------------------------------------------

    # --- bounded, ordered reads ---------------------------------------------

    async def test_a_zero_page_is_an_empty_page(self, store: ConversationStore) -> None:
        """Asking for nothing is a question with an answer, not an unbounded read."""
        await _stamp_many(store, 2)
        await _seed(store, 2)

        assert await store.recent(limit=0) == []
        assert await store.stamped_conversation_ids(limit=0) == []

    async def test_recent_orders_by_last_activity_with_the_id_as_tie_break(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2: some total order must be named, or two stores answer differently."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["b", "a", "c"]))
        await store.start()  # b, at _NOW
        await store.start()  # a, at _NOW — ties with b
        clock.advance(_HOUR)
        await store.start()  # c, later

        listed = [one.id for one in await store.recent()]

        assert listed == ["c", "a", "b"], "activity descending, then id ascending"

    async def test_recent_orders_an_empty_conversation_beside_one_with_turns(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2: the sort key is activity, never ``last_turn_at``.

        The case a suite built only from conversations that have turns never
        reaches, and the one that catches a store sorting on ``last_turn_at``: an
        empty conversation opened a minute ago must not sink below one whose last
        turn landed an hour before.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["older", "newer"]))
        older = await store.start()
        await store.record_turn(older.id, episode_id=_EPISODE, occurred_at=_NOW)
        clock.advance(_HOUR)
        await store.start()  # newer, and empty

        listed = [one.id for one in await store.recent()]

        assert listed == ["newer", "older"], (
            "a conversation with no turn at all has to be orderable, so the key is "
            "activity — which every conversation has — and not the turn stamp"
        )

    async def test_recent_is_bounded_by_default(self, factory: ConversationStoreFactory) -> None:
        """§9.3: 50, the figure ``AuditTrail.recent`` set and ADR-0073 §2 reused."""
        store = _build(factory)
        for _ in range(52):
            await store.start()

        assert len(await store.recent()) == 50

    async def test_recent_pages_by_offset(self, factory: ConversationStoreFactory) -> None:
        """A page is the slice ``[offset : offset + limit]`` of the ordered sequence."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["a", "b", "c", "d"]))
        for _ in range(4):
            await store.start()
            clock.advance(_MINUTE)

        assert [one.id for one in await store.recent(limit=2)] == ["d", "c"]
        assert [one.id for one in await store.recent(limit=2, offset=2)] == ["b", "a"]
        assert await store.recent(limit=2, offset=9) == []

    @pytest.mark.parametrize("bad", [-1, 2**63, 2**64])
    async def test_a_paging_argument_out_of_range_is_refused(
        self, store: ConversationStore, bad: int
    ) -> None:
        """ADR-0073 §2's posture, inherited: refused, never clamped."""
        await _seed(store, 1)

        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(offset=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.stamped_conversation_ids(limit=bad)

    @pytest.mark.parametrize("bad", [1.5, "3", True], ids=["float", "str", "bool"])
    async def test_a_paging_argument_that_is_not_an_integer_is_refused(
        self, store: ConversationStore, bad: object
    ) -> None:
        """ADR-0073 §2 is about a *signed 64-bit integer*, so the type is the range.

        Without this, the two backends disagree about the same bad argument —
        ``LIMIT 1.5`` reaches SQLite as a datatype error while an in-memory store
        slices a list and raises ``TypeError`` — which is the failure that rule
        exists to stop. ``True`` is in the list because ``bool`` is an ``int``
        subclass and is not a page size.
        """
        await _seed(store, 1)
        limit = cast("int", bad)

        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=limit)
        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(offset=limit)
        with pytest.raises(ValueError, match="must be an int"):
            await store.stamped_conversation_ids(limit=limit)

    async def test_recent_has_no_none_spelling_for_its_limit(
        self, store: ConversationStore
    ) -> None:
        """``recent``'s ``limit`` has a named default of 50 and no ``None`` spelling.

        So passing one is the same malformed argument as any other non-integer.
        """
        await _seed(store, 1)

        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=cast("int", None))

    async def test_a_fresh_conversation_carries_no_observation_watermark(
        self, store: ConversationStore
    ) -> None:
        """ADR-0285 §4: the cursor is gone from the record and from the contract.

        Asserted on what every presenting read hands back rather than on the type
        alone, so an implementation that went on carrying the member — or an
        operation to write it — fails here rather than passing silently.
        """
        conversation_id, _ = await _seed(store, 1)

        read = await store.get(conversation_id)
        assert read is not None
        assert "observed_through" not in type(read).model_fields
        assert not hasattr(store, "record_observed")

    # --- the tombstone -------------------------------------------------------

    async def test_a_stamped_conversation_is_hidden_from_every_presenting_read(
        self, store: ConversationStore
    ) -> None:
        """§9: the pair that keeps a tombstone from being a readable record."""
        conversation_id, _ = await _seed(store, 2)
        await store.record_turn(
            conversation_id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )

        assert await store.stamp_deleted(conversation_id) is True

        assert await store.get(conversation_id) is None
        assert await store.recent() == []
        assert (await store.export()).conversations == ()
        assert await store.deliveries(conversation_id, episode_ids=[_EPISODE]) == {}
        with pytest.raises(ConversationStoreError):
            await store.record_delivery(conversation_id, episode_id=_EPISODE, delivery=_COMPLETE)

        assert await store.stamped_conversation_ids() == [conversation_id], (
            "the sweep must still be able to find the tombstone it has to finish"
        )

    async def test_writing_to_a_stamped_conversation_is_refused(
        self, store: ConversationStore
    ) -> None:
        """§8: the stamp is what stops a racing capture slipping a turn in behind it."""
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)

        assert (
            await store.record_turn(conversation_id, episode_id=_EPISODE, occurred_at=_NOW) is None
        )
        with pytest.raises(ConversationStoreError):
            await store.mark_active(conversation_id)

    async def test_stamping_reports_whether_it_acted_and_never_creates(
        self, store: ConversationStore
    ) -> None:
        """§8: the protocol is re-runnable, so a repeat is a no-op rather than an error."""
        conversation_id, _ = await _seed(store, 1)

        assert await store.stamp_deleted(conversation_id) is True
        assert await store.stamp_deleted(conversation_id) is False
        assert await store.stamp_deleted("nobody") is False
        assert await store.recent() == [], "refusing to stamp an unknown id creates nothing"

    async def test_a_tombstone_survives_its_grace_and_is_dropped_after_it(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§8: the grace keeps the record naming a pending intent alive past the deletion."""
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE)
        conversation_id, _ = await _seed(store, 2)
        await store.stamp_deleted(conversation_id)

        assert await store.drop_if_eligible(conversation_id) is False, "still inside the grace"
        assert await store.stamped_conversation_ids() == [conversation_id], (
            "the record naming the pending deletion is still there to be found"
        )

        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True

    async def test_a_reclaim_is_idempotent_and_a_late_capture_is_refused(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§8: the residue this ADR accepts, pinned rather than rediscovered.

        Once the tombstone has been reclaimed, a capture that lands *after* it has
        nowhere to record itself: ``record_turn`` answers ``None`` and writes nothing,
        which the writer reads as the deletion verification failing (ADR-0283 §7:2).
        The reclaim itself can run any number of times.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)
        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True
        assert await store.drop_if_eligible(conversation_id) is False, "a re-run is a no-op"

        assert (
            await store.record_turn(conversation_id, episode_id=_EPISODE, occurred_at=clock())
            is None
        )
        assert await store.get(conversation_id) is None, "and the late write created nothing"

    # --- enumerating the tombstones (ADR-0076) -------------------------------

    async def test_a_stamped_conversation_is_enumerable_and_an_unstamped_one_is_not(
        self, store: ConversationStore
    ) -> None:
        """ADR-0076 §4.1: the pair, so returning everything passes neither half.

        This is the read the whole ADR exists for. Without it a process that died
        between §8's stamp and its drop left a tombstone no later run could
        rediscover, so the deletion was never finished.
        """
        stamped, _ = await _seed(store, 1)
        live, _ = await _seed(store, 1)
        await store.stamp_deleted(stamped)

        assert await store.stamped_conversation_ids() == [stamped]
        assert live not in await store.stamped_conversation_ids()

    async def test_a_dropped_conversation_is_not_enumerated(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.2: the trivially-true half, and what makes the walk terminate."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)
        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True

        assert await store.stamped_conversation_ids() == []

    async def test_grace_is_not_a_filter_on_the_enumeration(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.3: a conversation stamped a moment ago is still enumerated.

        §8's step 2 destroys a stamped conversation's episodes **whether or not**
        its grace has elapsed; only step 3 is conditional, and step 3 is
        ``drop_if_eligible``, which judges for itself under the exclusion. An
        implementation that pre-filtered on the grace here would hide exactly the
        tombstones whose episodes still have to be destroyed.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE)
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)

        assert await store.stamped_conversation_ids() == [conversation_id]
        assert await store.drop_if_eligible(conversation_id) is False, "still inside the grace"

    async def test_a_crashed_deletion_is_rediscoverable_and_finishable(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.4: the clause this ADR exists for.

        The interrupted §8 sequence: stamp, then *nothing* — no purge, no drop, as
        a process death between steps leaves it. A later run must be able to find
        the tombstone and finish the deletion once the grace has elapsed; which
        episodes it destroys is the channel's to answer (ADR-0283 §7:3), not this
        store's.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE)
        conversation_id, _ = await _seed(store, 3)
        await store.stamp_deleted(conversation_id)

        assert await store.stamped_conversation_ids() == [conversation_id]

        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True
        assert await store.stamped_conversation_ids() == []

    async def test_the_stamped_walk_reaches_every_batch(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.5: more tombstones than one batch, drained, each seen once."""
        store = _build(factory, purge_batch=2)
        ids = await _stamp_many(store, 7)

        walked = await _walk_stamped(store, page=2)

        assert walked == ids, "the walk must visit every tombstone exactly once, id ascending"

    async def test_the_stamped_walk_survives_its_own_drops(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.6: the clause the lexical cursor exists for.

        The ordinary sweep sequence drops the rows it is walking, so by the time it
        asks for the next batch the id it carries names nothing. An implementation
        resolving the cursor by looking the row up passes every other clause here
        and stalls after its first page in ordinary use — exactly when the sweep is
        working correctly.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE, purge_batch=2)
        ids = await _stamp_many(store, 7)
        clock.advance(_GRACE)

        seen: list[str] = []
        cursor: str | None = None
        while True:
            batch = await store.stamped_conversation_ids(limit=2, after_id=cursor)
            if not batch:
                break
            seen.extend(batch)
            for conversation_id in batch:
                assert await store.drop_if_eligible(conversation_id) is True
            cursor = batch[-1]  # this row is now gone

        assert seen == ids, "a cursor placed by row lookup would stall after the first page"

    async def test_a_row_dropped_by_another_sweeper_still_positions_the_walk(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.6, from outside: someone else drops the cursor row.

        Same case, arriving from a second caller rather than from this walk's own
        drops — which is the one the start-up sweep actually meets.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE, purge_batch=2)
        ids = await _stamp_many(store, 5)
        clock.advance(_GRACE)

        first = await store.stamped_conversation_ids(limit=2)
        assert first == ids[:2]
        # A *second* sweeper finishes the conversation this walk is about to page
        # from, so the cursor names no row by the time it is used.
        assert await store.drop_if_eligible(first[-1]) is True

        rest = await _walk_stamped_from(store, cursor=first[-1], page=2)

        assert rest == ids[2:], "the walk must reach the remaining tombstones and terminate"

    async def test_the_enumeration_is_id_ascending_and_bounded_by_the_configured_batch(
        self, store: ConversationStore, purge_default: int
    ) -> None:
        """ADR-0076 §4.7: the order, and the default — 100, the purge walk's figure.

        Exercised with more than a batch of tombstones so the figure is really
        asserted: a suite testing only small explicit values never reaches either
        (ADR-0073 §8), and an unasserted default is two stores answering the same
        sweep differently.
        """
        ids = await _stamp_many(store, purge_default + 2)

        page = await store.stamped_conversation_ids()

        assert len(page) == purge_default
        assert page == ids[:purge_default], "id ascending, and the batch is the configured one"

    async def test_the_stamped_enumerations_paging_posture(self, store: ConversationStore) -> None:
        """ADR-0076 §4.8: out of range refused, ``limit=0`` empty, an absent cursor placed.

        The last half is the negative of the lexical-cursor clause: ``after_id``
        names a *position in the id space*, so an id naming no row is a perfectly
        good cursor rather than an error — which is what keeps a resumed walk
        working after its rows have been dropped.
        """
        ids = await _stamp_many(store, 2)

        for bad in (-1, 2**63, 2**64):
            with pytest.raises(ValueError, match="must be an int"):
                await store.stamped_conversation_ids(limit=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.stamped_conversation_ids(limit=cast("int", 1.5))
        assert await store.stamped_conversation_ids(limit=0) == []
        assert await store.stamped_conversation_ids(after_id="") == ids, (
            "a cursor before every id positions the walk at the beginning"
        )
        assert await store.stamped_conversation_ids(after_id=ids[-1] + "￿") == [], (
            "a cursor naming no row positions the walk rather than raising"
        )

    async def test_the_enumeration_is_not_a_way_around_the_front_door(
        self, store: ConversationStore
    ) -> None:
        """ADR-0076 §4.9: every other read still refuses the conversation it names.

        Asserted on the *same* conversation while it is enumerable here, because
        that pair is the whole of what bounds this method: the return shape and the
        reads that still say nothing.
        """
        conversation_id, _ = await _seed(store, 1)
        await store.record_turn(
            conversation_id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        await store.stamp_deleted(conversation_id)

        assert await store.stamped_conversation_ids() == [conversation_id]

        assert await store.get(conversation_id) is None
        assert await store.recent() == []
        assert (await store.export()).conversations == ()
        assert await store.deliveries(conversation_id, episode_ids=[_EPISODE]) == {}

    async def test_an_unknown_id_raises_the_narrow_subclass(self, store: ConversationStore) -> None:
        """ADR-0076 §4.10, first half: every method that refuses an unknown id.

        The sweep's whole use for the subclass is telling *someone else already
        finished this one* from *stop*, so an implementation that raised the base
        class here would leave a start-up sweep unable to carry on past a
        conversation another sweeper had just dropped.
        """
        for call in (
            store.mark_active("nobody"),
            store.record_delivery("nobody", episode_id=_EPISODE, delivery=_COMPLETE),
        ):
            with pytest.raises(UnknownConversationError):
                await call

    async def test_a_store_fault_raises_the_base_class_and_not_the_subclass(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0076 §4.10, second half: a subclass raised for everything buys less than nothing.

        A non-conforming clock reading is a genuine store fault every
        implementation reaches (ADR-0026 §7), and it must arrive as the base class:
        a sweep that treated it as "already done" would silently skip the
        conversations after it and report success.
        """
        store = _build(factory, now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001 — the fault

        with pytest.raises(ConversationStoreError) as raised:
            await store.start()

        assert not isinstance(raised.value, UnknownConversationError), (
            "a store fault is not 'this conversation is already gone', and a sweep "
            "that read it as one would abandon the rest of its work quietly"
        )

    # --- retention reclaim ---------------------------------------------------

    async def test_an_idle_conversation_is_reclaimed_only_once_past_the_horizon(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7: eligibility is activity against the horizon in force when reclaim runs."""
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_RETENTION)
        conversation = await store.start()

        clock.advance(_RETENTION - _MINUTE)
        assert await store.drop_if_eligible(conversation.id) is False

        clock.advance(_MINUTE)
        assert await store.drop_if_eligible(conversation.id) is True
        assert await store.get(conversation.id) is None

    async def test_the_default_retention_horizon_is_finite(
        self, defaults: tuple[ConversationStore, MovableClock]
    ) -> None:
        """§7: an unset horizon is finite, never unbounded retention.

        The pair with the explicit-``None`` case below is what catches an
        implementation that inherited a nullable duration's ``None`` default and so
        ships unbounded retention while passing every other clause.
        """
        store, clock = defaults
        conversation = await store.start()

        clock.advance(3650 * _DAY)

        assert await store.drop_if_eligible(conversation.id) is True, (
            "a store whose default horizon were unset would refuse this forever"
        )

    async def test_the_default_tombstone_grace_is_positive_and_finite(
        self, defaults: tuple[ConversationStore, MovableClock]
    ) -> None:
        """§8: unset stamps a positive finite grace — the two failures, both closed.

        Zero would drop the record immediately, which is the orphaned late write the
        tombstone exists to catch; unbounded would keep every deleted
        conversation's record forever.
        """
        store, clock = defaults
        conversation = await store.start()
        await store.stamp_deleted(conversation.id)

        assert await store.drop_if_eligible(conversation.id) is False, "the grace is positive"

        clock.advance(3650 * _DAY)

        assert await store.drop_if_eligible(conversation.id) is True, "the grace is finite"

    async def test_activity_within_the_horizon_defeats_a_reclaim(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9.4: the boundary, in the direction where the continuation wins."""
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_RETENTION)
        conversation = await store.start()
        clock.advance(_RETENTION)

        await store.mark_active(conversation.id)

        assert await store.drop_if_eligible(conversation.id) is False, (
            "eligibility is re-checked under the exclusion, so a continuation that "
            "landed first makes the conversation ineligible and the reclaim skips it"
        )
        assert await store.get(conversation.id) is not None

    async def test_a_reclaim_that_lands_first_refuses_the_continuation_behind_it(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9.4: the boundary, in the direction where the reclaim wins."""
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_RETENTION)
        conversation = await store.start()
        clock.advance(_RETENTION)

        assert await store.drop_if_eligible(conversation.id) is True

        with pytest.raises(ConversationStoreError):
            await store.mark_active(conversation.id)

    async def test_a_reclaim_racing_a_continuation_resolves_one_way_or_the_other(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9.4: issued together, the two never half-happen.

        A reclaim whose eligibility is decided outside the exclusion passes a
        single-threaded test and destroys a conversation the user just returned to,
        so the assertion is on the *conjunction*: dropped implies gone and the mark
        refused; not dropped implies the mark landed and the record stands.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_RETENTION)
        conversation = await store.start()
        clock.advance(_RETENTION)

        dropped, marked = await asyncio.gather(
            store.drop_if_eligible(conversation.id),
            store.mark_active(conversation.id),
            return_exceptions=True,
        )

        surviving = await store.get(conversation.id)
        if dropped is True:
            assert isinstance(marked, ConversationStoreError), _INTERLEAVED
            assert surviving is None, _INTERLEAVED
        else:
            assert dropped is False
            assert not isinstance(marked, BaseException), marked
            assert surviving is not None, _INTERLEAVED
            assert surviving.last_active_at == clock(), _INTERLEAVED

    async def test_reclaim_is_switched_off_when_retention_is_unset(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7: "keep the episodes forever" is not a setting under which records vanish."""
        clock = MovableClock()
        store = _build(factory, now=clock, retention=None)
        conversation = await store.start()

        clock.advance(1000 * _DAY)

        assert await store.drop_if_eligible(conversation.id) is False, (
            "with no duration there is no horizon to compare against, so the "
            "comparison is switched off rather than read as 'everything is past it'"
        )
        assert await store.get(conversation.id) is not None

    async def test_a_deletion_is_reclaimed_even_when_retention_is_unset(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7: under ``None``, deletion is the only thing that removes a conversation."""
        clock = MovableClock()
        store = _build(factory, now=clock, retention=None)
        conversation = await store.start()
        await store.stamp_deleted(conversation.id)

        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation.id) is True

    # --- export --------------------------------------------------------------

    async def test_export_carries_the_conversations_in_order_and_no_history(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9, ADR-0283 §4:3: the store's own snapshot, ordered as its reads are.

        The conversations and nothing else: a recorded episode and its delivery row
        leave no trace in the document beyond the conversation's own ``last_turn_at``.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["first", "second"]))
        first = await store.start()
        await store.record_turn(
            first.id, episode_id=_EPISODE, occurred_at=_NOW + _MINUTE, delivery=_UNSTAMPED
        )
        clock.advance(_HOUR)
        second = await store.start()

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [second.id, first.id]
        assert exported.conversations[1].last_turn_at == _NOW + _MINUTE
        assert exported.schema_version == 6
        assert set(exported.model_dump()) == {
            "schema_version",
            "exported_at",
            "conversations",
            "messages",
        }
        assert exported.messages == ()

    async def test_export_omits_a_stamped_conversation(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9: a stamped conversation is deleted as far as every read is concerned."""
        store = _build(factory, new_id=ScriptedIds(["kept", "stamped"]))
        kept, _ = await _seed(store, 1)
        stamped, _ = await _seed(store, 1)
        await store.stamp_deleted(stamped)

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [kept]

    async def test_export_carries_an_empty_conversation(self, store: ConversationStore) -> None:
        """A conversation with no turns is state the user holds; it exports as itself."""
        conversation = await store.start()

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [conversation.id]
        assert exported.conversations[0].last_turn_at is None

    # --- the chat space: the transcript (ADR-0293 §4, §5) --------------------

    async def test_a_started_conversation_is_empty_and_on_my_devices(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2:1, §3:1: starting creates an empty conversation shown on "my devices"."""
        store = _build(factory, new_id=ScriptedIds(["c-1"]))
        await store.set_my_devices([_WATCH, _PHONE])

        started = await store.start()

        page = await store.transcript(started.id)
        assert page is not None
        assert page.entries == ()
        assert await store.conversation_devices(started.id) == (_PHONE, _WATCH)
        changes = await _all_changes(store)
        assert changes[-1] == ConversationStartedChange(
            seq=changes[-1].seq, conversation_id="c-1", devices=(_PHONE, _WATCH)
        )

    async def test_a_message_is_recorded_at_the_next_position_and_answers_received(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§4:4, §5:2: the send answers with the position; the entry is exactly it."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation = await _chat(store)
        clock.advance(_MINUTE)

        first = await store.append_message(
            conversation, _said("book the campsite", message_id="m-1")
        )
        second = await store.append_message(conversation, _answered("Which weekend?", replies_to=1))

        assert (first.outcome, first.position) == (SendOutcome.RECORDED, 1)
        assert (second.outcome, second.position) == (SendOutcome.RECORDED, 2)
        page = await store.transcript(conversation)
        assert page is not None
        assert page.entries == (
            TranscriptMessage(
                conversation_id=conversation,
                position=1,
                written_at=_NOW + _MINUTE,
                author=MessageAuthor.USER,
                text="book the campsite",
                device_id="phone",
                message_id="m-1",
            ),
            TranscriptMessage(
                conversation_id=conversation,
                position=2,
                written_at=_NOW + _MINUTE,
                author=MessageAuthor.ASSISTANT,
                text="Which weekend?",
                replies_to=1,
            ),
        )

    async def test_a_repeated_send_is_the_same_message(self, store: ConversationStore) -> None:
        """§4:2: the same device and id is one entry and one change, at one position."""
        conversation = await _chat(store)
        first = await store.append_message(conversation, _said("hello", message_id="m-1"))
        before = await store.changes(after=0)

        again = await store.append_message(conversation, _said("hello again", message_id="m-1"))

        assert (again.outcome, again.position) == (SendOutcome.REPEATED, first.position)
        page = await store.transcript(conversation)
        assert page is not None
        assert [one.position for one in page.entries] == [1]
        assert (await store.changes(after=before.next_after)).changes == ()

    async def test_a_late_repeat_of_a_deleted_message_does_not_come_back(
        self, store: ConversationStore
    ) -> None:
        """§4:3, §5:12: the marker keeps the id, so the repeat is still recognised."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("oops", message_id="m-1"))
        assert await store.delete_message(conversation, 1) is True

        again = await store.append_message(conversation, _said("oops", message_id="m-1"))

        assert (again.outcome, again.position) == (SendOutcome.REPEATED, 1)
        page = await store.transcript(conversation)
        assert page is not None
        assert page.entries == (DeletedMessage(conversation_id=conversation, position=1),)

    async def test_one_id_from_two_devices_is_two_messages(self, store: ConversationStore) -> None:
        """§4:1: a message id is unique per device, not across devices."""
        await store.set_my_devices([_PHONE, _LAPTOP])
        conversation = (await store.start()).id

        one = await store.append_message(conversation, _said("a", message_id="m-1"))
        other = await store.append_message(
            conversation, _said("b", message_id="m-1", device="laptop")
        )

        assert (one.position, other.position) == (1, 2)
        assert other.outcome is SendOutcome.RECORDED

    async def test_only_a_conversations_writing_devices_write_in_it(
        self, store: ConversationStore
    ) -> None:
        """§7:2, §3:5: a device outside the set, or one that only reads, writes nothing."""
        conversation = await _chat(store)
        before = await store.changes(after=0)

        stranger = await store.append_message(
            conversation, _said("hi", message_id="m-1", device="laptop")
        )
        reader = await store.append_message(
            conversation, _said("hi", message_id="m-2", device="watch")
        )

        assert (stranger.outcome, stranger.position) == (SendOutcome.NOT_AN_END, None)
        assert (reader.outcome, reader.position) == (SendOutcome.NOT_AN_END, None)
        page = await store.transcript(conversation)
        assert page is not None
        assert page.entries == ()
        assert (await store.changes(after=before.next_after)).changes == ()

    async def test_a_reply_names_an_earlier_message_deleted_or_not(
        self, store: ConversationStore
    ) -> None:
        """§4:5, §5:8: a reply to a deleted message is recorded; one to none is refused."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("first", message_id="m-1"))
        assert await store.delete_message(conversation, 1) is True

        to_deleted = await store.append_message(
            conversation, _said("about that", message_id="m-2", replies_to=1)
        )
        to_nothing = await store.append_message(conversation, _answered("?", replies_to=3))

        assert (to_deleted.outcome, to_deleted.position) == (SendOutcome.RECORDED, 2)
        assert (to_nothing.outcome, to_nothing.position) == (SendOutcome.NO_SUCH_REPLY, None)
        page = await store.transcript(conversation)
        assert page is not None
        assert [one.position for one in page.entries] == [1, 2]

    async def test_a_cut_off_answer_is_recorded_as_one(self, store: ConversationStore) -> None:
        """§6:16: what was sent is recorded, marked cut off."""
        conversation = await _chat(store)

        await store.append_message(conversation, _answered("Looking into", cut_off=True))

        page = await store.transcript(conversation)
        assert page is not None
        (entry,) = page.entries
        assert isinstance(entry, TranscriptMessage)
        assert entry.cut_off is True

    async def test_deleting_a_message_leaves_its_marker_and_its_reply(
        self, store: ConversationStore
    ) -> None:
        """§5:8, §5:12: the message alone goes; its reply stays naming it; no reuse."""
        conversation = await _chat(store)
        await store.append_message(conversation, _answered("Pinecrest it is"))
        await store.append_message(
            conversation, _said("no, the other one", message_id="m-1", replies_to=1)
        )

        assert await store.delete_message(conversation, 1) is True
        assert await store.delete_message(conversation, 1) is False
        assert await store.delete_message(conversation, 9) is False
        later = await store.append_message(conversation, _answered("Sorry."))

        assert later.position == 3
        page = await store.transcript(conversation)
        assert page is not None
        assert page.entries[0] == DeletedMessage(conversation_id=conversation, position=1)
        reply = page.entries[1]
        assert isinstance(reply, TranscriptMessage)
        assert reply.replies_to == 1

    async def test_a_deleted_messages_text_leaves_the_change_stream(
        self, store: ConversationStore
    ) -> None:
        """§5:10, §5:12: the addition goes from the stream and a deletion is recorded."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("my PIN is 1234", message_id="m-1"))

        await store.delete_message(conversation, 1)

        changes = await _all_changes(store)
        assert not any(isinstance(one, MessageAddedChange) for one in changes)
        assert isinstance(changes[-1], MessageDeletedChange)
        assert changes[-1].marker == DeletedMessage(conversation_id=conversation, position=1)
        assert "1234" not in repr(changes)

    async def test_the_transcript_acts_refuse_an_unknown_or_stamped_conversation(
        self, store: ConversationStore
    ) -> None:
        """§2:2: a message never creates a conversation; a deleted one takes none."""
        stamped = await _chat(store)
        assert await store.stamp_deleted(stamped) is True

        for conversation_id in ("nobody", stamped):
            with pytest.raises(UnknownConversationError):
                await store.append_message(conversation_id, _said("hi", message_id="m-1"))
            with pytest.raises(UnknownConversationError):
                await store.delete_message(conversation_id, 1)
            with pytest.raises(UnknownConversationError):
                await store.set_conversation_devices(conversation_id, [_PHONE])
            with pytest.raises(UnknownConversationError):
                await store.take_in(conversation_id, positions=[1], activation_id="a-1")
            assert await store.transcript(conversation_id) is None
            assert await store.conversation_devices(conversation_id) is None
            assert await store.untaken_messages(conversation_id) == ()
            assert await store.taken_in(conversation_id, positions=[1]) == {}

    async def test_a_message_over_the_size_bound_cannot_be_sent(self) -> None:
        """§4:7: refused with the error on the send, so nothing reaches a store."""
        with pytest.raises(ValidationError):
            _said("x" * (TRANSCRIPT_MESSAGE_MAX_CHARS + 1), message_id="m-1")

    async def test_the_snapshot_is_the_recent_messages_and_older_ones_load_by_range(
        self, store: ConversationStore
    ) -> None:
        """§5:13: the last ``limit`` entries, then those before a position."""
        conversation = await _chat(store)
        for index in range(1, 6):
            await store.append_message(conversation, _said(f"m{index}", message_id=f"m-{index}"))
        await store.delete_message(conversation, 4)

        snapshot = await store.transcript(conversation, limit=3)
        older = await store.transcript(conversation, before=3, limit=10)
        nothing = await store.transcript(conversation, limit=0)
        # A limit above the count but below twice it, and the default: every entry.
        wider = await store.transcript(conversation, limit=6)
        default = await store.transcript(conversation)
        assert wider is not None
        assert default is not None
        assert [one.position for one in wider.entries] == [1, 2, 3, 4, 5]
        assert default == wider

        assert snapshot is not None
        assert older is not None
        assert nothing is not None
        assert [one.position for one in snapshot.entries] == [3, 4, 5]
        assert isinstance(snapshot.entries[1], DeletedMessage)
        assert [one.position for one in older.entries] == [1, 2]
        assert nothing.entries == ()
        assert snapshot.as_of == (await store.changes(after=0)).next_after

    async def test_the_transcript_reads_refuse_a_malformed_page(
        self, store: ConversationStore
    ) -> None:
        """ADR-0073 §2's posture on the new reads, before any I/O."""
        conversation = await _chat(store)
        for bad in (0, -1, 1.5, True, 2**63):
            with pytest.raises(ValueError, match="before"):
                await store.transcript(conversation, before=bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="position"):
                await store.delete_message(conversation, bad)  # type: ignore[arg-type]
        for bad in (-1, 1.5, True, 2**63):
            with pytest.raises(ValueError, match="limit"):
                await store.transcript(conversation, limit=bad)  # type: ignore[arg-type]

    # --- the chat space: the change stream (ADR-0293 §5:10, §5:11) ---------------

    async def test_every_change_is_numbered_across_the_chat_space(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§5:10: one counter, increasing, over every kind of change."""
        store = _build(factory, new_id=ScriptedIds(["c-1", "c-2"]))
        await store.set_my_devices([_PHONE])
        first = (await store.start()).id
        second = (await store.start()).id
        await store.append_message(first, _said("a", message_id="m-1"))
        await store.append_message(second, _said("b", message_id="m-1"))
        await store.set_conversation_devices(second, [_PHONE, _WATCH])
        await store.delete_message(first, 1)
        await store.stamp_deleted(second)

        changes = await _all_changes(store)

        seqs = [one.seq for one in changes]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        assert [type(one) for one in changes] == [
            DevicesChangedChange,
            ConversationStartedChange,
            MessageDeletedChange,
            ConversationDeletedChange,
        ]
        assert changes[0].conversation_id is None
        assert (changes[2].conversation_id, changes[3].conversation_id) == (first, second)

    async def test_catching_up_is_every_change_after_the_cursor(
        self, store: ConversationStore
    ) -> None:
        """§5:11: one request after a cursor, paged, never repeating a change."""
        conversation = await _chat(store)
        middle = await store.changes(after=0)
        for index in range(5):
            await store.append_message(conversation, _said(str(index), message_id=f"m-{index}"))

        first = await store.changes(after=middle.next_after, limit=2)
        rest = await store.changes(after=first.next_after)
        done = await store.changes(after=rest.next_after)

        added = [*first.changes, *rest.changes]
        assert len(first.changes) == 2
        assert [one.message.position for one in added if isinstance(one, MessageAddedChange)] == [
            1,
            2,
            3,
            4,
            5,
        ]
        assert done.changes == ()
        assert done.next_after == rest.next_after

    async def test_a_restricted_read_carries_its_conversations_and_my_devices(
        self, store: ConversationStore
    ) -> None:
        """§5:11: a reader of some conversations sees theirs and "my devices", and moves on."""
        await store.set_my_devices([_PHONE])
        mine = (await store.start()).id
        other = (await store.start()).id
        await store.append_message(other, _said("not yours", message_id="m-1"))
        await store.set_my_devices([_PHONE, _WATCH])
        await store.append_message(mine, _said("yours", message_id="m-1"))
        await store.append_message(other, _said("not yours either", message_id="m-2"))

        page = await store.changes(after=0, conversation_ids=[mine])

        assert all(one.conversation_id in {mine, None} for one in page.changes)
        assert [type(one) for one in page.changes] == [
            DevicesChangedChange,
            ConversationStartedChange,
            DevicesChangedChange,
            MessageAddedChange,
        ]
        everything = await store.changes(after=0)
        assert page.next_after == everything.next_after

    async def test_a_cursor_past_the_stream_is_answered_with_where_the_stream_is(
        self, store: ConversationStore
    ) -> None:
        """A store started afresh answers a cursor beyond it with a lower one."""
        await _chat(store)
        head = (await store.changes(after=0)).next_after

        beyond = await store.changes(after=head + 100)

        assert beyond.changes == ()
        assert beyond.next_after == head

    async def test_the_change_stream_refuses_a_malformed_read(
        self, store: ConversationStore
    ) -> None:
        """ADR-0073 §2's posture, and a bare ``str`` is not a list of ids."""
        for bad in (-1, 1.5, True, 2**63):
            with pytest.raises(ValueError, match="after"):
                await store.changes(after=bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="limit"):
                await store.changes(after=0, limit=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="conversation_ids"):
            await store.changes(after=0, conversation_ids="c-1")
        with pytest.raises(ValueError, match="conversation_ids"):
            await store.changes(after=0, conversation_ids=[1])  # type: ignore[list-item]
        with pytest.raises(ValueError, match="conversation_ids"):
            await store.changes(after=0, conversation_ids=["c"] * 1001)
        assert (await store.changes(after=7, limit=0)).next_after == 7

    async def test_deleting_a_conversation_deletes_its_transcript_and_says_so(
        self, store: ConversationStore
    ) -> None:
        """§2:3: the transcript goes; the stream keeps only the deletion."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("forget me", message_id="m-1"))

        assert await store.stamp_deleted(conversation) is True

        assert await store.transcript(conversation) is None
        mine = (await store.changes(after=0, conversation_ids=[conversation])).changes
        assert [type(one) for one in mine if one.conversation_id == conversation] == [
            ConversationDeletedChange
        ]
        assert (await store.export()).messages == ()

    async def test_dropping_a_stamped_conversation_keeps_the_news_of_its_deletion(
        self, factory: ConversationStoreFactory
    ) -> None:
        """A device catching up after the grace still learns the conversation went."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation = await _chat(store)
        await store.stamp_deleted(conversation)
        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation) is True

        kinds = [
            type(one) for one in await _all_changes(store) if one.conversation_id == conversation
        ]
        assert kinds == [ConversationDeletedChange]

    async def test_reclaim_never_drops_a_conversation_that_holds_a_message(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§5:4: a transcript is kept until the user deletes it; a marker is no message."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        holding = await _chat(store)
        emptied = (await store.start()).id
        await store.append_message(holding, _said("keep", message_id="m-1"))
        await store.append_message(emptied, _said("gone", message_id="m-1"))
        await store.delete_message(emptied, 1)
        clock.advance(_RETENTION)

        assert await store.drop_if_eligible(holding) is False
        assert await store.drop_if_eligible(emptied) is True

        assert await store.get(holding) is not None
        changes = await _all_changes(store)
        assert [type(one) for one in changes if one.conversation_id == emptied] == [
            ConversationDeletedChange
        ]

    # --- the chat space: devices (ADR-0293 §3) ------------------------------------

    async def test_my_devices_is_one_set_and_changing_it_is_recorded(
        self, store: ConversationStore
    ) -> None:
        """§3:1: set whole, read back in one order, recorded only where it changes."""
        assert await store.my_devices() == ()

        assert await store.set_my_devices([_WATCH, _PHONE]) is True
        assert await store.set_my_devices([_PHONE, _WATCH]) is False

        assert await store.my_devices() == (_PHONE, _WATCH)
        changes = await _all_changes(store)
        assert changes == [DevicesChangedChange(seq=changes[0].seq, devices=(_PHONE, _WATCH))]

    async def test_a_conversations_devices_differ_from_my_devices_and_from_each_other(
        self, store: ConversationStore
    ) -> None:
        """§3:1, §3:3: a new conversation starts on "my devices"; each changes alone."""
        earlier = await _chat(store)
        assert await store.set_conversation_devices(earlier, [_PHONE]) is True
        assert await store.set_conversation_devices(earlier, [_PHONE]) is False
        await store.set_my_devices([_LAPTOP])
        later = (await store.start()).id

        assert await store.conversation_devices(earlier) == (_PHONE,)
        assert await store.conversation_devices(later) == (_LAPTOP,)
        assert await store.my_devices() == (_LAPTOP,)
        refused = await store.append_message(
            earlier, _said("hi", message_id="m-1", device="laptop")
        )
        assert refused.outcome is SendOutcome.NOT_AN_END

    async def test_a_set_of_devices_is_refused_where_it_is_malformed(
        self, store: ConversationStore
    ) -> None:
        """One device named twice, a ``str``, or something that is not a device."""
        conversation = await _chat(store)
        twice = [_PHONE, ChatDevice(device_id="phone", access=DeviceAccess.READ)]
        for bad in (twice, "phone", ["phone"]):
            with pytest.raises(ValueError, match="devices"):
                await store.set_my_devices(bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="devices"):
                await store.set_conversation_devices(conversation, bad)  # type: ignore[arg-type]

    # --- the chat space: the reader's bookkeeping (ADR-0293 §6) ------------------

    async def test_the_reader_takes_in_the_users_waiting_messages_once(
        self, store: ConversationStore
    ) -> None:
        """§6:3, §6:6, §6:9: untaken until marked; marked once, by the first activation."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("one", message_id="m-1"))
        await store.append_message(conversation, _answered("noted"))
        await store.append_message(conversation, _said("two", message_id="m-2"))
        await store.append_message(conversation, _said("three", message_id="m-3"))
        await store.delete_message(conversation, 4)

        waiting = await store.untaken_messages(conversation)
        marked = await store.take_in(conversation, positions=[1, 2, 3, 4, 3], activation_id="a-1")
        again = await store.take_in(conversation, positions=[1, 3], activation_id="a-2")

        assert [one.position for one in waiting] == [1, 3]
        assert marked == (1, 3)
        assert again == ()
        assert await store.untaken_messages(conversation) == ()
        assert await store.taken_in(conversation, positions=[1, 2, 3, 4]) == {1: "a-1", 3: "a-1"}

    async def test_the_reader_finds_every_conversation_still_awaiting_it(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§6:9: after a restart, the conversations with messages never taken in."""
        store = _build(factory, new_id=ScriptedIds(["c-b", "c-a", "c-c", "c-d"]))
        await store.set_my_devices([_PHONE])
        second = (await store.start()).id
        first = (await store.start()).id
        answered = (await store.start()).id
        stamped = (await store.start()).id
        for conversation in (first, second, stamped):
            await store.append_message(conversation, _said("hi", message_id="m-1"))
        await store.append_message(answered, _answered("unprompted"))
        await store.stamp_deleted(stamped)

        assert await store.conversations_awaiting() == [first, second]
        assert await store.conversations_awaiting(limit=1, after_id=first) == [second]
        await store.take_in(first, positions=[1], activation_id="a-1")
        assert await store.conversations_awaiting() == [second]

    async def test_the_bookkeeping_is_in_no_transcript_read_and_no_change(
        self, store: ConversationStore
    ) -> None:
        """§6:7: the conversation does not know whether the assistant has read it."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("hi", message_id="m-1"))
        before_page = await store.transcript(conversation)
        before_changes = await store.changes(after=0)

        await store.take_in(conversation, positions=[1], activation_id="a-1")

        assert await store.transcript(conversation) == before_page
        assert await store.changes(after=0) == before_changes

    async def test_the_bookkeeping_refuses_a_malformed_call(self, store: ConversationStore) -> None:
        """Positions are ints from 1, at most 1000; the activation a non-blank id."""
        conversation = await _chat(store)
        for bad in ("1", [0], [True], [1.5], [1] * 1001):
            with pytest.raises(ValueError, match="position"):
                await store.take_in(conversation, positions=bad, activation_id="a-1")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="position"):
                await store.taken_in(conversation, positions=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="activation_id"):
            await store.take_in(conversation, positions=[1], activation_id=" ")
        for bad_limit in (-1, True):
            with pytest.raises(ValueError, match="limit"):
                await store.untaken_messages(conversation, limit=bad_limit)
            with pytest.raises(ValueError, match="limit"):
                await store.conversations_awaiting(limit=bad_limit)

    # --- the chat space: one device's view (ADR-0296 §3, §4) ----------------------

    async def test_a_device_sees_the_changes_of_the_conversations_it_reads(
        self, store: ConversationStore
    ) -> None:
        """§4:5: a reading end sees its conversation; a device that is no end does not."""
        await store.set_my_devices([_PHONE, _WATCH])
        shown = (await store.start()).id
        await store.set_my_devices([_LAPTOP])
        elsewhere = (await store.start()).id
        await store.append_message(shown, _said("hi", message_id="m-1"))
        await store.append_message(elsewhere, _said("not here", message_id="m-1", device="laptop"))

        for device in ("phone", "watch"):
            seen = await _seen_by(store, device)
            assert {one.conversation_id for one in seen if one.conversation_id} == {shown}
            assert "message_added" in _kinds(seen)
        assert {one.conversation_id for one in await _seen_by(store, "laptop")} == {
            None,
            elsewhere,
        }
        assert await _seen_by(store, "stranger") == []

    async def test_a_device_sees_the_change_that_removed_it_and_nothing_after(
        self, store: ConversationStore
    ) -> None:
        """ADR-0296 §4:8: the removal reaches the removed device; later changes do not."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("deleted later", message_id="m-1"))
        await store.append_message(conversation, _said("kept", message_id="m-2"))
        await store.set_conversation_devices(conversation, [_PHONE])
        await store.append_message(conversation, _said("after", message_id="m-3"))
        await store.delete_message(conversation, 1)

        seen = await _seen_by(store, "watch")

        # The deletion took the first message's addition out of the stream (§5:10),
        # and it came after the watch was removed, so the watch sees neither.
        assert _kinds(seen) == [
            "devices_changed",
            "conversation_started",
            "message_added",
            "devices_changed",
        ]
        assert seen[2].message.position == 2
        assert seen[-1] == DevicesChangedChange(
            seq=seen[-1].seq, conversation_id=conversation, devices=(_PHONE,)
        )
        assert _kinds(await _seen_by(store, "phone"))[-4:] == [
            "message_added",
            "devices_changed",
            "message_added",
            "message_deleted",
        ]

    async def test_a_device_added_late_sees_from_the_change_that_added_it(
        self, store: ConversationStore
    ) -> None:
        """ADR-0296 §4:7: nothing from before it joined; the snapshot covers that."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("before", message_id="m-1"))
        await store.set_conversation_devices(conversation, [_PHONE, _WATCH, _LAPTOP])
        await store.append_message(conversation, _said("after", message_id="m-2"))

        seen = await _seen_by(store, "laptop")

        assert _kinds(seen) == ["devices_changed", "message_added"]
        assert seen[0].devices == (_LAPTOP, _PHONE, _WATCH)
        assert seen[1].message.position == 2

    async def test_whether_a_change_reaches_a_device_is_decided_as_of_that_change(
        self, store: ConversationStore
    ) -> None:
        """A later change of membership does not reach back over an earlier change."""
        conversation = await _chat(store)
        await store.set_conversation_devices(conversation, [_PHONE])
        await store.append_message(conversation, _said("while away", message_id="m-1"))
        await store.set_conversation_devices(conversation, [_PHONE, _WATCH])
        await store.append_message(conversation, _said("back", message_id="m-2"))

        seen = await _seen_by(store, "watch")

        added = [one.message.position for one in seen if isinstance(one, MessageAddedChange)]
        assert added == [2]
        assert _kinds(seen).count("devices_changed") == 3  # my devices, left, rejoined

    async def test_a_writing_end_alone_is_shown_its_membership_and_nothing_said(
        self, store: ConversationStore
    ) -> None:
        """§3:5: a device that only writes is not shown the conversation's messages."""
        await store.set_my_devices([_PHONE, _KEYBOARD])
        conversation = (await store.start()).id
        sent = await store.append_message(
            conversation, _said("typed", message_id="m-1", device="keyboard")
        )
        await store.append_message(conversation, _answered("read it"))

        seen = await _seen_by(store, "keyboard")

        assert sent.outcome is SendOutcome.RECORDED
        assert _kinds(seen) == ["devices_changed", "conversation_started"]
        assert await store.device_conversations("keyboard") == []

    async def test_a_change_to_my_devices_reaches_the_devices_in_either_set(
        self, store: ConversationStore
    ) -> None:
        """A device sees "my devices" change while it is in the set or as it leaves it."""
        await store.set_my_devices([_PHONE])
        await store.set_my_devices([_PHONE, _WATCH])
        await store.set_my_devices([_PHONE])
        await store.set_my_devices([_PHONE, _LAPTOP])

        assert [one.devices for one in await _seen_by(store, "watch")] == [
            (_PHONE, _WATCH),
            (_PHONE,),
        ]
        assert len(await _seen_by(store, "phone")) == 4
        assert len(await _seen_by(store, "laptop")) == 1

    async def test_a_deletion_reaches_the_devices_that_read_the_conversation(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2:3, §4:8: deleted or reclaimed, a conversation's readers learn it went."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["stamped", "reclaimed"]))
        await store.set_my_devices([_PHONE, _WATCH, _KEYBOARD])
        stamped = (await store.start()).id
        reclaimed = (await store.start()).id
        await store.set_conversation_devices(stamped, [_PHONE])
        await store.set_my_devices([_LAPTOP])

        assert await store.stamp_deleted(stamped) is True
        clock.advance(_RETENTION)
        assert await store.drop_if_eligible(reclaimed) is True

        def deleted(seen: list[Any]) -> set[str]:
            return {one.conversation_id for one in seen if one.kind == "conversation_deleted"}

        # The watch read the stamped conversation before it was moved off it, and the
        # deletion cleared that removal from the stream, so it carries the news.
        assert deleted(await _seen_by(store, "phone")) == {stamped, reclaimed}
        assert deleted(await _seen_by(store, "watch")) == {stamped, reclaimed}
        assert deleted(await _seen_by(store, "keyboard")) == set()
        assert deleted(await _seen_by(store, "laptop")) == set()

    async def test_a_removed_device_catching_up_after_a_deletion_still_drops_it(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0296 §4:8: the deletion that clears a removal tells the removed device."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["stamped", "reclaimed"]))
        await store.set_my_devices([_PHONE, _WATCH])
        stamped = (await store.start()).id
        reclaimed = (await store.start()).id
        saved = (await store.device_changes("watch", after=0)).next_after
        for conversation in (stamped, reclaimed):
            await store.set_conversation_devices(conversation, [_PHONE])
        await store.set_conversation_devices(stamped, [_PHONE, _KEYBOARD])

        await store.stamp_deleted(stamped)
        clock.advance(_RETENTION)
        assert await store.drop_if_eligible(reclaimed) is True

        caught_up = await _seen_by(store, "watch", after=saved)
        assert {one.conversation_id for one in caught_up if one.kind == "conversation_deleted"} == {
            stamped,
            reclaimed,
        }
        assert not [
            one for one in await _seen_by(store, "keyboard") if one.kind == "conversation_deleted"
        ]

    async def test_a_deletion_reaches_readers_beyond_one_sets_bound(
        self, store: ConversationStore
    ) -> None:
        """Each set holds at most ``CHAT_DEVICES_MAX``; a history of readers does not."""
        conversation = await _chat(store)
        for index in range(CHAT_DEVICES_MAX + 3):
            reader = ChatDevice(device_id=f"reader-{index:03}", access=DeviceAccess.READ)
            await store.set_conversation_devices(conversation, [_PHONE, reader])

        await store.stamp_deleted(conversation)

        for device in ("watch", "reader-000", f"reader-{CHAT_DEVICES_MAX + 2:03}"):
            seen = await _seen_by(store, device)
            assert [one.kind for one in seen][-1] == "conversation_deleted"

    async def test_a_deleted_messages_addition_reaches_no_device(
        self, store: ConversationStore
    ) -> None:
        """§5:12: a reader sees the marker, never the text that was deleted."""
        conversation = await _chat(store)
        await store.append_message(conversation, _said("oops", message_id="m-1"))
        await store.delete_message(conversation, 1)

        seen = await _seen_by(store, "watch")

        assert _kinds(seen)[-1:] == ["message_deleted"]
        assert "message_added" not in _kinds(seen)

    async def test_a_devices_cursor_moves_over_what_it_does_not_see(
        self, store: ConversationStore
    ) -> None:
        """ADR-0296 §4:6: a device sees gaps, and a quiet device keeps up."""
        conversation = await _chat(store)
        everything = await store.changes(after=0)
        for index in range(3):
            await store.append_message(conversation, _said(str(index), message_id=f"m-{index}"))
        head = (await store.changes(after=0)).next_after

        quiet = await store.device_changes("laptop", after=0)
        first = await store.device_changes("watch", after=everything.next_after, limit=2)
        rest = await store.device_changes("watch", after=first.next_after, limit=2)

        assert quiet.changes == ()
        assert quiet.next_after == head
        assert len(first.changes) == 2
        assert first.next_after == first.changes[-1].seq
        assert len(rest.changes) == 1
        assert rest.next_after == head
        assert (await store.device_changes("watch", after=4, limit=0)).next_after == 4
        assert (await store.device_changes("watch", after=head + 9)).next_after == head

    async def test_device_scoped_reads_refuse_a_malformed_call(
        self, store: ConversationStore
    ) -> None:
        """A device is a non-blank ``str``; paging carries ADR-0073 §2's posture."""
        for bad_device in ("", "  ", 7, None):
            with pytest.raises(ValueError, match="device_id"):
                await store.device_changes(bad_device, after=0)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="device_id"):
                await store.device_conversations(bad_device)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="device_id"):
                await store.remove_device(bad_device)  # type: ignore[arg-type]
        for bad in (-1, 1.5, True, 2**63):
            with pytest.raises(ValueError, match="after"):
                await store.device_changes("phone", after=bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="limit"):
                await store.device_changes("phone", after=0, limit=bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="limit"):
                await store.device_conversations("phone", limit=bad)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="offset"):
                await store.device_conversations("phone", offset=bad)  # type: ignore[arg-type]

    async def test_a_device_lists_the_conversations_it_reads_as_recent_orders_them(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0296 §4:5, §4:7: its reading conversations, with its access, newest first."""
        clock = MovableClock()
        ids = ScriptedIds(["c-old", "c-tie-b", "c-tie-a", "c-gone", "c-off"])
        store = _build(factory, now=clock, new_id=ids)
        await store.set_my_devices([_PHONE, _WATCH])
        old = (await store.start()).id
        clock.advance(_HOUR)
        tie_b = (await store.start()).id
        tie_a = (await store.start()).id
        gone = (await store.start()).id
        off = (await store.start()).id
        await store.set_conversation_devices(off, [_PHONE])
        await store.stamp_deleted(gone)
        assert off < tie_a

        watch = await store.device_conversations("watch")
        phone = await store.device_conversations("phone", limit=2, offset=1)

        assert [one.conversation.id for one in watch] == [tie_a, tie_b, old]
        assert {one.access for one in watch} == {DeviceAccess.READ}
        for one in watch:
            assert one.conversation == await store.get(one.conversation.id)
        assert [one.conversation.id for one in phone] == [tie_a, tie_b]
        assert {one.access for one in phone} == {DeviceAccess.READ_WRITE}
        assert isinstance(phone[0], DeviceConversation)
        assert await store.device_conversations("watch", limit=0) == []
        assert await store.device_conversations("watch", offset=3) == []
        assert await store.device_conversations("stranger") == []

    async def test_removing_a_device_takes_it_out_of_every_set_and_says_so(
        self, factory: ConversationStoreFactory
    ) -> None:
        """ADR-0296 §3:6: out of "my devices" and every conversation, each a change."""
        store = _build(factory, new_id=ScriptedIds(["c-1", "c-2", "c-3", "c-4"]))
        await store.set_my_devices([_PHONE, _WATCH])
        first = (await store.start()).id
        second = (await store.start()).id
        without = (await store.start()).id
        stamped = (await store.start()).id
        await store.set_conversation_devices(without, [_WATCH])
        await store.stamp_deleted(stamped)
        cursor = (await store.changes(after=0)).next_after

        assert await store.remove_device("phone") is True
        assert await store.remove_device("phone") is False

        assert await store.my_devices() == (_WATCH,)
        for conversation in (first, second, without):
            assert await store.conversation_devices(conversation) == (_WATCH,)
        recorded = (await store.changes(after=cursor)).changes
        assert recorded == (
            DevicesChangedChange(seq=recorded[0].seq, devices=(_WATCH,)),
            DevicesChangedChange(seq=recorded[1].seq, conversation_id=first, devices=(_WATCH,)),
            DevicesChangedChange(seq=recorded[2].seq, conversation_id=second, devices=(_WATCH,)),
        )
        assert await _seen_by(store, "phone", after=cursor) == list(recorded)
        assert await _seen_by(store, "watch", after=cursor) == list(recorded)
        refused = await store.append_message(first, _said("still here?", message_id="m-1"))
        assert refused.outcome is SendOutcome.NOT_AN_END
        assert await store.device_conversations("phone") == []
        assert await store.conversation_devices((await store.start()).id) == (_WATCH,)
        assert await store.remove_device("stranger") is False

    async def test_removing_a_device_is_one_step_against_starting_a_conversation(
        self, store: ConversationStore
    ) -> None:
        """No conversation started alongside a removal keeps the removed device."""
        await store.set_my_devices([_PHONE, _WATCH])
        await store.start()

        results = await asyncio.gather(
            store.start(), store.remove_device("phone"), store.start(), store.start()
        )

        assert results[1] is True
        assert await store.my_devices() == (_WATCH,)
        for conversation in await store.recent():
            assert await store.conversation_devices(conversation.id) == (_WATCH,)

    # --- the chat space: export and serialisation (ADR-0293 §5:3) -----------------

    async def test_export_carries_every_standing_message_in_order(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§5:3, ADR-0292 §3:11: the transcripts are the user's data; markers carry nothing."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["older", "newer"]))
        await store.set_my_devices([_PHONE])
        older = (await store.start()).id
        clock.advance(_HOUR)
        newer = (await store.start()).id
        await store.append_message(older, _said("a", message_id="m-1"))
        await store.append_message(older, _said("b", message_id="m-2"))
        await store.append_message(newer, _said("c", message_id="m-1"))
        await store.delete_message(older, 1)

        exported = await store.export()

        assert [(one.conversation_id, one.position) for one in exported.messages] == [
            (newer, 1),
            (older, 2),
        ]

    async def test_two_sends_issued_together_take_distinct_positions(
        self, store: ConversationStore
    ) -> None:
        """The exclusion: two writes never draw one position or one sequence number."""
        conversation = await _chat(store)

        receipts = await asyncio.gather(
            store.append_message(conversation, _said("a", message_id="m-1")),
            store.append_message(conversation, _said("b", message_id="m-2")),
            store.append_message(conversation, _said("a", message_id="m-1")),
        )

        recorded = sorted(
            one.position or 0 for one in receipts if one.outcome is SendOutcome.RECORDED
        )
        repeated = [one for one in receipts if one.outcome is SendOutcome.REPEATED]
        assert recorded == [1, 2], _INTERLEAVED
        assert len(repeated) == 1, _INTERLEAVED
        changes = await _all_changes(store)
        assert len({one.seq for one in changes}) == len(changes), _INTERLEAVED

    # --- detachment and construction ----------------------------------------

    async def test_reads_return_detached_frozen_snapshots(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9.5: what a caller holds cannot be changed by the store, or by the caller.

        The exchanged types are frozen, so detachment costs nothing — but a store
        that grew a mutable internal row and handed one out would break both
        halves at once, which is why both are asserted rather than assumed.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation = await store.start()
        await store.record_turn(
            conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
        )
        held = await store.deliveries(conversation.id, episode_ids=[_EPISODE])

        clock.advance(_HOUR)
        await store.mark_active(conversation.id)
        await store.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)

        assert conversation.last_active_at == _NOW, "the caller's snapshot did not move"
        assert held == {_EPISODE: _UNSTAMPED}, "the caller's mapping did not move"
        with pytest.raises(ValidationError):
            conversation.last_active_at = _NOW + _DAY
        with pytest.raises(ValidationError):
            held[_EPISODE].state = SpokenDeliveryState.COMPLETE

    @pytest.mark.parametrize("grace", [timedelta(0), -timedelta(seconds=1)])
    async def test_a_zero_or_negative_tombstone_grace_is_refused_at_construction(
        self, factory: ConversationStoreFactory, grace: timedelta
    ) -> None:
        """§8: both values break the deletion protocol, in opposite directions."""
        with pytest.raises(ValueError, match="tombstone_grace"):
            _build(factory, tombstone_grace=grace)

    @pytest.mark.parametrize("bad", [None, "30 days", 30], ids=["none", "str", "int"])
    async def test_a_malformed_duration_is_refused_at_construction(
        self, factory: ConversationStoreFactory, bad: object
    ) -> None:
        """The constructor documents ``ValueError`` for a duration it will not take.

        Whatever is wrong with it: ``None <= timedelta(0)`` raises ``TypeError``,
        so the type has to be checked before the comparison or the promise is only
        kept for the values that happen to compare.
        """
        with pytest.raises(ValueError, match="tombstone_grace"):
            _build(factory, tombstone_grace=cast("timedelta", bad))
        if bad is not None:  # `retention=None` is the ratified "keep forever" (§7)
            with pytest.raises(ValueError, match="retention"):
                _build(factory, retention=cast("timedelta", bad))

    async def test_a_non_positive_retention_is_refused_at_construction(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7: ``None`` disables reclaim; zero is not a spelling for it."""
        with pytest.raises(ValueError, match="retention"):
            _build(factory, retention=timedelta(0))

    # --- cancellation (ADR-0060) ---------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction a
    #: ``CancelledError`` could unwind past. ``core.protocols``' clause is then
    #: vacuously satisfied and there is nothing for the case below to observe.
    #: Left ``False``, the suite requires the implementation to *prove* the
    #: invariant by overriding :meth:`store_suspended_mid_write`, so a new durable
    #: backend that reintroduces ADR-0054's bug fails here rather than passing a
    #: suite that never looked. Opting out is a visible declaration in the subclass.
    acquires_no_shared_resource: bool = False

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[ConversationStore]]:
        """Supply a store whose named locked operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. ADR-0074 §9.5
        binds this store to ``core.protocols``' standing cancellation clause like
        every other Protocol, and ADR-0060 §3 is explicit that asserting only that
        ``CancelledError`` escapes is worthless — the *pre*-ADR-0054 code did that
        correctly and released the connection anyway. So the case cancels a call
        while it is held open inside the resource and watches what a second caller
        can reach.

        The returned :class:`SuspendedMidWrite` carries the store, its
        ``ResourceLog``, and an ``arm(operation)`` lever the case calls — *after*
        its preconditions, so a fake arming its single resource suspends the
        operation under test rather than a setup write. Every distinct
        ``async with self._lock`` site is a separate place the same regression can
        reappear — the locked *reads* included, since ADR-0060 §3 binds any method
        that acquires the resource (#370, #492) — so ``arm`` says how it stops a
        given one: a worker thread parked mid-SQL, a fake's modelled resource.

        The ``ResourceLog`` is not redundant with the blocked-caller assertion. That
        one is decisive only where queueing is loop-bound; a store whose work runs
        on an executor can leave a second call pending for reasons that have nothing
        to do with the resource, and the log settles it directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked call (ADR-0074 §9.5).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a test
        of the invariant rather than of propagation: a single cancelled call in
        isolation looks identical either way (ADR-0060 §3).

        The first call's *effect* is deliberately not asserted (the op's ``verify``
        pins only what a caller may rely on): the clause's third paragraph makes it
        indeterminate, since under ADR-0054's shield a cancelled write that reached
        its commit is durably written. What is pinned is that the second call is
        whole and the store still serves reads.

        **Named for an operation, not a mutation.** ADR-0060 §3 binds any method
        that acquires the resource; the mutations were covered first (#487) and
        the five locked reads are the same invariant on the other half of the
        surface (#492). A read that released the connection under cancellation while
        its worker still held it is the identical ADR-0054 hazard, and no mutation
        case can see it.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await op.prepare(store)
            # Armed *after* the preconditions, so a fake arming its one resource
            # suspends the operation under test rather than a setup write.
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(store))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(store))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring *one* cancellation is not the contract: a
                # second delivered while the deferred wait runs must not escape and
                # unwind out of the resource either (ADR-0054's helper loops on
                # ``while not done.is_set()`` for exactly this).
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at once. A delta, because a fake's
            # preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(store)

    # --- input observation (ADR-0065) ----------------------------------------

    #: Whether this implementation performs no ``await`` between the coroutine's
    #: first executed line and the point its caller-owned argument is observed — no
    #: suspension window for a mutation to land in. ``core.protocols``' input clause
    #: is then discharged by "do not suspend" and the two cases below reduce to a
    #: post-call assertion, correctly: a call with no window has none to tear in.
    #: Left ``False``, the suite requires the implementation to open that window by
    #: overriding :meth:`store_suspended_at_its_first_await`. Nothing declares it —
    #: both shipped subjects suspend before they read anything — so it is stated
    #: hypothetically, as the declaration a future non-suspending backend makes
    #: rather than as a description of one that exists. Deliberately *not* the same
    #: declaration as :attr:`acquires_no_shared_resource`: ADR-0065 §"This is not
    #: ADR-0060's axis" holds that the two have different vacuity sets.
    observes_without_suspending: bool = False

    def store_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[ConversationStore, Callable[[str], SuspendedCall]]]:
        """Supply a store whose next call to a **named operation** stops at its first ``await``.

        Override unless :attr:`observes_without_suspending` is set. The suite runs
        any preconditions the operation needs, then calls the returned
        ``arm(operation)`` to get the :class:`SuspendedCall` lever back — after the
        preconditions, so a store arming one collaborator suspends the operation
        under test rather than a setup write. The named call must suspend at its own
        first ``await`` and stay there until the case releases it; later calls run
        free, because the cases go on to read the store back.

        **The position is part of the hook's contract, not the implementer's
        choice** (ADR-0065 §3). A hook fired at method *entry* would let the mutation
        land before the method had read anything, so the store would observe one
        coherent mutated version, the case would pass, and a tear at the real window
        would survive untested. The first ``await`` is exactly the boundary the
        clause draws: a conforming call has taken its one observation before that
        point and cannot be reached by the mutation, while a call that reads its
        argument afterwards answers from the later version.

        The two operations the cases below arm are ``record_turn`` and
        ``deliveries`` — the only methods on this Protocol that take a caller-owned
        argument which is not a plain ``str``, ``int`` or ``datetime``:
        ``record_turn``'s ``delivery``, a frozen model, and ``deliveries``'
        ``episode_ids``, the one *mutable* argument on the surface. Returned as a
        context manager so the subject is disposed of the way that implementation
        needs.
        """
        raise NotImplementedError

    @contextlib.asynccontextmanager
    async def _observation_subject(
        self, store: ConversationStore
    ) -> AsyncIterator[tuple[ConversationStore, Callable[[str], SuspendedCall] | None]]:
        """The store the two cases below drive, and the lever arming one of its calls.

        ``None`` for the lever where the implementation declares itself
        non-suspending (:attr:`observes_without_suspending`); the ``store`` fixture
        is then the subject, since there is no window to open and nothing to build.
        The caller arms *after* its own preconditions, which is why the lever is
        handed out rather than the gate. Mirrors ``MemoryStoreContract``'s helper of
        the same name.
        """
        if self.observes_without_suspending:
            yield store, None
            return
        async with self.store_suspended_at_its_first_await() as (subject, arm):
            yield subject, arm

    async def test_record_turn_cannot_tear_on_a_mid_flight_mutation_of_its_delivery(
        self, store: ConversationStore
    ) -> None:
        """``core.protocols``' input clause, on ``record_turn``'s ``delivery`` (ADR-0065).

        **What is actually at risk here is small, and worth saying rather than
        overstating.** ``SpokenDelivery`` is a frozen model, the id a ``str`` and the
        instant a ``datetime``, so the #286 tear — the caller rewriting the argument
        while the write is suspended and the store committing a mix of two versions —
        is not reachable through the exchanged types today. That is exactly why the
        case earns its keep: nothing would notice if the argument stopped being
        frozen, and this fails the moment it does.

        So the assertion is in two halves: the mutation must be unrepresentable
        while the call is in flight, and what the store recorded must correspond to
        the delivery as constructed.
        """
        async with self._observation_subject(store) as (subject, arm):
            conversation = await subject.start()
            delivery = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
            handed_over = delivery.model_copy(deep=True)
            # Armed after the precondition, so the collaborator that stops the
            # write is not spent on the ``start``.
            gate = None if arm is None else arm("record_turn")
            call = subject.record_turn(
                conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=delivery
            )
            async with held_at_its_first_await(gate, call) as pending:
                with pytest.raises(ValidationError):
                    delivery.state = SpokenDeliveryState.COMPLETE
            await pending

            assert await subject.deliveries(conversation.id, episode_ids=[_EPISODE]) == {
                _EPISODE: handed_over
            }, _TORN_INPUT

    async def test_deliveries_observes_its_episode_ids_before_its_first_await(
        self, store: ConversationStore
    ) -> None:
        """The same clause on the read side, on the one mutable argument there is.

        ``episode_ids`` is a caller's list, and a caller may go on editing it while
        the read is suspended. A read derives one answer from one argument, so a
        store that observed the list late would return the later version's answer
        whole; what makes it checkable is the *position* ADR-0065 §1 fixes — every
        discharge yields the answer for the argument as it stood when the work began
        — so the case rewrites the list mid-flight and asserts the pre-mutation
        answer.
        """
        async with self._observation_subject(store) as (subject, arm):
            conversation = await subject.start()
            await subject.record_turn(
                conversation.id, episode_id=_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
            )
            await subject.record_turn(
                conversation.id, episode_id=_OTHER_EPISODE, occurred_at=_NOW, delivery=_UNSTAMPED
            )
            await subject.record_delivery(conversation.id, episode_id=_EPISODE, delivery=_COMPLETE)
            asked = [_EPISODE]
            gate = None if arm is None else arm("deliveries")
            call = subject.deliveries(conversation.id, episode_ids=asked)
            async with held_at_its_first_await(gate, call) as pending:
                asked[0] = _OTHER_EPISODE
                asked.append("activation:added-late")
            found = await pending

            assert found == {_EPISODE: _COMPLETE}, _LATE_ARGUMENT

    async def test_setting_devices_observes_its_set_before_its_first_await(
        self, store: ConversationStore
    ) -> None:
        """ADR-0065 on ``set_conversation_devices``' ``devices``, a caller's list."""
        async with self._observation_subject(store) as (subject, arm):
            conversation = await _chat(subject)
            asked = [_WATCH]
            gate = None if arm is None else arm("set_conversation_devices")
            call = subject.set_conversation_devices(conversation, asked)
            async with held_at_its_first_await(gate, call) as pending:
                asked[0] = _LAPTOP
                asked.append(_PHONE)
            await pending

            assert await subject.conversation_devices(conversation) == (_WATCH,), _LATE_ARGUMENT

    async def test_changes_observes_its_restriction_before_its_first_await(
        self, store: ConversationStore
    ) -> None:
        """ADR-0065 on ``changes``' ``conversation_ids``, a caller's list."""
        async with self._observation_subject(store) as (subject, arm):
            mine = await _chat(subject)
            other = (await subject.start()).id
            asked = [mine]
            gate = None if arm is None else arm("changes")
            call = subject.changes(after=0, conversation_ids=asked)
            async with held_at_its_first_await(gate, call) as pending:
                asked[0] = other
            found = await pending

            assert {one.conversation_id for one in found.changes} == {mine, None}, _LATE_ARGUMENT

    async def test_take_in_observes_its_positions_before_its_first_await(
        self, store: ConversationStore
    ) -> None:
        """ADR-0065 on ``take_in``'s ``positions``, a caller's list."""
        async with self._observation_subject(store) as (subject, arm):
            conversation = await _chat(subject)
            await subject.append_message(conversation, _said("one", message_id="m-1"))
            await subject.append_message(conversation, _said("two", message_id="m-2"))
            asked = [1]
            gate = None if arm is None else arm("take_in")
            call = subject.take_in(conversation, positions=asked, activation_id="a-1")
            async with held_at_its_first_await(gate, call) as pending:
                asked[0] = 2
            marked = await pending

            assert marked == (1,), _LATE_ARGUMENT
