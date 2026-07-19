"""A canonical in-memory :class:`~ai_assistant.core.protocols.MemoryStore` fake.

The shared test double for the ``MemoryStore`` contract, so a subsystem that
depends on memory (planning, orchestration, ...) can test against a real,
contract-correct store *without importing the memory subsystem's internals*
(CLAUDE.md golden rule 1). It is deliberately minimal — a dict with naive lexical
retrieval — and lives in ``ai_assistant.testing`` so it is importable from any
test while staying out of production code paths (``lint-imports`` forbids
production modules from importing it).

It honours the full contract, including read-time retention: a record past its
``expires_at`` is hidden from ``get``/``search`` (ADR-0007). It is intentionally
neither persistent nor semantic; for those, use ``SqliteMemoryStore``. Its
retrieval rules are not part of the contract — only the behaviour asserted by the
shared ``MemoryStore`` conformance suite is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import MemoryKind, MemoryRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakeMemoryStore:
    """A non-persistent ``MemoryStore`` test double backed by a dict.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryStore`. Records are keyed by id;
    adding a record whose id already exists overwrites it.
    """

    def __init__(self, *, now: Callable[[], datetime] = _utcnow) -> None:
        """Create an empty store.

        Args:
            now: Clock used to decide whether a record has expired; injectable for
                deterministic tests. Defaults to the UTC wall clock.
        """
        self._records: dict[str, MemoryRecord] = {}
        self._now = now

    def _now_utc(self) -> datetime:
        """The clock's current time, normalising a naive result to UTC."""
        now = self._now()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    def _is_expired(self, record: MemoryRecord) -> bool:
        return record.expires_at is not None and record.expires_at <= self._now_utc()

    async def add(self, record: MemoryRecord) -> str:
        """Persist ``record`` (overwriting any existing same id) and return its id.

        Stores a deep copy, so a caller mutating the record after ``add`` cannot
        reach into stored state — matching the isolation the persistent store gets
        for free by serialising to the database.
        """
        self._records[record.id] = record.model_copy(deep=True)
        return record.id

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent or expired."""
        record = self._records.get(record_id)
        if record is None or self._is_expired(record):
            return None
        # Deep copy so callers cannot mutate stored state — including nested fields
        # like provenance — matching the persistent store (ADR-0007).
        return record.model_copy(deep=True)

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return live records matching ``query`` by lexical overlap, best first.

        Relevance is the fraction of query terms that appear as substrings of a
        record's content. Expired records, non-matching records, an empty query,
        and a non-positive ``limit`` all yield nothing.
        """
        query_terms = {term for term in query.lower().split() if term}
        if limit <= 0 or not query_terms:
            return []
        wanted = {str(kind) for kind in kinds} if kinds is not None else None
        scored: list[MemoryRecord] = []
        for record in self._records.values():
            if self._is_expired(record) or (wanted is not None and record.kind not in wanted):
                continue
            content = record.content.lower()
            hits = sum(1 for term in query_terms if term in content)
            if hits:
                scored.append(
                    record.model_copy(update={"score": hits / len(query_terms)}, deep=True)
                )
        scored.sort(key=lambda record: record.score or 0.0, reverse=True)
        return scored[:limit]

    async def delete(self, record_id: str) -> bool:
        """Delete one record, returning whether it existed."""
        return self._records.pop(record_id, None) is not None

    async def clear(self) -> int:
        """Delete every record, returning the number removed."""
        count = len(self._records)
        self._records.clear()
        return count

    async def export(self) -> list[MemoryRecord]:
        """Return an independent snapshot of all live (non-expired) records."""
        return [r.model_copy(deep=True) for r in self._records.values() if not self._is_expired(r)]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        expired = [rid for rid, record in self._records.items() if self._is_expired(record)]
        for rid in expired:
            del self._records[rid]
        return len(expired)
