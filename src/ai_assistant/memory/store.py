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
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.types import MemoryWriteMode, band_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import BeliefBand, MemoryKind, MemoryRecord, MemoryWrite

#: One past the largest value ``list_beliefs`` accepts for ``limit``/``offset``:
#: the signed 64-bit ceiling a SQLite bind parameter tops out at (ADR-0073 §2).
_PAGE_BOUND = 2**63


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_page_bounds(limit: int, offset: int) -> None:
    """Refuse a paging argument outside ``[0, 2**63)`` (ADR-0073 §2).

    Duplicated across the two stores and the canonical fake rather than shared,
    exactly as ``AuditTrail.recent``'s check is: ``ai_assistant.testing`` may not
    import a subsystem (golden rule 1), and ADR-0073 adds nothing to ``core``.

    Raises:
        ValueError: If either value is negative or beyond the signed 64-bit range.
    """
    for name, value in (("limit", limit), ("offset", offset)):
        if not 0 <= value < _PAGE_BOUND:
            msg = f"{name} must be in [0, 2**63), got {value}"
            raise ValueError(msg)


def _newest_revision_first(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """ADR-0073 §2's total order: ``last_updated`` descending, ``id`` ascending.

    Two passes over a stable sort rather than one composite key, because the two
    halves run in opposite directions and ``datetime`` has no negation — the idiom
    ``FakeAuditTrail._ordered`` already uses for the same shape.
    """
    by_id = sorted(records, key=lambda record: record.id)
    return sorted(by_id, key=lambda record: record.provenance.last_updated, reverse=True)


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

    @staticmethod
    def _is_expired(record: MemoryRecord, now: datetime) -> bool:
        return record.expires_at is not None and record.expires_at <= now

    def _is_readable(self, record: MemoryRecord, now: datetime) -> bool:
        """Whether a record may be returned by ``get``/``search`` at ``now``.

        Both read-time filters at once: not expired (ADR-0007) and live at now —
        the validity window's ``live_at`` predicate, both ends (ADR-0045 §6).
        ``now`` is captured **once per read operation** and passed in, so every
        record in one ``search`` is judged against a single instant (matching the
        persistent store, which reads its clock once). ``export`` deliberately
        does not use this: it keeps window-closed records.
        """
        return not self._is_expired(record, now) and record.validity.live_at(now)

    async def add(self, record: MemoryRecord) -> str:
        """Persist a record and return its id.

        Args:
            record: The record to store. Its ``id`` is used as the key; storing
                a record with an existing id overwrites the previous one.

        Returns:
            The stored record's id.
        """
        # Deep copy so a caller mutating the record (including nested fields like
        # validity, which drives read filtering) after add cannot reach stored
        # state — matching FakeMemoryStore and the serialised persistent store.
        self._records[record.id] = record.model_copy(deep=True)
        return record.id

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """Apply every write in one atomic unit — all commit, or none do.

        A ``dict`` has no transaction, so atomicity is *emulated*: the whole batch
        is validated up front (no repeated id, no ``INSERT_IF_ABSENT`` collision)
        and every mutation is staged, then applied only once every check has
        passed — so a mid-batch failure mutates nothing (ADR-0046 §4, in-call
        all-or-nothing). This is the whole guarantee a non-durable store owes;
        crash atomicity is vacuous for it.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id names a
                stored record — physical presence, so an expired or window-closed
                row still collides (ADR-0046 §3). Nothing is written.
            MemoryStoreError: the batch names the same id twice (ADR-0046 §3).
                Nothing is written.
        """
        self._reject_repeated_ids(writes)
        # Stage first: validate every element against the *pre-batch* state, then
        # apply. No element's check may observe an earlier element's staged write
        # (the repeated-id rejection above makes that case unreachable anyway).
        staged: list[MemoryRecord] = []
        for write in writes:
            if write.mode is MemoryWriteMode.INSERT_IF_ABSENT and write.record.id in self._records:
                msg = f"cannot insert {write.record.id!r}: a record with that id is already stored"
                raise MemoryStoreConflictError(msg)
            # Deep copy so a caller mutating the record after the call cannot reach
            # stored state, matching ``add``.
            staged.append(write.record.model_copy(deep=True))
        for record in staged:
            self._records[record.id] = record
        return [record.id for record in staged]

    @staticmethod
    def _reject_repeated_ids(writes: Sequence[MemoryWrite]) -> None:
        """Refuse a batch that writes the same id twice (ADR-0046 §3).

        A property of the batch, checked before anything is written: two writes to
        one id is the case a sequential SQLite apply and a stage-then-swap fake
        would resolve differently, so it is forbidden rather than defined.
        """
        ids = [write.record.id for write in writes]
        if len(set(ids)) != len(ids):
            msg = "an atomic batch may not write the same id twice"
            raise MemoryStoreError(msg)

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if not readable.

        ``None`` when the record is absent, expired, or not live at now — a closed
        or not-yet-open validity window, both ends (ADR-0045 §6).
        """
        record = self._records.get(record_id)
        if record is None or not self._is_readable(record, self._now_utc()):
            return None
        # Deep copy so callers cannot mutate stored state — including nested fields
        # like validity — matching the persistent store.
        return record.model_copy(deep=True)

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
        term, expired records, and records not live at now (a closed or
        not-yet-open validity window, both ends — ADR-0045 §6) are omitted. An
        empty or whitespace-only query matches nothing.

        Args:
            query: The search text.
            limit: Maximum number of records to return; ``<= 0`` matches nothing.
            kinds: If given, restrict results to these memory kinds.

        Returns:
            Matching records, highest score first, each carrying its relevance
            ``score``, truncated to ``limit``.

        Note:
            ``kinds`` is materialised on the coroutine's **first executed line**, as
            in ``list_beliefs`` below and for the same reason: this method never
            suspends, so ADR-0065's clause is vacuous here, but the snapshot keeps
            the three implementations one shape and keeps the discharge from
            resting on the absence of a suspension point a later revision could
            add (#436).
        """
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        query_terms = {term for term in query.lower().split() if term}
        if limit <= 0 or not query_terms:
            return []

        now = self._now_utc()  # one reading for the whole search, not one per record
        scored = [
            record.model_copy(update={"score": score}, deep=True)
            for record in self._records.values()
            if self._is_readable(record, now)
            and (wanted is None or record.kind in wanted)
            and (score := _relevance(query_terms, record.content)) > 0.0
        ]
        scored.sort(key=lambda record: record.score or 0.0, reverse=True)
        return scored[:limit]

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Enumerate live beliefs, newest revision first (ADR-0073 §1).

        Filters, orders, then pages — in that order, so a page is full whenever
        enough matching records exist. Both read-time axes are applied through the
        same ``_is_readable`` predicate ``get``/``search`` use, against one clock
        reading for the whole call, so this read cannot disagree with retrieval
        about what is live (ADR-0073 §2).

        Both ``Sequence`` filters are materialised on the coroutine's **first
        executed line** and only the copies are read thereafter, which is ADR-0065
        §3's second discharge. There is no ``await`` here at all, so the clause is
        already vacuous for this store — taking the snapshot anyway keeps the three
        implementations one shape, and keeps the discharge from depending on the
        absence of a suspension point a later revision could add.

        Args:
            bands: Belief bands to include; ``None`` is every band, ``()`` none.
            kinds: Memory kinds to include; ``None`` is every kind, ``()`` none.
            limit: Page size; ``0`` returns an empty page.
            offset: How many ordered, filtered records to skip.

        Returns:
            The page, each record a detached snapshot with ``score`` cleared.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            MemoryStoreError: If the injected clock's reading is not conforming.
        """
        wanted_bands = None if bands is None else frozenset(bands)
        wanted_kinds = None if kinds is None else frozenset(str(kind) for kind in kinds)
        _check_page_bounds(limit, offset)
        selects_nothing = (wanted_bands is not None and not wanted_bands) or (
            wanted_kinds is not None and not wanted_kinds
        )
        if limit == 0 or selects_nothing:
            return []

        now = self._now_utc()  # one reading for the whole page, as ``search`` takes
        matched = [
            record
            for record in self._records.values()
            if self._is_readable(record, now)
            and (wanted_bands is None or band_of(record.provenance.source) in wanted_bands)
            and (wanted_kinds is None or record.kind in wanted_kinds)
        ]
        page = _newest_revision_first(matched)[offset : offset + limit]
        # ``score`` is cleared rather than left as stored: a record re-added after a
        # search carries that query's relevance, which means nothing here.
        return [record.model_copy(update={"score": None}, deep=True) for record in page]

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
            record.model_copy(deep=True)
            for record in self._records.values()
            if not self._is_expired(record, now)
        ]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        now = self._now_utc()
        expired = [rid for rid, record in self._records.items() if self._is_expired(record, now)]
        for rid in expired:
            del self._records[rid]
        return len(expired)
