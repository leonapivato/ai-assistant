"""A canonical in-memory :class:`~ai_assistant.core.protocols.ConversationStore` fake.

The shared test double for the ``ConversationStore`` contract (ADR-0074 §9), so a
subsystem that depends on conversations — `orchestration`'s capture stage above
all — can test against a real, contract-correct store *without importing a
subsystem's internals* (CLAUDE.md golden rule 1). It is deliberately minimal: two
dicts, an injected clock and an injected id factory. Like the store it doubles for,
it holds no history — a conversation's turns are the episodes on its channel in the
``MemoryStore`` (ADR-0283 §1, §4).

It honours the whole contract, including the parts a dict gets for free only if
they are written down: the per-conversation mutation exclusion and the
tombstone's asymmetric visibility (hidden from every presenting read, still
enumerable by the sweeps).

Each conversation and each message carries its home (ADR-0386 §4): ``start`` writes the
one it is handed and ``append_message`` the one its message carries, no write changes
either, and a home no write may carry is a ``ValueError`` before anything is read, as the
durable store refuses it (§6:2). A deleted message's marker carries none (ADR-0293
§5:12); the durable store keeps the home on the marker's row, which no read gives back,
and this double keeps it beside the marker, in a map no read gives back either. A
message replying to a message of another home, standing or deleted, is answered
``another_home`` and writes nothing (ADR-0383 §4:7); one of another home than its
conversation is recorded, as the durable store records it.

**It can be bound to a sight** (ADR-0383 §7:1), as the store is:
:meth:`FakeConversationStore.bound` returns a copy sharing every piece of this fake's
state, with the sight set. Built to withhold, the copy holds a conversation whose home
the sight sees and, within it, each message or marker whose own home it sees, applied
before anything is ordered, sliced or counted; it gives back no device row (§3:3), and a
conversation it does not hold is, for every member naming it, one never started. Built
to count, the default, it answers as unbound and logs ``sight_counted`` for each read.

It holds ADR-0293's chat space as the store does: each conversation's transcript,
"my devices" and each conversation's devices, the change stream as one list of
changes under one counter, and the reader's bookkeeping. A change is held as the
frozen model a read returns, so deleting a message removes its addition from the
list and deleting a conversation leaves only its deletion there — the same stream
the ``sqlite3`` store answers with.

**Its critical sections really suspend.** Each mutation yields to the event loop
inside its exclusion, before reading the state it is about to change. Without
that, a fake backed by a dict would satisfy every concurrency case in the shared
suite by accident — nothing in it ever awaits, so nothing can interleave — and
the suite's serialisation clauses would be vacuous against exactly the
implementation they most need to hold for. With it, dropping the lock makes those
cases fail here as they would against a real store.

**Its mutations and its reads pass through a modelled resource**, a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` entered inside the
exclusion for a mutation and on its own for a read. A dict needs no serialising, so
without one this fake could only opt out of ADR-0060's cancellation clause — and the
suite's case would then run solely against the ``sqlite3`` store, which is the
implementation that already got it right. The reads are in because that store holds
its connection lock across every one of them, so each is its own place the resource
could be handed over early (#492). Uncontended, entering it does not yield, so it
adds no interleaving point that was not there before; under contention it only
reinforces the exclusion.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    CHAT_SNAPSHOT_ENTRIES,
    ChatChanges,
    ChatDevice,
    Conversation,
    ConversationDeletedChange,
    ConversationExport,
    ConversationStartedChange,
    DeletedMessage,
    DeviceChange,
    DeviceChanges,
    DeviceConversation,
    DevicesChangedChange,
    ExportedMessage,
    Identifier,
    MessageAddedChange,
    MessageAuthor,
    MessageDeletedChange,
    MessageReceipt,
    RecordHome,
    SendOutcome,
    SightMode,
    TranscriptMessage,
    TranscriptPage,
    UtcInstant,
    checked_chat_devices,
    describe_untrusted,
    home_may_be_written,
)
from ai_assistant.testing._home_count import count_homes
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ChatChange, NewMessage, Sight
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The store's code in ADR-0383 §11:1's event, as the conversation store writes it.
_STORE_CODE: Final = "conversations"

#: One past the largest value a paging argument accepts — the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2). Duplicated from the
#: production store rather than shared, exactly as ``MemoryStore``'s bound is:
#: ``ai_assistant.testing`` may not import a subsystem (golden rule 1), and a fake
#: looser than the contract would certify consumers a real store rejects.
_PAGE_BOUND = 2**63

#: The batch :meth:`FakeConversationStore.stamped_conversation_ids` yields by
#: default (ADR-0076 §2).
_DEFAULT_PURGE_BATCH = 100

#: The retention horizon a conversation record is judged against when nobody
#: injects one (ADR-0074 §7). **Finite**, because an unbounded default would ship
#: an ever-growing Tier 1 index with no cap decision behind it; ``None`` means
#: "keep forever", is the user's deliberate choice, and switches reclaim off.
#: The ``Settings`` field this mirrors is owed by the capture/lifecycle lane.
_DEFAULT_EPISODE_RETENTION = timedelta(days=30)

#: How long a tombstone outlives the deletion that stamped it (ADR-0074 §8).
#: Positive and finite, with no ``None`` spelling: an unbounded grace keeps every
#: deleted conversation's record forever, and a zero or negative one drops it
#: immediately, which is the orphaned late write the tombstone exists to catch.
_DEFAULT_TOMBSTONE_GRACE = timedelta(hours=1)

#: How many times :meth:`FakeConversationStore.start` re-mints before giving up.
_START_RETRY_BUDGET = 8

#: ``record_turn``'s two checked arguments go through ``core``'s own annotated types,
#: exactly as the production store's do, so the two refuse the same values.
_EPISODE_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

#: The most ids or positions one chat-space call takes (ADR-0293), so one page is one
#: call. Duplicated from the production store rather than shared, for
#: :data:`_PAGE_BOUND`'s reason.
_MAX_NAMED: Final = 1000

#: The page sizes the chat-space reads default to. The snapshot's is the figure
#: ADR-0293 leaves open (What stays open), chosen by the implementation.
_DEFAULT_TRANSCRIPT_PAGE: Final = 50
_DEFAULT_CHANGES_PAGE: Final = 100
_DEFAULT_AWAITING_PAGE: Final = 100

#: The page size :meth:`FakeConversationStore.device_conversations` defaults to:
#: ``recent``'s, since it is ``recent`` for one device.
_DEFAULT_DEVICE_CONVERSATIONS_PAGE: Final = 50

#: The device a device-scoped call names goes through the type a ``ChatDevice``
#: holds its id in, exactly as the production store's does.
_DEVICE_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)

#: The effect record ``effect_position`` names goes through the type ``NewMessage``
#: holds it in, exactly as the production store's does (ADR-0350 §12:9).
_EFFECT_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)


def _check_position(name: str, value: object) -> int:
    """Refuse a position that is not an exact ``int`` in ``[1, 2**63)``.

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason. ``bool`` is refused with the rest: ``True`` is not a position.

    Raises:
        ValueError: If ``value`` is not such an ``int``.
    """
    if type(value) is not int or not 1 <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [1, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _checked_positions(positions: object) -> tuple[int, ...]:
    """Check a sequence of positions once, before anything is read (ADR-0065).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason.

    Raises:
        ValueError: If ``positions`` is a ``str`` or not a sequence, holds more than
            :data:`_MAX_NAMED`, or holds a value that is not a position.
    """
    if isinstance(positions, (str, bytes)) or not isinstance(positions, Sequence):
        msg = f"positions must be a sequence of int, got {describe_untrusted(positions)}"
        raise ValueError(msg)
    held = tuple(positions)
    if len(held) > _MAX_NAMED:
        msg = f"positions holds {len(held)}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        _check_position("a position", one)
    return held


def _checked_device_id(device_id: object) -> str:
    """Check the device a device-scoped call names, before anything is read.

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason.

    Raises:
        ValueError: If ``device_id`` is not a non-blank ``str``.
    """
    try:
        return _DEVICE_ID.validate_python(device_id, strict=True)
    except ValidationError as exc:
        msg = f"device_id must be a non-blank str, got {describe_untrusted(device_id)}"
        raise ValueError(msg) from exc


def _access_of(device: str, devices: tuple[ChatDevice, ...]) -> ChatDevice | None:
    """The entry ``devices`` holds for ``device``, or ``None``."""
    return next((one for one in devices if one.device_id == device), None)


def _checked_conversation_ids(conversation_ids: object) -> tuple[str, ...] | None:
    """Check ``changes``' restriction once, before anything is read (ADR-0065).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason.

    Raises:
        ValueError: If ``conversation_ids`` is a ``str`` or not a sequence, holds more
            than :data:`_MAX_NAMED` ids, or holds an element that is not a ``str``.
    """
    if conversation_ids is None:
        return None
    if isinstance(conversation_ids, (str, bytes)) or not isinstance(conversation_ids, Sequence):
        described = describe_untrusted(conversation_ids)
        msg = f"conversation_ids must be a sequence of str, got {described}"
        raise ValueError(msg)
    held = tuple(conversation_ids)
    if len(held) > _MAX_NAMED:
        msg = f"conversation_ids holds {len(held)}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        if type(one) is not str:
            msg = f"conversation_ids holds an id that is not a str: {describe_untrusted(one)}"
            raise ValueError(msg)
    return held


def _checked_activation_id(activation_id: object) -> str:
    """Check ``take_in``'s activation through ``core``'s own identifier type.

    Raises:
        ValueError: If ``activation_id`` is not a non-blank ``str``.
    """
    try:
        return _EPISODE_ID.validate_python(activation_id, strict=True)
    except ValidationError as exc:
        msg = f"activation_id must be a non-blank str, got {describe_untrusted(activation_id)}"
        raise ValueError(msg) from exc


def _checked_effect_id(effect_id: object) -> str:
    """Check the effect record ``effect_position`` names, through ``core``'s type.

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason.

    Raises:
        ValueError: If ``effect_id`` is not a non-blank ``str``.
    """
    try:
        return _EFFECT_ID.validate_python(effect_id, strict=True)
    except ValidationError as exc:
        msg = f"effect_id must be a non-blank str, got {describe_untrusted(effect_id)}"
        raise ValueError(msg) from exc


def _checked_home(home: object) -> RecordHome:
    """Refuse a home that is no ``RecordHome``, or one no write may carry (ADR-0386 §6:2).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason, so the two refuse the same homes, before anything is read.

    Raises:
        ValueError: If ``home`` is not a home a write may carry.
    """
    if not isinstance(home, RecordHome):
        msg = f"a home must be a RecordHome, got {type(home).__name__}"
        raise ValueError(msg)
    checked = RecordHome.model_validate(home.model_dump())
    if not home_may_be_written(checked):
        msg = f"a {checked.kind} home is one no write may carry (ADR-0383 §2:3)"
        raise ValueError(msg)
    return checked


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _random_id() -> str:
    """Mint an opaque, random, device-agnostic conversation id (ADR-0074 §1)."""
    return str(uuid4())


def _check_page_bound(name: str, value: object) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[0, 2**63)``.

    Duplicated from the production store rather than shared, for the reason given
    on :data:`_PAGE_BOUND`. **The type is part of the range**: without it this fake
    would slice a list on ``limit=1.5`` and raise ``TypeError`` where the real
    store raises out of the driver, and two stores disagreeing about a bad
    argument is the failure ADR-0073 §2 exists to stop. ``bool`` is refused with
    the rest, being an ``int`` subclass that is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is negative, or is beyond the
            signed 64-bit range.
    """
    if type(value) is not int or not 0 <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [0, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _checked_turn(episode_id: object, occurred_at: object) -> tuple[str, datetime]:
    """Check ``record_turn``'s arguments before anything is read (ADR-0283 §6:3).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason; both go through ``core``'s annotated types, so they refuse the same values.

    Returns:
        The episode id and the instant, as ``core`` normalises them.

    Raises:
        ValueError: If ``episode_id`` is not a non-blank ``str``, or ``occurred_at``
            is not an aware instant.
    """
    try:
        checked_id = _EPISODE_ID.validate_python(episode_id, strict=True)
    except ValidationError as exc:
        msg = f"episode_id must be a non-blank str, got {describe_untrusted(episode_id)}"
        raise ValueError(msg) from exc
    try:
        checked_at = _INSTANT.validate_python(occurred_at, strict=True)
    except ValidationError as exc:
        msg = (
            f"occurred_at must be a timezone-aware instant with a determinate offset, "
            f"got {describe_untrusted(occurred_at)}"
        )
        raise ValueError(msg) from exc
    return checked_id, checked_at


@dataclass(slots=True)
class _Exclusion:
    """One conversation's mutation lock, and how many callers still need it.

    The pair travels together so the two halves cannot be created or discarded
    apart, which is the whole safety property :meth:`FakeConversationStore._exclusive`
    depends on (#453).

    Attributes:
        lock: The mutation exclusion for one conversation id.
        holders: How many callers are between entering ``_exclusive`` and leaving
            it — waiting on the lock included. While it is above zero the entry
            must not be discarded, because a caller arriving now has to be handed
            *this* lock and not a fresh one.
    """

    lock: asyncio.Lock
    holders: int = 0


@dataclass(slots=True)
class _Shared:
    """The fake's two values a write replaces, held apart so a bound copy shares them.

    A fake bound to a sight is a copy sharing every piece of its state by reference
    (:meth:`FakeConversationStore.bound`); a counter or a set held as a plain attribute
    would be copied by value, and a write through the copy would leave the store's own
    behind.
    """

    seq: int = 0
    my_devices: tuple[ChatDevice, ...] = ()


def _by_last_activity(conversations: list[Conversation]) -> list[Conversation]:
    """ADR-0074 §2's total order: ``last_active_at`` descending, ``id`` ascending.

    Two passes over a stable sort rather than one composite key, because the two
    halves run in opposite directions and ``datetime`` has no negation.
    """
    by_id = sorted(conversations, key=lambda one: one.id)
    return sorted(by_id, key=lambda one: one.last_active_at, reverse=True)


class FakeConversationStore:
    """A non-persistent ``ConversationStore`` test double backed by dicts.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ConversationStore`.
    """

    def __init__(  # noqa: PLR0913 — one keyword per injected seam the contract names
        self,
        *,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _random_id,
        retention: timedelta | None = _DEFAULT_EPISODE_RETENTION,
        tombstone_grace: timedelta = _DEFAULT_TOMBSTONE_GRACE,
        purge_batch: int = _DEFAULT_PURGE_BATCH,
        sight_mode: SightMode = SightMode.COUNT,
    ) -> None:
        """Create an empty store.

        Args:
            now: Clock the store stamps and judges deadlines with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` exactly as the real
                store is, because a fake looser than the contract would certify
                consumers the real implementation rejects (ADR-0026 §7).
            new_id: The injected id factory ``start`` mints through. Injected
                rather than hard-wired to ``uuid4`` because that is what makes
                ``start``'s insert-if-absent retry reachable in a test at all
                (ADR-0074 §1).
            retention: The horizon an idle conversation is reclaimed against;
                ``None`` disables reclaim entirely (ADR-0074 §7).
            tombstone_grace: How long a stamped conversation's record survives the
                stamp (ADR-0074 §8).
            purge_batch: The batch size :meth:`stamped_conversation_ids` uses by
                default.
            sight_mode: Whether a copy bound to a sight withholds or only counts
                (ADR-0383 §7:10).

        Raises:
            ValueError: If ``tombstone_grace`` is not strictly positive, if
                ``retention`` is set and not strictly positive, or if the default
                batch size is outside ``[0, 2**63)``. Both durations are
                refused here rather than clamped for ADR-0074 §8's reason: a zero
                or negative grace and an unbounded one break the deletion protocol
                in opposite directions.
        """
        # The type is checked before the comparison: `None <= timedelta(0)` raises
        # `TypeError`, and this constructor documents `ValueError` for a duration
        # it will not accept — whatever is wrong with it.
        if not isinstance(tombstone_grace, timedelta) or tombstone_grace <= timedelta(0):
            described = describe_untrusted(tombstone_grace)
            msg = f"tombstone_grace must be a strictly positive timedelta, got {described}"
            raise ValueError(msg)
        if retention is not None and (
            not isinstance(retention, timedelta) or retention <= timedelta(0)
        ):
            described = describe_untrusted(retention)
            msg = f"retention must be a strictly positive timedelta or None, got {described}"
            raise ValueError(msg)
        _check_page_bound("purge_batch", purge_batch)
        self._clock = checked_clock(now, owner="FakeConversationStore")
        self._new_id = new_id
        self._retention = retention
        self._grace = tombstone_grace
        self._purge_batch = purge_batch
        self._conversations: dict[str, Conversation] = {}
        #: One entry per conversation currently being mutated, and only those:
        #: :meth:`_exclusive` discards an entry once nobody holds it (#453).
        self._locks: dict[str, _Exclusion] = {}
        #: ADR-0293 §5's transcripts: per conversation, position to the message or
        #: the marker it left (§5:12). A position stays until the conversation goes.
        self._messages: dict[str, dict[int, TranscriptMessage | DeletedMessage]] = {}
        #: Per conversation, the home each deleted message's marker keeps, by position:
        #: what the durable store keeps on the marker's row and the marker a read returns
        #: carries none of (ADR-0293 §5:12), read only to refuse a reply naming it
        #: across homes (ADR-0383 §4:7).
        self._marker_homes: dict[str, dict[int, RecordHome]] = {}
        #: Per conversation, (device, message id) to position: what recognises a
        #: repeated send, deleted message or not (§4:2, §4:3).
        self._sent: dict[str, dict[tuple[str, str], int]] = {}
        #: Per conversation, the effect record an assistant's message was claimed
        #: under to its position, deleted message or not (ADR-0350 §12:9). Kept apart
        #: from the message, which a device reads and which never carries it.
        self._claimed: dict[str, dict[str, int]] = {}
        #: "My devices" (§3:1), and each conversation's devices (§3:3).
        #: "My devices" (§3:1) and the change stream's counter (§5:10), held apart so a
        #: copy bound to a sight shares them (:meth:`bound`).
        self._shared = _Shared()
        self._devices: dict[str, tuple[ChatDevice, ...]] = {}
        #: The change stream (§5:10), in sequence order; its counter is in `_shared`.
        self._changes: list[ChatChange] = []
        #: Per deletion's sequence number, every device that read its conversation at
        #: any point of its recorded history: what the store keeps beside the deletion,
        #: read by :meth:`device_changes` alone (ADR-0296 §4:5, §4:8).
        self._deleted_ends: dict[int, tuple[ChatDevice, ...]] = {}
        #: Per sequence number of a change setting a conversation's devices, the
        #: conversation's highest message position when it was recorded: the snapshot
        #: a device it adds is given is the conversation at or below it (ADR-0298
        #: §7:7). A start has none recorded, and its conversation holds no message.
        self._positions_at: dict[int, int] = {}
        #: The reader's bookkeeping (§6:6): per conversation, position to activation.
        self._taken: dict[str, dict[int, str]] = {}
        self._start_lock = asyncio.Lock()
        self._resource = SuspendableResource()
        self._sight_mode = sight_mode
        self._sight: Sight | None = None

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call open *inside* the resource it acquired (ADR-0060 §3).

        The hook ``ConversationStoreContract``'s cancellation case takes, and its
        input-observation case with it (ADR-0065): every method observes its
        arguments only after entering the resource, so the entry is both the lock
        site one clause names and the first ``await`` the other does. Test-only, and
        deliberately not on the ``ConversationStore`` seam: the Protocol grows no
        affordance for this, so the suite asks the *subject* it was handed rather
        than the contract every consumer depends on.

        Named for an *operation* rather than a mutation because the reads enter the
        resource too (#492); it holds whichever call arrives next, so a suite arms
        it after its preconditions have run.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    # --- a copy bound to a sight (ADR-0383 §7, §11) ----------------------------

    def bound(self, sight: Sight) -> FakeConversationStore:
        """This fake, bound to ``sight`` (ADR-0383 §7:1); the Protocol states the rest.

        A shallow copy sharing every piece of this fake's state, its locks and its
        modelled resource, with the sight set: the meet of the one it was already bound
        to, where it was (§6:6).

        Raises:
            ValueError: If this fake is already bound to a sight of another reader or
                activation.
        """
        view = copy.copy(self)
        view._sight = sight if self._sight is None else self._sight.meet(sight)
        return view

    def _withholding(self) -> Sight | None:
        """The sight this fake withholds by, where it is bound and withholds."""
        return None if self._sight_mode is SightMode.COUNT else self._sight

    def _holds(self, home: RecordHome | None) -> bool:
        """Whether this fake, as bound, holds a record of ``home``."""
        sight = self._withholding()
        return sight is None or sight.sees(home)

    def _standing_held(self, conversation_id: str) -> Conversation | None:
        """The conversation where it stands and this fake, as bound, holds it."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            return None
        return conversation if self._holds(conversation.home) else None

    def _message_home(self, conversation_id: str, position: int) -> RecordHome | None:
        """The home of the message, or the marker, at ``position``; ``None`` where none is."""
        held = self._messages.get(conversation_id, {}).get(position)
        if isinstance(held, TranscriptMessage):
            return held.home
        return self._marker_homes.get(conversation_id, {}).get(position)

    def _holds_message(self, conversation_id: str, position: int) -> bool:
        """Whether this fake, as bound, holds the message or marker at ``position``."""
        return self._holds(self._message_home(conversation_id, position))

    def _keeps_unheld(self, conversation_id: str) -> bool:
        """Whether the conversation keeps a message or marker this fake, as bound, does not hold."""
        return any(
            not self._holds_message(conversation_id, position)
            for position in self._messages.get(conversation_id, {})
        )

    def _counted(self, member: str, given: Iterable[RecordHome | None]) -> None:
        """Write §11:1's count of one read, where this fake is bound and only counts."""
        if self._sight is None or self._sight_mode is not SightMode.COUNT:
            return
        count_homes(self._sight, store=_STORE_CODE, member=member, homes=given)

    def _deciding(
        self, conversation: RecordHome | None, message: RecordHome | None
    ) -> RecordHome | None:
        """The home a message in ``conversation`` is withheld by, as the store counts it."""
        if self._sight is None or self._sight.sees(conversation):
            return message
        return conversation

    def _change_home(self, change: ChatChange) -> RecordHome | None:
        """The home a change is withheld by: none for a set of devices (§3:3)."""
        if isinstance(change, DevicesChangedChange):
            return None
        held = self._conversations.get(change.conversation_id or "")
        conversation = None if held is None else held.home
        if isinstance(change, MessageAddedChange):
            return self._deciding(conversation, change.message.home)
        if isinstance(change, MessageDeletedChange):
            return self._deciding(
                conversation, self._message_home(change.conversation_id, change.marker.position)
            )
        return conversation

    def _holds_change(self, change: ChatChange) -> bool:
        """Whether this fake, as bound, gives back ``change`` (ADR-0383 §3:3, §5:3)."""
        if self._withholding() is None:
            return True
        if isinstance(change, DevicesChangedChange):
            return False
        held = self._conversations.get(change.conversation_id or "")
        if held is None or not self._holds(held.home):
            return False
        if isinstance(change, MessageAddedChange):
            return self._holds(change.message.home)
        if isinstance(change, MessageDeletedChange):
            return self._holds_message(change.conversation_id, change.marker.position)
        return True

    def _given(self, change: ChatChange) -> ChatChange:
        """``change`` as given back: a start carries no devices through a withholding copy."""
        if self._withholding() is None or not isinstance(change, ConversationStartedChange):
            return change
        return change.model_copy(update={"devices": ()})

    # --- internals -----------------------------------------------------------

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error the real store raises.

        ``ConversationStoreError``, not the raw ``ValueError`` ``core`` raises: a
        fake that leaked it would certify a consumer's error handling against
        behaviour it will never meet in production (ADR-0026 §4).

        Raises:
            ConversationStoreError: If the reading is naive, indeterminate, or
                outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise ConversationStoreError(str(exc)) from exc

    @contextlib.asynccontextmanager
    async def _exclusive(self, conversation_id: str) -> AsyncIterator[None]:
        """Hold this conversation's mutation exclusion for the block (ADR-0074 §8).

        The suspension is deliberate and load-bearing (see the module docstring):
        it hands the loop back *inside* the exclusion and before the body reads
        anything, so a second mutation of the same conversation really has to
        queue. Remove the lock and the shared suite's serialisation and
        reclaim-race cases fail here rather than passing vacuously.

        **The lock is taken before the body checks whether the id names anything**,
        and that ordering is the reason a lock cannot simply be created on demand
        and dropped on the way out: it is what stops a concurrent ``stamp_deleted``
        and ``record_turn`` both observing the conversation as live. So the entry is
        reference-counted instead, and discarded only once nobody is left between
        entering here and leaving (#453) — otherwise a long-running or fuzzing
        process grows ``_locks`` for every id it was ever *asked* about, dropped
        conversations and typos included.

        Counting is safe without any lock of its own because the loop is
        single-threaded and there is **no ``await`` between reading the entry and
        incrementing it**: a caller that arrives while another is inside finds
        ``holders`` above zero, so it finds that caller's lock object rather than a
        second one. Handing two waiters two different locks for one id is the one
        failure this fake must not have — the exclusion would go on being
        *acquired* and silently stop *excluding*.
        """
        exclusion = self._locks.get(conversation_id)
        if exclusion is None:
            exclusion = _Exclusion(asyncio.Lock())
            self._locks[conversation_id] = exclusion
        exclusion.holders += 1
        try:
            async with exclusion.lock, self._resource.held():
                await asyncio.sleep(0)
                yield
        finally:
            exclusion.holders -= 1
            if not exclusion.holders:
                del self._locks[conversation_id]

    def _live(self, conversation_id: str) -> Conversation:
        """Return a conversation that exists and is not stamped, or raise.

        Raises:
            UnknownConversationError: If the id names nothing, or names a
                conversation stamped deleted — refused, never created (ADR-0074
                §1, §8) — or, bound and withholding, one this fake does not hold.
                The narrow subclass, so a sweep can tell "someone else already
                finished this" from "the store is broken" (ADR-0076 §2).
        """
        conversation = self._standing_held(conversation_id)
        if conversation is None:
            described = describe_untrusted(conversation_id)
            msg = f"no such conversation: {described}"
            raise UnknownConversationError(msg)
        return conversation

    def _next_seq(self) -> int:
        """Draw the next sequence number of the change stream (ADR-0293 §5:10).

        Drawn inside the step that makes the change and appended in the same
        expression, with no ``await`` between, so the list stays in sequence order.
        """
        self._shared.seq += 1
        return self._shared.seq

    def _drop_changes_of(self, conversation_id: str) -> None:
        """Remove every change of one conversation from the stream."""
        self._changes[:] = [one for one in self._changes if one.conversation_id != conversation_id]

    def _readers_of(self, conversation_id: str) -> tuple[ChatDevice, ...]:
        """Every device that read the conversation at any point of its recorded history.

        What its deletion keeps (ADR-0296 §4:8): the deletion clears every change of
        the conversation, a device's removal among them, so a device removed before
        it is told by the deletion instead. Each with its latest reading access.
        """
        readers: dict[str, ChatDevice] = {}
        sets = [
            one.devices
            for one in self._changes
            if isinstance(one, (ConversationStartedChange, DevicesChangedChange))
            and one.conversation_id == conversation_id
        ]
        for devices in (*sets, self._devices.get(conversation_id, ())):
            for one in devices:
                if one.access.reads:
                    readers[one.device_id] = one
        return tuple(readers[one] for one in sorted(readers))

    def _record_deletion(self, conversation_id: str, ends: tuple[ChatDevice, ...]) -> None:
        """Record a conversation's deletion, keeping the ends it had (ADR-0296 §4:5)."""
        seq = self._next_seq()
        self._deleted_ends[seq] = ends
        self._changes.append(ConversationDeletedChange(seq=seq, conversation_id=conversation_id))

    def _reaches(
        self, device: str, change: ChatChange, devices: dict[str | None, tuple[ChatDevice, ...]]
    ) -> bool:
        """Whether ``change`` reaches ``device``, ``devices`` holding the sets before it.

        The class docstring's rule on the Protocol: a change that sets a set reaches
        every device in it before or after; a deletion, every device that read the
        conversation at any point of its recorded history; every other change, the
        ends that read its conversation as its devices stood when it was recorded.
        """
        if isinstance(change, (ConversationStartedChange, DevicesChangedChange)):
            before = devices.get(change.conversation_id, ())
            return (
                _access_of(device, before) is not None
                or _access_of(device, change.devices) is not None
            )
        if isinstance(change, ConversationDeletedChange):
            ends = self._deleted_ends.get(change.seq, ())
        else:
            ends = devices.get(change.conversation_id, ())
        held = _access_of(device, ends)
        return held is not None and held.access.reads

    def _clear_chat_of(self, conversation_id: str) -> None:
        """Remove the transcript, devices and bookkeeping kept under a conversation."""
        self._messages.pop(conversation_id, None)
        self._marker_homes.pop(conversation_id, None)
        self._sent.pop(conversation_id, None)
        self._claimed.pop(conversation_id, None)
        self._devices.pop(conversation_id, None)
        self._taken.pop(conversation_id, None)

    def _names_refusal(
        self, conversation_id: str, message: NewMessage, position: int
    ) -> SendOutcome | None:
        """Refuse a message naming what it may not, or ``None`` (§4:5, ADR-0383 §4:7).

        ``NO_SUCH_REPLY`` where it replies to a position the conversation never held,
        ``position`` being the one it would take; then ``ANOTHER_HOME`` where the
        message it replies to, standing or deleted, whose marker's home is kept beside
        it, is of another home.
        """
        if message.replies_to is not None:
            if message.replies_to >= position:
                return SendOutcome.NO_SUCH_REPLY
            if message.replies_to in self._messages[conversation_id] and not (
                self._holds_message(conversation_id, message.replies_to)
            ):
                # ADR-0383 §4:8: a reply to a message this copy does not hold is
                # refused as one to a position never held.
                return SendOutcome.NO_SUCH_REPLY
            target = self._messages[conversation_id].get(message.replies_to)
            replied: RecordHome | None = (
                target.home
                if isinstance(target, TranscriptMessage)
                else self._marker_homes[conversation_id].get(message.replies_to)
            )
            if replied is not None and replied != message.home:
                return SendOutcome.ANOTHER_HOME
        return None

    def _standing(self, conversation_id: str) -> list[TranscriptMessage]:
        """The conversation's standing messages, ascending by position."""
        held = self._messages.get(conversation_id, {})
        return [one for _, one in sorted(held.items()) if isinstance(one, TranscriptMessage)]

    def _exported(self, conversation_id: str) -> list[ExportedMessage]:
        """The conversation's standing messages as the export carries them (§12:9)."""
        claims = {
            position: effect for effect, position in self._claimed.get(conversation_id, {}).items()
        }
        return [
            ExportedMessage(**dict(one), effect_id=claims.get(one.position))
            for one in self._standing(conversation_id)
        ]

    def _untaken(self, conversation_id: str) -> list[TranscriptMessage]:
        """The standing user's messages no activation has taken in, ascending."""
        taken = self._taken.get(conversation_id, {})
        return [
            one
            for one in self._standing(conversation_id)
            if one.author is MessageAuthor.USER and one.position not in taken
        ]

    # ADR-0212 §7's read-side discard has no limb this double can reach. ADR-0283 §6:6
    # leaves only "not a positive integer", and a frozen pydantic model cannot hold
    # such a value, so a dict-backed store has nowhere to keep one; the ``sqlite3``
    # store's own cases cover what a file can carry.

    # --- the contract --------------------------------------------------------

    async def start(self, *, home: RecordHome) -> Conversation:
        """Mint an id, insert the record in ``home`` if that id is absent, and return it.

        Retries on collision with a freshly minted id and gives up loudly rather
        than returning a conversation whose id names someone else's (ADR-0074 §1).
        The home is checked before anything is read or minted (ADR-0386 §6:2).

        Raises:
            ValueError: If ``home`` is one no write may carry.
            ConversationStoreError: If the retry budget is exhausted, or the id
                factory produced something that is not a usable identifier.
        """
        checked = _checked_home(home)
        async with self._start_lock, self._resource.held():
            await asyncio.sleep(0)
            for _ in range(_START_RETRY_BUDGET):
                minted = self._new_id()
                now = self._now()
                # Validated *before* it is used as a key, exactly as the
                # persistent store validates before it reaches the database. A
                # misbehaving factory can hand back something that is not a
                # usable identifier — or not even hashable — and probing the
                # index with it first would leak a raw `TypeError` where the
                # contract promises `ConversationStoreError`. Validating first
                # also makes the presence check read the *stripped* id the store
                # would go on to store, rather than the raw value.
                try:
                    conversation = Conversation(
                        id=minted, started_at=now, last_active_at=now, home=checked
                    )
                except (ValidationError, TypeError) as exc:
                    msg = f"the id factory minted an unusable id: {describe_untrusted(minted)}"
                    raise ConversationStoreError(msg) from exc
                if conversation.id in self._conversations:
                    continue
                self._conversations[conversation.id] = conversation
                # ADR-0293 §2:1, §3:1: empty, on "my devices" as they stand.
                devices = self._shared.my_devices
                self._messages[conversation.id] = {}
                self._marker_homes[conversation.id] = {}
                self._sent[conversation.id] = {}
                self._claimed[conversation.id] = {}
                self._devices[conversation.id] = devices
                self._taken[conversation.id] = {}
                self._changes.append(
                    ConversationStartedChange(
                        seq=self._next_seq(), conversation_id=conversation.id, devices=devices
                    )
                )
                return conversation
        msg = (
            f"could not mint an unused conversation id in {_START_RETRY_BUDGET} attempts; "
            f"the injected id factory is repeating"
        )
        raise ConversationStoreError(msg)

    async def get(self, conversation_id: str) -> Conversation | None:
        """Return the conversation, or ``None`` if it is absent or stamped.

        Read inside the modelled resource, like every other read: the ``sqlite3``
        store answers this from under its connection lock, so it is one of the lock
        sites ADR-0060's clause binds (#492).
        """
        async with self._resource.held():
            conversation = self._standing_held(conversation_id)
            self._counted("get", () if conversation is None else [conversation.home])
            return conversation

    async def mark_active(self, conversation_id: str) -> Conversation:
        """Record that a turn has begun, leaving ``last_turn_at`` alone.

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        async with self._exclusive(conversation_id):
            conversation = self._live(conversation_id)
            marked = conversation.model_copy(update={"last_active_at": self._now()})
            self._conversations[conversation_id] = marked
            return marked

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
    ) -> Conversation | None:
        """Record that a conversational episode landed, under the exclusion (ADR-0283 §6:2).

        **Read and write inside the one exclusion**, which is what makes a ``None``
        here the writer's deletion verification (§7:2): a ``stamp_deleted`` or a
        ``drop_if_eligible`` lands wholly before or wholly after it.

        The argument checks are before the exclusion is taken and before anything
        is read, which is "locally, before any I/O" (§6:3).

        Raises:
            ValueError: If ``episode_id`` is blank, or ``occurred_at`` is not an
                aware instant.
        """
        _, checked_at = _checked_turn(episode_id, occurred_at)
        async with self._exclusive(conversation_id):
            conversation = self._standing_held(conversation_id)
            if conversation is None:
                return None
            recorded = conversation.model_copy(update={"last_turn_at": checked_at})
            self._conversations[conversation_id] = recorded
            return recorded

    async def stamped_conversation_ids(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of stamped-but-not-dropped ids, ``id`` ascending.

        The cursor is placed **lexically** and never by looking the row up: this
        walk's rows are removed by the very sweep walking them, so the id the
        caller carries has to be enough to position the next batch on its own
        (ADR-0076 §2). An ``after_id`` naming no row is therefore a valid cursor.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        if batch == 0:
            self._counted("stamped_conversation_ids", ())
            return []
        async with self._resource.held():  # a locked read on the durable store (#492)
            stamped = sorted(
                (
                    one
                    for one in self._conversations.values()
                    if one.deleted_at is not None and self._holds(one.home)
                ),
                key=lambda one: one.id,
            )
        if after_id is not None:
            stamped = [one for one in stamped if one.id > after_id]
        self._counted("stamped_conversation_ids", (one.home for one in stamped[:batch]))
        return [one.id for one in stamped[:batch]]

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List unstamped conversations, last activity first, ``id`` breaking ties.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        if limit == 0:
            self._counted("recent", ())
            return []
        async with self._resource.held():  # a locked read on the durable store (#492)
            live = [
                one
                for one in self._conversations.values()
                if one.deleted_at is None and self._holds(one.home)
            ]
        page = _by_last_activity(live)[offset : offset + limit]
        self._counted("recent", (one.home for one in page))
        return page

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp the conversation deleted, returning whether this call did it."""
        async with self._exclusive(conversation_id):
            conversation = self._standing_held(conversation_id)
            if conversation is None or self._keeps_unheld(conversation_id):
                # Bound and withholding: one it does not hold, or one keeping what it
                # does not hold, is not deleted (ADR-0383 §7:5).
                return False
            self._conversations[conversation_id] = conversation.model_copy(
                update={"deleted_at": self._now()}
            )
            # ADR-0293 §2:3: the conversation's transcript goes with it, and its
            # devices learn of it from the one change left in the stream, which
            # keeps every device that read it (ADR-0296 §4:5, §4:8).
            ends = self._readers_of(conversation_id)
            self._clear_chat_of(conversation_id)
            self._drop_changes_of(conversation_id)
            self._record_deletion(conversation_id, ends)
            return True

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove the record and what is kept under it if still eligible, under the exclusion.

        Re-checks eligibility here rather than trusting the caller's earlier
        reading, which is what stops a reclaim destroying a conversation the user
        has just come back to (ADR-0074 §9.4).
        """
        async with self._exclusive(conversation_id):
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return False
            if not self._holds(conversation.home) or self._keeps_unheld(conversation_id):
                return False  # bound and withholding, not held, or keeping what is not
            now = self._now()
            # `now - stamp >= duration` rather than `stamp + duration <= now`:
            # equivalent, and only the first cannot overflow at a clock reading
            # near `datetime.max`, which `checked_clock` admits (ADR-0026 §3).
            stamped = conversation.deleted_at is not None
            if conversation.deleted_at is not None:
                eligible = now - conversation.deleted_at >= self._grace
            else:
                # ADR-0293 §5:4: reclaim never drops a conversation holding a message.
                eligible = (
                    self._retention is not None
                    and now - conversation.last_active_at >= self._retention
                    and not self._standing(conversation_id)
                )
            if not eligible:
                return False
            ends = self._readers_of(conversation_id)
            self._clear_chat_of(conversation_id)
            del self._conversations[conversation_id]
            if not stamped:
                # A reclaim is a deletion as far as the conversation's devices go;
                # a stamped one recorded its deletion when it was stamped.
                self._drop_changes_of(conversation_id)
                self._record_deletion(conversation_id, ends)
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: its unstamped conversations (ADR-0283 §4:3).

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether
        a conversation's channel still holds an episode, and the user-facing export
        is composed in `orchestration` (ADR-0074 §9).
        """
        async with self._resource.held():  # a locked read on the durable store (#492)
            live = _by_last_activity(
                [
                    one
                    for one in self._conversations.values()
                    if one.deleted_at is None and self._holds(one.home)
                ]
            )
            messages = [
                message
                for one in live
                for message in self._exported(one.id)
                if self._holds(message.home)
            ]
            self._counted(
                "export",
                [
                    *(one.home for one in live),
                    *(
                        self._deciding(self._conversations[one.conversation_id].home, one.home)
                        for one in messages
                    ),
                ],
            )
            return ConversationExport(
                exported_at=self._now(),
                conversations=tuple(live),
                messages=tuple(messages),
            )

    # --- the chat space (ADR-0293) --------------------------------------------

    async def append_message(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        """Write one message into the transcript, under the exclusion (ADR-0293 §4, §6).

        The message's home is checked before anything is read (ADR-0386 §6:2), and the
        message recorded carries it.

        Raises:
            ValueError: If the message's home is one no write may carry.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        _checked_home(message.home)
        async with self._exclusive(conversation_id):
            self._live(conversation_id)
            held = self._messages[conversation_id]
            if message.author is MessageAuthor.USER:
                # Narrowed by `NewMessage`'s own validator: a user's message carries both.
                if message.device_id is None or message.message_id is None:  # pragma: no cover
                    msg = "a user's message carries its device and message id"
                    raise ValueError(msg)
                sent = self._sent[conversation_id].get((message.device_id, message.message_id))
                if sent is not None:
                    return MessageReceipt(
                        conversation_id=conversation_id,
                        outcome=SendOutcome.REPEATED,
                        position=sent,
                    )
                ends = {
                    one.device_id for one in self._devices[conversation_id] if one.access.writes
                }
                if message.device_id not in ends:
                    return MessageReceipt(
                        conversation_id=conversation_id, outcome=SendOutcome.NOT_AN_END
                    )
            elif message.effect_id is not None:
                claimed = self._claimed[conversation_id].get(message.effect_id)
                if claimed is not None:
                    return MessageReceipt(
                        conversation_id=conversation_id,
                        outcome=SendOutcome.REPEATED,
                        position=claimed,
                    )
            position = max(held, default=0) + 1
            if refused := self._names_refusal(conversation_id, message, position):
                return MessageReceipt(conversation_id=conversation_id, outcome=refused)
            recorded = TranscriptMessage(
                conversation_id=conversation_id,
                position=position,
                written_at=self._now(),
                **message.model_dump(exclude={"effect_id"}),
            )
            held[position] = recorded
            if recorded.device_id is not None and recorded.message_id is not None:
                self._sent[conversation_id][(recorded.device_id, recorded.message_id)] = position
            if message.effect_id is not None:
                self._claimed[conversation_id][message.effect_id] = position
            self._changes.append(MessageAddedChange(seq=self._next_seq(), message=recorded))
            return MessageReceipt(
                conversation_id=conversation_id, outcome=SendOutcome.RECORDED, position=position
            )

    async def delete_message(self, conversation_id: str, position: int) -> bool:
        """Delete one message, leaving its marker, under the exclusion (ADR-0293 §5:8).

        Raises:
            ValueError: If ``position`` is not an ``int`` in ``[1, 2**63)``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        _check_position("position", position)
        async with self._exclusive(conversation_id):
            self._live(conversation_id)
            held = self._messages[conversation_id]
            standing = held.get(position)
            if not isinstance(standing, TranscriptMessage) or not self._holds(standing.home):
                return False
            marker = DeletedMessage(conversation_id=conversation_id, position=position)
            held[position] = marker
            self._marker_homes[conversation_id][position] = standing.home
            self._changes[:] = [
                one
                for one in self._changes
                if not (
                    isinstance(one, MessageAddedChange)
                    and one.conversation_id == conversation_id
                    and one.message.position == position
                )
            ]
            self._changes.append(MessageDeletedChange(seq=self._next_seq(), marker=marker))
            return True

    async def effect_position(self, conversation_id: str, effect_id: str, /) -> int | None:
        """Read where the message claimed under ``effect_id`` stands (ADR-0350 §12:9).

        Raises:
            ValueError: If ``effect_id`` is not a non-blank ``str``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        effect = _checked_effect_id(effect_id)
        async with self._resource.held():  # a locked read on the durable store (#492)
            conversation = self._live(conversation_id)
            position = self._claimed[conversation_id].get(effect)
            if position is not None and not self._holds_message(conversation_id, position):
                position = None  # bound and withholding, a message never written
            self._counted(
                "effect_position",
                [
                    conversation.home,
                    *(
                        ()
                        if position is None
                        else [
                            self._deciding(
                                conversation.home, self._message_home(conversation_id, position)
                            )
                        ]
                    ),
                ],
            )
            return position

    async def transcript(
        self,
        conversation_id: str,
        *,
        before: int | None = None,
        limit: int = _DEFAULT_TRANSCRIPT_PAGE,
    ) -> TranscriptPage | None:
        """Read the last ``limit`` entries before ``before``, ascending (ADR-0293 §5:13).

        Raises:
            ValueError: If ``before`` or ``limit`` is out of range.
        """
        if before is not None:
            _check_position("before", before)
        _check_page_bound("limit", limit)
        async with self._resource.held():  # a locked read on the durable store (#492)
            conversation = self._standing_held(conversation_id)
            if conversation is None:
                self._counted("transcript", ())
                return None
            held = self._messages[conversation_id]
            positions = [
                one
                for one in sorted(held)
                if (before is None or one < before) and self._holds_message(conversation_id, one)
            ]
            chosen = positions[-limit:] if limit else []
            self._counted(
                "transcript",
                [
                    conversation.home,
                    *(
                        self._deciding(conversation.home, self._message_home(conversation_id, one))
                        for one in chosen
                    ),
                ],
            )
            return TranscriptPage(
                conversation_id=conversation_id,
                entries=tuple(held[one] for one in chosen),
                as_of=self._shared.seq,
            )

    async def changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[str] | None = None,
        limit: int = _DEFAULT_CHANGES_PAGE,
    ) -> ChatChanges:
        """Read every change after ``after``, in sequence order (ADR-0293 §5:10, §5:11).

        Raises:
            ValueError: If ``after`` or ``limit`` is out of range, or
                ``conversation_ids`` is malformed.
        """
        _check_page_bound("after", after)
        _check_page_bound("limit", limit)
        named = _checked_conversation_ids(conversation_ids)
        async with self._resource.held():  # a locked read on the durable store (#492)
            if limit == 0:
                self._counted("changes", ())
                return ChatChanges(next_after=after)
            wanted = None if named is None else set(named)
            page: list[ChatChange] = []
            for one in self._changes:
                if one.seq <= after or not self._holds_change(one):
                    continue
                if wanted is not None and one.conversation_id not in wanted | {None}:
                    continue
                page.append(one)
                if len(page) == limit:
                    break
            self._counted("changes", (self._change_home(one) for one in page))
            # Where the page is not full, the cursor is the stream's head: a store-wide
            # figure that counts writes, alike bound or not (ADR-0383 §8:5).
            next_after = page[-1].seq if len(page) == limit else self._shared.seq
            return ChatChanges(
                changes=tuple(self._given(one) for one in page), next_after=next_after
            )

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Return "my devices", ``device_id`` ascending (ADR-0293 §3:1)."""
        async with self._resource.held():  # a locked read on the durable store (#492)
            if self._withholding() is not None:
                return ()  # a device row is given back by no bound store (ADR-0383 §3:3)
            self._counted("my_devices", (None for _ in self._shared.my_devices))
            return self._shared.my_devices

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices", recording the change where it is one (ADR-0293 §3:1).

        One step against ``start``, which copies the set: both hold the lock
        ``start`` mints under.

        Raises:
            ValueError: If ``devices`` is malformed.
        """
        wanted = checked_chat_devices(devices)
        async with self._start_lock, self._resource.held():
            await asyncio.sleep(0)
            if wanted == self._shared.my_devices:
                return False
            self._shared.my_devices = wanted
            self._changes.append(DevicesChangedChange(seq=self._next_seq(), devices=wanted))
            return True

    async def conversation_devices(self, conversation_id: str) -> tuple[ChatDevice, ...] | None:
        """Return a conversation's devices, or ``None`` if absent or stamped (§3:3)."""
        async with self._resource.held():  # a locked read on the durable store (#492)
            conversation = self._standing_held(conversation_id)
            if conversation is None:
                self._counted("conversation_devices", ())
                return None
            if self._withholding() is not None:
                return ()  # a device row is given back by no bound store (§3:3)
            devices = self._devices[conversation_id]
            self._counted("conversation_devices", [conversation.home, *(None for _ in devices)])
            return devices

    async def set_conversation_devices(
        self, conversation_id: str, devices: Sequence[ChatDevice]
    ) -> bool:
        """Replace a conversation's devices, under the exclusion (ADR-0293 §3:3).

        Raises:
            ValueError: If ``devices`` is malformed.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        wanted = checked_chat_devices(devices)
        async with self._exclusive(conversation_id):
            self._live(conversation_id)
            if wanted == self._devices[conversation_id]:
                return False
            self._devices[conversation_id] = wanted
            seq = self._next_seq()
            self._positions_at[seq] = max(self._messages[conversation_id], default=0)
            self._changes.append(
                DevicesChangedChange(seq=seq, conversation_id=conversation_id, devices=wanted)
            )
            return True

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        """Mark the named user's messages taken in, under the exclusion (ADR-0293 §6:6).

        Raises:
            ValueError: If ``positions`` or ``activation_id`` is malformed.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        named = _checked_positions(positions)
        activation = _checked_activation_id(activation_id)
        async with self._exclusive(conversation_id):
            self._live(conversation_id)
            held = self._messages[conversation_id]
            taken = self._taken[conversation_id]
            marked: list[int] = []
            for position in sorted(set(named)):
                message = held.get(position)
                if not isinstance(message, TranscriptMessage) or not self._holds(message.home):
                    continue
                if message.author is not MessageAuthor.USER or position in taken:
                    continue
                taken[position] = activation
                marked.append(position)
            return tuple(marked)

    async def untaken_messages(
        self, conversation_id: str, *, limit: int = _DEFAULT_AWAITING_PAGE
    ) -> tuple[TranscriptMessage, ...]:
        """Return the user's standing messages not yet taken in (ADR-0293 §6:3, §6:9).

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        async with self._resource.held():  # a locked read on the durable store (#492)
            if limit == 0:
                self._counted("untaken_messages", ())
                return ()
            conversation = self._standing_held(conversation_id)
            if conversation is None:
                self._counted("untaken_messages", ())
                return ()
            found = [one for one in self._untaken(conversation_id) if self._holds(one.home)]
            self._counted(
                "untaken_messages",
                [
                    conversation.home,
                    *(self._deciding(conversation.home, one.home) for one in found[:limit]),
                ],
            )
            return tuple(found[:limit])

    async def conversations_awaiting(
        self, *, limit: int = _DEFAULT_AWAITING_PAGE, after_id: str | None = None
    ) -> list[str]:
        """Page over conversations holding an untaken user's message (ADR-0293 §6:9).

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        if limit == 0:
            self._counted("conversations_awaiting", ())
            return []
        async with self._resource.held():  # a locked read on the durable store (#492)
            awaiting = sorted(
                (
                    one
                    for one in self._conversations.values()
                    if one.deleted_at is None
                    and self._holds(one.home)
                    and any(self._holds(message.home) for message in self._untaken(one.id))
                ),
                key=lambda one: one.id,
            )
        if after_id is not None:
            awaiting = [one for one in awaiting if one.id > after_id]
        self._counted("conversations_awaiting", (one.home for one in awaiting[:limit]))
        return [one.id for one in awaiting[:limit]]

    async def taken_in(
        self, conversation_id: str, *, positions: Sequence[int]
    ) -> Mapping[int, str]:
        """Return which activation took in each named message, where one did (§6:6).

        Raises:
            ValueError: If ``positions`` is malformed.
        """
        named = _checked_positions(positions)
        if not named:
            self._counted("taken_in", ())
            return {}
        async with self._resource.held():  # a locked read on the durable store (#492)
            conversation = self._standing_held(conversation_id)
            if conversation is None:
                self._counted("taken_in", ())
                return {}
            taken = self._taken[conversation_id]
            found = {
                one: taken[one]
                for one in named
                if one in taken and self._holds_message(conversation_id, one)
            }
            self._counted(
                "taken_in",
                [
                    conversation.home,
                    *(
                        self._deciding(conversation.home, self._message_home(conversation_id, one))
                        for one in found
                    ),
                ],
            )
            return found

    # --- the chat space: one device's view (ADR-0296 §3, §4) ------------------

    async def device_changes(
        self, device_id: str, *, after: int, limit: int = _DEFAULT_CHANGES_PAGE
    ) -> DeviceChanges:
        """Read the changes after ``after`` that ``device_id`` may see (ADR-0296 §4:5).

        Walks the whole stream from its start, carrying each set of devices forward
        as the changes that set it pass, so each change is judged against the set as
        it stood when it was recorded — the walk the ``sqlite3`` store does per change
        with a subquery. A change that adds the device as an end for reading carries
        the conversation's snapshot as of that change (ADR-0298 §7:6, §7:7).

        Raises:
            ValueError: If ``device_id`` is malformed, or ``after`` or ``limit`` is
                out of range.
        """
        device = _checked_device_id(device_id)
        _check_page_bound("after", after)
        _check_page_bound("limit", limit)
        async with self._resource.held():  # a locked read on the durable store (#492)
            if limit == 0:
                self._counted("device_changes", ())
                return DeviceChanges(next_after=after)
            if self._withholding() is not None:
                # Holding no device row, a withholding copy reaches no device with any
                # change, and its cursor moves to the head (ADR-0383 §3:3, §8:5).
                return DeviceChanges(next_after=self._shared.seq)
            devices: dict[str | None, tuple[ChatDevice, ...]] = {}
            page: list[DeviceChange] = []
            for one in self._changes:
                if one.seq > after and self._reaches(device, one, devices):
                    page.append(self._with_snapshot(device, one, devices))
                    if len(page) == limit:
                        self._counted("device_changes", (None for _ in page))
                        return DeviceChanges(changes=tuple(page), next_after=page[-1].seq)
                if isinstance(one, (ConversationStartedChange, DevicesChangedChange)):
                    devices[one.conversation_id] = one.devices
            self._counted("device_changes", (None for _ in page))
            return DeviceChanges(changes=tuple(page), next_after=self._shared.seq)

    def _with_snapshot(
        self, device: str, change: ChatChange, devices: dict[str | None, tuple[ChatDevice, ...]]
    ) -> DeviceChange:
        """``change``, with the snapshot it carries where it adds ``device`` as a reader."""
        if (
            not isinstance(change, (ConversationStartedChange, DevicesChangedChange))
            or change.conversation_id is None
        ):
            return DeviceChange(change=change)
        now = _access_of(device, change.devices)
        then = _access_of(device, devices.get(change.conversation_id, ()))
        if now is None or not now.access.reads or (then is not None and then.access.reads):
            return DeviceChange(change=change)
        highest = self._positions_at.get(change.seq, 0)
        held = self._messages.get(change.conversation_id, {})
        chosen = [one for one in sorted(held) if one <= highest][-CHAT_SNAPSHOT_ENTRIES:]
        return DeviceChange(change=change, snapshot=tuple(held[one] for one in chosen))

    async def device_conversations(
        self,
        device_id: str,
        *,
        limit: int = _DEFAULT_DEVICE_CONVERSATIONS_PAGE,
        offset: int = 0,
    ) -> list[DeviceConversation]:
        """List the unstamped conversations ``device_id`` reads, as ``recent`` orders them.

        Raises:
            ValueError: If ``device_id`` is malformed, or ``limit`` or ``offset`` is
                out of range.
        """
        device = _checked_device_id(device_id)
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        if limit == 0:
            self._counted("device_conversations", ())
            return []
        if self._withholding() is not None:
            return []  # each entry is a device row's access, which §3:3 gives back none of
        async with self._resource.held():  # a locked read on the durable store (#492)
            access = {
                conversation_id: held
                for conversation_id, devices in self._devices.items()
                if (held := _access_of(device, devices)) is not None and held.access.reads
            }
            live = [
                one
                for one in self._conversations.values()
                if one.deleted_at is None and one.id in access
            ]
        page = _by_last_activity(live)[offset : offset + limit]
        self._counted("device_conversations", (None for _ in page))
        return [DeviceConversation(conversation=one, access=access[one.id].access) for one in page]

    async def remove_device(self, device_id: str) -> bool:
        """Remove a device from every set of devices, as one step (ADR-0296 §3:6).

        Held under the lock ``start`` and ``set_my_devices`` take, inside the
        modelled resource every per-conversation mutation also holds, so nothing on
        "my devices" or on any conversation lands between two of its removals.

        Raises:
            ValueError: If ``device_id`` is malformed.
        """
        device = _checked_device_id(device_id)
        async with self._start_lock, self._resource.held():
            await asyncio.sleep(0)
            removed = False
            if _access_of(device, self._shared.my_devices) is not None:
                self._shared.my_devices = tuple(
                    one for one in self._shared.my_devices if one.device_id != device
                )
                self._changes.append(
                    DevicesChangedChange(seq=self._next_seq(), devices=self._shared.my_devices)
                )
                removed = True
            for conversation_id in sorted(self._devices):
                devices = self._devices[conversation_id]
                # A stamp clears its conversation's devices, so every set held here
                # is a standing conversation's.
                if _access_of(device, devices) is None:
                    continue
                kept = tuple(one for one in devices if one.device_id != device)
                self._devices[conversation_id] = kept
                self._changes.append(
                    DevicesChangedChange(
                        seq=self._next_seq(), conversation_id=conversation_id, devices=kept
                    )
                )
                removed = True
            return removed
