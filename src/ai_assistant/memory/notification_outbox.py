"""The delivery outbox: custody of a ruled interruption until a device has it.

ADR-0131 §3's durable queue, backed by ``sqlite3`` in the hub's data directory.
It holds one queue **for the owner** — not one per device — bounded by count and
by bytes, leased, at-least-once, and surviving a hub restart.

**Why it lives in ``memory/`` rather than beside the listener.** Every peer
durable store in this tree does: :mod:`~ai_assistant.memory.notification_store`,
:mod:`~ai_assistant.memory.deferral_store`,
:mod:`~ai_assistant.memory.conversation_store`. The composition root wires it, and
``app`` may name ``memory`` and may not name ``service`` — so this is the only
home from which ADR-0131 §3b's Protocol can reach both the producer that offers
and the engine that polls. ADR-0131 §3's "not a memory, not an episode and not a
trace" is a rule about what the outbox may **hold** and what may read it, not
about which package compiles it; nothing here is routed through ``MemoryStore``
and no retrieval path reads it.

**Two faces on one object, and only one of them is ``core`` surface.**
:class:`~ai_assistant.core.protocols.NotificationOutbox` carries "exactly one
method" (§3b) — :meth:`SqliteNotificationOutbox.offer`, what a *producer* holds.
The engine needs three more transitions to serve a poll, and ADR-0131 declares no
Protocol for them; :class:`~ai_assistant.orchestration.delivery.DeliveryOutbox` is
the local ``Protocol`` ``orchestration`` declares for its own collaborator, in the
shape :class:`ai_assistant.wire.server.Admission` already takes for the listener's.
Nothing imports across a subsystem boundary — the composition root injects one
object into both roles — so ``lint-imports`` stays green and ``core`` gains
exactly what §3b ratified and nothing more.

**Every transition is one ``BEGIN IMMEDIATE`` transaction inside one
:class:`asyncio.Lock`**, which is how §3's linearizability rule is discharged.
That rule is stated over *every* transition rather than an enumeration, because
ADR-0131 §3 records four separate findings of one defect: a predicate stated over
outbox state binds nothing unless the read and the act that depends on it are one
step. Holding the lock across a whole operation — the awaited dismissal of another
store included — is the "holding transitions against one another" arm §3 permits.

**Departure is a two-store dance the ADR orders rather than makes atomic** (§3b).
The ADR-0130 record is dismissed **first** and the entry removed only after that
dismissal has committed, so "entry absent" implies "record dismissed" implies
"record not actionable" — and the contrapositive is the invariant reconciliation
rests on: an actionable record with no entry is one whose enqueue never committed.
The ``departing`` column is how a crash between the two is made recoverable: it
records that this seam has **given the entry up**, which makes the entry
ineligible for every transition but its own removal (§3) — the conservative
direction, since marking early can only make an entry less deliverable, never
more. :meth:`SqliteNotificationOutbox.reconcile` finishes any departure a crash
interrupted, and :meth:`SqliteNotificationOutbox.offer` settles them first so the
repair is not restart-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import NotificationOutboxError
from ai_assistant.core.types import (
    NotificationCandidate,
    NotificationDelivery,
    NotificationDispositionKind,
    NotificationEnqueue,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import NotificationStore

import structlog

_log = structlog.get_logger(__name__)

#: ADR-0004 §4's mode for a database holding the user's own text.
_OWNER_ONLY = 0o600

#: The journal, WAL and shared-memory files SQLite may put beside the database.
_SIDECARS = ("-journal", "-wal", "-shm")

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: ADR-0131 §4: the identifier's UTF-8 encoding is at most 96 bytes. The random
#: half renders as 32 hex characters and the separator is one, so 63 bytes are
#: left for the counter — the figure §4's exhaustion clause is stated against.
_DELIVERY_ID_MAX_BYTES = 96

#: The counter's ceiling, from the bound above: ``10**63`` writes, which at a
#: delivery a second is some ``10**55`` years. Unreachable, and ruled anyway
#: because ADR-0131 §4 applies its own standard to its own clause — a state the
#: two bounds genuinely define may not be left with no conforming outcome.
_DELIVERY_COUNTER_CEILING = 10**63

#: How many records one page of :meth:`NotificationStore.held` asks for while the
#: reconciliation walks them. A page size rather than one call, because ADR-0130
#: §7's cap bounds the store at a few hundred and paging keeps the read bounded
#: whatever an operator sets it to.
_RECORD_PAGE = 200


#: The per-entry cost of the fixed-width columns an implementation persists
#: beside the candidate — the lease instant, the enqueue sequence, the departing
#: flag and the byte figure itself, at eight bytes each. Counted because ADR-0131
#: §3 defines an entry's byte cost as "everything the outbox persists for it,
#: defined by that property and not by a list": an implementation counting only
#: the candidate would accept entries up to the bound while the durable outbox sat
#: above it, which is the bound failing by arithmetic rather than by disobedience.
_FIXED_COLUMN_BYTES = 32


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes.

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses (ADR-0054, ADR-0060).

    Deliberately duplicated from :mod:`ai_assistant.memory.notification_store`
    rather than shared, for the reason recorded there: ADR-0060 refuses a common
    home for this helper so that subsystems depend on the *obligation* and not on
    one way of meeting it.
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


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289)."""
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _from_micros(value: int) -> datetime:
    """The instant an integer microsecond epoch names."""
    return _EPOCH + _timedelta_micros(value)


def _timedelta_micros(value: int) -> timedelta:
    from datetime import timedelta as _td  # noqa: PLC0415 — a runtime-only import of a stdlib type

    return _td(microseconds=value)


def _random_half() -> str:
    """128 bits from a cryptographically secure source, as lowercase hex.

    ADR-0131 §4 makes ``delivery_id`` a **capability**, and this is the half that
    makes holding it mean something: with a bare counter a device that has seen
    ``41`` could send ``acknowledging="42"`` and retire an entry leased to another
    device that has not yet shown it — losing a notification outright.
    """
    return secrets.token_hex(16)


