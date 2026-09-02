"""The canonical FakeMemoryStore passes the shared MemoryStore conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryStore``
as a stand-in for a real store: it is held to the same contract as
``InMemoryMemoryStore`` and ``SqliteMemoryStore``.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from memory_store_contract import _BEYOND_MARGIN, MemoryStoreContract
from pydantic import ValidationError

from ai_assistant.core.errors import MemoryStoreError, MemoryStoreStaleError
from ai_assistant.core.types import (
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.cancellation import SuspendedMidWrite
from ai_assistant.testing.memory import _mint_position

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.testing.cancellation import SuspendedCall


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _semantic(record_id: str, content: str) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=_fixed_now()
        ),
    )


async def test_an_absent_rows_refusal_says_no_record_is_stored_under_that_id() -> None:
    """ADR-0219 §3's third fact, on ``FakeMemoryStore``'s own wording.

    §3 requires the refusal to name "what the store found — the stored revision, or
    that the id named nothing", and ``MemoryStoreContract``'s two message arms hold
    every implementation to everything about that which is wording-free: the id, the
    expectation, no revision the store could not have found, and the two limbs
    reading differently. What they deliberately do **not** carry is a vocabulary for
    absence — §3 declares none, so a shared suite reading for one would fail a
    conforming store whose spelling it had not anticipated.

    A store's own sentence is a property of that store, so it is pinned here, where
    this backend's other own properties are. Without it every assertion in the suite
    is satisfied by "…at revision 1: stale request", which names both other facts and
    leaves an operator unable to tell the missing row from the moved one (#1835).
    """
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_semantic("vanished", "the version the caller read"))
    read = await store.get("vanished")
    assert read is not None
    assert await store.delete("vanished") is True

    with pytest.raises(MemoryStoreStaleError) as absent:
        await store.write_atomic(
            [
                MemoryWrite(
                    record=_semantic("vanished", "computed over a record that is gone"),
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=read.revision,
                )
            ]
        )

    assert "no record is stored under that id" in str(absent.value)


class TestFakeMemoryStoreContract(MemoryStoreContract):
    """Runs FakeMemoryStore through the shared MemoryStore conformance suite."""

    # No ``reads_without_suspending`` opt-out. It was here while the fake's reads
    # touched a dict and returned, with no ``await`` for a mid-flight mutation to
    # land in (#436). Routing the reads through the modelled resource for ADR-0060
    # (#397) gives them a real suspension point — and one in the right place, since
    # both filters are materialised on the coroutine's first executed line and the
    # resource is entered only afterwards. So the read-side input-observation cases
    # now run non-vacuously here as well as against ``SqliteMemoryStore``, and a
    # fake that started reading its filters late would fail them.

    @pytest.fixture
    def store(self) -> MemoryStore:
        return FakeMemoryStore(now=_fixed_now)

    async def record_unusable_walk_position(self, store: MemoryStore, walk: str) -> None:
        """Park text this build cannot read where the fake keeps its positions.

        Reaches past the Protocol on purpose: every position the contract hands
        out is by construction a usable one, so the only way to exercise ADR-0114
        §4's discard-and-restart is to plant an unusable one the way a older or
        newer build would have left it behind.
        """
        assert isinstance(store, FakeMemoryStore)
        store._walks[walk] = "written-by-a-build-that-is-not-this-one"

    async def record_walk_position_beyond_the_store(self, store: MemoryStore, walk: str) -> None:
        """Park a number above this fake's own issued-key counter."""
        assert isinstance(store, FakeMemoryStore)
        store._walks[walk] = _mint_position(walk, store._sequence + _BEYOND_MARGIN).token

    @pytest.fixture
    def store_factory(self) -> Callable[[Callable[[], datetime]], MemoryStore]:
        return lambda now: FakeMemoryStore(now=now)

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[MemoryStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        A dict needs no serialising, so without this the canonical fake could
        only opt out — and the cancellation case would run solely against the
        ``sqlite3`` store that already holds the invariant. Every write passes
        through the *one* modelled resource, so ``arm`` ignores which operation it
        is handed: the parametrised cases (#370) exercise the same ``held()`` path
        on the fake and earn their keep on the ``sqlite3`` store, where each
        operation is a separate lock site. Nothing to dispose of, hence the bare
        yield.
        """
        store = FakeMemoryStore(now=_fixed_now)
        yield SuspendedMidWrite(
            store=store,
            log=store.resource_log,
            arm=lambda _operation: store.suspend_next_operation(),
        )

    @contextlib.asynccontextmanager
    async def store_suspended_at_its_first_await(
        self,
    ) -> AsyncIterator[tuple[MemoryStore, Callable[[str], SuspendedCall]]]:
        """The same modelled resource, read for ADR-0065's position instead.

        The fake takes its one observation of the record on its first executed
        line and only then enters :class:`~ai_assistant.testing.cancellation.
        SuspendableResource`, so the armed suspension *is* the write's first
        ``await`` — the position ADR-0065 §3 fixes. One hook serves both clauses
        here only because the fake's resource sits exactly at that boundary; the
        ``sqlite3`` store needs two, since its resource is acquired after the
        embedding await its input clause turns on.

        ``arm`` ignores the operation for the same reason it does above: one
        modelled resource serves every call, reads included since #397, and each
        enters it only after taking its one observation of its arguments.
        """
        store = FakeMemoryStore(now=_fixed_now)
        yield store, lambda _operation: store.suspend_next_operation()


# Behaviour specific to FakeMemoryStore, beyond the shared contract: the contract
# only asserts that a match is found, so the fake's own ordering/scoring and its
# state-isolation guarantees are pinned here (adversarial review of the fakes slice).


async def test_search_orders_by_overlap_and_populates_scores() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_semantic("both", "alpha beta gamma"))
    await store.add(_semantic("one", "alpha delta"))

    results = (await store.search("alpha beta")).records

    assert [r.id for r in results] == ["both", "one"]  # higher overlap first
    assert results[0].score == 1.0  # both query terms matched
    assert results[1].score == 0.5  # one of two matched


async def test_returned_records_cannot_be_mutated_to_reach_stored_state() -> None:
    # Under ADR-0068 the record graph is frozen, so isolation is subsumed by
    # immutability: there is no handed-out copy to diverge from stored state,
    # because none of these mutations is representable at all.
    store = FakeMemoryStore(now=_fixed_now)
    original = _semantic("1", "original content")
    await store.add(original)

    with pytest.raises(ValidationError):
        original.content = "mutated after add"  # ingress: caller keeps a reference
    got = await store.get("1")
    assert got is not None
    with pytest.raises(ValidationError):
        got.content = "mutated on egress"  # egress: top-level field
    with pytest.raises(ValidationError):
        got.provenance.confidence = 0.1  # egress: nested model is frozen too
    assert isinstance(got.provenance.evidence, tuple)  # egress: nested collection is immutable

    fresh = await store.get("1")
    assert fresh is not None
    assert fresh.content == "original content"  # stored state untouched
    assert fresh.provenance.evidence == ()


async def test_search_results_cannot_be_mutated_to_reach_stored_state() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_semantic("1", "coffee note"))

    results = (await store.search("coffee")).records
    assert results
    with pytest.raises(ValidationError):
        results[0].provenance.confidence = 0.1  # nested model of a result is frozen
    assert isinstance(results[0].provenance.evidence, tuple)

    fresh = await store.get("1")
    assert fresh is not None
    assert fresh.provenance.evidence == ()


async def test_exported_records_cannot_be_mutated_to_reach_stored_state() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_semantic("1", "coffee note"))

    exported = await store.export()
    assert exported
    with pytest.raises(ValidationError):
        exported[0].content = "mutated"
    with pytest.raises(ValidationError):
        exported[0].provenance.confidence = 0.1
    assert isinstance(exported[0].provenance.evidence, tuple)

    fresh = await store.get("1")
    assert fresh is not None
    assert fresh.content == "coffee note"
    assert fresh.provenance.evidence == ()


# --------------------------------------------------------------------------- #
# the configured retrieval failure (issue #105)                               #
# --------------------------------------------------------------------------- #

#: The message the fake is configured to fail with, so each case asserts that the
#: caller's own text came back rather than some generic store error.
_BROKEN = "fake: retrieval is unavailable"


def _broken_store() -> FakeMemoryStore:
    return FakeMemoryStore(now=_fixed_now, failure=_BROKEN)


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda store: store.get("1"), id="get"),
        pytest.param(lambda store: store.get_many(["1"]), id="get_many"),
        pytest.param(lambda store: store.search("coffee"), id="search"),
        pytest.param(lambda store: store.list_beliefs(), id="list_beliefs"),
        pytest.param(lambda store: store.walk_records("nightly", limit=1), id="walk_records"),
    ],
)
async def test_every_read_raises_the_configured_failure(
    read: Callable[[FakeMemoryStore], Awaitable[object]],
) -> None:
    """`failure=` breaks the whole read surface, not just `search` (issue #105).

    Enumerated rather than asserted of ``search`` alone, because a consumer that
    degrades on retrieval reads whichever of these its own path uses, and a fake
    that broke one of five would send it back to the subclass this replaces.
    """
    store = _broken_store()
    await store.add(_semantic("1", "coffee note"))

    with pytest.raises(MemoryStoreError, match="retrieval is unavailable"):
        await read(store)


async def test_the_failure_repeats_as_a_distinct_instance_each_call() -> None:
    # A fresh exception per call, for `FakeContextProvider`'s reason: one stored
    # instance re-raised would accumulate a traceback across calls.
    store = _broken_store()

    raised = []
    for _ in range(2):
        with pytest.raises(MemoryStoreError, match="retrieval is unavailable") as caught:
            await store.search("coffee")
        raised.append(caught.value)

    assert raised[0] is not raised[1]


async def test_a_broken_store_still_writes_and_still_exports() -> None:
    """The two halves a degradation case needs while retrieval is down.

    A consumer that survives a failed read is owed both: the store it was handed
    could be seeded, and what it did *not* write is assertable afterwards. Closing
    ``export`` would leave "the turn degraded and wrote nothing" — the whole of
    ADR-0022 §3's obligation — unprovable, so the failure deliberately stops at the
    reads. ``export`` is ADR-0007's data-rights snapshot, not a retrieval.
    """
    store = _broken_store()

    assert await store.add(_semantic("1", "coffee note")) == "1"
    assert [record.id for record in await store.export()] == ["1"]
    assert await store.delete("1") is True
    assert await store.export() == []


async def test_a_read_that_reaches_no_record_is_answered_rather_than_failed() -> None:
    """The failure models the backing, so it cannot bite where the backing is untouched.

    Each of these returns before the fake enters its modelled resource, exactly as
    it does on an unbroken store — ``visits`` is what pins that it really did not
    reach it. A fake that failed them would certify a consumer against a call the
    real store never makes (ADR-0026 §7).
    """
    store = _broken_store()

    assert (await store.search("   ")).records == ()
    assert (await store.search("coffee", limit=0)).records == ()
    assert await store.get_many([]) == {}
    assert await store.list_beliefs(limit=0) == []
    assert await store.list_beliefs(kinds=()) == []

    assert store.resource_log.visits == 0


async def test_an_argument_the_store_would_refuse_is_still_refused_first() -> None:
    # A malformed argument is the caller's mistake whether or not the backing can
    # answer, and the real stores refuse it before they touch anything. A fake that
    # reported a store failure here would hide a test's own bug behind the outage
    # it configured.
    store = _broken_store()

    with pytest.raises(ValueError, match="non-blank encodable text"):
        await store.walk_records("   ", limit=1)
    with pytest.raises(ValueError, match=r"limit must be in \[0, 2\*\*63\)"):
        await store.list_beliefs(limit=-1)

    assert store.resource_log.visits == 0


async def test_a_failing_read_entered_the_store_before_it_failed() -> None:
    # The call reached the backing and the backing was broken, which is the outage
    # being modelled; a refusal at the door would be a different fault, and would
    # take the read out of the cancellation clause's reach (ADR-0060).
    store = _broken_store()

    with pytest.raises(MemoryStoreError, match="retrieval is unavailable"):
        await store.get("1")

    assert store.resource_log.visits == 1
