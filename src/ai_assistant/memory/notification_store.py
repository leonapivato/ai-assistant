"""A persistent :class:`~ai_assistant.core.protocols.NotificationStore` on SQLite.

Local-first storage (ADR-0002) for ADR-0130's held notifications: the durable
home of a proposal the policy ruled ``HOLD`` or ``INTERRUPT`` on, together with
the three standing settings §6 tunes and the rate limiter's own spend ledger.

**Why this module lives in `memory/` while its contract does not.** ADR-0130 §9
rules ``NotificationStore`` its own Protocol, exchanging its own types, holding no
memory and held by none — and that separation is intact here: nothing in this
module imports the memory store, and nothing in the memory store imports this.
What is shared is a *package*, because the architecture map (`CLAUDE.md`) names no
``notifications`` subsystem and minting a top-level one is an architecture
decision an ADR makes rather than a side effect of an implementation lane. Every
top-level package this tree has gained was minted by a clause of its own ADR
naming the ``lint-imports`` edit — ``readers`` by ADR-0093 §2, ``evaluation`` by
ADR-0119 §6, ``secret_store`` by ADR-0125 §8 — and ADR-0130 §9 mints none. It is
therefore the placement ``conversation_store.py`` and ``deferral_store.py``
already have, for the reason ``memory/__init__.py`` already records.

The database file is created with owner-only permissions (ADR-0004 §4): a
candidate carries free text a producer wrote to be shown to a person, so this is
a Tier 1 store and inherits every obligation the ``MemoryStore`` carries.

**The ruling happens inside the transaction, and that is the whole of §3.** The
duplicate lookup, the cap check, the budget read, the policy's ruling and the
write of any record are one atomic act: this store opens ``BEGIN IMMEDIATE``,
reads the four facts §5 weighs, awaits the policy *with the write lock
still held*, and writes and commits under the same transaction. Holding a
transaction open across an ``await`` is deliberate rather than incidental — a
read-then-rule-then-write that released between the steps satisfies every word of
§3 except the one that matters, and the three guarantees §3 names (the last unit
of budget, the last free slot under the cap, the same absence of an actionable
record for one key) would each be advisory. The exposure it buys is bounded by
what §4 makes the policy: deterministic, in-process, reading no clock of its own
and consulting no provider (§11), so the section it holds is arithmetic rather
than I/O.

**Every boundary is judged by the record, never re-spelled in SQL.** SQL narrows
by *state* — the two cessation stamps, the presence of a due instant — which is
exact and cheap; whether a record is actionable, whether it has fallen due and
whether a sweep may take it are all answered by ``HeldNotification``'s own
predicates. ADR-0130 §7 fixes those boundaries half-open precisely so two
backends cannot disagree at the instant they name, and the surest way to honour
that is to have exactly one implementation of each.

**The spend ledger is a table of its own, holding instants and nothing else.**
§5 is unconditional that "no spent unit is refunded except by an act that says
so", so the count cannot be derived from the retained records: deriving it would
refund a unit on :meth:`~SqliteNotificationStore.delete`, on
:meth:`~SqliteNotificationStore.clear`, and on a :meth:`~SqliteNotificationStore.purge`
running under a retention horizon shorter than the budget window — the last a
*scheduler's* act, so the bound §5 exists to make computable would widen on a
timer. What is kept is a bare instant: no key, no summary, no class, so it is a
rate limiter's state rather than the user's content, it appears in no export, and
destroying a notification still destroys everything the notification said.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import NotificationStoreError
from ai_assistant.core.types import (
    HeldNotification,
    NotificationCandidate,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    describe_untrusted,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import NotificationPolicy

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same
#: Tier 1 pages the database does (ADR-0004 §4, #490). Duplicated from
#: ``deferral_store`` rather than shared, for the reason ``_transactions.py``
#: records about ``_restrict_permissions`` (#506).
_SIDECARS = ("-journal", "-wal", "-shm")

#: One past the largest value a paging argument accepts: the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2).
_PAGE_BOUND = 2**63

#: The most **actionable** records this store holds (ADR-0130 §7). Strictly
#: positive with no "unlimited" spelling: a cap of zero is at capacity before its
#: first admission.
_DEFAULT_CAP = 100

#: How long a record is kept after it ceases to be actionable (ADR-0130 §7).
#: Deliberately shorter than the deferral queue's thirty days: a question keeps
#: its value until it is answered, a notification about a thing that already
#: happened does not.
_DEFAULT_RETENTION = timedelta(days=7)

#: The bounded default every enumeration here uses (ADR-0073 §2, §8).
_DEFAULT_PAGE_LIMIT = 50

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The row shape every read decodes, in one place so the column order and
#: :func:`_notification_from` cannot drift apart. ``candidate_key`` is **not**
#: here: it is a narrowing key held beside the record and is read back off the
#: candidate itself.
_COLUMNS = (
    "id, candidate, kind, reason, failed, ruled_at, reconsider_at, "
    "admitted_at, retention, dismissed_at, dropped_at"
)

#: The rows a state narrowing calls "not yet ceased by an act". Expiry is
#: deliberately absent: it lives inside the candidate and is judged by
#: :meth:`~ai_assistant.core.types.HeldNotification.is_actionable_at`.
_UNCEASED = "dismissed_at IS NULL AND dropped_at IS NULL"


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    That reasoning bites harder here than anywhere else in the tree, because this
    store's ruling transaction spans three worker hops with an ``await`` of the
    policy between them: a cancellation absorbed anywhere but at the physical
    completion of the running hop would unwind the rollback's own transaction.

    Deliberately duplicated from :mod:`ai_assistant.memory.deferral_store` rather
    than shared. ADR-0060 refuses a common home for this helper precisely so that
    subsystems depend on the *obligation* and not on one way of meeting it, and
    reaching into another module for a private name would be the wrong way to
    spell "the same shape" in any case.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[BaseException] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except BaseException as exc:  # relayed to the caller once the thread has finished
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
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_notification_id() -> str:
    """Draw a record id.

    An **identity rather than a capability**, so this is a plain UUID and not a
    ``secrets`` draw: nothing is authorised by holding a notification's id, every
    read that names one already returns the record beside it, and the engine's
    dismissal and delete surfaces take an id the user was shown.
    """
    return uuid.uuid4().hex


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289).

    Integer arithmetic rather than ``datetime.timestamp()``: an IEEE-754 double's
    53-bit mantissa cannot resolve microseconds near the far end of the datetime
    range, and every instant this store stamps has to stay exact there.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _duration_micros(duration: timedelta) -> int:
    """Exact integer microseconds for a duration, by the same argument as an instant."""
    return (duration.days * 86_400 + duration.seconds) * 1_000_000 + duration.microseconds


def _shift(instant: datetime, by: timedelta) -> datetime | None:
    """``instant + by``, or ``None`` where that is not a representable instant.

    Both callers reach values a *user* chose: ``budget_window`` is a standing
    setting written through the engine surface and bounded only by being strictly
    positive, so ``now - window`` and ``spent + window`` are each one edit away
    from ``OverflowError``. That would escape a seam documenting
    :class:`~ai_assistant.core.errors.NotificationStoreError` as a bare
    arithmetic failure, and each caller has an honest answer for the absent
    instant: a window wider than the epoch prunes nothing, and a unit whose window
    ends beyond the representable range is one time alone will not free (§5).

    Args:
        instant: The instant to move.
        by: How far, positive or negative.

    Returns:
        The moved instant, or ``None`` where it is not representable.
    """
    try:
        return instant + by
    except OverflowError, ValueError:
        return None


def _instant_from(value: object, *, what: str) -> datetime:
    """Rebuild the aware UTC instant a stored microsecond epoch encodes.

    **An exact ``int`` is required, and that is the point.** SQLite's ``INTEGER``
    affinity is a preference rather than a constraint: a ``REAL`` that is not
    losslessly integral stays a ``REAL`` in the column, and ``timedelta`` would
    silently *round* one into a plausible instant — so a corrupt value would read
    back as data instead of as the corruption it is. ``bool`` is an ``int``
    subclass and is refused with it, since ``True`` is not an epoch.

    Raises:
        NotificationStoreError: If the stored value is not an exact integer, or
            is outside the representable datetime range.
    """
    if type(value) is not int:
        msg = f"a stored {what} is not an integer epoch: {describe_untrusted(value)}"
        raise NotificationStoreError(msg)
    try:
        return _EPOCH + timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored {what} is out of range: {describe_untrusted(value)}"
        raise NotificationStoreError(msg) from exc


def _optional_instant_from(value: object, *, what: str) -> datetime | None:
    """As :func:`_instant_from`, passing a stored ``NULL`` through unchanged."""
    return None if value is None else _instant_from(value, what=what)


def _duration_from(value: object) -> timedelta | None:
    """Rebuild the stored retention, or ``None`` for "never purged".

    ``None`` is a real value with stated behaviour rather than a gap (ADR-0130
    §7), so a store that coerced it to a sentinel far-future instant would
    disagree with one that kept it about whether the record still exists.

    Raises:
        NotificationStoreError: If a stored non-``NULL`` value is not an exact
            integer number of microseconds, or is out of range.
    """
    if value is None:
        return None
    if type(value) is not int:
        msg = f"a stored retention is not an integer duration: {describe_untrusted(value)}"
        raise NotificationStoreError(msg)
    try:
        return timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored retention is out of range: {describe_untrusted(value)}"
        raise NotificationStoreError(msg) from exc


def _text_from(value: object, *, what: str) -> str:
    """Read a stored ``TEXT`` column, refusing anything that is not usable text.

    Raises:
        NotificationStoreError: If the value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored {what} is not usable: {describe_untrusted(value)}"
        raise NotificationStoreError(msg)
    return value


