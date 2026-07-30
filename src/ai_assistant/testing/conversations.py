"""A canonical in-memory :class:`~ai_assistant.core.protocols.ConversationStore` fake.

The shared test double for the ``ConversationStore`` contract (ADR-0074 §9), so a
subsystem that depends on conversations — `orchestration`'s capture stage above
all — can test against a real, contract-correct store *without importing a
subsystem's internals* (CLAUDE.md golden rule 1). It is deliberately minimal: two
dicts, an injected clock and an injected id factory.

It honours the whole contract, including the parts a dict gets for free only if
they are written down: the per-conversation mutation exclusion, the ordinal
invariant, the reserved episode-id namespace, and the tombstone's asymmetric
visibility (hidden from every presenting read, still enumerable by the sweeps).

**Its critical sections really suspend.** Each mutation yields to the event loop
inside its exclusion, before reading the state it is about to change. Without
that, a fake backed by a dict would satisfy every concurrency case in the shared
suite by accident — nothing in it ever awaits, so nothing can interleave — and
the suite's serialisation clauses would be vacuous against exactly the
implementation they most need to hold for. With it, dropping the lock makes those
cases fail here as they would against a real store.

**Its mutations pass through a modelled resource**, a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` entered inside the
exclusion. A dict needs no serialising, so without one this fake could only opt out
of ADR-0060's cancellation clause — and the suite's case would then run solely
against the ``sqlite3`` store, which is the implementation that already got it
right. Uncontended, entering it does not yield, so it adds no interleaving point
that was not there before; under contention it only reinforces the exclusion.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    FIRST_TURN_ORDINAL,
    Conversation,
    ConversationExport,
    ConversationTurn,
    describe_untrusted,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ParkedBinding
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: One past the largest value a paging argument accepts — the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2). Duplicated from the
#: production store rather than shared, exactly as ``MemoryStore``'s bound is:
#: ``ai_assistant.testing`` may not import a subsystem (golden rule 1), and a fake
#: looser than the contract would certify consumers a real store rejects.
_PAGE_BOUND = 2**63

#: The store's configured replay window: what :meth:`FakeConversationStore.turns`
#: returns to a caller that names no ``limit`` (ADR-0074 §9.3). Finite, and the
#: same value every caller gets by saying nothing.
_DEFAULT_TAIL_LIMIT = 20

#: The batch :meth:`FakeConversationStore.episodes_to_purge` yields by default.
_DEFAULT_PURGE_BATCH = 100

#: The retention horizon a conversation record is judged against when nobody
#: injects one (ADR-0074 §7). **Finite**, because an unbounded default would ship
#: an ever-growing Tier 1 index with no cap decision behind it; ``None`` means
#: "keep forever", is the user's deliberate choice, and switches reclaim off.
#: The ``Settings`` field this mirrors is owed by the capture/lifecycle lane.
_DEFAULT_EPISODE_RETENTION = timedelta(days=30)

#: How long a tombstone outlives the deletion that stamped it (ADR-0074 §8).
#: Positive and finite, with no ``None`` spelling: an unbounded grace keeps every
#: deleted conversation's index forever, and a zero or negative one drops it
#: immediately, which is the orphaned late write the tombstone exists to catch.
_DEFAULT_TOMBSTONE_GRACE = timedelta(hours=1)

#: How many times :meth:`FakeConversationStore.start` re-mints before giving up.
_START_RETRY_BUDGET = 8

#: The reserved namespace a captured turn's episode id is minted into (ADR-0074
#: §3). Structurally recognisable, and no other producer may mint into it.
_EPISODE_NAMESPACE = "conv"


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

    def __init__(  # noqa: PLR0913 — one keyword per injected seam the contract names
        self,
        *,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _random_id,
        retention: timedelta | None = _DEFAULT_EPISODE_RETENTION,
        tombstone_grace: timedelta = _DEFAULT_TOMBSTONE_GRACE,
        tail_limit: int = _DEFAULT_TAIL_LIMIT,
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
            tombstone_grace: How long a stamped conversation's index survives the
                stamp (ADR-0074 §8).
            tail_limit: The configured replay window :meth:`turns` uses by default.
            purge_batch: The batch size :meth:`episodes_to_purge` uses by default.

        Raises:
            ValueError: If ``tombstone_grace`` is not strictly positive, if
                ``retention`` is set and not strictly positive, or if either
                default page size is outside ``[0, 2**63)``. Both durations are
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
        _check_page_bound("tail_limit", tail_limit)
        _check_page_bound("purge_batch", purge_batch)
        self._clock = checked_clock(now, owner="FakeConversationStore")
        self._new_id = new_id
        self._retention = retention
        self._grace = tombstone_grace
        self._tail_limit = tail_limit
        self._purge_batch = purge_batch
        self._conversations: dict[str, Conversation] = {}
        self._turns: dict[str, list[ConversationTurn]] = {}
        self._by_episode: dict[str, ConversationTurn] = {}
        self._by_binding: dict[ParkedBinding, ConversationTurn] = {}
        #: One entry per conversation currently being mutated, and only those:
        #: :meth:`_exclusive` discards an entry once nobody holds it (#453).
        self._locks: dict[str, _Exclusion] = {}
        self._start_lock = asyncio.Lock()
        self._resource = SuspendableResource()

    def suspend_next_write(self) -> LoopSuspension:
        """Hold the next mutation open *inside* the resource it acquired (ADR-0060 §3).

        The hook ``ConversationStoreContract``'s cancellation case takes. Test-only,
        and deliberately not on the ``ConversationStore`` seam: the Protocol grows no
        affordance for this, so the suite asks the *subject* it was handed rather
        than the contract every consumer depends on.

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
        queue. Remove the lock and the shared suite's ordinal, serialisation and
        reclaim-race cases fail here rather than passing vacuously.

        **The lock is taken before the body checks whether the id names anything**,
        and that ordering is the reason a lock cannot simply be created on demand
        and dropped on the way out: it is what stops a concurrent ``stamp_deleted``
        and ``append`` both observing the conversation as live. So the entry is
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

    def _known(self, conversation_id: str) -> Conversation:
        """Return a conversation whether or not it is stamped, or raise.

        What the sweeps need: :meth:`episodes_to_purge` reads a stamped
        conversation's index precisely *because* it is stamped (ADR-0074 §8).

        Raises:
            UnknownConversationError: If the id names nothing.
        """
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            msg = f"no such conversation: {describe_untrusted(conversation_id)}"
            raise UnknownConversationError(msg)
        return conversation

    def _episode_id(self, conversation_id: str, ordinal: int) -> str:
        """Derive a turn's episode id from the two values the store proved unique.

        Reserved to captured conversation turns (ADR-0074 §3): no other producer
        mints into this namespace, so a collision inside it is a broken invariant
        rather than bad luck.
        """
        return f"{_EPISODE_NAMESPACE}:{conversation_id}:{ordinal}"

    def _visible_turn(self, turn: ConversationTurn | None) -> ConversationTurn | None:
        """Hide a turn whose conversation is stamped (ADR-0074 §9).

        The reverse lookups are otherwise a way around the front door: a caller
        holding an episode id or a binding from before the deletion would receive
        exactly the metadata every presenting read withholds.
        """
        if turn is None:
            return None
        conversation = self._conversations.get(turn.conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            return None
        return turn

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
                self._turns[conversation.id] = []
                return conversation
        msg = (
            f"could not mint an unused conversation id in {_START_RETRY_BUDGET} attempts; "
            f"the injected id factory is repeating"
        )
        raise ConversationStoreError(msg)

    async def get(self, conversation_id: str) -> Conversation | None:
        """Return the conversation, or ``None`` if it is absent or stamped."""
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

    async def append(
        self,
        conversation_id: str,
        *,
        occurred_at: datetime,
        parked: ParkedBinding | None = None,
    ) -> ConversationTurn:
        """Allocate the ordinal, derive the episode id, and record the turn.

        The duplicate-binding check runs *before* anything is allocated, so a
        refusal consumes no ordinal and leaves no row behind (ADR-0074 §9.1).

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If ``parked`` duplicates a binding already
                claimed.
            ValueError: If ``occurred_at`` is not a timezone-aware instant.
        """
        async with self._exclusive(conversation_id):
            conversation = self._live(conversation_id)
            if parked is not None and parked in self._by_binding:
                msg = (
                    f"a turn already parked on execution {parked.execution_id!r} "
                    f"step {parked.step_id!r}"
                )
                raise ConversationStoreError(msg)
            existing = self._turns[conversation_id]
            ordinal = existing[-1].ordinal + 1 if existing else FIRST_TURN_ORDINAL
            turn = ConversationTurn(
                conversation_id=conversation_id,
                ordinal=ordinal,
                episode_id=self._episode_id(conversation_id, ordinal),
                occurred_at=occurred_at,
                parked=parked,
            )
            existing.append(turn)
            self._by_episode[turn.episode_id] = turn
            if parked is not None:
                self._by_binding[parked] = turn
            self._conversations[conversation_id] = conversation.model_copy(
                update={"last_turn_at": turn.occurred_at}
            )
            return turn

    async def turns(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        before_ordinal: int | None = None,
    ) -> list[ConversationTurn]:
        """Return a page of turns, ordinal ascending, ending below ``before_ordinal``.

        Raises:
            ValueError: If ``limit`` or ``before_ordinal`` is out of range.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        page = self._tail_limit if limit is None else limit
        _check_page_bound("limit", page)
        if before_ordinal is not None:
            _check_page_bound("before_ordinal", before_ordinal, floor=FIRST_TURN_ORDINAL)
        self._live(conversation_id)
        rows = self._turns[conversation_id]
        if before_ordinal is not None:
            rows = [turn for turn in rows if turn.ordinal < before_ordinal]
        return list(rows[-page:]) if page else []

    async def episodes_to_purge(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of this conversation's episode ids, in ordinal order.

        Reads nothing but ids, and removes nothing: the rows are the intent log
        and they go only when :meth:`drop_if_eligible` succeeds (ADR-0074 §9).

        Raises:
            ValueError: If ``limit`` is out of range, or ``after_id`` is not an
                episode id of this conversation.
            UnknownConversationError: If the id names nothing.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        self._known(conversation_id)
        rows = self._turns[conversation_id]
        start = 0
        if after_id is not None:
            positions = [index for index, turn in enumerate(rows) if turn.episode_id == after_id]
            if not positions:
                msg = (
                    f"after_id {describe_untrusted(after_id)} is not an episode id of this "
                    f"conversation"
                )
                raise ValueError(msg)
            start = positions[0] + 1
        return [turn.episode_id for turn in rows[start : start + batch]]

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
        live = [one for one in self._conversations.values() if one.deleted_at is None]
        return _by_last_activity(live)[offset : offset + limit]

    async def turn_of_episode(self, episode_id: str) -> ConversationTurn | None:
        """Return the turn an episode records, or ``None`` if absent or stamped."""
        return self._visible_turn(self._by_episode.get(episode_id))

    async def turn_of_binding(self, binding: ParkedBinding) -> ConversationTurn | None:
        """Return the turn that parked on ``binding``, or ``None`` if absent or stamped."""
        return self._visible_turn(self._by_binding.get(binding))

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
        """Remove the record and its index if it is still eligible, under the exclusion.

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
            for turn in self._turns.pop(conversation_id, []):
                self._by_episode.pop(turn.episode_id, None)
                if turn.parked is not None:
                    self._by_binding.pop(turn.parked, None)
            del self._conversations[conversation_id]
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: unstamped conversations and their turns.

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether
        an episode still resolves, and the user-facing export is composed in
        `orchestration` (ADR-0074 §9).
        """
        live = _by_last_activity(
            [one for one in self._conversations.values() if one.deleted_at is None]
        )
        turns = [
            turn
            for conversation_id in sorted(one.id for one in live)
            for turn in self._turns[conversation_id]
        ]
        return ConversationExport(
            exported_at=self._now(),
            conversations=tuple(live),
            turns=tuple(turns),
        )
