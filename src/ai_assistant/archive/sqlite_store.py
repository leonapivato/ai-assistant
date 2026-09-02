"""The transcript archive on SQLite — a store of text and nothing else (ADR-0225).

One file, ``transcripts.db``, under ``Settings.data_dir``, holding one table and
the indexes inside it. It satisfies both of ADR-0225 §10's Protocols structurally,
so the composition root hands each collaborator exactly the seam it is entitled
to: a :class:`~ai_assistant.core.protocols.TranscriptArchiveWriter` to capture,
which can append and cannot read, and a
:class:`~ai_assistant.core.protocols.TranscriptArchive` to ``AssistantEngine``,
which can read and cannot append.

**A Tier 1 store, and the one nothing but the user reads** (ADR-0004 §1, ADR-0225
§4). Nothing here is embedded, nothing here is walked, nothing here is a citation
target, and no text held here is written to a log, a trace or an audit trail. Those
are properties of the package fence and of the two seams rather than of this module
— but this module is where they would be broken, so: it constructs no
``Embedder``, offers no cursor, and its failures name an address and never an
entry's text (ADR-0004 §5).

**A database of its own rather than a table beside** ``memory.db`` (§10, on
ADR-0119 §6's reasoning). A separate file is what makes the reach of every
whole-store operation a decided question instead of an accident of which tables
share a connection: ``MemoryStore.clear`` empties the memory store and does not
touch the archive, and §5 obliges whoever gives ``clear`` a surface to erase both
in one act — which is a decision stated in an ADR rather than a consequence of SQL.

**The search is a scan over folded text held in this database, not a full-text
index** (§7). ADR-0225's predicate is a *case-insensitive substring* match under
full Unicode case folding; FTS5 tokenises, so it cannot answer "this folded run
occurs contiguously in that folded field" for a query that straddles a token
boundary or falls inside one — and §7 is explicit that "an implementation whose
index cannot answer this predicate is not a conforming implementation, and the
predicate is not relaxed to fit one". So each half of an entry is stored twice: as
the user's own bytes, and as the NFC-normalised, case-folded form the predicate is
evaluated over. Both live inside the one database file, which is §6's closed set.

**Retention is enforced at the read and stamped nowhere** (§6). No column holds an
expiry, no sweep is required and none runs: every read compares ``occurred_at``
against *the instant of that read minus the retention this store was built with*,
so a shortened retention takes effect immediately and everywhere, and the guarantee
does not depend on a background job — which is ADR-0007 §2's own rule, inherited
deliberately and for the same reason. The **destroys** reach what the reads hide.

Local-first (ADR-0002) and locally only. The database file and every sidecar SQLite
may keep beside it are owner-only on **every** open (ADR-0004 §4, ADR-0225 §9),
which is the case file-mode inheritance does not cover.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.archive._transactions import transaction
from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import TranscriptArchiveError
from ai_assistant.core.types import (
    TRANSCRIPT_EXCERPT_BYTES,
    ExchangeDisposition,
    TranscriptArchiveSize,
    TranscriptEntry,
    TranscriptHit,
    describe_untrusted,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so a transcript is exposed by an unrestricted ``-wal``
#: exactly as it would be by an unrestricted ``.db`` (ADR-0225 §9). Kept identical
#: to the other six stores' lists rather than re-derived: #506 is the issue that
#: consolidates the family, and a store that spelled it differently would be the
#: one that has to be brought back in.
_SIDECARS = ("-journal", "-wal", "-shm")

#: One past the largest value a paging argument may take: the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2). ADR-0225 §10 states
#: the refusals that matter to a caller — a ``limit`` of zero or below and a
#: negative ``offset`` — and this is the backend's own edge beyond them, refused
#: here rather than raising ``OverflowError`` out of the driver. The canonical
#: fake refuses the same range, so two conforming implementations agree.
_PAGE_BOUND = 2**63

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS entries("
    "address TEXT PRIMARY KEY NOT NULL, "
    "conversation_id TEXT NOT NULL, "
    "ordinal INTEGER NOT NULL, "
    "occurred_at_us INTEGER NOT NULL, "
    "asked TEXT, "
    "replied TEXT, "
    "asked_folded TEXT, "
    "replied_folded TEXT, "
    "disposition TEXT NOT NULL)"
)

#: Both indexes live **inside** the database file, which is what keeps §6's closed
#: set closed: an index is not a second on-disk artifact, so every byte
#: ``stored_bytes`` counts is a byte ADR-0225 §9's ``0600`` protects.
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS entries_by_conversation ON entries(conversation_id, ordinal)",
    "CREATE INDEX IF NOT EXISTS entries_by_instant ON entries(occurred_at_us DESC, address)",
)

_INSERT = (
    "INSERT INTO entries("
    "address, conversation_id, ordinal, occurred_at_us, "
    "asked, replied, asked_folded, replied_folded, disposition) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_COLUMNS = "address, conversation_id, ordinal, occurred_at_us, asked, replied, disposition"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_micros(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``, for the reason :mod:`ai_assistant.memory.sqlite_store`
    records: a float epoch second carrying microsecond precision needs sixteen
    significant digits at present-day values, right at the edge of a double, so two
    instants a microsecond apart could compare equal or invert — and this key
    decides what a retention predicate hides and what an ordering puts first.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _span_micros(span: timedelta) -> int:
    """Return ``span`` as whole microseconds, by the same integer arithmetic.

    Paired with :func:`_to_micros` so a horizon can be taken **in microseconds**
    rather than by subtracting a ``timedelta`` from a ``datetime``: that subtraction
    raises ``OverflowError`` for any reading close enough to ``datetime.min``, and
    ``checked_clock`` admits such a reading — it refuses a naive or indeterminate
    one, not an early one. A read that crashed on the clock rather than answering
    would take every one of ADR-0225 §7's four reads down with it.
    """
    return (span.days * 86_400 + span.seconds) * 1_000_000 + span.microseconds


def _from_micros(micros: int) -> datetime:
    """Return the instant ``micros`` names, as the UTC value it was stored from."""
    return _EPOCH + timedelta(microseconds=micros)


def folded(text: str) -> str:
    """Return ``text`` as ADR-0225 §7's predicate sees it: NFC, then full case folding.

    **The order is the ADR's and is load-bearing.** NFC first makes a composed
    ``é`` and a decomposed one one string; ``str.casefold`` then applies *full*
    Unicode case folding, which folds ``ß`` to ``ss`` where a lower-casing
    tokenizer does not — the two divergences §7 names, each invisible in a test
    suite written against one implementation and immediately visible to a user who
    switches backends.

    Nothing else is applied: no stemming, no lemmatisation, no stop-word removal,
    no accent stripping beyond what NFC performs, and no trimming. The same
    function folds the stored text and the query, so the two cannot disagree.

    Args:
        text: The value to fold, exactly as it was given.

    Returns:
        Its folded, normalised form.
    """
    return unicodedata.normalize("NFC", text).casefold()


def excerpt_of(text: str) -> tuple[str, bool]:
    """Return a bounded window of ``text`` and whether the bound truncated it (§7).

    At most :data:`~ai_assistant.core.types.TRANSCRIPT_EXCERPT_BYTES` bytes of
    UTF-8, cut at a codepoint boundary: the trailing bytes of a multi-byte
    codepoint straddling the bound are **dropped rather than split**, so the result
    is always valid text and always encodes to at most the bound. Where the whole
    of ``text`` fits, the excerpt is ``text`` and nothing was elided — which is what
    a bound means rather than an exception to it.

    Which window is taken is this implementation's (§7 leaves it open); this one
    takes the leading window, so a hit reads as the start of what was said.

    Args:
        text: The matching half of an entry, whole.

    Returns:
        The excerpt, and whether the bound cut it short.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= TRANSCRIPT_EXCERPT_BYTES:
        return text, False
    # ``errors="ignore"`` drops exactly the trailing incomplete sequence: the
    # prefix of a valid UTF-8 encoding contains no other invalid byte, so this is
    # the codepoint-boundary cut rather than a lossy decode.
    return encoded[:TRANSCRIPT_EXCERPT_BYTES].decode("utf-8", errors="ignore"), True