def _kind_from(value: object) -> NotificationDispositionKind:
    """Read a stored disposition kind as its enum member.

    Raises:
        NotificationStoreError: If the value names no known kind. A row in a
            state no code knows is corruption, not a state to guess at.
    """
    try:
        return NotificationDispositionKind(_text_from(value, what="disposition kind"))
    except ValueError as exc:
        msg = f"a stored disposition kind is not a known kind: {describe_untrusted(value)}"
        raise NotificationStoreError(msg) from exc


def _condition_from(value: object) -> NotificationCondition:
    """Read one stored condition name as its enum member.

    Raises:
        NotificationStoreError: If the value names no known condition.
    """
    try:
        return NotificationCondition(_text_from(value, what="ruling condition"))
    except ValueError as exc:
        msg = f"a stored ruling condition is not a known condition: {describe_untrusted(value)}"
        raise NotificationStoreError(msg) from exc


def _failed_from(value: object) -> tuple[NotificationCondition, ...]:
    """Rebuild the ordered failed set §6 reads when a standing setting changes.

    Stored as a JSON array rather than as a delimited string, so a condition name
    can never be split by a separator that happens to appear in it.

    Raises:
        NotificationStoreError: If the column is not a JSON array of known
            condition names.
    """
    text = _text_from(value, what="failed set")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"a stored failed set is not readable JSON: {describe_untrusted(text)}"
        raise NotificationStoreError(msg) from exc
    if not isinstance(decoded, list):
        msg = f"a stored failed set is not a JSON array: {describe_untrusted(decoded)}"
        raise NotificationStoreError(msg)
    return tuple(_condition_from(entry) for entry in decoded)


