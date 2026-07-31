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
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall, SuspendedMidWrite

    StoreFactory = Callable[[Callable[[], datetime]], MemoryStore]
from ai_assistant.core.types import (
    BeliefBand,
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
_ONE_MINUTE = timedelta(minutes=1)
#: The transaction stamp every fixture record carries unless a case varies it —
#: comfortably before ``_STORE_NOW``, so nothing is accidentally not-yet-live.
_REVISED = datetime(2026, 1, 1, tzinfo=UTC)
#: ``list_beliefs``'s default page size (ADR-0073 §2), and the number of extra
#: records the default-limit case seeds beyond it so the default is really tested.
_DEFAULT_PAGE = 50
_MORE_THAN_A_PAGE = 55

#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


def _provenance(
    *,
    source: MemorySource = MemorySource.OBSERVED,
    last_updated: datetime = _REVISED,
) -> Provenance:
    """Provenance for a fixture record, in whichever band ``source`` places it.

    Confidence follows the source rather than being a parameter: ``USER_ASSERTED``
    provenance is unconstructable below 1.0 (``_user_asserted_is_certain``), and
    every other source in these cases wants a sub-1.0 figure.
    """
    certain = source is MemorySource.USER_ASSERTED
    return Provenance(source=source, confidence=1.0 if certain else 0.6, last_updated=last_updated)


def _semantic(  # noqa: PLR0913 — one keyword per record axis a case may need to vary
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
    source: MemorySource = MemorySource.OBSERVED,
    last_updated: datetime = _REVISED,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(source=source, last_updated=last_updated),
        expires_at=expires_at,
        validity=validity or Validity(),
    )


def _preference(
    record_id: str,
    content: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    last_updated: datetime = _REVISED,
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=_provenance(source=source, last_updated=last_updated),
    )


#: What a failure of either input-observation case below means, in one place
#: (ADR-0065): the call read the caller's argument more than once and the reads
#: disagreed, so one result now describes two versions of one input.
_TORN_INPUT = (
    "the write derived its outcome from more than one observation of its input: a "
    "caller's mid-flight mutation reached part of what was committed and not the "
    "rest, so no single version of the argument describes the result"
)
_LATE_FILTER = (
    "the read answered from a version of its filter that did not exist when the "
    "work began: a caller's mid-flight mutation widened the result, so the filter "
    "was observed after the first await rather than before it (ADR-0065 §1)"
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


#: What a torn atomic batch looks like after the fact: some of its rows landed and
#: some did not, which ``write_atomic`` forbids however its caller was cancelled.
_TORN_ATOMIC = "the atomic batch committed some rows and not others"


class _CancellationOp(Protocol):
    """One locked ``MemoryStore`` operation the ADR-0060 case drives (#370, #397).

    Each :attr:`name` selects a distinct ``async with self._lock:
    _run_to_completion(...)`` site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``add``. :meth:`first` and :meth:`second` are two *independent* subjects, so
    the concurrent second succeeds whatever the cancelled first's indeterminate
    effect turns out to be.

    **Reads are operations too** (#397). ADR-0060 §3 binds any method that
    acquires the resource, and every locked read here holds the connection lock
    around its own worker-thread SQL — so a regression replacing one read's
    ``_run_to_completion`` with a bare ``to_thread`` would release the connection
    to a concurrent caller while that read's worker still used it, and every write
    case would still pass.
    """

    name: str

    async def prepare(self, store: MemoryStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, store: MemoryStore) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _AddOp:
    """The single-row ``add`` path — ADR-0060's original subject."""

    name = "add"

    async def prepare(self, store: MemoryStore) -> None:
        """No preconditions."""

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Add the record whose write is cancelled."""
        return store.add(_semantic("cancel-1", "alpha"))

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Add an independent record concurrently."""
        return store.add(_semantic("cancel-2", "bravo"))

    async def verify(self, store: MemoryStore) -> None:
        """The second record is durable; the first is absent-or-whole; reads work."""
        assert await store.get("cancel-2") is not None
        cancelled = await store.get("cancel-1")
        assert cancelled is None or cancelled.content == "alpha"
        assert {record.id for record in await store.export()} >= {"cancel-2"}


class _WriteAtomicOp:
    """The multi-row ``write_atomic`` transaction (#370, priority 1).

    Two rows per call, so a torn intermediate state is reachable that ``add``'s
    single row cannot produce: the case pins that the concurrent batch commits
    whole and the cancelled batch is all-or-nothing.
    """

    name = "write_atomic"

    async def prepare(self, store: MemoryStore) -> None:
        """No preconditions."""

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Commit a two-row batch whose write is cancelled."""
        return store.write_atomic(
            [
                MemoryWrite(record=_semantic("wa-1a", "alpha one")),
                MemoryWrite(record=_semantic("wa-1b", "alpha two")),
            ]
        )

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Commit an independent two-row batch concurrently."""
        return store.write_atomic(
            [
                MemoryWrite(record=_semantic("wa-2a", "bravo one")),
                MemoryWrite(record=_semantic("wa-2b", "bravo two")),
            ]
        )

    async def verify(self, store: MemoryStore) -> None:
        """The second batch is whole and correct; the cancelled batch is all-or-nothing.

        Each present row is compared to the record it was *given*, not merely by
        id: a torn write that kept the id but committed the wrong row — the
        ADR-0056 shape — would slip past an id-only check.
        """
        by_id = {record.id: record for record in await store.export()}
        assert by_id.get("wa-2a") == _semantic("wa-2a", "bravo one")
        assert by_id.get("wa-2b") == _semantic("wa-2b", "bravo two")
        cancelled = {"wa-1a", "wa-1b"} & by_id.keys()
        assert cancelled in ({"wa-1a", "wa-1b"}, set()), _TORN_ATOMIC
        for record_id, content in (("wa-1a", "alpha one"), ("wa-1b", "alpha two")):
            if record_id in by_id:
                assert by_id[record_id] == _semantic(record_id, content), _TORN_ATOMIC


class _DeleteOp:
    """The ``delete`` path, on two independent pre-seeded records."""

    name = "delete"

    async def prepare(self, store: MemoryStore) -> None:
        """Seed the two records the calls delete."""
        await store.add(_semantic("del-a", "alpha"))
        await store.add(_semantic("del-b", "bravo"))

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Delete record A — the call that is cancelled."""
        return store.delete("del-a")

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Delete record B concurrently."""
        return store.delete("del-b")

    async def verify(self, store: MemoryStore) -> None:
        """Record B is gone; the store still serves reads."""
        assert await store.get("del-b") is None


class _ClearOp:
    """The ``clear`` path, with a seeded record so it does real connection work."""

    name = "clear"

    async def prepare(self, store: MemoryStore) -> None:
        """A record for ``clear`` to remove."""
        await store.add(_semantic("seed", "alpha"))

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Clear the store — the call that is cancelled."""
        return store.clear()

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return store.clear()

    async def verify(self, store: MemoryStore) -> None:
        """The store is empty and still serves reads."""
        assert not await store.export()


class _PurgeExpiredOp:
    """The ``purge_expired`` sweep, its own locked write distinct from ``clear``."""

    name = "purge_expired"

    async def prepare(self, store: MemoryStore) -> None:
        """Seed an expired record for the sweep to remove, and a live one to keep."""
        await store.add(_semantic("expired", "alpha", expires_at=_LONG_AGO))
        await store.add(_semantic("live", "bravo"))

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Sweep expired records — the call that is cancelled."""
        return store.purge_expired()

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Sweep again concurrently."""
        return store.purge_expired()

    async def verify(self, store: MemoryStore) -> None:
        """The live record survives; the store still serves reads."""
        assert await store.get("live") is not None


class _ReadOp:
    """A locked ``MemoryStore`` read, driven against a store seeded the same way (#397).

    The two calls are the *same* read of independent records rather than two
    different ones, because what distinguishes a read op is its lock site and both
    calls have to enter it. Nothing is asserted about the cancelled read's answer —
    it has none, its task was cancelled — so :meth:`verify` pins the state the
    second call had to see, re-read after the scenario.
    """

    name = ""

    async def prepare(self, store: MemoryStore) -> None:
        """Seed the two records every read op below answers from."""
        await store.add(_semantic("read-a", "alpha alpha alpha"))
        await store.add(_preference("read-b", "bravo bravo bravo"))

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: MemoryStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        assert await store.get("read-a") == _semantic("read-a", "alpha alpha alpha")
        assert {record.id for record in await store.export()} == {"read-a", "read-b"}


class _GetOp(_ReadOp):
    """``get`` — one row by id, under the connection lock (``sqlite_store.py:641``)."""

    name = "get"

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Read record A — the call that is cancelled."""
        return store.get("read-a")

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Read record B concurrently."""
        return store.get("read-b")


class _SearchOp(_ReadOp):
    """``search`` — retrieval under the same lock, after the embedding await."""

    name = "search"

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Search for A's words — the call that is cancelled."""
        return store.search("alpha")

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Search for B's words concurrently."""
        return store.search("bravo")


class _ListBeliefsOp(_ReadOp):
    """``list_beliefs`` — ADR-0073's enumeration, its own lock site.

    Not in #397's enumeration, which predates it: the method landed with ADR-0073
    and holds the connection lock across its own ``_run_to_completion`` like every
    other read, so leaving it out would preserve exactly the gap the issue is
    about.
    """

    name = "list_beliefs"

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Enumerate the semantic beliefs — the call that is cancelled."""
        return store.list_beliefs(kinds=[MemoryKind.SEMANTIC])

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Enumerate the preferences concurrently."""
        return store.list_beliefs(kinds=[MemoryKind.PREFERENCE])


class _ExportOp(_ReadOp):
    """``export`` — the whole-store read, its own lock site."""

    name = "export"

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


#: Every locked ``MemoryStore`` operation ADR-0060's case is run against: each is a
#: distinct ``async with self._lock`` site with its own ``_run_to_completion``. The
#: writes came first (#370); the reads are the same invariant on the other half of
#: the surface (#397), and ADR-0060 §3 binds "any method that acquires the
#: resource" rather than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _AddOp,
    _WriteAtomicOp,
    _DeleteOp,
    _ClearOp,
    _PurgeExpiredOp,
    _GetOp,
    _SearchOp,
    _ListBeliefsOp,
    _ExportOp,
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

    async def test_stored_records_cannot_be_mutated_by_the_caller(self, store: MemoryStore) -> None:
        """Immutability subsumes post-call aliasing isolation (ADR-0068).

        The property the old aliasing case protected — a handed-out copy cannot
        reach stored state — is now guaranteed by the record graph being frozen:
        there is no mutation to isolate against, because none is representable.
        Both mutations below (the object the caller passed to ``add``, and one a
        read handed back) raise on a validly-constructed record, so the caller can
        neither retire nor revive a stored record by editing the nested
        ``Validity``.
        """
        original = _semantic("iso", "coffee", validity=Validity(valid_until=_FAR_FUTURE))
        await store.add(original)

        with pytest.raises(ValidationError):
            original.validity.valid_until = _LONG_AGO  # the caller's own object is frozen
        assert await store.get("iso") is not None  # stored copy is still live

        got = await store.get("iso")
        assert got is not None
        with pytest.raises(ValidationError):
            got.validity.valid_until = _LONG_AGO  # a returned object is frozen too
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

    # --- band-scoped enumeration: list_beliefs (ADR-0073 §2) ------------------
    # One clause per obligation in ADR-0073 §2, as §8 requires. Two of them are
    # about the *arguments doing anything* and a suite of small explicit values
    # never reaches either: the offset case asserts returned **ids** (an
    # implementation ignoring offset serves a correct first page forever and
    # passes a length-only assertion), and the default-limit case seeds more than
    # a page (an implementation defaulting to 100, or to unbounded, satisfies
    # every explicit-limit case while breaking the bounded default).
    #
    # Its **input-observation** clause is not here but with the other three, under
    # "input observation (ADR-0065)" below, because what it asserts only makes sense
    # beside them. ADR-0073 §8 left this obligation stated and unproven — the
    # suspension hook named only writes, so no case could position a mutation inside
    # a read — and #436 closed it for both reads at once, which is the condition §8
    # set. No cancellation clause, though: ``_CANCELLATION_OPS`` is write-scoped and
    # the locked read paths are tracked separately (#397).

    async def test_list_beliefs_returns_live_beliefs(self, store: MemoryStore) -> None:
        # The baseline: an enumeration with no query, returning what is held.
        await store.add(_semantic("s", "a stored fact"))
        await store.add(_preference("p", "a stored preference"))

        listed = await store.list_beliefs()

        assert {record.id for record in listed} == {"s", "p"}
        assert {record.kind for record in listed} == {"semantic", "preference"}

    async def test_list_beliefs_honours_both_read_time_axes_on_both_ends(
        self, store: MemoryStore
    ) -> None:
        # ADR-0073 §2/§3: inspection reads live beliefs only, through the same
        # predicate get/search use — expired, retired, and not-yet-open alike are
        # out, so this read and retrieval cannot disagree.
        await store.add(_semantic("live", "held"))
        await store.add(_semantic("expired", "forgotten", expires_at=_LONG_AGO))
        await store.add(_semantic("retired", "was held", validity=Validity(valid_until=_LONG_AGO)))
        await store.add(_semantic("future", "not yet", validity=Validity(valid_from=_FAR_FUTURE)))

        assert [record.id for record in await store.list_beliefs()] == ["live"]
        # ...and the three hidden ones are still *retained*: this is a read filter,
        # never a deletion (the retired one is export's business, ADR-0073 §3).
        assert {record.id for record in await store.export()} >= {"retired", "future"}

    async def test_list_beliefs_window_boundaries_are_half_open(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # [from, until), the same boundary get/search are held to: at valid_until
        # the belief is already retired; at valid_from it is already live.
        await store.add(_semantic("at_until", "x", validity=Validity(valid_until=now)))
        await store.add(_semantic("at_from", "y", validity=Validity(valid_from=now)))
        await store.add(
            _semantic("before_until", "z", validity=Validity(valid_until=now + _ONE_HOUR))
        )

        assert {record.id for record in await store.list_beliefs()} == {"at_from", "before_until"}

    async def test_list_beliefs_orders_by_last_updated_descending_then_id_ascending(
        self, store: MemoryStore
    ) -> None:
        # ADR-0073 §2's total order. Both halves are needed: without the time key
        # the newest revision does not lead, and without the id tie-break two
        # stores answer the same page differently while each believes it conforms.
        await store.add(_semantic("b", "tied, second by id", last_updated=_REVISED))
        await store.add(_semantic("a", "tied, first by id", last_updated=_REVISED))
        await store.add(_semantic("c", "newest revision", last_updated=_REVISED + _ONE_HOUR))

        assert [record.id for record in await store.list_beliefs()] == ["c", "a", "b"]

    async def test_list_beliefs_offset_selects_a_later_slice_of_the_same_order(
        self, store: MemoryStore
    ) -> None:
        # Asserting *ids*, not the page's length: an implementation that ignores
        # offset returns a full, correctly-ordered first page forever and passes a
        # length-only assertion for good, leaving nothing past it reachable.
        for i in range(5):
            await store.add(_semantic(f"r{i}", f"note {i}", last_updated=_REVISED - i * _ONE_HOUR))

        assert [r.id for r in await store.list_beliefs(limit=2)] == ["r0", "r1"]
        assert [r.id for r in await store.list_beliefs(limit=2, offset=2)] == ["r2", "r3"]
        assert [r.id for r in await store.list_beliefs(limit=2, offset=4)] == ["r4"]
        assert await store.list_beliefs(limit=2, offset=5) == []  # past the end

    async def test_list_beliefs_default_limit_is_a_bounded_page(self, store: MemoryStore) -> None:
        # Exercised with more than a page of matching records, deliberately: an
        # implementation defaulting to 100, or to unbounded, satisfies every
        # explicit-limit case on this list while breaking the guarantee that keeps
        # an unbounded read of a Tier 1 store from being what saying nothing gets.
        for i in range(_MORE_THAN_A_PAGE):
            await store.add(
                _semantic(f"r{i:03d}", f"note {i}", last_updated=_REVISED - i * _ONE_MINUTE)
            )

        listed = await store.list_beliefs()

        assert [r.id for r in listed] == [f"r{i:03d}" for i in range(_DEFAULT_PAGE)]

    async def test_list_beliefs_limit_zero_returns_an_empty_page(self, store: MemoryStore) -> None:
        # Asking for nothing is a question with an answer, not an error.
        await store.add(_semantic("1", "a stored fact"))

        assert await store.list_beliefs(limit=0) == []

    @pytest.mark.parametrize(
        ("limit", "offset", "rejected"),
        [
            pytest.param(-1, 0, "limit", id="negative-limit"),
            pytest.param(_DEFAULT_PAGE, -1, "offset", id="negative-offset"),
            pytest.param(2**63, 0, "limit", id="over-wide-limit"),
            pytest.param(_DEFAULT_PAGE, 2**63, "offset", id="over-wide-offset"),
        ],
    )
    async def test_list_beliefs_refuses_paging_outside_the_signed_64_bit_range(
        self, store: MemoryStore, limit: int, offset: int, rejected: str
    ) -> None:
        # Both ends, because both are places two backends silently disagree:
        # SQLite reads LIMIT -1 as *no limit at all*, and a value past the bind
        # range raises OverflowError out of the driver where an in-memory store
        # answers with an empty page (ADR-0073 §2). Refused, never clamped.
        #
        # The message must name the offending parameter. That is what separates
        # "the store refused this argument" from any other ValueError raised
        # somewhere inside the read — a decode failure would otherwise satisfy an
        # unqualified ``pytest.raises`` and certify a store that never checked.
        await store.add(_semantic("1", "a stored fact"))

        with pytest.raises(ValueError, match=rejected):
            await store.list_beliefs(limit=limit, offset=offset)

    async def test_list_beliefs_filters_by_band(self, store: MemoryStore) -> None:
        # None is every band; an empty sequence selects nothing; a band selects the
        # whole band, both sources of DERIVED together (ADR-0072 §4 keeps them
        # indistinguishable, which is why the filter is by band and not by source).
        await store.add(_semantic("asserted", "told", source=MemorySource.USER_ASSERTED))
        await store.add(_semantic("observed", "watched", source=MemorySource.OBSERVED))
        await store.add(_semantic("inferred", "reasoned", source=MemorySource.INFERRED))
        await store.add(_semantic("external", "reported", source=MemorySource.EXTERNAL))
        every = {"asserted", "observed", "inferred", "external"}

        assert {r.id for r in await store.list_beliefs()} == every
        assert {r.id for r in await store.list_beliefs(bands=None)} == every
        assert await store.list_beliefs(bands=[]) == []
        derived = await store.list_beliefs(bands=[BeliefBand.DERIVED])
        assert {r.id for r in derived} == {"observed", "inferred"}
        pair = await store.list_beliefs(bands=[BeliefBand.ASSERTED, BeliefBand.ATTESTED])
        assert {r.id for r in pair} == {"asserted", "external"}

    async def test_list_beliefs_filters_by_kind(self, store: MemoryStore) -> None:
        # The same convention, stated rather than inferred from ``search``: an
        # empty ``kinds`` selects nothing, never "no filter" (ADR-0073 §1).
        await store.add(_semantic("s", "a fact"))
        await store.add(_preference("p", "a preference"))

        assert {r.id for r in await store.list_beliefs()} == {"s", "p"}
        assert {r.id for r in await store.list_beliefs(kinds=None)} == {"s", "p"}
        assert await store.list_beliefs(kinds=[]) == []
        listed = await store.list_beliefs(kinds=[MemoryKind.PREFERENCE])
        assert [r.id for r in listed] == ["p"]

    async def test_list_beliefs_composes_the_two_filters_by_conjunction(
        self, store: MemoryStore
    ) -> None:
        # A record is listed when its band is selected *and* its kind is — the full
        # 2x2, so a store that unions the filters fails on three of the four.
        await store.add(_semantic("as", "fact told", source=MemorySource.USER_ASSERTED))
        await store.add(_preference("ap", "pref told", source=MemorySource.USER_ASSERTED))
        await store.add(_semantic("ds", "fact inferred", source=MemorySource.INFERRED))
        await store.add(_preference("dp", "pref inferred", source=MemorySource.INFERRED))

        listed = await store.list_beliefs(
            bands=[BeliefBand.ASSERTED], kinds=[MemoryKind.PREFERENCE]
        )

        assert [r.id for r in listed] == ["ap"]

    async def test_list_beliefs_page_is_full_under_the_filters(self, store: MemoryStore) -> None:
        # Filtering must happen before the cut: an implementation that takes the
        # first ``limit`` records and *then* drops the non-matching ones returns a
        # short page while matches it never looked at remain.
        for i in range(6):
            stamp = _REVISED - i * _ONE_HOUR
            if i % 2 == 0:  # the non-matching kind sorts ahead of each match
                await store.add(_preference(f"r{i}", f"note {i}", last_updated=stamp))
            else:
                await store.add(_semantic(f"r{i}", f"note {i}", last_updated=stamp))

        page = await store.list_beliefs(kinds=[MemoryKind.SEMANTIC], limit=2)

        assert [r.id for r in page] == ["r1", "r3"]

    async def test_list_beliefs_page_is_full_under_the_window_and_expiry_axes(
        self, store: MemoryStore
    ) -> None:
        # The case a suite naturally omits, and the one that separates this read
        # from ``search``: the records sorting *ahead* of the cut are unreadable
        # (expired, retired, not yet open), so an implementation that mirrors
        # search's ratified post-filter (ADR-0045 §6) applies them after LIMIT and
        # returns a short page — losing rows no later page returns.
        newest = _REVISED
        await store.add(_semantic("x0", "expired", last_updated=newest, expires_at=_LONG_AGO))
        await store.add(
            _semantic(
                "x1",
                "retired",
                last_updated=newest - _ONE_HOUR,
                validity=Validity(valid_until=_LONG_AGO),
            )
        )
        await store.add(
            _semantic(
                "x2",
                "not yet",
                last_updated=newest - 2 * _ONE_HOUR,
                validity=Validity(valid_from=_FAR_FUTURE),
            )
        )
        for i in range(3):
            await store.add(
                _semantic(f"r{i}", f"live {i}", last_updated=newest - (3 + i) * _ONE_HOUR)
            )

        page = await store.list_beliefs(limit=2)

        assert [r.id for r in page] == ["r0", "r1"]

    async def test_list_beliefs_clears_a_score_the_stored_record_carries(
        self, store: MemoryStore
    ) -> None:
        # Seeded non-None on purpose: ``add`` takes any MemoryRecord, including one
        # ``search`` handed back with its relevance populated, so an enumerator
        # returning stored copies unchanged would surface a figure from some other
        # query. Asserting None over default-constructed records tests nothing.
        await store.add(_semantic("scored", "coffee"))
        ranked = [r for r in await store.search("coffee") if r.id == "scored"]
        assert ranked
        assert ranked[0].score is not None  # the store populated one
        await store.add(ranked[0])  # re-add the *scored* copy

        listed = await store.list_beliefs()

        assert [r.id for r in listed] == ["scored"]
        assert listed[0].score is None

    async def test_list_beliefs_judges_every_record_against_one_clock_reading(
        self, store_factory: StoreFactory
    ) -> None:
        # One page, one "now" — the clause ``search`` already carries, which
        # matters more here: rows dropped mid-scan are also a *paging* fault, since
        # they shift every subsequent offset.
        step = _ONE_HOUR
        state = {"now": _STORE_NOW}

        def advancing() -> datetime:
            reading = state["now"]
            state["now"] = reading + step
            return reading

        store = store_factory(advancing)
        # All fall due after the first reading but before any later one, so a
        # per-record advancing clock would retire the later-iterated ones.
        deadline = _STORE_NOW + step // 2
        for i in range(3):
            await store.add(
                _semantic(f"c{i}", f"note {i}", validity=Validity(valid_until=deadline))
            )

        listed = await store.list_beliefs()

        assert {record.id for record in listed} == {"c0", "c1", "c2"}

    async def test_list_beliefs_returns_detached_snapshots(self, store: MemoryStore) -> None:
        # Like every other MemoryStore read: what comes back cannot reach stored
        # state. Under ADR-0068 the record graph is frozen, so the mutations that
        # would reach it are unrepresentable rather than merely isolated.
        await store.add(_semantic("iso", "coffee", validity=Validity(valid_until=_FAR_FUTURE)))

        listed = await store.list_beliefs()
        assert [record.id for record in listed] == ["iso"]
        with pytest.raises(ValidationError):
            listed[0].validity.valid_until = _LONG_AGO  # would retire the stored belief
        with pytest.raises(ValidationError):
            listed[0].provenance.confidence = 0.1  # nested model is frozen too

        again = await store.list_beliefs()
        assert [record.id for record in again] == ["iso"]
        assert again[0].provenance.confidence == 0.6

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
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[MemoryStore]]:
        """Supply a store whose named locked operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the store raised ``CancelledError`` correctly
        and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        The returned :class:`SuspendedMidWrite` carries the store, its
        :class:`ResourceLog`, and an ``arm(operation)`` lever the case calls —
        *after* its preconditions — to hold the next entry into that operation
        (#370, #397). Every distinct ``async with self._lock`` site is a separate
        place the same regression can reappear — the locked *reads* included, since
        ADR-0060 §3 binds any method that acquires the resource — so the case is run
        against each; ``arm``
        is where the implementation says how it stops a given one — a worker
        thread parked mid-SQL, a fake's single modelled resource. Returned as a
        context manager so the subject is disposed of the way that implementation
        needs.

        The :class:`ResourceLog` records each call's time *inside* the resource,
        and the case reads it once the scenario is over. It is not redundant with
        the blocked-caller check below: that one is decisive only where queueing
        is loop-bound (a fake on an ``asyncio.Lock``), while a store whose work
        runs on an executor can leave a second call pending for reasons that have
        nothing to do with the resource. The log settles that case directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per locked operation, so
        a regression reintroduced at any one lock site — not just ``add`` — is
        caught.

        **Named for an operation, not a write.** ADR-0060 §3 binds any method that
        acquires the resource; the writes were covered first (#370) and the locked
        reads are the same invariant on the other half of the surface (#397). A
        read that released the connection under cancellation while its worker still
        held it is the identical ADR-0054 hazard, and no write case can see it.

        The first call's *effect* is deliberately not asserted here (the op's
        ``verify`` pins only what a caller may rely on). The clause's third
        paragraph makes it indeterminate to the caller — under ADR-0054's shield a
        cancelled write that reached ``COMMIT`` is durably written — so the two
        calls are independent subjects and what is pinned is that the second is
        whole and the store still serves reads.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await op.prepare(store)
            # Arm *after* the preconditions, so a fake arming its one resource
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
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(store)

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

    #: The same declaration for the **read** side: whether ``search`` and
    #: ``list_beliefs`` perform no ``await`` between the coroutine's first executed
    #: line and the point their ``Sequence`` filters are read. A separate axis from
    #: :attr:`writes_without_suspending` because the two halves of a store diverge
    #: — the dict-backed implementations reach their filters with no ``await`` at
    #: all, while ``SqliteMemoryStore`` embeds the query and takes its lock first,
    #: which is exactly where #436 lived. Left ``False``, the suite requires the
    #: read window to be opened through the hook below.
    reads_without_suspending: bool = False

    def store_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[MemoryStore, Callable[[str], SuspendedCall]]]:
        """Supply a store whose next call to a **named operation** stops at its first ``await``.

        Override unless both :attr:`writes_without_suspending` and
        :attr:`reads_without_suspending` are set. The suite runs any preconditions
        the operation needs, then calls the returned ``arm(operation)`` to get the
        :class:`SuspendedCall` lever back — after the preconditions, so a store
        arming its one collaborator suspends the operation under test rather than a
        setup write. The named call must suspend at its own first ``await`` and stay
        there until the case releases it; later calls run free, because the cases go
        on to read the store back.

        **Naming the operation is what makes the hook reach reads** (#436). It
        originally suspended "the next write", which no read-side case could
        position a mutation inside — so ADR-0073 §8 had to state the
        materialise-before-the-first-await discharge as an obligation while
        recording that the suite would not prove it. The four operations the cases
        below arm are ``add``, ``write_atomic``, ``search`` and ``list_beliefs``;
        which collaborator stops each one is the implementation's business, and for
        one store they are not all the same collaborator.

        **The position is part of the hook's contract, not the implementer's
        choice** (ADR-0065 §3). A hook fired at method *entry* would let the
        mutation land before the method had read anything, so the store would
        observe one coherent mutated version, the case would pass, and a tear at
        the real window would survive untested. The first ``await`` is exactly the
        boundary the clause draws: a conforming call has taken its one observation
        before that point and cannot be reached by the mutation, while a call that
        reads its argument afterwards answers from the later version. It is also
        well-defined for a *non*-conforming implementation, which matters — a
        conforming one has no later read to position a hook against.

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
    async def _observation_subject(
        self, store: MemoryStore, *, vacuous: bool
    ) -> AsyncIterator[tuple[MemoryStore, Callable[[str], SuspendedCall] | None]]:
        """The store the four cases below drive, and the lever arming one of its calls.

        ``None`` for the lever where the implementation declares its axis
        non-suspending (:attr:`writes_without_suspending` for the two writes,
        :attr:`reads_without_suspending` for the two reads); the ``store`` fixture
        is then the subject, since there is no window to open and nothing to build.
        The caller arms *after* its own preconditions, which is why the lever is
        handed out rather than the gate.
        """
        if vacuous:
            yield store, None
            return
        async with self.store_suspended_at_its_first_await() as (subject, arm):
            yield subject, arm

    async def test_add_cannot_tear_on_a_mid_flight_mutation_of_its_record(
        self, store: MemoryStore
    ) -> None:
        """The ``add`` single-element tear is unrepresentable under ADR-0068.

        ADR-0065's input clause guarded ``add`` against the #286 tear, where the
        caller rewrote the record's id/content while the write was suspended and a
        backend that observed the record twice committed a mix of two versions.
        Freezing ``MemoryRecord`` makes that *stimulus* unrepresentable — the very
        point of ADR-0068: the mutation raises rather than tearing, so no backend
        can observe two versions of a single validly-constructed record. The clause
        survives only for the ``Sequence`` arguments (ADR-0068 §4), which
        :meth:`test_write_atomic_derives_everything_from_one_observation_of_its_batch`
        still exercises through the caller-owned, mutable list.
        """
        async with self._observation_subject(store, vacuous=self.writes_without_suspending) as (
            subject,
            arm,
        ):
            gate = None if arm is None else arm("add")
            record = _semantic("obs-add", "alpha alpha alpha")
            async with _held_at_its_first_await(gate, subject.add(record)) as call:
                # The tear needed these two rewrites mid-flight; the frozen record
                # refuses both, so there is no second version to commit.
                with pytest.raises(ValidationError):
                    record.id = "obs-add-moved"
                with pytest.raises(ValidationError):
                    record.content = "bravo bravo bravo"
            returned = await call

            stored = await subject.get(returned)
            assert stored is not None, (
                f"add returned {returned!r}, which names no readable row. {_TORN_INPUT}"
            )
            assert stored == record, _TORN_INPUT  # the one and only version
            assert {r.id for r in await subject.export()} == {returned}, _TORN_INPUT
            await _assert_indexed_from_the_content_it_carries(
                subject, returned, rejected_content="bravo bravo bravo"
            )

    async def test_write_atomic_derives_everything_from_one_observation_of_its_batch(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``write_atomic`` (ADR-0065, ADR-0068 §4).

        Not a rewording of the ``add`` case: freezing removes ``add``'s
        single-element tear, but this argument is a caller-owned ``Sequence``
        whose *container* is mutable whatever its (now-frozen) elements are — so
        the input clause survives here, exactly as ADR-0068 §4 states. The element
        rewrites the older form used (an id collision, a content edit) can no
        longer be made, but the caller can still grow the list while the write is
        suspended. The store must therefore rest its whole outcome on one
        observation of the batch: either it saw the two-element list, or it saw the
        three-element one, and what it commits matches what it returns — never a
        mix of the two observations.
        """
        async with self._observation_subject(store, vacuous=self.writes_without_suspending) as (
            subject,
            arm,
        ):
            gate = None if arm is None else arm("write_atomic")
            first = _semantic("obs-batch-1", "alpha alpha alpha")
            second = _semantic("obs-batch-2", "bravo bravo bravo")
            writes = [MemoryWrite(record=first), MemoryWrite(record=second)]
            before = {write.record.id for write in writes}
            third = MemoryWrite(record=_semantic("obs-batch-3", "delta delta delta"))
            async with _held_at_its_first_await(gate, subject.write_atomic(writes)) as call:
                writes.append(third)  # grow the caller's own list while the write is held
                after = {write.record.id for write in writes}
            returned = set(await call)

            committed = {record.id for record in await subject.export()}
            # One observation: what was returned is exactly what was committed, and
            # both correspond to a single reading of the caller's list.
            assert returned == committed, _TORN_INPUT
            assert committed in (before, after), _TORN_INPUT

    # The read side of the same clause (#436). The two cases below assert a
    # *stronger* thing than the two above, and the difference is worth stating
    # because it is not obvious from the clause's wording.
    #
    # A write derives several things from its argument — what it returns, what it
    # persists, what it indexes — so "one observation" is checkable by comparing
    # them, and either version may be the one observed: the cases above accept
    # ``before`` or ``after`` and reject a mix. A read derives *one* answer from
    # *one* filter. There is nothing to compare it against, so an implementation
    # that took its only observation late would return the later version's answer
    # whole — coherent, and invisible to a mix-detecting case. That is why an
    # earlier revision of this file recorded that no read-side clause was
    # available "in a weaker form".
    #
    # What makes them checkable is the *position* the clause fixes rather than the
    # coherence it guarantees. ADR-0065 §1 offers three discharges — do not
    # suspend, do not read the argument after suspending, snapshot on the
    # coroutine's first executed line — and every one of them yields the answer for
    # the filter **as it stood when the work began**. ADR-0073 §8 already required
    # exactly that of ``list_beliefs``, naming ``SqliteMemoryStore.search``'s
    # materialisation "after two suspension points" as the practice that did not
    # supply it. So these cases assert the pre-mutation answer, which is what the
    # ratified position amounts to observationally, and a store that reads its
    # filter only after suspending fails them.

    async def test_search_observes_its_kinds_filter_before_its_first_await(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``search``'s ``kinds`` (ADR-0065, #436).

        ``kinds`` is a caller-owned ``Sequence`` — the weaker of the two shapes
        ADR-0065's Context names, a mutable container of immutable elements: a
        re-read cannot tear a single value but it can change *which* values the
        call sees. Growing the list while the call is suspended must not widen the
        answer, because a conforming ``search`` has observed the filter before it
        suspended.

        Both seeded records match the query, so the filter is the only thing
        deciding the result and a late read is the only way the second one can
        appear in it.
        """
        async with self._observation_subject(store, vacuous=self.reads_without_suspending) as (
            subject,
            arm,
        ):
            await subject.add(_semantic("obs-search-s", "gamma gamma gamma"))
            await subject.add(_preference("obs-search-p", "gamma gamma gamma"))
            kinds = [MemoryKind.SEMANTIC]
            # Armed after the seeding writes, so the collaborator that stops the
            # read is not spent on a precondition.
            gate = None if arm is None else arm("search")
            async with _held_at_its_first_await(gate, subject.search("gamma", kinds=kinds)) as call:
                kinds.append(MemoryKind.PREFERENCE)  # grow the caller's own list mid-flight
            found = {record.id for record in await call}

            assert found == {"obs-search-s"}, _LATE_FILTER

    async def test_list_beliefs_observes_its_filters_before_its_first_await(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``list_beliefs`` (ADR-0065, ADR-0073 §8).

        ADR-0073 §8 states the obligation — materialise ``bands`` **and** ``kinds``
        before the first ``await`` — and records that the suite of the day could not
        prove it, because the suspension hook named only writes. It can now, so both
        filters are exercised: the two extra records are excluded one by each, so a
        store that re-read either one after suspending returns a wider page.
        """
        async with self._observation_subject(store, vacuous=self.reads_without_suspending) as (
            subject,
            arm,
        ):
            await subject.add(_semantic("obs-list-kept", "epsilon"))
            # Excluded by ``kinds`` alone, and by ``bands`` alone, respectively.
            await subject.add(_preference("obs-list-kind", "epsilon"))
            await subject.add(_semantic("obs-list-band", "epsilon", source=MemorySource.EXTERNAL))
            bands = [BeliefBand.DERIVED]
            kinds = [MemoryKind.SEMANTIC]
            gate = None if arm is None else arm("list_beliefs")
            async with _held_at_its_first_await(
                gate, subject.list_beliefs(bands=bands, kinds=kinds)
            ) as call:
                bands.append(BeliefBand.ATTESTED)
                kinds.append(MemoryKind.PREFERENCE)
            listed = {record.id for record in await call}

            assert listed == {"obs-list-kept"}, _LATE_FILTER
