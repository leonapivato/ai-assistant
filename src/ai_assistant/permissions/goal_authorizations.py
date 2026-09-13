"""A durable :class:`~ai_assistant.core.protocols.GoalAuthorizationStore` (ADR-0254 §16).

What the user's own acts bounded about one goal's calls: for one declaration,
against one connected account, over one canonical destination set, with fixed
values and permitted ranges over the **arguments**, until one instant. It is the
record ADR-0148 §3's **route (d)** rests on and the record ADR-0254 §6's
argument-authority bar is taken over.

**One object, three faces.** It satisfies
:class:`~ai_assistant.core.protocols.GoalAuthorizationStore` and therefore
:class:`~ai_assistant.core.protocols.GoalAuthorizations` and
:class:`~ai_assistant.core.protocols.AuthorizationResolution` too, so a
composition root passes *this* object to ``orchestration``, to the
``ActionPolicy`` as the query face, and to the ``AuditTrail`` as the resolution
face. Structural typing is what makes that sound: what a policy cannot do is
**name** ``record``, and what a trail cannot do is name ``record`` or
``live_for``, because ``mypy --strict`` runs over ``src`` and ``tests``
(ADR-0254 §16, on ADR-0097 §3's split).

**Where it departs from :mod:`ai_assistant.permissions.recipient_grants`,
deliberately.** That store is append-only and a revocation *is* an append; this
one **settles a disposition in place**, because an authorization is a question
before it is an authority and ``ParkedRead``'s shape is the one that fits — a
durable row written when the question is put, a deadline computed once at that
instant, a settlement by whatever operation next reads an expired one, and a
disposition that tells an answered question from an abandoned one (ADR-0254 §1,
on ADR-0244). A settlement moves **one field and its instant** and nothing else,
and :data:`_SETTLE_ONLY` states that to SQLite rather than only to the reader.

**And where it departs in what it refuses.** The recipient store admits
overlapping grants over different destination sets; this one admits **at most one
``ESTABLISHED`` row per goal and declaration `id`** (ADR-0254 §1), which is what
makes ``live_for`` answer with one row or none and what §6's bar rests on. The
key is the **id** and not the declaration by value: every pair a value key would
refuse the id key refuses too, and it additionally refuses a second row about an
*edited* declaration of the same id.

**The uniqueness rule is enforced inside the write and is deliberately not also a
partial unique index.** ADR-0254 §1 states the refusal at ``record`` and at
``settle`` — both of which must answer in this seam's own vocabulary, an
:class:`~ai_assistant.core.errors.InvalidAuthorizationError` and an
:attr:`~ai_assistant.core.types.AuthorizationSettlement.WOULD_DUPLICATE` — and a
durable index would be a second statement of one rule whose failure arrives as a
raw integrity error at an unrelated point, which is the drift ADR-0150 is named
after. It would also make §1's **read-side** refusal untestable on this store,
and that is the refusal that matters: ``live_for`` **raises** where two live rows
of a pair would answer, so a state planted behind this store's back takes §6's
bar and asks, rather than authorising a request neither row covers.

**Two clock disciplines, and they are not interchangeable** (ADR-0254 §16).
``live_for`` evaluates liveness, so it reads the clock — **once** per call, and
every row it considers is measured against that one instant. ``record``,
``settle``, ``resolve``, ``standing``, ``recent``, ``export`` and ``clear`` read
**no** clock at all: ``standing`` returns the ``ESTABLISHED`` rows and **the
caller compares**, and ``settle`` and ``record`` take their instants from the
caller because a store neither mints ids nor reads a clock (ADR-0021 §3).

Local-first (ADR-0002), and **locally only**: ADR-0254 §16 rules these records
Tier 1 — a goal statement, an argument value and a span of the user's words are
the user's personal data — and applies ADR-0004 §2's residency clause to them, so
nothing here may reach a remote service. The database file is created owner-only
(ADR-0004 §4, ADR-0084 §9), before the first statement, so a rollback journal
SQLite opens for it inherits that mode rather than the process umask.
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

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import AuthorizationError, InvalidAuthorizationError
from ai_assistant.core.types import (
    Authorization,
    AuthorizationDisposition,
    AuthorizationSettlement,
    BoundKind,
    CoverageMember,
    ValueBound,
    describe_untrusted,
)
from ai_assistant.permissions._detachment import field_state
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too (see
#: :mod:`ai_assistant.permissions.recipient_grants`, whose note this repeats
#: because the family shares this method by copy today — #506).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The largest value SQLite will bind as an integer parameter.
_MAX_SQLITE_INT = 2**63 - 1

#: ADR-0254 §1's transition graph, whole and as data: the five edges, keyed by the
#: disposition each one leaves. **Stated once**, so ``settle``'s refusal and the
#: conformance suite's enumeration cannot disagree about which moves exist. The
#: four dispositions absent as keys are the **retired** ones — no edge leaves
#: them, which is what ``settle`` refuses a move out of.
_EDGES: Final[dict[AuthorizationDisposition, frozenset[AuthorizationDisposition]]] = {
    AuthorizationDisposition.PROPOSED: frozenset(
        {
            AuthorizationDisposition.ESTABLISHED,
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
        }
    ),
    AuthorizationDisposition.ESTABLISHED: frozenset(
        {AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED}
    ),
}


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The **eighth** copy of this helper rather than an import from a sibling, which
    is the tree's established position rather than a fresh choice: each SQLite
    store carries its own, and #506 and #563 already track consolidating the
    family. A private import from :mod:`ai_assistant.permissions.recipient_grants`
    would make one store's helper silently govern another's, and would leave the
    other six out of the arrangement anyway.

    The store serialises one ``sqlite3`` connection behind an
    :class:`asyncio.Lock` and runs the SQL in a worker thread. A thread cannot be
    interrupted, so if the awaiting coroutine were simply cancelled the enclosing
    ``async with self._lock`` would unwind and release the lock **while the worker
    was still using the connection** — letting a second caller use the same
    connection concurrently, which SQLite refuses. The worker records its own
    outcome and sets a :class:`threading.Event` when it physically returns; this
    coroutine waits on *that* signal, so the lock is held for the whole life of
    the worker even under a blanket task cancellation.

    Every failure the worker sees is relayed, ``BaseException`` included, and the
    completion wait is submitted **at most once** (#697).
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


#: One shape only, so far. There is no ``_migrate`` here and that is not an
#: omission: version 1 is the first shape this store has ever had, so an unlabelled
#: database is one this code is creating now, and it is stamped rather than
#: migrated.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``goal_authorizations`` table is created or
#: read — creating a table is a write, and the refusal precedes any write.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the sort keys count from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# **The blob is the record, and every column that decides anything is derived from
# it** (ADR-0252 I1's ``_EVIDENCE_INDEX_RULE``, taken in its strongest available
# form). ``id``, ``goal``, ``tool_id`` and ``disposition`` are ``GENERATED ALWAYS``
# from the JSON, which is ``SqliteRecipientGrantStore``'s shape one module over and
# is taken for its reason: a stored column that merely *agreed* with the blob when
# it was written is a second copy of a value, and a store whose uniqueness check
# reads the copy while its answer decodes the blob can be made to say that a second
# established row is the only one. Derived, they cannot disagree — so the rule's
# *"refused if its record disagrees with them"* limb has nothing left to refuse,
# and *"a row is never selected under a goal its columns do not name"* holds by
# construction.
#
# **``proposed_at_us`` is a plain column and orders nothing that authorises.** It
# exists because ``recent`` and ``export`` sort by proposal time and SQLite cannot
# sort an ISO-8601 instant correctly — ``"…:00.000001Z"`` sorts *before* ``"…:00Z"``
# by code point, so a generated column over ``json_extract`` would put a later row
# first. Liveness is therefore **not** decided in SQL at all: the interval is
# evaluated over the decoded record, against one clock reading, so both instants
# that decide it come from the blob.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS goal_authorizations("
    "proposed_at_us INTEGER NOT NULL, data TEXT NOT NULL, "
    "id TEXT GENERATED ALWAYS AS (json_extract(data, '$.id')) VIRTUAL, "
    "goal TEXT GENERATED ALWAYS AS (json_extract(data, '$.goal')) VIRTUAL, "
    "tool_id TEXT GENERATED ALWAYS AS (json_extract(data, '$.tool.id')) VIRTUAL, "
    "disposition TEXT GENERATED ALWAYS AS (json_extract(data, '$.disposition')) VIRTUAL)"
)

#: Keyed by name, because :data:`_OBJECTS` holds each one to its own definition and
#: a positional tuple would make that mapping a place to get wrong.
_INDEXES = {
    # The primary key `id` cannot be, because SQLite refuses a generated column in
    # one. Same constraint, same enforcement, and the derivation is kept.
    "goal_authorizations_id": (
        "CREATE UNIQUE INDEX IF NOT EXISTS goal_authorizations_id ON goal_authorizations(id)"
    ),
    # The pair `live_for`, `standing` and every uniqueness check select on. **Not
    # unique**: see the module docstring on why ADR-0254 §1's one-established-row
    # rule is stated once, inside the write, rather than twice.
    "goal_authorizations_pair": (
        "CREATE INDEX IF NOT EXISTS goal_authorizations_pair "
        "ON goal_authorizations(goal, tool_id, disposition)"
    ),
    "goal_authorizations_order": (
        "CREATE INDEX IF NOT EXISTS goal_authorizations_order "
        "ON goal_authorizations(proposed_at_us DESC, id ASC)"
    ),
}

#: **A settlement moves one field and its instant, and nothing else is ever
#: edited** — said to SQLite rather than only to the reader (ADR-0254 §1).
#:
#: This store is not append-only: ``settle`` is a genuine ``UPDATE``, which is what
#: makes the disposition itself the compare-and-swap token and why no version field
#: is on the record. What must still be impossible is an edit to the row's
#: *substance* — its coverage, its basis, its account, its destinations, its
#: expiry, its pointers, its origin — because those are what a ruling was taken
#: over and what
#: :attr:`~ai_assistant.core.types.Authorization.subject_digest` fingerprints. The
#: guard compares the two blobs with ``disposition`` and ``settled_at`` removed:
#: both sides are produced by one serializer in one field order, and ``json_remove``
#: renders both in SQLite's own canonical form, so the comparison is over the same
#: shape on each side.
#:
#: ``proposed_at_us`` is named separately because it is the only column the blob
#: does not generate, and a row whose ordering key was rewritten falls outside a
#: bounded listing's cut without ever being decoded — the caller is handed a wrong
#: page with every row on it valid.
#:
#: **What it is and is not.** It is this store's invariant enforced by the store,
#: the way a ``UNIQUE`` index enforces write-once; it is not a boundary against an
#: actor who can already run arbitrary SQL against the file, who could drop it as
#: easily as run the ``UPDATE``. ADR-0004 §4's owner-only mode is where that
#: question is answered, and ADR-0099 §1's single-user model is what scopes it.
_SETTLE_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS goal_authorizations_settle_only "
    "BEFORE UPDATE ON goal_authorizations "
    "WHEN OLD.proposed_at_us IS NOT NEW.proposed_at_us "
    "OR json_remove(OLD.data, '$.disposition', '$.settled_at') "
    "IS NOT json_remove(NEW.data, '$.disposition', '$.settled_at') "
    "BEGIN SELECT RAISE(ABORT, 'a settlement moves an authorization''s disposition and its "
    "instant; its coverage, basis, account, destinations and expiry are never edited'); END"
)

#: **Every object this store defines, held to its own definition.** ``CREATE TABLE
#: IF NOT EXISTS`` is a no-op against a table already there under that name
#: *whatever shape it has*, so a file arriving with a ``goal_authorizations`` table
#: of ordinary columns keeps it — and all four generated projections then read as
#: ``NULL``, because the insert writes only ``proposed_at_us`` and ``data``. Every
#: uniqueness check would then find nothing and every pair would admit a second
#: established row: the exact failure the generated columns exist to make
#: impossible, walked around rather than through. The indexes and the trigger are
#: held the same way and for the same reason — a pre-existing trigger that does
#: nothing lets a stored row's substance be rewritten under a recorded ``ALLOW``.
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds
#: is compared against these very statements rather than against a second copy of
#: them written out by hand.
_OBJECTS: Final = {
    "goal_authorizations": _CREATE_TABLE,
    **_INDEXES,
    "goal_authorizations_settle_only": _SETTLE_ONLY,
}

_ORDERED = "SELECT data FROM goal_authorizations ORDER BY proposed_at_us DESC, id ASC"

#: Every row of one goal and one declaration id, whatever its disposition — what
#: ``live_for`` reads, what the uniqueness checks count over, and what ``settle``
#: re-counts after its own supersession. **One statement**, because two spellings
#: of "the rows of this pair" are two answers free to drift apart.
_OF_PAIR = (
    "SELECT data FROM goal_authorizations WHERE goal = ? AND tool_id = ? "
    "ORDER BY proposed_at_us DESC, id ASC"
)

#: Every ``ESTABLISHED`` row of one goal — :meth:`SqliteGoalAuthorizationStore.
#: standing`'s whole query. **No instant appears in it**: liveness is the caller's
#: comparison (ADR-0254 §16).
_ESTABLISHED_OF_GOAL = (
    "SELECT data FROM goal_authorizations WHERE goal = ? AND disposition = ? "
    "ORDER BY proposed_at_us DESC, id ASC"
)

_BY_ID = "SELECT data FROM goal_authorizations WHERE id = ?"

#: Whether one id is already held, over the derived column so a hand-written ``id``
#: cannot hide a row from the duplicate check.
_ID_IS_HELD = "SELECT 1 FROM goal_authorizations WHERE id = ?"


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``. Ordering is part of ``recent``'s contract, and a float
    epoch second carrying microsecond precision needs sixteen significant digits at
    present-day values — right at the edge of a double, so two rows a microsecond
    apart could compare equal or invert. The subtraction below is exact.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _is_live(row: Authorization, reading: datetime) -> bool:
    """Whether ``row`` is live at ``reading`` (ADR-0254 §1).

    ``ESTABLISHED``, and the reading **at or after** ``settled_at`` and **strictly
    before** ``expires_at``. Both ends are read off the **record** rather than off
    a column, so no instant that decides coverage comes from a projection.

    **The lower end is stated because the clock can move backwards** — an operator
    correction, an NTP step — and a row this store called live whose ``settled_at``
    is after the ruling's ``decided_at`` is one ADR-0254 §7's trail then refuses as
    **backdated**, so the policy would report an authority the dispatch could not
    use and the step would die at the write rather than at the ruling. Equality is
    permitted at the lower end, which is §7's own discipline for the same
    comparison one component over.

    A ``PROPOSED`` row is **never** live, and neither is a retired one: the
    disposition test is first and there is no arm on which it is skipped.
    """
    if row.disposition is not AuthorizationDisposition.ESTABLISHED:
        return False
    settled_at = row.settled_at
    if settled_at is None:  # pragma: no cover — the model pairs the two
        return False
    return settled_at <= reading < row.expires_at


def _utc_now() -> datetime:
    """Read the wall clock as an aware UTC instant."""
    return datetime.now(UTC)


def _narrows(  # noqa: PLR0911 — one return per refusal, and each names a different widening
    later: ValueBound, earlier: ValueBound
) -> bool:
    """Whether ``later`` permits no value ``earlier`` does not (ADR-0254 §1, §9).

    The non-widening test, per kind, and it is a **subset** question rather than a
    difference: a correction may narrow a bound for an argument the superseded row
    already bounded, and *"the interpretation narrows what the act covers and can
    never widen it"*. Equality narrows vacuously and is admitted.

    **A change of ``kind`` is not a narrowing**, whatever the two bounds permit:
    the kinds are compared by different readings (§4) and a claim that one of them
    is inside another is a comparison this corpus does not establish. Likewise a
    change of ``currency``, of ``currency_argument`` or of a ``PERIOD``'s
    ``timezone``: each re-denominates what the bound is *about* rather than
    shrinking what it permits, so each takes path (i) and is confirmed.

    Args:
        later: The correcting row's bound for this argument.
        earlier: The superseded row's bound for the same argument.

    Returns:
        Whether every value ``later`` permits ``earlier`` permits too.
    """
    if later.kind is not earlier.kind:
        return False
    if later.kind is BoundKind.MONEY:
        # A ``None`` on either side is unreachable — the model requires a ``MONEY``
        # bound's ``currency``, ``currency_argument`` and ``maximum`` — and the
        # narrowing question is answered ``False`` for one all the same, which is the
        # fail-closed direction and costs a confirmation rather than an assertion.
        if (later.currency, later.currency_argument) != (
            earlier.currency,
            earlier.currency_argument,
        ):
            return False
        if later.maximum is None or earlier.maximum is None or later.maximum > earlier.maximum:
            return False
        # A lower bound the correction **drops** widens: every amount below the
        # earlier minimum becomes permitted. One it **adds** narrows, and one it
        # raises narrows; one it lowers widens.
        if earlier.minimum is None:
            return True
        return later.minimum is not None and later.minimum >= earlier.minimum
    if later.kind is BoundKind.PERIOD:
        if later.timezone != earlier.timezone:
            return False
        interval = (later.starts_at, later.ends_at, earlier.starts_at, earlier.ends_at)
        if any(instant is None for instant in interval):
            return False
        starts, ends, was_starts, was_ends = (
            instant for instant in interval if instant is not None
        )
        return starts >= was_starts and ends <= was_ends
    if later.terms is None or earlier.terms is None:
        return False
    return set(later.terms) <= set(earlier.terms)


def _member_defect(later: CoverageMember, earlier: CoverageMember | None) -> str | None:
    """Why ``later`` is not a permitted correction of ``earlier`` — or ``None``.

    ADR-0254 §1's *"what path (ii) may change, and what it may never touch"*, per
    argument, with §9 clause (ii)'s principle as the whole of the reason: **the
    interpretation narrows what the act covers and can never widen it**.

    * A member the superseded row does not name at all is an **addition**, refused.
    * A member **byte-identical** to the superseded row's is carried forward, and
      that is the ordinary case for every argument the correction does not touch —
      its own basis included, so the record says which act each value came from.
    * A member that **replaces a fixed value** for an argument the superseded row
      already fixed is admitted, whatever the new value: this is *"make it
      Sunday"*, and the act that states it is itself recorded.
    * A member that **narrows a bound** for an argument the superseded row already
      bounded is admitted; one that widens it, or that changes the bound's kind, is
      refused.
    * A member that turns a fixed value into a bound, or a bound into a fixed
      value, is **neither** of those two motions and is refused: it does not
      replace a value for an argument the row *fixed*, and it does not narrow a
      bound for one the row *bounded*.

    Args:
        later: The correcting row's member.
        earlier: The superseded row's member for the same argument, or ``None``
            where it names none.

    Returns:
        The refusal's reason, or ``None`` where the member is a permitted
        correction.
    """
    key = later.argument
    if earlier is None:
        return (
            f"a correction may not add a coverage member for {key!r}, which the row it "
            f"supersedes names in no member; an argument no earlier act covered is a "
            f"widening and takes path (i)"
        )
    if later == earlier:
        return None
    if (later.bound is None) is not (earlier.bound is None):
        return (
            f"a correction may replace a fixed value the superseded row fixed, or narrow a "
            f"bound it bounded; for {key!r} it does neither, turning one shape into the "
            f"other"
        )
    if later.bound is not None:
        assert earlier.bound is not None  # noqa: S101 — the shapes agree, checked above
        if not _narrows(later.bound, earlier.bound):
            return (
                f"a correction may only narrow a bound; for {key!r} it widens one, changes "
                f"its kind, or re-denominates it, each of which takes path (i) and is "
                f"confirmed"
            )
    return None


class SqliteGoalAuthorizationStore:
    """A :class:`~ai_assistant.core.protocols.GoalAuthorizationStore` on SQLite.

    One SQLite file under ``Settings.data_dir``, owner-only, holding every
    :class:`~ai_assistant.core.types.Authorization` in every disposition. See the
    module docstring for what it is, how it departs from the recipient-grant store
    and why its uniqueness rule is stated once.

    **One connection behind one :class:`asyncio.Lock`**, with every statement run
    in a worker thread that is held to physical completion (:func:`_run_to_completion`).

    **``close`` is not on the Protocol** and is this class's own, for the reason
    every SQLite store in this corpus has one: a test that opens a hundred stores
    should not depend on the garbage collector to release their handles.
    """

    def __init__(self, *, path: Path | str, now: Callable[[], datetime] = _utc_now) -> None:
        """Open (or create) the authorization store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                implementation exists — an authority the user's own act opened must
                still be on file after a restart, and ADR-0254 §1 rests the
                question-to-answer window on exactly that — so a default would let
                the ordinary construction produce a store that forgets every
                standing authority on restart. An ephemeral store is available and
                has to be asked for. It lives under ``Settings.data_dir`` in a real
                deployment, which is the composition root's choice rather than this
                class's.
            now: The clock :meth:`live_for` evaluates liveness against, wrapped by
                ``checked_clock`` (ADR-0026). Injected so a suite pins the interval
                boundary rather than racing it. **No caller supplies an instant**
                to it: a store that enforced liveness against a number the party
                being authorised chose would enforce nothing. It is the only member
                that reads it.
                **A clock this process cannot read propagates untranslated** —
                ``checked_clock``'s own ``ClockReadingError`` (ADR-0026 §3), which
                is a ``ValueError``. It is a **wiring bug** rather than a store
                fault, and translating it into an
                :class:`~ai_assistant.core.errors.AuthorizationError` would have the
                policy take ADR-0254 §6's bar for a reason that is not about the
                store at all — and log *"the authorization store could not be
                read"* about a store that answered perfectly well. That is
                ``SqliteRecipientGrantStore``'s posture one store over, stated here
                rather than inherited silently.

        Raises:
            AuthorizationError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqliteGoalAuthorizationStore")
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- setup ------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL raises
            # it out of the driver rather than a ``sqlite3.Error``, and a bad path is
            # this layer's fault to report rather than a raw builtin escaping past
            # the ``AuthorizationError`` boundary this constructor documents (#238).
            msg = f"failed to open the authorization store at {self._path!r}: {exc}"
            raise AuthorizationError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built: SQLite copies the database file's mode onto every rollback
            # journal it creates for it, so a journal opened while the file still
            # carried the process umask is world-readable too — and an interrupted
            # write leaves it on disk holding Tier 1 pages (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                # The table is held to its definition **before** the indexes and the
                # trigger are created over it, so a file arriving with a
                # ``goal_authorizations`` table of ordinary columns is reported as
                # what it is rather than as an index failing on a column it lacks.
                self._check_objects(conn, ("goal_authorizations",))
                for statement in _INDEXES.values():
                    conn.execute(statement)
                conn.execute(_SETTLE_ONLY)
                self._check_objects(conn, tuple(_OBJECTS))
                if not labelled:
                    # Stamped *after* the creates and inside the same transaction, so
                    # a failure rolls the marker — and the `meta` table itself — back
                    # rather than leaving a database falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except AuthorizationError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the authorization store at {self._path!r}: {exc}"
            raise AuthorizationError(msg) from exc
        return conn

    def _check_objects(self, conn: sqlite3.Connection, names: tuple[str, ...]) -> None:
        """Refuse a file whose ``names`` are not the objects this store defines.

        Run after the creates and **before** the marker is written, inside the same
        transaction, so a refusal leaves the file exactly as it arrived. Every
        object is compared to the statement that defines it (:data:`_OBJECTS` says
        why each one matters); an object this open created matches by construction,
        and one already there matches only if it is the same object.

        Args:
            conn: The connection the setup transaction is running on.
            names: Which of :data:`_OBJECTS` to check.

        Raises:
            AuthorizationError: If an object is missing or is not the one this store
                defines.
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
                    f"the authorization store at {self._path!r} holds an object named "
                    f"{name!r} that is not the one this store defines; its rows cannot be "
                    f"trusted to say what the user authorised, so it is not opened"
                )
                raise AuthorizationError(msg)

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault, so absence is
        tolerated one name at a time; nothing else is. A *symlink* under a sidecar's
        name is skipped rather than followed, because ``chmod`` follows links and
        restricting one would silently narrow a file this store has no business
        modifying. A no-op in memory.

        **Duplicated from the seven other SQLite stores on purpose** (#506).
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
        ``goal_authorizations`` table is created or read. An unlabelled database is
        **stamped rather than migrated**: version 1 is the only shape this store has
        ever written.

        Returns:
            Whether the database already carries a ``schema_version``.

        Raises:
            AuthorizationError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single
                unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code
            # created — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing
            # `meta` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers, and reading the first row would let an unsupported
            # version through on the strength of a sibling that agrees.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the authorization store at {self._path!r} holds {len(rows)} "
                f"schema_version rows ({', '.join(repr(value) for value in found)}); "
                f"the store is corrupt"
            )
            raise AuthorizationError(msg)
        raw = rows[0][0]
        msg = (
            f"the authorization store at {self._path!r} holds a non-numeric schema_version {raw!r}"
        )
        # The marker this code writes is always TEXT, but a hand-built `meta` may
        # declare no type. `int(float("inf"))` raises `OverflowError`, which is
        # neither `ValueError` nor an `AssistantError` and would leave this layer's
        # boundary through a hole. `bool` is an `int` in Python, so it is named
        # rather than left to read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise AuthorizationError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise AuthorizationError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the authorization store at {self._path!r} has schema_version={stored}, "
                f"but this code supports only version {_SCHEMA_VERSION}; refusing to open "
                f"it rather than read it blindly"
            )
            raise AuthorizationError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write,
        which is what puts every decision this store makes under it: ``record``'s
        free-id check, its uniqueness count and its two-row comparisons, and
        ``settle``'s compare-and-swap, its conditional supersession and its own
        re-count all decide whether the write may happen. A deferred begin would let
        a second process observe the same free id or the same absent established row
        between the decision and the write. The ``asyncio`` lock closes that within
        one process; this closes it against the file.

        Raises:
            AuthorizationError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=AuthorizationError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, authorization: Authorization) -> str:
        """Append ``authorization`` and return its id (ADR-0254 §1, §16).

        Write-once and atomic over the duplicate-id check, the path rules, the
        uniqueness refusal, the two-row checks and the append — and, on a path-(ii)
        correction, over the ``SUPERSEDED`` settlement of the row it names, which
        lands in the **same indivisible write**.

        Raises:
            InvalidAuthorizationError: On any ground
                :meth:`~ai_assistant.core.protocols.GoalAuthorizationStore.record`
                names. Pydantic's ``ValidationError`` is deliberately not allowed to
                escape: ``CONTRIBUTING`` has this layer raise only from the
                ``AssistantError`` hierarchy.
            AuthorizationError: If the database refuses the write.
        """
        snapshot = _revalidated(authorization)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: Authorization) -> None:
        """Validate against what is stored and insert, as one transaction."""
        with self._transaction(f"record authorization {snapshot.id!r}") as conn:
            if conn.execute(_ID_IS_HELD, (snapshot.id,)).fetchone():
                msg = (
                    f"authorization {snapshot.id!r} is already recorded; the store is "
                    f"write-once, so history cannot be rewritten by replaying a write"
                )
                raise InvalidAuthorizationError(msg)
            self._check_write_path(snapshot)
            superseded = self._check_supersedes(conn, snapshot)
            self._check_uniqueness(conn, snapshot, retiring=superseded)
            # Only the two stored columns: the other four are derived from the blob by
            # the table's own definition, so there is nothing to write and nothing that
            # could be written disagreeing with it.
            conn.execute(
                "INSERT INTO goal_authorizations(proposed_at_us, data) VALUES (?, ?)",
                (_sort_key(snapshot.proposed_at), snapshot.model_dump_json()),
            )
            if superseded is not None and snapshot.confirmation is None:
                # **Path (ii) alone.** A path-(i) proposal's ``supersedes`` states what
                # *approving* it would replace, and ADR-0254 §§1 and 5 put that
                # retirement in the same write as the ``ESTABLISHED`` settlement rather
                # than in the proposal: a proposal that retired its predecessor would
                # leave the user with neither authority while the question stood.
                self._write_settlement(
                    conn,
                    superseded,
                    to=AuthorizationDisposition.SUPERSEDED,
                    settled_at=snapshot.proposed_at,
                )

    @staticmethod
    def _check_write_path(row: Authorization) -> None:
        """Refuse a row written in a disposition its path does not admit (§1, §16).

        **A rule about the state a row may be first written in**, which ADR-0254 §1
        puts here rather than on the model: the same row is later persisted
        ``ESTABLISHED`` with that same ``confirmation``, so a validator stating it
        would refuse to decode the row it had just written — and ``resolve``,
        ``recent`` and ``export`` must return every row whatever its disposition.

        Raises:
            InvalidAuthorizationError: If a row carrying ``confirmation`` is written
                in any disposition but ``PROPOSED``, or one carrying it unset in any
                disposition but ``ESTABLISHED`` or with ``settled_at`` unequal to
                ``proposed_at``.
        """
        if row.confirmation is not None:
            if row.disposition is not AuthorizationDisposition.PROPOSED:
                msg = (
                    f"authorization {row.id!r} names a confirmation, so it is written "
                    f"PROPOSED and reaches every later disposition through settle alone; "
                    f"it was written {row.disposition} (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
            return
        if row.disposition is not AuthorizationDisposition.ESTABLISHED:
            msg = (
                f"authorization {row.id!r} names no confirmation, so it records an act "
                f"that needed no question and is written ESTABLISHED; it was written "
                f"{row.disposition} (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)
        if row.settled_at != row.proposed_at:
            msg = (
                f"authorization {row.id!r} records an act that needed no question, so it "
                f"was settled at the instant it was written; its settled_at is not its "
                f"proposed_at (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)

    def _check_supersedes(
        self, conn: sqlite3.Connection, row: Authorization
    ) -> Authorization | None:
        """Resolve ``row``'s ``supersedes``, and hold a correction to what it may change.

        Returns the named row where there is one, so the caller can retire it in the
        same write. **A rule comparing two rows is the store's**, at the write,
        where both are in hand (ADR-0254 §1).

        Raises:
            InvalidAuthorizationError: If ``supersedes`` resolves to no
                ``ESTABLISHED`` row of that goal and declaration id, or if a
                path-(ii) correction alters a transcribed field, adds or widens a
                coverage member, or moves ``expires_at`` other than by ADR-0256 §5's
                one narrowing.
        """
        named = row.supersedes
        if named is None:
            return None
        found = conn.execute(_BY_ID, (named,)).fetchone()
        earlier = _decode(found[0]) if found else None
        if (
            earlier is None
            or earlier.disposition is not AuthorizationDisposition.ESTABLISHED
            or earlier.goal != row.goal
            or earlier.tool.id != row.tool.id
        ):
            msg = (
                f"authorization {row.id!r} supersedes {named!r}, which is not an "
                f"ESTABLISHED row of goal {row.goal!r} through declaration "
                f"{row.tool.id!r}: it is absent, stands elsewhere, or belongs to another "
                f"pair (ADR-0254 §1, §16)"
            )
            raise InvalidAuthorizationError(msg)
        if row.confirmation is None:
            self._check_correction(row, earlier)
        return earlier

    @staticmethod
    def _check_correction(row: Authorization, earlier: Authorization) -> None:
        """Hold a path-(ii) correction to what ADR-0254 §1 lets it change.

        **A path-(i) proposal carrying ``supersedes`` is subject to none of this**
        (ADR-0256 §9): §1 lets it set ``expires_at``, ``account``, ``destinations``
        and ``tool``, §5 has it compute a fresh expiry, and it is confirmed — so it
        may carry a **later** instant than the row it names, which is what renews an
        authority whose expiry has passed. Applying this rule to one would break
        renewal.

        Raises:
            InvalidAuthorizationError: If a transcribed field moved, if the coverage
                added, dropped or widened a member, or if ``expires_at`` moved other
                than by ADR-0256 §5's one narrowing.
        """
        for name in ("goal", "tool", "account", "destinations", "origin"):
            if getattr(row, name) != getattr(earlier, name):
                msg = (
                    f"authorization {row.id!r} corrects {earlier.id!r} and alters its "
                    f"{name}; a correction transcribes goal, tool, account, destinations "
                    f"and origin unchanged, and a change to any of them takes path (i) "
                    f"and is confirmed (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
        # **ADR-0256 §5's one narrowing, and every other movement refused.** The
        # bound is the **superseded** row's own instant and never a chain's first, so
        # a second correction is measured against the row it actually replaces —
        # which is what keeps "no sequence of corrections outlives the confirmation
        # that began it" true a fortiori rather than by arithmetic over a chain.
        if row.expires_at != earlier.expires_at and not (
            row.proposed_at < row.expires_at < earlier.expires_at
        ):
            msg = (
                f"authorization {row.id!r} corrects {earlier.id!r} and moves its "
                f"expires_at; a correction may carry only an instant strictly after its "
                f"own proposed_at and strictly before the superseded row's, and nothing "
                f"lengthens a horizon on any path but (i) (ADR-0256 §5)"
            )
            raise InvalidAuthorizationError(msg)
        held = {member.argument: member for member in earlier.coverage}
        for member in row.coverage:
            defect = _member_defect(member, held.get(member.argument))
            if defect is not None:
                msg = (
                    f"authorization {row.id!r} corrects {earlier.id!r}: {defect} (ADR-0254 §1, §9)"
                )
                raise InvalidAuthorizationError(msg)
        dropped = sorted(held.keys() - {member.argument for member in row.coverage})
        if dropped:
            msg = (
                f"authorization {row.id!r} corrects {earlier.id!r} and drops its member "
                f"for {', '.join(repr(key) for key in dropped)}; every member the "
                f"correction does not replace is carried forward byte for byte, with its "
                f"own basis (ADR-0254 §1, §5)"
            )
            raise InvalidAuthorizationError(msg)

    def _check_uniqueness(
        self, conn: sqlite3.Connection, row: Authorization, *, retiring: Authorization | None
    ) -> None:
        """Refuse a write leaving two ``ESTABLISHED`` rows of one pair (ADR-0254 §1).

        Taken over what would remain **after** this write's own supersession, and
        stated over the **disposition** rather than over liveness, so the write path
        reads no clock — ADR-0193 §1's duplicate-refusal discipline.

        A path-(i) proposal is written ``PROPOSED`` and adds no established row, so
        it is never refused here; where two proposals of one pair are each recorded,
        it is the **second settlement** that answers ``WOULD_DUPLICATE``, which is
        what that member exists for.

        Args:
            conn: The open transaction.
            row: The row about to be written.
            retiring: The row this write will settle ``SUPERSEDED`` in the same
                step, or ``None``.

        Raises:
            InvalidAuthorizationError: If an ``ESTABLISHED`` row of that goal and
                declaration id would survive beside this one.
        """
        if row.disposition is not AuthorizationDisposition.ESTABLISHED:
            return
        surviving = self._established_ids(conn, row) - {
            retiring.id for retiring in (retiring,) if retiring is not None
        }
        if surviving:
            msg = (
                f"authorization {row.id!r} would be the second ESTABLISHED row of goal "
                f"{row.goal!r} through declaration {row.tool.id!r}, beside "
                f"{', '.join(repr(held) for held in sorted(surviving))}; at most one "
                f"stands per pair (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)

    @staticmethod
    def _established_ids(conn: sqlite3.Connection, row: Authorization) -> set[str]:
        """The ids of every ``ESTABLISHED`` row of ``row``'s goal and declaration id.

        Over the **derived** columns, so a hand-written projection cannot hide a row
        from the count, and decoded from the blob so the id compared is the record's.
        """
        held = (
            _decode(str(stored[0]))
            for stored in conn.execute(_OF_PAIR, (row.goal, row.tool.id)).fetchall()
        )
        return {one.id for one in held if one.disposition is AuthorizationDisposition.ESTABLISHED}

    async def settle(
        self,
        authorization_id: str,
        /,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime,
    ) -> AuthorizationSettlement:
        """Move one row along one of ADR-0254 §1's five edges, or say why not.

        **The read, the comparisons and the writes are one indivisible step** — one
        ``BEGIN IMMEDIATE`` transaction — so no caller reads a row, decides, and
        writes back, and two racing settlements of one row cannot both win: the
        second finds a disposition the edge does not leave and is answered
        ``NOT_AT_SOURCE``.

        **It reads no clock**: ``settled_at`` is the caller's, as ``record``'s
        instants are (ADR-0021 §3).

        Raises:
            AuthorizationError: If the store cannot be read or written. **A refusal
                is not this**: the four outcomes are total over what the step can
                answer, and a refusal that raised would make one an exception.
        """
        async with self._lock:
            return await _run_to_completion(self._settle_sync, authorization_id, to, settled_at)

    def _settle_sync(
        self, authorization_id: str, to: AuthorizationDisposition, settled_at: datetime
    ) -> AuthorizationSettlement:
        """Compare and swap on the disposition, with §1's supersession inside the step."""
        with self._transaction(f"settle authorization {authorization_id!r}") as conn:
            found = conn.execute(_BY_ID, (authorization_id,)).fetchone()
            if found is None:
                return AuthorizationSettlement.NO_SUCH_AUTHORIZATION
            stored = _decode(str(found[0]))
            # The expiry settlement is taken **first** by any operation that reads a
            # lapsed proposal (ADR-0254 §1), and is skipped only where the caller
            # asked for exactly that move: there the two coincide, the ordinary edge
            # takes it, and the step answers ``SETTLED`` about the settlement it
            # actually performed.
            held = (
                stored
                if to is AuthorizationDisposition.EXPIRED
                else self._expired_first(conn, stored, settled_at)
            )
            if to not in _EDGES.get(held.disposition, frozenset()):
                # **One member and not four** (ADR-0254 §16): a PROPOSED row asked for
                # an edge that leaves ESTABLISHED, a retired row asked for anything, a
                # move that is not an edge at all, and the loser of two racing
                # settlements are one fact — the row's own disposition is the
                # compare-and-swap's token, and "it was not there" is the whole of what
                # this store can honestly say.
                return AuthorizationSettlement.NOT_AT_SOURCE
            if to is not AuthorizationDisposition.ESTABLISHED:
                self._write_settlement(conn, held, to=to, settled_at=settled_at)
                return AuthorizationSettlement.SETTLED
            return self._establish(conn, held, settled_at=settled_at)

    def _expired_first(
        self, conn: sqlite3.Connection, held: Authorization, settled_at: datetime
    ) -> Authorization:
        """Settle a lapsed proposal ``EXPIRED`` before the requested edge is evaluated.

        **``settle`` is the second of ADR-0254 §1's exactly two settling
        operations** — *"a ``live_for`` read, and **the answer that names it**"* —
        and this is that clause. *"An answer arriving at or after ``expires_at``
        settles ``EXPIRED`` and **establishes nothing**"*, because *"an expired
        proposal is refused as an establishment at all"*.

        **The expiry settlement is taken first, and the caller's requested move is
        then evaluated from where the row stands.** So an approval that arrives late
        lands the row ``EXPIRED`` and is answered
        :attr:`~ai_assistant.core.types.AuthorizationSettlement.NOT_AT_SOURCE` — the
        row genuinely does not stand at ``PROPOSED`` by the time that edge is
        considered, which is the honest member and the safe one. Answering
        ``SETTLED`` would tell the caller an authority came into being that §12 says
        did not; and the ordering is not an invention, it is *"the first operation
        that reads it"* read literally.

        **A late answer of any kind takes it**, not an approval alone: arm 37 states
        the rule over *"the answer that names it"*, and a refusal arriving after the
        deadline is as much an answer to a question that has lapsed as an approval
        is. Where the caller asked for ``EXPIRED`` the two coincide and the step
        answers ``SETTLED``.

        **It reads no clock**: ``settled_at`` is the caller's instant and
        ``expires_at`` is the row's, so this is a comparison of two recorded values
        exactly as every other rule on this write path is (ADR-0021 §3).

        Args:
            conn: The open transaction.
            held: The row as the store holds it.
            settled_at: The instant the caller took the settlement at.

        Returns:
            The row as it stands once any owed expiry settlement has been taken.
        """
        if held.disposition is not AuthorizationDisposition.PROPOSED:
            return held
        if held.expires_at > settled_at:
            return held
        self._write_settlement(
            conn, held, to=AuthorizationDisposition.EXPIRED, settled_at=settled_at
        )
        return held.model_copy(
            update={
                "disposition": AuthorizationDisposition.EXPIRED,
                "settled_at": settled_at,
            }
        )

    def _establish(
        self, conn: sqlite3.Connection, held: Authorization, *, settled_at: datetime
    ) -> AuthorizationSettlement:
        """Take §1's conditional supersession and its uniqueness check in one step.

        **The supersession is conditional on the named row still standing
        ``ESTABLISHED``, read at the instant of the settlement rather than at the
        proposal** (ADR-0254 §1). Between the proposal and the answer the named row
        may leave ``ESTABLISHED`` by an act of the user's own — a revocation — or by
        a third row's supersession, and there are exactly two arms:

        * **it still stands** — it is settled ``SUPERSEDED`` in the same write as
          this row's ``ESTABLISHED`` settlement, which is §5's *"in one write"*;
        * **it has already left** — this row is settled ``ESTABLISHED`` all the
          same and **the named row is written to at all**, staying in whatever
          retired disposition it reached. The approval is the user's later and more
          explicit act, taken with §11's full projection in front of them; the
          uniqueness the supersession protects is already satisfied; and refusing
          instead would let an earlier revocation silently void the answer to a
          question still standing, leaving the user with neither authority after
          they approved one.

        The uniqueness check is then taken over **what would remain after that
        supersession**, which is why a *third* row of the pair standing
        ``ESTABLISHED`` answers ``WOULD_DUPLICATE`` and nothing is written: it is a
        row this write's ``supersedes`` does not name.
        """
        named = held.supersedes
        retiring: Authorization | None = None
        if named is not None:
            found = conn.execute(_BY_ID, (named,)).fetchone()
            candidate = _decode(str(found[0])) if found else None
            if (
                candidate is not None
                and candidate.disposition is AuthorizationDisposition.ESTABLISHED
            ):
                retiring = candidate
        surviving = self._established_ids(conn, held) - {
            retired.id for retired in (retiring,) if retired is not None
        }
        if surviving:
            return AuthorizationSettlement.WOULD_DUPLICATE
        self._write_settlement(
            conn, held, to=AuthorizationDisposition.ESTABLISHED, settled_at=settled_at
        )
        if retiring is not None:
            self._write_settlement(
                conn, retiring, to=AuthorizationDisposition.SUPERSEDED, settled_at=settled_at
            )
        return AuthorizationSettlement.SETTLED

    @staticmethod
    def _write_settlement(
        conn: sqlite3.Connection,
        row: Authorization,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime,
    ) -> None:
        """Rewrite one row's disposition and its instant, and nothing else.

        **Through the record's own model** rather than by editing the JSON in SQL,
        which is what makes ADR-0254 §1's pairing rule a thing the type guarantees:
        a settled row carrying no ``settled_at`` is refused at construction here, as
        it would be on the way back out. :data:`_SETTLE_ONLY` is the second
        statement of the same rule, to the database, for the rows this code did not
        write.
        """
        settled = Authorization.model_validate(
            {**row.model_dump(), "disposition": to, "settled_at": settled_at}
        )
        conn.execute(
            "UPDATE goal_authorizations SET data = ? WHERE id = ?",
            (settled.model_dump_json(), row.id),
        )

    # --- the read path ----------------------------------------------------

    async def live_for(self, goal: str, tool_id: str) -> Authorization | None:
        """The live authorization of ``goal`` through ``tool_id``, or ``None``.

        ADR-0254 §3's conditions 1 and 2 and the **id half** of condition 3; the
        policy takes the declaration-by-value comparison and conditions 4, 5 and 6
        over the row returned. **The split is what lets a policy tell *no record*
        from *a record that did not cover***, which §6's bar is stated over.

        **The clock is read exactly once**, before the lock, and every row this call
        considers is measured against that one instant — a query reading an
        advancing clock per row could answer over a set true at no real instant
        (ADR-0193 §9's rule, adopted). Liveness is decided over the **decoded**
        record, so both instants come from the blob rather than from a column.

        **It settles an expired proposal it reads** (§1, ADR-0244 §10's mechanism),
        and the settlement is taken **after** the integrity check below, so a store
        holding two live rows of one pair is left exactly as it was found.

        Raises:
            AuthorizationError: If the store cannot be read or written, **or if more
                than one live row of that pair would answer** — refused at the read
                as well as at the write because a query that chose between two would
                be the composition ADR-0254 §5 declines, and **raised rather than
                answered ``None``** because ``None`` is this seam's word for *"the
                store holds no live record"*.
        """
        reading = self._clock()
        async with self._lock:
            return await _run_to_completion(self._live_for_sync, goal, tool_id, reading)

    def _live_for_sync(self, goal: str, tool_id: str, reading: datetime) -> Authorization | None:
        """Read the pair's rows, refuse two live ones, settle the lapsed proposals."""
        with self._transaction(f"read the live authorization of goal {goal!r}") as conn:
            rows = [
                _decode(str(stored[0]))
                for stored in conn.execute(_OF_PAIR, (goal, tool_id)).fetchall()
            ]
            live = [row for row in rows if _is_live(row, reading)]
            if len(live) > 1:
                msg = (
                    f"the authorization store holds {len(live)} live rows for goal {goal!r} "
                    f"through declaration {tool_id!r} ({', '.join(repr(row.id) for row in live)}); "
                    f"at most one stands per pair, and a query that chose between two would "
                    f"compose coverage across records (ADR-0254 §1, §5)"
                )
                raise AuthorizationError(msg)
            for row in rows:
                if (
                    row.disposition is AuthorizationDisposition.PROPOSED
                    and row.expires_at <= reading
                ):
                    self._write_settlement(
                        conn, row, to=AuthorizationDisposition.EXPIRED, settled_at=reading
                    )
            return live[0] if live else None

    async def resolve(self, authorization_id: str) -> Authorization | None:
        """The row with ``authorization_id``, whatever its disposition, or ``None``.

        **It reads no clock and settles nothing**: the trail's own check reads the
        disposition and decides both ends of liveness against the decision's own
        ``decided_at`` (ADR-0254 §7, §16).

        Raises:
            AuthorizationError: If the store cannot be read, or holds a row that no
                longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._read_sync, _BY_ID, (authorization_id,))
        return _decode(rows[0]) if rows else None

    async def standing(self, goal: str) -> tuple[Authorization, ...]:
        """Every ``ESTABLISHED`` row of ``goal``, live **and** lapsed (ADR-0254 §16).

        **It evaluates no liveness, reports none and reads no clock**: each row
        carries its own ``expires_at``, and whether it has passed is the caller's
        comparison against one reading of the injected clock (ADR-0026). The engine
        takes that reading when it assembles the listing and hands the surface the
        answer as data, which is ADR-0042 §6's division.

        **Complete or nothing**, and nothing is truncated, sampled or elided: a page
        of what the user authorises reads as complete while omitting an
        authorisation. The order is :meth:`recent`'s — newest first by
        ``proposed_at``, ties broken by ``id`` ascending — so a listing is stable
        across calls rather than at the database's discretion.

        Raises:
            AuthorizationError: If the store cannot be read, or holds a row that no
                longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(
                self._read_sync,
                _ESTABLISHED_OF_GOAL,
                (goal, AuthorizationDisposition.ESTABLISHED.value),
            )
        return tuple(_decode(row) for row in rows)

    async def recent(self, *, limit: int = 50) -> tuple[Authorization, ...]:
        """Up to ``limit`` rows, newest first by ``proposed_at``, ties broken by id.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021
        §4). Rows of **every** disposition are returned, a declined and a superseded
        one included, and no liveness is evaluated, so no clock is read.

        Raises:
            ValueError: If ``limit`` is not a strictly positive **exact** ``int``,
                refused **locally and before any I/O** exactly as
                :meth:`~ai_assistant.permissions.recipient_grants.SqliteRecipientGrantStore.recent`
                refuses it, and for that member's reasons: SQLite reads ``LIMIT -1``
                as *no limit at all*, so the one call offering a bounded read of a
                Tier 1 store would become the unbounded read it exists to avoid; and
                the type is checked as an allowlist of the exact ``int`` because
                ``True`` is an ``int``, passes ``<= 0``, and is silently taken as a
                bound of one.
            AuthorizationError: If the store cannot be read, or holds a row that no
                longer validates.
        """
        if type(limit) is not int or limit <= 0:
            msg = (
                f"limit must be a strictly positive int, got "
                f"{describe_untrusted(limit)}; the type is checked because a bool "
                f"passes the comparison while meaning a bound of one"
            )
            raise ValueError(msg)
        # Clamped *upward* only. A Python int has no width, and binding one wider
        # than SQLite's signed 64-bit parameter raises `OverflowError` — neither
        # `ValueError` nor `AuthorizationError`, so it would leave this layer's error
        # boundary through a hole. A bound above any possible row count means "all of
        # them", which is what the query then returns.
        async with self._lock:
            rows = await _run_to_completion(
                self._read_sync, f"{_ORDERED} LIMIT ?", (min(limit, _MAX_SQLITE_INT),)
            )
        return tuple(_decode(row) for row in rows)

    async def export(self) -> tuple[Authorization, ...]:
        """**Every** row, in the same order as :meth:`recent` (ADR-0004 §6).

        Proposed, established, declined, expired, revoked and superseded, **with
        each member's basis whole** — act, span and resolution. What this store is
        *for* is saying, completely and in order, what the user authorised, what
        they declined and what lapsed, and a portable snapshot that omits rows is
        not one.

        Raises:
            AuthorizationError: If the store cannot be read, or holds a row that no
                longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._read_sync, _ORDERED, ())
        return tuple(_decode(row) for row in rows)

    def _read_sync(self, statement: str, parameters: tuple[object, ...]) -> Sequence[str]:
        """Run one ``SELECT data`` statement, translating a backend failure.

        One helper rather than a ``try`` per read, so no read acquires its own error
        boundary and every one of them fails the same way — which is what a
        consumer's fail-closed branch is written against.

        Raises:
            AuthorizationError: If the backend fails.
        """
        try:
            rows = self._conn.execute(statement, parameters).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the authorization store: {exc}"
            raise AuthorizationError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every row, returning the number removed (ADR-0004 §6, ADR-0254 §16).

        Wholesale by design: the user may burn the book, and nobody may tear out a
        page. There is no ``delete(id)``, and its reason here is the recipient
        store's — an ``authorised_by`` in the trail points into this store, so
        deleting the row it points at would make a recorded ``ALLOW`` unexplainable
        while leaving it looking complete.

        **It retracts, invalidates and re-opens nothing**: a recorded ``ALLOW``
        stays recorded and stays true about the moment it was made. What is lost is
        the row's **own** text — its coverage, its basis, its expiry — because the
        decision carries a pointer and a digest and never the record by value.

        Raises:
            AuthorizationError: If the store cannot be cleared.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        """Delete everything in one statement, counting what the delete removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it: a separate count is read before SQLite opens the
        write transaction, so a second store on the same file could append between
        the two and be erased without being counted — and each instance has its own
        ``asyncio.Lock``, which arbitrates nothing across them.

        Only ``goal_authorizations`` is emptied: the ``meta`` schema marker
        describes the file's shape rather than the user's history, so burning the
        book leaves a database this code can still open. Nothing else is retained —
        no id, no tombstone, no derived value — so an id held before this may be
        recorded again afterwards.
        """
        with self._transaction("clear the authorization store") as conn:
            removed = conn.execute("DELETE FROM goal_authorizations").rowcount
        return int(removed)

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _revalidated(row: Authorization) -> Authorization:
    """Rebuild ``row`` as a validated :class:`Authorization`.

    ADR-0097 §3 asks for a *validated* snapshot, not merely a detached one. A copy
    alone detaches without checking, so a record corrupted past its frozen model's
    guard would be stored and make every later read incoherent — a naive
    ``proposed_at`` makes ``recent`` raise on comparing it against the aware values
    beside it, and a destination tuple written back out of canonical order would
    make the uniqueness comparison, the trail's subject match and
    :attr:`~ai_assistant.core.types.Authorization.subject_digest` three comparisons
    over a spelling the record's own validator refuses.

    Rebuilt as an ``Authorization`` specifically, not as ``type(row)``: a caller's
    subclass could carry extra fields, and they are refused here rather than
    allowed to vanish at serialisation and make the stored record differ from the
    one that reloads.

    **And rebuilt from the instance's field state rather than from
    ``model_dump()``**, which is
    :func:`~ai_assistant.permissions.recipient_grants._revalidated`'s discipline
    and matters at least as much here. ``model_dump`` is an ordinary overridable
    method, so a subclass can return a mapping that does not describe itself — a
    row bounding sixty pounds whose dump names eight hundred — and the store would
    then hold **an authority the user never gave**. ``field_state`` is that read —
    the class's own serializer, resolved on the class, consulting no instance
    attribute — and it is shared with the trail rather than spelled a second way.

    **And detached *recursively*, which is what ``field_state`` buys over a copy of
    ``__dict__``.** A mapping of the instance's own field values still holds the
    caller's ``tool``, ``coverage`` members and ``CanonicalDestination`` objects:
    pydantic's default ``revalidate_instances="never"`` keeps whatever instance was
    passed, so the snapshot and the caller share every model beneath the root.
    ``frozen=True`` refuses ``member.bound = …`` and does not refuse
    ``member.__dict__["bound"] = …``, so a caller could raise a ``maximum``
    **after** ``record`` accepted the row and before the write inside the lock
    serialises it.

    **Nothing of the caller's is read outside the guard**, the diagnostic id
    included (:func:`_named`).

    Raises:
        InvalidAuthorizationError: If the record does not satisfy its own model,
            carries state :class:`Authorization` declares no field for, or holds
            beneath it a model of any type other than exactly the declared one. The
            **subclass** rather than the ``AuthorizationError`` base: here the base
            is the *store fault* and only the subclass says "your record was
            refused", which is the distinction a consumer's fail-closed branch keeps
            alive.
    """
    try:
        return Authorization.model_validate(field_state(Authorization, row))
    except ValueError as exc:
        # `describe_untrusted` on the cause as well as on the id: `field_state`
        # re-raises a `ValueError` the caller's own code raised, and a hostile
        # `__str__` on it would replace this refusal with whatever it threw — from
        # inside the `except` block that exists to report it.
        msg = f"authorization {_named(row)} is not a valid record: {describe_untrusted(exc)}"
        raise InvalidAuthorizationError(msg) from exc


def _named(given: object) -> str:
    """Name ``given`` for a refusal message, without reading an attribute of it.

    ``given.id`` is not available: the value reaching :func:`_revalidated` is
    whatever the caller passed, and a record whose ``__dict__`` is missing a field —
    or a value that is not a record at all — has no ``id`` attribute, so composing
    the message from one would replace the refusal this layer owes with a builtin
    escaping its error boundary. ``isinstance`` is inside the guard with everything
    else, because asking what something is consults ``__class__``, which can be a
    property that raises.

    Nothing here hashes a key the caller controls: a model's ``__dict__`` is
    annotated ``dict[str, Any]`` and nothing enforces it at runtime, so a key can be
    an object whose ``__hash__`` collides with a field name and whose ``__eq__``
    raises on the comparison that collision provokes. Iterating hashes nothing, and
    only a real ``str`` — whose hash and equality are the interpreter's — is asked
    whether it names the id.
    """
    try:
        if isinstance(given, Authorization):
            for key, value in object.__getattribute__(given, "__dict__").items():
                if type(key) is str and key == "id":
                    return describe_untrusted(value)
    except Exception:  # the value cannot even be named; say so and carry on
        return "the given value"
    return "the given value"


def _decode(data: str) -> Authorization:
    """Rebuild a stored row from its JSON.

    Raises:
        AuthorizationError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to
            hand on. The **base** class here, not ``InvalidAuthorizationError``:
            nothing the caller handed in was refused, the store itself is unreadable,
            and a consumer's fail-closed branch is exactly the right response.
    """
    try:
        return Authorization.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the authorization store holds a record that no longer validates: {exc}"
        raise AuthorizationError(msg) from exc


__all__ = ["SqliteGoalAuthorizationStore"]
