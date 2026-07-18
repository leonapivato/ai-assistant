"""An in-memory :class:`~ai_assistant.core.protocols.MemoryStore`.

This is the first, dependency-free implementation of the memory contract. It
keeps records in a process-local dict and scores retrieval by naive lexical
overlap — it is **not persistent and not semantic**. Its purpose is to satisfy
the ``add``/``search`` contract so downstream subsystems (planning,
orchestration) can be developed and tested against a real ``MemoryStore``
without standing up a database.

The persistent local-first backend (SQLite + vector search per ADR-0002) and
the user-data-rights operations (export/delete/retention per ADR-0004) are a
separate, later slice: they need an embedding seam and Protocol additions that
warrant their own ADR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryKind, MemoryRecord


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

    def __init__(self) -> None:
        """Create an empty store."""
        self._records: dict[str, MemoryRecord] = {}

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
        """Return the record with ``record_id``, or ``None`` if absent."""
        return self._records.get(record_id)

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
        term are omitted. An empty or whitespace-only query matches nothing.

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
            if (wanted is None or record.kind in wanted)
            and (score := _relevance(query_terms, record.content)) > 0.0
        ]
        scored.sort(key=lambda record: record.score or 0.0, reverse=True)
        return scored[:limit]