class _Entry:
    """One decoded outbox row.

    Attributes:
        key: The candidate's own ``candidate_key`` (ADR-0130 §8), which is the
            entry's key. The outbox takes no key from a caller.
        candidate: What would be shown.
        record_id: The ADR-0130 record this entry carries, so a departure can
            dismiss it (§3b). ``None`` where no record could be resolved, which a
            departure then treats as nothing further owed.
        sequence: The enqueue order, stable across a restart — without it "the
            oldest entry" has no meaning once the process has died.
        delivery_id: The current outstanding delivery, or ``None``.
        leased_at: When the lease was **taken**, or ``None`` where none is held.
            The start rather than the expiry, because §3 runs a lease for its whole
            configured span and §5a bounds that span below and not above — an expiry
            for a span near ``timedelta.max`` is nameable neither as a ``datetime``
            nor as microseconds in an ``INTEGER``, while the start always is.
        departing: Whether this seam has given the entry up (§3).
        cost: The entry's byte cost, as persisted.
    """

    __slots__ = (
        "candidate",
        "cost",
        "delivery_id",
        "departing",
        "key",
        "leased_at",
        "record_id",
        "sequence",
    )

    def __init__(  # noqa: PLR0913 — one parameter per persisted column
        self,
        *,
        key: str,
        candidate: NotificationCandidate,
        record_id: str | None,
        sequence: int,
        delivery_id: str | None,
        leased_at: int | None,
        departing: bool,
        cost: int,
    ) -> None:
        """Hold one decoded row."""
        self.key = key
        self.candidate = candidate
        self.record_id = record_id
        self.sequence = sequence
        self.delivery_id = delivery_id
        self.leased_at = leased_at
        self.departing = departing
        self.cost = cost

    def is_leased_at(self, moment: datetime, lease: timedelta) -> bool:
        """Whether a live lease holds this entry at ``moment``.

        Half-open in the direction a lease has to take: **at** the expiry the
        lease has run out and the entry is available again, which is what makes
        ADR-0131 §3's "on expiry it returns to the outbox" true rather than
        approximately true.
        """
        if self.leased_at is None:
            return False
        return moment - _from_micros(self.leased_at) < lease

    def is_departing_at(self, moment: datetime) -> bool:
        """Whether ADR-0131 §3's departing predicate holds.

        **Two things make an entry departing and the seam decides both without
        reading the other store** (§3): this seam gave the entry up and dismissed
        its record — the ``departing`` column — or the entry's own candidate
        carries an expiry that has passed on the hub's clock. The expiry is a
        field on the candidate and the candidate is *in* the entry, so the second
        is a question about this row's own content.

        Defining it by the record's actionability rather than by the dismissal is
        what ADR-0131 §3's forty-third round found: a candidate enqueued while
        actionable and never polled before its expiry was never dismissed, would
        not be departing under a dismissal-only reading, and would be delivered
        stale — a notification arriving after the moment it said it stopped
        mattering.
        """
        expiry = self.candidate.expires_at
        return self.departing or (expiry is not None and expiry <= moment)


def _cost_of(key: str, encoded: str, record_id: str | None) -> int:
    """One entry's byte cost — **everything the outbox persists for it** (§3).

    Defined by that property and not by a list, which is ADR-0131 §3's own
    instruction: "a field an implementation adds is counted by being persisted".
    The variable-width columns are measured in UTF-8, the fixed-width ones by
    :data:`_FIXED_COLUMN_BYTES`, and the delivery identifier is charged at its
    ceiling rather than its current length so that leasing an entry can never push
    the outbox over a bound it was inside a moment earlier.
    """
    return (
        len(key.encode("utf-8"))
        + len(encoded.encode("utf-8"))
        + len((record_id or "").encode("utf-8"))
        + _DELIVERY_ID_MAX_BYTES
        + _FIXED_COLUMN_BYTES
    )


