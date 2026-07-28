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
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ConversationStoreError
from ai_assistant.core.types import FIRST_TURN_ORDINAL, ParkedBinding

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.core.types import ConversationTurn

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
