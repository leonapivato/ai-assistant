"""The canonical FakeMemoryStore passes the shared MemoryStore conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryStore``
as a stand-in for a real store: it is held to the same contract as
``InMemoryMemoryStore`` and ``SqliteMemoryStore``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from memory_store_contract import MemoryStoreContract

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore


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

    @pytest.fixture
    def store(self) -> MemoryStore:
        return FakeMemoryStore(now=_fixed_now)


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


async def test_returned_records_are_isolated_from_stored_state() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    original = _semantic("1", "original content")
    await store.add(original)

    original.content = "mutated after add"  # ingress: caller keeps a reference
    got = await store.get("1")
    assert got is not None
    got.content = "mutated on egress"  # egress: top-level field
    got.provenance.evidence.append("injected")  # egress: nested mutable field

    fresh = await store.get("1")
    assert fresh is not None
    assert fresh.content == "original content"  # no mutation reached stored state
    assert fresh.provenance.evidence == []
