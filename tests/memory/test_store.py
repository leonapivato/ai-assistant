"""Tests for the in-memory MemoryStore."""

from __future__ import annotations

from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import MemoryRecord
from ai_assistant.memory import InMemoryMemoryStore


def _record(record_id: str, content: str) -> MemoryRecord:
    return MemoryRecord(id=record_id, content=content)


def test_store_conforms_to_protocol() -> None:
    assert isinstance(InMemoryMemoryStore(), MemoryStore)


async def test_add_returns_id_and_persists() -> None:
    store = InMemoryMemoryStore()

    returned = await store.add(_record("1", "the user likes espresso"))

    assert returned == "1"
    results = await store.search("espresso")
    assert [r.id for r in results] == ["1"]


async def test_add_overwrites_same_id() -> None:
    store = InMemoryMemoryStore()

    await store.add(_record("1", "old content about tea"))
    await store.add(_record("1", "new content about coffee"))

    assert await store.search("tea") == []
    assert [r.id for r in await store.search("coffee")] == ["1"]


async def test_search_orders_by_relevance_and_scores() -> None:
    store = InMemoryMemoryStore()
    await store.add(_record("both", "coffee and tea preferences"))
    await store.add(_record("one", "coffee only"))
    await store.add(_record("none", "unrelated note"))

    results = await store.search("coffee tea")

    assert [r.id for r in results] == ["both", "one"]
    assert results[0].score == 1.0  # both query terms matched
    assert results[1].score == 0.5  # one of two terms matched


async def test_search_respects_limit() -> None:
    store = InMemoryMemoryStore()
    for i in range(5):
        await store.add(_record(str(i), "shared keyword here"))

    results = await store.search("keyword", limit=3)

    assert len(results) == 3


async def test_empty_query_matches_nothing() -> None:
    store = InMemoryMemoryStore()
    await store.add(_record("1", "some content"))

    assert await store.search("   ") == []


async def test_no_match_returns_empty() -> None:
    store = InMemoryMemoryStore()
    await store.add(_record("1", "content about cats"))

    assert await store.search("spacecraft") == []
