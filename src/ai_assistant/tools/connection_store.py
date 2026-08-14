"""The hub's append-only connection store, on SQLite (ADR-0149 §3).

The seventh durable Tier 1 store under ``Settings.data_dir``, and the one
ADR-0148 §6's provisioning act is stated over. It holds what the user connected,
re-provisioned and disconnected, for which reference, in order — the identity,
the revision, the provisioning state and the credential slot §6 requires, and no
credential value or value derived from one in any field, the identity included.

**Its seam is `tools/`-internal and stays that way** (ADR-0149 §3). This module
declares no Protocol and none is declared for it in ``core``: every party
ADR-0148 §6 lets consult a record is inside `tools/`, and a ``core`` seam between
two modules of one subsystem is surface with no boundary to hold.

**Append-only, in ADR-0097 §4's shape and for that section's reason.** Every act
appends; no entry is updated in place and none is deleted except by the wholesale
purge ADR-0149 §8 governs. That buys three things at once: it is what ADR-0149 §7
offers as ADR-0004 §7's *recorded* half; it makes ADR-0149 §5's revision
monotonicity a property of the store rather than an extra obligation on an
implementation — which is what closes the ABA sequence a store that dropped
history with the record would reopen; and it keeps superseded slots visible to
the purge, which is what stops a failed predecessor deletion from becoming an
entry nothing can name.

**Two entries per provisioning act, and that granularity is not exposed.**
ADR-0148 §6's act writes the record *pending* and then, after the credential,
*active*; both are appends here, at one revision, and
:meth:`SqliteConnectionStore.recent` collapses them into the one
:class:`~ai_assistant.core.types.ConnectionAct` per ``(reference, revision)``
ADR-0151 §9 requires, carrying the furthest state that act reached. A
disconnection appends a third kind of entry — a **removal** — which carries no
identity, no state and no slot, and is not a third
:class:`~ai_assistant.core.types.ProvisioningState` (ADR-0149 §5).

**The compare-and-swap is the store's, and it is one primitive.**
:meth:`SqliteConnectionStore.append` takes the sequence number of the entry the
caller observed and appends only if that entry is still the reference's latest —
which is ADR-0148 §6's compare-and-swap in ADR-0149 §3's own terms, and which
serves all three of the act's decision points with one method: the taking swap,
the activation's own swap, and the mint's refusal of a reference the store
already holds (``expected_latest=None`` means *this reference has no entries at
all*).

**One resident process does not relieve it.** ADR-0083 §1 puts one hub per data
directory, so two provisioning acts race inside one process today rather than
across two — but ADR-0148 §6 states the swap over the record regardless, and the
property it needs is that a displacing act's activation is *observable* to the
act it displaced. An in-process convention would stop being true the first time
anything outside the hub wrote this file, so the swap runs inside
``BEGIN IMMEDIATE`` and holds against the file.

Local-first (ADR-0002) and locally only. The database file is created owner-only
(ADR-0004 §4, ADR-0084 §9), following the precedent
:mod:`ai_assistant.memory.sqlite_store` set.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    CONNECTION_REFERENCE_MAX_BYTES,
    ConnectedAccount,
    ConnectionAct,
    DurableIdentifier,
    NonBlankEncodableText,
    ProvisioningState,
    SecretName,
    encodable_text,
)
from ai_assistant.tools._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from contextlib import AbstractContextManager

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too — and the inheritance
#: SQLite gives a sidecar *it creates* does not reach one that is already there
#: (#490).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The widest value SQLite will bind to an INTEGER parameter. A Python ``int`` is
#: unbounded, so :meth:`SqliteConnectionStore.recent` clamps to this before
#: binding ``LIMIT``.
_MAX_SQLITE_INT = 2**63 - 1

#: The only on-disk schema this code understands, recorded in ``meta`` so a
#: future schema change has a marker to migrate *from* (ADR-0049 §1). Version 1
#: is the first shape this store has ever had, so an unlabelled database is one
#: this code is creating now: it is stamped rather than migrated, and there is no
#: ``_migrate`` here.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``entries`` table is created or read.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

# The columns beside the ``data`` blob exist only so SQLite can order, group and
# narrow; **the blob is the entry, and every semantic answer is read off it**.
# ``sequence`` is the append order and the compare-and-swap's token —
# ``INTEGER PRIMARY KEY`` is the rowid, which SQLite assigns monotonically for an
# insert that does not supply one.
#
# **There is deliberately no ``state`` column and no ``slot`` column**, and their
# absence is the rule ``permissions/grants.py`` already states for the same
# hazard: "two spellings of 'is this source granted' are two answers free to drift
# apart, and the one that drifted would still pass its own half of the suite". An
# earlier draft here projected both and made ``state IS NOT NULL`` the liveness
# predicate — so an ``UPDATE entries SET state = NULL`` on a file left a JSON
# payload that was still a valid *active* record while ``live`` reported the
# reference as gone, which is a change of meaning rather than a corruption this
# store reports. Liveness and slot membership are now decided by
# :meth:`ConnectionEntry.account` and :attr:`ConnectionEntry.slot` over the
# decoded entry, which is the one representation every read answers from.
#
# ``reference`` and ``revision`` stay, because they choose *which rows* rather
# than what a row means, and :func:`_decoded` checks each returned row's pair
# against the entry it decodes — so the projection cannot disagree with the blob
# without the read failing. What that check cannot see is a row the query never
# returned, which is why the two filters ADR-0149 §5 and §8 state over revisions
# run over decoded entries rather than in SQL.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS entries("
    "sequence INTEGER PRIMARY KEY, reference TEXT NOT NULL, revision INTEGER NOT NULL, "
    "data TEXT NOT NULL)"
)

_INDEXES = (
    # Every read but `recent` and the purge narrows on `reference` first, and the
    # descending sequence is what makes "this reference's latest entry" — the
    # value the compare-and-swap is stated over — a single index seek.
    "CREATE INDEX IF NOT EXISTS entries_reference ON entries(reference, sequence DESC)",
)

#: The sequence of each reference's latest entry. The projection ADR-0149 §3's
#: third clause defines: "the **live connection record** for a reference … is
#: that reference's latest entry".
_LATEST_PER_REFERENCE = "SELECT MAX(sequence) FROM entries GROUP BY reference"

#: The latest entry per reference. Which of them are *live* is decided over the
#: decoded entries — "a reference whose latest entry is a removal (§5) has no live
#: record at all" (ADR-0149 §3) — rather than by a predicate over a projected
#: column, for the reason the schema comment gives.
_LIVE = (
    "SELECT reference, revision, data FROM entries "  # noqa: S608
    f"WHERE sequence IN ({_LATEST_PER_REFERENCE}) ORDER BY sequence ASC"
)

#: The furthest entry of each act — each ``(reference, revision)`` pair — newest
#: first. ADR-0151 §9's row granularity, computed here rather than by the caller:
#: "no implementation returns two rows for one act, and no client reads the
#: store's internal shape off this result".
#:
#: **Ordered by the act's furthest entry rather than by its first**, so the
#: sequence a client walks is the order the store last recorded something about
#: each act. Either endpoint is an append order; this one is the one under which
#: a completed activation reads as more recent than the pending entry of an act
#: that has not finished.
#: The grouping is the one place a projected column decides which rows come back
#: and the check cannot see the rows it excluded: a corrupted ``revision`` would
#: split or merge two acts here. It is kept in SQL because the alternative is to
#: over-fetch and slice, which is the paging surface ADR-0102 §10 calls one that
#: lies about its cost — and the exposure is bounded, because this listing states
#: nothing about liveness (ADR-0151 §9) and every row it does return is checked.
_ACTS = (
    "SELECT reference, revision, data FROM entries WHERE sequence IN "
    "(SELECT MAX(sequence) FROM entries GROUP BY reference, revision) "
    "ORDER BY sequence DESC"
)


#: The Unicode general categories ADR-0149 §4's "no control character, no line
#: break" excludes: ``Cc`` is every C0 and C1 control, which is where ``\n``,
#: ``\r``, ``\v``, ``\f``, the file/group/record separators and ``\x85`` all
#: live, and ``Zl``/``Zp`` are the two separators that are line breaks without
#: being controls (``\u2028`` and ``\u2029``).
#:
#: Stated as categories rather than as a character set because the set is the one
#: that grows: a rule written as ``"\n" not in value`` passes ``\u2028``, which
#: ``str.splitlines`` treats as a line break and a terminal renders as one.
_UNPRINTABLE_CATEGORIES: Final = frozenset({"Cc", "Zl", "Zp"})


def printable_identity(identity: str) -> str:
    """Enforce ADR-0149 §4's identity shape at the store, returning it unchanged.

    §4 rules an identity "**bounded, single-line printable text**: no control
    character, no line break, and a length bound the implementing lane sets **and
    the store enforces**", and "a violation refuses the act and writes nothing".
    ADR-0151 §5 moved the bound's *location* into ``core`` so the wire client and
    the in-process engine refuse the same values without a round trip; ADR-0151
    §17 records that this did not move the enforcement — "a lane holding only
    ADR-0149 §4 sets a bound and enforces it in the store, which stays exactly what
    they must do".

    So this is the second of two refusals rather than a duplicate of one. The
    engine's is the one a person sees, raised locally with nothing sent (ADR-0151
    §5); this one is what makes §4 true of the store however the record got here —
    including from a caller inside `tools/` that never crossed the engine surface.

    **It normalises nothing.** ADR-0149 §4 forbids stripping, case-folding and
    Unicode-normalising an identity at any layer, so a violation is refused and
    never repaired.

    **The message names no part of the identity and no length of it.** The
    identity is Tier 1 personal data (ADR-0149 §3) and reaches no log line, error
    message or operator diagnostic; the bound is a constant and may be named.

    Args:
        identity: The account identity an entry carries.

    Returns:
        The identity, unchanged and unnormalised.

    Raises:
        ConnectionStoreError: If it carries a control character or a line break,
            or if its UTF-8 encoding exceeds
            :data:`~ai_assistant.core.types.ACCOUNT_IDENTITY_MAX_BYTES`.
    """
    if any(unicodedata.category(char) in _UNPRINTABLE_CATEGORIES for char in identity):
        msg = (
            "an account identity is single-line printable text: no control character and "
            "no line break (ADR-0149 §4). Nothing was written"
        )
        raise ConnectionStoreError(msg)
    if len(identity.encode("utf-8")) > ACCOUNT_IDENTITY_MAX_BYTES:
        msg = (
            f"an account identity encodes to at most {ACCOUNT_IDENTITY_MAX_BYTES} UTF-8 "
            f"bytes (ADR-0149 §4, ADR-0151 §5). Nothing was written"
        )
        raise ConnectionStoreError(msg)
    return identity


def receivable(reference: str) -> str:
    """Refuse a minted reference the caller could never receive (ADR-0151 §11).

    ADR-0151 §11 fixes :data:`~ai_assistant.core.types.CONNECTION_REFERENCE_MAX_BYTES`
    here rather than leaving it to the lane, and the asymmetry with the identity's
    bound is the mint. An oversized *identity* refuses the request the caller sent,
    and the caller still holds the value and can send a shorter one. An oversized
    *reference* refuses a **response** carrying a value that exists only in the
    hub — so the act has landed and its handle is unreachable, recoverable only by
    matching on an identity nothing makes unique. This is what stops a conforming
    minting scheme producing that state.

    Checked **before the first write**, so a factory fault leaves nothing behind
    and ADR-0151 §7's first bucket is the honest classification of it.

    Args:
        reference: What the factory produced.

    Returns:
        The reference, unchanged.

    Raises:
        ConnectionStoreError: If it has no UTF-8 encoding, or if that encoding
            exceeds the bound. The reference is **not named** in the message: §7
            permits no assertion about an act whose first write did not return,
            and this one never started.
    """
    try:
        encoded = len(encodable_text(reference).encode("utf-8"))
    except ValueError as exc:
        msg = (
            "the reference factory produced a value with no UTF-8 encoding; a handle the "
            "caller could never receive is refused before anything is written"
        )
        raise ConnectionStoreError(msg) from exc
    if encoded > CONNECTION_REFERENCE_MAX_BYTES:
        msg = (
            f"the reference factory produced {encoded} bytes, above "
            f"CONNECTION_REFERENCE_MAX_BYTES ({CONNECTION_REFERENCE_MAX_BYTES}); a handle "
            f"the caller could never receive is refused before anything is written"
        )
        raise ConnectionStoreError(msg)
    return reference


class ConnectionEntry(BaseModel):
    """One append to the connection store (ADR-0148 §6, ADR-0149 §3, §5).

    Two shapes in one model, told apart by whether :attr:`state` is present:

    - a **provisioning entry**, carrying the identity, the revision, the
      provisioning state and this act's own credential slot; and
    - a **removal entry**, carrying "the reference, the incremented revision and
      the fact that the connection was removed" and nothing else (ADR-0149 §5).

    A removal is deliberately *not* a third
    :class:`~ai_assistant.core.types.ProvisioningState`, which ADR-0149 §5 forbids
    in terms; the absence of one is what says the reference has no live record.

    **`tools/`-internal, and not a promoted type.** ADR-0149 §3 adds no Protocol
    for reading or writing a connection record and this model is not `core`
    surface: what crosses a subsystem boundary is
    :class:`~ai_assistant.core.types.ConnectedAccount` and
    :class:`~ai_assistant.core.types.ConnectionAct`, neither of which carries a
    slot.

    **It carries no credential value and nothing derived from one, in any field,
    including the identity** — ADR-0148 §6's exclusion clause applied to the
    record the same clause creates (ADR-0149 §3).

    Attributes:
        reference: The connection this entry is about.
        revision: ADR-0148 §6's monotonic revision, never reused and never
            decreasing across the reference's whole history, a disconnection
            included (ADR-0149 §5).
        identity: The account identity, verbatim, or ``None`` on a removal.
        state: How far the act that wrote this entry had got, or ``None`` on a
            removal.
        slot: The credential slot the act which wrote this entry wrote its
            credential to, or ``None`` on a removal. Never a slot an earlier act
            wrote, and never written by two acts (ADR-0148 §6).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: DurableIdentifier
    revision: int = Field(gt=0)
    identity: NonBlankEncodableText | None
    state: ProvisioningState | None
    slot: SecretName | None

    @model_validator(mode="after")
    def _is_one_shape_or_the_other(self) -> ConnectionEntry:
        """Refuse an entry that is neither a provisioning entry nor a removal.

        The three optional members travel together: an entry with a state but no
        slot would name a record no credential read could satisfy, and one with a
        slot but no state would be a record ADR-0148 §6 has no state for. Making
        the mixture unconstructible is cheaper than checking for it at each of
        the six places that read an entry.

        Raises:
            ValueError: If some but not all of the identity, the state and the
                slot are present.
        """
        present = (self.identity is not None, self.state is not None, self.slot is not None)
        if any(present) and not all(present):
            msg = (
                "a connection entry carries an identity, a state and a slot together "
                "(a provisioning entry) or none of them (a removal entry, ADR-0149 §5); "
                f"got identity={present[0]}, state={present[1]}, slot={present[2]}"
            )
            raise ValueError(msg)
        return self

    def account(self) -> ConnectedAccount | None:
        """This entry as the record a caller outside `tools/` sees, or ``None``.

        ``None`` for a removal entry, which is exactly ADR-0151 §4's rule for
        :attr:`~ai_assistant.core.types.ConnectionAct.account`.

        Returns:
            The promoted record, less the slot no caller may name (ADR-0149 §10).
        """
        if self.identity is None or self.state is None:
            return None
        return ConnectedAccount(
            reference=self.reference,
            identity=self.identity,
            revision=self.revision,
            state=self.state,
        )

    def act(self) -> ConnectionAct:
        """This entry as the act row ``recent_connection_acts`` returns.

        Returns:
            The act, with its record present exactly where this entry is a
            provisioning entry (ADR-0151 §4).
        """
        return ConnectionAct(
            reference=self.reference, revision=self.revision, account=self.account()
        )


