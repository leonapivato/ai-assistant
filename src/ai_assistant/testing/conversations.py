"""A canonical in-memory :class:`~ai_assistant.core.protocols.ConversationStore` fake.

The shared test double for the ``ConversationStore`` contract (ADR-0074 §9), so a
subsystem that depends on conversations — `orchestration`'s capture stage above
all — can test against a real, contract-correct store *without importing a
subsystem's internals* (CLAUDE.md golden rule 1). It is deliberately minimal: two
dicts, an injected clock and an injected id factory. Like the store it doubles for,
it holds no history — a conversation's turns are the episodes on its channel in the
``MemoryStore`` (ADR-0283 §1, §4).

It honours the whole contract, including the parts a dict gets for free only if
they are written down: the per-conversation mutation exclusion, the stamped-once
delivery rows, and the tombstone's asymmetric visibility (hidden from every
presenting read, still enumerable by the sweeps).

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    FIRST_TURN_ORDINAL,
    Conversation,
    ConversationExport,
    Identifier,
    SpokenDeliveryState,
    UtcInstant,
    describe_untrusted,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import SpokenDelivery
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

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

#: The most episode ids one :meth:`FakeConversationStore.deliveries` call takes
#: (ADR-0283 §6:5). Duplicated from the production store rather than shared, for
#: :data:`_PAGE_BOUND`'s reason.
_MAX_DELIVERY_IDS: Final = 1000

#: ``record_turn``'s two checked arguments go through ``core``'s own annotated types,
#: exactly as the production store's do, so the two refuse the same values.
_EPISODE_ID: Final[TypeAdapter[str]] = TypeAdapter(Identifier)
_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _random_id() -> str:
    """Mint an opaque, random, device-agnostic conversation id (ADR-0074 §1)."""
    return str(uuid4())


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    Duplicated from the production store rather than shared, for the reason given
    on :data:`_PAGE_BOUND`. **The type is part of the range**: without it this fake
    would slice a list on ``limit=1.5`` and raise ``TypeError`` where the real
    store raises out of the driver, and two stores disagreeing about a bad
    argument is the failure ADR-0073 §2 exists to stop. ``bool`` is refused with
    the rest, being an ``int`` subclass that is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _checked_turn(
    episode_id: object, occurred_at: object, delivery: SpokenDelivery | None
) -> tuple[str, datetime]:
    """Check ``record_turn``'s arguments before anything is read (ADR-0283 §6:3).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason; both go through ``core``'s annotated types, so they refuse the same values.

    Returns:
        The episode id and the instant, as ``core`` normalises them.

    Raises:
        ValueError: If ``delivery`` is given and is not ``UNKNOWN``, ``episode_id``
            is not a non-blank ``str``, or ``occurred_at`` is not an aware instant.
    """
    if delivery is not None and delivery.state is not SpokenDeliveryState.UNKNOWN:
        msg = (
            f"record_turn writes only an UNKNOWN delivery, got {delivery.state.value}: "
            f"a device's report reaches a row through record_delivery (ADR-0283 §6:3)"
        )
        raise ValueError(msg)
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


def _checked_episode_ids(episode_ids: object) -> list[str]:
    """Check ``deliveries``' ids before anything is read (ADR-0283 §6:5).

    Duplicated from the production store rather than shared, for :data:`_PAGE_BOUND`'s
    reason. A bare ``str`` is refused by name rather than read as its characters.

    Returns:
        The ids, as a list in the order given.

    Raises:
        ValueError: If ``episode_ids`` is a ``str`` or not a sequence, holds more than
            :data:`_MAX_DELIVERY_IDS` ids, or holds an element that is not a ``str``.
    """
    if isinstance(episode_ids, (str, bytes)) or not isinstance(episode_ids, Sequence):
        msg = f"episode_ids must be a sequence of str, got {describe_untrusted(episode_ids)}"
        raise ValueError(msg)
    ids = list(episode_ids)
    if len(ids) > _MAX_DELIVERY_IDS:
        msg = f"episode_ids holds {len(ids)} ids; at most {_MAX_DELIVERY_IDS} are read at once"
        raise ValueError(msg)
    for one in ids:
        if type(one) is not str:
            msg = f"episode_ids holds an id that is not a str: {describe_untrusted(one)}"
            raise ValueError(msg)
    return ids


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

    def __init__(
        self,
        *,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _random_id,
        retention: timedelta | None = _DEFAULT_EPISODE_RETENTION,
        tombstone_grace: timedelta = _DEFAULT_TOMBSTONE_GRACE,
        purge_batch: int = _DEFAULT_PURGE_BATCH,
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
        #: ADR-0283 §6's delivery rows: per conversation, episode id to delivery.
        self._deliveries: dict[str, dict[str, SpokenDelivery]] = {}
        #: One entry per conversation currently being mutated, and only those:
        #: :meth:`_exclusive` discards an entry once nobody holds it (#453).
        self._locks: dict[str, _Exclusion] = {}
        self._start_lock = asyncio.Lock()
        self._resource = SuspendableResource()

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
                §1, §8). The narrow subclass, so a sweep can tell "someone else
                already finished this" from "the store is broken" (ADR-0076 §2).
        """
        conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            described = describe_untrusted(conversation_id)
            msg = f"no such conversation: {described}"
            raise UnknownConversationError(msg)
        return conversation

    # ADR-0212 §7's read-side discard has no limb this double can reach. ADR-0283 §6:6
    # leaves only "not a positive integer", and a frozen pydantic model cannot hold
    # such a value, so a dict-backed store has nowhere to keep one; the ``sqlite3``
    # store's own cases cover what a file can carry.

    # --- the contract --------------------------------------------------------

    async def start(self) -> Conversation:
        """Mint an id, insert the record if that id is absent, and return it.

        Retries on collision with a freshly minted id and gives up loudly rather
        than returning a conversation whose id names someone else's (ADR-0074 §1).

        Raises:
            ConversationStoreError: If the retry budget is exhausted, or the id
                factory produced something that is not a usable identifier.
        """
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
                    conversation = Conversation(id=minted, started_at=now, last_active_at=now)
                except (ValidationError, TypeError) as exc:
                    msg = f"the id factory minted an unusable id: {describe_untrusted(minted)}"
                    raise ConversationStoreError(msg) from exc
                if conversation.id in self._conversations:
                    continue
                self._conversations[conversation.id] = conversation
                self._deliveries[conversation.id] = {}
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
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                return None
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
        delivery: SpokenDelivery | None = None,
    ) -> Conversation | None:
        """Record that a conversational episode landed, under the exclusion (ADR-0283 §6:2).

        **Read and write inside the one exclusion**, which is what makes a ``None``
        here the writer's deletion verification (§7:2): a ``stamp_deleted`` or a
        ``drop_if_eligible`` lands wholly before or wholly after it. The delivery
        row is written only where none exists, so a retried capture cannot reset a
        stamped delivery (ADR-0205 §1).

        The argument checks are before the exclusion is taken and before anything
        is read, which is "locally, before any I/O" (§6:3).

        Raises:
            ValueError: If ``delivery`` is not ``UNKNOWN``, ``episode_id`` is blank,
                or ``occurred_at`` is not an aware instant.
        """
        checked_id, checked_at = _checked_turn(episode_id, occurred_at, delivery)
        async with self._exclusive(conversation_id):
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                return None
            recorded = conversation.model_copy(update={"last_turn_at": checked_at})
            self._conversations[conversation_id] = recorded
            if delivery is not None:
                # ADR-0205 §1: a row already held for the episode stands as it is.
                self._deliveries[conversation_id].setdefault(checked_id, delivery)
            return recorded

    async def record_delivery(
        self, conversation_id: str, *, episode_id: str, delivery: SpokenDelivery
    ) -> bool:
        """Stamp the episode's delivery row if it is still ``UNKNOWN`` (ADR-0283 §6:4).

        **Read and write inside the one exclusion** (ADR-0205 §3), which is what the
        suite's two-reports-racing
        cases are asserting against: the exclusion hands the loop back before this
        reads anything, so a second report really has to queue and really does find
        the state the first left.

        The ``UNKNOWN`` refusal is before the exclusion is taken and before anything
        is read, which is "locally, before any I/O".

        Raises:
            ValueError: If ``delivery.state`` is ``UNKNOWN``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        if delivery.state is SpokenDeliveryState.UNKNOWN:
            msg = (
                "record_delivery does not carry an UNKNOWN delivery: that value is written "
                "by capture through record_turn, and a device that does not know reports "
                "nothing (ADR-0205 §2, §3)"
            )
            raise ValueError(msg)
        async with self._exclusive(conversation_id):
            self._live(conversation_id)
            held = self._deliveries[conversation_id]
            current = held.get(episode_id)
            if current is None or current.state is not SpokenDeliveryState.UNKNOWN:
                # Any of ADR-0205 §3's conditions failing: the episode belongs to
                # another conversation or to nothing, or its row already carries a
                # stamp. An episode with no row is not given one by this operation.
                return False
            held[episode_id] = delivery
            return True

    async def deliveries(
        self, conversation_id: str, *, episode_ids: Sequence[str]
    ) -> Mapping[str, SpokenDelivery]:
        """Return the delivery rows the conversation holds among ``episode_ids``.

        Read inside the modelled resource, like every other read (#492). An absent or
        stamped conversation answers with an empty mapping, and the mapping is a
        fresh one on every call.

        Raises:
            ValueError: If ``episode_ids`` is a ``str``, holds more than 1000 ids, or
                holds an element that is not a ``str``.
        """
        ids = _checked_episode_ids(episode_ids)
        if not ids:
            return {}
        async with self._resource.held():
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                return {}
            held = self._deliveries[conversation_id]
            return {one: held[one] for one in ids if one in held}

    async def record_observed(
        self, conversation_id: str, *, through_episode: int
    ) -> Conversation | None:
        """Advance the watermark if it moves forward (ADR-0212 §8, ADR-0283 §6:6).

        **The condition is read and the row written inside the one exclusion**
        (ADR-0212 §8), which is what the suite's two-advances-racing case is
        asserting against: the exclusion hands the loop back before this reads
        anything, so a second advance really has to queue and really does find the
        position the first left. Nothing bounds the value above: it is an episode
        number, which this store cannot see.

        The range refusal is before the exclusion is taken and before anything is
        read, which is "locally, before any I/O".

        Raises:
            ValueError: If ``through_episode`` is outside ``[1, 2**63)``.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        _check_page_bound("through_episode", through_episode, floor=FIRST_TURN_ORDINAL)
        async with self._exclusive(conversation_id):
            conversation = self._live(conversation_id)
            recorded = conversation.observed_through
            if recorded is not None and through_episode <= recorded:
                # An attempt that loses is an attempt whose position already stands:
                # nothing is written and nothing is raised, `record_delivery`'s shape.
                return None
            stamped = conversation.model_copy(update={"observed_through": through_episode})
            self._conversations[conversation_id] = stamped
            return stamped

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
            return []
        async with self._resource.held():  # a locked read on the durable store (#492)
            stamped = sorted(
                one.id for one in self._conversations.values() if one.deleted_at is not None
            )
        if after_id is not None:
            stamped = [one for one in stamped if one > after_id]
        return stamped[:batch]

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List unstamped conversations, last activity first, ``id`` breaking ties.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        if limit == 0:
            return []
        async with self._resource.held():  # a locked read on the durable store (#492)
            live = [one for one in self._conversations.values() if one.deleted_at is None]
        return _by_last_activity(live)[offset : offset + limit]

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp the conversation deleted, returning whether this call did it."""
        async with self._exclusive(conversation_id):
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                return False
            self._conversations[conversation_id] = conversation.model_copy(
                update={"deleted_at": self._now()}
            )
            return True

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove the record and its delivery rows if still eligible, under the exclusion.

        Re-checks eligibility here rather than trusting the caller's earlier
        reading, which is what stops a reclaim destroying a conversation the user
        has just come back to (ADR-0074 §9.4).
        """
        async with self._exclusive(conversation_id):
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return False
            now = self._now()
            # `now - stamp >= duration` rather than `stamp + duration <= now`:
            # equivalent, and only the first cannot overflow at a clock reading
            # near `datetime.max`, which `checked_clock` admits (ADR-0026 §3).
            if conversation.deleted_at is not None:
                eligible = now - conversation.deleted_at >= self._grace
            else:
                eligible = (
                    self._retention is not None
                    and now - conversation.last_active_at >= self._retention
                )
            if not eligible:
                return False
            self._deliveries.pop(conversation_id, None)  # ADR-0283 §6:7
            del self._conversations[conversation_id]
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: its unstamped conversations (ADR-0283 §4:3).

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether
        a conversation's channel still holds an episode, and the user-facing export
        is composed in `orchestration` (ADR-0074 §9).
        """
        async with self._resource.held():  # a locked read on the durable store (#492)
            live = _by_last_activity(
                [one for one in self._conversations.values() if one.deleted_at is None]
            )
            return ConversationExport(
                exported_at=self._now(),
                conversations=tuple(live),
            )
