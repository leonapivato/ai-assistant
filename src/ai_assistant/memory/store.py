"""An in-memory :class:`~ai_assistant.core.protocols.MemoryStore`.

This is the first, dependency-free implementation of the memory contract. It
keeps records in a process-local dict and scores retrieval by naive lexical
overlap — it is **not persistent and not semantic**. Its purpose is to satisfy
the ``MemoryStore`` contract so downstream subsystems (planning, orchestration)
can be developed and tested against a real store without standing up a database.

It implements the full contract, including the data-rights operations
(``delete``/``clear``/``export``/``purge_expired``) and read-time retention
(expired records are hidden from ``get``/``search``) per ADR-0007. Semantic
retrieval and persistence live in ``SqliteMemoryStore`` (ADR-0002/0006).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryKind, MemoryRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _relevance(query_terms: set[str], content: str) -> float:
    """Score a record's content against query terms by fractional term overlap.

    Args:
        query_terms: Lower-cased, whitespace-split query terms (non-empty).
        content: The record's content.

    Returns:
        The fraction of query terms that appear as substrings of ``content``,
        in ``[0.0, 1.0]``.
    """
    content_lower = content.lower()
    hits = sum(1 for term in query_terms if term in content_lower)
    return hits / len(query_terms)


class InMemoryMemoryStore:
    """A non-persistent ``MemoryStore`` backed by a dict, for dev and tests.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryStore`. Records are stored by
    their id; adding a record whose id already exists overwrites it.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Create an empty store.

        Args:
            now: Clock used to decide whether a record has expired; injectable
                for deterministic tests. Defaults to UTC wall-clock. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a naive or
                indeterminate reading is a ``MemoryStoreError`` rather than a
                fabricated UTC instant the expiry comparison then trusts
                (ADR-0026 §2).
        """
        self._records: dict[str, MemoryRecord] = {}
        self._clock = checked_clock(now, owner="InMemoryMemoryStore")

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as `memory`'s own error (ADR-0026 §4).

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _is_expired(self, record: MemoryRecord) -> bool:
        return record.expires_at is not None and record.expires_at <= self._now_utc()

    async def add(self, record: MemoryRecord) -> str:
        """Persist a record and return its id.

        Args:
            record: The record to store. Its ``id`` is used as the key; storing
                a record with an existing id overwrites the previous one.

        Returns:
            The stored record's id.
        """
        self._records[record.id] = record
        return record.id

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent or expired."""
        record = self._records.get(record_id)
        if record is None or self._is_expired(record):
            return None
        # Copy so callers cannot mutate stored state, matching the persistent store.
        return record.model_copy()

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return the records most relevant to ``query``, best first.

        Relevance is naive lexical overlap: the fraction of query terms that
        appear as substrings of a record's content. Records that match no query
        term, and expired records, are omitted. An empty or whitespace-only
        query matches nothing.

        Args:
            query: The search text.
            limit: Maximum number of records to return; ``<= 0`` matches nothing.
            kinds: If given, restrict results to these memory kinds.

        Returns:
            Matching records, highest score first, each carrying its relevance
            ``score``, truncated to ``limit``.
        """
        query_terms = {term for term in query.lower().split() if term}
        if limit <= 0 or not query_terms:
            return []

        wanted = {str(kind) for kind in kinds} if kinds is not None else None
        scored = [
            record.model_copy(update={"score": score})
            for record in self._records.values()
            if not self._is_expired(record)
            and (wanted is None or record.kind in wanted)
            and (score := _relevance(query_terms, record.content)) > 0.0
        ]
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
        return [
            record.model_copy() for record in self._records.values() if not self._is_expired(record)
        ]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        expired = [rid for rid, record in self._records.items() if self._is_expired(record)]
        for rid in expired:
            del self._records[rid]
        return len(expired)