@final
class StoredEntry:
    """An entry and the sequence number the store filed it under.

    The sequence is the **compare-and-swap token**: a caller observes a
    reference's latest entry, does some work, and hands the sequence back to
    :meth:`SqliteConnectionStore.append`, which appends only if that entry is
    still the latest. It is not part of :class:`ConnectionEntry` because it is the
    store's own bookkeeping rather than anything ADR-0148 §6 says a record
    carries, and a model that held it would invite a caller to construct one.
    """

    __slots__ = ("entry", "sequence")

    def __init__(self, sequence: int, entry: ConnectionEntry) -> None:
        """Pair an entry with its filed position.

        Args:
            sequence: The store's own append order for this entry.
            entry: The entry itself.
        """
        self.sequence = sequence
        self.entry = entry

    def __repr__(self) -> str:
        """Describe the pair by its position and its reference, never its identity."""
        return (
            f"{type(self).__name__}(sequence={self.sequence}, "
            f"reference={self.entry.reference!r}, revision={self.entry.revision})"
        )


@final
class Removal:
    """What a disconnection's first step did, and what its deletion pass may reach.

    ADR-0149 §5 gives a disconnection three outcomes at the store, and a caller
    has to tell them apart to know what to say and what to delete:

    - the store holds **no entry** for the reference — no instance of this class
      is produced at all, nothing is written and no deletion pass runs;
    - the reference had a **live record** — :attr:`removed` is it, as it stood
      immediately before the removal entry was appended, and :attr:`cutoff` is
      that new entry's revision; and
    - the reference had **entries but no live record** — no second removal entry
      is appended, :attr:`removed` is ``None``, and :attr:`cutoff` is the latest
      removal entry's revision, which is what makes the re-run repeat the same
      deletion pass.

    Attributes:
        removed: The live record this call removed, or ``None``.
        cutoff: The revision the deletion pass is bounded by. Every distinct slot
            named by an entry for the reference at a **strictly lower** revision
            is deleted; a slot at or above it belongs to an act this disconnection
            did not displace, and deleting one would leave that act's activation
            standing over an empty slot (ADR-0149 §5).
    """

    __slots__ = ("cutoff", "removed")

    def __init__(self, removed: ConnectionEntry | None, cutoff: int) -> None:
        """Record what the removal step did.

        Args:
            removed: The live record removed, or ``None``.
            cutoff: The revision bounding the deletion pass.
        """
        self.removed = removed
        self.cutoff = cutoff


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    The worker records its own outcome and sets a :class:`threading.Event` when it
    physically returns. This coroutine waits on *that* signal — not on the
    cancellable state of any task — so the lock is held for the whole life of the
    worker even if the awaiting task, or a blanket :func:`asyncio.all_tasks`
    cancellation, is cancelled. An absorbed cancellation takes precedence over the
    worker's own result or failure and is re-raised once the thread has finished:
    the caller's task still cancels, which is ADR-0060's delivery half, and what is
    prevented is connection reuse rather than the cancellation itself. That is
    also the whole of ADR-0153 §8's resource obligation on this store — a cancelled
    :meth:`SqliteConnectionStore.append` leaves no worker still holding the
    connection after the ``CancelledError`` has left it.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the
    caller is then answered out of an empty ``outcome``, an ``IndexError`` standing
    in for the cause rather than chained to it (#680).

    **The completion wait is submitted at most once** (#697). Absorbing a
    cancellation hands the loop a blocking ``done.wait`` job on the default
    executor; a copy that submits a fresh one per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it — which turns one stalled store operation into a
    process that cannot run any thread work at all.

    **The sixth copy of this helper rather than an import from a sibling**, which
    is the tree's established position rather than a fresh choice: each SQLite
    store carries its own, golden rule 1 forbids importing another subsystem's, and
    #506 and #563 already track consolidating the family.
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
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


class SqliteConnectionStore:
    """A persistent, append-only connection store (ADR-0149 §3).

    **Not ``@final``, unlike the value types above, and the exception is
    deliberate.** ADR-0148 §6's classification is stated over what a *store*
    failure does at each of five points — the first write, both re-reads, an
    activation whose swap does not land, and an activation that fails rather than
    returning — and ADR-0151 §16 requires one deterministic case each. A subclass
    that overrides one method to raise, or to commit and then raise, is how a test
    reaches those points against the real implementation; the alternative is a
    duck-typed double, which would test a second store rather than this one. No
    production subclass exists and none is expected.

    **Entries are stored as their JSON dump and rebuilt on every read**, which is
    how a detached snapshot is obtained here without a copy step to forget:
    serialising rebuilds every reachable value, so there is no object graph shared
    with a caller in either direction, and the store cannot hand back a
    caller-supplied subclass.

    **Atomicity comes from an :class:`asyncio.Lock` around each method, with the
    compare-and-swap's read and its append inside one ``BEGIN IMMEDIATE``
    transaction.** Two concurrent provisioning acts therefore cannot both observe
    the same latest entry and both append, which is the guarantee ADR-0148 §6's
    ownership clause exists for.

    **No busy timeout is set here, and that is the family's posture rather than
    this store's choice** (#564): no SQLite store in this tree sets one
    deliberately, so under cross-process contention ``BEGIN IMMEDIATE`` surfaces
    ``SQLITE_BUSY`` after the driver's default.
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the connection store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                store exists — it is the *only* durable list of the credential
                slots the provisioner wrote (ADR-0149 §8), because ADR-0125 §5
                refuses enumeration and nothing can discover a slot it did not
                record — so a default would let the ordinary construction produce
                a store whose loss orphans Tier 0 data nothing can ever name
                again. An ephemeral store is available and has to be asked for.

                It lives under ``Settings.data_dir`` in a real deployment
                (ADR-0149 §3), which is the composition root's choice rather than
                this class's.

        Raises:
            ConnectionStoreError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def __repr__(self) -> str:
        """Describe the store by its path, never by what it holds."""
        return f"{type(self).__name__}(path={self._path!r})"

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``, and a
            # bad path is this layer's fault to report rather than a raw builtin
            # escaping its error boundary (#238).
            msg = f"failed to open the connection store at {self._path!r}: {exc}"
            raise ConnectionStoreError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built: SQLite copies the database file's mode onto every rollback
            # journal it creates, so a journal opened while the file still carried
            # the process umask is world-readable too — and an interrupted write
            # leaves it on disk holding Tier 1 pages (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                for statement in _INDEXES:
                    conn.execute(statement)
                if not labelled:
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except ConnectionStoreError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the connection store at {self._path!r}: {exc}"
            raise ConnectionStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault. A *symlink*
        under a sidecar's name is skipped rather than followed: ``chmod`` follows
        links, so restricting one would silently narrow a file that holds none of
        this store's data.

        A no-op in memory, where there is no file to restrict.

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

        Runs inside the setup transaction, after ``meta`` exists and **before**
        the ``entries`` table is created or read (ADR-0049 §1's ordering).

        Returns:
            Whether the database already carries a ``schema_version``. ``False``
            means it does not, and :meth:`_setup` stamps one.

        Raises:
            ConnectionStoreError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single
                unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the connection store at {self._path!r} holds {len(rows)} schema_version "
                f"rows ({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise ConnectionStoreError(msg)
        raw = rows[0][0]
        msg = f"the connection store at {self._path!r} holds a non-numeric schema_version {raw!r}"
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise ConnectionStoreError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise ConnectionStoreError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the connection store at {self._path!r} has schema_version={stored}, but "
                f"this code supports only version {_SCHEMA_VERSION}; refusing to open it "
                f"rather than read it blindly"
            )
            raise ConnectionStoreError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` is what puts :meth:`_append_sync`'s *read* under the write
        lock: the latest-entry lookup decides whether the append may happen, so a
        deferred begin would let a second process append between the two and
        ADR-0148 §6's compare-and-swap would be a race. The :class:`asyncio.Lock`
        closes that within one process; this closes it against the file.

        Raises:
            ConnectionStoreError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=ConnectionStoreError, immediate=immediate)

    # --- the write path -------------------------------------------------------

    async def append(
        self, entry: ConnectionEntry, *, expected_latest: int | None
    ) -> StoredEntry | None:
        """Append ``entry`` if the reference's latest is still ``expected_latest``.

        ADR-0148 §6's compare-and-swap, in ADR-0149 §3's terms: "an act appends
        only if the entry it observed is still the latest, and appends nothing
        otherwise". One primitive serves all three of the act's decision points —
        the taking swap, the activation's own swap, and the mint's refusal.

        Args:
            entry: The entry to append.
            expected_latest: The sequence of the entry the caller observed as this
                reference's latest, or ``None`` to require that the reference has
                **no entries at all**. That second form is ADR-0151 §3's mint
                guarantee — "the store refuses an append that would introduce a
                reference it already holds, which is the half of the guarantee it
                can establish by itself".

        Returns:
            The filed entry, or ``None`` where the swap did not land — which is
            not a fault: the caller's act was displaced and "never held it and
            writes nothing" (ADR-0148 §6).

        Raises:
            ConnectionStoreError: If the store could not be read or written, or
                if the append would break the revision monotonicity ADR-0148 §6
                requires.
        """
        snapshot = _revalidated(entry)
        async with self._lock:
            return await _run_to_completion(self._append_sync, snapshot, expected_latest)

    def _append_sync(
        self, entry: ConnectionEntry, expected_latest: int | None
    ) -> StoredEntry | None:
        """Compare, swap and insert, as one transaction."""
        with self._transaction(f"append to connection {entry.reference!r}") as conn:
            row = conn.execute(
                "SELECT sequence, reference, revision, data FROM entries WHERE reference = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (entry.reference,),
            ).fetchone()
            current = None if row is None else _sequence(row[0])
            if current != expected_latest:
                return None
            if row is not None and entry.revision < _decoded(_projection(row, at=1)).revision:
                # Not a displacement — a caller that computed a revision below one
                # the reference already holds. ADR-0148 §6 makes monotonicity the
                # property a credential read's "unchanged since I looked" rests on,
                # so the store refuses rather than filing an entry that breaks it.
                msg = (
                    f"connection {entry.reference!r} already holds a higher revision, so an "
                    f"entry at revision {entry.revision} would break the monotonicity "
                    f"ADR-0148 §6 requires"
                )
                raise ConnectionStoreError(msg)
            cursor = conn.execute(
                "INSERT INTO entries(reference, revision, data) VALUES (?, ?, ?)",
                (entry.reference, entry.revision, entry.model_dump_json()),
            )
            sequence = _sequence(cursor.lastrowid or 0)
        return StoredEntry(sequence, entry)

    async def remove(self, reference: str) -> Removal | None:
        """Append a removal entry for ``reference``, or report that none is owed.

        ADR-0149 §5's **first** step, and only that: the slots are the caller's to
        delete second, bounded by :attr:`Removal.cutoff`.

        **Idempotent.** A reference with entries but no live record appends no
        second removal entry and yields the latest removal's revision, so the
        re-run repeats the same deletion pass — which is the remedy for a slot a
        displaced act wrote after that removal landed, and for one whose deletion
        failed.

        Args:
            reference: The connection to disconnect, compared exactly.

        Returns:
            What the removal step did, or ``None`` where the store holds no entry
            for the reference — in which case nothing was written, no revision
            sequence was created, and no deletion pass is owed (ADR-0149 §5).

        Raises:
            ConnectionStoreError: If the store could not be read or written.
        """
        async with self._lock:
            return await _run_to_completion(self._remove_sync, reference)

    def _remove_sync(self, reference: str) -> Removal | None:
        """Read the latest entry and append a removal where one is owed."""
        with self._transaction(f"disconnect connection {reference!r}") as conn:
            row = conn.execute(
                "SELECT reference, revision, data FROM entries WHERE reference = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (reference,),
            ).fetchone()
            if row is None:
                return None
            latest = _decoded(row)
            if latest.state is None:
                # The latest entry is already a removal: no second one, and the
                # deletion pass repeats at its revision (ADR-0149 §5).
                return Removal(None, latest.revision)
            revision = latest.revision + 1
            removal = ConnectionEntry(
                reference=reference,
                revision=revision,
                identity=None,
                state=None,
                slot=None,
            )
            conn.execute(
                "INSERT INTO entries(reference, revision, data) VALUES (?, ?, ?)",
                (reference, revision, removal.model_dump_json()),
            )
        return Removal(latest, revision)

    async def clear(self) -> None:
        """Delete every entry, wholesale (ADR-0149 §8).

        The second half of the purge, run **only** once every distinct slot the
        store named has been confirmed deleted or confirmed absent. There is no
        ``delete(reference)`` beside it: a selective delete would tear a page out
        of a record ADR-0149 §7 offers as ADR-0004 §7's recorded half.

        Only ``entries`` is emptied; the ``meta`` schema marker describes the
        file's shape rather than the user's history.

        Raises:
            ConnectionStoreError: If the store cannot be cleared.
        """
        async with self._lock:
            await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> None:
        """Empty the table in one statement."""
        with self._transaction("clear the connection store") as conn:
            conn.execute("DELETE FROM entries")

    # --- the read path --------------------------------------------------------

    async def latest(self, reference: str) -> StoredEntry | None:
        """The reference's latest entry and its swap token, or ``None``.

        ``reference`` is compared with SQLite's ``=`` on a ``TEXT`` column and
        nothing else — no strip, no case-fold, no normalising of any kind
        (ADR-0151 §3).

        Args:
            reference: The connection to look up.

        Returns:
            The latest entry filed for it, or ``None`` if the store holds none.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        async with self._lock:
            row = await _run_to_completion(self._latest_sync, reference)
        if row is None:
            return None
        return StoredEntry(_sequence(row[0]), _decoded(_projection(row, at=1)))

    def _latest_sync(self, reference: str) -> Sequence[object] | None:
        """Read the reference's newest row, uncoerced."""
        try:
            row = self._conn.execute(
                "SELECT sequence, reference, revision, data FROM entries WHERE reference = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (reference,),
            ).fetchone()
        except sqlite3.Error as exc:
            msg = f"failed to read connection {reference!r}: {exc}"
            raise ConnectionStoreError(msg) from exc
        return None if row is None else tuple(row)

    async def live(self) -> tuple[ConnectedAccount, ...]:
        """Every reference's live record (ADR-0149 §3, ADR-0151 §9).

        **Computed from one read**, so the set is a snapshot: no reference appears
        twice, and none is missing because another was being written.

        Returns:
            The live record for every reference that has one, including those
            whose live record is ``PENDING``.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._select_sync, _LIVE, (), "read the live records")
        return tuple(record for row in rows if (record := _decoded(row).account()) is not None)

    async def recent(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        """Up to ``limit`` acts, newest first (ADR-0151 §9).

        One row per ``(reference, revision)``, carrying the furthest provisioning
        state that act reached — so an act whose activation landed reads as
        ``ACTIVE`` and a displaced act's own entry stays ``PENDING`` at its own
        revision, which is the row ADR-0149 §5's deletion pass and §8's purge each
        reach that act's slot through.

        Args:
            limit: The most rows to return. Clamped **upward** only, because a
                Python ``int`` has no width and binding one wider than SQLite's
                signed 64-bit parameter raises ``OverflowError`` — neither
                ``ValueError`` nor ``ConnectionStoreError``, so it would leave
                this layer's error boundary through a hole. A bound above any
                possible row count means "all of them", which is what the query
                then returns.

        Returns:
            The acts, newest first.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        bound = min(limit, _MAX_SQLITE_INT)
        async with self._lock:
            rows = await _run_to_completion(
                self._select_sync, f"{_ACTS} LIMIT ?", (bound,), "read the connection acts"
            )
        return tuple(_decoded(row).act() for row in rows)

    async def entries_for(self, reference: str) -> tuple[ConnectionEntry, ...]:
        """Every entry filed for ``reference``, oldest first.

        The store is append-only, so this is the reference's whole history — which
        is what makes a superseded slot nameable after the act that wrote it is
        gone (ADR-0149 §3).

        Args:
            reference: The connection to read.

        Returns:
            Its entries in append order.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(
                self._select_sync,
                "SELECT reference, revision, data FROM entries WHERE reference = ? "
                "ORDER BY sequence ASC",
                (reference,),
                f"read the history of connection {reference!r}",
            )
        return tuple(_decoded(row) for row in rows)

    async def slots_below(self, reference: str, revision: int) -> tuple[SecretName, ...]:
        """Every distinct slot named for ``reference`` below ``revision``.

        ADR-0149 §5's deletion set, exactly: "every distinct slot named by an
        entry for that reference whose revision is strictly less than that
        disconnection's own removal entry's revision — the removed record's, and
        every superseded, pending or earlier removed entry's". Deleting only the
        live record's slot does not satisfy it, and deleting a slot at or above
        the cutoff **violates** it.

        Args:
            reference: The connection whose slots are being deleted.
            revision: The removal entry's revision, exclusive.

        Returns:
            The distinct slots, in the order they were first recorded.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(
                self._select_sync,
                "SELECT reference, revision, data FROM entries WHERE reference = ? "
                "ORDER BY sequence ASC",
                (reference,),
                f"read the credential slots of connection {reference!r}",
            )
        # The cutoff runs over the decoded entries rather than in SQL, so every
        # row it excludes has been checked against its own projection first — a
        # revision filtered out in the database is one nothing would have read.
        entries = (_decoded(row) for row in rows)
        return _distinct(entry.slot for entry in entries if entry.revision < revision)

    async def slots(self) -> tuple[SecretName, ...]:
        """Every distinct slot the store names, for ADR-0149 §8's purge.

        The live records' slots and every superseded, pending or removed record's
        — which is what makes the purge complete, because ADR-0125 §5 refuses
        enumeration and this store is the only durable list of them.
        **Deduplicated**, which is half of what makes the purge idempotent.

        Returns:
            The distinct slots, in the order they were first recorded.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(
                self._select_sync,
                "SELECT reference, revision, data FROM entries ORDER BY sequence ASC",
                (),
                "read the credential slots",
            )
        return _distinct(_decoded(row).slot for row in rows)

    def _select_sync(
        self, statement: str, parameters: Sequence[object], what: str
    ) -> list[tuple[str, int, str]]:
        """Run one statement and return its ``(reference, revision, data)`` rows."""
        try:
            rows = self._conn.execute(statement, tuple(parameters)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise ConnectionStoreError(msg) from exc
        return [_projection(row, at=0) for row in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _distinct(slots: Iterable[SecretName | None]) -> tuple[SecretName, ...]:
    """Return the slots in first-recorded order with duplicates dropped.

    Deduplicated on both fields of a :class:`~ai_assistant.core.types.SecretName`,
    because "two ``SecretName`` values name the same entry when and only when both
    fields are equal" (ADR-0125 §2) — and the model is frozen but not hashable, so
    the pair is what a ``dict`` is keyed on rather than the value itself.

    Written over an iterable of ``SecretName | None`` because the queries that
    feed it already exclude a NULL slot; the ``None`` guard is what keeps the
    types honest rather than a case anyone expects.

    Args:
        slots: The slots read, in append order.

    Returns:
        The distinct slots, in the order they were first seen.
    """
    seen: dict[tuple[str, str], SecretName] = {}
    for slot in slots:
        if slot is not None and (key := (slot.scope.value, slot.key)) not in seen:
            seen[key] = slot
    return tuple(seen.values())


def _revalidated(entry: ConnectionEntry) -> ConnectionEntry:
    """Rebuild ``entry`` as a validated :class:`ConnectionEntry`.

    ``model_construct`` is public and yields a well-typed object carrying values
    the model's own invariants forbid, so an entry is rebuilt before it is filed
    rather than trusted — the discipline ADR-0125 §4 states for the keyring seam,
    applied to this store's own append. Rebuilt **from the instance's field state**
    rather than from ``model_dump()``, which is an ordinary overridable method: a
    subclass could return a mapping that does not describe itself, and the store
    would then file a record different from the one it was handed.

    It is also where ADR-0149 §4's identity shape is enforced, because this is the
    one function every append passes through — a check on the model itself would
    raise pydantic's ``ValidationError`` at construction, which is not a failure
    ADR-0151 §2a declares of any operation on this surface.

    Raises:
        ConnectionStoreError: If the entry does not satisfy its own model, or if
            its identity is not ADR-0149 §4's bounded single-line printable text.
    """
    fields = dict(object.__getattribute__(entry, "__dict__"))
    try:
        rebuilt = ConnectionEntry.model_validate(fields)
    except ValidationError as exc:
        msg = f"the connection entry for {fields.get('reference')!r} is not a valid record: {exc}"
        raise ConnectionStoreError(msg) from exc
    if rebuilt.identity is not None:
        printable_identity(rebuilt.identity)
    return rebuilt


def _sequence(value: object) -> int:
    """Accept a row's integer column, refusing anything that is not one.

    Separate from :func:`_projection` because the compare-and-swap reads the
    sequence without the rest of the row, and a token this code cannot read is a
    store it cannot swap on.

    **It refuses rather than coerces, and the difference is a silent corruption.**
    ``int(...)`` is a *conversion*: it reads ``1.5`` as ``1`` and ``True`` as ``1``,
    so a hand-edited ``revision = 1.5`` would decode against a JSON revision of 1,
    pass :func:`_decoded`'s projection check, and be returned as a valid row —
    while ``recent``'s ``GROUP BY revision`` had already split that one act into
    two groups, both reported at revision 1. So the test is the *type*, not what
    the value converts to: SQLite stores an integer as an integer, and anything
    else in these columns is a file this code did not write. ``bool`` is named
    because it is an ``int`` in Python, which is the same trap
    :meth:`SqliteConnectionStore._check_schema_version` names for its own marker.

    Args:
        value: The column, as ``sqlite3`` handed it back.

    Returns:
        The value, unchanged.

    Raises:
        ConnectionStoreError: If it is not an integer this code wrote.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = (
            f"the connection store holds a {type(value).__name__} where this code writes an "
            f"integer; the store is corrupt"
        )
        raise ConnectionStoreError(msg)
    return value


def _projection(row: Sequence[object], *, at: int) -> tuple[str, int, str]:
    """Read a row's ``(reference, revision, data)`` projection, coercing safely.

    ``sqlite3`` hands back whatever the file holds, and this store's columns carry
    no type affinity strong enough to promise otherwise: a hand-built or corrupted
    database can put a string, a NULL or a float in ``revision``, where a bare
    ``int(...)`` raises ``ValueError``, ``TypeError`` or ``OverflowError``. None of
    those is an :class:`~ai_assistant.core.errors.AssistantError`, so each would
    leave this layer's error boundary through a hole — the same hole #238 records
    on the audit trail — and reach a caller that was promised
    :class:`~ai_assistant.core.errors.ConnectionStoreError` for a store it cannot
    read.

    Args:
        row: The selected row, projected columns first.
        at: Where ``reference`` starts, so the one caller that also selects
            ``sequence`` can share this.

    Returns:
        The coerced projection.

    Raises:
        ConnectionStoreError: If the row's columns are not the shape this store
            wrote — a corrupt database, reported rather than coerced past. The
            revision goes through :func:`_sequence`, which is the same coercion
            the swap token takes and for the same reason.
    """
    try:
        reference, revision, data = row[at], row[at + 1], row[at + 2]
    except IndexError as exc:
        msg = f"the connection store holds a row this code did not write: {exc}"
        raise ConnectionStoreError(msg) from exc
    return str(reference), _sequence(revision), str(data)


def _decoded(row: tuple[str, int, str]) -> ConnectionEntry:
    """Rebuild a stored entry from its JSON, refusing a row that disagrees with it.

    The blob is the entry; ``reference`` and ``revision`` are projections SQLite
    narrows and groups on. A row whose projection does not describe the entry it
    carries is a file something else has written to, and reading it would answer a
    question about rows the query never selected — so it is reported rather than
    resolved, on the same footing as a row that no longer validates.

    Args:
        row: The ``(reference, revision, data)`` triple every read selects.

    Returns:
        The decoded entry.

    Raises:
        ConnectionStoreError: If the row no longer validates — a corrupted or
            downgraded database — if its identity is outside ADR-0149 §4's shape,
            or if its projected reference or revision disagrees with the entry.
    """
    reference, revision, data = row
    try:
        entry = ConnectionEntry.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the connection store holds an entry that no longer validates: {exc}"
        raise ConnectionStoreError(msg) from exc
    if entry.identity is not None:
        # The same shape check the append runs, on the way back out. ADR-0149 §4
        # binds the *store*, and a store that enforced only on write would hand a
        # caller an identity it would refuse to accept — which is a file edit away
        # and is exactly the "reported rather than resolved" case the decode above
        # already covers for a row that no longer validates.
        printable_identity(entry.identity)
    if entry.reference != reference or entry.revision != revision:
        msg = (
            f"the connection store holds a row projected as {reference!r} at revision "
            f"{revision} carrying an entry for {entry.reference!r} at revision "
            f"{entry.revision}; the store is corrupt"
        )
        raise ConnectionStoreError(msg)
    return entry


__all__ = [
    "ConnectionEntry",
    "Removal",
    "SqliteConnectionStore",
    "StoredEntry",
    "receivable",
]
