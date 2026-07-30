"""A persistent :class:`~ai_assistant.core.protocols.DeferralStore` on SQLite.

Local-first storage (ADR-0002) for ADR-0078's deferred-question queue: the
durable home of a memory proposal the policy ruled ``ASK_USER`` on, which until
this store existed was reported and then dropped.

**Why this module lives in `memory/` while its contract does not.** ADR-0078 §1
rules that ``DeferralStore`` is its *own* Protocol and emphatically not a corner
of the ``MemoryStore`` — what it holds is a question, not a belief of any band —
and that separation is intact: a distinct Protocol exchanging distinct types, with
neither store holding the other. What is shared is a *package*, because the
architecture map (`CLAUDE.md`) names no ``deferrals`` subsystem and inventing one
is an architecture decision owed its own ADR rather than a side effect of an
implementation lane. It is the placement ``conversation_store.py`` already has, for
the same reason. Nothing here imports the memory store, and nothing in the memory
store imports this.

The database file is created with owner-only permissions (ADR-0004 §4): the
proposal carries the user's own words, so this is a Tier 1 store and inherits every
obligation the ``MemoryStore`` carries. Every mutation runs inside one ``BEGIN
IMMEDIATE`` transaction, which is how the admission's atomicity and the two
compare-and-sets hold **across processes** as well as across coroutines on one
loop — a lock inside one engine would not.

**Every deadline is judged by the record, never re-spelled in SQL.** SQL narrows by
*state*, which is exact and cheap; whether a question is answerable, whether its
key still speaks, and whether a sweep may take it are all answered by
``DeferredProposal``'s own predicates. ADR-0078 §2 fixes the half-open boundary
precisely so two backends cannot disagree at the instant they name, and the surest
way to honour that is to have exactly one implementation of it.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import DeferralIdConflictError, DeferralStoreError
from ai_assistant.core.types import (
    TERMINAL_DEFERRAL_STATES,
    DeferralAdmission,
    DeferralAdmissionOutcome,
    DeferralClaim,
    DeferralState,
    DeferredProposal,
    MemoryDecision,
    MemoryUpdateProposal,
    describe_untrusted,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.clock import Clock

_OWNER_ONLY = 0o600

#: One past the largest value a paging argument accepts: the signed 64-bit ceiling
#: a SQLite bind parameter tops out at (ADR-0073 §2), which this store inherits
#: rather than restates. Duplicated in the canonical fake rather than shared, for
#: the reason ``MemoryStore``'s own bound is: ``ai_assistant.testing`` may not
#: import a subsystem (golden rule 1).
_PAGE_BOUND = 2**63

#: How long a question stays answerable when nobody injects a lifetime (ADR-0078
#: §6). **Finite**, and deliberately ``episode_retention``'s own horizon: a
#: deferred question is about a belief, and for an observed one the evidence is
#: episodes on that clock, so a question outliving them would ask the user to
#: adjudicate something the system can no longer explain. ``None`` means "ask me
#: forever" and is the user's deliberate choice.
_DEFAULT_DEFERRAL_TTL = timedelta(days=30)

#: The most answerable questions the queue holds (ADR-0078 §7). Strictly positive:
#: a cap of zero is at capacity before its first admission, so every question would
#: be refused while the system reported health.
_DEFAULT_QUEUE_LIMIT = 50

#: The bounded default both enumerations use (ADR-0073 §2, §8), which keeps an
#: unbounded read of a Tier 1 store from being what a caller gets by saying nothing.
_DEFAULT_PAGE_LIMIT = 50

#: How many times :meth:`SqliteDeferralStore.claim` re-draws a token a live claim
#: already holds before giving up (ADR-0078 §2).
_CLAIM_RETRY_BUDGET = 8

#: Bytes drawn per claim token: 32 bytes is 256 bits, comfortably past ADR-0078
#: §2's 128-bit floor.
_CLAIM_TOKEN_BYTES = 32

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The row shape every read decodes, in one place so the column order and
#: :func:`_deferral_from` cannot drift apart. ``claim_id`` is **not** here: it is a
#: capability, and no read republishes it (ADR-0078 §2).
_COLUMNS = (
    "id, state, deferred_at, retention, expires_at, claimed_at, answered_at, "
    "predecessor_id, successor_id, outcome_record_id, proposal, decision"
)


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    Deliberately duplicated from :mod:`ai_assistant.memory.sqlite_store` rather
    than shared. ADR-0060 refuses a common home for this helper precisely so that
    subsystems depend on the *obligation* and not on one way of meeting it, and
    reaching into another module for a private name would be the wrong way to spell
    "the same shape" in any case.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[Exception] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except Exception as exc:  # relayed to the caller once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _secret_claim_id() -> str:
    """Draw a cryptographically unpredictable claim token (ADR-0078 §2).

    The store's **default**, not merely an injectable seam, and that split is the
    decision: injection exists for determinism in tests, but injection alone would
    let a composition root wire a counter and satisfy every word of "fresh" while
    :meth:`SqliteDeferralStore.interrupted` publishes every claimed question's id.
    A capability anyone can guess is a parameter with extra steps, so a caller has
    to go out of its way to replace this.
    """
    return secrets.token_hex(_CLAIM_TOKEN_BYTES)


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289).

    Integer arithmetic rather than ``datetime.timestamp()``: an IEEE-754 double's
    53-bit mantissa cannot resolve microseconds near the far end of the datetime
    range, and every deadline this store stamps has to stay exact there.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _instant_from(value: object, *, what: str) -> datetime:
    """Rebuild the aware UTC instant a stored microsecond epoch encodes.

    **An exact ``int`` is required, and that is the point.** SQLite's ``INTEGER``
    affinity is a preference rather than a constraint: a ``REAL`` that is not
    losslessly integral stays a ``REAL`` in the column, and ``timedelta`` would
    silently *round* one into a plausible instant — so a corrupt value would read
    back as data instead of as the corruption it is. ``bool`` is an ``int`` subclass
    and is refused with it, since ``True`` is not an epoch.

    Raises:
        DeferralStoreError: If the stored value is not an exact integer, or is
            outside the representable datetime range. Both are store faults, and
            this seam owes its own error rather than a raw ``OverflowError``.
    """
    if type(value) is not int:
        msg = f"a stored {what} is not an integer epoch: {describe_untrusted(value)}"
        raise DeferralStoreError(msg)
    try:
        return _EPOCH + timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored {what} is out of range: {describe_untrusted(value)}"
        raise DeferralStoreError(msg) from exc


def _optional_instant_from(value: object, *, what: str) -> datetime | None:
    """As :func:`_instant_from`, passing a stored ``NULL`` through unchanged."""
    return None if value is None else _instant_from(value, what=what)


def _duration_from(value: object) -> timedelta | None:
    """Rebuild the stored retention duration, or ``None`` for "ask me forever".

    ``None`` is a real value with stated behaviour rather than a gap: a question
    admitted under it never lapses and is never purged (ADR-0078 §6), so a store
    that coerced it to a sentinel far-future instant would disagree with one that
    kept it about whether the question still exists.

    Raises:
        DeferralStoreError: If a stored non-``NULL`` value is not an exact integer
            number of microseconds, or is out of range.
    """
    if value is None:
        return None
    if type(value) is not int:
        msg = f"a stored retention is not an integer duration: {describe_untrusted(value)}"
        raise DeferralStoreError(msg)
    try:
        return timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored retention is out of range: {describe_untrusted(value)}"
        raise DeferralStoreError(msg) from exc


def _text_from(value: object, *, what: str) -> str:
    """Read a stored ``TEXT`` column, refusing anything that is not usable text.

    Every other read reaches a frozen type whose ``Identifier`` refuses the same
    values; the ones this guards — the state name and the two JSON payloads —
    reach a parser first, and coercing a ``BLOB`` with ``str()`` yields a
    plausible-looking ``"b'...'"`` that would surface as a parse failure a long way
    from its cause.

    Raises:
        DeferralStoreError: If the value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored {what} is not usable: {describe_untrusted(value)}"
        raise DeferralStoreError(msg)
    return value


