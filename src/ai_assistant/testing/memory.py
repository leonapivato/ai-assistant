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

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.types import MemoryWriteMode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryKind, MemoryRecord, MemoryWrite


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakeMemoryStore:
    """A non-persistent ``MemoryStore`` test double backed by a dict.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryStore`. Records are keyed by id;
    adding a record whose id already exists overwrites it.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Create an empty store.

        Args:
            now: Clock used to decide whether a record has expired; injectable for
                deterministic tests. Defaults to the UTC wall clock. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, exactly as the
                real stores are: a fake looser than the contract would certify
                consumers the real implementation rejects (ADR-0026 §7).
        """
        self._records: dict[str, MemoryRecord] = {}
        self._clock = checked_clock(now, owner="FakeMemoryStore")

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as the error the real store raises.

        ``MemoryStoreError``, not the raw ``ValueError`` ``core`` raises: a fake
        that leaked it would certify a consumer's error handling against
        behaviour it will never meet in production (ADR-0026 §4).

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    @staticmethod
    def _is_expired(record: MemoryRecord, now: datetime) -> bool:
        return record.expires_at is not None and record.expires_at <= now

    def _is_readable(self, record: MemoryRecord, now: datetime) -> bool:
        """Whether a record may be returned by ``get``/``search`` at ``now``.

        Both read-time filters: not expired (ADR-0007) and live at now — the
        validity window's ``live_at`` predicate, both ends (ADR-0045 §6). ``now``
        is captured **once per read operation** and passed in, so every record in
        one ``search`` is judged against a single instant, matching the persistent
        store. ``export`` deliberately does not use this: it keeps window-closed
        records.
        """
        return not self._is_expired(record, now) and record.validity.live_at(now)

    async def add(self, record: MemoryRecord) -> str:
        """Persist ``record`` (overwriting any existing same id) and return its id.

        Stores a deep copy, so a caller mutating the record after ``add`` cannot
        reach into stored state — matching the isolation the persistent store gets
        for free by serialising to the database.
        """
        self._records[record.id] = record.model_copy(deep=True)
        return record.id

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """Apply every write in one atomic unit — all commit, or none do.

        Emulates atomicity the same way the real in-memory store does, so the fake
        honours the contract the durable backend does: the batch is validated up
        front (no repeated id, no ``INSERT_IF_ABSENT`` collision) and every
        mutation is staged, then applied only once every check has passed — a
        mid-batch failure mutates nothing (ADR-0046 §4).

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id names a
                stored record — physical presence, so an expired or window-closed
                row still collides (ADR-0046 §3). Nothing is written.
            MemoryStoreError: the batch names the same id twice (ADR-0046 §3).
                Nothing is written.
        """
        ids = [write.record.id for write in writes]
        if len(set(ids)) != len(ids):
            msg = "an atomic batch may not write the same id twice"
            raise MemoryStoreError(msg)
        staged: list[MemoryRecord] = []
        for write in writes:
            if write.mode is MemoryWriteMode.INSERT_IF_ABSENT and write.record.id in self._records:
                msg = f"cannot insert {write.record.id!r}: a record with that id is already stored"
                raise MemoryStoreConflictError(msg)
            staged.append(write.record.model_copy(deep=True))
        for record in staged:
            self._records[record.id] = record
        return [record.id for record in staged]

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if not readable.

        ``None`` when the record is absent, expired, or not live at now — a closed
        or not-yet-open validity window, both ends (ADR-0045 §6).
        """
        record = self._records.get(record_id)
        if record is None or not self._is_readable(record, self._now_utc()):
            return None
        # Deep copy so callers cannot mutate stored state — including nested fields
        # like provenance and validity — matching the persistent store (ADR-0007).
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
        record's content. Non-matching records, expired records, records not live
        at now (a closed or not-yet-open validity window, both ends — ADR-0045
        §6), an empty query, and a non-positive ``limit`` all yield nothing.
        """
        query_terms = {term for term in query.lower().split() if term}
        if limit <= 0 or not query_terms:
            return []
        now = self._now_utc()  # one reading for the whole search, not one per record
        wanted = {str(kind) for kind in kinds} if kinds is not None else None
        scored: list[MemoryRecord] = []
        for record in self._records.values():
            if not self._is_readable(record, now) or (
                wanted is not None and record.kind not in wanted
            ):
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
        """Return an independent snapshot of every retained (non-expired) record.

        Includes window-closed records: unlike ``get``/``search`` this does not
        filter on the validity window — a superseded belief is retained data a
        data-rights export must keep; only expired records are excluded (ADR-0045
        §6, amending ADR-0007 §3).
        """
        now = self._now_utc()
        return [
            r.model_copy(deep=True) for r in self._records.values() if not self._is_expired(r, now)
        ]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        now = self._now_utc()
        expired = [rid for rid, record in self._records.items() if self._is_expired(record, now)]
        for rid in expired:
            del self._records[rid]
        return len(expired)