def _check_retention(retention: timedelta | None) -> None:
    """Refuse a retention that is not ``None`` or a strictly positive duration.

    ADR-0225 §6 gives the setting the shape ``timedelta | None`` with ``None``
    meaning *keep forever*; ``core.config.Settings`` refuses the rest at load with
    ``gt=timedelta(0)``, and this is the same refusal at the constructor, on the
    ground ``SqliteConversationStore`` states for its own: the class is public and a
    guard that only fires when a caller remembered to ask is not a guard.

    ``isinstance`` and then the comparison, in that order and not the reverse: a
    non-duration reaches ``<=`` and raises ``TypeError``, which is not what this
    constructor documents.

    Args:
        retention: The value to check.

    Raises:
        ValueError: If it is neither ``None`` nor a strictly positive ``timedelta``.
    """
    if retention is None:
        return
    if not isinstance(retention, timedelta) or retention <= timedelta(0):
        described = describe_untrusted(retention)
        msg = f"retention must be a strictly positive timedelta or None, got {described}"
        raise ValueError(msg)


def check_page(limit: int, offset: int) -> None:
    """Refuse a paging argument ADR-0225 §10 or the backend will not take.

    A ``limit`` of zero or below and a negative ``offset`` are §10's own refusals,
    for ADR-0114 §6's reason. The upper edge is the backend's: an over-wide bind
    raises ``OverflowError`` out of the driver, which is neither a
    ``TranscriptArchiveError`` nor anything the seam documents.

    Duplicated in the canonical fake rather than shared, exactly as
    ``MemoryStore``'s equivalent is: ``ai_assistant.testing`` may not import a
    subsystem (golden rule 1), and ADR-0225 adds no helper to ``core``.

    Args:
        limit: The page size asked for.
        offset: How many rows to skip.

    Raises:
        ValueError: If ``limit`` is outside ``[1, 2**63)`` or ``offset`` is outside
            ``[0, 2**63)``.
    """
    if not 1 <= limit < _PAGE_BOUND:
        msg = f"limit must be in [1, 2**63), got {limit}"
        raise ValueError(msg)
    if not 0 <= offset < _PAGE_BOUND:
        msg = f"offset must be in [0, 2**63), got {offset}"
        raise ValueError(msg)


