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
from ai_assistant.testing.cancellation import held_at_its_first_await, settle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall, SuspendedMidWrite

    StoreFactory = Callable[[Callable[[], datetime]], MemoryStore]
from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    Attestation,
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
    WalkPosition,
    band_of,
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
    every other source in these cases wants a sub-1.0 figure. The attestation
    follows the *band* for the same reason (ADR-0092 §1): the ``ATTESTED`` band is
    unconstructable without one, and keying on the band rather than on ``EXTERNAL``
    covers a ``MemorySource`` added into it later without an edit here. No
    obligation in this suite reads it — a store keeps what it is given — so one
    value serves every case.
    """
    certain = source is MemorySource.USER_ASSERTED
    return Provenance(
        source=source,
        confidence=1.0 if certain else 0.6,
        last_updated=last_updated,
        attestation=(
            Attestation(reported_by="source-instance", reported_at=_REVISED)
            if band_of(source) is BeliefBand.ATTESTED
            else None
        ),
    )


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


#: Positions no chunk read could have issued, each reaching a different line of a
#: careless implementation (ADR-0114 §8). ``model_construct`` bypasses the model's
#: validator — that is what it is for — so each arrives with the declared type
#: satisfied, exactly as a real caller's mistake would; building them through
#: validation would test pydantic rather than the store. The list is exemplary and
#: the obligation is the general rule: a variant not named here is still refused.
#: ``S106`` reads ``token=`` as a credential; a walk position is an opaque cursor
#: into a row order, and ADR-0114 §2 declines to authenticate it at all.
_MALFORMED_POSITIONS: tuple[object, ...] = (
    WalkPosition.model_construct(token=""),
    WalkPosition.model_construct(token="   "),  # noqa: S106 — a row position, not a secret
    WalkPosition.model_construct(token="\ud800"),  # noqa: S106 — a row position, not a secret
    WalkPosition.model_construct(),
    "not-a-position",
    None,
)
_MALFORMED_POSITION_IDS = ("empty", "blank", "surrogate", "no-token", "wrong-type", "none")

#: A well-formed position for the cases where the *name* is what is under test, so
#: the refusal they assert cannot be the position's. Same ``S106`` note as above.
_ANY_POSITION = WalkPosition(token="anything")  # noqa: S106 — a row position, not a secret

#: An upper bound on chunk reads in a walk loop, so a store that fails to advance
#: fails an assertion rather than hanging the suite. Every walk case below holds
#: fewer than a dozen records, so reaching this bound is a defect by construction.
_WALK_ROUNDS = 50


async def _walk_to_exhaustion(store: MemoryStore, walk: str, *, limit: int) -> list[str]:
    """Walk ``walk`` to its end, advancing on each chunk, collecting ids in order.

    Advances **after** reading, which is the ordering ADR-0114 §3 obliges of every
    caller and the whole reason the read and the advance are two operations.
    """
    seen: list[str] = []
    for _ in range(_WALK_ROUNDS):
        chunk = await store.walk_records(walk, limit=limit)
        if chunk.position is None:
            return seen
        seen.extend(record.id for record in chunk.records)
        await store.advance_walk(walk, position=chunk.position)
    msg = f"walk {walk!r} did not exhaust in {_WALK_ROUNDS} chunks — the cursor is not advancing"
    raise AssertionError(msg)


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


class _WalkRecordsOp(_ReadOp):
    """``walk_records`` — ADR-0114's chunk read, its own lock site.

    In for :class:`_ListBeliefsOp`'s reason one contract on: the method holds the
    connection lock across its own ``_run_to_completion`` like every other read, so
    leaving it out would preserve exactly the gap #397 is about at the newest read
    on the surface.
    """

    name = "walk_records"

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Read one walk's chunk — the call that is cancelled."""
        return store.walk_records("cancel-a", limit=5)

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Read a second, independent walk's chunk concurrently."""
        return store.walk_records("cancel-b", limit=5)