def _failed_json(failed: Sequence[NotificationCondition]) -> str:
    """The stored form of a failed set."""
    return json.dumps([condition.value for condition in failed])


def _notification_from(row: Sequence[object]) -> HeldNotification:
    """Rebuild the frozen record one :data:`_COLUMNS` row encodes.

    Raises:
        NotificationStoreError: If any column is corrupt, or the reassembled
            record violates the type's own invariants — which is a store fault
            rather than a caller's, and is reported as one instead of escaping as
            a ``ValidationError`` no ``AssistantError`` boundary catches.
    """
    try:
        return HeldNotification(
            id=_text_from(row[0], what="notification id"),
            candidate=NotificationCandidate.model_validate_json(
                _text_from(row[1], what="stored candidate")
            ),
            kind=_kind_from(row[2]),
            reason=_condition_from(row[3]),
            failed=_failed_from(row[4]),
            ruled_at=_instant_from(row[5], what="ruling instant"),
            reconsider_at=_optional_instant_from(row[6], what="reconsideration instant"),
            admitted_at=_instant_from(row[7], what="admission instant"),
            retention=_duration_from(row[8]),
            dismissed_at=_optional_instant_from(row[9], what="dismissal instant"),
            dropped_at=_optional_instant_from(row[10], what="drop instant"),
        )
    except ValidationError as exc:
        msg = f"a stored notification is corrupt: {exc}"
        raise NotificationStoreError(msg) from exc


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    ADR-0073 §2's posture, and the check this backend most needs: a negative
    bound would reach SQLite, which reads ``LIMIT -1`` as *no limit at all*, and
    an over-wide one raises ``OverflowError`` out of the driver. **The type is
    part of the range**, because "a signed 64-bit integer" is what the rule is
    about and the two backends disagree without it. ``bool`` is refused with the
    rest — it is an ``int`` subclass, and ``limit=True`` is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _check_tuning(retention: timedelta | None, cap: object) -> None:
    """Refuse a retention or a cap the store cannot work under (ADR-0130 §7).

    The ``_check_tuning`` arrangement ADR-0022 §4a ratified, and for its reason: a
    bad value here disables a stage while the loop keeps reporting health, so it
    is refused when the store is built rather than per admission. Being
    constructor parameters is also what makes the retention read **once per
    store** — the other half of §7's rule that a stamped duration is never
    consulted from the setting afterwards.

    Raises:
        ValueError: If ``retention`` is set and not strictly positive, or ``cap``
            is not an ``int`` in ``[1, 2**63)``.
    """
    # The type is checked before the comparison, because `None <= timedelta(0)`
    # raises `TypeError` and this documents `ValueError` for a duration it will
    # not accept — whatever is wrong with it.
    if retention is not None and (
        not isinstance(retention, timedelta) or retention <= timedelta(0)
    ):
        described = describe_untrusted(retention)
        msg = f"retention must be a strictly positive timedelta or None, got {described}"
        raise ValueError(msg)
    _check_page_bound("cap", cap, floor=1)


def _classes_reaching(
    previous: NotificationPreferences,
    current: NotificationPreferences,
    reach: NotificationReach,
) -> frozenset[str]:
    """The classes the write moved *to* ``reach`` from something else.

    Duplicated in the canonical fake rather than shared: ``ai_assistant.testing``
    may not import a subsystem (golden rule 1), and ``lint-imports`` fails the
    gate on the edge rather than merely discouraging it.

    Args:
        previous: The settings before the write.
        current: The settings after it.
        reach: The level to look for.

    Returns:
        The class names whose reach changed to ``reach``.
    """
    named = {row.notification_class for row in previous.reaches} | {
        row.notification_class for row in current.reaches
    }
    return frozenset(
        name
        for name in named
        if current.reach_for(name) is reach and previous.reach_for(name) is not reach
    )


def _conditions_a_change_removes(
    previous: NotificationPreferences, current: NotificationPreferences
) -> frozenset[NotificationCondition]:
    """The failed conditions this write could remove, other than the reach one.

    §6 stamps a due instant onto every actionable held record whose *failed set*
    holds a condition the change could remove — the whole set, never the first
    reason alone, which is what buys the user the hours they just paid for when a
    record failed two conditions and the change removed the second.

    Args:
        previous: The settings before the write.
        current: The settings after it.

    Returns:
        The conditions to look for in a record's failed set.
    """
    removable: set[NotificationCondition] = set()
    if previous.quiet_windows != current.quiet_windows:
        removable.add(NotificationCondition.QUIET_WINDOW)
    if (previous.interruption_budget, previous.budget_window) != (
        current.interruption_budget,
        current.budget_window,
    ):
        removable.add(NotificationCondition.BUDGET)
    return frozenset(removable)


@dataclass(frozen=True, slots=True)
class _StoreFacts:
    """The four store-side facts §5 weighs, plus the settings in force.

    Read inside the ruling transaction and handed straight to the policy, so no
    window exists between reading the state and writing the record it was ruled
    against.

    Attributes:
        preferences: The standing settings, defaulted where nothing is held.
        duplicate: Whether an actionable record carries this candidate's key.
        at_cap: Whether the store holds its cap of actionable records.
        budget_spent: ``INTERRUPT`` rulings recorded inside the budget window.
        budget_frees_at: When that window next frees a unit, or ``None``.
    """

    preferences: NotificationPreferences
    duplicate: bool
    at_cap: bool
    budget_spent: int
    budget_frees_at: datetime | None


