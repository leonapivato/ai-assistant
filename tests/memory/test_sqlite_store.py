"""Tests for the persistent SQLite-backed MemoryStore.

These use the deterministic ``HashingEmbedder`` so retrieval is reproducible and
offline; its similarity reflects shared tokens, which is enough to exercise the
store's ranking, filtering, and persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.protocols import MemoryStore
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from pathlib import Path

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


def _semantic(record_id: str, content: str) -> MemoryRecord:
    return SemanticMemory(id=record_id, content=content, fact=content, provenance=_provenance())


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


def _store(tmp_path: Path, *, dimensions: int = 256) -> SqliteMemoryStore:
    return SqliteMemoryStore(
        path=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=dimensions)
    )


def test_store_conforms_to_protocol(tmp_path: Path) -> None:
    assert isinstance(_store(tmp_path), MemoryStore)


async def test_add_and_get_round_trips_typed_record(tmp_path: Path) -> None:
    store = _store(tmp_path)

    await store.add(_preference("p1", "prefers concise replies"))
    got = await store.get("p1")

    assert isinstance(got, PreferenceMemory)
    assert got.id == "p1"
    assert got.preference == "prefers concise replies"


async def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert await store.get("nope") is None


async def test_search_ranks_by_similarity_and_scores(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.add(_semantic("c1", "coffee tea"))
    await store.add(_semantic("c2", "coffee milk"))
    await store.add(_semantic("r1", "rocket ship"))

    results = await store.search("coffee")

    assert {results[0].id, results[1].id} == {"c1", "c2"}
    assert results[-1].id == "r1"
    assert results[0].score is not None
    assert results[0].score > results[-1].score  # type: ignore[operator]


async def test_add_overwrites_same_id(tmp_path: Path) -> None:
    store = _store(tmp_path)

    await store.add(_semantic("1", "old note about tea"))
    await store.add(_semantic("1", "new note about coffee"))

    got = await store.get("1")
    assert got is not None
    assert got.content == "new note about coffee"


async def test_search_filters_by_kind(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.add(_semantic("s", "coffee fact"))
    await store.add(_preference("p", "coffee preference"))

    results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

    assert [r.id for r in results] == ["p"]


async def test_empty_query_matches_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.add(_semantic("1", "some content"))
    assert await store.search("   ") == []


async def test_persists_across_reopen(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.add(_semantic("1", "durable memory"))
    store.close()

    reopened = _store(tmp_path)
    got = await reopened.get("1")
    assert got is not None
    assert got.content == "durable memory"


async def test_reopening_with_different_embedder_raises(tmp_path: Path) -> None:
    store = _store(tmp_path, dimensions=256)
    await store.add(_semantic("1", "x"))
    store.close()

    with pytest.raises(MemoryStoreError, match="re-embedding is required"):
        _store(tmp_path, dimensions=128)


def test_database_file_is_owner_only(tmp_path: Path) -> None:
    _store(tmp_path)
    mode = (tmp_path / "memory.db").stat().st_mode & 0o777
    assert mode == 0o600