class _AdvanceWalkOp:
    """``advance_walk`` — the cursor write, its own lock site.

    A write rather than a read, so it takes the write shape: two *independent*
    walks, so the concurrent second succeeds whatever the cancelled first's
    indeterminate effect turns out to be.
    """

    name = "advance_walk"

    def __init__(self) -> None:
        """Hold the two positions :meth:`prepare` mints, one per walk."""
        self._positions: dict[str, WalkPosition] = {}

    async def prepare(self, store: MemoryStore) -> None:
        """Seed a record and mint each walk its own position.

        Both are minted here rather than inside :meth:`second`, so each of the two
        calls the case drives enters the resource exactly **once** — the count the
        scenario asserts, and the reason this op cannot read its own position on
        the way past.
        """
        await store.add(_semantic("cancel-walk", "alpha"))
        for walk in ("cancel-a", "cancel-b"):
            chunk = await store.walk_records(walk, limit=5)
            assert chunk.position is not None
            self._positions[walk] = chunk.position

    def first(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Advance walk A — the call that is cancelled."""
        return store.advance_walk("cancel-a", position=self._positions["cancel-a"])

    def second(self, store: MemoryStore) -> Coroutine[Any, Any, object]:
        """Advance walk B concurrently, from a position of its own."""
        return store.advance_walk("cancel-b", position=self._positions["cancel-b"])

    async def verify(self, store: MemoryStore) -> None:
        """The store survived: the record is intact and walk B advanced whole."""
        assert await store.get("cancel-walk") is not None
        assert (await store.walk_records("cancel-b", limit=5)).position is None


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
    _WalkRecordsOp,
    _AdvanceWalkOp,
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
        # Upsert is a full replacement, not a merge: re-adding an id must leave no
        # trace of the previous record — not its content, not its subtype fields,
        # and not the columns a backend indexes *beside* the payload. Varying
        # `expires_at` and the validity window is what proves those columns are
        # rewritten and not merely the JSON blob: a store that rewrote only the
        # payload would keep the old retention deadline and closed window, and
        # `get` would then answer `None` for a record that is fully open.
        #
        # Same-kind, deliberately. The old form of this case proved the same thing
        # by re-adding at a *different* kind, which ADR-0108 §4 now refuses on every
        # upsert-capable door; the cross-kind collision has its own cases below.
        await store.add(
            _semantic(
                "1",
                "old semantic note",
                expires_at=_FAR_FUTURE,
                validity=Validity(valid_until=_FAR_FUTURE),
            )
        )
        replacement = _semantic("1", "new semantic note", last_updated=_LONG_AGO)
        await store.add(replacement)

        got = await store.get("1")
        assert got is not None
        assert got == replacement  # the whole record equals the second input
        assert got.expires_at is None  # the old deadline is gone, not merged
        assert got.validity.valid_until is None  # and so is the old window
        assert got.provenance.last_updated == _LONG_AGO

    async def test_add_at_a_different_kind_is_refused_and_changes_nothing(
        self, store: MemoryStore
    ) -> None:
        # ADR-0108 §4's backstop on `add`, the door whose default is the upsert. A
        # caller that means to install uses write_atomic/INSERT_IF_ABSENT (§1); this
        # is what catches the caller that wrongly reached for the upsert anyway, and
        # it is the one refusal that holds however wrong the declaration was.
        #
        # `MemoryStoreError` and not `MemoryStoreConflictError`: the latter's
        # documented remedy is "re-mint and retry", which does not answer a caller
        # that asked to overwrite something of a kind it did not expect.
        stored = _semantic("1", "the user drinks coffee")
        await store.add(stored)

        with pytest.raises(MemoryStoreError) as excinfo:
            await store.add(_preference("1", "prefers tea"))
        assert not isinstance(excinfo.value, MemoryStoreConflictError)

        assert await store.get("1") == stored  # nothing was written

    async def test_add_at_a_different_kind_collides_on_physical_presence(
        self, store: MemoryStore
    ) -> None:
        # Presence is physical, in `INSERT_IF_ABSENT`'s sense (ADR-0046 §3, ADR-0108
        # §4): a record hidden from every read still occupies its id. A store that
        # judged this on read-visibility would let an unreadable-but-retained
        # record be silently replaced by one of another kind, which is the loss the
        # rule exists to prevent — and retained history is exactly what is least
        # recoverable.
        retired = _semantic("1", "coffee", validity=Validity(valid_until=_LONG_AGO))
        await store.add(retired)
        assert await store.get("1") is None  # invisible to reads, still stored

        with pytest.raises(MemoryStoreError) as excinfo:
            await store.add(_preference("1", "prefers tea"))
        assert not isinstance(excinfo.value, MemoryStoreConflictError)

        assert list(await store.export()) == [retired]  # retained and unchanged

    async def test_upsert_at_a_different_kind_collides_on_physical_presence(
        self, store: MemoryStore
    ) -> None:
        # The same physical-presence rule on the *other* upsert-capable door. Its
        # own case rather than a parametrisation of the one above, because the two
        # doors reach the refusal by different routes and an implementation can get
        # one right and the other wrong — the divergence ADR-0046 §3 forbids,
        # arriving through a new rule.
        #
        # Window-closed, like the `add` case above and for the same reason
        # (ADR-0108 §5(a)): it is the only present-but-unreadable state `export`
        # still shows, so it is the only one that can witness "nothing is written"
        # alongside the refusal itself.
        retired = _semantic("1", "coffee", validity=Validity(valid_until=_LONG_AGO))
        await store.add(retired)
        assert await store.get("1") is None

        with pytest.raises(MemoryStoreError) as excinfo:
            await store.write_atomic(
                [MemoryWrite(record=_preference("1", "prefers tea"), mode=MemoryWriteMode.UPSERT)]
            )
        assert not isinstance(excinfo.value, MemoryStoreConflictError)

        assert list(await store.export()) == [retired]  # retained and unchanged

    @pytest.mark.parametrize("through_batch", [False, True], ids=["add", "write_atomic"])
    async def test_an_expired_row_still_occupies_its_id_against_a_cross_kind_write(
        self, store: MemoryStore, through_batch: bool
    ) -> None:
        # The second invisibility axis. Expiry and a closed window hide a row from
        # reads for different reasons — retention (ADR-0007) and truth (ADR-0045 §6)
        # — and physical presence is meant to be blind to both, so both are
        # exercised on both doors.
        #
        # This case proves **occupancy only**, and deliberately does not stand in
        # for the two above: `export` drops an expired record entirely, so once the
        # write is refused there is no contract-visible way to look at the row at
        # all, and an implementation that damaged it and *then* raised would pass
        # here. That is precisely why ADR-0108 §5(a) names the window-closed record
        # for the nothing-was-written half rather than offering a choice.
        incoming = _preference("1", "prefers tea")
        await store.add(_semantic("1", "coffee", expires_at=_LONG_AGO))
        assert await store.get("1") is None
        write = (
            store.write_atomic([MemoryWrite(record=incoming, mode=MemoryWriteMode.UPSERT)])
            if through_batch
            else store.add(incoming)
        )

        with pytest.raises(MemoryStoreError) as excinfo:
            await write
        assert not isinstance(excinfo.value, MemoryStoreConflictError)

        # The refusal is itself the occupancy evidence: the store could only have
        # learned the stored kind by finding a row under that id, which is what a
        # read-visibility rule would have failed to do.

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

    async def test_a_search_limit_wider_than_a_backing_store_can_bind_still_answers(
        self, store: MemoryStore
    ) -> None:
        """A ranking cut above any possible row count means "all of them", not an error.

        ``limit`` is a Python ``int`` and has no width, so ``2**63`` is a perfectly
        valid request. A backend that carries it into its query binds it as an
        integer parameter, and one that wide raises ``OverflowError`` out of the
        driver — neither ``ValueError`` nor ``MemoryStoreError``, so it leaves this
        seam's error boundary through a hole while every other clause here passes.

        **Clamped, where ``list_beliefs`` refuses — and this decides nothing, the
        ratified Protocol already did.** ``list_beliefs`` documents ``ValueError``
        outside ``[0, 2**63)`` and then names the exception in the same breath:
        that refusal "deliberately differs from ``search``, whose non-positive
        ``limit`` matches nothing: that limit is a ranking cut applied after a KNN
        and can neither invert into unboundedness nor reach a bind parameter".
        ``search``'s own ``Raises:`` documents no ``ValueError`` at all. So the
        contract as written already puts a wide positive ``limit`` on the served
        side of the line, and this pins that rather than adding to it.

        The clamp is where the mechanism catches up with the promise:
        ``SqliteMemoryStore._search_sync`` *does* carry ``limit`` into a bind
        parameter, as the KNN's ``k``, and clamps it to sqlite-vec's own ceiling —
        the lower of the two bounds, which subsumes the bind range (issue #115).
        Until now that was a property of one implementation and of nothing else
        (#679).
        """
        await store.add(_semantic("1", "coffee"))

        assert [record.id for record in await store.search("coffee", limit=2**63)] == ["1"]

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

    # --- the batch read: get_many (ADR-0086 §6) -------------------------------
    # One case per obligation. The suite asserts the **observable snapshot** and
    # stops there, deliberately: a conforming store may answer in one remote
    # request, one statement or one in-memory snapshot, so it has no per-chunk
    # boundary a portable test could inject a mutation at, and a case that raced a
    # writer against an in-flight call would be nondeterministic where it was not
    # simply testing SQLite. Demanding that boundary would also make one store's
    # chunking a universal obligation — the mechanism §6 says the contract is
    # explicitly *not*. ``SqliteMemoryStore``'s own suite carries the interleaving
    # case, where both the chunk boundary and the competing writer are controllable
    # and the result is deterministic (ADR-0086 §8).

    async def test_get_many_never_disagrees_with_get(self, store: MemoryStore) -> None:
        """The whole of §6's first obligation, over every read-time outcome.

        Asserted as an **equality against ``get``** rather than against a
        hand-written expectation, so the case cannot drift from the predicate it is
        about: whatever ``get`` decides for an id, ``get_many`` decides the same,
        and an id ``get`` answers ``None`` for is *omitted* rather than mapped to
        ``None``. All four outcomes a caller can reach are in the one call —
        readable, absent, expired, window-closed and not-yet-open — because a store
        that applied only some of its filters to the batch would pass a case that
        used one of them.
        """
        await store.add(_semantic("live", "alpha"))
        await store.add(_semantic("gone", "alpha", expires_at=_LONG_AGO))
        await store.add(_semantic("retired", "alpha", validity=Validity(valid_until=_LONG_AGO)))
        await store.add(_semantic("early", "alpha", validity=Validity(valid_from=_FAR_FUTURE)))
        asked = ["live", "gone", "retired", "early", "never-stored"]

        batch = await store.get_many(asked)

        singles = {}
        for record_id in asked:
            single = await store.get(record_id)
            if single is not None:
                singles[record_id] = single
        assert set(batch) == set(singles), (
            "get_many and get disagree about which ids are readable, so two reads of "
            "the same store answer differently about a record's liveness"
        )
        assert set(batch) == {"live"}, "the fixtures did not exercise every read-time outcome"
        assert batch["live"].id == "live"
        # An omission, never a `None` value: the mapping has no key at all for the
        # four ids `get` answered `None` for.
        assert all(value is not None for value in batch.values())

    async def test_get_many_of_nothing_is_an_empty_mapping(self, store: MemoryStore) -> None:
        """Asking for nothing is a question with an answer (§6).

        The same words ``list_beliefs``' ``limit=0`` and ``write_atomic``'s empty
        batch already use. Seeded first, so an implementation that ignored its
        argument and returned everything would fail rather than return ``{}`` for
        an empty store either way.
        """
        await store.add(_semantic("stored", "alpha"))

        assert await store.get_many([]) == {}

    async def test_get_many_collapses_duplicate_ids(self, store: MemoryStore) -> None:
        """A mapping, so duplicates collapse and never multiply the result (§6).

        The count is what carries this: a mapping cannot hold one key twice, so the
        assertion that would fail on a store returning a positional result is the
        one about *length* relative to the argument's.
        """
        await store.add(_semantic("dup", "alpha"))
        await store.add(_semantic("other", "alpha"))

        batch = await store.get_many(["dup", "dup", "other", "dup"])

        assert set(batch) == {"dup", "other"}
        assert len(batch) < len(["dup", "dup", "other", "dup"])

    async def test_get_many_returns_detached_snapshots(self, store: MemoryStore) -> None:
        """Records are detached snapshots, like every other ``MemoryStore`` read (§6).

        Frozen under ADR-0068, so the property is asserted the way
        ``test_stored_records_cannot_be_mutated_by_the_caller`` asserts it for
        ``get``: the returned object refuses mutation, and the stored record is
        unaffected either way.
        """
        await store.add(_semantic("snap", "alpha", validity=Validity(valid_until=_FAR_FUTURE)))

        batch = await store.get_many(["snap"])

        with pytest.raises(ValidationError):
            batch["snap"].validity.valid_until = _LONG_AGO
        assert await store.get("snap") is not None

    async def test_get_many_judges_every_id_against_one_clock_reading(
        self, store_factory: StoreFactory
    ) -> None:
        """§6's snapshot clause, on the axis a portable test can reach.

        The point of the batch: resolving *k* citations through *k* ``get``s judges
        them against *k* instants, so one can expire mid-resolution and a belief's
        rendered count disagree with its own tombstones. Every record here falls due
        after the first reading and before the second, so a store re-reading an
        advancing clock per id retires everything after the first and this fails —
        which is exactly the loop-of-singles implementation §6 forbids, seen from
        outside. The clause about the *stored state* is the other half of the same
        snapshot and is pinned where a chunk boundary exists to interleave at
        (``tests/memory/test_sqlite_store.py``, ADR-0086 §8).
        """
        step = timedelta(hours=1)
        state = {"now": _STORE_NOW}

        def advancing() -> datetime:
            reading = state["now"]
            state["now"] = reading + step
            return reading

        store = store_factory(advancing)
        deadline = _STORE_NOW + step // 2
        wanted = [f"b{i}" for i in range(3)]
        for record_id in wanted:
            await store.add(_semantic(record_id, "alpha", validity=Validity(valid_until=deadline)))

        batch = await store.get_many(wanted)

        assert set(batch) == set(wanted), (
            "the batch judged its ids against more than one instant, so two entries "
            "in one result disagree about when 'now' was"
        )

    async def test_a_record_over_the_evidence_bound_stays_readable(
        self, store: MemoryStore
    ) -> None:
        """ADR-0086 §2's residue, pinned on the read path where it would be broken.

        The bound is a ``MemoryWriter`` obligation and deliberately **not** a
        ``Provenance`` validator, and this is the property that placement buys: a
        deployment that accumulated a belief above the bound before the rule landed
        keeps it, readable, through **every** read. A store decoding through the
        model — which the persistent one does on every read — would start failing
        on exactly those records the day a ``max_length`` appeared, so this is the
        case a validator-based implementation cannot pass however correctly its
        writer truncates.

        Every read is exercised, because they decode by different paths and a bound
        on the type would break them one at a time.
        """
        over_bound = tuple(f"legacy-ev-{index:03d}" for index in range(MAX_EVIDENCE_CITATIONS + 16))
        legacy = SemanticMemory(
            id="legacy",
            content="a belief accumulated before the bound landed",
            fact="a belief accumulated before the bound landed",
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.6,
                last_updated=_REVISED,
                evidence=over_bound,
                evidence_elided=3,
            ),
        )

        await store.add(legacy)

        got = await store.get("legacy")
        assert got is not None
        assert got.provenance.evidence == over_bound
        assert got.provenance.evidence_elided == 3
        assert set(await store.get_many(["legacy"])) == {"legacy"}
        assert "legacy" in {record.id for record in await store.list_beliefs()}
        assert "legacy" in {record.id for record in await store.export()}
        assert "legacy" in {record.id for record in await store.search("accumulated")}

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
        # does — and it is a full replacement, so the retention deadline and the
        # window the previous record carried are gone rather than merged.
        #
        # Same-kind, deliberately: ADR-0108 §4 refuses a cross-kind UPSERT on this
        # door too, which is the next case.
        await store.add(
            _semantic(
                "1",
                "old semantic note",
                expires_at=_FAR_FUTURE,
                validity=Validity(valid_until=_FAR_FUTURE),
            )
        )
        replacement = _semantic("1", "new semantic note", last_updated=_LONG_AGO)

        await store.write_atomic([MemoryWrite(record=replacement, mode=MemoryWriteMode.UPSERT)])

        got = await store.get("1")
        assert got is not None
        assert got == replacement
        assert got.expires_at is None
        assert got.validity.valid_until is None

    async def test_write_atomic_upsert_at_a_different_kind_fails_the_whole_batch(
        self, store: MemoryStore
    ) -> None:
        # ADR-0108 §4 binds `write_atomic`'s UPSERT as well as `add`, because
        # `write_atomic` is a **second door** into the store: a rule stated only on
        # `add` would read as protection while leaving the door every ingestor write
        # now uses wide open. And the refusal is an element failure like any other,
        # so ADR-0046 §4's all-or-nothing rule carries it — the *other*, entirely
        # valid element of the batch is not committed either.
        stored = _semantic("collide", "the user drinks coffee")
        await store.add(stored)
        innocent = _semantic("fresh", "the user cycles to work")

        with pytest.raises(MemoryStoreError) as excinfo:
            await store.write_atomic(
                [
                    MemoryWrite(record=innocent, mode=MemoryWriteMode.INSERT_IF_ABSENT),
                    MemoryWrite(
                        record=_preference("collide", "prefers tea"),
                        mode=MemoryWriteMode.UPSERT,
                    ),
                ]
            )
        assert not isinstance(excinfo.value, MemoryStoreConflictError)

        assert await store.get("collide") == stored
        assert await store.get("fresh") is None  # nothing in the batch landed

    async def test_write_atomic_insert_if_absent_at_a_different_kind_is_still_a_conflict(
        self, store: MemoryStore
    ) -> None:
        # The existing rule wins on this door, and keeps its narrower remedy.
        # INSERT_IF_ABSENT refuses *every* collision and refuses it earlier, so a
        # cross-kind one never reaches ADR-0108 §4's check: the caller minted a
        # colliding id and "re-mint and retry" is exactly the right advice, which is
        # what `MemoryStoreConflictError` means and `MemoryStoreError` does not.
        stored = _semantic("1", "the user drinks coffee")
        await store.add(stored)

        with pytest.raises(MemoryStoreConflictError):
            await store.write_atomic(
                [
                    MemoryWrite(
                        record=_preference("1", "prefers tea"),
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    )
                ]
            )

        assert await store.get("1") == stored

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
            async with held_at_its_first_await(gate, subject.add(record)) as call:
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
            async with held_at_its_first_await(gate, subject.write_atomic(writes)) as call:
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
            async with held_at_its_first_await(gate, subject.search("gamma", kinds=kinds)) as call:
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
            async with held_at_its_first_await(
                gate, subject.list_beliefs(bands=bands, kinds=kinds)
            ) as call:
                bands.append(BeliefBand.ATTESTED)
                kinds.append(MemoryKind.PREFERENCE)
            listed = {record.id for record in await call}

            assert listed == {"obs-list-kept"}, _LATE_FILTER

    async def test_get_many_observes_its_record_ids_before_its_first_await(
        self, store: MemoryStore
    ) -> None:
        """``core.protocols``' input clause, on ``get_many``'s ``record_ids`` (ADR-0086 §8).

        A second ``Sequence`` argument on this Protocol, so it gets the case
        ``write_atomic``'s already has, or the clause is declared and unenforced.
        It needs its own: none of ``get_many``'s other obligations mutates the
        sequence mid-call, so an implementation that took its lock first and
        materialised the argument afterwards would satisfy every one of them — the
        snapshot, the agreement with ``get``, the collapsed duplicates — while
        answering a later version of the caller's input. Growing the caller's own
        list while the call is suspended must not widen the mapping.

        The second id is stored and readable, so the filter is the only thing
        keeping it out and a late read is the only way it can appear.
        """
        async with self._observation_subject(store, vacuous=self.reads_without_suspending) as (
            subject,
            arm,
        ):
            await subject.add(_semantic("obs-batch-asked", "zeta"))
            await subject.add(_semantic("obs-batch-added", "zeta"))
            record_ids = ["obs-batch-asked"]
            gate = None if arm is None else arm("get_many")
            async with held_at_its_first_await(gate, subject.get_many(record_ids)) as call:
                record_ids.append("obs-batch-added")  # grow the caller's own list mid-flight
            resolved = set(await call)

            assert resolved == {"obs-batch-asked"}, _LATE_FILTER

    # --- the resumable walk (ADR-0114 §8) ------------------------------------
    # Each clause below names the case that can fail, because each has a wrong
    # implementation the neighbouring test waves through. A suite that only walks
    # a store nobody writes to passes an offset masquerading as a position, which
    # is the single defect ADR-0111 §2 spends its longest paragraph on; one that
    # never hands the store an unusable position passes an implementation that
    # raises, which under ADR-0111 §7 would take the hub down over scaffolding.

    async def record_unusable_walk_position(self, store: MemoryStore, walk: str) -> None:
        """Record a position this build cannot use, however this store records one.

        Overridden by every concrete subclass, because *how* a position is stored
        is each implementation's and the contract deliberately says nothing about
        it. The obligation the hook serves is universal — ADR-0114 §4 requires
        discard-and-restart rather than a raise — and it is unreachable from the
        outside, since every position the Protocol hands out is by construction a
        usable one.
        """
        raise NotImplementedError

    async def test_a_walk_with_no_recorded_position_starts_at_the_first_record(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §4: no recorded position means the walk has not started.

        Never a sentinel — there is no integer below the order's floor, and the
        obvious choice silently skips every record at or below it (ADR-0104 §2).
        """
        await store.add(_semantic("w-first", "alpha"))
        await store.add(_semantic("w-second", "bravo"))

        chunk = await store.walk_records("fresh", limit=10)

        assert [record.id for record in chunk.records] == ["w-first", "w-second"]

    async def test_reading_a_chunk_twice_without_advancing_returns_the_same_records(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1: the chunk read writes nothing.

        Fails an implementation that advances as it reads — the convenient shape,
        and the one that puts the cursor permanently ahead of the caller's effects
        in the direction ADR-0111 §3 forbids.
        """
        await store.add(_semantic("w-a", "alpha"))
        await store.add(_semantic("w-b", "bravo"))

        first = await store.walk_records("twice", limit=1)
        second = await store.walk_records("twice", limit=1)

        assert [r.id for r in first.records] == [r.id for r in second.records] == ["w-a"]
        assert first.position == second.position

    async def test_advancing_moves_the_walk_to_the_following_records(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1, §3: a walk resumes strictly after the recorded position."""
        for index in range(4):
            await store.add(_semantic(f"w-{index}", "alpha"))

        first = await store.walk_records("forward", limit=2)
        assert first.position is not None
        await store.advance_walk("forward", position=first.position)
        second = await store.walk_records("forward", limit=2)

        assert [r.id for r in first.records] == ["w-0", "w-1"]
        assert [r.id for r in second.records] == ["w-2", "w-3"]

    async def test_a_walk_reaches_every_record_exactly_once(self, store: MemoryStore) -> None:
        """ADR-0114 §1: the order is total, and no chunk repeats another's record."""
        expected = [f"w-{index:02d}" for index in range(7)]
        for record_id in expected:
            await store.add(_semantic(record_id, "alpha"))

        seen = await _walk_to_exhaustion(store, "once", limit=2)

        assert seen == expected

    async def test_advancing_to_a_position_at_or_behind_the_recorded_one_is_a_no_op(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §3: the cursor never moves backwards, and that is not an error.

        A walk is at-least-once, so a resumed run can legitimately hold a stale
        position. Under this clause the worst outcome is repeated work; without it
        the worst outcome is a walk rewound past records the *next* advance skips
        forever, and the two costs are not comparable.
        """
        for index in range(4):
            await store.add(_semantic(f"w-{index}", "alpha"))
        first = await store.walk_records("backwards", limit=1)
        assert first.position is not None
        await store.advance_walk("backwards", position=first.position)
        second = await store.walk_records("backwards", limit=1)
        assert second.position is not None
        await store.advance_walk("backwards", position=second.position)

        await store.advance_walk("backwards", position=first.position)  # behind
        await store.advance_walk("backwards", position=second.position)  # equal

        resumed = await store.walk_records("backwards", limit=1)
        assert [r.id for r in resumed.records] == ["w-2"]

    async def test_two_walk_names_hold_independent_positions(self, store: MemoryStore) -> None:
        """ADR-0114 §5: a position is per walk name, and names are never merged.

        Two names differing only in case are two walks: a store that quietly
        normalised them would merge two jobs' positions and skip records for one.
        """
        for index in range(3):
            await store.add(_semantic(f"w-{index}", "alpha"))
        chunk = await store.walk_records("Job", limit=2)
        assert chunk.position is not None
        await store.advance_walk("Job", position=chunk.position)

        advanced = await store.walk_records("Job", limit=3)
        untouched = await store.walk_records("job", limit=3)

        assert [r.id for r in advanced.records] == ["w-2"]
        assert [r.id for r in untouched.records] == ["w-0", "w-1", "w-2"]

    async def test_a_chunk_carries_no_position_exactly_when_it_examined_nothing(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1: an absent position is the exhaustion signal, not an empty list."""
        empty = await store.walk_records("exhaustion", limit=5)
        assert empty.position is None
        assert empty.records == ()

        await store.add(_semantic("w-only", "alpha"))
        held = await store.walk_records("exhaustion", limit=5)
        assert held.position is not None
        await store.advance_walk("exhaustion", position=held.position)

        assert (await store.walk_records("exhaustion", limit=5)).position is None

    async def test_clear_leaves_no_walk_resumable(self, store: MemoryStore) -> None:
        """ADR-0114 §4: ``clear`` discards every recorded position with the records.

        Leaving them produces exactly the cursor-disagrees-with-store state
        ADR-0111 §7 has to detect, and not creating it beats detecting it.
        """
        for index in range(3):
            await store.add(_semantic(f"w-{index}", "alpha"))
        chunk = await store.walk_records("cleared", limit=2)
        assert chunk.position is not None
        await store.advance_walk("cleared", position=chunk.position)

        await store.clear()
        await store.add(_semantic("w-after", "alpha"))

        resumed = await store.walk_records("cleared", limit=5)
        assert [r.id for r in resumed.records] == ["w-after"]

    async def test_clear_does_not_reset_the_key_sequence(self, store: MemoryStore) -> None:
        """ADR-0114 §4, §8: a ``clear`` must not rewind the high-water mark.

        The half that makes an in-flight walk safe across a ``clear``. A walker
        holding a chunk's position when another caller empties the store will
        advance to a position ``clear`` already discarded, and nothing compares
        against it because the walk now has none — harmless *only* because every
        record added afterwards is issued a key above it. An implementation that
        reset its mark passes every other clause here and fails this one, leaving
        that stale position sitting above live records no walk would read again.
        """
        for index in range(3):
            await store.add(_semantic(f"w-{index}", "alpha"))
        held = await store.walk_records("survivor", limit=3)
        assert held.position is not None

        await store.clear()
        await store.add(_semantic("w-post-clear", "alpha"))
        await store.advance_walk("survivor", position=held.position)  # the stale advance

        resumed = await store.walk_records("survivor", limit=5)
        assert [r.id for r in resumed.records] == ["w-post-clear"]

    async def record_walk_position_beyond_the_store(self, store: MemoryStore, walk: str) -> None:
        """Record a well-formed position above every key this store has issued.

        A second hook beside :meth:`record_unusable_walk_position`, because the two
        are different failures and only one of them looks broken. A malformed
        position is obviously unusable; a *number* beyond the high-water mark is
        well-formed, parses, compares, and is unreachable forever — which is why it
        needs its own case and its own way in. Unreachable through the Protocol by
        construction: a position is only ever issued for a record that was examined.
        """
        raise NotImplementedError

    async def test_a_walk_restarts_rather_than_raising_on_a_position_beyond_the_store(
        self, store: MemoryStore
    ) -> None:
        """ADR-0111 §7: nothing may resume from a position the contents do not support.

        The dangerous half of ADR-0114 §4's discard rule, and the one a suite that
        only plants *malformed* text never reaches. A number above every key the
        store has ever issued names a range no record can ever occupy — §1's
        guarantee is that each new key exceeds every key already issued — so the
        walk answers "nothing left to examine" on every run while the store fills
        up behind it. That is the silent skip the whole contract exists to prevent,
        arriving through the cursor itself, and it reports success while it happens.

        Records added *after* the bad position is planted are the assertion that
        matters: a store that merely restarted once would pass a weaker check.
        """
        await store.add(_semantic("w-a", "alpha"))
        await store.add(_semantic("w-b", "bravo"))
        await self.record_walk_position_beyond_the_store(store, "beyond")

        first = await store.walk_records("beyond", limit=5)
        await store.add(_semantic("w-c", "charlie"))
        second = await store.walk_records("beyond", limit=5)

        assert [record.id for record in first.records] == ["w-a", "w-b"]
        assert [record.id for record in second.records] == ["w-a", "w-b", "w-c"]

    async def test_a_position_above_the_records_present_is_kept_not_discarded(
        self, store: MemoryStore
    ) -> None:
        """The other side of that rule, and the reason it is keyed on the high-water mark.

        Walking to the end and then deleting the top records leaves a position above
        everything the store now holds, and that position is **good**: ADR-0114 §2
        makes it a bound rather than a reference, and §1's never-reissued key is what
        puts the next record above it. An implementation that ceilinged on the keys
        *present* would pass the case above and rewind this walk, re-reading every
        surviving record — at-least-once, so not unsafe, but it would make a delete
        silently undo a walk's progress.
        """
        for index in range(3):
            await store.add(_semantic(f"w-{index}", "alpha"))
        assert await _walk_to_exhaustion(store, "kept", limit=5) == ["w-0", "w-1", "w-2"]
        assert await store.delete("w-2") is True
        assert await store.delete("w-1") is True

        await store.add(_semantic("w-new", "alpha"))

        resumed = await store.walk_records("kept", limit=5)
        assert [record.id for record in resumed.records] == ["w-new"]

    async def test_the_chunk_read_stops_at_its_limit_rather_than_scanning_the_tail(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1: the read's work is bounded by ``limit``, not by what remains.

        Asserted on the *position* rather than by timing, which is what makes it a
        contract case rather than a benchmark: a read that stopped after ``limit``
        records carries the position of the ``limit``-th, and one that walked further
        — to sort the tail, or to fill a chunk — would carry a later one. An
        implementation that materialises every unwalked record before slicing passes
        every other clause here and makes one chunk's cost a function of the whole
        store, which is the unbounded chunk ADR-0111 §4 forbids.
        """
        for index in range(20):
            await store.add(_semantic(f"w-{index:02d}", "alpha"))

        chunk = await store.walk_records("bounded-tail", limit=1)
        assert chunk.position is not None
        await store.advance_walk("bounded-tail", position=chunk.position)

        assert [record.id for record in chunk.records] == ["w-00"]
        # The position is the first record's, so the read stopped there: had it
        # examined the tail, the position it carried would be a later record's.
        assert [r.id for r in (await store.walk_records("bounded-tail", limit=1)).records] == [
            "w-01"
        ]

    async def test_a_walk_restarts_rather_than_raising_on_an_unusable_position(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §4, §8: an unusable cursor is discarded, never a state fault.

        Fails an implementation that treats one as a fault, which under ADR-0111
        §7 would take a resident process down over scaffolding — a cursor holds no
        evidence and answers no query, so discarding one returns nothing wrong to
        any client.
        """
        await store.add(_semantic("w-a", "alpha"))
        await store.add(_semantic("w-b", "bravo"))
        await self.record_unusable_walk_position(store, "damaged")

        chunk = await store.walk_records("damaged", limit=5)

        assert [r.id for r in chunk.records] == ["w-a", "w-b"]

    async def test_a_record_added_mid_walk_is_reached_without_shifting_the_position(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §8: fails an implementation that records an offset and calls it a position.

        An offset is a count into a result set, so a record inserted below it moves
        every later record's number — the defect ADR-0111 §2 spends its longest
        paragraph on, and one a suite that only walks a static store never sees.
        """
        await store.add(_semantic("w-0", "alpha"))
        await store.add(_semantic("w-1", "alpha"))
        chunk = await store.walk_records("growing", limit=2)
        assert chunk.position is not None
        await store.advance_walk("growing", position=chunk.position)

        await store.add(_semantic("w-2", "alpha"))

        assert [r.id for r in (await store.walk_records("growing", limit=5)).records] == ["w-2"]

    async def test_a_key_is_never_reissued_after_a_delete(self, store: MemoryStore) -> None:
        """ADR-0114 §1, §8: the sequence that breaks a merely-unique key.

        Walk to the end, delete the record holding the highest position, add
        another, and the walk must reach it. A bare SQLite ``rowid`` releases the
        deleted number to the next insert, so the new record is issued a position
        the walk has already passed, never returned, and never mentioned — the
        silent skip arriving through the one axis ADR-0111 §2 named as safe.
        """
        await store.add(_semantic("w-0", "alpha"))
        await store.add(_semantic("w-top", "alpha"))
        assert await _walk_to_exhaustion(store, "reissue", limit=5) == ["w-0", "w-top"]

        assert await store.delete("w-top") is True
        await store.add(_semantic("w-new", "alpha"))

        assert [r.id for r in (await store.walk_records("reissue", limit=5)).records] == ["w-new"]

    async def test_a_key_is_never_reissued_after_a_purge(self, store: MemoryStore) -> None:
        """ADR-0114 §8: the same sequence reached through ``purge_expired``.

        Run for its own door because ``purge_expired`` reclaims rows on a path
        ``delete`` does not, and a store that got one right can get the other
        wrong. Letting the newest expiring record be reclaimed is ordinary rather
        than exotic, which is why the clause names both.
        """
        await store.add(_semantic("w-0", "alpha"))
        await store.add(_semantic("w-top", "alpha", expires_at=_LONG_AGO))
        assert await _walk_to_exhaustion(store, "purged", limit=5) == ["w-0"]

        assert await store.purge_expired() == 1
        await store.add(_semantic("w-new", "alpha"))

        assert [r.id for r in (await store.walk_records("purged", limit=5)).records] == ["w-new"]

    async def test_the_walk_never_yields_an_expired_record(self, store: MemoryStore) -> None:
        """ADR-0114 §1: retention binds the walk exactly as it binds ``get``/``search``.

        Otherwise this is the one read in the store that breaches retention, and
        it hands expired content to a producer that writes a *new* durable belief
        from it (ADR-0045 §6).
        """
        await store.add(_semantic("w-gone", "alpha", expires_at=_LONG_AGO))
        await store.add(_semantic("w-live", "alpha"))

        chunk = await store.walk_records("retained", limit=5)

        assert [r.id for r in chunk.records] == ["w-live"]

    async def test_the_walk_never_yields_a_record_outside_its_validity_window(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1: both ends of the window, as ``get`` and ``search`` enforce them.

        A window-closed record is a belief the user has already corrected; a
        not-yet-open one is not yet believed. Handing either to a consolidator
        resurrects retired content through the one door nobody was watching.
        """
        await store.add(_semantic("w-closed", "alpha", validity=Validity(valid_until=_LONG_AGO)))
        await store.add(_semantic("w-unopened", "alpha", validity=Validity(valid_from=_FAR_FUTURE)))
        await store.add(_semantic("w-live", "alpha"))

        chunk = await store.walk_records("windowed", limit=5)

        assert [r.id for r in chunk.records] == ["w-live"]

    async def test_a_wholly_ineligible_stretch_yields_a_chunk_that_still_carries_a_position(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §8: a dead range advances rather than stalling the walk for good.

        Fails an implementation that returns no position for a range holding
        nothing eligible: a caller reading that as exhaustion stops short forever,
        and one that re-read without advancing would rescan the range every run.
        """
        for index in range(3):
            await store.add(_semantic(f"w-dead-{index}", "alpha", expires_at=_LONG_AGO))
        await store.add(_semantic("w-live", "alpha"))

        dead = await store.walk_records("deadrange", limit=3)
        assert dead.records == ()
        assert dead.position is not None
        await store.advance_walk("deadrange", position=dead.position)

        beyond = await store.walk_records("deadrange", limit=3)
        assert [r.id for r in beyond.records] == ["w-live"]

    async def test_the_chunk_bound_counts_records_examined_not_records_returned(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §1, §8: the bound is on examination, which ADR-0111 §4 forces.

        An implementation that scanned on until it had ``limit`` *eligible*
        records passes every other clause here and has no bound at all: ``limit=1``
        over an all-ineligible tail scans to the end of the store, holding the
        serial loop for as long as that takes with no figure in ``Settings`` that
        would say so.
        """
        for index in range(5):
            await store.add(_semantic(f"w-dead-{index}", "alpha", expires_at=_LONG_AGO))
        await store.add(_semantic("w-live", "alpha"))

        chunks = 0
        seen: list[str] = []
        for _ in range(_WALK_ROUNDS):
            chunk = await store.walk_records("bounded", limit=2)
            if chunk.position is None:
                break
            chunks += 1
            seen.extend(record.id for record in chunk.records)
            await store.advance_walk("bounded", position=chunk.position)

        # Six records, two examined per chunk: three chunks, never one long scan.
        assert chunks == 3
        assert seen == ["w-live"]

    @pytest.mark.parametrize("walk", ["", "   ", "\ud800"], ids=["empty", "blank", "surrogate"])
    async def test_both_walk_operations_refuse_an_inadmissible_name(
        self, store: MemoryStore, walk: str
    ) -> None:
        """ADR-0114 §5, §6a: the same ``ValueError`` on every backend, from both doors.

        Called directly rather than through a validated model, which is how every
        caller reaches it: these aliases are pydantic validators and Python runs
        nothing for an ordinary method call, so the entry check is the whole of the
        enforcement. Without it SQLite raises out of its driver on a lone surrogate
        while an in-memory store accepts it happily.
        """
        with pytest.raises(ValueError, match="walk name"):
            await store.walk_records(walk, limit=5)
        with pytest.raises(ValueError, match="walk name"):
            await store.advance_walk(walk, position=_ANY_POSITION)

    @pytest.mark.parametrize(
        "limit",
        [-1, 0, 2**63, True, 1.5, "5", None],
        ids=["negative", "zero", "over-wide", "bool", "float", "str", "none"],
    )
    async def test_the_chunk_read_refuses_an_inadmissible_limit(
        self, store: MemoryStore, limit: object
    ) -> None:
        """ADR-0114 §6, §6a: exactly an ``int`` in ``[1, 2**63)``, refused not clamped.

        Run against a **non-empty, unexhausted** walk, because that is what makes
        the zero case able to fail: a chunk that examines nothing carries no
        position, and an absent position *means the walk is exhausted*, so a store
        that accepted ``limit=0`` would answer with the exact shape telling a
        caller its walk was finished having read nothing at all.

        ``True`` is the case that matters most and the one a reader would not think
        to write: ``bool`` is an ``int`` subclass, so it satisfies every range
        comparison and would quietly become a one-record chunk. ``-1`` is not
        symmetric with the over-wide end and only one of them looks dangerous —
        SQLite reads ``LIMIT -1`` as *no limit*, so a forwarded argument returns
        the whole store from inside a job whose entire purpose is to be bounded.
        """
        await store.add(_semantic("w-present", "alpha"))

        with pytest.raises(ValueError, match="limit"):
            await store.walk_records("bounds", limit=limit)  # type: ignore[arg-type] # the point

    async def test_the_advance_refuses_another_walks_position_and_changes_nothing(
        self, store: MemoryStore
    ) -> None:
        """ADR-0114 §2, §8: the cross-walk refusal, as *no observable change at all*.

        Run against a walk that **already holds a position**, and asserted on the
        next chunk rather than on the recorded position, because the two weaker
        forms each pass a real defect. Against a fresh ``B`` the case cannot fail
        at all — ``B`` has no position to lose. Asserting only that ``B`` resumes
        *after* its prior position passes an implementation that writes ``A``'s
        position and then raises, since a cursor dragged from 20 to 50 is still
        strictly after 20 while positions 21-50 are gone.
        """
        for index in range(6):
            await store.add(_semantic(f"w-{index}", "alpha"))
        far = await store.walk_records("A", limit=5)
        assert far.position is not None
        await store.advance_walk("A", position=far.position)
        near = await store.walk_records("B", limit=1)
        assert near.position is not None
        await store.advance_walk("B", position=near.position)
        kept = await store.walk_records("B", limit=2)

        with pytest.raises(ValueError, match="issued for walk"):
            await store.advance_walk("B", position=far.position)

        assert await store.walk_records("B", limit=2) == kept

    @pytest.mark.parametrize("position", _MALFORMED_POSITIONS, ids=_MALFORMED_POSITION_IDS)
    async def test_the_advance_refuses_an_invalid_position_and_disturbs_no_walk(
        self, store: MemoryStore, position: object
    ) -> None:
        """ADR-0114 §6a, §8: general over malformation, and every recorded position survives.

        ``model_construct`` bypasses the model's validator — that is what it is for
        — so each of these reaches the store with the declared type satisfied,
        exactly as a real caller's mistake would; building the position through
        validation would test pydantic rather than the store. Each shape reaches a
        different line of a careless implementation: reading ``position.token``
        before validating raises ``AttributeError``, and an ``isinstance``-then-read
        guard passes every case whose token merely has the wrong *value*. Those are
        breaches of §6a rather than variants of it, which is why the assertion is
        on ``ValueError`` and nothing wider.

        **A second, independently progressed walk is watched alongside**, because
        §6a says *every* recorded position survives a refusal and a test watching
        only the named walk passes an implementation that disturbs a sibling's.
        """
        for index in range(6):
            await store.add(_semantic(f"w-{index}", "alpha"))
        for name, size in (("named", 2), ("sibling", 3)):
            chunk = await store.walk_records(name, limit=size)
            assert chunk.position is not None
            await store.advance_walk(name, position=chunk.position)
        kept_named = await store.walk_records("named", limit=9)
        kept_sibling = await store.walk_records("sibling", limit=9)

        with pytest.raises(ValueError):  # noqa: PT011 — the class is the obligation
            await store.advance_walk("named", position=position)  # type: ignore[arg-type] # the point

        assert await store.walk_records("named", limit=9) == kept_named
        assert await store.walk_records("sibling", limit=9) == kept_sibling