class SqliteNotificationStore:
    """A persistent ``NotificationStore`` backed by ``sqlite3``."""

    def __init__(
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        retention: timedelta | None = _DEFAULT_RETENTION,
        cap: int = _DEFAULT_CAP,
        new_id: Callable[[], str] = _new_notification_id,
    ) -> None:
        """Open (or create) the notification store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: Clock the store stamps and judges instants with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, because this seam
                never reaches a `core` field validator — every reading becomes an
                integer microsecond epoch — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).
            retention: How long a record is kept after it ceases to be
                actionable. Read **once**, here, and stamped onto each record at
                admission; no operation consults it again, which is what keeps a
                later configuration change from reaching back into a record
                already admitted (ADR-0130 §7). ``None`` means never purged.
            cap: The most **actionable** records this store holds. Strictly
                positive, with no unlimited spelling (§7).
            new_id: The record-id source. The store mints every id and no caller
                supplies one, so this exists for determinism in tests rather than
                as a capability seam.

        Raises:
            ValueError: If ``retention`` is set and not strictly positive, or
                ``cap`` is not an ``int`` in ``[1, 2**63)``. Refused rather than
                clamped, because a zero cap and an unbounded store break
                ADR-0130's promises in opposite directions.
            NotificationStoreError: If the database cannot be opened or prepared.
        """
        _check_tuning(retention, cap)
        self._clock = checked_clock(now, owner="SqliteNotificationStore")
        self._retention = retention
        self._cap = cap
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error.

        Raises:
            NotificationStoreError: If the database cannot be opened or prepared.
        """
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves §3's read-rule-write open to exactly the interleaving
            # it exists to forbid.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            msg = f"failed to open notification store at {self._path!r}: {exc}"
            raise NotificationStoreError(msg) from exc
        try:
            # Restricted *before* the first write, not after the schema is built:
            # SQLite copies the database file's mode onto every rollback journal
            # it creates for it, and an interrupted write leaves that journal on
            # disk holding Tier 1 pages (ADR-0004 §4).
            self._restrict_permissions()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notifications("
                "id TEXT PRIMARY KEY, candidate_key TEXT NOT NULL, candidate TEXT NOT NULL, "
                "kind TEXT NOT NULL, reason TEXT NOT NULL, failed TEXT NOT NULL, "
                "ruled_at INTEGER NOT NULL, reconsider_at INTEGER, admitted_at INTEGER NOT NULL, "
                "retention INTEGER, dismissed_at INTEGER, dropped_at INTEGER)"
            )
            # The key is *indexed* rather than unique: several records may share
            # one over time, and only an **actionable** one suppresses a new
            # arrival (ADR-0130 §7, §8) — a predicate the record answers rather
            # than a constraint a column can carry.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS notifications_key ON notifications(candidate_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS notifications_order ON notifications(admitted_at, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS notifications_due ON notifications(reconsider_at, id)"
            )
            # One row, holding the whole preferences value: §6's write replaces
            # what is held rather than merging into it, and the contract is
            # explicit that the last write wins.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notification_preferences("
                "id INTEGER PRIMARY KEY CHECK(id = 1), value TEXT NOT NULL)"
            )
            # The rate limiter's own state, and nothing of the user's content.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notification_interruptions(spent_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS notification_interruptions_at "
                "ON notification_interruptions(spent_at)"
            )
        except (sqlite3.Error, OSError) as exc:
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open notification store at {self._path!r}: {exc}"
            raise NotificationStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — a cleanly
        closed database has none of them — so absence is tolerated one name at a
        time. A *symlink* under a sidecar's name is skipped rather than followed:
        ``chmod`` follows links, so restricting one would silently narrow a file
        that holds none of this store's data. SQLite does not follow such a link
        either, so nothing is stranded by skipping it; the argument is
        ``SqliteDeferralStore._restrict_permissions``' in full.

        A no-op in memory, where there is no file to restrict.
        """
        if self._path == ":memory:":
            return
        database = Path(self._path)
        database.chmod(_OWNER_ONLY)
        for suffix in _SIDECARS:
            sidecar = database.with_name(database.name + suffix)
            if sidecar.is_symlink():
                continue
            with contextlib.suppress(FileNotFoundError):
                sidecar.chmod(_OWNER_ONLY)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # --- internals -----------------------------------------------------------

    @property
    def cap(self) -> int:
        """The most **actionable** records this store holds (ADR-0130 §7)."""
        return self._cap

    def _now(self) -> datetime:
        """The guarded clock's reading, as this store's own error (ADR-0026 §4).

        Raises:
            NotificationStoreError: If the reading is naive, indeterminate, or
                outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise NotificationStoreError(str(exc)) from exc

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so §3's read-then-rule-then-write
        cannot interleave with another writer's — which is how the atomicity holds
        **across processes** and not merely across coroutines on one loop.
        ``immediate=False`` is the read form: a deferred transaction, so several
        ``SELECT`` statements in one block see one consistent snapshot.

        Raises:
            NotificationStoreError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=NotificationStoreError, immediate=immediate)

    @contextlib.asynccontextmanager
    async def _ruling_transaction(self, what: str) -> AsyncIterator[None]:
        """Hold one ``IMMEDIATE`` transaction open across the policy's ruling (§3).

        The transaction spans three worker hops — read the facts, ``await`` the
        ruling, write the record — because §3 requires them to be **one atomic
        act in the store**. Every hop runs on a worker thread through
        :func:`_run_to_completion`, including the rollback, so a cancellation
        arriving mid-block cannot unwind while the connection is in use.

        The block's own failure is re-raised after the rollback, unchanged unless
        it is a backend fault, which becomes this seam's error.

        Args:
            what: What the caller is doing, read as the tail of ``failed to {what}``.

        Yields:
            Nothing; the connection is this store's own.

        Raises:
            NotificationStoreError: If the backend fails opening, running or
                committing the transaction.
        """
        await _run_to_completion(self._begin_sync, what)
        try:
            yield
        except BaseException as exc:
            await _run_to_completion(self._rollback_sync)
            if isinstance(exc, sqlite3.Error):
                msg = f"failed to {what}: {exc}"
                raise NotificationStoreError(msg) from exc
            raise
        await _run_to_completion(self._commit_sync, what)

    def _begin_sync(self, what: str) -> None:
        """Open the write transaction.

        Raises:
            NotificationStoreError: If the backend refuses.
        """
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise NotificationStoreError(msg) from exc

    def _rollback_sync(self) -> None:
        """Abandon the open transaction, absorbing a backend failure.

        A rollback that itself fails must not replace the failure that caused it;
        the connection is poisoned either way and the caller's exception is the
        one worth seeing.
        """
        with contextlib.suppress(sqlite3.Error):
            self._conn.execute("ROLLBACK")

    def _commit_sync(self, what: str) -> None:
        """Commit the open transaction, rolling back if the commit itself fails.

        Raises:
            NotificationStoreError: If the backend refuses.
        """
        try:
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._rollback_sync()
            msg = f"failed to {what}: {exc}"
            raise NotificationStoreError(msg) from exc

    @staticmethod
    def _fetch(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        """Run one read on an open connection, translating a backend failure.

        Raises:
            NotificationStoreError: If the store cannot be read.
        """
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise NotificationStoreError(msg) from exc

    def _row(self, conn: sqlite3.Connection, notification_id: str) -> HeldNotification | None:
        """The stored record with ``notification_id``, decoded, or ``None``."""
        rows = self._fetch(
            conn,
            "read a notification",
            f"SELECT {_COLUMNS} FROM notifications WHERE id = ?",  # noqa: S608 — a module constant, no input
            (notification_id,),
        )
        return _notification_from(rows[0]) if rows else None

    def _all(self, conn: sqlite3.Connection) -> list[HeldNotification]:
        """Every stored record, oldest first (ADR-0078 §7's ordering, via §7)."""
        rows = self._fetch(
            conn,
            "enumerate notifications",
            f"SELECT {_COLUMNS} FROM notifications ORDER BY admitted_at ASC, id ASC",  # noqa: S608 — a module constant, no input
        )
        return [_notification_from(row) for row in rows]

    def _actionable(self, conn: sqlite3.Connection, now: datetime) -> list[HeldNotification]:
        """The population the cap counts and §8's duplicate rule reads (§7).

        SQL narrows to the rows no *act* has ceased; expiry is then judged by the
        record's own predicate, because §7 fixes that boundary half-open and
        re-spelling it here is how two conforming stores come to disagree about
        whether a record is still actionable.
        """
        rows = self._fetch(
            conn,
            "enumerate actionable notifications",
            f"SELECT {_COLUMNS} FROM notifications WHERE {_UNCEASED} "  # noqa: S608 — module constants, no input
            f"ORDER BY admitted_at ASC, id ASC",
        )
        return [record for record in map(_notification_from, rows) if record.is_actionable_at(now)]

    def _is_duplicate(self, conn: sqlite3.Connection, key: str, now: datetime) -> bool:
        """Whether an **actionable** record already carries this key (§8)."""
        rows = self._fetch(
            conn,
            "look up a candidate key",
            f"SELECT {_COLUMNS} FROM notifications "  # noqa: S608 — module constants, no input
            f"WHERE candidate_key = ? AND {_UNCEASED}",
            (key,),
        )
        return any(record.is_actionable_at(now) for record in map(_notification_from, rows))

    def _fresh_id(self, conn: sqlite3.Connection) -> str:
        """Draw a record id, refusing one this store already holds.

        **A store that overwrote a record here would lose one silently**, and the
        two dispositions would name the same id — which is ``DeferralStore.defer``'s
        argument for making a present id "a hard error, not an overwrite". A
        collision is the *store's* fault and never a caller's, ids being minted
        here, so it carries this seam's error rather than a ``ValueError``.

        Raises:
            NotificationStoreError: If the id source returns something blank, not
                a ``str``, or already present.
        """
        record_id = self._new_id()
        if not isinstance(record_id, str) or not record_id.strip():
            msg = (
                f"the notification store's id source returned "
                f"{describe_untrusted(record_id)}, which is not an identifier"
            )
            raise NotificationStoreError(msg)
        held = self._fetch(
            conn,
            "check a notification id",
            "SELECT 1 FROM notifications WHERE id = ?",
            (record_id,),
        )
        if held:
            msg = (
                f"the notification store's id source returned {record_id!r}, which a "
                f"stored record already holds: admitting over it would lose that record "
                f"and leave two dispositions naming one id"
            )
            raise NotificationStoreError(msg)
        return record_id

    def _preferences_row(self, conn: sqlite3.Connection) -> NotificationPreferences:
        """The standing settings in force, defaulted where nothing is held (§6).

        Raises:
            NotificationStoreError: If the stored value is corrupt.
        """
        rows = self._fetch(
            conn,
            "read the notification preferences",
            "SELECT value FROM notification_preferences WHERE id = 1",
        )
        if not rows:
            return NotificationPreferences()
        try:
            return NotificationPreferences.model_validate_json(
                _text_from(rows[0][0], what="stored preferences")
            )
        except ValidationError as exc:
            msg = f"the stored notification preferences are corrupt: {exc}"
            raise NotificationStoreError(msg) from exc

    def _budget(
        self, conn: sqlite3.Connection, preferences: NotificationPreferences, now: datetime
    ) -> tuple[int, datetime | None]:
        """The two budget facts §5's conjunctive clause reads (§6).

        Entries outside the window in force are **deleted** rather than merely
        skipped, which is what keeps the ledger bounded by the window rather than
        by uptime — and widening the budget window is the "act that says so" §5
        leaves room for, the user asking to be interrupted more being the one
        party entitled to grant it.

        Args:
            conn: The open transaction.
            preferences: The settings whose window and budget are in force.
            now: The ruling instant.

        Returns:
            How many units are spent inside the window, and when it next frees
            one — ``None`` where time alone will not.
        """
        window = preferences.budget_window
        floor = _shift(now, -window)
        if floor is not None:
            conn.execute(
                "DELETE FROM notification_interruptions WHERE spent_at <= ?", (_to_micros(floor),)
            )
        spent = [
            _instant_from(row[0], what="interruption instant")
            for row in self._fetch(
                conn,
                "read the interruption budget",
                "SELECT spent_at FROM notification_interruptions ORDER BY spent_at ASC",
            )
        ]
        budget = preferences.interruption_budget
        frees_at: datetime | None = None
        if budget > 0 and len(spent) >= budget:
            frees_at = _shift(spent[len(spent) - budget], window)
        return len(spent), frees_at

    def _facts(self, conn: sqlite3.Connection, key: str | None, now: datetime) -> _StoreFacts:
        """Read everything §5 weighs that is not the candidate itself.

        Args:
            conn: The open ruling transaction.
            key: The offered candidate's key, or ``None`` for a reconsideration —
                which is not an offer, never matches itself, and already holds
                its slot under the cap (§5).
            now: The ruling instant.

        Returns:
            The facts, ready to hand to the policy.
        """
        preferences = self._preferences_row(conn)
        spent, frees_at = self._budget(conn, preferences, now)
        return _StoreFacts(
            preferences=preferences,
            duplicate=key is not None and self._is_duplicate(conn, key, now),
            at_cap=key is not None and len(self._actionable(conn, now)) >= self._cap,
            budget_spent=spent,
            budget_frees_at=frees_at,
        )

    def _record_spend(self, conn: sqlite3.Connection, ruling: NotificationDisposition) -> None:
        """Note a unit spent, if this ruling spent one (ADR-0130 §5).

        A unit is spent when an ``INTERRUPT`` disposition is **recorded**, never
        when contact is attempted and never when it succeeds — and a
        reconsideration ruled ``INTERRUPT`` spends one like any other ruling.
        """
        if ruling.kind is NotificationDispositionKind.INTERRUPT:
            conn.execute(
                "INSERT INTO notification_interruptions(spent_at) VALUES(?)",
                (_to_micros(ruling.ruled_at),),
            )

    def _write(self, conn: sqlite3.Connection, record: HeldNotification) -> None:
        """Insert or replace one record, in the one column order this store uses."""
        conn.execute(
            "INSERT OR REPLACE INTO notifications(id, candidate_key, candidate, kind, reason, "
            "failed, ruled_at, reconsider_at, admitted_at, retention, dismissed_at, dropped_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.candidate.candidate_key,
                record.candidate.model_dump_json(),
                record.kind.value,
                record.reason.value,
                _failed_json(record.failed),
                _to_micros(record.ruled_at),
                None if record.reconsider_at is None else _to_micros(record.reconsider_at),
                _to_micros(record.admitted_at),
                None if record.retention is None else _duration_micros(record.retention),
                None if record.dismissed_at is None else _to_micros(record.dismissed_at),
                None if record.dropped_at is None else _to_micros(record.dropped_at),
            ),
        )

    # --- the contract --------------------------------------------------------

    async def admit(
        self, candidate: NotificationCandidate, *, policy: NotificationPolicy
    ) -> NotificationDisposition:
        """Rule on an offered candidate and record the ruling — atomically (§3).

        Raises:
            NotificationStoreError: If the clock's reading is unusable, the id
                source returns an unusable id, or the store cannot be read or
                written. Nothing is committed by a failed admission — no record,
                and **no unit of budget**.
        """
        now = self._now()
        async with self._lock, self._ruling_transaction("admit a notification"):
            record_id, facts = await _run_to_completion(self._admit_facts, candidate, now)
            ruling = await policy.rule(
                candidate,
                notification_id=record_id,
                preferences=facts.preferences,
                now=now,
                duplicate=facts.duplicate,
                at_cap=facts.at_cap,
                budget_spent=facts.budget_spent,
                budget_frees_at=facts.budget_frees_at,
            )
            return await _run_to_completion(self._admit_write, candidate, ruling, record_id, now)

    def _admit_facts(
        self, candidate: NotificationCandidate, now: datetime
    ) -> tuple[str, _StoreFacts]:
        """Mint the id and read the four facts, inside the open transaction."""
        record_id = self._fresh_id(self._conn)
        return record_id, self._facts(self._conn, candidate.candidate_key, now)

    def _admit_write(
        self,
        candidate: NotificationCandidate,
        ruling: NotificationDisposition,
        record_id: str,
        now: datetime,
    ) -> NotificationDisposition:
        """Record what was ruled, inside the same transaction the facts were read in.

        **A ``DROP`` writes no durable record** (§8), and the disposition returned
        for one carries no ``notification_id``: there is no record to name.

        Raises:
            ValueError: If the ruling and the candidate make an unconstructable
                record. Raised **before** anything is written, so a record the
                type refuses leaves no spent unit behind it (§5), and the
                enclosing transaction rolls back.
        """
        if ruling.kind is NotificationDispositionKind.DROP:
            return ruling.model_copy(update={"notification_id": None})
        # Built before anything is committed, for the reason above.
        record = HeldNotification(
            id=record_id,
            candidate=candidate,
            kind=ruling.kind,
            reason=ruling.reason,
            failed=ruling.failed,
            ruled_at=now,
            reconsider_at=ruling.reconsider_at,
            admitted_at=now,
            retention=self._retention,
        )
        self._record_spend(self._conn, ruling)
        self._write(self._conn, record)
        return ruling

    async def reconsider(
        self, notification_id: str, *, policy: NotificationPolicy
    ) -> NotificationDisposition | None:
        """Re-rule one held record that has fallen due, in place (§5).

        Returns:
            The fresh disposition, or ``None`` where the id named nothing, or
            named a record that is not actionable or has not fallen due.

        Raises:
            NotificationStoreError: If the clock's reading is unusable, or the
                store cannot be read or written.
        """
        now = self._now()
        async with self._lock, self._ruling_transaction("reconsider a notification"):
            held = await _run_to_completion(self._reconsider_facts, notification_id, now)
            if held is None:
                return None
            record, facts = held
            ruling = await policy.rule(
                record.candidate,
                notification_id=record.id,
                preferences=facts.preferences,
                now=now,
                # A reconsideration is not an offer: it never matches itself
                # (§5), and the record already holds its slot under the cap.
                duplicate=facts.duplicate,
                at_cap=facts.at_cap,
                budget_spent=facts.budget_spent,
                budget_frees_at=facts.budget_frees_at,
            )
            return await _run_to_completion(self._reconsider_write, record, ruling, now)

    def _reconsider_facts(
        self, notification_id: str, now: datetime
    ) -> tuple[HeldNotification, _StoreFacts] | None:
        """The due record and the facts to re-rule it against, or ``None``."""
        record = self._row(self._conn, notification_id)
        if record is None or not record.is_due_at(now):
            return None
        return record, self._facts(self._conn, None, now)

    def _reconsider_write(
        self, record: HeldNotification, ruling: NotificationDisposition, now: datetime
    ) -> NotificationDisposition:
        """Update the record in place, never writing a second one (§5).

        Ruled ``DROP`` it records that disposition and the record ceases to be
        actionable; §7's retention is what removes it.

        Raises:
            ValueError: If the ruling makes the updated record unconstructable.
                Nothing is written and the enclosing transaction rolls back.
        """
        ruled = HeldNotification(
            id=record.id,
            candidate=record.candidate,
            kind=ruling.kind,
            reason=ruling.reason,
            failed=ruling.failed,
            ruled_at=now,
            reconsider_at=ruling.reconsider_at,
            admitted_at=record.admitted_at,
            retention=record.retention,
            dismissed_at=record.dismissed_at,
            dropped_at=now if ruling.kind is NotificationDispositionKind.DROP else None,
        )
        self._record_spend(self._conn, ruling)
        self._write(self._conn, ruled)
        return ruling

    async def due(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[HeldNotification]:
        """The actionable records whose ``reconsider_at`` has arrived, oldest due first.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``. Refused **before the first await**, so a bad call
                reaches no state at all.
            NotificationStoreError: If the store cannot be read, or a row is
                corrupt.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        # One clock reading for the whole page (ADR-0073 §8): a row dropping out
        # mid-scan would otherwise shift every subsequent offset.
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._due_sync, limit, offset, now)

    def _due_sync(self, limit: int, offset: int, now: datetime) -> list[HeldNotification]:
        with self._transaction("enumerate due notifications", immediate=False) as conn:
            rows = self._fetch(
                conn,
                "enumerate due notifications",
                f"SELECT {_COLUMNS} FROM notifications "  # noqa: S608 — module constants, no input
                f"WHERE {_UNCEASED} AND reconsider_at IS NOT NULL AND reconsider_at <= ? "
                f"ORDER BY reconsider_at ASC, id ASC",
                (_to_micros(now),),
            )
            # Paging is applied **after** the record's own predicate rather than
            # in SQL, so `offset` counts the rows a caller can actually see.
            records = [record for record in map(_notification_from, rows) if record.is_due_at(now)]
            return records[offset : offset + limit]

    async def held(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[HeldNotification]:
        """Every retained record, oldest first (§7).

        **Every retained record, not only the actionable ones**: §7 is explicit
        that expiry "deletes nothing, and an expired record stays enumerable and
        renders as expired", so filtering here would hide from the user the record
        whose moment passed.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``.
            NotificationStoreError: If the store cannot be read, or a row is
                corrupt.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        async with self._lock:
            return await _run_to_completion(self._held_sync, limit, offset)

    def _held_sync(self, limit: int, offset: int) -> list[HeldNotification]:
        with self._transaction("enumerate notifications", immediate=False) as conn:
            rows = self._fetch(
                conn,
                "enumerate notifications",
                f"SELECT {_COLUMNS} FROM notifications "  # noqa: S608 — a module constant, no input
                f"ORDER BY admitted_at ASC, id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [_notification_from(row) for row in rows]

    async def get(self, notification_id: str) -> HeldNotification | None:
        """One record by id, or ``None`` where the id names nothing.

        Raises:
            NotificationStoreError: If the store cannot be read, or the row is
                corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._get_sync, notification_id)

    def _get_sync(self, notification_id: str) -> HeldNotification | None:
        with self._transaction("read a notification", immediate=False) as conn:
            return self._row(conn, notification_id)

    async def dismiss(self, notification_id: str) -> bool:
        """End one record's actionability, leaving it readable (§7, §9).

        Returns:
            ``True`` if an actionable record was dismissed, ``False`` if the id
            named nothing or named a record that was already not actionable —
            the cessation instant a retention horizon is measured from may not be
            moved by a second call.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._dismiss_sync, notification_id, now)

    def _dismiss_sync(self, notification_id: str, now: datetime) -> bool:
        with self._transaction("dismiss a notification") as conn:
            record = self._row(conn, notification_id)
            if record is None or not record.is_actionable_at(now):
                return False
            conn.execute(
                "UPDATE notifications SET dismissed_at = ? WHERE id = ?",
                (_to_micros(now), record.id),
            )
            return True

    async def preferences(self) -> NotificationPreferences:
        """The three standing settings in force, defaulted where nothing is set (§6).

        Raises:
            NotificationStoreError: If the store cannot be read, or the stored
                value is corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._preferences_sync)

    def _preferences_sync(self) -> NotificationPreferences:
        with self._transaction("read the notification preferences", immediate=False) as conn:
            return self._preferences_row(conn)

    async def set_preferences(self, preferences: NotificationPreferences) -> int:
        """Write the standing settings, and re-arm what the change reaches (§6).

        Returns:
            How many records the write made due for reconsideration.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._set_preferences_sync, preferences, now)

    def _set_preferences_sync(self, preferences: NotificationPreferences, now: datetime) -> int:
        """The write and the re-arming, as one atomic act (§6).

        **Nothing here re-rules anything.** Stamping the write instant routes the
        act through §5's one ruling path instead of adding a second, and the
        reconsideration job picks the records up on its next run.
        """
        with self._transaction("write the notification preferences") as conn:
            previous = self._preferences_row(conn)
            removable = _conditions_a_change_removes(previous, preferences)
            raised = _classes_reaching(previous, preferences, NotificationReach.INTERRUPT)
            silenced = _classes_reaching(previous, preferences, NotificationReach.OFF)
            touched = 0
            for record in self._actionable(conn, now):
                # No setting change reaches a record already ruled INTERRUPT (§6).
                if record.kind is not NotificationDispositionKind.HOLD:
                    continue
                held_class = record.candidate.notification_class
                reaches = (
                    # Lowering a class to `off` is the one change that reads no
                    # failed set: "never tell me this" reaches what is already
                    # held, including a record held only for an absent expiry.
                    held_class in silenced
                    or (
                        held_class in raised
                        and NotificationCondition.REACH_INTERRUPT in record.failed
                    )
                    or bool(set(record.failed) & removable)
                )
                if reaches:
                    conn.execute(
                        "UPDATE notifications SET reconsider_at = ? WHERE id = ?",
                        (_to_micros(now), record.id),
                    )
                    touched += 1
            conn.execute(
                "INSERT OR REPLACE INTO notification_preferences(id, value) VALUES(1, ?)",
                (preferences.model_dump_json(),),
            )
            return touched

    async def delete(self, notification_id: str) -> bool:
        """Destroy one record — **unconditionally** (§9, ADR-0004 §6).

        **It does not refund a unit of budget** (§5): destroying the record of an
        interruption does not unmake the interruption, and a store that let it
        would hand any caller a way to spend the budget twice per window.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        async with self._lock:
            return await _run_to_completion(self._delete_sync, notification_id)

    def _delete_sync(self, notification_id: str) -> bool:
        with self._transaction("delete a notification") as conn:
            deleted = conn.execute(
                "DELETE FROM notifications WHERE id = ?", (notification_id,)
            ).rowcount
            return deleted > 0

    async def clear(self) -> int:
        """Destroy every record, whatever its state (§9, ADR-0007).

        It does **not** reset the standing preferences: those are the user's
        settings rather than the user's notifications, and a sweep that silently
        restored every class to ``hold`` would undo a "never tell me this" the
        user meant to keep. It does **not** refund the budget either, for
        :meth:`delete`'s reason.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the notification store") as conn:
            return int(conn.execute("DELETE FROM notifications").rowcount)

    async def export(self) -> list[HeldNotification]:
        """Every stored record, for the user's own data export (ADR-0004 §6).

        Every record is included, dismissed, expired and dropped alike: the
        content is the user's. **No spend instant appears**: the ledger is a rate
        limiter's state rather than the user's content.

        Raises:
            NotificationStoreError: If the store cannot be read, or a row is
                corrupt.
        """
        async with self._lock:
            return await _run_to_completion(self._export_sync)

    def _export_sync(self) -> list[HeldNotification]:
        with self._transaction("export the notification store", immediate=False) as conn:
            return self._all(conn)

    async def purge(self) -> int:
        """Sweep the records retention has released (§7).

        **No record is purged while it is still actionable, whatever its
        retention**, so a record's key suppresses duplicates for the whole time §8
        says it does; and ``retention is None`` is a complete answer rather than
        an undefined expression. **It refunds no unit of budget** (§5), which
        matters here more than at :meth:`delete`: this is a *scheduler's* act, so
        a store deriving its spend count from the retained records would widen the
        budget on a timer wherever a deployment configured a retention shorter
        than the budget window.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._purge_sync, now)

    def _purge_sync(self, now: datetime) -> int:
        with self._transaction("purge the notification store") as conn:
            # `retention IS NULL` is excluded in SQL because the exclusion is
            # about the *column* and nothing else; the horizon and the
            # actionability are then judged by the record, which is where their
            # one definition lives (`is_purgeable_at`).
            rows = self._fetch(
                conn,
                "purge the notification store",
                f"SELECT {_COLUMNS} FROM notifications WHERE retention IS NOT NULL",  # noqa: S608 — a module constant, no input
            )
            doomed = [
                record.id for record in map(_notification_from, rows) if record.is_purgeable_at(now)
            ]
            for notification_id in doomed:
                conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
            return len(doomed)