class SqliteNotificationOutbox:
    """A durable ``NotificationOutbox`` and delivery queue backed by ``sqlite3``."""

    def __init__(  # noqa: PLR0913 — the store it dismisses through, plus one figure per ADR-0131 §5a bound
        self,
        *,
        path: Path | str,
        records: NotificationStore,
        lease: timedelta,
        max_entries: int,
        max_bytes: int,
        candidate_ceiling: int,
        now: Clock = _utcnow,
        new_token: Callable[[], str] = _random_half,
    ) -> None:
        """Open (or create) the delivery outbox at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral outbox.
            records: The ADR-0130 record store, held **through the Protocol the
                composition root injects** (ADR-0131 §3b) rather than reached
                into. Every way an entry leaves the outbox dismisses its record
                through it, and the reconciliation reads it.
            lease: ``hub_notification_lease``. How long a delivery taken by a
                device stays unavailable to any other poll.
            max_entries: ``hub_notification_outbox_entries``.
            max_bytes: ``hub_notification_outbox_bytes``.
            candidate_ceiling: ADR-0085 §8's contract limit **less ADR-0131 §4's
                256-byte delivery reserve**. Passed in rather than derived here
                because it falls out of ``hub_max_frame_bytes``, which differs
                between deployments — the reason ADR-0131 §4 puts this ceiling at
                the seam and forbids a size validator on
                :class:`~ai_assistant.core.types.NotificationCandidate`, whose
                frozen `core` model has no ``Settings`` input.
            now: The hub's clock. **No value a device sends influences a lease**
                (ADR-0131 §3): a peer that could choose its own would hand the
                eviction rule to whichever peer asked for the longest.
            new_token: The source of ``delivery_id``'s random half; injectable for
                determinism in tests, and a ``secrets`` draw in production because
                §4 makes the identifier a capability.

        Raises:
            ValueError: If any bound is not strictly positive, or the candidate
                ceiling is not positive.
            NotificationOutboxError: If the database cannot be opened or prepared.
        """
        _check_bounds(
            lease=lease,
            max_entries=max_entries,
            max_bytes=max_bytes,
            candidate_ceiling=candidate_ceiling,
        )
        self._clock = checked_clock(now, owner="SqliteNotificationOutbox")
        self._records = records
        self._lease = lease
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._candidate_ceiling = candidate_ceiling
        self._new_token = new_token
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        #: Set whenever an entry may have become available, so a parked poll wakes
        #: on an enqueue instead of waiting out its whole budget. In-process only,
        #: and never load-bearing: a poll that misses it falls back on its own
        #: deadline, so correctness never rests on a notification nobody received.
        self._arrivals = asyncio.Event()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error.

        Raises:
            NotificationOutboxError: If the database cannot be opened or prepared.
        """
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The driver's implicit transactions are *deferred*,
            # upgrading to a write lock only at the first write — which leaves
            # every read-decide-write step here open to exactly the interleaving
            # ADR-0131 §3's linearizability rule forbids.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            msg = f"failed to open notification outbox at {self._path!r}: {exc}"
            raise NotificationOutboxError(msg) from exc
        try:
            # Restricted *before* the first write: SQLite copies the database
            # file's mode onto every rollback journal it creates, and an
            # interrupted write leaves that journal on disk holding the user's own
            # text (ADR-0004 §4).
            self._restrict_permissions()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS outbox("
                "candidate_key TEXT PRIMARY KEY, candidate TEXT NOT NULL, record_id TEXT, "
                "sequence INTEGER NOT NULL, delivery_id TEXT, leased_at INTEGER, "
                "departing INTEGER NOT NULL DEFAULT 0, cost INTEGER NOT NULL)"
            )
            # The enqueue order is what "the oldest entry" means, and it has to
            # survive the process: a restart voids every lease (§3) but may not
            # renumber the queue, or eviction would drop whichever row SQLite
            # happened to return first.
            conn.execute("CREATE INDEX IF NOT EXISTS outbox_order ON outbox(sequence)")
            conn.execute("CREATE INDEX IF NOT EXISTS outbox_delivery ON outbox(delivery_id)")
            # One row, holding the two monotonic counters. The delivery counter is
            # what makes §4's uniqueness a *guarantee* rather than a probability —
            # "a UUID is unique by construction" is false, a v4 UUID being
            # collision-resistant — for one integer of durable state, and with no
            # unbounded history of minted identifiers to keep.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS outbox_counters("
                "id INTEGER PRIMARY KEY CHECK(id = 1), next_sequence INTEGER NOT NULL, "
                "next_delivery INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO outbox_counters(id, next_sequence, next_delivery) "
                "VALUES (1, 1, 1)"
            )
        except (sqlite3.Error, OSError) as exc:
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open notification outbox at {self._path!r}: {exc}"
            raise NotificationOutboxError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault, and a
        *symlink* under a sidecar's name is skipped rather than followed:
        ``chmod`` follows links, so restricting one would silently narrow a file
        holding none of this store's data. The argument is
        ``SqliteNotificationStore._restrict_permissions``' in full.
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

    def _now(self) -> datetime:
        """The guarded clock's reading, as this seam's own error (ADR-0026 §4).

        Raises:
            NotificationOutboxError: If the reading is naive, indeterminate, or
                outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise NotificationOutboxError(str(exc)) from exc

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read this seam's next
        act depends on cannot be interleaved by another writer — which is how
        ADR-0131 §3's linearizability holds **across processes** and not merely
        across coroutines on one loop.

        Raises:
            NotificationOutboxError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=NotificationOutboxError, immediate=immediate)

    @staticmethod
    def _rows(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        """Run one read on an open connection, translating a backend failure.

        Raises:
            NotificationOutboxError: If the outbox cannot be read.
        """
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise NotificationOutboxError(msg) from exc

    def _all(self, conn: sqlite3.Connection) -> list[_Entry]:
        """Every entry, oldest first."""
        rows = self._rows(
            conn,
            "read the outbox",
            "SELECT candidate_key, candidate, record_id, sequence, delivery_id, "
            "leased_at, departing, cost FROM outbox ORDER BY sequence",
        )
        return [_entry_from(row) for row in rows]

    async def _held_records(self) -> list[Any]:
        """Every ADR-0130 record the store retains, walked a page at a time.

        Raises:
            NotificationOutboxError: If the record store cannot be read. Its own
                ``NotificationStoreError`` is translated, because a caller of this
                seam is promised **this** seam's failure (ADR-0131 §3b).
        """
        gathered: list[Any] = []
        offset = 0
        while True:
            try:
                page = await self._records.held(limit=_RECORD_PAGE, offset=offset)
            except Exception as exc:  # re-raised as this seam's declared failure (ADR-0131 §3b)
                msg = (
                    f"failed to read the notification records the outbox reconciles against: {exc}"
                )
                raise NotificationOutboxError(msg) from exc
            gathered.extend(page)
            if len(page) < _RECORD_PAGE:
                return gathered
            offset += len(page)

    async def _dismiss(self, record_id: str | None) -> bool:
        """Dismiss one ADR-0130 record, translating the other store's failure.

        A ``None`` id is the case where no record could be resolved for an entry,
        and ADR-0131 §3b's "where the act that removed the entry has already ended
        the record's actionability, nothing further is owed" covers it: there is
        nothing to dismiss.

        Returns:
            Whether an actionable record was dismissed by this call.

        Raises:
            NotificationOutboxError: If the dismissal could not commit. **Nothing
                is removed then**, which is what keeps §3b's ordering true — an
                entry is never removed before its record's dismissal has
                committed.
        """
        if record_id is None:
            return False
        try:
            return await self._records.dismiss(record_id)
        except Exception as exc:  # re-raised as this seam's declared failure (ADR-0131 §3b)
            msg = f"failed to dismiss the notification record an outbox entry carried: {exc}"
            raise NotificationOutboxError(msg) from exc

    # --- the producer's seam (ADR-0131 §3b) ----------------------------------

    async def offer(self, candidate: NotificationCandidate) -> NotificationEnqueue:
        """Take custody of one ruled interruption, or say why not (ADR-0131 §3).

        Args:
            candidate: What ADR-0130 §5 ruled ``INTERRUPT``.

        Returns:
            Which of §3's four outcomes the offer reached.

        Raises:
            NotificationOutboxError: If the durable store cannot commit. No
                custody transfers.
        """
        return await self._offer(candidate, reconciled=False)

    async def _offer(
        self, candidate: NotificationCandidate, *, reconciled: bool
    ) -> NotificationEnqueue:
        """Take custody, or say why not — the body :meth:`offer` and the repair share.

        ``reconciled`` is what tells the two callers apart, and it decides one thing:
        whether an offer may commit an entry that **no actionable record backs**.

        **A producer's offer may.** ADR-0131 §3b's live handoff arrives holding a
        candidate whose disposition was just ruled, and §3b's "nothing further is
        owed" covers a caller that keeps no records of its own; refusing it would
        make the outbox unusable by anything but ADR-0130's store.

        **The repair may not**, because it is working from a snapshot. §3b's
        reconciliation reads the records, releases the lock and offers what is
        missing — and the owner can dismiss or delete one of those records in the
        gap. The withdrawal that disposal performs then finds no entry to take, and
        an unconditional re-offer would insert one *afterwards*, delivering a
        notification the owner had already removed and defeating §3a's whole
        ordering. Re-resolving under this lock is what closes it: the record is
        looked up now rather than when the snapshot was taken, and a disposal racing
        this call serialises against the same lock its own withdrawal needs.
        """
        encoded = candidate.model_dump_json()
        async with self._lock:
            await self._settle_departing()
            now = self._now()
            # Resolved before either ceiling is measured, because a terminal
            # refusal has to *dismiss* this record and cannot dismiss one it never
            # looked up (§3b).
            record_id = await self._resolve_record(candidate.candidate_key)
            if reconciled and record_id is None:
                # The record this repair was reading has ceased to be actionable
                # since the snapshot — dismissed, deleted, or expired. There is
                # nothing to re-offer, and inserting anyway would resurrect what the
                # owner disposed of.
                _log.info(
                    "notification_outbox_reconcile_skipped",
                    candidate_key=candidate.candidate_key,
                )
                return NotificationEnqueue.ALREADY_HELD
            # §4's delivery ceiling is measured on the *candidate*, before any
            # bound is consulted, because it is a refusal the offer can never
            # satisfy by evicting other entries (§3).
            if len(encoded.encode("utf-8")) > self._candidate_ceiling:
                await self._refuse(NotificationEnqueue.TOO_LARGE, candidate, record_id)
                return NotificationEnqueue.TOO_LARGE
            cost = _cost_of(candidate.candidate_key, encoded, record_id)
            if cost > self._max_bytes:
                await self._refuse(NotificationEnqueue.TOO_LARGE, candidate, record_id)
                return NotificationEnqueue.TOO_LARGE
            outcome, victims, held_record = await _run_to_completion(
                self._enqueue_sync, candidate, encoded, record_id, cost, now
            )
            if outcome is None:
                # One retry, after the departure has been finished dismissal-first.
                # Bounded at one because the settle removes the row: a second
                # decline means another writer is re-opening departures under
                # this key as fast as we clear them, and looping on that would spin
                # the hub rather than answer the producer.
                await self._settle_departing()
                outcome, victims, held_record = await _run_to_completion(
                    self._enqueue_sync, candidate, encoded, record_id, cost, now
                )
            if outcome is None:
                msg = (
                    "the outbox key this offer needs is held by an entry whose departure "
                    "another writer keeps re-opening, so no custody transferred"
                )
                raise NotificationOutboxError(msg)
            if outcome is NotificationEnqueue.KEY_COLLISION:
                await self._refuse(
                    NotificationEnqueue.KEY_COLLISION, candidate, record_id, held_by=held_record
                )
                return outcome
            if outcome is not NotificationEnqueue.ENQUEUED:
                return outcome
            # **The key is durably reserved before a single victim is touched**, and
            # that ordering is the whole of the fix. Evicting first meant an offer
            # that then lost the key to another writer had already dismissed and
            # removed an unrelated entry — an outcome no serial order of the two
            # offers produces, which is exactly what ADR-0131 §3's linearizability
            # rule forbids. With the insert committed, the outcome can no longer
            # change, so the eviction it authorised is the eviction that happens.
            #
            # Dismiss first, remove after (§3b). The victims are already marked
            # departing by the same transaction that inserted, so no poll can select
            # one while the dismissals run, and the bounds they still count toward
            # are restored by the removal below — or by the next `_settle_departing`
            # if this call dies in between.
            # **Custody has transferred, so nothing after this point may report that
            # it did not.** The entry is durably committed, so raising here would
            # tell a producer it still owned a candidate the outbox will deliver —
            # and its retry would come back `ALREADY_HELD`, contradicting the error
            # it was just given. ADR-0131 §4 rules this exact shape at the other end
            # of an entry's life: "a failure of the entry's subsequent removal does
            # **not** fail the call: the entry is departing, it is deliverable to
            # nobody, and §3b's reconciliation completes the removal." The victims
            # are marked departing by the same transaction that inserted, so a
            # failure below leaves entries no poll can select, and the bounds they
            # still count toward are restored by the next `_settle_departing`.
            try:
                await self._evict(victims)
            except NotificationOutboxError as exc:
                _log.warning("notification_outbox_eviction_deferred", reason=str(exc))
            self._wake()
            return NotificationEnqueue.ENQUEUED

    async def _refuse(
        self,
        outcome: NotificationEnqueue,
        candidate: NotificationCandidate,
        record_id: str | None,
        *,
        held_by: str | None = None,
    ) -> None:
        """End a terminally refused offer's record, and log the refusal (§3b).

        **A terminal refusal is terminal for the *record*, not merely for the
        offer**, and leaving it actionable is the fifty-seventh round's defect:
        "Returning ``TOO_LARGE`` and doing nothing else left the record actionable
        with no entry, which is exactly the state §3b's invariant reads as an
        incomplete handoff: every reconciliation would offer the same permanently-
        undeliverable candidate again, until it expired, while a polling device
        received nothing." ``KEY_COLLISION`` has the same shape and takes the same
        answer.

        **Dismissing is the terminal outcome that fits**, because the record's own
        vocabulary already has one: a dismissal ends actionability and leaves the
        record readable (ADR-0130 §9), so the owner can still see the notification
        in the held surface, ADR-0130 §7's cap is freed, and nothing retries it.

        **The unit is not refunded**, and that is stated because the alternative is
        forbidden: ADR-0130 §5 rules that a delivery seam "may not refund a unit
        implicitly on a failed attempt". So an undeliverable notification costs the
        owner one unit of that hour's budget, and this log entry is what makes that
        cost visible.

        **A collision whose record is the held entry's dismisses nothing**, which
        is where §3b's clause meets §3's. ADR-0130 §8 suppresses duplicates by key,
        so a differing candidate offered under a held key ordinarily shares the
        held entry's record — and dismissing that would make the held entry
        departing, contradicting §3's "The held entry is not replaced". The
        invariant §3b is protecting is not breached there either: that record still
        *has* an entry.

        Args:
            outcome: Which terminal refusal was reached.
            candidate: What was refused.
            record_id: Its ADR-0130 record, or ``None`` where none was found —
                which §3b's "nothing further is owed" covers.
            held_by: The record of the entry a collision matched, where the outcome
                is a collision.
        """
        dismissed = record_id is not None and record_id != held_by
        if dismissed:
            await self._dismiss(record_id)
        _log.info(
            "notification_outbox_refused",
            reason=outcome.value,
            candidate_key=candidate.candidate_key,
            notification_id=record_id,
            record_dismissed=dismissed,
        )

    def _enqueue_sync(
        self,
        candidate: NotificationCandidate,
        encoded: str,
        record_id: str | None,
        cost: int,
        now: datetime,
    ) -> tuple[NotificationEnqueue | None, list[_Entry], str | None]:
        """Decide the offer, mark what it evicts and insert it — one transaction.

        **One transaction and not two, which is what makes the enqueue a single
        linearizable transition** (ADR-0131 §3). Splitting the decision from the act
        left two gaps and both were real: another writer could take the key between
        them, so two callers were told ``ENQUEUED`` and one entry silently replaced
        the other; and the victims were dismissed on the strength of a decision that
        could still change, so an offer refused as a collision had already evicted an
        unrelated entry. §3 records four separate findings of that one shape — "a
        predicate stated over outbox state binds nothing unless the read and the act
        that depends on it are one step" — and this is that step.

        **The victims are marked here and removed later, and that split is forced.**
        Their ADR-0130 records must be dismissed before their entries are removed
        (§3b), and that dismissal reaches the *other* store, so it cannot run inside
        a transaction on this one. Marking inside this transaction is what makes the
        split safe: a marked entry is departing, so it "participates in no transition
        except its own removal" — not selected, not matched, not made available by a
        lease expiry — and it still counts toward both bounds until it goes, which is
        what §3 requires of it.

        Returns:
            The outcome, the entries this enqueue gave up, and — on a collision — the
            record of the entry the key matched, so the refusal can tell that record
            from the offered candidate's. A ``None`` outcome is not one of §3's four:
            it means the key is held by a **departing** entry, which this transition
            may not remove because §3b requires that entry's record be dismissed
            first. The caller finishes that departure and retries.
        """
        with self._transaction("enqueue a notification") as conn:
            entries = self._all(conn)
            held = next((entry for entry in entries if entry.key == candidate.candidate_key), None)
            if held is not None and not held.is_departing_at(now):
                # Matching on the key *and* the candidate is what makes the no-op a
                # **retry** rather than a coincidence (§3): matching on the key alone
                # would turn a producer's bug into a silent loss, a differing
                # candidate receiving what looks like a successful enqueue. Model
                # equality is ADR-0087 §2's canonical comparison for a frozen model
                # that forbids extras — two candidates whose encodings agree are
                # exactly the two that compare equal.
                if held.candidate == candidate:
                    return NotificationEnqueue.ALREADY_HELD, [], held.record_id
                return NotificationEnqueue.KEY_COLLISION, [], held.record_id
            if held is not None:
                # **Departing, and this is not the transition that may remove it.**
                # §3b admits no exception: "No implementation removes an entry whose
                # record it has not already dismissed." A row marked departing by
                # another writer after this call's `_settle_departing` — or by one
                # whose own dismissal has not committed — would be deleted here
                # before its record was ever dismissed, which is the one order §3b
                # rules unsafe. So this transition declines, the caller finishes the
                # departure through the path that dismisses first, and the enqueue is
                # retried against a table that no longer holds it.
                return None, [], None
            victims = self._victims_for(entries, None, cost, now)
            for victim in victims:
                conn.execute(
                    "UPDATE outbox SET departing = 1 WHERE candidate_key = ?", (victim.key,)
                )
            sequence = self._take_sequence(conn)
            conn.execute(
                "INSERT INTO outbox(candidate_key, candidate, record_id, sequence, "
                "delivery_id, leased_at, departing, cost) VALUES (?, ?, ?, ?, NULL, NULL, 0, ?)",
                (candidate.candidate_key, encoded, record_id, sequence, cost),
            )
            return NotificationEnqueue.ENQUEUED, victims, None

    def _victims_for(
        self, entries: list[_Entry], held: _Entry | None, cost: int, now: datetime
    ) -> list[_Entry]:
        """Which entries this enqueue drops, in the order ADR-0131 §3 fixes.

        **It drops until both bounds hold with the new entry counted, not once**,
        and the difference is not pedantry: one drop is enough for the count bound,
        where every entry costs exactly one, but not for the byte bound, where
        entries differ in size by orders of magnitude. §3 exhibits the arithmetic —
        an outbox one byte below a 1 MiB bound whose oldest entry costs a byte,
        taking a 512 KiB entry, is half a megabyte over after a single drop.

        **Each drop takes the oldest entry that is not leased, or, when every
        remaining entry is leased, the oldest entry, breaking its lease.** Stating
        it as a *total* function is the point: "drop the oldest undelivered entry"
        has no subject when every entry is leased, and an implementation reaching
        that state has two illegal moves available and nothing to choose between
        them. Breaking a lease forfeits the *redelivery*, not the notification —
        the entry has already been written to a device — and degrades at-least-once
        to at-most-once for that one entry, which is the only place ADR-0131 does
        so and is what buys the bound a total rule.

        A **departing** entry is a preferred victim rather than an exempt one:
        evicting one is not a second decision to give it up, it is the removal
        already owed, arriving through the path that was going to run anyway (§3).
        It still counts toward both bounds until it is removed.

        The loop terminates because each pass removes an entry and the incoming one
        is separately guaranteed to fit by the refusal in :meth:`offer` — so in the
        worst case the outbox empties and holds one.
        """
        remaining = [entry for entry in entries if held is None or entry.key != held.key]
        count = len(remaining) + 1
        total = sum(entry.cost for entry in remaining) + cost
        victims: list[_Entry] = []
        while remaining and (count > self._max_entries or total > self._max_bytes):
            available = [entry for entry in remaining if not entry.is_leased_at(now, self._lease)]
            departing = [entry for entry in available if entry.is_departing_at(now)]
            pool = departing or available or remaining
            victim = min(pool, key=lambda entry: entry.sequence)
            remaining.remove(victim)
            victims.append(victim)
            count -= 1
            total -= victim.cost
        return victims

    def _take_sequence(self, conn: sqlite3.Connection) -> int:
        """The next enqueue order, advanced durably in the same transaction."""
        rows = self._rows(
            conn, "read the outbox order", "SELECT next_sequence FROM outbox_counters"
        )
        sequence = int(rows[0][0])
        conn.execute("UPDATE outbox_counters SET next_sequence = ? WHERE id = 1", (sequence + 1,))
        return sequence

    # --- the engine's seam (ADR-0131 §2a, §3, §3b) ---------------------------

    async def claim(self) -> NotificationDelivery | None:
        """Select an entry, mint its identifier and lease it — one indivisible step.

        ADR-0131 §2a: "Selecting an entry, minting its ``delivery_id`` and starting
        its lease are **one indivisible step** inside ``next_notification``. There
        is no state in which an entry is chosen for a poll and not yet leased, and
        nothing about the lease depends on the transport." Collapsing them is what
        removed a whole class of question: with no reservation state, an entry is
        available or leased and there is no third state for eviction, a restart or
        a race to have an opinion about.

        Returns:
            The delivery to write, or ``None`` where nothing is available.

        Raises:
            NotificationOutboxError: If the outbox cannot be read or written.
        """
        async with self._lock:
            now = self._now()
            return await _run_to_completion(self._claim_sync, now)

    def _claim_sync(self, now: datetime) -> NotificationDelivery | None:
        with self._transaction("select a notification for delivery") as conn:
            entries = self._all(conn)
            available = [
                entry
                for entry in entries
                if not entry.is_leased_at(now, self._lease) and not entry.is_departing_at(now)
            ]
            if not available:
                # **Cleared here and nowhere else**, which is what makes the wake
                # lossless. Clearing inside the wait erased an arrival that landed
                # between a poll's empty claim and its call to wait: the event was
                # already set, the wait discarded it, and the poll slept out its
                # whole budget with an entry available the whole time. The clear
                # belongs to the transition that *observed* the emptiness, so it is
                # taken under the same lock as that observation and an ``offer``
                # setting it afterwards cannot be lost.
                self._arrivals.clear()
                return None
            entry = min(available, key=lambda candidate_entry: candidate_entry.sequence)
            delivery_id = self._take_delivery_id(conn)
            if delivery_id is None:
                # §4's exhaustion clause: a delivery that would advance the counter
                # beyond what the 96-byte bound leaves room to render does not
                # happen — the poll answers as though the outbox held nothing, and
                # the condition is logged. The counter is never wrapped, reset or
                # reused to make room, because all three break the uniqueness it
                # exists to supply.
                _log.error("notification_outbox_delivery_counter_exhausted")
                return None
            conn.execute(
                "UPDATE outbox SET delivery_id = ?, leased_at = ? WHERE candidate_key = ?",
                (delivery_id, _to_micros(now), entry.key),
            )
            return NotificationDelivery(delivery_id=delivery_id, notification=entry.candidate)

    def _take_delivery_id(self, conn: sqlite3.Connection) -> str | None:
        """Mint one delivery identifier, advancing the durable counter.

        **Two halves, because the identifier carries two obligations and neither
        half carries both** (ADR-0131 §4). The counter is for *uniqueness* — a
        guarantee rather than a probability, bought for one integer of durable
        state instead of the unbounded history of minted identifiers §3 refuses.
        The 128-bit half is for *unguessability*, and it is there because the
        counter alone created a capability anyone could forge.

        Returns:
            The identifier, or ``None`` where the counter has no room left to
            advance inside §4's 96-byte bound.
        """
        rows = self._rows(
            conn, "read the outbox delivery counter", "SELECT next_delivery FROM outbox_counters"
        )
        counter = int(rows[0][0])
        if counter >= _DELIVERY_COUNTER_CEILING:
            return None
        conn.execute("UPDATE outbox_counters SET next_delivery = ? WHERE id = 1", (counter + 1,))
        return f"{counter}.{self._new_token()}"

    async def acknowledge(self, delivery_id: str) -> None:
        """Retire the entry ``delivery_id`` is the current outstanding delivery of.

        **Only where it is current** (ADR-0131 §3). An acknowledgement naming
        anything else — an unknown identifier, a retired entry, or a delivery the
        entry has since superseded — is accepted and does nothing. That idempotent
        no-op is what lets a client reconnect after any failure and acknowledge
        blindly; the "current" condition is what stops a stale holder retiring
        someone else's notification, which §4 mints a fresh identifier per delivery
        precisely to make decidable without the hub knowing who is asking.

        **The marking and the check are one step, and that is the twentieth
        round's finding.** Device A's lease expires while it reconnects to
        acknowledge; without marking, an implementation reads that its delivery is
        current, device B's selection then mints a new one for the same entry, and
        A's retirement lands on its stale read — B holding a delivery that can
        never be confirmed and never be redelivered. Marking the entry departing in
        the same transaction as the check makes that unreachable: once marked, no
        later poll can select it.

        Raises:
            NotificationOutboxError: If the acknowledgement's **dismissal** cannot
                commit. Nothing is retired then and the same value may be sent
                again — the mark is reversed first, so the entry is exactly as it
                was (ADR-0131 §4).
        """
        async with self._lock:
            now = self._now()
            entry = await _run_to_completion(self._mark_acknowledged_sync, delivery_id, now)
            if entry is None:
                return
            try:
                await self._dismiss(entry.record_id)
            except NotificationOutboxError:
                await _run_to_completion(self._unmark_sync, entry.key, entry.sequence)
                raise
            # Once the dismissal has committed the acknowledgement has taken
            # effect, and a failure of the removal does **not** fail the call: the
            # entry is departing, deliverable to nobody, and the reconciliation
            # completes the removal (§4).
            with contextlib.suppress(NotificationOutboxError):
                await _run_to_completion(self._remove_sync, entry.key, entry.sequence)

    def _mark_acknowledged_sync(self, delivery_id: str, now: datetime) -> _Entry | None:
        with self._transaction("acknowledge a notification delivery") as conn:
            rows = self._rows(
                conn,
                "read the acknowledged delivery",
                "SELECT candidate_key, candidate, record_id, sequence, delivery_id, "
                "leased_at, departing, cost FROM outbox WHERE delivery_id = ?",
                (delivery_id,),
            )
            if not rows:
                return None
            entry = _entry_from(rows[0])
            if entry.is_departing_at(now):
                return None
            conn.execute(
                "UPDATE outbox SET departing = 1 WHERE candidate_key = ? AND sequence = ?",
                (entry.key, entry.sequence),
            )
            return entry

    def _unmark_sync(self, key: str, sequence: int) -> None:
        """Restore the row this acknowledgement marked, and no other.

        Qualified for :meth:`_remove_sync`'s reason, in the other direction: a
        replacement under the same key is not the row whose mark is being reversed,
        and clearing *its* flag would revive an entry another writer is giving up.
        """
        with self._transaction("restore an outbox entry") as conn:
            conn.execute(
                "UPDATE outbox SET departing = 0 WHERE candidate_key = ? AND sequence = ?",
                (key, sequence),
            )

    def _remove_sync(self, key: str, sequence: int) -> None:
        """Remove the row this departure decided against, and no other.

        **A delete by key alone can take a *replacement*.** Between the read that
        marked a row departing and the delete that finishes it, this call awaits the
        other store's dismissal — and in that window another writer may remove the
        old row and enqueue a fresh candidate under the same key. An unqualified
        delete then takes the new row without its record having been dismissed,
        which breaks §3b's "entry absent implies record dismissed" outright and
        loses a notification until the next restart. Conditioning on ``sequence``
        makes the delete name the row it was decided against: sequences are drawn
        from a durable monotonic counter, so a replacement never shares one, and the
        delete simply matches nothing.
        """
        with self._transaction("remove an outbox entry") as conn:
            conn.execute(
                "DELETE FROM outbox WHERE candidate_key = ? AND sequence = ?", (key, sequence)
            )

    async def _evict(self, victims: list[_Entry]) -> None:
        """Dismiss each victim's record, then remove them all (ADR-0131 §3b).

        Dismiss first, remove after — the order §3b makes its invariant rest on. The
        victims are already marked departing, so nothing can select one while this
        runs, and a failure part-way leaves entries the next
        :meth:`_settle_departing` finishes rather than entries a poll can reach.

        Raises:
            NotificationOutboxError: If a dismissal or the removal cannot commit.
                What that means is the caller's to decide: after an insert has
                committed it means the eviction is deferred, not that the offer
                failed.
        """
        for victim in victims:
            await self._dismiss(victim.record_id)
            _log.info(
                "notification_outbox_evicted",
                candidate_key=victim.key,
                notification_id=victim.record_id,
            )
        if victims:
            await _run_to_completion(
                self._remove_many_sync, [(victim.key, victim.sequence) for victim in victims]
            )

    def _remove_many_sync(self, rows: list[tuple[str, int]]) -> None:
        """Remove every dismissed victim in one transaction.

        One transaction rather than one each, so an enqueue's eviction either frees
        the room it decided to free or frees none of it. Each delete is qualified by
        the row's ``sequence`` for :meth:`_remove_sync`'s reason: a victim replaced
        under its own key while the dismissals ran is a different entry, and taking
        it would remove a row whose record nobody dismissed.
        """
        with self._transaction("remove the evicted outbox entries") as conn:
            for key, sequence in rows:
                conn.execute(
                    "DELETE FROM outbox WHERE candidate_key = ? AND sequence = ?", (key, sequence)
                )

    async def withdraw(self, record_id: str) -> bool:
        """Give up the entry carrying one ADR-0130 record, as an eviction does (§3a).

        The act that disposes of a notification differently calls this, and
        ADR-0131 §3a makes the ordering mandatory for a **delete**: "An act that
        deletes an ADR-0130 record… withdraws the record's outbox entry **first**,
        and deletes the record only after the withdrawal has committed. No lane may
        delete a record whose entry it has not already withdrawn." Deleting the
        record first would leave an entry whose record is gone — not departing, not
        expired, undetectably stale, and delivered after the user deleted the thing
        it was about.

        **Selection does not protect the entry** (§3a). Every departure cause may
        remove any entry, selected or not, and removing a selected one breaks its
        lease and forfeits its redelivery exactly as §3's all-leased eviction does.
        What a withdrawal guarantees is that no *later* poll selects the entry —
        never that a delivery already staged will not land, which no hub-side state
        change can catch once ``next_notification`` has returned it.

        Args:
            record_id: The ADR-0130 record whose entry is given up.

        Returns:
            Whether the withdrawal **dismissed an actionable record**. That, rather
            than "an entry was found", is what a caller can act on: a dismissal
            surface has to report whether it ended anything, and the withdrawal is
            what performs that dismissal once the entry is marked. ``False`` covers
            both "no entry" and "its record had already ceased to be actionable".

        Raises:
            NotificationOutboxError: If the outbox cannot be read or written, or the
                record's dismissal cannot commit. **The entry is left marked
                departing then, which is the safe direction**: a marked entry
                participates in no transition but its own removal, so no later poll
                can select it, and §3b's reconciliation completes what this call
                could not.
        """
        async with self._lock:
            marked = await _run_to_completion(self._mark_withdrawn_sync, record_id)
            if marked is None:
                return False
            key, sequence = marked
            dismissed = await self._dismiss(record_id)
            await _run_to_completion(self._remove_sync, key, sequence)
            return dismissed

    def _mark_withdrawn_sync(self, record_id: str) -> tuple[str, int] | None:
        """Mark the entry carrying one record, returning the row it marked."""
        with self._transaction("withdraw an outbox entry") as conn:
            rows = self._rows(
                conn,
                "read the withdrawn entry",
                "SELECT candidate_key, sequence FROM outbox WHERE record_id = ?",
                (record_id,),
            )
            if not rows:
                return None
            key = str(rows[0][0])
            sequence = _require_int(rows[0][1], what="a withdrawn entry's order")
            conn.execute(
                "UPDATE outbox SET departing = 1 WHERE candidate_key = ? AND sequence = ?",
                (key, sequence),
            )
            return key, sequence

    # --- startup reconciliation (ADR-0131 §3b) -------------------------------

    async def recover_leases(self) -> None:
        """Void every lease this hub inherited from the process before it (§3).

        ADR-0131 §3: "A hub restart voids every lease. An entry leased when the hub
        stopped is available again when it starts, and no lease survives the
        process that granted it." §3 argues it is "the only answer that is both
        correct and free" because "an entry still leased at startup is one whose
        holder is definitionally gone".

        **A step of its own, because the argument above is about a restart and
        nothing here can detect one.** An earlier shape hung the voiding off the
        first :meth:`reconcile` of each outbox *object*, which reads as
        once-per-process and is not: a second object over the same database in the
        same live process begins un-voided, and its first reconciliation strips the
        lease from a device the first object is currently delivering to — one entry
        outstanding to two devices, which §3 forbids outright. ADR-0131 §3
        deliberately does not say who detects a restart, so this method makes no
        claim to: **it voids unconditionally, every time it is called**, and the
        caller owns the once-ness. The caller is
        :meth:`~ai_assistant.orchestration.engine.Engine.start`, which is what the
        hub starts, and the chain that makes it once per restart runs instance lock
        → one hub process → one composition root → one engine → one recovery.

        Leaving :meth:`reconcile` purely repeatable is the other half of the same
        move, and is what ``Engine.start``'s documented "safe to call more than
        once" actually needs.

        Raises:
            NotificationOutboxError: If the outbox cannot be written.
        """
        async with self._lock:
            await _run_to_completion(self._void_leases_sync)

    async def reconcile(self) -> None:
        """Make the two stores agree, in **both** directions, before any poll runs.

        ADR-0131 §3b: "every ADR-0130 record ruled ``INTERRUPT`` and still
        **actionable** for which the outbox holds no entry has its candidate
        offered, and every **departing** entry (§3) — dismissed or expired — is
        removed."

        **Both directions, because a repair that runs one way leaves the other way
        accumulating.** A draft reconciled only the missing-entry direction, and a
        removal that failed — a crashed hub, a store error — leaves a departing
        entry which that sweep never looks at: it has a record, so the missing-entry
        pass skips it, and it is undeliverable while still counting against both
        bounds. Repeat that and the outbox fills with entries nothing can clear.

        **It is a repair and never the trigger a notification relies on** (§3b). The
        live handoff is the primary path; a repair that is also the primary path is
        a design where the ordinary case waits on a restart. It is idempotent by
        §3's key rule, since every path keys on the candidate's own
        ``candidate_key``, and it requires no state of its own — both directions are
        read off the two stores as they stand.

        **It touches no lease**, and that separation is deliberate. Voiding the
        leases a restart inherited is §3's own clause but it is not a repair the two
        stores disagreeing calls for, and hanging it off this method made it happen
        once per outbox *object* — which is not once per restart. It has its own
        step, :meth:`recover_leases`, invoked by ``Engine.start``; everything here
        is repeatable, which is what that method's promise that it is safe to call
        more than once actually requires.

        Raises:
            NotificationOutboxError: If either store cannot be read or written.
        """
        async with self._lock:
            await self._settle_departing()
            records = await self._held_records()
            now = self._now()
            keyed = await _run_to_completion(self._keys_sync)
        for record in records:
            if record.kind is not NotificationDispositionKind.INTERRUPT:
                continue
            if not record.is_actionable_at(now):
                continue
            if record.candidate.candidate_key in keyed:
                continue
            await self._offer(record.candidate, reconciled=True)

    def _void_leases_sync(self) -> None:
        """Void every lease the stopped process granted (ADR-0131 §3)."""
        with self._transaction("void the outbox leases a restart ended") as conn:
            conn.execute("UPDATE outbox SET delivery_id = NULL, leased_at = NULL")

    def _keys_sync(self) -> set[str]:
        with self._transaction("read the outbox keys", immediate=False) as conn:
            return {entry.key for entry in self._all(conn)}

    async def _settle_departing(self) -> None:
        """Finish every departure a crash or a store failure left half-done.

        Called from :meth:`reconcile` and from the head of :meth:`offer`, so the
        repair is routine rather than restart-only. It dismisses **before** it
        removes, which is what keeps §3b's invariant true whichever of the two
        points a previous attempt died at: an entry marked with an actionable
        record has its record dismissed here and is then removed, and one whose
        record was already dismissed simply has the removal completed.

        The caller holds the lock.
        """
        now = self._now()
        departing = await _run_to_completion(self._departing_sync, now)
        for entry in departing:
            await self._dismiss(entry.record_id)
            await _run_to_completion(self._remove_sync, entry.key, entry.sequence)

    def _departing_sync(self, now: datetime) -> list[_Entry]:
        with self._transaction("read the departing outbox entries", immediate=False) as conn:
            return [entry for entry in self._all(conn) if entry.is_departing_at(now)]

    # --- waking a parked poll ------------------------------------------------

    def _wake(self) -> None:
        """Report that an entry may have become available."""
        self._arrivals.set()

    async def wait_for_arrival(
        self,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's own poll budget, not a deadline this seam owns (ADR-0029 §4)
    ) -> bool:
        """Park until an entry may be available, or until ``timeout`` elapses.

        **A wake is a hint and never a guarantee**, which is what keeps a poll
        correct without a durable subscription: a caller that misses one falls back
        on its own deadline and re-reads the outbox, and a caller woken spuriously
        finds nothing and parks again. Correctness rests on the re-read, so a
        notification enqueued by another process — which this event cannot see —
        costs latency rather than delivery.

        **The timeout, by contrast, is a fact the caller may act on**, and saying
        so is what stops the caller's loop becoming a spin: a wait that returned
        without waiting would have it re-read, find nothing and ask to wait again,
        forever wherever the caller's clock is injected and does not move.

        Args:
            timeout: How long to wait at most.

        Returns:
            Whether an arrival may have happened; ``False`` where the wait ran out.
        """
        try:
            await asyncio.wait_for(self._arrivals.wait(), timeout.total_seconds())
        except TimeoutError:
            return False
        return True

    async def _resolve_record(self, candidate_key: str) -> str | None:
        """The id of the actionable ADR-0130 record this candidate belongs to.

        Held on the entry so that every departure can dismiss its record without a
        second walk of the record store. ``None`` where no record is found, which
        is the ordinary case for a caller that offers a candidate no writer ruled —
        a test, or a producer that keeps its own records — and which §3b's "nothing
        further is owed" covers at every departure.

        Raises:
            NotificationOutboxError: If the record store cannot be read.
        """
        now = self._now()
        for record in await self._held_records():
            if record.candidate.candidate_key == candidate_key and record.is_actionable_at(now):
                return str(record.id)
        return None


def _check_bounds(
    *, lease: timedelta, max_entries: int, max_bytes: int, candidate_ceiling: int
) -> None:
    """Refuse a bound that cannot hold, at construction (ADR-0131 §5a).

    None of these is nullable and none may be zero: a hub serving delivery with no
    lease, no outbox bound or no delivery ceiling has exactly the failure the
    clause naming it exists to prevent, so "off" is not an available value.

    Raises:
        ValueError: If any figure is not strictly positive.
    """
    if lease.total_seconds() <= 0:
        msg = f"hub_notification_lease must be positive, got {lease!r} (ADR-0131 §5a)"
        raise ValueError(msg)
    for name, value in (
        ("hub_notification_outbox_entries", max_entries),
        ("hub_notification_outbox_bytes", max_bytes),
        ("the delivery ceiling", candidate_ceiling),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            msg = f"{name} must be a positive integer, got {value!r} (ADR-0131 §5a)"
            raise ValueError(msg)


def _entry_from(row: Sequence[object]) -> _Entry:
    """Decode one stored row.

    Raises:
        NotificationOutboxError: If the stored candidate no longer validates,
            which is a corrupt outbox rather than a caller's fault.
    """
    key, encoded, record_id, sequence, delivery_id, leased_at, departing, cost = row
    try:
        candidate = NotificationCandidate.model_validate_json(str(encoded))
    except ValidationError as exc:
        msg = f"a stored outbox entry no longer validates: {exc}"
        raise NotificationOutboxError(msg) from exc
    leased = _int_from(leased_at, what="an outbox lease instant")
    return _Entry(
        key=str(key),
        candidate=candidate,
        record_id=None if record_id is None else str(record_id),
        sequence=_require_int(sequence, what="an outbox entry's order"),
        delivery_id=None if delivery_id is None else str(delivery_id),
        leased_at=leased,
        departing=bool(_require_int(departing, what="an outbox entry's departing flag")),
        cost=_require_int(cost, what="an outbox entry's byte cost"),
    )


def _require_int(value: object, *, what: str) -> int:
    """Narrow one stored integer column, or refuse the row as corrupt.

    ``sqlite3`` types a column's value as ``object`` to a type checker, and a
    ``cast`` would assert what this checks. A row that is not what the schema
    declares is a corrupt outbox rather than a caller's fault, so it raises this
    seam's error rather than a ``TypeError`` from somewhere further in.

    Raises:
        NotificationOutboxError: If the stored value is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{what} is stored as {type(value).__name__} rather than an integer"
        raise NotificationOutboxError(msg)
    return value


def _int_from(value: object, *, what: str) -> int | None:
    """Narrow one nullable stored integer column, keeping ``NULL`` as ``None``.

    Raises:
        NotificationOutboxError: If a present value is not an integer.
    """
    return None if value is None else _require_int(value, what=what)


__all__ = ["SqliteNotificationOutbox"]
