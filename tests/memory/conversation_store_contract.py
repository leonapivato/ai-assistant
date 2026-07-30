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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import FIRST_TURN_ORDINAL, ParkedBinding
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import ConversationTurn
    from ai_assistant.testing.cancellation import SuspendedMidWrite

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

#: The reserved namespace every implementation mints a captured turn's episode id
#: into (ADR-0074 §3). Asserted rather than assumed, because the reservation is
#: only enforceable if it is observable.
_EPISODE_PREFIX = "conv:"

#: What a failure of the exclusion cases means, in one place (ADR-0074 §8): two
#: mutations of one conversation interleaved, so one of them acted on state the
#: other had already replaced.
_INTERLEAVED = (
    "two mutations of one conversation interleaved: the store's per-conversation "
    "exclusion is not holding, so an append, an activity mark, a deletion stamp "
    "and a reclaim can each act on state another has already replaced"
)

#: What a failure of the cancellation case below means (ADR-0060 §3).
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

    def __call__(  # noqa: PLR0913 — one keyword per injected seam
        self,
        *,
        now: Callable[[], datetime],
        new_id: Callable[[], str],
        retention: timedelta | None,
        tombstone_grace: timedelta,
        tail_limit: int,
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
    tail_limit: int = 5,
    purge_batch: int = 100,
) -> ConversationStore:
    """Build a subject, filling in whatever the case does not care about."""
    return factory(
        now=now or MovableClock(),
        new_id=new_id or ScriptedIds([]),
        retention=retention,
        tombstone_grace=tombstone_grace,
        tail_limit=tail_limit,
        purge_batch=purge_batch,
    )


async def _seed(
    store: ConversationStore, count: int, *, at: datetime = _NOW
) -> tuple[str, list[ConversationTurn]]:
    """Start a conversation and append ``count`` turns to it."""
    conversation = await store.start()
    turns = [
        await store.append(conversation.id, occurred_at=at + index * _MINUTE)
        for index in range(count)
    ]
    return conversation.id, turns


async def _walk_turns(store: ConversationStore, conversation_id: str, *, page: int) -> list[int]:
    """Walk every turn backwards through ``before_ordinal``, oldest first."""
    seen: list[int] = []
    cursor: int | None = None
    while True:
        batch = await store.turns(conversation_id, limit=page, before_ordinal=cursor)
        if not batch:
            return sorted(seen)
        assert [turn.ordinal for turn in batch] == sorted(turn.ordinal for turn in batch), (
            "a page of turns must be ordinal ascending"
        )
        seen.extend(turn.ordinal for turn in batch)
        cursor = batch[0].ordinal