def _optional_text_from(value: object, *, what: str) -> str | None:
    """As :func:`_text_from`, passing a stored ``NULL`` through unchanged."""
    return None if value is None else _text_from(value, what=what)


def _state_from(value: object) -> DeferralState:
    """Read a stored state name as its enum member.

    Raises:
        DeferralStoreError: If the value is not one of the contract's states. A row
            in a state no code knows is corruption, not a state to guess at.
    """
    try:
        return DeferralState(_text_from(value, what="deferral state"))
    except ValueError as exc:
        msg = f"a stored deferral state is not a known state: {describe_untrusted(value)}"
        raise DeferralStoreError(msg) from exc


def _deferral_from(row: Sequence[object]) -> DeferredProposal:
    """Rebuild the frozen record one :data:`_COLUMNS` row encodes.

    Raises:
        DeferralStoreError: If any column is corrupt, or the reassembled record
            violates the type's own invariants — which is a store fault rather
            than a caller's, and is reported as one instead of escaping as a
            ``ValidationError`` no ``AssistantError`` boundary catches.
    """
    try:
        return DeferredProposal(
            id=_text_from(row[0], what="deferral id"),
            state=_state_from(row[1]),
            deferred_at=_instant_from(row[2], what="deferral instant"),
            retention=_duration_from(row[3]),
            expires_at=_optional_instant_from(row[4], what="expiry instant"),
            claimed_at=_optional_instant_from(row[5], what="claim instant"),
            answered_at=_optional_instant_from(row[6], what="answer instant"),
            predecessor_id=_optional_text_from(row[7], what="predecessor id"),
            successor_id=_optional_text_from(row[8], what="successor id"),
            outcome_record_id=_optional_text_from(row[9], what="outcome record id"),
            proposal=MemoryUpdateProposal.model_validate_json(
                _text_from(row[10], what="stored proposal")
            ),
            decision=MemoryDecision.model_validate_json(
                _text_from(row[11], what="stored decision")
            ),
        )
    except ValidationError as exc:
        msg = f"a stored deferral is corrupt: {exc}"
        raise DeferralStoreError(msg) from exc


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    ADR-0073 §2's posture, and the check this backend most needs: a negative bound
    would reach SQLite, which reads ``LIMIT -1`` as *no limit at all*, and an
    over-wide one raises ``OverflowError`` out of the driver.

    **The type is part of the range**, because "a signed 64-bit integer" is what
    the rule is about and the two backends disagree without it: ``LIMIT 1.5``
    reaches SQLite as a datatype error while an in-memory store slices a list
    happily. ``bool`` is refused with the rest — it is an ``int`` subclass, and
    ``limit=True`` is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is beyond
            the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _check_tuning(retention: timedelta | None, queue_limit: object) -> None:
    """Refuse a lifetime or a cap the queue cannot work under (ADR-0078 §2, §7).

    The ``_check_tuning`` arrangement ADR-0022 §4a ratified, and for its reason: a
    bad value here disables a stage while the loop keeps reporting health, so it is
    refused when the store is built rather than per call. Being constructor
    parameters is also what makes each read **once per store** — the other half of
    ADR-0078 §2's rule that live configuration never reaches back into a question
    already asked.

    Raises:
        ValueError: If ``retention`` is set and not strictly positive, or
            ``queue_limit`` is not an ``int`` in ``[1, 2**63)``.
    """
    # The type is checked before the comparison, because `None <= timedelta(0)`
    # raises `TypeError` and this documents `ValueError` for a duration it will not
    # accept — whatever is wrong with it.
    if retention is not None and (
        not isinstance(retention, timedelta) or retention <= timedelta(0)
    ):
        described = describe_untrusted(retention)
        msg = f"retention must be a strictly positive timedelta or None, got {described}"
        raise ValueError(msg)
    _check_page_bound("queue_limit", queue_limit, floor=1)


