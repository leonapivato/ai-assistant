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
from ai_assistant.core.errors import (
    MemoryStoreConflictError,
    MemoryStoreError,
    MemoryStoreStaleError,
)
from ai_assistant.core.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryWriteMode,
    NonBlankEncodableText,
    RecordChunk,
    TopicLabel,
    WalkPosition,
    band_of,
    caseless_key,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        BeliefBand,
        MemoryKind,
        MemoryRecord,
        MemoryWrite,
        TimeWindow,
    )
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


def _resume_key(recorded: str | None, *, walk: str, issued_through: int) -> int | None:
    """Read a recorded position back, restarting the walk on anything unusable.

    Absent, unreadable, malformed, bound to another walk, or above every key this
    store has ever issued all mean the same thing: discard and restart from the
    first record, never raise (ADR-0114 §4, ADR-0111 §7).

    ``None`` is "no recorded position" and **no integer stands in for it**: ADR-0114
    §4 refuses a sentinel because a legacy ``rowid`` can be negative, so a walk that
    began at ``0`` would silently skip every record at or below it. What is stored
    is the token rather than the bare key, so a value this build refuses once it
    refuses for good — a raw number would be ignored while it sat above the
    high-water mark and become authoritative once inserts raised that mark past it.
    """
    if recorded is None:
        return None
    try:
        key = _read_position(walk, WalkPosition(token=recorded))
    except ValueError:
        return None
    return None if key > issued_through else key


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


def _selects_nothing(*axes: frozenset[object] | None) -> bool:
    """Whether any applied sequence axis is **empty**, and so selects nothing.

    ADR-0113 §3's convention, which ADR-0237 §2 restates for the three axes it
    adds: ``None`` means the axis is not applied and an empty sequence selects
    nothing. Answered here rather than by an empty ``in`` test per axis so that
    every axis gets the same answer — leaving it to be inherited is how one
    implementation comes to read ``()`` as "no filter", the opposite outcome.

    A read this returns ``True`` for matches nothing **by construction**, so its
    result is empty and ``capped`` is ``False`` and never ``True`` (ADR-0128 §2).

    Args:
        axes: The materialised axes, ``None`` where the axis is not applied.

    Returns:
        Whether at least one applied axis is empty.
    """
    return any(axis is not None and not axis for axis in axes)


#: The refusal ADR-0237 §2 attributes to the type, made whatever a caller passes.
#: A Protocol signature is not a validated model — an ``Annotated`` alias in a
#: method's annotations runs no validator at a normal call — so the type is asked
#: explicitly, and it is *this* type rather than a hand-written check so the form a
#: filter value must take cannot drift from the form a stored label must take
#: (ADR-0213 §3).
_TOPIC_LABEL: Final = TypeAdapter[str](TopicLabel)


def _topic_keys(values: Sequence[str]) -> frozenset[str]:
    """The ``topics`` filter as a comparison set, refusing a non-canonical label.

    ADR-0237 §2: "a ``topics`` value not already in ``TopicLabel``'s canonical form
    is refused by the type". Refused rather than allowed to match nothing, and that
    is not a nicety: an unrefused ``"Health"`` returns an **empty result**, which is
    the one answer ADR-0237 §7 spends four clauses insisting a caller must never
    read as "nothing happened". A caller's typo would be indistinguishable from a
    true absence, on the read whose whole contract is about what an absence means.

    Matching is equality of the stored characters (ADR-0213 §3), so the values need
    no fold — unlike the two person axes — and duplicates collapse into the set.

    Args:
        values: The labels the call named.

    Returns:
        Them, as a set.

    Raises:
        ValueError: If any value is not already in ``TopicLabel``'s canonical form —
            not equal to its own ``str.casefold()``, empty, over-long, carrying
            whitespace other than ``U+0020``, leading or trailing a space, or
            carrying a run of two. Pydantic's ``ValidationError`` is a ``ValueError``,
            which is the class §2 names for the sibling refusal on this parameter.
    """
    return frozenset(_TOPIC_LABEL.validate_python(value) for value in values)


#: The refusal ADR-0237 §2 puts on the two person axes, asked of the declared type
#: rather than hand-written. ``NonBlankEncodableText`` carries **both** halves — it
#: refuses a blank *and* a string with no UTF-8 encoding — and asking the type is
#: what keeps the two from drifting apart: a hand-written blank check let
#: ``"\\ud800"`` through, where the in-memory stores matched nothing and the SQL one
#: raised a raw ``UnicodeEncodeError`` out of its parameter binding, past the
#: ``MemoryStoreError`` boundary the store documents. ADR-0087 §7 rules that "the
#: place a non-encodable value is refused is the type, not the frame", and issue
#: #565 is the same value doing the same thing one seam over.
_PERSON_LABEL: Final = TypeAdapter[str](NonBlankEncodableText)


