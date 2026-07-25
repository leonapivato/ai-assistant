"""Shared conformance suite for the MemoryStore Protocol.

Every ``MemoryStore`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryStoreContract` and overrides the ``store`` fixture; the suite
asserts only behaviour *universal* to the contract — not the retrieval rules of
any one implementation (lexical vs. semantic), which stay in the per-implementation
test modules.

Expiry cases use a deadline far in the past, so they hold under any store clock
(wall-clock or injected) without the suite having to dictate one.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import ResourceLog, SuspendedCall

    StoreFactory = Callable[[Callable[[], datetime]], MemoryStore]
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)

# Far in the past: expired (or window-closed) under any clock at or after 2000 —
# every real wall-clock and the fixed test clocks the subclasses inject.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
# Far in the future: a ``valid_from`` here is not yet open under any such clock.
_FAR_FUTURE = datetime(2999, 1, 1, tzinfo=UTC)
# The instant every shipped store fixture's injected clock returns; the ``now``
# fixture below exposes it so window *boundary* cases can be built relative to it.
_STORE_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)

#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


def _provenance() -> Provenance:
    return Provenance(
        source=MemorySource.OBSERVED,
        confidence=0.6,
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _semantic(
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(),
        expires_at=expires_at,
        validity=validity or Validity(),
    )


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


#: What a failure of either input-observation case below means, in one place
#: (ADR-0065): the call read the caller's argument more than once and the reads
#: disagreed, so one result now describes two versions of one input.
_TORN_INPUT = (
    "the write derived its outcome from more than one observation of its input: a "
    "caller's mid-flight mutation reached part of what was committed and not the "
    "rest, so no single version of the argument describes the result"
)


@contextlib.asynccontextmanager
async def _held_at_its_first_await(
    gate: SuspendedCall | None, call: Coroutine[Any, Any, Any]
) -> AsyncIterator[asyncio.Task[Any]]:
    """Run ``call`` and hold it at its first ``await`` for the body of the block.

    The body is where the caller mutates what it passed; leaving the block lets
    the call finish. The task is yielded rather than its result: the mutation has
    to happen *while* the call is in flight, so the case awaits it afterwards.

    ``gate`` of ``None`` is ADR-0065 §3's reduction for an implementation that
    declares no suspension window: the call is run to completion first, so the
    body's mutation is a post-call one. That is the right weakening and not a
    hole — a store that performs no ``await`` between reading its input and
    committing it has no window for a mutation to land in, so the only thing left
    to assert is the isolation the suite has asserted since ADR-0045.
    """
    task = asyncio.ensure_future(call)
    try:
        if gate is None:
            await asyncio.wait([task])
        else:
            await gate.reached()
        yield task
    finally:
        if gate is not None:
            gate.release()


async def _score_for(store: MemoryStore, query: str, record_id: str) -> float:
    """How relevant ``store`` finds ``record_id`` to ``query``; ``0.0`` if unmatched."""
    for record in await store.search(query):
        if record.id == record_id:
            return record.score or 0.0
    return 0.0


async def _assert_indexed_from_the_content_it_carries(
    store: MemoryStore, record_id: str, *, rejected_content: str
) -> None:
    """Assert the stored record's retrieval entry was built from its own content.

    The half of ADR-0065's obligation the record itself cannot show. A torn write
    persists one version of the content and indexes another — the ADR-0056 tear
    (#286), where the row's JSON and the vector beside it described two different
    records — and asking whether the row comes *back* hides that completely: a
    vector store applies no similarity floor, so it returns its rows for any
    query at all.

    So this asks the only question the index answers: is the record more relevant
    to the content it carries than to ``rejected_content`` — the version of that
    content the store did **not** keep? A store that indexed what it persisted
    says yes. One that embedded the version it discarded says no, because the
    vector it is holding is the rejected text's.

    Deliberately **one record against two queries**, never two records against
    one. Comparing the subject with an identically-worded second record would
    assume the store scores equal strings equally — which a store weighting
    recency, or an embedder that is not bit-deterministic, may conformingly not
    do, and neither :meth:`~ai_assistant.core.protocols.MemoryStore.search` nor
    any ADR promises it. Holding the record fixed cancels every per-record signal
    of that kind and leaves only the thing under test. The one premise left is
    that a record is more relevant to its own words than to words it does not
    carry, which the suite already relies on in
    ``test_search_finds_a_matching_record``.
    """
    stored = await store.get(record_id)
    assert stored is not None
    assert stored.content != rejected_content, "the two versions must be distinguishable"
    carried = await _score_for(store, stored.content, record_id)
    rejected = await _score_for(store, rejected_content, record_id)
    assert carried >= rejected, (
        f"{record_id!r} carries {stored.content!r} but the store finds it more relevant "
        f"to {rejected_content!r} ({rejected} > {carried}) — it was indexed from the "
        f"version of the record it did not store. {_TORN_INPUT}"
    )


class MemoryStoreContract:
    """The behavioural contract every ``MemoryStore`` implementation must satisfy."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    @pytest.fixture
    def now(self) -> datetime:
        """The instant the store-under-test's injected clock returns.

        Every shipped ``MemoryStore`` subclass injects a clock fixed at
        :data:`_STORE_NOW`, so the validity-window boundary cases below (a
        ``valid_from``/``valid_until`` exactly *at* now) can be built relative to
        it. A subclass whose ``store`` fixture uses a different clock overrides
        this fixture to match.
        """
        return _STORE_NOW

    @pytest.fixture
    def store_factory(self) -> StoreFactory:
        """Override in a subclass to build a store under test with a given clock.

        Used by the read-consistency case that needs an *advancing* clock — one
        returning a later instant on each call — which the fixed ``store`` fixture
        cannot express.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, store: MemoryStore) -> None:
        assert isinstance(store, MemoryStore)

    async def test_add_returns_id_and_get_round_trips(self, store: MemoryStore) -> None:
        returned = await store.add(_preference("p1", "prefers concise replies"))

        assert returned == "p1"
        got = await store.get("p1")
        assert got is not None
        assert got.id == "p1"
        assert got.kind == "preference"  # the typed record survives the round trip

    async def test_get_missing_returns_none(self, store: MemoryStore) -> None:
        assert await store.get("nope") is None

    async def test_add_overwrites_same_id_with_full_replacement(self, store: MemoryStore) -> None:
        # Upsert is a full replacement, not a merge: re-adding an id with a
        # different kind must leave no trace of the previous record — not its
        # kind, nor its subtype fields. (Overwriting across kinds also proves the
        # backend rewrites every column, not just the payload.)
        await store.add(_semantic("1", "old semantic note"))
        replacement = _preference("1", "new preference note")
        await store.add(replacement)

        got = await store.get("1")
        assert got is not None
        assert got.kind == "preference"  # the old semantic kind is gone
        assert got == replacement  # the whole record equals the second input

    async def test_search_finds_a_matching_record(self, store: MemoryStore) -> None:
        await store.add(_semantic("c", "the user likes coffee"))

        results = await store.search("coffee")

        assert "c" in {r.id for r in results}

    async def test_search_filters_by_kind(self, store: MemoryStore) -> None:
        await store.add(_semantic("s", "coffee fact"))
        await store.add(_preference("p", "coffee preference"))

        results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

        assert [r.id for r in results] == ["p"]

    async def test_search_respects_limit(self, store: MemoryStore) -> None:
        for i in range(4):
            await store.add(_semantic(f"k{i}", "shared coffee keyword"))

        results = await store.search("coffee", limit=2)

        assert len(results) <= 2

    async def test_empty_query_matches_nothing(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "some content"))

        assert await store.search("   ") == []

    async def test_non_positive_limit_matches_nothing(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "coffee"))

        assert await store.search("coffee", limit=0) == []
        assert await store.search("coffee", limit=-1) == []

    async def test_delete_removes_and_reports_existence(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "a fact"))

        assert await store.delete("1") is True
        assert await store.get("1") is None
        assert await store.delete("1") is False  # already gone

    async def test_clear_removes_all_and_returns_count(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "one"))
        await store.add(_semantic("2", "two"))

        assert await store.clear() == 2
        assert await store.get("1") is None
        assert await store.clear() == 0  # empty now

    async def test_export_returns_live_records_only(self, store: MemoryStore) -> None:
        await store.add(_semantic("live", "still valid"))
        await store.add(_semantic("dead", "gone", expires_at=_LONG_AGO))

        exported = await store.export()

        assert [r.id for r in exported] == ["live"]

    async def test_expired_records_are_hidden_from_get_and_search(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "coffee", expires_at=_LONG_AGO))

        assert await store.get("1") is None
        assert "1" not in {r.id for r in await store.search("coffee")}

    async def test_purge_expired_removes_only_expired(self, store: MemoryStore) -> None:
        await store.add(_semantic("live", "keeps"))
        await store.add(_semantic("dead", "goes", expires_at=_LONG_AGO))

        assert await store.purge_expired() == 1
        assert await store.get("live") is not None
        assert await store.purge_expired() == 0  # nothing left

    # --- Validity window read obligations (ADR-0045 §6) -----------------------

    async def test_fully_open_window_is_live_everywhere(self, store: MemoryStore) -> None:
        # The default window (both ends None) preserves today's behaviour: the
        # record is returned by get, search, and export alike.
        await store.add(_semantic("open", "coffee", validity=Validity()))

        assert await store.get("open") is not None
        assert "open" in {r.id for r in await store.search("coffee")}
        assert "open" in {r.id for r in await store.export()}

    async def test_window_closed_record_is_hidden_from_reads_but_kept_by_export(
        self, store: MemoryStore
    ) -> None:
        # A retired belief (closed valid_until) leaves the read path but is
        # retained: export is a data-rights obligation and must still return it.
        await store.add(_semantic("closed", "coffee", validity=Validity(valid_until=_LONG_AGO)))

        assert await store.get("closed") is None
        assert "closed" not in {r.id for r in await store.search("coffee")}
        assert "closed" in {r.id for r in await store.export()}

    async def test_not_yet_valid_record_is_hidden_from_reads_but_kept_by_export(
        self, store: MemoryStore
    ) -> None:
        # The valid_from end is enforced too, not assumed away: a record that is
        # not yet live is off the read path, yet still retained for export.
        await store.add(_semantic("future", "coffee", validity=Validity(valid_from=_FAR_FUTURE)))

        assert await store.get("future") is None
        assert "future" not in {r.id for r in await store.search("coffee")}
        assert "future" in {r.id for r in await store.export()}

    async def test_expired_wins_over_a_closed_window_in_export(self, store: MemoryStore) -> None:
        # The two axes are orthogonal but retention wins: a record that is both
        # window-closed *and* expired is excluded from export, not kept as history.
        # export keeps closed-window records only while they are still retained.
        await store.add(
            _semantic(
                "gone",
                "coffee",
                expires_at=_LONG_AGO,
                validity=Validity(valid_until=_LONG_AGO),
            )
        )

        assert await store.get("gone") is None
        assert "gone" not in {r.id for r in await store.export()}  # retention beats history

    async def test_valid_until_boundary_is_half_open(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # [from, until): at valid_until the record is already retired; strictly
        # before it, it is still live. Both get and search agree.
        await store.add(_semantic("at_until", "coffee alpha", validity=Validity(valid_until=now)))
        await store.add(
            _semantic("before_until", "coffee beta", validity=Validity(valid_until=now + _ONE_HOUR))
        )

        assert await store.get("at_until") is None
        assert await store.get("before_until") is not None
        found = {r.id for r in await store.search("coffee")}
        assert "at_until" not in found
        assert "before_until" in found

    async def test_valid_from_boundary_is_half_open(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # [from, until), all three cases for the valid_from end: strictly before
        # now is already live, at now is live, strictly after now is not yet live.
        # Both get and search agree on each.
        await store.add(
            _semantic("before_from", "coffee beta", validity=Validity(valid_from=now - _ONE_HOUR))
        )
        await store.add(_semantic("at_from", "coffee gamma", validity=Validity(valid_from=now)))
        await store.add(
            _semantic("after_from", "coffee delta", validity=Validity(valid_from=now + _ONE_HOUR))
        )

        assert await store.get("before_from") is not None
        assert await store.get("at_from") is not None
        assert await store.get("after_from") is None
        found = {r.id for r in await store.search("coffee")}
        assert "before_from" in found
        assert "at_from" in found
        assert "after_from" not in found

    async def test_stored_records_are_isolated_from_caller_mutation(
        self, store: MemoryStore
    ) -> None:
        """Post-call **aliasing** isolation, and deliberately nothing more (ADR-0045 §4).

        Read the name narrowly: both mutations below happen *after* their call has
        returned, so what this pins is that the store copied rather than aliased
        the caller's object. It says nothing about a mutation made **while** a
        write is in flight, and the difference is not academic — the torn ``add``
        of #286 passed this case, on every backend, for the whole time the tear was
        live, because by the time it mutates there is nothing left to tear
        (ADR-0065 §"The suite already appears to cover this"). Kept because
        non-aliasing is a real property this is the only case for; the mid-flight
        window is
        :meth:`test_add_derives_everything_from_one_observation_of_its_record` and
        :meth:`test_write_atomic_derives_everything_from_one_observation_of_its_batch`.
        """
        # The window drives read filtering, so a caller must not be able to retire
        # or revive a stored record by mutating the nested Validity — neither the
        # object it passed to add, nor one a read handed back.
        original = _semantic("iso", "coffee", validity=Validity(valid_until=_FAR_FUTURE))
        await store.add(original)

        original.validity.valid_until = _LONG_AGO  # mutate the caller's own object
        assert await store.get("iso") is not None  # stored copy is still live

        got = await store.get("iso")
        assert got is not None
        got.validity.valid_until = _LONG_AGO  # mutate a returned object
        assert await store.get("iso") is not None  # stored copy is still live

    async def test_search_judges_every_record_against_one_clock_reading(
        self, store_factory: StoreFactory
    ) -> None:
        # A single search must use one "now" for all candidates, not re-read an
        # advancing clock per record — otherwise a boundary record's fate depends
        # on iteration order, and implementations of the Protocol diverge.
        step = timedelta(hours=1)
        state = {"now": _STORE_NOW}

        def advancing() -> datetime:
            reading = state["now"]
            state["now"] = reading + step
            return reading

        store = store_factory(advancing)
        # All fall due after the first reading but before later ones, so a
        # per-record advancing clock would retire the later-iterated ones.
        deadline = _STORE_NOW + step // 2
        for i in range(3):
            await store.add(_semantic(f"c{i}", "coffee", validity=Validity(valid_until=deadline)))

        results = await store.search("coffee")

        assert {r.id for r in results} == {"c0", "c1", "c2"}

    # --- Atomic multi-write obligations (ADR-0046) ----------------------------

    async def test_write_atomic_commits_all_and_returns_ids_in_order(
        self, store: MemoryStore
    ) -> None:
        # An all-UPSERT batch persists every record; the returned ids are exactly
        # the writes' ids, in order (not sorted, not the store's own order).
        writes = [MemoryWrite(record=_semantic(f"w{i}", "coffee note")) for i in (2, 0, 1)]

        returned = await store.write_atomic(writes)

        assert list(returned) == ["w2", "w0", "w1"]
        for wid in ("w0", "w1", "w2"):
            assert await store.get(wid) is not None

    async def test_write_atomic_empty_batch_is_a_noop(self, store: MemoryStore) -> None:
        assert list(await store.write_atomic([])) == []

    async def test_write_atomic_upsert_overwrites_a_present_id(self, store: MemoryStore) -> None:
        # An UPSERT on an existing id overwrites it, exactly as a bare add upsert
        # does — verified with an open, different-kind replacement so get sees it.
        await store.add(_semantic("1", "old semantic note"))
        replacement = _preference("1", "new preference note")

        await store.write_atomic([MemoryWrite(record=replacement, mode=MemoryWriteMode.UPSERT)])

        got = await store.get("1")
        assert got is not None
        assert got.kind == "preference"  # the old semantic kind is gone
        assert got == replacement

    async def test_write_atomic_upsert_window_close_is_kept_by_export_not_get(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # The SUPERSEDE batch's first element: an UPSERT whose replacement is
        # window-closed (valid_until = now). By ADR-0045 §6 that is asserted
        # through export (present) and get (None), not get returning it.
        await store.add(_semantic("t", "coffee target"))
        closed = _semantic("t", "coffee target", validity=Validity(valid_until=now))

        await store.write_atomic([MemoryWrite(record=closed, mode=MemoryWriteMode.UPSERT)])

        assert await store.get("t") is None
        assert "t" in {r.id for r in await store.export()}

    async def test_write_atomic_insert_if_absent_writes_a_new_id(self, store: MemoryStore) -> None:
        await store.write_atomic(
            [MemoryWrite(record=_semantic("p", "coffee"), mode=MemoryWriteMode.INSERT_IF_ABSENT)]
        )

        assert await store.get("p") is not None

    async def test_write_atomic_insert_if_absent_rejects_a_present_id(
        self, store: MemoryStore
    ) -> None:
        # A collision is rejected, not upserted: the stored record is untouched
        # and the colliding write is not applied (nothing from the batch commits).
        await store.add(_semantic("x", "original content"))
        collide = _preference("x", "would clobber")

        with pytest.raises(MemoryStoreConflictError):
            await store.write_atomic(
                [MemoryWrite(record=collide, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )

        got = await store.get("x")
        assert got is not None
        assert got.kind == "semantic"  # the original, not the rejected preference
        assert got.content == "original content"

    async def test_write_atomic_insert_if_absent_collides_on_a_window_closed_row(
        self, store: MemoryStore
    ) -> None:
        # "Absent" is physical presence, not read-visibility: a window-closed row
        # is off the read path yet still occupies its id, so an INSERT_IF_ABSENT
        # whose minted id equals it must fail rather than clobber retained history.
        await store.add(_semantic("retired", "coffee", validity=Validity(valid_until=_LONG_AGO)))
        assert await store.get("retired") is None  # invisible to reads...

        with pytest.raises(MemoryStoreConflictError):  # ...but still present
            await store.write_atomic(
                [
                    MemoryWrite(
                        record=_semantic("retired", "new"), mode=MemoryWriteMode.INSERT_IF_ABSENT
                    )
                ]
            )

        assert "retired" in {r.id for r in await store.export()}  # the old row survives

    async def test_write_atomic_insert_if_absent_collides_on_an_expired_row(
        self, store: MemoryStore
    ) -> None:
        # The same physical-presence rule for the other hidden-row axis: an
        # expired row still blocks an insert on its id.
        await store.add(_semantic("gone", "coffee", expires_at=_LONG_AGO))

        for _ in range(2):
            # Twice: a rejected batch must *retain* the colliding row, not delete
            # it. Both get and export hide an expired row, so one collision cannot
            # tell "rejected and kept" from "deleted then raised"; a second
            # collision on the same id proves the row survived the first.
            with pytest.raises(MemoryStoreConflictError):
                await store.write_atomic(
                    [
                        MemoryWrite(
                            record=_semantic("gone", "new"), mode=MemoryWriteMode.INSERT_IF_ABSENT
                        )
                    ]
                )

    async def test_write_atomic_supersede_shape_commits_both_atomically(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # The canonical two-element batch: close the target's window (UPSERT) and
        # insert the correction at a fresh id (INSERT_IF_ABSENT). Both land.
        await store.add(_semantic("target", "coffee target"))
        t_closed = _semantic("target", "coffee target", validity=Validity(valid_until=now))
        correction = _semantic("correction", "coffee correction")

        returned = await store.write_atomic(
            [
                MemoryWrite(record=t_closed, mode=MemoryWriteMode.UPSERT),
                MemoryWrite(record=correction, mode=MemoryWriteMode.INSERT_IF_ABSENT),
            ]
        )

        assert list(returned) == ["target", "correction"]
        assert await store.get("target") is None  # retired
        assert await store.get("correction") is not None  # live replacement
        assert {r.id for r in await store.export()} == {"target", "correction"}  # both retained

    async def test_write_atomic_rolls_back_when_a_later_element_conflicts(
        self, store: MemoryStore
    ) -> None:
        # A valid element followed by a colliding one commits nothing: the valid
        # element's record must not appear (in-call all-or-nothing).
        await store.add(_semantic("present", "already here"))

        with pytest.raises(MemoryStoreConflictError):
            await store.write_atomic(
                [
                    MemoryWrite(record=_semantic("fresh", "would be written")),
                    MemoryWrite(
                        record=_semantic("present", "collides"),
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    ),
                ]
            )

        assert await store.get("fresh") is None  # the earlier element rolled back

    async def test_write_atomic_rolls_back_when_an_earlier_element_conflicts(
        self, store: MemoryStore
    ) -> None:
        # The conflict-first order: the later valid element must not commit either.
        await store.add(_semantic("present", "already here"))

        with pytest.raises(MemoryStoreConflictError):
            await store.write_atomic(
                [
                    MemoryWrite(
                        record=_semantic("present", "collides"),
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    ),
                    MemoryWrite(record=_semantic("fresh", "would be written")),
                ]
            )

        assert await store.get("fresh") is None

    async def test_write_atomic_rejects_a_repeated_id(self, store: MemoryStore) -> None:
        # Two writes to one id is forbidden as a malformed batch, and nothing is
        # written — a MemoryStoreError, not a conflict.
        with pytest.raises(MemoryStoreError):
            await store.write_atomic(
                [
                    MemoryWrite(record=_semantic("dup", "first")),
                    MemoryWrite(record=_semantic("dup", "second")),
                ]
            )

        assert await store.get("dup") is None

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`store_suspended_mid_write` — so a new
    #: durable backend that reintroduces ADR-0054's bug fails here rather than
    #: passing a suite that never looked. Opting out is a visible declaration in
    #: the subclass, exactly as ``serves_a_fixed_instant`` is for the context
    #: provider.
    acquires_no_shared_resource: bool = False

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[tuple[MemoryStore, SuspendedCall, ResourceLog]]:
        """Supply a store whose next ``add`` stops *inside* the resource it took.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the store raised ``CancelledError`` correctly
        and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        How the call is made to stop there is implementation-specific — a worker
        thread parked mid-SQL, a fake's modelled resource — which is why this is a
        hook and not something the suite can build. Returned as a context manager
        so the subject is disposed of the way that implementation needs.

        The :class:`ResourceLog` records each call's time *inside* the resource,
        and the case reads it once the scenario is over. It is not redundant with
        the blocked-caller check below: that one is decisive only where queueing
        is loop-bound (a fake on an ``asyncio.Lock``), while a store whose work
        runs on an executor can leave a second call pending for reasons that have
        nothing to do with the resource. The log settles that case directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_cancelled_write_holds_its_resource_until_the_work_finishes(self) -> None:
        """``core.protocols``' cancellation clause, on the write path (ADR-0060).

        A cancelled write must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way.

        The first write's *effect* is deliberately not asserted. The clause's
        third paragraph makes it indeterminate to the caller — under ADR-0054's
        shield a cancelled write that reached ``COMMIT`` is durably written — so
        the suite pins what a caller may actually rely on: the record is absent or
        whole, never torn, and the store still serves reads.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        async with self.store_suspended_mid_write() as (store, suspended, log):
            first = asyncio.ensure_future(store.add(_semantic("cancel-1", "alpha")))
            second = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(store.add(_semantic("cancel-2", "bravo")))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract:
                # a second delivered while the deferred wait runs must not escape
                # and unwind out of the resource either (ADR-0054's helper loops
                # on `while not done.is_set()` for exactly this).
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            assert await second == "cancel-2"

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time.
            assert not log.overlapped, _RELEASED_EARLY
            assert log.visits == 2, "both calls should have reached the resource by now"

            # The resource survived both: the second write is durable, the first
            # is absent-or-whole, and reads still work.
            assert await store.get("cancel-2") is not None
            cancelled_record = await store.get("cancel-1")
            assert cancelled_record is None or cancelled_record.content == "alpha"
            assert {record.id for record in await store.export()} >= {"cancel-2"}

    # --- input observation (ADR-0065) ---------------------------------------

    #: Whether this implementation performs no ``await`` between the coroutine's
    #: first executed line and the point its input is committed — no suspension
    #: window for a caller's mutation to land in. ``core.protocols``' input clause
    #: is then discharged by "do not suspend" and the two cases below reduce to a
    #: post-call assertion, correctly: a write with no window has none to tear in.
    #: Left ``False``, the suite requires the implementation to open that window by
    #: overriding :meth:`store_suspended_at_its_first_await` — so a backend that
    #: reintroduces the #286 tear fails here rather than passing a suite that never
    #: looked. Deliberately *not* the same declaration as
    #: :attr:`acquires_no_shared_resource`: the two clauses are different axes with
    #: different vacuity sets (ADR-0065 §"This is not ADR-0060's axis"), so a store
    #: may well be vacuous under one and live under the other.
    writes_without_suspending: bool = False

    def store_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[MemoryStore, SuspendedCall]]:
        """Supply a store whose next write stops at **its own first ``await``**.

        Override unless :attr:`writes_without_suspending` is set. The next
        :meth:`~ai_assistant.core.protocols.MemoryStore.add` or
        :meth:`~ai_assistant.core.protocols.MemoryStore.write_atomic` must suspend
        there and stay suspended until the case releases it; later calls run free,
        because the cases go on to read the store back.

        **The position is part of the hook's contract, not the implementer's
        choice** (ADR-0065 §3). A hook fired at method *entry* would let the
        mutation land before the method had read anything, so the store would
        observe one coherent mutated version, the case would pass, and a tear at
        the real window would survive untested. The first ``await`` is exactly the
        boundary the clause draws: a conforming write has taken its one observation
        before that point and cannot be reached by the mutation, while a write that
        reads its argument again afterwards is torn by it. It is also well-defined
        for a *non*-conforming implementation, which matters — a conforming one has
        no second read to position a hook against.

        What to suspend on is implementation-specific — a store's injected
        collaborator, a fake's modelled resource — which is why this is a hook and
        not something the suite can build. It is a real, if small, obligation on
        anything handed to this suite, taken deliberately: ADR-0060 §3 settled the
        same trade for its own hook, and a test-only affordance on the production
        seam would buy observability by widening the contract every consumer
        depends on. Returned as a context manager so the subject is disposed of the
        way that implementation needs.
        """
        raise NotImplementedError

    @contextlib.asynccontextmanager
    async def _write_subject(
        self, store: MemoryStore
    ) -> AsyncIterator[tuple[MemoryStore, SuspendedCall | None]]:
        """The store the two cases below drive, and the gate holding its next write.

        ``None`` for the gate where the implementation declares
        :attr:`writes_without_suspending`; the ``store`` fixture is then the
        subject, since there is no window to open and nothing to build.
        """
        if self.writes_without_suspending:
            yield store, None
            return
        async with self.store_suspended_at_its_first_await() as (subject, gate):
            yield subject, gate

    async def test_add_derives_everything_from_one_observation_of_its_record(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``add`` (ADR-0065, ADR-0056/#286).

        With the write held at its first ``await``, the caller mutates the record
        it still holds. Which version the store commits is *not* asserted — the
        clause makes that indeterminate, and both "snapshot first" and "read once,
        after suspending" are conforming discharges. What is asserted is that one
        version describes the whole outcome: the returned id names the row that was
        written, that row is some single version of the record rather than a mix of
        two, and its retrieval entry was built from the content the row carries.

        The last of those is the point. ``test_stored_records_are_isolated_from_
        caller_mutation`` mutates *after* ``add`` returns, and the torn code passed
        it on every backend for the whole time the tear was live (ADR-0065
        §"The suite already appears to cover this"): a post-call assertion cannot
        distinguish a store that snapshots from one that tears, because by then
        there is nothing left to tear.
        """
        async with self._write_subject(store) as (subject, gate):
            record = _semantic("obs-add", "alpha alpha alpha")
            before = record.model_copy(deep=True)
            async with _held_at_its_first_await(gate, subject.add(record)) as call:
                record.id = "obs-add-moved"
                record.content = "bravo bravo bravo"
                after = record.model_copy(deep=True)
            returned = await call

            stored = await subject.get(returned)
            assert stored is not None, (
                f"add returned {returned!r}, which names no readable row. {_TORN_INPUT}"
            )
            assert stored in (before, after), _TORN_INPUT
            # One record was written, at one id — not the old id and the new one.
            assert {r.id for r in await subject.export()} == {returned}, _TORN_INPUT
            rejected = after.content if stored.content == before.content else before.content
            await _assert_indexed_from_the_content_it_carries(
                subject, returned, rejected_content=rejected
            )

    async def test_write_atomic_derives_everything_from_one_observation_of_its_batch(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``write_atomic`` (ADR-0065, ADR-0046 §3).

        Not a rewording of the ``add`` case: this argument is a caller-owned
        ``Sequence`` whose elements are ``frozen`` ``MemoryWrite``s holding
        *mutable* records — the clause's own example of why "the argument is
        frozen" is not a discharge — and the batch is validated for repeated ids
        before it is committed. A backend that validates one observation and
        commits another can pass its duplicate-id check on a batch it does not
        write.

        So all three axes move at once while the write is held: an element's id
        (the one the check validated), an element's content, and the caller's list
        itself. Either outcome is conforming — the batch commits, or the store saw
        the repeated id and rejected the whole thing — but each must rest on one
        observation.
        """
        async with self._write_subject(store) as (subject, gate):
            first = _semantic("obs-batch-1", "alpha alpha alpha")
            second = _semantic("obs-batch-2", "bravo bravo bravo")
            writes = [MemoryWrite(record=first), MemoryWrite(record=second)]
            before = [write.record.model_copy(deep=True) for write in writes]
            async with _held_at_its_first_await(gate, subject.write_atomic(writes)) as call:
                first.id = second.id  # a repeated id the pre-await check did not see
                second.content = "charlie charlie charlie"
                writes.append(MemoryWrite(record=_semantic("obs-batch-3", "delta delta delta")))
                after = [write.record.model_copy(deep=True) for write in writes]

            try:
                returned = list(await call)
            except MemoryStoreError:
                # Conforming the other way: a store that took its one observation
                # *after* suspending saw the repeated id and refused the batch. The
                # refusal is all-or-nothing like any other (ADR-0046 §4).
                assert await subject.export() == [], _TORN_INPUT
                return

            committed = {record.id: record for record in await subject.export()}
            assert len(returned) == len(committed), (
                f"write_atomic returned {returned} but committed {sorted(committed)}: an id "
                f"was written twice, so the repeated-id check and the commit disagreed. "
                f"{_TORN_INPUT}"
            )
            assert set(returned) == set(committed), _TORN_INPUT
            assert committed in ({r.id: r for r in before}, {r.id: r for r in after}), _TORN_INPUT
            # The second element is the one whose *content* moved (its id did not),
            # so it is where a batch that persisted one version and indexed the
            # other shows up.
            surviving = committed.get(before[1].id)
            assert surviving is not None, _TORN_INPUT
            await _assert_indexed_from_the_content_it_carries(
                subject,
                surviving.id,
                rejected_content=(
                    after[1].content
                    if surviving.content == before[1].content
                    else before[1].content
                ),
            )
