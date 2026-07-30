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
from memory_store_contract import MemoryStoreContract
from pydantic import ValidationError

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

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


class TestFakeMemoryStoreContract(MemoryStoreContract):
    """Runs FakeMemoryStore through the shared MemoryStore conformance suite."""

    #: ``search`` and ``list_beliefs`` read a dict and return, with no ``await``
    #: between the coroutine's first executed line and the filter being applied —
    #: nothing for a mid-flight mutation to land in (#436). Unlike the write side
    #: below, the fake does *not* model a suspension it does not have here: an
    #: ``await`` invented inside a read would exist only to be gated, and the two
    #: read cases run non-vacuously against ``SqliteMemoryStore``, which is where
    #: the clause was actually broken.
    reads_without_suspending = True

    @pytest.fixture
    def store(self) -> MemoryStore:
        return FakeMemoryStore(now=_fixed_now)

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
            arm=lambda _operation: store.suspend_next_write(),
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

        ``arm`` ignores the operation for the same reason it does above — one
        modelled resource serves every write — and is never asked for a read, since
        :attr:`reads_without_suspending` declares that axis vacuous.
        """
        store = FakeMemoryStore(now=_fixed_now)
        yield store, lambda _operation: store.suspend_next_write()


# Behaviour specific to FakeMemoryStore, beyond the shared contract: the contract
# only asserts that a match is found, so the fake's own ordering/scoring and its
# state-isolation guarantees are pinned here (adversarial review of the fakes slice).


async def test_search_orders_by_overlap_and_populates_scores() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_semantic("both", "alpha beta gamma"))
    await store.add(_semantic("one", "alpha delta"))

    results = await store.search("alpha beta")

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

    results = await store.search("coffee")
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