def _check_terminal_payload(
    state: DeferralState, record_id: str | None, successor_id: str | None
) -> None:
    """Refuse a resolution whose state is not terminal or whose payload is not its.

    Each terminal state requires its own payload and forbids the other's, in the
    shape ``MemoryDecision._outcome_fields_are_consistent`` enforces for a ruling.
    Without it a valid claim can resolve ``ACCEPTED`` naming nothing that was
    written — a terminal state that lies, reached through the one call whose whole
    job is to record what happened. Duplicated in the canonical fake rather than
    shared, for the reason given on :data:`_PAGE_BOUND`.

    Raises:
        ValueError: If ``state`` is not terminal, or the two ids do not match what
            it requires and forbids.
    """
    if state not in TERMINAL_DEFERRAL_STATES:
        msg = f"resolve records a terminal state, got {state.name}"
        raise ValueError(msg)
    if state is DeferralState.ACCEPTED:
        if record_id is None:
            msg = "an ACCEPTED resolution requires record_id: it names what was written"
            raise ValueError(msg)
        if successor_id is not None:
            msg = "an ACCEPTED resolution raised no successor question"
            raise ValueError(msg)
        return
    if state is DeferralState.REDEFERRED:
        if successor_id is None:
            msg = "a REDEFERRED resolution requires successor_id: it names the question it raised"
            raise ValueError(msg)
        if record_id is not None:
            msg = "a REDEFERRED resolution wrote no record"
            raise ValueError(msg)
        return
    if record_id is not None or successor_id is not None:
        msg = f"a {state.name} resolution carries neither a record id nor a successor id"
        raise ValueError(msg)