async def _walk_episodes(store: ConversationStore, conversation_id: str, *, page: int) -> list[str]:
    """Walk every episode id forwards through ``after_id``, in ordinal order."""
    seen: list[str] = []
    cursor: str | None = None
    while True:
        batch = await store.episodes_to_purge(conversation_id, limit=page, after_id=cursor)
        if not batch:
            return seen
        seen.extend(batch)
        cursor = batch[-1]


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
    """One locked ``ConversationStore`` mutation ADR-0060's case drives.

    Every ``async with self._lock`` site is a separate place the resource could be
    handed over early (#370), so the same cancelled-first / concurrent-second
    scenario runs against each rather than only against ``append``. :meth:`first`
    and :meth:`second` act on two *independent* subjects, because the clause's
    third paragraph makes the cancelled call's effect indeterminate to the caller
    — under ADR-0054's shield a cancelled write that reached its commit is durably
    written — so only the second's outcome is assertable.
    """

    name: str

    async def prepare(self, store: ConversationStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends mid-write and then cancels."""
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


class _AppendOp(_PairedOp):
    """``append`` — the ordinal allocation and the derived id, in one transaction."""

    name = "append"

    def first(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Record a turn on the left conversation — the call that is cancelled."""
        return store.append(self.left, occurred_at=_NOW)

    def second(self, store: ConversationStore) -> Coroutine[Any, Any, object]:
        """Record a turn on the right one concurrently."""
        return store.append(self.right, occurred_at=_NOW)

    async def verify(self, store: ConversationStore) -> None:
        """The concurrent turn is whole and enumerable; the cancelled one is all-or-nothing.

        Checked through the purge walk as well as through :meth:`turns`, because a
        half-written turn that the reader shows and the sweep cannot find is the
        shape that would leave an episode undestroyable (ADR-0074 §8).
        """
        recorded = await store.turns(self.right)
        assert [turn.ordinal for turn in recorded] == [FIRST_TURN_ORDINAL]
        assert recorded[0].episode_id.startswith(_EPISODE_PREFIX)
        assert await store.episodes_to_purge(self.right) == [recorded[0].episode_id]
        cancelled = await store.turns(self.left)
        assert [turn.ordinal for turn in cancelled] in ([], [FIRST_TURN_ORDINAL])
        assert [turn.episode_id for turn in cancelled] == await store.episodes_to_purge(self.left)


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


#: Every locked ``ConversationStore`` *mutation* ADR-0060's case is run against:
#: each is a distinct ``async with self._lock`` site (#370). The locked *read*
#: paths are the same invariant on a different axis and are tracked separately,
#: as ``MemoryStore``'s are under #397.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _StartOp,
    _MarkActiveOp,
    _AppendOp,
    _StampDeletedOp,
    _DropIfEligibleOp,
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
    def tail_default(self) -> int:
        """The replay window the ``store`` fixture's implementation defaults to."""
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
        await store.append(first.id, occurred_at=_NOW)

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
        await store.append(first.id, occurred_at=_NOW)

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
            store.append("nobody", occurred_at=_NOW),
            store.turns("nobody"),
            store.episodes_to_purge("nobody"),
        ):
            with pytest.raises(ConversationStoreError):
                await call

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

    async def test_append_records_the_turn_stamp_from_the_turn_and_not_the_clock(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§2: ``last_turn_at`` is recorded-time — the instant the caller passed."""
        clock = MovableClock()
        store = _build(factory, now=clock)
        started = await store.start()
        clock.advance(_HOUR)
        occurred = _NOW + 3 * _MINUTE

        turn = await store.append(started.id, occurred_at=occurred)

        after = await store.get(started.id)
        assert after is not None
        assert after.last_turn_at == occurred == turn.occurred_at
        assert after.last_active_at == started.last_active_at, "an append is not an activity mark"

    # --- the ordinal invariant and the derived id ---------------------------

    async def test_ordinals_are_dense_unique_and_monotonic(self, store: ConversationStore) -> None:
        """§9.2: the numbering is the store's invariant, not a caller's convention."""
        conversation_id, turns = await _seed(store, 12)

        ordinals = [turn.ordinal for turn in turns]
        assert ordinals == list(range(FIRST_TURN_ORDINAL, FIRST_TURN_ORDINAL + 12))
        assert all(turn.conversation_id == conversation_id for turn in turns)

    async def test_each_turn_derives_a_distinct_reserved_episode_id(
        self, store: ConversationStore
    ) -> None:
        """§3: the id is derived from conversation and ordinal, in a reserved space."""
        _, turns = await _seed(store, 5)

        episode_ids = [turn.episode_id for turn in turns]
        assert len(set(episode_ids)) == len(episode_ids), "two turns cannot share an episode id"
        assert all(one.startswith(_EPISODE_PREFIX) for one in episode_ids), (
            "a captured turn's episode id must be recognisable as one, so the "
            "namespace reservation is observable rather than merely asserted"
        )

    async def test_concurrent_appends_take_distinct_ordinals(
        self, store: ConversationStore
    ) -> None:
        """§8, §9.4: appends to one conversation serialise at the store."""
        conversation = await store.start()

        turns = await asyncio.gather(
            *(store.append(conversation.id, occurred_at=_NOW) for _ in range(8))
        )

        ordinals = sorted(turn.ordinal for turn in turns)
        assert ordinals == list(range(FIRST_TURN_ORDINAL, FIRST_TURN_ORDINAL + 8)), _INTERLEAVED
        assert len({turn.episode_id for turn in turns}) == 8, _INTERLEAVED

    async def test_a_duplicate_parked_binding_is_refused_atomically(
        self, store: ConversationStore
    ) -> None:
        """§9.1: no ordinal consumed, no row left behind, the original still resolves."""
        conversation = await store.start()
        binding = ParkedBinding(execution_id="exec-1", step_id="step-1")
        parked = await store.append(conversation.id, occurred_at=_NOW, parked=binding)

        with pytest.raises(ConversationStoreError):
            await store.append(conversation.id, occurred_at=_NOW, parked=binding)

        following = await store.append(conversation.id, occurred_at=_NOW)
        assert following.ordinal == parked.ordinal + 1, "the refusal consumed no ordinal"
        assert await store.turn_of_binding(binding) == parked
        assert [turn.ordinal for turn in await store.turns(conversation.id)] == [
            parked.ordinal,
            following.ordinal,
        ], "the refused append left no row behind"

    async def test_turns_that_parked_nothing_are_unconstrained(
        self, store: ConversationStore
    ) -> None:
        """§9.1: the uniqueness rule binds bindings, not the turns that have none."""
        _, turns = await _seed(store, 3)

        assert all(turn.parked is None for turn in turns)

    # --- the reverse lookups -------------------------------------------------

    async def test_the_reverse_lookups_resolve_a_recorded_turn(
        self, store: ConversationStore
    ) -> None:
        """§9: the store owes both directions of the membership relation."""
        conversation = await store.start()
        binding = ParkedBinding(execution_id="exec-2", step_id="step-2")
        turn = await store.append(conversation.id, occurred_at=_NOW, parked=binding)

        assert await store.turn_of_episode(turn.episode_id) == turn
        assert await store.turn_of_binding(binding) == turn

    async def test_an_unresolvable_episode_or_binding_is_skipped_not_raised(
        self, store: ConversationStore
    ) -> None:
        """§5: a turn that does not resolve is a gap, never an error."""
        await store.start()

        assert await store.turn_of_episode("conv:nobody:1") is None
        assert await store.turn_of_binding(ParkedBinding(execution_id="x", step_id="y")) is None

    # --- bounded, ordered reads ---------------------------------------------

    async def test_turns_returns_the_tail_in_ordinal_order(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9.3: the most recent turns, oldest first within the page."""
        store = _build(factory, tail_limit=3)
        conversation_id, turns = await _seed(store, 6)

        page = await store.turns(conversation_id)

        assert [turn.ordinal for turn in page] == [4, 5, 6]
        assert page == turns[3:]

    async def test_turns_uses_the_configured_replay_window_by_default(
        self, store: ConversationStore, tail_default: int
    ) -> None:
        """§9.3: the default is finite and the same for every caller that says nothing."""
        conversation_id, _ = await _seed(store, tail_default + 3)

        page = await store.turns(conversation_id)

        assert len(page) == tail_default
        assert [turn.ordinal for turn in page] == list(range(4, tail_default + 4))

    async def test_turns_walks_the_whole_conversation_to_an_empty_page(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9: both traversals are complete, terminate, and visit each turn once."""
        store = _build(factory, tail_limit=2)
        conversation_id, _ = await _seed(store, 7)

        assert await _walk_turns(store, conversation_id, page=2) == list(range(1, 8))

    async def test_a_zero_page_is_an_empty_page(self, store: ConversationStore) -> None:
        """Asking for nothing is a question with an answer, not an unbounded read."""
        conversation_id, _ = await _seed(store, 2)

        assert await store.turns(conversation_id, limit=0) == []
        assert await store.episodes_to_purge(conversation_id, limit=0) == []
        assert await store.recent(limit=0) == []

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
        await store.append(older.id, occurred_at=_NOW)
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
        conversation_id, _ = await _seed(store, 1)

        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(offset=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.turns(conversation_id, limit=bad)
        with pytest.raises(ValueError, match="must be an int"):
            await store.episodes_to_purge(conversation_id, limit=bad)

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
        conversation_id, _ = await _seed(store, 1)
        limit = cast("int", bad)

        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=limit)
        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(offset=limit)
        with pytest.raises(ValueError, match="must be an int"):
            await store.turns(conversation_id, limit=limit)
        with pytest.raises(ValueError, match="must be an int"):
            await store.episodes_to_purge(conversation_id, limit=limit)

    async def test_only_the_two_reads_that_document_it_accept_a_none_limit(
        self, store: ConversationStore
    ) -> None:
        """``None`` is a spelling, not a hole — and only where the contract gives it one.

        On :meth:`turns` and :meth:`episodes_to_purge` it asks for the store's
        configured default; :meth:`recent` has a named default of 50 and no
        ``None`` spelling, so passing one there is the same malformed argument as
        any other non-integer.
        """
        conversation_id, turns = await _seed(store, 2)

        assert await store.turns(conversation_id, limit=None) == turns
        assert await store.episodes_to_purge(conversation_id, limit=None) == [
            turn.episode_id for turn in turns
        ]
        with pytest.raises(ValueError, match="must be an int"):
            await store.recent(limit=cast("int", None))

    async def test_an_ordinal_cursor_below_the_first_turn_is_refused(
        self, store: ConversationStore
    ) -> None:
        """``before_ordinal`` names a position, and 0 names none."""
        conversation_id, _ = await _seed(store, 1)

        with pytest.raises(ValueError, match="must be an int"):
            await store.turns(conversation_id, before_ordinal=0)

    # --- the purge walk ------------------------------------------------------

    async def test_episodes_to_purge_walks_forwards_over_every_batch(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9: a conversation longer than one batch is fully reachable.

        A fixture with one batch of turns passes a single-batch implementation and
        proves nothing — which is why the walk here spans several and is compared
        against the whole index.
        """
        store = _build(factory, purge_batch=2)
        conversation_id, turns = await _seed(store, 7)

        walked = await _walk_episodes(store, conversation_id, page=2)

        assert walked == [turn.episode_id for turn in turns], (
            "the walk must visit every turn exactly once, in ordinal order"
        )

    async def test_episodes_to_purge_uses_the_configured_batch_by_default(
        self, store: ConversationStore, purge_default: int
    ) -> None:
        """§9.3: bounded by default, with a figure every caller shares."""
        conversation_id, _ = await _seed(store, purge_default + 2)

        assert len(await store.episodes_to_purge(conversation_id)) == purge_default

    async def test_the_purge_walk_removes_nothing(self, store: ConversationStore) -> None:
        """§9: the rows are the intent log, so reading them is never consuming them."""
        conversation_id, turns = await _seed(store, 3)

        first = await store.episodes_to_purge(conversation_id)
        again = await store.episodes_to_purge(conversation_id)

        assert first == again == [turn.episode_id for turn in turns]

    async def test_a_purge_cursor_the_store_cannot_place_is_refused(
        self, store: ConversationStore
    ) -> None:
        """A silently-restarted walk is a sweep that loops forever over batch one."""
        conversation_id, _ = await _seed(store, 2)
        other_id, other_turns = await _seed(store, 1)

        with pytest.raises(ValueError, match="not an episode id"):
            await store.episodes_to_purge(conversation_id, after_id="conv:nobody:1")
        with pytest.raises(ValueError, match="not an episode id"):
            await store.episodes_to_purge(conversation_id, after_id=other_turns[0].episode_id)
        assert other_id != conversation_id

    # --- the tombstone -------------------------------------------------------

    async def test_a_stamped_conversation_is_hidden_from_every_presenting_read(
        self, store: ConversationStore
    ) -> None:
        """§9: the pair that keeps a tombstone from being a readable record."""
        conversation_id, turns = await _seed(store, 2)
        binding = ParkedBinding(execution_id="exec-3", step_id="step-3")
        parked = await store.append(conversation_id, occurred_at=_NOW, parked=binding)

        assert await store.stamp_deleted(conversation_id) is True

        assert await store.get(conversation_id) is None
        assert await store.recent() == []
        assert (await store.export()).conversations == ()
        assert (await store.export()).turns == ()
        assert await store.turn_of_episode(turns[0].episode_id) is None
        assert await store.turn_of_binding(binding) is None
        with pytest.raises(ConversationStoreError):
            await store.turns(conversation_id)

        assert await store.episodes_to_purge(conversation_id) == [
            *(turn.episode_id for turn in turns),
            parked.episode_id,
        ], "the sweep must still be handed the ids it has to destroy"

    async def test_appending_to_a_stamped_conversation_is_refused(
        self, store: ConversationStore
    ) -> None:
        """§8: the stamp is what stops a racing capture slipping a turn in behind it."""
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)

        with pytest.raises(ConversationStoreError):
            await store.append(conversation_id, occurred_at=_NOW)
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
        conversation_id, turns = await _seed(store, 2)
        await store.stamp_deleted(conversation_id)

        assert await store.drop_if_eligible(conversation_id) is False, "still inside the grace"
        assert await store.episodes_to_purge(conversation_id) == [
            turn.episode_id for turn in turns
        ], "the index still names every episode the sweep must destroy"

        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True

    async def test_a_reclaim_is_idempotent_and_a_late_capture_is_refused(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§8: the residue this ADR accepts, pinned rather than rediscovered.

        Once the tombstone has been reclaimed, a capture that lands *after* it has
        nowhere to record itself: the append is refused, so the turn is not
        recorded, and an episode whose write commits at that point is an orphan
        no sweep can find. That is the accepted window, not a bug — and the
        reclaim itself can run any number of times.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        conversation_id, _ = await _seed(store, 1)
        await store.stamp_deleted(conversation_id)
        clock.advance(_GRACE)

        assert await store.drop_if_eligible(conversation_id) is True
        assert await store.drop_if_eligible(conversation_id) is False, "a re-run is a no-op"

        with pytest.raises(ConversationStoreError):
            await store.append(conversation_id, occurred_at=clock())
        with pytest.raises(ConversationStoreError):
            await store.episodes_to_purge(conversation_id)

    async def test_a_capture_and_a_deletion_issued_together_serialise(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§8: the exclusion is the store's obligation, not a caller's lock.

        The store-level half of the clause. Whichever lands first, the outcome is
        one of exactly two consistent states — never a turn recorded *into* a
        stamped conversation, and never a stamp that lost a turn it should have
        named.
        """
        store = _build(factory)
        conversation_id, _ = await _seed(store, 1)

        appended, stamped = await asyncio.gather(
            store.append(conversation_id, occurred_at=_NOW),
            store.stamp_deleted(conversation_id),
            return_exceptions=True,
        )

        assert stamped is True, "the deletion is unconditional and must have happened"
        named = await store.episodes_to_purge(conversation_id)
        if isinstance(appended, BaseException):
            assert isinstance(appended, ConversationStoreError), appended
            assert len(named) == 1, _INTERLEAVED
        else:
            assert appended.episode_id in named, (
                f"{_INTERLEAVED}: the append succeeded, so the index the sweep reads "
                f"must name its episode"
            )

    # --- enumerating the tombstones (ADR-0076) -------------------------------

    async def test_a_stamped_conversation_is_enumerable_and_an_unstamped_one_is_not(
        self, store: ConversationStore
    ) -> None:
        """ADR-0076 §4.1: the pair, so returning everything passes neither half.

        This is the read the whole ADR exists for. Without it a process that died
        between §8's stamp and its drop left a tombstone no later run could
        rediscover, so the episodes its index named were never destroyed.
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
        the tombstone, still read the episode ids it names, and finish the deletion
        once the grace has elapsed.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, tombstone_grace=_GRACE)
        conversation_id, turns = await _seed(store, 3)
        await store.stamp_deleted(conversation_id)

        assert await store.stamped_conversation_ids() == [conversation_id]
        assert await store.episodes_to_purge(conversation_id) == [
            turn.episode_id for turn in turns
        ], "the tombstone still names every episode the sweep must destroy"

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
        five reads that still say nothing.
        """
        conversation_id, turns = await _seed(store, 1)
        binding = ParkedBinding(execution_id="exec-9", step_id="step-9")
        await store.append(conversation_id, occurred_at=_NOW, parked=binding)
        await store.stamp_deleted(conversation_id)

        assert await store.stamped_conversation_ids() == [conversation_id]

        assert await store.get(conversation_id) is None
        assert await store.recent() == []
        assert (await store.export()).conversations == ()
        assert (await store.export()).turns == ()
        assert await store.turn_of_episode(turns[0].episode_id) is None
        assert await store.turn_of_binding(binding) is None
        with pytest.raises(ConversationStoreError):
            await store.turns(conversation_id)

    async def test_an_unknown_id_raises_the_narrow_subclass(self, store: ConversationStore) -> None:
        """ADR-0076 §4.10, first half: every method that refuses an unknown id.

        The sweep's whole use for the subclass is telling *someone else already
        finished this one* from *stop*, so an implementation that raised the base
        class here would leave a start-up sweep unable to carry on past a
        conversation another sweeper had just dropped.
        """
        for call in (
            store.mark_active("nobody"),
            store.append("nobody", occurred_at=_NOW),
            store.turns("nobody"),
            store.episodes_to_purge("nobody"),
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

        Zero would drop the index immediately, which is the orphaned late write the
        tombstone exists to catch; unbounded would keep every deleted
        conversation's index forever.
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

    async def test_a_reclaim_walk_reaches_every_batch_before_the_drop(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§7: reclaim's precondition is that *no* turn resolves, over every batch.

        An implementation that served only the first batch would let a coordinator
        drop the index while live episodes sat behind it. The multi-batch walk is
        what makes that visible, and it must work on an **unstamped** conversation:
        retention reclaim never stamps anything.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_RETENTION, purge_batch=2)
        conversation_id, turns = await _seed(store, 5)
        clock.advance(_RETENTION)

        walked = await _walk_episodes(store, conversation_id, page=2)

        assert walked == [turn.episode_id for turn in turns]
        assert await store.drop_if_eligible(conversation_id) is True
        with pytest.raises(ConversationStoreError):
            await store.episodes_to_purge(conversation_id)

    # --- export --------------------------------------------------------------

    async def test_export_carries_the_conversations_and_their_turns_in_order(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9: the store's own snapshot, ordered as its reads are."""
        clock = MovableClock()
        store = _build(factory, now=clock, new_id=ScriptedIds(["first", "second"]))
        first = await store.start()
        await store.append(first.id, occurred_at=_NOW)
        await store.append(first.id, occurred_at=_NOW + _MINUTE)
        clock.advance(_HOUR)
        second = await store.start()

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [second.id, first.id]
        assert [(turn.conversation_id, turn.ordinal) for turn in exported.turns] == [
            (first.id, 1),
            (first.id, 2),
        ]
        assert exported.schema_version == 1

    async def test_export_omits_a_stamped_conversation_and_its_turns(
        self, factory: ConversationStoreFactory
    ) -> None:
        """§9: a stamped conversation is deleted as far as every read is concerned."""
        store = _build(factory, new_id=ScriptedIds(["kept", "stamped"]))
        kept, _ = await _seed(store, 1)
        stamped, _ = await _seed(store, 1)
        await store.stamp_deleted(stamped)

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [kept]
        assert all(turn.conversation_id == kept for turn in exported.turns)

    async def test_export_carries_an_empty_conversation(self, store: ConversationStore) -> None:
        """A conversation with no turns is state the user holds; it exports as itself."""
        conversation = await store.start()

        exported = await store.export()

        assert [one.id for one in exported.conversations] == [conversation.id]
        assert exported.turns == ()

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
        turn = await store.append(conversation.id, occurred_at=_NOW)

        clock.advance(_HOUR)
        await store.mark_active(conversation.id)

        assert conversation.last_active_at == _NOW, "the caller's snapshot did not move"
        with pytest.raises(ValidationError):
            conversation.last_active_at = _NOW + _DAY
        with pytest.raises(ValidationError):
            turn.ordinal = 99

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
        """Supply a store whose named locked mutation can be stopped *inside* its resource.

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
        reappear (#370), so ``arm`` is where the implementation says how it stops a
        given one: a worker thread parked mid-SQL, a fake's modelled resource.

        The ``ResourceLog`` is not redundant with the blocked-caller assertion. That
        one is decisive only where queueing is loop-bound; a store whose work runs
        on an executor can leave a second call pending for reasons that have nothing
        to do with the resource, and the log settles it directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_mutation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked mutation (ADR-0074 §9.5).

        A cancelled mutation must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a test
        of the invariant rather than of propagation: a single cancelled call in
        isolation looks identical either way (ADR-0060 §3).

        The first call's *effect* is deliberately not asserted (the op's ``verify``
        pins only what a caller may rely on): the clause's third paragraph makes it
        indeterminate, since under ADR-0054's shield a cancelled write that reached
        its commit is durably written. What is pinned is that the second call is
        whole and the store still serves reads.
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
