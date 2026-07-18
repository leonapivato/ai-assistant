"""Tests for the in-memory MemoryStore."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import InMemoryMemoryStore

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _NOW


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


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


def test_store_conforms_to_protocol() -> None:
    assert isinstance(InMemoryMemoryStore(), MemoryStore)


async def test_add_returns_id_and_persists() -> None:
    store = InMemoryMemoryStore()

    returned = await store.add(_semantic("1", "the user likes espresso"))

    assert returned == "1"
    results = await store.search("espresso")
    assert [r.id for r in results] == ["1"]


async def test_get_returns_record_or_none() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "some fact"))

    got = await store.get("1")
    assert got is not None
    assert got.id == "1"
    assert await store.get("missing") is None


async def test_add_overwrites_same_id() -> None:
    store = InMemoryMemoryStore()

    await store.add(_semantic("1", "old content about tea"))
    await store.add(_semantic("1", "new content about coffee"))

    assert await store.search("tea") == []
    assert [r.id for r in await store.search("coffee")] == ["1"]


async def test_search_orders_by_relevance_and_scores() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("both", "coffee and tea preferences"))
    await store.add(_semantic("one", "coffee only"))
    await store.add(_semantic("none", "unrelated note"))

    results = await store.search("coffee tea")

    assert [r.id for r in results] == ["both", "one"]
    assert results[0].score == 1.0  # both query terms matched
    assert results[1].score == 0.5  # one of two terms matched


async def test_search_filters_by_kind() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("s", "shared coffee keyword"))
    await store.add(_preference("p", "shared coffee keyword"))

    results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

    assert [r.id for r in results] == ["p"]
    assert results[0].kind == "preference"


async def test_search_respects_limit() -> None:
    store = InMemoryMemoryStore()
    for i in range(5):
        await store.add(_semantic(str(i), "shared keyword here"))

    results = await store.search("keyword", limit=3)

    assert len(results) == 3


async def test_non_positive_limit_matches_nothing() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "shared keyword here"))

    assert await store.search("keyword", limit=0) == []
    assert await store.search("keyword", limit=-2) == []


async def test_empty_query_matches_nothing() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "some content"))

    assert await store.search("   ") == []


async def test_no_match_returns_empty() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "content about cats"))

    assert await store.search("spacecraft") == []


async def test_delete_removes_record_and_reports_existence() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "a fact"))

    assert await store.delete("1") is True
    assert await store.get("1") is None
    assert await store.delete("1") is False  # already gone


async def test_clear_removes_all_and_returns_count() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "one"))
    await store.add(_semantic("2", "two"))

    assert await store.clear() == 2
    assert await store.get("1") is None
    assert await store.clear() == 0  # empty now


async def test_export_returns_live_records_only() -> None:
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_semantic("live", "still valid"))
    await store.add(_semantic("dead", "gone", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    exported = await store.export()

    assert [r.id for r in exported] == ["live"]


async def test_expired_records_are_hidden_from_get_and_search() -> None:
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_semantic("1", "shared keyword", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    assert await store.get("1") is None
    assert await store.search("keyword") == []


async def test_expiry_boundary_is_exclusive_at_now() -> None:
    store = InMemoryMemoryStore(now=_fixed_now)
    # expires_at exactly == now counts as expired (<= now); one second later is live.
    await store.add(_semantic("at_now", "keyword one", expires_at=_NOW))
    await store.add(
        _semantic("future", "keyword two", expires_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC))
    )

    assert await store.get("at_now") is None
    assert await store.get("future") is not None


async def test_naive_injected_clock_is_treated_as_utc() -> None:
    store = InMemoryMemoryStore(now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001  naive clock
    await store.add(_semantic("1", "keyword", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    assert await store.get("1") is None  # no crash; expired under the UTC-normalised clock


async def test_export_is_an_independent_snapshot() -> None:
    store = InMemoryMemoryStore()
    await store.add(_semantic("1", "original"))

    exported = await store.export()
    exported[0].content = "mutated"  # must not reach into stored state

    got = await store.get("1")
    assert got is not None
    assert got.content == "original"


async def test_naive_expiry_is_treated_as_utc_not_a_crash() -> None:
    store = InMemoryMemoryStore(now=_fixed_now)
    # A naive deadline (accepted by the model, coerced to UTC) must not crash the
    # aware-vs-naive comparison; here it is in the past, so the record is hidden.
    await store.add(_semantic("1", "keyword", expires_at=datetime(2026, 1, 2)))  # noqa: DTZ001

    assert await store.get("1") is None
    assert await store.search("keyword") == []


async def test_purge_expired_removes_only_expired_and_returns_count() -> None:
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_semantic("live", "keeps"))
    await store.add(_semantic("dead", "goes", expires_at=datetime(2026, 1, 2, tzinfo=UTC)))

    removed = await store.purge_expired()

    assert removed == 1
    assert await store.get("live") is not None
    assert await store.purge_expired() == 0  # nothing left to purge