class SqliteDeferralStore:
    """A persistent ``DeferralStore`` backed by ``sqlite3``."""

    def __init__(
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        retention: timedelta | None = _DEFAULT_DEFERRAL_TTL,
        queue_limit: int = _DEFAULT_QUEUE_LIMIT,
        new_claim_id: Callable[[], str] = _secret_claim_id,
    ) -> None:
        """Open (or create) the queue at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: Clock the store stamps and judges deadlines with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, because this seam
                never reaches a `core` field validator — every reading becomes an
                integer microsecond epoch — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).
            retention: How long an admitted question stays answerable. Read
                **once**, here, and stamped onto each record at admission; no
                operation consults it again, which is what keeps a later
                configuration change from reaching back into a question already
                asked (ADR-0078 §2). ``None`` is the deliberate "ask me forever".
            queue_limit: The most answerable questions the queue holds. Strictly
                positive, with no unlimited spelling (ADR-0078 §7).
            new_claim_id: The injected source :meth:`claim` mints its token from.
                Defaults to :func:`_secret_claim_id`, which a caller has to go out
                of its way to replace.

        Raises:
            ValueError: If ``retention`` is set and not strictly positive, or
                ``queue_limit`` is not an ``int`` in ``[1, 2**63)``. Refused rather
                than clamped, because a zero cap and an unbounded queue break
                ADR-0078's promises in opposite directions.
            DeferralStoreError: If the database cannot be opened or prepared.
        """
        _check_tuning(retention, queue_limit)
        self._clock = checked_clock(now, owner="SqliteDeferralStore")
        self._retention = retention
        self._queue_limit = queue_limit
        self._new_claim_id = new_claim_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error.

        Raises:
            DeferralStoreError: If the database cannot be opened or prepared.
        """
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves a read-then-write compare-and-set open to exactly the
            # interleaving it exists to forbid.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            msg = f"failed to open deferral store at {self._path!r}: {exc}"
            raise DeferralStoreError(msg) from exc
        try:
            # Restricted *before* the first write, not after the schema is built.
            # SQLite copies the database file's mode onto every rollback journal it
            # creates for it, so a journal written while the file still carried the
            # process umask would be world-readable — and an interrupted write
            # leaves that journal on disk holding Tier 1 pages (ADR-0004 §4).
            self._restrict_permissions()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS deferrals("
                "id TEXT PRIMARY KEY, question_key TEXT NOT NULL, state TEXT NOT NULL, "
                "deferred_at INTEGER NOT NULL, retention INTEGER, expires_at INTEGER, "
                "claimed_at INTEGER, answered_at INTEGER, claim_id TEXT, "
                "predecessor_id TEXT, successor_id TEXT, outcome_record_id TEXT, "
                "proposal TEXT NOT NULL, decision TEXT NOT NULL)"
            )
            # The key is *indexed* rather than unique: several finished questions
            # can share one, and only the ones a key still speaks for suppress a new
            # arrival (ADR-0078 §2), which is a predicate the record answers rather
            # than a constraint a column can carry.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS deferrals_key ON deferrals(question_key, state)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS deferrals_order ON deferrals(state, deferred_at, id)"
            )
        except (sqlite3.Error, OSError) as exc:
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open deferral store at {self._path!r}: {exc}"
            raise DeferralStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        if self._path != ":memory:":
            Path(self._path).chmod(_OWNER_ONLY)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # --- internals -----------------------------------------------------------

    def _now(self) -> datetime:
        """The guarded clock's reading, as this store's own error (ADR-0026 §4).

        Raises:
            DeferralStoreError: If the reading is naive, indeterminate, or outside
                the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise DeferralStoreError(str(exc)) from exc

    @contextlib.contextmanager
    def _transaction(self, what: str, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read-then-write mutation
        cannot interleave with another writer's — which is how the admission's
        atomicity and the two compare-and-sets hold **across processes** and not
        merely across coroutines on one loop. ``immediate=False`` is the read form:
        a deferred transaction, so several ``SELECT``s in one block see one
        consistent snapshot rather than two states either side of a racing write.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`defer` refuses a physical
        id collision without leaving anything behind.

        Raises:
            DeferralStoreError: If the backend fails at any point.
        """
        conn = self._conn
        begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
        try:
            conn.execute(begin)
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise DeferralStoreError(msg) from exc
        try:
            yield conn
        except BaseException as exc:
            # `BaseException`, not `Exception`: ADR-0060's resource clause is
            # unconditional, and a transaction left open on the shared connection is
            # a resource held with nothing running that will release it — the next
            # `BEGIN` fails and the store is poisoned for every later caller.
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                msg = f"failed to {what}: {exc}"
                raise DeferralStoreError(msg) from exc
            raise
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            msg = f"failed to {what}: {exc}"
            raise DeferralStoreError(msg) from exc

    @staticmethod
    def _fetch(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        """Run one read on an open connection, translating a backend failure.

        Raises:
            DeferralStoreError: If the store cannot be read.
        """
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise DeferralStoreError(msg) from exc

    def _checked_token(self, value: object) -> str:
        """Refuse a token source that did not return a usable identifier.

        The token is a capability, and a blank or non-``str`` one would be stored as
        a key nothing can present — leaving a claim unresolvable while the call
        reported success. The guard the ``MemoryWriter``'s id factory already
        carries, applied to a second injected source.

        Raises:
            DeferralStoreError: If the source returned anything but a non-blank
                ``str``. Nothing is committed.
        """
        if type(value) is not str or not value.strip():
            msg = f"the claim token source returned an unusable token: {describe_untrusted(value)}"
            raise DeferralStoreError(msg)
        return value.strip()

    def _row(self, conn: sqlite3.Connection, deferral_id: str) -> DeferredProposal | None:
        """The stored record with ``deferral_id``, decoded, or ``None``."""
        rows = self._fetch(
            conn,
            "read a deferral",
            f"SELECT {_COLUMNS} FROM deferrals WHERE id = ?",  # noqa: S608 — a module constant, no input
            (deferral_id,),
        )
        return _deferral_from(rows[0]) if rows else None

    def _in_state(self, conn: sqlite3.Connection, state: DeferralState) -> list[DeferredProposal]:
        """Every stored record in ``state``, oldest first (ADR-0078 §7's order)."""
        rows = self._fetch(
            conn,
            "enumerate deferrals",
            f"SELECT {_COLUMNS} FROM deferrals WHERE state = ? "  # noqa: S608 — a module constant, no input
            f"ORDER BY deferred_at ASC, id ASC",
            (state.value,),
        )
        return [_deferral_from(row) for row in rows]

    def _insert(self, conn: sqlite3.Connection, record: DeferredProposal, key: str) -> None:
        """Write one freshly admitted question."""
        conn.execute(
            "INSERT INTO deferrals(id, question_key, state, deferred_at, retention, expires_at, "
            "claimed_at, answered_at, claim_id, predecessor_id, successor_id, "
            "outcome_record_id, proposal, decision) "
            "VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?)",
            (
                record.id,
                key,
                record.state.value,
                _to_micros(record.deferred_at),
                None if record.retention is None else _duration_micros(record.retention),
                None if record.expires_at is None else _to_micros(record.expires_at),
                record.predecessor_id,
                record.proposal.model_dump_json(),
                record.decision.model_dump_json(),
            ),
        )

    # --- the contract --------------------------------------------------------

    async def defer(
        self,
        *,
        deferral_id: str,
        proposal: MemoryUpdateProposal,
        decision: MemoryDecision,
        predecessor_id: str | None = None,
        successor_to_claim: str | None = None,
    ) -> DeferralAdmission:
        """Admit a question, reporting what happened and which deferral holds it.

        The full contract is on
        :meth:`~ai_assistant.core.protocols.DeferralStore.defer`. What is worth
        saying here is the *order*, because two rules can both fire on one input:
        the exemption is judged first (a bad token against a live parent strands a
        real answer, which is the worst outcome available), then the **physical
        id** (a caller-side minting fault that suppression would hide), then the
        key.

        Raises:
            DeferralIdConflictError: If ``deferral_id`` names a stored row carrying
                a different question, or one whose key no longer speaks for it.
            DeferralStoreError: If the exemption arguments disagree about being
                present, the exemption does not hold against a live parent, or the
                store cannot be written.
            ValueError: If the proposal or the ruling makes the record
                unconstructable; the store is left unchanged.
        """
        if (predecessor_id is None) != (successor_to_claim is None):
            msg = (
                "predecessor_id and successor_to_claim are given together or not at all: "
                "a parent with no token, or a token naming no parent, is a malformed call"
            )
            raise DeferralStoreError(msg)
        now = self._now()
        # Built here, before the store is touched at all, so an inadmissible
        # proposal (a `DataTier.SECRET` one, a ruling that is not `ASK_USER`) leaves
        # the queue unchanged by construction rather than by care.
        # Built with **no** parent link, whatever the caller named. Whether the
        # successor genuinely links is only knowable inside the atomic section — the
        # parent may have been destroyed by the user mid-apply — and ADR-0078 §2 is
        # explicit that a `predecessor_id` naming no stored deferral admits the
        # successor as an ordinary question "linked to nothing". A record carrying a
        # link to a row that no longer exists would claim a lineage nothing can walk,
        # which the surface would then try to resolve and fail.
        candidate = DeferredProposal(
            id=deferral_id,
            proposal=proposal,
            decision=decision,
            state=DeferralState.PENDING,
            deferred_at=now,
            retention=self._retention,
            expires_at=self._expiry_from(now),
        )
        key = proposal.question_key
        async with self._lock:
            return await _run_to_completion(
                self._defer_sync, candidate, key, predecessor_id, successor_to_claim, now
            )

    def _expiry_from(self, now: datetime) -> datetime | None:
        """The answerability deadline for a question admitted at ``now`` (ADR-0078 §2).

        ``None`` under "ask me forever". Otherwise ``now + retention`` — and where
        that is not a representable instant, the admission is refused with **this
        seam's own error**, rather than letting a raw ``OverflowError`` cross a
        boundary that documents ``DeferralStoreError`` and would escape an adapter's
        ``AssistantError`` handler as a traceback.

        Refused here rather than at construction, and that placement is the
        decision: it is **not a property of the tuning alone**. A five-thousand-year
        lifetime yields a perfectly good deadline in 2026 and an unrepresentable one
        in 7026, so whether it works depends on *when* the question is admitted.
        ADR-0022 §4a's argument for refusing at construction covers values that are
        bad whatever the clock says — a non-positive lifetime, a cap of zero — and
        those are refused there; this one cannot honestly join them.

        Raises:
            DeferralStoreError: If the deadline is not representable. Nothing is
                admitted.
        """
        if self._retention is None:
            return None
        try:
            return now + self._retention
        except (OverflowError, ValueError) as exc:
            msg = (
                f"a question admitted at {now.isoformat()} under a lifetime of "
                f"{self._retention} has no representable deadline: the configured "
                f"deferral lifetime is too large for this clock"
            )
            raise DeferralStoreError(msg) from exc

    def _defer_sync(
        self,
        candidate: DeferredProposal,
        key: str,
        predecessor_id: str | None,
        successor_to_claim: str | None,
        now: datetime,
    ) -> DeferralAdmission:
        """One atomic admission: the exemption, the id, the key, the cap, the insert."""
        with self._transaction("admit a deferral") as conn:
            parent = self._validated_parent(conn, predecessor_id, successor_to_claim)
            linked = (
                candidate if parent is None else _transition(candidate, predecessor_id=parent.id)
            )
            admission = self._admit(conn, linked, key, exempt=parent is not None, now=now)
            if parent is not None and admission.deferral is not None:
                conn.execute(
                    "UPDATE deferrals SET successor_id = ? WHERE id = ?",
                    (admission.deferral.id, parent.id),
                )
            return admission

    def _validated_parent(
        self,
        conn: sqlite3.Connection,
        predecessor_id: str | None,
        successor_to_claim: str | None,
    ) -> DeferredProposal | None:
        """Judge the re-deferral exemption, returning the parent it protects.

        ``None`` when there is nothing to protect — either no exemption was claimed,
        or the parent was destroyed by the user mid-apply, in which case the
        successor is admitted as an **ordinary** question and nothing raises: the
        exemption exists to protect a waiting parent and there is none.

        Raises:
            DeferralStoreError: If the parent is alive and the exemption does not
                hold — a token that does not claim it, a parent no longer
                ``APPLYING``, or one that already names a successor. A live parent
                with a bad token would otherwise be left with no ``successor_id`` to
                name and a ``resolve(REDEFERRED)`` that fails forever, so it is
                surfaced rather than absorbed.
        """
        if predecessor_id is None:
            return None
        parent = self._row(conn, predecessor_id)
        if parent is None:
            return None
        described = describe_untrusted(predecessor_id)
        if parent.state is not DeferralState.APPLYING:
            msg = f"the parent deferral {described} is not APPLYING, so no answer is in flight"
            raise DeferralStoreError(msg)
        if self._claim_token(conn, predecessor_id) != successor_to_claim:
            msg = f"the supplied claim token does not claim the parent deferral {described}"
            raise DeferralStoreError(msg)
        if parent.successor_id is not None:
            msg = f"the parent deferral {described} already names a successor"
            raise DeferralStoreError(msg)
        return parent

    def _claim_token(self, conn: sqlite3.Connection, deferral_id: str) -> str | None:
        """The live claim token on ``deferral_id``, read inside the transaction."""
        rows = self._fetch(
            conn,
            "read a claim",
            "SELECT claim_id FROM deferrals WHERE id = ?",
            (deferral_id,),
        )
        if not rows or rows[0][0] is None:
            return None
        return _text_from(rows[0][0], what="claim token")

    def _admit(
        self,
        conn: sqlite3.Connection,
        candidate: DeferredProposal,
        key: str,
        *,
        exempt: bool,
        now: datetime,
    ) -> DeferralAdmission:
        """Insert, suppress or refuse, inside the caller's transaction.

        Raises:
            DeferralIdConflictError: If the id names a different question.
        """
        held = self._row(conn, candidate.id)
        if held is not None:
            if held.proposal.question_key == key and held.speaks_for_its_key_at(now):
                # The one stated exception: an uncertain admission retried under the
                # same id names a question that is still open, so it is the
                # key-idempotent path rather than a minting fault.
                return DeferralAdmission(outcome=DeferralAdmissionOutcome.SUPPRESSED, deferral=held)
            described = describe_untrusted(candidate.id)
            msg = (
                f"the deferral id {described} already names a different question; re-mint and retry"
            )
            raise DeferralIdConflictError(msg)
        speaker = self._speaker_for(conn, key, now)
        if speaker is not None:
            return DeferralAdmission(outcome=DeferralAdmissionOutcome.SUPPRESSED, deferral=speaker)
        if not exempt and self._answerable_count(conn, now) >= self._queue_limit:
            return DeferralAdmission(outcome=DeferralAdmissionOutcome.REFUSED)
        self._insert(conn, candidate, key)
        return DeferralAdmission(outcome=DeferralAdmissionOutcome.ADMITTED, deferral=candidate)

    def _speaker_for(
        self, conn: sqlite3.Connection, key: str, now: datetime
    ) -> DeferredProposal | None:
        """The stored question whose key still speaks for ``key`` at ``now``.

        SQL narrows to the rows carrying the key, in the contract's own order; the
        *reach* of the key is then answered by
        :meth:`~ai_assistant.core.types.DeferredProposal.speaks_for_its_key_at`,
        because that predicate spans three states and two deadlines and re-spelling
        it in SQL is how two conforming stores come to disagree about whether a
        question still exists.
        """
        rows = self._fetch(
            conn,
            "look up a question key",
            f"SELECT {_COLUMNS} FROM deferrals WHERE question_key = ? "  # noqa: S608 — a module constant, no input
            f"ORDER BY deferred_at ASC, id ASC",
            (key,),
        )
        for row in rows:
            record = _deferral_from(row)
            if record.speaks_for_its_key_at(now):
                return record
        return None

    def _answerable_count(self, conn: sqlite3.Connection, now: datetime) -> int:
        """How many questions count against the cap at ``now`` (ADR-0078 §7).

        The **answerable** queue only: lapsed and resolved rows awaiting a sweep do
        not count, so a queue cannot be held shut by questions nobody can answer.
        Judged through the record's own predicate for the reason
        :meth:`_speaker_for` gives.
        """
        return sum(
            1
            for record in self._in_state(conn, DeferralState.PENDING)
            if record.is_answerable_at(now)
        )

    async def get(self, deferral_id: str) -> DeferredProposal | None:
        """Return the deferral with ``deferral_id``, or ``None``, in any state.

        Raises:
            DeferralStoreError: If the store cannot be read, or the row is corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._get_sync, deferral_id)

    def _get_sync(self, deferral_id: str) -> DeferredProposal | None:
        with self._transaction("read a deferral", immediate=False) as conn:
            return self._row(conn, deferral_id)

    async def claim(self, deferral_id: str) -> DeferralClaim | None:
        """Take an answerable question to ``APPLYING`` and mint its token.

        Raises:
            DeferralStoreError: If the bounded re-draw was exhausted against a
                source that keeps returning a token a live claim already holds, if
                the source returned an unusable value, or if the store cannot be
                written. The deferral is left ``PENDING`` and nothing is committed.
        """
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._claim_sync, deferral_id, now)

    def _claim_sync(self, deferral_id: str, now: datetime) -> DeferralClaim | None:
        with self._transaction("claim a deferral") as conn:
            row = self._row(conn, deferral_id)
            if row is None or not row.is_answerable_at(now):
                return None
            token = self._mint_claim_token(conn)
            claimed = _transition(row, state=DeferralState.APPLYING, claimed_at=now)
            conn.execute(
                "UPDATE deferrals SET state = ?, claimed_at = ?, claim_id = ? WHERE id = ?",
                (claimed.state.value, _to_micros(now), token, deferral_id),
            )
            return DeferralClaim(deferral=claimed, claim_id=token)

    def _mint_claim_token(self, conn: sqlite3.Connection) -> str:
        """Draw a token no live claim already holds, bounded.

        A duplicate is not a cosmetic clash: two live claims sharing a token lets
        either holder resolve the other's question or spend its successor exemption,
        which is the whole capability collapsing. Uniqueness is promised among
        **live** claims only — closing the historical case would need a durable
        ledger of every token ever issued, surviving ``delete`` and ``clear``, which
        is storage of exactly what the user asked to destroy.

        Raises:
            DeferralStoreError: If the budget was exhausted; the caller's
                transaction is rolled back, so nothing changed.
        """
        held = {
            _text_from(row[0], what="claim token")
            for row in self._fetch(
                conn,
                "read the live claims",
                "SELECT claim_id FROM deferrals WHERE claim_id IS NOT NULL AND state = ?",
                (DeferralState.APPLYING.value,),
            )
        }
        for _ in range(_CLAIM_RETRY_BUDGET):
            token = self._checked_token(self._new_claim_id())
            if token not in held:
                return token
        msg = (
            f"the claim token source returned a token already held by a live claim "
            f"{_CLAIM_RETRY_BUDGET} times; nothing was claimed"
        )
        raise DeferralStoreError(msg)

    async def pending(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[DeferredProposal]:
        """Enumerate the answerable questions, oldest first.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``.
            DeferralStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._page(DeferralState.PENDING, limit=limit, offset=offset)

    async def interrupted(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[DeferredProposal]:
        """Enumerate the ``APPLYING`` questions, in :meth:`pending`'s order.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``.
            DeferralStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._page(DeferralState.APPLYING, limit=limit, offset=offset)

    async def _page(
        self, state: DeferralState, *, limit: int, offset: int
    ) -> list[DeferredProposal]:
        """One bounded, totally ordered page of the rows in ``state``.

        The two enumerations are **disjoint** by construction: ``PENDING`` is
        further narrowed to the answerable ones and ``APPLYING`` is a different
        state, so no row can appear in both — a store that offered an interrupted
        question among the answerable ones would present a claim that cannot be
        taken.

        Paging is applied **after** the deadline filter rather than in SQL, so
        ``offset`` counts the rows a caller can actually see. A ``LIMIT``/``OFFSET``
        applied before it would page over rows the filter then removes and return
        short pages with gaps.

        Raises:
            ValueError: If either paging argument is out of range or the wrong type.
                Refused **before the first await**, so a bad call reaches no state
                at all.
            DeferralStoreError: If the store cannot be read, or a row is corrupt.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        # One clock reading for the whole page (ADR-0073 §8): a row dropping out
        # mid-scan would otherwise shift every subsequent offset.
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._page_sync, state, limit, offset, now)

    def _page_sync(
        self, state: DeferralState, limit: int, offset: int, now: datetime
    ) -> list[DeferredProposal]:
        with self._transaction("enumerate deferrals", immediate=False) as conn:
            records = self._in_state(conn, state)
            if state is DeferralState.PENDING:
                records = [record for record in records if record.is_answerable_at(now)]
            return records[offset : offset + limit]

    async def resolve(
        self,
        deferral_id: str,
        *,
        claim_id: str | None,
        state: DeferralState,
        record_id: str | None = None,
        successor_id: str | None = None,
    ) -> bool:
        """Record a question's outcome, if this call is the one entitled to.

        Raises:
            ValueError: If ``state`` is not terminal, or the payload is malformed
                for it. Refused before any state is read.
            DeferralStoreError: If the store cannot be written.
        """
        _check_terminal_payload(state, record_id, successor_id)
        now = self._now()
        async with self._lock:
            return await _run_to_completion(
                self._resolve_sync, deferral_id, claim_id, state, record_id, successor_id, now
            )

    def _resolve_sync(  # noqa: PLR0913 — one argument per value the CAS is judged on
        self,
        deferral_id: str,
        claim_id: str | None,
        state: DeferralState,
        record_id: str | None,
        successor_id: str | None,
        now: datetime,
    ) -> bool:
        with self._transaction("resolve a deferral") as conn:
            row = self._row(conn, deferral_id)
            if row is None or not self._may_resolve(conn, row, claim_id, state, successor_id, now):
                return False
            # Revalidated through the record type before anything is written, so an
            # illegal transition raises and rolls back rather than persisting a
            # record no read should ever return.
            _transition(
                row,
                state=state,
                answered_at=now,
                outcome_record_id=record_id,
                successor_id=row.successor_id,
            )
            conn.execute(
                "UPDATE deferrals SET state = ?, answered_at = ?, outcome_record_id = ?, "
                "claim_id = NULL WHERE id = ?",
                (state.value, _to_micros(now), record_id, deferral_id),
            )
            return True

    def _may_resolve(  # noqa: PLR0913 — one argument per value the CAS is judged on
        self,
        conn: sqlite3.Connection,
        row: DeferredProposal,
        claim_id: str | None,
        state: DeferralState,
        successor_id: str | None,
        now: datetime,
    ) -> bool:
        """Whether this call may record ``state`` on ``row`` (ADR-0078 §2, §9)."""
        if claim_id is None:
            # The one unclaimed transition, and it is subject to the deadline too: a
            # question nobody could answer is not rejectable either, or a lapsed row
            # would become a retained REJECTED key that suppresses the next honest
            # proposal.
            return state is DeferralState.REJECTED and row.is_answerable_at(now)
        if row.state is not DeferralState.APPLYING or self._claim_token(conn, row.id) != claim_id:
            return False
        if state is DeferralState.REDEFERRED:
            # Checked against the successor the store itself stamped, rather than
            # trusting the caller to name the right question.
            return row.successor_id == successor_id
        # A row that raised a successor has one outcome available to it, and it is
        # not this one — the record type forbids a successor on every other terminal
        # state, so recording one here would store a contradiction.
        return row.successor_id is None

    async def delete(self, deferral_id: str) -> bool:
        """Destroy one question unconditionally, whatever its state.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        async with self._lock:
            return await _run_to_completion(self._delete_sync, deferral_id)

    def _delete_sync(self, deferral_id: str) -> bool:
        with self._transaction("delete a deferral") as conn:
            return conn.execute("DELETE FROM deferrals WHERE id = ?", (deferral_id,)).rowcount > 0

    async def clear(self) -> int:
        """Destroy every question, whatever its state, and report how many.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the deferral store") as conn:
            return int(conn.execute("DELETE FROM deferrals").rowcount)

    async def export(self) -> list[DeferredProposal]:
        """Return every stored question, in :meth:`pending`'s total order.

        Every state, lapsed and terminal alike — the content is the user's. **No
        claim token appears**, here or on any other read: a capability is not the
        user's data, and an export carrying one would hand the ability to resolve a
        live claim to anything that reads the file.

        Raises:
            DeferralStoreError: If the store cannot be read, or a row is corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._export_sync)

    def _export_sync(self) -> list[DeferredProposal]:
        with self._transaction("export the deferral store", immediate=False) as conn:
            rows = self._fetch(
                conn,
                "export the deferral store",
                f"SELECT {_COLUMNS} FROM deferrals ORDER BY deferred_at ASC, id ASC",  # noqa: S608 — a module constant, no input
            )
            return [_deferral_from(row) for row in rows]

    async def purge(self) -> int:
        """Sweep the rows whose own stamped deadline has passed, and report how many.

        Never an ``APPLYING`` row, at any age: it is the only durable record that an
        answer was begun, and destroying it while its ingest may still be running
        would let the memory write commit against a question that no longer exists.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._purge_sync, now)

    def _purge_sync(self, now: datetime) -> int:
        with self._transaction("purge the deferral store") as conn:
            # `APPLYING` is excluded in SQL because the exclusion is about the
            # *state* and nothing else; the two deadlines are then judged by the
            # record, which is where their one definition lives.
            rows = self._fetch(
                conn,
                "purge the deferral store",
                f"SELECT {_COLUMNS} FROM deferrals WHERE state != ?",  # noqa: S608 — a module constant, no input
                (DeferralState.APPLYING.value,),
            )
            doomed = [
                record.id for record in map(_deferral_from, rows) if record.is_purgeable_at(now)
            ]
            for deferral_id in doomed:
                conn.execute("DELETE FROM deferrals WHERE id = ?", (deferral_id,))
            return len(doomed)


def _duration_micros(duration: timedelta) -> int:
    """Exact integer microseconds for a duration, by the same argument as an instant."""
    return (duration.days * 86_400 + duration.seconds) * 1_000_000 + duration.microseconds


def _transition(row: DeferredProposal, **changes: object) -> DeferredProposal:
    """Apply ``changes`` to ``row`` and **re-run the record's own validator**.

    ``model_copy(update=...)`` deliberately does not revalidate, so a transition
    built with it could persist a record :class:`DeferredProposal` forbids — an
    ``ACCEPTED`` row naming a successor, an ``APPLYING`` one with no ``claimed_at``.
    Revalidating means an illegal transition raises inside the transaction, which
    rolls back, rather than leaving a stored record no read should ever return.
    Duplicated in the canonical fake rather than shared, for the reason given on
    :data:`_PAGE_BOUND`.
    """
    return DeferredProposal.model_validate(row.model_copy(update=changes).model_dump())