def _person_keys(argument: str, values: Sequence[str]) -> frozenset[str]:
    """Fold one person-axis filter to ADR-0101 §2's comparison keys, refusing a bad value.

    Duplicated across the two stores and the canonical fake rather than shared,
    exactly as ``_check_page_bounds`` is: ``ai_assistant.testing`` may not import a
    subsystem (golden rule 1). The **fold** is not duplicated — it is
    :func:`~ai_assistant.core.types.caseless_key` in ``core``, because a fold that
    drifted between three implementations would make one call answer differently
    per backend, which is the divergence ADR-0237 §3 borrows an external standard
    to prevent. Neither is the *refusal*: the declared type makes it.

    Duplicates collapse into the set, which is the set semantics ADR-0237 §2 gives
    every sequence axis, and the caller's sequence is read exactly once.

    **The refusal is re-raised naming the parameter**, which is the one thing the
    type cannot say: :func:`~ai_assistant.core.types._rejecting_non_blank`
    deliberately names no field, because three unrelated ones reach it. Here the
    caller needs to know *which* argument it passed badly, and there are two.

    Args:
        argument: The parameter's name, for the refusal message.
        values: The labels the call named.

    Returns:
        Their canonical caseless keys.

    Raises:
        ValueError: If any value is blank or whitespace-only (ADR-0237 §2), or has
            no UTF-8 encoding. A blank is never read as "unstated" and never
            matches a record, so it is refused rather than quietly ignored; an
            unencodable one is refused because the parameter's declared type
            refuses it and because a value that reaches no backend intact must
            fail the same way on every one of them.
    """
    keys: set[str] = set()
    for value in values:
        try:
            checked = _PERSON_LABEL.validate_python(value)
        except ValidationError as exc:
            msg = f"a {argument} value must be non-blank text with a UTF-8 encoding: {exc}"
            raise ValueError(msg) from exc
        keys.add(caseless_key(checked))
    return frozenset(keys)


def _refuse_an_axis_less_select(axes: tuple[object | None, ...]) -> None:
    """Refuse a ``select`` that applies no axis at all (ADR-0237 §4).

    ``select`` is not a second ``list_beliefs``: no value of any axis means
    "everything", so a call naming no criterion is a caller that reached for one
    and gave none. Refusing it is what keeps the two reads from becoming
    substitutes for one another.

    Raises:
        ValueError: If every axis is ``None``.
    """
    if all(axis is None for axis in axes):
        msg = "select applies at least one axis; a call naming none is refused (ADR-0237 §4)"
        raise ValueError(msg)


