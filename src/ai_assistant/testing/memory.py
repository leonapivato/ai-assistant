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

Its reads *and* its writes go through a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` so it is a real
subject for the cancellation clause ``core.protocols`` states (ADR-0060), rather
than an implementation the obligation cannot reach. A dict needs no serialising,
so this buys the fake nothing on its own — what it buys is that the shared suite's
cancellation case runs against the canonical fake and not only against the
``sqlite3`` stores that already got the invariant right once. The reads are in
because ``SqliteMemoryStore`` serialises them through the same connection lock its
writes take, so every one of them is its own place the resource can be handed over
early (#397); modelling only the writes would have left that half of the matrix
proved by a single implementation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreError
from ai_assistant.core.types import (
    MemoryWriteMode,
    NonBlankEncodableText,
    RecordChunk,
    WalkPosition,
    band_of,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import BeliefBand, MemoryKind, MemoryRecord, MemoryWrite
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: One past the largest value ``list_beliefs`` accepts for ``limit``/``offset``
#: (ADR-0073 §2). The fake enforces the real stores' range: a fake looser than the
#: contract would certify consumers a real store rejects (ADR-0026 §7).
_PAGE_BOUND = 2**63


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_page_bounds(limit: int, offset: int) -> None:
    """Refuse a paging argument outside ``[0, 2**63)`` (ADR-0073 §2).

    Duplicated from the two stores rather than shared: ``ai_assistant.testing`` may
    not import a subsystem (golden rule 1), and ADR-0073 adds nothing to ``core``.

    Raises:
        ValueError: If either value is negative or beyond the signed 64-bit range.
    """
    for name, value in (("limit", limit), ("offset", offset)):
        if not 0 <= value < _PAGE_BOUND:
            msg = f"{name} must be in [0, 2**63), got {value}"
            raise ValueError(msg)


# --- the walk surface's checks and its opaque token (ADR-0114) ---------------
# Duplicated from ``ai_assistant.memory._walk`` for ``_check_page_bounds``'s
# reason and no other: ``ai_assistant.testing`` may not import a subsystem
# (golden rule 1). A fake looser than the contract would certify consumers a real
# store rejects (ADR-0026 §7), so these enforce exactly the real stores' rules,
# and the shared suite runs the same cases against all three.

#: The validator :data:`NonBlankEncodableText` applies, run explicitly on entry:
#: these aliases are pydantic ``Annotated`` validators and Python runs nothing for
#: an ordinary method call (ADR-0114 §5).
_WALK_NAME: Final = TypeAdapter[str](NonBlankEncodableText)


def _check_walk_name(walk: str) -> None:
    r"""Refuse a walk name that is empty, whitespace-only or unencodable.

    Never normalised: two names differing only in case or spacing are two walks
    (ADR-0114 §5). Checked here rather than left to the annotation because
    ``walk_records("\ud800", …)`` is an ordinary Python call, and a fake that
    accepted one would certify a consumer SQLite refuses at bind time.

    Raises:
        ValueError: If ``walk`` is not non-blank encodable text.
    """
    try:
        _WALK_NAME.validate_python(walk)
    except ValidationError as exc:
        msg = f"walk name must be non-blank encodable text, got {walk!r}"
        raise ValueError(msg) from exc


def _check_walk_limit(limit: int) -> None:
    """Refuse a chunk limit that is not exactly an ``int`` in ``[1, 2**63)``.

    ``bool`` is refused with the rest and is the case that matters most: it is an
    ``int`` subclass, so ``True`` satisfies every range comparison and would
    quietly become a one-record chunk. Zero is refused rather than answering with
    an empty page as ``list_beliefs`` does, because a chunk that examines nothing
    carries no position and an absent position *means the walk is exhausted*
    (ADR-0114 §6).

    Raises:
        ValueError: If ``limit`` is not exactly an ``int``, or is out of range.
    """
    if type(limit) is not int:
        msg = f"limit must be exactly an int, got {type(limit).__name__}: {limit!r}"
        raise ValueError(msg)
    if not 1 <= limit < _PAGE_BOUND:
        msg = f"limit must be in [1, 2**63), got {limit}"
        raise ValueError(msg)


def _resume_key(recorded: str | None, *, issued_through: int) -> int:
    """Read a recorded position back, restarting the walk on anything unusable.

    Absent, unreadable or malformed all mean the same thing: discard and restart
    from the first record, never raise (ADR-0114 §4, ADR-0111 §7). ``0`` is the
    position before the first record rather than a sentinel — there is no integer
    below the order's floor, and the obvious choice silently skips every record at
    or below it (ADR-0104 §2).

    A well-formed number **above every key this store has ever issued** is
    unsupported too, and is the dangerous case: it names a range no record can
    ever occupy, so the walk would answer "nothing left" on every run while the
    store filled up behind it. The ceiling is the high-water mark and not the
    largest key *present*, because walking to the end and then deleting the top
    records leaves a legitimate position above everything the store now holds.
    """
    if recorded is None:
        return 0
    try:
        key = int(recorded)
    except TypeError, ValueError:
        return 0
    if not 0 <= key <= issued_through:
        return 0
    return key


def _mint_position(walk: str, key: int) -> WalkPosition:
    """Encode ``key`` as a position bound to ``walk``.

    JSON rather than a delimiter join, so a walk name containing the delimiter
    cannot make one walk's position parse as another's.
    """
    return WalkPosition(token=json.dumps({"w": walk, "k": key}, ensure_ascii=False))


def _read_position(walk: str, position: object) -> int:
    """Decode ``position``'s order key, refusing anything not this walk's.

    Validates the argument before reading any field:
    ``WalkPosition.model_construct(token=…)`` builds an instance without running
    the model's validator, so a malformed token — or none at all — reaches here
    with the declared type satisfied, and reading ``position.token`` first would
    raise ``AttributeError``, which ADR-0114 §6a makes a breach rather than a
    variant. General over malformation and stopping exactly there: a well-formed
    token naming the right walk that no chunk read issued stays undetected by
    design (ADR-0114 §2).

    Raises:
        ValueError: If ``position`` is not a
            :class:`~ai_assistant.core.types.WalkPosition`, carries no usable
            token, or is bound to a different walk.
    """
    if not isinstance(position, WalkPosition):
        msg = f"position must be a WalkPosition, got {type(position).__name__}"
        raise ValueError(msg)
    token = getattr(position, "token", None)
    if not isinstance(token, str):
        msg = "position carries no token"
        raise ValueError(msg)
    try:
        decoded = json.loads(token)
    except ValueError as exc:
        msg = f"position token is malformed: {token!r}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, dict) or type(decoded.get("k")) is not int:
        msg = f"position token is malformed: {token!r}"
        raise ValueError(msg)
    issued_for = decoded.get("w")
    if issued_for != walk:
        msg = f"position was issued for walk {issued_for!r}, not {walk!r}"
        raise ValueError(msg)
    return int(decoded["k"])


def _newest_revision_first(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """ADR-0073 §2's total order: ``last_updated`` descending, ``id`` ascending.

    Two passes over a stable sort rather than one composite key, because the two
    halves run in opposite directions and ``datetime`` has no negation.
    """
    by_id = sorted(records, key=lambda record: record.id)
    return sorted(by_id, key=lambda record: record.provenance.last_updated, reverse=True)


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
        self._resource = SuspendableResource()
        # The walk's never-reissued order key (ADR-0114 §1). `_sequence` only ever
        # rises: `delete`, `purge_expired` and `clear` drop entries from `_keys`
        # and none of them touches it, so a number a removed record held is never
        # handed to a later one and an exhausted walk cannot skip that record.
        # Positions are recorded as text, as the real stores record them, so "a
        # position this build cannot use" is one shape across all three.
        self._keys: dict[str, int] = {}
        self._sequence = 0
        self._walks: dict[str, str] = {}

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        The hook ``MemoryStoreContract``'s cancellation case takes (ADR-0060 §3),
        and its input-observation cases with it (ADR-0065 §3), since the fake
        enters the modelled resource at exactly the boundary both clauses turn on:
        every method takes its one observation of its arguments on its first
        executed lines and only then enters. Test-only, and not part of the
        ``MemoryStore`` contract: the Protocol deliberately grows no affordance for
        this, so the suite asks the *subject* it was handed rather than the seam
        every consumer depends on.

        Named for an *operation* rather than a write because the reads enter too
        (#397). It holds whichever call arrives next, so a suite arms it after its
        preconditions have run.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

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

        The copy is taken on the coroutine's **first executed line**, before the
        first ``await``, and nothing downstream reads ``record`` again — the
        returned id included (``core.protocols``' input clause, ADR-0065). The
        copy was already here for post-call isolation; taking it before the
        resource is what closes the *mid-call* window too, so the id returned and
        the row it names can never come from two different versions of one record
        — the shape ``SqliteMemoryStore.add`` snapshots for (ADR-0056).

        **The cross-kind refusal is judged inside the resource**, from the snapshot
        (ADR-0108 §4). Reading stored state is what the persistent store does under
        its connection lock, so a fake judging it outside would certify a consumer
        against a check the production store cannot make there.

        Raises:
            MemoryStoreError: ``record.id`` names a stored record of a different
                ``kind`` (ADR-0108 §4). Nothing is written.
        """
        snapshot = record.model_copy(deep=True)
        async with self._resource.held():
            self._refuse_cross_kind(snapshot)
            self._records[snapshot.id] = snapshot
            self._issue_key(snapshot.id)
        return snapshot.id

    def _refuse_cross_kind(self, record: MemoryRecord) -> None:
        """Refuse an upsert landing on a stored record of a different kind.

        ADR-0108 §4's backstop, on **both** upsert-capable doors — so a consumer
        certified against this fake meets the same refusal the shipped store makes,
        which is the whole reason the fake is canonical (ADR-0026 §4). Presence is
        physical, matching ``INSERT_IF_ABSENT``: an expired or window-closed record
        still occupies its id and still collides.

        A plain ``MemoryStoreError`` and deliberately not
        ``MemoryStoreConflictError``, whose documented remedy is "re-mint and
        retry" — which does not answer a caller that asked to overwrite something
        of a kind it did not expect (ADR-0108 §4, on ADR-0081 §3's reasoning).

        Raises:
            MemoryStoreError: ``record.id`` names a stored record of a different
                ``kind``.
        """
        stored = self._records.get(record.id)
        if stored is not None and stored.kind != record.kind:
            msg = (
                f"cannot write {record.id!r} as a {record.kind} record: "
                f"a {stored.kind} record is already stored under that id"
            )
            raise MemoryStoreError(msg)

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """Apply every write in one atomic unit — all commit, or none do.

        Emulates atomicity the same way the real in-memory store does, so the fake
        honours the contract the durable backend does: the batch is validated up
        front (no repeated id, no ``INSERT_IF_ABSENT`` collision, no cross-kind
        ``UPSERT``) and every mutation is staged, then applied only once every
        check has passed — a mid-batch failure mutates nothing (ADR-0046 §4).

        The whole batch — the caller's ``Sequence`` and each element's mutable
        record — is snapshotted on the **first executed line**, before the first
        ``await``, and every later step reads only that snapshot: the repeated-id
        check, the collision check, what is committed, and the ids returned
        (``core.protocols``' input clause, ADR-0065). A ``MemoryWrite`` being
        ``frozen`` is not a discharge — it holds a record that is not — and
        validating one observation while committing another is exactly how a
        batch passes its duplicate-id check and then writes an id twice
        (ADR-0046 §3). Mirrors ``SqliteMemoryStore.write_atomic``.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id names a
                stored record — physical presence, so an expired or window-closed
                row still collides (ADR-0046 §3). Nothing is written.
            MemoryStoreError: an ``UPSERT`` element's id names a stored record of a
                different ``kind`` (ADR-0108 §4), or the batch names the same id
                twice (ADR-0046 §3). Nothing is written.
        """
        staged = [(write.record.model_copy(deep=True), write.mode) for write in writes]
        ids = [record.id for record, _ in staged]
        if len(set(ids)) != len(ids):
            msg = "an atomic batch may not write the same id twice"
            raise MemoryStoreError(msg)
        async with self._resource.held():
            for record, mode in staged:
                if mode is MemoryWriteMode.INSERT_IF_ABSENT and record.id in self._records:
                    msg = f"cannot insert {record.id!r}: a record with that id is already stored"
                    raise MemoryStoreConflictError(msg)
                # Only an UPSERT can reach a collision past the check above, so
                # this judges exactly the door ADR-0108 §4 exists to close. It runs
                # in the validation pass, before anything is committed, so the
                # refusal mutates nothing.
                self._refuse_cross_kind(record)
            for record, _ in staged:
                self._records[record.id] = record
                self._issue_key(record.id)
        return ids

    def _issue_key(self, record_id: str) -> None:
        """Give a newly stored record its walk position, leaving an upsert's alone.

        An upsert keeps the key it already holds, which is what the persistent
        store's ``rowid`` does on the same path: a record revised in place stays
        where it is in the walk and is not revisited by a cursor that has passed
        it. That is ADR-0111 §2's named limit, and the three stores agree about it
        rather than one of them quietly re-queueing the record.
        """
        if record_id not in self._keys:
            self._sequence += 1
            self._keys[record_id] = self._sequence

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if not readable.

        ``None`` when the record is absent, expired, or not live at now — a closed
        or not-yet-open validity window, both ends (ADR-0045 §6).

        Routed through the modelled resource like every other method: the
        ``sqlite3`` store answers this from under its connection lock, so it is one
        of the lock sites ADR-0060's clause binds (#397).
        """
        async with self._resource.held():
            record = self._records.get(record_id)
            if record is None or not self._is_readable(record, self._now_utc()):
                return None
            # Deep copy so callers cannot mutate stored state — including nested
            # fields like provenance and validity — matching the persistent store
            # (ADR-0007).
            return record.model_copy(deep=True)

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        """Return the readable records among ``record_ids``, keyed by id (ADR-0086 §6).

        One snapshot for the batch: ``record_ids`` is materialised on the first
        executed line — before the resource is entered, which is where ADR-0065
        puts the observation — and the clock is read **once**, so every id is
        judged against a single instant. A missing, expired or not-live id is an
        omission from the mapping, never an error and never a ``None`` value.

        Routed through the modelled resource like every other method, so the
        cancellation clause has a real subject here too (ADR-0060, #397).
        """
        wanted = dict.fromkeys(record_ids)
        if not wanted:
            # No round trip for an empty argument, so the fake reaches its modelled
            # resource exactly where the persistent store reaches its lock — a fake
            # that queued behind a held resource where the real store would not
            # would certify a consumer the real store never blocks (ADR-0026 §7).
            return {}
        async with self._resource.held():
            now = self._now_utc()
            return {
                record_id: record.model_copy(deep=True)
                for record_id in wanted
                if (record := self._records.get(record_id)) is not None
                and self._is_readable(record, now)
            }

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

        ``kinds`` is materialised on the coroutine's **first executed line**, as in
        ``list_beliefs`` below and for the same reason: it is the discharge
        ADR-0065 §3 names second — the caller's ``Sequence`` is observed once,
        before this method enters the modelled resource, and only the copy is read
        afterwards (#436). That ordering is what the suite's read-side
        input-observation case turns on here, so the entry below must stay *after*
        the materialisation.
        """
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        query_terms = {term for term in query.lower().split() if term}
        if limit <= 0 or not query_terms:
            return []
        async with self._resource.held():
            now = self._now_utc()  # one reading for the whole search, not one per record
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
        enough matching records exist. Both read-time axes go through the same
        ``_is_readable`` predicate ``get``/``search`` use, against one clock reading
        for the whole page (ADR-0073 §2).

        Routed through the modelled
        :class:`~ai_assistant.testing.cancellation.SuspendableResource` like the
        fake's writes, because ``SqliteMemoryStore`` answers this from under its
        connection lock and that lock site is one more place the resource could be
        handed over early (#397). An earlier revision of this docstring recorded the
        opposite, on the premise that the shared suite's cancellation case was
        write-scoped; closing #397 removed that premise.

        Both ``Sequence`` filters are materialised on the coroutine's **first
        executed line**, before that entry, and only the copies are read thereafter
        — ADR-0065 §3's second discharge, and the shape ADR-0073 §8 requires of
        every implementation.

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

        async with self._resource.held():
            now = self._now_utc()  # one reading for the whole page
            matched = [
                record
                for record in self._records.values()
                if self._is_readable(record, now)
                and (wanted_bands is None or band_of(record.provenance.source) in wanted_bands)
                and (wanted_kinds is None or record.kind in wanted_kinds)
            ]
        page = _newest_revision_first(matched)[offset : offset + limit]
        # Cleared, not merely absent: a record re-added after a search carries that
        # query's relevance, and nothing was ranked here (ADR-0073 §2).
        return [record.model_copy(update={"score": None}, deep=True) for record in page]

    async def walk_records(self, walk: str, *, limit: int) -> RecordChunk:
        """Read the next chunk of ``walk`` without changing anything (ADR-0114 §1).

        Routed through the modelled resource, like every other read (#397).

        Raises:
            ValueError: ``walk`` is not non-blank encodable text, or ``limit`` is
                not exactly an ``int`` in ``[1, 2**63)``. Both are checked on the
                coroutine's first executed line, before the resource is held, so a
                refused call takes nothing and changes nothing.
            MemoryStoreError: The injected clock's reading is not a conforming one.
        """
        _check_walk_name(walk)
        _check_walk_limit(limit)
        async with self._resource.held():
            now = self._now_utc()
            after = _resume_key(self._walks.get(walk), issued_through=self._sequence)
            # `limit` bounds records *examined*, not records returned: a scan that
            # ran on until it had `limit` eligible records would be unbounded over
            # a long ineligible run, which is the hazard ADR-0111 §4 forbids.
            # Stops at `limit` rather than sorting the whole unwalked tail, so the
            # work does not grow with what is left to walk. `_keys` is already in
            # ascending key order and stays that way: `_issue_key` only appends a
            # fresh, larger key, an upsert leaves an existing entry alone, and a
            # delete disturbs no other.
            examined: list[tuple[int, str]] = []
            for rid, key in self._keys.items():
                if key <= after:
                    continue
                examined.append((key, rid))
                if len(examined) == limit:
                    break
            eligible = [
                self._records[rid].model_copy(deep=True)
                for _, rid in examined
                if self._is_readable(self._records[rid], now)
            ]
            # Absent exactly when nothing was examined — never merely when nothing
            # was eligible, which is how a walk crosses a dead range instead of
            # stalling on it for good.
            position = _mint_position(walk, examined[-1][0]) if examined else None
        return RecordChunk(records=tuple(eligible), position=position)

    async def advance_walk(self, walk: str, *, position: WalkPosition) -> None:
        """Record how far ``walk`` has reached (ADR-0114 §3).

        Raises:
            ValueError: ``walk`` is not non-blank encodable text, or ``position``
                is malformed or was issued for a different walk. Both are checked
                before the resource is held, so every recorded position — this
                walk's and every sibling's — is left exactly as it was.
        """
        _check_walk_name(walk)
        key = _read_position(walk, position)
        async with self._resource.held():
            # Never backwards, and not an error: a walk is at-least-once, so a
            # resumed run can legitimately hold a stale position. Repeated work is
            # the cost; records skipped forever would be the alternative.
            if key > _resume_key(self._walks.get(walk), issued_through=self._sequence):
                self._walks[walk] = str(key)

    async def delete(self, record_id: str) -> bool:
        """Delete one record, returning whether it existed."""
        async with self._resource.held():
            self._keys.pop(record_id, None)
            return self._records.pop(record_id, None) is not None

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Discards every recorded walk position in the same operation (ADR-0114 §4),
        and deliberately does **not** reset ``_sequence``: a walker can be holding
        a chunk's position across this call and will then advance to a position
        discarded here, which is harmless only because every record added
        afterwards is issued a key above it.
        """
        async with self._resource.held():
            count = len(self._records)
            self._records.clear()
            self._keys.clear()
            self._walks.clear()
        return count

    async def export(self) -> list[MemoryRecord]:
        """Return an independent snapshot of every retained (non-expired) record.

        Includes window-closed records: unlike ``get``/``search`` this does not
        filter on the validity window — a superseded belief is retained data a
        data-rights export must keep; only expired records are excluded (ADR-0045
        §6, amending ADR-0007 §3).

        Routed through the modelled resource, like every other read (#397).
        """
        async with self._resource.held():
            now = self._now_utc()
            return [
                r.model_copy(deep=True)
                for r in self._records.values()
                if not self._is_expired(r, now)
            ]

    async def purge_expired(self) -> int:
        """Physically remove expired records, returning the number removed."""
        now = self._now_utc()
        async with self._resource.held():
            expired = [
                rid for rid, record in self._records.items() if self._is_expired(record, now)
            ]
            for rid in expired:
                del self._records[rid]
                self._keys.pop(rid, None)
        return len(expired)