def check_named(value: str, *, name: str) -> str:
    """Refuse a blank ``address``, ``conversation_id`` or ``query`` (ADR-0225 §10).

    Never read as "everything" — ADR-0101 §1's own rule for a blank label, and
    ADR-0101 §9's rule that no spelling of a destructive operation's scope widens
    what it destroys.

    **It returns the value unchanged rather than stripped**, which matters for
    ``query`` and is harmless for the two ids: §10 types the query
    ``NonBlankEncodableText`` and not ``Identifier`` precisely because stripping
    would rewrite the user's search text before the predicate saw it and would make
    ``" hello"`` and ``"hello"`` one query.

    Args:
        value: The argument, as given.
        name: Its parameter name, for the message.

    Returns:
        ``value``, byte for byte.

    Raises:
        ValueError: If it is blank or whitespace-only.
    """
    if not value.strip():
        msg = f"{name} must not be blank"
        raise ValueError(msg)
    return value


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
    worker's own result and is re-raised once the thread has finished: the caller's
    task still cancels; what is prevented is connection reuse.

    **The completion wait is submitted at most once** (#697): a copy that submitted
    a fresh one per cancellation would leave every earlier one running, and repeated
    cancellation of one blocked call would occupy the whole executor.

    **The eighth copy of this helper rather than an import from a sibling**, which
    is the tree's established position rather than a fresh choice: each SQLite store
    carries its own, #506 and #563 already track consolidating the family, and this
    package is a leaf that may import nothing but ``core`` (ADR-0225 §10).

    Args:
        fn: The synchronous work to run.
        *args: Its arguments.

    Returns:
        Whatever ``fn`` returned.

    Raises:
        BaseException: Whatever the worker raised, once it has finished; or the
            absorbed cancellation, which takes precedence.
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


class SqliteTranscriptArchive:
    """The durable transcript archive: capture writes, the user reads (ADR-0225)."""

    def __init__(
        self,
        *,
        path: Path | str,
        retention: timedelta | None = None,
        now: Clock = _utcnow,
    ) -> None:
        """Open (or create) the archive at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral archive.
                **Required, with no default**: an archive that forgot everything on
                restart would satisfy the type and defeat the decision, so the
                ephemeral form is available and has to be asked for. It lives under
                ``Settings.data_dir`` in a real deployment (ADR-0225 §10), which is
                the composition root's choice rather than this class's.
            retention: How long an entry stays readable, or ``None`` for "keep
                forever" — which is the shipped default and the deliberate opposite
                of ``episode_retention``'s (ADR-0225 §6). It is **the archive's own
                setting**: nothing here derives it from ``episode_retention``, and a
                change to that setting moves nothing in this store. Enforced at the
                read against this value, so no entry carries an expiry stamp and no
                sweep is required.
            now: Clock the retention predicate is evaluated against; injectable so
                tests are deterministic (CONTRIBUTING, "Determinism"). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, because this seam
                never reaches a ``core`` field validator — the reading becomes an
                integer microsecond epoch — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).

        Raises:
            ValueError: If ``retention`` is set and is not a strictly positive
                ``timedelta``. Checked here rather than trusted from configuration,
                for the reason ``SqliteConversationStore`` checks its own: this class
                is public, anyone may construct one directly, and a guard that only
                fires when a caller remembered to ask is not a guard. A negative
                horizon would put the floor *after* the reading and hide entries that
                are plainly live; a value that is not a duration at all would reach
                the arithmetic and raise something this seam does not document.
            TranscriptArchiveError: If the database cannot be opened or its schema
                cannot be created.
        """
        _check_retention(retention)
        self._path = path if path == ":memory:" else str(Path(path))
        self._retention = retention
        self._clock = checked_clock(now, owner="SqliteTranscriptArchive")
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection.

        Returns:
            The open connection.

        Raises:
            TranscriptArchiveError: If the database cannot be opened or initialised.
        """
        try:
            # ``isolation_level=None`` puts the driver in autocommit mode, so every
            # transaction here is an explicit ``BEGIN … COMMIT`` this module
            # controls — the shape :mod:`ai_assistant.memory.sqlite_store` records,
            # and for its reason: the driver's implicit transactions are *deferred*,
            # upgrading to a write lock only at the first write, which leaves a
            # read-then-write sequence open to the cross-process interleaving
            # ``BEGIN IMMEDIATE`` forbids.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL raises
            # it out of the driver rather than a ``sqlite3.Error``.
            msg = f"failed to open the transcript archive at {self._path!r}: {exc}"
            raise TranscriptArchiveError(msg) from exc
        try:
            # Restricted *before* the first statement (ADR-0225 §9, #489): SQLite
            # copies the database file's mode onto a journal **it creates**, and the
            # ``BEGIN IMMEDIATE`` below is such a write. ``connect`` creates the
            # file, so there is something to restrict by the time this runs (#451).
            self._restrict_permissions()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_TABLE)
            for statement in _INDEXES:
                conn.execute(statement)
            conn.execute("COMMIT")
        except TranscriptArchiveError:
            # Closing also discards the uncommitted ``BEGIN IMMEDIATE``, so a
            # refused open leaves no half-built schema behind.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the transcript archive at {self._path!r}: {exc}"
            raise TranscriptArchiveError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0225 §9).

        ADR-0225 §9 holds the archive to ``SqliteMemoryStore._restrict_permissions``'s
        standard and restates none of how it works, so this is that method: a missing
        sidecar tolerated one name at a time, because a cleanly closed database has
        none; a sidecar this process cannot restrict failing the open, because it is a
        file about to be written through; and a *symlink* under a sidecar's name
        skipped rather than followed, because ``chmod`` follows links and
        ``os.chmod(follow_symlinks=False)`` is unsupported on Linux, so restricting one
        would silently narrow a file this store has no business modifying (#490).

        **Called on every open and not at creation alone**, which is the case file-mode
        inheritance does not cover: a ``-wal`` a previous process left group-readable
        keeps its own mode across a reopen and then takes Tier 1 pages.

        A no-op in memory, where there is no file to restrict.

        **Duplicated from the six other SQLite stores on purpose** (#506).
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

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so ``append``'s
        insert-if-absent guard holds **across processes** and not merely across
        coroutines on one loop: without it a second process could land the same
        address between this one's check and its insert, and §2's loud failure would
        become a silent overwrite. ``immediate=False`` is the read form, so the two
        statements a paged read runs see one consistent snapshot.

        Raises:
            TranscriptArchiveError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=TranscriptArchiveError, immediate=immediate)

    # --- the retention predicate (§6) ---------------------------------------

    def _floor(self) -> int:
        """The oldest ``occurred_at`` a read may still return, in microseconds.

        ADR-0225 §6's predicate, evaluated **at the read** against the setting in
        force: an entry strictly older than *this read's instant minus the
        retention* is treated as already evicted, whether or not anything has
        physically reclaimed it, whether or not the archive has been written to
        since, and on a process that has run no sweep at all. That is ADR-0007 §2's
        rule for a record past ``expires_at``, inherited deliberately so the
        guarantee does not depend on a background job.

        With no retention there is no floor, and the sentinel is the smallest value
        a stored key can take rather than a branch every query would have to carry.
        The arithmetic is integer microseconds throughout, so no reading and no
        retention this seam admits can make a read raise instead of answering.

        Raises:
            TranscriptArchiveError: If the clock reading is naive, indeterminate, or
                outside the localizable range.
        """
        if self._retention is None:
            return -_PAGE_BOUND
        try:
            reading = self._clock()
        except ClockReadingError as exc:
            raise TranscriptArchiveError(str(exc)) from exc
        # In microseconds rather than as `reading - self._retention`, and clamped to
        # the smallest value a SQLite bind takes. Both halves are about a horizon
        # that falls off the end of the representable range: `datetime` subtraction
        # raises `OverflowError` below `datetime.min`, and `timedelta.max` is wide
        # enough to put the floor below the signed 64-bit bind range from any
        # reading at all. A floor no stored instant can precede hides nothing, which
        # is the right answer for a horizon longer than the calendar.
        return max(_to_micros(reading) - _span_micros(self._retention), -_PAGE_BOUND)

    # --- the writer seam (§2, §5) -------------------------------------------

    async def append(self, entry: TranscriptEntry) -> None:
        """Write ``entry`` at its own address (ADR-0225 §1, §2, §3).

        The folded halves are computed here, from the entry's own text and nothing
        else, so the predicate the search evaluates and the text a read returns
        cannot drift apart.

        Raises:
            TranscriptArchiveError: If the archive cannot be written, an entry
                already standing at ``entry.address`` included — the fault ADR-0225
                §2 fails loudly rather than resolving.
        """
        row = (
            entry.address,
            entry.conversation_id,
            entry.ordinal,
            _to_micros(entry.occurred_at),
            entry.asked,
            entry.replied,
            None if entry.asked is None else folded(entry.asked),
            None if entry.replied is None else folded(entry.replied),
            str(entry.disposition),
        )
        async with self._lock:
            await _run_to_completion(self._append_sync, row)

    def _append_sync(self, row: tuple[object, ...]) -> None:
        with self._transaction("append a transcript entry") as conn:
            try:
                conn.execute(_INSERT, row)
            except sqlite3.IntegrityError as exc:
                # The address is the episode's own id, derived from a unique
                # conversation and a store-proved ordinal, so a collision means a
                # broken ordinal invariant or a foreign producer in the reserved
                # namespace (ADR-0074 §3, ADR-0225 §2). Neither is a race, a retry
                # answers neither, and the message names the address and never the
                # text (ADR-0004 §5).
                msg = f"a transcript entry already stands at address {row[0]!r}"
                raise TranscriptArchiveError(msg) from exc

    async def discard(self, address: str) -> bool:
        """Destroy the entry at ``address``; report whether one was there (§5).

        **No retention floor is applied.** A destruction is never refused on the
        ground that a read would not have shown it: the destroys reach what the
        reads hide (§6).

        Raises:
            ValueError: If ``address`` is blank or whitespace-only.
            TranscriptArchiveError: If the archive cannot be written.
        """
        named = check_named(address, name="address")
        async with self._lock:
            return await _run_to_completion(self._discard_sync, named)

    def _discard_sync(self, address: str) -> bool:
        with self._transaction("discard a transcript entry") as conn:
            cursor = conn.execute("DELETE FROM entries WHERE address = ?", (address,))
            return cursor.rowcount > 0

    async def discard_conversation(self, conversation_id: str) -> int:
        """Destroy every entry grouped under ``conversation_id``; return how many (§5).

        Resolved inside this store against its own rows, so it needs neither the
        conversation index, the conversation record nor the memory record to still
        exist — which is what lets a user destroy the transcript of a conversation
        ADR-0074 §7's reclaim has already dropped.

        Raises:
            ValueError: If ``conversation_id`` is blank or whitespace-only.
            TranscriptArchiveError: If the archive cannot be written.
        """
        named = check_named(conversation_id, name="conversation_id")
        async with self._lock:
            return await _run_to_completion(self._discard_conversation_sync, named)

    def _discard_conversation_sync(self, conversation_id: str) -> int:
        with self._transaction("discard a conversation's transcript") as conn:
            cursor = conn.execute(
                "DELETE FROM entries WHERE conversation_id = ?", (conversation_id,)
            )
            return max(cursor.rowcount, 0)

    # --- the reads (§7) ------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20, offset: int = 0) -> list[TranscriptHit]:
        """Find entries whose text contains ``query``, newest first (§7).

        The predicate binds **before** the ordering and **before** the pagination,
        in the one statement, so an entry the retention hides consumes no page slot
        and shifts no offset.

        Raises:
            ValueError: If ``query`` is blank, ``limit`` is zero or below, or
                ``offset`` is negative.
            TranscriptArchiveError: If the archive cannot be read.
        """
        needle = folded(check_named(query, name="query"))
        check_page(limit, offset)
        floor = self._floor()
        async with self._lock:
            rows = await _run_to_completion(self._search_sync, needle, floor, limit, offset)
        return [_hit_of(row, needle) for row in rows]

    def _search_sync(
        self, needle: str, floor: int, limit: int, offset: int
    ) -> list[tuple[Any, ...]]:
        with self._transaction("search the transcript archive", immediate=False) as conn:
            return list(
                conn.execute(
                    # `replied_folded` is selected and not read: the two halves are
                    # matched separately, so `asked_folded` failing the needle is
                    # already the answer that `replied` is the matching half. Keeping
                    # the column in the projection is what makes that legible beside
                    # the `WHERE` clause it mirrors.
                    "SELECT address, conversation_id, occurred_at_us, "
                    "asked, replied, asked_folded, replied_folded "
                    "FROM entries WHERE occurred_at_us >= ? "
                    "AND (instr(asked_folded, ?) > 0 OR instr(replied_folded, ?) > 0) "
                    "ORDER BY occurred_at_us DESC, address ASC LIMIT ? OFFSET ?",
                    (floor, needle, needle, limit, offset),
                )
            )

    async def conversation(
        self, conversation_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[TranscriptEntry]:
        """One conversation's entries, in ordinal order (§7).

        Raises:
            ValueError: If ``conversation_id`` is blank, ``limit`` is zero or below,
                or ``offset`` is negative.
            TranscriptArchiveError: If the archive cannot be read.
        """
        named = check_named(conversation_id, name="conversation_id")
        check_page(limit, offset)
        floor = self._floor()
        async with self._lock:
            rows = await _run_to_completion(self._conversation_sync, named, floor, limit, offset)
        return [_entry_of(row) for row in rows]

    def _conversation_sync(
        self, conversation_id: str, floor: int, limit: int, offset: int
    ) -> list[tuple[Any, ...]]:
        with self._transaction("read a conversation's transcript", immediate=False) as conn:
            return list(
                conn.execute(
                    f"SELECT {_COLUMNS} FROM entries "  # noqa: S608 — a module constant, no input
                    "WHERE conversation_id = ? AND occurred_at_us >= ? "
                    "ORDER BY ordinal ASC LIMIT ? OFFSET ?",
                    (conversation_id, floor, limit, offset),
                )
            )

    async def entry(self, address: str) -> TranscriptEntry | None:
        """The entry at ``address``, whole, or ``None`` (§7).

        Raises:
            ValueError: If ``address`` is blank or whitespace-only.
            TranscriptArchiveError: If the archive cannot be read.
        """
        named = check_named(address, name="address")
        floor = self._floor()
        async with self._lock:
            rows = await _run_to_completion(self._entry_sync, named, floor)
        return _entry_of(rows[0]) if rows else None

    def _entry_sync(self, address: str, floor: int) -> list[tuple[Any, ...]]:
        with self._transaction("read a transcript entry", immediate=False) as conn:
            return list(
                conn.execute(
                    f"SELECT {_COLUMNS} FROM entries "  # noqa: S608 — a module constant, no input
                    "WHERE address = ? AND occurred_at_us >= ?",
                    (address, floor),
                )
            )

    async def entries(self, *, limit: int = 50, offset: int = 0) -> list[TranscriptEntry]:
        """Every entry the archive holds, newest first — the archive's export (§7).

        Raises:
            ValueError: If ``limit`` is zero or below, or ``offset`` is negative.
            TranscriptArchiveError: If the archive cannot be read.
        """
        check_page(limit, offset)
        floor = self._floor()
        async with self._lock:
            rows = await _run_to_completion(self._entries_sync, floor, limit, offset)
        return [_entry_of(row) for row in rows]

    def _entries_sync(self, floor: int, limit: int, offset: int) -> list[tuple[Any, ...]]:
        with self._transaction("export the transcript archive", immediate=False) as conn:
            return list(
                conn.execute(
                    f"SELECT {_COLUMNS} FROM entries "  # noqa: S608 — a module constant, no input
                    "WHERE occurred_at_us >= ? "
                    "ORDER BY occurred_at_us DESC, address ASC LIMIT ? OFFSET ?",
                    (floor, limit, offset),
                )
            )

    # --- the size report (§6) ------------------------------------------------

    async def size(self) -> TranscriptArchiveSize:
        """How many entries the reads would return, and what the files cost (§6).

        The two figures answer different questions and are allowed to disagree:
        ``entries`` applies the retention predicate, ``stored_bytes`` does not,
        because the figure that would fire the deferred cap is the one that measures
        the storage.

        Raises:
            TranscriptArchiveError: If the archive cannot be read.
        """
        floor = self._floor()
        async with self._lock:
            counted = await _run_to_completion(self._count_sync, floor)
            occupied = await _run_to_completion(self._bytes_sync)
        return TranscriptArchiveSize(entries=counted, stored_bytes=occupied)

    def _count_sync(self, floor: int) -> int:
        with self._transaction("count the transcript archive", immediate=False) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE occurred_at_us >= ?", (floor,)
            ).fetchone()
        return int(row[0])

    def _bytes_sync(self) -> int:
        """Every byte the archive's files occupy on disk, right now (§6).

        The database, the indexes inside it, and any journal or write-ahead log
        beside it — §6's closed set exactly, which is why this can be a sum over
        four names rather than a directory walk that might find something else. An
        accounting that summed entry lengths, or read the main database file alone,
        would understate an index-carrying archive by roughly half and an
        un-checkpointed log without bound.

        In memory there are no files, and §6 requires the same standard rather than
        a zero: ``page_count * page_size`` is what the entries occupy in what holds
        them, and a populated archive therefore never reports zero.

        **The database and its sidecars are not stat-ed under the same tolerance**,
        because they answer different questions. A sidecar that is absent is the
        ordinary case — a cleanly closed database has none — so it contributes
        nothing. The database is not optional, and an unreadable one is the single
        way this method could produce the answer §6 names as conforming for no
        implementation: ``stored_bytes`` of zero over an archive holding entries.
        The connection outlives the directory entry — a POSIX file another process
        unlinks or moves stays whole for an open descriptor — so ``entries`` keeps
        counting from a file no path reaches, and a swallowed ``stat`` would report
        the two side by side. Raising is what the seam already documents for a read
        it cannot answer, and it is the answer the deferred cap can act on.

        Raises:
            TranscriptArchiveError: If the database file cannot be measured.
        """
        if self._path == ":memory:":
            with self._transaction("measure the transcript archive", immediate=False) as conn:
                pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
                size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            return pages * size
        database = Path(self._path)
        try:
            total = database.stat().st_size
        except OSError as exc:
            msg = f"failed to measure the transcript archive at {self._path!r}: {exc}"
            raise TranscriptArchiveError(msg) from exc
        for suffix in _SIDECARS:
            try:
                total += database.with_name(database.name + suffix).stat().st_size
            except OSError:
                # Absent, or gone between the listing and the stat: the same answer
                # either way, and the ordinary one for a quiescent database.
                continue
        return total

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()


def _text(value: object) -> str:
    """The value of a ``TEXT`` column, refusing any other storage class.

    **SQLite is dynamically typed and a column's declared type does not bind what a
    row holds**, so a value some other writer put in this database — a BLOB, an
    integer, a float — arrives here as itself. ``str()`` would *coerce* it, and for a
    transcript's own halves that is the worst available failure: ``str(b"...")`` is
    ``"b'...'"``, so a read would report, as something the user said, words nobody
    said. A store whose whole value is fidelity may not fabricate text.

    So the storage class is checked and a wrong one is a fault — routed through
    :func:`_unreadable` by the caller's own handler, since this raises ``TypeError``.

    Args:
        value: What the driver returned for the column.

    Returns:
        The value, unchanged.

    Raises:
        TypeError: If it is not a ``str``. The message names the class and never the
            value (ADR-0225 §4, ADR-0004 §5).
    """
    if not isinstance(value, str):
        msg = f"expected a TEXT column, found {type(value).__name__}"
        raise TypeError(msg)
    return value


def _optional_text(value: object) -> str | None:
    """:func:`_text`, admitting ``NULL`` — which is a fact and not a missing value.

    ADR-0225 §1 makes ``asked`` absent where the pass received no user words and
    ``replied`` absent where it produced no reply, so ``None`` is what those columns
    legitimately hold and is the one non-``str`` this admits.
    """
    return None if value is None else _text(value)


def _integer(value: object) -> int:
    """The value of an ``INTEGER`` column, refusing any other storage class.

    ``int()`` would coerce a float and a numeric string alike, and both would land in
    a domain the model then judges — an ordinal or an instant read off a value that
    was never one. ``bool`` is excluded although it is an ``int`` subclass: the driver
    stores none, so one here is a value something else put there.

    Raises:
        TypeError: If it is not an ``int``, or is a ``bool``.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"expected an INTEGER column, found {type(value).__name__}"
        raise TypeError(msg)
    return value


def _unreadable(address: object, fault: Exception) -> TranscriptArchiveError:
    """The one error a row this store cannot rebuild raises (ADR-0225 §10).

    A read reaches this only for a row the SQL already returned — a value some other
    writer put in the reserved namespace, or a damaged one. §10 gives this seam a
    single archive error class, and a raw ``ValidationError``, ``ValueError`` or
    ``OverflowError`` out of the model conversion would leave every caller matching on
    a class the contract does not document. It is the arrangement ADR-0119 §3 already
    makes for a trace row that cannot be hydrated: **raised over rather than skipped**,
    because dropping the row silently would hide from the user a transcript that is
    on their disk.

    **The message names the address and the fault's class, and nothing is chained.**
    A ``ValidationError`` renders the value it refused into its own text, and here
    that value is the entry — so attaching it as ``__cause__`` would put the
    transcript one ``exc_info`` away from a log, which is the leak §4 forbids
    (ADR-0004 §5). The class name goes through
    :func:`~ai_assistant.core.types.fault_class_of`, which is total and drops a name
    that will not fit rather than carrying it.

    Args:
        address: The row's address, as stored. Not the text.
        fault: What the conversion raised.

    Returns:
        The error to raise.
    """
    # An address that is not itself text is described by its class rather than
    # rendered: the row is already one this store did not write, so nothing says the
    # bytes in that column are an address at all, and a message is not the place to
    # find out.
    described = (
        describe_untrusted(address)
        if isinstance(address, str)
        else f"an unreadable address ({type(address).__name__})"
    )
    msg = (
        f"a stored transcript entry at address {described} could not be read back "
        f"({fault_class_of(fault)})"
    )
    return TranscriptArchiveError(msg)


def _hit_of(row: tuple[Any, ...], needle: str) -> TranscriptHit:
    """Build one hit, excerpting **the half the needle actually occurs in** (§7).

    ADR-0225 §7 says a hit carries "a bounded excerpt of the matching text", and the
    two halves are matched separately — so which half matched is part of the answer
    and cannot be guessed from which half is present. An implementation that
    excerpted ``asked`` whenever it was non-``None`` would hand back the user's
    sentence for a query that occurs only in the reply: a hit that does not contain
    what was searched for, which reads to a user as a wrong result rather than as a
    bounded one.

    The decision is made here against the **folded** columns the row already carries,
    so the excerpt is decided by exactly the predicate the ``WHERE`` clause used —
    two evaluations of one rule rather than two rules that could disagree.

    ``asked`` is preferred where **both** halves match, so a hit reads as what the
    *user* said wherever they said it; it never carries both, which §7 forbids where
    either exceeds the bound.
    """
    address, conversation_id, occurred_at_us, asked, replied, asked_folded, _ = row
    try:
        folded_asked = _optional_text(asked_folded)
        matched = (
            _optional_text(asked)
            if folded_asked is not None and needle in folded_asked
            else _optional_text(replied)
        )
        # A row only reaches here because one folded half contained the needle, so
        # `matched` is never both-None; the fallback keeps the type total.
        text, elided = excerpt_of("" if matched is None else matched)
        return TranscriptHit(
            address=_text(address),
            conversation_id=_text(conversation_id),
            occurred_at=_from_micros(_integer(occurred_at_us)),
            excerpt=text,
            elided=elided,
        )
    except (ValidationError, ValueError, OverflowError, TypeError) as fault:
        raise _unreadable(address, fault) from None


def _entry_of(row: tuple[Any, ...]) -> TranscriptEntry:
    """Rebuild one :class:`TranscriptEntry` from its row, whole and validated.

    Raises:
        TranscriptArchiveError: If the row cannot be rebuilt — see :func:`_unreadable`
            for why that is raised rather than skipped, and why nothing is chained.
    """
    address, conversation_id, ordinal, occurred_at_us, asked, replied, disposition = row
    try:
        return TranscriptEntry(
            address=_text(address),
            conversation_id=_text(conversation_id),
            ordinal=_integer(ordinal),
            occurred_at=_from_micros(_integer(occurred_at_us)),
            asked=_optional_text(asked),
            replied=_optional_text(replied),
            disposition=ExchangeDisposition(_text(disposition)),
        )
    except (ValidationError, ValueError, OverflowError, TypeError) as fault:
        # Every arm is reachable from a row this store did not write: a disposition
        # outside the vocabulary and an ordinal outside its domain are `ValueError`
        # and `ValidationError`, an `occurred_at_us` outside the calendar is
        # `OverflowError`, and a column holding the wrong storage class is the
        # `TypeError` the three accessors above raise. `ValidationError` is named
        # first because it is a `ValueError` and the ordering would otherwise be
        # silent about which one is meant.
        raise _unreadable(address, fault) from None


__all__ = ["SqliteTranscriptArchive"]
