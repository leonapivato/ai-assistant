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

from datetime import UTC, datetime

import pytest

from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)

# Far in the past: expired under any real or injected clock the suite is run with.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(
        source=MemorySource.OBSERVED,
        confidence=0.6,
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _semantic(record_id: str, content: str, *, expires_at: datetime | None = None) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(),
        expires_at=expires_at,
    )


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


class MemoryStoreContract:
    """The behavioural contract every ``MemoryStore`` implementation must satisfy."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        """Override in a subclass to supply the implementation under test."""
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

    async def test_add_overwrites_same_id(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "old note"))
        await store.add(_semantic("1", "new note"))

        got = await store.get("1")
        assert got is not None
        assert got.content == "new note"

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
