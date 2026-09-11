"""A durable :class:`~ai_assistant.core.protocols.ParkedReads` on SQLite.

ADR-0244 §3's store, and ADR-0244 §18's Lane 2. It holds the questions a recorded
``CONFIRM`` on a read left standing: one row per park, carrying the search request's
own ``parameters``, the ``Goal`` the parked turn was planned against and the
``ActionPlan`` the planner returned on it, until the question is answered, denied,
withdrawn or expires — at which point the three go and six scalar facts remain.

**Here in ``permissions/``, for the reason
:class:`~ai_assistant.permissions.reads.SqliteSourceReadTrail` already is.** ADR-0004 §7
charters this subsystem for gating access to Tier 0/1 data *and* recording it, and a park
is the unanswered half of a recorded permission question, joined to the trail by
``decision_id``. It is deliberately **not** the ``AuditTrail`` (ADR-0244 §3): that store's
invariants are stated over ``tool``, ``parameters_digest``, ``step_id`` and
``execution_id``, and putting the query itself into it would breach ADR-0148 §6's "bound
by digest, never stored" in the one store that clause is about.

**Three of the nine fields are Tier 1 content, so ADR-0004 §2's residency clause governs
the file**: it is written locally only, under ``Settings.data_dir``, never to a remote
service, and it is created owner-only (ADR-0004 §4, ADR-0084 §9) before the first
statement, so a rollback journal SQLite opens for it inherits that mode rather than the
process umask. ADR-0004 §5's "Tier 0/1 data must never be logged" binds without
qualification: nothing here interpolates a park's ``parameters``, ``goal`` or ``plan``
into a message, a log line or an exception.

**What the database enforces, rather than this module's care.** ADR-0244 §3 puts three
invariants on the *store* and says so in terms — a conversation holds at most one ``OPEN``
park, one park names one decision, and a settlement clears the content **in the same step**
that moves the disposition — and each is a claim about what two engines over one data
directory can reach, not about what one caller remembers to do. So each is stated to
SQLite: a partial ``UNIQUE`` index over the open rows, a ``UNIQUE`` index over
``decision_id``, and :data:`_SETTLE_ONLY`, a trigger admitting exactly one mutation. The
guarded reads in :meth:`SqliteParkedReads._park_sync` are what turn the first two into
ADR-0244 §3's **answer** — ``False``, never a raise, because §1's third clause is written
over that answer — and the constraints are what make them true of the file rather than of
one process.

**Atomicity is ``BEGIN IMMEDIATE`` plus an :class:`asyncio.Lock`**, the shape every SQLite
store in this package takes. The write lock is taken before the read the write depends on,
which is what closes ``park``'s check-then-insert and ``settle``'s compare-and-swap against
a second process; the lock closes them within this one. ADR-0244 §19's Arm 9 — "two
concurrent ``park`` calls for one conversation yield exactly one park; two concurrent
``settle`` calls for one park yield exactly one ``True``" — is one of the three arms §19
names as the ones "this decision would be worthless without".

**ADR-0244 mints no error class** (§9), so a store that cannot be read or written raises
:class:`~ai_assistant.core.errors.AssistantError` itself — the class the ``ParkedReads``
Protocol declares at every member and the class
:class:`~ai_assistant.testing.parked_reads.FakeParkedReads` raises. A new subtype would be
minting one in ``core/errors.py`` on a decision that rules against it; borrowing a
neighbour's — :class:`~ai_assistant.core.errors.ReadTrailError`, say — would give a caller
one ``except`` clause catching two stores whose recourses differ. Every caller in
``orchestration`` treats a raise from :meth:`SqliteParkedReads.park` exactly as ADR-0244
§1's third clause rules: **no park exists**, nothing is outstanding, and the servicing is
exactly what it is today.

**No busy timeout is set here, and that is the family's posture rather than this store's
choice** (#564): no SQLite store in this tree sets one deliberately, so under cross-process
contention ``BEGIN IMMEDIATE`` surfaces ``SQLITE_BUSY`` after the driver's default.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import ParkedRead, ParkedReadDisposition
from ai_assistant.permissions._detachment import field_state
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

__all__ = ["SqliteParkedReads"]

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages the
#: database does, so ADR-0004 §4 reaches them too — the family shares
#: :meth:`SqliteParkedReads._restrict_permissions` by copy today (#506), and this store
#: takes its copy rather than making a fresh choice.
_SIDECARS = ("-journal", "-wal", "-shm")

#: The three fields ADR-0244 §3's settlement clears, named once so the clause and every
#: assertion about it cannot come apart.
_CONTENT: Final = ("parameters", "goal", "plan")


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    **A copy of the family's helper rather than an import from a sibling**, which is the
    tree's established position rather than a fresh choice: every SQLite store in this tree
    carries its own, and #506 and #563 already track consolidating the family. A private import
    from :mod:`ai_assistant.permissions.destination_trust` would make one store's helper
    silently govern another's.

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock` and
    runs the SQL in a worker thread. A thread cannot be interrupted, so if the awaiting
    coroutine were simply cancelled the enclosing ``async with self._lock`` would unwind
    and release the lock **while the worker was still using the connection** — letting a
    second caller use the same connection concurrently, which SQLite refuses. The worker
    records its own outcome and sets a :class:`threading.Event` when it physically returns;
    this coroutine waits on *that* signal, so the lock is held for the whole life of the
    worker even under a blanket task cancellation.

    The completion wait is submitted **at most once** (#697): a copy that submits a fresh
    one per cancellation leaves every earlier one parked in ``Event.wait``, which turns one
    stalled store operation into a process that cannot run any thread work at all.
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
    waiting: asyncio.Future[Any] | None = None
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


#: One shape only, so far, and there is no ``_migrate`` here because version 1 is the first
#: shape this store has ever had: an unlabelled database is one this code is creating now,
#: and it is stamped rather than migrated.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code cannot read
#: is refused *before* the ``parked_reads`` table is created or read — creating a table is
#: a write, and the refusal precedes any write.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the sort keys count from. Any fixed instant would do; this one is conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# **The blob is the record, and every column that decides anything is derived from it.**
# ``id``, ``conversation_id``, ``decision_id`` and ``disposition`` are ``GENERATED ALWAYS``
# from the JSON, which is `SqliteDestinationTrustStore`'s shape one module over and is taken
# for its reason: a stored column that merely *agreed* with the blob when it was written is
# a second copy of a value, and a store whose uniqueness constraints read the copy while its
# answer decodes the blob can be made to hold two open parks for one conversation. Derived,
# they cannot disagree — which matters more here than anywhere in this package, because
# three of this store's four constraints are indexes and a trigger over these very columns.
#
# **``parked_at_us`` is a plain column and decides nothing.** It exists because
# ``outstanding`` is contractually in ``parked_at`` order and SQLite cannot sort an ISO-8601
# instant correctly — ``"…:00.000001Z"`` sorts *before* ``"…:00Z"`` by code point, so a
# generated column over ``json_extract`` would put a later park first. What is left on it is
# an ordering, and :data:`_SETTLE_ONLY` is what holds it across the one mutation.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS parked_reads("
    "parked_at_us INTEGER NOT NULL, data TEXT NOT NULL, "
    "id TEXT GENERATED ALWAYS AS (json_extract(data, '$.id')) VIRTUAL, "
    "conversation_id TEXT GENERATED ALWAYS AS (json_extract(data, '$.conversation_id')) "
    "VIRTUAL, "
    "decision_id TEXT GENERATED ALWAYS AS (json_extract(data, '$.decision_id')) VIRTUAL, "
    "disposition TEXT GENERATED ALWAYS AS (json_extract(data, '$.disposition')) VIRTUAL)"
)

#: Keyed by name, because :data:`_OBJECTS` holds each one to its own definition and a
#: positional tuple would make that mapping a place to get wrong.
_INDEXES = {
    # The primary key `id` cannot be, because SQLite refuses a generated column in one.
    # Same constraint, same enforcement, and the derivation is kept.
    "parked_reads_id": "CREATE UNIQUE INDEX IF NOT EXISTS parked_reads_id ON parked_reads(id)",
    # **One park names one decision** (ADR-0244 §3), said to the database. It is what makes
    # `park_of_decision` a single answer rather than a listing, and §3 states it "so that an
    # implementation cannot reach a state where two rows answer one decision id" — a
    # sentence about a *state*, which a guarded read alone cannot promise of a file two
    # engines share.
    "parked_reads_decision": (
        "CREATE UNIQUE INDEX IF NOT EXISTS parked_reads_decision ON parked_reads(decision_id)"
    ),
    # **A conversation holds at most one ``OPEN`` park** (ADR-0244 §3), for `admit_search`'s
    # own reason (ADR-0238 §8): "two turns of one conversation, two servicings of one turn,
    # and two engines over one data directory can none of them be admitted against the same
    # conversation's park." A *partial* index, over the open rows alone, is what makes that
    # the rule ADR-0244 §3 states rather than one park per conversation ever — a settled
    # park leaves the index and the conversation's one slot is free again, which is §11's
    # "a cancelled park frees the conversation's one open-park slot".
    "parked_reads_one_open": (
        "CREATE UNIQUE INDEX IF NOT EXISTS parked_reads_one_open ON parked_reads"
        "(conversation_id) WHERE disposition = 'open'"
    ),
    # ``outstanding``'s order, with ``id`` as the tie-break so two parks written at one
    # instant are enumerated in a fixed order rather than in whatever order the file holds.
    "parked_reads_order": (
        "CREATE INDEX IF NOT EXISTS parked_reads_order ON parked_reads(parked_at_us ASC, id ASC)"
    ),
}

#: **The one mutation this store admits, said to SQLite rather than only to the reader.**
#: ADR-0244 §3 rules that ``settle`` moves an ``OPEN`` park to a terminal member and clears
#: ``parameters``, ``goal`` and ``plan`` *in the same step*, that an already-terminal park
#: "answers ``False`` and changes nothing", and (§2) that **no transition leaves a terminal
#: member**. This trigger is what makes all three claims the database keeps rather than ones
#: this module remembers: an ``UPDATE`` is admitted only where the row was open, is not open
#: afterwards, carries none of the three content fields, and leaves every terminal fact —
#: ``id``, ``conversation_id``, ``decision_id``, ``parked_at`` and ``expires_at``, and the
#: ordering key derived from the first of those — byte for byte as it was.
#:
#: **What it is and is not.** It is this store's invariant enforced by the store, the way a
#: ``UNIQUE`` index enforces write-once; it is not a boundary against an actor who can
#: already run arbitrary SQL against the file, who could drop it as easily as run the
#: ``UPDATE``. ADR-0004 §4's owner-only mode is where that question is answered, and
#: ADR-0099 §1's single-user model is what scopes it.
_SETTLE_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS parked_reads_settle_only "
    "BEFORE UPDATE ON parked_reads "
    "WHEN OLD.disposition IS NOT 'open' OR NEW.disposition IS 'open' "
    "OR NEW.id IS NOT OLD.id OR NEW.conversation_id IS NOT OLD.conversation_id "
    "OR NEW.decision_id IS NOT OLD.decision_id "
    "OR NEW.parked_at_us IS NOT OLD.parked_at_us "
    "OR json_extract(NEW.data, '$.parked_at') IS NOT json_extract(OLD.data, '$.parked_at') "
    "OR json_extract(NEW.data, '$.expires_at') IS NOT json_extract(OLD.data, '$.expires_at') "
    "OR json_extract(NEW.data, '$.parameters') IS NOT NULL "
    "OR json_extract(NEW.data, '$.goal') IS NOT NULL "
    "OR json_extract(NEW.data, '$.plan') IS NOT NULL "
    "BEGIN SELECT RAISE(ABORT, 'a parked read is mutated only by settling an open park: "
    "the disposition moves to a terminal member, the three content fields are cleared in "
    "the same step, and every terminal fact stands (ADR-0244 §2, §3)'); END"
)

#: **Every object this store defines, held to its own definition.** ``CREATE TABLE IF NOT
#: EXISTS`` is a no-op against a table already there under that name *whatever shape it
#: has*, so a file arriving with a ``parked_reads`` table of ordinary columns would keep it
#: — and all four generated projections would then read as ``NULL``, because
#: :meth:`SqliteParkedReads._park_sync` writes only ``parked_at_us`` and ``data``. Every
#: park would then answer as neither open nor terminal, the two uniqueness constraints
#: would constrain nothing, and the settle trigger would fire on the wrong rows: the exact
#: failures the generated columns exist to make impossible, walked around rather than
#: through. The indexes and the trigger are held the same way and for the same reason.
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds is
#: compared against these very statements rather than against a second copy of them written
#: out by hand.
_OBJECTS: Final = {
    "parked_reads": _CREATE_TABLE,
    **_INDEXES,
    "parked_reads_settle_only": _SETTLE_ONLY,
}

_BY_ID = "SELECT data FROM parked_reads WHERE id = ?"

_ID_IS_HELD = "SELECT 1 FROM parked_reads WHERE id = ?"

_DECISION_IS_HELD = "SELECT 1 FROM parked_reads WHERE decision_id = ?"

_BY_DECISION = "SELECT data FROM parked_reads WHERE decision_id = ?"

_OPEN_OF_CONVERSATION = (
    "SELECT data FROM parked_reads WHERE conversation_id = ? AND disposition = 'open'"
)

#: Every ``OPEN`` park, oldest first. **No instant appears in this statement at all**, which
#: is ADR-0244 §3's clause rather than an omission: this member "reports what is ``OPEN`` and
#: takes no view of the clock", because ADR-0244 §5 puts the expiry settlement at the read,
#: in the engine — a store that read a clock would be deciding a lifetime it does not own.
_OUTSTANDING = (
    "SELECT data FROM parked_reads WHERE disposition = 'open' ORDER BY parked_at_us ASC, id ASC"
)

#: The settlement, guarded on the disposition it is moving *from*. The guard is what makes
#: the compare and the write one statement rather than a read this coroutine acts on: the
#: row's own state decides whether the update matches, so exactly one of two concurrent
#: callers can see a row changed and the other sees none.
_SETTLE = "UPDATE parked_reads SET data = ? WHERE id = ? AND disposition = 'open'"

_DROP_FOR_CONVERSATION = "DELETE FROM parked_reads WHERE conversation_id = ?"


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than from
    ``timestamp()``. Ordering is part of :meth:`SqliteParkedReads.outstanding`'s contract,
    and a float epoch second carrying microsecond precision needs sixteen significant digits
    at present-day values — right at the edge of a double, so two parks a microsecond apart
    could compare equal or invert. The subtraction below is exact.

    ``parked_at`` is a ``UtcInstant``, already normalised to UTC by ``core``, so this is a
    key over *instants* — which is what makes the DST repeated hour sort correctly rather
    than by wall clock.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


class SqliteParkedReads:
    """A persistent, validating ``ParkedReads`` (ADR-0244 §3, §18).

    Structurally implements :class:`~ai_assistant.core.protocols.ParkedReads`.

    **Records are stored as their JSON dump and rebuilt on every read**, which is how the
    detachment obligation is obtained here without a copy step to forget: serialising
    rebuilds every reachable value, so there is no object graph shared with the caller in
    either direction, and the store cannot hand back a caller-supplied subclass. It bites
    hardest on this surface, because a park's ``goal`` and ``plan`` are models whose own
    members a caller could otherwise reach.

    **The write-side snapshot is taken from the instance's own field state**, not from
    ``model_dump()`` — see :func:`_revalidated`.
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the parked-read store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                implementation exists — ADR-0244 §15 rules the park the thing that survives
                a restart, and a token minted before one must find its park after it — so a
                default would let the ordinary construction produce a store that forgets the
                user's outstanding question. An ephemeral store is available and has to be
                asked for. It lives under ``Settings.data_dir`` in a real deployment, which
                is the composition root's choice rather than this class's.

        Raises:
            AssistantError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening ----------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL raises it out
            # of the driver rather than a ``sqlite3.Error``, and a bad path is this layer's
            # fault to report rather than a raw builtin escaping past its error boundary.
            msg = f"failed to open the parked-read store at {self._path!r}: {exc}"
            raise AssistantError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is built:
            # SQLite copies the database file's mode onto every rollback journal it creates
            # for it, so a journal opened while the file still carried the process umask is
            # world-readable too — and an interrupted write leaves it on disk holding the
            # Tier 1 pages a park's three content fields are (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                # The table is held to its definition **before** the indexes and the trigger
                # are created over it. A file arriving with a ``parked_reads`` table of
                # ordinary columns would otherwise fail on an index naming a column it does
                # not have, and the open would report a raw SQLite complaint instead of the
                # fact — that this is not this store's table and its rows cannot be trusted
                # to say what the user was asked.
                self._check_objects(conn, ("parked_reads",))
                for statement in _INDEXES.values():
                    conn.execute(statement)
                conn.execute(_SETTLE_ONLY)
                self._check_objects(conn, tuple(_OBJECTS))
                if not labelled:
                    # Stamped *after* the creates above, and inside the same transaction, so
                    # a failure rolls the marker — and the ``meta`` table itself — back with
                    # it rather than leaving a database falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except AssistantError:
            # A refused schema version or object is already this layer's error; it still
            # leaves a connection to close before it propagates.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the parked-read store at {self._path!r}: {exc}"
            raise AssistantError(msg) from exc
        return conn

    def _check_objects(self, conn: sqlite3.Connection, names: tuple[str, ...]) -> None:
        """Refuse a file whose ``names`` are not the objects this store defines.

        Run after the creates and **before** the marker is written, inside the same
        transaction, so a refusal leaves the file exactly as it arrived — unopened,
        unlabelled, and not carrying this store's marker over a shape that is not this
        store's. See :data:`_OBJECTS` for what each one buys.

        Args:
            conn: The connection the setup transaction is running on.
            names: Which of :data:`_OBJECTS` to check. The table alone runs first, so a file
                that is not this store's is reported as that rather than as an index failing
                on a column it does not have.

        Raises:
            AssistantError: If an object is missing or is not the one this store defines.
        """
        held = {
            str(name): sql
            for name, sql in conn.execute("SELECT name, sql FROM sqlite_master")
            if name in names
        }
        for name in names:
            defined = _OBJECTS[name].replace(" IF NOT EXISTS", "", 1)
            if held.get(name) != defined:
                msg = (
                    f"the parked-read store at {self._path!r} holds an object named {name!r} "
                    f"that is not the one this store defines; its rows cannot be trusted to "
                    f"hold one open park per conversation, so it is not opened"
                )
                raise AssistantError(msg)

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault, so absence is tolerated
        one name at a time; nothing else is. A *symlink* under a sidecar's name is skipped
        rather than followed, because ``chmod`` follows links and restricting one would
        silently narrow a file this store has no business modifying. A no-op in memory.

        **Duplicated from the other SQLite stores on purpose** (#506): the family shares
        this method by copy today, and consolidating it is that issue's, not this lane's.
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

    def _check_schema_version(self, conn: sqlite3.Connection) -> bool:
        """Refuse a labelled schema this code cannot read; say whether one is labelled.

        Runs inside the setup transaction, after ``meta`` exists and **before** the
        ``parked_reads`` table is created or read.

        **An unlabelled database is stamped rather than migrated**: this store ships *with*
        its marker, so version 1 is the only shape it has ever written and an unlabelled
        file is one this open is creating.

        Returns:
            Whether the database already carries a ``schema_version``.

        Raises:
            AssistantError: If the stored version is not one this code understands, is not
                an integer at all, or is not a single unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # ``meta``'s primary key makes this unreachable for a table *this* code created
            # — but ``CREATE TABLE IF NOT EXISTS`` accepts a pre-existing ``meta`` declared
            # without one, so a corrupt or hand-built file can hold conflicting markers, and
            # reading the first row would let an unsupported version through on the strength
            # of a sibling that agrees.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the parked-read store at {self._path!r} holds {len(rows)} schema_version "
                f"rows ({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise AssistantError(msg)
        raw = rows[0][0]
        msg = f"the parked-read store at {self._path!r} holds a non-numeric schema_version {raw!r}"
        # The marker this code writes is always TEXT, but a hand-built ``meta`` may declare
        # no type, in which case SQLite hands back whatever was stored.
        # ``int(float("inf"))`` raises ``OverflowError``, which is neither ``ValueError`` nor
        # an ``AssistantError`` and would leave this layer's boundary through a hole.
        # ``bool`` is an ``int`` in Python, so it is named rather than left to read as
        # version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise AssistantError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise AssistantError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the parked-read store at {self._path!r} has schema_version={stored}, but "
                f"this code supports only version {_SCHEMA_VERSION}; refusing to open it "
                f"rather than read it blindly"
            )
            raise AssistantError(msg)
        return True

    def _transaction(self, what: str) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write, which is
        what puts :meth:`_park_sync`'s *reads* under it: the free-id check, the
        one-park-per-decision refusal and the one-open-park refusal all decide whether the
        insert may happen, so a deferred begin would let a second process observe the same
        free id or the same absent open park between them and the insert. The ``asyncio``
        lock closes that within one process; this closes it against the file. The uniqueness
        constraints behind both are what make the *state* unreachable either way (ADR-0244
        §3), and this is what makes the **answer** ``False`` rather than a raise.

        Raises:
            AssistantError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=AssistantError, immediate=True)

    # --- the write path ---------------------------------------------------

    async def park(self, record: ParkedRead, /) -> bool:
        """Write an ``OPEN`` park, or answer ``False`` where one already stands.

        **The read of the existing park and the write are one indivisible step** (ADR-0244
        §3): both refusals are decided inside one ``BEGIN IMMEDIATE`` transaction with the
        insert, so two turns of one conversation, two servicings of one turn and two engines
        over one data directory can none of them be admitted against the same conversation's
        park.

        Args:
            record: The park to write. Its ``disposition`` is ``OPEN``.

        Returns:
            ``True`` where this call wrote the park; ``False`` where this conversation
            already holds an ``OPEN`` one, or where a park already names this decision.

        Raises:
            AssistantError: If the record does not satisfy its own model, if its
                ``disposition`` is not ``OPEN``, if its id is already recorded, or if the
                database refuses the write. Pydantic's ``ValidationError`` is deliberately
                not allowed to escape: ``CONTRIBUTING`` has this layer raise only from the
                ``AssistantError`` hierarchy.
        """
        snapshot = _revalidated(record)
        if snapshot.disposition is not ParkedReadDisposition.OPEN:
            msg = (
                f"park {snapshot.id!r} is written OPEN; a terminal park is reached by "
                f"settlement and never by a write (ADR-0244 §2, §3)"
            )
            raise AssistantError(msg)
        async with self._lock:
            return await _run_to_completion(self._park_sync, snapshot)

    def _park_sync(self, snapshot: ParkedRead) -> bool:
        """Apply ADR-0244 §3's two refusals and insert, as one transaction.

        The id check is a **raise** and the other two are an **answer**, and the split is
        ADR-0244 §3's own. A conversation that already holds an open park, or a decision a
        park already names, are states the servicing reaches on an ordinary turn and ADR-0244
        §1's third clause is written over the ``False`` they produce. A duplicate *id* is
        not: ids are minted by the injected factory, one park per minting, so a second write
        under one id is a caller replaying a write into a store that is write-once — the
        posture every store in this package takes.

        Returns:
            Whether the park was written.

        Raises:
            AssistantError: If the id is already recorded, or the database refuses.
        """
        with self._transaction(f"write parked read {snapshot.id!r}") as conn:
            if conn.execute(_ID_IS_HELD, (snapshot.id,)).fetchone():
                msg = (
                    f"park {snapshot.id!r} is already recorded; a park's id is minted once "
                    f"and a second write under it would rewrite a standing question"
                )
                raise AssistantError(msg)
            if conn.execute(_DECISION_IS_HELD, (snapshot.decision_id,)).fetchone():
                # **One park names one decision** (ADR-0244 §3), which is what makes
                # `park_of_decision` a single answer rather than a listing.
                return False
            if conn.execute(_OPEN_OF_CONVERSATION, (snapshot.conversation_id,)).fetchone():
                # **A conversation holds at most one ``OPEN`` park** (ADR-0244 §3).
                return False
            # Only the two stored columns: the four projections are derived from the blob by
            # the table's own definition, so there is nothing to write and nothing that could
            # be written disagreeing with it.
            conn.execute(
                "INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)",
                (_sort_key(snapshot.parked_at), snapshot.model_dump_json()),
            )
            return True

    async def settle(
        self, park_id: str, /, *, disposition: ParkedReadDisposition, at: datetime
    ) -> bool:
        """Move an ``OPEN`` park to a terminal member and clear its content.

        **The resolve-once gate** (ADR-0244 §3, §6). The read, the comparison and the write
        are one indivisible step — one guarded ``UPDATE`` inside one ``BEGIN IMMEDIATE``
        transaction — so exactly one of two concurrent callers is answered ``True``, and a
        caller answered ``False`` "dispatches nothing, sends nothing and reports the settled
        state".

        **``at`` lands in no field here, and that is ADR-0244 §3 rather than a gap.** The
        terminal facts a settled park keeps are its ``id``, ``conversation_id``,
        ``decision_id``, ``parked_at``, ``expires_at`` and ``disposition``; there is no
        settled-at member on :class:`~ai_assistant.core.types.ParkedRead`, ADR-0244 §3
        forbids a store adding "a stamp of its own", and this store mints none. What the
        contract obliges is that the caller supplies the instant rather than the store
        reading a clock, which is the rule every store on this surface holds — and it is why
        the parameter is taken rather than removed.

        Args:
            park_id: The park to settle.
            disposition: The terminal member to move it to.
            at: The instant the caller took the settlement at.

        Returns:
            ``True`` where this call moved the park; ``False`` where it was already terminal
            or no row holds that id.

        Raises:
            AssistantError: If the store could not be written.
            ValueError: If ``disposition`` is ``OPEN``, which is not a settlement.
        """
        del at  # see above: a settled park keeps no settled-at fact for this store to hold
        if disposition is ParkedReadDisposition.OPEN:
            msg = (
                "settle moves a park to a terminal disposition; OPEN is not a settlement "
                "and no transition leaves a terminal member (ADR-0244 §2, §3)"
            )
            raise ValueError(msg)
        async with self._lock:
            return await _run_to_completion(self._settle_sync, park_id, disposition)

    def _settle_sync(self, park_id: str, disposition: ParkedReadDisposition) -> bool:
        """Read, clear and move the park, as one transaction.

        The content is cleared **through the record's own model** rather than by editing the
        JSON in SQL, which is what makes ADR-0244 §2's terminal shape a thing the type
        guarantees: a settled park carrying any of the three is refused at construction here,
        as it would be on the way back out. :data:`_SETTLE_ONLY` is the second statement of
        the same rule, to the database, for the rows this code did not write.
        """
        with self._transaction(f"settle parked read {park_id!r}") as conn:
            row = conn.execute(_BY_ID, (park_id,)).fetchone()
            if row is None:
                return False
            held = self._decode(row[0])
            if held.disposition is not ParkedReadDisposition.OPEN:
                return False
            settled = ParkedRead.model_validate(
                {
                    **held.model_dump(),
                    "disposition": disposition,
                    **dict.fromkeys(_CONTENT),
                }
            )
            cursor = conn.execute(_SETTLE, (settled.model_dump_json(), park_id))
            return cursor.rowcount == 1

    async def drop_for_conversation(self, conversation_id: str, /) -> int:
        """Remove **every** park of that conversation and answer how many rows went.

        Open and terminal alike, content and terminal facts alike. The one destructive
        member, the conversation deletion sequence's route, and **idempotent**: a second call
        answers ``0`` (ADR-0244 §3).

        Args:
            conversation_id: The conversation whose parks to remove.

        Returns:
            How many rows were removed.

        Raises:
            AssistantError: If the store could not be written.
        """
        async with self._lock:
            return await _run_to_completion(self._drop_sync, conversation_id)

    def _drop_sync(self, conversation_id: str) -> int:
        with self._transaction(f"drop parked reads for conversation {conversation_id!r}") as conn:
            return int(conn.execute(_DROP_FOR_CONVERSATION, (conversation_id,)).rowcount)

    # --- the read path ----------------------------------------------------

    async def get(self, park_id: str, /) -> ParkedRead | None:
        """The park under that id, whatever its disposition, or ``None``.

        Raises:
            AssistantError: If the store could not be read, or holds a park that no longer
                validates.
        """
        async with self._lock:
            row = await _run_to_completion(
                self._one_sync, _BY_ID, park_id, "read a parked read by its id"
            )
        return None if row is None else self._decode(row)

    async def open_park(self, conversation_id: str, /) -> ParkedRead | None:
        """This conversation's open park, or ``None``.

        Stated over the **disposition** and not over the row's existence: a settled park is
        not this conversation's open one, and the conversation's one slot is free again.

        Raises:
            AssistantError: If the store could not be read, or holds a park that no longer
                validates.
        """
        async with self._lock:
            row = await _run_to_completion(
                self._one_sync,
                _OPEN_OF_CONVERSATION,
                conversation_id,
                "read a conversation's open park",
            )
        return None if row is None else self._decode(row)

    async def park_of_decision(self, decision_id: str, /) -> ParkedRead | None:
        """The park naming that decision, **whatever its disposition**, or ``None``.

        What ADR-0244 §5's eighth ``grantable_decisions`` condition is decided from, and it
        **survives a restart because the row does**: a member answering only an open park
        would let the establishing act resolve a decision whose park had just taken the
        user's answer (§19's Arms 13 and 14).

        Raises:
            AssistantError: If the store could not be read, or holds a park that no longer
                validates.
        """
        async with self._lock:
            row = await _run_to_completion(
                self._one_sync, _BY_DECISION, decision_id, "read the park naming a decision"
            )
        return None if row is None else self._decode(row)

    def _one_sync(self, statement: str, key: str, what: str) -> str | None:
        """Run a one-row read under a deferred transaction, or answer ``None``.

        ``what`` is this store's own phrasing of the operation and never the caller's key:
        ADR-0004 §5 keeps Tier 0/1 content out of every message, and while an id is not
        content, a store that interpolated a caller-supplied string into a diagnostic is one
        byte away from doing so.
        """
        with transaction(self._conn, what, error=AssistantError, immediate=False) as conn:
            row = conn.execute(statement, (key,)).fetchone()
        return None if row is None else str(row[0])

    async def outstanding(self) -> tuple[ParkedRead, ...]:
        """Every ``OPEN`` park, in ``parked_at`` order, oldest first.

        ADR-0244 §5's enumeration. **It lists expired parks too, and settling them is the
        caller's**: §5 puts the settlement at the read rather than in a sweep of its own, so
        this member takes no view of the clock.

        A tuple rather than a list, like every other enumeration on a contract: a caller that
        mutated a returned page has changed nothing about the store's state and may believe
        otherwise (ADR-0085 §3b).

        Raises:
            AssistantError: If the store could not be read, or holds a park that no longer
                validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._outstanding_sync)
        return tuple(self._decode(row[0]) for row in rows)

    def _outstanding_sync(self) -> Sequence[tuple[str]]:
        with transaction(
            self._conn, "read the outstanding parked reads", error=AssistantError, immediate=False
        ) as conn:
            return conn.execute(_OUTSTANDING).fetchall()

    def _decode(self, data: str) -> ParkedRead:
        """Rebuild one stored row.

        Rebuilding is what makes every read a **detached** snapshot: nothing of this store's
        state is reachable from what a caller receives, the park's ``goal`` and ``plan``
        included, and nothing a caller mutates reaches the store.

        Raises:
            AssistantError: If the row does not validate. A stored row that no longer
                satisfies its own model is a corrupt store rather than a caller's mistake,
                and reporting it as an absent park would let an answered question read as
                unasked. **The refusal names no field of the row**: ADR-0244 §2's validator
                fires on exactly the three Tier 1 content fields, so a pydantic message
                rendered whole is the one diagnostic in this store that could carry the
                user's query — ADR-0004 §5 forbids it, and the park id it is keyed by is
                what an operator needs.
        """
        try:
            return ParkedRead.model_validate_json(data)
        except ValidationError as exc:
            msg = (
                f"the parked-read store at {self._path!r} holds a park that no longer "
                f"validates ({exc.error_count()} refusals); the store is corrupt"
            )
            raise AssistantError(msg) from exc

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