def _admits(
    record: MemoryRecord,
    *,
    window: TimeWindow | None,
    participants: frozenset[str] | None,
    topics: frozenset[str] | None,
    subjects: frozenset[str] | None,
) -> bool:
    """Whether ``record`` is eligible on all four of ADR-0237 §1's axes.

    Conjunction across the axes, disjunction within each (§2), and each axis reads
    the record's **own stored value** and nothing derived from ``content`` or any
    other span (§1). A record carrying no value on an axis is reached by no filter
    on it — whether the field is empty, unset, or absent from its kind altogether
    (§6) — so the ``occurred_at`` and ``participants`` tests fail closed on every
    kind but the episodic one, and ``about_person``'s on every record that states
    no subject (ADR-0101 §2).

    Args:
        record: The stored record, decoded.
        window: The instant window, or ``None`` where the axis is not applied.
        participants: Caseless keys, or ``None``.
        topics: Labels compared by exact stored characters, or ``None``.
        subjects: Caseless keys for ``about_person``, or ``None``.

    Returns:
        Whether every applied axis admits the record.
    """
    episode = record if isinstance(record, EpisodicMemory) else None
    if window is not None and (episode is None or not window.contains(episode.occurred_at)):
        return False
    if participants is not None and not (
        episode is not None
        and any(caseless_key(person) in participants for person in episode.participants)
    ):
        return False
    if topics is not None and not any(label in topics for label in record.topics):
        return False
    return subjects is None or (
        record.about_person is not None and caseless_key(record.about_person) in subjects
    )


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
    adding a record whose id already exists overwrites it. Beyond the contract it
    can be configured to fail its reads, so a consumer's retrieval-degradation path
    is testable without hand-rolling a raising subclass (issue #105); only the
    behaviour pinned by the shared ``MemoryStore`` conformance suite is part of the
    contract.
    """

    def __init__(self, *, now: Clock = _utcnow, failure: str | None = None) -> None:
        """Create an empty store.

        Args:
            now: Clock used to decide whether a record has expired; injectable for
                deterministic tests. Defaults to the UTC wall clock. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, exactly as the
                real stores are: a fake looser than the contract would certify
                consumers the real implementation rejects (ADR-0026 §7).
            failure: If given, every read that reaches the stored records raises
                ``MemoryStoreError`` with this message instead of answering. It lets
                a consumer exercise the retrieval-failure path ADR-0022 §3 documents
                — a turn that loses memory degrades and says so — against the shared
                fake rather than a bespoke raising subclass (issue #105).

                A message rather than an exception instance, for the reason
                ``FakeContextProvider`` records: an instance parameter would make it
                possible to configure the canonical fake to raise outside the
                contract, and one stored instance re-raised would accumulate a
                traceback across calls. Every call raises a fresh instance.

                **It models the backing being unavailable, so it bites exactly where
                the fake touches its records** — inside the modelled resource,
                *after* the argument checks and after any short-circuit that reads
                nothing (``search`` with an empty query or a non-positive ``limit``,
                ``get_many`` with no ids, ``list_beliefs`` with ``limit=0``). An
                argument the store would refuse anyway is the caller's mistake
                whether or not the backing answers, and a fake that failed a call the
                real store never makes would certify a consumer against fiction
                (ADR-0026 §7).

                **The writes and :meth:`export` are deliberately unaffected.** The
                writes because the parameter names a broken *retrieval* path, and a
                test still has to seed the store it is breaking. ``export`` because
                it is how a test reads the fake's state back: what a degradation path
                owes is that the consumer carried on *and wrote nothing*, and a
                failure that closed the inspection window would make the second half
                unprovable — ``tests/orchestration/test_loop.py`` asserts exactly
                that. It is ADR-0007's data-rights snapshot rather than a retrieval,
                which is the same distinction from the other side.
        """
        self._records: dict[str, MemoryRecord] = {}
        self._clock = checked_clock(now, owner="FakeMemoryStore")
        self._failure = failure
        self._resource = SuspendableResource()
        # The walk's never-reissued order key (ADR-0114 §1). `_sequence` only ever
        # rises: `delete`, `purge_expired` and `clear` drop entries from `_keys`
        # and none of them touches it, so a number a removed record held is never
        # handed to a later one and an exhausted walk cannot skip that record.
        # Positions are recorded as text, as the real stores record them, so "a
        # position this build cannot use" is one shape across all three.
        self._keys: dict[str, int] = {}
        self._sequence = 0
        # The concurrency token's issuer (ADR-0219 §1), on the same footing: it only
        # ever rises, no removal touches it, and `clear` explicitly leaves it — an
        # issuer reset by a bulk erase would reissue every stamp it had handed out,
        # which is the ABA hole the never-reissued clause closes. Counting is the
        # mechanism; §1 forbids any caller reading order or difference off it.
        self._revisions = 0
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

    def _refuse_read(self) -> None:
        """Raise the configured retrieval failure, if one was configured.

        Called on the first line inside the modelled resource by every read that
        reaches the records, so a call against a broken backing is entered and
        *then* fails: it really did reach the store, and ``resource_log`` records
        that it did.

        Raises:
            MemoryStoreError: Carrying the ``failure`` message passed at
                construction, if one was given. A fresh instance per call.
        """
        if self._failure is not None:
            raise MemoryStoreError(self._failure)

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
            self._records[snapshot.id] = self._stamped(snapshot)
            self._issue_key(snapshot.id)
        return snapshot.id

    def _stamped(self, snapshot: MemoryRecord) -> MemoryRecord:
        """The already-detached snapshot, carrying a freshly issued ``revision``.

        ADR-0219 §1's assignment rule on every door that stores a row: the submitted
        value is discarded rather than persisted, and the stamp written is one this
        store has never issued and will never issue again — whatever id it is stored
        at and whatever was stored there before. A fake that resumed a per-id count
        after a delete would certify a consumer against an ABA hole the shipped
        store does not have (ADR-0026 §7).
        """
        self._revisions += 1
        return snapshot.model_copy(update={"revision": self._revisions})

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

        An ``IF_UNCHANGED`` element is judged in that same validation pass, from the
        same snapshot and inside the resource (ADR-0219 §3): the comparison and the
        write are indivisible here because nothing can interleave with a synchronous
        body once the resource is held, which is the fake's counterpart of the
        durable store's ``BEGIN IMMEDIATE``.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id names a
                stored record — physical presence, so an expired or window-closed
                row still collides (ADR-0046 §3). Nothing is written.
            MemoryStoreStaleError: an ``IF_UNCHANGED`` element's id names a stored
                row at a different ``revision``, or names no stored row at all
                (ADR-0219 §3). Nothing is written.
            MemoryStoreError: an ``UPSERT`` or ``IF_UNCHANGED`` element's id names a
                stored record of a different ``kind`` (ADR-0108 §4, ADR-0219 §4), or
                the batch names the same id twice (ADR-0046 §3). Nothing is written.
        """
        staged = [
            (write.record.model_copy(deep=True), write.mode, write.expected_revision)
            for write in writes
        ]
        ids = [record.id for record, _, _ in staged]
        if len(set(ids)) != len(ids):
            msg = "an atomic batch may not write the same id twice"
            raise MemoryStoreError(msg)
        async with self._resource.held():
            for record, mode, expected in staged:
                if mode is MemoryWriteMode.INSERT_IF_ABSENT and record.id in self._records:
                    msg = f"cannot insert {record.id!r}: a record with that id is already stored"
                    raise MemoryStoreConflictError(msg)
                if mode is MemoryWriteMode.IF_UNCHANGED:
                    self._refuse_stale(record.id, expected)
                # Only an UPSERT or an IF_UNCHANGED can reach a collision past the
                # check above, so this judges exactly the doors ADR-0108 §4 and
                # ADR-0219 §4 close. It runs in the validation pass, before anything
                # is committed, so the refusal mutates nothing.
                self._refuse_cross_kind(record)
            for record, _, _ in staged:
                self._records[record.id] = self._stamped(record)
                self._issue_key(record.id)
        return ids

    def _refuse_stale(self, record_id: str, expected: int | None) -> None:
        """Refuse a conditional write whose expectation this store does not meet.

        ADR-0219 §3, judged against the pre-batch state. Presence is *physical*, as
        at every other door: an expired or window-closed row is present and its
        revision is the one compared, which is what lets a window-close be
        conditional (§4). An absent id is the same refusal and not a different one —
        answering a deleted row with a silent no-op would hand the caller exactly the
        healthy result the lost-update race used to hand both writers.

        Raises:
            MemoryStoreStaleError: The id names no stored row, or names one at a
                different ``revision``.
        """
        stored = self._records.get(record_id)
        if stored is None:
            msg = (
                f"cannot write {record_id!r} at revision {expected}: "
                f"no record is stored under that id"
            )
            raise MemoryStoreStaleError(msg)
        if stored.revision != expected:
            msg = (
                f"cannot write {record_id!r} at revision {expected}: "
                f"the stored record is at revision {stored.revision}"
            )
            raise MemoryStoreStaleError(msg)

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

        Raises:
            MemoryStoreError: If the fake was constructed with a ``failure``, or the
                injected clock's reading is not a conforming one.
        """
        async with self._resource.held():
            self._refuse_read()
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

        Raises:
            MemoryStoreError: If the fake was constructed with a ``failure``, or the
                injected clock's reading is not a conforming one. An empty
                ``record_ids`` is answered without reaching either.
        """
        wanted = dict.fromkeys(record_ids)
        if not wanted:
            # No round trip for an empty argument, so the fake reaches its modelled
            # resource exactly where the persistent store reaches its lock — a fake
            # that queued behind a held resource where the real store would not
            # would certify a consumer the real store never blocks (ADR-0026 §7).
            return {}
        async with self._resource.held():
            self._refuse_read()
            now = self._now_utc()
            return {
                record_id: record.model_copy(deep=True)
                for record_id in wanted
                if (record := self._records.get(record_id)) is not None
                and self._is_readable(record, now)
            }

    async def search(  # noqa: PLR0913 — ADR-0237 §1's signature, one keyword per axis
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        occurred_within: TimeWindow | None = None,
        participants: Sequence[str] | None = None,
        topics: Sequence[TopicLabel] | None = None,
        about_person: Sequence[str] | None = None,
    ) -> MemorySearchResult:
        """Return live records matching ``query`` by lexical overlap, best first.

        Relevance is the fraction of query terms that appear as substrings of a
        record's content. Non-matching records, expired records, records not live
        at now (a closed or not-yet-open validity window, both ends — ADR-0045
        §6), an empty query, and a non-positive ``limit`` all yield nothing.

        **Every eligibility predicate binds before the cut** (ADR-0128 §1), which
        this store gets for free: it scores every live record and truncates once, at
        the end, so every predicate below is already upstream of the ``[:limit]``
        and there is no candidate budget an ineligible record could spend.
        ``SqliteMemoryStore`` is where the clause costs something, and the shared
        suite proves it of both.

        **``capped`` is always ``False``** (ADR-0128 §2). The fake has no KNN and so
        no candidate ceiling — nothing but ``limit`` can shorten a result, so every
        short result is the whole eligible set and is certified as such. That is not
        a simplification the fake takes: ``True`` is unreachable here because the
        input that produces it is unconstructable, which is why the shared suite
        **skips** the two ceiling cases against it rather than faking them. The case
        that bites lives in ``tests/memory/test_sqlite_store.py``.

        **Four structured axes join them** (ADR-0237 §1), each reading the
        record's own stored value: the half-open ``occurred_within`` window over
        ``occurred_at``, ``participants`` and ``about_person`` under ADR-0101 §2's
        D145 fold, and ``topics`` by exact stored characters. A record carrying no
        value on an axis is reached by no filter on it (§6). They bind before the
        cut for the reason above, and an empty sequence on any of them selects
        nothing rather than everything (§2).

        Every ``Sequence`` filter is materialised on the coroutine's **first
        executed lines**, as in ``select`` and ``list_beliefs`` below and for the
        same reason: it is the discharge ADR-0065 §3 names second — the caller's
        ``Sequence`` is observed once, before this method enters the modelled
        resource, and only the copy is read afterwards (#436). That ordering is
        what the suite's read-side input-observation cases turn on here, so the
        entry below must stay *after* every materialisation.

        Raises:
            ValueError: If a ``participants`` or ``about_person`` value is blank
                (ADR-0237 §2). Raised before the modelled resource is entered, so
                a refused call reaches no failure the fake was constructed with.
            MemoryStoreError: If the fake was constructed with a ``failure``, or the
                injected clock's reading is not a conforming one. A query with no
                terms, a non-positive ``limit``, or an axis selecting nothing is
                answered without reaching either.
        """
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        wanted_bands = None if bands is None else frozenset(bands)
        wanted_people = None if participants is None else _person_keys("participants", participants)
        wanted_topics = None if topics is None else _topic_keys(topics)
        wanted_subjects = (
            None if about_person is None else _person_keys("about_person", about_person)
        )
        query_terms = {term for term in query.lower().split() if term}
        if (
            limit <= 0
            or not query_terms
            or _selects_nothing(wanted, wanted_bands, wanted_people, wanted_topics, wanted_subjects)
        ):
            return MemorySearchResult(records=())
        async with self._resource.held():
            self._refuse_read()
            now = self._now_utc()  # one reading for the whole search, not one per record
            scored: list[MemoryRecord] = []
            for record in self._records.values():
                if not self._is_readable(record, now) or (
                    wanted is not None and record.kind not in wanted
                ):
                    continue
                if (
                    wanted_bands is not None
                    and band_of(record.provenance.source) not in wanted_bands
                ):
                    continue
                if not _admits(
                    record,
                    window=occurred_within,
                    participants=wanted_people,
                    topics=wanted_topics,
                    subjects=wanted_subjects,
                ):
                    continue
                content = record.content.lower()
                hits = sum(1 for term in query_terms if term in content)
                if hits:
                    scored.append(
                        record.model_copy(update={"score": hits / len(query_terms)}, deep=True)
                    )
        scored.sort(key=lambda record: record.score or 0.0, reverse=True)
        return MemorySearchResult(records=tuple(scored[:limit]))

    async def select(  # noqa: PLR0913 — ADR-0237 §1's signature, one keyword per axis
        self,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        occurred_within: TimeWindow | None = None,
        participants: Sequence[str] | None = None,
        topics: Sequence[TopicLabel] | None = None,
        about_person: Sequence[str] | None = None,
    ) -> MemorySearchResult:
        """Return the records the criteria select, newest write first (ADR-0237 §4).

        The structured read: six axes, a ``limit`` and no query. Filters, orders,
        then cuts, so every axis binds before ``limit``'s cut (§1) — free here, as
        it is for ``search`` above: the fake filters every live record and
        truncates once at the end, so no candidate budget exists for an ineligible
        record to consume.

        **``capped`` is always ``False``** (§7): the fake has no candidate ceiling,
        so a short result is always the whole eligible set. That is not a
        simplification it takes — ``True`` is unreachable because the input that
        produces it is unconstructable, which is why the shared suite skips the
        ceiling case here rather than faking it.

        The order is ``provenance.last_updated`` descending, ties by ``id``
        ascending, and ``score`` is **cleared** on every record (§5).

        Routed through the modelled
        :class:`~ai_assistant.testing.cancellation.SuspendableResource` like every
        other read (#397), with every ``Sequence`` filter materialised before that
        entry — ADR-0065 §3's second discharge.

        Args:
            limit: Maximum number of records to return; ``<= 0`` matches nothing
                and is not refused.
            kinds: Memory kinds to include; ``None`` is every kind, ``()`` none.
            bands: Belief bands to include; ``None`` is every band, ``()`` none.
            occurred_within: The half-open ``[start, end)`` window a record's
                ``occurred_at`` must fall inside; a record carrying none is
                reached by no window.
            participants: Person labels compared by ADR-0101 §2's D145 fold
                against each of a record's own; ``()`` selects nothing.
            topics: Labels compared by exact stored characters; ``()`` selects
                nothing.
            about_person: Subject labels compared by the same fold; a record
                stating no subject is matched by none. ``()`` selects nothing.

        Returns:
            A :class:`~ai_assistant.core.types.MemorySearchResult` holding the
            eligible records in that order, cut to ``limit``, each with ``score``
            cleared — and ``capped=False``.

        Raises:
            ValueError: If the call applies no axis at all, or a ``participants``
                or ``about_person`` value is blank (ADR-0237 §§2, 4). Raised
                before the modelled resource is entered.
            MemoryStoreError: If the fake was constructed with a ``failure``, or
                the injected clock's reading is not conforming. A non-positive
                ``limit``, or an axis selecting nothing, is answered without
                reaching either.
        """
        wanted_kinds = None if kinds is None else frozenset(str(kind) for kind in kinds)
        wanted_bands = None if bands is None else frozenset(bands)
        wanted_people = None if participants is None else _person_keys("participants", participants)
        wanted_topics = None if topics is None else _topic_keys(topics)
        wanted_subjects = (
            None if about_person is None else _person_keys("about_person", about_person)
        )
        _refuse_an_axis_less_select(
            (kinds, bands, occurred_within, participants, topics, about_person)
        )
        if limit <= 0 or _selects_nothing(
            wanted_kinds, wanted_bands, wanted_people, wanted_topics, wanted_subjects
        ):
            return MemorySearchResult(records=())

        async with self._resource.held():
            self._refuse_read()
            now = self._now_utc()  # one reading for the whole read
            matched = [
                record
                for record in self._records.values()
                if self._is_readable(record, now)
                and (wanted_kinds is None or record.kind in wanted_kinds)
                and (wanted_bands is None or band_of(record.provenance.source) in wanted_bands)
                and _admits(
                    record,
                    window=occurred_within,
                    participants=wanted_people,
                    topics=wanted_topics,
                    subjects=wanted_subjects,
                )
            ]
        page = _newest_revision_first(matched)[:limit]
        # Cleared, not merely absent: a record re-added after a search carries that
        # query's relevance, and nothing was ranked here (ADR-0237 §5).
        return MemorySearchResult(
            records=tuple(record.model_copy(update={"score": None}, deep=True) for record in page)
        )

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
            MemoryStoreError: If the fake was constructed with a ``failure``, or the
                injected clock's reading is not conforming. A page that selects
                nothing is answered without reaching either.
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
            self._refuse_read()
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
            MemoryStoreError: The fake was constructed with a ``failure``, or the
                injected clock's reading is not a conforming one.
        """
        _check_walk_name(walk)
        _check_walk_limit(limit)
        async with self._resource.held():
            self._refuse_read()
            now = self._now_utc()
            after = _resume_key(self._walks.get(walk), walk=walk, issued_through=self._sequence)
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
                if after is not None and key <= after:
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
            current = _resume_key(self._walks.get(walk), walk=walk, issued_through=self._sequence)
            if current is None or key > current:
                self._walks[walk] = _mint_position(walk, key).token

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

        It leaves the revision issuer standing too, and that one is a contract
        obligation rather than a local invariant (ADR-0219 §1): ``clear`` destroys
        records and never the issuer, because an issuer reset by a bulk erase would
        reissue every stamp it had already handed out.
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