def _revalidated(record: ParkedRead) -> ParkedRead:
    """Rebuild ``record`` as a validated :class:`ParkedRead`.

    A copy alone detaches without checking, so a record corrupted past its frozen model's
    guard would be stored and make every later read incoherent — an ``OPEN`` park written
    with no ``parameters`` would be a question with nothing to dispatch, and a terminal one
    written with its query intact would breach ADR-0244 §3's retention rule in the one place
    a reader would not look.

    Rebuilt as a ``ParkedRead`` specifically, not as ``type(record)``: a caller's subclass
    could carry extra fields, and they are refused here rather than allowed to vanish at
    serialisation and make the stored park differ from the one that reloads.

    **And rebuilt from the instance's field state rather than from ``model_dump()``.**
    ``model_dump`` is an ordinary overridable method, so a subclass can return a mapping that
    does not describe itself — a park whose dump names a conversation it does not belong to
    would take that conversation's one open slot, and one whose dump names another decision
    would put a question in front of a ruling it was never taken over.
    :func:`~ai_assistant.permissions._detachment.field_state` is that read, and it detaches
    *recursively*: a mapping of the instance's own field values would still hold the caller's
    ``Goal`` and ``ActionPlan`` objects, which ``frozen=True`` does not protect against a
    write through ``__dict__``.

    **Nothing of the caller's is interpolated into the refusal**, the diagnostic id included:
    ``record`` is typed to take a ``ParkedRead`` and the caller is not obliged by anything at
    runtime to pass one — and a ``ParkedRead``'s own validation message would carry the three
    content fields ADR-0004 §5 keeps out of every message.

    Raises:
        AssistantError: If the record does not satisfy its own model, carries state
            ``ParkedRead`` declares no field for, or holds beneath it a model of any type
            other than exactly the declared one.
    """
    try:
        return ParkedRead.model_validate(field_state(ParkedRead, record))
    except ValueError as exc:
        msg = f"the park offered to this store is not a valid parked read ({type(exc).__name__})"
        raise AssistantError(msg) from exc
